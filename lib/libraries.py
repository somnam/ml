# Import {{{
import re
import sys
import json
import logging
import requests
from datetime import datetime, timedelta
from lib.db import BookLibraryAvailabilityModel, Handler
from lib.automata import FirefoxBrowser
from lib.config import Config
from lib.utils import bs4_scope
from lib.exceptions import BrowserUnavailable, LibraryNotSupported, LibraryPageNotValid
from selenium.common.exceptions import (NoSuchElementException, WebDriverException,
                                        NoSuchWindowException, TimeoutException)
from selenium.webdriver.common.keys import Keys
# }}}


def library_factory(library_id, logger=None):
    try:
        library = getattr(sys.modules.get(__name__), f'Library{library_id}')
        if logger:
            setattr(library, 'logger', logging.getLogger(logger))
    except AttributeError:
        raise LibraryNotSupported(f'Library with id {library_id} not supported')
    return library


class LibraryBase:  # {{{
    logger = logging.getLogger(__name__)

    def __init__(self, library_id, search_fields, books):
        self.books = books
        self.config = Config()[f'libraries:{library_id}']
        self.search_fields = search_fields
        self.isbn_sub_re = re.compile(r'\D+')

        invalidate_days = self.config.getint('invalidate_days', fallback=1)
        self.invalidate_date = datetime.utcnow() - timedelta(days=invalidate_days)

        self.handler = Handler()
        self.handler.create_all()

        self.session = None
        self.browser = None

    def run(self):
        with FirefoxBrowser() as self.browser, requests.Session() as self.session:
            try:
                # Open requested library page.
                self.open_library_page()
                # Fetch all books info.
                books_availability = self.get_books_availability()
            except (NoSuchWindowException, TimeoutException, WebDriverException) as e:
                raise BrowserUnavailable(str(e))

        return books_availability

    def open_library_page(self):
        # Open library page.
        self.browser.get(self.config['url'])
        # Check if correct library page is opened.
        if 'title' in self.config and self.config['title']:
            if self.config['title'] not in self.browser.title:
                raise LibraryPageNotValid('Incorrect library page title:'
                                          f' {self.browser.title}')

    def get_books_availability(self):
        books_availability = []
        for book in self.books:
            book_availability = self.get_book_availability(book)

            # Don't append empty info.
            if book_availability:
                books_availability.append(book_availability)

        return [entry
                for book_availability in books_availability
                for entry in book_availability]

    def get_book_availability(self, book):
        book_md5 = BookLibraryAvailabilityModel.md5_from_book(book)
        with self.handler.session_scope() as session:
            book_availability = session.query(BookLibraryAvailabilityModel.search_results)\
                .filter(BookLibraryAvailabilityModel.library_id == self.config["id"],
                        BookLibraryAvailabilityModel.book_md5 == book_md5,
                        BookLibraryAvailabilityModel.created >= self.invalidate_date)\
                .one_or_none()

        if book_availability:
            return book_availability.search_results

        search_results = self.search_for_book(book)
        with self.handler.session_scope() as session:
            session.query(BookLibraryAvailabilityModel).filter(
                BookLibraryAvailabilityModel.library_id == self.config["id"],
                BookLibraryAvailabilityModel.book_md5 == book_md5,
            ).delete()
            session.add(BookLibraryAvailabilityModel(
                library_id=self.config['id'],
                book_md5=BookLibraryAvailabilityModel.md5_from_book(book),
                search_results=search_results,
            ))

        return search_results

    def search_for_book(self, book):
        # Search fields are used to retry fetching book info.
        search_fields = self.search_fields[:]
        search_results = None
        while search_fields:
            # Search first by isbn, then by title.
            search_field = search_fields.pop(0)

            # Fetch book info.
            search_results = self.search_for_book_by_field(book, search_field)

            # Book was found as available or unavailable.
            if search_results is not None:
                search_results = self.process_search_results(
                    book, search_results
                )
                break
            # Any fields to search by remain?
            elif search_fields:
                self.logger.info(f'Retry fetching book "{book["title"]}"'
                                 f' by {book["author"]}.')
            # Book was not found for any search field.
            else:
                self.logger.info(f'Book "{book["title"]}" by {book["author"]}'
                                 ' not found.')
        return search_results

    def search_for_book_by_field(self, book, search_field):
        # Query book and fetch results.
        search_form_results = self.submit_search_form(
            book, search_field
        )
        matching_search_form_results = self.find_matching_search_form_results(
            book, search_field, search_form_results
        )
        return self.scrape_search_results(
            book, matching_search_form_results
        )

    def process_search_results(self, book, search_results):
        # Book info:
        # None - book wasn't found, search by other criteria
        # []   - book was found but is unavailable, end search
        is_unavailable = search_results is not None and not search_results
        if is_unavailable:
            self.logger.warning(f'Book "{book["title"]}" by {book["author"]}'
                                ' not available.')
            return None

        # Book has been successfully queried or is not for rent.
        self.logger.info(f'Successfully queried "{book["title"]}"'
                         f' by {book["author"]} info.')
        # Return info in json format.
        return [{
            "author": book["author"],
            "title": book["title"],
            "department": entry[0],
            "section": entry[1],
            "pages": book["pages"],
            "link": book["url"],
        } for entry in search_results]

    def submit_search_form(self, book, search_field):
        raise NotImplementedError()

    def find_matching_search_form_results(self, book, search_field):
        raise NotImplementedError()

    def scrape_search_results(self, book, results):
        raise NotImplementedError()
