from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.auth import get_current_user, User
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


def _is_overdue(log: AuditLog) -> bool:
    if not log.due_at:
        return False
    now = datetime.now(timezone.utc)
    return log.due_at < now and (log.status or "").lower() in ("open", "in_progress", "waiting", "pending")


@router.get("", response_model=List[AuditLogOut])
def list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: Optional[str] = Query(None, description="ISO date-time"),
    end_date: Optional[str] = Query(None, description="ISO date-time"),
    actor: Optional[str] = Query(None, description="Filter by actor email"),
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None, description="low|medium|high"),
    high_risk_only: Optional[bool] = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = db.query(AuditLog)

    if start_date:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        q = q.filter(AuditLog.created_at >= dt)
    if end_date:
        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        q = q.filter(AuditLog.created_at <= dt)
    if actor:
        q = q.filter(AuditLog.actor_email == actor)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if action:
        q = q.filter(AuditLog.action == action)
    if source:
        q = q.filter(AuditLog.source == source)
    if risk_level:
        q = q.filter(AuditLog.risk_level == risk_level)

    logs = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    if high_risk_only:
        logs = [l for l in logs if _is_overdue(l) or l.risk_level == "high"]
    return logs


@router.get("/stats")
def audit_log_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total = db.query(AuditLog).count()
    today = db.query(AuditLog).filter(AuditLog.created_at >= start_today).count()
    deletions = db.query(AuditLog).filter(AuditLog.action == "deleted").count()

    logs = db.query(AuditLog).all()
    high_risk = sum(1 for l in logs if _is_overdue(l) or l.risk_level == "high")

    return {
        "total": total,
        "today": today,
        "high_risk": high_risk,
        "deletions": deletions,
        "retention_days": 90,
    }
