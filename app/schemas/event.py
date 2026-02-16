from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class EventCreate(BaseModel):
    event_type: str  # "ticket_created", "approval_created", etc.
    property_id: int
    ticket_id: Optional[int] = None  # Will be None or valid ticket ID, NOT 0
    approval_id: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None  # Will be in UTC
    
    @field_validator('ticket_id', 'approval_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        """Convert 0 or empty string to None to avoid foreign key violations"""
        if v == 0 or v == "":
            return None
        return v


class EventUpdate(BaseModel):
    event_type: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class EventOut(BaseModel):
    id: int
    event_type: str
    property_id: int
    ticket_id: Optional[int]
    approval_id: Optional[str]
    description: Optional[str]
    due_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
