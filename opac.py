# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import json
import codecs
import socket
import shutil
import subprocess
import cookielib
import urllib2
import gdata.spreadsheet.service
from optparse import OptionParser
from BeautifulSoup import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from imogeen import get_file_path, dump_books_list
from nomnom_filter import (
    get_auth_data,
    connect_to_service,
    retrieve_spreadsheet_id,
    get_writable_worksheet,
    get_writable_cells
)

# Lovely constants.
OPAC_URL       = 'http://opac.ksiaznica.bielsko.pl/'
SOCKET_TIMEOUT = 4.0
REFRESH_SCRIPT = 'imogeen'
SHELF_NAME     = 'polowanie-biblioteczne'

def browser_start():
    print(u'Starting browser.')

    # Set browser profile.
    # profile = webdriver.FirefoxProfile('./firefox.selenium')
    # browser = webdriver.Firefox(firefox_profile=profile)

    # Load webdriver.
    browser = webdriver.Firefox()
    # Some of sites elements are loaded via ajax - wait for them.
    browser.implicitly_wait(1)
    return browser

def browser_load_opac(browser):
    print(u'Loading search form.')
    browser.get(OPAC_URL)
    assert 'Opac' in browser.title
    return

def browser_reload_opac(browser):
    print(u'Reloading search form.')
    browser.find_element_by_id('form1:textField1').clear()
    return

def browser_stop(browser):
    print('Stopping browser.')
    browser.quit()
    return

def browser_timeout(browser):
    print('Restarting browser.')

    # Kill current browser instance.
    # /F is to forcefully kill
    # /T is to kill all child processes
    taskkill = None
    if browser.binary and browser.binary.process:
        print(u'Killing firefox process "%s".' % browser.binary.process.pid)
        taskkill = 'taskkill /PID %s /F /T' % browser.binary.process.pid
    else:
        print(u'Killing firefox process.')
        taskkill = 'taskkill /IM firefox.exe /F /T'
    os.system(taskkill)

    # Remove temp folder.
    if browser.profile and browser.profile.tempfolder:
        print(u'Removing temporary profile.')
        time.sleep(0.1)
        shutil.rmtree(browser.profile.tempfolder)

    # Remove object.
    browser = None
    return

def browser_select_by_id_and_value(browser, select_id, select_value):
    select = Select(browser.find_element_by_id(select_id))
    select.select_by_value(select_value)
    return select

def browser_click(browser, elem):
    webdriver.ActionChains(browser).move_to_element(elem) \
                                   .click(elem) \
                                   .perform()
    return

def prepare_opener():
    # Prepare request handler.
    cookie_jar = cookielib.CookieJar()
    opener     = urllib2.build_opener(
        urllib2.HTTPCookieProcessor(cookie_jar),
        # urllib2.HTTPHandler(debuglevel=1),
    )

    # Prepare request headers.
    headers   = {
        'Referer':    OPAC_URL,
        'User-Agent': "Mozilla/5.0",
    }
    opener.addheaders = [(key, headers[key]) for key in headers.keys()]

    # Request used to initialize cookie.
    request = urllib2.Request(OPAC_URL)
    opener.open(request)

    return opener

# 'opener' will be created only once.
def get_url_response(url, opener = prepare_opener()):
    response = None
    if url:
        response = opener.open(urllib2.Request(url)).read()
    return response

# Search type:
# 1 - Author
# 2 - Title
# 3 - ISBN
# 4 - Series

# Resource type:
# 1  - All
# 2  - Book
# 9  - Magazine
# 15 - Audiobook
def query_book_by_isbn(book):
    return book['isbn'], '3', '2'
def query_book_by_title(book):
    return book['title'], '2', '2'

def query_book(browser, book):

    search_value, search_type, resource_type = None, None, None
    if book['isbn']:
        print(u'Querying book by isbn "%s" .' % book['isbn'])
        search_value, search_type, resource_type = query_book_by_isbn(book)
    elif book['title']:
        print(u'Querying book by title.')
        search_value, search_type, resource_type = query_book_by_title(book)

    # Input search value.
    print(u'Inputing search value.')
    browser.find_element_by_id('form1:textField1').send_keys(search_value)

    # Set search type.
    print(u'Setting search type.')
    browser_select_by_id_and_value(browser, 'form1:dropdown1', search_type)

    # Set resource_type.
    print(u'Setting resource type.')
    browser_select_by_id_and_value(browser, 'form1:dropdown4', resource_type)

    # Submit form.
    print(u'Submitting form.')
    submit = browser.find_element_by_id('form1:btnSzukajIndeks')
    browser_click(browser, submit)

    # Wait for results to appear.
    print(u'Waiting for results.')
    results         = None
    results_wrapper = browser.find_element_by_class_name('hasla')
    if (results_wrapper):
        results = results_wrapper.find_elements_by_tag_name('a')

    # Return search results.
    print(u'Returning search results.')
    return results

def get_matching_result(browser, book, results):
    if not results:
        print(u'No match found.')
        return

    match_field, replace_from = None, None
    if book['isbn']:
        match_field, replace_from = 'isbn', '-'
    elif book['title']:
        match_field, replace_from = 'title', ' '

    match_value = book[match_field].replace(replace_from, '')
    print(u'Matching for value by field "%s".' % match_field)

    match = None
    for elem in results:
        if elem.text.lstrip().replace(replace_from, '') == match_value:
            print(u'Found match.')
            browser_click(browser, elem)
            match = elem.find_element_by_xpath('..') \
                        .find_element_by_class_name('zawartosc') \
                        .find_element_by_tag_name('a')
            break

    if not match:
        print(u'No match found.')

    return match

