# -*- coding: utf-8 -*-

# Import {{{
import re
import json
import time
import socket
from math import floor
from fuzzywuzzy import fuzz
from lib.diskcache import diskcache, DAY
from lib.common import (
    open_url,
    get_config,
    prepare_opener,
    encode_url_params,
    get_parsed_url_response,
    get_url_query_string,
    get_url_net_location,
    get_unverifield_ssl_handler,
)
from lib.automata import (
    browser_start,
    browser_stop,
    set_input_value,
    select_by_id_and_value,
    wait_is_visible,
    wait_is_visible_by_css,
    wait_is_not_visible,
)
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
# }}}

LIBRARIES_DATA = get_config('opac')['libraries']

class LibraryBase(object): # {{{
    handlers = []

    def __init__(self, books=None):
        self.opener  = None
        self.browser = None
        self.books   = [] if books is None else books

    def get_book_uid(self, book):
        return '{0}:{1}'.format(self.data['id'], book['isbn'])

    def pre_process(self):
        pass

    def post_process(self):
        pass

    def init_browser(self):
        # Request used to initialize opener.
        self.opener = prepare_opener(self.data['url'], handlers=self.handlers)

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
                print('Browser start timed out.')
                browser_stop(self.browser)
                retry_start -= 1
                if retry_start:
                    print('Retry starting browser')
                else:
                    print(u"Browser start failed.")
                    raise

    def stop_browser(self):
        # Quit browser.
        if self.browser: browser_stop(self.browser)

    def get_next_search_field(self, index):
        return self.search_fields[index]

    def get_books_status(self):
        self.init_browser()

        cached_book_info_wrapper = self.cached_book_info_wrapper()

        # Will contain books info.
        books_status = {}
        for book in self.books:
            # Skip if book was already fetched
            book_uid = self.get_book_uid(book)
            if book_uid in books_status: continue
            # Fetch book info
            book_json = cached_book_info_wrapper(book_uid)
            # Don't append empty info.
            if not book_json: continue
            books_status[book_uid] = json.loads(book_json)

        self.stop_browser()

        return [book for entry in books_status.values() for book in entry]

    def cached_book_info_wrapper(self):
        books_by_uid = {self.get_book_uid(book): book for book in self.books}
        @diskcache(DAY)
        def get_cached_book_info(book_uid):
            return self.get_book_info(books_by_uid[book_uid])
        return get_cached_book_info

    def get_book_info(self, book):
        book_info = None
        field_idx = 0

        # Retry fetching book info (title vs isbn).
        search_fields_len = len(self.search_fields)
        while not book_info and field_idx < search_fields_len:
            # Start browser if required.
            self.retry_load_browser()
            # Check if browser actually started - can't continue without it.
            if not self.browser: break

            # Search first by isbn, then by title.
            search_field = self.get_next_search_field(field_idx)

            # Try fetching book info.
            try:
                # Fetch book info.
                self.pre_process()
                book_info = self.query_book_info(book, search_field)
                self.post_process()
            except socket.timeout:
                print('Querying book info timed out.')
                browser_stop(self.browser)
                # Remove object.
                self.browser = None
                # Retry fetching book with same params and a new browser.
                if not book_info: continue
            finally:
                # Is called when except does 'continue'
                field_idx += 1

            # None - book wasn't found, search by other criteria
            # []   - book was found but is unavailable, end search
            is_unavailable = book_info is not None and not book_info

            # Book has been successfully queried or is not for rent.
            if book_info:
                print('Successfully queried book info.')
                # Return info in json format.
                book_info = json.dumps([{
                    'author':     book['author'],
                    'title':      '"{0}"'.format(book['title']),
                    'department': entry[0],
                    'section':    entry[1],
                    'pages':      book['pages'],
                    'link':       book['url'],
                } for entry in book_info])
                break
            # If book is unavailable then don't search for it a second time.
            elif is_unavailable:
                print('Book not available.')
                book_info = None
                break

            # Print next loop info.
            print('Retry book fetching.' if field_idx < search_fields_len else 'Book not found.')

        return book_info

    def query_book_info(self, book, search_field):
        # Query book and fetch results.
        results = self.query_book(book, search_field)
        match   = self.get_matching_result(book, search_field, results)
        info    = self.extract_book_info(book, match)

        return info

    def find_by_css(self, selector):
        return self.browser.find_element_by_css_selector(selector)

    def find_all_by_css(self, selector):
        return self.browser.find_elements_by_css_selector(selector)
# }}}

