#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import sys
from gdata.spreadsheets.client import SpreadsheetsClient, SpreadsheetQuery, CellQuery
from gdata.spreadsheets.data import BuildBatchCellsUpdate
from oauth2client.client import SignedJwtAssertionCredentials
from httplib2 import Http
from lib.common import get_json_file
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

def get_auth_data(file_name):
    return get_json_file(file_name)

def connect_to_service(auth_data):
    if not auth_data:
        return

    scope       = ['https://spreadsheets.google.com/feeds']
    credentials = SignedJwtAssertionCredentials(
        auth_data['client_email'], auth_data['private_key'], scope
    )
    client      = SpreadsheetsClient(
        auth_token=TokenFromOAuth2Creds(credentials)
    )

    return client

def get_service_client(auth_file):
    # Read auth data from input file.
    auth_data = get_auth_data(auth_file)

    # Connect to spreadsheet service.
    return connect_to_service(auth_data)

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
        # Arbitrary number of rows. Must be later adjusted to no. of hits.
        row_count,
        col_count,
    )

    return worksheet

def get_destination_cells(client, spreadsheet_id, dst_worksheet):
    return get_writable_cells(client, spreadsheet_id, dst_worksheet)

def get_writable_cells(client, spreadsheet_id, dst_worksheet,
                       return_empty='true', max_col=2):

    query = CellQuery(return_empty=return_empty, max_col=max_col)
    return client.GetCells(spreadsheet_id, get_sheet_id(dst_worksheet), q=query)

def write_to_cells(client, spreadsheet_id, dst_worksheet, dst_cells, rows):
    # Prepare request that will be used to update worksheet cells.
    batch_request = BuildBatchCellsUpdate(spreadsheet_id, get_sheet_id(dst_worksheet))

    # Write rows to destination worksheet.
    cell_index = 0
    for row in rows:
        # Update each destination cell.
        for cell in row:
            # Get destination cell.
            dst_cell = dst_cells.entry[cell_index]
            # Update cell value.
            dst_cell.cell.input_value = cell.cell.input_value
            # Set cell for update.
            batch_request.AddBatchEntry(dst_cell, operation_string='update')
            # Go to next cell.
            cell_index += 1

    # Execute batch update of destination cells.
    return client.batch(batch_request)

def write_rows_to_worksheet(client, spreadsheet_id, worksheet_name, rows):
    rows_len = len(rows)

    # Get worksheet for writing rows.
    dst_worksheet = get_writable_worksheet(
        client,
        spreadsheet_id,
        worksheet_name,
        rows_len
    )

    # Get cells for Writing rows.
    dst_cells = get_destination_cells(
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

