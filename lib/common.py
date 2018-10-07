# -*- coding: utf-8 -*-

# Import {{{
import os
import ssl
import sys
import json
import codecs
from http.cookiejar import CookieJar
from http.client import BadStatusLine
from urllib.request import (build_opener, HTTPCookieProcessor, HTTPSHandler,  Request)
from urllib.error import (HTTPError, URLError)
from urllib.parse import urlparse, urlencode
from bs4 import BeautifulSoup, Comment
from multiprocessing.dummy import Lock
# }}}

def get_file_path(file_name):
    return os.path.join(os.getcwd(), file_name)

def remove_file(file_name):
    file_path = get_file_path(file_name)
    if os.path.isfile(file_path):
        os.remove(file_path)

def make_dir_if_not_exists(dir_path):
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
        except:
            if not os.path.isdir(dir_path):
                raise
        else:
            print(u'Creating path %s' % dir_path.decode('utf-8'))

def get_json_file(file_name):

    file_path = get_file_path(file_name)

    file_data = None
    try:
        with codecs.open(file_path, 'r', 'utf-8') as file_handle:
            file_data = json.load(file_handle)
    except IOError as e:
        errno, strerror = e.args
        print("I/O error({0}): {1}".format(errno, strerror))

    return file_data

def get_config(script_name):
    if script_name is not None and len(script_name):
        config        = get_json_file('config.json')
        script_config = config[script_name] if script_name in config else None
    return (script_config or {})

def dump_json_file(struct, file_path):
    # utf-8 chars should be displayed properly in results file:
    # - codecs.open must be used instead of open, with 'utf-8' flag
    with codecs.open(file_path, 'w+', 'utf-8') as file_handle:
        # - json.dumps must have ensure_ascii set to False
        json.dump(struct, file_handle, ensure_ascii=False, indent=2)

    return

def get_unverifield_ssl_handler():
    return HTTPSHandler(context=ssl._create_unverified_context())

def prepare_opener(url, headers=None, data=None, handlers=None, cookie_jar=None):
    # Prepare jar for cookies.
    if cookie_jar is None: cookie_jar = CookieJar()

    if handlers is None: handlers = []
    handlers.append(HTTPCookieProcessor(cookie_jar))

    # Prepare request handler.
    opener = build_opener(*handlers)

    # Prepare request headers.
    headers = headers if headers else {}

    # Append user agent to headers.
    if not 'User-Agent' in headers: headers['User-Agent'] = 'Mozilla/5.0 Gecko Firefox'

    # Append referer to headers.
    if not 'Referer' in headers: headers['Referer'] = url

    # Update opener with headers
    opener.addheaders = [(key, headers[key]) for key in headers.keys()]

    return opener

def open_url(url, opener, data=None, verbose=True):
    request = Request(url, data=data)

    response = None
    try:
        response = opener.open(request)
        response = (response if response.getcode() == 200 else None)
    except (ValueError, BadStatusLine, HTTPError, URLError) as e:
        if verbose:
            print("Could not fetch url '%s'. Error: %s." % (url, e))

    return response

def get_url_response(url, headers=None, data=None, opener=None, verbose=True):
    """Send request to given url and ask for response."""

    if opener is None: opener = prepare_opener(url, headers=headers)

    return open_url(url, opener, data, verbose=verbose)

def parse_url_response(response, verbose=True):
    # Parse html response (if available)
    parser = None
    if response:
        try:
            parser = BeautifulSoup(
                # Convert results to utf-8 encoding.
                response.read().decode('utf-8', 'ignore'),
                "lxml",
            )
        except TypeError:
            if verbose:
                print(u'Error parsing response.')

    return parser

def get_parsed_url_response(url, data=None, opener=None, verbose=True):
    """Send request to given url and return parsed HTML response."""

    # Fetch url response object
    return parse_url_response(
        get_url_response(url, data=data, opener=opener, verbose=verbose),
        verbose=verbose
    )

def get_url_query_string(url):
    return urlparse(url).query

def get_url_net_location(url):
    parser = urlparse(url)
    return '{0}://{1}/'.format(parser.scheme, parser.netloc)

def build_url(base_url, query):
    if not base_url: return ''
    return '{0}?{1}'.format( base_url, urlencode(query or {}) )

def encode_url_params(params):
    return urlencode(params).encode("utf-8")

def print_progress(lock=Lock()):
    with lock:
        sys.stdout.write(".")
        sys.stdout.flush()

def print_progress_end(lock=Lock()):
    with lock:
        sys.stdout.write("\n")
        sys.stdout.flush()

