<#
.SYNOPSIS
  Deploy course_schedule plugin into N.E.K.O dev environment (Windows PowerShell 5.1+)

.DESCRIPTION
  1. Probe uv / git prerequisites
  2. Auto-detect or ask for N.E.K.O source path
  3. Clone or update the plugin from GitHub
  4. Mount into N.E.K.O plugin/plugins/course_schedule via robocopy
  5. Run uv sync + neko-plugin check --release

.USAGE
  powershell -ExecutionPolicy Bypass -File .\deploy.ps1
#>

[CmdletBinding()]
param(
    [string]$NekoSrc = "",
    [string]$PluginRepo = "https://github.com/lingtongxinyv/n.e.k.o_plugin_course_schedule_plugin.git",
    [string]$PluginId = "course_schedule",
    [string]$WorkRoot = "$env:TEMP\neko-plugin-deploy",
    [switch]$SkipSync,
    [switch]$SkipCheck,
    [switch]$CleanClone
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)  { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg){ Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg){ Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Test-Cmd([string]$name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# ── Step 0: prerequisites ──
Write-Step "Step 0/5 - check prerequisites"

$missing = @()
foreach ($c in @("git", "uv")) {
    if (Test-Cmd $c) {
        Write-Ok "$c : $((Get-Command $c).Source)"
    } else {
        Write-Fail "$c not found on PATH"
        $missing += $c
    }
}
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "Install links:" -ForegroundColor Red
    Write-Host "  uv : https://docs.astral.sh/uv/getting-started/installation/"
    Write-Host "  git: https://git-scm.com/download/win"
    exit 1
}

# ── Step 1: locate N.E.K.O source ──
Write-Step "Step 1/5 - locate N.E.K.O source"

if (-not $NekoSrc) {
    $candidates = @(
        "$env:USERPROFILE\Documents\N.E.K.O-src",
        "$env:USERPROFILE\N.E.K.O-src",
        "$env:USERPROFILE\code\N.E.K.O-src",
        "$env:USERPROFILE\source\repos\N.E.K.O-src",
        "C:\N.E.K.O-src"
    ) | Where-Object { Test-Path (Join-Path $_ "pyproject.toml") }

    if ($candidates.Count -gt 0) {
        $NekoSrc = $candidates[0]
        Write-Ok "auto-detected: $NekoSrc"
    } else {
        Write-Warn "could not auto-detect N.E.K.O source"
        $NekoSrc = Read-Host "Enter N.E.K.O source root (the folder with pyproject.toml)"
    }
}

$NekoSrc = $NekoSrc.Trim('"', "'")
if (-not (Test-Path (Join-Path $NekoSrc "pyproject.toml"))) {
    Write-Fail "invalid path: $NekoSrc (pyproject.toml not found)"
    exit 1
}
$PluginMount = Join-Path $NekoSrc "plugin\plugins\$PluginId"
Write-Ok "N.E.K.O src   : $NekoSrc"
Write-Ok "mount target  : $PluginMount"

# ── Step 2: get plugin source ──
Write-Step "Step 2/5 - get plugin source from GitHub"

New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
$pluginDir = Join-Path $WorkRoot $PluginId

$gitOk = $true
if ((Test-Path $pluginDir) -and -not $CleanClone) {
    Write-Host "    existing dir found, running git pull..." -ForegroundColor DarkGray
    Push-Location $pluginDir
    $gitOut = git pull --ff-only 2>&1
    $gitCode = $LASTEXITCODE
    Pop-Location
    $gitOut | ForEach-Object { Write-Host "    $_" }
    if ($gitCode -ne 0) {
        Write-Warn "pull failed, will delete and re-clone"
        Remove-Item -Recurse -Force $pluginDir
        $gitOut = git clone $PluginRepo $pluginDir 2>&1
        $gitCode = $LASTEXITCODE
        $gitOut | ForEach-Object { Write-Host "    $_" }
        if ($gitCode -ne 0) { $gitOk = $false }
    }
} else {
    if (Test-Path $pluginDir) { Remove-Item -Recurse -Force $pluginDir }
    $gitOut = git clone $PluginRepo $pluginDir 2>&1
    $gitCode = $LASTEXITCODE
    $gitOut | ForEach-Object { Write-Host "    $_" }
    if ($gitCode -ne 0) { $gitOk = $false }
}
if (-not $gitOk) { Write-Fail "clone/pull failed"; exit 1 }
Write-Ok "plugin source ready: $pluginDir"

# ── Step 3: mount into N.E.K.O tree ──
Write-Step "Step 3/5 - mount plugin into N.E.K.O"

New-Item -ItemType Directory -Force -Path (Split-Path $PluginMount) | Out-Null

robocopy $pluginDir $PluginMount /MIR `
    /XD .git .github __pycache__ .pytest_cache .ruff_cache node_modules .venv `
    /XF *.pyc *.pyo *.log sync.ps1 `
    /NFL /NDL /NJH /NJS /NP 2>&1 | Out-Null
$code = $LASTEXITCODE
if ($code -gt 7) {
    Write-Fail "robocopy failed (exit $code)"
    exit 1
}
Write-Ok "mounted -> $PluginMount"

# ── Step 4: uv sync ──
if (-not $SkipSync) {
    Write-Step "Step 4/5 - uv sync plugin dependencies"
    Push-Location $NekoSrc
    try {
        $syncArgs = @("run", "--with", "pip", "python", "-m",
                      "plugin.neko_plugin_cli.cli", "sync", $PluginId, "--clean")
        Write-Host "    uv $($syncArgs -join ' ')" -ForegroundColor DarkGray
        & uv @syncArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "sync returned non-zero, continuing..."
        } else {
            Write-Ok "deps synced"
        }
    } finally { Pop-Location }
} else {
    Write-Step "Step 4/5 - skipped (-SkipSync)"
}

# ── Step 5: release check ──
if (-not $SkipCheck) {
    Write-Step "Step 5/5 - neko-plugin check --release"
    Push-Location $NekoSrc
    try {
        $checkArgs = @("run", "python", "-m",
                       "plugin.neko_plugin_cli.cli", "check", $PluginId, "--release")
        Write-Host "    uv $($checkArgs -join ' ')" -ForegroundColor DarkGray
        & uv @checkArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "release check FAILED - see output above"
            exit 1
        }
        Write-Ok "release check PASSED"
    } finally { Pop-Location }
} else {
    Write-Step "Step 5/5 - skipped (-SkipCheck)"
}

# ── Done ──
Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  Plugin deployed successfully!" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Mounted at : $PluginMount"
Write-Host "Quick verify:"
Write-Host "  cd `"$NekoSrc`""
Write-Host "  uv run python -m plugin.neko_plugin_cli.cli check $PluginId --release"
Write-Host ""
Write-Host "Start N.E.K.O, open Dashboard -> Course Schedule panel."
Write-Host ""
