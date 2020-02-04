import os
from contextlib import contextmanager
from bs4 import BeautifulSoup
from progress.bar import Bar


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


class ProgressBar(Bar):
    check_tty = False
