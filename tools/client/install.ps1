# 蜂元虚拟工厂 客户端安装脚本（IExpress 自解压安装包解出 payload.zip + 本文件后运行；不需要管理员权限）。
#   安装到 %LOCALAPPDATA%\Programs\HoneyVF\<版本>\，建开始菜单和桌面快捷方式，注册 .vfhw（作业包）文件关联，写"应用和功能"里的卸载项。
#   测试 / 静默：环境变量 VF_INSTALL_ROOT=<安装根目录>、VF_INSTALL_QUIET=1（不弹窗、装完不启动）。
param([string]$InstallRoot = $env:VF_INSTALL_ROOT, [switch]$Quiet)
$ErrorActionPreference = 'Stop'
if ($env:VF_INSTALL_QUIET -eq '1') { $Quiet = $true }
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, System.IO.Compression, System.IO.Compression.FileSystem
$Product = '蜂元虚拟工厂'
$Publisher = '蜂元科技（郑州）有限责任公司'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ver = (Get-Content -LiteralPath (Join-Path $here 'version.txt') -TotalCount 1).Trim()
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\HoneyVF' }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$dest = Join-Path $InstallRoot $ver
$exeName = "$Product.exe"
$log = Join-Path $env:TEMP 'HoneyVF-install.log'
function Log($m) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss ') + $m) -Encoding UTF8 }
function Say($m, $icon = 'Information') { Log $m; if (-not $Quiet) { [void][Windows.Forms.MessageBox]::Show($m, "$Product $ver 安装", 'OK', $icon) } }

