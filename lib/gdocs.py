#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import sys
from gdata.spreadsheets.client import SpreadsheetsClient, SpreadsheetQuery, CellQuery
from gdata.spreadsheets.data import BuildBatchCellsUpdate
from oauth2client.service_account import ServiceAccountCredentials
from httplib2 import Http
# }}}

class TokenFromOAuth2Creds:
    def __init__(self, creds):
        self.creds = creds

    def modify_request(self, reqest):
        if (
            self.creds.access_token_expired or 
            not self.creds.access_token_expired
        ):
            self.creds.refresh(Http())
        self.creds.apply(reqest.headers)

def connect_to_service(auth_file):
    if not auth_file:
        return

    scope       = ['https://spreadsheets.google.com/feeds']
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        auth_file, scope
    )
    client      = SpreadsheetsClient(
        auth_token=TokenFromOAuth2Creds(credentials)
    )

    return client

def get_service_client(auth_file):
    # Connect to spreadsheet service.
    return connect_to_service(auth_file)

def get_sheet_id(sheet):
    return sheet.id.text.rsplit('/', 1)[-1] if sheet else None

def retrieve_spreadsheet_id(client, title):
    if not client:
        return

    query      = SpreadsheetQuery(title=title)
    sheet_feed = client.get_spreadsheets(query=query)

    spreadsheet_id = None
    if sheet_feed.entry:
        spreadsheet     = sheet_feed.entry[0]
        spreadsheet_id  = get_sheet_id(spreadsheet)

    return spreadsheet_id

def get_writable_worksheet(client, spreadsheet_id, worksheet_name,
                           row_count=100, col_count=20):

    # Used for name comparison.
    stdin_enc = sys.stdin.encoding

    # Get worksheet for given name.
    work_feed = client.GetWorksheets(spreadsheet_id)
    worksheet = None
    for worksheet_entry in work_feed.entry:
        worksheet_entry_name = worksheet_entry.title.text
        if worksheet_entry_name == worksheet_name:
            worksheet = worksheet_entry
            break

    # Update - delete + insert new.
    if worksheet: client.Delete(worksheet)

    # Create new worksheet.
    worksheet = client.AddWorksheet(
        spreadsheet_id,
        worksheet_name,
        row_count,
        col_count,
    )

    return worksheet

def get_writable_cells(client, spreadsheet_id, dst_worksheet,
                       return_empty='true', **kwargs):

    query = CellQuery(return_empty=return_empty, **kwargs)
    return client.GetCells(spreadsheet_id, get_sheet_id(dst_worksheet), q=query)

def write_to_cells(client, spreadsheet_id, dst_worksheet, dst_cells, rows):
    # Prepare request that will be used to update worksheet cells.
    batch_request = BuildBatchCellsUpdate(spreadsheet_id, get_sheet_id(dst_worksheet))

    # Write rows to destination worksheet.
    cell_index = 0
    for row in rows:
        # Update each destination cell.
        for value in row:
            # Get destination cell.
            dst_cell = dst_cells.entry[cell_index]
            # Update cell value.
            dst_cell.cell.input_value = value
            # Set cell for update.
            batch_request.AddBatchEntry(
                dst_cell, operation_string='update'
            )
            # Go to next cell.
            cell_index += 1

    # Execute batch update of destination cells.
    return client.batch(batch_request)

def write_rows_to_worksheet(client, spreadsheet_title, worksheet_name, rows):
    if not rows: return

    # Get worksheet id.
    spreadsheet_id = retrieve_spreadsheet_id(client, spreadsheet_title)

    # Get worksheet for writing rows.
    dst_worksheet = get_writable_worksheet(
        client,
        spreadsheet_id,
        worksheet_name,
        row_count=len(rows),
        col_count=len(rows[0])
    )

    # Get cells for Writing rows.
    dst_cells = get_writable_cells(
        client,
        spreadsheet_id,
        dst_worksheet,
    )

    write_to_cells(
        client,
        spreadsheet_id,
        dst_worksheet,
        dst_cells,
        rows
    )

