#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import codecs
import json
import sys
import re
import subprocess
import threading
import pexpect
import time
import codecs
import urllib2
import cookielib
from BeautifulSoup import BeautifulSoup
from optparse import OptionParser
from imogeen import get_file_path, dump_books_list
from nomnom_filter import get_step_end_index
# }}}

KEY_DOWN       = '\x1b[B'
KEY_ESCAPE     = '\x1b'
KEY_BACKSPACE  = '\x7f'
OPAC_URL       = 'http://opac.ksiaznica.bielsko.pl/'

def test(): # {{{
    import urllib
    import urllib2
    import cookielib

    # Get session and cookie.
    host_ip            = '212.244.68.155'
    opac_link          = 'http://%s/Opac4/' % host_ip
    form_link          = '%sfaces/Szukaj.jsp' % opac_link
    autocompleter_link = '%sfaces/ax/autocmp.jsp' % opac_link

    # Prepare cookie jar.
    cookie_jar = cookielib.CookieJar()
    opener     = urllib2.build_opener(
        urllib2.HTTPCookieProcessor(cookie_jar),
        urllib2.HTTPHandler(debuglevel=1),
    )

    headers   = {
        # 'Accept':          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        # 'Accept-Encoding': "gzip, deflate",
        # 'Accept-Language': "en-US,en;q=0.5",
        # 'Connection':      'keep-alive',
        'Host':            host_ip,
        'Referer':         opac_link,
        'User-Agent':      "Mozilla/5.0",
    }

    opener.addheaders = [(key, headers[key]) for key in headers.keys()];
    request           = urllib2.Request(opac_link)
    response          = opener.open(request)

    # ck = cookielib.Cookie(version=0, name='haslo_hist', value="", port=None, port_specified=False, domain=host_ip, domain_specified=False, domain_initial_dot=False, path='/Opac4/', path_specified=True, secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={'HttpOnly': None}, rfc2109=False)
    # cookie_jar.set_cookie(ck)

    payload_autocompleter = {
        'idx' : 3,
        'txt' : 9788307033044,
    }

    # Append headers required by POST request.
    cookies = {}
    for cookie in cookie_jar:
        cookies[cookie.name] = cookie.value

    cookie_header = '; '.join( '%s=%s' % (key, cookies[key]) for key in cookies.keys())

    post_suffix = ';jsessionid=%s' % cookies['JSESSIONID']
    post_link   = '%s%s' % (form_link, post_suffix)

    payload_form = {
        # Index search method.
        'form1:btnSzukajIndeks': 'Szukaj',

        # Resource type:
        # 1 - Author
        # 2 - Title
        # 3 - ISBN
        # 4 - Series
        # 'form1:dropdown1': 3,
        'form1:dropdown1': "1",

        # Resource type:
        # 1  - All
        # 2  - Book
        # 9  - Magazine
        # 15 - Audiobook
        'form1:dropdown4': "2",

        # Search phrase.
        # 'form1:textField1': 9788307033044,
        'form1:textField1': "vandermeer",

        # 'Ustaw początek indeksu na podaną frazę'.
        'rbOperStem': "a",

        # Index.
        'form1:hidIdxId': "1",
        # 'form1:hidHistId': "",

        # Rubbish.
        'form1:textField2': "",
        'form1:textField3': "",
        'form1:textField4': "",
        'form1:textField5': "",
        'form1:dropdown2':  "2",
        'form1:dropdown3':  "3",
        'form1:dropdown4':  "2",
        'form1:dropdown5':  "20",
        'form1:dropdown6':  "-1",
        'rbOper1':          'a',
        'rbOper2':          'a',
        'rbOper1':          'a',
        'rbOper2':          'a',

        # Rubbish 2.
        'form1_hidden':                                               'form1_hidden',
        'javax.faces.ViewState':                                      'j_id24020:j_id24021',
        'com_sun_rave_web_ui_appbase_renderer_CommandLinkRendererer': "",
    }

    # POST headers.
    headers['Referer']      = form_link
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    headers['Cookie']       = cookie_header
    headers['Connection']   = 'keep-alive'
    opener.addheaders       = [(key, headers[key]) for key in headers.keys()];

    # request  = urllib2.Request(autocompleter_link, urllib.urlencode(payload_autocompleter))
    # response = opener.open(request)
    request  = urllib2.Request(post_link, urllib.urlencode(payload_form))
    response = opener.open(request)
# }}}

