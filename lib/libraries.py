#!/usr/bin/python -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import time
import socket
from fuzzywuzzy import fuzz
from filecache import filecache
from lib.common import (
    open_url,
    get_json_file,
    prepare_opener,
    get_parsed_url_response,
    get_url_query_string,
    get_url_net_location,
)
from lib.automata import (
    browser_start,
    browser_stop,
    set_input_value,
    select_by_id_and_value,
    wait_is_visible,
    wait_is_not_visible,
)
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
# }}}

LIBRARIES_DATA = get_json_file('opac.json')

class LibraryBase(object):
    def __init__(self, books=None):
        self.opener  = None
        self.browser = None
        self.books   = [] if books is None else books

    def pre_process(self):
        pass

    def init_browser(self):
        # Request used to initialize opener.
        self.opener = prepare_opener(self.data['url'])

        # Get redirect url from site response
        redirect_url = open_url(self.data['url'], self.opener).geturl()

        # Get base url from redirect.
        self.net_location = get_url_net_location(redirect_url)

        # Get query params from redirect.
        self.query_string = get_url_query_string(redirect_url)

        # Try to load browser.
        self.retry_load_browser()

    def retry_load_browser(self):
        retry_start = 2
        while not self.browser and retry_start:
            try:
                self.browser = browser_start()
                self.browser.get(self.data['url'])
                if 'title' in self.data and self.data['title']:
                    assert self.data['title'] in self.browser.title
            except socket.timeout:
                print(u'Browser start timed out.')
                browser_stop(self.browser)
                retry_start -= 1
                if retry_start:
                    print(u'Retry starting browser')
                else:
                    print(u"Browser start failed.")
                    raise

    def stop_browser(self):
        # Quit browser.
        if self.browser: browser_stop(self.browser)

    def get_books_status(self):
        self.init_browser()

        cached_book_info_wrapper = self.cached_book_info_wrapper()

        # Will contain books info.
        books_status = []
        for book in self.books:
            book_info = cached_book_info_wrapper(book)
            books_status.append(book_info)

        self.stop_browser()

        return books_status

    def cached_book_info_wrapper(self):
        @filecache(24 * 60 * 60)
        def get_cached_book_info(book):
            return self.get_book_info(book)
        return get_cached_book_info

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
                browser_stop(self.browser)
                # Remove object.
                self.browser = None
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
            'title' : u'"{0}"'.format(book['title']),
            'info'  : book_info if book_info else "Brak",
            'pages' : book['pages'],
            'link'  : book['url'],
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

    isbn_re    = re.compile('\D+')
    section_re = re.compile('\([^\)]+\)')

    search_type_id     = 'form1:dropdown1'
    resource_type_id   = 'form1:dropdown4'
    clear_button_id    = 'form1:btnCzyscForme'

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
        return (self.query_book_by_isbn(book)
                if search_field == 'isbn'
                else self.query_book_by_title(book))

    def select_form(self, form_type):
        # Select standard or advanced form.
        links_wrapper = self.browser.find_element_by_class_name('historia')
        for link in links_wrapper.find_elements_by_tag_name('a'):
            if link.text != form_type: continue
            link.click()
            break

        # Clear form before using.
        if (wait_is_visible(self.browser, self.clear_button_id)):
            clear = self.browser.find_element_by_id(self.clear_button_id)
            clear.click()

        return

    def hide_autocomplete_popup(self, text_field_id, autocomp_popup_id):
        if (wait_is_visible(self.browser, autocomp_popup_id)):
            text_field = self.browser.find_element_by_id(text_field_id)
            text_field.send_keys(Keys.ESCAPE)
            wait_is_not_visible(self.browser, autocomp_popup_id)

    def query_book_by_isbn(self, book):
        search_type        = '3'
        resource_type      = '2'
        submit_button_id   = 'form1:btnSzukajIndeks'
        results_list_xpath = '//ul[@class="kl"]'

        # Select standard form.
        self.select_form(u'Indeks')

        # Input search value.
        set_input_value(self.browser, 'form1:textField1', book['isbn'])

        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField1', 'autoc1')

        # Set search type.
        select_by_id_and_value(self.browser, self.search_type_id, search_type)

        # Set resource_type.
        select_by_id_and_value(self.browser, self.resource_type_id, resource_type)

        # Submit form.
        results = None
        if (wait_is_visible(self.browser, submit_button_id)):
            submit = self.browser.find_element_by_id(submit_button_id)
            submit.click()

            # Wait for results to appear.
            if (wait_is_visible(self.browser, results_list_xpath, By.XPATH)):
                results_wrapper = self.browser.find_element_by_xpath(
                    results_list_xpath
                )
                results = results_wrapper.find_elements_by_xpath('li/a')

        # Return search results.
        return results

    def query_book_by_title(self, book):
        resource_type    = '2'
        submit_button_id = 'form1:btnSzukajOpisow'

        # Select advanced form.
        self.select_form(u'Złożone')

        # Input book author.
        author_name_list = book['author'].split(' ')
        author_string    = u'{0}, {1}'.format(
            author_name_list.pop(),
            ' '.join(author_name_list)
        )
        set_input_value(self.browser, 'form1:textField1', author_string)
        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField1', 'autoc1')

        # Input book title.
        set_input_value(self.browser, 'form1:textField2', book['title'])
        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField2', 'autoc2')

        # Set resource_type.
        select_by_id_and_value(self.browser, self.resource_type_id, resource_type)

        results = None
        if (wait_is_visible(self.browser, submit_button_id)):
            submit = self.browser.find_element_by_id(submit_button_id)
            submit.click()

            if (wait_is_visible(self.browser, 'opisy')):
                results = self.browser.find_elements_by_class_name('opis')

        # Return search results.
        return results

    def get_matching_result(self, book, search_field, results):
        if not results: return

        return (self.get_matching_result_isbn(book, results) 
                if search_field == 'isbn'
                else self.get_matching_result_title(book, results))

    def get_matching_result_isbn(self, book, results):
        match_value = book['isbn'].replace('-', '')

        matching = []
        for elem in results:
            # Replace all non-numeric characters in isbn.
            elem_value = self.isbn_re.sub('', elem.text)
            if elem_value != match_value: continue

            matching = self.extract_matching_results(elem)
            break

        return matching

    def get_matching_result_title(self, book, results):
        match_value = book['title']

        matching = []
        for elem in results:
            book_id = elem.get_attribute('id').replace('dvop', '')
            matching.append('{0}{1}{2}'.format(
                self.net_location,
                self.data['book_url_suffix'],
                book_id
            ))

        return matching

    def extract_matching_results(self, elem):
        elem.click()
        content = elem.find_element_by_xpath('..') \
                      .find_element_by_class_name('zawartosc')
        results = []
        try:
            results = [match.get_attribute('href') 
                       for match in content.find_elements_by_tag_name('a')]
        except NoSuchElementException:
            pass

        return results

    def extract_book_info(self, book, results):
        if not (book and results):
            return

        re_unavailable = re.compile('Brak\szasobu')

        info_by_library = []
        for book_url in results:
            response = get_parsed_url_response(book_url, opener=self.opener)
            resource = response.find('div', { 'id': 'zasob' })
            if (not resource or
                not resource.contents or
                re_unavailable.match(resource.text)
            ):
                response.decompose()
                continue

            ul = resource.find('ul', { 'class': 'zas_filie' })
            for li in ul.findAll('li'):
                department_info = li.find('div', { 'class': 'filia' })

                # Get library address.
                department, address = '', ''
                if (department_info and department_info.contents):
                    department = department_info.contents[0]
                    location   = (department_info.contents[-1].split(',')
                                  if department_info.contents[-1] else '')
                    address    = (location[0] if location else '')

                # Check if address is in accepted list.
                if not address in self.data['accepted_address']: continue

                # Get availability info.
                availability_info = li.find('div', { 'class': 'dostepnosc' })
                availability_info = (availability_info.text.split("\n")
                                     if availability_info else [])

                warning = li.find('div', { 'class': 'opis_uwaga' })

                not_available_str = u'Pozycja nie do wypożyczenia'
                not_available     = li.find('img', { 'title': not_available_str })

                # Extract availability string
                availability = ''
                if not_available:
                    availability = not_available_str
                elif warning and warning.text:
                    availability = warning.text
                elif availability_info and availability_info[0]:
                    availability = availability_info[0].strip()

                # Extract section name.
                section_info  = (warning.previous.strip() if warning.previous else '')
                section_match = self.section_re.search(section_info)
                section       = (section_match.group() if section_match else '')

                info_by_library.append(u'{0} - {1} - {2} - {3}'.format(
                    department, address, section, availability
                ))

            response.decompose()

            # Sleep for short time to avoid frequent requests.
            time.sleep(0.1)

        return "\n".join(info_by_library) if info_by_library else None

