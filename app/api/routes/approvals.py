from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.api.deps import get_db
from app.models.approval import Approval
from app.models.event import Event
from app.schemas.approval import ApprovalCreate, ApprovalOut, ApprovalUpdate

router = APIRouter(prefix="/approvals", tags=["approvals"])

from sqlalchemy import func
from datetime import datetime, timezone

@router.get("/stats")
def approvals_stats(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)

    pending_count = (
        db.query(func.count(Approval.id))
        .filter(Approval.status == "pending")
        .scalar()
    ) or 0

    pending_amount = (
        db.query(func.coalesce(func.sum(Approval.amount), 0))
        .filter(Approval.status == "pending")
        .scalar()
    )

    overdue_count = (
        db.query(func.count(Approval.id))
        .filter(Approval.status == "pending")
        .filter(Approval.due_at.isnot(None))
        .filter(Approval.due_at < now)
        .scalar()
    ) or 0

    print(pending_count, pending_amount, overdue_count)
    return {
        "pending": int(pending_count),
        "pending_amount": float(pending_amount),  # or str(pending_amount) if you want exact decimals
        "overdue": int(overdue_count),
    }
@router.get("", response_model=List[ApprovalOut])
def list_approvals(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    property: Optional[str] = Query(None),
    requested_by: Optional[str] = Query(None),
    overdue: Optional[bool] = Query(None),
):
    q = db.query(Approval)

    if status:
        q = q.filter(Approval.status == status)
    if type:
        q = q.filter(Approval.type == type)
    if property:
        q = q.filter(Approval.property == property)
    if requested_by:
        q = q.filter(Approval.requested_by == requested_by)

    if overdue is True:
        now = datetime.now(timezone.utc)
        q = q.filter(Approval.status == "pending").filter(Approval.due_at.isnot(None)).filter(Approval.due_at < now)

    return q.order_by(Approval.created_at.desc()).all()

@router.post("", response_model=ApprovalOut)
def create_approval(payload: ApprovalCreate, db: Session = Depends(get_db)):
    exists = db.query(Approval).filter(Approval.id == payload.id).first()
    if exists:
        raise HTTPException(status_code=409, detail="Approval id already exists")

    row = Approval(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    
    # Automatically create an event when approval is created
    event = Event(
        event_type="approval_created",
        property_id=row.property_id,
        approval_id=row.id,
        description=f"Approval {row.id} created: {row.type} - ${row.amount}",
        due_date=row.due_at,  # Copy due date from approval (already in UTC)
    )
    db.add(event)
    db.commit()
    
    return row

@router.patch("/{approval_id}", response_model=ApprovalOut)
def update_approval(approval_id: str, payload: ApprovalUpdate, db: Session = Depends(get_db)):
    row = db.query(Approval).filter(Approval.id == approval_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)

    db.commit()
    db.refresh(row)
    return row

@router.delete("/{approval_id}")
def delete_approval(approval_id: str, db: Session = Depends(get_db)):
    row = db.query(Approval).filter(Approval.id == approval_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    db.delete(row)
    db.commit()
    return {"ok": True}