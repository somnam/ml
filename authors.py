# -*- coding: utf-8 -*-

# Import {{{
import re
import json
from urllib.parse import urlencode
from lib.diskcache import diskcache, YEAR
from optparse import OptionParser
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool
from lib.common import (
    open_url,
    prepare_opener,
    get_parsed_url_response,
    get_config,
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

def prepare_gr_opener():
    gr_url = 'http://www.goodreads.com/'
    opener = prepare_opener(gr_url)
    # Request used to initialize cookie.
    open_url(gr_url, opener)
    return opener

def get_parsed_gr_url_response(url, opener=prepare_gr_opener()):
    return get_parsed_url_response(url, opener=opener)

def get_unique_authors(books_list):
    authors = set()
    for book in (books_list or []):
        if not('author' in book and book['author']): continue
        authors.add(book['author'].strip())
    return authors

@diskcache(YEAR)
def get_author_info(author):
    # Prepare query url.
    api_url  = 'http://www.goodreads.com/search?{0}'.format(
        urlencode({ 'q': re.sub(r'\s+', '+', author) })
    )

    # Query site for author.
    response = get_parsed_gr_url_response(api_url)
    if not response: return

    # Find book author(s).
    info_link = response.find('a', text=author)
    response.decompose()
    if not info_link: return

    response = get_parsed_url_response(info_link['href'])
    if not response: return

    birth_label = response.find('div', text='Born')
    birth_place = (birth_label.next_sibling.split(',').pop().strip().replace('in ', '')
                   if birth_label else None)
    response.decompose()

    return [author, birth_place] if birth_place else None

def progress_author_info(author):
    author_info = get_author_info(author)
    print_progress()
    return author_info

def get_authors_info(books_list):
    # Get unique authors.
    authors = get_unique_authors(books_list)

    # Create workers pool.
    workers_count = cpu_count() * 2
    pool          = Pool(workers_count)

    print('Fetching %d authors info.' % len(authors))
    authors_info = pool.map(progress_author_info, authors)

    # No new jobs can be added to pool.
    pool.close()

    # Wait until all threads finish.
    pool.join()

    print_progress_end()

    return authors_info

def map_authors_by_country(authors_info):

    authors_by_country = {}
    for author_info in authors_info:
        if not author_info: continue

        country = author_info[1]
        if not country in authors_by_country:
            authors_by_country[country] = []

        authors_by_country[country].append(author_info[0])

    return authors_by_country

def prepare_contry_rows(countries_map):
    return [
        [country, "\n".join(countries_map[country]) ]
        for country in sorted(list(countries_map.keys()))
    ];

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
        return

    if options.refresh:
        print('Updating list of books from source "%s".' % options.source)
        refresh_books_list(options.source)

    # Read in source file.
    books_list = get_json_file(get_books_source_file(options.source))

    # Fetch author info for each book.
    authors_info  = get_authors_info(books_list)
    # Map authors by countries.
    countries_map = map_authors_by_country(authors_info)
    # Prepare data for worksheet.
    country_rows  = prepare_contry_rows(countries_map)

    print("Authenticating to Google service.")
    client = get_service_client(options.auth_data)

    print("Writing authors.")
    config = get_config('authors')
    write_rows_to_worksheet(client,
                            config['workbook_title'],
                            config['worksheet_title'],
                            country_rows)

if __name__ == "__main__":
    main()
