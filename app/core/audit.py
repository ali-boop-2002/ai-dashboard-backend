from datetime import datetime, timezone
from typing import Optional

from app.core.auth import User
from app.models.audit_log import AuditLog
from sqlalchemy.orm import Session


def _compute_risk_level(
    entity_type: str,
    status: Optional[str],
    due_at: Optional[datetime],
    explicit: Optional[str] = None,
) -> str:
    if explicit:
        return explicit
    if due_at is None:
        return "low"
    now = datetime.now(timezone.utc)
    overdue = due_at < now
    if not overdue:
        return "low"

    status_l = (status or "").lower()
    if entity_type == "approval" and status_l == "pending":
        return "high"
    if entity_type == "ticket" and status_l != "closed":
        return "high"
    return "low"


def log_audit(
    db: Session,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: str,
    source: str = "api",
    status: Optional[str] = None,
    due_at: Optional[datetime] = None,
    property_id: Optional[int] = None,
    description: Optional[str] = None,
    risk_level: Optional[str] = None,
) -> AuditLog:
    log = AuditLog(
        actor_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        source=source,
        status=status,
        due_at=due_at,
        property_id=property_id,
        description=description,
        risk_level=_compute_risk_level(entity_type, status, due_at, risk_level),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
