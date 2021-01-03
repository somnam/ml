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
                search_results = self.get_books_search_results()
            except (NoSuchWindowException, TimeoutException, WebDriverException) as e:
                # Save error screenshot.
                timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
                screenshot_path = get_file_path(f"var/log/critical_error_{timestamp}.png")
                self.browser.save_screenshot(screenshot_path)

                raise BrowserUnavailable(e)

        return search_results

    def open_library_page(self):
        # Open library page.
        self.browser.get(self.config['url'])
        # Check if correct library page is opened.
        if 'title' in self.config and self.config['title']:
            if self.config['title'] not in self.browser.title:
                raise LibraryPageNotValid('Incorrect library page title:'
                                          f' {self.browser.title}')

    def get_books_search_results(self):
        search_results = []
        for book in self.books:
            self.logger.debug(f"Start search '{book['title']}' by {book['author']}")

            search_result = self.get_book_search_result(book)

            if search_result:
                self.logger.info(f'Successfully queried "{book["title"]}" by {book["author"]}.')
                search_results.append(search_result)
            else:
                self.logger.info(f'Book "{book["title"]}" by {book["author"]} not found.')

            self.logger.debug(f"End search '{book['title']}' by {book['author']}")

        return [entry
                for search_result in search_results
                for entry in search_result]

    def get_book_search_result(self, book):
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

        search_results = self.search_for_book(book)

        with self.handler.session_scope() as session:
            book_availability = session.query(BookLibraryAvailabilityModel).filter(
                BookLibraryAvailabilityModel.library_id == self.config["id"],
                BookLibraryAvailabilityModel.book_md5 == book_md5,
            ).one_or_none()
            if book_availability:
                book_availability.search_results = search_results
                book_availability.created = datetime.utcnow()
            else:
                book_availability = BookLibraryAvailabilityModel(
                    library_id=self.config['id'],
                    book_md5=BookLibraryAvailabilityModel.md5_from_book(book),
                    search_results=search_results,
                )
            session.add(book_availability)

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

            # Book info:
            # [{}] - book was found as available, end search
            # []   - book was found but is unavailable, end search
            # None - book wasn't found, search by other criteria
            if search_results is not None:
                search_results = self.process_search_results(book, search_results)
                break
            # Any fields to search by remain?
            elif search_fields:
                self.logger.info(f'Retry fetching book "{book["title"]}" by {book["author"]}.')
        return search_results

    def search_for_book_by_field(self, book, search_field):
        # Query book and fetch results.
        search_form_results = self.search(
            book, search_field
        )
        matching_search_form_results = self.filter_search_results(
            book, search_form_results
        )
        return self.scrape_search_results(
            book, matching_search_form_results
        )

    def process_search_results(self, book, search_results):
        if not search_results:
            self.logger.warning(f'Book "{book["title"]}" by {book["author"]} not available.')
            return None

        # Book has been successfully queried or is not for rent.
        return [{
            "author": book["author"],
            "title": book["title"],
            "department": entry[0],
            "section": entry[1],
            "pages": book["pages"],
            "link": book["url"],
        } for entry in search_results]

    def search(self, book, search_field):
        raise NotImplementedError()

    def filter_search_results(self, book, results):
        raise NotImplementedError()

    def scrape_search_results(self, book, results):
        raise NotImplementedError()
# }}}


