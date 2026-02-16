from sqlalchemy import Column, String, Integer, DateTime, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Property(Base):
    __tablename__ = "properties"

    id = Column(BigInteger, primary_key=True, index=True)

    name = Column(String, nullable=False)
    address = Column(String, nullable=False)

    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip = Column(String, nullable=True)

    total_units = Column(Integer, nullable=False, default=0)
    occupancy = Column(Integer, nullable=False, default=0)  # Current occupied units

    # keep simple now; later you can change to manager_user_id FK
    manager_name = Column(String, nullable=True)

    # healthy / attention / critical
    status = Column(String, nullable=False, default="healthy")
    
    # Reverse relationships - ONE property has MANY tickets, approvals, units, rent_payments
    tickets = relationship("Ticket", back_populates="property", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="property", cascade="all, delete-orphan")
    units = relationship("Unit", back_populates="property", cascade="all, delete-orphan")
    rent_payments = relationship("RentPayment", back_populates="property", cascade="all, delete-orphan")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )