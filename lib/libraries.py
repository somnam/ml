#!/usr/bin/python -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import time
import urllib2
from BeautifulSoup import BeautifulSoup
from lib.common import prepare_opener, open_url, get_json_file
from lib.automata import (
    browser_select_by_id_and_value,
    wait_is_visible,
    wait_is_not_visible,
)
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
# }}}

LIBRARIES_DATA = get_json_file('opac.json')

class n4949(object):
    url   = LIBRARIES_DATA['4949']['url']
    title = LIBRARIES_DATA['4949']['title']

    def __init__(self):
        self.opener = prepare_opener(n4949.url)
        # Request used to initialize cookie.
        open_url(n4949.url, self.opener)

    def pre_process(self, browser):
        # Clear opac site.
        print(u'Clearing search form.')
        browser.find_element_by_id('form1:textField1').clear()
        return

    def post_process(self, browser):
        pass

    # Search type:
    # 1 - Author
    # 2 - Title
    # 3 - ISBN
    # 4 - Series
    # Resource type:
    # 1  - All
    # 2  - Book
    # 9  - Magazine
    # 15 - Audiobook
    def query_book(self, browser, search_value, search_field):
        search_type, resource_type = None, None
        if search_field == 'isbn':
            print(u'Querying book by isbn "%s" .' % search_value)
            search_type, resource_type = '3', '2'
        elif search_field == 'title':
            print(u'Querying book by title.')
            search_type, resource_type = '2', '2'

        # Input search value.
        text_field = browser.find_element_by_id('form1:textField1')
        text_field.send_keys(search_value)

        # Hide autocomplete popup.
        autocomplete_popup = 'autoc1'
        wait_is_visible(browser, autocomplete_popup)
        text_field.send_keys(Keys.ESCAPE)
        wait_is_not_visible(browser, autocomplete_popup)

        # Set search type.
        browser_select_by_id_and_value(browser, 'form1:dropdown1', search_type)

        # Set resource_type.
        browser_select_by_id_and_value(browser, 'form1:dropdown4', resource_type)

        # Submit form.
        print(u'Submitting form.')
        submit = browser.find_element_by_id('form1:btnSzukajIndeks')
        submit.click()

        # Wait for results to appear.
        results         = None
        results_wrapper = browser.find_element_by_class_name(
            'hasla'
        )
        if (results_wrapper):
            results = results_wrapper.find_elements_by_tag_name(
                'a'
            )

        # Return search results.
        print(u'Returning search results.')
        return results

    def get_matching_result(self, browser, search_value, search_field, results):
        if not results:
            print(u'No match found.')
            return

        replace_from = '-' if search_field == 'isbn' else ' '
        match_value  = search_value.replace(replace_from, '')
        print(u'Matching for value by field "%s".' % search_field)

        match = None
        for elem in results:
            if elem.text.lstrip().replace(replace_from, '') == match_value:
                print(u'Found match.')
                elem.click()
                match = elem.find_element_by_xpath('..') \
                            .find_element_by_class_name('zawartosc') \
                            .find_element_by_tag_name('a')
                break

        if not match:
            print(u'No match found.')

        return match

    def get_url_response(self, url):
        response = None
        if url:
            response = self.opener.open(urllib2.Request(url)).read()
        return response

    def extract_book_info(self, browser, book, match):
        if not (book and match):
            return

        print(u'Redirecting to book info.')
        book_url = match.get_attribute('href')
        response = self.get_url_response(book_url)

        print(u'Fetching book infos.')
        div = BeautifulSoup(
            response,
            convertEntities=BeautifulSoup.HTML_ENTITIES
        ).find('div', { 'id': 'zasob' })
        warnings = div.findAll('div', { 'class': 'opis_uwaga' })
        infos    = [ div.parent for div in warnings ]

        re_department   = re.compile('\([^\)]+\)')
        re_address      = re.compile('\,[^\,]+\,')

        # Fetch department, address and availability info.
        info_by_library = []
        for i in range(len(infos)):
            print(u'Fetching department, address and availability info %d.' % i)
            info, warning = infos[i].text, warnings[i].text

            # Get department string.
            department = re_department.search(info)
            if department:
                department = department.group()

            # Get address string.
            address = re_address.search(info)
            if address:
                address = address.group().replace(',', '').lstrip()

            # Get availability info.
            availability = warning
            if not availability:
                availability = u'Dostępna'

            info_by_library.append(
                '%s - %s - %s' % 
                (department, address, availability)
            )

        div.decompose()

        return "\n".join(info_by_library)

    def get_book_info(self, browser, book, search_field):
        if not(book.has_key(search_field) and book[search_field]):
            return

        # Query book and fetch results.
        results = self.query_book(
            browser, book[search_field], search_field
        )
        match   = self.get_matching_result(
            browser, book[search_field], search_field, results
        )
        info    = self.extract_book_info(browser, book, match)

        if info:
            print(u'Book info found.')
        else:
            print(u'Failed fetching book info.')

        return info

