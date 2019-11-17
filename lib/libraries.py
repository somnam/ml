# Import {{{
import re
import sys
import json
import requests
from operator import itemgetter
from lib.diskcache import diskcache, DAY
from lib.automata import FirefoxBrowserWrapper
from lib.config import Config
from lib.common import (
    open_url,
    prepare_opener,
    get_parsed_url_response,
    get_url_net_location,
    get_unverifield_ssl_handler,
)
from lib.utils import bs4_scope
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
# }}}


def library_factory(library_id):
    return getattr(sys.modules.get(__name__), f'Library{library_id}')


class LibraryBase(FirefoxBrowserWrapper):  # {{{
    config = None
    handlers = []
    headers = None

    def __init__(self, books):
        super().__init__()
        self.books = books
        self._uuids = None
        self._opener = None
        self.session = None

    @property
    def uuids(self):
        if not self._uuids:
            self._uuids = {book["isbn"]: f'{self.config["id"]}:{book["isbn"]}'
                           for book in self.books}
        return self._uuids

    @property
    def opener(self):
        if not self._opener:
            self._opener = prepare_opener(self.config['url'],
                                          handlers=self.handlers,
                                          headers=self.headers)
        return self._opener

    def run(self):
        with self.browser:
            # Open library page.
            self.browser.get(self.config['url'])
            # Check if correct library page is opened.
            self.check_library_title()
            # Fetch all books status.
            books_status = self.get_books_status()

        # Sort books by deparment and section.
        books_status.sort(key=itemgetter('department', 'section'))
        return books_status

    def check_library_title(self):
        if 'title' in self.config and self.config['title']:
            assert self.config['title'] in self.browser.title

    def get_books_status(self):
        # Allows to cache library info for given time.
        cached_book_info_wrapper = self.cached_book_info_wrapper()

        books_status = {}
        for book in self.books:
            # Check if wasn't already processed.
            book_uid = self.uuids[book["isbn"]]
            if book_uid in books_status:
                continue
            # Fetch book info
            book_json = cached_book_info_wrapper(book_uid)
            # Don't append empty info.
            if book_json:
                books_status[book_uid] = json.loads(book_json)

        return [status for entry in books_status.values() for status in entry]

    def cached_book_info_wrapper(self):
        # Use book uuid as cache key.
        books_by_uid = {self.uuids[book["isbn"]]: book for book in self.books}

        # Cache book fetch status for 24h.
        @diskcache(DAY)
        def get_cached_book_info(book_uid):
            return self.get_book_info(books_by_uid[book_uid])
        return get_cached_book_info

    def get_book_info(self, book):
        book_info = None
        # Search fields are used to retry fetching book info.
        search_fields = self.search_fields[:]
        while not book_info and search_fields:
            # Search first by isbn, then by title.
            search_field = search_fields.pop(0)

            # Fetch book info.
            book_info, is_unavailable = self.query_book_info(book, search_field)

            # Book was found as available or unavailable.
            if book_info or is_unavailable:
                break
            elif search_fields:
                print('Retry book fetching.')
            else:
                print(f'Book "{book["title"]}" by {book["author"]} not found.')

        return book_info

    def query_book_info(self, book, search_field):
        # Query book and fetch results.
        query_results = self.query_book(book, search_field)
        query_match = self.get_matching_result(book, search_field, query_results)
        book_info = self.extract_book_info(book, query_match)

        return self.process_book_info(book, book_info)

    def process_book_info(self, book, book_info):
        # Book info:
        # None - book wasn't found, search by other criteria
        # []   - book was found but is unavailable, end search
        is_unavailable = book_info is not None and not book_info

        # Book has been successfully queried or is not for rent.
        if book_info:
            print(f'Successfully queried "{book["title"]}"'
                  f' by {book["author"]} info.')
            # Return info in json format.
            book_info = json.dumps([{
                "author": book["author"],
                "title": f'"{book["title"]}"',
                "department": entry[0],
                "section": entry[1],
                "pages": book["pages"],
                "link": book["url"],
            } for entry in book_info])
        # If book is unavailable then don't search for it a second time.
        elif is_unavailable:
            print(f'Book "{book["title"]}" by {book["author"]} not available.')
            book_info = None

        return book_info, is_unavailable

    def query_book(self, book, search_field):
        raise NotImplementedError()

    def get_matching_result(self, book, search_field):
        raise NotImplementedError()

    def extract_book_info(self, book, search_field):
        raise NotImplementedError()
# }}}


