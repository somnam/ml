import re
import json
import logging
import requests
from json import JSONDecodeError
from urllib.parse import urlparse
from requests.exceptions import HTTPError, ConnectionError
from datetime import datetime, timedelta
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool, Lock
from lib.db import BookShelfInfoModel, Handler
from lib.utils import bs4_scope, ProgressBar
from lib.config import Config
from lib.utils import shelf_name_to_file_path
from lib.exceptions import ProfileNotFoundError, ShelvesScrapeError, BooksCollectError,\
    DatabaseError


class ShelfScraper:
    logger = logging.getLogger(__name__)

    def __init__(self, profile_name, shelf_name, include_price=False):
        self.profile_name = profile_name
        self.shelf_name = shelf_name
        self.include_price = include_price

        self.config = Config()['shelf_scraper']
        self.isbn_sub_re = re.compile(r'\D+')

        invalidate_days = self.config.getint('invalidate_days', fallback=30)
        self.invalidate_date = datetime.utcnow() - timedelta(days=invalidate_days)

        self.handler = Handler()
        self.handler.create_all()

        self.profile_id = None
        self.shelves = None
        self.session = None
        self.pool = None

    def run(self):
        with requests.Session() as self.session:
            # Fetch profile id for given name
            try:
                self.profile_id = self.get_profile_id()
            except ProfileNotFoundError as e:
                self.logger.error(f'Profile search failed: {e}')
                return

            try:
                self.shelves = self.get_book_shelves()
            except ShelvesScrapeError as e:
                self.logger.error(f'Shelf "{self.shelf_name}" not found: {e}')
                return

            # Fetch books from given shelves.
            try:
                self.get_books()
            except (BooksCollectError, DatabaseError) as e:
                self.logger.error(e)
                return

    def get_profile_id(self):
        return self.match_profile_by_name(self.search_for_profile())

    def search_for_profile(self):
        self.logger.info(f'Searching for profile "{self.profile_name}"')
        try:
            # Query user.
            response = self.session.post(
                self.config['lc_profile_search_url'],
                data={'phrase': self.profile_name},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )
            response.raise_for_status()

            # Parse json response.
            response_json = response.json()
            search_results = response_json['data']['content']
            self.logger.debug(f'Got search results: {bool(search_results)}')
        except (HTTPError, JSONDecodeError, KeyError) as e:
            raise ProfileNotFoundError(f'HTML request error: {e}')

        return search_results

    def match_profile_by_name(self, search_results):
        self.logger.debug('Matching profile in search results')

        profile_url_re = re.compile(r'/profil/\d+/{0}'.format(self.profile_name),
                                    re.IGNORECASE)
        with bs4_scope(search_results) as parsed_results:
            # Search for profile link in results.
            profile_link = parsed_results.find('a', {'href': profile_url_re})

        if not profile_link:
            raise ProfileNotFoundError('Empty search result')

        parsed_url = urlparse(profile_link.get('href'))
        if not parsed_url.path:
            raise ProfileNotFoundError(f'Profile matching {self.profile_name}'
                                       ' not found')

        profile_id_result = re.search(r'\d+', parsed_url.path)

        if not(profile_id_result and profile_id_result.group()):
            raise ProfileNotFoundError(f'Profile id matching {self.profile_name}'
                                       ' not found')

        profile_id = profile_id_result.group()
        self.logger.info(f'Found profile matching "{self.profile_name}"'
                         f' with id: {profile_id}')
        return profile_id

    def get_book_shelves(self):
        return self.build_book_shelves_from_shelf_tags(
            self.search_for_book_shelf_tags()
        )

    def search_for_book_shelf_tags(self):
        self.logger.info(f'Searching for shelf "{self.shelf_name}"'
                         if self.shelf_name != 'all'
                         else 'Fetching all book shelves')
        try:
            response = self.session.get(self.get_profile_library_url())
            response.raise_for_status()
            with bs4_scope(response.content) as profile_library:
                # Select single shelf or all shelves.
                shelves_selector = 'ul.filtr__wrapItems'
                if self.shelf_name != 'all':
                    shelves_selector += f' input[data-shelf-name="{self.shelf_name}"]'
                else:
                    shelves_selector += ' input[name="shelfs[]"]'

                shelf_tags = profile_library.select(shelves_selector)
        except HTTPError as e:
            raise ShelvesScrapeError(f'HTML request error: {e}')

        if not shelf_tags:
            raise ShelvesScrapeError(f'Shelves list not found')

        return shelf_tags

    def build_book_shelves_from_shelf_tags(self, shelf_tags):
        book_shelves = []
        for shelf_tag in shelf_tags:
            shelf_id = shelf_tag['value']
            shelf_name = shelf_tag['data-shelf-name']
            shelf_url = self.get_shelf_url(shelf_id)

            try:
                self.logger.debug(f'Fetching "{shelf_name}" shelf page at {shelf_url}')
                response = self.session.get(shelf_url)
                response.raise_for_status()
                with bs4_scope(response.content) as shelf_page:
                    self.logger.debug(f'Fetching "{shelf_name}" pager info')
                    last_pager_tag = shelf_page.select_one(
                        'ul#buttonPaginationListP'
                        '> li.page-item:nth-last-child(2)'
                        '> a.page-link'
                    )
                    pager_count = (int(last_pager_tag['data-pager-page'])
                                   if last_pager_tag else 1)
            except HTTPError as e:
                raise ShelvesScrapeError(f'HTML request error: {e}')

            shelf = {
                'id': shelf_id,
                'name': shelf_name,
                'pager_count': pager_count,
            }
            self.logger.debug(f'Shelf info: {shelf}')

            # Append shelf info.
            book_shelves.append(shelf)

        self.logger.info(f'Found shelf matching "{self.shelf_name}"'
                         if self.shelf_name != 'all'
                         else 'Fetched all book shelves')

        return book_shelves

    def get_books(self):
        for shelf in self.shelves:
            with Pool(processes=(cpu_count())) as self.pool:
                self.logger.debug(f'Fetching "{shelf["name"]}" shelf books')
                shelf_book_urls = self.get_shelf_book_urls(shelf)

            if not shelf_book_urls:
                self.logger.warning(f'No books found on shelf {shelf["name"]}')
                continue
            self.logger.debug(f'Shelf book urls: {shelf_book_urls}')

            with Pool(processes=(cpu_count() * 2)) as self.pool:
                shelf_books = self.get_books_from_urls(shelf_book_urls)
                self.logger.debug(f'Shelf books: {shelf_books}')

                if self.include_price:
                    self.set_book_prices(shelf_books)

            self.sort_books_list(shelf_books)
            self.save_books_list(shelf['name'], shelf_books)

    def get_shelf_book_urls(self, shelf):
        pages_info = [json.dumps({'page': page, 'shelf_id': shelf['id']})
                      for page in range(1, shelf['pager_count'] + 1)]

        shelf_book_urls = [
            book_url
            for book_urls in self.pool.map(self.get_page_book_urls, pages_info)
            for book_url in book_urls
        ]
        return shelf_book_urls

    def get_page_book_urls(self, page_info_json):
        try:
            page_info = json.loads(page_info_json)
            data = {
                'page': page_info['page'],
                'listId': 'booksFilteredList',
                'shelfs[]': page_info['shelf_id'],
                'objectId': self.profile_id,
                'own': 0,
            }
            self.logger.debug(f'Requesting page {self.config["lc_shelf_page_url"]}'
                              f' with data {data}')
            response = self.session.post(
                self.config['lc_shelf_page_url'],
                data=data,
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )
            response.raise_for_status()

            # Parse json response.
            response_json = response.json()
            response_content = response_json['data']['content']
            self.logger.debug(f'Got page content: {bool(response_content)}')

            # Parse HTML response part.
            with bs4_scope(response_content) as pager_page:
                book_urls = [
                    f'{self.config["lc_url"]}{link["href"]}'
                    for link in pager_page.select(
                        'div#booksFilteredListPaginator'
                        ' a.authorAllBooks__singleTextTitle'
                    )
                ]
                self.logger.debug(f'Found {len(book_urls)} urls on page {page_info["page"]}')
        except JSONDecodeError as e:
            raise BooksCollectError(f'JSON error: {e}')
        except HTTPError as e:
            raise BooksCollectError(f'HTML request error: {e}')

        return book_urls

    def get_books_from_urls(self, shelf_book_urls):
        shelf_books = self.pool.map(self.get_book_info, shelf_book_urls)
        return shelf_books

    def get_book_info(self, book_url):
        # Check if current book info exists in DB.
        with self.handler.session_scope() as session:
            book_info = session.query(BookShelfInfoModel.book_info).filter(
                BookShelfInfoModel.url_md5 == BookShelfInfoModel.md5_from_url(book_url),
                BookShelfInfoModel.created >= self.invalidate_date,
            ).scalar()

        if book_info:
            return book_info

        book_info = self.get_book_info_by_url(book_url)
        with self.handler.session_scope() as session:
            session.query(BookShelfInfoModel).filter(
                BookShelfInfoModel.url_md5 == BookShelfInfoModel.md5_from_url(book_url),
            ).delete(synchronize_session=False)
            session.add(BookShelfInfoModel(
                url_md5=BookShelfInfoModel.md5_from_url(book_url),
                book_info=book_info,
            ))

        return book_info

    def get_book_info_by_url(self, book_url):
        try:
            response = self.session.get(book_url)
            response.raise_for_status()
            with bs4_scope(response.content) as book_page:
                # Get title and author.
                title = book_page.select_one(
                    'div.title-container'
                )['data-title']
                author = book_page.select_one(
                    'span.author > a.link-name'
                ).text.strip()

                # Search for subtitle in title.
                subtitle = None
                if '.' in title:
                    title, subtitle = title.split('.', maxsplit=1)

                # Get details element.
                book_details = book_page.select_one('div#book-details')

                # Get original title.
                original_title_tag = book_details.select_one(
                    'dt:-soup-contains("Tytuł oryginału") + dd'
                )
                original_title = (original_title_tag.text.strip()
                                  if original_title_tag else None)

                # Get pages count.
                pages_count_tag = book_details.select_one(
                    'dt:-soup-contains("Liczba stron") + dd'
                )
                pages_count = (pages_count_tag.text.strip()
                               if pages_count_tag else None)

                # Get category.
                category = book_page.select_one('a.book__category').text.strip()

                # Get release date.
                release_tag = book_details.select_one(
                    'dt:-soup-contains("Data wydania") + dd'
                )
                release = (release_tag.text.strip() if release_tag else None)

                # Get book ISBN. ISBN is not always present.
                isbn_tag = book_details.select_one(
                    'dt:-soup-contains("ISBN") + dd'
                )
                isbn = (self.isbn_sub_re.sub('', isbn_tag.text) if isbn_tag else None)

                book_info = {
                    'title': title,
                    'subtitle': subtitle,
                    'original_title': original_title,
                    'author': author,
                    'category': category,
                    'pages': pages_count,
                    'url': book_url,
                    'isbn': isbn,
                    'release': release,
                }
        except (HTTPError, JSONDecodeError) as e:
            raise BooksCollectError(f'HTML request error: {e}')

        return book_info

    def set_book_prices(self, shelf_books):
        self.pool.map(self.set_book_price, shelf_books)

    def set_book_price(self, book):
        try:
            response = self.session.get(
                self.config['bb_url'],
                params={
                    'name': book['title'],
                    'info': book['author'],
                    'number': book['isbn'],
                    'skip_jQuery': '1',
                },
            )
            response.raise_for_status()

            price_info = json.loads(response.text)
            if not price_info.get('status'):
                book['price'] = 0.0
                return

            book_price = self.find_retailer_book_price(price_info)
        except (HTTPError, ConnectionError, JSONDecodeError) as e:
            raise BooksCollectError(f'HTML request error: {e}')

        book['price'] = book_price

    def find_retailer_book_price(self, price_info):
        entries = (price_info['data'].values()
                   if type(price_info['data']) is dict
                   else price_info['data'])

        book_price = 0.0
        retailer_choices = self.config.getstruct('retailers')
        for entry in entries:
            has_retailer_price = (
                entry.get('type', '') == 'book'
                and entry.get('name', '') in retailer_choices
            )
            if not has_retailer_price:
                continue

            book_price = float(entry.get('price', book_price))
            break

        return book_price

    def sort_books_list(self, shelf_books):
        self.logger.debug('Sorting books')

        sort_key = 'price' if self.include_price else 'release'
        reverse_sort = sort_key != 'price'
        default_value = 0.0 if sort_key == 'price' else ''

        shelf_books.sort(key=lambda book: getattr(book, sort_key, default_value),
                         reverse=reverse_sort)

    def save_books_list(self, shelf_name, shelf_books):
        raise NotImplementedError

    def get_profile_library_url(self):
        return self.get_profile_url(f'{self.profile_id}/{self.profile_name}'
                                    '/biblioteczka/lista')

    def get_shelf_url(self, shelf_id):
        return self.get_profile_url(f'{self.profile_id}/{self.profile_name}'
                                    f'/biblioteczka/lista?shelfs={shelf_id}')

    def get_profile_url(self, path):
        return (path
                if self.config['lc_profile_url'] in path
                else f'{self.config["lc_profile_url"]}/{path}')


