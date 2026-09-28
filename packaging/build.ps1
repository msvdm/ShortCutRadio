# Build ShortCutRadio for Windows, from this checkout, on this machine.
#
#     powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Makes, in dist\:
#   ShortCutRadio\                              the built app (a folder)
#   ShortCutRadio-<ver>-windows-x64.zip         that folder, portable: settings
#                                               live in data\ beside the app
#   ShortCutRadio-<ver>-windows-x64-setup.exe   the same app, installed with a
#                                               Start menu entry and uninstaller
#
# Needs, besides .venv (pip install -r requirements.txt):
#   libmpv-2.dll in the checkout's root. Windows has no system libmpv, so the
#     build bundles this one: take it from the mpv-dev-x86_64-*.7z archive of
#     https://github.com/shinchiro/mpv-winbuild-cmake/releases. It is
#     gitignored; see packaging\THIRD_PARTY-windows.txt for its licence.
#   Inno Setup 6 (https://jrsoftware.org/isinfo.php) for the installer.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Run {
    param([string]$Exe, [Parameter(ValueFromRemainingArguments)][string[]]$Rest)
    & $Exe @Rest
    if ($LASTEXITCODE) { throw "failed ($LASTEXITCODE): $Exe $Rest" }
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Version = (& $Py -c "from src import __version__; print(__version__)").Trim()
Write-Host "== ShortCutRadio $Version"
if (-not (Test-Path libmpv-2.dll)) {
    throw "libmpv-2.dll is missing from $Root -- see the top of this script"
}
$Iscc = Get-Command iscc -ErrorAction SilentlyContinue
$Iscc = if ($Iscc) { $Iscc.Source } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 is not installed (no $Iscc)" }

# The builder is pinned so that two builds of one commit are the same build.
Run $Py -m pip install -q "pyinstaller==6.22.3"

Write-Host "== tests"
$env:QT_QPA_PLATFORM = "offscreen"
try { Run $Py -m pytest -q tests } finally { Remove-Item Env:QT_QPA_PLATFORM }

Write-Host "== build"
Run $Py -m PyInstaller --noconfirm --clean shortcutradio-windows.spec

# Not dead on arrival: the bundle starts its interpreter and knows its version.
# (Piped, so PowerShell waits for a GUI-subsystem exe and reads what it says.)
$Out = (& dist\ShortCutRadio\shortcutradio.exe --version | Out-String).Trim()
if ($Out -ne "ShortCutRadio $Version") {
    throw "expected 'ShortCutRadio $Version', the build says '$Out'"
}
Write-Host "build says: $Out"

Write-Host "== portable zip"
$Name = "ShortCutRadio-$Version"
$Stage = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid())
New-Item -ItemType Directory $Stage | Out-Null
$Zip = "dist\$Name-windows-x64.zip"
try {
    Copy-Item -Recurse dist\ShortCutRadio "$Stage\$Name"
    Copy-Item README.md, LICENSE "$Stage\$Name\"
    Copy-Item packaging\THIRD_PARTY-windows.txt "$Stage\$Name\THIRD_PARTY.txt"
    # Settings stay in the folder (core/config.py:data_dir).
    New-Item -ItemType File "$Stage\$Name\shortcutradio.portable" | Out-Null
    if (Test-Path $Zip) { Remove-Item $Zip }
    Compress-Archive -Path "$Stage\$Name" -DestinationPath $Zip
} finally {
    Remove-Item -Recurse -Force $Stage
}
Write-Host "built $Zip"

Write-Host "== installer"
Run $Iscc /Q "/DAppVersion=$Version" packaging\shortcutradio.iss
$Setup = "dist\$Name-windows-x64-setup.exe"
Write-Host "built $Setup"

Write-Host ""
Get-Item $Zip, $Setup | Format-Table Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
