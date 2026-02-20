import logging
from pathlib import Path
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from app.core.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TICKET_SHEET_HEADERS = [
    "ID",
    "Type",
    "Issue",
    "Priority",
    "Status",
    "Assigned To",
    "Maintenance Category",
    "SLA Due At",
]


def _get_client() -> gspread.Client:
    """Build and return an authorised gspread client using the service-account JSON."""
    creds_path = Path(settings.GOOGLE_SHEETS_CREDENTIALS_FILE)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google credentials file not found at {creds_path.resolve()}"
        )
    creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    return gspread.authorize(creds)


def _get_worksheet() -> gspread.Worksheet:
    """Open the configured spreadsheet and return the target worksheet."""
    client = _get_client()
    spreadsheet = client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)
    return spreadsheet.worksheet(settings.GOOGLE_SHEETS_WORKSHEET_NAME)


def _ensure_headers(worksheet: gspread.Worksheet) -> None:
    """Add header row if the sheet is empty."""
    existing = worksheet.row_values(1)
    if not existing:
        worksheet.append_row(TICKET_SHEET_HEADERS, value_input_option="USER_ENTERED")


def _ticket_to_row(ticket) -> list:
    """Convert a ticket ORM instance into a flat list matching TICKET_SHEET_HEADERS."""
    return [
        ticket.id,
        ticket.type or "",
        ticket.issue or "",
        ticket.priority or "",
        ticket.status or "",
        ticket.assigned_to or "",
        ticket.maintenance_category or "",
        ticket.sla_due_at.isoformat() if ticket.sla_due_at else "",
    ]


def _find_row_by_ticket_id(worksheet: gspread.Worksheet, ticket_id: int) -> Optional[int]:
    """
    Search column A (the ID column) for the given ticket_id.
    Returns the 1-based row number, or None if not found.
    """
    id_column = worksheet.col_values(1)
    for idx, value in enumerate(id_column):
        if str(value) == str(ticket_id):
            return idx + 1  # gspread rows are 1-based
    return None


def append_ticket_row(ticket) -> None:
    """Append a new ticket as a row at the bottom of the sheet."""
    try:
        worksheet = _get_worksheet()
        _ensure_headers(worksheet)
        worksheet.append_row(_ticket_to_row(ticket), value_input_option="USER_ENTERED")
        logger.info("Ticket %s appended to Google Sheet", ticket.id)
    except Exception:
        logger.exception("Failed to append ticket %s to Google Sheet", ticket.id)


def update_ticket_row(ticket) -> None:
    """Find the row matching ticket.id and overwrite it with the latest data."""
    try:
        worksheet = _get_worksheet()
        row_number = _find_row_by_ticket_id(worksheet, ticket.id)
        if row_number is None:
            logger.warning("Ticket %s not found in Google Sheet — appending instead", ticket.id)
            _ensure_headers(worksheet)
            worksheet.append_row(_ticket_to_row(ticket), value_input_option="USER_ENTERED")
            return

        num_cols = len(TICKET_SHEET_HEADERS)
        cell_range = worksheet.range(row_number, 1, row_number, num_cols)
        new_values = _ticket_to_row(ticket)
        for cell, value in zip(cell_range, new_values):
            cell.value = value
        worksheet.update_cells(cell_range, value_input_option="USER_ENTERED")
        logger.info("Ticket %s updated in Google Sheet (row %s)", ticket.id, row_number)
    except Exception:
        logger.exception("Failed to update ticket %s in Google Sheet", ticket.id)


def delete_ticket_row(ticket_id: int) -> None:
    """Find the row matching ticket_id and delete it from the sheet."""
    try:
        worksheet = _get_worksheet()
        row_number = _find_row_by_ticket_id(worksheet, ticket_id)
        if row_number is None:
            logger.warning("Ticket %s not found in Google Sheet — nothing to delete", ticket_id)
            return

        worksheet.delete_rows(row_number)
        logger.info("Ticket %s deleted from Google Sheet (row %s)", ticket_id, row_number)
    except Exception:
        logger.exception("Failed to delete ticket %s from Google Sheet", ticket_id)
