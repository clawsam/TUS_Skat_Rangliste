"""Überträgt die Gruppen aus einer Setzliste in Spieler.dbf einer VMZ."""

import argparse
import re
import struct
import zipfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ergaenze_setzliste import ods_rows
from export_vmz import dbf

TARGETS = {'Grün': 0, 'Gelb': 1, 'Rot': 2}


def group_ids(setzliste):
    rows = ods_rows(setzliste)['Tabelle1']
    header = next(row for row in rows if 'ID' in row and 'Gruppe' in row)
    id_index, group_index = header.index('ID'), header.index('Gruppe')
    result = {}
    for row in rows[rows.index(header) + 1:]:
        raw_group = row[group_index].strip() if len(row) > group_index else ''
        match = re.match(r'(Grün|Gelb|Rot|Grau|Blau)\b', raw_group)
        group = match.group(1) if match else ''
        if group not in TARGETS:
            continue  # Blau und Grau bleiben unangetastet.
        player_id = row[id_index].strip() if len(row) > id_index else ''
        if not player_id:
            raise ValueError(f'Gruppe {group} ohne Spieler-ID')
        if player_id in result:
            raise ValueError(f'Spieler-ID doppelt in Setzliste: {player_id}')
        result[player_id] = (TARGETS[group], group)
    return result


def patch_players(data, wanted):
    fields, rows = dbf(data)
    names = [field[0] for field in fields]
    required = ['NR', 'M1', 'M2', 'M3']
    if any(name not in names for name in required):
        raise ValueError('Spieler.dbf enthält nicht die Felder NR/M1/M2/M3')
    index = {name: 2 + names.index(name) for name in required}
    live = {row[index['NR']]: row for row in rows if row[1] == '0'}
    missing = sorted(set(wanted) - set(live))
    if missing:
        raise ValueError(f'Spieler-IDs nicht in Spieler.dbf: {", ".join(missing)}')

    header, width = struct.unpack_from('<HH', data, 8)
    field_offsets = {}
    offset = 1
    for name, _, size, _ in fields:
        field_offsets[name] = offset
        offset += size
    if any(next(field[2] for field in fields if field[0] == name) != 1
           for name in ('M1', 'M2', 'M3')):
        raise ValueError('Spieler.dbf-Gruppenfelder sind nicht ein Byte breit')

    result = bytearray(data)
    changes = []
    for player_id, (group, label) in wanted.items():
        row = live[player_id]
        record = int(row[0]) - 1
        start = header + record * width
        values = [b'F', b'F', b'F']
        values[group] = b'T'
        old = tuple(result[start + field_offsets[name]:start + field_offsets[name] + 1]
                    for name in ('M1', 'M2', 'M3'))
        new = tuple(values)
        if old != new:
            for name, value in zip(('M1', 'M2', 'M3'), new):
                result[start + field_offsets[name]] = value[0]
            changes.append((player_id, label, old, new))
    return bytes(result), changes


def update(source, setzliste, output):
    wanted = group_ids(setzliste)
    with zipfile.ZipFile(source) as archive:
        entries = {entry.filename: archive.read(entry) for entry in archive.infolist()}
        if 'Spieler.dbf' not in entries:
            raise ValueError('Spieler.dbf fehlt in der VMZ')
        entries['Spieler.dbf'], changes = patch_players(entries['Spieler.dbf'], wanted)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as result:
            for entry in archive.infolist():
                result.writestr(entry, entries[entry.filename])
    return changes


def self_test():
    assert TARGETS == {'Grün': 0, 'Gelb': 1, 'Rot': 2}
    assert 'Blau' not in TARGETS and 'Grau' not in TARGETS
    print('Self-test passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmz', type=Path, nargs='?')
    parser.add_argument('setzliste', type=Path, nargs='?')
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.vmz or not args.setzliste or not args.output:
        parser.error('VMZ, Setzliste und -o/--output sind erforderlich')
    if args.vmz.resolve() == args.output.resolve():
        parser.error('Ausgabe darf nicht die Eingabe überschreiben')
    changes = update(args.vmz, args.setzliste, args.output)
    print(f'VMZ vorbereitet: {args.output} ({len(changes)} Gruppenänderungen)')


if __name__ == '__main__':
    main()