# }}}


class Library4949(LibraryBase):  # {{{
    def __init__(self, books):
        super().__init__(
            library_id=4949,
            search_fields=['isbn', 'title'],
            books=books,
        )

    def submit_search_form(self, book, search_field):
        # Check if book contains given search field.
        if not book.get(search_field):
            return

        return (self.submit_search_form_using_isbn(book)
                if search_field == 'isbn'
                else self.submit_search_form_using_title(book))

    def submit_search_form_using_isbn(self, book):
        # Select standard form.
        self.select_search_form('indeks')

        # Input search value.
        self.browser.set_input_value_by_id('form1:textField1', book['isbn'])

        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField1', 'autoc1')

        # Set search type.
        search_type = '3'
        self.browser.set_select_option_by_id('form1:dropdown1', search_type)

        # Set resource_type.
        resource_type = '2'
        self.browser.set_select_option_by_id('form1:dropdown4', resource_type)

        # Submit form.
        results = None
        submit_button_id = 'form1:btnSzukajIndeks'
        if self.browser.wait_is_visible_by_id(submit_button_id):
            self.browser.find_element_by_id(submit_button_id).click()

            # Wait for results to appear.
            results_list_selector = 'ul.kl'
            if self.browser.wait_is_visible_by_css_selector(results_list_selector):
                results_wrapper = self.browser.find_element_by_css_selector(
                    results_list_selector
                )
                results = results_wrapper.find_elements_by_css_selector('li>a')

        # Return search results.
        return results

    def submit_search_form_using_title(self, book):
        # Select advanced form.
        self.select_search_form('zaawansowane')

        # Input book author.
        author_name_list = book['author'].split(' ')
        author_string = '{0}, {1}'.format(
            author_name_list.pop(),
            ' '.join(author_name_list)
        )
        self.browser.set_input_value_by_id('form1:textField1', author_string)
        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField1', 'autoc1')

        # Input book title.
        self.browser.set_input_value_by_id('form1:textField2', book['title'])
        # Hide autocomplete popup.
        self.hide_autocomplete_popup('form1:textField2', 'autoc2')

        # Set resource_type.
        resource_type = '2'
        self.browser.set_select_option_by_id('form1:dropdown4', resource_type)

        results = None
        submit_button_id = 'form1:btnSzukajOpisow'
        if self.browser.wait_is_visible_by_id(submit_button_id):
            self.browser.find_element_by_id(submit_button_id).click()
            if self.browser.wait_is_visible_by_id('opisy'):
                results = self.browser.find_elements_by_class_name('opis')

        # Return search results.
        return results

    def select_search_form(self, form_type):
        # Select given form.
        form_selector = f'div.historia a[title*="{form_type}"]'
        if self.browser.wait_is_visible_by_css_selector(form_selector):
            self.browser.find_element_by_css_selector(form_selector).click()

        # Clear form before using.
        clear_button_id = 'form1:btnCzyscForme'
        if self.browser.wait_is_visible_by_id(clear_button_id):
            self.browser.find_element_by_id(clear_button_id).click()

    def hide_autocomplete_popup(self, text_field_id, autocomp_popup_id):
        if self.browser.wait_is_visible_by_id(autocomp_popup_id):
            text_field = self.browser.find_element_by_id(text_field_id)
            text_field.send_keys(Keys.ESCAPE)
            self.browser.wait_is_not_visible_by_id(autocomp_popup_id)

    def find_matching_search_form_results(self, book, search_field, results):
        if not results:
            return

        return (self.find_matching_search_form_results_by_isbn(book, results)
                if search_field == 'isbn'
                else self.find_matching_search_form_results_by_title(book, results))

    def find_matching_search_form_results_by_isbn(self, book, results):
        # Match result using isbn value.
        isbn_result = next((result for result in results
                            if self.isbn_sub_re.sub('', result.text) == book['isbn']),
                           None)
        # No match found - empty results list.
        if not isbn_result:
            return []

        # Expand matching results entry and get book links.
        isbn_result.click()
        try:
            self.browser.wait_is_visible_by_css_selector('div.zawartosc')
            return [
                link.get_attribute('href') for link in
                self.browser.find_elements_by_css_selector('div.zawartosc ul a')
            ]
        except NoSuchElementException:
            return []

    def find_matching_search_form_results_by_title(self, book, results):
        matching = []
        for elem in results:
            book_id = elem.get_attribute('id').replace('dvop', '')
            matching.append(f'{self.config["book_url"]}{book_id}')
        return matching

    def scrape_search_results(self, book, results):
        if not results:
            return

        accepted_locations = self.config.getstruct('accepted_locations')

        search_results = []
        for book_url in results:
            try:
                response = self.session.get(book_url)
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                self.logger.error(f'Error fetching url {book_url}: {e}')
                continue

            with bs4_scope(response.content) as book_page:
                for li in book_page.select('div.zasob ul.zas_filie > li'):
                    # Get department info.
                    department_info = li.select_one('div.filia')
                    if not(department_info and department_info.contents):
                        continue

                    # Get library address.
                    department, _, location = department_info.contents
                    address = location.split(',')[0] if location else None

                    # Check if address is in accepted list.
                    if address not in accepted_locations:
                        continue

                    # Get availability info.
                    availability = li.select_one('div.dostepnosc').text
                    available = re.search(r'\d', availability)

                    # Book is not available.
                    if not(available and int(available.group()) > 0):
                        continue

                    # Extract section name.
                    section_info = li.select_one('table.zasob tr>td:nth-last-child(2)')
                    section_match = re.search(r'\s\(\s(.+)\s\)\s', section_info.text)
                    section = section_match.group(1) if section_match else ''

                    search_results.append((department, section))

        return search_results