class Library4949(LibraryBase):  # {{{
    def __init__(self, books):
        super().__init__(library_id=4949, books=books)

    def search(self, book, search_field):
        # Check if book contains given search field.
        if not book.get(search_field):
            return

        return (self.search_using_isbn(book)
                if search_field == 'isbn'
                else self.search_using_title(book))

    def search_using_isbn(self, book):
        results_after_submit = self.submit_search_form(
            search_field=self.config["search_by_isbn_query"],
            value=book['isbn'],
        )

        if not results_after_submit:
            self.logger.debug('No results found after submit form.')
            return None

        results_after_filter = self.apply_search_filters()

        if not results_after_filter:
            self.logger.debug('No results found after apply filters.')
            return None

        # Return search results.
        return self.browser.find_elements_by_css_selector(self.config['result_row_query'])

    def search_using_title(self, book):
        self.logger.debug(f"Search '{book['title']}' by {book['author']} using title")

        results_after_submit = self.submit_search_form(
            search_field=self.config["search_by_title_query"],
            value=book['title'],
        )

        if not results_after_submit:
            self.logger.debug('No results found after submit form.')
            return None

        results_after_advanced_submit = self.submit_advanced_form(
            search_field=self.config['search_by_author_query'],
            value=book['author'],
        )

        if not results_after_advanced_submit:
            self.logger.debug('No results found after submit advanced form.')

            return None

        results_after_filter = self.apply_search_filters()

        if not results_after_filter:
            self.logger.debug('No results found after apply filters.')
            return None

        # Return search results.
        return self.browser.find_elements_by_css_selector(self.config['result_row_query'])

    def set_select_option(self, select_query, option_xpath):
        if self.browser.wait_is_visible_by_css(select_query, timeout=1):
            self.browser.find_element_by_css_selector(select_query).click()
            if self.browser.wait_is_visible_by_xpath(option_xpath, timeout=1):
                self.browser.find_element_by_xpath(option_xpath).click()
                return True

        return False

    def submit_search_form(self, search_field, value):
        # Reopen main search form.
        if not self.browser.wait_is_visible_by_xpath(self.config['main_page_query']):
            raise LibraryPageNotValid("Unable to open search page.")

        self.browser.find_element_by_xpath(self.config['main_page_query']).click()

        if not self.browser.wait_is_visible_by_css(self.config['search_form_query']):
            raise LibraryPageNotValid("Unable to load search form.")

        # Input search value.
        self.browser.set_input_value_by_css(self.config['search_input_query'], value)
        # Hide autocomplete popup.
        self.hide_autocomplete_popup(self.config['search_input_query'],
                                     self.config['search_autocomplete_query'])

        # Set search by field.
        self.set_select_option(self.config["search_by_query"], search_field)

        # Submit form.
        if not self.browser.wait_is_visible_by_css(self.config['search_button_query']):
            raise LibraryPageNotValid("Unable to submit search form.")

        self.browser.find_element_by_css_selector(self.config['search_button_query']).click()
        self.logger.debug('Submit form.')

        # Check if no results were found.
        if self.browser.wait_is_visible_by_css(self.config['no_results_query']):
            self.logger.debug('No results found after submit form.')
            return False

        return True

    def submit_advanced_form(self, search_field, value):
        if self.browser.wait_is_visible_by_css(self.config['add_search_form_query']):
            self.browser.find_element_by_css_selector(self.config['add_search_form_query'])\
                .click()
            self.logger.debug('Setting advanched search.')

            # Set operator field.
            operator_set = self.set_select_option(self.config["add_operator_query"],
                                                  self.config["search_and_query"])
            if operator_set:
                self.logger.debug('Setting search operator.')

            # Set search by field.
            if self.set_select_option(self.config['add_search_by_query'], search_field):
                self.logger.debug('Setting search type.')

            # Input field value.
            self.browser.set_input_value_by_css(self.config['add_search_input_query'], value)
            self.logger.debug('Setting search value.')
            self.hide_autocomplete_popup(self.config['add_search_input_query'],
                                         self.config['search_autocomplete_query'])

            # Submit form.
            if self.browser.wait_is_visible_by_css(self.config['add_search_button_query']):
                self.browser.find_element_by_css_selector(self.config['add_search_button_query'])\
                    .click()
                self.logger.debug('Submitting advanced search.')

        # Check if no results were found.
        if self.browser.wait_is_visible_by_css(self.config['no_results_query']):
            self.logger.debug('No results found after submit form.')
            return False

        return True

    def apply_search_filters(self):

        # Set document type.
        self.logger.debug('Apply document type filter.')
        books_selectable = self.browser.wait_is_clickable_by_xpath(
            self.config['book_document_query'], timeout=3
        )
        if not books_selectable:
            return False

        self.browser.find_element_by_xpath(self.config['book_document_query'])\
            .click()

        # Check for available locations.
        self.logger.debug('Apply locations filter.')
        locations_selectable = self.browser.wait_is_clickable_by_xpath(
            self.config['available_locations_query']
        )
        if not locations_selectable:
            return False

        self.browser.find_element_by_xpath(self.config['available_locations_query'])\
            .click()

        # Set accepted locations.
        more_locations_selectable = self.browser.wait_is_clickable_by_xpath(
            self.config['more_locations_query'], timeout=1
        )
        if more_locations_selectable:
            self.browser.find_element_by_xpath(self.config['more_locations_query'])\
                .click()
            self.logger.debug('Enable more accepted locations.')

        any_location_set = False
        for accepted_location_query in self.config.getstruct("accepted_locations_query"):
            self.logger.debug('Try enable accepted location.')
            location_selectable = self.browser.wait_is_clickable_by_xpath(
                accepted_location_query, timeout=1
            )
            if location_selectable:
                self.browser.find_element_by_xpath(accepted_location_query).click()
                self.logger.debug('Enabled accepted location.')
                any_location_set = True

        # Close expanded locations filter.
        self.browser.find_element_by_xpath(self.config['available_locations_query'])\
            .click()

        # No accepted locations available.
        if not any_location_set:
            return False

        # Filter unavailable items.
        availability_selectable = self.browser.wait_is_clickable_by_css(
            self.config['button_availability_query'], timeout=1
        )
        if availability_selectable:
            self.browser.find_element_by_css_selector(self.config['button_availability_query'])\
                .click()
            if self.browser.wait_is_clickable_by_xpath(
                self.config['button_available_query'], timeout=1
            ):
                self.browser.find_element_by_xpath(self.config['button_available_query'])\
                    .click()

            self.logger.debug('Filter unavailable items.')

        # Check if all results were filtered out.
        return not self.browser.wait_is_visible_by_css(
            self.config['no_results_query'], timeout=1
        )

    def hide_autocomplete_popup(self, text_field_query, autocomp_popup_query):
        if self.browser.wait_is_visible_by_css(
            autocomp_popup_query, timeout=10
        ):
            self.logger.debug('Hide autocomplete popup.')
            text_field = self.browser.find_element_by_css_selector(text_field_query)
            text_field.send_keys(Keys.ESCAPE)
            self.browser.wait_is_not_visible_by_css(autocomp_popup_query)

    def filter_search_results(self, book, results):
        if not results:
            return

        return [
            result for result in results
            if book['author'] in result.text and book['title'] in result.text
        ]

    def scrape_search_results(self, book, results):
        if not results:
            return

        accepted_locations = self.config.getstruct('accepted_locations')

        search_results = []
        for result in results:
            # Open action modal on result item.
            result.find_element_by_css_selector(self.config['action_button_query']).click()
            if not self.browser.wait_is_visible_by_css(
                self.config['action_modal_query'], timeout=1
            ):
                continue
            self.logger.debug('Open action modal on result item.')

            # Wait for loading overlay to hide.
            self.browser.wait_is_not_visible_by_css(self.config['modal_loading_overlay'])

            # Select available items only.
            if self.browser.wait_is_visible_by_xpath(self.config['modal_only_available_query']):
                self.browser.find_element_by_xpath(self.config['modal_only_available_query']).click()
            self.logger.debug('Select available items only.')

            # Item not available in any accepted location?
            if self.browser.wait_is_visible_by_xpath(
                self.config['modal_no_results_query'], timeout=1
            ):
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
                section = ''
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

                search_results.append((location, section))

            # Close modal.
            self.browser.find_element_by_xpath(self.config['modal_close_button']).click()

        return search_results
