from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Numeric, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Approval(Base):
    __tablename__ = "approvals"

    # Use a string so you can store "APR-001"
    id = Column(String, primary_key=True, index=True)

    type = Column(String, nullable=False)          # refund / credit / vendor_payment
    status = Column(String, nullable=False, default="pending")  # pending/approved/rejected

    amount = Column(Numeric(10, 2), nullable=False)

    # link to ticket (keep it simple as int FK to tickets.id)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)

    # link to property (BigInteger FK to properties.id)
    property_id = Column(BigInteger, ForeignKey("properties.id"), nullable=False, index=True)
    property = relationship("Property", back_populates="approvals")

    requested_by = Column(String, nullable=False, index=True)

    # due_at is needed to mark overdue
    due_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())