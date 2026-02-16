from pydantic import BaseModel, model_validator
from datetime import datetime, timezone
from typing import Optional
from decimal import Decimal


def compute_over_due(occupied: bool, rent_date: Optional[datetime], paid: bool) -> bool:
    """
    Overdue = occupied AND rent_date has passed (rent_date < today UTC) AND not paid.
    If paid is True, over_due is always False.
    """
    if paid:
        return False
    if not occupied or rent_date is None:
        return False
    today = datetime.now(timezone.utc).date()
    rent_date_only = rent_date.date() if hasattr(rent_date, "date") else rent_date
    return rent_date_only < today


class UnitCreate(BaseModel):
    unit_number: int
    rent_amount: Optional[Decimal] = None
    rent_date: Optional[datetime] = None  # UTC; accepts ISO 8601 e.g. "2026-02-14T00:00:00Z"
    occupied: bool = False
    paid: bool = False
    # over_due is computed, not set by user

    @model_validator(mode="after")
    def validate_invariants(self) -> "UnitCreate":
        # If occupied, rent_amount and rent_date must exist
        if self.occupied:
            if self.rent_amount is None or self.rent_date is None:
                raise ValueError("rent_amount and rent_date are required when occupied is true")
        else:
            # If not occupied, paid must be false and rent fields must be null
            if self.paid:
                raise ValueError("paid cannot be true when occupied is false")
            if self.rent_amount is not None or self.rent_date is not None:
                raise ValueError("rent_amount and rent_date must be null when occupied is false")
        return self



class UnitUpdate(BaseModel):
    unit_number: Optional[int] = None
    rent_amount: Optional[Decimal] = None
    rent_date: Optional[datetime] = None  # UTC; accepts ISO 8601
    occupied: Optional[bool] = None
    paid: Optional[bool] = None
    # over_due is computed from occupied, rent_date, paid - not set by user

    @model_validator(mode="after")
    def validate_invariants(self) -> "UnitUpdate":
        # PATCH-safe: only enforce the stricter rules when this payload explicitly sets occupied.

        # If this PATCH explicitly sets occupied=False, then paid must not be True and rent fields must be null.
        if self.occupied is False:
            if self.paid is True:
                raise ValueError("paid cannot be true when occupied is false")
            if self.rent_amount is not None or self.rent_date is not None:
                raise ValueError("rent_amount and rent_date must be null when occupied is false")

        # If this PATCH explicitly sets occupied=True, require rent_amount and rent_date.
        if self.occupied is True:
            if self.rent_amount is None or self.rent_date is None:
                raise ValueError("rent_amount and rent_date are required when occupied is true")

        return self


class UnitOut(BaseModel):
    id: int
    property_id: int
    unit_number: int
    rent_amount: Optional[Decimal]
    rent_date: Optional[datetime] = None  # UTC
    occupied: bool
    paid: bool
    over_due: bool  # Computed: occupied AND rent_date < today AND not paid
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def set_computed_over_due(self) -> "UnitOut":
        """Compute over_due from occupied, rent_date, paid. paid=True -> always False."""
        self.over_due = compute_over_due(self.occupied, self.rent_date, self.paid)
        return self

    class Config:
        from_attributes = True

  