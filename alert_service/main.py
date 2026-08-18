from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Optional
import models
import schemas
import database
from kafka import KafkaConsumer
import json
import threading
import os
import time
from telegram_bot import send_telegram_message
import requests

app = FastAPI()

# Create tables
models.Base.metadata.create_all(bind=database.engine)

# Configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "metrics"
KAFKA_GROUP_ID = "alert-service"
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

# Cache for rules to avoid DB hits on every metric
# Structure: {agent_id: [rule1, rule2, ...]}
RULES_CACHE = {}
# Cache for recipients
# Structure: {user_id: chat_id}
RECIPIENTS_CACHE = {}

# Cooldown tracker: {"rule_id:metric_type": last_triggered_timestamp}
# Each metric type (cpu, memory, disk) has its own cooldown timer per rule
COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 300  # 5 minutes cooldown

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authentication")
    
    try:
        # Verify token with auth service
        response = requests.get(
            f"{AUTH_SERVICE_URL}/users/me",
            headers={"Authorization": authorization}
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_data = response.json()
        # Store the original authorization header for downstream calls
        user_data["_authorization"] = authorization
        return user_data
    except requests.RequestException as e:
        raise HTTPException(status_code=401, detail="Authentication failed")

def refresh_caches():
    """Reload rules and recipients from DB to memory"""
    db = database.SessionLocal()
    try:
        # Refresh Rules
        rules = db.query(models.AlertRule).filter(models.AlertRule.enabled == True).all()
        new_rules_cache = {}
        for rule in rules:
            if rule.agent_id not in new_rules_cache:
                new_rules_cache[rule.agent_id] = []
            new_rules_cache[rule.agent_id].append({
                "id": rule.id,
                "metric_type": rule.metric_type,
                "condition": rule.condition,
                "threshold": rule.threshold,
                "user_id": rule.user_id
            })
        global RULES_CACHE
        RULES_CACHE = new_rules_cache

        # Refresh Recipients
        recipients = db.query(models.AlertRecipient).filter(models.AlertRecipient.enabled == True).all()
        new_recipients_cache = {}
        for recipient in recipients:
            if recipient.telegram_chat_id:
                new_recipients_cache[recipient.user_id] = recipient.telegram_chat_id
        global RECIPIENTS_CACHE
        RECIPIENTS_CACHE = new_recipients_cache
    finally:
        db.close()

def check_metrics(data):
    """Evaluate metrics against rules"""
    agent_id = str(data.get("agent_id"))
    data_user_id = data.get("user_id")
    
    if agent_id not in RULES_CACHE:
        return

    rules = RULES_CACHE[agent_id]
    
    for rule in rules:
        # Security check: ensure rule belongs to the same user as the metrics data
        if rule["user_id"] != data_user_id:
            continue
        
        # Check cooldown - each metric type has its own timer
        cooldown_key = f"{rule['id']}:{rule['metric_type']}"
        last_triggered = COOLDOWN_TRACKER.get(cooldown_key, 0)
        if time.time() - last_triggered < COOLDOWN_SECONDS:
            continue

        triggered = False
        current_value = 0
        
        # Extract value based on metric type
        if rule["metric_type"] == "cpu":
            current_value = data.get("cpu", {}).get("usage_percent", 0)
        elif rule["metric_type"] == "memory":
            mem = data.get("memory", {})
            current_value = mem.get("used_percent", mem.get("usage_percent", mem.get("percent", 0)))
        elif rule["metric_type"] == "disk":
            # Disk metrics are in partitions array - use max across all partitions
            disk = data.get("disk", {})
            partitions = disk.get("partitions", [])
            if partitions:
                current_value = max(p.get("percent", 0) for p in partitions)
            else:
                # Fallback for flat structure
                current_value = disk.get("usage_percent", disk.get("percent", 0))
            
        # Evaluate condition
        if rule["condition"] == "gt" and current_value > rule["threshold"]:
            triggered = True
        elif rule["condition"] == "lt" and current_value < rule["threshold"]:
            triggered = True
            
        if triggered:
            # Send Alert
            chat_id = RECIPIENTS_CACHE.get(rule["user_id"])
            agent_name = data.get("agent_name", "Unknown Agent")
            msg = f"🚨 *Alert for {agent_name}*\n\n"
            msg += f"Metric: {rule['metric_type'].upper()}\n"
            msg += f"Current Value: {current_value:.1f}%\n"
            msg += f"Threshold: {'>' if rule['condition'] == 'gt' else '<'} {rule['threshold']}%\n"
            
            # Log to history regardless of telegram delivery
            db = None
            try:
                db = database.SessionLocal()
                history = models.AlertHistory(
                    user_id=rule["user_id"],
                    rule_id=rule["id"],
                    agent_id=agent_id,
                    agent_name=agent_name,
                    metric_type=rule["metric_type"],
                    condition=rule["condition"],
                    threshold=rule["threshold"],
                    value=current_value,
                    message=msg
                )
                db.add(history)
                db.commit()
            except Exception as e:
                print(f"Error logging alert history: {e}")
            finally:
                if db:
                    db.close()
            
            if chat_id and send_telegram_message(chat_id, msg):
                COOLDOWN_TRACKER[cooldown_key] = time.time()
            else:
                # Still set cooldown even if telegram fails, to prevent spam
                COOLDOWN_TRACKER[cooldown_key] = time.time()

def kafka_listener():
    """Background task to consume metrics from Kafka with auto-reconnect"""
    backoff = 1
    max_backoff = 60
    
    while True:
        consumer = None
        try:
            print(f"Connecting to Kafka at {KAFKA_BOOTSTRAP_SERVERS}...")
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(','),
                group_id=KAFKA_GROUP_ID,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset='latest',
                enable_auto_commit=True,
            )
            
            print(f"Started Kafka consumer for alerts (topic: {KAFKA_TOPIC})")
            backoff = 1  # Reset backoff on successful connection
            
            for message in consumer:
                try:
                    data = message.value
                    check_metrics(data)
                except Exception as e:
                    pass  # Silently ignore malformed messages
        except Exception as e:
            print(f"Kafka consumer error: {e}. Reconnecting in {backoff} seconds...")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)  # Exponential backoff
        finally:
            if consumer:
                try:
                    consumer.close()
                except:
                    pass

