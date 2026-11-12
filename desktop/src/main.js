// 蜂元虚拟工厂 Windows 客户端（Electron 外壳，设计 4.5）。界面就是网页版（同一个 Vue 构建，由本机 Python 服务提供），外壳负责：
//   启动画面 → 起本机服务（resources\python + resources\vf，或开发时的源码）→ 一次性令牌换会话 → 主窗口；单实例；托盘；关闭行为；
//   窗口位置记忆；任务栏跳转列表和角标；系统通知；.vfhw / .vfplant 文件关联和 vfactory:// 链接；自动更新。
// 环境变量（开发/测试用）：VF_HOME 数据目录；VF_PYTHON 解释器；VF_ENTRY 启动脚本（空 = -m vfactory）；VF_SOURCE 源码目录；
//   VF_DEBUG=1 允许 Ctrl+Shift+I；VF_UPDATE_URL 更新地址；VF_NO_REGISTER=1 不注册 vfactory:// 和跳转列表（测试）。
'use strict';
const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, dialog, shell, Notification, screen, nativeTheme } = require('electron');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { Backend } = require('./backend');
const { Prefs } = require('./prefs');
const { Updater } = require('./updater');
const { badgeImage } = require('./badge');

const APP_ID = 'com.honeymeta.vfactory';
const PRODUCT = '蜂元虚拟工厂';
const PACKAGED = app.isPackaged;
const DEV = !PACKAGED || process.argv.includes('--dev');
const DEBUG = DEV || process.env.VF_DEBUG === '1';
const SRC_ROOT = path.resolve(process.env.VF_SOURCE || path.join(__dirname, '..', '..'));
const EXE_DIR = path.dirname(process.execPath);
const NO_REGISTER = process.env.VF_NO_REGISTER === '1';

// ---------------------------------------------------------------- 目录
const argValue = (argv, name) => { const i = argv.indexOf(name); return i > 0 && i + 1 < argv.length ? argv[i + 1] : null; };
function resolveHome() {
  const h = argValue(process.argv, '--home') || process.env.VF_HOME;
  if (h) return path.resolve(h);
  if (PACKAGED && fs.existsSync(path.join(EXE_DIR, 'portable.flag'))) return path.join(EXE_DIR, 'data');      // 绿色版：数据在程序旁
  if (!PACKAGED) return path.resolve(SRC_ROOT, '..', 'VF_electron_home');
  return path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'HoneyVF');                           // 和 4.2 客户端同一个数据目录
}
const HOME = resolveHome();
const LOGS = path.join(HOME, 'logs');
app.setPath('userData', path.resolve(process.env.VF_USER_DATA || path.join(HOME, 'electron')));   // 必须在单实例锁之前（锁按 userData 区分）
fs.mkdirSync(LOGS, { recursive: true });

const LOG_FILE = path.join(LOGS, 'electron.log');
try { if (fs.statSync(LOG_FILE).size > 2 * 1024 * 1024) fs.renameSync(LOG_FILE, LOG_FILE + '.1'); } catch { /* 没有 */ }
function log(m) {
  const line = `${new Date().toISOString().replace('T', ' ').slice(0, 19)} [${process.pid}] ${m}\n`;
  try { fs.appendFileSync(LOG_FILE, line); } catch { /* */ }
  if (DEV) process.stdout.write(line);
}

function pythonCmd() {
  if (process.env.VF_PYTHON) return { python: process.env.VF_PYTHON, entry: process.env.VF_ENTRY || '', cwd: SRC_ROOT };
  if (PACKAGED) {
    const vf = path.join(process.resourcesPath, 'vf');
    return { python: path.join(process.resourcesPath, 'python', 'python.exe'), entry: '', cwd: vf };
  }
  return { python: 'python', entry: process.env.VF_ENTRY || '', cwd: SRC_ROOT };   // dev: set VF_PYTHON for another interpreter
}

/** 外壳的图片：安装版在 resources\assets，开发时在 desktop\build（美术给的）或 desktop\.res（构建脚本生成的占位）。 */
function asset(name) {
  const c = PACKAGED ? [path.join(process.resourcesPath, 'assets', name)]
    : [path.join(__dirname, '..', 'build', name), path.join(__dirname, '..', '.res', name), path.join(SRC_ROOT, 'web', 'public', 'brand', name)];
  return c.find((p) => fs.existsSync(p)) || null;
}
const logoPng = () => asset('icon.png') || [path.join(process.resourcesPath || '', 'vf', 'web', 'dist', 'logo.png'), path.join(SRC_ROOT, 'web', 'public', 'logo.png'),
  path.join(SRC_ROOT, 'web', 'dist', 'logo.png')].find((p) => fs.existsSync(p)) || null;
