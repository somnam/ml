# -*- coding: utf-8 -*-

# Import {{{
import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound
from oauth2client.service_account import ServiceAccountCredentials
# }}}

def get_service_client(auth):
    if not auth: return

    credentials = ServiceAccountCredentials.from_json_keyfile_name(auth, [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive',
    ])
    return gspread.authorize(credentials)

def get_writable_worksheet(client, workbook_title, worksheet_title, rows_n, cols_n):
    if not client: return

    try:
        workbook = client.open(workbook_title)
    except SpreadsheetNotFound:
        workbook = client.create(title=workbook_title)

    try:
        worksheet = workbook.worksheet(title=worksheet_title)
    except WorksheetNotFound:
        # Create new worksheet.
        worksheet = workbook.add_worksheet(title=worksheet_title, rows=rows_n, cols=cols_n)
    else:
        # Clear existing worksheet
        worksheet.clear()
        # Check if all rows will fit.
        if ((rows_n - worksheet.row_count) or (cols_n - worksheet.col_count)):
            worksheet.resize(rows=rows_n, cols=cols_n)
            # Fetch updated worksheet after resizing.
            worksheet = workbook.worksheet(title=worksheet.title)

    return worksheet

def write_to_cells(worksheet, rows):
    if not(worksheet and rows): return

    # Get cells for writing rows.
    cells = worksheet.range(1, 1, worksheet.row_count, worksheet.col_count)

    # Update each destination cell.
    cell_index = 0
    for row in rows:
        for value in row:
            cells[cell_index].value = value
            cell_index += 1

    # Execute batch update of destination cells.
    worksheet.update_cells(cells)

def write_rows_to_worksheet(client, workbook_title, worksheet_title, rows):
    if not(client and rows): return

    worksheet = get_writable_worksheet(
        client, workbook_title, worksheet_title, len(rows), len(rows[0])
    )
    write_to_cells(worksheet, rows)
