import re
import json
import logging
import aiohttp
import asyncio
from sqlalchemy import func
from itertools import chain
from datetime import date, datetime, timedelta
from lib.db import NewBooksInfoModel, Handler
from lib.xls import make_xls
from lib.gdocs import get_service_client, write_rows_to_worksheet
from lib.config import Config
from lib.shelf_scraper import CLIShelfScraper
from lib.utils import bs4_scope, ProgressCounter, shelf_name_to_file_path


class LibraryBase:
    logger = logging.getLogger(__name__)
    library_id = None

    def __init__(self, *args, **kwargs):
        self.config = Config()
        self.session = None

        self.handler = Handler()
        self.handler.create_all()

        # Set invalidate date.
        invalidate_days = self.config.getint('latest_books_scraper',
                                             'invalidate_days',
                                             fallback=1)
        self.invalidate_date = datetime.utcnow() - timedelta(days=invalidate_days)

    def __str__(self):
        return f'Library {self.library_id}'

    async def get_books_isbn(self):
        raise NotImplementedError()

    async def get_book_isbn_from_link(book_url):
        raise NotImplementedError()

    async def get_book_isbn(self, book_url):
        # Check if current page info exists in DB.
        isbn_list = self.get_book_isbn_from_db(book_url)
        if isbn_list is not None:
            return isbn_list

        isbn_list = await self.get_book_isbn_from_link(book_url)

        if isbn_list:
            self.store_book_isbn(book_url, isbn_list)
        return isbn_list

    def get_book_isbn_from_db(self, book_url):
        book_url_md5 = NewBooksInfoModel.md5_from_url(book_url)
        with self.handler.session_scope() as session:
            has_isbn = session.query(func.count(NewBooksInfoModel._pk))\
                .filter(NewBooksInfoModel.url_md5 == book_url_md5,
                        NewBooksInfoModel.created >= self.invalidate_date)\
                .scalar()
            if not has_isbn:
                return None

            return [
                row.isbn for row in session
                .query(NewBooksInfoModel.isbn)
                .filter(NewBooksInfoModel.url_md5 == book_url_md5,
                        NewBooksInfoModel.created >= self.invalidate_date)
            ]

    def store_book_isbn(self, book_url, isbn_list):
        book_url_md5 = NewBooksInfoModel.md5_from_url(book_url)
        with self.handler.session_scope() as session:
            session.query(NewBooksInfoModel).filter(
                NewBooksInfoModel.url_md5 == book_url_md5,
            ).delete(synchronize_session=False)

            session.bulk_save_objects([NewBooksInfoModel(
                url_md5=book_url_md5,
                library_id=self.library_id,
                isbn=isbn,
            ) for isbn in isbn_list])


class Library4949(LibraryBase):
    library_id = '4949'


