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
from lib.utils import bs4_scope, get_file_path
from lib.exceptions import BrowserUnavailable, LibraryNotSupported, LibraryPageNotValid
from selenium.common.exceptions import (NoSuchElementException, WebDriverException,
                                        NoSuchWindowException, TimeoutException)
from selenium.webdriver.common.keys import Keys
# }}}


def library_factory(library_id, logger=None, invalidate_days=None):
    try:
        library = getattr(sys.modules.get(__name__), f'Library{library_id}')
        if logger:
            setattr(library, 'logger', logging.getLogger(logger))
        if invalidate_days is not None:
            setattr(library, 'invalidate_days', invalidate_days)
    except AttributeError:
        raise LibraryNotSupported(f'Library with id {library_id} not supported')
    return library


class LibraryBase:  # {{{
    logger = logging.getLogger(__name__)
    invalidate_days = 1

    def __init__(self, library_id, books):
        self.books = books
        self.config = Config()[f'libraries:{library_id}']
        self.search_fields = self.config.getstruct('search_fields')

        self.invalidate_date = datetime.utcnow() - timedelta(days=self.invalidate_days)

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
                books_info = self.get_books_info()
            except (NoSuchWindowException, TimeoutException, WebDriverException) as e:
                # Save error screenshot.
                self.save_screenshot('error')

                raise BrowserUnavailable(e)

        return books_info

    def save_screenshot(self, severity: str = 'info') -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        self.browser.save_screenshot(get_file_path(f"var/log/{severity}_{timestamp}.png"))

    def open_library_page(self):
        # Open library page.
        self.browser.get(self.config['url'])
        # Check if correct library page is opened.
        if 'title' in self.config and self.config['title']:
            if self.config['title'] not in self.browser.title:
                raise LibraryPageNotValid('Incorrect library page title: {self.browser.title}')

    def get_books_info(self):

        books_info = []

        for book in self.books:
            self.logger.debug(f"Start search '{book['title']}' by {book['author']}")

            book_info = self.get_book_info(book)

            if book_info:
                self.logger.info(f'Successfully queried "{book["title"]}" by {book["author"]}.')
                books_info.append(book_info)
            else:
                self.logger.info(f'Book "{book["title"]}" by {book["author"]} not found.')

            self.logger.debug(f"End search '{book['title']}' by {book['author']}")

        return [entry for result in books_info for entry in result]

    def get_book_info(self, book):
        book_md5 = BookLibraryAvailabilityModel.md5_from_book(book)

        with self.handler.session_scope() as session:
            book_availability = session.query(BookLibraryAvailabilityModel.search_results)\
                .filter(BookLibraryAvailabilityModel.library_id == self.config["id"],
                        BookLibraryAvailabilityModel.book_md5 == book_md5,
                        BookLibraryAvailabilityModel.created >= self.invalidate_date)\
                .one_or_none()

        if book_availability:
            self.logger.debug(f"Cache hit for '{book['title']}' by {book['author']}")
            return book_availability.search_results

        self.logger.debug(f"Cache miss for '{book['title']}' by {book['author']}")

        book_info = self.search_for_book(book)

        with self.handler.session_scope() as session:
            book_availability = session.query(BookLibraryAvailabilityModel).filter(
                BookLibraryAvailabilityModel.library_id == self.config["id"],
                BookLibraryAvailabilityModel.book_md5 == book_md5,
            ).one_or_none()
            if book_availability:
                book_availability.search_results = book_info
                book_availability.created = datetime.utcnow()
            else:
                book_availability = BookLibraryAvailabilityModel(
                    library_id=self.config['id'],
                    book_md5=BookLibraryAvailabilityModel.md5_from_book(book),
                    search_results=book_info,
                )
            session.add(book_availability)

        return book_info

    def search_for_book(self, book):
        # Search fields are used to retry fetching book info.
        search_fields = self.search_fields[:]

        book_info = None

        while search_fields:
            # Search first by isbn, then by title.
            search_field = search_fields.pop(0)

            # Fetch book info.
            search_results = self.search_for_book_by_field(book, search_field)

            matching_search_results = self.filter_search_results(book, search_results)

            book_info = self.scrape_book_info(matching_search_results)

            # Book info:
            # [{}] - book was found as available, end search
            # []   - book was found but is unavailable, end search
            # None - book wasn't found, search by other criteria
            if book_info is not None:
                book_info = self.process_book_info(book, book_info)
                break

            # Any fields to search by remain?
            elif search_fields:
                self.logger.info(f'Retry fetching book "{book["title"]}" by {book["author"]}.')

        return book_info

    def process_book_info(self, book, book_info):
        if not book_info:
            self.logger.debug(f'Book "{book["title"]}" by {book["author"]} not available.')
            return None

        # Book has been successfully queried or is not for rent.
        return [{
            "author": book["author"],
            "title": book["title"],
            "department": entry[0],
            "section": entry[1],
            "pages": book["pages"],
            "link": book["url"],
        } for entry in book_info]

    def search_for_book_by_field(self, book, search_field):
        raise NotImplementedError()

    def filter_search_results(self, book, results):
        raise NotImplementedError()

    def scrape_book_info(self, results):
        raise NotImplementedError()
