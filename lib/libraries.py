#!/usr/bin/python -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import time
import socket
import cookielib
from fuzzywuzzy import fuzz
from lib.common import prepare_opener, open_url, get_json_file, get_parsed_url_response
from lib.automata import (
    browser_start,
    browser_stop,
    browser_timeout,
    browser_select_by_id_and_value,
    wait_is_visible,
    wait_is_not_visible,
)
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
# }}}

LIBRARIES_DATA = get_json_file('opac.json')

class LibraryBase(object):
    socket_timeout = 10.0

    def __init__(self, books=None):
        self.opener  = None
        self.browser = None
        self.books   = [] if books is None else books

    def init_browser(self):
        # Request used to initialize cookie.
        self.cookie_jar = cookielib.CookieJar()
        self.opener     = prepare_opener(self.data['url'], cookie_jar=self.cookie_jar)
        open_url(self.data['url'], self.opener)

        # Set timeout for request.
        socket.setdefaulttimeout(self.socket_timeout)

        # Try to load browser.
        self.retry_load_browser()

    def retry_load_browser(self):
        retry_start = 2
        while not self.browser and retry_start:
            try:
                self.browser = browser_start()
                print(u'Loading search form.')
                self.browser.get(self.data['url'])
                if 'title' in self.data and self.data['title']:
                    assert self.data['title'] in self.browser.title
            except socket.timeout:
                print(u'Browser start timed out.')
                retry_start -= 1
                if retry_start:
                    print(u'Retry starting browser')
                else:
                    print(u"Browser start failed.")
                    raise

    def stop_browser(self):
        # Quit browser.
        if self.browser: browser_stop(self.browser)
        # Restore default timeout value.
        socket.setdefaulttimeout(None)

    def get_books_status(self):
        self.init_browser()

        # Will contain books info.
        books_status = []
        for book in self.books:
            book_info = self.get_book_info(book)
            books_status.append(book_info)

        self.stop_browser()

        return books_status

    def get_book_info(self, book):
        book_info = None
        # Retry fetching book info (title vs isbn).
        retry_fetch = 2
        while not book_info and retry_fetch:
            # Start browser if required.
            self.retry_load_browser()
            # Check if browser actually started - can't continue without it.
            if not self.browser: break

            # Search first by isbn, then by title.
            search_field = 'title' if retry_fetch % 2 else 'isbn'

            # Try fetching book info.
            try:
                # Fetch book info.
                self.pre_process()
                book_info = self.query_book_info(book, search_field)
                self.post_process()
            except socket.timeout:
                print(u'Querying book info timed out.')
                browser_timeout(self.browser)
                # Retry fetching book with same params and a new browser.
                if not book_info: continue
            finally:
                # Is called when except does 'continue'
                retry_fetch -= 1

            if book_info:
                print(u'Successfully queried book info.')
                break
            elif retry_fetch:
                print(u'Retry book fetching.')
            else:
                print(u'Book fetching failed.')

        return {
            'author': book['author'],
            'title' : '"%s"' % book['title'],
            'info'  : book_info if book_info else "Brak",
        }

    def query_book_info(self, book, search_field):
        if not(book.has_key(search_field) and book[search_field]):
            return

        # Query book and fetch results.
        results = self.query_book(book, search_field)
        match   = self.get_matching_result(book, search_field, results)
        info    = self.extract_book_info(book, match)

        return info

class n4949(LibraryBase):
    data = LIBRARIES_DATA['4949']

    def pre_process(self):
        # Clear opac site.
        self.browser.find_element_by_id('form1:textField1').clear()

    def post_process(self):
        # Sleep for short time to avoid frequent requests.
        time.sleep(0.2)

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
    def query_book(self, book, search_field):
        search_value = book[search_field]
        search_type, resource_type = None, None
        if search_field == 'isbn':
            search_type, resource_type = '3', '2'
        elif search_field == 'title':
            search_type, resource_type = '2', '2'

        # Input search value.
        text_field = self.browser.find_element_by_id('form1:textField1')
        text_field.send_keys(search_value)

        # Hide autocomplete popup.
        autocomplete_popup = 'autoc1'
        wait_is_visible(self.browser, autocomplete_popup)
        text_field.send_keys(Keys.ESCAPE)
        wait_is_not_visible(self.browser, autocomplete_popup)

        # Set search type.
        browser_select_by_id_and_value(self.browser, 'form1:dropdown1', search_type)

        # Set resource_type.
        browser_select_by_id_and_value(self.browser, 'form1:dropdown4', resource_type)

        # Submit form.
        submit = self.browser.find_element_by_id('form1:btnSzukajIndeks')
        submit.click()

        # Wait for results to appear.
        results         = None
        results_wrapper = self.browser.find_element_by_xpath('//ul[@class="kl"]')
        if (results_wrapper):
            results = results_wrapper.find_elements_by_xpath('//li/a')

        # Return search results.
        return results

    def get_matching_result(self, book, search_field, results):
        if not results:
            print(u'No match found.')
            return

        return (self.get_matching_result_isbn(book, results) 
                if search_field == 'isbn'
                else self.get_matching_result_name(book, results))

    def get_matching_result_isbn(self, book, results):
        match_value = book['isbn'].replace('-', '')

        print(u'Matching for value by field "isbn".')
        matching = []
        for elem in results:
            elem_value = elem.text.lstrip().replace('-', '')
            if elem_value != match_value: continue

            matching = self.extract_matching_results(elem)
            break

        return matching

    def get_matching_result_name(self, book, results):
        match_value = book['title']

        print(u'Matching for value by field "title".')
        matching = []
        for elem in results:
            elem_value  = elem.text.lstrip()
            match_ratio = fuzz.partial_ratio(match_value, elem_value)

            if match_ratio < 95: continue
            matching = self.extract_matching_results(elem)
            break

        return matching

    def extract_matching_results(self, elem):
        elem.click()
        content = elem.find_element_by_xpath('..') \
                      .find_element_by_class_name('zawartosc')
        results = []
        try:
            results = content.find_elements_by_xpath('//img[@title="Książka"]/..')
        except NoSuchElementException:
            print(u'Empty results list.')

        return results

    def extract_book_info(self, book, results):
        if not (book and results):
            return

        re_department = re.compile('\([^\)]+\)')
        re_address    = re.compile('\,[^\,]+\,')

        info_by_library = []
        print(u'Fetching %d editions info.' % len(results))
        for match in results:
            book_url = match.get_attribute('href')
            response = get_parsed_url_response(book_url, opener=self.opener)

            div      = response.find('div', { 'id': 'zasob' })
            warnings = div.findAll('div', { 'class': 'opis_uwaga' })
            infos    = [ div.parent for div in warnings ]

            # Fetch department, address and availability info.
            for i in range(len(infos)):
                info, warning = infos[i].text, warnings[i].text

                # Get address string.
                address = re_address.search(info)
                if address:
                    address = address.group().replace(',', '').lstrip()
                # Check if address is in accepted list.
                if not address in self.data['accepted_address']: continue

                # Get department string.
                department = re_department.search(info)
                if department:
                    department = department.group()

                # Get availability info.
                availability = warning if warning else u'Dostępna'

                info_by_library.append(
                    '%s - %s - %s' % 
                    (department, address, availability)
                )

            response.decompose()

            # Sleep for short time to avoid frequent requests.
            time.sleep(0.1)

        if info_by_library:
            print(u'Found match.')

        return "\n".join(info_by_library) if info_by_library else None

