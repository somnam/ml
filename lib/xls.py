#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import xlwt
from lib.common import get_file_path
# }}}

def make_xls(file_name, worksheet_name, worksheet_headers, entries):
    if not entries: return

    # Create a new workbook.
    workbook = xlwt.Workbook()

    # Add a new sheet.
    sheet = workbook.add_sheet(worksheet_name)

    # Add headers
    for col in range(len(worksheet_headers)):
        sheet.write(0, col, worksheet_headers[col].capitalize())

    # Build rows.
    rows = []
    for entry in entries:
        row = [entry[header] for header in worksheet_headers]
        rows.append(row)

    # Format rows as text.
    cell_style = xlwt.XFStyle()
    cell_style.num_format_str = '@'

    # Write rows.
    row_i = 1
    for row in rows:
        for col_i in range(len(row)):
            sheet.write(row_i, col_i, row[col_i])
        row_i += 1

    # Write workbook.
    workbook_path = get_file_path('{0}.xls'.format(file_name))
    workbook.save(workbook_path)