@app.on_event("startup")
async def startup_event():
    refresh_caches()
    # Start Kafka consumer in background thread
    thread = threading.Thread(target=kafka_listener, daemon=True)
    thread.start()

@app.get("/health")
def health():
    return {"status": "ok"}

# API Endpoints

@app.get("/rules", response_model=List[schemas.AlertRuleResponse])
def get_rules(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    return db.query(models.AlertRule).filter(models.AlertRule.user_id == current_user["id"]).all()

@app.post("/rules", response_model=schemas.AlertRuleResponse)
def create_rule(
    rule: schemas.AlertRuleCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    # Verify agent ownership via auth service
    # Use the original authorization header stored in current_user
    auth_header = current_user.get("_authorization", "")
    try:
        response = requests.get(
            f"{AUTH_SERVICE_URL}/agents/{rule.agent_id}",
            headers={"Authorization": auth_header},
            timeout=5
        )
        # If auth service returns 404 or 401/403, reject the request
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Agent not found or does not belong to you")
        if response.status_code in (401, 403):
            raise HTTPException(status_code=403, detail="Not authorized to create rules for this agent")
        if response.status_code != 200:
            # Unexpected error - fail closed for security
            raise HTTPException(status_code=503, detail="Unable to verify agent ownership")
    except requests.RequestException:
        # If auth service is unreachable, fail closed for security
        raise HTTPException(status_code=503, detail="Auth service unavailable - cannot verify agent ownership")
    
    db_rule = models.AlertRule(**rule.dict(), user_id=current_user["id"])
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    refresh_caches()
    
    return db_rule

@app.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.id == rule_id,
        models.AlertRule.user_id == current_user["id"]
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(rule)
    db.commit()
    refresh_caches()
    return {"status": "deleted"}

@app.get("/recipient", response_model=Optional[schemas.AlertRecipientResponse])
def get_recipient(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    return db.query(models.AlertRecipient).filter(models.AlertRecipient.user_id == current_user["id"]).first()

@app.post("/recipient", response_model=schemas.AlertRecipientResponse)
def update_recipient(
    recipient: schemas.AlertRecipientCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    db_recipient = db.query(models.AlertRecipient).filter(models.AlertRecipient.user_id == current_user["id"]).first()
    if db_recipient:
        db_recipient.telegram_chat_id = recipient.telegram_chat_id
        db_recipient.enabled = recipient.enabled
    else:
        db_recipient = models.AlertRecipient(**recipient.dict(), user_id=current_user["id"])
        db.add(db_recipient)
    
    db.commit()
    db.refresh(db_recipient)
    refresh_caches()
    return db_recipient

@app.get("/history", response_model=List[schemas.AlertHistoryResponse])
def get_alert_history(
    agent_id: Optional[str] = None,
    metric_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """Get alert history with optional filtering"""
    # Validate limit and offset to prevent DoS
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="Offset must be non-negative")
    
    query = db.query(models.AlertHistory).filter(
        models.AlertHistory.user_id == current_user["id"]
    )
    
    if agent_id:
        query = query.filter(models.AlertHistory.agent_id == agent_id)
    if metric_type:
        query = query.filter(models.AlertHistory.metric_type == metric_type)
    
    # Order by most recent first
    query = query.order_by(models.AlertHistory.triggered_at.desc())
    
    return query.offset(offset).limit(limit).all()

@app.delete("/history")
def clear_alert_history(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """Clear all alert history for the current user"""
    db.query(models.AlertHistory).filter(
        models.AlertHistory.user_id == current_user["id"]
    ).delete()
    db.commit()
    return {"status": "cleared"}
