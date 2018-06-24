#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import 
import re
import zlib
import threading
from optparse import OptionParser
from urllib.parse import urlparse
from lib.diskcache import diskcache, YEAR
from lib.common import (
    get_parsed_url_response,
    get_config,
    print_progress,
    print_progress_end,
)
from lib.gdocs import (
    get_service_client,
    get_workbook,
    write_rows_to_worksheet,
)

# Lock for appending row to list.
LOCK = threading.Lock()

def get_page_text(recipe_url):
    # Get parsed page instance.
    page = get_parsed_url_response(recipe_url, verbose=False)
    if not page: return

    # Remove <script> tags from page.
    # Remove <style> tags from page.
    # Remove <a> tags from page.
    # Remove <form> tags from page.
    for elem in page.body.find_all(['script', 'style', 'form', 'a']):
        elem.extract()

    # Remove all hidden items.
    for elem in page.body.find_all(attrs={ 'display': 'none' }):
        elem.extract()

    # Remove comments.
    for attr_name in ('comment', 'koment'):
        attr_re = re.compile('.*{0}.*'.format(attr_name), re.I)
        for elem in page.body.find_all(attrs={ 'id': attr_re }):
            elem.extract()
        for elem in page.body.find_all(attrs={ 'class': attr_re }):
            elem.extract()

    page_text = page.body.get_text().replace("\n", '')

    page.decompose()

    return page_text

@diskcache(YEAR)
def get_compressed_page_text(recipe_url):
    page_text = get_page_text(recipe_url)
    return zlib.compress(page_text.encode('utf-8')) if page_text else None

def get_recipe_text(recipe_url):
    compressed_text = get_compressed_page_text(recipe_url)
    return (zlib.decompress(compressed_text).decode('utf-8') if compressed_text
                                                                else None)

def filter_recipe(recipe_page, contains_re, filter_re):
    if not recipe_page: return False

    result = False
    if contains_re and not filter_re:
        result = re.search(contains_re, recipe_page, re.UNICODE)

    if filter_re and not contains_re:
        result = not re.search(filter_re, recipe_page, re.UNICODE)

    if contains_re and filter_re:
        result = (
            re.search(contains_re, recipe_page, re.UNICODE) and
            not re.search(filter_re, recipe_page, re.UNICODE)
        )

    return result

def filter_recipe_row(row, results, contains_re, filter_re):
    # Skip empty rows.
    if not row[1]: return

    parsed_url = urlparse(row[1])
    recipe_url = parsed_url.geturl()

    is_filtered = False
    # First quick check - try if recipe description matches given filters.
    if filter_recipe(row[0], contains_re, filter_re):
        is_filtered = True
    # Second quick check - treat cell content as recipe.
    elif filter_recipe(row[1], contains_re, filter_re):
        is_filtered = True
    # No luck - check if recipe page matches given filters.
    elif parsed_url.scheme and parsed_url.netloc:
        is_filtered = filter_recipe(get_recipe_text(recipe_url),
                                    contains_re,
                                    filter_re)

    # Print progress info.
    print_progress()

    # Append filtered row.
    with LOCK:
        if is_filtered and recipe_url not in results:
            results[recipe_url] = row

    return

def filter_recipes(rows, contains_re, filter_re):
    if not rows: return

    # Will contain filtered results.
    results = {}

    # Process rows in groups of 10.
    step = 10
    for chunk in [ rows[i:i+step] for i in range(0, len(rows), step) ]:
        threads = [threading.Thread(target=filter_recipe_row,
                                    args=(row, results, contains_re, filter_re))
                   for row in chunk]
        # Wait for threads to finish.
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    print_progress_end()

    return list(results.values())

def get_result_worksheet_name(options):
    """ Get name of writable worksheet. """

    result_name = options.result or ''
    if not result_name:
        # Create name from 'contains' and 'filter' params.
        if options.contains:
            result_name += '+' + options.contains
        if options.filter:
            result_name += '-' + options.filter

    return result_name

def build_and_regex(option):
    return ''.join('(?=.*%s)' % opt for opt in re.split(',', option))

def build_regex_from_options(options):
    # Build regexp for required phrases.
    contains_re = build_and_regex(options.contains) if options.contains else None

    # Build regexp for phrases to be filtered out.
    filter_re = build_and_regex(options.filter) if options.filter else None

    return (contains_re, filter_re)

def get_worksheets_from_options(options):
    return (options.worksheets.split(',') if options.worksheets else None)

def retrieve_recipe_rows(client, workbook_title, worksheet_names):
    if not client: return

    # Get worksheet feed.
    workbook = get_workbook(client, workbook_title)

    # Filter worksheets if 'worksheets' option was given.
    worksheets = workbook.worksheets()
    if worksheet_names:
        worksheets = [ ws for ws in worksheets if ws.title in worksheet_names ]

    # Fetch worksheet rows.
    recipe_rows = []
    for worksheet in worksheets:
        recipe_rows.extend(worksheet.get_all_values())

    return recipe_rows

def main():
    # Cmd options parser
    option_parser = OptionParser()

    option_parser.add_option("-a", "--auth-data")
    option_parser.add_option("-c", "--contains")
    option_parser.add_option("-f", "--filter")
    option_parser.add_option("-w", "--worksheets")
    option_parser.add_option("-r", "--result")

    (options, args) = option_parser.parse_args()

    # Display help.
    if (not options.auth_data or not (options.contains or options.filter)):
        option_parser.print_help()
    else:
        config = get_config('nomnom_filter')

        # Fetch google_docs client.
        print('Authenticating to Google service.')
        client = get_service_client(options.auth_data)

        print("Retrieving recipes.")
        recipe_rows = retrieve_recipe_rows(client,
                                           config['workbook_title'],
                                           get_worksheets_from_options(options))

        print("Filtering recipes.")
        filtered_recipes = filter_recipes(recipe_rows,
                                          *build_regex_from_options(options))

        # Write recipes only when any were found.
        if filtered_recipes:
            print("Writing %d filtered recipes." % len(filtered_recipes))
            write_rows_to_worksheet(client,
                                    config['workbook_title'],
                                    get_result_worksheet_name(options),
                                    filtered_recipes)
        else:
            print("No recipes found :(.")

if __name__ == "__main__":
    main()
