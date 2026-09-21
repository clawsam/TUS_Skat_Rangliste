"""Aktualisiere Serien und Gesamtpunkte einer bestehenden Ranglisten-ODS."""

import argparse
from decimal import Decimal, ROUND_HALF_UP
from html import escape, unescape
from pathlib import Path
import re
import zipfile

ROW_RE = re.compile(r'<table:table-row\b.*?</table:table-row>', re.DOTALL)
CELL_RE = re.compile(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', re.DOTALL)
TEXT_RE = re.compile(r'<text:p\b[^>]*>(.*?)</text:p>', re.DOTALL)
STYLE_RE = re.compile(r'table:style-name="([^"]+)"')
BLACK_TO_RED = {'ce3': 'ce8', 'ce9': 'ce15', 'ce16': 'ce21',
                'ce22': 'ce27', 'ce29': 'ce34', 'ce36': 'ce41'}
RED_TO_BLACK = {red: black for black, red in BLACK_TO_RED.items()}


def key(name):
    return ' '.join(name.casefold().split())


def parse_report(path):
    pattern_with_id = re.compile(r'^\s*\d+\.\s+(\d+)\s+(.+?)\s+(\d+)\s+([\d.]+,\d{2})\s+(-?\d+)\s*$')
    pattern = re.compile(r'^\s*\d+\.\s+(.+?)\s+(\d+)\s+([\d.]+,\d{2})\s+(-?\d+)\s*$')
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = pattern_with_id.match(line)
        if match:
            player_id, name, series, average, points = match.groups()
        else:
            match = pattern.match(line)
            if not match:
                continue
            name, series, average, points = match.groups()
            player_id = None
        result_key = player_id or key(name)
        if result_key in result:
            raise ValueError(f'Doppelter Name in Auswertung: {name}')
        result[result_key] = {
            'name': name,
            'id': player_id,
            'series': int(series),
            'points': int(points),
            'average': Decimal(average.replace('.', '').replace(',', '.')),
        }
    if not result:
        raise ValueError(f'Keine Ranglistenzeilen in {path}')
    return result


def set_number(cell, value, display, formula=None):
    self_closing = cell.rstrip().endswith('/>')
    if self_closing:
        cell = cell.rstrip()[:-2] + '>'
    opening_end = cell.find('>')
    opening = cell[:opening_end]
    rest = cell[opening_end:]
    for name, replacement in [('office:value-type', 'float'), ('office:value', str(value))]:
        attribute = re.compile(rf'\s{name}="[^"]*"')
        if attribute.search(opening):
            opening = attribute.sub(f' {name}="{replacement}"', opening, count=1)
        else:
            opening += f' {name}="{replacement}"'
    if formula is not None:
        attribute = re.compile(r'\stable:formula="[^"]*"')
        if attribute.search(opening):
            opening = attribute.sub(f' table:formula="{formula}"', opening, count=1)
        else:
            opening += f' table:formula="{formula}"'
    text = f'<text:p>{display}</text:p>'
    rest = f'>{text}</table:table-cell>' if self_closing else TEXT_RE.sub(text, rest, count=1)
    return opening + rest


def set_text(cell, value):
    self_closing = cell.rstrip().endswith('/>')
    if self_closing:
        cell = cell.rstrip()[:-2] + '>'
    opening_end = cell.find('>')
    opening = cell[:opening_end]
    rest = cell[opening_end:]
    opening = re.sub(r'\s+office:value-type="[^"]*"', '', opening)
    opening = re.sub(r'\s+office:value="[^"]*"', '', opening)
    opening += ' office:value-type="string"'
    text = f'<text:p>{escape(value)}</text:p>'
    rest = f'>{text}</table:table-cell>' if self_closing else TEXT_RE.sub(text, rest, count=1)
    return opening + rest


def logical_cells(row):
    cells = []
    for cell in CELL_RE.findall(row):
        repeated = re.search(r'number-columns-repeated="(\d+)"', cell)
        cells.extend([cell] * int(repeated.group(1)) if repeated else [cell])
    return cells


def number(cell, default='0'):
    match = re.search(r'office:value="([^"]+)"', cell)
    return Decimal(match.group(1)) if match else Decimal(default)


def replace_cells(row, updates):
    spans = []
    logical = 0
    for match in CELL_RE.finditer(row):
        cell = match.group(0)
        repeated = re.search(r'number-columns-repeated="(\d+)"', cell)
        count = int(repeated.group(1)) if repeated else 1
        spans.append((logical, logical + count, match.start(), match.end(), cell))
        logical += count
    replacements = []
    for index, update in updates.items():
        span = next((span for span in spans if span[0] <= index < span[1]), None)
        if span is None:
            raise ValueError(f'Ranglistenzeile hat keine Spalte {index} (nur {logical} Spalten)')
        start, end, left, right, cell = span
        replacements.append((left, right, update(cell)))
    for left, right, replacement in reversed(replacements):
        row = row[:left] + replacement + row[right:]
    return row


def replace_one_cell(row, index, update):
    logical = 0
    for match in CELL_RE.finditer(row):
        cell = match.group(0)
        repeated = re.search(r'number-columns-repeated="(\d+)"', cell)
        count = int(repeated.group(1)) if repeated else 1
        if logical <= index < logical + count:
            changed = update(cell)
            if count > 1:
                rest = cell
                if repeated:
                    rest = re.sub(r'number-columns-repeated="\d+"',
                                  f'number-columns-repeated="{count - 1}"', cell, count=1)
                changed += rest
            return row[:match.start()] + changed + row[match.end():]
        logical += count
    raise IndexError(f'Keine Zelle an Position {index}')


def id_cell(value):
    return (f'<table:table-cell office:value-type="float" office:value="{value}">'
            f'<text:p>{value}</text:p></table:table-cell>')


def text_cell(value):
    return f'<table:table-cell office:value-type="string"><text:p>{value}</text:p></table:table-cell>'


def style_color_pairs(content):
    black_to_red = {}
    red_to_black = {}
    groups = {}
    for block in re.findall(r'<style:style\b[^>]*>.*?</style:style>', content, re.DOTALL):
        name_match = re.search(r'style:name="([^"]+)"', block)
        if not name_match or '#000000' not in block and '#ff3333' not in block:
            continue
        name = name_match.group(1)
        normalized = re.sub(r'style:name="[^"]+"', '', block)
        normalized = normalized.replace('#000000', '#COLOR').replace('#ff3333', '#COLOR')
        groups.setdefault(normalized, []).append((name, '#ff3333' in block))
    for group in groups.values():
        black = [name for name, red in group if not red]
        red = [name for name, is_red in group if is_red]
        for name in black:
            if red:
                black_to_red[name] = red[0]
        for name in red:
            if black:
                red_to_black[name] = black[0]
    return black_to_red, red_to_black


def set_border_color(row, red, style_pairs):
    def replace(match):
        name = match.group(1)
        styles = style_pairs[0] if red else style_pairs[1]
        return f'table:style-name="{styles.get(name, name)}"'
    return STYLE_RE.sub(replace, row)


def update_ods(source, output, report):
    values = parse_report(report)
    with zipfile.ZipFile(source) as archive:
        content = archive.read('content.xml').decode('utf-8')
        style_pairs = style_color_pairs(content)
        existing = set()
        updated = set()
        report_by_id = {item['id']: item for item in values.values() if item['id']}
        if not report_by_id:
            raise ValueError('Die Auswertung enthält keine Spieler-IDs')
        data_rows = []
        row_matches = list(ROW_RE.finditer(content))
        header_match = next((match for match in row_matches
                             if 'Name' in [unescape(TEXT_RE.search(cell).group(1))
                                           if TEXT_RE.search(cell) else ''
                                           for cell in logical_cells(match.group(0))]), None)
        if header_match is None:
            raise ValueError('Keine Ranglisten-Kopfzeile gefunden')
        header_cells = logical_cells(header_match.group(0))
        header_values = [unescape(TEXT_RE.search(cell).group(1)).strip()
                         if TEXT_RE.search(cell) else '' for cell in header_cells]
        if 'ID' not in header_values:
            raise ValueError('Die Rangliste benötigt eine vorhandene ID-Spalte')
        id_index = header_values.index('ID')
        for match in row_matches:
            row = match.group(0)
            row_cells = logical_cells(row)
            if len(row_cells) <= 12:
                continue
            if match is header_match:
                continue
            row_id = (unescape(TEXT_RE.search(row_cells[id_index]).group(1)).strip()
                      if len(row_cells) > id_index and TEXT_RE.search(row_cells[id_index]) else '')
            if row_id:
                existing.add(row_id)
            item = report_by_id.get(row_id)
            if item is not None:
                calculated = Decimal(item['points']) / Decimal(item['series'])
                display = calculated.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                row = replace_cells(row, {
                    2: lambda cell: set_text(cell, item['name']),
                    3: lambda cell: set_number(cell, item['series'], str(item['series'])),
                    4: lambda cell: set_number(cell, item['points'], str(item['points'])),
                    5: lambda cell: set_number(cell, calculated, f'{display:.2f}'.replace('.', ',')),
                })
                updated.add(row_id)
                row_cells = logical_cells(row)
                name = item['name']
            else:
                name_match = TEXT_RE.search(row_cells[2])
                if not name_match:
                    continue
                name = unescape(name_match.group(1)).strip()
                if not name or name.casefold() == 'name':
                    continue
            series = int(number(row_cells[3]))
            points = int(number(row_cells[4]))
            average = Decimal(points) / Decimal(series) if series else Decimal('0')
            bonus = Decimal(series - 50) / 2
            total = average + bonus
            row = replace_cells(row, {
                11: lambda cell: set_number(cell, bonus, f'{bonus:.2f}'.replace('.', ',')),
                12: lambda cell: set_number(cell, total, f'{total.quantize(Decimal(".01"), rounding=ROUND_HALF_UP):.2f}'.replace('.', ',')),
            })
            data_rows.append({'match': match, 'row': row, 'name': name,
                              'series': series, 'points': points, 'total': total})

        slots = sorted((item['match'].start(), item['match'].end()) for item in data_rows)
        data_rows.sort(key=lambda item: (item['series'] < 40, -item['total'],
                                         -item['points'], key(item['name'])))
        top_count = sum(item['series'] >= 40 for item in data_rows)
        replacements = []
        for rank, item in enumerate(data_rows, 1):
            row = item['row']
            row_cells = logical_cells(row)
            bonus = Decimal(item['series'] - 50) / 2
            total = Decimal(item['points']) / Decimal(item['series']) + bonus if item['series'] else bonus
            row = replace_cells(row, {
                1: lambda cell: set_number(cell, rank, str(rank)),
                11: lambda cell: set_number(cell, bonus, f'{bonus:.2f}'.replace('.', ','),
                                             f'of:=([.D{rank + 1}]-50)/2'),
                12: lambda cell: set_number(cell, total,
                                             f'{total.quantize(Decimal(".01"), rounding=ROUND_HALF_UP):.2f}'.replace('.', ',')),
            })
            row = re.sub(r'\.([A-Z]+)\d+',
                         lambda match: f'.{match.group(1)}{rank + 1}', row)
            row = set_border_color(row, rank > top_count, style_pairs)
            replacements.append((*slots[rank - 1], row))
        for start, end, row in sorted(replacements, reverse=True):
            content = content[:start] + row + content[end:]

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as result:
            for entry in archive.infolist():
                data = content.encode('utf-8') if entry.filename == 'content.xml' else archive.read(entry)
                result.writestr(entry, data)

    skipped = sorted(f'{item["id"]}: {item["name"]}' for item in values.values()
                     if item['id'] and item['id'] not in updated)
    return len(updated), len(existing), skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('rangliste', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    updated, existing, skipped = update_ods(args.rangliste, args.output, args.report)
    print(f'{updated} IDs aktualisiert, {existing} Ranglisten-IDs geprüft')
    if skipped:
        print(f'Nicht übernommen: {len(skipped)} Namen (nicht in der bestehenden Rangliste)')


if __name__ == '__main__':
    main()