# }}}


class Library4949(LibraryBase):  # {{{
    def __init__(self, books):
        super().__init__(library_id=4949, books=books)

    def open_library_page(self):
        super().open_library_page()

        self.init_search_form('title')

        self.init_advanced_form('author')

        self.init_search_filters()

    def init_search_form(self, search_field):
        self.logger.debug('Setting basic search.')

        # Wait for books list to load.
        if self.browser.wait_is_visible_by_css(self.config['modal_loading_overlay_query']):
            self.logger.debug('Waiting for overlay.')
            self.browser.wait_is_not_visible_by_css(
                self.config['modal_loading_overlay_query'],
                timeout=10,
            )

        if not self.browser.wait_is_visible_by_xpath(self.config['search_page_query']):
            raise LibraryPageNotValid("Unable to open search form.")

        if not self.browser.wait_is_visible_by_css(self.config['search_input_query']):
            raise LibraryPageNotValid("Unable to load search form.")

        # Open search page.
        self.browser.find_element_by_xpath(self.config['search_page_query']).click()

        # Expand advanced search options.
        expand_search_form_query = self.config['expand_search_form_query']
        if self.browser.wait_is_visible_by_css(expand_search_form_query, timeout=1):
            self.browser.find_element_by_css_selector(expand_search_form_query).click()

        search_by_query = self.config[f'search_by_{search_field}_query']
        if self.set_select_option(self.config['search_by_query'], search_by_query):
            self.logger.debug('Setting search type.')

    def init_advanced_form(self, search_field):
        self.logger.debug('Setting advanched search.')

        if not self.browser.wait_is_visible_by_css(self.config['add_search_form_query'], timeout=1):
            raise LibraryPageNotValid("Unable to load advanced search form.")

        self.browser.find_element_by_css_selector(self.config['add_search_form_query']).click()

        # Set operator field.
        if self.set_select_option(self.config["add_operator_query"], self.config["search_and_query"]):
            self.logger.debug('Setting search operator.')

        # Set search by field.
        search_by_query = self.config[f'search_by_{search_field}_query']
        if self.set_select_option(self.config['add_search_by_query'], search_by_query):
            self.logger.debug('Setting advanced search type.')

    def init_search_filters(self):
        self.logger.debug('Setting search filters.')

        available_locations_query = self.config['available_locations_query']
        if not self.browser.wait_is_clickable_by_xpath(available_locations_query):
            raise LibraryPageNotValid("Unable to select library locations.")

        for query in ('book_document_query', 'button_available_query'):
            if self.browser.wait_is_clickable_by_xpath(self.config[query]):
                self.browser.find_element_by_xpath(self.config[query]).click()

        for accepted_location_query in self.config.getstruct("accepted_locations_query"):
            if self.browser.wait_is_clickable_by_xpath(accepted_location_query):
                self.browser.find_element_by_xpath(accepted_location_query).click()

    def search_for_book_by_field(self, book, search_field):
        if not book.get(search_field):
            return

        if search_field == "title":
            return self.search_using_title_and_author(book)

        return None

    def search_using_title_and_author(self, book):
        self.logger.debug(f"Search '{book['title']}' by {book['author']} using title and author")

        self.fill_search_form(book['title'])

        self.fill_advanced_form(book['author'])

        if not self.submit_search_form():
            self.logger.debug('No results found after form submit.')
            return None

        # Return search results.
        search_results = self.browser.find_elements_by_css_selector(self.config['result_row_query'])

        self.logger.debug(f'Found {len(search_results)} books.')

        return search_results

    def fill_search_form(self, value):
        self.logger.debug('Setting basic search.')

        if not self.browser.wait_is_visible_by_xpath(self.config['search_page_query'], timeout=1):
            raise LibraryPageNotValid("Unable to open search form.")

        self.browser.find_element_by_xpath(self.config['search_page_query']).click()

        if not self.browser.wait_is_visible_by_css(self.config['search_input_query']):
            raise LibraryPageNotValid("Unable to load search form.")

        self.browser.set_input_value_by_css(self.config['search_input_query'], value)

        self.hide_autocomplete_popup(self.config['search_input_query'],
                                     self.config['search_autocomplete_query'])

    def fill_advanced_form(self, value):
        self.logger.debug('Setting advanched search.')

        if not self.browser.wait_is_visible_by_css(self.config['add_search_form_query'], timeout=1):
            raise LibraryPageNotValid("Unable to load advanced search form.")

        self.browser.set_input_value_by_css(self.config['add_search_input_query'], value)

        self.hide_autocomplete_popup(self.config['add_search_input_query'],
                                     self.config['search_autocomplete_query'])

    def submit_search_form(self):
        if self.browser.wait_is_visible_by_css(self.config['search_button_query']):
            self.browser.find_element_by_css_selector(self.config['search_button_query']).click()
            self.logger.debug('Submitting advanced search.')

        # Check if no results were found.
        if self.browser.wait_is_visible_by_css(self.config['no_results_query']):
            self.logger.debug('No results found after submit form.')
            return False

        return True

    def hide_autocomplete_popup(self, text_field_query, autocomp_popup_query):
        if self.browser.wait_is_visible_by_css(
            autocomp_popup_query, timeout=10
        ):
            self.logger.debug('Hide autocomplete popup.')
            text_field = self.browser.find_element_by_css_selector(text_field_query)
            text_field.send_keys(Keys.ESCAPE)
            self.browser.wait_is_not_visible_by_css(autocomp_popup_query)

    def set_select_option(self, select_query, option_xpath):
        if self.browser.wait_is_visible_by_css(select_query, timeout=1):
            self.browser.find_element_by_css_selector(select_query).click()
            if self.browser.wait_is_visible_by_xpath(option_xpath, timeout=1):
                self.browser.find_element_by_xpath(option_xpath).click()
                return True

        return False

    def filter_search_results(self, book, results):
        return results if results else None

    def scrape_book_info(self, results):
        if not results:
            return

        accepted_locations = self.config.getstruct('accepted_locations')

        book_info = []
        for result in results:
            # Open action modal on result item.
            result.find_element_by_css_selector(self.config['action_button_query']).click()
            if not self.browser.wait_is_visible_by_css(self.config['action_modal_query']):
                continue
            self.logger.debug('Open action modal on result item.')

            # Wait for loading overlay to hide.
            if self.browser.wait_is_visible_by_css(self.config['modal_loading_overlay_query']):
                self.logger.debug('Waiting for overlay.')
                self.browser.wait_is_not_visible_by_css(
                    self.config['modal_loading_overlay_query'],
                    timeout=10,
                )

            # Select available items only.
            if self.browser.wait_is_visible_by_xpath(self.config['modal_only_available_query']):
                self.browser.find_element_by_xpath(self.config['modal_only_available_query']).click()

            self.logger.debug('Select available items only.')

            # Item not available in any accepted location?
            if self.browser.wait_is_visible_by_xpath(self.config['modal_no_results_query'], timeout=1):
                self.logger.debug('Item not available in any accepted location.')
                continue

            rows = self.browser.find_elements_by_css_selector(self.config['modal_result_row_query'])
            for row in rows:
                # Get address.
                address = row.find_element_by_css_selector(self.config['modal_row_address_query'])
                if not address:
                    continue
                self.logger.debug('Get address.')

                # Check address.
                location = next(
                    (location for location in accepted_locations
                     if location.lower() in address.text.lower()),
                    None
                )
                if not location:
                    self.logger.debug('Address not in accepted locations.')
                    continue

                # Get section name.
                self.browser.find_element_by_xpath(self.config['modal_row_show_section_query'])\
                    .click()
                if self.browser.wait_is_visible_by_css(
                    self.config['modal_row_section_query'], timeout=1
                ):
                    section_info = self.browser.find_element_by_css_selector(
                        self.config['modal_row_section_query']
                    )
                    self.logger.debug('Address not in accepted locations.')

                    section_match = re.search(r'\s\(\s(.+)\s\)\s', section_info.text)
                    section = section_match.group(1) if section_match else ''
                else:
                    section = ''

                book_info.append((location, section))

            # Close modal.
            self.browser.find_element_by_xpath(self.config['modal_close_button']).click()

        return book_info
