#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from lib.common import get_file_path
# }}}

def make_xls(file_name, worksheet_name, worksheet_headers, entries):
    if not entries: return

    # Create a new workbook.
    workbook = Workbook()

    # Add a new sheet.
    sheet = workbook.active
    sheet.title = worksheet_name

    # Add headers
    sheet.append([header.capitalize() for header in worksheet_headers])

    # Colum widths will be stored here
    column_widths = [10 for _ in worksheet_headers]
    no_newlie_re  = re.compile(r'^[^\n]*$')
    len_lambda    = lambda e: len(e)
    # Add rows
    for entry in entries:
        row = []
        for index, header in enumerate(worksheet_headers):
            entry_value = entry[header]
            # Don't process empty values.
            if entry_value is None:
                row.append(None)
                continue

            # Calculate entry length.
            if no_newlie_re.match(entry_value):
                entry_length = len(entry_value)
            else:
                entry_length = len(max(entry_value.split(u"\n"), key=len_lambda))

            # Adjust column width according to text length.
            if entry_length > column_widths[index]:
                column_widths[index] = entry_length

            row.append(entry_value)

        sheet.append(row)

    # Set column dimensions.
    for index in range(len(worksheet_headers)):
        # Worksheet indices start from 1.
        column_letter     = get_column_letter(index+1)
        column_dimensions = sheet.column_dimensions[column_letter]

        column_dimensions.width = column_widths[index]

    # Write workbook.
    workbook_path = get_file_path('{0}.xls'.format(file_name))
    workbook.save(workbook_path)

def open_workbook(file_name):
    if not file_name:
        return None, u'Please provide a correct xls file.'

    workbook, error = None, None
    try:
        workbook_path = get_file_path(file_name)
        workbook      = load_workbook(workbook_path)
    except (IOError, InvalidFileException) as e:
        message = e.strerror if hasattr(e, 'strerror') else e.message
        error   = u'Error: {0}'.format(message)

    return workbook, error

def save_workbook(workbook, file_name):
    workbook_path = get_file_path(file_name)
    workbook.save(workbook_path)
