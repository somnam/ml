from contextlib import contextmanager
from bs4 import BeautifulSoup


@contextmanager
def bs4_scope(markup):
    '''Parse markup to BeautifulSoup object and decompose it after use.'''
    parsed_markup = BeautifulSoup(markup, 'lxml')
    try:
        yield parsed_markup
    finally:
        parsed_markup.decompose()
