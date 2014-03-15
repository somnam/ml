import xlrd

# Get xls sheet
workbook = xlrd.open_workbook('/home/tomek/Documents/Madzialena/2013-02-29 mg ca.xls')

# Get fist sheet from workbook
worksheet = workbook.sheet_by_name('Sheet1')

# Grab contents of column C (2)
columnC = filter(
    # Filter out empty items
    lambda(x): len(x),
    worksheet.col_values(2)
)

# Grab contents of column Y (25)
columnY = filter(
    lambda(x): len(x),
    worksheet.col_values(24)
)
# Divide contents of column to mg and ca
mg, ca = [], []
for index in range(len(columnY)):
    # Odd value - ca
    if index % 2:
        ca.append(columnY[index])
    # Even value - mg
    else:
        mg.append(columnY[index])

# Print data in 3 columns:
# Id - contains each entry from columnC list
# Mg - contains each entry from mg list
# Ca - contains each entry from ca list
for index in range(len(columnC)):
    print "%-10s , %-10s , %-10s" % (columnC[index], mg[index], ca[index])

