# 一键构建 Windows 客户端（在 B 机或任何装了 Node 的 Windows 上运行；Windows PowerShell 5 即可）：
#
#   powershell -ExecutionPolicy Bypass -File tools\build_client.ps1 [-Server http://学校服务器:8800] [-Out dist-client] [-PyVersion 3.12.10] [-SkipWeb] [-Clean]
#
# -Server：预置服务器地址（写进安装目录的 server.json，登录页直接填好）；不填就由用户第一次打开时自己填。
#
# 产物（dist-client\，已在 .gitignore 里）：
#   蜂元虚拟工厂-安装-<版本>.exe     IExpress 自解压安装包（按用户安装，不要管理员权限）
#   蜂元虚拟工厂-绿色版-<版本>.zip   绿色版（解压即用，数据放在程序旁的 data\）
#   work\stage\蜂元虚拟工厂\         安装后的目录结构：蜂元虚拟工厂.exe、runtime\（精简 Python）、app\（vfactory、templates、web\dist）、uninstall.ps1
#
# 旧版（C# 启动器 + Edge 窗口 + IExpress 安装包），保留一轮；默认的客户端已经是 Electron 版：tools\build_electron.ps1。
# 版本号只在 vfactory\__init__.py 的 __version__ 里改。
# 步骤：网页构建 → 精简运行时（python.org 官方嵌入版 + pip 装 requirements.txt，缓存到 dist-client\cache）→ 图标 → 启动器（Windows 自带 csc.exe 编译）
#       → 组装 → 安装包（Windows 自带 iexpress.exe）+ 绿色版 zip。不会打包 config\（大模型密钥）、data\、plants\、tests\。
param(
    [string]$Repo = '',
    [string]$Out = '',
    [string]$PyVersion = '3.12.10',
    [string]$Server = '',
    [switch]$SkipWeb,
    [switch]$Clean
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
if (-not $Repo) { $Repo = Split-Path -Parent $PSScriptRoot }
$Repo = (Resolve-Path $Repo).Path
if (-not $Out) { $Out = Join-Path $Repo 'dist-client' }
$Product = '蜂元虚拟工厂'
$utf8bom = New-Object Text.UTF8Encoding $true
$sw = [Diagnostics.Stopwatch]::StartNew()
function Step($m) { Write-Host ("[{0,5:n0}s] {1}" -f $sw.Elapsed.TotalSeconds, $m) }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what 失败（退出码 $LASTEXITCODE）" } }
function SizeMB($p) { if (Test-Path -LiteralPath $p -PathType Leaf) { return [math]::Round((Get-Item -LiteralPath $p).Length / 1MB, 1) }
    return [math]::Round((Get-ChildItem -LiteralPath $p -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1) }
function CopyTree($src, $dst, [string[]]$xd = @(), [string[]]$xf = @()) {
    $a = @($src, $dst, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    if ($xd.Count) { $a += '/XD'; $a += $xd }
    if ($xf.Count) { $a += '/XF'; $a += $xf }
    & robocopy @a | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制 $src 失败（robocopy $LASTEXITCODE）" }
    $global:LASTEXITCODE = 0
}
function WriteBom($src, $dst) { [IO.File]::WriteAllText($dst, [IO.File]::ReadAllText($src, [Text.Encoding]::UTF8), $utf8bom) }

$ver = ([regex]"__version__\s*=\s*'([^']+)'").Match([IO.File]::ReadAllText("$Repo\vfactory\__init__.py")).Groups[1].Value
if (-not $ver) { throw '没在 vfactory\__init__.py 里找到 __version__' }
$parts = @($ver.Split('.') | ForEach-Object { [int]($_ -replace '\D', '') }); while ($parts.Count -lt 4) { $parts += 0 }
$ver4 = ($parts[0..3] -join '.')
Step "构建 $Product $ver → $Out"
$cache = Join-Path $Out 'cache'; $work = Join-Path $Out 'work'
if ($Clean -and (Test-Path $work)) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $cache, $work | Out-Null

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

# ---------------------------------------------------------------- 2. 精简运行时（和 Electron 客户端共用，见 tools\client\runtime.ps1）
$rt = Join-Path $work 'runtime'
. (Join-Path $PSScriptRoot 'client\runtime.ps1')
Build-VfRuntime -Repo $Repo -Cache $cache -Rt $rt -PyVersion $PyVersion -Log { param($m) Step $m }

# ---------------------------------------------------------------- 3. 图标 + 4. 启动器
$ico = Join-Path $work 'app.ico'
& (Join-Path $rt 'python.exe') "$PSScriptRoot\client\make_icon.py" (Join-Path $Repo 'web\public\logo.png') $ico | Out-Null; Check '生成图标'
Step '编译启动器（.NET Framework csc）'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
$vinfo = Join-Path $work 'VersionInfo.cs'
$year = (Get-Date).Year
@"
using System.Reflection;
[assembly: AssemblyTitle("$Product")]
[assembly: AssemblyDescription("$Product 客户端启动器")]
[assembly: AssemblyProduct("$Product")]
[assembly: AssemblyCompany("蜂元科技（郑州）有限责任公司")]
[assembly: AssemblyCopyright("© $year 蜂元科技（郑州）有限责任公司 HoneyMeta")]
[assembly: AssemblyVersion("$ver4")]
[assembly: AssemblyFileVersion("$ver4")]
[assembly: AssemblyInformationalVersion("$ver")]
"@ | ForEach-Object { [IO.File]::WriteAllText($vinfo, $_, $utf8bom) }
$launcher = Join-Path $work 'HoneyVF.exe'
& $csc /nologo /target:winexe /optimize+ /codepage:65001 "/win32icon:$ico" "/out:$launcher" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Management.dll "$PSScriptRoot\client\Launcher.cs" $vinfo
Check 'csc'

# 安装/卸载脚本先过一遍语法（PowerShell 5 把中文弯引号也当引号，写错了安装包会静默失败）
foreach ($f in @('install.ps1', 'uninstall.ps1')) {
    $errs = $null
    [void][Management.Automation.PSParser]::Tokenize([IO.File]::ReadAllText("$PSScriptRoot\client\$f", [Text.Encoding]::UTF8), [ref]$errs)
    if ($errs.Count) { throw "$f 语法错误：$($errs[0].Message)（第 $($errs[0].Token.StartLine) 行）" }
}

# ---------------------------------------------------------------- 5. 组装
Step '组装程序目录'
$stageRoot = Join-Path $work 'stage'
if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
$stage = Join-Path $stageRoot $Product
New-Item -ItemType Directory -Force -Path "$stage\app\web" | Out-Null
CopyTree $rt "$stage\runtime" @() @('.vf-stamp')
CopyTree "$Repo\vfactory" "$stage\app\vfactory" @('__pycache__') @('*.pyc', '*.log')
CopyTree "$Repo\templates" "$stage\app\templates"
CopyTree "$Repo\web\dist" "$stage\app\web\dist"
Copy-Item $launcher (Join-Path $stage "$Product.exe")
WriteBom "$PSScriptRoot\client\uninstall.ps1" (Join-Path $stage 'uninstall.ps1')
Set-Content -Path (Join-Path $stage 'version.txt') -Value $ver -Encoding ASCII
if ($Server) {                                 # 预置服务器地址（vfactory/desktop.py 的 preset_server 读它）
    if ($Server -notmatch '^https?://') { $Server = 'http://' + $Server }
    [IO.File]::WriteAllText((Join-Path $stage 'server.json'), (@{ server = $Server.TrimEnd('/') } | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    Step "预置服务器地址：$Server"
}
# 防止把密钥打进去
$leak = Get-ChildItem $stage -Recurse -File -Include 'llm.local.json', '*.db', 'run.json', 'desktop.json' -ErrorAction SilentlyContinue
if ($leak) { throw "安装内容里不该有：$($leak.FullName -join ', ')" }
Step "程序目录 $(SizeMB $stage) MB（运行时 $(SizeMB "$stage\runtime") MB，程序 $(SizeMB "$stage\app") MB）"

# ---------------------------------------------------------------- 6. 绿色版 zip（带 portable.flag，外面套一层"蜂元虚拟工厂"目录）
$portable = Join-Path $Out "$Product-绿色版-$ver.zip"
if (Test-Path $portable) { Remove-Item $portable -Force }
Set-Content -Path (Join-Path $stage 'portable.flag') -Value '有这个文件时，数据放在程序旁的 data 文件夹（绿色版）。删掉它数据就放到 %LOCALAPPDATA%\HoneyVF。' -Encoding UTF8
Step '打包绿色版 zip'
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $portable, [IO.Compression.CompressionLevel]::Optimal, $true)
Remove-Item (Join-Path $stage 'portable.flag') -Force

# ---------------------------------------------------------------- 7. 安装包（IExpress）
Step '打包安装包（IExpress）'
$iexp = Join-Path $work 'iexp'
if (Test-Path $iexp) { Remove-Item $iexp -Recurse -Force }
New-Item -ItemType Directory -Force -Path $iexp | Out-Null
[IO.Compression.ZipFile]::CreateFromDirectory($stage, "$iexp\payload.zip", [IO.Compression.CompressionLevel]::Optimal, $false)
WriteBom "$PSScriptRoot\client\install.ps1" "$iexp\install.ps1"
Set-Content -Path "$iexp\version.txt" -Value $ver -Encoding ASCII
$target = Join-Path $work "HoneyVF-Setup-$ver.exe"
if (Test-Path $target) { Remove-Item $target -Force }
$sed = Join-Path $work 'setup.sed'
@"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$target
FriendlyName=HoneyVF $ver
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File install.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File install.ps1 -Quiet
UserQuietInstCmd=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File install.ps1 -Quiet
FILE0="payload.zip"
FILE1="install.ps1"
FILE2="version.txt"
[SourceFiles]
SourceFiles0=$iexp\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@ | Set-Content -Path $sed -Encoding ASCII
$p = Start-Process -FilePath (Join-Path $env:WINDIR 'System32\iexpress.exe') -ArgumentList @('/N', '/Q', $sed) -Wait -PassThru -WindowStyle Hidden
if (-not (Test-Path $target)) { throw "IExpress 没有生成安装包（退出码 $($p.ExitCode)）" }
$setup = Join-Path $Out "$Product-安装-$ver.exe"
Move-Item -LiteralPath $target -Destination $setup -Force

Step '完成'
Write-Host ''
Write-Host ("  安装包  {0}  {1} MB" -f $setup, (SizeMB $setup))
Write-Host ("  绿色版  {0}  {1} MB" -f $portable, (SizeMB $portable))
Write-Host ("  运行时  {0} MB；程序目录（解压后）{1} MB" -f (SizeMB "$stage\runtime"), (SizeMB $stage))
