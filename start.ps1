# AsukaRVC-SVC launcher
# Uses .venv-rvc when available. Prefers the Gradio-hosted fullstack app
# (app/gradio_app.py) and falls back to the stdlib server (app/server.py).
param([Parameter(ValueFromRemainingArguments = $true)] $ServerArgs)

$root = $PSScriptRoot
$venvPy = Join-Path $root ".venv-rvc\Scripts\python.exe"

if (Test-Path $venvPy) {
    $py = $venvPy
} else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Host "Python not found. Install Python 3.11+ or run setup_rvc.bat" -ForegroundColor Red
        exit 1
    }
    $py = $cmd.Source
}

$gradioApp = Join-Path $root "app\gradio_app.py"
$stdlibApp = Join-Path $root "app\server.py"

$hasGradio = $false
try {
    & $py -c "import gradio" 2>$null
    $hasGradio = ($LASTEXITCODE -eq 0)
} catch {
    $hasGradio = $false
}

if ($hasGradio -and (Test-Path $gradioApp)) {
    $entry = $gradioApp
    $label = "Gradio host"
} else {
    $entry = $stdlibApp
    $label = "stdlib server"
}

Write-Host "Starting AsukaRVC-SVC ($label) with $py" -ForegroundColor DarkGray
if (-not $hasGradio) {
    Write-Host "  Gradio not installed - run setup_rvc.bat for the full experience." -ForegroundColor DarkYellow
}

& $py $entry @ServerArgs
