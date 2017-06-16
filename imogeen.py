#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import urllib
import simplejson as json
# import time
from operator import itemgetter
from multiprocessing.dummy import Pool, cpu_count
from filecache import filecache
# TODO: Deprecated, use argparse instead.
from optparse import OptionParser
# from datetime import datetime
from lib.common import (
    get_file_path,
    get_json_file,
    dump_json_file,
    prepare_opener,
    open_url,
    get_url_response,
    get_parsed_url_response,
    print_progress,
    print_progress_end
)
# }}}

config = get_json_file('imogeen.json')

to_read_class_re       = re.compile('shelf-name')
book_original_title_re = re.compile('tytu?')
book_pages_no_re       = re.compile('liczba stron')
book_subtitle_re       = re.compile('^([^\.]+)(?:\.\s(.*))?$')

def prepare_lc_opener():
    opener = prepare_opener(config['lc_url'])

    # Request used to initialize cookie.
    open_url(config['lc_url'], opener)

    return opener

# 'opener' will be created only once.
def get_parsed_lc_url_response(url, opener = prepare_lc_opener()):
    return get_parsed_url_response(url, opener = opener)

def get_site_url(suffix):
    return (suffix 
            if re.match(config['lc_url'], suffix) 
            else '%s/%s' % (config['lc_url'], suffix))

def get_profile_url(profile_id):
    return get_site_url('profil/%d' % profile_id)

def get_profile_name(profile_id):
    profile_url  = get_profile_url(profile_id)
    profile_page = get_parsed_lc_url_response(profile_url)

    profile_name = ''
    if profile_page:
        profile_header = profile_page.find(
            'div', 
            { 'class': re.compile('profile-header') }
        )
        if profile_header:
            profile_name = profile_header.find('h5', { 'class': 'title' }).text
            profile_name = profile_name.replace(u'\xa0', u' ').strip()
        profile_page.decompose()

    return profile_name

def get_library_re():
    return re.compile('.*profil\/.*\/biblioteczka\/lista')

def get_library_url(profile_page):
    library_url = None
    if profile_page:
        library_re       = get_library_re()
        library_url_base = profile_page.find('a', { 'href': library_re })
        library_url      = get_site_url(library_url_base['href'])
        profile_page.decompose()

    return library_url

def get_shelf_list_url(shelf_url):
    return shelf_url.replace('miniatury', 'lista')

def get_shelf_url(library_page, shelf):
    shelf_url = None
    if library_page:
        to_read_re       = re.compile('\/%s\/miniatury' % shelf)
        shelf_url_base   = library_page.find(
            'a',
            { 'href': to_read_re, 'class': to_read_class_re }
        )
        if shelf_url_base:
            shelf_url = get_shelf_list_url(
                get_site_url(shelf_url_base['href'])
            )

        library_page.decompose()

    return shelf_url

def get_pager_info(shelf_page, shelf_page_url):
    """Get pager count and link from div."""

    pager_info = None
    if shelf_page:
        # Default pager values.
        pager_count, pager_url_base = 1, shelf_page_url

        # Get last pager entry.
        pager = shelf_page.find('table', { 'class': 'pager-default' })
        if pager:
            pager_cell     = pager.find('td', { 'class': 'centered' })
            pager_tags     = pager_cell.findAll('a')
            last_pager_tag = pager_tags.pop()

            # Get pages count
            pager_count = int(re.search('\d+$', last_pager_tag['href']).group())

            # Remove page index from pager url so the url can be reused
            pager_url_base = re.sub(
                '\d+$',
                '',
                last_pager_tag['href']
            )

        # List composition.
        pager_info = pager_count, pager_url_base

        shelf_page.decompose()

    return pager_info

def progress_books_on_page(pager_url):
    books = get_books_on_page(pager_url)
    print_progress()
    return books


# Invalidate values after 6 hours.
@filecache(6 * 60 * 60)
def get_books_on_page(pager_url):
    """Get list of books on current page."""
    
    books = None
    if pager_url:
        pager_page = get_parsed_lc_url_response(pager_url)
        book_tags  = pager_page.findAll(
            'a',
            { 'class' : 'withTipFixed' }
        )
        books = [ book['href'] for book in book_tags ]
        pager_page.decompose()

    return books

