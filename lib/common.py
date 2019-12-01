# -*- coding: utf-8 -*-

# Import {{{
import os
import ssl
import sys
import json
import codecs
from http.cookiejar import CookieJar
from http.client import BadStatusLine
from urllib.request import (build_opener, HTTPCookieProcessor, HTTPSHandler, Request)
from urllib.error import (HTTPError, URLError)
from urllib.parse import urlparse, urlencode
from bs4 import BeautifulSoup
from multiprocessing.dummy import Lock
# }}}


def get_file_path(*file_name):
    return os.path.join(os.getcwd(), *file_name)