class Library5004(LibraryBase):
    library_id = '5004'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.news_url_template = self.config.get(f'libraries:{self.library_id}',
                                                 'news_url_template')

    async def get_books_isbn(self):
        async with aiohttp.ClientSession() as self.session:
            book_urls = await self.get_book_urls()

            book_isbn_tasks = [self.get_book_isbn(book_url)
                               for book_url in book_urls]

            isbn_list = await asyncio.gather(*book_isbn_tasks)
            isbn_set = set(chain(*isbn_list))

        return isbn_set

    async def get_book_urls(self):
        news_urls = await self.prepare_news_urls()

        book_url_tasks = [self.get_book_urls_on_page(news_url)
                          for news_url in news_urls]

        book_urls = await asyncio.gather(*book_url_tasks)

        return list(chain(*book_urls))

    async def get_book_urls_on_page(self, news_url):
        base_url = self.config.get(f'libraries:{self.library_id}', 'base_url')

        try:
            async with self.session.get(news_url, raise_for_status=True) as response:
                content = await response.read()
                with bs4_scope(content) as news_page:
                    return [
                        f'{base_url}{a["href"]}' for a in
                        news_page.select(
                            'div.description-list-section > dl > dd:nth-child(2) > a'
                        )
                    ]
        except aiohttp.ClientError as e:
            self.logger.error(f'Fetching book urls on page failed: {e}')
            return []

    async def prepare_news_urls(self):
        params = await self.prepare_news_url_params()
        pagers = await self.prepare_news_url_pagers(params)

        return [
            self.news_url_template.format(*params, pager)
            for pager in pagers
        ]

    async def prepare_news_url_params(self):
        news_url = re.sub(r'\?.*$', '', self.news_url_template)

        defaults = {
            'agenda': '?f2[0]=7',
            'document_type': 'f4[0]=1',
            'language': 'f8[0]=pol',
            'pagination': 'rp=100',
        }

        try:
            async with self.session.get(news_url, raise_for_status=True) as response:
                # Prepare params for generatig urls.
                content = await response.read()
                config = self.config[f'libraries:{self.library_id}']
                with bs4_scope(content) as news_page:
                    agenda_title = config['agenda_title']
                    agenda = news_page.select_one(f'a[title="{agenda_title}"]')\
                        .get('href', f'/news?{defaults["agenda"]}')\
                        .replace('/news?', '')

                    document_type_title = config['document_type_title']
                    document_type = news_page.select_one(f'a[title="{document_type_title}"]')\
                        .get('href', f'/news?{defaults["document_type"]}')\
                        .replace('/news?', '')

                    language_title = config['language_title']
                    language = news_page.select_one(f'a[title="{language_title}"]')\
                        .get('href', f'/news?{defaults["language"]}')\
                        .replace('/news?', '')

                    pagination_re = re.compile(config['pagination_value'])
                    pagination = news_page.find('a', string=pagination_re)\
                        .get('href', f'/news?{defaults["pagination"]}')\
                        .replace('/news?', '')
        except aiohttp.ClientError as e:
            self.logger.error(f'Fetching news url params failed: {e}')
            agenda = defaults['agenda']
            document_type = defaults['document_type']
            language = defaults['language']
            pagination = defaults['pagination']

        return agenda, document_type, language, pagination

    async def prepare_news_url_pagers(self, params):
        # Open page with params to calculate pager.
        news_url = self.news_url_template.format(*params, '')

        try:
            async with self.session.get(news_url, raise_for_status=True) as response:
                content = await response.read()
                config = self.config[f'libraries:{self.library_id}']
                with bs4_scope(content) as news_page:
                    last_pager_re = re.compile(config['last_page_title'])
                    last_pager = news_page.find('a', string=last_pager_re)\
                        .get('href', '')\
                        .replace(news_url.replace(config['base_url'], ''), '')
        except aiohttp.ClientError as e:
            self.logger.error(f'Fetching news urls failed: {e}')
            return []

        # Get pager range from last pager.
        last_pager_items = int(re.sub(r'\D+', '', last_pager))
        per_page = config.getint('pagination_value')
        return [
            last_pager.replace(str(last_pager_items), str(items))
            for items in range(1, last_pager_items + per_page, per_page)
        ]

    async def get_book_isbn(self, book_url):
        # Check if current page info exists in DB.
        isbn_list = self.get_book_isbn_from_db(book_url)
        if isbn_list is not None:
            return isbn_list

        isbn_list = await self.get_book_isbn_from_link(book_url)

        if isbn_list:
            self.store_book_isbn(book_url, isbn_list)
        return isbn_list

    async def get_book_isbn_from_link(self, book_url):
        try:
            async with self.session.get(book_url, raise_for_status=True) as response:
                content = await response.read()
                with bs4_scope(content) as book_page:
                    isbn_label = book_page.find('dt', string=re.compile(r'ISBN'))
                    if not isbn_label:
                        return []

                    isbn_list_tag = isbn_label.find_next_sibling('dd')
                    if not isbn_list_tag:
                        return []

                    isbn_list = [re.sub(r'\D+', '', child.string)
                                 for child in isbn_list_tag.children
                                 if child.string]
        except aiohttp.ClientError as e:
            self.logger.error(f'Fetching book failed: {e}')
            return []

        return isbn_list


