"""Check supplied VMZ, ODS and PDF examples; write analysis reports only.

Run from any directory: py -3 scripts/pruefe_beispiele.py
The PDF text files were extracted once with pypdf; runtime uses only stdlib.
"""
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_vmz import dbf

T = '{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'
O = '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'


def ods(name):
    with zipfile.ZipFile(ROOT / name) as z:
        sheet = next(ET.fromstring(z.read('content.xml')).iter(T + 'table'))
    rows = []
    for row in sheet.iter(T + 'table-row'):
        cells = []
        for cell in row:
            # These checks inspect only the first 160 columns of the examples.
            count = min(int(cell.get(T + 'number-columns-repeated', '1')), 160 - len(cells))
            cells.extend([(''.join(cell.itertext()), cell.get(O + 'value'))] * count)
        if any(text or value is not None for text, value in cells):
            rows.append(cells)
    return rows


def norm(name):
    return re.sub(r'[\s,*-]', '', name.casefold())


def pdf(name):
    records = {}
    for line in (ROOT / 'analyse' / (name + '.txt')).read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'\s*\d+\.\s+(.+?)\s+([\d.,]+)\s+(\d+)\s+(\d+)\s*', line)
        if match:
            person, average, points, series = match.groups()
            assert norm(person) not in records
            records[norm(person)] = (int(series), int(points),
                                    Decimal(average.replace('.', '').replace(',', '.')))
    return records


def table(z, name):
    fields, rows = dbf(z.read(name))
    names = ['_record', '_deleted'] + [f[0] for f in fields]
    return [dict(zip(names, row)) for row in rows if row[1] == '0']


