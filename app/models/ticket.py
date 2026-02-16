from sqlalchemy import Column, String, DateTime, Integer, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign key to Property
    property_id = Column(BigInteger, ForeignKey("properties.id"), nullable=False, index=True)
    property = relationship("Property", back_populates="tickets")

    # UI columns
    type = Column(String, nullable=False)             # maintenance/complaint/refund/task
    issue = Column(String, nullable=False)            # what the user sees as "Issue"
    priority = Column(String, nullable=False, default="medium")
    status = Column(String, nullable=False, default="open")  # open/in_progress/waiting/closed
    assigned_to = Column(String, nullable=True)       # e.g. "John Doe" (later: user_id FK)
    maintenance_category = Column(String, nullable=True)  # For maintenance tickets: plumbing, hvac, electrical


    # SLA
    sla_due_at = Column(DateTime(timezone=True), nullable=True)

    # timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)