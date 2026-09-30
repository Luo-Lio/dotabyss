#Requires -Version 7
<#
.SYNOPSIS
  截取指定进程的主窗口画面(用于游戏卡在加载画面时"看到"实际显示内容)。

.DESCRIPTION
  用 Win32 PrintWindow(PW_RENDERFULLCONTENT)把目标窗口画进内存位图,再存成 PNG。
  不依赖游戏自身的截图能力(游戏内 ScreenCapture 走 interop 有已知缺陷),也不需要窗口在前台。

  背景:离线模式排查中游戏停在标题加载画面,插件自带的纹理截图是首选方案,
  本脚本作为外部兜底,在游戏仍运行时由排查方执行。

.PARAMETER ProcessName
  进程名(支持通配匹配,如 'ドットアビスX' 或 'OpenChamber')。

.PARAMETER OutFile
  输出 PNG 路径;留空则写到 <项目>\output\captures\window-<yyyyMMdd-HHmmss>.png。

.PARAMETER Client
  只截客户区(默认截整个窗口含边框)。

.EXAMPLE
  pwsh -File tools/client-mod/capture-window.ps1 -ProcessName 'ドットアビスX'
  截取游戏窗口到 output\captures\ 下。
#>
param(
    [string]$ProcessName = 'ドットアビスX',
    [string]$OutFile = '',
    [switch]$Client
)

$ErrorActionPreference = 'Stop'

Add-Type -Namespace Win32 -Name Gdi32 -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool PrintWindow(System.IntPtr hwnd, System.IntPtr hdcBlt, uint nFlags);
[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr hwnd, out RECT lpRect);
[DllImport("user32.dll")] public static extern bool GetClientRect(System.IntPtr hwnd, out RECT lpRect);
[DllImport("user32.dll")] public static extern bool ClientToScreen(System.IntPtr hwnd, ref POINT lpPoint);
[StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
'@

# 找到第一个有可见主窗口的匹配进程。
$proc = Get-Process -Name "*$ProcessName*" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Select-Object -First 1
if (-not $proc) {
    $all = (Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" } | ForEach-Object { $_.ProcessName }) -join ', '
    throw "找不到有可见窗口的进程(匹配 '$ProcessName');同名进程: $all"
}

$hwnd = $proc.MainWindowHandle
$w = [Win32.Gdi32+RECT]::new()
$c = [Win32.Gdi32+RECT]::new()
if ($Client) {
    [void][Win32.Gdi32]::GetClientRect($hwnd, [ref]$c)
    $origin = [Win32.Gdi32+POINT]::new()
    [void][Win32.Gdi32]::ClientToScreen($hwnd, [ref]$origin)
    $x = $origin.X; $y = $origin.Y
    $width = $c.Right - $c.Left; $height = $c.Bottom - $c.Top
} else {
    [void][Win32.Gdi32]::GetWindowRect($hwnd, [ref]$w)
    $x = $w.Left; $y = $w.Top
    $width = $w.Right - $w.Left; $height = $w.Bottom - $w.Top
}
if ($width -le 0 -or $height -le 0) { throw "窗口尺寸异常: ${width}x${height}" }

if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $dir = Join-Path $repo 'output\captures'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $OutFile = Join-Path $dir ("window-{0}.png" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
} else {
    $dir = Split-Path -Parent $OutFile
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}

Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Bitmap]::new($width, $height)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $gfx.GetHdc()
try {
    # nFlags=2:PW_RENDERFULLCONTENT(DirectX/Unity 窗口也能截到内容)。
    $ok = [Win32.Gdi32]::PrintWindow($hwnd, $hdc, 2)
} finally {
    $gfx.ReleaseHdc($hdc)
    $gfx.Dispose()
}
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

[pscustomobject]@{
    Process   = $proc.ProcessName
    Pid       = $proc.Id
    Hwnd      = ('0x{0:X}' -f [int64]$hwnd)
    PrintOk   = $ok
    Width     = $width
    Height    = $height
    OutFile   = $OutFile
    Bytes     = (Get-Item -LiteralPath $OutFile).Length
} | Format-List
