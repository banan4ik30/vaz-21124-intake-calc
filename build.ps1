# Сборка одиночного exe: .\build.ps1  ->  dist\VAZ21124-IntakeCalc.exe
Set-Location $PSScriptRoot
function Run([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "Ошибка: $exe $argv (код $LASTEXITCODE)" }
}
if (-not (Test-Path .venv)) { Run python @('-m', 'venv', '.venv') }
$py = '.\.venv\Scripts\python.exe'
Run $py @('-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', 'requirements-dev.txt')
if (-not (Test-Path icon.ico)) { Run $py @('make_icon.py') }
Run $py @('-m', 'pytest', '-q')
Run $py @('-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--log-level', 'WARN',
          '--name', 'VAZ21124-IntakeCalc', '--icon', 'icon.ico', '--add-data', 'ui;ui', 'app.py')
Write-Host "Готово: dist\VAZ21124-IntakeCalc.exe"