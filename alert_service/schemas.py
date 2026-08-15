from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AlertRuleBase(BaseModel):
    agent_id: str
    metric_type: str
    condition: str
    threshold: float
    enabled: bool = True

class AlertRuleCreate(AlertRuleBase):
    pass

class AlertRuleResponse(AlertRuleBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class AlertRecipientBase(BaseModel):
    telegram_chat_id: str
    enabled: bool = True

class AlertRecipientCreate(AlertRecipientBase):
    pass

class AlertRecipientResponse(AlertRecipientBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class AlertHistoryResponse(BaseModel):
    id: int
    rule_id: Optional[int]
    agent_id: str
    agent_name: Optional[str] = None
    metric_type: str
    condition: str
    threshold: float
    value: float
    message: str
    triggered_at: datetime

    class Config:
        from_attributes = True
