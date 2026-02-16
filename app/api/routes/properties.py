from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func
from typing import List, Optional

from app.api.deps import get_db
from app.models.property import Property
from app.models.ticket import Ticket
from app.models.unit import Unit
from app.models.event import Event
from app.models.approval import Approval

from app.schemas.property import (
    PropertyCreate,
    PropertyUpdate,
    PropertyOut,
    PropertyDetailOut,
    PropertyStatsOut,
    OccupancyUpdate,
)

router = APIRouter(prefix="/properties", tags=["properties"])


def apply_property_filters(
    q, status: Optional[str], manager_name: Optional[str], search: Optional[str]
):
    if status:
        q = q.filter(Property.status == status)

    if manager_name:
        q = q.filter(Property.manager_name == manager_name)

    # basic search: name/address/city/state/zip
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            Property.name.ilike(like)
            | Property.address.ilike(like)
            | Property.city.ilike(like)
            | Property.state.ilike(like)
            | Property.zip.ilike(like)
        )

    return q


@router.get("", response_model=List[PropertyOut])
def list_properties(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="healthy|attention|critical"),
    manager_name: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="search by name/address/city/state/zip"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Returns properties with:
    - tickets_count (all tickets)
    - open_tickets_count (tickets where status != 'closed')
    - high_priority_tickets_count (open tickets where priority == 'high')
    - occupied_units_count (units where occupied=true)

    NOTE: We aggregate tickets and units in separate subqueries to avoid
    inflated counts caused by joining two one-to-many tables in a single query.
    """
    from sqlalchemy import case

    # --- Ticket aggregates per property ---
    tickets_agg = (
        db.query(
            Ticket.property_id.label("property_id"),
            func.count(Ticket.id).label("tickets_count"),
            func.sum(case((Ticket.status != "closed", 1), else_=0)).label("open_tickets_count"),
            func.sum(
                case(
                    ((Ticket.status != "closed") & (Ticket.priority == "high"), 1),
                    else_=0,
                )
            ).label("high_priority_tickets_count"),
        )
        .group_by(Ticket.property_id)
        .subquery()
    )

    # --- Unit aggregates per property ---
    units_agg = (
        db.query(
            Unit.property_id.label("property_id"),
            func.sum(case((Unit.occupied == True, 1), else_=0)).label("occupied_units_count"),
        )
        .group_by(Unit.property_id)
        .subquery()
    )

    # Base query: Property + aggregated columns (LEFT JOIN so properties with no rows still appear)
    q = (
        db.query(
            Property,
            func.coalesce(tickets_agg.c.tickets_count, 0).label("tickets_count"),
            func.coalesce(tickets_agg.c.open_tickets_count, 0).label("open_tickets_count"),
            func.coalesce(tickets_agg.c.high_priority_tickets_count, 0).label(
                "high_priority_tickets_count"
            ),
            func.coalesce(units_agg.c.occupied_units_count, 0).label("occupied_units_count"),
        )
        .outerjoin(tickets_agg, tickets_agg.c.property_id == Property.id)
        .outerjoin(units_agg, units_agg.c.property_id == Property.id)
    )

    q = apply_property_filters(q, status, manager_name, search)
    q = q.order_by(Property.id.desc())

    items = q.offset(offset).limit(limit).all()

    # Transform results: [(Property, tickets_count, open_count, high_priority_count, occupied_units_count), ...]
    result: List[Property] = []
    for (
        prop,
        tickets_count,
        open_tickets_count,
        high_priority_tickets_count,
        occupied_units_count,
    ) in items:
        prop.tickets_count = int(tickets_count or 0)
        prop.open_tickets_count = int(open_tickets_count or 0)
        prop.high_priority_tickets_count = int(high_priority_tickets_count or 0)
        prop.occupied_units_count = int(occupied_units_count or 0)
        result.append(prop)

    return result


@router.get("/stats", response_model=PropertyStatsOut)
def properties_stats(db: Session = Depends(get_db)):
    """
    For the top cards:
    - Total Properties
    - Active Issues (open tickets)
    - High Priority Issues
    - Upcoming Appointments (placeholder for now)
    - SLA Risks (placeholder for now)
    """
    total_properties = db.query(func.count(Property.id)).scalar() or 0

    # "Active Issues" = tickets not closed
    active_issues = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.status != "closed")
        .scalar()
        or 0
    )

    high_priority_issues = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.status != "closed", Ticket.priority == "high")
        .scalar()
        or 0
    )

    # These depend on your future models (events + SLA engine)
    upcoming_appointments = 0
    sla_risks = 0

    return {
        "total_properties": total_properties,
        "active_issues": active_issues,
        "high_priority_issues": high_priority_issues,
        "upcoming_appointments": upcoming_appointments,
        "sla_risks": sla_risks,
    }


@router.get("/{property_id}", response_model=PropertyDetailOut)
def get_property(property_id: int, db: Session = Depends(get_db)):
    """
    For your Property detail page:
    - property fields
    - all tickets under that property (active and closed)
    - all approvals under that property
    - all units with their rent amounts and occupancy status
    """
    prop = (
        db.query(Property)
        .options(
            selectinload(Property.tickets),     # Load all tickets
            selectinload(Property.approvals),   # Load all approvals
            selectinload(Property.units)        # Load all units (NEW)
        )
        .filter(Property.id == property_id)
        .first()
    )

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    return prop


@router.post("", response_model=PropertyOut, status_code=201)
def create_property(payload: PropertyCreate, db: Session = Depends(get_db)):
    """
    Create a property and automatically create units based on total_units.
    """
    prop = Property(**payload.model_dump())
    db.add(prop)
    db.commit()
    db.refresh(prop)
    
    # Automatically create units for this property
    # If total_units = 4, create units 1, 2, 3, 4
    for unit_num in range(1, prop.total_units + 1):
        unit = Unit(
            property_id=prop.id,
            unit_number=unit_num,
            rent_amount=None,  # User will set this later
            occupied=False,
        )
        db.add(unit)
    
    db.commit()
    return prop


@router.patch("/{property_id}", response_model=PropertyOut)
def update_property(property_id: int, payload: PropertyUpdate, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    old_total_units = prop.total_units
    data = payload.model_dump(exclude_unset=True)
    
    for k, v in data.items():
        setattr(prop, k, v)

    # Handle total_units change - auto-create new units
    new_total_units = prop.total_units
    if 'total_units' in data and new_total_units > old_total_units:
        # Create additional units
        current_unit_count = db.query(Unit).filter(Unit.property_id == property_id).count()
        
        for unit_num in range(current_unit_count + 1, new_total_units + 1):
            unit = Unit(
                property_id=property_id,
                unit_number=unit_num,
                rent_amount=None,
                occupied=False,
            )
            db.add(unit)

    db.commit()
    db.refresh(prop)
    return prop


@router.delete("/{property_id}", status_code=204)
def delete_property(property_id: int, db: Session = Depends(get_db)):
    """
    Delete a property and all related data (events, approvals, tickets, units, rent_payments).
    """
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    # Delete in dependency order (children before parents due to FKs)
    db.query(Event).filter(Event.property_id == property_id).delete()
    db.query(Approval).filter(Approval.property_id == property_id).delete()
    db.query(Ticket).filter(Ticket.property_id == property_id).delete()
    db.delete(prop)  # cascade deletes units, rent_payments
    db.commit()
    return None


@router.patch("/{property_id}/occupancy", response_model=PropertyOut)
def update_property_occupancy(property_id: int, payload: OccupancyUpdate, db: Session = Depends(get_db)):
    """
    Update occupancy for a specific property.
    
    **Validation:**
    - occupancy cannot be negative
    - occupancy cannot exceed total_units
    
    **Example:**
    ```
    PATCH /properties/{property_id}/occupancy
    {
        "occupancy": 3
    }
    ```
    
    If property has 4 units and you try to set occupancy to 5, you'll get a 400 error.
    """
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    
    # Validate: occupancy cannot exceed total_units
    if payload.occupancy > prop.total_units:
        raise HTTPException(
            status_code=400,
            detail=f"Occupancy ({payload.occupancy}) cannot exceed total_units ({prop.total_units})"
        )
    
    prop.occupancy = payload.occupancy
    db.commit()
    db.refresh(prop)
    return prop