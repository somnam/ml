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
from lib.common import (
    open_url,
    prepare_opener,
    get_parsed_url_response,
    get_json_file,
    print_progress,
    print_progress_end
)
from lib.gdocs import (
    get_service_client,
    write_rows_to_worksheet,
)
from opac import get_books_source_file, refresh_books_list
# }}}

def prepare_goodreads_opener():
    gr_url = 'http://www.goodreads.com/'
    opener = prepare_opener(gr_url)
    # Request used to initialize cookie.
    open_url(gr_url, opener)
    return opener

def get_unique_authors(books_list):
    authors = set()
    for book in (books_list or []):
        if book and book['author']:
            authors.add(
                re.sub(r'\s+', ' ', book['author'].strip()).encode('utf-8')
            )
    return authors

@filecache(30 * 24 * 60 * 60)
def get_author_info(author):
    # Prepare query url.
    api_url  = 'http://www.goodreads.com/search?%s' % (
        urllib.urlencode({ 'q': re.sub(r'\s+', '+', author) })
    )

    # Query site for author.
    response = get_parsed_url_response(api_url, opener=OPENER)

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
        response = get_parsed_url_response(info_url, opener=OPENER)
        if response:
            birth_place = response.first('div', text=u'born')
            if birth_place:
                # Striptease.
                birth_place = birth_place.next.strip().split(',').pop().strip().replace('in ', '')
            response.decompose()

    with LOCK:
        print_progress()

    return [author, birth_place]

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

    print_progress_end()

    return authors_info

def map_authors_by_country(authors_info):
    authors_by_country = {}

    for author_info in authors_info:
        country = (author_info[1] or 'None')
        if not authors_by_country.has_key(country):
            authors_by_country[country] = []
        authors_by_country[country].append(author_info[0])

    return authors_by_country

def prepare_contry_rows(countries_map):
    # Sort countries
    countries = countries_map.keys()
    countries.sort()
    return [
        [
            country.decode('utf-8'), 
            "\n".join(countries_map[country]).decode('utf-8')
        ]
        for country in countries
    ]

def main():
    # Cmd options parser
    option_parser = OptionParser()

    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-a", "--auth-data")
    option_parser.add_option("-s", "--source")
    option_parser.add_option("-d", "--destination")

    (options, args) = option_parser.parse_args()

    if not (options.auth_data and options.source):
        # Display help.
        option_parser.print_help()
    else:
        if options.refresh:
            print(u'Updating list of books from source "%s".' % options.source)
            refresh_books_list(options.source)

        books_source = get_books_source_file(options.source)

        # Read in source file.
        books_list = get_json_file(books_source)

        # Fetch author info for each book.
        authors_info   = get_authors_info(books_list)
        # Map authors by countries.
        countries_map  = map_authors_by_country(authors_info)
        # Prepare data for worksheet.
        countries_rows = prepare_contry_rows(countries_map)

        print("Authenticating to Google service.")
        client = get_service_client(options.auth_data)

        print("Writing authors.")
        spreadsheet_title = u'Karty'
        dst_name          = (options.destination or u'Krajoliteratura')
        write_rows_to_worksheet(
            client,
            spreadsheet_title,
            dst_name,
            countries_rows,
        )

if __name__ == "__main__":
    LOCK   = Lock()
    OPENER = prepare_goodreads_opener()
    main()