class n5004(object):
    url   = LIBRARIES_DATA['5004']['url']
    title = LIBRARIES_DATA['5004']['title']

    def pre_process(self, browser):
        pass

    def post_process(self, browser):
        button = browser.find_element_by_id('logo_content')
        link   = button.find_element_by_tag_name('a')
        link.click()

    def set_search_type_and_value(self, browser, type_name, type_value, search_name, search_value):
        # Set search type.
        browser_select_by_id_and_value(browser, type_name, type_value)
        # Input search value.
        browser.find_element_by_id(search_name).send_keys(search_value)

    def query_book(self, browser, book, search_field):
        search_value = book[search_field]
        type_value   = 'm21isn' if search_field == 'isbn' else 'nowy'
        self.set_search_type_and_value(
            browser, 'IdSzIdx1', type_value, 'IdTxtSz1', search_value
        )
        if search_field != 'isbn':
            self.set_search_type_and_value(
                browser, 'IdSzIdx2', 'if100a', 'IdTxtSz2', book['author']
            )

        # Submit form.
        submit = browser.find_element_by_id('search')
        submit.click()

        # Search for results in table.
        results = None
        try:
            browser.find_element_by_class_name('emptyRecord')
        except NoSuchElementException:
            results = browser.find_elements_by_class_name(
                'opisokladka'
            );

        return results

    def get_matching_result(self, browser, book, search_field, results):
        if not results: return

        match = None
        # Only one result should be returned when searching by ISBN.
        if search_field == 'isbn' and len(results) == 1:
            match = results[0].find_element_by_tag_name('a')
        else:
            info_re = re.compile(r'^(.+)\.\s-.*$')
            for result in results:
                # Extract title and author form entry.
                info = info_re.search(result.text)
                if not info: continue

                # Check if author and title match.
                info_match = info.group(1)
                if not info_match: continue

                title, author = info_match.split('/')
                if re.search(book['author'], author) and \
                   re.search(book['title'], title):
                    match = result.find_element_by_tag_name('a')
                    break
        return match

    def extract_book_info(self, browser, book, match):
        if not match: return

        # Click book link
        match.click()

        # Search for book info.
        info_table = None
        try:
            info_table = browser.find_element_by_xpath(
                '//table[@class="tabOutWyniki_w"]'
            )
        except NoSuchElementException:
            return

        # Extract book info from rows.
        info_rows = info_table.find_elements_by_class_name('tdOutWyniki_w')

        # Pack results.
        headers_len, book_info = 5, []
        found_rows_num = len(info_rows) / headers_len
        for row_num in range(found_rows_num):
            range_start = row_num * headers_len
            range_end   = range_start + headers_len
            book_info.append('-'.join(map(
                lambda r: r.text,
                info_rows[range_start:range_end]
            )))

        return "\n".join(book_info)

    def get_book_info(self, browser, book, search_field):
        if not(book.has_key(search_field) and book[search_field]):
            return

        # Query book and fetch results.
        results = self.query_book(browser, book, search_field)
        match   = self.get_matching_result(
            browser, book, search_field, results
        )
        info    = self.extract_book_info(browser, book, match)

        return info
