import re
import os
from lib.common import (
    prepare_opener,
    open_url,
    get_parsed_url_response,
    print_progress,
    print_progress_end,
)
from lib.xls import open_workbook, save_workbook
from lib.diskcache import diskcache, YEAR
from optparse import OptionParser
from multiprocessing.dummy import Pool, cpu_count

# Site url.
NCBI_URL = 'https://www.ncbi.nlm.nih.gov/'

def prepare_ncbi_opener():
    opener = prepare_opener(NCBI_URL)
    # Request used to initialize cookie.
    open_url(NCBI_URL, opener)
    return opener

# 'opener' will be created only once.
def get_parsed_ncbi_url_response(url, opener = prepare_ncbi_opener()):
    return get_parsed_url_response(url, opener = opener)

# Invalidate values after 1 year.
@diskcache(YEAR)
def fetch_proteins(accession):
    if accession is None: return

    protein_url  = u'{0}protein/{1}'.format(NCBI_URL, accession)
    protein_page = get_parsed_ncbi_url_response(protein_url)

    protein = None
    if protein_page:
        header  = protein_page.find('div', {'class': 'rprtheader'})
        protein = header.h1.text if (header and header.h1) else ''
        protein_page.decompose()

    return protein

def append_protein_names_to_workbook(workbook):
    # Workers pool.
    pool = Pool(cpu_count() * 2)

    # Process each worksheet.
    sheet_names = workbook.get_sheet_names()
    # Used to search for accession column.
    accession_re = re.compile(r'.*accession$')
    print(u'Processing {0} sheets'.format(len(sheet_names)))
    for name in sheet_names:
        sheet = workbook.get_sheet_by_name(name)
        # Get column with accessions.
        accession_col = 2
        for col_i in range(2, sheet.max_column+1):
            cell = sheet.cell(row=2, column=col_i)
            if cell and cell.value and accession_re.match(cell.value):
                accession_col = col_i
                break
        # Get protein data.
        accessions = []
        for row_i in range(2, sheet.max_row+1):
            cell = sheet.cell(row=row_i, column=accession_col)
            # Skip empty rows.
            if not(cell and cell.value): continue
            accessions.append(cell.value)

        # Fetch proteins.
        proteins = pool.map(fetch_proteins, accessions)

        # Write protein data.
        for row_i, protein in enumerate(proteins, 2):
            cell = sheet.cell(row=row_i, column=1)
            if not cell.value or (protein and cell.value != protein):
                cell.value = protein

        print_progress()

    # Wait for pool threads to finish.
    pool.close()
    pool.join()

    print_progress_end()

    return

def get_excel_file_names(args):
    file_names = args
    # If file names aren't given in path, look for them inside current dir.
    if not args:
        file_names = filter(
            lambda fn: fn.endswith(('.xlsx', '.xls')),
            os.listdir(os.getcwd())
        )
    return file_names

def process_workbooks(file_names):
    for idx, file_name in enumerate(file_names, 1):
        workbook, error = open_workbook(file_name)

        if error:
            print(error)
            continue

        append_protein_names_to_workbook(workbook)

        print(u"Saving workbook {0} of {1}.".format(idx, len(file_names)))
        save_workbook(workbook, file_name)

def main():
    # cmd options parser
    option_parser = OptionParser()

    (options, args) = option_parser.parse_args()

    file_names = get_excel_file_names(args)

    process_workbooks(file_names)

    raw_input(u"Done, please press [Enter]")

if __name__ == "__main__":
    main()
