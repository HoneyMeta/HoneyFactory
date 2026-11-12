# 一键构建 Windows 客户端（Electron 版，默认）：在 B 机或任何装了 Node 的 Windows 上运行；Windows PowerShell 5 即可。
#
#   powershell -ExecutionPolicy Bypass -File tools\build_electron.ps1 [-Server http://学校服务器:8800] [-UpdateUrl http://…/api/client/update/]
#              [-Out dist-electron] [-PyVersion 3.12.10] [-SkipWeb] [-NoPortable] [-Dir] [-Mirror cn|none] [-Version 4.5.1]
#              [-NoMes]
#
# -Server     预置服务器地址（resources\server.json，登录页直接填好）；不填就由用户第一次打开时自己填。
# -UpdateUrl  没连服务器（单机使用）时手动"检查更新"用的地址（resources\update.json）；联网时总是从连着的服务器更新。
# -Dir        只出 win-unpacked 目录（不做安装包，快，测试用）。
# -Version    测试用：不用 vfactory\__init__.py 的版本号（例如做一个"新版本"测自动更新）；desktop\package.json 下次正常构建时会改回来。
#             蜂元教学 MES 在本仓库（vfmes\ 包，见 vfmes\README.md）：默认一起打包到 resources\vf\vfmes（客户端按需启动，见 vfactory\mes\sidecar.py），
#             它多要的依赖（sqlalchemy，tools\client\mes-requirements.txt）装进同一个运行时。5.0.1 起 MES 的页面在虚拟工厂自己的网页里（web\src\mes\），不再单独构建。
# -NoMes      不带 MES（客户端里的"MES"页面会提示没带）。
# -Mirror     cn（默认）= Electron 和打包工具从 npmmirror.com 下载（国内连不上 GitHub）；none = 用官方地址或已设好的环境变量。
#
# 产物（dist-electron\，已在 .gitignore 里）：
#   HoneyVF-Setup-<版本>.exe           NSIS 安装包：按用户安装（不要管理员），可改安装目录，开始菜单 + 桌面快捷方式，.vfhw/.vfplant 关联，卸载时可选删数据
#   HoneyVF-Setup-<版本>.exe.blockmap  增量更新用
#   latest.yml                         自动更新的版本说明：和安装包一起发布到服务器（python tools\publish_client_update.py）
#   HoneyVF-Portable-<版本>.zip        绿色版（解压即用，带 portable.flag，数据放在程序旁的 data\）
#   win-unpacked\                      安装后的目录结构：HoneyVF.exe、resources\app.asar（外壳）、resources\python（精简运行时）、resources\vf（vfactory、templates、web\dist，以及蜂元教学 MES 的 vfmes）
#
# 步骤：版本号同步（vfactory\__init__.py → desktop\package.json）→ 网页构建 → 精简运行时（tools\client\runtime.ps1，和旧客户端共用，缓存在 dist-client\cache）
#       → 准备 desktop\.stage（python、vf、extra）和 desktop\.res（美术图片，缺的生成占位）→ npm install（desktop\）→ electron-builder → 绿色版 zip。
# 不会打包 config\（大模型密钥）、data\、plants\、tests\、web 的 node_modules。
# 代码签名：设了环境变量 CSC_LINK + CSC_KEY_PASSWORD 时 electron-builder 自动签名（见 desktop\electron-builder.yml）。
param(
    [string]$Repo = '',
    [string]$Out = '',
    [string]$PyVersion = '3.12.10',
    [string]$Server = '',
    [string]$UpdateUrl = '',
    [string]$Mirror = 'cn',
    [string]$Version = '',
    [switch]$SkipWeb,
    [switch]$NoPortable,
    [switch]$Dir,
    [switch]$NoMes
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
if (-not $Repo) { $Repo = Split-Path -Parent $PSScriptRoot }
$Repo = (Resolve-Path $Repo).Path
if (-not $Out) { $Out = Join-Path $Repo 'dist-electron' }
$desk = Join-Path $Repo 'desktop'
$utf8 = New-Object Text.UTF8Encoding $false
$sw = [Diagnostics.Stopwatch]::StartNew()
function Step($m) { Write-Host ("[{0,5:n0}s] {1}" -f $sw.Elapsed.TotalSeconds, $m) }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what 失败（退出码 $LASTEXITCODE）" } }
function SizeMB($p) { if (Test-Path -LiteralPath $p -PathType Leaf) { return [math]::Round((Get-Item -LiteralPath $p).Length / 1MB, 1) }
    return [math]::Round((Get-ChildItem -LiteralPath $p -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1) }
function Mirror($src, $dst, [string[]]$xd = @(), [string[]]$xf = @()) {
    $a = @($src, $dst, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    if ($xd.Count) { $a += '/XD'; $a += $xd }
    if ($xf.Count) { $a += '/XF'; $a += $xf }
    & robocopy @a | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制 $src 失败（robocopy $LASTEXITCODE）" }
    $global:LASTEXITCODE = 0
}
if ($env:VF_NODE_DIR) { $env:Path = $env:VF_NODE_DIR + ';' + $env:Path }     # folder with node.exe / npm, if not on PATH
if ($Mirror -eq 'cn') {
    if (-not $env:ELECTRON_MIRROR) { $env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/' }
    if (-not $env:ELECTRON_BUILDER_BINARIES_MIRROR) { $env:ELECTRON_BUILDER_BINARIES_MIRROR = 'https://npmmirror.com/mirrors/electron-builder-binaries/' }
}

# ---------------------------------------------------------------- 0. 版本号
$ver = ([regex]"__version__\s*=\s*'([^']+)'").Match([IO.File]::ReadAllText("$Repo\vfactory\__init__.py")).Groups[1].Value
if (-not $ver) { throw '没在 vfactory\__init__.py 里找到 __version__' }
if ($Version) { $ver = $Version }
$pj = Join-Path $desk 'package.json'
$pjText = [IO.File]::ReadAllText($pj, [Text.Encoding]::UTF8)
$pjNew = ([regex]'"version"\s*:\s*"[^"]*"').Replace($pjText, "`"version`": `"$ver`"", 1)
if ($pjNew -ne $pjText) { [IO.File]::WriteAllText($pj, $pjNew, $utf8); Step "desktop\package.json 版本改成 $ver" }
Step "构建 蜂元虚拟工厂（Electron）$ver → $Out"

# ---------------------------------------------------------------- 1. 网页
if (-not $SkipWeb) {
    Step '网页构建（vite build）'
    Push-Location (Join-Path $Repo 'web')
    try {
        if (-not (Test-Path node_modules)) { npm ci; Check 'npm ci' }
        $env:VF_KEEP_BUILDS = '1'                     # 4.6.2 安装包里只要这次构建的文件（网页版服务器才留上一次的，见 web/vite.config.ts）
        npm run build; Check 'npm run build'
        Remove-Item Env:VF_KEEP_BUILDS -ErrorAction SilentlyContinue
    } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $Repo 'web\dist\index.html'))) { throw '没有 web\dist\index.html（网页没构建）' }

# ---------------------------------------------------------------- 1b. 蜂元教学 MES（本仓库 vfmes\；页面在 web\src\mes\，上面一起构建了）
if (-not $NoMes -and -not (Test-Path (Join-Path $Repo 'vfmes\__main__.py'))) { throw "没找到蜂元教学 MES：$Repo\vfmes（或用 -NoMes 不带 MES）" }

# ---------------------------------------------------------------- 2. 精简运行时（和旧客户端共用缓存）
$cache = Join-Path $Repo 'dist-client\cache'
$rt = Join-Path $cache "runtime-$PyVersion"                 # 运行时也缓存在这里（换输出目录不用重建）
$extraReq = @()
if (-not $NoMes) {                                          # 带 MES：多装 sqlalchemy（tools\client\mes-requirements.txt），单独一个缓存目录，不影响旧客户端的运行时
    $rt = Join-Path $cache "runtime-$PyVersion-mes"
    $extraReq = @((Join-Path $PSScriptRoot 'client\mes-requirements.txt'))
}
. (Join-Path $PSScriptRoot 'client\runtime.ps1')
Build-VfRuntime -Repo $Repo -Cache $cache -Rt $rt -PyVersion $PyVersion -Log { param($m) Step $m } -ExtraReq $extraReq

# ---------------------------------------------------------------- 3. desktop\.stage：resources\python、resources\vf、resources\（server.json、update.json）
Step '准备 resources（python、vf）'
$stage = Join-Path $desk '.stage'
New-Item -ItemType Directory -Force -Path "$stage\vf\web", "$stage\extra" | Out-Null
Mirror $rt "$stage\python" @() @('.vf-stamp')
Mirror "$Repo\vfactory" "$stage\vf\vfactory" @('__pycache__') @('*.pyc', '*.log')
Mirror "$Repo\templates" "$stage\vf\templates"
Mirror "$Repo\web\dist" "$stage\vf\web\dist"
Set-Content -Path "$stage\vf\version.txt" -Value $ver -Encoding ASCII
# 蜂元教学 MES：vfmes 包放在 resources\vf 里（和 vfactory 同一个目录，sidecar.py 的 mes_source 就找这里）；数据库、密钥、日志都不带。
# 5.0.1 起没有 web-mes\dist 了（页面在 web\dist 里），旧的 stage 里留下的也删掉
if (Test-Path "$stage\mes") { Remove-Item "$stage\mes" -Recurse -Force }          # 4.6 的旧位置 resources\mes 不再用
foreach ($d in "$stage\vf\vfmes", "$stage\vf\web-mes") { if (Test-Path $d) { Remove-Item $d -Recurse -Force } }
if (-not $NoMes) {
    Mirror "$Repo\vfmes" "$stage\vf\vfmes" @('__pycache__') @('*.pyc', '*.log', 'llm*.json', '*.db', '*.db-*', 'secret.key', '.env')
}
Get-ChildItem "$stage\extra" -File | Remove-Item -Force
if ($Server) {                                 # 预置服务器地址（vfactory/desktop.py 的 preset_server 读 resources\server.json）
    if ($Server -notmatch '^https?://') { $Server = 'http://' + $Server }
    [IO.File]::WriteAllText("$stage\extra\server.json", (@{ server = $Server.TrimEnd('/') } | ConvertTo-Json -Compress), $utf8)
    Step "预置服务器地址：$Server"
}
if ($UpdateUrl) {
    [IO.File]::WriteAllText("$stage\extra\update.json", (@{ url = $UpdateUrl } | ConvertTo-Json -Compress), $utf8)
    Step "单机时的更新地址：$UpdateUrl"
}
Set-Content -Path "$stage\extra\README-resources.txt" -Value 'python = 精简 Python 运行时；vf = 本地服务（vfactory、templates、web\dist；vfmes = 蜂元教学 MES，本机工厂按需启动，页面在 web\dist 里）；assets = 外壳图片；server.json / update.json = 预置的服务器地址和更新地址（可选）。' -Encoding UTF8
$leak = Get-ChildItem $stage -Recurse -File -Include 'llm*.json', '*.db', 'run.json', 'desktop.json', 'account.json', 'secret.key', 'current.json', '.env' -ErrorAction SilentlyContinue
if ($leak) { throw "打包内容里不该有：$($leak.FullName -join ', ')" }
# 再按内容扫一遍 vf（含 vfmes）和 extra（运行时里的第三方包不扫）：大模型密钥（sk-…）、写了值的 api_key、私钥
$keyRx = 'sk-[A-Za-z0-9_-]{20,}|["'']api_key["'']\s*:\s*["''][^"'']{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
$hits = Get-ChildItem "$stage\vf", "$stage\extra" -Recurse -File -Include '*.py', '*.js', '*.json', '*.txt', '*.yaml', '*.yml', '*.html', '*.cfg', '*.ini' -ErrorAction SilentlyContinue |
    Select-String -Pattern $keyRx -List -ErrorAction SilentlyContinue
if ($hits) { throw "打包内容里像是有密钥：$(($hits | ForEach-Object { $_.Path + ':' + $_.LineNumber }) -join ', ')" }
Step '密钥扫描：没有发现密钥文件和密钥内容'

# ---------------------------------------------------------------- 4. desktop\.res：美术图片（desktop\build），缺的生成占位
Step '图片资源（desktop\build，缺的用占位图）'
$res = Join-Path $desk '.res'
if (Test-Path $res) { Remove-Item $res -Recurse -Force }
$logo = Join-Path $Repo 'web\public\logo.png'
& (Join-Path $rt 'python.exe') "$PSScriptRoot\client\make_placeholders.py" (Join-Path $desk 'build') $logo $res; Check '图片资源'

# ---------------------------------------------------------------- 5. 外壳依赖 + electron-builder
Push-Location $desk
try {
    if (-not (Test-Path 'node_modules\electron-builder')) {
        Step 'npm install（desktop）'
        if (Test-Path 'package-lock.json') { npm ci --no-audit --no-fund } else { npm install --no-audit --no-fund }
        Check 'npm install'
    }
    Step ('electron-builder（' + ($(if ($Dir) { '只出目录' } else { 'NSIS 安装包' })) + '）')
    $ebArgs = @('--win', '--x64', '--config', 'electron-builder.yml', '--publish', 'never', "-c.directories.output=$Out")
    if ($Dir) { $ebArgs += '--dir' }
    & node 'node_modules\electron-builder\cli.js' @ebArgs
    Check 'electron-builder'
} finally { Pop-Location }

# ---------------------------------------------------------------- 6. 绿色版 zip（win-unpacked + portable.flag，外面套一层 HoneyVF 目录）
$unpacked = Join-Path $Out 'win-unpacked'
$portable = Join-Path $Out "HoneyVF-Portable-$ver.zip"
if (-not $NoPortable -and -not $Dir) {
    Step '打包绿色版 zip'
    if (Test-Path $portable) { Remove-Item $portable -Force }
    $flag = Join-Path $unpacked 'portable.flag'
    Set-Content -Path $flag -Value '有这个文件时，数据放在程序旁的 data 文件夹（绿色版）。删掉它数据就放到 %LOCALAPPDATA%\HoneyVF。' -Encoding UTF8
    try {
        $tmp = Join-Path $Out 'work\portable'
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Mirror $unpacked "$tmp\HoneyVF"
        [IO.Compression.ZipFile]::CreateFromDirectory($tmp, $portable, [IO.Compression.CompressionLevel]::Optimal, $false)
        Remove-Item $tmp -Recurse -Force
    } finally { Remove-Item $flag -Force -ErrorAction SilentlyContinue }
}

Step '完成'
Write-Host ''
$setup = Join-Path $Out "HoneyVF-Setup-$ver.exe"
if (Test-Path $setup) { Write-Host ("  安装包    {0}  {1} MB" -f $setup, (SizeMB $setup)) }
if (Test-Path $portable) { Write-Host ("  绿色版    {0}  {1} MB" -f $portable, (SizeMB $portable)) }
$mesMB = 0
foreach ($d in "$unpacked\resources\vf\vfmes") { if (Test-Path $d) { $mesMB += SizeMB $d } }
Write-Host ("  安装后    {0} MB（Electron {1} MB，运行时 {2} MB，本地服务 {3} MB（其中蜂元教学 MES {5} MB），外壳 app.asar {4} MB）" -f (SizeMB $unpacked),
    [math]::Round((SizeMB $unpacked) - (SizeMB "$unpacked\resources"), 1), (SizeMB "$unpacked\resources\python"), (SizeMB "$unpacked\resources\vf"),
    (SizeMB "$unpacked\resources\app.asar"), [math]::Round($mesMB, 1))
