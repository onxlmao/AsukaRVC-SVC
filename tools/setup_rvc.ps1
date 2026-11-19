# AsukaRVC-SVC — one-time RVC environment setup
# Creates .venv-rvc (Python 3.12 + PyTorch + RVC deps) and downloads pretrained models.
#
#   powershell -ExecutionPolicy Bypass -File tools\setup_rvc.ps1
#
param(
    [switch]$SkipAssets,
    [switch]$SkipTorch
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "  AsukaRVC-SVC - RVC setup" -ForegroundColor Magenta
Write-Host "  -------------------" -ForegroundColor DarkGray
Write-Host "  project: $root"
Write-Host ""

# ---------------------------------------------------------------- locate uv
$uvExe = $null
$pyHost = $null
$cmd = Get-Command uv -ErrorAction SilentlyContinue
if ($cmd) { $uvExe = $cmd.Source }
if (-not $uvExe) {
    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    $local = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Python") -Filter "uv.exe" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($local) { $candidates += $local.FullName }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { $uvExe = $c; break }
    }
}
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd) { $pyHost = $pyCmd.Source }

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)] $UvArgs)
    if ($script:uvExe) {
        & $script:uvExe @UvArgs
    } elseif ($script:pyHost) {
        & $script:pyHost -m uv @UvArgs
    } else {
        throw "uv was not found. Install it from https://docs.astral.sh/uv/ and re-run."
    }
    if ($LASTEXITCODE -ne 0) { throw "uv command failed (exit $LASTEXITCODE)" }
}

if (-not $uvExe -and $pyHost) {
    & $pyHost -m uv --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing uv with pip..." -ForegroundColor Yellow
        & $pyHost -m pip install --user uv
    }
}

try {
    $ver = Invoke-Uv --version
    Write-Host "uv: $ver" -ForegroundColor DarkGray
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- Python 3.12
$py312 = Get-ChildItem (Join-Path $root ".python") -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "cpython-3\.12" } |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $py312) {
    Write-Host "`n[1/4] Installing Python 3.12..." -ForegroundColor Cyan
    Invoke-Uv python install 3.12 --install-dir (Join-Path $root ".python")
    $py312 = Get-ChildItem (Join-Path $root ".python") -Recurse -Filter "python.exe" |
        Where-Object { $_.FullName -match "cpython-3\.12" } |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $py312) { throw "Python 3.12 installation failed." }
Write-Host "python: $py312" -ForegroundColor DarkGray

# ---------------------------------------------------------------- venv
$venv = Join-Path $root ".venv-rvc"
$venvPy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "`n[2/4] Creating .venv-rvc..." -ForegroundColor Cyan
    Invoke-Uv venv $venv --python $py312
} else {
    Write-Host "`n[2/4] .venv-rvc already exists" -ForegroundColor Cyan
}

# ---------------------------------------------------------------- packages
Write-Host "`n[3/4] Installing PyTorch + RVC dependencies (this can take a few minutes)..." -ForegroundColor Cyan
Invoke-Uv pip install --python $venvPy -r (Join-Path $root "requirements-rvc.txt")

if (-not $SkipTorch) {
    & $venvPy -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
}

# ---------------------------------------------------------------- assets
if (-not $SkipAssets) {
    Write-Host "`n[4/4] Downloading ContentVec, RMVPE, FCPE and the CMU dictionary (~600 MB)..." -ForegroundColor Cyan
    & $venvPy (Join-Path $root "tools\download_assets.py")
} else {
    Write-Host "`n[4/4] Skipped asset download (-SkipAssets)" -ForegroundColor Yellow
}

# clear the cached probe so the app re-checks
$statusFile = Join-Path $root "data\rvc_status.json"
if (Test-Path $statusFile) { Remove-Item $statusFile -Force }

Write-Host ""
Write-Host "  RVC environment ready." -ForegroundColor Green
Write-Host "  Put voicebanks in models\ (or upload them in the UI), then start the app:"
Write-Host "    .\start.bat" -ForegroundColor White
Write-Host ""
