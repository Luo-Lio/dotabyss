<#
  切换 StoryViewer 的配置档(离线 / 在线对照抓包)。

  用法:
    pwsh -File tools\client-mod\set-profile.ps1 show        # 只看当前关键开关
    pwsh -File tools\client-mod\set-profile.ps1 offline     # 纯离线模式(默认工作档)
    pwsh -File tools\client-mod\set-profile.ps1 online-ref  # 在线对照:真 SDK 登录 + 真 API(经本机抓包转发)+ 真资源

  说明:
  - 只改 [Offline] 段里列出的键;配置文件里没有的键会自动补到 [Offline] 段末尾。
  - 在线对照档需要:①VPN 已连;②启动参数是新鲜的(先用 DMM Game Player 跑一次原版刷新 dll.log)。
  - 抓包结果写到 client\BepInEx\capture\(*.txt 摘要 + 需要时 *.bin 原始正文)。
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('show', 'offline', 'online-ref')]
    [string]$Profile
)

$cfg = Join-Path $PSScriptRoot '..\..\client\BepInEx\config\dotabyss.storyviewer.cfg'
if (-not (Test-Path -LiteralPath $cfg)) { throw "找不到配置文件: $cfg" }

# 两档的开关组合(键名与 [Offline] 段一致)
$profiles = [ordered]@{
    'offline' = [ordered]@{
        OfflineAuth           = 'true'    # 假 DMM 凭证
        OfflineApi            = 'true'    # API 指向本机假服务器
        RedirectAssetServer   = 'true'    # 资源也指向本机
        ServeCachedBundles    = 'true'    # 用本地 Caches 供 bundle
        SkipRequestEncryption = 'true'    # 跳过请求体加密
        ForceDmmSdkSuccess    = 'true'    # SDK 失败改判成功(藏掉错误弹窗)
        CaptureForward        = 'false'   # 不转发上游
    }
    'online-ref' = [ordered]@{
        OfflineAuth           = 'false'   # 用启动器传入的真实凭证
        OfflineApi            = 'true'    # 仍走本机(才能抓到完整往返)
        RedirectAssetServer   = 'false'   # 资源直连官方 CDN
        ServeCachedBundles    = 'true'    # 资源直连时用不到,保持默认
        SkipRequestEncryption = 'false'   # 真实加密(服务器才解得开)
        ForceDmmSdkSuccess    = 'false'   # 真实 SDK 行为(失败就弹错误框,便于判断)
        CaptureForward        = 'true'    # 转发到真实 API 并抓包
    }
}

$lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $cfg)
$keys = @('OfflineAuth', 'OfflineApi', 'RedirectAssetServer', 'ServeCachedBundles',
    'SkipRequestEncryption', 'ForceDmmSdkSuccess', 'CaptureForward')

if ($Profile -eq 'show') {
    "配置文件: $cfg"
    foreach ($key in $keys) {
        $hit = $lines | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
        '{0,-22} {1}' -f $key, ($hit ?? '(未设置,用默认值)')
    }
    return
}

$settings = $profiles[$Profile]
$sectionIndex = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*\[Offline\]\s*$') { $sectionIndex = $i; break }
}
if ($sectionIndex -lt 0) {
    $lines.Add('[Offline]')
    $sectionIndex = $lines.Count - 1
}

foreach ($key in $settings.Keys) {
    $value = $settings[$key]
    $hitIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$key\s*=") { $hitIndex = $i; break }
    }
    if ($hitIndex -ge 0) {
        $lines[$hitIndex] = "$key = $value"
    }
    else {
        # 插到 [Offline] 段末尾(下一个小节标题之前)
        $insertAt = $lines.Count
        for ($i = $sectionIndex + 1; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^\s*\[') { $insertAt = $i; break }
        }
        $lines.Insert($insertAt, "$key = $value")
    }
}

[System.IO.File]::WriteAllLines($cfg, $lines, (New-Object System.Text.UTF8Encoding($false)))
"已切换到配置档: $Profile"
& $PSCommandPath show
