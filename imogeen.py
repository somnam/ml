#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import re
import sys
import json
import time
import cookielib
import httplib
import urllib2
import codecs
import locale
import threading
from operator import itemgetter
from multiprocessing.dummy import Pool, cpu_count
from filecache import filecache
from BeautifulSoup import BeautifulSoup
# TODO: Deprecated, use argparse instead.
from optparse import OptionParser
from datetime import datetime
# }}}

def prepare_opener(url, headers=None, data=None):
    # Prepare request handler.
    cookie_jar = cookielib.CookieJar()
    opener     = urllib2.build_opener(
        urllib2.HTTPCookieProcessor(cookie_jar),
        # urllib2.HTTPHandler(debuglevel=1),
    )

    # Prepare request headers.
    headers = headers if headers else {}
    # Append user agent to headers.
    headers['User-Agent'] = headers['User-Agent'] if headers.has_key('User-Agent') \
                                                  else 'Mozilla/5.0 Gecko Firefox'
    # Append referer to headers.
    headers['Referer'] = headers['Referer'] if headers.has_key('Referer') else url

    # Update opener with headers
    opener.addheaders = [(key, headers[key]) for key in headers.keys()]

    return opener

def get_url_response(url, headers=None, data=None, opener=None):
    """Send request to given url and ask for response."""

    opener  = (opener or prepare_opener(url, headers=headers))
    request = urllib2.Request(url, data=data)

    response = None
    try:
        response = opener.open(request)
        if response.getcode() != 200:
            response = None
    except (
        httplib.BadStatusLine,
        urllib2.HTTPError,
        urllib2.URLError
    ) as e:
        print "Could not fetch url '%s'. Error: %s." % (url, e)

    return response

def get_parsed_url_response(url, data=None, opener=None):
    """Send request to given url and return parsed HTML response."""

    # Fetch url response object
    response = get_url_response(url, data=data, opener=opener)

    # Parse html response (if available)
    parser = None
    if response:
        try:
            parser = BeautifulSoup(
                response,
                convertEntities=BeautifulSoup.HTML_ENTITIES
            )
        except TypeError:
            print(u'Error fetching response for url "%s".' % url)

    return parser

def get_site_url(suffix):
    url_base = 'http://lubimyczytac.pl'
    return suffix if re.match(url_base, suffix) else '%s/%s' % (url_base, suffix)

def get_profile_url(profile_id):
    return get_site_url('profil/%d' % profile_id)