def main():
    with zipfile.ZipFile(ROOT / 'VM-Daten_03092026.VMZ') as z:
        results = table(z, 'VM.dbf')
        players = {r['NR']: r for r in table(z, 'Spieler.dbf')}
    by_name = {norm(r['NAME1']): nr for nr, r in players.items()}
    aggregates = defaultdict(lambda: [0, 0])
    for r in results:
        if r['SPIELTAG'].startswith('2026'):
            aggregates[r['NR']][0] += 1
            aggregates[r['NR']][1] += int(r['WERT'])
    older, newer = pdf('Auswertung_03.09.pdf'), pdf('Auswertung_10.09.26.pdf')
    assert len(older) == 64 and len(newer) == 65
    for name, (series, points, average) in older.items():
        assert aggregates[by_name[name]] == [series, points], name
        assert abs(Decimal(points) / series - average) <= Decimal('.005'), name

    rankings = ['Rangliste.ods', 'Rangliste_10.09.26.ods',
                'Rangliste_10.09.26_nach_Gesamtschnitt_sortiert.ods']
    bonus_count = 0
    for name in rankings:
        for row in ods(name)[1:]:
            series, bonus = (Decimal(row[i][1] or '0') for i in [3, 11])
            assert bonus == (series - 50) / 2, row[2][0]
            bonus_count += 1

    ranking = ods(rankings[1])[1:]
    reordered = {r[2][0]: r for r in ods(rankings[2])[1:]}
    assert all(r[3:13] == reordered[r[2][0]][3:13] for r in ranking)
    statuses = Counter()
    evidence = []
    for row in ranking:
        name = row[2][0]
        key = norm(name)
        if key == norm('Hemmer, Fritz'):
            key = norm('Hemmer, Ringo')  # Candidate alias, not an automatic rename.
        actual = tuple(int(row[i][1] or '0') for i in [3, 4])
        expected = newer.get(key)
        status = ('nicht in PDF' if expected is None else
                  'Stand 10.09.' if actual == expected[:2] else
                  'Stand 03.09.' if actual == older.get(key, ())[:2] else 'abweichend')
        statuses[status] += 1
        evidence.append([name, status, *actual, *(expected[:2] if expected else ('', ''))])
    with (ROOT / 'analyse/rangliste_abgleich.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Name', 'Status', 'ODS_Serien', 'ODS_Punkte', 'PDF_Serien', 'PDF_Punkte'])
        writer.writerows(evidence)
    assert statuses == {'Stand 10.09.': 28, 'Stand 03.09.': 24, 'abweichend': 1, 'nicht in PDF': 5}

    seats = {r[1][0]: r for r in ods('Setzliste_17.09.26.ods')[1:] if r[1][0].isdigit()}
    day = [r for r in results if r['SPIELTAG'] == '20260903']
    table_sizes = Counter((r['SERIE'], r['TISCH']) for r in day)
    for r in day:
        size = table_sizes[r['SERIE'], r['TISCH']]
        assert size in (3, 4)
        payment = {'3': '2', '2': '1.2', '1': '1' if size == 3 else '.8', '0': '0'}[r['TP']]
        actual = seats[r['NR']][86 + int(r['SERIE'])][1]
        assert Decimal(actual) == Decimal(payment), (r['NR'], r['SERIE'])
    assert len(day) == 55
    assert not ods('Setzliste_17.09.26.ods')[0][89][0]
    assert seats['31'][89][1] is not None  # Populated column without date heading.

    updated = ods('Setzliste_17.09.26_aktualisiert.ods')[1:]
    raw_matches, no_results, deviations = 0, 0, []
    for row in updated:
        nr = row[1][0]
        if not nr.isdigit():
            continue
        expected = newer.get(norm(players[nr]['NAME1']))
        if expected is None:
            no_results += 1
        elif Decimal(row[3][1]) == expected[2]:
            raw_matches += 1
        else:
            deviations.append(nr)
    assert (raw_matches, no_results, deviations) == (52, 5, ['60'])
    summary = {'PDF_03_09_exact_matches': 64, 'bonus_checks': bonus_count,
               'table_payment_matches_03_09': 55, 'ranking_10_09': dict(statuses),
               'updated_seating_raw_average_matches': raw_matches,
               'updated_seating_deviating_player_ids': deviations}
    # Additional examples supplied during the analysis close the 10 September gap.
    with zipfile.ZipFile(ROOT / '2.Runde/VM-Daten_10092026.VMZ') as z:
        results10 = table(z, 'VM.dbf')
        players10 = {r['NR']: r for r in table(z, 'Spieler.dbf')}
        original_vm = z.read('VM.dbf')
    totals10 = defaultdict(lambda: [0, 0])
    latest = {}
    for r in results10:
        if r['SPIELTAG'].startswith('2026'):
            totals10[r['NR']][0] += 1
            totals10[r['NR']][1] += int(r['WERT'])
        previous = latest.get(r['NR'])
        if previous is None or (r['SPIELTAG'], int(r['SERIE'])) > (previous['SPIELTAG'], int(previous['SERIE'])):
            latest[r['NR']] = r
    names10 = {norm(r['NAME1']): nr for nr, r in players10.items()}
    for name, (series, points, average) in newer.items():
        assert totals10[names10[name]] == [series, points], name
        assert abs(Decimal(points) / series - average) <= Decimal('.005'), name
    sheet10 = ods('2.Runde/Vorwoche/Setzliste.ods')
    columns = {c[0]: i for i, c in enumerate(sheet10[0]) if c[0]}
    roster10 = {r[1][0]: r for r in sheet10[1:] if r[1][0].isdigit()}
    for r in sheet10[1:]:
        if r[1][0] == 'G':
            matches = [nr for nr, p in players10.items()
                       if norm(''.join(reversed(p['NAME1'].split(',', 1)))) == norm(r[2][0])]
            assert len(matches) == 1, r[2][0]
            roster10[matches[0]] = r
    day10 = [r for r in results10 if r['SPIELTAG'] == '20260910']
    sizes10 = Counter((r['SERIE'], r['TISCH']) for r in day10)
    for r in day10:
        size = sizes10[r['SERIE'], r['TISCH']]
        assert size in (3, 4)
        amount = {'3': '2', '2': '1.2', '1': '1' if size == 3 else '.8', '0': '0'}[r['TP']]
        assert Decimal(roster10[r['NR']][columns['10.9.-' + r['SERIE']]][1]) == Decimal(amount)
    last_count = 0
    for nr, r in roster10.items():
        if r[4][0]:
            assert r[4][0] == latest[nr]['WERT'], nr
            last_count += 1
    complete_rank = {norm(r[2][0]): r for r in ods('2.Runde/Vorwoche/Rangliste.ods')[1:]}
    total_count = 0
    for nr, r in roster10.items():
        if not r[1][0].isdigit():
            continue
        name = norm('Hemmer, Fritz') if nr == '60' else norm(players10[nr]['NAME1'])
        assert abs(Decimal(r[3][1]) - Decimal(complete_rank[name][12][1])) < Decimal('.011')
        total_count += 1
    with zipfile.ZipFile(ROOT / '2.Runde/VM-Daten_17092026.VMZ') as z:
        assert table(z, 'VM.dbf') == results10
        updated_vm = z.read('VM.dbf')
    assert len(original_vm) == len(updated_vm)
    assert [i for i, (a, b) in enumerate(zip(original_vm, updated_vm)) if a != b] == [3]
    assert len(day10) == 50 and total_count == 59
    summary.update(PDF_10_09_exact_matches=65, table_payment_matches_10_09=50,
                   last_series_matches=last_count, complete_roster_bonus_average_matches=59,
                   VM_10_to_17_result_rows_unchanged=True)
    (ROOT / 'analyse/pruefergebnisse.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