const windowIcon = () => asset('icon.ico') || logoPng() || undefined;

// ---------------------------------------------------------------- 状态
const prefs = new Prefs(app.getPath('userData'));
const py = pythonCmd();
const backend = new Backend({ ...py, home: HOME, log, port: Number(process.env.VF_BACKEND_PORT || 0) });
let splash = null, main = null, tray = null, closeWin = null;
let splashLast = { status: '启动本地服务…' };
let quitting = false, cleaned = false, starting = false;
let nativeInfo = null, seq = 0, lastRecentKey = '', lastBadge = -1, pollTimer = null;
let pendingOpen = null;                   // 启动时命令行带的文件（还没开窗口）
const listening = new Set();              // 当前页面注册了哪些事件（preload 报上来的）
const T = { notifications: [], lastArgs: null, shown: 0, events: [] };   // 测试用（tests/electron_smoke.js 在主进程里读 global.__vf）

function parseArgs(argv, cwd) {
  const out = { files: [], links: [], plant: null, path: null };
  for (let i = 1; i < argv.length; i++) {
    const a = argv[i];
    if (!a) continue;
    if (a === '--open-plant' && argv[i + 1]) { out.plant = argv[++i]; continue; }
    if (a === '--open-path' && argv[i + 1]) { const p = argv[++i]; if (p.startsWith('/') && !p.startsWith('//')) out.path = p; continue; }
    if (a === '--home') { i++; continue; }
    if (/^vfactory:\/\//i.test(a)) { out.links.push(a); continue; }
    if (a.startsWith('-')) continue;
    if (/\.(vfhw|vfplant)$/i.test(a)) {
      const p = path.resolve(cwd || process.cwd(), a);
      if (fs.existsSync(p)) out.files.push(p);
    }
  }
  return out;
}

// ---------------------------------------------------------------- 单实例
if (!app.requestSingleInstanceLock({ argv: process.argv })) {
  app.quit();
} else {
  app.on('second-instance', (_e, argv, cwd) => {
    const a = parseArgs(argv, cwd);
    T.lastArgs = a;
    log('又启动了一次：' + JSON.stringify(a));
    showMain();
    handleArgs(a);
  });
  app.whenReady().then(boot);
}

function handleArgs(a) {
  for (const f of a.files) deliver('vf:open-file', f, `/?open=${encodeURIComponent(f)}`);
  for (const l of a.links) deepLink(l);
  if (a.plant) navigate(`/p/${encodeURIComponent(a.plant)}/workbench`);
  if (a.path) navigate(a.path);
}

/** vfactory://open?file=<路径> | ?plant=<工厂编号> | ?path=/站内路径 */
function deepLink(raw) {
  let u;
  try { u = new URL(raw); } catch { return; }
  const q = u.searchParams;
  const link = { action: (u.hostname || u.pathname.replace(/^\/+/, '') || 'open').toLowerCase(), url: raw,
    file: q.get('file') || undefined, plant: q.get('plant') || undefined, path: q.get('path') || undefined };
  if (link.path && (!link.path.startsWith('/') || link.path.startsWith('//'))) link.path = undefined;
  if (link.file && !(/\.(vfhw|vfplant)$/i.test(link.file) && fs.existsSync(link.file))) link.file = undefined;
  log('链接：' + raw);
  if (listening.has('vf:deep-link')) return send('vf:deep-link', link);
  if (link.file) return deliver('vf:open-file', link.file, `/?open=${encodeURIComponent(link.file)}`);
  if (link.plant) return navigate(`/p/${encodeURIComponent(link.plant)}/workbench`);
  if (link.path) return navigate(link.path);
}

function send(ch, v) { if (main && !main.isDestroyed()) main.webContents.send(ch, v); }

/** 交给页面：页面注册了这个事件就发事件，否则带参数重新加载（换一个一次性令牌）。窗口还没开就等开窗口时带上。 */
async function deliver(ch, value, fallbackPath) {
  if (!main || !backend.info) { if (ch === 'vf:open-file') pendingOpen = value; return; }
  if (listening.has(ch)) return send(ch, value);
  await reloadAt(fallbackPath);
}

function navigate(p) {
  showMain();
  if (listening.has('vf:navigate')) return send('vf:navigate', p);
  reloadAt(p);
}

async function reloadAt(p) {
  if (!main || !backend.info) return;
  try {
    const t = await backend.ticket();
    main.loadURL(backend.base + (p || '/') + '#dt=' + encodeURIComponent(t));
  } catch (e) { log('重新加载失败：' + e.message); }
}

// ---------------------------------------------------------------- 启动
async function boot() {
  app.setAppUserModelId(APP_ID);
  Menu.setApplicationMenu(null);
  log(`启动 ${PRODUCT} ${app.getVersion()}（Electron ${process.versions.electron}${PACKAGED ? '' : '，开发版'}）数据目录 ${HOME}`);
  if (!NO_REGISTER) registerProtocol();
  pendingOpen = null;
  const a = parseArgs(process.argv, process.cwd());
  T.lastArgs = a;
  if (a.files[0]) pendingOpen = a.files[0];
  createSplash();
  createTray();
  await startAll();
  if (a.links.length || a.plant || a.path) handleArgs({ ...a, files: [] });
  updater.schedule(async () => !!(nativeInfo && nativeInfo.mode === 'server' && nativeInfo.update_url));
}

function registerProtocol() {
  try {
    if (PACKAGED) app.setAsDefaultProtocolClient('vfactory');
    else if (process.env.VF_REGISTER_PROTOCOL === '1') app.setAsDefaultProtocolClient('vfactory', process.execPath, [path.resolve(process.argv[1] || '.')]);
  } catch (e) { log('注册 vfactory:// 失败：' + e.message); }
}

async function startAll() {
  if (starting) return;
  starting = true;
  splashState({ status: '启动本地服务…', error: null });
  try {
    const info = await backend.start((s) => splashState({ status: s }));
    nativeInfo = await backend.native(0).catch(() => null);
    seq = nativeInfo ? nativeInfo.seq : 0;
    splashState({ status: '加载界面…' });
    await openMain(info.token, pendingOpen);
    pendingOpen = null;
    startPolling();
  } catch (e) {
    log('启动失败：' + e.message);
    splashFail(e.message);
  } finally { starting = false; }
}

// ---------------------------------------------------------------- 启动画面
function createSplash() {
  splash = new BrowserWindow({
    width: 640, height: 400, frame: false, resizable: false, maximizable: false, fullscreenable: false, show: false, center: true,
    title: PRODUCT, icon: windowIcon(), backgroundColor: '#f9f7f4',
    webPreferences: { preload: path.join(__dirname, 'ui', 'ui-preload.js'), contextIsolation: true, sandbox: true },
  });
  const img = asset('splash.png');
  splash.loadFile(path.join(__dirname, 'ui', 'splash.html'), { query: { version: app.getVersion(), img: img ? pathToFileURL(img).href : '' } });
  splash.once('ready-to-show', () => { if (splash && !splash.isDestroyed()) splash.show(); });
  splash.webContents.on('did-finish-load', () => splashState({}));
  splash.on('closed', () => { splash = null; if (!main && !quitting) quitApp(); });
}

function splashState(s) {
  splashLast = { ...splashLast, ...s };
  if (splash && !splash.isDestroyed()) splash.webContents.send('vf:ui-state', splashLast);
}

function splashFail(msg) {
  if (!splash) createSplash();
  const tail = tailLog(path.join(LOGS, 'vfactory.log'), 900) || tailLog(path.join(LOGS, 'backend-console.log'), 900);
  splashState({ error: msg + (tail ? '\n\n日志最后几行：\n' + tail : ''), title: '启动失败' });
  if (splash) { splash.show(); splash.focus(); }
}

function tailLog(f, n) {
  try { const s = fs.readFileSync(f, 'utf-8'); return s.slice(-n).trim(); } catch { return ''; }
}

// ---------------------------------------------------------------- 主窗口
function mainUrl(token, open) {
  return `${backend.base}/${open ? '?open=' + encodeURIComponent(open) : ''}#dt=${encodeURIComponent(token)}`;
}

function visibleOn(b) {
  return screen.getAllDisplays().some((d) => {
    const w = d.workArea;
    const ix = Math.min(b.x + b.width, w.x + w.width) - Math.max(b.x, w.x), iy = Math.min(b.y + b.height, w.y + w.height) - Math.max(b.y, w.y);
    return ix >= 120 && iy >= 60;
  });
}

/** 上次的位置和大小；显示器拔掉了（位置不在任何屏幕上）就放到主屏中间。 */
function restoredBounds() {
  const wa = screen.getPrimaryDisplay().workArea;
  const s = prefs.get('window');
  const w = Math.min(s && s.width > 400 ? s.width : 1440, wa.width), h = Math.min(s && s.height > 300 ? s.height : 900, wa.height);
  if (s && Number.isFinite(s.x) && Number.isFinite(s.y) && visibleOn({ x: s.x, y: s.y, width: w, height: h })) return { x: s.x, y: s.y, width: w, height: h, maximized: !!s.maximized };
  return { x: Math.round(wa.x + (wa.width - w) / 2), y: Math.round(wa.y + (wa.height - h) / 2), width: w, height: h, maximized: !!(s && s.maximized), moved: !!s };
}

let saveTimer = null;
function saveWindowState() {
  if (!main || main.isDestroyed()) return;
  const b = main.getNormalBounds();
  prefs.set('window', { x: b.x, y: b.y, width: b.width, height: b.height, maximized: main.isMaximized() });
}

function openMain(token, open) {
  return new Promise((resolve, reject) => {
    const b = restoredBounds();
    if (b.moved) log('上次的窗口位置不在任何显示器上，放回主屏中间');
    main = new BrowserWindow({
      x: b.x, y: b.y, width: b.width, height: b.height, minWidth: 960, minHeight: 600, show: false, title: PRODUCT, icon: windowIcon(),
      backgroundColor: '#f3f6fa', autoHideMenuBar: true,
      webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, nodeIntegration: false, spellcheck: false },
    });
    main.setMenuBarVisibility(false);
    const wc = main.webContents;
    let ready = false, loaded = false, done = false;
    const finish = () => {
      if (done || !ready || !loaded) return;
      done = true;
      if (b.maximized) main.maximize();
      main.show();
      T.shown++;
      if (splash && !splash.isDestroyed()) splash.destroy();
      splash = null;
      resolve();
    };
    main.once('ready-to-show', () => { ready = true; finish(); });
    wc.on('did-finish-load', () => {
      if (loaded) return;
      loaded = true;
      if (nativeInfo && nativeInfo.mode === 'server') splashState({ status: '连接服务器…' });
      setTimeout(finish, nativeInfo && nativeInfo.mode === 'server' ? 400 : 0);
    });
    wc.on('did-fail-load', (_e, code, desc, url, isMain) => {
      if (!isMain || code === -3) return;                // -3 = 被新的导航取消，不算
      log(`页面没加载出来 ${code} ${desc} ${url}`);
      if (!done) { done = true; const w = main; main = null; w.destroy(); reject(new Error(`界面没有加载出来（${desc}）`)); }
    });
    wc.on('did-navigate', () => listening.clear());     // 整页导航：页面重新注册事件
    wc.on('render-process-gone', (_e, d) => { log('页面进程退出：' + d.reason); if (d.reason !== 'clean-exit' && !quitting) reloadAt(currentPath()); });
    wc.on('before-input-event', (e, input) => shortcut(e, input));
    wc.setWindowOpenHandler(({ url }) => openHandler(url));
    wc.on('will-navigate', (e, url) => {
      if (url.startsWith(backend.base + '/')) return;
      e.preventDefault();
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    });
    main.on('resize', () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveWindowState, 600); });
    main.on('move', () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveWindowState, 600); });
    main.on('close', (e) => onMainClose(e));
    main.on('closed', () => { main = null; });
    main.loadURL(mainUrl(token, open)).catch(() => { /* did-fail-load 里处理 */ });
  });
}

