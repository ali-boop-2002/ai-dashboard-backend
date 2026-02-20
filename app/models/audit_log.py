from sqlalchemy import Column, String, DateTime, Integer, BigInteger
from sqlalchemy.sql import func
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(String, nullable=False, index=True)
    actor_email = Column(String, nullable=True, index=True)
    actor_role = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)  # created/updated/deleted
    entity_type = Column(String, nullable=False, index=True)  # ticket/approval/etc
    entity_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=True, index=True)  # web/api/ai/system
    status = Column(String, nullable=True, index=True)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    property_id = Column(BigInteger, nullable=True, index=True)
    risk_level = Column(String, nullable=False, default="low", index=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