def query_and_dump_results(book, dump_file_name):
    # elinks browser instance.
    elinks = pexpect.spawn('elinks about:', timeout=10)

    # Open url.
    elinks.send('g')
    elinks.sendline(OPAC_URL)

    # "Wait for page to load."
    time.sleep(0.5)
    elinks.expect('Katalog Patron 3 Opac')

    # "Go to author search field."
    elinks.send(KEY_DOWN*14)
    elinks.sendline('')

    # Type query:

    # # - author
    # elinks.send('vandermeer')
    # elinks.send(KEY_ESCAPE)

    # - isbn
    elinks.send(book['isbn'])
    elinks.send(KEY_DOWN)
    elinks.sendline('')
    elinks.send(KEY_DOWN*2)
    elinks.sendline('')


    # Go to form submit.
    # # - author
    # elinks.send(KEY_DOWN*17)
    # - isbn
    elinks.send(KEY_DOWN*16)

    # Send form.
    elinks.sendline('')

    # Accept form sending.
    elinks.sendline('')

    # Wait for results.
    time.sleep(0.2)

    # Dump results.
    elinks.send(KEY_ESCAPE)
    elinks.send(KEY_DOWN + 's')
    elinks.send(KEY_BACKSPACE*54)
    elinks.send(dump_file_name)
    elinks.sendline('')

    # Quit elinks.
    elinks.sendline('q')
    
    return

def extract_book_info_params(dump_file_name, book):
    # Fetch results div from dumped file.
    parser = None
    with codecs.open(dump_file_name, 'r', 'utf-8') as file_handle:
        parser = BeautifulSoup(
            file_handle,
            convertEntities=BeautifulSoup.HTML_ENTITIES
        )

    # Skip empty results.
    results_div = parser.find('div', { 'class': 'hasla' })
    if not results_div:
        return

    # Result entries will be matched by isbn value.
    isbn = book['isbn'].replace('-', '')

    # Hrefs to all books in results.
    results_a  = results_div.findAll('a', { 'onclick': re.compile('return haslo') })

    # Extract params for GET book info request.
    get_params = None
    for a in results_a:
        if a.string.lstrip().replace('-', '') == isbn:
            onclick = a['onclick']
            match   = re.findall("'[^']+'", onclick)
            if match:
                get_params = re.sub("'", '', match[1])
            break

    return get_params

def extract_book_info_from_response(response):
    if not response:
        return

    info_by_library = []

    div = BeautifulSoup(
        response,
        convertEntities=BeautifulSoup.HTML_ENTITIES
    ).find('div', { 'id': 'zasob' })

    # Fetch 'td' tags containing book info by child element.
    warnings = div.findAll('div', { 'class': 'opis_uwaga' })
    info_td  = [ div.parent for div in warnings ]

    # Fetch department, address and availability info.
    re_department = re.compile('\([^\)]+\)')
    re_address    = re.compile('\,[^\,]+\,')
    for td in info_td:
        td_text = td.text

        # Get department string.
        department = re_department.search(td_text)
        if department:
            department = department.group()

        # Get address string.
        address = re_address.search(td_text)
        if address:
            address = address.group().replace(',', '').lstrip()

        # Get availability info.
        availability = td.find('div', { 'class': 'opis_uwaga' }).string
        if not availability:
            availability = u'Dostępna'

        info_by_library.append(
            '%s - %s - %s' % 
            (department, address, availability)
        )

    return info_by_library

def fetch_book_info(book, info_params):
    if not info_params:
        return

    # Prepare urls.
    form_url = '%sfaces/Szukaj.jsp' % OPAC_URL
    info_url = '%sfaces/ax/haslo?idh=%s' % (OPAC_URL, info_params)

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
    opener.addheaders = [(key, headers[key]) for key in headers.keys()];

    # Request used to initialize cookie.
    request  = urllib2.Request(OPAC_URL)
    response = opener.open(request)

    # Request used to fetch book info.
    request         = urllib2.Request(info_url)
    response_string = opener.open(request).read()

    # Extract book url from response.
    a = BeautifulSoup(
        response_string,
        convertEntities=BeautifulSoup.HTML_ENTITIES
    ).find('a')
    # Remove '/Opac4/' path entry before creating book url.
    # book_url = '%s%s' % (OPAC_URL, re.sub('\/Opac4\/', '', a['href']))
    book_url = '%s%s' % (OPAC_URL, a['href'].replace('/Opac4/', ''))

    request           = urllib2.Request(book_url)
    response_string   = opener.open(request).read()

    info_by_library = extract_book_info_from_response(response_string)

    return {
        'author': book['author'],
        'title' : book['title'],
        'info'  : info_by_library,
    }

