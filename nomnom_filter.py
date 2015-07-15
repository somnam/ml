#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import 
import sys
import re
import json
import codecs
import urllib2
import threading
import gdata.spreadsheet.service
from optparse import OptionParser
from urlparse import urlparse
from filecache import filecache
from lib.common import get_parsed_url_response, get_file_path
from lib.gdocs import (
    get_service_client,
    get_destination_cells
)

SPREADSHEET_TITLE = u'Lista'

def retrieve_recipe_cells(client):
    if not client:
        return

    # Prepare cells query.
    cell_query              = gdata.spreadsheet.service.CellQuery()
    cell_query.return_empty = 'true'
    cell_query.max_col      = '2'

    # Get worksheet feed.
    spreadsheet_id    = retrieve_spreadsheet_id(client, SPREADSHEET_TITLE)
    work_feed         = client.GetWorksheetsFeed(spreadsheet_id)

    recipe_cells    = []
    for worksheet in work_feed.entry:
        # Fetch worksheet cells.
        print("\tFetching worksheet '%s'." % worksheet.title.text)
        worksheet_id = worksheet.id.text.rsplit('/', 1)[-1]
        cells        = client.GetCellsFeed(
            key=spreadsheet_id,
            wksht_id=worksheet_id,
            query=cell_query
        )

        recipe_cells.append(cells)

    return recipe_cells

def filter_nomnoms(row, lock, filtered_recipes, contains_re, filter_re):

    # Skip empty rows.
    recipe_cell  = row[1].cell.inputValue
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
            print("\tProcessing url '%s'." % recipe_url_value)

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
        if filter_recipe(recipe_page, contains_re, filter_re):
            filtered_recipe = True

    return filtered_recipe

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_nomnom_page(recipe_url):
    # Get BeautifulSoup page instance.
    parser = get_parsed_url_response(recipe_url)

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

        # Convert back to string.
        parser = unicode(parser)

    return parser

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

    # Will contain filtered results.
    filtered_recipes = {}

    # Build regexp for required phrases.
    contains_re = None
    if options.contains:
        contains_re = build_and_regex(options.contains)

    # Build regexp for phrases to be filtered out.
    filter_re = None
    if options.filter:
        filter_re = build_and_regex(options.filter)

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

    return filtered_recipes.values()

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

def write_recipes(client, dst_cells, filtered_recipes):

    # Prepare request that will be used to update worksheet cells.
    batch_request = gdata.spreadsheet.SpreadsheetsCellsFeed()

    # Write filtered recipes to destination worksheet.
    cell_index = 0
    # Each row contains recipe name and href.
    for row in filtered_recipes:
        # Update each destination cell.
        for cell in row:
            # Get destination cell.
            dst_cell = dst_cells.entry[cell_index]
            # Update cell value.
            dst_cell.cell.inputValue = cell.cell.inputValue
            # Set cell for update.
            batch_request.AddUpdate(dst_cell)
            # Go to next cell.
            cell_index += 1

    # Execute batch update of destination cells.
    return client.ExecuteBatch(batch_request, dst_cells.GetBatchLink().href)

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
        client = get_service_client(options.auth_data)

        print("Retrieving recipes.")
        recipe_cells = retrieve_recipe_cells(client)

        print("Filtering recipes.")
        filtered_recipes = filter_recipe_cells(recipe_cells, options)

        # Write recipes only when any were found.
        if filtered_recipes:
            # Get worksheet for writing recipes.
            dst_worksheet_name   = get_worksheet_name(options)
            filtered_recipes_len = len(filtered_recipes)

            dst_cells = get_destination_cells(
                client,
                SPREADSHEET_TITLE,
                dst_worksheet_name,
                filtered_recipes_len
            )

            print("Writing filtered %d recipes." % filtered_recipes_len)
            write_recipes(client, dst_cells, filtered_recipes)
        else:
            print("No recipes found :(.")

if __name__ == "__main__":
    main()
