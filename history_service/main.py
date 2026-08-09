from fastapi import FastAPI, Query, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from aiokafka import AIOKafkaConsumer
import asyncio
import os
import json
import httpx
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from influxdb_client import InfluxDBClient, Point, BucketRetentionRules
from influxdb_client.client.write_api import SYNCHRONOUS
from pydantic import BaseModel

app = FastAPI()

# Validation patterns for Flux query parameters to prevent injection
DURATION_PATTERN = re.compile(r'^-?(\d+)(s|m|h|d|w|mo|y)$')
INTERVAL_PATTERN = re.compile(r'^\d+(s|m|h|d)$')
STOP_PATTERN = re.compile(r'^(now\(\)|-?\d+(s|m|h|d|w|mo|y))$')

# Maximum allowed duration in seconds (365 days) to prevent resource exhaustion
MAX_DURATION_SECONDS = 365 * 24 * 60 * 60

# Duration unit multipliers for validation
DURATION_MULTIPLIERS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
    'mo': 2592000,  # ~30 days
    'y': 31536000   # ~365 days
}

def validate_duration(value: str, param_name: str) -> str:
    """Validate and sanitize duration parameters to prevent Flux injection and resource exhaustion."""
    if value == "now()":
        return value
    
    match = DURATION_PATTERN.match(value)
    if not match:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name} format. Use patterns like -1h, -24h, -7d, -30d, -1y"
        )
    
    # Extract numeric value and unit, clamp to max allowed duration
    num_value = int(match.group(1))
    unit = match.group(2)
    duration_seconds = num_value * DURATION_MULTIPLIERS.get(unit, 1)
    
    if duration_seconds > MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Duration exceeds maximum allowed (365 days). Requested: {value}"
        )
    
    return value

def validate_interval(value: str) -> str:
    """Validate and sanitize interval parameters to prevent Flux injection."""
    if not INTERVAL_PATTERN.match(value):
        raise HTTPException(
            status_code=400,
            detail="Invalid interval format. Use patterns like 1m, 5m, 1h, 1d"
        )
    return value

def validate_stop(value: str) -> str:
    """Validate stop parameter to prevent Flux injection and resource exhaustion."""
    if value == "now()":
        return value
    
    match = DURATION_PATTERN.match(value)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Invalid stop format. Use 'now()' or patterns like -1h, -24h"
        )
    
    # Also clamp stop parameter to prevent huge ranges
    num_value = int(match.group(1))
    unit = match.group(2)
    duration_seconds = num_value * DURATION_MULTIPLIERS.get(unit, 1)
    
    if duration_seconds > MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Stop duration exceeds maximum allowed (365 days). Requested: {value}"
        )
    
    return value

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "metrics"
KAFKA_GROUP_ID = "history-service"

# InfluxDB configuration
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "statusmonitor-token")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "statusmonitor")

# Bucket names for different retention tiers
BUCKET_RAW = "metrics_raw"      # 5-second resolution, 24-hour retention
BUCKET_1M = "metrics_1m"        # 1-minute resolution, 7-day retention
BUCKET_1H = "metrics_1h"        # 1-hour resolution, 365-day retention
BUCKET_LEGACY = "metrics"       # Legacy bucket (backward compatibility)

# InfluxDB client
influx_client = None
write_api = None
query_api = None
buckets_api = None
tasks_api = None

# Bucket configurations for downsampling
# NOTE: The downsampling tasks assume a typical agent reporting interval.
# If agents report less frequently (e.g., every 30s+), the 1-minute aggregation
# will have fewer data points, and hourly min/max/avg values may be less accurate.
# Consider this trade-off when configuring agent intervals.
BUCKET_CONFIGS = {
    BUCKET_RAW: {
        "retention_seconds": 24 * 60 * 60,  # 24 hours
        "description": "Raw metrics at agent-configured interval (default: few seconds)"
    },
    BUCKET_1M: {
        "retention_seconds": 7 * 24 * 60 * 60,  # 7 days
        "description": "1-minute aggregated metrics (accuracy depends on agent interval)"
    },
    BUCKET_1H: {
        "retention_seconds": 365 * 24 * 60 * 60,  # 1 year
        "description": "1-hour aggregated metrics with min/max/avg"
    }
}


