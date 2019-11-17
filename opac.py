# Import {{{
import re
import sys
import json
import codecs
import subprocess
from datetime import datetime
from optparse import OptionParser

import lib.libraries
from lib.config import Config
from lib.common import get_file_path
from lib.gdocs import (
    get_service_client,
    write_rows_to_worksheet,
)
from lib.xls import make_xls
# }}}

# Lovely constants.
WORKSHEET_HEADERS = ('author', 'title', 'department', 'section', 'pages',
                     'link')


def get_books_status(books_list, library):
    if not books_list:
        return

    # Get library instance.
    library = getattr(lib.libraries, f'Library{library}')(books=books_list)

    # # Fetch all books status.
    books_status = library.run()

    return books_status


def get_worksheet_name(shelf_name):
    return '{0} {1}'.format(shelf_name, get_today_date())


def get_today_date():
    return datetime.today().strftime("%Y-%m-%d")


def get_books_list(file_name):
    file_path = get_file_path('var', file_name)

    books_list = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        books_list = json.load(file_handle)

    return books_list


def write_books_to_google_docs(auth_data,
                               shelf_name,
                               workbook_title,
                               books_status):
    # Fetch google_docs client.
    print("Authenticating to Google service.")
    client = get_service_client(auth_data)

    # Fetch spreadsheet params.
    books_status = [[book[header] for header in WORKSHEET_HEADERS]
                    for book in books_status]

    print("Writing books.")
    write_rows_to_worksheet(client,
                            workbook_title,
                            get_worksheet_name(shelf_name),
                            books_status)


def write_books_to_xls(shelf_name, books_status):
    return make_xls(shelf_name,
                    get_today_date(),
                    WORKSHEET_HEADERS,
                    books_status)


def get_books_source_file(source, profile_name=''):
    if re.match(r'^.*\.json$', source):
        return source

    source_file = re.sub(r'\s+', '_', source.lower())
    return f'{profile_name}_{source_file}.json'


def refresh_books_list(books_source, profile_name):
    return subprocess.call([
        sys.executable,
        '-tt', get_file_path('shelf_scraper.py'),
        '--shelf-name', books_source,
        '--profile-name', profile_name,
    ])


def parse_args(library_choices):
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-a", "--auth-data")

    # Add library option.
    option_parser.add_option(
        "-l",
        "--library",
        type='choice',
        choices=library_choices,
        help="Choose one of {0}".format("|".join(library_choices)),
    )

    options, _ = option_parser.parse_args()

    # Check for library name.
    if not options.library:
        option_parser.print_help()
        exit(-1)

    return options


def main():
    # Fetch library data.
    config = Config()['opac']

    # Parse arguments
    options = parse_args(config.getstruct('libraries'))

    # Get source file for library.
    profile_name = config['profile_name']
    books_source = Config()[f'libraries:{options.library}']['source']

    if options.refresh:
        print('Updating list of books from source "%s".' % books_source)
        refresh_books_list(books_source, profile_name)

    books_source_file = get_books_source_file(books_source, profile_name)

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
                                   config['workbook_title'],
                                   books_status)
    else:
        write_books_to_xls(books_source_file, books_status)


if __name__ == "__main__":
    main()