Log "安装 $ver 到 $dest"
try {
    # 1. 正在运行就先请用户关掉（安装目录下的启动器 / 本地服务进程）
    while ($true) {
        $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($InstallRoot + '\', [StringComparison]::OrdinalIgnoreCase) })
        if (-not $running.Count) { break }
        if ($Quiet) { throw "$Product 正在运行，无法安装" }
        $r = [Windows.Forms.MessageBox]::Show("$Product 正在运行。请先关闭它的窗口，再点「重试」。", "$Product $ver 安装", 'RetryCancel', 'Warning')
        if ($r -ne 'Retry') { exit 1 }
    }

    # 2. 进度窗口
    $form = $null; $bar = $null
    if (-not $Quiet) {
        $form = New-Object Windows.Forms.Form -Property @{ Text = "$Product $ver 安装"; Size = New-Object Drawing.Size(460, 150); StartPosition = 'CenterScreen'; FormBorderStyle = 'FixedDialog'; MaximizeBox = $false; MinimizeBox = $false; ControlBox = $false }
        $lbl = New-Object Windows.Forms.Label -Property @{ Text = "正在安装到 $dest …"; Location = New-Object Drawing.Point(20, 20); Size = New-Object Drawing.Size(410, 36) }
        $bar = New-Object Windows.Forms.ProgressBar -Property @{ Location = New-Object Drawing.Point(20, 64); Size = New-Object Drawing.Size(410, 18); Minimum = 0; Maximum = 100 }
        $form.Controls.AddRange(@($lbl, $bar)); $form.Show(); [Windows.Forms.Application]::DoEvents()
    }

    # 3. 解压（先解到临时目录，成功后再换上去）
    $tmp = "$dest.new"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead((Join-Path $here 'payload.zip'))
    try {
        $n = $zip.Entries.Count; $i = 0
        foreach ($e in $zip.Entries) {
            $i++
            $target = Join-Path $tmp $e.FullName
            if ($e.FullName.EndsWith('/')) { New-Item -ItemType Directory -Force -Path $target | Out-Null; continue }
            $dir = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $target, $true)
            if ($bar -and ($i % 40 -eq 0)) { $bar.Value = [int](100 * $i / $n); [Windows.Forms.Application]::DoEvents() }
        }
    } finally { $zip.Dispose() }
    if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
    Move-Item -LiteralPath $tmp -Destination $dest
    Copy-Item -LiteralPath (Join-Path $dest 'uninstall.ps1') -Destination (Join-Path $InstallRoot 'uninstall.ps1') -Force
    $exe = Join-Path $dest $exeName

    # 4. 快捷方式（开始菜单 + 桌面）
    $ws = New-Object -ComObject WScript.Shell
    $links = @((Join-Path ([Environment]::GetFolderPath('Programs')) "$Product.lnk"), (Join-Path ([Environment]::GetFolderPath('Desktop')) "$Product.lnk"))
    foreach ($l in $links) {
        $s = $ws.CreateShortcut($l)
        $s.TargetPath = $exe; $s.WorkingDirectory = $dest; $s.IconLocation = "$exe,0"; $s.Description = '工业数字孪生仿真平台（本机客户端）'
        $s.Save()
    }

    # 5. .vfhw 作业包关联（当前用户）
    $cls = 'HKCU:\Software\Classes'
    New-Item -Path "$cls\.vfhw" -Force | Out-Null
    Set-ItemProperty -Path "$cls\.vfhw" -Name '(default)' -Value 'HoneyVF.vfhw'
    New-Item -Path "$cls\HoneyVF.vfhw\DefaultIcon" -Force | Out-Null
    New-Item -Path "$cls\HoneyVF.vfhw\shell\open\command" -Force | Out-Null
    Set-ItemProperty -Path "$cls\HoneyVF.vfhw" -Name '(default)' -Value "$Product 作业包"
    Set-ItemProperty -Path "$cls\HoneyVF.vfhw\DefaultIcon" -Name '(default)' -Value "`"$exe`",0"
    Set-ItemProperty -Path "$cls\HoneyVF.vfhw\shell\open\command" -Name '(default)' -Value "`"$exe`" `"%1`""

    # 6. 卸载项（应用和功能）
    $un = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HoneyVF'
    New-Item -Path $un -Force | Out-Null
    $size = [int]((Get-ChildItem -LiteralPath $dest -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1KB)
    $unCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $InstallRoot 'uninstall.ps1')`""
    $props = @{ DisplayName = $Product; DisplayVersion = $ver; Publisher = $Publisher; InstallLocation = $InstallRoot; DisplayIcon = "$exe,0";
        UninstallString = $unCmd; QuietUninstallString = "$unCmd -Quiet -KeepData"; InstallDate = (Get-Date -Format 'yyyyMMdd');
        DataDir = (Join-Path $env:LOCALAPPDATA 'HoneyVF') }
    foreach ($k in $props.Keys) { Set-ItemProperty -Path $un -Name $k -Value $props[$k] }
    Set-ItemProperty -Path $un -Name 'EstimatedSize' -Value $size -Type DWord
    Set-ItemProperty -Path $un -Name 'NoModify' -Value 1 -Type DWord
    Set-ItemProperty -Path $un -Name 'NoRepair' -Value 1 -Type DWord

    # 7. 通知资源管理器刷新文件关联图标
    try {
        Add-Type -Namespace VF -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b);'
        [VF.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch { }

    # 8. 旧版本目录（升级）
    Get-ChildItem -LiteralPath $InstallRoot -Directory | Where-Object { $_.Name -ne $ver -and $_.Name -match '^\d+\.\d+' } | ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Recurse -Force; Log "删除旧版本 $($_.Name)" } catch { Log "旧版本没删掉：$($_.Name) $_" }
    }
    if ($form) { $form.Close() }
    Log '安装完成'
    if (-not $Quiet) {
        $r = [Windows.Forms.MessageBox]::Show("$Product $ver 已安装。`n`n开始菜单和桌面上有「$Product」快捷方式；数据保存在 %LOCALAPPDATA%\HoneyVF。`n`n现在打开吗？", "$Product $ver 安装", 'YesNo', 'Information')
        if ($r -eq 'Yes') { Start-Process -FilePath $exe -WorkingDirectory $dest }
    }
    exit 0
} catch {
    if ($form) { $form.Close() }
    Say "安装失败：$($_.Exception.Message)`n`n日志：$log" 'Error'
    exit 1
}
