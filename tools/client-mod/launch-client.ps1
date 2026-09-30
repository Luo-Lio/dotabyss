<#
.SYNOPSIS
    启动项目内的「客户端副本」。

.DESCRIPTION
    默认模式 DmmArgs:从 DMM GAME PLAYER 日志(dll.log)读取最近一次
    ドットアビスX 的启动参数(登录凭证),用同一组参数启动副本。
    这是社区验证过的「绕过 DMM 启动器直接启动游戏」做法(参考
    GoldYgg/dotabyssx-dmm-shortcut):凭证只在启动瞬间从日志读取并
    经命令行传给游戏,本脚本不把凭证写入任何文件。

    Plain 模式:不带参数直接启动 —— 会因缺少 DMM 参数在
    DmmGamesSdk.PlayerInitialize 处初始化失败。

.PARAMETER Mode
    DmmArgs(默认)、Plain,或 GrabToken。
    GrabToken:等待 DMM GAME PLAYER 点击「ゲーム開始」写出新的启动记录,
    随即结束刚启动的正版进程(抢在它消费一次性凭证之前),再用同一组
    新凭证启动目标(默认副本)—— 解决"凭证已被正版用掉"的登录失败。

.PARAMETER TokenTarget
    GrabToken 模式下启动谁:copy(副本,默认)或 original(正版 exe 直启)。

.PARAMETER WaitSeconds
    GrabToken 模式等待新启动记录的最长秒数(默认 180)。

.PARAMETER DryRun
    只解析并显示将要启动的信息(参数仅显示条数,不显示内容),不真正启动。

.PARAMETER CreateShortcut
    在本项目 tools/client-mod/ 下创建「启动副本.lnk」快捷方式(指向本脚本,不含凭证)。

.EXAMPLE
    pwsh -File tools/client-mod/launch-client.ps1 -DryRun
    pwsh -File tools/client-mod/launch-client.ps1
    pwsh -File tools/client-mod/launch-client.ps1 -CreateShortcut
#>
param(
    [ValidateSet('DmmArgs', 'Plain', 'GrabToken')]
    [string]$Mode = 'DmmArgs',
    [ValidateSet('copy', 'original')]
    [string]$TokenTarget = 'copy',
    [int]$WaitSeconds = 180,
    [string]$OriginalDir = 'E:\dmm\dotabyss_x_cl',
    [switch]$DryRun,
    [switch]$CreateShortcut,
    [string]$ShortcutName = '启动副本.lnk'
)

$ErrorActionPreference = 'Stop'

# --- 路径 ---
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$copyExe = Join-Path $root 'client\ドットアビスX.exe'
if (-not (Test-Path -LiteralPath $copyExe)) { throw "找不到客户端副本: $copyExe" }
$copyDir = Split-Path $copyExe -Parent

# --- 工具函数 ---
# 读取 dll.log 里最后一条「ドットアビスX」启动记录(含凭证,只在内存里流转,不打印)
function Get-LaunchRecord {
    param([string]$Path)
    $record = Select-String -Path $Path -Pattern 'Execute of:: dotabyss_x_cl' | Select-Object -Last 1
    if (-not $record) { return $null }
    $m = [regex]::Match($record.Line, 'exe:\s*(?<exe>.+?)\s+dir:(?<dir>.+?)\s+arg:(?<arg>.+?)\s+admin:\s*false')
    if (-not $m.Success) { return $null }
    return [pscustomobject]@{
        Exe = $m.Groups['exe'].Value
        Dir = $m.Groups['dir'].Value
        Arg = $m.Groups['arg'].Value
        Line = $record.Line
    }
}

function Get-ProcessAtPath {
    param([string]$DirPrefix)
    @(Get-Process -Name 'ドットアビスX' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($DirPrefix, [StringComparison]::OrdinalIgnoreCase) })
}

function Resolve-LogPath {
    $candidates = @(
        (Join-Path $env:APPDATA 'dmmgameplayer5\logs\dll.log'),
        (Join-Path $env:APPDATA 'dmmgameplayer\logs\dll.log')
    )
    $found = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $found) { throw "找不到 DMM GAME PLAYER 日志(已尝试: $($candidates -join '; '))" }
    return $found
}

# --- 进程检查(原游戏与副本共用 LocalLow 数据目录,不要同时运行) ---
$copyRunning = Get-ProcessAtPath -DirPrefix $copyDir
$origRunning = Get-ProcessAtPath -DirPrefix $OriginalDir
if ($copyRunning) { Write-Warning "检测到副本进程正在运行(PID $(($copyRunning.Id) -join ','))。" }
if ($origRunning) { Write-Warning "检测到正版进程正在运行(PID $(($origRunning.Id) -join ','))。" }

