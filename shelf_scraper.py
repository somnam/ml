import re
import json
import click
import logging
import logging.config
from multiprocessing.dummy import Lock
from progress.bar import Bar
from lib.common import get_file_path
from lib.shelf_scraper import ShelfScraper

logging.config.fileConfig(get_file_path('etc', 'config.ini'))


class CLIShelfScraper(ShelfScraper):
    logger = logging.getLogger('script')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = None
        self.lock = Lock()

    def get_shelf_book_urls(self, shelf):
        bar_title = f'Collecting shelf pages'
        with Bar(bar_title, max=shelf["pager_count"]) as self.bar:
            shelf_book_urls = super().get_shelf_book_urls(shelf)
        return shelf_book_urls

    def get_page_book_urls(self, page_info_json):
        book_urls = super().get_page_book_urls(page_info_json)
        with self.lock:
            self.bar.next()
        return book_urls

    def get_books_from_urls(self, shelf_book_urls):
        bar_title = f'Collecting  books'
        with Bar(bar_title, max=len(shelf_book_urls)) as self.bar:
            shelf_books = super().get_books_from_urls(shelf_book_urls)
        return shelf_books

    def get_book_info(self, book_url):
        book_info = super().get_book_info(book_url)
        with self.lock:
            self.bar.next()
        return book_info

    def set_book_prices(self, shelf_books):
        bar_title = f'Collecting book prices'
        with Bar(bar_title, max=len(shelf_books)) as self.bar:
            super().set_book_prices(shelf_books)

    def set_book_price(self, book):
        super().set_book_price(book)
        with self.lock:
            self.bar.next()

    def shelf_name_to_file_path(self, shelf_name):
        shelf_filename = re.sub(r'\s+', '_', shelf_name.lower())
        file_name = f'{self.profile_name}_{shelf_filename}.json'
        return get_file_path('var', file_name)

    def save_books_list(self, shelf_name, shelf_books):
        file_path = self.shelf_name_to_file_path(shelf_name)
        self.logger.info('Writing books to file')
        with open(file_path, 'w', encoding='utf-8') as file_handle:
            json.dump(shelf_books, file_handle, ensure_ascii=False, indent=2)


@click.command()
@click.option('--profile-name', required=True, help='Profile name')
@click.option('--shelf-name', required=True, help='Shelf name to search')
@click.option('--include-price', is_flag=True, default=False,
              help='Append price to books')
def run(profile_name, shelf_name, include_price):
    CLIShelfScraper(profile_name=profile_name,
                    shelf_name=shelf_name,
                    include_price=include_price).run()


if __name__ == '__main__':
    run()
