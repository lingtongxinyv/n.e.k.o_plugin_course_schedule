<#
.SYNOPSIS
  部署 course_schedule 插件：同步代码到已安装目录 + 提交推送 git。

.DESCRIPTION
  1. robocopy /E 增量同步开发目录到 N.E.K.O 已安装插件目录（保留运行时 data/config）。
  2. 检查 git 工作区，有变更则 git add -A + commit + push。

.PARAMETER Message
  自定义 commit message。不指定则用 "deploy: 同步代码 <时间戳>"。

.PARAMETER DryRun
  预览将执行的操作，不实际执行。

.PARAMETER SkipSync
  跳过同步，只做 git 提交推送。

.PARAMETER SkipGit
  跳过 git 提交推送，只做同步。

.EXAMPLE
  .\deploy.ps1
  .\deploy.ps1 -Message "fix: 修复课表解析"
  .\deploy.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Message,
    [switch]$DryRun,
    [switch]$SkipSync,
    [switch]$SkipGit
)

$ErrorActionPreference = 'Stop'

# ── 配置（按本机实际路径）──
$DevDir     = 'c:\Users\16650\Desktop\course schedule plugin'
$InstallDir = 'c:\Users\16650\AppData\Local\N.E.K.O\plugins\course_schedule'
$ExcludeDirs = @('.git', '__pycache__', '.pytest_cache', '.ruff_cache', '.venv', '.vscode')

function Write-Step($m) { Write-Host "[deploy] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[deploy] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[deploy] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[deploy] $m" -ForegroundColor Red }

# ── 1. 同步代码到已安装插件目录 ──
if (-not $SkipSync) {
    Write-Step "同步: $DevDir -> $InstallDir"
    if (-not (Test-Path $InstallDir)) {
        Write-Err "已安装插件目录不存在: $InstallDir"
        exit 1
    }
    if ($DryRun) {
        Write-Warn "DRY-RUN: 跳过 robocopy"
    } else {
        $rcArgs = @($DevDir, $InstallDir, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NP')
        foreach ($d in $ExcludeDirs) { $rcArgs += @('/XD', $d) }
        & robocopy @rcArgs
        if ($LASTEXITCODE -ge 8) {
            Write-Err "robocopy 失败 (退出码 $LASTEXITCODE)"
            exit 1
        }
        Write-Ok "同步完成 (robocopy 退出码 $LASTEXITCODE)"
    }
}

# ── 2. Git 提交推送 ──
if (-not $SkipGit) {
    Push-Location $DevDir
    try {
        Write-Step "检查 git 变更"
        $status = git status --porcelain
        if (-not $status) {
            Write-Ok "工作区干净，无变更需要提交"
        } else {
            $msg = if ($Message) { $Message } else { "deploy: 同步代码到已安装插件目录 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" }
            Write-Step "提交: $msg"
            if ($DryRun) {
                Write-Warn "DRY-RUN: 跳过 git add/commit/push"
            } else {
                git add -A
                git commit -m $msg
                if ($LASTEXITCODE -ne 0) { Write-Err "git commit 失败"; exit 1 }
                git push
                if ($LASTEXITCODE -ne 0) { Write-Err "git push 失败（请先 git pull --rebase）"; exit 1 }
                Write-Ok "提交并推送完成"
            }
        }
    } finally {
        Pop-Location
    }
}

Write-Ok "部署流程结束"
