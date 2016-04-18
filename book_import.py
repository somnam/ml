#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import urllib
from filecache import filecache
from optparse import OptionParser
from lib.common import (
    get_url_response,
    parse_url_response,
    get_parsed_url_response,
    print_progress,
    print_progress_end
)
from lib.gr import get_gr_books_pl_info
from lib.gdocs import (
    get_service_client,
    write_rows_to_worksheet,
)
from lib.xls import make_xls
# }}}

WORKSHEET_HEADERS = (u'author', u'title', u'isbn')

def ted_recommendations(): # {{{
    print('Fetching books list')
    url = (
        'http://ideas.ted.com/'
        'your-holiday-reading-list-58-books-recommended-by-ted-speakers/'
    )
    tx_response = get_parsed_url_response(url)

    books = []
    if not tx_response: return books

    content = tx_response.find('div', { 'class': 'article-content' })
    if not content:
        tx_response.decompose()
        return books

    author_pre_re = re.compile('^.+by\s+')

    print('Extracting books info')
    paragraphs = content.findAll('p')
    for paragraph in paragraphs:
        # Get first 'em' element in paragraph.
        if not paragraph.em: continue

        book_tag    = (paragraph.em.b or paragraph.em.a)
        book_author = author_pre_re.sub('', paragraph.contents[1])
        # Fetch book isbn from site.
        book_isbn   = _get_tx_book_isbn(paragraph.a['href'])

        book = {
            'title':  book_tag.text,
            'author': book_author,
            'isbn':   book_isbn,
        }

        books.append(book)
        print_progress()

    tx_response.decompose()
    print_progress_end()

    print('Fetching polish editions')
    books_pl_info = get_gr_books_pl_info(books)
    print_progress_end()

    return (books_pl_info, u'Ted recommendations')
# }}}

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def _get_tx_book_isbn(book_url):
    if not book_url: return

    response = get_url_response(book_url)
    if not response: return

    response_url    = response.geturl()
    parsed_response = parse_url_response(response)
    if not parsed_response: return

    isbn_value = None
    if re.compile('amazon').search(response_url):
        details_tag = (
            # amazon.co.uk
            parsed_response.find('div', {'id': 'detail_bullets_id'}) or
            # amazon.com
            parsed_response.find('div', {'id': 'detail-bullets'})
        )
        info_tags = details_tag.find('div', {'class': 'content'}).ul.findAll('li')

        for li in info_tags:
            if li.b.text.startswith('ISBN'):
                isbn_value = li.contents[1].lstrip()
                break
    elif re.compile('ecstore').search(response_url):
        # TODO
        pass

    parsed_response.decompose()

    return isbn_value

def process_page():
    return ted_recommendations()

def main():
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-a", "--auth-data")

    (options, args) = option_parser.parse_args()

    # Fetch books entries to iterate over.
    books_list, shelf_name = process_page()
    if not books_list: return

    # Write results to given format.
    print('Writing found books')
    if options.auth_data:
        write_rows_to_worksheet(
            get_service_client(options.auth_data),
            u'Karty',
            shelf_name,
            [
                [book[header] for header in WORKSHEET_HEADERS]
                for book in books_list
            ]
        )
    else:
        make_xls(
            'book_import',
            shelf_name,
            WORKSHEET_HEADERS,
            books_list
        )

if __name__ == "__main__":
    main()