function currentPath() {
  try { const u = new URL(main.webContents.getURL()); return u.pathname + u.search; } catch { return '/'; }
}

function openHandler(url) {
  if (!url || url === 'about:blank') return { action: 'allow' };
  // 本机 MES（蜂元教学 MES，内嵌在 /mes 页面里，端口不同）：它的下载和新窗口（追溯打印、车间大屏）也留在客户端里
  const mesLocal = /^http:\/\/127\.0\.0\.1:\d+\//.test(url) && !(backend.info && url.startsWith(backend.base + '/'));
  if (mesLocal) {
    if (new URL(url).pathname.startsWith('/api/')) { main.webContents.downloadURL(url); return { action: 'deny' }; }
    return { action: 'allow', overrideBrowserWindowOptions: { autoHideMenuBar: true, icon: windowIcon(), backgroundColor: '#ffffff' } };
  }
  if (backend.info && url.startsWith(backend.base + '/')) {
    const p = new URL(url).pathname;
    if (p.startsWith('/api/')) { main.webContents.downloadURL(url); return { action: 'deny' }; }   // 网页里的"下载"：直接下载（会弹出保存对话框）
    return { action: 'allow', overrideBrowserWindowOptions: { autoHideMenuBar: true, icon: windowIcon(), backgroundColor: '#ffffff' } };
  }
  if (/^https?:\/\//i.test(url)) shell.openExternal(url);
  return { action: 'deny' };
}

/** 菜单栏隐藏了，常用快捷键自己处理。 */
function shortcut(e, i) {
  if (i.type !== 'keyDown') return;
  const k = i.key.toLowerCase(), ctrl = i.control || i.meta;
  const wc = main.webContents;
  if (DEBUG && ((ctrl && i.shift && k === 'i') || k === 'f12')) { wc.toggleDevTools(); e.preventDefault(); return; }
  if (k === 'f5' || (ctrl && k === 'r')) { wc.reload(); e.preventDefault(); return; }
  if (k === 'f11') { main.setFullScreen(!main.isFullScreen()); e.preventDefault(); return; }
  if (ctrl && (k === '=' || k === '+' || k === 'add')) { wc.setZoomLevel(Math.min(wc.getZoomLevel() + 0.5, 4)); e.preventDefault(); return; }
  if (ctrl && (k === '-' || k === 'subtract')) { wc.setZoomLevel(Math.max(wc.getZoomLevel() - 0.5, -3)); e.preventDefault(); return; }
  if (ctrl && k === '0') { wc.setZoomLevel(0); e.preventDefault(); }
}

function showMain() {
  if (!main || main.isDestroyed()) return;
  if (main.isMinimized()) main.restore();
  if (!main.isVisible()) main.show();
  main.focus();
}

// ---------------------------------------------------------------- 关闭按钮
function onMainClose(e) {
  if (quitting) { saveWindowState(); return; }
  e.preventDefault();
  saveWindowState();
  const b = prefs.get('closeBehaviour');
  if (b === 'tray') return hideToTray();
  if (b === 'quit') return quitApp();
  askClose();
}

function askClose() {
  if (closeWin && !closeWin.isDestroyed()) { closeWin.focus(); return; }
  closeWin = new BrowserWindow({
    parent: main && main.isVisible() ? main : undefined, modal: !!(main && main.isVisible()), width: 470, height: 290, useContentSize: true,
    resizable: false, minimizable: false, maximizable: false, fullscreenable: false, show: false, title: '关闭' + PRODUCT, icon: windowIcon(),
    autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, 'ui', 'ui-preload.js'), contextIsolation: true, sandbox: true },
  });
  closeWin.setMenu(null);
  closeWin.loadFile(path.join(__dirname, 'ui', 'close.html'));
  closeWin.once('ready-to-show', () => closeWin && closeWin.show());
  closeWin.on('closed', () => { closeWin = null; });
}