# }}}


class Library5004(LibraryBase):  # {{{
    def __init__(self, books):
        super().__init__(library_id=5004, books=books)

    def open_library_page(self):
        super().open_library_page()

        # Confirm modal dialog.
        try:
            modal_confirm_query = self.config['modal_confirm_query']
            if self.browser.wait_is_visible_by_css(modal_confirm_query):
                self.browser.find_element_by_css_selector(modal_confirm_query).click()
        except NoSuchElementException:
            pass

    def search_for_book(self, book):
        # Wait for submit button to be visible.
        try:
            self.browser.wait_is_visible_by_css(self.config['search_button_query'])
        except NoSuchElementException:
            pass

        book_info = super().search_for_book(book)

        # Reopen search form page.
        try:
            self.browser.find_element_by_css_selector(self.config['main_page_query']).click()
        except NoSuchElementException:
            pass

        return book_info

    def set_search_value(self, search_value):
        # Input search value.
        search_input_query = self.config['search_input_query']
        if self.browser.wait_is_visible_by_css(search_input_query):
            self.browser.find_element_by_css_selector(search_input_query)\
                .send_keys(search_value)
            return True
        return False

    def search_for_book_by_field(self, book, search_field):
        if not book.get(search_field):
            return

        if search_field == "title":
            return self.search_using_title_and_author(book)

        return None

    def search_using_title_and_author(self, book):

        # Search field didn't load - can't run query.
        search_value = self.config['search_value_query'].format(book['title'], book['author'])
        if not self.set_search_value(search_value):
            return None

        # Submit form.
        self.browser.find_element_by_css_selector(self.config['search_button_query']).click()

        # Wait for results to load.
        self.browser.wait_is_visible_by_css(self.config['result_header_query'])

        results = None
        try:
            self.browser.find_element_by_css_selector(self.config['no_results_query'])
        except NoSuchElementException:
            # Display up to 100 results on page.
            if self.browser.wait_is_visible_by_css(self.config['pager_query']):
                self.browser.find_element_by_css_selector(self.config['pager_query'])\
                    .click()

                if self.browser.wait_is_visible_by_css(self.config['pager_menu_query']):
                    self.browser.find_element_by_css_selector(
                        self.config['pager_option_query']
                    ).click()

            results = self.browser.find_elements_by_css_selector(self.config['search_results_query'])

        return results

    def filter_search_results(self, book, results):
        if not results:
            return

        matching = []
        for result in results:
            book_anchor = result.find_element_by_tag_name('a')
            if book_anchor:
                matching.append(book_anchor.get_attribute('href'))

        return matching

    def scrape_book_info(self, results):
        if not results:
            return

        book_info = None
        for book_url in results:
            try:
                response = self.session.get(book_url)
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                self.logger.error(f'Error fetching url {book_url}: {e}')
                continue

            with bs4_scope(response.content) as book_page:
                items_list = book_page.select(self.config['library_items_query'])
                yii_token = book_page.select_one(self.config['yii_token_query']).get('value')
                if not(items_list and yii_token):
                    continue

                book_info = self.scrape_first_book_info(
                    yii_token=yii_token,
                    items_list=items_list,
                )
                # All books are available in the same section.
                if book_info:
                    break

        return [book_info] if book_info else None

    def scrape_first_book_info(self, yii_token, items_list):
        book_info = None

        for item in items_list:
            # Check if book is available.
            is_book_available = self.get_book_accessibility(yii_token, item)
            if not is_book_available:
                continue

            # Extract book location, section and availability from row.
            item_signatures = item.select(self.config['location_details_query'])
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
            "docid": item.get(self.config['a11y_docid_key']),
            "doclibid": item.get(self.config['a11y_doclibid_key']),
            'locationid': item.get(self.config['a11y_locationid_key']),
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
        return (self.config['accepted_status'] in accessibility_value['message'])
# }}}