def parse_duration_to_seconds(duration: str) -> int:
    """Parse InfluxDB duration string to seconds"""
    if not duration.startswith("-"):
        return 3600  # Default 1 hour
    
    time_str = duration[1:]  # Remove leading '-'
    
    # Match patterns like "1h", "24h", "7d", "30d", "1mo", "1y"
    match = re.match(r'^(\d+)(s|m|h|d|w|mo|y)$', time_str)
    if not match:
        return 3600
    
    value = int(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800,
        'mo': 2592000,  # ~30 days
        'y': 31536000   # ~365 days
    }
    
    return value * multipliers.get(unit, 3600)


def get_bucket_for_time_range(start: str) -> tuple:
    """
    Determine the appropriate bucket based on time range.
    
    Returns:
        tuple: (bucket_name, field_suffix, recommended_interval)
        - field_suffix is empty for raw/1m data, "_avg" for 1h aggregated data
    """
    seconds = parse_duration_to_seconds(start)
    
    # Bucket selection logic:
    # <= 24 hours: Use raw data (metrics_raw) - highest resolution
    # <= 7 days: Use 1-minute data (metrics_1m) - medium resolution  
    # > 7 days: Use 1-hour data (metrics_1h) - long-term storage
    
    if seconds <= 24 * 3600:  # <= 24 hours
        return BUCKET_RAW, "", "1m"
    elif seconds <= 7 * 24 * 3600:  # <= 7 days
        return BUCKET_1M, "", "5m"
    else:  # > 7 days
        return BUCKET_1H, "_avg", "1h"


def setup_buckets_and_tasks():
    """Set up InfluxDB buckets and downsampling tasks"""
    global buckets_api, tasks_api
    
    try:
        buckets_api = influx_client.buckets_api()
        tasks_api = influx_client.tasks_api()
        orgs_api = influx_client.organizations_api()
        
        # Get org ID
        orgs = orgs_api.find_organizations(org=INFLUXDB_ORG)
        if not orgs:
            print(f"Organization '{INFLUXDB_ORG}' not found!")
            return False
        org_id = orgs[0].id
        
        # Create buckets
        for bucket_name, config in BUCKET_CONFIGS.items():
            existing = buckets_api.find_bucket_by_name(bucket_name)
            if existing:
                print(f"  Bucket '{bucket_name}' exists, updating retention...")
                existing.retention_rules = [
                    BucketRetentionRules(
                        type="expire",
                        every_seconds=config["retention_seconds"]
                    )
                ]
                buckets_api.update_bucket(bucket=existing)
            else:
                print(f"  Creating bucket '{bucket_name}'...")
                buckets_api.create_bucket(
                    bucket_name=bucket_name,
                    retention_rules=[
                        BucketRetentionRules(
                            type="expire",
                            every_seconds=config["retention_seconds"]
                        )
                    ],
                    org_id=org_id,
                    description=config["description"]
                )
        
        # Create downsampling tasks
        create_downsampling_tasks(org_id)
        
        print("InfluxDB buckets and tasks configured!")
        return True
        
    except Exception as e:
        print(f"Error setting up buckets: {e}")
        return False


