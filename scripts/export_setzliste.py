"""Exportiert die Setzliste aus einer VMZ-Datei als CSV."""

import argparse
import csv
from pathlib import Path
import sys
import zipfile

PROCESS = Path(__file__).resolve().parent
sys.path.insert(0, str(PROCESS))
from export_vmz import dbf


def export(source, output):
    with zipfile.ZipFile(source) as archive:
        fields, records = dbf(archive.read('Setzlist.dbf'))
    header = [field[0] for field in fields]
    active = [record for record in records if record[1] == '0']
    with output.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(record[2:] for record in active)
    return len(active)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    count = export(args.source, args.output)
    print(f'{args.output}: {count} Datensätze')


if __name__ == '__main__':
    main()
