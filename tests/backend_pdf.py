
from io import StringIO, BytesIO

from pyte.backend.pdf.cos import Document, Boolean, Catalog, String








d = Document()

b = Boolean(True, indirect=True)

d.catalog['Pages'].new_page(100, 150)

#file = BytesIO()
file = open('backend_pdf.pdf', 'wb')
d.write(file)

file.close()

#print(file.getvalue())


