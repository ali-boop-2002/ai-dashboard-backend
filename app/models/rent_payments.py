from sqlalchemy import Column, BigInteger, Integer, ForeignKey, Date, Numeric, String, DateTime, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class RentPayment(Base):
    __tablename__ = "rent_payments"

    id = Column(BigInteger, primary_key=True, index=True)

    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)

    # First day of the month this payment belongs to (ex: 2026-02-01)
    period_start = Column(Date, nullable=False, index=True)

    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String, nullable=False, default="paid")  # paid / void / refunded / partial

    paid_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships (use back_populates to match other models; Unit/Property define the reverse)
    unit = relationship("Unit", back_populates="rent_payments")
    property = relationship("Property", back_populates="rent_payments")
