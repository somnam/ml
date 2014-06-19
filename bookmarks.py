#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import sys
import codecs
import gdata.spreadsheet.service
from optparse import OptionParser
from BeautifulSoup import BeautifulSoup
from imogeen import get_file_path
from nomnom_filter import (
    get_auth_data,
    connect_to_service,
    get_writable_worksheet,
    get_writable_cells
)
# }}}

def get_bookmarks_parser(file_name):

    file_path = get_file_path(file_name)

    parser = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        parser = BeautifulSoup(
            file_handle,
            convertEntities=BeautifulSoup.HTML_ENTITIES
        )

    return parser

def get_recipes(parser):

    tags    = parser.find(text = 'Przepisy').parent.parent.findAll('dt');
    recipes = []
    for tag in tags:
        a = tag.find('a')
        recipes.append([a.text, a['href']])

    return recipes

def write_recipes(client, dst_cells, recipes):

    # Prepare request that will be used to update worksheet cells.
    batch_request = gdata.spreadsheet.SpreadsheetsCellsFeed()

    cell_index = 0
    for recipe in recipes:
        recipe_text, recipe_url = recipe

        text_cell                 = dst_cells.entry[cell_index]
        text_cell.cell.inputValue = recipe_text
        batch_request.AddUpdate(text_cell)

        cell_index += 1

        url_cell                 = dst_cells.entry[cell_index]
        url_cell.cell.inputValue = recipe_url
        batch_request.AddUpdate(url_cell)

        cell_index += 1

    # Execute batch update of destination cells.
    return client.ExecuteBatch(batch_request, dst_cells.GetBatchLink().href)

def main(file_name):
    # Cmd options parser
    option_parser = OptionParser()
    option_parser.add_option("-a", "--auth-data")

    (options, args) = option_parser.parse_args()

    if not options.auth_data:
        option_parser.print_help()
    else:
        print("Fetching bookmarks.")
        parser  = get_bookmarks_parser(file_name)

        print("Fetching recipes from bookmarks.")
        recipes = get_recipes(parser)

        # Read auth data from input file.
        auth_data = get_auth_data(options.auth_data)

        # Connect to spreadsheet service.
        print("Authenticating to Google service.")
        client = connect_to_service(auth_data)

        dst_worksheet_name = u'Zakładki'
        print("Fetching destination worksheet '%s'." % dst_worksheet_name)
        dst_worksheet      = get_writable_worksheet(
            client, dst_worksheet_name, len(recipes)
        )

        print("Fetching destination cells.")
        writable_cells = get_writable_cells(
            client,
            dst_worksheet,
            recipes
        )

        print("Writing recipes.")
        write_recipes(client, writable_cells, recipes)

if __name__ == "__main__":
    main('bookmarks.html');
