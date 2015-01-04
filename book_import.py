#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import urllib
from imogeen import get_parsed_url_response
# }}}

def ny_times_100_notable_books_of_2014():
    url = (
        'http://www.nytimes.com/2014/12/07/books/review/'
        '100-notable-books-of-2014.html'
    )
    response = get_parsed_url_response(
        url, 
        urllib.urlencode({ '_r': 0 })
    )

    result = []
    if response:
        # Fetch article paragraphs.
        paragraphs = response.findAll('p', { 'itemprop': 'articleBody' })
        for paragraph in paragraphs:
            author = paragraph.find('em')
            if author:
                author.string.encode('utf-8')

            # Get title container.
            title = (paragraph.find('strong') or paragraph.find('a'))
            if title:
                # Fetch title value.
                if title.find('a'):
                    title = paragraph.find('strong').find('a')
                elif title.find('strong'):
                    title = paragraph.find('a').find('strong')

                # Additional processing.
                if title:
                    # Convert to utf-8.
                    title = title.string.encode('utf-8')
                    # 

            if title:
                # Book found.
                if author:
                    # print("Book: %s, %s" % (title, author))
                    print("Book: %s" % title)
                else:
                    print('Category: %s' % title)

        response.decompose()

    return result

def page_processors():
    return [
        ny_times_100_notable_books_of_2014,
    ]

def main():
    # Fetch books entries to iterate over.
    books_list = [
        book
        for processor in page_processors()
        for book in processor()
    ]

    if books_list:
        # Dump book list to json.
        pass

if __name__ == "__main__":
    main()
