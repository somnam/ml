#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import 
import sys
import re
import zlib
import json
import codecs
import urllib2
import threading
from optparse import OptionParser
from urlparse import urlparse
from filecache import filecache
from lib.common import (
    get_parsed_url_response,
    get_file_path,
    print_progress,
    print_progress_end,
)
from lib.gdocs import (
    get_service_client,
    get_writable_cells,
    retrieve_spreadsheet_id,
    write_rows_to_worksheet,
)

SPREADSHEET_TITLE = u'Lista'

def retrieve_recipe_cells(client):
    if not client:
        return

    # Get worksheet feed.
    spreadsheet_id = retrieve_spreadsheet_id(client, SPREADSHEET_TITLE)
    work_feed      = client.GetWorksheets(spreadsheet_id)

    recipe_cells = []
    for worksheet in work_feed.entry:
        # Fetch worksheet cells.
        print_progress()
        cells = get_writable_cells(
            client, spreadsheet_id, worksheet, max_col=2
        )
        recipe_cells.append(cells)
    print_progress_end()

    return recipe_cells

def filter_nomnoms(row, lock, filtered_recipes, contains_re, filter_re):
    # Skip empty rows.
    recipe_cell  = row[1].cell.input_value
    if not recipe_cell:
        return

    # Check if current recipe matches given filters.
    filtered_recipe  = False
    recipe_url       = urlparse(recipe_cell)
    recipe_url_value = recipe_url.geturl()
    # Check for correct url.
    if recipe_url.scheme and recipe_url.netloc:
        # Print info.
        with lock:
            print_progress()

        filtered_recipe = filter_nomnom_page(
            recipe_url_value,
            contains_re,
            filter_re
        )
    # No url given - treat cell content as recipe.
    else:
        if filter_recipe(recipe_cell, contains_re, filter_re):
            filtered_recipe = True

    # Append filtered row.
    with lock:
        if filtered_recipe and not filtered_recipes.has_key(recipe_url_value):
            filtered_recipes[recipe_url_value] = row

    return

def filter_nomnom_page(recipe_url_value, contains_re, filter_re):
    """ Check if current recipe url matches given filters."""

    filtered_recipe = False

    # Fetch parsed recipe page.
    recipe_page = get_nomnom_page(recipe_url_value)
    if recipe_page:
        # Check page content with given filters.
        if filter_recipe(zlib.decompress(recipe_page), contains_re, filter_re):
            filtered_recipe = True

    return filtered_recipe

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_nomnom_page(recipe_url):
    # Get BeautifulSoup page instance.
    parser = get_parsed_url_response(recipe_url)

    page = None
    if parser and parser.find('body'):
        # Don't search in header.
        parser = parser.find('body')

        # Remove <script> tags from page.
        [script.extract() for script in parser.findAll('script')]

        # Remove <a> tags from page.
        [a.extract() for a in parser.findAll('a')]

        # Remove <form> tags from page.
        [form.extract() for form in parser.findAll('form')]

        # Remove all hidden items.
        [elem.extract() for elem in parser.findAll(None, { 'display': 'none' })]

        # Remove comments.
        comments = ('comment', 'koment')
        for comment in comments:
            comment_re = re.compile('.*' + comment + '.*', re.I)
            [elem.extract() for elem in parser.findAll(
                None,
                { 'id': comment_re }
            )]
            [elem.extract() for elem in parser.findAll(
                None,
                { 'class': comment_re }
            )]

        # Convert back to string and zip.
        page = zlib.compress(unicode(parser).encode('utf-8'))

    return page

def filter_recipe(recipe_page, contains_re, filter_re):
    return (
        (contains_re and re.search(contains_re, recipe_page, re.UNICODE)) or
        (filter_re and not re.search(filter_re, recipe_page, re.UNICODE))
    )

def get_step_end_index(rows_len, step, i):
    return (i+step) if (i+step) < rows_len else rows_len

def build_and_regex(option):
    return ''.join('(?=.*%s)' % opt for opt in re.split(',', option))

def filter_recipe_cells(recipe_cells, options):
    if not recipe_cells:
        return

    # Build regexp for required phrases.
    contains_re = None
    if options.contains:
        contains_re = build_and_regex(options.contains)

    # Build regexp for phrases to be filtered out.
    filter_re = None
    if options.filter:
        filter_re = build_and_regex(options.filter)

    # Will contain filtered results.
    filtered_recipes = {}

    # Lock for appending row to list.
    lock = threading.Lock()

    # Process rows in groups of 10.
    step = 10
    for cells in recipe_cells:
        # Build rows - each row contains name and href cells in a tuple.
        rows        = zip(*([iter(cells.entry)] * 2))
        rows_len    = len(rows)

        # Create treads per group.
        for i in range(rows_len)[::step]:
            j = get_step_end_index(rows_len, step, i)

            # Start a new thread for each row.
            recipe_threads = [
                threading.Thread(
                    target=filter_nomnoms,
                    args=(row, lock, filtered_recipes, contains_re, filter_re)
                )
                for row in rows[i:j]
            ]

            # Wait for threads to finish.
            for thread in recipe_threads:
                thread.start()
            for thread in recipe_threads:
                thread.join()
    print_progress_end()

    # Map cell objects to values.
    filtered_recipe_values = []
    for row in filtered_recipes.values():
        filtered_recipe_values.append([
            cell.cell.input_value for cell in row
        ])

    return filtered_recipe_values

def get_worksheet_name(options):
    """ Get name of writable worksheet. """

    worksheet_name = options.worksheet or u''
    if not worksheet_name:
        # Create name from 'contains' and 'filter' params.
        if options.contains:
            worksheet_name += u'+' + options.contains
        if options.filter:
            worksheet_name += u'-' + options.filter

    return worksheet_name

def decode_options(options):
    """Decode non-ascii option values."""

    # Used to decode options.
    stdin_enc = sys.stdin.encoding

    options.contains, options.filter, options.worksheet = (
        options.contains.decode(stdin_enc) if options.contains else None,
        options.filter.decode(stdin_enc) if options.filter else None,
        options.worksheet.decode(stdin_enc) if options.worksheet else None
    )

    return

def main():
    # Cmd options parser
    option_parser = OptionParser()

    option_parser.add_option("-a", "--auth-data")
    option_parser.add_option("-c", "--contains")
    option_parser.add_option("-f", "--filter")
    option_parser.add_option("-w", "--worksheet")

    (options, args) = option_parser.parse_args()

    if (
        not options.auth_data or
        not (options.contains or options.filter)
    ):
        # Display help.
        option_parser.print_help()
    else:
        decode_options(options)

        # Fetch gdata client.
        print(u'Authenticating to Google service.')
        client = get_service_client(options.auth_data)

        print("Retrieving recipes.")
        recipe_cells = retrieve_recipe_cells(client)

        print("Filtering recipes.")
        filtered_recipes = filter_recipe_cells(recipe_cells, options)

        # Write recipes only when any were found.
        if filtered_recipes:
            print("Writing %d filtered recipes." % len(filtered_recipes))
            write_rows_to_worksheet(
                client,
                SPREADSHEET_TITLE,
                get_worksheet_name(options),
                filtered_recipes
            )
        else:
            print("No recipes found :(.")

if __name__ == "__main__":
    main()
