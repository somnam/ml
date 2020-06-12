import re
import os
from contextlib import contextmanager
from bs4 import BeautifulSoup
from progress.bar import Bar
from progress.counter import Counter
from threading import Lock


@contextmanager
def bs4_scope(markup):
    '''Parse markup to BeautifulSoup object and decompose it after use.'''
    parsed_markup = BeautifulSoup(markup, 'lxml')
    try:
        yield parsed_markup
    finally:
        parsed_markup.decompose()


def get_file_path(*file_name):
    return os.path.join(os.getcwd(), *file_name)


def shelf_name_to_file_path(profile_name, shelf_name):
    shelf_filename = re.sub(r'\s+', '_', shelf_name.lower())
    file_name = f'{profile_name}_{shelf_filename}.json'
    return get_file_path('var', file_name)


class ProgressBar(Bar):
    check_tty = False


class ProgressCounter(Counter):
    check_tty = False


class Singleton:
    _lock: Lock = Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not hasattr(cls, '_instance'):
                cls._insance = super().__new__(cls, *args, **kwargs)
        return cls._insance
