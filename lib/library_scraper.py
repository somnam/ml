import re
import json
import math
import logging
import datetime
import concurrent.futures
from lib.shelf_scraper import CLIShelfScraper
from lib.libraries import library_factory, LibraryNotSupported  # noqa: F401
from lib.automata import BrowserUnavailable
from lib.gdocs import get_service_client, write_rows_to_worksheet
from lib.xls import make_xls
from lib.common import get_file_path
from lib.config import Config


class LibraryNotConfigured(Exception):
    pass


class BooksListUnavailable(Exception):
    pass


class LibraryScraper:
    logger = logging.getLogger(__name__)

    def __init__(self, library_id, profile_name, auth_data, refresh=False):
        self.library_id = library_id
        self.profile_name = profile_name
        self.refresh = refresh
        self.library_factory = library_factory(library_id)
        self.config = Config()

        # Authenticate to Google if auth data is available.
        if auth_data:
            self.logger.info('Authenticating to Google service')
            self.google_client = get_service_client(auth_data)
        else:
            self.google_client = None

        # How many selenium workers will be used.
        self.nodes = (self.config['selenium'].getint('nodes')
                      if ('selenium' in self.config
                          and 'nodes' in self.config['selenium'])
                      else 5)

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
    def shelf_contents_file_name(self):
        if not hasattr(self, '_shelf_contents_file_name'):
            file_name = re.sub(r'\s+', '_', self.shelf_name.lower())
            file_name = f'{self.profile_name}_{file_name}.json'

            setattr(self, '_shelf_contents_file_name', file_name)
        return self._shelf_contents_file_name

    @property
    def shelf_books(self):
        if not hasattr(self, '_shelf_books'):
            shelf_contents_file_path = get_file_path('var',
                                                     self.shelf_contents_file_name)
            # Read file contents.
            self.logger.info(f'Reading in books list from shelf "{self.shelf_name}"')
            try:
                with open(shelf_contents_file_path, 'r', encoding='utf-8') as file_handle:
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

        # Fetch books status from library.
        try:
            books_status = self.fetch_books_status()
        except (BrowserUnavailable, BooksListUnavailable) as e:
            self.logger.error(f'Feching books status failed: {e}')
            return

        if not books_status:
            self.logger.info(f'No books from list available.')
            return

        # Write books status locally or in Google drive.
        self.write_books_status(books_status)

    def fetch_books_status(self):
        shelf_books = self.shelf_books
        self.logger.info(f'Fetching {len(shelf_books)} books library status')

        # Split shelf books into batches for worker nodes.
        step_size = math.ceil(len(shelf_books) / self.nodes)
        shelf_books_per_node = [shelf_books[i:i + step_size]
                                for i in range(0, len(shelf_books), step_size)]
        self.logger.debug(f'Built {len(shelf_books_per_node)} batches for nodes')

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.nodes) as executor:
            books_status_from_nodes = executor.map(self.fetch_books_status_using_node,
                                                   shelf_books_per_node)
        return [
            book_status
            for books_status_batch in books_status_from_nodes
            for book_status in books_status_batch
        ]

    def fetch_books_status_using_node(self, shelf_books_for_node):
        # Work, work?
        if not shelf_books_for_node:
            return

        # Get library instance.
        library = self.library_factory(books=shelf_books_for_node)

        # Fetch books status
        return library.run()

    def write_books_status(self, books_status):
        if self.google_client:
            self.write_books_status_to_google_drive(books_status)
        else:
            self.write_books_status_to_xls(books_status)

    def write_books_status_to_google_drive(self, books_status):
        # Convert books info to spreadsheet rows.
        worksheet_headers = self.config['library_scraper'].getstruct('worksheet_headers')
        rows = [[book[header] for header in worksheet_headers]
                for book in books_status]

        # Get workbook and worksheet title.
        workbook_title = self.config['library_scraper']['workbook_title']
        worksheet_title = f'{self.shelf_name} {datetime.date.today()}'

        self.logger.info('Writing books status to Google Drive')
        write_rows_to_worksheet(
            client=self.google_client,
            workbook_title=workbook_title,
            worksheet_title=worksheet_title,
            rows=rows,
        )
        self.logger.info('Books status written to Google Drive')

    def write_books_status_to_xls(self, books_status):
        worksheet_headers = self.config['library_scraper'].getstruct('worksheet_headers')
        worksheet_name = f'{datetime.date.today()}'

        self.logger.info('Writing books status to XLS file')
        make_xls(
            file_name=self.shelf_name,
            worksheet_name=worksheet_name,
            worksheet_headers=worksheet_headers,
            rows=books_status,
        )
        self.logger.info(f'Books status written to XLS file')


class CLILibraryScraper(LibraryScraper):
    logger = logging.getLogger('script')
