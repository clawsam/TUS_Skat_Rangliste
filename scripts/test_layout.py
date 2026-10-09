"""Ausführen: python/python.exe scripts/test_layout.py"""

from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ergaenze_setzliste import cells, formula_cell, replace_at, update_cell
from formatiere_listen import COLORS, ROW, format_layout

ROOT = Path(__file__).resolve().parent.parent
N = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
     's': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
     'f': 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0'}


def inspect(content):
    root = ET.fromstring(content)
    styles = {s.get(f'{{{N["s"]}}}name'): s for s in root.findall('.//s:style', N)}
    rows, properties = [], []
    for row in root.findall('.//t:table-row', N):
        values, formats = [], []
        for cell in row.findall('t:table-cell', N):
            count = int(cell.get(f'{{{N["t"]}}}number-columns-repeated', '1'))
            attrs = {k: v for k, v in cell.attrib.items()
                     if k not in (f'{{{N["t"]}}}style-name', f'{{{N["t"]}}}number-columns-repeated')}
            values.extend([(attrs, ''.join(cell.itertext()))] * count)
            style = styles.get(cell.get(f'{{{N["t"]}}}style-name'))
            props = style.find('s:table-cell-properties', N) if style is not None else None
            formats.extend([props.attrib if props is not None else {}] * count)
        rows.append(values)
        properties.append(formats)
    return rows, properties


def check(ranking):
    with zipfile.ZipFile(ROOT / ('Rangliste.ods' if ranking else 'Setzliste.ods')) as archive:
        content = archive.read('content.xml').decode()
    matches = list(ROW.finditer(content))
    header = matches[0].group()
    rows = [header]
    # Absichtlich alte obere/untere Rahmen in wechselnden Zeilen verwenden.
    for index, group in enumerate(COLORS, 1):
        row = matches[min(index, len(matches) - 1)].group()
        for column, value in ([(1, str(index)), (3, '40' if index < 3 else '39')]
                              if ranking else [(0, str(index)), (2, group)]):
            row = replace_at(row, column, update_cell(cells(row)[column], value))
        column = 12 if ranking else 7
        row = replace_at(row, column, formula_cell(cells(row)[column], 'of:=SUM([.A1:.A2])', '3,00'))
        rows.append(row)
    if not ranking:
        total = header
        total = replace_at(total, 0, update_cell(cells(total)[0], ''))
        total = replace_at(total, 6, update_cell(cells(total)[6], 'Summe'))
        rows.append(total)
    content = content[:matches[0].start()] + ''.join(rows) + content[matches[-1].end():]
    expected, _ = inspect(content)
    for _ in range(2):
        content = format_layout(content, ranking=ranking)
        actual, styles = inspect(content)
        assert actual == expected, 'Werte, Formeln oder Spaltenzahl verändert'
        attr = lambda row, col, name: styles[row][col][f'{{{N["f"]}}}{name}']
        first, last = (1, 12) if ranking else (0, 7)
        for row in range(1, 6):
            color = '#ff3333' if ranking and row >= 3 else '#000000'
            assert attr(row, first, 'border-left') == f'0.088cm solid {color}'
            assert attr(row, last, 'border-right') == f'0.088cm solid {color}'
            assert attr(row, first + 1, 'border-left') == f'0.002cm solid {color}'
            assert attr(row, first, 'background-color') == '#ffffff'
            assert attr(row, first + 1, 'background-color') == (
                '#00cc00' if ranking else list(COLORS.values())[row - 1])
        assert attr(5, last, 'border-bottom').startswith('0.088cm')
        assert attr(1, last, 'border-bottom').startswith('0.002cm')
        if ranking:
            assert attr(2, last, 'border-bottom') == '0.088cm solid #000000'
            assert attr(3, last, 'border-top') == '0.088cm solid #ff3333'
        else:
            assert attr(6, 6, 'border-left') == '0.088cm solid #000000'
            assert attr(6, 7, 'background-color') == '#ffffff'


if __name__ == '__main__':
    check(True)
    check(False)
    print('Layout geprüft: Farben, Rahmen, Wiederholung und unveränderte Zellinhalte.')
