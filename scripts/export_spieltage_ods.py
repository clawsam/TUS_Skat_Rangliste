"""Exportiert alle Spieltage einer VMZ in eine ODS-Datei."""

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

PROCESS = Path(__file__).resolve().parent
sys.path.insert(0, str(PROCESS))
from export_vmz import dbf

NS = {
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

HEADER = [
    'Nummer', 'Name', 'Wertung', 'Spielerpunkte', 'Spiele gewonnen', 'Spiele verloren',
    'Datum', 'Uhrzeit', 'Serie', 'Tisch', 'Tischgröße', 'Abreizgeld',
    'Startgeld', 'Tischgeld',
]
NUMERIC = {0, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13}


def rows(source):
    with zipfile.ZipFile(source) as archive:
        fields, records = dbf(archive.read('VM.dbf'))
    names = ['_record', '_deleted'] + [field[0] for field in fields]
    return [dict(zip(names, record)) for record in records if record[1] == '0']


def cell(row, value, numeric=False):
    attributes = {'office:value-type': 'float'} if numeric and value != '' else {
        'office:value-type': 'string'}
    if numeric and value != '':
        attributes['office:value'] = str(value)
    item = ET.SubElement(row, f'{{{NS["table"]}}}table-cell', attributes)
    text = ET.SubElement(item, f'{{{NS["text"]}}}p')
    text.text = str(value)


def create_content(data):
    root = ET.Element(f'{{{NS["office"]}}}document-content', {
        f'{{{NS["office"]}}}version': '1.2'})
    body = ET.SubElement(root, f'{{{NS["office"]}}}body')
    spreadsheet = ET.SubElement(body, f'{{{NS["office"]}}}spreadsheet')
    for date in sorted(data, reverse=True):
        title = datetime.strptime(date, '%Y%m%d').strftime('%d.%m.%Y')
        table = ET.SubElement(spreadsheet, f'{{{NS["table"]}}}table',
                              {f'{{{NS["table"]}}}name': title})
        header = ET.SubElement(table, f'{{{NS["table"]}}}table-row')
        for value in HEADER:
            cell(header, value)
        for values in data[date]:
            output = ET.SubElement(table, f'{{{NS["table"]}}}table-row')
            for index, value in enumerate(values):
                cell(output, value, index in NUMERIC)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def write_ods(source, output, year):
    results = [row for row in rows(source) if row['SPIELTAG'].startswith(year)]
    if not results:
        raise ValueError(f'Keine Ergebnisse für das Spieljahr {year}')
    sizes = Counter((r['SPIELTAG'], r['SERIE'], r['TISCH']) for r in results)
    data = {}
    for r in results:
        key = (r['SPIELTAG'], r['SERIE'], r['TISCH'])
        data.setdefault(r['SPIELTAG'], []).append([
            r['NR'], r['NAME1'], r['WERT'], r['PUNKTE'], r['GSP'], r['VSP'],
            datetime.strptime(r['SPIELTAG'], '%Y%m%d').strftime('%d.%m.%Y'),
            r['ZEIT'], r['SERIE'], r['TISCH'], sizes[key], r['REIZGELD'],
            r['STARTGELD'], r['TP'],
        ])
    for values in data.values():
        values.sort(key=lambda row: (row[7], row[8], row[0]))

    content = create_content(data)
    manifest = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>'''.encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.spreadsheet',
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr('content.xml', content)
        archive.writestr('META-INF/manifest.xml', manifest)
    return len(data), len(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--jahr', default=str(datetime.now().year),
                        help='Spieljahr als YYYY; Standard: aktuelles Jahr')
    parser.add_argument('-o', '--output', type=Path)
    args = parser.parse_args()
    if len(args.jahr) != 4 or not args.jahr.isdigit():
        parser.error('--jahr muss YYYY sein')
    output = args.output or PROCESS / 'output' / f'Spieltage_{args.jahr}.ods'
    days, records = write_ods(args.source, output, args.jahr)
    print(f'{output}: {days} Spieltage, {records} Datensätze')


if __name__ == '__main__':
    main()
