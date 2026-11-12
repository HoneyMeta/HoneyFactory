# 开发用一键启动：服务端（学校/公司服务器，http://localhost:8800）+ 客户端（Electron 外壳，开发模式，直接用源码跑，不用安装）
# 用法：双击仓库根目录的 dev-start.cmd [fresh] [legacy] [noserver]；或 powershell -ExecutionPolicy Bypass -File tools\dev-start.ps1 [-NoServer] [-Fresh] [-Legacy] [-ServerPort 8800]
#   -NoServer   只起客户端
#   -Fresh      清空客户端的本机数据（相当于新装：登录、本机工厂、窗口位置、关闭按钮的选择都清掉）
#   -Legacy     用旧的方式开客户端窗口（本地服务 + Edge 应用模式），不用 Electron
#   -NoMes      已不用（5.0.1 起蜂元教学 MES 的页面在 web\src\mes\，和虚拟工厂的网页一起；MES 的代码在本仓库 vfmes\，客户端左侧「MES」按需启动）
#   -Edition    已不用（4.3 起权限按账号角色），保留参数只为旧的快捷方式还能用
# 客户端已经开着时再运行：Electron 是单实例的，会把开着的窗口调到前面（不会再起一个本地服务）。
# 第一次运行会在 desktop\ 里 npm install（Electron 从 npmmirror.com 下载）。
param([string]$Edition = '', [switch]$NoServer, [switch]$Fresh, [switch]$Legacy, [int]$ServerPort = 8800, [switch]$NoMes)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot                        # 仓库根目录
# Environment overrides: VF_PYTHON (Python interpreter, default: python on PATH), VF_NODE_DIR (folder with node.exe/npm,
# put in front of PATH), VF_DEV_CLIENT_HOME (client data, default %LOCALAPPDATA%\HoneyVF-dev).
$py = 'python'; if ($env:VF_PYTHON) { $py = $env:VF_PYTHON }
if ($env:VF_NODE_DIR) { $env:Path = $env:VF_NODE_DIR + ';' + $env:Path }
# 客户端的本机数据（和安装版的 %LOCALAPPDATA%\HoneyVF 分开），不要放进项目的父目录
$clientHome = $env:VF_DEV_CLIENT_HOME
if (-not $clientHome) { $clientHome = Join-Path $env:LOCALAPPDATA 'HoneyVF-dev' }
function Listening($p) { [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }
function WaitPort($p, $sec) { for ($i = 0; $i -lt $sec; $i++) { if (Listening $p) { return $true }; Start-Sleep 1 }; return $false }
if ($Edition) { Write-Host "（-Edition $Edition 已不用：4.3 起客户端用服务器账号登录，权限按角色）" -ForegroundColor DarkGray }

# ---------- 1. 服务端 ----------
if (-not $NoServer) {
  if (Listening $ServerPort) { Write-Host "服务端已经在运行：http://localhost:$ServerPort" }
  else {
    Write-Host '启动服务端（新窗口，关掉窗口就停）…'
    Start-Process cmd -ArgumentList '/k', "title 服务端 VirtualFactory :$ServerPort & cd /d `"$root`" & `"$py`" -m vfactory serve --http $ServerPort" -WorkingDirectory $root
    if (-not (WaitPort $ServerPort 180)) { Write-Host '服务端 3 分钟内没起来，请看它的窗口' -ForegroundColor Yellow }
  }
  Start-Process "http://localhost:$ServerPort"
}

# ---------- 2. 客户端 ----------
$rj = Join-Path $clientHome 'run.json'
if ($Fresh -and (Test-Path $clientHome)) {
  $busy = $false
  try { $busy = (Test-Path $rj) -and (Listening ((Get-Content $rj -Raw | ConvertFrom-Json).port)) } catch { }
  if ($busy) { Write-Host '客户端正在运行：先退出它（托盘图标 → 退出）再用 -Fresh' -ForegroundColor Yellow; exit 1 }
  Remove-Item $clientHome -Recurse -Force; Write-Host '已清空客户端数据'
}
New-Item -ItemType Directory -Force $clientHome | Out-Null

# ---------- 本机 MES（蜂元教学 MES，本仓库 vfmes\）：客户端按需启动（vfactory\mes\sidecar.py），页面在虚拟工厂的网页里（web\src\mes\） ----------
Remove-Item Env:VF_MES_SOURCE -ErrorAction SilentlyContinue      # 4.6 的旧变量（指向 HoneyMES 仓库），已不用
if (Test-Path (Join-Path $root 'vfmes\__main__.py')) { Write-Host '本机 MES：蜂元教学 MES（vfmes），客户端左侧菜单「MES」' }

$desk = Join-Path $root 'desktop'
$electron = Join-Path $desk 'node_modules\electron\dist\electron.exe'
if (-not $Legacy -and -not (Test-Path $electron)) {
  Write-Host '第一次运行：安装 Electron（desktop\ 里 npm install）…'
  if (-not $env:ELECTRON_MIRROR) { $env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/' }
  if (-not $env:ELECTRON_BUILDER_BINARIES_MIRROR) { $env:ELECTRON_BUILDER_BINARIES_MIRROR = 'https://npmmirror.com/mirrors/electron-builder-binaries/' }
  Push-Location $desk
  try {
    npm install --no-audit --no-fund
    if (-not (Test-Path $electron)) { node node_modules\electron\install.js }     # npm 没跑依赖的安装脚本时，手动下载 Electron
  } finally { Pop-Location }
  if (-not (Test-Path $electron)) { Write-Host 'Electron 没装上，改用旧方式（Edge 窗口）打开' -ForegroundColor Yellow; $Legacy = $true }
}
if (-not $Legacy) {
  if (-not (Test-Path (Join-Path $root 'web\dist\index.html'))) { Write-Host '还没有 web\dist：先在 web\ 里 npm run build' -ForegroundColor Yellow }
  $env:VF_HOME = $clientHome; $env:VF_SOURCE = $root; $env:VF_PYTHON = $py; $env:VF_DEBUG = '1'
  Start-Process -FilePath $electron -ArgumentList "`"$desk`"", '--dev' -WorkingDirectory $desk
  Write-Host ''
  Write-Host "客户端（Electron 开发版）已启动：本机数据在 $clientHome，外壳日志在 $clientHome\logs\electron.log"
  Write-Host "在客户端里登录服务器：地址填 http://127.0.0.1:$ServerPort，用网页端「用户与角色」里的账号；或者「不连服务器，单机使用」。"
  Write-Host 'Ctrl+Shift+I 开发者工具。改了 web\src：npm run build 后在窗口里按 F5；改了 desktop\src：托盘 → 退出，再运行一次。'
  exit 0
}

# ---------- 旧方式：本地服务 + Edge 应用模式 ----------
$info = $null
if (Test-Path $rj) {   # 已经在运行：向它要一个新的一次性令牌再开一个窗口
  try { $old = Get-Content $rj -Raw | ConvertFrom-Json; if (Listening $old.port) { $info = $old } } catch { }
}
if ($info) {
  $tk = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($info.port)/api/desktop/ticket" -Headers @{ 'x-vf-key' = $info.key } -ContentType 'application/json' -Body '{}').token
} else {
  if (Test-Path $rj) { Remove-Item $rj -Force }
  Write-Host '启动客户端本地服务（新窗口，关掉窗口就停）…'
  Start-Process cmd -ArgumentList '/k', "title 客户端 本地服务 & cd /d `"$root`" & `"$py`" -m vfactory desktop --home `"$clientHome`"" -WorkingDirectory $root
  for ($i = 0; $i -lt 120 -and -not (Test-Path $rj); $i++) { Start-Sleep 1 }
  if (-not (Test-Path $rj)) { Write-Host '客户端 2 分钟内没起来，请看它的窗口' -ForegroundColor Yellow; exit 1 }
  $info = Get-Content $rj -Raw | ConvertFrom-Json
  WaitPort $info.port 60 | Out-Null
  $tk = $info.token
}
$url = "http://127.0.0.1:$($info.port)/#dt=$([uri]::EscapeDataString($tk))"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) { Start-Process $edge -ArgumentList "--app=$url", "--user-data-dir=$clientHome\browser\edge", '--no-first-run' }
else { Start-Process $url }
Write-Host ''
Write-Host "客户端（旧方式）：http://127.0.0.1:$($info.port)（本机数据在 $clientHome）"
