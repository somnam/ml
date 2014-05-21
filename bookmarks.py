#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import codecs
from BeautifulSoup import BeautifulSoup
from imogeen import get_file_path
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

def main(file_name):
    parser = get_bookmarks_parser(file_name)

    recipes = get_recipes(parser)
    import pprint; pprint.pprint(recipes)

if __name__ == "__main__":
    main('bookmarks.html');
