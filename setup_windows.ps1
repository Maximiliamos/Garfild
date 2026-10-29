# Installs Garfield into a project-local virtual environment on Windows.
# Run from PowerShell: powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
param(
    [switch]$InstallWhisper,
    [switch]$InstallBrowser,
    [switch]$InstallUIAutomation
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = $null
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    & py -3.11 -c "import sys; print(sys.version)"
    if ($LASTEXITCODE -eq 0) { $python = @("py", "-3.11") }
}
if (-not $python) {
    $direct = Get-Command python -ErrorAction SilentlyContinue
    if ($direct) { $python = @("python") }
}
if (-not $python) {
    throw "Python 3.11 or another compatible Python was not found. Install Python 3.11."
}

Write-Host "Creating local virtual environment..."
if ($python.Count -eq 2) {
    & $python[0] $python[1] -m venv .venv
} else {
    & $python[0] -m venv .venv
}
$exe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

if ($InstallWhisper) {
    & $exe -m pip install faster-whisper
    if ($LASTEXITCODE -ne 0) { throw "Whisper installation failed" }
}
if ($InstallBrowser) {
    & $exe -m pip install playwright
    if ($LASTEXITCODE -ne 0) { throw "Playwright install failed" }
    & $exe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Chromium install failed" }
}
if ($InstallUIAutomation) {
    & $exe -m pip install pywinauto
    if ($LASTEXITCODE -ne 0) { throw "UI Automation install failed" }
}

Write-Host "Running automated checks..."
& $exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Garfield was not started." }

Write-Host "Installation completed. Run Start_Garfild.bat."
Write-Host "Remember to install a Vosk or Whisper recognition model and configure Piper audio if needed."