function closeChoice(d) {
  if (closeWin && !closeWin.isDestroyed()) closeWin.destroy();
  closeWin = null;
  if (!d || d.choice === 'cancel') return;
  if (d.remember && ['tray', 'quit'].includes(d.choice)) prefs.set('closeBehaviour', d.choice);
  if (d.choice === 'tray') hideToTray(); else quitApp();
}

function hideToTray() {
  if (main && !main.isDestroyed()) main.hide();
  if (!prefs.get('trayNotified')) {
    prefs.set('trayNotified', true);
    const body = '蜂元虚拟工厂还在后台运行（本机工厂、待交作业照常）。点托盘图标打开，右键菜单里可以退出。';
    T.notifications.push({ title: PRODUCT, body, kind: 'tray' });
    if (tray && !tray.isDestroyed()) tray.displayBalloon({ title: PRODUCT, content: body, iconType: 'info', noSound: true });
  }
}

function quitApp() { quitting = true; app.quit(); }

app.on('before-quit', (e) => {
  quitting = true;
  if (cleaned) return;
  e.preventDefault();
  cleanup().finally(() => { cleaned = true; app.quit(); });
});
app.on('window-all-closed', () => { if (quitting) app.quit(); });   // 窗口都关了但还在托盘里：不退出

let cleaning = null;
function cleanup() {
  if (cleaning) return cleaning;
  cleaning = (async () => {
    log('退出：停止本地服务');
    clearInterval(pollTimer);
    saveWindowState();
    try { await backend.stop(); } catch (e) { log('停止本地服务出错：' + e.message); }
    if (tray && !tray.isDestroyed()) tray.destroy();
    log('已退出');
  })();
  return cleaning;
}