class Library4949(LibraryBase):  # {{{
    config = Config()['libraries:4949']

    search_fields = ['isbn', 'title']

    isbn_re = re.compile(r'\D+')
    section_re = re.compile(r'\s\(\s.+\s\)\s')

    search_type_id = 'form1:dropdown1'
    resource_type_id = 'form1:dropdown4'
    clear_button_id = 'form1:btnCzyscForme'

    def __init__(self, books):
        super().__init__(books)
        self._net_location = None

    @property
    def net_location(self):
        if not self._net_location:
            # Get base url from redirect.
            self._net_location = get_url_net_location(
                # Get redirect url from site response
                open_url(self.config["url"], self.opener).geturl()
            )
        return self._net_location

    # Search type: 1 - Author, 2 - Title, 3 - ISBN, 4 - Series
    # Resource type: 1  - All, 2  - Book, 9  - Magazine, 15 - Audiobook
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
            if link.text != form_type:
                continue
            link.click()
            break

        # Clear form before using.
        if (self.wait_is_visible(self.clear_button_id)):
            clear = self.browser.find_element_by_id(self.clear_button_id)
            clear.click()

        return

    def hide_autocomplete_popup(self, text_field_id, autocomp_popup_id):
        if (self.wait_is_visible(autocomp_popup_id)):
            text_field = self.browser.find_element_by_id(text_field_id)
            text_field.send_keys(Keys.ESCAPE)
            self.wait_is_not_visible(autocomp_popup_id)

    def query_book_by_isbn(self, book):
        search_type = '3'
        resource_type = '2'
        submit_button_id = 'form1:btnSzukajIndeks'
        results_list_xpath = '//ul[@class="kl"]'

        # Select standard form.
        self.select_form('Indeks')

        # Input search value.
        self.set_input_value('form1:textField1', book['isbn'])

        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField1', 'autoc1')

        # Set search type.
        self.select_by_id_and_value(self.search_type_id, search_type)

        # Set resource_type.
        self.select_by_id_and_value(self.resource_type_id, resource_type)

        # Submit form.
        results = None
        if (self.wait_is_visible(submit_button_id)):
            submit = self.browser.find_element_by_id(submit_button_id)
            submit.click()

            # Wait for results to appear.
            if (self.wait_is_visible(results_list_xpath, By.XPATH)):
                results_wrapper = self.browser.find_element_by_xpath(
                    results_list_xpath
                )
                results = results_wrapper.find_elements_by_xpath('li/a')

        # Return search results.
        return results

    def query_book_by_title(self, book):
        resource_type = '2'
        submit_button_id = 'form1:btnSzukajOpisow'

        # Select advanced form.
        self.select_form('Złożone')

        # Input book author.
        author_name_list = book['author'].split(' ')
        author_string = '{0}, {1}'.format(
            author_name_list.pop(),
            ' '.join(author_name_list)
        )
        self.set_input_value('form1:textField1', author_string)
        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField1', 'autoc1')

        # Input book title.
        self.set_input_value('form1:textField2', book['title'])
        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField2', 'autoc2')

        # Set resource_type.
        self.select_by_id_and_value(self.resource_type_id, resource_type)

        results = None
        if (self.wait_is_visible(submit_button_id)):
            submit = self.browser.find_element_by_id(submit_button_id)
            submit.click()

            if (self.wait_is_visible('opisy')):
                results = self.browser.find_elements_by_class_name('opis')

        # Return search results.
        return results

    def get_matching_result(self, book, search_field, results):
        if not results:
            return

        return (self.get_matching_result_isbn(book, results)
                if search_field == 'isbn'
                else self.get_matching_result_title(book, results))

    def get_matching_result_isbn(self, book, results):
        match_value = book['isbn'].replace('-', '')

        matching = []
        for elem in results:
            # Replace all non-numeric characters in isbn.
            elem_value = self.isbn_re.sub('', elem.text)
            if elem_value != match_value:
                continue

            matching = self.extract_matching_results(elem)
            break

        return matching

    def get_matching_result_title(self, book, results):
        matching = []
        for elem in results:
            book_id = elem.get_attribute('id').replace('dvop', '')
            matching.append('{0}{1}{2}'.format(
                self.net_location,
                self.config['book_url_suffix'],
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

        book_info = []
        for book_url in results:
            response = get_parsed_url_response(book_url, opener=self.opener)
            resource = response.find('div', {'id': 'zasob'})
            if (not resource or not resource.contents or resource.text.strip() == 'Brak zasobu'):
                response.decompose()
                continue

            ul = resource.find('ul', {'class': 'zas_filie'})
            for li in ul.find_all('li'):
                department_info = li.find('div', {'class': 'filia'})

                # Get library address.
                department, address = '', ''
                if (department_info and department_info.contents):
                    department = department_info.contents[0]
                    location = (department_info.contents[-1].split(',')
                                if department_info.contents[-1] else None)
                    address = (location[0] if location else None)

                # Check if address is in accepted list.
                if address not in self.config.getstruct('accepted_locations'):
                    continue

                # Check if book is rented/not available.
                warning = li.find('div', {'class': 'opis_uwaga'})
                not_available = li.find('img', {'title': 'Pozycja nie do wypożyczenia'})
                if (not_available or (warning and warning.text)):
                    continue

                # Get availability info.
                availability = [int(d) for d in
                                li.find('div', {'class': 'dostepnosc'}).text.split()
                                if d.isdigit()]

                # Book is not available.
                if not(availability and availability[0]):
                    continue

                # Extract section name.
                section_info = li.find('table', {'class': 'zasob'}).td.find_next('td')
                section_match = self.section_re.search(section_info.text)
                section = section_match.group().strip() if section_match else ''

                book_info.append((department, section))

            response.decompose()

        return book_info
# }}}


class Library5004(LibraryBase):  # {{{
    config = Config()['libraries:5004']
    search_fields = ['title_and_author']

    handlers = [get_unverifield_ssl_handler()]
    headers = {'X-Requested-With': 'XMLHttpRequest'}

    search_input = '#SimpleSearchForm_q'
    search_button = '.btn.search-main-btn'
    results_header = '.row.row-full-text'

    items_list_re = re.compile('prolibitem')
    item_signature_re = re.compile('dl-horizontal')

    def get_book_info(self, book):
        # Wait for submit button to be visible.
        try:
            self.wait_is_visible_by_css(self.search_button)
        except NoSuchElementException:
            pass

        book_info = super().get_book_info(book)

        # Reopen search form page.
        try:
            button = self.browser.find_element_by_class_name('library_title-pages')
            button.find_element_by_tag_name('a').click()
        except NoSuchElementException:
            pass

        return book_info

    def set_search_value(self, search_value):
        # Input search value.
        if self.wait_is_visible_by_css(self.search_input):
            self.find_by_css(self.search_input).send_keys(search_value)
            return True
        return False

    def query_book(self, book, search_field):
        # Search field didn't load - can't run query.
        search_value = '"{0}" AND "{1}"'.format(book['title'], book['author'])
        if not self.set_search_value(search_value):
            return None

        # Submit form.
        self.find_by_css(self.search_button).click()

        # Wait for results to load.
        self.wait_is_visible_by_css(self.results_header)

        results = None
        try:
            self.find_by_css('.info-empty')
        except NoSuchElementException:
            # Display up to 100 results on page.
            if self.wait_is_visible_by_css('.btn-group>.hidden-xs'):
                self.find_by_css('.btn-group>.hidden-xs').click()
                if self.wait_is_visible_by_css('.btn-group.open>.dropdown-menu'):
                    self.find_by_css('.btn-group.open>.dropdown-menu>li:last-child').click()
            results = self.find_all_by_css('dl.dl-horizontal')
        return results

    def get_matching_result(self, book, search_field, results):
        if not results:
            return

        matching = []
        for result in results:
            book_anchor = result.find_element_by_tag_name('a')
            if book_anchor:
                matching.append(book_anchor.get_attribute('href'))

        return matching

    def extract_book_info(self, book, results):
        if not (book and results):
            return

        book_info = None
        for book_url in results:
            # All books are available in the same section.
            if book_info:
                break

            try:
                with requests.Session() as self.session:
                    response = self.session.get(book_url)
                    response.raise_for_status()

                    with bs4_scope(response.content) as book_page:
                        items_list = book_page.find_all('div',
                                                        {'class': self.items_list_re})
                        if not items_list:
                            continue

                        book_info = self.extract_single_book_info(
                            book_page.find('input', {'name': 'YII_CSRF_TOKEN'}).get('value'),
                            items_list,
                        )
            except requests.exceptions.HTTPError as e:
                print(f'Error fetching book url {book_url}: {e}')
                continue

        return [book_info] if book_info else None

    def extract_single_book_info(self, yii_token, items_list):
        book_info = None
        for item in items_list:
            # Check if book is available.
            is_book_available = self.get_book_accessibility(yii_token, item)
            if not is_book_available:
                continue

            # Extract book location, section and availability from row.
            item_signatures = item.div.find(
                'dl',
                {'class': self.item_signature_re}
            ).find_all('dd')
            if not item_signatures:
                continue

            signature_values = item_signatures[1].text.split()
            # Skip books without section name.
            if len(signature_values) < 2:
                continue

            # Check if address is in accepted list.
            location = signature_values[0]
            if location not in self.config.getstruct('accepted_locations'):
                continue
            # Get full section name.
            section = ' '.join(signature_values[1:])
            book_info = (self.config['department'], section)

            # All remaining available books will be in the same section.
            break

        return book_info

    def get_book_accessibility(self, yii_token, item):
        accessibility_url = '{0}/itemrequest/getiteminfomessage'.format(
            self.config['base_url']
        )
        accessibility_params = {
            "docid": item.get('data-item-id'),
            "doclibid": item.get('data-item-lib-id'),
            'locationid': item.get('data-item-location-id'),
            'accessibility': 1,
            "YII_CSRF_TOKEN": yii_token,
        }
        accessibility_params['libid'] = accessibility_params['doclibid']

        response = self.session.post(
            accessibility_url,
            data=accessibility_params,
            headers=self.headers,
        )
        response.raise_for_status()

        with bs4_scope(response.content) as accessibility_result:
            accessibility_value = json.loads(
                accessibility_result.html.body.p.text
            )
        return (self.config['accepted_status']
                in accessibility_value['message'])
# }}}
