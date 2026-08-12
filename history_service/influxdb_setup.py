"""
InfluxDB Downsampling and Retention Setup

This module sets up:
1. Multiple buckets with different retention policies:
   - metrics_raw: 5-second resolution, 24-hour retention
   - metrics_1m: 1-minute resolution (aggregated), 7-day retention  
   - metrics_1h: 1-hour resolution (aggregated), 365-day retention

2. Downsampling tasks that automatically aggregate data:
   - Raw -> 1-minute (runs every minute)
   - 1-minute -> 1-hour (runs every hour)
"""

import os
from influxdb_client import InfluxDBClient, BucketRetentionRules
from influxdb_client.client.exceptions import InfluxDBError

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "statusmonitor-secret-token")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "statusmonitor")

# Bucket configurations
BUCKETS = {
    "metrics_raw": {
        "retention_seconds": 24 * 60 * 60,  # 24 hours
        "description": "Raw metrics at 5-second resolution"
    },
    "metrics_1m": {
        "retention_seconds": 7 * 24 * 60 * 60,  # 7 days
        "description": "1-minute aggregated metrics"
    },
    "metrics_1h": {
        "retention_seconds": 365 * 24 * 60 * 60,  # 1 year
        "description": "1-hour aggregated metrics"
    }
}

# Downsampling task: Raw (5s) -> 1 minute
TASK_RAW_TO_1M = '''
option task = {name: "downsample_raw_to_1m", every: 1m}

// CPU metrics
from(bucket: "metrics_raw")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    |> set(key: "_measurement", value: "cpu")
    |> to(bucket: "metrics_1m", org: "{org}")

// Memory metrics
from(bucket: "metrics_raw")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    |> set(key: "_measurement", value: "memory")
    |> to(bucket: "metrics_1m", org: "{org}")

// Disk metrics (percent)
from(bucket: "metrics_raw")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "disk")
    |> filter(fn: (r) => r["_field"] == "percent")
    |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    |> set(key: "_measurement", value: "disk")
    |> to(bucket: "metrics_1m", org: "{org}")

// Network bytes (use last to preserve cumulative values)
from(bucket: "metrics_raw")
    |> range(start: -2m)
    |> filter(fn: (r) => r["_measurement"] == "network")
    |> filter(fn: (r) => r["_field"] == "bytes_sent" or r["_field"] == "bytes_recv")
    |> aggregateWindow(every: 1m, fn: last, createEmpty: false)
    |> set(key: "_measurement", value: "network")
    |> to(bucket: "metrics_1m", org: "{org}")
'''

# Downsampling task: 1 minute -> 1 hour
TASK_1M_TO_1H = '''
option task = {name: "downsample_1m_to_1h", every: 1h}

// CPU metrics with min/max/avg
from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_field", value: "usage_percent_avg")
    |> set(key: "_measurement", value: "cpu")
    |> to(bucket: "metrics_1h", org: "{org}")

from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> set(key: "_field", value: "usage_percent_max")
    |> set(key: "_measurement", value: "cpu")
    |> to(bucket: "metrics_1h", org: "{org}")

from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "cpu")
    |> filter(fn: (r) => r["_field"] == "usage_percent")
    |> aggregateWindow(every: 1h, fn: min, createEmpty: false)
    |> set(key: "_field", value: "usage_percent_min")
    |> set(key: "_measurement", value: "cpu")
    |> to(bucket: "metrics_1h", org: "{org}")

// Memory metrics with min/max/avg
from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_field", value: "used_percent_avg")
    |> set(key: "_measurement", value: "memory")
    |> to(bucket: "metrics_1h", org: "{org}")

from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> set(key: "_field", value: "used_percent_max")
    |> set(key: "_measurement", value: "memory")
    |> to(bucket: "metrics_1h", org: "{org}")

from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "memory")
    |> filter(fn: (r) => r["_field"] == "used_percent")
    |> aggregateWindow(every: 1h, fn: min, createEmpty: false)
    |> set(key: "_field", value: "used_percent_min")
    |> set(key: "_measurement", value: "memory")
    |> to(bucket: "metrics_1h", org: "{org}")

// Disk metrics
from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "disk")
    |> filter(fn: (r) => r["_field"] == "percent")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_field", value: "percent_avg")
    |> set(key: "_measurement", value: "disk")
    |> to(bucket: "metrics_1h", org: "{org}")

// Network bytes (last value for cumulative counters)
from(bucket: "metrics_1m")
    |> range(start: -2h)
    |> filter(fn: (r) => r["_measurement"] == "network")
    |> filter(fn: (r) => r["_field"] == "bytes_sent" or r["_field"] == "bytes_recv")
    |> aggregateWindow(every: 1h, fn: last, createEmpty: false)
    |> set(key: "_measurement", value: "network")
    |> to(bucket: "metrics_1h", org: "{org}")
'''