// ---------------------------------------------------------------- 本地服务意外退出
backend.on('died', async (x) => {
  if (quitting) return;
  clearInterval(pollTimer);
  const parent = main && !main.isDestroyed() && main.isVisible() ? main : undefined;
  for (;;) {
    const r = await dialog.showMessageBox(parent, {
      type: 'error', title: PRODUCT, message: '本地服务意外退出了',
      detail: `退出码 ${x.code}${x.error ? '（' + x.error + '）' : ''}。没保存的改动可能丢了；本机工厂文件和待交作业还在。\n日志在 ${LOGS}`,
      buttons: ['重启本地服务', '查看日志', '退出'], defaultId: 0, cancelId: 2, noLink: true,
    });
    if (r.response === 1) { shell.openPath(LOGS); continue; }
    if (r.response === 2) return quitApp();
    break;
  }
  try {
    const info = await backend.start();
    nativeInfo = await backend.native(0).catch(() => null);
    seq = nativeInfo ? nativeInfo.seq : 0;
    listening.clear();
    if (main && !main.isDestroyed()) main.loadURL(mainUrl(info.token));
    else await openMain(info.token);
    startPolling();
  } catch (e) { splashFail(e.message); }
});

// ---------------------------------------------------------------- 托盘
/** 任务栏是不是深色：注册表 SystemUsesLightTheme（任务栏/开始菜单的主题，和应用的深浅色分开设），读不到再看 nativeTheme。 */
function taskbarDark() {
  if (process.platform === 'win32') {
    try {
      const out = require('child_process').execFileSync('reg.exe', ['query', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize', '/v', 'SystemUsesLightTheme'],
        { windowsHide: true, timeout: 3000, encoding: 'utf-8' });
      const m = out.match(/SystemUsesLightTheme\s+REG_DWORD\s+0x([0-9a-f]+)/i);
      if (m) return parseInt(m[1], 16) === 0;
    } catch { /* 没有这个值（老系统）：Windows 10 以前任务栏都是深色 */ }
  }
  return nativeTheme.shouldUseDarkColorsForSystemIntegratedUI ?? nativeTheme.shouldUseDarkColors;
}

function trayImage() {
  const dark = taskbarDark();
  T.trayTheme = dark ? 'dark' : 'light';
  const base = dark ? 'tray-dark' : 'tray';         // tray-dark-* 是给深色任务栏的（浅色图形）
  const p16 = asset(base + '-16.png') || asset('tray-16.png'), p32 = asset(base + '-32.png') || asset('tray-32.png');
  let img = p16 ? nativeImage.createFromPath(p16) : nativeImage.createEmpty();
  if (!img.isEmpty() && p32) { try { img.addRepresentation({ scaleFactor: 2, buffer: fs.readFileSync(p32) }); } catch { /* */ } }
  if (img.isEmpty() && logoPng()) img = nativeImage.createFromPath(logoPng()).resize({ width: 32, height: 32, quality: 'best' });
  if (img.isEmpty()) img = badgeImage(0);
  return img;
}

function createTray() {
  if (tray) return;
  tray = new Tray(trayImage());
  tray.setToolTip(PRODUCT);
  tray.on('click', () => showMain());
  tray.on('double-click', () => showMain());
  tray.on('balloon-click', () => showMain());
  nativeTheme.on('updated', () => { if (tray && !tray.isDestroyed()) tray.setImage(trayImage()); });
  refreshTray();
}

function trayItems() {
  const n = nativeInfo || {};
  const recent = (n.recent || []).slice(0, 8);
  const ob = n.outbox || {};
  const st = !n.user ? '作业提交状态：没有登录' : ob.waiting ? `作业提交状态：${ob.waiting} 份待交（联网后自动交）` : ob.failed ? `作业提交状态：${ob.failed} 份被服务器拒收` : '作业提交状态：没有待交的作业';
  return [
    { id: 'open', label: '打开主窗口', click: () => showMain() },
    { id: 'recent', label: '最近的工厂', submenu: recent.length ? recent.map((r) => ({ label: `${r.name || r.pid}${r.local ? '（本机）' : ''}`, click: () => navigate(`/p/${encodeURIComponent(r.pid)}/workbench`) }))
      : [{ label: '（还没有打开过工厂）', enabled: false }] },
    { id: 'outbox', label: st, click: () => navigate('/settings'), enabled: !!n.user },
    { type: 'separator' },
    { id: 'update', label: '检查更新', click: () => manualUpdateCheck() },
    { id: 'settings', label: '设置', click: () => navigate('/settings'), enabled: !!n.user },
    { type: 'separator' },
    { id: 'quit', label: '退出', click: () => quitApp() },
  ];
}

function refreshTray() {
  if (!tray || tray.isDestroyed()) return;
  const items = trayItems();
  T.trayMenu = items.map((x) => x.label || '—');
  tray.setContextMenu(Menu.buildFromTemplate(items));
  const ob = (nativeInfo && nativeInfo.outbox) || {};
  tray.setToolTip(PRODUCT + (ob.waiting ? `（${ob.waiting} 份作业待交）` : ''));
}

async function manualUpdateCheck() {
  const s = await updater.check(true);
  const parent = main && main.isVisible() ? main : undefined;
  const type = s.status === 'error' ? 'warning' : 'info';
  dialog.showMessageBox(parent, { type, title: '检查更新', message: s.message || '检查完了', buttons: ['好'], noLink: true });
  return s;
}

// ---------------------------------------------------------------- 轮询本地服务：托盘、跳转列表、角标、通知
function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(poll, Number(process.env.VF_POLL_MS || 10000));
  poll();
}

