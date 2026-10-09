"""Exportiert die Ausschnitte der fertigen ODS-Listen über Chrome/Edge als PDF."""

import argparse
from html import escape
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from xml.etree import ElementTree as ET
import zipfile

N = {prefix: f'urn:oasis:names:tc:opendocument:xmlns:{name}:1.0'
     for prefix, name in [('office', 'office'), ('table', 'table'), ('text', 'text'),
                          ('style', 'style'), ('fo', 'xsl-fo-compatible')]}


def browser_path():
    candidates = [shutil.which(name) for name in ('chrome', 'msedge', 'chromium')]
    for root in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        for suffix in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
            candidates.append(str(Path(os.environ.get(root, '')) / suffix))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError('Für den PDF-Export wird Google Chrome oder Microsoft Edge benötigt.')


def html_document(source, ranking):
    with zipfile.ZipFile(source) as archive:
        content = ET.fromstring(archive.read('content.xml'))
        common = ET.fromstring(archive.read('styles.xml'))
    styles = {node.get(f'{{{N["style"]}}}name'): node
              for root in (common, content) for node in root.findall('.//style:style', N)}

    def properties(name):
        node = styles.get(name)
        if node is None:
            return {}
        parent = node.get(f'{{{N["style"]}}}parent-style-name')
        result = properties(parent) if parent and parent != name else {}
        for child in node:
            result.update(child.attrib)
        return result

    def label(cell):
        return ''.join(cell.itertext()).strip()

    table = content.find('.//table:table', N)
    rows = []
    for row in table.findall('table:table-row', N):
        expanded = []
        for cell in row.findall('table:table-cell', N):
            count = int(cell.get(f'{{{N["table"]}}}number-columns-repeated', '1'))
            expanded.extend([cell] * min(count, 14 - len(expanded)))
        rows.append(expanded)
    header_index = next(i for i, row in enumerate(rows) if 'Name' in [label(c) for c in row])
    header = [label(cell) for cell in rows[header_index]]
    # ponytail: nur die beiden Vereinslisten; weitere Tabellen brauchen eigene Spaltenauswahl.
    if ranking:
        columns = [1] + [header.index(name) for name in ('Name', 'Serien', 'Punkte', 'Schnitt', 'Bonus', 'Gesamt')]
        widths = [9, 45, 15, 19, 20, 16, 23]
    else:
        absence = next(name for name in ('Abwesenheit', 'Abwesenheiten') if name in header)
        columns = [header.index(name) for name in ('Platz', 'ID', 'Name', absence, 'Schnitt', 'letzte Serie', 'Tischpunkte')]
        widths = [9, 8, 51, 6, 22, 23, 25]
    rendered = []
    for i, row in enumerate(rows[header_index:], header_index):
        labels = [label(cell) for cell in row]
        if i != header_index and not labels[columns[0]].isdigit() and 'Summe' not in labels:
            continue
        cells = []
        for column in columns:
            cell = row[column]
            props = properties(cell.get(f'{{{N["table"]}}}style-name'))
            css = []
            for key in ('background-color', 'color', 'font-weight', 'border',
                        'border-left', 'border-right', 'border-top', 'border-bottom'):
                value = props.get(f'{{{N["fo"]}}}{key}')
                if value:
                    css.append(f'{key}:{value}')
            value = labels[column].replace(' €', '')
            if i == header_index and not ranking and column == columns[3]:
                value = 'F'
            if value.startswith('-'):
                css.append('color:#ff0000')
            alignment = 'center' if i == header_index or not ranking else ('left' if column == columns[1] else 'right')
            css.append(f'text-align:{alignment}')
            cells.append(f'<td style="{escape(";".join(css), quote=True)}">{escape(value)}</td>')
        rendered.append('<tr>' + ''.join(cells) + '</tr>')
    if len(rendered) < 2:
        raise ValueError(f'Keine Spielerzeilen für den PDF-Export: {source}')
    return '''<!doctype html><html lang="de"><meta charset="utf-8">
<style>
@page { size: A4 portrait; margin: 10mm; }
* { box-sizing: border-box; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
body { margin: 0; font: 10pt Arial, sans-serif; }
table { border-collapse: collapse; table-layout: fixed; }
td { padding: 0.25mm 0.3mm; line-height: 1.15; white-space: nowrap; }
tr { break-inside: avoid; }
</style><body><table><colgroup>''' + ''.join(
        f'<col style="width:{width}mm">' for width in widths) + '</colgroup>' + ''.join(rendered) + '''</table>
<script>
const table = document.querySelector('table');
// Inklusive aller Spieler und der Summenzeile auf eine A4-Seite verkleinern.
table.style.zoom = Math.min(1, 188 * 96 / 25.4 / table.offsetWidth,
                              275 * 96 / 25.4 / table.offsetHeight);
</script></body></html>'''


def export_pdfs(ranking, seating):
    browser = browser_path()
    for source, is_ranking in ((ranking, True), (seating, False)):
        source = source.resolve()
        with tempfile.TemporaryDirectory(prefix='skat_pdf_') as directory:
            temp = Path(directory)
            html = temp / 'liste.html'
            pdf = temp / 'liste.pdf'
            html.write_text(html_document(source, is_ranking), encoding='utf-8')
            subprocess.run([browser, '--headless', '--disable-gpu', '--no-pdf-header-footer',
                            '--no-first-run', '--no-default-browser-check',
                            f'--user-data-dir={temp / "profile"}', f'--print-to-pdf={pdf}', html.as_uri()],
                           check=True, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
                raise RuntimeError(f'PDF-Export fehlgeschlagen: {source}')
            output = source.with_suffix('.pdf')
            shutil.copyfile(pdf, output)
            print(f'PDF erstellt: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rangliste', type=Path)
    parser.add_argument('setzliste', type=Path)
    args = parser.parse_args()
    export_pdfs(args.rangliste, args.setzliste)