class CLIShelfScraper(ShelfScraper):
    logger = logging.getLogger('script')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = None
        self.lock = Lock()

    def get_shelf_book_urls(self, shelf):
        bar_title = f'Collecting shelf pages'
        with ProgressBar(bar_title, max=shelf["pager_count"]) as self.bar:
            shelf_book_urls = super().get_shelf_book_urls(shelf)
        return shelf_book_urls

    def get_page_book_urls(self, page_info_json):
        book_urls = super().get_page_book_urls(page_info_json)
        with self.lock:
            self.bar.next()
        return book_urls

    def get_books_from_urls(self, shelf_book_urls):
        bar_title = 'Collecting books'
        with ProgressBar(bar_title, max=len(shelf_book_urls)) as self.bar:
            shelf_books = super().get_books_from_urls(shelf_book_urls)
        return shelf_books

    def get_book_info(self, book_url):
        book_info = super().get_book_info(book_url)
        with self.lock:
            self.bar.next()
        return book_info

    def set_book_prices(self, shelf_books):
        bar_title = 'Collecting book prices'
        with ProgressBar(bar_title, max=len(shelf_books)) as self.bar:
            super().set_book_prices(shelf_books)

    def set_book_price(self, book):
        super().set_book_price(book)
        with self.lock:
            self.bar.next()

    def save_books_list(self, shelf_name, shelf_books):
        self.logger.info(f'Writing books on shelf {shelf_name} to file')
        file_path = shelf_name_to_file_path(self.profile_name, shelf_name)
        with open(file_path, 'w', encoding='utf-8') as file_handle:
            json.dump(shelf_books, file_handle, ensure_ascii=False, indent=2)
