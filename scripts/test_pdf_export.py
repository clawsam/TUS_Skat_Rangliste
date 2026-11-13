"""Prüft den einseitigen PDF-Export mit Chrome/Edge: python/python.exe scripts/test_pdf_export.py"""

from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ergaenze_setzliste import cells, formula_cell, replace_at, update_cell
from export_listen_pdf import export_pdfs
from formatiere_listen import ROW, format_layout

ROOT = Path(__file__).resolve().parent.parent


def check():
    with TemporaryDirectory(prefix='skat_pdf_test_') as directory:
        sources = []
        for ranking in (True, False):
            name = 'Rangliste.ods' if ranking else 'Setzliste.ods'
            output = Path(directory) / name
            with zipfile.ZipFile(ROOT / name) as archive:
                content = archive.read('content.xml').decode()
                matches = list(ROW.finditer(content))
                rows = [matches[0].group()]
                for place in range(1, 81):
                    row = matches[1].group()
                    column = 1 if ranking else 0
                    row = replace_at(row, column, update_cell(cells(row)[column], str(place)))
                    rows.append(row)
                if not ranking:
                    total = rows[0]
                    for column in range(8):
                        total = replace_at(total, column, update_cell(cells(total)[column], ''))
                    total = replace_at(total, 6, update_cell(cells(total)[6], 'Summe'))
                    total = replace_at(total, 7, formula_cell(cells(total)[7], 'of:=SUM([.H2:.H81])', '160,00', suffix=' €'))
                    rows.append(total)
                content = content[:matches[0].start()] + ''.join(rows) + content[matches[-1].end():]
                content = format_layout(content, ranking=ranking)
                with zipfile.ZipFile(output, 'w') as result:
                    for entry in archive.infolist():
                        result.writestr(entry, content.encode() if entry.filename == 'content.xml' else archive.read(entry))
            sources.append(output)
        export_pdfs(*sources)
        for source in sources:
            pages = re.findall(rb'/Type\s*/Page\b', source.with_suffix('.pdf').read_bytes())
            assert len(pages) == 1, f'{source.name}: {len(pages)} Seiten statt einer'
    print('PDF geprüft: beide Listen mit 80 Spielern, einschließlich Summenzeile, auf je einer Seite.')


if __name__ == '__main__':
    check()