def get_profile_name(profile_id):
    profile_url  = get_profile_url(profile_id)
    profile_page = get_parsed_url_response(profile_url)

    profile_name = ''
    if profile_page:
        profile_header = profile_page.find(
            'div', 
            { 'class': re.compile('profile-header') }
        )
        if profile_header:
            profile_name = profile_header.find('h5', { 'class': 'title' }).string
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
        to_read_re       = re.compile('%s\/miniatury' % shelf)
        to_read_class_re = re.compile('shelf-name')
        shelf_url_base   = library_page.find(
            'a',
            { 'href': to_read_re, 'class': to_read_class_re }
        )
        shelf_url        = get_shelf_list_url(
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

def print_progress():
    sys.stdout.write(".")
    sys.stdout.flush()

def print_progress_end():
    sys.stdout.write("\n")
    sys.stdout.flush()

def get_books_on_page(pager_url):
    """Get list of books on current page."""
    
    books = None
    if pager_url:
        pager_page = get_parsed_url_response(pager_url)
        book_tags  = pager_page.findAll(
            'a',
            { 'class' : 'withTipFixed' }
        )
        books = [ book['href'] for book in book_tags ]
        pager_page.decompose()
        print_progress()

    return books

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_book_info(book_url):
    """Get all kinds of info on book."""

    book_page = get_parsed_url_response(book_url)

    book_info = None
    if book_page:

        # Get book title and author from breadcrumbs.
        breadcrumbs = book_page.find(
            'ul',
            { 'class': 'breadcrumb' }
        ).findAll('li')
        book_title  = breadcrumbs.pop()
        book_author = breadcrumbs.pop().find('a')

        # Get book details.
        book_details  = book_page.find('div', { 'id': 'dBookDetails' })
        book_category = book_details.find('a', { 'itemprop': 'genre' })
        book_isbn     = book_details.find('span', { 'itemprop': 'isbn' })
        book_release  = book_details.find('dd', { 'itemprop': 'datePublished' })

        # Get original title if present.
        book_original_title     = None
        book_original_title_re  = re.compile('tytu?')
        # Get pages number.
        book_pages_no    = None
        book_pages_no_re = re.compile('liczba stron')
        for div in book_details.findAll('div', { 'class': 'profil-desc-inline' }):
            if div.find(text=book_original_title_re):
                book_original_title = div.find('dd').string
            elif div.find(text=book_pages_no_re):
                book_pages_no = div.find('dd').string

        book_info = {
            'title'             : book_title.string,
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
        print_progress()

    return book_info

def collect_shelf_books(pager_count, pager_url_base):
    shelf_books = []
    if pager_count and pager_url_base:
        # Create workers pool.
        workers_count = cpu_count() * 2
        pool          = Pool(workers_count)

        # Assume 10 books per page.
        books_batch_count = 10

        print("Fetching %d shelf pages." % pager_count)
        pager_urls = [
            '%s%d' % (pager_url_base, index)
            for index in range(1, (pager_count+1))
        ]

        books_per_page = pool.map(
            get_books_on_page,
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
            shelf_books = pool.map(
                get_book_info,
                book_urls
            )
            print_progress_end()
            print("Fetched %d books." % len(shelf_books))
        else:
            print('No books fetched.')

        # No new jobs can be added to pool.
        pool.close()

        # Wait until all threads finish.
        pool.join()

    return shelf_books

def dump_json_file(struct, file_name):
    file_path = get_file_path(file_name)

    # utf-8 chars should be displayed properly in results file:
    # - codecs.open must be used instead of open, with 'utf-8' flag
    file_handle = codecs.open(file_path, 'w+', 'utf-8')

    # - json.dumps must have ensure_ascii set to False
    json.dump(struct, file_handle, ensure_ascii=False, indent=2)

    file_handle.close()

    return

def get_file_path(file_name):
    return os.path.join(
        os.path.dirname(__file__),
        file_name
    )

def dump_books_list(shelf_books, file_name):
    if shelf_books:
        # Save sorted list to json
        print("Dumping results to file %s." % file_name)
        dump_json_file(shelf_books, file_name)

    return

def fetch_shelf_list(profile_id, shelf_name=None, shelf_url=None, file_name=None):
    # Fetch shelf url if required.
    if not shelf_url:
        # Get profile url
        profile_url = get_profile_url(profile_id)

        # Fetch profile page
        print("Fetching profile page.")
        profile_page = get_parsed_url_response(profile_url)

        # Make library url.
        library_url = get_library_url(profile_page)

        # Fetch library page.
        print("Fetching library page.")
        library_page = get_parsed_url_response(library_url)

        # Make 'to read' url
        shelf_url = get_shelf_url(library_page, shelf_name)

    # Fetch 'to read' books list
    shelf_page = get_parsed_url_response(shelf_url)
    print("Fetching '%s' books list." % shelf_name)

    # Get pages url and count
    pager_info = get_pager_info(shelf_page, shelf_url)

    # Fetch info of all books on list
    shelf_books = collect_shelf_books(*pager_info)

    if shelf_books:
        # Sort books by release.
        shelf_books.sort(key=itemgetter('release'), reverse=True)

        # Dump list of books to file
        if not file_name:
            profile_name = get_profile_name(profile_id)
            file_name    = '%s_%s.json' % (profile_name, shelf_name)
        dump_books_list(shelf_books, file_name)

def fetch_shelves_info(profile_id, skip_library_shelf=True):

    # Fetch library page.
    profile_name = get_profile_name(profile_id)
    profile_url  = get_profile_url(profile_id)
    profile_page = get_parsed_url_response(profile_url)
    library_url  = get_library_url(profile_page)
    library_page = get_parsed_url_response(library_url)

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

def fetch_all_shelves(profile_id):
    shelves = fetch_shelves_info(profile_id)

    for shelf in shelves:
        fetch_shelf_list(
            profile_id, 
            shelf_name=shelf['name'],
            shelf_url=shelf['url'],
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
    option_parser.add_option("-p", "--hunt", action="store_true")
    option_parser.add_option("-s", "--shelf")
    option_parser.add_option("-i", "--profile-id", type="int")

    (options, args) = option_parser.parse_args()

    if not (options.profile_id and (
        options.to_read or 
        options.owned or 
        options.read or 
        options.hunt or
        options.shelf
    )):
        # Display help
        option_parser.print_help()
    elif options.to_read:
        # Scan to read list
        fetch_shelf_list(options.profile_id, 'chce-przeczytac')
    elif options.read:
        fetch_shelf_list(options.profile_id, 'przeczytane')
    elif options.owned:
        # Scan owned list.
        fetch_shelf_list(options.profile_id, 'posiadam')
    elif options.hunt:
        fetch_shelf_list(options.profile_id, 'polowanie-biblioteczne');
    elif options.shelf:
        # Fetch books from all shelves.
        if options.shelf == 'all':
            fetch_all_shelves(options.profile_id)
        else:
            fetch_shelf_list(options.profile_id, options.shelf)

if __name__ == "__main__":
    # start_time = datetime.now()
    main()
    # print("Run time:")
    # print(datetime.now() - start_time)
