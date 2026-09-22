"""Ergänzt eine bestehende Setzliste um den neuesten Spieltag."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

from aktualisiere_rangliste import parse_report

N = {
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
}
MAX_COLUMNS = 135  # EE: letzter Bereich, den die Tischpunkte-Formeln auswerten
GROUPS = {'0': 'Grün', '1': 'Gelb', '2': 'Rot', '3': 'Grau', '4': 'Blau'}
GROUP_COLORS = {
    'Grün': '#99ff66', 'Gelb': '#ffff99', 'Rot': '#ff9999',
    'Grau': '#dddddd', 'Blau': '#66ccff',
}
GROUP_SUFFIX = {'Grün': 'gruen', 'Gelb': 'gelb', 'Rot': 'rot',
                'Grau': 'grau', 'Blau': 'blau'}
for prefix, uri in N.items():
    ET.register_namespace(prefix, uri)


def key(name):
    return ' '.join(sorted(re.sub(r'[^\wäöüÄÖÜß]+', ' ', name).casefold().split()))


def ods_rows(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('content.xml'))
    result = {}
    for table in root.findall('.//table:table', N):
        name = table.get(f'{{{N["table"]}}}name')
        rows = []
        for table_row in table.findall('table:table-row', N):
            values = []
            for cell in table_row.findall('table:table-cell', N):
                repeat = int(cell.get(f'{{{N["table"]}}}number-columns-repeated', '1'))
                paragraph = cell.find('text:p', N)
                value = ''.join(paragraph.itertext()) if paragraph is not None else ''
                values.extend([value] * repeat)
            rows.append(values)
        result[name] = rows
    return result


def rank_values(path):
    for rows in ods_rows(path).values():
        index = next((i for i, row in enumerate(rows)
                      if 'Name' in row and 'Schnitt' in row), None)
        if index is None:
            continue
        header = rows[index]
        name_col = header.index('Name')
        id_col = header.index('ID') if 'ID' in header else None
        value_col = header.index('Gesamt' if 'Gesamt' in header else 'Schnitt')
        return {
            'by_id': {row[id_col].strip(): row[value_col]
                      for row in rows[index + 1:]
                      if id_col is not None and len(row) > max(id_col, value_col)
                      and row[id_col].strip() and row[value_col].strip()},
            'by_name': {key(row[name_col]): row[value_col]
                for row in rows[index + 1:]
                if len(row) > value_col and row[name_col].strip() and row[value_col].strip()},
            'players': {row[id_col].strip(): row[name_col].strip()
                for row in rows[index + 1:]
                if id_col is not None and len(row) > max(id_col, name_col)
                and row[id_col].strip() and row[name_col].strip()}
        }
    raise ValueError(f'Keine Ranglistentabelle in {path}')


def latest_game(path, target_date=None):
    sheets = ods_rows(path)
    dated = [(datetime.strptime(name, '%d.%m.%Y'), name, rows)
             for name, rows in sheets.items()
             if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', name)]
    if not dated:
        raise ValueError(f'Keine Spieltagblätter in {path}')
    if target_date is None:
        _, date, rows = max(dated)
    else:
        matches = [item for item in dated if item[1] == target_date]
        if not matches:
            raise ValueError(f'Spieltag {target_date} ist nicht in {path} enthalten')
        _, date, rows = matches[0]
    header, data = rows[0], rows[1:]
    groups = Counter((row[8], row[9]) for row in data)
    grouped_rows = defaultdict(list)
    for index, row in enumerate(data):
        grouped_rows[row[8], row[9]].append((index, row))
    inferred_tp = {}
    for group, entries in grouped_rows.items():
        if not any(not row[13] for _, row in entries):
            continue
        ranked = sorted(entries, key=lambda item: int(item[1][2]), reverse=True)
        size = groups[group]
        codes = (['3', '2', '1', '0'] if size == 4 else
                 ['3', '1', '0'] if size == 3 else [])
        for rank, (index, _) in enumerate(ranked):
            if rank < len(codes):
                inferred_tp[index] = codes[rank]
    values = defaultdict(list)
    last_series = {}
    for index, row in enumerate(data):
        player = row[0].strip()
        series = int(row[8])
        if row[2] and (player not in last_series or series >= last_series[player][0]):
            last_series[player] = (series, row[2])
        table_position = row[13] or inferred_tp.get(index)
        if not table_position:
            continue
        size = groups[(row[8], row[9])]
        money = ({'3': '2,00 €', '2': '1,20 €', '1': '0,80 €', '0': '0,00 €'}
                 if size == 4 else {'3': '2,00 €', '1': '1,00 €', '0': '0,00 €'}).get(table_position)
        if money is None:
            raise ValueError(f'Unbekannter Tischgeldwert: TP={row[13]}, Größe={size}')
        values[player].append((series, money))
    return date, values, {player: value for player, (_, value) in last_series.items()}


def date_group(label):
    match = re.fullmatch(r'(\d{1,2})\.(\d{1,2})(?:\.)?[-.]\d+', label.strip())
    if not match:
        match = re.fullmatch(r'(\d{1,2})\.(\d{1,2})4[-.]\d+', label.strip())
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    if month > 12 and str(month).endswith('4'):
        month //= 10
    return day, month


def absence_groups(header, start, qualified_dates=None):
    named = [i for i, value in enumerate(header[start:], start) if date_group(value)]
    if not named:
        return []
    groups, index = [], start
    last = max(named)
    while index <= last:
        label = header[index].strip()
        group = date_group(label)
        if group and qualified_dates is not None:
            try:
                group_date = datetime(next(iter(qualified_dates)).year, group[1], group[0]).date()
            except (StopIteration, ValueError):
                group_date = None
            if group_date not in qualified_dates:
                index += 1
                continue
        if group:
            columns = [index]
            index += 1
            while index <= last and date_group(header[index]) == group:
                columns.append(index)
                index += 1
        else:
            columns = [index]
            index += 1
            while index <= last and not header[index].strip():
                columns.append(index)
                index += 1
        groups.append(columns)
    return groups


def qualified_game_dates(source_games):
    qualified, all_dates = set(), []
    for name, rows in ods_rows(source_games).items():
        try:
            date = datetime.strptime(name, '%d.%m.%Y').date()
        except ValueError:
            continue
        all_dates.append(date)
        tables = {row[9].strip() for row in rows[1:] if len(row) > 9 and row[9].strip()}
        if len(tables) >= 3:
            qualified.add(date)
    return qualified, max(all_dates) if all_dates else None


def absence_value(logical, groups, as_of=None, header=None, start=None):
    if as_of is not None and header is not None and start is not None:
        dates = []
        for columns in groups:
            label = next((header[index] for index in columns if date_group(header[index])), '')
            day_month = date_group(label)
            dates.append(datetime(as_of.year, day_month[1], day_month[0]).date()
                         if day_month else None)
        last_entry = None
        for columns, date in zip(groups, dates):
            if date and any(index < len(logical) and cell_text(logical[index]).strip()
                            for index in columns):
                last_entry = date
        if last_entry is None:
            return '4'
        current_week = as_of - timedelta(days=as_of.weekday())
        last_week = last_entry - timedelta(days=last_entry.weekday())
        return str(min(4, max(0, (current_week - last_week).days // 7)))
    absent = 0
    for group in reversed(groups):
        if any(index < len(logical)
               and logical[index].find('<text:p') >= 0
               and cell_text(logical[index]).strip()
               for index in group):
            break
        absent += 1
        if absent == 4:
            break
    return str(absent)


def data_rows(rows):
    return [rows[0]] + [row for row in rows[1:]
                        if cells(row)
                        and ((cell_text(cells(row)[0]).strip().isdigit()
                              and int(cell_text(cells(row)[0]).strip()) > 0)
                             or (len(cells(row)) > 1
                                 and cell_text(cells(row)[1]).strip().isdigit()
                                 and int(cell_text(cells(row)[1]).strip()) > 0))]


def cell_text(cell):
    match = re.search(r'<text:p\b[^>]*>(.*?)</text:p>', cell, re.DOTALL)
    return re.sub(r'<.*?>', '', match.group(1)) if match else ''


def numeric_cell_value(cell):
    match = re.search(r'office:value="([0-9]+(?:\.[0-9]+)?)"', cell)
    if match:
        return Decimal(match.group(1))
    value = re.sub(r'[^0-9,.-]', '', cell_text(cell)).replace(',', '.')
    try:
        return Decimal(value) if value else Decimal('0')
    except ArithmeticError:
        return Decimal('0')


def normalize_money_cells(row, header, start):
    logical = cells(row)
    for index in range(start, min(MAX_COLUMNS, len(logical), len(header))):
        if date_group(header[index]) and cell_text(logical[index]).strip():
            amount = numeric_cell_value(logical[index])
            row = replace_at(row, index,
                             update_cell(logical[index],
                                         f'{amount:.2f}'.replace('.', ','),
                                         numeric=True, suffix=' €'))
            logical = cells(row)
    return row


def cells(row):
    result = []
    for cell in re.findall(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', row, re.DOTALL):
        repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
        result.extend([cell] * (int(repeat.group(1)) if repeat else 1))
    return result


def remove_at(row, index):
    matches = list(re.finditer(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', row, re.DOTALL))
    logical = 0
    for match in matches:
        template = match.group(0)
        repeat_match = re.search(r'table:number-columns-repeated="(\d+)"', template)
        count = int(repeat_match.group(1)) if repeat_match else 1
        if logical <= index < logical + count:
            def repeated(amount):
                if amount <= 0:
                    return ''
                if amount == 1:
                    return re.sub(r'\s+table:number-columns-repeated="\d+"', '', template, count=1)
                return re.sub(r'table:number-columns-repeated="\d+"',
                              f'table:number-columns-repeated="{amount}"', template, count=1)
            before = index - logical
            replacement = repeated(before) + repeated(count - before - 1)
            return row[:match.start()] + replacement + row[match.end():]
        logical += count
    raise ValueError(f'ODS-Zelle {index} nicht gefunden')


def absence_index(header):
    for label in ('Abwesenheit', 'Abwesenheiten'):
        if label in header:
            return header.index(label)
    return None


def reuse_absence_column(rows, header):
    singular = header.index('Abwesenheit') if 'Abwesenheit' in header else None
    plural = header.index('Abwesenheiten') if 'Abwesenheiten' in header else None
    if singular is not None and plural is not None:
        header.pop(plural)
        rows[:] = [remove_at(row, plural) for row in rows]
    return absence_index(header)


def trim_row(row, limit=MAX_COLUMNS):
    matches = list(re.finditer(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', row, re.DOTALL))
    logical, kept = 0, []
    for match in matches:
        cell = match.group(0)
        repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
        count = int(repeat.group(1)) if repeat else 1
        take = min(count, max(0, limit - logical))
        if take:
            if take != count:
                if take == 1:
                    cell = re.sub(r'\s+table:number-columns-repeated="\d+"', '', cell)
                else:
                    cell = re.sub(r'table:number-columns-repeated="\d+"',
                                  f'table:number-columns-repeated="{take}"', cell)
            kept.append(cell)
        logical += count
        if logical >= limit:
            break
    if not matches:
        return row
    return row[:matches[0].start()] + ''.join(kept) + row[matches[-1].end():]


def trim_columns(body, limit=MAX_COLUMNS):
    matches = list(re.finditer(r'<table:table-column\b[^>]*/>|<table:table-column\b[^>]*>.*?</table:table-column>', body, re.DOTALL))
    logical, kept = 0, []
    for match in matches:
        column = match.group(0)
        repeat = re.search(r'table:number-columns-repeated="(\d+)"', column)
        count = int(repeat.group(1)) if repeat else 1
        take = min(count, max(0, limit - logical))
        if take:
            if take != count:
                if take == 1:
                    column = re.sub(r'\s+table:number-columns-repeated="\d+"', '', column)
                else:
                    column = re.sub(r'table:number-columns-repeated="\d+"',
                                    f'table:number-columns-repeated="{take}"', column)
            column = re.sub(r'\s+table:visibility="collapse"', '', column)
            kept.append(column)
        logical += count
        if logical >= limit:
            break
    if not matches:
        return body
    return body[:matches[0].start()] + ''.join(kept) + body[matches[-1].end():]


def fix_tischpunkte_formulas(body):
    return re.sub(r'table:formula="of:=SUM\(\[\.G(\d+):\.EE\1\]\)"',
                  r'table:formula="of:=SUM([.H\1:.EE\1])"', body)


def remove_formulas(body):
    return re.sub(r'\s+table:formula="[^"]*"', '', body)


def remove_repeated_rows(body):
    return re.sub(r'\s+table:number-rows-repeated="\d+"', '', body)


def tag_end(cell):
    quote = None
    for index, char in enumerate(cell):
        if char in '\"\'' and (index == 0 or cell[index - 1] != '\\'):
            quote = None if quote == char else char if quote is None else quote
        elif char == '>' and quote is None:
            return index
    raise ValueError('ODS-Zelle ohne schließendes öffnendes Tag')


def update_cell(cell, value, numeric=False, suffix=''):
    self_closing = cell.rstrip().endswith('/>')
    end = tag_end(cell)
    opening, rest = cell[:end], cell[end:]
    opening = opening.rstrip('/')
    rest = rest[1:]
    opening = re.sub(r'\s+office:value-type="[^"]*"', '', opening)
    opening = re.sub(r'\s+office:value="[^"]*"', '', opening)
    opening = re.sub(r'\s+table:formula="[^"]*"', '', opening)
    opening += f' office:value-type="{"float" if numeric and value else "string"}"'
    if numeric and value:
        opening += f' office:value="{value.replace(",", ".")}"'
    display = f'{value}{suffix}' if numeric and value else value
    if '<text:p' in rest:
        rest = re.sub(r'(<text:p\b[^>]*>).*?(</text:p>)',
                      lambda match: match.group(1) + display + match.group(2),
                      rest, count=1, flags=re.DOTALL)
    else:
        rest = f'<text:p>{display}</text:p>' + rest
    if self_closing:
        rest += '</table:table-cell>'
    return opening + '>' + rest


def column_name(index):
    result = ''
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(65 + remainder) + result
        index -= 1
    return result


def formula_cell(cell, formula, value, suffix=''):
    cell = update_cell(cell, value, numeric=True, suffix=suffix)
    end = tag_end(cell)
    opening = re.sub(r'\s+table:formula="[^"]*"', '', cell[:end])
    return opening + f' table:formula="{escape(formula, quote=True)}">' + cell[end + 1:]


def absence_formula(groups, row_number):
    # LibreOffice evaluates direct ranges reliably; Python updates these
    # ranges whenever a new game day is added.
    recent = groups[-4:]
    expression = '4'
    for status, group in reversed(list(enumerate(recent))):
        first, last = column_name(group[0]), column_name(group[-1])
        expression = (f'IF(COUNTA([.{first}{row_number}:.{last}{row_number}])>0;'
                      f'{status};{expression})')
    return f'of:={expression}'


def group_name(value):
    match = re.match(r'(Grün|Gelb|Rot|Grau|Blau)\b', value.strip())
    return match.group(1) if match else ''


def color_styles(content):
    group_suffixes = tuple(f'_{suffix}' for suffix in GROUP_SUFFIX.values())
    styles = {
        match.group(1): match.group(0)
        for match in re.finditer(
            r'<style:style\b[^>]*style:name="([^"]+)".*?</style:style>',
            content, re.DOTALL)
    }
    result = {}
    additions = []
    for name, style in list(styles.items()):
        if name.endswith(group_suffixes):
            continue
        for group, color in GROUP_COLORS.items():
            existing = re.search(r'fo:background-color="(#[0-9a-fA-F]+)"', style)
            if existing and existing.group(1).lower() == color:
                result[name, group] = name
                continue
            clone = f'{name}_{GROUP_SUFFIX[group]}'
            if clone not in styles:
                replacement = re.sub(r'(style:name=")[^"]+"', rf'\g<1>{clone}"', style, count=1)
                if existing:
                    replacement = replacement.replace(existing.group(0), f'fo:background-color="{color}"', 1)
                else:
                    replacement = replacement.replace(
                        '<style:table-cell-properties',
                        f'<style:table-cell-properties fo:background-color="{color}"', 1)
                styles[clone] = replacement
                additions.append(replacement)
            result[name, group] = clone

    # Auch bereits formatierte Zellen müssen eine Gruppenvariante bekommen.
    # Dabei wird ausschließlich die Hintergrundfarbe ersetzt.
    for block in re.findall(r'<style:style\b[^>]*>.*?</style:style>', content, re.DOTALL):
        name_match = re.search(r'style:name="([^"]+)"', block)
        family_match = re.search(r'style:family="([^"]+)"', block)
        if not name_match or not family_match or family_match.group(1) != 'table-cell':
            continue
        base = name_match.group(1)
        if base.endswith(group_suffixes):
            continue
        for group, color in GROUP_COLORS.items():
            clone = f'{base}_{GROUP_SUFFIX[group]}'
            if clone in styles:
                result[base, group] = clone
                continue
            replacement = re.sub(r'(style:name=")[^"]+"', rf'\g<1>{clone}"', block, count=1)
            if 'fo:background-color=' in replacement:
                replacement = re.sub(r'fo:background-color="#[0-9a-fA-F]+"',
                                     f'fo:background-color="{color}"', replacement, count=1)
            else:
                replacement = replacement.replace(
                    '<style:table-cell-properties',
                    f'<style:table-cell-properties fo:background-color="{color}"', 1)
            styles[clone] = replacement
            additions.append(replacement)
            result[base, group] = clone
    for block in re.findall(r'<style:style\b[^>]*>.*?</style:style>', content, re.DOTALL):
        name_match = re.search(r'style:name="([^"]+)"', block)
        family_match = re.search(r'style:family="([^"]+)"', block)
        if not name_match or not family_match or family_match.group(1) != 'table-row':
            continue
        base = name_match.group(1)
        if base.endswith(group_suffixes):
            continue
        for group, suffix in GROUP_SUFFIX.items():
            clone = f'{base}_{suffix}'
            replacement = re.sub(r'(style:name=")[^"]+"', rf'\g<1>{clone}"', block, count=1)
            if 'fo:background-color=' in replacement:
                replacement = re.sub(r'fo:background-color="#[0-9a-fA-F]+"',
                                     f'fo:background-color="{GROUP_COLORS[group]}"', replacement, count=1)
            else:
                replacement = replacement.replace(
                    '<style:table-row-properties',
                    f'<style:table-row-properties fo:background-color="{GROUP_COLORS[group]}"', 1)
            additions.append(replacement)
            result['row', base, group] = clone
    if additions:
        content = content.replace('</office:automatic-styles>',
                                  ''.join(additions) + '</office:automatic-styles>', 1)
    return content, result


def currency_styles(content):
    def replace_style(match):
        style = match.group(0)
        if re.search(r'style:name="ce(?:28|45)(?:_[^"]+)?"', style):
            style = re.sub(r'style:data-style-name="[^"]+"',
                           'style:data-style-name="N8107"', style, count=1)
        return style
    return re.sub(r'<style:style\b[^>]*>.*?</style:style>', replace_style,
                  content, flags=re.DOTALL)


def set_style(cell, style_name):
    if 'table:style-name=' in cell:
        return re.sub(r'table:style-name="[^"]+"',
                      f'table:style-name="{style_name}"', cell, count=1)
    return cell.replace('<table:table-cell',
                        f'<table:table-cell table:style-name="{style_name}"', 1)


def colorize_row(row, group, styles, templates):
    row_style = re.search(r'<table:table-row\b[^>]*table:style-name="([^"]+)"', row)
    if row_style and ('row', row_style.group(1), group) in styles:
        row = row.replace(f'table:style-name="{row_style.group(1)}"',
                          f'table:style-name="{styles["row", row_style.group(1), group]}"', 1)
    matches = list(re.finditer(
        r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>',
        row, re.DOTALL))
    if not matches:
        return row
    expanded = []
    for match in matches:
        cell = match.group(0)
        repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
        cell = re.sub(r'\s+table:number-columns-repeated="\d+"', '', cell, count=1)
        expanded.extend([cell] * (int(repeat.group(1)) if repeat else 1))
    recolored = []
    for index, cell in enumerate(expanded):
        style = re.search(r'table:style-name="([^"]+)"', cell)
        base = style.group(1) if style else templates.get(index)
        if base and (base, group) in styles:
            replacement = f'table:style-name="{styles[base, group]}"'
            if style:
                cell = cell.replace(style.group(0), replacement, 1)
            else:
                cell = cell.replace('<table:table-cell',
                                    f'<table:table-cell {replacement}', 1)
        recolored.append(cell)
    return row[:matches[0].start()] + ''.join(recolored) + row[matches[-1].end():]


def assign_groups(rows, header, styles=None):
    group_index = header.index('Gruppe')
    id_index = header.index('ID')
    status_index = absence_index(header)
    if status_index is None:
        raise ValueError('Keine Abwesenheitsspalte in der Setzliste')
    value_index = header.index('Schnitt')
    templates = {}
    for row in rows[1:]:
        for index, cell in enumerate(cells(row)):
            style = re.search(r'table:style-name="([^"]+)"', cell)
            if style and index not in templates:
                templates[index] = style.group(1)
    active = []
    parsed = {}
    for row_index, row in enumerate(rows[1:], 1):
        logical = cells(row)
        previous = group_name(cell_text(logical[group_index]))
        try:
            player_id = int(cell_text(logical[id_index]).strip())
            status = int(cell_text(logical[status_index]).strip() or '4')
            value = numeric_cell_value(logical[value_index])
        except (IndexError, ValueError, ArithmeticError):
            continue
        parsed[row_index] = (player_id, status, value)
        if player_id < 100 and status < 4:
            active.append((value, row_index))
    active.sort(key=lambda item: (-item[0], item[1]))
    base, remainder = divmod(len(active), 3)
    sizes = [base + (remainder > 0), base + (remainder > 1), base]
    labels = (['Grün'] * sizes[0] + ['Gelb'] * sizes[1] + ['Rot'] * sizes[2])
    assigned = {row_index: labels[index] for index, (_, row_index) in enumerate(active)}
    for row_index, (player_id, status, _) in parsed.items():
        previous = group_name(cell_text(cells(rows[row_index])[group_index]))
        assigned[row_index] = ('Blau' if player_id > 99 else
                                'Grau' if status >= 4 else assigned.get(row_index, 'Rot'))
    for row_index, row in enumerate(rows[1:], 1):
        logical = cells(row)
        if row_index in assigned:
            current = assigned[row_index]
            previous = group_name(cell_text(logical[group_index]))
            label = (f'{current} (vorher {previous})'
                     if current in ('Grün', 'Gelb', 'Rot')
                     and previous in ('Grün', 'Gelb', 'Rot')
                     and current != previous else current)
            row = replace_at(row, group_index, update_cell(logical[group_index], label))
            rows[row_index] = (colorize_row(row, current, styles, templates)
                               if styles else row)
    return rows


def sort_rows(rows, header):
    group_index = header.index('Gruppe')
    place_index = header.index('Platz')
    last_index = header.index('letzte Serie')
    value_index = header.index('Schnitt')
    order = {'Grün': 0, 'Gelb': 1, 'Rot': 2, 'Grau': 3, 'Blau': 4}
    sortable = []
    for row_index, row in enumerate(rows[1:], 1):
        logical = cells(row)
        group = group_name(cell_text(logical[group_index]))
        try:
            last = (numeric_cell_value(logical[last_index])
                    if cell_text(logical[last_index]).strip() else Decimal('-999999999'))
        except (IndexError, ValueError, ArithmeticError):
            last = Decimal('-999999999')
        try:
            value = (numeric_cell_value(logical[value_index])
                     if cell_text(logical[value_index]).strip() else Decimal('-999999999'))
        except (IndexError, ValueError, ArithmeticError):
            value = Decimal('-999999999')
        sortable.append((order.get(group, 99), -last, -value, row_index, row))
    sortable.sort(key=lambda item: item[:4])
    result = [rows[0]]
    for place, (_, _, _, old_row_index, row) in enumerate(sortable, 1):
        row = re.sub(rf'(?<=[A-Z]){old_row_index + 1}(?!\d)', str(place + 1), row)
        logical = cells(row)
        row = replace_at(row, place_index,
                         update_cell(logical[place_index], str(place), numeric=True))
        result.append(row)
    return result


def replace_at(row, index, replacement):
    matches = list(re.finditer(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', row, re.DOTALL))
    logical = 0
    for match in matches:
        cell = match.group(0)
        repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
        count = int(repeat.group(1)) if repeat else 1
        if logical <= index < logical + count:
            return row[:match.start()] + replacement + row[match.end():]
        logical += count
    raise ValueError(f'ODS-Zelle {index} nicht gefunden')


def empty_row(row):
    for index in range(len(cells(row))):
        row = replace_at(row, index, update_cell(cells(row)[index], ''))
    return row


def insert_at(row, index, values):
    matches = list(re.finditer(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', row, re.DOTALL))
    logical = 0
    for match in matches:
        template = match.group(0)
        repeat = re.search(r'table:number-columns-repeated="(\d+)"', template)
        count = int(repeat.group(1)) if repeat else 1
        if logical <= index < logical + count:
            before = index - logical
            opening = template[:tag_end(template)]
            opening = opening.rstrip('/') + '>'
            opening = re.sub(r'\s+table:number-columns-repeated="[^"]*"', '', opening)
            empty = opening + '</table:table-cell>'
            new = ''.join(update_cell(empty, value) for value in values)
            def repeated_cell(amount):
                if amount <= 0:
                    return ''
                if amount == 1:
                    return re.sub(r'\s+table:number-columns-repeated="\d+"', '', template, count=1)
                return re.sub(r'table:number-columns-repeated="\d+"',
                              f'table:number-columns-repeated="{amount}"', template, count=1)
            replacement = repeated_cell(before) + new + repeated_cell(count - before - 1)
            return row[:match.start()] + replacement + row[match.end():]
        logical += count
    raise ValueError(f'ODS-Einfügeposition {index} nicht gefunden')


def update(source_rank, source_setz, source_games, output, target_date=None,
           finalize=True, report=None):
    ranking = rank_values(source_rank)
    report_values = parse_report(report) if report else {}
    date, games, last_series = latest_game(source_games, target_date)
    qualified_dates, _ = qualified_game_dates(source_games)
    latest_names = {
        row[0].strip(): (row[1].strip(), row[2].strip())
        for row in ods_rows(source_games)[date][1:]
        if len(row) > 2 and row[0].strip() and row[1].strip()
    }
    day = datetime.strptime(date, '%d.%m.%Y')
    label = f'{day.day}.{day.month}.'
    with zipfile.ZipFile(source_setz) as archive:
        content = archive.read('content.xml').decode()
        content, styles = color_styles(content)
        content = currency_styles(content)
        match = re.search(r'(<table:table\b[^>]*table:name="Tabelle1"[^>]*>)(.*?)(</table:table>)', content, re.DOTALL)
        if not match:
            raise ValueError('Tabelle1 fehlt in der Setzliste')
        body = match.group(2)
        original_rows = re.findall(r'<table:table-row\b.*?</table:table-row>', body, re.DOTALL)
        original_rows = data_rows(original_rows)
        header = [cell_text(cell) for cell in cells(original_rows[0])]
        reuse_absence_column(original_rows, header)
        group_index = header.index('ID') + 1
        add_group = 'Gruppe' not in header
        if add_group:
            header.insert(group_index, 'Gruppe')
        name_index = header.index('Name')
        id_index = header.index('ID')
        value_index = header.index('Schnitt')
        points_index = header.index('Tischpunkte')
        last_index = header.index('letzte Serie')
        status_index = absence_index(header) if absence_index(header) is not None else name_index + 1
        add_status = absence_index(header) is None
        header_row = original_rows[0]
        if add_group:
            header_row = insert_at(header_row, group_index, ['Gruppe'])
        if add_status:
            header.insert(status_index, 'Abwesenheiten')
            header_row = insert_at(header_row, status_index, ['Abwesenheiten'])
        name_index = header.index('Name')
        value_index = header.index('Schnitt')
        points_index = header.index('Tischpunkte')
        last_index = header.index('letzte Serie')
        daily_column = column_name(points_index + 1)
        status_index = absence_index(header)
        start = max(i for i, value in enumerate(header) if value.strip()) + 1
        slot_count = max((len(values) for values in games.values()), default=1)
        new_labels = [f'{label}-{slot}' for slot in range(1, slot_count + 1)]
        if any(value in header for value in new_labels):
            raise ValueError(f'Spieltag {label} ist bereits in der Setzliste enthalten')
        effective_header = header[:start] + new_labels + header[start:]
        groups = absence_groups(effective_header, points_index + 1, qualified_dates)
        day_for_absence = day.date()
        earlier = [value for value in qualified_dates if value <= day_for_absence]
        if earlier:
            day_for_absence = max(earlier)
        new_rows = [trim_row(insert_at(header_row, start, new_labels))]
        updated, unmatched = 0, set(games)
        for row in original_rows[1:]:
            if add_group:
                row = insert_at(row, group_index, [''])
            if add_status:
                row = insert_at(row, status_index, ['0'])
            logical = cells(row)
            name = cell_text(logical[name_index]).strip() if len(logical) > name_index else ''
            player_key = cell_text(logical[id_index]).strip()
            player_id = cell_text(logical[id_index]).strip()
            rank_value = (ranking['by_id'].get(player_id)
                          or ranking['by_name'].get(key(name)))
            if group_name(cell_text(logical[group_index])) == 'Blau':
                report_value = report_values.get(player_id)
                if report_value:
                    rank_value = f'{report_value["average"]:.2f}'.replace('.', ',')
            if rank_value is not None:
                row = replace_at(row, value_index,
                                 update_cell(logical[value_index], rank_value,
                                             numeric=True, suffix=' €'))
            logical = cells(row)
            if player_key in last_series:
                row = replace_at(row, last_index,
                                 update_cell(logical[last_index], last_series[player_key], numeric=True))
            values = [value for _, value in sorted(games.get(player_key, []))]
            if values:
                updated += len(values)
                unmatched.discard(player_key)
                previous = cell_text(logical[points_index]).replace('€', '').replace(',', '.').strip()
                total = Decimal(previous or '0') + sum(
                    (Decimal(value.replace(' €', '').replace(',', '.')) for value in values),
                    Decimal('0'))
                row = replace_at(row, points_index,
                                 update_cell(logical[points_index],
                                             f'{total:.2f}'.replace('.', ','), numeric=True))
            row = insert_at(row, start, values + [''] * max(0, slot_count - len(values)))
            row = normalize_money_cells(row, effective_header, points_index + 1)
            logical = cells(row)
            sheet_row = len(new_rows) + 1
            status = absence_value(logical, groups, day_for_absence, effective_header, points_index + 1)
            row = replace_at(row, status_index, update_cell(logical[status_index], status))
            logical = cells(row)
            total = sum((numeric_cell_value(logical[index])
                         for index in range(points_index + 1,
                                            min(MAX_COLUMNS, len(logical)))
                         if index < len(effective_header)
                         and date_group(effective_header[index])),
                        Decimal('0'))
            formula_end = column_name(min(MAX_COLUMNS, len(logical)) - 1)
            row = replace_at(row, points_index,
                             formula_cell(logical[points_index],
                                          f'of:=SUM([.{daily_column}{sheet_row}:.{formula_end}{sheet_row}])',
                                          f'{total:.2f}'.replace('.', ','), suffix=' €'))
            new_rows.append(trim_row(row))

        # Spieler, die erstmals in der Rangliste erscheinen, starten immer blau.
        existing_ids = {cell_text(cells(row)[id_index]).strip()
                        for row in new_rows[1:] if len(cells(row)) > id_index}
        template = (new_rows[1] if len(new_rows) > 1 else
                    empty_row(trim_row(insert_at(header_row, start, new_labels))))
        player_ids = set(latest_names) | set(ranking['players'])
        for player_id in sorted(player_ids):
            if player_id in existing_ids:
                continue
            game_name, game_value = latest_names.get(
                player_id, (ranking['players'].get(player_id, ''), ''))
            row = template
            logical = cells(row)
            for index in range(len(logical)):
                row = replace_at(row, index, update_cell(cells(row)[index], ''))
            first, last = (part.strip() for part in game_name.split(',', 1))
            name = f'{last} {first}' if last else first
            row = replace_at(row, id_index, update_cell(cells(row)[id_index], player_id))
            row = replace_at(row, group_index, update_cell(cells(row)[group_index], 'Blau'))
            row = replace_at(row, name_index, update_cell(cells(row)[name_index], name))
            row = replace_at(row, status_index, update_cell(cells(row)[status_index], '0'))
            report_value = report_values.get(player_id)
            value = (f'{report_value["average"]:.2f}'.replace('.', ',')
                     if report_value else ranking['by_id'].get(player_id, game_value or '0'))
            row = replace_at(row, value_index,
                             update_cell(cells(row)[value_index], value,
                                         numeric=True, suffix=' €'))
            if player_id in last_series:
                row = replace_at(row, last_index,
                                 update_cell(cells(row)[last_index], last_series[player_id], numeric=True))
            values = [value for _, value in sorted(games.get(player_id, []))]
            updated += len(values)
            row = insert_at(row, start, values + [''] * max(0, slot_count - len(values)))
            row = normalize_money_cells(row, effective_header, points_index + 1)
            logical = cells(row)
            sheet_row = len(new_rows) + 1
            status = absence_value(logical, groups, day_for_absence, effective_header, points_index + 1)
            row = replace_at(row, status_index, update_cell(logical[status_index], status))
            logical = cells(row)
            total = sum((numeric_cell_value(logical[index])
                         for index in range(points_index + 1, min(MAX_COLUMNS, len(logical)))
                         if index < len(effective_header) and date_group(effective_header[index])),
                        Decimal('0'))
            formula_end = column_name(min(MAX_COLUMNS, len(logical)) - 1)
            row = replace_at(row, points_index,
                             formula_cell(logical[points_index],
                                          f'of:=SUM([.{daily_column}{sheet_row}:.{formula_end}{sheet_row}])',
                                          f'{total:.2f}'.replace('.', ','), suffix=' €'))
            new_rows.append(trim_row(row))
            existing_ids.add(player_id)
            unmatched.discard(player_id)
        if finalize:
            new_rows = assign_groups(new_rows, header, styles)
            new_rows = sort_rows(new_rows, header)
        total_row = header_row
        total_cells = cells(total_row)
        for index in range(len(header)):
            total_row = replace_at(total_row, index,
                                   update_cell(total_cells[index], '', numeric=False))
            total_cells = cells(total_row)
        total_row = replace_at(total_row, last_index,
                               update_cell(cells(total_row)[last_index], 'Summe'))
        data_first = 2
        data_last = len(new_rows)
        total_cells = cells(total_row)
        column = column_name(points_index)
        total_value = sum((numeric_cell_value(cells(row)[points_index])
                           for row in new_rows[1:]), Decimal('0'))
        total_row = replace_at(
            total_row, points_index,
            formula_cell(total_cells[points_index],
                         f'of:=SUM([.{column}{data_first}:.{column}{data_last}])',
                         f'{total_value:.2f}'.replace('.', ','), suffix=' €'))
        new_rows.append(trim_row(total_row))
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
    return date, updated, sorted(unmatched)


def finalize_setzliste(source, output, source_games=None):
    with zipfile.ZipFile(source) as archive:
        content = archive.read('content.xml').decode()
        content, styles = color_styles(content)
        content = currency_styles(content)
        match = re.search(r'(<table:table\b[^>]*table:name="Tabelle1"[^>]*>)(.*?)(</table:table>)',
                          content, re.DOTALL)
        if not match:
            raise ValueError('Tabelle1 fehlt in der Setzliste')
        body = match.group(2)
        source_rows = re.findall(r'<table:table-row\b.*?</table:table-row>', body, re.DOTALL)
        total_row = next((row for row in source_rows if 'Summe' in row), None)
        rows = data_rows(source_rows)
        header = [cell_text(cell) for cell in cells(rows[0])]
        reuse_absence_column(rows, header)
        points_index = header.index('Tischpunkte')
        template_cells = cells(rows[1]) if len(rows) > 1 else []
        template_style = (re.search(r'table:style-name="([^"]+)"',
                                    template_cells[points_index + 1])
                          if len(template_cells) > points_index + 1 else None)
        money_style = template_style.group(1) if template_style else 'ce52'
        qualified_dates = None
        final_date = None
        if source_games:
            qualified_dates, final_date = qualified_game_dates(source_games)
        groups = absence_groups(header, points_index + 1, qualified_dates)
        money_columns = [i for i, label in enumerate(header)
                         if i > points_index and date_group(label)]
        for row_index, row in enumerate(rows[1:], 1):
            row = normalize_money_cells(row, header, points_index + 1)
            logical = cells(row)
            for index in money_columns:
                if index < len(logical):
                    row = replace_at(row, index, set_style(logical[index], money_style))
                    logical = cells(row)
            total = sum((numeric_cell_value(cells(row)[index])
                         for index in money_columns if index < len(cells(row))), Decimal('0'))
            row = replace_at(row, points_index,
                             update_cell(cells(row)[points_index],
                                         f'{total:.2f}'.replace('.', ','),
                                         numeric=True, suffix=' €'))
            if final_date and groups:
                logical = cells(row)
                status = absence_value(logical, groups, final_date, header, points_index + 1)
                status_index = absence_index(header)
                row = replace_at(row, status_index,
                                 update_cell(cells(row)[status_index], status))
            rows[row_index] = row
        rows = assign_groups(rows, header, styles)
        rows = sort_rows(rows, header)
        if total_row:
            points_index = header.index('Tischpunkte')
            total = sum((numeric_cell_value(cells(row)[points_index])
                         for row in rows[1:]), Decimal('0'))
            total_row = replace_at(
                total_row, points_index,
                update_cell(cells(total_row)[points_index],
                            f'{total:.2f}'.replace('.', ','),
                            numeric=True, suffix=' €'))
            rows.append(trim_row(total_row))
        row_start = body.find('<table:table-row')
        new_body = body[:row_start] + ''.join(rows)
        new_body = remove_repeated_rows(new_body)
        content = content[:match.start(2)] + new_body + content[match.end(2):]
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as result:
            for entry in archive.infolist():
                result.writestr(entry, content.encode() if entry.filename == 'content.xml' else archive.read(entry))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rangliste', type=Path, nargs='?')
    parser.add_argument('setzliste', type=Path, nargs='?')
    parser.add_argument('spieltage', type=Path, nargs='?')
    parser.add_argument('--datum', help='Spieltag im Format TT.MM.JJJJ')
    parser.add_argument('--ohne-sortierung', action='store_true')
    parser.add_argument('--finalisieren', type=Path,
                        help='Nur Sortierung, Abwesenheiten und Farben anwenden')
    parser.add_argument('--spieltage', type=Path,
                        help='Spieltage-ODS zur Ermittlung der qualifizierten Spieltage')
    parser.add_argument('--auswertung', type=Path,
                        help='Jahresauswertung für den Schnitt blauer Spieler')
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    if args.finalisieren:
        finalize_setzliste(args.finalisieren, args.output, args.spieltage)
        print(f'{args.output}: finalisiert')
        return
    if not args.rangliste or not args.setzliste or not args.spieltage:
        parser.error('Rangliste, Setzliste und Spieltage sind erforderlich')
    date, updated, unmatched = update(args.rangliste, args.setzliste, args.spieltage,
                                      args.output, args.datum, not args.ohne_sortierung,
                                      args.auswertung)
    print(f'{args.output}: {date}, {updated} Tischgeldwerte ergänzt')
    if unmatched:
        print(f'Nicht in Setzliste gefunden: {len(unmatched)} Spieler')


if __name__ == '__main__':
    main()
