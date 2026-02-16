from sqlalchemy import Column, String, DateTime, Integer, BigInteger, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    # Event type: "ticket_created", "approval_created", "ticket_updated", "approval_updated"
    event_type = Column(String, nullable=False, index=True)

    # Link to property
    property_id = Column(BigInteger, ForeignKey("properties.id"), nullable=False, index=True)

    # Link to ticket (optional - only for ticket events)
    # Note: nullable=True allows NULL, but we also check with isnot(None) to avoid foreign key violations
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True, index=True)

    # Link to approval (optional - only for approval events)
    approval_id = Column(String, ForeignKey("approvals.id"), nullable=True, index=True)

    # Description of the event
    description = Column(String, nullable=True)

    # Due date (copied from ticket/approval) - ALWAYS UTC
    due_date = Column(DateTime(timezone=True), nullable=True, index=True)

    # When the event was created
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)
