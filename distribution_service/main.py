from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, status
from aiokafka import AIOKafkaConsumer
import asyncio
import os
import json
import httpx
from typing import Dict, Set, Optional

app = FastAPI()

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")

from fastapi.middleware.cors import CORSMiddleware

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
KAFKA_GROUP_ID = "distribution-service"

async def validate_token(token: str) -> Optional[dict]:
    """Validate JWT token with auth service and return user info"""
    if not token:
        return None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{AUTH_SERVICE_URL}/users/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Token validation error: {e}")
    return None

class ConnectionManager:
    def __init__(self):
        # Map: user_id -> set of (websocket, agent_id_filter)
        self.user_connections: Dict[int, Set[tuple]] = {}
        # Map: websocket -> (user_id, agent_id_filter)
        self.connection_info: Dict[WebSocket, tuple] = {}

    async def connect(self, websocket: WebSocket, user_id: int, agent_id: Optional[int] = None):
        await websocket.accept()
        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add((websocket, agent_id))
        self.connection_info[websocket] = (user_id, agent_id)
        print(f"Client connected: user_id={user_id}, agent_id_filter={agent_id}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connection_info:
            user_id, agent_id = self.connection_info[websocket]
            if user_id in self.user_connections:
                self.user_connections[user_id].discard((websocket, agent_id))
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]
            del self.connection_info[websocket]
            print(f"Client disconnected: user_id={user_id}")

    async def send_to_user(self, user_id: int, message: str, agent_id: int):
        """Send message to all connections for a user, filtering by agent_id if specified"""
        if user_id not in self.user_connections:
            return
        
        for websocket, agent_id_filter in list(self.user_connections[user_id]):
            # Send if no filter, or if agent_id matches filter
            if agent_id_filter is None or agent_id_filter == agent_id:
                try:
                    await websocket.send_text(message)
                except Exception:
                    pass

    def get_subscribed_user_ids(self) -> Set[int]:
        """Get all user IDs that have active connections"""
        return set(self.user_connections.keys())

manager = ConnectionManager()

async def kafka_consumer():
    """Consume metrics from Kafka and distribute to WebSocket clients with auto-reconnect"""
    while True:
        consumer = None
        try:
            print(f"Connecting to Kafka at {KAFKA_BOOTSTRAP_SERVERS}...")
            consumer = AIOKafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                group_id=KAFKA_GROUP_ID,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset="latest",  # Only new messages for realtime
                enable_auto_commit=True,
            )
            await consumer.start()
            print(f"Connected to Kafka, consuming from topic: {KAFKA_TOPIC}")

            async for msg in consumer:
                try:
                    data = msg.value
                    user_id = data.get("user_id")
                    agent_id = data.get("agent_id")
                    
                    if user_id:
                        # Serialize back to JSON string for WebSocket
                        await manager.send_to_user(user_id, json.dumps(data), agent_id)
                except Exception as e:
                    print(f"Error processing Kafka message: {e}")
                    
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
    asyncio.create_task(kafka_consumer())

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    agent_id: Optional[int] = Query(None)
):
    """
    WebSocket endpoint for receiving metrics.
    - token: Required, JWT access token for authentication
    - agent_id: Optional, filter to only receive metrics from a specific agent
    """
    # Validate token before accepting connection
    user = await validate_token(token)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    user_id = user["id"]
    await manager.connect(websocket, user_id, agent_id)
    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@app.get("/health")
def health():
    total_connections = sum(len(conns) for conns in manager.user_connections.values())
    return {
        "status": "ok",
        "broker": "kafka",
        "total_connections": total_connections,
        "users_connected": len(manager.user_connections)
    }