def progress_book_info(book_url):
    book_info = get_book_info(book_url)
    print_progress()
    return book_info

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_book_info(book_url):
    """Get all kinds of info on book."""

    book_page = get_parsed_lc_url_response(book_url)

    book_info = None
    if book_page:

        # Get book title and author from breadcrumbs.
        breadcrumbs = book_page.find('ul', { 'class': 'breadcrumb' }).findAll('li')
        book_title  = breadcrumbs.pop()
        book_author = breadcrumbs.pop().find('a')

        # Get book details.
        book_details  = book_page.find('div', { 'id': 'dBookDetails' })
        book_category = book_details.find('a', { 'itemprop': 'genre' })
        book_isbn     = book_details.find('span', { 'itemprop': 'isbn' })
        book_release  = book_details.find('dd', { 'itemprop': 'datePublished' })

        # Get original title if present.
        book_original_title     = None
        # Get pages number.
        book_pages_no    = None
        for div in book_details.findAll('div', { 'class': 'profil-desc-inline' }):
            if div.find(text=book_original_title_re):
                book_original_title = div.find('dd').string
            elif div.find(text=book_pages_no_re):
                book_pages_no = div.find('dd').string

        title, subtitle = book_subtitle_re.search(book_title.string).groups()

        book_info = {
            'title'             : (title or book_title.string),
            'subtitle'          : subtitle,
            'original_title'    : book_original_title,
            'author'            : book_author.string,
            'category'          : book_category.string,
            # ISBN is not always present.
            'isbn'              : book_isbn.string if book_isbn else None,
            'pages'             : book_pages_no,
            'url'               : book_url,
            'release'           : book_release['content'] if book_release else None,
        }

        book_page.decompose()

    return book_info

def progress_book_price(book_info):
    url = '{0}?{1}'.format(config['bb_url'], urllib.urlencode({
        'name':        book_info['title'],
        'info':        book_info['author'],
        'number':      book_info['isbn'],
        'skip_jQuery': '1',
    }))
    book_info['price'] = get_book_price(url)
    print_progress()
    return

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_book_price(url):
    """Get book price."""

    response      = get_url_response(url)
    response_json = json.load(response) if response else None

    book_price    = None
    if response_json and 'status' in response_json and response_json['status']:
        entries = (response_json['data'].values()
                   if type(response_json['data']) is dict
                   else response_json['data'])
        for entry in entries:
            if not('type' in entry and
                   'name' in entry and
                   entry['type'] == 'book' and
                   entry['name'] in config['retailers']):
                continue
            book_price = (entry['price']
                          if 'price' in entry and entry['price']
                          else None)
            break
    return book_price

def collect_shelf_books(pager_count, pager_url_base, include_price):
    shelf_books = []
    if pager_count and pager_url_base:
        # Create workers pool.
        workers_count = cpu_count() * 2
        pool          = Pool(workers_count)

        print("Fetching %d shelf pages." % pager_count)
        pager_urls = [
            '%s%d' % (pager_url_base, index)
            for index in range(1, (pager_count+1))
        ]

        books_per_page = pool.map(
            progress_books_on_page,
            pager_urls
        )
        print_progress_end()

        book_urls = [
            book
            for books in books_per_page
            for book in books
        ]

        if book_urls:
            print("Fetching %d books info." % len(book_urls))
            shelf_books = pool.map(progress_book_info, book_urls)
            print_progress_end()
            print("Fetched %d books." % len(shelf_books))
        else:
            print('No books fetched.')

        if book_urls and include_price:
            print("Fetching %d book prices." % len(shelf_books))
            pool.map(progress_book_price, shelf_books)
            print_progress_end()
            print("Fetched %d book prices." % len(shelf_books))

        # No new jobs can be added to pool.
        pool.close()

        # Wait until all threads finish.
        pool.join()

    return shelf_books

def dump_books_list(shelf_books, file_name):
    if shelf_books:
        # Save sorted list to json
        print("Dumping results to file %s." % file_name)
        dump_json_file(shelf_books, get_file_path(file_name))

    return

