"""Übernimmt die Spieler-Nr aus Spieler.dbf in eine Setzlisten-ODS."""

import argparse
from pathlib import Path
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_vmz import dbf
from ergaenze_setzliste import (absence_formula, absence_groups, absence_value,
                                absence_index, assign_groups, cells, cell_text, column_name,
                                data_rows, reuse_absence_column,
                                fix_tischpunkte_formulas, formula_cell, insert_at, key,
                                remove_repeated_rows, replace_at, sort_rows, trim_columns,
                                trim_row, update_cell)

GROUPS = {'0': 'Grün', '1': 'Gelb', '2': 'Rot', '3': 'Grau', '4': 'Blau'}


def confirm_number_change(name, old, new):
    try:
        answer = input(
            f'Neue Spielernummer für {name}: {old} -> {new}. Richtig? [J/n] '
        ).strip().casefold()
    except EOFError:
        answer = ''
    return answer not in {'n', 'nein', 'no'}


def player_numbers(source):
    with zipfile.ZipFile(source) as archive:
        fields, records = dbf(archive.read('Spieler.dbf'))
    names = ['_record', '_deleted'] + [field[0] for field in fields]
    result = {}
    for record in records:
        row = dict(zip(names, record))
        if row['_deleted'] == '1':
            continue
        name = key(row['NAME1'])
        if name in result and result[name] != row['NR']:
            raise ValueError(f'Doppelter Spielername: {row["NAME1"]}')
        result[name] = row['NR']
    return result


def update(source_vmz, source_setzliste, output):
    numbers = player_numbers(source_vmz)
    with zipfile.ZipFile(source_setzliste) as archive:
        content = archive.read('content.xml').decode()
        import re
        match = re.search(r'(<table:table\b[^>]*table:name="Tabelle1"[^>]*>)(.*?)(</table:table>)', content, re.DOTALL)
        if not match:
            raise ValueError('Tabelle1 fehlt in der Setzliste')
        body = match.group(2)
        original_rows = re.findall(r'<table:table-row\b.*?</table:table-row>', body, re.DOTALL)
        original_rows = data_rows(original_rows)
        header = [cell_text(cell) for cell in cells(original_rows[0])]
        reuse_absence_column(original_rows, header)
        source_name_index = header.index('Name')
        source_id_index = header.index('ID')
        group_index = source_id_index + 1
        add_group = 'Gruppe' not in header
        if add_group:
            header.insert(group_index, 'Gruppe')
        name_index = header.index('Name')
        id_index = header.index('ID')
        status_index = absence_index(header) if absence_index(header) is not None else name_index + 1
        add_status = absence_index(header) is None
        header_row = original_rows[0]
        if add_group:
            header_row = insert_at(header_row, group_index, ['Gruppe'])
        if add_status:
            header.insert(status_index, 'Abwesenheiten')
            header_row = insert_at(header_row, status_index, ['Abwesenheiten'])
        points_index = header.index('Tischpunkte')
        daily_column = column_name(points_index + 1)
        groups = absence_groups(header, points_index + 1)
        valid_numbers = set(numbers.values())
        changed, unmatched = 0, []
        new_rows = [trim_row(header_row)]
        for row in original_rows[1:]:
            logical = cells(row)
            name = cell_text(logical[source_name_index]).strip().rstrip('*').strip() if len(logical) > source_name_index else ''
            existing_number = (cell_text(logical[source_id_index]).strip()
                               if len(logical) > source_id_index else '')
            number = numbers.get(key(name))
            if number is not None and existing_number and number != existing_number:
                if not confirm_number_change(name, existing_number, number):
                    number = existing_number
            elif number is None and existing_number in valid_numbers:
                number = existing_number
            if number is None:
                if name:
                    unmatched.append(name)
            else:
                row = replace_at(row, source_id_index, update_cell(logical[source_id_index], number, numeric=False))
                changed += 1
            if add_group:
                row = insert_at(row, group_index, [''])
            if add_status:
                row = insert_at(row, status_index, ['0'])
            logical = cells(row)
            sheet_row = len(new_rows) + 1
            status = absence_value(logical, groups)
            row = replace_at(row, status_index,
                             formula_cell(logical[status_index],
                                          absence_formula(groups, sheet_row), status))
            logical = cells(row)
            row = replace_at(row, points_index,
                             formula_cell(logical[points_index],
                                          f'of:=SUM([.{daily_column}{sheet_row}:.EE{sheet_row}])',
                                          cell_text(logical[points_index]) or '0'))
            new_rows.append(trim_row(row))
        row_start = body.find('<table:table-row')
        new_body = body[:row_start] + ''.join(new_rows)
        new_body = fix_tischpunkte_formulas(new_body)
        new_body = trim_columns(new_body)
        new_body = remove_repeated_rows(new_body)
        content = content[:match.start(2)] + new_body + content[match.end(2):]
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as result:
            for entry in archive.infolist():
                result.writestr(entry, content.encode() if entry.filename == 'content.xml' else archive.read(entry))
    return changed, sorted(set(unmatched))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmz', type=Path)
    parser.add_argument('setzliste', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    changed, unmatched = update(args.vmz, args.setzliste, args.output)
    print(f'{args.output}: {changed} Spieler-Nummern übernommen')
    if unmatched:
        print('Nicht zugeordnet:')
        print('\n'.join(f'- {name}' for name in unmatched))


if __name__ == '__main__':
    main()
