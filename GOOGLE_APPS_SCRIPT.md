# Google Apps Script Setup for Sheet-to-Ticket Sync

This script automatically creates tickets in your Supabase database when you add a new row to the Google Sheet.

## Step 1: Open Google Apps Script Editor

1. Open your Google Sheet: https://docs.google.com/spreadsheets/d/1DcSCddZxIic8c6AOfkrgwJWOPpjAqY0R7TQMgHgBeJ0/edit
2. Click **Extensions** → **Apps Script**
3. A new tab will open with the Apps Script editor

## Step 2: Paste the Script

Delete any existing code in the editor and paste the entire script below:

```javascript
// Configuration
const API_URL = "https://ai-automated-dashboard-69e6e6b125d9.herokuapp.com/tickets/from-sheet";
const SHEET_NAME = "Sheet1";
const HEADERS_ROW = 1;

// Column indices (0-based)
const COLUMNS = {
  ID: 0,
  PROPERTY_ID: 1,
  TYPE: 2,
  ISSUE: 3,
  PRIORITY: 4,
  STATUS: 5,
  ASSIGNED_TO: 6,
  MAINTENANCE_CATEGORY: 7,
  SLA_DUE_AT: 8,
  SOURCE: 9
};

function onEdit(e) {
  // Only process the target sheet
  if (e.source.getActiveSheet().getName() !== SHEET_NAME) {
    return;
  }

  const range = e.range;
  const row = range.getRow();

  // Skip header row
  if (row === HEADERS_ROW) {
    return;
  }

  // Get the sheet and row data
  const sheet = e.source.getActiveSheet();
  const rowData = sheet.getRange(row, 1, 1, 10).getValues()[0];

  // Check if the Source column is empty (meaning it was manually added, not from API)
  const sourceValue = rowData[COLUMNS.SOURCE];
  if (sourceValue && sourceValue.trim() !== "") {
    // Already processed or created by API
    return;
  }

  // Extract values from the row
  const propertyId = rowData[COLUMNS.PROPERTY_ID];
  const type = rowData[COLUMNS.TYPE];
  const issue = rowData[COLUMNS.ISSUE];
  const priority = rowData[COLUMNS.PRIORITY] || "medium";
  const status = rowData[COLUMNS.STATUS] || "open";
  const assignedTo = rowData[COLUMNS.ASSIGNED_TO] || null;
  const maintenanceCategory = rowData[COLUMNS.MAINTENANCE_CATEGORY] || null;
  const slaDueAt = rowData[COLUMNS.SLA_DUE_AT] || null;

  // Validate required fields
  if (!propertyId || !type || !issue) {
    Logger.log("Row " + row + ": Missing required fields (property_id, type, or issue)");
    return;
  }

  // Build the payload
  const payload = {
    property_id: parseInt(propertyId),
    type: type,
    issue: issue,
    priority: priority,
    status: status,
    assigned_to: assignedTo || null,
    maintenance_category: maintenanceCategory || null,
    sla_due_at: slaDueAt ? new Date(slaDueAt).toISOString() : null
  };

  // Send to the API
  try {
    const options = {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(API_URL, options);
    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      // Success! Mark the Source column as "Sheet"
      const ticketIdCell = sheet.getRange(row, COLUMNS.ID + 1);
      const sourceCell = sheet.getRange(row, COLUMNS.SOURCE + 1);
      
      const responseData = JSON.parse(response.getContentText());
      ticketIdCell.setValue(responseData.id);
      sourceCell.setValue("Sheet");
      
      Logger.log("Row " + row + ": Successfully created ticket ID " + responseData.id);
    } else {
      const error = response.getContentText();
      Logger.log("Row " + row + ": API Error " + responseCode + " - " + error);
    }
  } catch (error) {
    Logger.log("Row " + row + ": Error - " + error.toString());
  }
}

function doPost(e) {
  // Optional: Handle direct webhook calls if needed
  return ContentService.createTextOutput("OK");
}
```

## Step 3: Save the Script

1. Press **Ctrl+S** (or **Cmd+S** on Mac)
2. Give it a name like "Sheet-to-Ticket Sync"
3. Click **Save**

## Step 4: Test It

1. Go back to your Google Sheet
2. Add a new row with test data:
   - **Property ID**: 1 (or a valid property ID from your database)
   - **Type**: maintenance
   - **Issue**: Test issue from sheet
   - **Priority**: high
   - **Status**: open
   - Leave ID and Source empty initially

3. As soon as you edit the cells, the script will trigger and:
   - Send the data to your backend API
   - Automatically fill in the ID column with the ticket ID
   - Mark the Source column as "Sheet"

## How It Works

1. **Trigger**: When any cell in the sheet is edited, the `onEdit(e)` function runs
2. **Validation**: Checks if this is a new row (Source column is empty)
3. **Extract**: Pulls property_id, type, issue, priority, etc. from the row
4. **Send**: POSTs the data to `/tickets/from-sheet` endpoint
5. **Update**: Once successful, fills in the ticket ID and marks Source as "Sheet"

## Column Reference

| Column | Field | Required? | Example |
|--------|-------|-----------|---------|
| A | ID | Auto-filled | (empty at first) |
| B | Property ID | Yes | 1 |
| C | Type | Yes | maintenance |
| D | Issue | Yes | Broken pipe |
| E | Priority | No | high |
| F | Status | No | open |
| G | Assigned To | No | John Doe |
| H | Maintenance Category | No | plumbing |
| I | SLA Due At | No | 2026-02-20T20:50:00 |
| J | Source | Auto-filled | (empty or "Sheet" after sync) |

## Troubleshooting

- **Script doesn't run?** Make sure you saved it and are editing the correct sheet
- **API Error 422?** Check your property_id — it must be a valid ID that exists in your database
- **API Error 403/401?** The endpoint is unauthenticated, so this shouldn't happen. Contact support if it does
- **Check logs**: In the Apps Script editor, click **Execution log** to see what happened

## Notes

- The first time you use this, Google will ask for permission to make external requests. Click **Allow**.
- Once a row has Source = "Sheet", it won't process again (prevents duplicates)
- If the API fails, the row stays unchanged and you can see the error in the logs
