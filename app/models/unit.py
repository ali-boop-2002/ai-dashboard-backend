from sqlalchemy import Column, String, Integer, DateTime, BigInteger, ForeignKey, Boolean, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Unit(Base):
    __tablename__ = "units"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign key to Property
    property_id = Column(BigInteger, ForeignKey("properties.id"), nullable=False, index=True)
    property = relationship("Property", back_populates="units")
    rent_payments = relationship("RentPayment", back_populates="unit", cascade="all, delete-orphan")

    # Unit information
    unit_number = Column(Integer, nullable=False, index=True)  # 1, 2, 3, etc.
    rent_amount = Column(Numeric(10, 2), nullable=True)  # Monthly rent (can be null initially)
    rent_date = Column(DateTime(timezone=True), nullable=True)  # Date rent starts; stored as UTC
    occupied = Column(Boolean, nullable=False, default=False)  # Is unit occupied?
    paid = Column(Boolean, nullable=False, default=False)  # Is rent paid?
    over_due = Column(Boolean, nullable=False, default=False)  # Is rent overdue?

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)

    class Config:
        from_attributes = True
