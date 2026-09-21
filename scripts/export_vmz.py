"""Export and compare VMZ backups using only the Python standard library.

Run: py -3 export_vmz.py older.VMZ newer.VMZ [--output exports]
Check: py -3 export_vmz.py --self-test
"""

import argparse
import base64
import csv
import hashlib
import io
import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
import struct
import zipfile


def dbf(data):
    if len(data) < 33 or data[0] != 3:
        raise ValueError('Expected a dBASE III table')
    count, header, width = struct.unpack_from('<IHH', data, 4)
    fields = []
    pos = 32
    while pos < header and data[pos] != 13:
        descriptor = data[pos:pos + 32]
        if len(descriptor) != 32:
            raise ValueError('Truncated field descriptor')
        name = descriptor[:11].split(b'\0')[0].decode('ascii')
        kind, size, decimals = chr(descriptor[11]), descriptor[16], descriptor[17]
        if kind not in 'CNDL' or not name or not size:
            raise ValueError(f'Unsupported DBF field: {name} {kind}')
        fields.append((name, kind, size, decimals))
        pos += 32
    end = header + count * width
    if (pos >= header or data[pos] != 13 or header > len(data)
            or sum(f[2] for f in fields) + 1 != width
            or len({f[0] for f in fields}) != len(fields)
            or len(data) < end or data[end:] not in (b'', b'\x1a')):
        raise ValueError('Invalid DBF layout or record count')
    rows = []
    for record in range(count):
        offset = header + record * width
        marker = data[offset:offset + 1]
        if marker not in (b' ', b'*'):
            raise ValueError(f'Invalid deletion marker in record {record + 1}')
        row = [str(record + 1), '1' if marker == b'*' else '0']
        offset += 1
        for _, kind, size, _ in fields:
            value = data[offset:offset + size].decode('cp850')
            row.append(value.rstrip(' ') if kind == 'C' else value.strip(' '))
            offset += size
        rows.append(row)
    return tuple(fields), rows


def csv_writer(stack, path, header):
    stream = stack.enter_context(path.open('w', encoding='utf-8-sig', newline=''))
    writer = csv.writer(stream)
    writer.writerow(header)
    return writer


