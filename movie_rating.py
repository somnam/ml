#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import re
import urllib
import urllib2
import simplejson as json
from optparse import OptionParser
from multiprocessing.dummy import Pool, cpu_count, Lock
from filecache import filecache
from fuzzywuzzy import fuzz
from lib.common import (
    prepare_opener,
    get_parsed_url_response,
    get_file_path,
    get_json_file,
    print_progress,
    print_progress_end,
    make_dir_if_not_exists,
)
from lib.gdocs import (
    get_service_client,
    write_rows_to_worksheet,
)
from lib.xls import make_xls
# }}}

FILTERS     = get_json_file('movie_rating.json')
IMDB_SITE   = 'https://www.imdb.com'
ROTTEN_SITE = 'https://www.rottentomatoes.com/'

def extract_tokens(dirname):
    closer_re  = re.compile('[\)\[\}].*$')
    opener_re  = re.compile('[\(\[\{]')
    version_re = re.compile(FILTERS['version'], flags=re.IGNORECASE)
    release_re = re.compile(FILTERS['release'])
    space_re   = re.compile('[\.\_]')
    year_re    = re.compile('\d{4}')
    trim_re    = re.compile('(^\s+)|(\s+$)')

    movie_title = closer_re.sub('',  dirname)
    movie_title = opener_re.sub('',  movie_title)
    movie_title = version_re.sub('', movie_title)
    movie_title = release_re.sub('', movie_title)
    movie_title = space_re.sub(' ',  movie_title)
    movie_year  = year_re.search(movie_title)
    movie_year  = movie_year.group() if movie_year else None
    movie_title = year_re.sub('', movie_title)
    movie_title = trim_re.sub('', movie_title)

    return json.dumps({
        'movie_title': movie_title,
        'movie_year':  int(movie_year) if movie_year else None,
    })

def extract_info(movie_struct):
    movie_struct = json.loads(movie_struct)
    info = [movie_struct['movie_title']] \
         + rottentomatoes_info(movie_struct) \
         + imdb_info(movie_struct)

    # Print progress.
    print_progress()

    return info

def normalize_rating(rating):
    float_re   = re.compile('.*\d+\.\d+.*')
    slash_re   = re.compile('.*\d+\/\d+.*')
    percent_re = re.compile('.*\d+\%')
    na_re      = re.compile('N\/A')

    normalized_rating = rating.strip()

    # Skip not available values.
    if na_re.match(normalized_rating):
        return ''

    if float_re.match(normalized_rating):
        rating_base = 10
        if slash_re.match(normalized_rating):
            normalized_rating, rating_base = normalized_rating.split('/')
            rating_base                    = int(rating_base)

        if rating_base == 5:
            normalized_rating = float(normalized_rating) * rating_base * 4
        elif rating_base == 10:
            normalized_rating = float(normalized_rating) * rating_base
    elif slash_re.match(normalized_rating):
        normalized_rating = normalized_rating.split('/')[0]
    elif percent_re.match(normalized_rating):
        normalized_rating = normalized_rating.replace('%', '')

    return str(int(normalized_rating))

def prepare_site_opener(site_url):
    opener = prepare_opener(site_url)

    # Initialize cookie.
    request    = urllib2.Request(site_url)
    opener.open(request)

    return opener

