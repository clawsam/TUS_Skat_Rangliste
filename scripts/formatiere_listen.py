"""Farben und Rahmen nach allen Datenänderungen aus der Endposition ableiten."""

from html import unescape
import re

ROW = re.compile(r'<table:table-row\b.*?</table:table-row>', re.DOTALL)
CELL = re.compile(r'<table:table-cell\b[^>]*/>|<table:table-cell\b[^>]*>.*?</table:table-cell>', re.DOTALL)
STYLE = re.compile(r'table:style-name="([^"]+)"')
COLORS = {'Grün': '#99ff66', 'Gelb': '#ffff99', 'Rot': '#ff9999',
          'Grau': '#dddddd', 'Blau': '#66ccff'}


def text(cell):
    return unescape(re.sub(r'<[^>]+>', '', cell)).strip()


def format_layout(content, ranking=False):
    table = re.search(r'<table:table\b[^>]*>.*?</table:table>', content, re.DOTALL)
    if table is None:
        raise ValueError('Keine Tabelle für die Formatierung gefunden')
    rows = list(ROW.finditer(table.group()))

    def values(row):
        result = []
        for cell in CELL.findall(row):
            repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
            result.extend([text(cell)] * min(int(repeat[1]) if repeat else 1, 135 - len(result)))
        return result

    labels = [values(row.group()) for row in rows]
    header_index = next(i for i, row in enumerate(labels) if 'Name' in row)
    header = labels[header_index]
    first, last = (1, header.index('Gesamt')) if ranking else (0, header.index('Tischpunkte'))
    place = first if ranking else header.index('Platz')
    data = [i for i in range(header_index + 1, len(rows))
            if len(labels[i]) > last and labels[i][place].isdigit()]
    groups = {i: ('#000000' if int(labels[i][header.index('Serien')] or '0') >= 40
                  else '#ff3333') if ranking else labels[i][header.index('Gruppe')].split(' (')[0]
              for i in data}
    definitions = {match[1]: match[0] for match in re.finditer(
        r'<style:style\b[^>]*style:name="([^"]+)"[^>]*>.*?</style:style>', content, re.DOTALL)}
    additions, cache = [], {}

    def styled(cell, background, edges):
        match = STYLE.search(cell)
        base = match[1] if match else 'Default'
        base = re.sub(r'^layout_\d+_', '', base)
        key = base, background, tuple(edges)
        if key not in cache:
            name = f'layout_{len(definitions) + len(additions)}_{base}'
            while name in definitions:
                name += '_'
            attributes = f'fo:background-color="{background}" fo:border="none"'
            attributes += ''.join(f' fo:border-{side}="{border}"' for side, border in edges)
            block = definitions.get(base, f'<style:style style:name="{base}" style:family="table-cell" '
                                    'style:parent-style-name="Default"></style:style>')
            block = re.sub(r'style:name="[^"]+"', f'style:name="{name}"', block, count=1)
            block = re.sub(r'\s+fo:(?:background-color|border(?:-left|-right|-top|-bottom)?)="[^"]*"', '', block)
            if '<style:table-cell-properties' in block:
                block = block.replace('<style:table-cell-properties', f'<style:table-cell-properties {attributes}', 1)
            else:
                block = block.replace('</style:style>', f'<style:table-cell-properties {attributes}/></style:style>')
            additions.append(block)
            cache[key] = name
        cell = re.sub(r'\s+table:number-columns-repeated="\d+"', '', cell)
        return (STYLE.sub(f'table:style-name="{cache[key]}"', cell, count=1) if match else
                cell.replace('<table:table-cell', f'<table:table-cell table:style-name="{cache[key]}"', 1))

    positions = {row: index for index, row in enumerate(data)}
    replacements = []
    for i, row in enumerate(rows):
        is_header = i == header_index
        is_total = not ranking and 'Summe' in labels[i]
        if not is_header and not is_total and i not in groups:
            continue
        left = header.index('letzte Serie') if is_total else first
        end = last if ranking or is_total else max(last, max(j for j, label in enumerate(header) if label))
        color = groups.get(i, '#000000') if ranking else '#000000'
        position = positions.get(i, 0)
        top = is_header or is_total or (ranking and (position == 0 or groups[data[position - 1]] != color))
        bottom = is_header or is_total or (i in groups and (position == len(data) - 1 or
                 (ranking and groups[data[position + 1]] != color)))
        column = 0

        def replace(match):
            nonlocal column
            cell = match.group()
            repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
            count = int(repeat[1]) if repeat else 1
            start = column
            column += count
            if column <= left or start > end:
                return cell
            parts = []
            for j in range(start, min(column, end + 1)):
                if j < left:
                    parts.append(re.sub(r'\s+table:number-columns-repeated="\d+"', '', cell))
                    continue
                background = ('#00cc00' if is_header or j == header.index('Name') else '#ffffff') if ranking else (
                    COLORS.get(groups.get(i), '#ffffff') if j != place and not is_header and not is_total else '#ffffff')
                edges = [(side, f'{"0.088" if thick else "0.002"}cm solid {color}')
                         for side, thick in [('left', j == left), ('right', j == last),
                                             ('top', top), ('bottom', bottom)]] if j <= last else []
                parts.append(styled(cell, background, edges))
            if column > end + 1:
                parts.append(re.sub(r'table:number-columns-repeated="\d+"',
                                    f'table:number-columns-repeated="{column - end - 1}"', cell))
            return ''.join(parts)

        replacements.append((row.start(), row.end(), CELL.sub(replace, row.group())))
    body = table.group()
    for start, end, row in reversed(replacements):
        body = body[:start] + row + body[end:]
    content = content[:table.start()] + body + content[table.end():]
    return content.replace('</office:automatic-styles>', ''.join(additions) + '</office:automatic-styles>', 1)
