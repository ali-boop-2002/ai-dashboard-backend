from pydantic import BaseModel
from typing import Optional, List


class ReportSummary(BaseModel):
    """Top cards: Total Revenue, Occupancy, Avg Resolution, Open Tickets."""
    total_revenue: float = 0.0
    total_revenue_change_pct: Optional[float] = 0.0
    occupancy_rate_pct: float = 0.0
    occupancy_display: str = "0 of 0 units occupied"
    avg_resolution_days: float = 0.0
    avg_resolution_change_pct: Optional[float] = 0.0
    open_tickets_count: int = 0
    overdue_tickets_count: int = 0


class RevenueExpensePoint(BaseModel):
    """Single point in revenue/expense trend chart."""
    month: str
    revenue: float = 0.0
    expenses: float = 0.0


class MaintenanceBreakdownItem(BaseModel):
    """Maintenance cost by category."""
    category: str
    amount: float = 0.0
    percentage: float = 0.0


class TicketsByCategoryItem(BaseModel):
    """Tickets grouped by type."""
    category: str
    ticket_count: int = 0
    avg_resolution_days: float = 0.0


class PropertyPerformanceItem(BaseModel):
    """Per-unit property performance row."""
    property_name: str
    occupancy_pct: float = 0.0
    revenue: float = 0.0
    maintenance_cost: float = 0.0
    issues: int = 0


class TechnicianPerformanceItem(BaseModel):
    """Technician stats."""
    technician: str
    tickets: int = 0
    completed: int = 0
    overdue: int = 0
    avg_days: float = 0.0


class OutstandingPaymentItem(BaseModel):
    """Outstanding payment row."""
    tenant_label: str
    amount_due: float = 0.0
    status: str
    days_overdue: Optional[int] = None


class TenantAnalyticsItem(BaseModel):
    """Tenant/unit analytics row."""
    unit_label: str
    maintenance_requests: int = 0
    late_payments: int = 0
    avg_resolution_days: float = 0.0


class ReportAnalyticsOut(BaseModel):
    """Full reports & analytics response."""
    summary: ReportSummary = ReportSummary()
    revenue_expense_trend: List[RevenueExpensePoint] = []
    maintenance_cost_breakdown: List[MaintenanceBreakdownItem] = []
    tickets_by_category: List[TicketsByCategoryItem] = []
    property_performance: List[PropertyPerformanceItem] = []
    technician_performance: List[TechnicianPerformanceItem] = []
    outstanding_payments: List[OutstandingPaymentItem] = []
    tenant_analytics: List[TenantAnalyticsItem] = []
