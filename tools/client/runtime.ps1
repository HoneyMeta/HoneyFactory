# 精简 Python 运行时（python.org 官方嵌入版 + pip 装 requirements.txt），tools\build_client.ps1（旧 IExpress 客户端）和 tools\build_electron.ps1（Electron 客户端）共用。
# 用法（点引用）：. "$PSScriptRoot\client\runtime.ps1"; Build-VfRuntime -Repo $Repo -Cache $cache -Rt $rt -PyVersion 3.12.10 -Log { param($m) Step $m }
# ._pth 里程序目录写了两个：..\app（旧客户端：runtime\ 旁边的 app\）和 ..\vf（Electron：resources\python 旁边的 resources\vf），不存在的目录 Python 会忽略。
# -ExtraReq：额外的 requirements 文件（Electron 客户端带的蜂元教学 MES 要 sqlalchemy，见 tools\client\mes-requirements.txt），一起装进同一个运行时、算进 .vf-stamp。
# 下载缓存：$Cache\python-<版本>-embed-amd64.zip、get-pip.py；运行时目录里的 .vf-stamp 记着版本和 requirements.txt 的哈希，没变就不重建。
function Build-VfRuntime {
    param([string]$Repo, [string]$Cache, [string]$Rt, [string]$PyVersion = '3.12.10', [scriptblock]$Log = { param($m) Write-Host $m }, [string[]]$ExtraReq = @())
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $mb = { param($p) [math]::Round((Get-ChildItem -LiteralPath $p -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1) }
    $req = [IO.File]::ReadAllText("$Repo\requirements.txt")
    foreach ($x in $ExtraReq) { if ($x) { $req += "`n# extra: " + (Split-Path -Leaf $x) + "`n" + [IO.File]::ReadAllText($x) } }
    $stampWant = "py=$PyVersion;rt=4;" + [BitConverter]::ToString((New-Object Security.Cryptography.SHA1Managed).ComputeHash([Text.Encoding]::UTF8.GetBytes($req)))
    $stampFile = Join-Path $Rt '.vf-stamp'
    if ((Test-Path $stampFile) -and ((Get-Content $stampFile -Raw).Trim() -eq $stampWant)) {
        & $Log "运行时已是最新（$(& $mb $Rt) MB），跳过"
        return
    }
    & $Log "精简运行时：Python $PyVersion 嵌入版 + requirements.txt"
    New-Item -ItemType Directory -Force -Path $Cache | Out-Null
    if (Test-Path $Rt) { Remove-Item $Rt -Recurse -Force }
    $zipName = "python-$PyVersion-embed-amd64.zip"
    $pyZip = Join-Path $Cache $zipName
    if (-not (Test-Path $pyZip)) { Invoke-WebRequest -UseBasicParsing "https://www.python.org/ftp/python/$PyVersion/$zipName" -OutFile "$pyZip.part"; Move-Item "$pyZip.part" $pyZip }
    $getPip = Join-Path $Cache 'get-pip.py'
    if (-not (Test-Path $getPip)) { Invoke-WebRequest -UseBasicParsing 'https://bootstrap.pypa.io/get-pip.py' -OutFile "$getPip.part"; Move-Item "$getPip.part" $getPip }
    [IO.Compression.ZipFile]::ExtractToDirectory($pyZip, $Rt)
    $pth = Get-ChildItem $Rt -Filter 'python3*._pth' | Select-Object -First 1
    $zipStd = (Get-ChildItem $Rt -Filter 'python3*.zip' | Select-Object -First 1).Name
    # 相对 ._pth 所在目录：标准库、site-packages、程序目录（..\app 或 ..\vf）
    [IO.File]::WriteAllText($pth.FullName, "$zipStd`r`n.`r`nLib\site-packages`r`n..\app`r`n..\vf`r`nimport site`r`n", (New-Object Text.ASCIIEncoding))
    $py = Join-Path $Rt 'python.exe'
    $env:PYTHONNOUSERSITE = '1'; $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    & $py $getPip --no-warn-script-location -q
    if ($LASTEXITCODE -ne 0) { throw "get-pip 失败（退出码 $LASTEXITCODE）" }
    & $py -m pip install --no-warn-script-location --no-compile -q -r "$Repo\requirements.txt"
    if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt 失败（退出码 $LASTEXITCODE）" }
    foreach ($x in $ExtraReq) {
        if (-not $x) { continue }
        & $py -m pip install --no-warn-script-location --no-compile -q -r $x
        if ($LASTEXITCODE -ne 0) { throw "pip install -r $x 失败（退出码 $LASTEXITCODE）" }
    }
    & $py -m pip list --format=freeze | Set-Content -Encoding UTF8 (Join-Path (Split-Path -Parent $Rt) 'runtime-packages.txt')
    $before = & $mb $Rt
    # 去掉运行时用不到的：pip 本身、各包自带的 tests 目录、字节码缓存、脚本入口、类型存根、numpy 的 C 头文件
    $sp = Join-Path $Rt 'Lib\site-packages'
    Get-ChildItem $sp -Directory | Where-Object { $_.Name -match '^(pip|setuptools|wheel|_distutils_hack)(-|$)' } | Remove-Item -Recurse -Force
    Get-ChildItem $sp -File -Filter 'distutils-precedence.pth' | Remove-Item -Force
    Get-ChildItem $sp -Recurse -Directory | Where-Object { $_.Name -eq 'tests' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $Rt -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    Get-ChildItem $sp -Recurse -File -Include '*.pyi', '*.pyx', '*.pxd' | Remove-Item -Force
    foreach ($d in @('Scripts', 'share')) { if (Test-Path "$Rt\$d") { Remove-Item "$Rt\$d" -Recurse -Force } }
    Get-ChildItem $sp -Recurse -Directory -Filter 'include' | Where-Object { $_.FullName -match '\\numpy\\_core\\include$' } | Remove-Item -Recurse -Force
    Set-Content -Path $stampFile -Value $stampWant -Encoding ASCII
    & $Log "运行时 $before MB → 精简后 $(& $mb $Rt) MB"
}