let polling = false;
async function poll() {
  if (polling || !backend.info) return;
  polling = true;
  try {
    const n = await backend.native(seq);
    nativeInfo = n;
    for (const ev of n.events || []) onEvent(ev);
    seq = n.seq;
    const rk = JSON.stringify((n.recent || []).map((r) => [r.pid, r.name, r.local]));
    if (rk !== lastRecentKey) { lastRecentKey = rk; updateJumpList(n.recent || []); }
    setBadge((n.outbox || {}).waiting || 0);
    refreshTray();
  } catch (e) {
    if (!/timeout/.test(e.message)) log('读本地服务信息失败：' + e.message);
  } finally { polling = false; }
}

const EVENT_TEXT = {
  submitted: (t) => ['作业已提交', `「${t}」已经交给服务器，服务器重新评分后在课程里能看到成绩。`],
  queued: (t) => ['已排队，联网后自动提交', `现在连不上服务器：「${t}」已存在这台电脑上，联网后自动交。`],
  resent: (t) => ['已自动补交', `「${t}」已经交给服务器（离线时交的）。`],
};
function onEvent(ev) {
  T.events.push(ev);
  const f = EVENT_TEXT[ev.kind];
  if (f) notify(...f(ev.title || '作业'));
}

function notify(title, body) {
  T.notifications.push({ title, body });
  log(`通知：${title} ${body}`);
  try {
    if (Notification.isSupported()) {
      const n = new Notification({ title, body, icon: logoPng() || undefined, silent: false });
      n.on('click', () => showMain());
      n.show();
      return true;
    }
  } catch (e) { log('系统通知失败：' + e.message); }
  if (tray && !tray.isDestroyed()) tray.displayBalloon({ title, content: body, iconType: 'info' });
  return true;
}

