from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    agent_id = Column(String, index=True)
    metric_type = Column(String)  # cpu, memory, disk
    condition = Column(String)    # gt (greater than), lt (less than)
    threshold = Column(Float)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AlertRecipient(Base):
    __tablename__ = "alert_recipients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True)
    telegram_chat_id = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AlertHistory(Base):
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(String, index=True)
    agent_name = Column(String, nullable=True)
    metric_type = Column(String)
    condition = Column(String)
    threshold = Column(Float)
    value = Column(Float)
    message = Column(String)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
