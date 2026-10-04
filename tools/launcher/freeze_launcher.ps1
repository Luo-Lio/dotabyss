<#
.SYNOPSIS
冻结ドットアビスX 离线启动器(PyInstaller onefile)到 client\,并冒烟自检。

.DESCRIPTION
产出 ``client\DotabyssOfflineLauncher.exe``:图标使用 tools\launcher\dotabyss_launcher.ico
(scripts\... 未打包时自动跳过图标);跑一次 ``--smoke`` 冒烟,输出 ``PASS`` 才算成功。

.PARAMETER SkipSmoke
只冻结不冒烟(调试冻结流程时用)。

.EXAMPLE
pwsh -File tools\launcher\freeze_launcher.ps1
#>
param([switch]$SkipSmoke)

$ErrorActionPreference = 'Stop'
$python = 'D:\Python\python.exe'
$scriptDir = $PSScriptRoot
$repo = Split-Path -Parent (Split-Path -Parent $scriptDir)
$gameDir = Join-Path $repo 'client'
$ico = Join-Path $scriptDir 'dotabyss_launcher.ico'
$build = Join-Path $env:TEMP ('dotabyss_launcher_build_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $build | Out-Null

# onefile 启动器会留下常驻父/子进程,持有 exe 会让 PyInstaller 覆盖失败(WinError 5)。
# 只结束"从本目录启动器 exe 运行时"的进程,避免误杀玩家手动开着的同一程序。
$targetExe = (Join-Path $gameDir 'DotabyssOfflineLauncher.exe')
Get-Process -Name 'DotabyssOfflineLauncher*' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $targetExe } |
    ForEach-Object {
        Write-Output ("结束残留启动器进程 PID {0}" -f $_.Id)
        Stop-Process -Id $_.Id -Force
    }
Start-Sleep -Milliseconds 500

# 冻结前从构建 env 生成内建默认端点模块(gitignore;未设 env 则写空→不内建任何端点)
& $python (Join-Path $scriptDir 'make_diag_default.py')
if ($LASTEXITCODE -ne 0) { throw "make_diag_default 失败,退出码 $LASTEXITCODE" }

& $python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name DotabyssOfflineLauncher `
    --icon $ico --add-data "$ico;." `
    --hidden-import dotabyss_diag_default `
    --distpath $gameDir --workpath $build --specpath $build `
    (Join-Path $scriptDir 'dotabyss_launcher.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败,退出码 $LASTEXITCODE" }

$exe = Join-Path $gameDir 'DotabyssOfflineLauncher.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "未生成 $exe" }
Write-Output ("已生成 {0} ({1:N1} MB)" -f $exe, ((Get-Item -LiteralPath $exe).Length / 1MB))

if ($SkipSmoke) { return }

$smoke = Join-Path $build 'smoke.txt'
Start-Process -FilePath $exe -ArgumentList @('--smoke', $smoke, '--game-dir', $gameDir) | Out-Null
$deadline = (Get-Date).AddSeconds(90)
while (-not (Test-Path -LiteralPath $smoke)) {
    if ((Get-Date) -gt $deadline) { throw '冒烟超时:90 秒内未写出结果文件' }
    Start-Sleep -Milliseconds 500
}
$content = (Get-Content -LiteralPath $smoke -Raw).Trim()
if ($content -notmatch '^PASS') { throw "冒烟失败:$content" }
Write-Output ("冒烟通过:{0}" -f $content)
