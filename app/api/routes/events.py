from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.api.deps import get_db
from app.models.event import Event
from app.schemas.event import EventCreate, EventOut, EventUpdate
from app.core.auth import get_current_user, User

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=List[EventOut])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    property_id: Optional[int] = Query(None),
    event_type: Optional[str] = Query(None),
    ticket_id: Optional[int] = Query(None),
    approval_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    List all events with optional filtering.
    Can filter by property, event type, ticket, or approval.
    """
    q = db.query(Event)

    if property_id:
        q = q.filter(Event.property_id == property_id)
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if ticket_id:
        q = q.filter(Event.ticket_id == ticket_id)
    if approval_id:
        q = q.filter(Event.approval_id == approval_id)

    return q.order_by(Event.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/upcoming", response_model=List[EventOut])
def upcoming_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    property_id: Optional[int] = Query(None),
    days_ahead: int = Query(7, ge=1, le=90),
):
    """
    Get upcoming events (with due_date within the next N days).
    Sorted by due_date ascending.
    """
    now = datetime.now(timezone.utc)
    future_date = datetime.fromtimestamp(now.timestamp() + (days_ahead * 24 * 3600), tz=timezone.utc)

    q = db.query(Event).filter(
        Event.due_date.isnot(None),
        Event.due_date >= now,
        Event.due_date <= future_date,
    )

    if property_id:
        q = q.filter(Event.property_id == property_id)

    return q.order_by(Event.due_date.asc()).all()


@router.get("/overdue", response_model=List[EventOut])
def overdue_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    property_id: Optional[int] = Query(None),
):
    """
    Get overdue events (with due_date in the past).
    """
    now = datetime.now(timezone.utc)

    q = db.query(Event).filter(
        Event.due_date.isnot(None),
        Event.due_date < now,
    )

    if property_id:
        q = q.filter(Event.property_id == property_id)

    return q.order_by(Event.due_date.asc()).all()


@router.post("", response_model=EventOut, status_code=201)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new event (usually done automatically when ticket/approval created).
    """
    event = Event(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a single event by ID.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update an event.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(event, k, v)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete an event.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    db.delete(event)
    db.commit()
    return {"ok": True}
