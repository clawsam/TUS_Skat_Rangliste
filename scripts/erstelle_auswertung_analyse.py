"""Erzeuge eine lesbare Jahresauswertung direkt aus einer VMZ-Datei.

Beispiel:
    py -3 scripts/erstelle_auswertung_analyse.py old/2026_09_10-16/VM-Daten_10092026.VMZ
"""

import argparse
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_vmz import dbf


def rows(archive, name):
    fields, records = dbf(archive.read(name))
    names = ['_record', '_deleted'] + [field[0] for field in fields]
    return [dict(zip(names, record)) for record in records if record[1] == '0']


def german_number(value, decimals=2):
    value = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    text = f'{value:,.{decimals}f}'
    return text.replace(',', 'X').replace('.', ',').replace('X', '.')


def create_report(source, output, year):
    with zipfile.ZipFile(source) as archive:
        results = rows(archive, 'VM.dbf')
        players = {player['NR']: player for player in rows(archive, 'Spieler.dbf')}

    selected = [result for result in results if result['SPIELTAG'].startswith(year)]
    if not selected:
        raise ValueError(f'Keine Ergebnisse für {year} in {source}')

    totals = defaultdict(lambda: [0, 0])
    for result in selected:
        totals[result['NR']][0] += 1
        totals[result['NR']][1] += int(result['WERT'])

    ranking = sorted(
        ((nr, count, points, Decimal(points) / Decimal(count), players.get(nr, {}).get('NAME1', nr))
         for nr, (count, points) in totals.items()),
        key=lambda item: (-item[3], -item[2], item[4]),
    )
    last_day = max(result['SPIELTAG'] for result in selected)
    date = datetime.strptime(last_day, '%Y%m%d').strftime('%d.%m.%Y')

    lines = [
        f'{year} - alle Serien - Mitglieder',
        f'Quelle: {source.name}',
        f'Stand der Ergebnisse: {date}',
        '',
        f'{"Platz":>5}  {"Name":<30}  {"Serien":>6}  {"Schnitt":>10}  {"Punkte":>8}',
    ]
    for place, (_, count, points, average, name) in enumerate(ranking, 1):
        lines.append(f'{place:>5}.  {name:<30}  {count:>6}  '
                     f'{german_number(average):>10}  {points:>8}')
    lines.extend(['', f'{len(ranking)} Personen, {len(selected)} Ergebnisse'])
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return len(ranking), len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--year', default='2026')
    args = parser.parse_args()
    output = args.output or ROOT / 'analyse' / f'Auswertung_{args.year}.txt'
    people, results = create_report(args.source, output, args.year)
    print(f'{output}: {people} Personen, {results} Ergebnisse')


if __name__ == '__main__':
    main()