function setBadge(n) {
  if (n === lastBadge || !main || main.isDestroyed()) return;
  lastBadge = n;
  T.badge = n;
  if (process.platform === 'win32') main.setOverlayIcon(n > 0 ? badgeImage(n) : null, n > 0 ? `${n} 份作业待交` : '');
  else app.setBadgeCount(n);
}

function updateJumpList(recent) {
  if (process.platform !== 'win32' || NO_REGISTER) return;
  const q = (s) => `"${String(s).replace(/"/g, '')}"`;
  const pre = PACKAGED ? '' : q(path.resolve(process.argv[1] || '.')) + ' ';
  const items = recent.slice(0, 8).map((r) => ({ type: 'task', title: r.name || r.pid, description: `${r.local ? '本机工厂' : '服务器上的工厂'} ${r.pid}`,
    program: process.execPath, args: `${pre}--open-plant ${q(r.pid)}`, iconPath: process.execPath, iconIndex: 0 }));
  try {
    const res = app.setJumpList([
      ...(items.length ? [{ type: 'custom', name: '最近的工厂', items }] : []),
      { type: 'tasks', items: [{ type: 'task', title: '设置', description: '打开客户端设置', program: process.execPath, args: `${pre}--open-path /settings`, iconPath: process.execPath, iconIndex: 0 }] },
    ]);
    if (res !== 'ok') log('跳转列表：' + res);
  } catch (e) { log('跳转列表失败：' + e.message); }
}

// ---------------------------------------------------------------- 自动更新
const updater = new Updater({
  log,
  notify,
  configDirs: [app.getPath('userData'), PACKAGED ? process.resourcesPath : path.join(__dirname, '..')],
  feedFromBackend: async () => { const n = nativeInfo || (backend.info ? await backend.native(seq) : {}); return n.mode === 'server' ? n.update_url || '' : ''; },
  ask: async (i) => {
    const parent = main && main.isVisible() ? main : undefined;
    const r = await dialog.showMessageBox(parent, { type: 'info', title: '有新版本', message: `蜂元虚拟工厂 ${i.version} 已经下载好了`,
      detail: '现在重启就装上新版本（没保存的改动请先保存）；也可以下次启动时再装。', buttons: ['现在重启更新', '下次启动时'], defaultId: 0, cancelId: 1, noLink: true });
    return r.response === 0;
  },
  beforeInstall: async () => { quitting = true; await cleanup(); cleaned = true; },
});

