# -*- coding: utf-8 -*-

# Import {{{
import re
import sys
import json
import time
import codecs
import subprocess
from datetime import datetime
from optparse import OptionParser
from operator import itemgetter

import lib.libraries
from lib.common import get_file_path, get_json_file
from lib.gdocs import (
    get_service_client,
    write_rows_to_worksheet,
)
from lib.xls import make_xls
# }}}

# Lovely constants.
WORKSHEET_HEADERS = ('author', 'title', 'department', 'section', 'pages', 'link')

def get_books_status(books_list, library):
    if not books_list: return

    # Get library instance.
    library = getattr(lib.libraries, 'n{0}'.format(library))(books=books_list)

    # Fetch all books status.
    books_status = library.get_books_status()

    # Sort books by deparment and section.
    books_status.sort(key=itemgetter('department', 'section'))

    return books_status

def get_worksheet_name(shelf_name):
    return '{0} {1}'.format(shelf_name.capitalize().replace('-', ' '),
                            get_today_date())

def get_today_date(): return datetime.today().strftime("%Y-%m-%d")

def get_books_list(file_name):
    file_path = get_file_path(file_name)

    books_list = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        books_list = json.load(file_handle)

    return books_list

def write_books_to_google_docs(auth_data, shelf_name, worksheet_title, books_status):
    # Fetch google_docs client.
    print("Authenticating to Google service.")
    client = get_service_client(auth_data)

    # Fetch spreadsheet params.
    books_status = [[book[header] for header in WORKSHEET_HEADERS]
                    for book in books_status]

    print("Writing books.")
    write_rows_to_worksheet(client,
                            worksheet_title,
                            get_worksheet_name(shelf_name),
                            books_status)

def write_books_to_xls(shelf_name, books_status):
    return make_xls(shelf_name,
                    get_today_date(),
                    WORKSHEET_HEADERS,
                    books_status)

def get_books_source_file(source):
    return source if re.match(r'^.*\.json$', source) else 'imogeen_%s.json' % (source)

def refresh_books_list(source, profile_id):
    return subprocess.call([
        sys.executable,
        '-tt', get_file_path('imogeen.py'),
        '-s',  source,
        '-i',  profile_id,
    ])

def main():
    # Fetch library data.
    config = get_json_file('opac.json')

    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-a", "--auth-data")

    # Add library option.
    library_choices = [*config['libraries']]
    option_parser.add_option(
        "-l",
        "--library",
        type='choice',
        choices=library_choices,
        help="Choose one of {0}".format("|".join(library_choices)),
    )

    (options, args) = option_parser.parse_args()

    # Check for library name.
    if not options.library:
        option_parser.print_help()
        exit(-1)

    # Get source file for library.
    library_data = config['libraries'][options.library]
    books_source = library_data['source']

    if options.refresh:
        print('Updating list of books from source "%s".' % books_source)
        refresh_books_list(books_source, config['profile_id'])

    books_source_file = get_books_source_file(books_source)

    # Read in books list.
    print('Reading in books list.')
    books_list = get_books_list(books_source_file)

    # Fetch books library status.
    print('Fetching {0} books library status.'.format(len(books_list)))
    books_status = get_books_status(books_list, options.library)

    # Check results list.
    if not books_status:
        print('No books from list available.')
        exit(-1)

    # Write books status.
    if options.auth_data:
        write_books_to_google_docs(options.auth_data,
                                   books_source,
                                   config['worksheet_title'],
                                   books_status)
    else:
        write_books_to_xls(books_source, books_status)

if __name__ == "__main__":
    main()
