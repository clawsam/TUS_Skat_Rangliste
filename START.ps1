$ErrorActionPreference = 'Stop'

$project = $PSScriptRoot
$python = Join-Path $project 'python\python.exe'
$runner = Join-Path $project 'scripts\run_alle_schritte.py'
$rangliste = Join-Path $project 'Rangliste.ods'
$setzliste = Join-Path $project 'Setzliste.ods'
if (-not (Test-Path -LiteralPath $python)) { throw "Portable Python fehlt: $python" }
if (-not (Test-Path -LiteralPath $rangliste)) { throw "Rangliste fehlt: $rangliste" }
if (-not (Test-Path -LiteralPath $setzliste)) { throw "Setzliste fehlt: $setzliste" }
$vmz = Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'VM-Daten_*.VMZ' |
    ForEach-Object {
        $match = [regex]::Match($_.BaseName, '^VM-Daten_(?<date>\d{8})$')
        if ($match.Success) {
            try {
                [pscustomobject]@{
                    File = $_
                    Date = [datetime]::ParseExact($match.Groups['date'].Value, 'ddMMyyyy', $null)
                }
            } catch { }
        }
    } |
    Sort-Object Date -Descending |
    Select-Object -First 1 |
    ForEach-Object File
if (-not $vmz) { throw 'Keine VMZ-Datei mit Datum im Namen gefunden.' }
$year = [regex]::Match($vmz.Name, '20\d{2}').Value

& $python $runner `
    $vmz.FullName `
    --jahr $year `
    --rangliste $rangliste `
    --setzliste $setzliste `
    -o $project

if ($LASTEXITCODE) { throw "Lauf fehlgeschlagen (Exitcode $LASTEXITCODE)." }
Write-Host 'Fertig.' -ForegroundColor Green
