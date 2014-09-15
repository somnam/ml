#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import re
import sys
import json
import time
import httplib
import urllib2
import codecs
import locale
import threading
from multiprocessing.dummy import Pool, cpu_count
from filecache import filecache
from BeautifulSoup import BeautifulSoup
from optparse import OptionParser
from datetime import datetime
# }}}

def get_url_response(url, data=None):
    """Send request to given url and ask for response."""

    # Send request to given url and fetch response
    headers     = { 'User-Agent' : 'Mozilla/5.0' }
    request     = urllib2.Request(url, headers=headers, data=data)

    response = None
    try:
        response = urllib2.urlopen(request)
        if response.getcode() != 200:
            response = None
    except (
        httplib.BadStatusLine,
        urllib2.HTTPError,
        urllib2.URLError
    ) as e:
        print "Could not fetch url '%s'. Error: %s." % (url, e)

    return response

def get_parsed_url_response(url, data=None):
    """Send request to given url and return parsed HTML response."""

    # Fetch url response object
    response = get_url_response(url, data=data)

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
    return 'http://lubimyczytac.pl/%s' % suffix

def get_profile_url(profile_id):
    return get_site_url('profil/%d' % profile_id)

def get_library_url(profile_page):
    library_url = None
    if profile_page:
        library_re       = re.compile('profil\/.*\/biblioteczka\/lista')
        library_url_base = profile_page.find('a', { 'href': library_re })
        library_url      = library_url_base['href']
        profile_page.decompose()

    return library_url

def get_shelf_url(library_page, shelf):
    shelf_url = None
    if library_page:
        to_read_re       = re.compile('%s\/lista' % shelf)
        to_read_class_re = re.compile('shelf-name')
        shelf_url_base = library_page.find(
            'a',
            { 'href': to_read_re, 'class': to_read_class_re }
        )
        shelf_url      = get_site_url(shelf_url_base['href'])
        library_page.decompose()

    return shelf_url

def get_pager_info(shelf_page):
    """Get pager count and link from div."""

    pager_info = None
    if shelf_page:
        # Get last pager entry.
        pager_cell      = shelf_page.find('td', { 'class': 'centered' })
        pager_tags      = pager_cell.findAll('a')
        last_pager_tag  = pager_tags.pop()

        # Get pages count
        pager_count = int(re.search('\d+$', last_pager_tag['href']).group())

        # Remove page index from pager url so the url can be reused
        pager_url_base = re.sub(
            '\d+$',
            '',
            last_pager_tag['href']
        )

        pager_info = pager_count, pager_url_base

        shelf_page.decompose()

    return pager_info

def get_books_on_page(pager_url):
    """Get list of books on current page."""
    
    books = None
    if pager_url:
        pager_page = get_parsed_url_response(pager_url)
        book_tags  = pager_page.findAll(
            'a',
            { 'class' : 'bookTitle' }
        )
        books = [ book['href'] for book in book_tags ]
        pager_page.decompose()

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
        book_details    = book_page.find('div', { 'id': 'dBookDetails' })
        book_category   = book_details.find('a', { 'itemprop': 'genre' })
        book_isbn       = book_details.find('span', { 'itemprop': 'isbn' })

        # Get original title if present.
        book_original_title     = None
        book_original_title_re  = re.compile('tytu?')
        # Get pages number.
        book_pages_no = None
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
        }

        book_page.decompose()

    return book_info

def collect_shelf_books(pager_count, pager_url_base):
    shelf_books = []
    if pager_count and pager_url_base:
        # Create workers pool.
        workers_count = cpu_count() * 2
        pool          = Pool(workers_count)

        # Assume 10 books per page.
        books_batch_count = 10

        print("Fetching %d shelf pages..." % pager_count)
        pager_urls = [
            '%s%d' % (pager_url_base, index)
            for index in range(1, (pager_count+1))
        ]

        print("Fetching approximately %d book urls..." % (
            # Each page contains 10 books.
            len(pager_urls)*books_batch_count
        ))
        books_per_page = pool.map(
            get_books_on_page,
            pager_urls
        )

        book_urls = [
            book
            for books in books_per_page
            for book in books
        ]

        print("Fetched %d book urls." % len(book_urls))

        print("Fetching %d books info..." % len(book_urls))
        shelf_books = pool.map(
            get_book_info,
            book_urls
        )
        print("Fetched %d books." % len(shelf_books))

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

def dump_books_list(shelf_books, file_name):
    if shelf_books:
        # Save sorted list to json
        print("Dumping results to file.")
        dump_json_file(shelf_books, file_name)

    return

def fetch_shelf_list(profile_id, shelf):
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
    shelf_url = get_shelf_url(library_page, shelf)

    # Fetch 'to read' books list
    print("Fetching '%s' books list." % shelf)
    shelf_page = get_parsed_url_response(shelf_url)

    # Get pages url and count
    pager_info = get_pager_info(shelf_page)

    # Fetch info of all books on list
    shelf_books = collect_shelf_books(*pager_info)

    # Sort books by rating
    # shelf_books.sort(key=itemgetter('rating'), reverse=True)

    # Dump list of books to file
    dump_books_list(shelf_books, ('imogeen_%s.json' % shelf))

def get_file_path(file_name):
    return os.path.join(
        os.path.dirname(__file__),
        file_name
    )

def fix_stdout_locale():
    encoding   = 'utf-8'
    sys.stdout = codecs.getwriter(encoding)(sys.stdout)
    sys.stderr = codecs.getwriter(encoding)(sys.stderr)
    return

def main():
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-t", "--to-read", action="store_true")
    option_parser.add_option("-o", "--owned", action="store_true")
    option_parser.add_option("-r", "--read", action="store_true")
    option_parser.add_option("-s", "--shelf")
    option_parser.add_option("-i", "--profile-id")

    (options, args) = option_parser.parse_args()

    if not options.profile_id:
        options.profile_id = 10058

    if not (options.to_read or options.owned or options.read or options.shelf):
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
    elif options.shelf:
        fetch_shelf_list(options.profile_id, options.shelf)

if __name__ == "__main__":
    start_time = datetime.now()
    main()
    # print("Run time:")
    # print(datetime.now() - start_time)