class n5004(LibraryBase):
    data = LIBRARIES_DATA['5004']

    info_re    = re.compile(u'^(.+)\.\s-\s.*$')
    tr_re      = re.compile(u'^(.+)\s;\s(?:przeł|\[tł).*$')
    onclick_re = re.compile(u"^javascript:LoadWebPg\('([^']+)',\s'([^']+)'\);.*$")

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
            select_by_id_and_value(self.browser, type_id, type_value)
            # Input search value.
            self.browser.find_element_by_id(search_id).send_keys(
                search_value
            )

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
            results = self.browser.find_elements_by_class_name('opisokladka')

        return results

    def get_matching_result(self, book, search_field, results):
        if not results: return

        matching = []
        # Only one result should be returned when searching by ISBN.
        if search_field == 'isbn' and len(results) == 1:
            matching.append(results[0].find_element_by_tag_name('a'))
        else:
            for result in results:
                info = self.info_re.search(result.text)
                if not info: continue

                info_match = info.group(1)

                # Check if entry contains translation info.
                tr_match = self.tr_re.search(info_match)
                # Remove translation info.
                if tr_match: info_match = tr_match.group(1)

                if not info_match: return

                # Extract title and author form entry.
                title, author = info_match.split('/')
                # Check if author and title match.
                title_ratio   = fuzz.partial_ratio(book['title'], title)
                author_ratio  = fuzz.partial_ratio(book['author'], author)
                # If title or author matches > 95% then collect results.
                if title_ratio < 95 and author_ratio < 95: continue

                matching.append(result.find_element_by_tag_name('a'))

        return matching

    def extract_book_info(self, book, results):
        if not (book and results): return

        headers_len, book_info = 5, []
        for match in results:
            onclick_match = self.onclick_re.search(match.get_attribute('onclick'))
            if not onclick_match: continue

            url_suffix, query_params = onclick_match.groups()

            book_url = '{0}{1}?{2}{3}'.format(
                self.data['base_url'], url_suffix, self.query_string, query_params
            )

            response = get_parsed_url_response(book_url, opener=self.opener)
            if not response: continue

            # Extract book info from rows.
            info_table = response.find('table', {'class': 'tabOutWyniki_w'})
            info_rows  = (info_table.findAll('td', {'class': 'tdOutWyniki_w'})
                          if info_table else None)
            if not info_rows:
                response.decompose()
                continue

            # Pack results.
            found_rows_num = len(info_rows) / headers_len
            for row_num in range(found_rows_num):
                range_start = row_num * headers_len
                range_end   = range_start + headers_len
                book_info.append(' '.join(
                    row.text for row in info_rows[range_start:range_end]
                ))

            response.decompose()

        return "\n".join(book_info) if book_info else None
