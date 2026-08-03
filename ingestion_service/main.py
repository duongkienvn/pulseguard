from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from aiokafka import AIOKafkaProducer
from contextlib import asynccontextmanager
import redis.asyncio as redis
import json
import os
import httpx
import asyncio

# Configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "metrics"
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TOKEN_CACHE_TTL = 300  # 5 minutes cache TTL

# Global clients (initialized at startup)
kafka_producer: Optional[AIOKafkaProducer] = None
redis_client: Optional[redis.Redis] = None


async def init_redis():
    """Initialize Redis connection with retry"""
    global redis_client
    max_retries = 10
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            print(f"Connecting to Redis at {REDIS_URL}...")
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            # Test connection
            await redis_client.ping()
            print(f"Connected to Redis at {REDIS_URL}")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Redis connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
            else:
                print(f"Failed to connect to Redis after {max_retries} attempts. Caching disabled.")
                redis_client = None


async def init_kafka():
    """Initialize Kafka producer with retry"""
    global kafka_producer
    
    print(f"Connecting to Kafka at {KAFKA_BOOTSTRAP_SERVERS}...")
    kafka_producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        key_serializer=lambda k: k.encode('utf-8') if k else None,
        acks='all'
    )
    
    max_retries = 10
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            await kafka_producer.start()
            print(f"Connected to Kafka at {KAFKA_BOOTSTRAP_SERVERS}")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Kafka connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
            else:
                print(f"Failed to connect to Kafka after {max_retries} attempts")
                kafka_producer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    await init_redis()
    await init_kafka()
    yield
    # Shutdown
    if kafka_producer:
        await kafka_producer.stop()
        print("Kafka producer stopped")
    if redis_client:
        await redis_client.close()
        print("Redis connection closed")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_cached_token(token: str) -> Optional[dict]:
    """Get token validation result from cache"""
    if not redis_client:
        return None
    
    try:
        cache_key = f"token_cache:{token}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        print(f"Redis get error: {e}")
    
    return None


async def cache_token(token: str, token_info: dict):
    """Cache token validation result with TTL"""
    if not redis_client:
        return
    
    try:
        cache_key = f"token_cache:{token}"
        await redis_client.setex(cache_key, TOKEN_CACHE_TTL, json.dumps(token_info))
    except Exception as e:
        print(f"Redis set error: {e}")


async def validate_agent_token(token: str) -> dict:
    """Validate agent token with caching to reduce auth service load"""
    
    # 1. Check cache first
    cached_result = await get_cached_token(token)
    if cached_result is not None:
        return cached_result
    
    # 2. Cache miss - call auth service
    result = {"valid": False}
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/agents/validate-token",
                params={"token": token}
            )
            if response.status_code == 200:
                result = response.json()
        except Exception as e:
            print(f"Error validating token with auth service: {e}")
            # On auth service error, don't cache - allow retry
            return {"valid": False}
    
    # 3. Cache the result (both valid and invalid tokens)
    await cache_token(token, result)
    
    return result


@app.post("/ingest")
async def ingest_metrics(
    request: Request,
    x_agent_token: Optional[str] = Header(None, alias="X-Agent-Token")
):
    """Ingest metrics from agent"""
    # Validate agent token
    if not x_agent_token:
        raise HTTPException(status_code=401, detail="Missing agent token")
    
    token_info = await validate_agent_token(x_agent_token)
    if not token_info.get("valid"):
        raise HTTPException(status_code=401, detail="Invalid agent token")
    
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Basic validation
    if "timestamp" not in data:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # Add agent info to the data
    data["agent_id"] = token_info["agent_id"]
    data["agent_name"] = token_info["agent_name"]
    data["user_id"] = token_info["user_id"]
    
    # Publish to Kafka
    if not kafka_producer:
        raise HTTPException(status_code=503, detail="Metrics broker unavailable")
    
    try:
        # Use agent_id as partition key to ensure ordering per agent
        await kafka_producer.send_and_wait(
            topic=KAFKA_TOPIC,
            key=str(token_info["agent_id"]),
            value=data
        )
    except Exception as e:
        print(f"Error publishing to Kafka: {e}")
        raise HTTPException(status_code=503, detail="Failed to publish metrics")
            
    return {"status": "received"}


@app.get("/health")
async def health():
    """Health check endpoint with service status"""
    kafka_status = "connected" if kafka_producer else "disconnected"
    
    # Check Redis health
    redis_status = "disconnected"
    if redis_client:
        try:
            await redis_client.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "error"
    
    return {
        "status": "ok",
        "kafka": kafka_status,
        "redis": redis_status,
        "cache_ttl_seconds": TOKEN_CACHE_TTL
    }


@app.get("/cache/stats")
async def cache_stats():
    """Get cache statistics (for debugging)"""
    if not redis_client:
        return {"error": "Redis not connected"}
    
    try:
        # Count cached tokens
        keys = await redis_client.keys("token_cache:*")
        return {
            "cached_tokens": len(keys),
            "cache_ttl_seconds": TOKEN_CACHE_TTL
        }
    except Exception as e:
        return {"error": str(e)}