// ---------------------------------------------------------------- 网页 ↔ 外壳
const fromMain = (e) => !!(main && !main.isDestroyed() && e.sender === main.webContents && backend.info && String(e.senderFrame && e.senderFrame.url).startsWith(backend.base + '/'));
const fromUi = (e) => String(e.senderFrame && e.senderFrame.url).startsWith('file:');
const handle = (ch, fn) => ipcMain.handle(ch, (e, arg) => { if (!fromMain(e)) throw new Error('不允许'); return fn(arg, e); });

handle('vf:app-info', () => ({
  version: app.getVersion(), backendVersion: nativeInfo && nativeInfo.version, electron: process.versions.electron, chrome: process.versions.chrome,
  packaged: PACKAGED, home: HOME, logs: LOGS, userData: app.getPath('userData'), exe: process.execPath, closeBehaviour: prefs.get('closeBehaviour'),
  updateUrl: updater.state.url || '', update: updater.state,
}));
handle('vf:open-dialog', async (o) => {
  const r = await dialog.showOpenDialog(main, { title: o.title || '打开', filters: o.filters, defaultPath: prefs.get('lastDir') || undefined,
    properties: ['openFile', ...(o.multi ? ['multiSelections'] : [])] });
  if (!r.canceled && r.filePaths[0]) prefs.set('lastDir', path.dirname(r.filePaths[0]));
  return r.canceled ? [] : r.filePaths;
});
handle('vf:save-dialog', async (o) => {
  const name = String(o.defaultName || '未命名').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 120);
  const ext = path.extname(name).replace('.', '');
  const NAMES = { vfhw: '蜂元作业包', vfplant: '蜂元工厂文件', xlsx: 'Excel 表格', docx: 'Word 文档', pptx: 'PowerPoint 演示文稿', csv: 'CSV', json: 'JSON', pdf: 'PDF' };
  const filters = o.filters || (ext ? [{ name: NAMES[ext] || ext.toUpperCase(), extensions: [ext] }, { name: '所有文件', extensions: ['*'] }] : undefined);
  const r = await dialog.showSaveDialog(main, { title: '保存', defaultPath: path.join(prefs.get('lastDir') || app.getPath('documents'), name), filters });
  if (r.canceled || !r.filePath) return null;
  if (o.data !== undefined && o.data !== null) fs.writeFileSync(r.filePath, Buffer.from(o.data instanceof ArrayBuffer ? new Uint8Array(o.data) : o.data));
  prefs.set('lastDir', path.dirname(r.filePath));
  return r.filePath;
});
handle('vf:notify', (o) => notify(String(o.title || PRODUCT).slice(0, 80), String(o.body || '').slice(0, 300)));
handle('vf:close-behaviour', (v) => {
  if (v && ['ask', 'tray', 'quit'].includes(v)) prefs.set('closeBehaviour', v);
  return prefs.get('closeBehaviour');
});
handle('vf:open-logs', () => shell.openPath(LOGS));
handle('vf:check-updates', () => updater.check(true));
handle('vf:badge', (n) => { setBadge(Math.max(0, Math.min(999, n | 0))); return true; });
ipcMain.on('vf:refresh', (e) => { if (fromMain(e)) setTimeout(poll, 300); });
ipcMain.on('vf:reload', (e) => { if (fromMain(e)) reloadAt(currentPath()); });      // 4.6.2 网页文件换了新版本：重新打开当前页
ipcMain.on('vf:listening', (e, ch) => { if (fromMain(e)) listening.add(String(ch)); });
ipcMain.on('vf:ui', (e, m) => {
  if (!fromUi(e) || !m) return;
  if (m.action === 'retry') { splashState({ error: null, status: '启动本地服务…' }); startAll(); }
  else if (m.action === 'logs') shell.openPath(LOGS);
  else if (m.action === 'quit') quitApp();
  else if (m.action === 'close-choice') closeChoice(m.data);
});

// 测试用（tests/electron_smoke.js 用 electronApp.evaluate 读）
global.__vf = {
  T, prefs, backend, updater, HOME, LOGS,
  get main() { return main; }, get splash() { return splash; }, get tray() { return tray; }, get closeWin() { return closeWin; },
  get nativeInfo() { return nativeInfo; }, showMain, poll, hideToTray, navigate, refreshTray, trayItems: () => trayItems().map((x) => x.label || '—'),
};
