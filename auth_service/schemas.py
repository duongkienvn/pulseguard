from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

# Agent schemas
class AgentCreate(BaseModel):
    name: str

class AgentResponse(BaseModel):
    """Response with token - only used for create/regenerate operations."""
    id: int
    name: str
    token: str
    token_expires_at: Optional[datetime] = None
    token_activated: bool = False
    created_at: datetime
    last_seen: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True

class AgentDetailResponse(BaseModel):
    """Response without token - used for GET operations to prevent token leakage."""
    id: int
    name: str
    token_expires_at: Optional[datetime] = None
    token_activated: bool = False
    created_at: datetime
    last_seen: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True

class AgentListResponse(BaseModel):
    id: int
    name: str
    token_activated: bool = False
    created_at: datetime
    last_seen: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True

class AgentTokenValidation(BaseModel):
    valid: bool
    agent_id: Optional[int] = None
    user_id: Optional[int] = None
    agent_name: Optional[str] = None
    error: Optional[str] = None
