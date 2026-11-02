# Optional unsigned Windows preview package. Runs only when explicitly invoked.
# Requires Windows Python venv already created by setup_windows.ps1.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "First run setup_windows.ps1 to install dependencies." }

& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed; build cancelled." }

& $python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed --name Garfield --collect-all customtkinter --paths $PSScriptRoot --hidden-import garfield_agent.vision --hidden-import garfield_agent.mcp_client --hidden-import garfield_agent.updates --hidden-import garfield_dashboard.workflow_builder garfield_flagship_gui.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

Write-Host "Portable bundle: dist\Garfield\Garfield.exe"
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($iscc) {
    & $iscc.Source "installer\Garfield.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
    Write-Host "Unsigned installer: dist\installers\Garfield-Setup-preview.exe"
} else {
    Write-Host "Inno Setup not installed. Portable build is ready, no installer compiled."
}
Write-Host "WARNING: this build is unsigned, contains no speech models and requires Windows hardware smoke tests."