def prepare_imdb_opener():
    return prepare_site_opener(IMDB_SITE)

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def imdb_info(movie_struct, opener=prepare_imdb_opener()):
    empty_value = ['']*5

    movie_title, movie_year = (movie_struct[key] for key in ('movie_title', 'movie_year'))

    # http://www.imdb.com/find?q=
    search_url = '%s/find?%s' % (
        IMDB_SITE,
        urllib.urlencode({ 'q': movie_title.encode('utf-8') })
    )
    response   = get_parsed_url_response(search_url, opener=opener)
    if not response: return empty_value

    if response.find('div', {'class': 'findNoResults'}):
        response.decompose()
        return empty_value

    res_list = response.find('table', {'class': 'findList'})
    res_rows = res_list.findAll('td', {'class': 'result_text' })
    year_re  = re.compile('\d{4}')

    movies_list = []
    for res_row in res_rows:
        decoded_title = res_row.i.string if res_row.i else res_row.a.string
        decoded_year  = res_row.a.nextSibling.string.strip()
        year_match    = year_re.search(decoded_year)
        decoded_year  = int(year_match.group()) if year_match else None
        decoded_href  = res_row.first('a')['href'] if res_row.first('a') else None
        movies_list.append({
            'title': decoded_title,
            'year':  decoded_year,
            'href':  decoded_href,
        })

    movie_exact_match = match_movie_title_and_year(
        movie_title, movie_year, movies_list
    )

    href_suffix = movie_exact_match['href'] if movie_exact_match else None
    if not href_suffix:
        response.decompose()
        return empty_value

    movie_url  = '%s/%s' % (IMDB_SITE, href_suffix)
    movie_page = get_parsed_url_response(movie_url, opener=opener)
    if not movie_page: 
        response.decompose()
        return empty_value

    movie_overview = movie_page.find('div', { 'id': 'title-overview-widget' })
    if not movie_overview:
        movie_page.decompose()
        response.decompose()
        return empty_value

    movie_details = movie_overview.find('div', {'class': 'plot_summary_wrapper'})
    movie_infobar = movie_overview.find('div', {'class': 'title_bar_wrapper'})

    # Extract movie rating, title and genre.
    imdb_rating, movie_duration, movie_genre = '', '', ''
    if movie_infobar:
        imdb_rating_el = movie_infobar.find('span', {'itemprop': 'ratingValue'})
        if imdb_rating_el:
            imdb_rating = normalize_rating(imdb_rating_el.string)

        movie_duration_el = movie_infobar.find('time', {'itemprop': 'duration'})
        if movie_duration_el:
            movie_duration \
                = movie_duration_el.string.replace('min', '').strip()

        movie_genres_el = movie_infobar.findAll('span', { 'itemprop': 'genre' })
        movie_genre     = ', '.join([genre.string for genre in movie_genres_el])

    # Extract description and metacritic value.
    movie_description, metacritic_rating = '', ''
    if movie_details:
        metacritic_re        = re.compile('metacriticScore')
        metacritic_rating_el = movie_details.find('div', {'class': metacritic_re})
        if metacritic_rating_el:
            metacritic_rating = normalize_rating(
                metacritic_rating_el.find('span').string
            )

        movie_description_el = movie_details.find('div', {'class': 'summary_text'})
        if movie_description_el:
            movie_description = movie_description_el.text

    info = [
        imdb_rating,
        metacritic_rating,
        movie_duration,
        movie_genre,
        movie_description,
    ]

    movie_page.decompose()
    response.decompose()

    return info

def prepare_rotten_opener():
    return prepare_site_opener(ROTTEN_SITE)

# Invalidate values after 30 days.
@filecache(30 * 24 * 60 * 60)
def rottentomatoes_info(movie_struct, opener=prepare_rotten_opener()):
    info = ['']

    movie_title, movie_year = (movie_struct[k] for k in ('movie_title', 'movie_year'))

    # http://www.rottentomatoes.com/search/?search=
    search_url = '%s/search/?%s' % (
        ROTTEN_SITE,
        urllib.urlencode({ 'search': movie_title.encode('utf-8') })
    )
    response   = get_parsed_url_response(search_url, opener=opener)
    if not response: return info

    # Extract JS content loader script.
    script = response.find('div', {'id': 'main_container'}).find('script').text
    # Extract JSON struct from script.
    search_re    = "(?<='%s',\s){.*\}(?=\);)" % movie_title
    found_struct = re.search(search_re, script)
    if not found_struct:
        response.decompose()
        return info

    decoded_struct = json.loads(found_struct.group())
    movies_list    = decoded_struct['movies'] if decoded_struct.has_key('movies') else []

    for movie in movies_list:
        movie['title'] = movie.pop('name', None)
        movie['year']  = int(movie['year']) if movie['year'] else None

    movie_exact_match = match_movie_title_and_year(
        movie_title, movie_year, movies_list
    )

    if movie_exact_match and movie_exact_match.has_key('meterScore'):
        info[0] = movie_exact_match['meterScore']

    response.decompose()

    return info

