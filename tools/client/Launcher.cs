// 蜂元虚拟工厂 Windows 客户端启动器（tools/build_client.ps1 用 Windows 自带的 .NET Framework csc.exe 编译，C# 5，不依赖第三方）。
//
//   蜂元虚拟工厂.exe [作业包.vfhw] [--home 数据目录] [--browser edge|chrome|default]
//
// 1. 数据目录：--home > 环境变量 VF_CLIENT_HOME > 程序旁边有 portable.flag 时用程序旁的 data\（绿色版）> %LOCALAPPDATA%\HoneyVF
// 2. 单实例（按数据目录）：已经在运行时，只再开一个窗口（双击作业包时把路径带过去），然后退出。
// 3. 启动 runtime\pythonw.exe -m vfactory desktop --home <数据目录> --watch-pid <本进程>（隐藏控制台），显示启动画面，
//    等 run.json + /api/health；
// 4. 用 Edge 应用模式打开 http://127.0.0.1:<端口>/[?open=<作业包>]#dt=<一次性令牌>（独立的浏览器数据目录 <数据目录>\browser\edge），
//    没有 Edge 用 Chrome，再没有用默认浏览器；
// 5. Edge/Chrome：所有窗口关掉后让本地服务退出（/api/desktop/shutdown），再收掉这个浏览器数据目录下残留的进程；
//    默认浏览器：没法知道窗口关没关，靠托盘图标"退出"。
// 测试用：环境变量 VF_CLIENT_DEBUG_PORT=<端口> 给浏览器加 --remote-debugging-port。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Management;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

static class Program
{
    const string Product = "蜂元虚拟工厂";
    static string AppDir, Home, RunJson, LogPath;

    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

    [STAThread]
    static int Main(string[] argv)
    {
        try { SetProcessDPIAware(); } catch { }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        AppDir = Path.GetDirectoryName(Application.ExecutablePath);
        string open = null, homeArg = null, browser = null;
        for (int i = 0; i < argv.Length; i++)
        {
            string a = argv[i];
            if (a == "--home" && i + 1 < argv.Length) homeArg = argv[++i];
            else if (a == "--browser" && i + 1 < argv.Length) browser = argv[++i];
            else if (!a.StartsWith("--") && File.Exists(a)) open = Path.GetFullPath(a);
        }
        Home = homeArg ?? Environment.GetEnvironmentVariable("VF_CLIENT_HOME");
        if (string.IsNullOrEmpty(Home))
            Home = File.Exists(Path.Combine(AppDir, "portable.flag")) ? Path.Combine(AppDir, "data")
                 : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HoneyVF");
        Home = Path.GetFullPath(Home).TrimEnd('\\');
        try { Directory.CreateDirectory(Path.Combine(Home, "logs")); }
        catch (Exception e) { MessageBox.Show("数据目录无法创建：" + Home + "\n" + e.Message, Product, MessageBoxButtons.OK, MessageBoxIcon.Error); return 2; }
        RunJson = Path.Combine(Home, "run.json");
        LogPath = Path.Combine(Home, "logs", "launcher.log");
        Log("启动 " + Application.ExecutablePath + " 数据目录 " + Home + (open != null ? " 打开 " + open : ""));

        bool first;
        string mname = "Local\\HoneyVF-" + Hash(Home.ToLowerInvariant());
        using (var mtx = new Mutex(true, mname, out first))
        {
            if (!first) return SecondInstance(open, browser);
            var ctx = new AppCtx(open, browser);
            Application.Run(ctx);
            return ctx.ExitCode;
        }
    }

