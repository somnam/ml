#!/usr/bin/python -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import urllib
import urllib2
from filecache import filecache
from lib.common import (
    print_progress,
    prepare_opener,
    get_url_response,
    parse_url_response,
    get_parsed_url_response,
)
# }}}

gr_url        = 'http://www.goodreads.com'
gr_search_url = '{0}/search'.format(gr_url)

def prepare_gr_opener(url):
    opener = prepare_opener(url)
    # Request used to initialize cookie.
    request = urllib2.Request(url)
    opener.open(request)
    return opener

def get_gr_opener(opener=prepare_gr_opener(gr_url)):
    return opener

def get_gr_books_pl_info(books):
    books_info = []
    for book in books:
        # No params to query for.
        if not(book.has_key('isbn') or book.has_key('title')):
            continue

        book_url  = get_gr_book_url(book)
        book_info = get_gr_book_pl_info(book_url)
        print_progress()
        if not book_info: continue

        books_info.append(book_info)

    return books_info

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_gr_book_url(book):
    # Query book first by isbn, next by title.
    book_url = None
    opener   = get_gr_opener()
    for query_param in ('isbn', 'title'):
        if not(book.has_key(query_param) and book[query_param]):
            continue

        # Search for book by query param.
        book_search_url = '{0}?{1}'.format(gr_search_url, urllib.urlencode({
            'query': book[query_param].encode('utf-8')
        }))
        response = get_url_response(book_search_url, opener=opener)

        # Search by isbn should yield the book page, search by title can.
        if re.search(r'book\/show', response.geturl()):
            book_url = response.geturl()
            break
        elif query_param == 'title':
            book_url = _get_gr_book_url_by_title(book, response)

    return book_url

def _get_gr_book_url_by_title(book, response):
    # Check if books list was found.
    parsed_response = parse_url_response(response)
    books_table     = parsed_response.find('table', {'class': 'tableList'})

    # Check for empty results.
    if (
        parsed_response.find('div', { 'class': re.compile('notice') }) or
        not books_table
    ):
        parsed_response.decompose()
        return

    # Multiple results were found.
    book_url   = None
    books_list = books_table.findAll('tr', {'itemtype': 'http://schema.org/Book'})
    for book_entry in books_list:
        edition_title_tag = book_entry.find('a', {'class': 'bookTitle'})
        edition_title     = edition_title_tag.find('span', {'itemprop': 'name'}).text
        book_author    = book_entry.find('a', {'class': 'authorName'}) \
                                   .find('span', {'itemprop': 'name'}).text

        if re.compile(book['title']).match(edition_title) and \
           re.compile(book['author']).match(book_author):
            book_url = '{0}{1}'.format(gr_url, edition_title_tag['href']);
            break

    parsed_response.decompose()

    return book_url

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def get_gr_book_pl_info(book_url):
    if not book_url: return

    opener          = get_gr_opener()
    parsed_response = get_parsed_url_response(book_url, opener=opener)
    if not parsed_response: return

    editions_tag = parsed_response.find('div', {'class': 'otherEditionsActions'})
    if not editions_tag:
        parsed_response.decompose()
        return

    # Get url to all book editions list.
    all_editons_url = (editions_tag.a['href']
                       if editions_tag.a.contents[0] == 'All Editions'
                       else None)
    if not all_editons_url:
        parsed_response.decompose()
        return
    all_editons_url = '{0}{1}?{2}'.format(
        gr_url,
        all_editons_url,
        urllib.urlencode({'per_page': 100}),
    )

    # Fetch list.
    parsed_response.decompose()
    parsed_response = get_parsed_url_response(all_editons_url, opener=opener)
    if not parsed_response: return
    editions_list = parsed_response.find(
        'div', {'class': re.compile('workEditions')}
    )
    if not editions_list:
        parsed_response.decompose()
        return

    # Find all book editions tags.
    editions = editions_list.findAll('div', {'class': 'editionData'})

    # Parsing helpers.
    more_details_re  = re.compile('moreDetails')
    edition_lang_re  = re.compile('language')
    edition_isbn_re  = re.compile('ISBN')
    edition_title_re = re.compile('\s\(\w+\)$')
    row_value_fetch  = lambda row: row.find(
        'div', {'class': 'dataValue'}
    ).contents[0].strip()

    # Search for polish edition.
    book_info            = {}
    polish_edition_found = False
    for edition in editions:
        edition_title = edition.find('a', {'class': 'bookTitle'}).string

        edition_isbn, edition_lang, edition_author = None, None, None

        rows = edition.find('div', {'class': more_details_re}).findAll(
            'div', {'class': 'dataRow'}
        )
        for row in rows:
            title = row.find('div', {'class': 'dataTitle'})
            if not title: continue

            if edition_isbn_re.search(title.contents[0]):
                # value        = row.find('div', {'class': 'dataValue'})
                # edition_isbn = value.contents[0].strip()
                edition_isbn = row_value_fetch(row)
            elif edition_lang_re.search(title.contents[0]):
                # value        = row.find('div', {'class': 'dataValue'})
                # edition_lang = value.contents[0].strip()
                edition_lang = row_value_fetch(row)
            elif row.find('a', {'class': 'authorName'}):
                edition_author = row.find('a', {'class': 'authorName'}).find(
                    'span'
                ).string

            if edition_isbn and edition_author and edition_lang and edition_lang == 'Polish':
                book_info['title']   = edition_title_re.sub('', edition_title)
                book_info['author']  = edition_author
                book_info['isbn']    = edition_isbn
                polish_edition_found = True
                break

        if polish_edition_found: break

    parsed_response.decompose()

    return book_info