class n4949(LibraryBase): # {{{
    data = LIBRARIES_DATA['4949']

    search_fields = ['isbn', 'title']

    isbn_re    = re.compile('\D+')
    section_re = re.compile('\s\(\s.+\s\)\s')

    search_type_id     = 'form1:dropdown1'
    resource_type_id   = 'form1:dropdown4'
    clear_button_id    = 'form1:btnCzyscForme'

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
        if not(search_field in book and book[search_field]):
            return

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
        self.select_form('Indeks')

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
        self.select_form('Złożone')

        # Input book author.
        author_name_list = book['author'].split(' ')
        author_string    = '{0}, {1}'.format(
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
        if not (book and results): return

        book_info = []
        for book_url in results:
            response = get_parsed_url_response(book_url, opener=self.opener)
            resource = response.find('div', { 'id': 'zasob' })
            if (not resource or
                not resource.contents or
                resource.text.strip() == 'Brak zasobu'
            ):
                response.decompose()
                continue

            ul = resource.find('ul', { 'class': 'zas_filie' })
            for li in ul.find_all('li'):
                department_info = li.find('div', { 'class': 'filia' })

                # Get library address.
                department, address = '', ''
                if (department_info and department_info.contents):
                    department = department_info.contents[0]
                    location   = (department_info.contents[-1].split(',')
                                  if department_info.contents[-1] else None)
                    address    = (location[0] if location else None)

                # Check if address is in accepted list.
                if not address in self.data['accepted_locations']: continue

                # Check if book is rented/not available.
                warning       = li.find('div', { 'class': 'opis_uwaga' })
                not_available = li.find('img', { 'title': 'Pozycja nie do wypożyczenia' })
                if (not_available or (warning and warning.text)):
                    continue

                # Get availability info.
                availability = [int(d) for d in
                                li.find('div', { 'class': 'dostepnosc' }).text.split()
                                if d.isdigit()]

                # Book is not available.
                if not(availability and availability[0]): continue

                # Extract section name.
                section_info  = li.find('table', {'class': 'zasob'}).td.find_next('td')
                section_match = self.section_re.search(section_info.text)
                section       = section_match.group().strip() if section_match else ''

                book_info.append((department, section))

            response.decompose()

        return book_info
# }}}

class n5004(LibraryBase): # {{{
    data = LIBRARIES_DATA['5004']

    search_fields = ['title_and_author']

    handlers = [get_unverifield_ssl_handler()]

    search_input   = '#SimpleSearchForm_q'
    search_button  = '.btn.search-main-btn'
    results_header = '.row.row-full-text'

    items_list_re     = re.compile('prolibitem')
    item_signature_re = re.compile('dl-horizontal')
    item_available_re = re.compile('Dostępny')

    def pre_process(self):
        # Wait for submit button to be visible.
        try:
            wait_is_visible_by_css(self.browser, self.search_button)
        except NoSuchElementException:
            pass

    def post_process(self):
        try:
            button = self.browser.find_element_by_class_name('library_title-pages')
            link   = button.find_element_by_tag_name('a')
            link.click()
        except NoSuchElementException:
            pass

    def set_search_value(self, search_value):
        # Input search value.
        if wait_is_visible_by_css(self.browser, self.search_input):
            self.find_by_css(self.search_input).send_keys(search_value)
            return True
        return False

    def query_book(self, book, search_field):
        # Search field didn't load properly - can't run query.
        search_value = '"{0}" AND "{1}"'.format(book['title'], book['author'])
        if not self.set_search_value(search_value):
            return None

        # Submit form.
        self.find_by_css(self.search_button).click()

        # Wait for results to load.
        wait_is_visible_by_css(self.browser, self.results_header)

        results = None
        try:
           self.find_by_css('.info-empty')
        except NoSuchElementException:
            # Display up to 100 results on page.
            if wait_is_visible_by_css(self.browser, '.btn-group>.hidden-xs'):
                self.find_by_css('.btn-group>.hidden-xs').click()
                if wait_is_visible_by_css(self.browser, '.btn-group.open>.dropdown-menu'):
                    self.find_by_css('.btn-group.open>.dropdown-menu>li:last-child').click()
            results = self.find_all_by_css('dl.dl-horizontal')
        return results

    def get_matching_result(self, book, search_field, results):
        if not results: return

        matching = []
        for result in results:
            book_anchor = result.find_element_by_tag_name('a')
            if book_anchor:
                matching.append(book_anchor.get_attribute('href'))

        return matching

    def extract_book_info(self, book, results):
        if not (book and results): return

        book_info = None
        for book_url in results:
            # All books are available in the same section.
            if book_info: break

            response   = get_parsed_url_response(book_url, opener=self.opener)
            items_list = response.findAll('div', { 'class': self.items_list_re })
            if not items_list:
                response.decompose()
                continue

            book_info = self.extract_single_book_info(
                response.find('input', {'name': 'YII_CSRF_TOKEN'}).get('value'),
                items_list,
            )

            response.decompose()

        return [book_info] if book_info else None

    def extract_single_book_info(self, yii_token, items_list):
        book_info = None
        for item in items_list:
            # Check if book is available.
            is_book_available = self.get_book_accessibility(yii_token, item)
            if not is_book_available: continue

            # Extract book location, section and availability from row.
            item_signatures = item.div.find('dl', { 'class': self.item_signature_re })\
                                      .find_all('dd')
            if not item_signatures: continue

            signature_values = item_signatures[-1].text.split()
            # Skip books without section name.
            if len(signature_values) < 2: continue

            # Check if address is in accepted list.
            location = signature_values[0]
            if not location in self.data['accepted_locations']: continue
            # Get full section name.
            section = ' '.join(signature_values[1:])
            book_info = (self.data['department'], section)

            # All remaining available books will be in the same section.
            break
        return book_info

    def get_book_accessibility(self, yii_token, result):
        accessibility_url = '{0}/ajax/getaccessibilityicon'.format(
            self.data['base_url']
        );
        accessibility_params = {
            "docid": result.get('data-item-id'),
            "doclibid": result.get('data-item-lib-id'),
            "YII_CSRF_TOKEN": yii_token,
        }
        accessibility_params['libid'] = accessibility_params['doclibid'];

        accessibility_result = get_parsed_url_response(
            accessibility_url,
            data=encode_url_params(accessibility_params),
            opener=self.opener,
        )
        is_book_available = self.item_available_re.search(
            accessibility_result.div.text
        )
        accessibility_result.decompose()

        return True if is_book_available else False
# }}}