    // ---------------------------------------------------------------- 第二次启动：只开窗口
    static int SecondInstance(string open, string browser)
    {
        Log("已在运行：再开一个窗口");
        var info = WaitRunning(null, 120);
        if (info == null)
        {
            MessageBox.Show(Product + " 正在启动或没有响应，请稍等片刻再试。", Product, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        string tok = Ticket(info);
        if (tok == null) { MessageBox.Show("无法连接本地服务，请关闭所有窗口后重新打开。", Product); return 1; }
        string kind;
        OpenWindow(info, tok, open, browser, out kind);
        return 0;
    }

    // ---------------------------------------------------------------- 运行信息
    internal class RunInfo { public int Port; public int Pid; public string Token, Key; }

    internal static RunInfo ReadRun()
    {
        try
        {
            string s = File.ReadAllText(RunJson, Encoding.UTF8);
            var r = new RunInfo();
            r.Port = int.Parse(Regex.Match(s, "\"port\"\\s*:\\s*(\\d+)").Groups[1].Value);
            r.Pid = int.Parse(Regex.Match(s, "\"pid\"\\s*:\\s*(\\d+)").Groups[1].Value);
            r.Token = Regex.Match(s, "\"token\"\\s*:\\s*\"([^\"]*)\"").Groups[1].Value;
            r.Key = Regex.Match(s, "\"key\"\\s*:\\s*\"([^\"]*)\"").Groups[1].Value;
            return r;
        }
        catch { return null; }
    }

    internal static bool Healthy(int port)
    {
        try
        {
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + "/api/health");
            req.Timeout = 3000; req.Proxy = null;
            using (var resp = (HttpWebResponse)req.GetResponse())
            using (var rd = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                return rd.ReadToEnd().Contains("\"desktop\":true");
        }
        catch { return false; }
    }

    /// <summary>等 run.json（pid 对得上）+ 健康检查通过；server 为空时不检查 pid（第二个实例）。</summary>
    internal static RunInfo WaitRunning(Process server, int seconds)
    {
        var sw = Stopwatch.StartNew();
        while (sw.Elapsed.TotalSeconds < seconds)
        {
            if (server != null && server.HasExited) return null;
            var r = ReadRun();
            if (r != null && (server == null || r.Pid == server.Id) && Healthy(r.Port)) return r;
            Thread.Sleep(300);
        }
        return null;
    }

    internal static string Post(RunInfo info, string path, int timeoutMs)
    {
        try
        {
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + info.Port + path);
            req.Method = "POST"; req.Timeout = timeoutMs; req.Proxy = null; req.ContentType = "application/json";
            req.Headers["X-VF-Key"] = info.Key;
            byte[] body = Encoding.UTF8.GetBytes("{}");
            req.ContentLength = body.Length;
            using (var st = req.GetRequestStream()) st.Write(body, 0, body.Length);
            using (var resp = (HttpWebResponse)req.GetResponse())
            using (var rd = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                return rd.ReadToEnd();
        }
        catch (Exception e) { Log("POST " + path + " 失败：" + e.Message); return null; }
    }

    internal static string Ticket(RunInfo info)
    {
        string s = Post(info, "/api/desktop/ticket", 5000);
        if (s == null) return null;
        var m = Regex.Match(s, "\"token\"\\s*:\\s*\"([^\"]*)\"");
        return m.Success ? m.Groups[1].Value : null;
    }

    // ---------------------------------------------------------------- 浏览器
    internal static string FindBrowser(string which)
    {
        string exe = which == "chrome" ? "chrome.exe" : "msedge.exe";
        foreach (var root in new[] { Microsoft.Win32.Registry.CurrentUser, Microsoft.Win32.Registry.LocalMachine })
        {
            foreach (var sub in new[] { @"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\", @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\" })
            {
                try
                {
                    using (var k = root.OpenSubKey(sub + exe))
                    {
                        var v = k == null ? null : k.GetValue(null) as string;
                        if (!string.IsNullOrEmpty(v) && File.Exists(v.Trim('"'))) return v.Trim('"');
                    }
                }
                catch { }
            }
        }
        string rel = which == "chrome" ? @"Google\Chrome\Application\chrome.exe" : @"Microsoft\Edge\Application\msedge.exe";
        foreach (var basedir in new[] { Environment.GetEnvironmentVariable("ProgramFiles(x86)"), Environment.GetEnvironmentVariable("ProgramFiles"),
                                        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) })
        {
            if (string.IsNullOrEmpty(basedir)) continue;
            string p = Path.Combine(basedir, rel);
            if (File.Exists(p)) return p;
        }
        return null;
    }

    internal static string Url(RunInfo info, string tok, string open)
    {
        string u = "http://127.0.0.1:" + info.Port + "/";
        if (open != null) u += "?open=" + Uri.EscapeDataString(open);     // 双击作业包：前端路由转到 /teach，由 PackageOpen 打开
        return u + "#dt=" + Uri.EscapeDataString(tok);
    }

    /// <summary>开一个窗口；kind = edge / chrome / default。返回浏览器数据目录（default 时为 null）。</summary>
    internal static string OpenWindow(RunInfo info, string tok, string open, string prefer, out string kind)
    {
        string url = Url(info, tok, open);
        var order = new List<string>();
        if (prefer == "chrome") order.Add("chrome");
        if (prefer != "default") { order.Add("edge"); order.Add("chrome"); }
        foreach (var b in order)
        {
            string exe = FindBrowser(b);
            if (exe == null) continue;
            string profile = Path.Combine(Home, "browser", b);
            Directory.CreateDirectory(profile);
            string args = "--app=\"" + url + "\" --user-data-dir=\"" + profile + "\" --no-first-run --no-default-browser-check"
                        + " --disable-features=msEdgeStartupBoost,msImplicitSignin,Translate --start-maximized";
            string dbg = Environment.GetEnvironmentVariable("VF_CLIENT_DEBUG_PORT");
            if (!string.IsNullOrEmpty(dbg)) args += " --remote-debugging-port=" + dbg;
            try
            {
                Process.Start(new ProcessStartInfo(exe, args) { UseShellExecute = false });
                Log("窗口：" + b + " " + exe);
                kind = b;
                return profile;
            }
            catch (Exception e) { Log(b + " 启动失败：" + e.Message); }
        }
        try { Process.Start(url); } catch (Exception e) { Log("默认浏览器打开失败：" + e.Message); }
        Log("窗口：默认浏览器");
        kind = "default";
        return null;
    }

    // 某个浏览器数据目录下的所有进程
    internal static List<int> ProfilePids(string browserKind, string profile)
    {
        var pids = new List<int>();
        string name = browserKind == "chrome" ? "chrome.exe" : "msedge.exe";
        string needle = profile.ToLowerInvariant();
        try
        {
            using (var s = new ManagementObjectSearcher("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='" + name + "'"))
            using (var res = s.Get())
            {
                foreach (ManagementObject o in res)
                {
                    var cl = o["CommandLine"] as string;
                    if (cl != null && cl.ToLowerInvariant().Contains(needle)) pids.Add(Convert.ToInt32(o["ProcessId"]));
                    o.Dispose();
                }
            }
        }
        catch (Exception e) { Log("查询浏览器进程失败：" + e.Message); }
        return pids;
    }

    delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);

    /// <summary>这些进程有没有可见的浏览器顶层窗口（Chrome_WidgetWin_1 且有标题）。</summary>
    internal static bool HasWindow(ICollection<int> pids)
    {
        if (pids.Count == 0) return false;
        var set = new HashSet<int>(pids);
        bool found = false;
        EnumWindows(delegate (IntPtr h, IntPtr l)
        {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            if (!set.Contains((int)pid) || !IsWindowVisible(h) || GetWindowTextLength(h) == 0) return true;
            var sb = new StringBuilder(64);
            GetClassName(h, sb, 64);
            if (sb.ToString().StartsWith("Chrome_WidgetWin")) { found = true; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    // ---------------------------------------------------------------- 杂项
    internal static string Hash(string s)
    {
        using (var sha = System.Security.Cryptography.SHA1.Create())
        {
            var b = sha.ComputeHash(Encoding.UTF8.GetBytes(s));
            var sb = new StringBuilder();
            for (int i = 0; i < 8; i++) sb.Append(b[i].ToString("x2"));
            return sb.ToString();
        }
    }

    static readonly object logLock = new object();
    internal static void Log(string msg)
    {
        try { lock (logLock) File.AppendAllText(LogPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + msg + "\r\n", Encoding.UTF8); } catch { }
    }

    internal static string LogTail(string file, int chars)
    {
        try
        {
            using (var fs = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var rd = new StreamReader(fs, Encoding.UTF8))
            {
                string s = rd.ReadToEnd();
                return s.Length > chars ? s.Substring(s.Length - chars) : s;
            }
        }
        catch { return ""; }
    }

    // ================================================================ 第一个实例：启动服务、开窗口、看着窗口
    class AppCtx : ApplicationContext
    {
        public int ExitCode;
        readonly string open, prefer;
        readonly Form splash;
        readonly Label status;
        readonly NotifyIcon tray;
        Process server;
        RunInfo info;
        string kind, profile;
        volatile bool quitting;

        public AppCtx(string open, string prefer)
        {
            this.open = open; this.prefer = prefer;
            Icon icon = null;
            try { icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            splash = new Form
            {
                FormBorderStyle = FormBorderStyle.None, StartPosition = FormStartPosition.CenterScreen, ShowInTaskbar = true,
                Size = new Size(460, 170), BackColor = Color.FromArgb(30, 35, 41), Text = Product, TopMost = false
            };
            if (icon != null) splash.Icon = icon;
            var pic = new PictureBox { Location = new Point(24, 28), Size = new Size(64, 64), SizeMode = PictureBoxSizeMode.Zoom };
            if (icon != null) pic.Image = new Icon(icon, 64, 64).ToBitmap();
            var title = new Label { Text = Product, ForeColor = Color.White, Font = new Font("Microsoft YaHei UI", 16f, FontStyle.Bold), Location = new Point(100, 30), AutoSize = true };
            status = new Label { Text = "正在启动本地服务…", ForeColor = Color.FromArgb(242, 201, 76), Font = new Font("Microsoft YaHei UI", 10f), Location = new Point(102, 72), AutoSize = true };
            var bar = new ProgressBar { Style = ProgressBarStyle.Marquee, Location = new Point(24, 120), Size = new Size(412, 10), MarqueeAnimationSpeed = 30 };
            splash.Controls.AddRange(new Control[] { pic, title, status, bar });
            splash.Show();

            tray = new NotifyIcon { Icon = icon ?? SystemIcons.Application, Text = Product + "（本机运行中）", Visible = false };
            var menu = new ContextMenuStrip();
            menu.Items.Add("打开窗口", null, delegate { NewWindow(); });
            menu.Items.Add("打开数据目录", null, delegate { try { Process.Start("explorer.exe", "\"" + Home + "\""); } catch { } });
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("退出", null, delegate { Quit("托盘菜单退出"); });
            tray.ContextMenuStrip = menu;
            tray.DoubleClick += delegate { NewWindow(); };

            new Thread(Work) { IsBackground = true }.Start();
        }

        void Ui(Action a)
        {
            try { if (splash.IsHandleCreated) splash.BeginInvoke(a); } catch { }
        }

        void Status(string s) { Ui(delegate { status.Text = s; }); }

        void Fail(string msg)
        {
            Log("失败：" + msg);
            Ui(delegate
            {
                splash.Hide();
                string tail = LogTail(Path.Combine(Home, "logs", "vfactory.log"), 1500);
                MessageBox.Show(msg + (tail.Length > 0 ? "\n\n日志（" + Path.Combine(Home, "logs") + "）：\n" + tail : ""), Product,
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
                ExitCode = 1;
                Cleanup();
            });
        }

        void Work()
        {
            try
            {
                string py = Path.Combine(AppDir, "runtime", "pythonw.exe");
                if (!File.Exists(py)) { Fail("程序文件不完整（缺少 runtime\\pythonw.exe），请重新安装。"); return; }
                try { if (File.Exists(RunJson)) File.Delete(RunJson); } catch { }
                var psi = new ProcessStartInfo(py, "-m vfactory desktop --home \"" + Home + "\" --watch-pid " + Process.GetCurrentProcess().Id)
                {
                    UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Home
                };
                psi.EnvironmentVariables.Remove("PYTHONHOME");
                psi.EnvironmentVariables.Remove("PYTHONPATH");
                psi.EnvironmentVariables.Remove("VF_HOME");
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
                server = Process.Start(psi);
                Log("本地服务进程 " + server.Id);
                info = WaitRunning(server, 240);
                if (info == null)
                {
                    Fail(server.HasExited ? "本地服务启动失败（退出码 " + server.ExitCode + "）。" : "本地服务 4 分钟内没有就绪。");
                    return;
                }
                Log("本地服务就绪 端口 " + info.Port);
                Status("正在打开窗口…");
                profile = OpenWindow(info, info.Token, open, prefer, out kind);
                Ui(delegate { tray.Visible = true; });
                Thread.Sleep(1500);
                Ui(delegate { splash.Hide(); });
                if (profile == null)
                {
                    Ui(delegate { tray.ShowBalloonTip(5000, Product, "已在浏览器里打开。用完后在右下角托盘图标上点\"退出\"。", ToolTipIcon.Info); });
                    WatchServerOnly();
                }
                else WatchWindows();
            }
            catch (Exception e) { Fail("启动出错：" + e.Message); }
        }

        void WatchServerOnly()
        {
            while (!quitting)
            {
                if (server.HasExited) { Ui(delegate { Quit("本地服务已退出"); }); return; }
                Thread.Sleep(1000);
            }
        }

        // 退出条件（连续 3 次检查都成立才算，约 4 秒）：
        //   见过这个浏览器数据目录的可见窗口，现在一个都没有了（浏览器设成"关闭后继续在后台运行"时进程还在，也算关了）；
        //   或者从没看到窗口（例如没有交互桌面），但它的浏览器进程出现过、现在全没了。
        // 浏览器进程一直没出现（被别的程序接管等）就不自动退出，靠托盘图标"退出"。
        void WatchWindows()
        {
            bool seenWin = false, seenProc = false;
            int missing = 0;
            while (!quitting)
            {
                if (server.HasExited) { Ui(delegate { Quit("本地服务已退出"); }); return; }
                var pids = ProfilePids(kind, profile);
                if (pids.Count > 0) seenProc = true;
                if (HasWindow(pids)) { seenWin = true; missing = 0; }
                else if (seenWin || (seenProc && pids.Count == 0))
                {
                    if (++missing >= 3) { Ui(delegate { Quit("窗口都已关闭"); }); return; }
                }
                else missing = 0;
                Thread.Sleep(1300);
            }
        }

        void NewWindow()
        {
            if (info == null) return;
            new Thread(delegate ()
            {
                string tok = Ticket(info);
                if (tok == null) return;
                string k;
                OpenWindow(info, tok, null, prefer, out k);
            }) { IsBackground = true }.Start();
        }

        void Quit(string why)
        {
            if (quitting) return;
            quitting = true;
            Log("退出：" + why);
            tray.Visible = false;
            new Thread(delegate ()
            {
                StopServer();
                Ui(Cleanup);
            }) { IsBackground = true }.Start();
        }

        void StopServer()
        {
            try
            {
                if (server != null && !server.HasExited)
                {
                    if (info != null) Post(info, "/api/desktop/shutdown", 5000);
                    if (!server.WaitForExit(15000)) { Log("本地服务没有按时退出，强制结束"); server.Kill(); }
                }
            }
            catch (Exception e) { Log("停止服务：" + e.Message); }
            if (profile != null)                      // 浏览器后台残留（"关闭后继续运行后台应用"）一并收掉
            {
                foreach (int pid in ProfilePids(kind, profile))
                {
                    try { Process.GetProcessById(pid).Kill(); } catch { }
                }
            }
        }

        void Cleanup()
        {
            try { tray.Visible = false; tray.Dispose(); } catch { }
            try { splash.Close(); } catch { }
            ExitThread();
        }
    }
}
