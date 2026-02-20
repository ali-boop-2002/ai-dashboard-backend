from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.api.deps import get_db
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketOut, TicketUpdate
from app.core.auth import get_current_user, User
from app.core.audit import log_audit
from app.core.google_sheets import append_ticket_row, update_ticket_row, delete_ticket_row

router = APIRouter(prefix="/tickets", tags=["tickets"])

@router.get("/", response_model=List[TicketOut])
def list_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    property: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    q: Optional[str] = Query(None),  # search in issue
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(Ticket)

    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if type:
        query = query.filter(Ticket.type == type)
    if property:
        query = query.filter(Ticket.property == property)
    if assigned_to:
        query = query.filter(Ticket.assigned_to == assigned_to)
    if q:
        query = query.filter(Ticket.issue.ilike(f"%{q}%"))

    return query.order_by(Ticket.id.desc()).offset(offset).limit(limit).all()

@router.post("/", response_model=TicketOut)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ticket = Ticket(**payload.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    log_audit(
        db,
        actor=current_user,
        action="created",
        entity_type="ticket",
        entity_id=str(ticket.id),
        status=ticket.status,
        due_at=ticket.sla_due_at,
        property_id=ticket.property_id,
        source="api",
        description=f"Ticket created: {ticket.issue}",
    )

    append_ticket_row(ticket)

    return ticket

@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(ticket, k, v)

    db.commit()
    db.refresh(ticket)
    log_audit(
        db,
        actor=current_user,
        action="updated",
        entity_type="ticket",
        entity_id=str(ticket.id),
        status=ticket.status,
        due_at=ticket.sla_due_at,
        property_id=ticket.property_id,
        source="api",
        description=f"Ticket updated: {ticket.issue}",
    )

    update_ticket_row(ticket)

    return ticket

@router.delete("/{ticket_id}")
def delete_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    db.delete(ticket)
    db.commit()
    log_audit(
        db,
        actor=current_user,
        action="deleted",
        entity_type="ticket",
        entity_id=str(ticket.id),
        status=ticket.status,
        due_at=ticket.sla_due_at,
        property_id=ticket.property_id,
        source="api",
        description=f"Ticket deleted: {ticket.issue}",
    )

    delete_ticket_row(ticket_id)

    return {"ok": True}

@router.post("/from-sheet", response_model=TicketOut)
def create_ticket_from_sheet(payload: TicketCreate, db: Session = Depends(get_db)):
    """
    Unauthenticated endpoint for Google Sheets to create tickets.
    Called by Google Apps Script when a new row is added to the sheet.
    """
    ticket = Ticket(**payload.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    
    log_audit(
        db,
        actor="GoogleSheets",
        action="created",
        entity_type="ticket",
        entity_id=str(ticket.id),
        status=ticket.status,
        due_at=ticket.sla_due_at,
        property_id=ticket.property_id,
        source="google_sheets",
        description=f"Ticket created from Google Sheets: {ticket.issue}",
    )

    append_ticket_row(ticket)

    return ticket
