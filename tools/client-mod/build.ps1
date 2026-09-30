# StoryViewer 构建与部署:编译插件并把 DLL/剧情索引复制到复制出来的客户端。
# 用法(任意目录均可): pwsh -File tools/client-mod/build.ps1
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
$projectRoot = Split-Path (Split-Path $here -Parent) -Parent
$client = Join-Path $projectRoot 'client'
$proj = Join-Path $here 'StoryViewer'
$projFile = Join-Path $proj 'StoryViewer.csproj'

if (-not (Test-Path -LiteralPath $projFile)) { throw "找不到工程: $projFile" }
if (-not (Test-Path -LiteralPath (Join-Path $client 'BepInEx\core'))) {
    throw "客户端副本不完整(缺 BepInEx\core): $client"
}

Write-Host "构建 StoryViewer..." -ForegroundColor Cyan
dotnet build $projFile -c Release -p:ClientDir="$client" --nologo
if ($LASTEXITCODE -ne 0) { throw "构建失败(exit=$LASTEXITCODE)" }

$dll = Join-Path $proj 'bin\Release\net6.0\StoryViewer.dll'
if (-not (Test-Path -LiteralPath $dll)) { throw "构建产物缺失: $dll" }

$dst = Join-Path $client 'BepInEx\plugins\StoryViewer'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -LiteralPath $dll -Destination $dst -Force
$json = Join-Path $proj 'stories.json'
if (Test-Path -LiteralPath $json) { Copy-Item -LiteralPath $json -Destination $dst -Force }

Write-Host "已部署到: $dst" -ForegroundColor Green
Get-ChildItem -LiteralPath $dst | Select-Object Name, @{n='KB';e={[math]::Round($_.Length/1KB,1)}}