class n5004(LibraryBase):
    data = LIBRARIES_DATA['5004']

    def pre_process(self):
        # Close alert box if present.
        try:
            alert_box = self.browser.find_element_by_id('alertboxsec')
            button    = alert_box.find_element_by_tag_name('button')
            button.click()
        except NoSuchElementException:
            pass

    def post_process(self):
        button = self.browser.find_element_by_id('logo_content')
        link   = button.find_element_by_tag_name('a')
        link.click()

    def set_search_type_and_value(self, type_id, type_value, search_id, search_value):
        can_search = (
            wait_is_visible(self.browser, type_id) and
            wait_is_visible(self.browser, search_id)
        )

        if can_search:
            # Set search type.
            browser_select_by_id_and_value(self.browser, type_id, type_value)
            # Input search value.
            self.browser.find_element_by_id(search_id).send_keys(search_value)

        return can_search

    def query_book(self, book, search_field):
        search_value = book[search_field]
        type_value   = 'm21isn' if search_field == 'isbn' else 'm21tytuł'
        can_search   = self.set_search_type_and_value(
            'IdSzIdx1', type_value, 'IdTxtSz1', search_value
        )
        if search_field != 'isbn':
            can_search = self.set_search_type_and_value(
                'IdSzIdx2', 'if100a', 'IdTxtSz2', book['author']
            )

        # Search fields didn't load properly - can't run query.
        if not can_search: return None

        # Submit form.
        submit = self.browser.find_element_by_id('search')
        submit.click()

        # Search for results in table.
        results = None
        try:
           self.browser.find_element_by_class_name('emptyRecord')
        except NoSuchElementException:
            results = self.browser.find_elements_by_class_name('opisokladka');

        return results

    def get_matching_result(self, book, search_field, results):
        if not results: return

        matching = []
        # Only one result should be returned when searching by ISBN.
        if search_field == 'isbn' and len(results) == 1:
            matching.append(results[0].find_element_by_tag_name('a'))
        else:
            info_re = re.compile(r'^(.+)\s;\s.*$')
            for result in results:
                # Extract title and author form entry.
                info = info_re.search(result.text)
                if not info: continue

                # Check if author and title match.
                info_match = info.group(1)
                if not info_match: continue

                title, author = info_match.split('/')
                title_ratio   = fuzz.partial_ratio(book['title'], title)
                author_ratio  = fuzz.partial_ratio(book['author'], author)
                if title_ratio < 95 and author_ratio < 95: continue

                matching.append(result.find_element_by_tag_name('a'))

        return matching

    def extract_book_info(self, book, results):
        if not (book and results): return

        onclick_re = re.compile(r"^javascript:LoadWebPg\('([^']+)',\s'([^']+)'\);.*$")

        # Get session cookie.
        session_cookie = next(
            (cookie for cookie in self.cookie_jar if cookie.name == 'idses'), None
        )
        session_id     = session_cookie.value if session_cookie else None

        headers_len, book_info = 5, []
        for match in results:
            onclick_match = onclick_re.search(match.get_attribute('onclick'))
            if not onclick_match: continue

            url_suffix, url_params = onclick_match.groups()

            book_url = '{0}{1}?ID1={2}&ln=pl{3}'.format(
                self.data['base_url'], url_suffix, session_id, url_params
            )

            response = get_parsed_url_response(book_url, opener=self.opener)
            if not response: continue

            # Extract book info from rows.
            info_table = response.find('table', {'class': 'tabOutWyniki_w'})
            info_rows  = info_table.findAll('td', {'class': 'tdOutWyniki_w'})

            # Pack results.
            found_rows_num = len(info_rows) / headers_len
            for row_num in range(found_rows_num):
                range_start = row_num * headers_len
                range_end   = range_start + headers_len
                book_info.append(' '.join(
                    row.text for row in info_rows[range_start:range_end]
                ))

        return "\n".join(book_info) if book_info else None
