from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    actor_id: str
    actor_email: Optional[str] = None
    actor_role: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    source: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    property_id: Optional[int] = None
    risk_level: str
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