# --- 解析 DMM 启动参数 ---
$argLine = $null
$logPath = $null
if ($Mode -eq 'Plain') {
    Write-Host "Plain 模式:不读日志、不带启动参数(会在 DmmGamesSdk.PlayerInitialize 处初始化失败)。" -ForegroundColor Yellow
}
else {
    $logPath = Resolve-LogPath

    if ($Mode -eq 'DmmArgs') {
        $rec = Get-LaunchRecord -Path $logPath
        if (-not $rec) { throw "日志中没有ドットアビスX 的启动记录;请先用 DMM GAME PLAYER 正常启动游戏一次。" }
        $argLine = $rec.Arg
    }
    elseif ($Mode -eq 'GrabToken') {
        $baseline = Get-LaunchRecord -Path $logPath
        if ($DryRun) {
            Write-Host "DryRun(GrabToken):跳过等待与进程结束(真正运行时才会等 dll.log 的新记录)。" -ForegroundColor Yellow
        }
        else {
        Write-Host "抢新凭证模式:请现在切到 DMM GAME PLAYER,点击ドットアビスX 的「ゲーム開始」。" -ForegroundColor Yellow
        Write-Host "脚本会在新记录写入 dll.log 的瞬间接住它,并结束刚启动的正版进程(避免它先消费掉一次性凭证)。" -ForegroundColor DarkGray
        Write-Host "等待中…(最多 $WaitSeconds 秒)" -ForegroundColor DarkGray

        $deadline = (Get-Date).AddSeconds($WaitSeconds)
        $fresh = $null
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 400
            $rec = Get-LaunchRecord -Path $logPath
            if (-not $rec) { continue }
            if ($baseline -and $rec.Line -eq $baseline.Line) { continue }
            $fresh = $rec
            break
        }
        if (-not $fresh) {
            throw "等待超时($WaitSeconds 秒):dll.log 中没有出现新的启动记录。请确认点了「ゲーム開始」后重试。"
        }
        $argLine = $fresh.Arg
        Write-Host "已接住新的启动记录($((($argLine -split '\s+').Count)) 项参数,内容脱敏)。" -ForegroundColor Green

        # 抢在正版消费凭证之前结束它(只结束 OriginalDir 下的进程,绝不动副本)
        $justStarted = Get-ProcessAtPath -DirPrefix $OriginalDir
        if ($justStarted) {
            foreach ($p in $justStarted) {
                Write-Host "结束刚启动的正版进程 PID $($p.Id)…" -ForegroundColor Yellow
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Milliseconds 800
        }
        }
    }
}

# --- 目标 exe(副本或正版) ---
$targetExe = $copyExe
$targetDir = $copyDir
$targetName = '副本'
if ($Mode -eq 'GrabToken' -and $TokenTarget -eq 'original') {
    $targetExe = Join-Path $OriginalDir 'ドットアビスX.exe'
    $targetDir = $OriginalDir
    $targetName = '正版'
    if (-not (Test-Path -LiteralPath $targetExe)) { throw "找不到正版 exe: $targetExe" }
}

# --- 显示信息(凭证脱敏) ---
Write-Host "目标: $targetName ($targetExe)" -ForegroundColor Cyan
if ($targetName -eq '副本') { Write-Host "日志: $(Join-Path $copyDir 'BepInEx\LogOutput.log')" -ForegroundColor DarkGray }
if ($argLine) {
    $n = ($argLine -split '\s+').Count
    Write-Host "启动参数: 取自 $([IO.Path]::GetFileName($logPath)),共 $n 项(内容脱敏,不显示)" -ForegroundColor DarkGray
}

# --- 可选:在项目内创建快捷方式(不包含凭证,每次启动时现场读日志;不写桌面) ---
if ($CreateShortcut) {
    $pwshExe = (Get-Command pwsh).Source
    $lnkPath = Join-Path $PSScriptRoot $ShortcutName
    $modeArgs = "-Mode $Mode"
    if ($Mode -eq 'GrabToken') { $modeArgs += " -TokenTarget $TokenTarget" }
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $pwshExe
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $modeArgs"
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = $copyExe
    $lnk.Save()
    Write-Host "已创建快捷方式: $lnkPath" -ForegroundColor Green
}

if ($DryRun) {
    Write-Host "DryRun: 未启动。" -ForegroundColor Yellow
    exit 0
}

# --- 启动(凭证只在内存与命令行中,不落盘) ---
if ($targetName -eq '副本' -and $copyRunning) {
    throw "副本已在运行(PID $(($copyRunning.Id) -join ',')):请先关闭它,或改用 -TokenTarget original。"
}
if ($argLine) {
    $p = Start-Process -FilePath $targetExe -ArgumentList $argLine -WorkingDirectory $targetDir -PassThru
} else {
    $p = Start-Process -FilePath $targetExe -WorkingDirectory $targetDir -PassThru
}
Write-Host "已请求启动(PID $($p.Id));本脚本立即返回,不等待游戏退出。" -ForegroundColor Green
