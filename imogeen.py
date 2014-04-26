#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import json
import time
import re
import httplib
import urllib2
import codecs
import threading
from BeautifulSoup import BeautifulSoup
# from operator import itemgetter
from optparse import OptionParser
# }}}

def get_url_response(url):
    """Send request to given url and ask for response."""

    # Send request to given url and fetch response
    headers     = { 'User-Agent' : 'Mozilla/5.0' }
    request     = urllib2.Request(url, headers=headers)

    response = None
    try:
        response = urllib2.urlopen(request)
        if response.getcode() != 200:
            response = None
    except httplib.BadStatusLine:
        print "Could not fetch url '%s'." % url

    return response

def get_parsed_url_response(url):
    """Send request to given url and return parsed HTML response."""

    # Fetch url response object
    response = get_url_response(url)

    # Parse html response (if available)
    parser = None
    if response:
        parser = BeautifulSoup(
            response,
            convertEntities=BeautifulSoup.HTML_ENTITIES
        )

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

    return library_url

def get_shelf_url(library_page, shelf):
    shelf_url = None
    if library_page:
        to_read_re     = re.compile(shelf)
        shelf_url_base = library_page.find('a', { 'href' : to_read_re })
        shelf_url      = get_site_url(shelf_url_base['href'])

    return shelf_url

def get_pager_info(shelf_page):
    """Get pager count and link from div."""

    pager_info = None
    if shelf_page:
        # Look for pager tag
        pager_tag = shelf_page.find('table', { 'class': 'pager-default' })

        # Get last pager entry.
        pager_cell      = pager_tag.find('td', { 'class': 'centered' })
        pager_tags      = pager_cell.findAll('a')
        last_pager_tag  = pager_tags.pop()

        # Get pages count
        pager_count = int(re.search('\d+$', last_pager_tag['href']).group())

        # Remove page index from pager url so the url can be reused
        pager_url_base = re.sub(
            '\d+$',
            '',
            last_pager_tag['href']
            # pager_count_tag.find('a')['href']
        )

        pager_info = pager_count, pager_url_base

    return pager_info

def get_books_on_page(pager_page):
    """Get list of books on current page."""
    
    books = None
    if pager_page:
        books = pager_page.find(
            'ul', 
            { 'class' : 'books-list' }
        ).findAll(
            'a', 
            { 'class' : 'bookTitle' }
        )

    return books

def get_book_info(book_page, book_url):
    """Get all kinds of info on book."""
    
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
        book_category   = book_details.find('a', { 'class': 'blue small' })
        book_isbn       = book_details.find('span', { 'itemprop': 'isbn' })

        # Get original title if present.
        book_original_title     = None
        book_original_title_re  = re.compile('tytu?')
        for div in book_details.findAll('div', { 'class': 'profil-desc-inline' }):
            if div.find(text=book_original_title_re):
                book_original_title = div.find('dd').string
                break


        book_info = {
            'title'             : book_title.string,
            'original_title'    : book_original_title,
            'author'            : book_author.string,
            'category'          : book_category.string,
            # ISBN is not always present.
            'isbn'              : book_isbn.string if book_isbn else None,
            'url'               : book_url,
        }

    return book_info

def fetch_shelf_book(counter, book, shelf_books, lock):
    book_url    = book['href']
    book_page   = get_parsed_url_response(book_url)
    book_info   = get_book_info(book_page, book_url)

    with lock:
        if book_info:
            print("\t\tFetched book %d" % (counter+1))
            shelf_books.append(book_info)

    return

def collect_shelf_books(pager_count, pager_url_base):
    shelf_books = []
    if pager_count and pager_url_base:

        # Lock for writing book info in shelf_books
        lock = threading.Lock()

        for index in range(1, (pager_count+1)):
            print("\tFetching page %d" % index)

            pager_url   = '%s%d' % (pager_url_base, index)
            pager_page  = get_parsed_url_response(pager_url)

            # Get list of all books on current page
            books = get_books_on_page(pager_page)

            # Start a new thread for each book to fetch
            book_threads = [
                threading.Thread(
                    target=fetch_shelf_book,
                    args=(counter, book, shelf_books, lock)
                )
                for counter,book in enumerate(books[1:])
            ]

            # Wait for threads to finish
            for thread in book_threads:
                thread.start()
            for thread in book_threads:
                thread.join()

    return shelf_books

def dump_books_list(shelf_books, file_name):
    if shelf_books:
        # Save sorted list to json
        print("Dumping results to file.")
        file_path = get_file_path(file_name)

        # utf-8 chars should be displayed properly in results file:
        # - codecs.open must be used instead of open, with 'utf-8' flag
        file_handle = codecs.open(file_path, 'w+', 'utf-8')
        # - json.dumps must have ensure_ascii set to False
        json.dump(shelf_books, file_handle, ensure_ascii=False, indent=2)
        file_handle.close()

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

if __name__ == "__main__":
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-r", "--to-read", action="store_true")
    option_parser.add_option("-o", "--owned", action="store_true")
    option_parser.add_option("-i", "--profile-id")

    (options, args) = option_parser.parse_args()

    if not options.profile_id:
        options.profile_id = 10058

    if not options.to_read and not options.owned:
        # Display help
        option_parser.print_help()
    elif options.to_read:
        # Scan to read list
        fetch_shelf_list(options.profile_id, 'chce-przeczytac')
    elif options.owned:
        # Scan owned list.
        fetch_shelf_list(options.profile_id, 'posiadam')
