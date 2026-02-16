from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime

from app.schemas.ticket import TicketOut  # so PropertyDetailOut can include tickets
from app.schemas.approval import ApprovalOut  # so PropertyDetailOut can include approvals
from app.schemas.unit import UnitOut  # so PropertyDetailOut can include units


class PropertyBase(BaseModel):
    name: str
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    total_units: int = 0
    occupancy: int = 0  # Current occupied units, defaults to 0
    manager_name: Optional[str] = None
    status: str = "healthy"  # healthy|attention|critical


class PropertyCreate(PropertyBase):
    pass


class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    total_units: Optional[int] = None
    occupancy: Optional[int] = None  # Can update occupancy
    manager_name: Optional[str] = None
    status: Optional[str] = None


class OccupancyUpdate(BaseModel):
    """Dedicated schema for updating just the occupancy of a property"""
    occupancy: int
    
    @field_validator('occupancy')
    @classmethod
    def occupancy_must_be_non_negative(cls, v):
        """Occupancy cannot be negative"""
        if v < 0:
            raise ValueError('occupancy cannot be negative')
        return v


class PropertyOut(PropertyBase):
    id: int
    occupancy: int  # Current occupied units
    occupied_units_count: int = 0  # Count of units where occupied=true (calculated from units table)
    tickets_count: int = 0  # Total tickets for this property
    open_tickets_count: int = 0  # Tickets with status != "closed"
    high_priority_tickets_count: int = 0  # High priority tickets
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PropertyDetailOut(PropertyOut):
    tickets: List[TicketOut] = []
    approvals: List[ApprovalOut] = []
    units: List[UnitOut] = []  # All units for this property


class PropertyStatsOut(BaseModel):
    total_properties: int
    active_issues: int
    high_priority_issues: int
    upcoming_appointments: int
    sla_risks: int