def fetch_shelf_list(profile_id, shelf_name=None, shelf_url=None, include_price=False, file_name=None):
    # Fetch shelf url if required.
    if not shelf_url:
        # Get profile url
        profile_url = get_profile_url(profile_id)

        # Fetch profile page
        print("Fetching profile page.")
        profile_page = get_parsed_lc_url_response(profile_url)

        # Make library url.
        library_url = get_library_url(profile_page)

        # Fetch library page.
        print("Fetching library page.")
        library_page = get_parsed_lc_url_response(library_url)

        # Make 'to read' url
        shelf_url = get_shelf_url(library_page, shelf_name)

    shelf_books = None
    if shelf_url:
        # Fetch 'to read' books list
        shelf_page = get_parsed_lc_url_response(shelf_url)
        print("Fetching '%s' books list." % shelf_name)

        # Get pages url and count
        pager_count, pager_url_base = get_pager_info(shelf_page, shelf_url)

        # Fetch info of all books on list
        shelf_books = collect_shelf_books(
            pager_count, pager_url_base, include_price
        )

    if shelf_books:
        # Sort books by release or price.
        sort_key     = 'price' if include_price else 'release'
        reverse_sort = False if sort_key == 'price' else True
        shelf_books.sort(key=itemgetter(sort_key), reverse=reverse_sort)

        # Dump list of books to file
        if not file_name:
            profile_name = get_profile_name(profile_id)
            file_name    = '%s_%s.json' % (profile_name, shelf_name)
        dump_books_list(shelf_books, file_name)
    else:
        print('No books were found for shelf "{0}".'.format(shelf_name))

def fetch_shelves_info(profile_id, skip_library_shelf=True):

    # Fetch library page.
    profile_name = get_profile_name(profile_id)
    profile_url  = get_profile_url(profile_id)
    profile_page = get_parsed_lc_url_response(profile_url)
    library_url  = get_library_url(profile_page)
    library_page = get_parsed_lc_url_response(library_url)

    shelves_info = []
    if library_page:
        shelves_list = library_page.find(
            'ul', 
            { 'class': re.compile('shelfs-list') }
        )
        if shelves_list:
            library_re = get_library_re() if skip_library_shelf else None

            for shelf in shelves_list.findAll('a', { 'class': re.compile('shelf') }):
                shelf_url = get_shelf_list_url(get_site_url(shelf['href']))

                # Skip library shelf.
                if skip_library_shelf and library_re.match(shelf_url):
                    continue

                shelf_name = shelf['href'].split('/')[-2]
                shelves_info.append({
                    'title':    shelf.string,
                    'name':     shelf_name,
                    'filename': '%s_%s.json' % (profile_name, shelf_name),
                    'url':      shelf_url,
                })

        library_page.decompose()

    return shelves_info

def fetch_all_shelves(profile_id, include_price):
    shelves = fetch_shelves_info(profile_id)

    for shelf in shelves:
        fetch_shelf_list(
            profile_id, 
            shelf_name=shelf['name'],
            shelf_url=shelf['url'],
            include_price=include_price,
            file_name=shelf['filename'],
        )

    return

def main():
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-t", "--to-read", action="store_true")
    option_parser.add_option("-o", "--owned", action="store_true")
    option_parser.add_option("-r", "--read", action="store_true")
    option_parser.add_option("-p", "--price", action="store_true")
    option_parser.add_option("-s", "--shelf")
    option_parser.add_option("-i", "--profile-id", type="int")

    (options, args) = option_parser.parse_args()

    if not (options.profile_id and (
        options.to_read or 
        options.owned or 
        options.read or 
        options.shelf
    )):
        # Display help
        option_parser.print_help()
    elif options.to_read:
        # Scan to read list
        fetch_shelf_list(
            options.profile_id, 'chce-przeczytac', include_price=options.price
        )
    elif options.read:
        fetch_shelf_list(options.profile_id, 'przeczytane')
    elif options.owned:
        # Scan owned list.
        fetch_shelf_list(options.profile_id, 'posiadam')
    elif options.shelf:
        # Fetch books from all shelves.
        if options.shelf == 'all':
            fetch_all_shelves(options.profile_id, options.price)
        else:
            fetch_shelf_list(
                options.profile_id, options.shelf, include_price=options.price
            )

if __name__ == "__main__":
    # start_time = datetime.now()
    main()
    # print("Run time:")
    # print(datetime.now() - start_time)
