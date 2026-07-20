from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
import database

class User(database.Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    
    refresh_tokens = relationship("RefreshToken", back_populates="user")
    agents = relationship("Agent", back_populates="user")

class RefreshToken(database.Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(DateTime)
    revoked = Column(Boolean, default=False)

    user = relationship("User", back_populates="refresh_tokens")

class Agent(database.Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    token = Column(String, unique=True, index=True)
    token_expires_at = Column(DateTime, nullable=True)  # Token expires 5 min after creation/regeneration
    token_activated = Column(Boolean, default=False)  # True once token is first used
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime)
    last_seen = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="agents")
