# -*- coding: utf-8 -*-

import xlwt
import codecs
import json
import os
import re

# Get file path
file_name   = 'imogeen_posiadam.json'
file_path   = os.path.join(
    os.path.dirname(__file__),
    file_name
)

# Read data.
file_data = None
with codecs.open(file_path, 'r', 'utf-8') as file_handle:
    file_data = json.load(file_handle)

# Create a new workbook.
workbook = xlwt.Workbook()

# Add a new sheet.
sheet = workbook.add_sheet('Posiadam')

# Add headers
headers = (u'Nazwisko', u'Imię', u"Tytuł", u'Gatunek')
for col in range(len(headers)):
    sheet.write(0, col, headers[col].capitalize())

books = []
author_re = re.compile('^\(')
for book in file_data:
    # Get author name and surname.
    author          = book['author'].split()
    author_surname  = author.pop()
    if author_re.match(author_surname):
        author_surname = author.pop()
    author_name     = ' '.join(author)

    row = (author_surname, author_name, book['title'], book['category'])
    books.append(row)

books.sort(key=lambda x: x[0])

row_i = 1
for book in books:
    for col_i in range(len(book)):
        sheet.write(row_i, col_i, book[col_i])
    row_i += 1

workbook_path = os.path.join(
    os.path.dirname(__file__),
    'imogeen_posiadam.xls'
)
workbook.save(workbook_path)