def create_downsampling_tasks(org_id: str):
    """Create InfluxDB tasks for downsampling data.
    
    IMPORTANT: These tasks assume agents report metrics at a configurable interval
    (typically a few seconds). If agents report less frequently:
    - Raw -> 1m aggregation: fewer points averaged, still accurate mean
    - 1m -> 1h aggregation: min/max/avg computed from fewer 1m samples
    
    For agents with intervals >= 30s, the 1-minute bucket will essentially
    mirror raw data, and hourly stats will have reduced granularity.
    """
    
    # Task: Raw -> 1 minute
    task_raw_to_1m = f'''
option task = {{name: "downsample_raw_to_1m", every: 1m}}

// CPU metrics
from(bucket: "{BUCKET_RAW}")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    |> to(bucket: "{BUCKET_1M}", org: "{INFLUXDB_ORG}")

// Memory metrics
from(bucket: "{BUCKET_RAW}")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    |> to(bucket: "{BUCKET_1M}", org: "{INFLUXDB_ORG}")

// Disk metrics
from(bucket: "{BUCKET_RAW}")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "disk")
    |> filter(fn: (r) => r["_field"] == "percent")
    |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    |> to(bucket: "{BUCKET_1M}", org: "{INFLUXDB_ORG}")

// Network bytes
from(bucket: "{BUCKET_RAW}")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "network")
    |> filter(fn: (r) => r["_field"] == "bytes_sent" or r["_field"] == "bytes_recv")
    |> aggregateWindow(every: 1m, fn: last, createEmpty: false)
    |> to(bucket: "{BUCKET_1M}", org: "{INFLUXDB_ORG}")
'''

    # Task: 1 minute -> 1 hour (with min/max/avg)
    task_1m_to_1h = f'''
option task = {{name: "downsample_1m_to_1h", every: 1h}}

// CPU avg
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_field", value: "usage_percent_avg")
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")

// CPU max
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> set(key: "_field", value: "usage_percent_max")
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")

// CPU min
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1h, fn: min, createEmpty: false)
    |> set(key: "_field", value: "usage_percent_min")
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")

// Memory avg
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_field", value: "used_percent_avg")
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")

// Memory max
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> set(key: "_field", value: "used_percent_max")
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")

// Disk avg
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "disk")
    |> filter(fn: (r) => r["_field"] == "percent")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_field", value: "percent_avg")
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")

// Network bytes
from(bucket: "{BUCKET_1M}")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "network")
    |> filter(fn: (r) => r["_field"] == "bytes_sent" or r["_field"] == "bytes_recv")
    |> aggregateWindow(every: 1h, fn: last, createEmpty: false)
    |> to(bucket: "{BUCKET_1H}", org: "{INFLUXDB_ORG}")
'''

    try:
        existing_tasks = tasks_api.find_tasks()
        task_names = {t.name: t for t in existing_tasks}
        
        # Create/update raw -> 1m task
        if "downsample_raw_to_1m" in task_names:
            print("  Updating task 'downsample_raw_to_1m'...")
            task = task_names["downsample_raw_to_1m"]
            task.flux = task_raw_to_1m
            tasks_api.update_task(task)
        else:
            print("  Creating task 'downsample_raw_to_1m'...")
            tasks_api.create_task_every(
                name="downsample_raw_to_1m",
                flux=task_raw_to_1m,
                every="1m",
                org_id=org_id
            )
        
        # Create/update 1m -> 1h task
        if "downsample_1m_to_1h" in task_names:
            print("  Updating task 'downsample_1m_to_1h'...")
            task = task_names["downsample_1m_to_1h"]
            task.flux = task_1m_to_1h
            tasks_api.update_task(task)
        else:
            print("  Creating task 'downsample_1m_to_1h'...")
            tasks_api.create_task_every(
                name="downsample_1m_to_1h",
                flux=task_1m_to_1h,
                every="1h",
                org_id=org_id
            )
            
    except Exception as e:
        print(f"Error creating tasks: {e}")


def init_influxdb():
    global influx_client, write_api, query_api
    try:
        influx_client = InfluxDBClient(
            url=INFLUXDB_URL,
            token=INFLUXDB_TOKEN,
            org=INFLUXDB_ORG
        )
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        query_api = influx_client.query_api()
        print(f"Connected to InfluxDB at {INFLUXDB_URL}")
        
        # Set up buckets and downsampling tasks
        setup_buckets_and_tasks()
        
        return True
    except Exception as e:
        print(f"Failed to connect to InfluxDB: {e}")
        return False