class LatestBooksScraper:
    logger = logging.getLogger(__name__)
    libraries = {'4994': Library4949, '5004': Library5004}

    def __init__(self, library_id, profile_name, auth_data, refresh=False):
        self.library = self.libraries.get(library_id)()
        self.profile_name = profile_name
        self.refresh = refresh
        self.config = Config()

        self.search_shelf_name = self.config.get('latest_books_scraper',
                                                 'search_shelf_name')
        self.search_file_path = shelf_name_to_file_path(self.profile_name,
                                                        self.search_shelf_name)

        # Get library settings.
        self.exclude_shelf_name = self.config.get(f'libraries:{library_id}',
                                                  'shelf_name')
        self.exclude_file_path = shelf_name_to_file_path(self.profile_name,
                                                         self.exclude_shelf_name)

        # Authenticate to Google if auth data is available.
        if auth_data:
            self.logger.info('Authenticating to Google service')
            self.google_client = get_service_client(auth_data)
        else:
            self.google_client = None

    def match_isbn_to_shelf_books(self, books_isbn):
        if not books_isbn:
            return

        with open(self.search_file_path, 'r') as search_books_file:
            search_books = {
                book['isbn']: book for book in
                json.load(search_books_file)
                if book['isbn'] is not None
            }
        self.logger.info(f'Got {len(search_books)} books to search for')

        with open(self.exclude_file_path, 'r') as exclude_books_file:
            exclude_books = {
                book['isbn']: book for book in
                json.load(exclude_books_file)
                if book['isbn'] is not None
            }
        self.logger.info(f'Got {len(exclude_books)} books to exclude from results')

        matching_books_isbn = set(search_books.keys())\
            .difference(exclude_books.keys())\
            .intersection(books_isbn)

        self.logger.info(f'Got {len(matching_books_isbn)} matching books')

        return [search_books[isbn] for isbn in matching_books_isbn]

    def write_books_info(self, matching_books):
        if self.google_client:
            self.write_books_info_to_google_drive(matching_books)
        else:
            self.write_books_info_to_xls(matching_books)

    def write_books_info_to_xls(self, matching_books):
        worksheet_headers = self.config.getstruct('latest_books_scraper',
                                                  'worksheet_headers')
        worksheet_name = f'{date.today()}'

        self.logger.debug('Writing books info to XLS file')
        make_xls(
            file_name=self.config.get('latest_books_scraper', 'xls_file_name'),
            worksheet_name=worksheet_name,
            worksheet_headers=worksheet_headers,
            rows=matching_books,
        )
        self.logger.info('Books info written to XLS file')

    def write_books_info_to_google_drive(self, matching_books):
        # Convert books info to spreadsheet rows.
        worksheet_headers = self.config.getstruct('latest_books_scraper',
                                                  'worksheet_headers')
        rows = [[book[header] for header in worksheet_headers]
                for book in matching_books]

        # Get workbook and worksheet title.
        workbook_title = self.config.get('latest_books_scraper', 'workbook_title')
        worksheet_title = self.config.get('latest_books_scraper', 'worksheet_title')\
            .format(date.today())

        self.logger.info('Writing books info to Google Drive')
        write_rows_to_worksheet(
            client=self.google_client,
            workbook_title=workbook_title,
            worksheet_title=worksheet_title,
            rows=rows,
        )
        self.logger.info('Books info written to Google Drive')

    def run(self):
        # Refresh books list.
        if self.refresh:
            for shelf_name in (self.search_shelf_name, self.exclude_shelf_name):
                self.logger.info(f'Updating list of books from shelf "{shelf_name}"')
                CLIShelfScraper(profile_name=self.profile_name,
                                shelf_name=shelf_name).run()

        books_isbn = asyncio.run(self.library.get_books_isbn())

        if not books_isbn:
            self.logger.info('No new books found')
            return

        matching_books = self.match_isbn_to_shelf_books(books_isbn)

        if matching_books:
            self.write_books_info(matching_books)
        else:
            self.logger.info('No matching books found')


class CLILibraryBaseMixin:
    logger = logging.getLogger('script')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.counter = None

    async def get_books_isbn(self):
        counter_title = 'Collecting books isbn '
        with ProgressCounter(counter_title) as self.counter:
            self.counter.update()
            isbn_set = await super().get_books_isbn()
        return isbn_set

    async def get_book_urls_on_page(self, news_url):
        urls_list = await super().get_book_urls_on_page(news_url)
        self.counter.next()
        return urls_list

    async def get_book_isbn(self, book_url):
        isbn_list = await super().get_book_isbn(book_url)
        self.counter.next()
        return isbn_list


class CLILibrary4949(CLILibraryBaseMixin, Library4949):
    pass


class CLILibrary5004(CLILibraryBaseMixin, Library5004):
    pass


class CLILatestBooksScraper(LatestBooksScraper):
    logger = logging.getLogger('script')
    libraries = {'4994': CLILibrary4949, '5004': CLILibrary5004}
