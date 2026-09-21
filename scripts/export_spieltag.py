"""Exportiert einen Spieltag aus einer VMZ-Datei als CSV.

Beispiele:
    py -3 export_spieltag.py VM-Daten_03092026.VMZ
    py -3 export_spieltag.py VM-Daten_03092026.VMZ --datum 20260903
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from export_vmz import dbf


HEADER = [
    'Nummer', 'Name', 'Wertung', 'Spielerpunkte', 'Spiele gewonnen', 'Spiele verloren',
    'Datum', 'Uhrzeit', 'Serie', 'Tisch', 'Tischgröße', 'Abreizgeld',
    'Startgeld', 'Tischgeld',
]


def vm_rows(source):
    with zipfile.ZipFile(source) as archive:
        fields, records = dbf(archive.read('VM.dbf'))
    names = ['_record', '_deleted'] + [field[0] for field in fields]
    return [dict(zip(names, record)) for record in records if record[1] == '0']


def export(source, output=None, date=None):
    results = vm_rows(source)
    available = {row['SPIELTAG'] for row in results if row['SPIELTAG']}
    date = date or max(available)
    if date not in available:
        raise ValueError(f'Kein Spieltag {date} in {source}')

    selected = [row for row in results if row['SPIELTAG'] == date]
    table_sizes = {}
    for row in selected:
        key = (row['SPIELTAG'], row['SERIE'], row['TISCH'])
        table_sizes[key] = table_sizes.get(key, 0) + 1
    invalid = {key: size for key, size in table_sizes.items() if size not in (3, 4)}
    if invalid:
        raise ValueError(f'Unerwartete Tischgröße: {invalid}')

    target = output or source.with_name(f'Spieltag_{date}.csv')
    with target.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER)
        writer.writeheader()
        for row in selected:
            writer.writerow({
                'Nummer': row['NR'],
                'Name': row['NAME1'],
                'Wertung': row['WERT'],
                'Spielerpunkte': row['PUNKTE'],
                'Spiele gewonnen': row['GSP'],
                'Spiele verloren': row['VSP'],
                'Datum': datetime.strptime(date, '%Y%m%d').strftime('%d.%m.%Y'),
                'Uhrzeit': row['ZEIT'],
                'Serie': row['SERIE'],
                'Tisch': row['TISCH'],
                'Tischgröße': table_sizes[(date, row['SERIE'], row['TISCH'])],
                'Abreizgeld': row['REIZGELD'],
                'Startgeld': row['STARTGELD'],
                'Tischgeld': row['TP'],
            })
    return target, len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--datum', help='Spieltag als YYYYMMDD; Standard: letzter Spieltag')
    parser.add_argument('-o', '--output', type=Path)
    args = parser.parse_args()
    if args.datum and (len(args.datum) != 8 or not args.datum.isdigit()):
        parser.error('--datum muss YYYYMMDD sein')
    output, count = export(args.source, args.output, args.datum)
    print(f'{output}: {count} Datensätze')


if __name__ == '__main__':
    main()
