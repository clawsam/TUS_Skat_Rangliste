"""Prüft Gesamtschnitte für bestehende und neue Mitglieder/Gäste in der ODS."""

from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ergaenze_setzliste import N, ods_rows, update


def write_ods(path, title, rows):
    content = '<office:document-content ' + ' '.join(
        f'xmlns:{prefix}="{uri}"' for prefix, uri in N.items()) + '>'
    content += f'<office:body><office:spreadsheet><table:table table:name="{title}">'
    for row in rows:
        content += '<table:table-row>' + ''.join(
            f'<table:table-cell><text:p>{escape(str(value))}</text:p></table:table-cell>'
            for value in row) + '</table:table-row>'
    content += '</table:table></office:spreadsheet></office:body></office:document-content>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('content.xml', content)


def check():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        rank, seating, games, report, output = [root / name for name in
            ('rank.ods', 'seating.ods', 'games.ods', 'report.txt', 'output.ods')]
        write_ods(rank, 'Rangliste', [
            ['ID', 'Name', 'Schnitt', 'Gesamt'], ['1', 'Mitglied, A', '1000', '1005']])
        header = ['Platz', 'ID', 'Gruppe', 'Name', 'Abwesenheiten',
                  'Schnitt', 'letzte Serie', 'Tischpunkte']
        write_ods(seating, 'Tabelle1', [header + [''] * (135 - len(header))] + [
            [place, player_id, group, name, '0', '999', '', '0'] + [''] * 127
            for place, player_id, group, name in (
                (1, '1', 'Grün', 'A Mitglied'), (2, '101', 'Blau', 'B Gast'),
                (3, '2', 'Grau', 'C OhneSerien'))])
        write_ods(games, '01.10.2026', [[''] * 14] + [
            [player_id, name, '1000', '', '', '', '', '', '1', '1', '', '', '', '3']
            for player_id, name in [('1', 'Mitglied, A'), ('101', 'Gast, B'),
                                    ('102', 'NeuerGast, D'), ('103', 'Rundung, E')]])
        report.write_text(
            '1. 1 Mitglied, A 60 1.000,00 60000\n'
            '2. 101 Gast, B 30 1.000,00 30000\n'
            '3. 2 OhneSerien, C 0 0,00 0\n'
            '4. 102 NeuerGast, D 50 1.000,00 50000\n'
            '5. 103 Rundung, E 80 1.000,02 80002\n', encoding='utf-8')
        update(rank, seating, games, output, report=report)
        rows = ods_rows(output)['Tabelle1']
        actual = {row[1]: row[5].replace(' €', '') for row in rows[1:] if row[1]}
        assert actual == {'1': '1005,00', '101': '990,00', '2': '-25,00',
                          '102': '1000,00', '103': '1015,03'}, actual
        update(rank, seating, games, output)
        assert next(row[5] for row in ods_rows(output)['Tabelle1']
                    if row[1] == '1') == '1005 €'
    print('OK: Mitglieder, bestehende/neue Gäste, null Serien, Rundung und Ranglistenübernahme')


if __name__ == '__main__':
    check()
