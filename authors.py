#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import sys
import json
import urllib
import urllib2
import gdata.spreadsheet.service
from filecache import filecache
from optparse import OptionParser
from multiprocessing.dummy import Pool, Lock, cpu_count
from nomnom_filter import get_json_file
from imogeen import get_parsed_url_response
from nomnom_filter import (
    get_auth_data,
    connect_to_service,
    retrieve_spreadsheet_id,
    get_writable_worksheet,
    get_writable_cells
)
from opac import get_books_source, refresh_books_list
# }}}

LOCK = Lock()

def get_unique_authors(books_list):
    authors = set()
    for book in books_list:
        if book and book['author']:
            authors.add(
                re.sub(r'\s+', ' ', book['author'].strip()).encode('utf-8')
            )
    return authors

@filecache(30 * 24 * 60 * 60)
def get_author_info(author):
    with LOCK:
        print('Fetching %s info.' % author)

    # Prepare query url.
    api_url  = 'http://www.goodreads.com/search?%s' % (
        urllib.urlencode({ 'q': re.sub(r'\s+', '+', author) })
    )

    # Query site for author.
    response = get_parsed_url_response(api_url)

    info_url = None
    if response:
        # Find book author(s).
        author_spans = response.findAll('span', {'itemprop': 'author'})
        if author_spans:
            # Match for current author.
            for span in author_spans:
                for a in span.findAll('a', {'class': 'authorName'}):
                    # Get author href.
                    if a.text.encode('utf-8') == author:
                        info_url = a['href']
                        break
                # Break of outer loop too.
                if info_url:
                    break
        response.decompose()

    birth_place = None
    if info_url:
        response = get_parsed_url_response(info_url)
        if response:
            birth_place = response.first('div', text=u'born')
            if birth_place:
                # Striptease.
                birth_place = birth_place.next.strip().split(',').pop().strip().replace('in ', '')
        response.decompose()


    return (author, birth_place)

def get_authors_info(books_list):
    # Get unique authors.
    authors = get_unique_authors(books_list)

    # Create workers pool.
    workers_count = cpu_count() * 2
    pool          = Pool(workers_count)

    print('Fetching %d authors info.' % len(authors))
    authors_info = pool.map(
        get_author_info,
        authors,
    )

    # No new jobs can be added to pool.
    pool.close()

    # Wait until all threads finish.
    pool.join()

    return authors_info

def map_authors_by_country(authors_info):
    authors_by_country = {}

    for author_info in authors_info:
        country = (author_info[1] or 'None')
        if not authors_by_country.has_key(country):
            authors_by_country[country] = []
        authors_by_country[country].append(author_info[0])

    return authors_by_country

def write_countries(client, dst_cells, countries_map):
    # Prepare request that will be used to update worksheet cells.
    batch_request = gdata.spreadsheet.SpreadsheetsCellsFeed()

    # Sort countries.
    countries  = countries_map.keys()
    countries.sort()

    cell_index = 0
    for country in countries:
        country_authors = "\n".join(countries_map[country])

        for value in (country, country_authors):
            # Fetch next cell.
            text_cell = dst_cells.entry[cell_index]

            # Update cell value.
            text_cell.cell.inputValue = value
            batch_request.AddUpdate(text_cell)

            # Go to next cell.
            cell_index += 1

    # Execute batch update of destination cells.
    return client.ExecuteBatch(
        batch_request, dst_cells.GetBatchLink().href
    )

def main():
    # Cmd options parser
    option_parser = OptionParser()

    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-a", "--auth-data")
    option_parser.add_option("-s", "--source")

    (options, args) = option_parser.parse_args()

    if not (options.auth_data and options.source):
        # Display help.
        option_parser.print_help()
    else:
        if options.refresh:
            refresh_books_list(options.source)

        books_source = get_books_source(options.source)

        # Read in source file.
        books_list = get_json_file(books_source)

        # Fetch author info for each book.
        authors_info = get_authors_info(books_list)

        countries_map = map_authors_by_country(authors_info)
        countries_len = len(countries_map.keys())

        # Drive connecton boilerplate.
        print("Authenticating to Google service.")
        auth_data = get_auth_data(options.auth_data)
        client    = connect_to_service(auth_data)

        # Fetch spreadsheet id.
        spreadsheet_title = u'Karty'
        ssid              = retrieve_spreadsheet_id(client, spreadsheet_title)

        # Destination worksheet boilerplate.
        dst_name      = u'Krajoliteratura'
        print(u"Fetching destination worksheet '%s'." % dst_name)
        dst_worksheet = get_writable_worksheet(
            client,
            dst_name,
            ssid,
            row_count=countries_len,
        )

        print("Fetching destination cells.")
        writable_cells = get_writable_cells(
            client,
            dst_worksheet,
            ssid,
            max_row=countries_len
        )

        print("Writing authors.")
        write_countries(client, writable_cells, countries_map)

if __name__ == "__main__":
    main()
