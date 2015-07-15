#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import sys
import gdata.spreadsheet.service
from gdata.service import CaptchaRequired
from lib.common import get_json_file
# }}}

def get_auth_data(file_name):

    auth_data = None
    file_data = get_json_file(file_name)
    if file_data:
        auth_data = (file_data['login'], file_data['password'])

    return auth_data

def connect_to_service(auth_data):
    if not auth_data:
        return

    # Create a client class to make HTTP requests with Google server.
    client = gdata.spreadsheet.service.SpreadsheetsService()

    # Authenticate using Google Docs email address and password.
    try:
        client.ClientLogin(*auth_data)
    except CaptchaRequired as e:
        print "Login error : %s" % (e)
        client = None

    return client

def get_service_client(auth_file):
    # Read auth data from input file.
    print(u'Fetching auth data.')
    auth_data = get_auth_data(auth_file)

    # Connect to spreadsheet service.
    print(u'Authenticating to Google service.')
    return connect_to_service(auth_data)

def retrieve_spreadsheet_id(client, title):
    if not client:
        return

    query       = gdata.spreadsheet.service.DocumentQuery()
    query.title = title
    sheet_feed  = client.GetSpreadsheetsFeed(query=query)

    spreadsheet_id = None
    if sheet_feed.entry:
        spreadsheet     = sheet_feed.entry[0]
        spreadsheet_id  = spreadsheet.id.text.rsplit('/', 1)[-1]

    return spreadsheet_id

def get_writable_worksheet(client, worksheet_name, spreadsheet_id, row_count=100, col_count=20):

    # Used for name comparison.
    stdin_enc = sys.stdin.encoding

    # Get worksheet for given name.
    work_feed = client.GetWorksheetsFeed(spreadsheet_id)
    worksheet = None
    for worksheet_entry in work_feed.entry:
        worksheet_entry_name = worksheet_entry.title.text.decode(stdin_enc)
        if worksheet_entry_name == worksheet_name:
            worksheet = worksheet_entry
            break

    # Create new worksheet when none was found.
    if not worksheet:
        worksheet = client.AddWorksheet(
            title=worksheet_name,
            # Arbitrary number of rows. Must be later adjusted to no. of hits.
            row_count=row_count,
            col_count=col_count,
            key=spreadsheet_id
        )
    # TODO: Clear worksheet.

    return worksheet

def get_writable_cells(client, dst_worksheet, spreadsheet_id, max_row=100, max_col=2):

    cell_query = gdata.spreadsheet.service.CellQuery()
    cell_query.return_empty = 'true'
    cell_query.max_row = '%d' % max_row
    cell_query.max_col = '%d' % max_col

    return client.GetCellsFeed(
        key=spreadsheet_id,
        wksht_id=dst_worksheet.id.text.rsplit('/', 1)[-1],
        query=cell_query
    )

def get_destination_cells(client, spreadsheet_title, dst_worksheet_name, entries_len):
    ssid = retrieve_spreadsheet_id(client, spreadsheet_title)

    print("Fetching destination worksheet '%s'." % dst_worksheet_name)
    dst_worksheet      = get_writable_worksheet(
        client,
        dst_worksheet_name,
        ssid,
        row_count=entries_len,
    )

    print("Fetching destination cells.")
    writable_cells = get_writable_cells(
        client,
        dst_worksheet,
        ssid,
        max_row=entries_len,
        max_col=3,
    )

