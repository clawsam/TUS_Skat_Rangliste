"""Fügt einen einzelnen Gast ad hoc in eine Setzliste ein."""

import argparse
from pathlib import Path
import re
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ergaenze_setzliste import (cells, cell_text, data_rows, remove_repeated_rows,
                                replace_at, tag_end, trim_columns, update_cell)


def blank_row(row):
    matches = list(re.finditer(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', row, re.DOTALL))
    result = []
    for match in matches:
        cell = re.sub(r'\s+table:(?:number-columns-repeated|formula)="[^"]*"', '', match.group(0))
        result.append(update_cell(cell, ''))
    return row[:matches[0].start()] + ''.join(result) + row[matches[-1].end():]


def add(source, output, player_id, name):
    with zipfile.ZipFile(source) as archive:
        content = archive.read('content.xml').decode()
        match = re.search(r'(<table:table\b[^>]*table:name="Tabelle1"[^>]*>)(.*?)(</table:table>)', content, re.DOTALL)
        if not match:
            raise ValueError('Tabelle1 fehlt in der Setzliste')
        body = match.group(2)
        rows = data_rows(re.findall(r'<table:table-row\b.*?</table:table-row>', body, re.DOTALL))
        header = [cell_text(cell) for cell in cells(rows[0])]
        name_index, id_index = header.index('Name'), header.index('ID')
        if any(cell_text(cells(row)[name_index]).strip().casefold() == name.casefold()
               for row in rows[1:]):
            raise ValueError(f'Gast bereits vorhanden: {name}')
        row = blank_row(rows[-1])
        missing = 135 - len(cells(row))
        if missing > 0:
            row = row.replace('</table:table-row>',
                              '<table:table-cell/>' * missing + '</table:table-row>')
        logical = cells(row)
        for index, value, numeric in (
                (0, '70', True), (id_index, str(player_id), False),
                (header.index('Gruppe'), 'Blau', False), (name_index, name, False),
                (header.index('Abwesenheiten'), '0', True),
                (header.index('Schnitt'), '0', True),
                (header.index('letzte Serie'), '0', True),
                (header.index('Tischpunkte'), '0', True)):
            suffix = ' €' if index in (header.index('Schnitt'), header.index('Tischpunkte')) else ''
            row = replace_at(row, index, update_cell(logical[index], value,
                                                     numeric=numeric, suffix=suffix))
            logical = cells(row)
        row_start = body.find('<table:table-row')
        new_body = body[:row_start] + ''.join(rows + [row])
        new_body = trim_columns(new_body)
        new_body = remove_repeated_rows(new_body)
        content = content[:match.start(2)] + new_body + content[match.end(2):]
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as result:
            for entry in archive.infolist():
                result.writestr(entry, content.encode() if entry.filename == 'content.xml' else archive.read(entry))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--id', type=int, required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    add(args.source, args.output, args.id, args.name)
    print(f'{args.name} (ID {args.id}) als Gast ergänzt: {args.output}')


if __name__ == '__main__':
    main()
