#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import sys
import simplejson as json
import cookielib
import httplib
import urllib2
import urlparse
import codecs
from BeautifulSoup import BeautifulSoup
from multiprocessing.dummy import Lock
# }}}

def get_file_path(file_name):
    return os.path.join(os.getcwd(), file_name)

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
    except IOError as (e,s):
        print "I/O error({0}): {1}".format(e,s)

    return file_data

def dump_json_file(struct, file_path):
    # utf-8 chars should be displayed properly in results file:
    # - codecs.open must be used instead of open, with 'utf-8' flag
    with codecs.open(file_path, 'w+', 'utf-8') as file_handle:
        # - json.dumps must have ensure_ascii set to False
        json.dump(struct, file_handle, ensure_ascii=False, indent=2)

    return


def prepare_opener(url, headers=None, data=None, cookie_jar=None):
    # Prepare jar for cookies.
    if cookie_jar is None: cookie_jar = cookielib.CookieJar()

    # Prepare request handler.
    opener     = urllib2.build_opener(
        urllib2.HTTPCookieProcessor(cookie_jar),
        # urllib2.HTTPHandler(debuglevel=1),
    )

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
    request = urllib2.Request(url, data=data)

    response = None
    try:
        response = opener.open(request)
        if response.getcode() != 200:
            response = None
    except (
        ValueError,
        httplib.BadStatusLine,
        urllib2.HTTPError,
        urllib2.URLError
    ) as e:
        if verbose:
            print "Could not fetch url '%s'. Error: %s." % (url, e)

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
                response,
                convertEntities=BeautifulSoup.HTML_ENTITIES
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
    return urlparse.urlparse(url).query

def print_progress(lock=Lock()):
    with lock:
        sys.stdout.write(".")
        sys.stdout.flush()

def print_progress_end(lock=Lock()):
    with lock:
        sys.stdout.write("\n")
        sys.stdout.flush()

