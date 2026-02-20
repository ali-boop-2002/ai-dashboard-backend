"""
Reports & Analytics endpoint.
Returns aggregated data for the Reports & Analytics dashboard.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.api.deps import get_db
from app.models.property import Property
from app.models.unit import Unit
from app.models.ticket import Ticket
from app.models.approval import Approval
from app.models.rent_payments import RentPayment

from app.schemas.report import (
    ReportAnalyticsOut,
    ReportSummary,
    RevenueExpensePoint,
    MaintenanceBreakdownItem,
    TicketsByCategoryItem,
    PropertyPerformanceItem,
    TechnicianPerformanceItem,
    OutstandingPaymentItem,
    TenantAnalyticsItem,
)
from app.core.auth import get_current_user, User

router = APIRouter(prefix="/reports", tags=["reports"])


def _get_base_ticket_query(db: Session, property_id: Optional[int], technician: Optional[str]):
    """Base ticket query with optional filters."""
    q = db.query(Ticket)
    if property_id is not None:
        q = q.filter(Ticket.property_id == property_id)
    if technician is not None:
        q = q.filter(Ticket.assigned_to == technician)
    return q


def _get_base_unit_query(db: Session, property_id: Optional[int]):
    """Base unit query with optional property filter."""
    q = db.query(Unit)
    if property_id is not None:
        q = q.filter(Unit.property_id == property_id)
    return q


def _get_base_property_query(db: Session, property_id: Optional[int]):
    """Base property query with optional filter."""
    q = db.query(Property)
    if property_id is not None:
        q = q.filter(Property.id == property_id)
    return q


def _compute_days_overdue(rent_date) -> Optional[int]:
    """Compute days overdue from rent_date to today UTC. Returns None if not overdue or no date."""
    if rent_date is None:
        return None
    today = datetime.now(timezone.utc).date()
    rd = rent_date.date() if hasattr(rent_date, "date") else rent_date
    if rd >= today:
        return None
    return (today - rd).days


def _status_bucket(days_overdue: Optional[int], occupied: bool, paid: bool) -> str:
    """Return status string for outstanding payments."""
    if paid:
        return "Paid"
    if not occupied:
        return "Vacant"
    if days_overdue is None or days_overdue < 10:
        return "1-10 days" if days_overdue and days_overdue > 0 else "Current"
    if days_overdue <= 30:
        return "10-30 days"
    return "30+ days"


def _build_analytics(
    db: Session,
    start_date: Optional[str],
    end_date: Optional[str],
    property_id: Optional[int],
    technician: Optional[str],
) -> ReportAnalyticsOut:
    """
    Shared logic: build the full ReportAnalyticsOut object.
    Called by the JSON, CSV, and PDF endpoints.
    """
    # Parse date range or default to last 3 months
    now = datetime.now(timezone.utc)
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            end_dt = now
    else:
        end_dt = now

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            start_dt = end_dt - timedelta(days=90)
    else:
        start_dt = end_dt - timedelta(days=90)

    # --- Summary ---
    unit_q = _get_base_unit_query(db, property_id)
    # Total revenue in selected range comes from RentPayment history (NOT current Unit state)
    rev_total_q = db.query(func.coalesce(func.sum(RentPayment.amount), 0)).filter(
        RentPayment.status == "paid",
        RentPayment.period_start >= start_dt.date(),
        RentPayment.period_start <= end_dt.date(),
    )
    if property_id is not None:
        rev_total_q = rev_total_q.filter(RentPayment.property_id == property_id)

    total_revenue = float(rev_total_q.scalar() or 0.0)

    prop_q = _get_base_property_query(db, property_id)
    total_units_result = prop_q.with_entities(
        func.sum(Property.total_units).label("total"),
        func.count(Property.id).label("count"),
    ).first()
    total_units = int(total_units_result[0] or 0) if total_units_result else 0

    occupied_count = (
        _get_base_unit_query(db, property_id)
        .filter(Unit.occupied == True)
        .count()
    )

    # fix what happens with dates like if someone wants to see for last month or last year or last 90 days
    occupancy_pct = (occupied_count / total_units * 100) if total_units > 0 else 0.0
    occupancy_display = f"{occupied_count} of {total_units} units occupied"

    ticket_q = _get_base_ticket_query(db, property_id, technician)
    closed_tickets = ticket_q.filter(Ticket.status == "closed")
    avg_res = (
        closed_tickets.with_entities(
            func.avg(
                extract("epoch", Ticket.updated_at) - extract("epoch", Ticket.created_at)
            ).label("avg_seconds"),
        ).scalar()
    )
    avg_resolution_days = (float(avg_res) / 86400.0) if avg_res is not None else 0.0

    open_count = ticket_q.filter(Ticket.status != "closed").count()
    overdue_count = (
        ticket_q.filter(Ticket.status != "closed")
        .filter(Ticket.sla_due_at.isnot(None))
        .filter(Ticket.sla_due_at < now)
        .count()
    )

    summary = ReportSummary(
        total_revenue=total_revenue,
        total_revenue_change_pct=0.0,
        occupancy_rate_pct=round(occupancy_pct, 1),
        occupancy_display=occupancy_display,
        avg_resolution_days=round(avg_resolution_days, 1),
        avg_resolution_change_pct=0.0,
        open_tickets_count=open_count,
        overdue_tickets_count=overdue_count,
    )

    # --- Revenue & Expense Trend ---
    months: List[RevenueExpensePoint] = []
    current = start_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    #month_revenue = total_revenue / max(1, (end_dt - start_dt).days / 30) if (end_dt - start_dt).days > 0 else total_revenue
    #"here so far so good"/ fix here it shows revenue by dividing one number across all the days in the range which is not correct
    #each month should have its own revenue
    while current <= end_dt:
        month_start = current
        month_end = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(seconds=1)
        if month_end > end_dt:
            month_end = end_dt

        exp_q = db.query(func.coalesce(func.sum(Approval.amount), 0)).filter(
            Approval.status == "approved",
            func.coalesce(Approval.updated_at, Approval.created_at) >= month_start,
            func.coalesce(Approval.updated_at, Approval.created_at) <= month_end,
        )
        if property_id is not None:
            exp_q = exp_q.filter(Approval.property_id == property_id)
        expenses = float(exp_q.scalar() or 0)

        # Revenue for this month comes from RentPayment history.
        rev_q = db.query(func.coalesce(func.sum(RentPayment.amount), 0)).filter(
            RentPayment.status == "paid",
            RentPayment.period_start >= month_start.date(),
            RentPayment.period_start <= month_end.date(),
        )
        if property_id is not None:
            rev_q = rev_q.filter(RentPayment.property_id == property_id)
        revenue = float(rev_q.scalar() or 0.0)

        months.append(
            RevenueExpensePoint(
                month=current.strftime("%b %Y"),
                revenue=round(revenue, 2),
                expenses=round(expenses, 2),
            )
        )
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # --- Maintenance Cost Breakdown ---
    maint_q = (
        db.query(
            func.coalesce(Ticket.maintenance_category, "other").label("category"),
            func.sum(Approval.amount).label("amount"),
        )
        .join(Approval, Approval.ticket_id == Ticket.id)
        .filter(Approval.status == "approved")
        .filter(Ticket.type == "maintenance")
    )
    if property_id is not None:
        maint_q = maint_q.filter(Ticket.property_id == property_id)
    if technician is not None:
        maint_q = maint_q.filter(Ticket.assigned_to == technician)

    maint_rows = maint_q.group_by(func.coalesce(Ticket.maintenance_category, "other")).all()
    total_maint = sum(float(r[1] or 0) for r in maint_rows)
    maintenance_breakdown = [
        MaintenanceBreakdownItem(
            category=r[0] or "other",
            amount=round(float(r[1] or 0), 2),
            percentage=round((float(r[1] or 0) / total_maint * 100), 1) if total_maint > 0 else 0,
        )
        for r in maint_rows
    ]

    ##here so far so good

    # --- Tickets by Category ---
    cat_q = (
        db.query(
            Ticket.type,
            func.count(Ticket.id).label("cnt"),
            func.avg(
                extract("epoch", Ticket.updated_at) - extract("epoch", Ticket.created_at)
            ).label("avg_sec"),
        )
        .filter(Ticket.status == "closed")
    )
    if property_id is not None:
        cat_q = cat_q.filter(Ticket.property_id == property_id)
    if technician is not None:
        cat_q = cat_q.filter(Ticket.assigned_to == technician)
    cat_rows = cat_q.group_by(Ticket.type).all()

    tickets_by_category = [
        TicketsByCategoryItem(
            category=r[0],
            ticket_count=int(r[1] or 0),
            avg_resolution_days=round(float(r[2] or 0) / 86400.0, 1),
        )
        for r in cat_rows
    ]

    # Also include categories with 0 tickets
    all_types = {"maintenance", "complaint", "refund", "task"}
    seen = {t.category for t in tickets_by_category}
    for t in all_types:
        if t not in seen:
            tickets_by_category.append(TicketsByCategoryItem(category=t, ticket_count=0, avg_resolution_days=0.0))

    # --- Property Performance ---
    props = _get_base_property_query(db, property_id).all()
    property_performance: List[PropertyPerformanceItem] = []
    for prop in props:
        prop_revenue = (
            db.query(func.coalesce(func.sum(Unit.rent_amount), 0))
            .filter(Unit.property_id == prop.id)
            .filter(Unit.occupied == True)
            .scalar()
        )
        prop_revenue = float(prop_revenue or 0)
        prop_approvals = (
            db.query(func.coalesce(func.sum(Approval.amount), 0))
            .filter(Approval.property_id == prop.id)
            .filter(Approval.status == "approved")
            .scalar()
        )
        prop_maintenance = float(prop_approvals or 0)
        prop_tickets = db.query(Ticket).filter(Ticket.property_id == prop.id).count()

        units = db.query(Unit).filter(Unit.property_id == prop.id).all()
        if units:
            unit_revenue = sum(float(u.rent_amount or 0) for u in units if u.occupied)
            occupied_count = sum(1 for u in units if u.occupied)
            occ_pct = (occupied_count / len(units) * 100)
            property_performance.append(
                PropertyPerformanceItem(
                    property_name=prop.name,

                    occupancy_pct=round(occ_pct, 1),
                    revenue=round(unit_revenue, 2),
                    maintenance_cost=round(prop_maintenance / len(units), 2),
                    issues=prop_tickets,
                )
            )
        else:
            property_performance.append(
                PropertyPerformanceItem(
                    property_name=prop.name,
                    unit_label="N/A",
                    occupancy_pct=0,
                    revenue=0,
                    maintenance_cost=prop_maintenance,
                    issues=prop_tickets,
                )
            )

    # --- Technician Performance ---
    tech_q = (
        db.query(Ticket.assigned_to)
        .filter(Ticket.assigned_to.isnot(None))
        .filter(Ticket.assigned_to != "")
        .distinct()
    )
    if property_id is not None:
        tech_q = tech_q.filter(Ticket.property_id == property_id)
    if technician is not None:
        tech_q = tech_q.filter(Ticket.assigned_to == technician)
    tech_names = [r[0] for r in tech_q.all()]

    technician_performance: List[TechnicianPerformanceItem] = []
    for name in tech_names:
        tq = db.query(Ticket).filter(Ticket.assigned_to == name)
        if property_id is not None:
            tq = tq.filter(Ticket.property_id == property_id)
        tickets_list = tq.all()
        total_t = len(tickets_list)
        completed = sum(1 for t in tickets_list if t.status == "closed")
        overdue = sum(
            1
            for t in tickets_list
            if t.status != "closed" and t.sla_due_at and t.sla_due_at < now
        )
        closed = [t for t in tickets_list if t.status == "closed"]
        avg_d = 0.0
        if closed:
            total_sec = sum(
                (t.updated_at - t.created_at).total_seconds() if t.updated_at and t.created_at else 0
                for t in closed
            )
            avg_d = total_sec / 86400.0 / len(closed)
        technician_performance.append(
            TechnicianPerformanceItem(
                technician=name,
                tickets=total_t,
                completed=completed,
                overdue=overdue,
                avg_days=round(avg_d, 1),
            )
        )

    # --- Outstanding Payments ---
    units_outstanding = _get_base_unit_query(db, property_id).all()
    outstanding_payments: List[OutstandingPaymentItem] = []
    for u in units_outstanding:
        prop = db.query(Property).filter(Property.id == u.property_id).first()
        prop_name = prop.name if prop else f"Property {u.property_id}"
        label = f"{prop_name} Unit {u.unit_number}"
        amt = 0.0 if u.paid else float(u.rent_amount or 0)
        days = _compute_days_overdue(u.rent_date) if not u.paid and u.occupied else None
        status = _status_bucket(days, u.occupied, u.paid)
        outstanding_payments.append(
            OutstandingPaymentItem(
                tenant_label=label,
                amount_due=round(amt, 2),
                status=status,
                days_overdue=days,
            )
        )

    # --- Tenant Analytics --- (single aggregated item across all units)
    property_ids = list({u.property_id for u in units_outstanding})
    total_maintenance = (
        db.query(Approval).filter(Approval.property_id.in_(property_ids)).count() if property_ids else 0
    )
    total_late = 0
    resolution_seconds: List[float] = []
    for u in units_outstanding:
        if u.occupied and not u.paid and _compute_days_overdue(u.rent_date):
            total_late += 1
        closed_t = (
            db.query(Ticket)
            .filter(Ticket.property_id == u.property_id)
            .filter(Ticket.status == "closed")
            .all()
        )
        for t in closed_t:
            if t.updated_at and t.created_at:
                resolution_seconds.append((t.updated_at - t.created_at).total_seconds())
    avg_res = sum(resolution_seconds) / 86400.0 / len(resolution_seconds) if resolution_seconds else 0.0
    prop_name = db.query(Property).filter(Property.id == property_id).first().name if property_id else "All Properties"
    tenant_analytics = [
        TenantAnalyticsItem(
            unit_label=prop_name,
            maintenance_requests=total_maintenance,
            late_payments=total_late,
            avg_resolution_days=round(avg_res, 1),
        )
    ]


    return ReportAnalyticsOut(
        summary=summary,
        revenue_expense_trend=months,
        maintenance_cost_breakdown=maintenance_breakdown,
        tickets_by_category=tickets_by_category,
        property_performance=property_performance,
        technician_performance=technician_performance,
        outstanding_payments=outstanding_payments,
        tenant_analytics=tenant_analytics,
    )


@router.get("/analytics", response_model=ReportAnalyticsOut)
def get_reports_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    property_id: Optional[int] = Query(None, description="Filter by property ID"),
    technician: Optional[str] = Query(None, description="Filter by technician name (assigned_to)"),
):
    """Reports & Analytics: aggregated metrics, charts, and tables (JSON)."""
    return _build_analytics(db, start_date, end_date, property_id, technician)


# ---------------------------------------------------------------------------
# CSV download
# ---------------------------------------------------------------------------

@router.get("/analytics/csv")
def download_reports_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    property_id: Optional[int] = Query(None, description="Filter by property ID"),
    technician: Optional[str] = Query(None, description="Filter by technician name (assigned_to)"),
):
    """Download the reports analytics data as a CSV file."""
    data = _build_analytics(db, start_date, end_date, property_id, technician)
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Summary
    writer.writerow(["--- Summary ---"])
    writer.writerow(["Total Revenue", "Occupancy Rate", "Avg Resolution Days", "Open Tickets", "Overdue Tickets"])
    s = data.summary
    writer.writerow([s.total_revenue, f"{s.occupancy_rate_pct}%", s.avg_resolution_days, s.open_tickets_count, s.overdue_tickets_count])
    writer.writerow([])

    # Revenue & Expense Trend
    writer.writerow(["--- Revenue & Expense Trend ---"])
    writer.writerow(["Month", "Revenue", "Expenses"])
    for r in data.revenue_expense_trend:
        writer.writerow([r.month, r.revenue, r.expenses])
    writer.writerow([])

    # Maintenance Cost Breakdown
    writer.writerow(["--- Maintenance Cost Breakdown ---"])
    writer.writerow(["Category", "Amount", "Percentage"])
    for m in data.maintenance_cost_breakdown:
        writer.writerow([m.category, m.amount, f"{m.percentage}%"])
    writer.writerow([])

    # Tickets by Category
    writer.writerow(["--- Tickets by Category ---"])
    writer.writerow(["Category", "Ticket Count", "Avg Resolution Days"])
    for t in data.tickets_by_category:
        writer.writerow([t.category, t.ticket_count, t.avg_resolution_days])
    writer.writerow([])

    # Property Performance
    writer.writerow(["--- Property Performance ---"])
    writer.writerow(["Property", "Occupancy %", "Revenue", "Maintenance Cost", "Issues"])
    for p in data.property_performance:
        writer.writerow([p.property_name, f"{p.occupancy_pct}%", p.revenue, p.maintenance_cost, p.issues])
    writer.writerow([])

    # Technician Performance
    writer.writerow(["--- Technician Performance ---"])
    writer.writerow(["Technician", "Tickets", "Completed", "Overdue", "Avg Days"])
    for tp in data.technician_performance:
        writer.writerow([tp.technician, tp.tickets, tp.completed, tp.overdue, tp.avg_days])
    writer.writerow([])

    # Outstanding Payments
    writer.writerow(["--- Outstanding Payments ---"])
    writer.writerow(["Tenant", "Amount Due", "Status", "Days Overdue"])
    for op in data.outstanding_payments:
        writer.writerow([op.tenant_label, op.amount_due, op.status, op.days_overdue or ""])
    writer.writerow([])

    # Tenant Analytics
    writer.writerow(["--- Tenant Analytics ---"])
    writer.writerow(["Label", "Maintenance Requests", "Late Payments", "Avg Resolution Days"])
    for ta in data.tenant_analytics:
        writer.writerow([ta.unit_label, ta.maintenance_requests, ta.late_payments, ta.avg_resolution_days])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=report.csv"},
    )


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------

def _pdf_section_title(pdf, title: str):
    """Add a styled section title to the PDF."""
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(41, 128, 185)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def _pdf_table(pdf, headers: List[str], rows: List[List[str]]):
    """Draw a simple table with alternating row shading."""
    col_count = len(headers)
    page_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = page_w / col_count

    # Header row
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(220, 220, 220)
    for h in headers:
        pdf.cell(col_w, 7, str(h), border=1, fill=True)
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 9)
    for i, row in enumerate(rows):
        if i % 2 == 0:
            pdf.set_fill_color(245, 245, 245)
        else:
            pdf.set_fill_color(255, 255, 255)
        for val in row:
            pdf.cell(col_w, 6, str(val), border=1, fill=True)
        pdf.ln()
    pdf.ln(4)


@router.get("/analytics/pdf")
def download_reports_pdf(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    property_id: Optional[int] = Query(None, description="Filter by property ID"),
    technician: Optional[str] = Query(None, description="Filter by technician name (assigned_to)"),
):
    """Download the reports analytics data as a PDF file."""
    from fpdf import FPDF

    data = _build_analytics(db, start_date, end_date, property_id, technician)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Reports & Analytics", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    date_label = f"{start_date or 'last 90 days'} to {end_date or 'today'}"
    filters = []
    if property_id:
        filters.append(f"Property: {property_id}")
    if technician:
        filters.append(f"Technician: {technician}")
    subtitle = date_label + (f"  |  {', '.join(filters)}" if filters else "")
    pdf.cell(0, 6, subtitle, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Summary
    _pdf_section_title(pdf, "Summary")
    s = data.summary
    _pdf_table(
        pdf,
        ["Total Revenue", "Occupancy", "Avg Resolution", "Open Tickets", "Overdue"],
        [[f"${s.total_revenue:,.2f}", f"{s.occupancy_rate_pct}%", f"{s.avg_resolution_days} days", str(s.open_tickets_count), str(s.overdue_tickets_count)]],
    )

    # Revenue & Expense Trend
    _pdf_section_title(pdf, "Revenue & Expense Trend")
    _pdf_table(
        pdf,
        ["Month", "Revenue", "Expenses"],
        [[r.month, f"${r.revenue:,.2f}", f"${r.expenses:,.2f}"] for r in data.revenue_expense_trend],
    )

    # Maintenance Cost Breakdown
    if data.maintenance_cost_breakdown:
        _pdf_section_title(pdf, "Maintenance Cost Breakdown")
        _pdf_table(
            pdf,
            ["Category", "Amount", "Percentage"],
            [[m.category, f"${m.amount:,.2f}", f"{m.percentage}%"] for m in data.maintenance_cost_breakdown],
        )

    # Tickets by Category
    _pdf_section_title(pdf, "Tickets by Category")
    _pdf_table(
        pdf,
        ["Category", "Count", "Avg Resolution"],
        [[t.category, str(t.ticket_count), f"{t.avg_resolution_days} days"] for t in data.tickets_by_category],
    )

    # Property Performance
    _pdf_section_title(pdf, "Property Performance")
    _pdf_table(
        pdf,
        ["Property", "Occupancy", "Revenue", "Maint. Cost", "Issues"],
        [[p.property_name, f"{p.occupancy_pct}%", f"${p.revenue:,.2f}", f"${p.maintenance_cost:,.2f}", str(p.issues)] for p in data.property_performance],
    )

    # Technician Performance
    if data.technician_performance:
        _pdf_section_title(pdf, "Technician Performance")
        _pdf_table(
            pdf,
            ["Technician", "Tickets", "Completed", "Overdue", "Avg Days"],
            [[tp.technician, str(tp.tickets), str(tp.completed), str(tp.overdue), str(tp.avg_days)] for tp in data.technician_performance],
        )

    # Outstanding Payments
    _pdf_section_title(pdf, "Outstanding Payments")
    _pdf_table(
        pdf,
        ["Tenant", "Amount Due", "Status", "Days Overdue"],
        [[op.tenant_label, f"${op.amount_due:,.2f}", op.status, str(op.days_overdue or "-")] for op in data.outstanding_payments],
    )

    # Tenant Analytics
    if data.tenant_analytics:
        _pdf_section_title(pdf, "Tenant Analytics")
        _pdf_table(
            pdf,
            ["Label", "Maint. Requests", "Late Payments", "Avg Resolution"],
            [[ta.unit_label, str(ta.maintenance_requests), str(ta.late_payments), f"{ta.avg_resolution_days} days"] for ta in data.tenant_analytics],
        )

    pdf_bytes = pdf.output()
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=report.pdf"},
    )
