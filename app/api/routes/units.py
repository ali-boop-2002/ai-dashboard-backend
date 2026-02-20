from calendar import monthrange
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api.deps import get_db
from app.models.unit import Unit
from app.models.rent_payments import RentPayment
from app.schemas.unit import UnitCreate, UnitUpdate, UnitOut, compute_over_due
from app.core.auth import get_current_user, User
from app.core.audit import log_audit


def _add_one_month(dt: datetime) -> datetime:
    """
    Add one month, same day. Jan 31 -> Feb 28/29.
    Handles month-end overflow (e.g. Jan 31 -> Feb 28 in non-leap year).
    """
    year, month, day = dt.year, dt.month, dt.day
    if month == 12:
        new_year, new_month = year + 1, 1
    else:
        new_year, new_month = year, month + 1
    _, last_day = monthrange(new_year, new_month)
    new_day = min(day, last_day)
    # Preserve timezone if present
    return dt.replace(year=new_year, month=new_month, day=new_day)

router = APIRouter(prefix="/units", tags=["units"])


@router.get("", response_model=List[UnitOut])
def list_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    property_id: Optional[int] = Query(None, description="Filter by property ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Get all units, optionally filtered by property_id.
    """
    q = db.query(Unit)

    if property_id is not None:
        q = q.filter(Unit.property_id == property_id)

    q = q.order_by(Unit.property_id, Unit.unit_number)
    items = q.offset(offset).limit(limit).all()
    return items


@router.get("/{unit_id}", response_model=UnitOut)
def get_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific unit by ID.
    """
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.post("", response_model=UnitOut, status_code=201)
def create_unit(
    payload: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Manually create a unit (normally units are auto-created when property is created).
    over_due is computed from occupied, rent_date, paid.
    """
    # Build DB model from request payload
    unit = Unit(**payload.model_dump())

    # Invariants:
    # - If occupied=True => rent_amount and rent_date required
    # - If occupied=False => paid must be False AND rent_amount/rent_date must be null
    if unit.occupied is True:
        if unit.rent_amount is None or unit.rent_date is None:
            raise HTTPException(
                status_code=400,
                detail="rent_amount and rent_date are required when occupied is true",
            )
    else:
        if unit.paid is True:
            raise HTTPException(status_code=400, detail="paid cannot be true when occupied is false")
        if unit.rent_amount is not None or unit.rent_date is not None:
            raise HTTPException(
                status_code=400,
                detail="rent_amount and rent_date must be null when occupied is false",
            )

    # Compute overdue from the final state
    unit.over_due = compute_over_due(unit.occupied, unit.rent_date, unit.paid)

    db.add(unit)
    db.commit()
    db.refresh(unit)
    log_audit(
        db,
        actor=current_user,
        action="created",
        entity_type="unit",
        entity_id=str(unit.id),
        status="over_due" if unit.over_due else "ok",
        property_id=unit.property_id,
        source="api",
        description=f"Unit created: {unit.unit_number}",
        risk_level="high" if unit.over_due else "low",
    )
    return unit


@router.patch("/{unit_id}", response_model=UnitOut)
def update_unit(
    unit_id: int,
    payload: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a unit's rent_amount and/or occupied status.
    """
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    data = payload.model_dump(exclude_unset=True)
    paid_just_set_true = data.get("paid") is True
    rent_payment: Optional[RentPayment] = None

    for k, v in data.items():
        setattr(unit, k, v)

    # When paid is set to True: create RentPayment, then roll forward to next month, reset paid to False.
    if paid_just_set_true and unit.occupied and unit.rent_date is not None and unit.rent_amount is not None:
        # 1. Capture current period (before advancing): rent_date defines the period being paid
        rent_dt = unit.rent_date
        # Ensure we use UTC: make timezone-aware if naive (treat as UTC)
        if rent_dt.tzinfo is None:
            rent_dt = rent_dt.replace(tzinfo=timezone.utc)
        period_start_date = rent_dt.date().replace(day=1)  # First day of the month

        # 2. Create RentPayment: linked to unit and property, records payment in UTC
        paid_at_utc = datetime.now(timezone.utc)
        rent_payment = RentPayment(
            unit_id=unit.id,
            property_id=unit.property_id,
            period_start=period_start_date,
            amount=unit.rent_amount,
            status="paid",
            paid_at=paid_at_utc,
        )
        db.add(rent_payment)

        # 3. Roll forward: next month same day, reset paid for new period
        unit.rent_date = _add_one_month(unit.rent_date)
        unit.paid = False

    # If not occupied, force a clean state (paid/rent fields must not be set)
    if unit.occupied is False:
        unit.paid = False
        unit.rent_amount = None
        unit.rent_date = None

    # If occupied, require rent fields
    if unit.occupied is True and (unit.rent_amount is None or unit.rent_date is None):
        raise HTTPException(
            status_code=400,
            detail="rent_amount and rent_date are required when occupied is true",
        )

    # Safety check (should be impossible after normalization, but keep it explicit)
    if unit.occupied is False and unit.paid is True:
        raise HTTPException(status_code=400, detail="paid cannot be true when occupied is false")

    # Recompute overdue from the final state
    unit.over_due = compute_over_due(unit.occupied, unit.rent_date, unit.paid)

    db.commit()
    db.refresh(unit)
    log_audit(
        db,
        actor=current_user,
        action="updated",
        entity_type="unit",
        entity_id=str(unit.id),
        status="over_due" if unit.over_due else "ok",
        property_id=unit.property_id,
        source="api",
        description=f"Unit updated: {unit.unit_number}",
        risk_level="high" if unit.over_due else "low",
    )
    if rent_payment is not None:
        log_audit(
            db,
            actor=current_user,
            action="created",
            entity_type="rent_payment",
            entity_id=str(rent_payment.id),
            status=rent_payment.status,
            property_id=rent_payment.property_id,
            source="api",
            description=f"Rent payment created for unit {unit.unit_number}",
        )
    return unit


@router.delete("/{unit_id}", status_code=204)
def delete_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a unit.
    """
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    db.delete(unit)
    db.commit()
    log_audit(
        db,
        actor=current_user,
        action="deleted",
        entity_type="unit",
        entity_id=str(unit.id),
        status="over_due" if unit.over_due else "ok",
        property_id=unit.property_id,
        source="api",
        description=f"Unit deleted: {unit.unit_number}",
        risk_level="high" if unit.over_due else "low",
    )
    return None