def store_metrics(data: dict):
    """Store metrics in InfluxDB"""
    if not write_api:
        return
    
    try:
        agent_id = data.get("agent_id")
        user_id = data.get("user_id")
        agent_name = data.get("agent_name", "unknown")
        timestamp = datetime.fromtimestamp(data.get("timestamp", datetime.now(timezone.utc).timestamp()), tz=timezone.utc)
        
        points = []
        
        # CPU metrics
        if "cpu" in data:
            cpu = data["cpu"]
            point = Point("cpu") \
                .tag("agent_id", str(agent_id)) \
                .tag("user_id", str(user_id)) \
                .tag("agent_name", agent_name) \
                .field("usage_percent", float(cpu.get("usage_percent", 0))) \
                .time(timestamp)
            points.append(point)
            
            # Per-core usage
            per_core = cpu.get("per_core_usage", [])
            for i, core_usage in enumerate(per_core):
                core_point = Point("cpu_core") \
                    .tag("agent_id", str(agent_id)) \
                    .tag("user_id", str(user_id)) \
                    .tag("core", str(i)) \
                    .field("usage_percent", float(core_usage)) \
                    .time(timestamp)
                points.append(core_point)
        
        # Memory metrics
        if "memory" in data:
            mem = data["memory"]
            point = Point("memory") \
                .tag("agent_id", str(agent_id)) \
                .tag("user_id", str(user_id)) \
                .tag("agent_name", agent_name) \
                .field("used_percent", float(mem.get("used_percent", 0))) \
                .field("total", int(mem.get("total", 0))) \
                .field("available", int(mem.get("available", 0))) \
                .time(timestamp)
            points.append(point)
        
        # Disk metrics
        if "disk" in data:
            disk = data["disk"]
            for partition in disk.get("partitions", []):
                point = Point("disk") \
                    .tag("agent_id", str(agent_id)) \
                    .tag("user_id", str(user_id)) \
                    .tag("mountpoint", partition.get("mountpoint", "unknown")) \
                    .tag("device", partition.get("device", "unknown")) \
                    .field("percent", float(partition.get("percent", 0))) \
                    .field("total", int(partition.get("total", 0))) \
                    .field("used", int(partition.get("used", 0))) \
                    .field("free", int(partition.get("free", 0))) \
                    .time(timestamp)
                points.append(point)
        
        # Network metrics
        if "network" in data:
            net = data["network"]
            point = Point("network") \
                .tag("agent_id", str(agent_id)) \
                .tag("user_id", str(user_id)) \
                .tag("agent_name", agent_name) \
                .field("bytes_sent", int(net.get("bytes_sent", 0))) \
                .field("bytes_recv", int(net.get("bytes_recv", 0))) \
                .field("packets_sent", int(net.get("packets_sent", 0))) \
                .field("packets_recv", int(net.get("packets_recv", 0))) \
                .time(timestamp)
            points.append(point)
        
        # Write all points to the RAW bucket (highest resolution, shortest retention)
        write_api.write(bucket=BUCKET_RAW, org=INFLUXDB_ORG, record=points)
        
    except Exception as e:
        print(f"Error storing metrics: {e}")

async def kafka_consumer():
    """Consume metrics from Kafka and store in InfluxDB with auto-reconnect"""
    while True:
        consumer = None
        try:
            print(f"Connecting to Kafka at {KAFKA_BOOTSTRAP_SERVERS}...")
            consumer = AIOKafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                group_id=KAFKA_GROUP_ID,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset="earliest",  # Process all messages (for history)
                enable_auto_commit=True,
            )
            await consumer.start()
            print(f"History service consuming from Kafka topic: {KAFKA_TOPIC}")

            async for msg in consumer:
                try:
                    data = msg.value
                    store_metrics(data)
                except Exception as e:
                    print(f"Error processing message: {e}")
        except Exception as e:
            print(f"Kafka consumer error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        finally:
            if consumer:
                try:
                    await consumer.stop()
                except:
                    pass

@app.on_event("startup")
async def startup_event():
    init_influxdb()
    asyncio.create_task(kafka_consumer())

@app.on_event("shutdown")
async def shutdown_event():
    if influx_client:
        influx_client.close()

# Auth helper
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Validate token and return current user"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authentication")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{AUTH_SERVICE_URL}/users/me",
                headers={"Authorization": authorization},
                timeout=5.0
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            return response.json()
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

