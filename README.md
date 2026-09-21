# Skat-Setzliste

> **Hinweis:** Der Code und diese Dokumentation wurden mit Unterstützung
> künstlicher Intelligenz erstellt. Ergebnisse und Berechnungen sollten vor
> der Verwendung geprüft werden.

Dieses Projekt bereitet die Daten aus einer Vereinsmeister-Datenbank (`.VMZ`)
für die Rangliste und die nächste Setzliste auf. Der frühere, überwiegend
manuelle Ablauf wird dabei weitgehend durch Python-Skripte ersetzt.

## HOWTO – Kurzanleitung

1. Die neue Datei `VM-Daten_*.VMZ` in den Projektordner kopieren.
2. Das Startskript `START.ps1` ausführen.
3. Die Ergebnisse liegen im Ordner `generated_VM-Daten_*.VMZ`:
   aktualisierte Rangliste, Setzliste und VMZ mit den neuen Gruppenzuteilungen.

## Was die Anwendung erledigt

Der komplette Lauf besteht aus diesen Schritten:

1. Die Jahresergebnisse werden direkt aus der VMZ gelesen und als Auswertung
   zusammengefasst.
2. Serienzahlen, Punkte und Schnitte werden in eine neue Rangliste übernommen.
3. Alle Spieltage werden aus der VMZ exportiert.
4. Die Spielernummern werden mit der vorhandenen Setzliste abgeglichen.
5. Für die Spieltage werden die Tischgeldwerte in die Setzliste eingetragen.
6. Die Setzliste wird finalisiert und nach den vorgesehenen Gruppen sortiert.
7. Die Gruppen Grün, Gelb und Rot werden in eine neue, vorbereitete VMZ
   zurückgeschrieben.

Die Originaldateien werden nicht überschrieben. Ergebnisse landen in einem
VMZ-spezifischen Ordner, zum Beispiel `generated_VM-Daten_17092026.VMZ`.
Bei einem neuen Datenbankstand wird automatisch ein neuer Ausgabeordner
angelegt.

## Voraussetzungen

Im Projektordner müssen vorhanden sein:

- `python\python.exe` – die mitgelieferte portable Python-Version
- `Rangliste.ods` – Vorlage für die Rangliste
- `Setzliste.ods` – Vorlage für die Setzliste
- eine Eingabedatei mit dem Namen `VM-Daten_*.VMZ`

Die Skripte verwenden nur die Python-Standardbibliothek. Eine zusätzliche
Python-Installation oder externe Pakete sind für den normalen Lauf nicht nötig.

## Normaler Ablauf

### 1. Datenbank ablegen

Die neue VMZ-Datei in den Projektordner kopieren, zum Beispiel:

```text
VM-Daten_21092026.VMZ
```

Das Startskript nimmt automatisch die VMZ-Datei mit dem neuesten Datum im
Dateinamen. Erwartet wird das Format `VM-Daten_TTMMJJJJ.VMZ`, zum Beispiel
`VM-Daten_21092026.VMZ`. Die Änderungszeit der Datei wird dabei nicht verwendet.

### 2. Lauf starten

PowerShell im Projektordner öffnen und ausführen:

```powershell
.\START.ps1
```

Alternativ kann der zentrale Runner direkt gestartet werden:

```powershell
.\python\python.exe .\scripts\run_alle_schritte.py `
  .\VM-Daten_21092026.VMZ `
  --jahr 2026 `
  --rangliste .\Rangliste.ods `
  --setzliste .\Setzliste.ods `
  -o .
