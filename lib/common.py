#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import sys
import json
import cookielib
import httplib
import urllib2
import codecs
from BeautifulSoup import BeautifulSoup
# }}}

def get_file_path(file_name):
    return os.path.join(
        os.path.dirname(__file__),
        '..',
        file_name
    )

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


def prepare_opener(url, headers=None, data=None):
    # Prepare request handler.
    cookie_jar = cookielib.CookieJar()
    opener     = urllib2.build_opener(
        urllib2.HTTPCookieProcessor(cookie_jar),
        # urllib2.HTTPHandler(debuglevel=1),
    )

    # Prepare request headers.
    headers = headers if headers else {}
    # Append user agent to headers.
    headers['User-Agent'] = headers['User-Agent'] if headers.has_key('User-Agent') \
                                                  else 'Mozilla/5.0 Gecko Firefox'
    # Append referer to headers.
    headers['Referer'] = headers['Referer'] if headers.has_key('Referer') else url

    # Update opener with headers
    opener.addheaders = [(key, headers[key]) for key in headers.keys()]

    return opener

def open_url(url, opener, data=None):
    request = urllib2.Request(url, data=data)

    response = None
    try:
        response = opener.open(request)
        if response.getcode() != 200:
            response = None
    except (
        httplib.BadStatusLine,
        urllib2.HTTPError,
        urllib2.URLError
    ) as e:
        print "Could not fetch url '%s'. Error: %s." % (url, e)

    return response

def get_url_response(url, headers=None, data=None, opener=None):
    """Send request to given url and ask for response."""

    opener = (opener or prepare_opener(url, headers=headers))

    return open_url(url, opener, data)

def parse_url_response(response):
    # Parse html response (if available)
    parser = None
    if response:
        try:
            parser = BeautifulSoup(
                response,
                convertEntities=BeautifulSoup.HTML_ENTITIES
            )
        except TypeError:
            print(u'Error fetching response for url "%s".' % url)

    return parser

def get_parsed_url_response(url, data=None, opener=None):
    """Send request to given url and return parsed HTML response."""

    # Fetch url response object
    return parse_url_response(get_url_response(url, data=data, opener=opener))


def print_progress():
    sys.stdout.write(".")
    sys.stdout.flush()

def print_progress_end():
    sys.stdout.write("\n")
    sys.stdout.flush()

