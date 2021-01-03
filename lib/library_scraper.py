import concurrent.futures
import datetime
import json
import logging
import math
import re
from operator import itemgetter

from lib.config import Config
from lib.exceptions import (BooksListUnavailable, BrowserUnavailable,
                            LibraryNotConfigured)
from lib.gdocs import get_service_client, write_rows_to_worksheet
from lib.libraries import library_factory
from lib.shelf_scraper import CLIShelfScraper
from lib.utils import get_file_path
from lib.xls import make_xls


class LibraryScraper:
    logger = logging.getLogger(__name__)

    def __init__(self, library_id, profile_name, auth_data, refresh=False):
        self.library_id = library_id
        self.profile_name = profile_name
        self.refresh = refresh
        self.config = Config()

        invalidate_days = self.config.getint('library_scraper', 'invalidate_days',
                                             fallback=1)
        self.library_factory = library_factory(library_id=library_id,
                                               logger=self.logger.name,
                                               invalidate_days=invalidate_days)

        # Authenticate to Google if auth data is available.
        if auth_data:
            self.logger.info('Authenticating to Google service')
            self.google_client = get_service_client(auth_data)
        else:
            self.google_client = None

        # How many selenium workers will be used.
        self.nodes = self.config.getint('library_scraper', 'selenium_nodes',
                                        fallback=5)
        self.retry_run = self.config.getint('library_scraper', 'selenium_retry_run',
                                            fallback=25)

    @property
    def shelf_name(self):
        if not hasattr(self, '_shelf_name'):
            library_section = f'libraries:{self.library_id}'

            if library_section in self.config and 'shelf_name' in self.config[library_section]:
                shelf_name = self.config[library_section]['shelf_name']
            else:
                raise LibraryNotConfigured('Library section not found in config')

            setattr(self, '_shelf_name', shelf_name)
        return self._shelf_name

    @property
    def shelf_file_name(self):
        if not hasattr(self, '_shelf_file_name'):
            file_name = re.sub(r'\s+', '_', self.shelf_name.lower())
            file_name = f'{self.profile_name}_{file_name}.json'

            setattr(self, '_shelf_file_name', file_name)
        return self._shelf_file_name

    @property
    def shelf_books(self):
        if not hasattr(self, '_shelf_books'):
            shelf_file_path = get_file_path('var', self.shelf_file_name)
            # Read file contents.
            self.logger.info(f'Reading in books list from shelf "{self.shelf_name}"')
            try:
                with open(shelf_file_path, 'r', encoding='utf-8') as file_handle:
                    file_data = json.load(file_handle)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                raise BooksListUnavailable(e)

            self.logger.debug(f'Read {len(file_data)} entries from file')

            setattr(self, '_shelf_books', file_data)
        return self._shelf_books

    def run(self):
        self.logger.info(f'Starting for shelf "{self.shelf_name}"')

        # Refresh books list.
        if self.refresh:
            self.logger.info(f'Updating list of books from shelf "{self.shelf_name}"')
            CLIShelfScraper(profile_name=self.profile_name,
                            shelf_name=self.shelf_name).run()

        # Fetch books info from library.
        try:
            books_info = self.fetch_books_info()
        except (BrowserUnavailable, BooksListUnavailable) as e:
            self.logger.error(f'Fetching books info failed: {e}')
            return

        if not books_info:
            self.logger.info('No books from list available.')
            return

        # Write books info locally or in Google drive.
        self.write_books_info(books_info)

    def fetch_books_info(self):
        shelf_books = self.shelf_books
        self.logger.info(f'Fetching {len(shelf_books)} books library info')

        # Split shelf books into batches for worker nodes.
        step_size = math.ceil(len(shelf_books) / self.nodes)
        shelf_books_per_node = [shelf_books[i:i + step_size]
                                for i in range(0, len(shelf_books), step_size)]
        self.logger.debug(f'Built {len(shelf_books_per_node)} batches for nodes')

        # Fetch status using worker nodes.
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.nodes) as executor:
            books_info_from_nodes = executor.map(self.fetch_books_info_using_node,
                                                 shelf_books_per_node)
        # Join results from nodes into a single list.
        books_info = [
            book_info
            for books_info_batch in books_info_from_nodes
            for book_info in books_info_batch
        ]

        # Sort books by deparment and section.
        books_info.sort(key=itemgetter('department', 'section'))

        return books_info

    def fetch_books_info_using_node(self, shelf_books_for_node):
        # Work, work?
        if not shelf_books_for_node:
            return

        # Get library instance.
        self.logger.debug('Creating library instance')
        library = self.library_factory(books=shelf_books_for_node)

        # Fetch books info
        self.logger.debug('Running library search')
        retry_run = self.retry_run
        while retry_run:
            try:
                return library.run()
            except BrowserUnavailable as e:
                self.logger.error(f'Restarting browser due to: {e}.')
            finally:
                retry_run -= 1

        # All retries have failed.
        self.logger.critical(f"Unable to search library {self.library_id}")
        return []

    def write_books_info(self, books_info):
        if self.google_client:
            self.write_books_info_to_google_drive(books_info)
        else:
            self.write_books_info_to_xls(books_info)

    def write_books_info_to_google_drive(self, books_info):
        # Convert books info to spreadsheet rows.
        worksheet_headers = self.config['library_scraper'].getstruct('worksheet_headers')
        rows = [[book[header] for header in worksheet_headers]
                for book in books_info]

        # Get workbook and worksheet title.
        workbook_title = self.config['library_scraper']['workbook_title']
        worksheet_title = f'{self.shelf_name} {datetime.date.today()}'

        self.logger.info('Writing books info to Google Drive')
        write_rows_to_worksheet(
            client=self.google_client,
            workbook_title=workbook_title,
            worksheet_title=worksheet_title,
            rows=rows,
        )
        self.logger.info('Books info written to Google Drive')

    def write_books_info_to_xls(self, books_info):
        worksheet_headers = self.config['library_scraper'].getstruct('worksheet_headers')
        worksheet_name = f'{datetime.date.today()}'

        self.logger.info('Writing books info to XLS file')
        make_xls(
            file_name=self.shelf_name,
            worksheet_name=worksheet_name,
            worksheet_headers=worksheet_headers,
            rows=books_info,
        )
        self.logger.info('Books info written to XLS file')


class CLILibraryScraper(LibraryScraper):
    logger = logging.getLogger('script')