```

### 3. Ergebnisse prüfen

Nach dem Lauf liegen die Dateien hier:

```text
generated_VM-Daten_21092026.VMZ\
├── temp\                 alle Zwischenstände und temporären Dateien
├── Rangliste_*.ods       fertige Rangliste
├── Setzliste_*.ods       fertige Setzliste
└── VM-Daten_vorbereitet.VMZ
```

Die fertige Rangliste und Setzliste liegen direkt im jeweiligen
`generated_VM-Daten_*.VMZ`-Ordner. Die Datei
`VM-Daten_vorbereitet.VMZ` ist die Datenbankkopie mit den aktualisierten
Gruppen. Erst diese Datei weitergeben oder im Vereinsmeister verwenden.

## Was weiterhin manuell geprüft wird

Der automatische Lauf berechnet und überträgt die bekannten Daten. Fachliche
Ausnahmen müssen vor der Weitergabe kontrolliert werden:

- neue Mitglieder und Gäste aufnehmen;
- Namen und Spielernummern bei neuen oder geänderten Personen prüfen;
- nicht eindeutig zuordenbare Namen aus der Konsolenausgabe klären;
- Zusatzlisten und deren Einfluss auf Aktivität beziehungsweise Inaktivität
  prüfen;
- Abwesenheiten, Sterne sowie graue und blaue Liste kontrollieren;
- die Einteilung in Grün, Gelb und Rot fachlich prüfen;
- Tischgeldsummen und auffällige oder fehlende Tischpunkte prüfen;
- Farben, Zellformatierung und schwarze Rahmen in der finalen ODS prüfen;
- die vorbereitete VMZ öffnen, Gruppenänderungen kontrollieren und danach
  exportieren beziehungsweise per Mail zurücksenden.

Blau und Grau werden beim Zurückschreiben in die VMZ bewusst nicht verändert.
Nur Grün, Gelb und Rot werden als Gruppen in `Spieler.dbf` aktualisiert.

## Die wichtigsten Berechnungen

Die Jahresauswertung zählt pro Spieler die Ergebnisse des gewählten Jahres und
summiert die Werte aus `VM.dbf`.

Die Rangliste enthält unter anderem:

- Anzahl der gespielten Serien;
- Summe der Punkte;
- Spielschnitt;
- Bonus und Gesamtschnitt.

Die Setzliste übernimmt zusätzlich die letzte Serie und die Tischgeldwerte aus
den Spieltagsdaten. Für Vierer- und Dreiertische gelten die im Projekt
hinterlegten Tischgeldregeln.

## Der frühere händische Prozess

Vor der Automatisierung lief die Bearbeitung ungefähr so ab:

1. Die Datenbank wurde per Mail empfangen.
2. Die Daten wurden importiert; anschließend musste etwa 20 Minuten gewartet
   werden.
3. Die Daten wurden als PDF exportiert.
4. Die Zahlen in ungefähr 60 Ranglisten wurden einzeln aktualisiert.
5. Die Formel für die TUS-Schnitte wurde angewendet.
6. Die berechneten Schnitte wurden einzeln in die Setzliste kopiert.
7. Etwa 40 bis 60 Setzlisten wurden einzeln geöffnet. Für jeden
   Tischteilnehmer wurden 0 bis 2 Euro eingetragen.
8. Aktive und inaktive Teilnehmer wurden gezählt und manuell in die graue oder
   farbige Liste verschoben.
9. Die neue Grün-/Gelb-/Rot-Liste wurde berechnet und die Teilnehmer wurden
   einsortiert.
10. Innerhalb der Farben wurde nochmals separat sortiert.
11. Für jede geänderte Gruppe wurde die Gruppe im Vereinsmeister manuell neu
    gesetzt.
12. Die Datenbank wurde erneut exportiert und per Mail zurückgeschickt.
13. Zusätzlich wurde die Excel-/ODS-Tabelle farbig markiert und schwarz
    umrandet.

Zusätzlich mussten neue Mitglieder und Gäste, Teilnehmernummern, Zusatzlisten,
Inaktivität und die Summen der Tischgeldbeträge manuell gepflegt werden.

## Einzelne Skripte

Die Einzelprogramme können bei Fehlern oder Sonderfällen separat verwendet
werden:

| Skript | Aufgabe |
| --- | --- |
| `erstelle_auswertung.py` | Jahresauswertung aus VMZ erzeugen |
| `aktualisiere_rangliste.py` | Ranglistenwerte aktualisieren |
| `export_spieltage_ods.py` | Spieltage für die Setzliste exportieren |
| `setze_spielernummern.py` | Datenbanknummern in die Setzliste übernehmen |
| `ergaenze_setzliste.py` | Spieltage und Tischgeld ergänzen |
| `aktualisiere_vmz_gruppen.py` | Grün/Gelb/Rot in eine neue VMZ schreiben |
| `add_gastspieler.py` | Einen Gast in eine Setzliste aufnehmen |
| `pruefe_beispiele.py` | Vorhandene Beispielstände prüfen |

## Sicherheit und Dateien

Eingaben wie VMZ, Rangliste und Setzliste werden nicht überschrieben. Jeder
Lauf erhält einen Zeitstempel und erzeugt eigene Dateien. Vor dem Rückimport in
den Vereinsmeister sollte immer die erzeugte Setzliste sowie die vorbereitete
VMZ geprüft und eine Sicherung des bisherigen Datenstands behalten werden.