def setup_influxdb():
    """Set up buckets and downsampling tasks in InfluxDB"""
    print("Setting up InfluxDB downsampling infrastructure...")
    
    try:
        client = InfluxDBClient(
            url=INFLUXDB_URL,
            token=INFLUXDB_TOKEN,
            org=INFLUXDB_ORG
        )
        
        buckets_api = client.buckets_api()
        tasks_api = client.tasks_api()
        orgs_api = client.organizations_api()
        
        # Get org ID
        orgs = orgs_api.find_organizations(org=INFLUXDB_ORG)
        if not orgs:
            print(f"Organization '{INFLUXDB_ORG}' not found!")
            return False
        org_id = orgs[0].id
        
        # Create buckets
        for bucket_name, config in BUCKETS.items():
            existing = buckets_api.find_bucket_by_name(bucket_name)
            if existing:
                print(f"  Bucket '{bucket_name}' already exists, updating retention...")
                # Update retention if needed
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
        
        # Create or update tasks
        existing_tasks = tasks_api.find_tasks()
        task_names = {t.name: t for t in existing_tasks}
        
        # Task: Raw -> 1m
        task_flux_1m = TASK_RAW_TO_1M.replace("{org}", INFLUXDB_ORG)
        if "downsample_raw_to_1m" in task_names:
            print("  Task 'downsample_raw_to_1m' already exists, updating...")
            task = task_names["downsample_raw_to_1m"]
            task.flux = task_flux_1m
            tasks_api.update_task(task)
        else:
            print("  Creating task 'downsample_raw_to_1m'...")
            tasks_api.create_task_every(
                name="downsample_raw_to_1m",
                flux=task_flux_1m,
                every="1m",
                org_id=org_id
            )
        
        # Task: 1m -> 1h
        task_flux_1h = TASK_1M_TO_1H.replace("{org}", INFLUXDB_ORG)
        if "downsample_1m_to_1h" in task_names:
            print("  Task 'downsample_1m_to_1h' already exists, updating...")
            task = task_names["downsample_1m_to_1h"]
            task.flux = task_flux_1h
            tasks_api.update_task(task)
        else:
            print("  Creating task 'downsample_1m_to_1h'...")
            tasks_api.create_task_every(
                name="downsample_1m_to_1h",
                flux=task_flux_1h,
                every="1h",
                org_id=org_id
            )
        
        # Also update the default 'metrics' bucket retention to 24h if it exists
        # (for backward compatibility during migration)
        default_bucket = buckets_api.find_bucket_by_name("metrics")
        if default_bucket:
            print("  Updating legacy 'metrics' bucket retention to 24h...")
            default_bucket.retention_rules = [
                BucketRetentionRules(
                    type="expire",
                    every_seconds=24 * 60 * 60  # 24 hours
                )
            ]
            buckets_api.update_bucket(bucket=default_bucket)
        
        client.close()
        print("InfluxDB downsampling setup complete!")
        return True
        
    except InfluxDBError as e:
        print(f"InfluxDB setup error: {e}")
        return False
    except Exception as e:
        print(f"Setup error: {e}")
        return False


def get_bucket_for_time_range(start: str) -> tuple[str, str]:
    """
    Determine the appropriate bucket and field suffix based on time range.
    
    Returns:
        tuple: (bucket_name, field_suffix)
        - field_suffix is empty for raw/1m data, "_avg" for 1h data
    """
    # Parse the start time to determine range
    # Format: -1h, -24h, -7d, -30d, etc.
    
    if start.startswith("-"):
        time_str = start[1:]  # Remove leading '-'
        
        # Parse value and unit
        if time_str.endswith("s"):
            seconds = int(time_str[:-1])
        elif time_str.endswith("m"):
            seconds = int(time_str[:-1]) * 60
        elif time_str.endswith("h"):
            seconds = int(time_str[:-1]) * 3600
        elif time_str.endswith("d"):
            seconds = int(time_str[:-1]) * 86400
        elif time_str.endswith("w"):
            seconds = int(time_str[:-1]) * 604800
        elif time_str.endswith("mo"):
            seconds = int(time_str[:-2]) * 2592000  # ~30 days
        elif time_str.endswith("y"):
            seconds = int(time_str[:-1]) * 31536000  # ~365 days
        else:
            seconds = 3600  # Default to 1 hour
        
        # Bucket selection logic:
        # <= 24 hours: Use raw data (metrics_raw) - highest resolution
        # <= 7 days: Use 1-minute data (metrics_1m) - medium resolution  
        # > 7 days: Use 1-hour data (metrics_1h) - long-term storage
        
        if seconds <= 24 * 3600:  # <= 24 hours
            return "metrics_raw", ""
        elif seconds <= 7 * 24 * 3600:  # <= 7 days
            return "metrics_1m", ""
        else:  # > 7 days
            return "metrics_1h", "_avg"
    
    # Default to raw bucket
    return "metrics_raw", ""


if __name__ == "__main__":
    setup_influxdb()