def match_movie_title_and_year(movie_title, movie_year, decoded_movies):
    movie_exact_match = None
    movie_maybe_match = { 'title_ratio': None, 'movie': None }

    for dec_movie in decoded_movies:
        # Match movie name using fuzzy matching
        title_ratio    = fuzz.partial_ratio(movie_title, dec_movie['title'])
        title_in_range = title_ratio >= 90

        # Match movie year
        # First check if year is exactly the same
        year_ok_match = (dec_movie['year'] == movie_year) if movie_year else True
        # Next check for (-1, +1) date range.
        year_in_range = dec_movie['year'] in range(movie_year-1, movie_year+2) if not year_ok_match else True

        if title_in_range and year_ok_match:
            movie_exact_match = dec_movie
            movie_maybe_match = None
            break

        if title_in_range and year_in_range:
            if (not movie_maybe_match or
                (movie_maybe_match and movie_maybe_match['title_ratio'] < title_ratio)
            ):
                movie_maybe_match['title_ratio'] = title_ratio
                movie_maybe_match['movie']       = dec_movie

    if not movie_exact_match and movie_maybe_match:
        movie_exact_match = movie_maybe_match['movie']

    return movie_exact_match

def extract_folders(extract_path):
    dirs = os.listdir(extract_path)
    vdir = 'Videos'

    # If we have dirs to process, check if 'Videos' directory is present.
    if dirs:
        make_dir_if_not_exists(get_file_path(vdir))

    for dir_name in dirs:
        dir_path = os.path.join(os.path.dirname(__file__), vdir, dir_name)
        make_dir_if_not_exists(dir_path)

def get_worksheet_name():
    return u'Filmoceny'

def write_movies_to_gdata(auth_data, headers, info):
    info.insert(0, headers)

    # Drive connecton boilerplate.
    print("Authenticating to Google service.")
    client = get_service_client(auth_data)

    print('Writing movies info.')
    spreadsheet_title = u'Karty'
    write_rows_to_worksheet(
        client,
        spreadsheet_title,
        get_worksheet_name(),
        info,
    )

def write_movies_to_xls(headers, info):
    headers_lc = [header.lower() for header in headers]
    info_map   = [dict(zip(headers_lc, entry)) for entry in info]

    print(u'Writing movies info.')
    return make_xls(
        'movie_rating',
        get_worksheet_name(),
        headers_lc,
        info_map,
    )

def fetch_movie_ratings(directory, auth_data):
    # Create workers pool.
    workers_count = cpu_count()
    pool          = Pool(workers_count)

    print(u'Reading movies directory.')
    tokens = pool.map(extract_tokens, os.listdir(directory))

    print(u'Fetching %d movies info.' % len(tokens))
    info   = pool.map(extract_info, tokens)
    # End progress print.
    print_progress_end()

    if info:
        # Append headers.
        headers = [
            "Title",
            "Tomato",
            "IMDB",
            "Metacritic",
            "Length",
            "Genre",
            "Description",
        ]

        if auth_data:
            write_movies_to_gdata(auth_data, headers, info)
        else:
            write_movies_to_xls(headers, info)

def main():
    # Cmd options parser
    option_parser = OptionParser()

    option_parser.add_option("-d", "--dir")
    option_parser.add_option("-e", "--extract")
    option_parser.add_option("-a", "--auth-data")

    (options, args) = option_parser.parse_args()

    if not (options.extract or options.dir):
        option_parser.print_help()
    elif options.extract:
        # Get folder names from given location and update contents of Videos dir.
        extract_folders(options.extract)
    elif options.dir:
        fetch_movie_ratings(options.dir, options.auth_data)

if __name__ == "__main__":
    main()