def extract_book_info(browser, book, match):
    if not (book and match):
        return

    print(u'Redirecting to book info.')
    book_url = match.get_attribute('href')
    response = get_url_response(book_url)

    print(u'Fetching book infos.')
    div = BeautifulSoup(
        response,
        convertEntities=BeautifulSoup.HTML_ENTITIES
    ).find('div', { 'id': 'zasob' })
    warnings = div.findAll('div', { 'class': 'opis_uwaga' })
    infos    = [ div.parent for div in warnings ]

    re_department   = re.compile('\([^\)]+\)')
    re_address      = re.compile('\,[^\,]+\,')

    # Fetch department, address and availability info.
    info_by_library = []
    for i in range(len(infos)):
        print(u'Fetching department, address and availability info %d.' % i)
        info, warning = infos[i].text, warnings[i].text

        # Get department string.
        department = re_department.search(info)
        if department:
            department = department.group()

        # Get address string.
        address = re_address.search(info)
        if address:
            address = address.group().replace(',', '').lstrip()

        # Get availability info.
        availability = warning
        if not availability:
            availability = u'Dostępna'

        info_by_library.append(
            '%s - %s - %s' % 
            (department, address, availability)
        )

    div.decompose()

    return "\n".join(info_by_library)

def get_book_info(browser, book):
    # Query book and fetch results.
    results = query_book(browser, book)
    match   = get_matching_result(browser, book, results)
    info    = extract_book_info(browser, book, match)

    print(u'Done fetching info.')
    return {
        'author': book['author'],
        'title' : '"%s"' % book['title'],
        'info'  : info if info else "Brak",
    }

def get_library_status(books_list):
    if not books_list:
        return

    # Get browser.
    browser = browser_start()

    # Load opac site.
    browser_load_opac(browser)

    # Will contains books info.
    books_info = []

    for book in books_list:
        book_info = None

        # Retry when fetching book info
        # (usually triggered by browser hang).
        retry = 2
        while not book_info and retry:
            # Set timeout for request.
            socket.setdefaulttimeout(SOCKET_TIMEOUT)

            # Try fetching book info.
            try:
                # Reload opac site.
                browser_reload_opac(browser)

                # Fetch book info.
                book_info = get_book_info(browser, book)
            except socket.timeout:
                print(u'Querying book info timed out.')
                # Restart browser.
                browser_timeout(browser)
                browser = browser_start()
                browser_load_opac(browser)
            else:
                print(u'Succsessfully queried book info.')
            finally:
                # Restore default timeout value.
                socket.setdefaulttimeout(None)

            # Append book info if present.
            if book_info:
                books_info.append(book_info)
            else:
                # Retry?
                retry -= 1
                if retry:
                    print(u'Retrying ...')

    browser_stop(browser)

    return books_info

def get_books_list(file_name):

    file_path = get_file_path(file_name)

    books_list = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        books_list = json.load(file_handle)

    return books_list

def write_books(client, dst_cells, library_status):
    # Prepare request that will be used to update worksheet cells.
    batch_request = gdata.spreadsheet.SpreadsheetsCellsFeed()

    cell_index = 0
    for book_status in library_status:
        for key in ('author', 'title', 'info'):
            # Fetch next cell.
            text_cell = dst_cells.entry[cell_index]

            # Update cell value.
            text_cell.cell.inputValue = book_status[key]
            batch_request.AddUpdate(text_cell)

            # Go to next cell.
            cell_index += 1

    # Execute batch update of destination cells.
    return client.ExecuteBatch(
        batch_request, dst_cells.GetBatchLink().href
    )

def get_books_source_file(source):
    return source if re.match(r'^.*\.json$', source) else '%s_%s.json' % (
        REFRESH_SCRIPT, source
    )

def refresh_books_list(source):
    print(u'Updating list of books from source "%s".' % source)
    script_file = './%s.py' % REFRESH_SCRIPT
    return subprocess.call([
        sys.executable,
        '-tt',
        script_file,
        '-s',
        source
    ])

def main():
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-s", "--source")
    option_parser.add_option("-a", "--auth-data")

    (options, args) = option_parser.parse_args()

    if not options.auth_data:
        # Display help.
        option_parser.print_help()
    else:
        books_source = (options.source or SHELF_NAME)

        if options.refresh:
            refresh_books_list(books_source)

        books_source_file = get_books_source_file(books_source)

        # Read in books list.
        print(u'Reading in books list.')
        books_list = get_books_list(books_source_file)

        # Fetch books library status.
        print(u'Fetching books library status.')
        library_status     = get_library_status(books_list)
        status_entries_len = len(library_status)

        # dump_books_list(library_status, 'opac.json')
        # library_status = get_books_list('opac.json')

        # Read auth data from input file.
        print(u'Fetching auth data.')
        auth_data = get_auth_data(options.auth_data)

        # Connect to spreadsheet service.
        print(u'Authenticating to Google service.')
        client = connect_to_service(auth_data)

        # Fetch spreadsheet id.
        spreadsheet_title = u'Karty'
        ssid              = retrieve_spreadsheet_id(client, spreadsheet_title)

        dst_worksheet_name = SHELF_NAME.capitalize()
        print("Fetching destination worksheet '%s'." % dst_worksheet_name)
        dst_worksheet      = get_writable_worksheet(
            client,
            dst_worksheet_name,
            ssid,
            row_count=status_entries_len,
        )

        print("Fetching destination cells.")
        writable_cells = get_writable_cells(
            client,
            dst_worksheet,
            ssid,
            max_row=status_entries_len,
            max_col=3,
        )

        print("Writing books.")
        write_books(client, writable_cells, library_status)

if __name__ == "__main__":
    main()
