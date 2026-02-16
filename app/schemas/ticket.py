from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional

class TicketCreate(BaseModel):
    property_id: int  # REQUIRED - every ticket must belong to a property
    type: str
    issue: str
    priority: str = "medium"
    assigned_to: Optional[str] = None
    sla_due_at: Optional[datetime] = None
    maintenance_category: Optional[str] = None  # Only for maintenance tickets: plumbing, hvac, electrical
    
    @field_validator('maintenance_category')
    @classmethod
    def validate_maintenance_category(cls, v, info):
        """Only allow maintenance_category if type is 'maintenance'"""
        if v is not None:
            # Get the type from data being validated
            ticket_type = info.data.get('type')
            
            # If maintenance_category is provided, type must be 'maintenance'
            if ticket_type != 'maintenance':
                raise ValueError("maintenance_category can only be set when type is 'maintenance'")
            
            # Validate that maintenance_category is one of the allowed values
            allowed_categories = ['plumbing', 'hvac', 'electrical']
            if v.lower() not in allowed_categories:
                raise ValueError(f"maintenance_category must be one of: {', '.join(allowed_categories)}")
        
        return v.lower() if v else None


class TicketUpdate(BaseModel):
    property_id: Optional[int] = None
    type: Optional[str] = None
    issue: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    sla_due_at: Optional[datetime] = None
    maintenance_category: Optional[str] = None


class TicketOut(BaseModel):
    id: int
    property_id: int  # Foreign key to Property
    type: str
    issue: str
    priority: str
    status: str
    assigned_to: Optional[str]
    sla_due_at: Optional[datetime]
    maintenance_category: Optional[str]  # Only for maintenance tickets
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True