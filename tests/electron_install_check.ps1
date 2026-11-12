# 安装包端到端：起一个临时服务器 → 静默安装到一次性目录 → tests\electron_install_check.js（启动、登录服务器、打开工厂、检查更新、退出）→ 静默卸载 → 查干净了没有。
#   powershell -ExecutionPolicy Bypass -File tests\electron_install_check.ps1 -Setup dist-electron\HoneyVF-Setup-<版本>.exe [-Dir <安装目录>] [-Port 8840]
#     [-Py python] [-Entry <启动脚本>] [-OpcUa 4880] [-Modbus 6300] [-Mqtt 1923]
# 会动当前 Windows 账号的：开始菜单和桌面快捷方式、"应用和功能"卸载项、.vfhw/.vfplant 关联、vfactory:// —— 卸载时全部删掉，脚本最后检查。
#   -NextDir <另一次构建的输出目录>（tools\build_electron.ps1 -Version 更高版本 -Out …）：再测一次真的自动更新（下载 + 静默安装）
param([Parameter(Mandatory = $true)][string]$Setup, [string]$Dir = '', [int]$Port = 8840, [string]$Py = 'python', [string]$Entry = '',
      [int]$OpcUa = 4880, [int]$Modbus = 6300, [int]$Mqtt = 1923, [string]$Shots = '', [string]$NextDir = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$Setup = (Resolve-Path $Setup).Path
if (-not $Dir) { $Dir = Join-Path $env:TEMP ('HoneyVF-e2e-' + (Get-Random)) }
$Product = '蜂元虚拟工厂'
$results = New-Object System.Collections.ArrayList
function Ok($name, $cond, $detail = '') { [void]$results.Add([bool]$cond); Write-Host (($(if ($cond) { 'PASS ' } else { 'FAIL ' })) + $name + ' ' + $detail) }
function UninstallKey { Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | ForEach-Object { Get-ItemProperty $_.PSPath } |
    Where-Object { $_.DisplayName -like "$Product*" -and $_.UninstallString -and $_.UninstallString.ToLower().Contains($Dir.TrimEnd('\').ToLower() + '\') } | Select-Object -First 1 }
function Uninstall {
    $k = UninstallKey
    if (-not $k) { return }
    $un = if ($k.QuietUninstallString) { $k.QuietUninstallString } else { $k.UninstallString + ' /S' }
    $m = [regex]::Match($un, '^"([^"]+)"\s*(.*)$')
    Start-Process -FilePath $m.Groups[1].Value -ArgumentList $m.Groups[2].Value -Wait
    # 卸载程序会把自己拷到临时目录再跑（Start-Process -Wait 早早就返回）：等到卸载项也没了
    for ($i = 0; $i -lt 90 -and ((Test-Path (Join-Path $Dir 'HoneyVF.exe')) -or (UninstallKey)); $i++) { Start-Sleep 1 }
    Start-Sleep 3
}
$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "$Product.lnk"
$startLnk = Join-Path ([Environment]::GetFolderPath('Programs')) "$Product.lnk"
$hadDesktop = Test-Path $desktopLnk; $hadStart = Test-Path $startLnk
$srvHome = Join-Path $env:TEMP ('HoneyVF-e2e-server-' + (Get-Random))
$server = $null
try {
    # ---------- 1. 服务器（临时数据目录） ----------
    New-Item -ItemType Directory -Force $srvHome | Out-Null
    $env:VF_HOME = $srvHome; $env:PYTHONIOENCODING = 'utf-8'
    $sargs = @(); if ($Entry) { $sargs += $Entry } else { $sargs += @('-m', 'vfactory') }
    $sargs += @('serve', '--http', $Port, '--opcua', $OpcUa, '--modbus', $Modbus, '--mqtt', $Mqtt)
    $server = Start-Process -FilePath $Py -ArgumentList $sargs -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $srvHome 'server.out.log') -RedirectStandardError (Join-Path $srvHome 'server.err.log')
    Remove-Item Env:VF_HOME
    $up = $false
    for ($i = 0; $i -lt 180 -and -not $up; $i++) { try { $up = (Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2).ok } catch { Start-Sleep 1 } }
    Ok "服务器起来了 :$Port" $up

    # ---------- 2. 静默安装 ----------
    $t = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $Setup -ArgumentList '/S', "/D=$Dir" -PassThru -Wait
    $exe = Join-Path $Dir 'HoneyVF.exe'
    Ok ("静默安装（{0:n0} 秒，退出码 {1}）" -f $t.Elapsed.TotalSeconds, $p.ExitCode) ((Test-Path $exe) -and $p.ExitCode -eq 0) $Dir
    Ok '安装目录：外壳 + 运行时 + 本地服务' ((Test-Path "$Dir\resources\app.asar") -and (Test-Path "$Dir\resources\python\python.exe") -and (Test-Path "$Dir\resources\vf\vfactory\desktop.py") -and (Test-Path "$Dir\resources\vf\web\dist\index.html"))
    $k = UninstallKey
    Ok '"应用和功能"里有卸载项（按用户）' ([bool]$k) $(if ($k) { $k.DisplayName + ' ' + $k.DisplayVersion })
    Ok '开始菜单 + 桌面快捷方式' ((Test-Path $startLnk) -and (Test-Path $desktopLnk))
    $assoc = @('.vfhw', '.vfplant') | ForEach-Object { (Get-ItemProperty "HKCU:\Software\Classes\$_" -ErrorAction SilentlyContinue).'(default)' }
    Ok '.vfhw / .vfplant 关联到客户端' (($assoc | Where-Object { $_ }).Count -eq 2) ($assoc -join ', ')
    $size = [math]::Round((Get-ChildItem $Dir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host "  安装后占用 $size MB"

    # ---------- 3. 启动、登录、打开工厂、检查更新、退出 ----------
    $env:VF_ELECTRON_EXE = $exe; $env:VF_URL = "http://127.0.0.1:$Port"
    if ($Shots) { $env:SHOT_DIR = $Shots }
    if ($NextDir) { $env:VF_NEXT_DIR = (Resolve-Path $NextDir).Path }      # 另一次构建（更高版本号）：测真的下载 + 安装更新
    node (Join-Path $PSScriptRoot 'electron_install_check.js')
    Ok '装好的客户端走查（electron_install_check.js）' ($LASTEXITCODE -eq 0)
    $proto = Test-Path 'HKCU:\Software\Classes\vfactory'
    Ok '第一次运行注册了 vfactory:// 链接' $proto

    # ---------- 4. 静默卸载 ----------
    Uninstall
    Ok '卸载：程序文件删掉了' (-not (Test-Path $exe))
    Ok '卸载：卸载项、快捷方式没了' ((-not (UninstallKey)) -and ((Test-Path $startLnk) -eq $hadStart) -and ((Test-Path $desktopLnk) -eq $hadDesktop))
    $assoc2 = @('.vfhw', '.vfplant') | ForEach-Object { (Get-ItemProperty "HKCU:\Software\Classes\$_" -ErrorAction SilentlyContinue).'(default)' } | Where-Object { $_ }
    Ok '卸载：文件关联、vfactory:// 去掉了' ((-not $assoc2) -and -not (Test-Path 'HKCU:\Software\Classes\vfactory')) ($assoc2 -join ', ')
} finally {
    try { Uninstall } catch { Write-Host "卸载出错：$_" }                    # 中途出错也卸掉，不在这台电脑上留快捷方式和关联
    if ($server -and -not $server.HasExited) { & taskkill.exe /PID $server.Id /T /F | Out-Null }
    Start-Sleep 1
    Remove-Item $srvHome -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force -ErrorAction SilentlyContinue }
}
$n = ($results | Where-Object { $_ }).Count
Write-Host "`n$n/$($results.Count) 通过"
exit $(if ($n -eq $results.Count) { 0 } else { 1 })