# Response models
class MetricPoint(BaseModel):
    time: str
    value: float

class HistoryResponse(BaseModel):
    metric: str
    agent_id: int
    data: List[MetricPoint]

@app.get("/history/{agent_id}/cpu")
async def get_cpu_history(
    agent_id: int,
    start: Optional[str] = Query("-1h", description="Start time (e.g., -1h, -24h, -7d)"),
    stop: Optional[str] = Query("now()", description="Stop time"),
    interval: Optional[str] = Query(None, description="Aggregation interval (auto-selected if not provided)"),
    current_user: dict = Depends(get_current_user)
):
    """Get CPU usage history for an agent (authenticated, ownership enforced).
    
    Automatically selects the appropriate bucket based on time range:
    - <= 24h: Raw data (agent-configured resolution)
    - <= 7d: 1-minute aggregated data
    - > 7d: 1-hour aggregated data
    """
    if not query_api:
        raise HTTPException(status_code=503, detail="InfluxDB not available")
    
    # Validate inputs to prevent Flux injection
    start = validate_duration(start, "start")
    stop = validate_stop(stop)
    
    user_id = current_user["id"]
    
    # Select appropriate bucket based on time range
    bucket, field_suffix, default_interval = get_bucket_for_time_range(start)
    use_interval = validate_interval(interval) if interval else default_interval
    
    # For hourly bucket, use the pre-aggregated avg field
    field_name = f"usage_percent{field_suffix}" if field_suffix else "usage_percent"
    
    query = f'''
    from(bucket: "{bucket}")
        |> range(start: {start}, stop: {stop})
        |> filter(fn: (r) => r["_measurement"] == "cpu")
        |> filter(fn: (r) => r["agent_id"] == "{agent_id}")
        |> filter(fn: (r) => r["user_id"] == "{user_id}")
        |> filter(fn: (r) => r["_field"] == "{field_name}")
        |> aggregateWindow(every: {use_interval}, fn: mean, createEmpty: false)
        |> yield(name: "mean")
    '''
    
    try:
        tables = query_api.query(query, org=INFLUXDB_ORG)
        data = []
        for table in tables:
            for record in table.records:
                data.append({
                    "time": record.get_time().isoformat(),
                    "value": record.get_value()
                })
        return {
            "metric": "cpu",
            "agent_id": agent_id,
            "data": data,
            "bucket": bucket,
            "interval": use_interval
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/{agent_id}/memory")
async def get_memory_history(
    agent_id: int,
    start: Optional[str] = Query("-1h", description="Start time"),
    stop: Optional[str] = Query("now()", description="Stop time"),
    interval: Optional[str] = Query(None, description="Aggregation interval (auto-selected if not provided)"),
    current_user: dict = Depends(get_current_user)
):
    """Get memory usage history for an agent (authenticated, ownership enforced).
    
    Automatically selects the appropriate bucket based on time range.
    """
    if not query_api:
        raise HTTPException(status_code=503, detail="InfluxDB not available")
    
    # Validate inputs to prevent Flux injection
    start = validate_duration(start, "start")
    stop = validate_stop(stop)
    
    user_id = current_user["id"]
    
    # Select appropriate bucket based on time range
    bucket, field_suffix, default_interval = get_bucket_for_time_range(start)
    use_interval = validate_interval(interval) if interval else default_interval
    field_name = f"used_percent{field_suffix}" if field_suffix else "used_percent"
    
    query = f'''
    from(bucket: "{bucket}")
        |> range(start: {start}, stop: {stop})
        |> filter(fn: (r) => r["_measurement"] == "memory")
        |> filter(fn: (r) => r["agent_id"] == "{agent_id}")
        |> filter(fn: (r) => r["user_id"] == "{user_id}")
        |> filter(fn: (r) => r["_field"] == "{field_name}")
        |> aggregateWindow(every: {use_interval}, fn: mean, createEmpty: false)
        |> yield(name: "mean")
    '''
    
    try:
        tables = query_api.query(query, org=INFLUXDB_ORG)
        data = []
        for table in tables:
            for record in table.records:
                data.append({
                    "time": record.get_time().isoformat(),
                    "value": record.get_value()
                })
        return {
            "metric": "memory",
            "agent_id": agent_id,
            "data": data,
            "bucket": bucket,
            "interval": use_interval
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/{agent_id}/disk")
async def get_disk_history(
    agent_id: int,
    mountpoint: Optional[str] = Query(None, description="Filter by mountpoint"),
    start: Optional[str] = Query("-1h", description="Start time"),
    stop: Optional[str] = Query("now()", description="Stop time"),
    interval: Optional[str] = Query(None, description="Aggregation interval (auto-selected if not provided)"),
    current_user: dict = Depends(get_current_user)
):
    """Get disk usage history for an agent (authenticated, ownership enforced).
    
    Automatically selects the appropriate bucket based on time range.
    """
    if not query_api:
        raise HTTPException(status_code=503, detail="InfluxDB not available")
    
    # Validate inputs to prevent Flux injection
    start = validate_duration(start, "start")
    stop = validate_stop(stop)
    
    user_id = current_user["id"]
    
    # Select appropriate bucket based on time range
    bucket, field_suffix, default_interval = get_bucket_for_time_range(start)
    use_interval = validate_interval(interval) if interval else default_interval
    field_name = f"percent{field_suffix}" if field_suffix else "percent"
    # Sanitize mountpoint to prevent injection (allow alphanumeric, /, \, :, _, -)
    if mountpoint and not re.match(r'^[a-zA-Z0-9/_:\\\-]+$', mountpoint):
        raise HTTPException(status_code=400, detail="Invalid mountpoint format")
    mountpoint_filter = f'|> filter(fn: (r) => r["mountpoint"] == "{mountpoint}")' if mountpoint else ""
    
    query = f'''
    from(bucket: "{bucket}")
        |> range(start: {start}, stop: {stop})
        |> filter(fn: (r) => r["_measurement"] == "disk")
        |> filter(fn: (r) => r["agent_id"] == "{agent_id}")
        |> filter(fn: (r) => r["user_id"] == "{user_id}")
        |> filter(fn: (r) => r["_field"] == "{field_name}")
        {mountpoint_filter}
        |> aggregateWindow(every: {use_interval}, fn: mean, createEmpty: false)
        |> yield(name: "mean")
    '''
    
    try:
        tables = query_api.query(query, org=INFLUXDB_ORG)
        data = []
        for table in tables:
            for record in table.records:
                data.append({
                    "time": record.get_time().isoformat(),
                    "value": record.get_value(),
                    "mountpoint": record.values.get("mountpoint", "unknown")
                })
        return {
            "metric": "disk",
            "agent_id": agent_id,
            "data": data,
            "bucket": bucket,
            "interval": use_interval
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/{agent_id}/network")
async def get_network_history(
    agent_id: int,
    start: Optional[str] = Query("-1h", description="Start time"),
    stop: Optional[str] = Query("now()", description="Stop time"),
    interval: Optional[str] = Query("1m", description="Aggregation interval"),
    current_user: dict = Depends(get_current_user)
):
    """Get network usage history for an agent (authenticated, ownership enforced)"""
    if not query_api:
        raise HTTPException(status_code=503, detail="InfluxDB not available")
    
    # Validate inputs to prevent Flux injection
    start = validate_duration(start, "start")
    stop = validate_stop(stop)
    
    user_id = current_user["id"]
    
    # Select appropriate bucket based on time range
    bucket, _, default_interval = get_bucket_for_time_range(start)
    use_interval = validate_interval(interval) if interval else default_interval
    
    query = f'''
    from(bucket: "{bucket}")
        |> range(start: {start}, stop: {stop})
        |> filter(fn: (r) => r["_measurement"] == "network")
        |> filter(fn: (r) => r["agent_id"] == "{agent_id}")
        |> filter(fn: (r) => r["user_id"] == "{user_id}")
        |> filter(fn: (r) => r["_field"] == "bytes_sent" or r["_field"] == "bytes_recv")
        |> aggregateWindow(every: {use_interval}, fn: last, createEmpty: false)
        |> yield(name: "last")
    '''
    
    try:
        tables = query_api.query(query, org=INFLUXDB_ORG)
        sent_data = []
        recv_data = []
        for table in tables:
            for record in table.records:
                point = {
                    "time": record.get_time().isoformat(),
                    "value": record.get_value()
                }
                if record.get_field() == "bytes_sent":
                    sent_data.append(point)
                else:
                    recv_data.append(point)
        return {
            "metric": "network",
            "agent_id": agent_id,
            "bytes_sent": sent_data,
            "bytes_recv": recv_data,
            "bucket": bucket,
            "interval": use_interval
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/{agent_id}/summary")
async def get_summary(
    agent_id: int,
    start: Optional[str] = Query("-24h", description="Start time"),
    stop: Optional[str] = Query("now()", description="Stop time"),
    current_user: dict = Depends(get_current_user)
):
    """Get summary statistics for an agent (authenticated, ownership enforced)"""
    if not query_api:
        raise HTTPException(status_code=503, detail="InfluxDB not available")
    
    # Validate inputs to prevent Flux injection
    start = validate_duration(start, "start")
    stop = validate_stop(stop)
    
    user_id = current_user["id"]
    
    # Select appropriate bucket based on time range
    bucket, field_suffix, _ = get_bucket_for_time_range(start)
    
    # Use correct field names based on bucket (hourly bucket has _avg suffix)
    cpu_field = f"usage_percent{field_suffix}" if field_suffix else "usage_percent"
    mem_field = f"used_percent{field_suffix}" if field_suffix else "used_percent"
    
    try:
        # CPU stats
        cpu_query = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {stop})
            |> filter(fn: (r) => r["_measurement"] == "cpu")
            |> filter(fn: (r) => r["agent_id"] == "{agent_id}")
            |> filter(fn: (r) => r["user_id"] == "{user_id}")
            |> filter(fn: (r) => r["_field"] == "{cpu_field}")
        '''
        
        cpu_tables = query_api.query(cpu_query, org=INFLUXDB_ORG)
        cpu_values = [record.get_value() for table in cpu_tables for record in table.records]
        
        # Memory stats
        mem_query = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {stop})
            |> filter(fn: (r) => r["_measurement"] == "memory")
            |> filter(fn: (r) => r["agent_id"] == "{agent_id}")
            |> filter(fn: (r) => r["user_id"] == "{user_id}")
            |> filter(fn: (r) => r["_field"] == "{mem_field}")
        '''
        
        mem_tables = query_api.query(mem_query, org=INFLUXDB_ORG)
        mem_values = [record.get_value() for table in mem_tables for record in table.records]
        
        return {
            "agent_id": agent_id,
            "period": {"start": start, "stop": stop},
            "bucket": bucket,
            "cpu": {
                "avg": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                "max": max(cpu_values) if cpu_values else 0,
                "min": min(cpu_values) if cpu_values else 0,
                "data_points": len(cpu_values)
            },
            "memory": {
                "avg": sum(mem_values) / len(mem_values) if mem_values else 0,
                "max": max(mem_values) if mem_values else 0,
                "min": min(mem_values) if mem_values else 0,
                "data_points": len(mem_values)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    influx_status = "connected" if influx_client else "disconnected"
    return {"status": "ok", "influxdb": influx_status}