# }}}


class Library5004(LibraryBase):  # {{{
    def __init__(self, books):
        super().__init__(
            library_id=5004,
            search_fields=['title_and_author'],
            books=books,
        )

    def open_library_page(self):
        super().open_library_page()
        # Confirm modal dialog.
        try:
            modal_confirm_class = '.modal-dialog #yt4'
            if self.browser.wait_is_visible_by_css_selector(modal_confirm_class):
                self.browser.find_element_by_css_selector(modal_confirm_class).click()
        except NoSuchElementException:
            pass

    def get_book_availability(self, book):
        # Wait for submit button to be visible.
        try:
            search_button = '.btn.search-main-btn'
            self.browser.wait_is_visible_by_css_selector(search_button)
        except NoSuchElementException:
            pass

        book_availability = super().get_book_availability(book)

        # Reopen search form page.
        try:
            main_page_selector = 'h1.library_title-pages > a'
            self.browser.find_element_by_css_selector(main_page_selector).click()
        except NoSuchElementException:
            pass

        return book_availability

    def set_search_value(self, search_value):
        # Input search value.
        search_input = '#SimpleSearchForm_q'
        if self.browser.wait_is_visible_by_css_selector(search_input):
            self.browser.find_element_by_css_selector(search_input)\
                .send_keys(search_value)
            return True
        return False

    def submit_search_form(self, book, search_field):
        # Search field didn't load - can't run query.
        search_value = '"{0}" AND "{1}"'.format(book['title'], book['author'])
        if not self.set_search_value(search_value):
            return None

        # Submit form.
        search_button = '.btn.search-main-btn'
        self.browser.find_element_by_css_selector(search_button).click()

        # Wait for results to load.
        results_header = '.row.row-full-text'
        self.browser.wait_is_visible_by_css_selector(results_header)

        results = None
        try:
            self.browser.find_element_by_css_selector('.info-empty')
        except NoSuchElementException:
            # Display up to 100 results on page.
            if self.browser.wait_is_visible_by_css_selector('.btn-group>.hidden-xs'):
                self.browser.find_element_by_css_selector('.btn-group>.hidden-xs')\
                    .click()
                if self.browser.wait_is_visible_by_css_selector('.btn-group.open>.dropdown-menu'):
                    self.browser.find_element_by_css_selector(
                        '.btn-group.open>.dropdown-menu>li:last-child'
                    ).click()
            results = self.browser.find_elements_by_css_selector('dl.dl-horizontal')
        return results

    def find_matching_search_form_results(self, book, search_field, results):
        if not results:
            return

        matching = []
        for result in results:
            book_anchor = result.find_element_by_tag_name('a')
            if book_anchor:
                matching.append(book_anchor.get_attribute('href'))

        return matching

    def scrape_search_results(self, book, results):
        if not results:
            return

        search_result = None
        for book_url in results:
            try:
                response = self.session.get(book_url)
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                self.logger.error(f'Error fetching url {book_url}: {e}')
                continue

            with bs4_scope(response.content) as book_page:
                items_list = book_page.select('div.prolibitem')
                yii_token = book_page.select_one('input[name="YII_CSRF_TOKEN"]')\
                    .get('value')
                if not(items_list and yii_token):
                    continue

                search_result = self.scrape_first_search_result(
                    yii_token=yii_token,
                    items_list=items_list,
                )
                # All books are available in the same section.
                if search_result:
                    break

        return [search_result] if search_result else None

    def scrape_first_search_result(self, yii_token, items_list):
        search_result = None
        for item in items_list:
            # Check if book is available.
            is_book_available = self.get_book_accessibility(yii_token, item)
            if not is_book_available:
                continue

            # Extract book location, section and availability from row.
            item_signatures = item.select('dl.dl-horizontal dd')
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
            search_result = (self.config['department'], section)

            # All remaining available books will be in the same section.
            break

        return search_result

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

        try:
            response = self.session.post(
                accessibility_url,
                data=accessibility_params,
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            self.logger.error(f'Error fetching url {accessibility_url}: {e}')
            return False

        with bs4_scope(response.content) as accessibility_result:
            accessibility_value = json.loads(
                accessibility_result.html.body.p.text
            )
        return (self.config['accepted_status']
                in accessibility_value['message'])
# }}}