def export_archive(path, folder):
    folder.mkdir()
    inventory, core, counts, schemas = {}, {}, Counter(), {}
    with zipfile.ZipFile(path) as archive, ExitStack() as stack:
        manifest = csv_writer(stack, folder / 'manifest.csv',
                              ['source_file', 'bytes', 'sha256', 'csv_file', 'rows'])
        schema_csv = csv_writer(stack, folder / 'schema.csv',
                                ['csv_file', 'position', 'field', 'type', 'width', 'decimals'])
        logs = csv_writer(stack, folder / 'LFL_lines.csv', ['source_file', 'line_number', 'text'])
        binary = csv_writer(stack, folder / 'settings_base64.csv', ['source_file', 'bytes', 'base64'])
        writers = {}
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            name = entry.filename
            if name in inventory:
                raise ValueError(f'Duplicate archive entry: {name}')
            data = archive.read(entry)  # zipfile also verifies each entry's CRC.
            digest = hashlib.sha256(data).hexdigest()
            suffix = Path(name).suffix.lower()
            if suffix == '.dbf':
                fields, rows = dbf(data)
                if name.upper().startswith('VM_'):
                    target = f'games_{len(fields)}_fields.csv'
                else:
                    target = Path(name).stem + '.csv'
                    core[name.lower()] = (fields, rows)
                if target not in writers:
                    schemas[target] = fields
                    writers[target] = csv_writer(stack, folder / target,
                                                 ['source_file', '_record', '_deleted'] + [f[0] for f in fields])
                    schema_csv.writerows((target, i, *field) for i, field in enumerate(fields, 1))
                if schemas[target] != fields:
                    raise ValueError(f'Conflicting schemas for {target}')
                writers[target].writerows([name, *row] for row in rows)
                exported = len(rows)
                counts['dbf_tables'] += 1
                counts['dbf_records'] += exported
            elif suffix == '.lfl':
                target = 'LFL_lines.csv'
                lines = data.decode('utf-8').splitlines(keepends=True)
                logs.writerows((name, i, line) for i, line in enumerate(lines, 1))
                exported = len(lines)
                counts['lfl_files'] += 1
            else:
                target = 'settings_base64.csv'
                binary.writerow([name, len(data), base64.b64encode(data).decode('ascii')])
                exported = 1
                counts['binary_files'] += 1
            inventory[name] = {'sha256': digest, 'bytes': len(data), 'rows': exported}
            manifest.writerow([name, len(data), digest, target, exported])
            counts['uncompressed_bytes'] += len(data)
        counts['files'] = len(inventory)
    # Read back every CSV and verify the number of exported records/lines.
    expected = Counter()
    with (folder / 'manifest.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            expected[row['csv_file']] += int(row['rows'])
    for target, count in expected.items():
        with (folder / target).open(encoding='utf-8-sig', newline='') as stream:
            actual = sum(1 for _ in csv.DictReader(stream))
        if actual != count:
            raise ValueError(f'CSV verification failed: {target}: {actual} != {count}')
    return inventory, core, dict(counts)


def compare(old, new, folder):
    before, after = old[0], new[0]
    totals = Counter()
    changes = {}
    with ExitStack() as stack:
        writer = csv_writer(stack, folder / 'file_comparison.csv',
                            ['source_file', 'status', 'old_bytes', 'new_bytes', 'old_sha256', 'new_sha256'])
        for name in sorted(before.keys() | after.keys()):
            a, b = before.get(name, {}), after.get(name, {})
            status = ('added' if not a else 'removed' if not b else
                      'unchanged' if a['sha256'] == b['sha256'] else 'changed')
            totals[status] += 1
            writer.writerow([name, status, a.get('bytes', ''), b.get('bytes', ''),
                             a.get('sha256', ''), b.get('sha256', '')])
        for name in sorted(old[1].keys() | new[1].keys()):
            fields, _ = new[1].get(name, old[1].get(name))
            a_fields, a_rows = old[1].get(name, (fields, []))
            b_fields, b_rows = new[1].get(name, (fields, []))
            if a_fields != b_fields:
                raise ValueError(f'Core table schema changed: {name}')
            # Ignore physical record positions; preserve deleted flags and duplicates.
            a = Counter(tuple(row[1:]) for row in a_rows)
            b = Counter(tuple(row[1:]) for row in b_rows)
            removed, added = a - b, b - a
            target = folder / (Path(name).stem + '_row_changes.csv')
            writer = csv_writer(stack, target, ['change', 'copies', '_deleted'] + [f[0] for f in fields])
            for label, delta in [('removed', removed), ('added', added)]:
                writer.writerows([label, copies, *row] for row, copies in sorted(delta.items()))
            changes[name] = {'old_records': len(a_rows), 'new_records': len(b_rows),
                             'removed_rows': sum(removed.values()), 'added_rows': sum(added.values())}
    return {'files': dict(totals), 'tables': changes}


def self_test():
    fields = [('NAME', 'C', 8, 0), ('VALUE', 'N', 6, 2), ('DATE', 'D', 8, 0), ('FLAG', 'L', 1, 0)]
    header = 32 + 32 * len(fields) + 1
    width = 1 + sum(f[2] for f in fields)
    data = bytearray(header)
    data[0] = 3
    struct.pack_into('<IHH', data, 4, 2, header, width)
    for i, (name, kind, size, decimals) in enumerate(fields):
        pos = 32 + i * 32
        data[pos:pos + len(name)] = name.encode('ascii')
        data[pos + 10] = 88  # Real archives contain garbage after the NUL terminator.
        data[pos + 11], data[pos + 16], data[pos + 17] = ord(kind), size, decimals
    data[-1] = 13
    record = 'Müller'.ljust(8).encode('cp850') + b' -1.2520260903T'
    data.extend(b' ' + record + b'*' + record + b'\x1a')
    actual_fields, rows = dbf(data)
    assert actual_fields == tuple(fields)
    assert rows == [['1', '0', 'Müller', '-1.25', '20260903', 'T'],
                    ['2', '1', 'Müller', '-1.25', '20260903', 'T']]
    for invalid in (data[:-3], b'bad header'):
        try:
            dbf(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid table accepted')
    stream = io.StringIO(newline='')
    original = ['comma, quote" and\r\nnewline', 'Müller']
    csv.writer(stream).writerow(original)
    stream.seek(0)
    assert next(csv.reader(stream)) == original
    print('Self-test passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='*', type=Path)
    parser.add_argument('--output', type=Path, default=Path('exports'))
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if len(args.archives) != 2:
        parser.error('Supply two archives, older first')
    if args.archives[0].stem == args.archives[1].stem:
        parser.error('Archive names must differ')
    args.output.mkdir(exist_ok=False)
    exported = []
    for path in args.archives:
        result = export_archive(path, args.output / path.stem)
        exported.append(result)
        print(f'Exported {path.name}: {result[2]}', flush=True)
    report = {'archives': {p.name: r[2] for p, r in zip(args.archives, exported)},
              'comparison': compare(*exported, args.output)}
    (args.output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['comparison'], indent=2))


if __name__ == '__main__':
    main()
