"""Führt die Schritte 1 bis 3 für einen Datenbankstand aus."""

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
P01 = P02 = P03 = SCRIPTS
sys.path.insert(0, str(SCRIPTS))
from ergaenze_setzliste import ods_rows


def run(script, *args):
    subprocess.run([sys.executable, str(script), *(str(arg) for arg in args)],
                   check=True, cwd=script.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmz', type=Path, help='VMZ-Datenbank')
    parser.add_argument('--jahr', required=True, help='Spieljahr, z. B. 2026')
    parser.add_argument('--rangliste', type=Path,
                        default=ROOT / 'Rangliste.ods')
    parser.add_argument('--setzliste', type=Path,
                        default=ROOT / 'Setzliste.ods')
    parser.add_argument('-o', '--output', type=Path, default=ROOT)
    args = parser.parse_args()
    args.vmz = args.vmz.resolve()
    args.rangliste = args.rangliste.resolve()
    args.setzliste = args.setzliste.resolve()
    args.output = args.output.resolve()

    run_dir = args.output
    generated = args.output / f'generated_{args.vmz.name}'
    temp = generated / 'temp'
    temp.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
    spieltag_export = temp / f'Spieltage{stamp}.ods'
    report = temp / f'Auswertung_{args.jahr}_{stamp}.txt'
    current_rangliste = generated / f'Rangliste_{args.jahr}_{stamp}.ods'
    vmz_prepared = generated / 'VM-Daten_vorbereitet.VMZ'

    run(P01 / 'erstelle_auswertung.py', args.vmz, '--year', args.jahr,
        '-o', report)
    run(P02 / 'aktualisiere_rangliste.py', report, args.rangliste,
        '-o', current_rangliste)
    run(P03 / 'export_spieltage_ods.py', args.vmz, '--jahr', args.jahr,
        '-o', spieltag_export)
    with tempfile.TemporaryDirectory(prefix='setzliste_ids_') as intermediate:
        setzliste_ids = Path(intermediate) / 'Setzliste_mit_IDs.ods'
        run(P03 / 'setze_spielernummern.py', args.vmz, args.setzliste, '-o', setzliste_ids)
        previous = setzliste_ids
        dates = sorted(
            (datetime.strptime(name, '%d.%m.%Y')
             for name in ods_rows(spieltag_export)
             if name == datetime.strptime(name, '%d.%m.%Y').strftime('%d.%m.%Y')))
        for day in dates:
            date_stamp = day.strftime('%Y_%m_%d')
            day_date = day.strftime('%d.%m.%Y')
            setzliste = temp / f'Setzliste_{date_stamp}_iteriert.ods'
            run(P03 / 'ergaenze_setzliste.py', current_rangliste, previous, spieltag_export,
                '--datum', day_date, '--ohne-sortierung', '-o', setzliste)
            previous = setzliste
        final_setzliste = generated / f'Setzliste_{dates[-1].strftime("%Y_%m_%d")}.ods'
        run(P03 / 'ergaenze_setzliste.py', '--finalisieren', previous,
            '--spieltage', spieltag_export, '-o', final_setzliste)
        setzliste = final_setzliste
    run(P03 / 'aktualisiere_vmz_gruppen.py', args.vmz, setzliste,
        '-o', vmz_prepared)
    print(f'Lauf abgeschlossen: {run_dir}')


if __name__ == '__main__':
    main()
