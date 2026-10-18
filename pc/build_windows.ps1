$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv-audio\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Créez .venv-audio avec python -m venv .venv-audio avant de compiler.'
}
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-desktop.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installation des dépendances échouée.' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name SmartCon --collect-all av --collect-all sounddevice --hidden-import pystray._win32 --distpath (Join-Path $projectRoot 'dist\SmartCon') --workpath (Join-Path $projectRoot 'build_desktop') --specpath (Join-Path $projectRoot 'build_desktop') (Join-Path $PSScriptRoot 'tray_app.py')
if ($LASTEXITCODE -ne 0) { throw 'Compilation échouée.' }
Write-Host "Exécutable prêt : $projectRoot\dist\SmartCon\SmartCon.exe"