def buu():
    import re
    import codecs
    import urllib2
    import cookielib
    from BeautifulSoup import BeautifulSoup
    from imogeen import get_file_path

    file_path = get_file_path('wynik.html')

    parser = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        parser = BeautifulSoup(
            file_handle,
            convertEntities=BeautifulSoup.HTML_ENTITIES
        )

    results_div = parser.find('div', { 'class': 'hasla' })

    if not results_div:
        raise "Buuuu!!"

    results_a   = results_div.findAll('a', { 'onclick': re.compile('return haslo') })

    isbn = '9788375152937'
    isbn_split = ('%s-%s-%s-%s-%s') % (isbn[:3], isbn[3:5], isbn[5:9], isbn[9:12], isbn[12])

    get_params = None
    for a in results_a:
        if a.string.lstrip() == isbn_split:
            onclick = a['onclick']
            match = re.findall("'[^']+'", onclick)
            if match:
                get_params = re.sub("'", '', match[1])
            break

    if get_params:
        host_ip   = '212.244.68.155'
        opac_link = 'http://%s/Opac4/' % host_ip
        form_link = '%sfaces/Szukaj.jsp' % opac_link
        info_link = '%sfaces/ax/haslo?idh=%s' % (opac_link, get_params)

        cookie_jar = cookielib.CookieJar()
        opener     = urllib2.build_opener(
            urllib2.HTTPCookieProcessor(cookie_jar),
            # urllib2.HTTPHandler(debuglevel=1),
        )

        headers   = {
            # 'Host':       host_ip,
            'Referer':    opac_link,
            'User-Agent': "Mozilla/5.0",
        }

        opener.addheaders = [(key, headers[key]) for key in headers.keys()];
        request           = urllib2.Request(opac_link)
        response          = opener.open(request)

        request           = urllib2.Request(info_link)
        response_string   = opener.open(request).read()

        a = BeautifulSoup(
            response_string,
            convertEntities=BeautifulSoup.HTML_ENTITIES
        ).find('a')
        book_link = 'http://%s/%s' % (host_ip, a['href'])

        request           = urllib2.Request(book_link)
        response_string   = opener.open(request).read()

def get_books_list(file_name):

    file_path = get_file_path(file_name)

    books_list = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        books_list = json.load(file_handle)

    return books_list

def book_dispatcher(book, lock, books_info):
    # Skip empty entries.
    if not book:
        return books_info

    with lock:
        # Print info.
        print(
            "\tProcessing book '%s - %s'." %
            (book['author'], book['title'])
        )

        # Search by title - author is not supported yet.
        if not book['isbn']:
            print(
                "\tSkipping book '%s - %s' - no isbn." %
                (book['author'], book['title'])
            )
            return

    # Retry operation 5 times before giving up.
    retry = 5
    while retry:
        # Get dump file name for current book.
        dump_file_name = '%s.html' % book['isbn']

        # Search and dump results file.
        with lock:
            print("\t\tQuerying OPAC server.")
        query_and_dump_results(book, dump_file_name)

        # Extract info url from dump.
        with lock:
            print("\t\tFetching book link.")
        info_params = extract_book_info_params(dump_file_name, book)

        # Remove dump file.
        os.remove(dump_file_name)

        # Retry fetching info?
        if info_params:
            with lock:
                print("\t\tBook link fetched.")
            retry = 0
        else:
            retry = retry - 1
            with lock:
                print("\t\tRetrying ...")

    # Fetch book info.
    with lock:
        print("\t\tFetching book info.")
    book_info = fetch_book_info(book, info_params)

    if book_info:
        with lock:
            print("\t\tWriting book info.")
            books_info.append(book_info)
    else:
        with lock:
            print("\t\tBook info not found.")

    return books_info

def get_library_status(books_list):
    if not books_list:
        return

    # Will contains books info.
    books_info = []

    # Lock for writing book info.
    lock = threading.Lock()

    # Process books in groups of 10.
    books_count = len(books_list)
    books_step  = 1

    # Create treads per group.
    for i in range(books_count)[::books_step]:
        j = get_step_end_index(books_count, books_step, i)

        # Start a new thead for each book.
        book_threads = [
            threading.Thread(
                target=book_dispatcher,
                args=(book, lock, books_info)
            )
            for book in books_list[i:j]
        ]

        # Wait for threads to finish.
        for thread in book_threads:
            thread.start()
        for thread in book_threads:
            thread.join()

    return books_info

def main():
    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-s", "--source")

    (options, args) = option_parser.parse_args()

    if not options.source:
        # Display help.
        option_parser.print_help()
    else:
        # Update books to read list.
        if options.refresh:
            print('Updating list of books to read.')
            subprocess.call([sys.executable, '-tt', './imogeen.py', '-t'])

        # Read in book to read.
        print('Reading in books list.')
        books_list = get_books_list(options.source)

        # Fetch books library status.
        print('Fetching books library status.')
        library_status = get_library_status(books_list)

        dump_books_list(library_status, 'opac.json')

    # pex()
    # buu()

if __name__ == "__main__":
    main()
