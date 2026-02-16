from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from decimal import Decimal

class ApprovalCreate(BaseModel):
    id: str                 # "APR-001"
    type: str               # refund/credit/vendor_payment
    amount: Decimal
    ticket_id: int
    property_id: int        # REQUIRED - must belong to a property
    requested_by: str
    due_at: Optional[datetime] = None
    
    @field_validator('id', 'type', 'requested_by', mode='before')
    @classmethod
    def strip_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

class ApprovalUpdate(BaseModel):
    status: Optional[str] = None        # pending/approved/rejected
    property_id: Optional[int] = None   # Can update property if needed
    due_at: Optional[datetime] = None
    
    @field_validator('status', mode='before')
    @classmethod
    def strip_status(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

class ApprovalOut(BaseModel):
    id: str
    type: str
    status: str
    amount: Decimal
    ticket_id: int
    property_id: int        # Foreign key to Property
    requested_by: str
    due_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True