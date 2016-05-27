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

def global_reading_list_80_books(): # {{{
    url = (
        'http://bookriot.com/2016/04/28/'
        'around-world-80-books-global-reading-list/'
    )

    content_attrs = { 'itemprop': 'articleBody' }

    def books_generator(paragraphs):
        author_pre_re   = re.compile('(?:^.*\W*by\s+)|(?:\:.*$)')
        country_post_re = re.compile(u'\s\u2013\xa0$')
        for paragraph in paragraphs:
            # Get first 'em' element in paragraph.
            if not paragraph.em: continue

            book_tag     = paragraph.em.a
            book_country = (paragraph.contents[1]
                            if paragraph.img 
                            else paragraph.contents[0])
            book_author  = paragraph.findAll('strong')[-1].contents[-1]

            book = {
                'title':   book_tag.text,
                'country': country_post_re.sub('', book_country),
                'author':  author_pre_re.sub('', book_author),
                'href':    (paragraph.a['href']
                            if paragraph.a.has_key('href')
                            else None),
            }

            yield(book)

    worksheet_name = u'80 books'

    return maybe_fetch_books_info(
        url, content_attrs, books_generator, worksheet_name
    )
# }}}

def ted_recommendations(): # {{{
    url = (
        'http://ideas.ted.com/'
        'your-holiday-reading-list-58-books-recommended-by-ted-speakers/'
    )

    content_attrs = { 'class': 'article-content' }

    def books_generator(paragraphs):
        author_pre_re = re.compile('^.+by\s+')
        for paragraph in paragraphs:
            # Get first 'em' element in paragraph.
            if not paragraph.em: continue

            book_tag    = (paragraph.em.b or paragraph.em.a)
            book_author = paragraph.contents[1]

            book = {
                'title':  book_tag.text,
                'author': author_pre_re.sub('', book_author),
                'href':   (paragraph.a['href']
                           if paragraph.a.has_key('href')
                           else None),
            }
            yield(book)

    worksheet_name = u'Ted recommendations'

    return maybe_fetch_books_info(
        url, content_attrs, books_generator, worksheet_name
    )
# }}}

def maybe_fetch_books_info(url, content_attrs, books_generator, worksheet_name): # {{{
    print('Fetching books list')
    tx_response = get_parsed_url_response(url)

    books = []
    if not tx_response: return books

    content = tx_response.find('div', content_attrs)
    if not content:
        tx_response.decompose()
        return books

    print('Extracting books info')
    for book in (books_generator(content.findAll('p'))):
        if book.has_key('href'):
            book['isbn'] = _get_tx_book_isbn(book['href'])

        books.append(book)
        print_progress()

    tx_response.decompose()
    print_progress_end()

    print('Fetching polish editions')
    books_pl_info = get_gr_books_pl_info(books)
    print_progress_end()

    return (books_pl_info, worksheet_name)
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
    return global_reading_list_80_books()

def main():
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-a", "--auth-data")

    (options, args) = option_parser.parse_args()

    # Fetch books entries to iterate over.
    books_list, worksheet_name = process_page()
    if not books_list: return

    # Write results to given format.
    print('Writing found books')
    if options.auth_data:
        write_rows_to_worksheet(
            get_service_client(options.auth_data),
            u'Karty',
            worksheet_name,
            [
                [book[header] for header in WORKSHEET_HEADERS]
                for book in books_list
            ]
        )
    else:
        make_xls(
            'book_import',
            worksheet_name,
            WORKSHEET_HEADERS,
            books_list
        )

if __name__ == "__main__":
    main()
