"""Prüft die Mitgliedergrenze 99/100 einschließlich alter Ranglistenzeilen."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aktualisiere_rangliste import ROW_RE, replace_cells, set_number, update_ods
from ergaenze_setzliste import assign_groups, cell_text, cells, ods_rows
from erstelle_auswertung import create_report
from setze_spielernummern import player_numbers


def check():
    header = ['ID', 'Gruppe', 'Abwesenheit', 'Schnitt']
    row = lambda values: '<table:table-row>' + ''.join(
        f'<table:table-cell><text:p>{value}</text:p></table:table-cell>'
        for value in values) + '</table:table-row>'
    result = assign_groups([row(header), row(['99', 'Rot', '0', '500']),
                            row(['100', 'Grün', '0', '900'])], header)
    assert cell_text(cells(result[1])[1]).startswith('Grün')
    assert cell_text(cells(result[2])[1]) == 'Blau'
    with TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / 'input.VMZ'
        with zipfile.ZipFile(database, 'w') as archive:
            archive.writestr('Spieler.dbf', b'')
        fields = [('NR',), ('NAME1',)]
        records = [['1', '0', '99', 'Mitglied'], ['2', '0', '100', 'Gast']]
        with patch('setze_spielernummern.dbf', return_value=(fields, records)):
            numbers, roster = player_numbers(database)
        assert set(numbers.values()) == {'99', '100'} and set(roster) == {'99'}
        report = root / 'report.txt'
        players = [{'NR': '99', 'NAME1': 'Mitglied'}, {'NR': '100', 'NAME1': 'Gast'}]
        games = [{'NR': '99', 'SPIELTAG': '20261001', 'WERT': '500'}]
        with patch('erstelle_auswertung.rows', side_effect=[games, players]):
            assert create_report(database, report, '2026') == (1, 1)
        report.write_text('1. 99 Mitglied 40 500,00 20000\n2. 100 Gast 50 900,00 45000\n', encoding='utf-8')
        template = Path(__file__).resolve().parent.parent / 'Rangliste.ods'
        source, output = root / 'source.ods', root / 'output.ods'
        with zipfile.ZipFile(template) as archive, zipfile.ZipFile(source, 'w') as result:
            content = archive.read('content.xml').decode()
            matches = list(ROW_RE.finditer(content))
            old = replace_cells(matches[1].group(), {13: lambda cell: set_number(cell, 100, '100')})
            content = content[:matches[1].start()] + old + content[matches[1].end():]
            for entry in archive.infolist():
                result.writestr(entry, content.encode() if entry.filename == 'content.xml' else archive.read(entry))
        update_ods(source, output, report)
        rows = next(iter(ods_rows(output).values()))
        assert [r[13] for r in rows[1:] if len(r) > 13 and r[1].isdigit()] == ['99']
    print('OK: Mitglied 99, Gast 100, Aufnahme ohne Serien und alte Ranglistenzeilen.')


if __name__ == '__main__':
    check()
