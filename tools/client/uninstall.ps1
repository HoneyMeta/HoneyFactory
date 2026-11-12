# 蜂元虚拟工厂 客户端卸载脚本（安装时复制到 %LOCALAPPDATA%\Programs\HoneyVF\uninstall.ps1；"应用和功能"里的卸载就是运行它）。
#   删除：所有版本的程序文件、开始菜单和桌面快捷方式、.vfhw 文件关联、卸载项。
#   数据目录（%LOCALAPPDATA%\HoneyVF：工厂、PLC 程序、课程进度、作业）会问要不要一起删；静默时 -KeepData / -RemoveData 决定（默认保留）。
param([switch]$Quiet, [switch]$KeepData, [switch]$RemoveData)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$Product = '蜂元虚拟工厂'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$un = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HoneyVF'
$dataDir = Join-Path $env:LOCALAPPDATA 'HoneyVF'
try { $d = (Get-ItemProperty -Path $un -Name DataDir -ErrorAction Stop).DataDir; if ($d) { $dataDir = $d } } catch { }
$log = Join-Path $env:TEMP 'HoneyVF-uninstall.log'
function Log($m) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss ') + $m) -Encoding UTF8 }
function Ask($m, $buttons = 'YesNo', $icon = 'Question') { [Windows.Forms.MessageBox]::Show($m, "卸载 $Product", $buttons, $icon) }

Log "卸载 $root"
if (-not $Quiet) {
    if ((Ask "确定要卸载 $Product 吗？") -ne 'Yes') { exit 1 }
}
# 正在运行：请用户关掉（静默时直接结束）
while ($true) {
    $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) })
    if (-not $running.Count) { break }
    if ($Quiet) { $running | ForEach-Object { try { $_.Kill() } catch { } }; Start-Sleep -Seconds 2; continue }
    if ((Ask "$Product 正在运行。请先关闭它的窗口，再点「重试」。" 'RetryCancel' 'Warning') -ne 'Retry') { exit 1 }
}

# 快捷方式（只删指向本安装目录的）
$ws = New-Object -ComObject WScript.Shell
foreach ($l in @((Join-Path ([Environment]::GetFolderPath('Programs')) "$Product.lnk"), (Join-Path ([Environment]::GetFolderPath('Desktop')) "$Product.lnk"))) {
    if (Test-Path -LiteralPath $l) {
        $t = $ws.CreateShortcut($l).TargetPath
        if (-not $t -or $t.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $l -Force; Log "删除快捷方式 $l" }
    }
}
# 文件关联、卸载项
$cls = 'HKCU:\Software\Classes'
try { if ((Get-ItemProperty -Path "$cls\.vfhw" -ErrorAction Stop).'(default)' -eq 'HoneyVF.vfhw') { Remove-Item -Path "$cls\.vfhw" -Recurse -Force } } catch { }
if (Test-Path "$cls\HoneyVF.vfhw") { Remove-Item -Path "$cls\HoneyVF.vfhw" -Recurse -Force }
if (Test-Path $un) { Remove-Item -Path $un -Recurse -Force }
try {
    Add-Type -Namespace VF -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b);'
    [VF.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
} catch { }

# 数据目录
$delData = $false
if (Test-Path -LiteralPath $dataDir) {
    if ($Quiet) { $delData = [bool]$RemoveData -and -not $KeepData }
    else { $delData = (Ask "要不要同时删除你的数据？`n`n$dataDir`n（工厂、PLC 程序、课程进度、作业包等）`n`n选「否」会保留，以后重新安装还能接着用。" 'YesNo' 'Question') -eq 'Yes' }
    if ($delData) { Remove-Item -LiteralPath $dataDir -Recurse -Force; Log "删除数据目录 $dataDir" } else { Log "保留数据目录 $dataDir" }
}

# 程序文件（包括本脚本）：在临时目录里起一个进程等本脚本退出后再删，避免删不掉正在用的目录
Set-Location -LiteralPath $env:TEMP
$cmd = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$($root.Replace("'", "''"))' -Recurse -Force -ErrorAction SilentlyContinue"
$enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-EncodedCommand', $enc) -WindowStyle Hidden
Log '卸载完成'
if (-not $Quiet) { [void](Ask "$Product 已卸载。" 'OK' 'Information') }
exit 0