# }}}


class Library5004(LibraryBase):  # {{{
    def __init__(self, books):
        super().__init__(library_id=5004, books=books)

    def open_library_page(self):
        super().open_library_page()

        # Confirm modal dialog.
        try:
            modal_confirm_class = '.modal-dialog input.btn-primary'
            if self.browser.wait_is_visible_by_css(modal_confirm_class):
                self.browser.find_element_by_css_selector(modal_confirm_class).click()
        except NoSuchElementException:
            pass

    def search_for_book(self, book):
        # Wait for submit button to be visible.
        try:
            search_button = '.btn.search-main-btn'
            self.browser.wait_is_visible_by_css(search_button)
        except NoSuchElementException:
            pass

        search_result = super().search_for_book(book)

        # Reopen search form page.
        try:
            main_page_selector = 'h1.library_title-pages > a'
            self.browser.find_element_by_css_selector(main_page_selector).click()
        except NoSuchElementException:
            pass

        return search_result

    def set_search_value(self, search_value):
        # Input search value.
        search_input = '#SimpleSearchForm_q'
        if self.browser.wait_is_visible_by_css(search_input):
            self.browser.find_element_by_css_selector(search_input)\
                .send_keys(search_value)
            return True
        return False

    def search(self, book, search_field):
        # Search field didn't load - can't run query.
        search_value = '"{0}" AND "{1}"'.format(book['title'], book['author'])
        if not self.set_search_value(search_value):
            return None

        # Submit form.
        search_button = '.btn.search-main-btn'
        self.browser.find_element_by_css_selector(search_button).click()

        # Wait for results to load.
        results_header = '.row.row-full-text'
        self.browser.wait_is_visible_by_css(results_header)

        results = None
        try:
            self.browser.find_element_by_css_selector('.info-empty')
        except NoSuchElementException:
            # Display up to 100 results on page.
            if self.browser.wait_is_visible_by_css('.btn-group>.hidden-xs'):
                self.browser.find_element_by_css_selector('.btn-group>.hidden-xs')\
                    .click()
                if self.browser.wait_is_visible_by_css('.btn-group.open>.dropdown-menu'):
                    self.browser.find_element_by_css_selector(
                        '.btn-group.open>.dropdown-menu>li:last-child'
                    ).click()
            results = self.browser.find_elements_by_css_selector('dl.dl-horizontal')
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
