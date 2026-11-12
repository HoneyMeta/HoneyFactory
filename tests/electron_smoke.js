// Electron 客户端（desktop/）冒烟测试：用 Playwright 的 _electron 启动外壳（开发版跑源码，或 VF_ELECTRON_EXE 指定的打包版），自己建临时数据目录。
//   node tests/electron_smoke.js
// 环境变量：VF_ELECTRON_EXE   测打包好的 HoneyVF.exe（dist-electron\win-unpacked\HoneyVF.exe 或安装目录里的）；不设 = desktop\node_modules\electron + 源码
//           VF_PYTHON / VF_ENTRY 开发版用的解释器和启动脚本；SHOT_DIR 截图目录；VF_TEST_KEEP=1 保留临时目录
// 覆盖：启动画面 → 主窗口出登录页（启动画面关掉）；托盘存在、菜单项；关闭按钮第一次问（记住选择 → 最小化到托盘 + 第一次的托盘提示）；
//       单机登录；window.vfNative 桥；单实例（第二次启动带 .vfplant → 交给第一个实例，页面打开文件）；最近的工厂；
//       自动更新（本地假更新源，更新的版本号 99.0.0）；退出时本地服务一起退出；窗口位置记忆；显示器拔掉后窗口回到主屏；命令行带 .vfplant 启动。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const { spawn } = require('child_process');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));

const ROOT = path.resolve(__dirname, '..');
const DESK = path.join(ROOT, 'desktop');
const EXE = process.env.VF_ELECTRON_EXE || '';
const OUT = process.env.SHOT_DIR || path.join(ROOT, 'data', 'ui_electron');
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'vf-electron-'));
const HOME = path.join(WORK, 'home');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(typeof detail === 'string' ? detail : JSON.stringify(detail)).slice(0, 260)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pidAlive = (pid) => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };

function bin() { return EXE || require(path.join(DESK, 'node_modules', 'electron')); }
function baseArgs() { return EXE ? [] : [DESK]; }
function env(extra = {}) {
  const e = { ...process.env, VF_HOME: HOME, VF_NO_REGISTER: '1', VF_POLL_MS: '1500', VF_UPDATE_NO_DOWNLOAD: '1', VF_UPDATE_DELAY_MS: '4000', ...extra };
  if (!EXE) Object.assign(e, { VF_SOURCE: process.env.VF_SOURCE || ROOT, VF_PYTHON: process.env.VF_PYTHON || 'python', VF_ENTRY: process.env.VF_ENTRY || '' });
  else for (const k of ['VF_PYTHON', 'VF_ENTRY', 'VF_SOURCE']) delete e[k];
  delete e.ELECTRON_RUN_AS_NODE;
  return e;
}
const launch = (args = [], extra = {}) => pw._electron.launch({ executablePath: bin(), args: [...baseArgs(), '--lang=zh-CN', ...args], env: env(extra), timeout: 180000 });

async function mainPage(app, ms = 240000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    for (const w of app.windows()) if (w.url().startsWith('http://127.0.0.1')) return w;
    await sleep(250);
  }
  throw new Error('主窗口没出来');
}
async function waitWin(app, part, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    for (const w of app.windows()) if (w.url().includes(part)) return w;
    await sleep(150);
  }
  return null;
}
const shot = async (page, name) => { try { await page.screenshot({ path: path.join(OUT, name) }); console.log('  截图', name); } catch (e) { console.log('  截图失败', name, e.message); } };
const vf = (app, fn, arg) => app.evaluate(fn, arg);

/** 假更新源：latest.yml 说有 99.0.0 */
function feed() {
  return new Promise((resolve) => {
    const s = http.createServer((req, r) => {
      if (req.url.startsWith('/latest.yml')) {
        r.writeHead(200, { 'Content-Type': 'text/yaml' });
        r.end('version: 99.0.0\nfiles:\n  - url: HoneyVF-Setup-99.0.0.exe\n    sha512: ' + 'A'.repeat(86) + '==\n    size: 1024\npath: HoneyVF-Setup-99.0.0.exe\nsha512: ' + 'A'.repeat(86) + "==\nreleaseDate: '2026-11-03T00:00:00.000Z'\n");
        s.hits = (s.hits || 0) + 1;
      } else { r.writeHead(404); r.end(); }
    });
    s.listen(0, '127.0.0.1', () => resolve(s));
  });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  if (EXE) {   // 4.7：蜂元教学 MES 在 resources\vf\vfmes（5.0.1 起页面在虚拟工厂自己的网页里，不再带 web-mes\dist；-NoMes 打的包这一条会失败）
    const R = path.join(path.dirname(EXE), 'resources');
    ok('打包版带蜂元教学 MES（resources\\vf\\vfmes；没有 web-mes、旧的 resources\\mes）', fs.existsSync(path.join(R, 'vf', 'vfmes', '__main__.py'))
      && !fs.existsSync(path.join(R, 'vf', 'web-mes')) && !fs.existsSync(path.join(R, 'mes')) && !fs.existsSync(path.join(R, 'vf', 'vfmes', 'agent')), R);
  }
  const fd = await feed();
  const FEED = `http://127.0.0.1:${fd.address().port}/`;
  let app;
  try {
    // ================================================================ 1. 第一次启动：启动画面 → 登录页
    const t0 = Date.now();
    app = await launch([], { VF_UPDATE_URL: FEED });
    await app.firstWindow();
    const sp = await waitWin(app, 'splash.html', 15000);
    const firstMain = app.windows().some((w) => w.url().startsWith('http://127.0.0.1'));
    ok('启动画面先出来（主窗口还没出来）', sp && !firstMain, sp && sp.url().split('?')[0].slice(-20));
    await sp.waitForSelector('#status', { timeout: 10000 }).catch(() => {});
    const st = await sp.locator('#status').textContent().catch(() => '');
    const ver = await sp.locator('#ver').textContent().catch(() => '');
    ok('启动画面：进度文字 + 版本号', /启动本地服务|加载界面|连接服务器/.test(st) && /版本/.test(ver), `${st} / ${ver}`);
    await shot(sp, 'e01-splash.png');
    const spb = await vf(app, () => { const s = global.__vf.splash; return s && !s.isDestroyed() ? { ...s.getBounds(), frame: s.isResizable() } : null; });
    ok('启动画面尺寸 640×400', spb && spb.width === 640 && spb.height === 400, spb);
    const page = await mainPage(app);
    await page.waitForSelector('text=不连服务器', { timeout: 120000 });
    ok(`主窗口出登录页（${((Date.now() - t0) / 1000).toFixed(1)} 秒）`, true);
    await sleep(500);
    const after = await vf(app, () => ({ splash: !!global.__vf.splash, visible: global.__vf.main.isVisible(), shown: global.__vf.T.shown, title: global.__vf.main.getTitle() }));
    ok('主窗口显示后启动画面关掉了', !after.splash && after.visible && after.shown === 1, after);
    await shot(page, 'e02-login.png');

    // ================================================================ 2. 托盘
    const tr = await vf(app, () => ({ ok: !!global.__vf.tray && !global.__vf.tray.isDestroyed(), menu: global.__vf.trayItems(), theme: global.__vf.T.trayTheme }));
    ok('托盘图标在（主进程里看）', tr.ok, tr.theme);
    ok('托盘菜单：打开主窗口 / 最近的工厂 / 作业提交状态 / 检查更新 / 设置 / 退出', ['打开主窗口', '最近的工厂', '检查更新', '设置', '退出'].every((x) => tr.menu.includes(x))
      && tr.menu.some((x) => x.startsWith('作业提交状态')), tr.menu);

    // ================================================================ 3. 关闭按钮：第一次问
    ok('关闭行为默认是"问"', (await vf(app, () => global.__vf.prefs.get('closeBehaviour'))) === 'ask');
    await vf(app, () => { global.__vf.main.close(); });
    const cw = await waitWin(app, 'close.html');
    ok('第一次点关闭：弹出"最小化到托盘 / 退出"询问框', !!cw);
    if (cw) {
      await cw.waitForSelector('#bOk');
      await shot(cw, 'e03-close-dialog.png');
      ok('询问框有"记住我的选择"', (await cw.locator('label').textContent()).includes('记住我的选择'));
      await cw.click('#oTray');
      await cw.check('#remember');
      await cw.click('#bOk');
      await sleep(800);
    }
    const cl = await vf(app, () => ({ visible: global.__vf.main.isVisible(), b: global.__vf.prefs.get('closeBehaviour'), n: global.__vf.T.notifications.filter((x) => x.kind === 'tray').length,
      dlg: !!global.__vf.closeWin }));
    ok('选"最小化到托盘"并记住：窗口藏起来、记下选择、第一次提示托盘', !cl.visible && cl.b === 'tray' && cl.n === 1 && !cl.dlg, cl);
    await vf(app, () => global.__vf.main.close());
    await sleep(500);
    ok('记住以后再点关闭：不再问，直接到托盘', !(await waitWin(app, 'close.html', 1500)) && (await vf(app, () => global.__vf.T.notifications.filter((x) => x.kind === 'tray').length)) === 1);
    await vf(app, () => global.__vf.showMain());

    // ================================================================ 4. 单机登录 + window.vfNative
    await page.click('text=不连服务器');
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60000 });
    await page.waitForTimeout(1500);
    ok('单机使用：进了首页', !page.url().includes('/login'), page.url());
    const nb = await page.evaluate(async () => ({ has: !!window.vfNative, info: await window.vfNative.getAppInfo(), cb: await window.vfNative.closeBehaviour.get(),
      keys: Object.keys(window.vfNative).sort() }));
    ok('网页里有 window.vfNative（getAppInfo、关闭行为、对话框、通知、更新、角标、事件）', nb.has && nb.cb === 'tray' && ['openFileDialog', 'saveFileDialog', 'notify', 'checkForUpdates',
      'setBadge', 'onDeepLink', 'onOpenFile', 'onNavigate', 'openLogFolder'].every((k) => nb.keys.includes(k)), nb.keys);
    ok('getAppInfo：版本、数据目录、日志目录', nb.info.version && nb.info.home === HOME && nb.info.logs.startsWith(HOME), { v: nb.info.version, e: nb.info.electron });
    ok('网页不能直接用 Node（contextIsolation + sandbox）', await page.evaluate(() => typeof window.require === 'undefined' && typeof window.process === 'undefined'));
    await page.evaluate(() => window.vfNative.closeBehaviour.set('ask'));
    ok('设置里改关闭行为（经 vfNative）→ 外壳记下', (await vf(app, () => global.__vf.prefs.get('closeBehaviour'))) === 'ask');
    await page.evaluate(() => window.vfNative.notify('测试通知', '来自网页'));
    ok('vfNative.notify → 系统通知', (await vf(app, () => global.__vf.T.notifications.map((n) => n.title))).includes('测试通知'));
    await shot(page, 'e04-home.png');

    // 一座"我的工厂"并导出成 .vfplant（给单实例 / 命令行打开文件用）
    const token = await page.evaluate(() => localStorage.getItem('vf_token'));
    const base = new URL(page.url()).origin;
    const api = async (m, u, b) => (await fetch(base + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + token }, body: b ? JSON.stringify(b) : undefined }));
    const mp = await (await api('POST', '/api/client/myplants', { name: '烟测工厂', template: 'blank' })).json();
    const vfplant = path.join(WORK, '烟测工厂.vfplant');
    fs.writeFileSync(vfplant, Buffer.from(await (await api('GET', `/api/client/myplants/${encodeURIComponent(mp.id)}/export`)).arrayBuffer()));
    ok('准备 .vfplant 文件', fs.statSync(vfplant).size > 200, mp.id);
    // 5.0.1：MES 页面在虚拟工厂的界面里，取数走本地服务的 /api/mes/* 转发（MES 没启动时 503；没登录 401）
    const mr = await api('GET', '/api/mes/me');
    const mr2 = await fetch(base + '/api/mes/me');
    ok('本地服务有本机 MES 的转发 /api/mes/*（没启动 503、没登录 401）', mr.status === 503 && mr2.status === 401, [mr.status, mr2.status]);

    // ================================================================ 5. 最近的工厂
    await page.goto(base + `/p/${encodeURIComponent(mp.id)}/workbench`);
    await page.waitForTimeout(3000);
    await vf(app, () => global.__vf.poll());
    await sleep(500);
    const rc = await vf(app, () => ({ recent: (global.__vf.nativeInfo || {}).recent || [], menu: global.__vf.trayItems() }));
    ok('进了工厂 → 托盘"最近的工厂"里有它', rc.recent[0] && rc.recent[0].pid === mp.id && rc.recent[0].name === '烟测工厂', rc.recent.map((r) => r.name));
    await vf(app, (_e, pid) => global.__vf.navigate('/'), mp.id);
    await page.waitForTimeout(800);
    ok('托盘/跳转列表的导航（onNavigate）：页面里换路由，不重新加载', new URL(page.url()).pathname === '/', page.url());

    // ================================================================ 6. 单实例：第二次启动带 .vfplant
    const t1 = Date.now();
    const second = spawn(bin(), [...baseArgs(), vfplant], { env: env(), stdio: 'ignore' });
    const code = await new Promise((r) => { const t = setTimeout(() => r('timeout'), 30000); second.on('exit', (c) => { clearTimeout(t); r(c); }); });
    ok(`第二次启动马上退出（${((Date.now() - t1) / 1000).toFixed(1)} 秒），不另起本地服务`, code === 0, code);
    const la = await vf(app, () => global.__vf.T.lastArgs);
    ok('第一个实例收到了文件路径', la && la.files && la.files[0] === vfplant, la);
    const dlg = await page.waitForSelector('[data-k="pkg-run"]', { timeout: 30000 }).catch(() => null);
    ok('页面打开了这个 .vfplant（作业包/工厂文件对话框）', !!dlg, page.url());
    if (dlg) {
      await page.waitForTimeout(800);
      await shot(page, 'e05-open-vfplant.png');
      ok('对话框认出是工厂文件', (await page.locator('.el-dialog').last().textContent()).includes('工厂'));
      await page.keyboard.press('Escape');
    }

    // ================================================================ 7. 自动更新（本地假更新源 99.0.0）
    await sleep(3500);
    const auto = await vf(app, () => global.__vf.updater.state);
    ok('启动后自动检查更新（配了更新地址）：发现 99.0.0', auto.status === 'available' && auto.version === '99.0.0', auto);
    const up = await page.evaluate(() => window.vfNative.checkForUpdates());
    ok('手动检查更新（vfNative.checkForUpdates）：有新版本 99.0.0', up.status === 'available' && up.version === '99.0.0' && fd.hits >= 2, up);
    ok('有新版本：系统通知', (await vf(app, () => global.__vf.T.notifications.map((n) => n.title))).includes('有新版本'));

    // ================================================================ 8. 窗口位置 + 退出时本地服务一起退出
    // 放得下的大小（ssh 会话里的虚拟屏幕可能只有 1024×768；主窗口最小 960×600）
    const want = await vf(app, ({ screen }) => {
      const wa = screen.getPrimaryDisplay().workArea, m = global.__vf.main;
      const b = { x: wa.x + 24, y: wa.y + 18, width: Math.max(960, Math.min(1180, wa.width - 48)), height: Math.max(600, Math.min(760, wa.height - 40)) };
      m.unmaximize(); m.setBounds(b); return b;
    });
    await sleep(1200);
    const run = JSON.parse(fs.readFileSync(path.join(HOME, 'run.json'), 'utf-8'));
    ok('本地服务在跑（run.json）', pidAlive(run.pid), run.pid);
    await app.close();
    app = null;
    await sleep(1500);
    ok('退出：本地服务（Python）也退出了', !pidAlive(run.pid), run.pid);
    const np = JSON.parse(fs.readFileSync(path.join(HOME, 'electron', 'native.json'), 'utf-8'));
    ok('窗口位置存下了', np.window && np.window.x === want.x && np.window.width === want.width, np.window);

    // ================================================================ 9. 再启动：恢复窗口位置；命令行带 .vfplant
    app = await launch([vfplant]);
    const p2 = await mainPage(app);
    const dlg2 = await p2.waitForSelector('[data-k="pkg-run"]', { timeout: 120000 }).catch(() => null);
    ok('命令行带 .vfplant 启动：记住的单机登录直接进，打开这个文件', !!dlg2, p2.url());
    const b2 = await vf(app, () => global.__vf.main.getBounds());
    ok('窗口回到上次的位置和大小', b2.x === want.x && b2.y === want.y && b2.width === want.width && b2.height === want.height, { b2, want });
    await app.close();
    app = null;

    // ================================================================ 10. 上次的位置在拔掉的显示器上 → 放回主屏
    np.window = { x: -32000, y: -32000, width: 1180, height: 760, maximized: false };
    fs.writeFileSync(path.join(HOME, 'electron', 'native.json'), JSON.stringify(np));
    app = await launch();
    await mainPage(app);
    await sleep(1500);
    const b3 = await vf(app, ({ screen }) => ({ b: global.__vf.main.getBounds(), wa: screen.getPrimaryDisplay().workArea }));
    ok('显示器没了：窗口放回主屏中间', b3.b.x >= b3.wa.x && b3.b.y >= b3.wa.y && b3.b.x + b3.b.width <= b3.wa.x + b3.wa.width + 1, b3);
    await app.close();
    app = null;
  } catch (e) {
    ok('意外出错', false, e.stack || e.message);
  } finally {
    if (app) await app.close().catch(() => {});
    fd.close();
    try { console.log('--- electron.log（最后几行）\n' + fs.readFileSync(path.join(HOME, 'logs', 'electron.log'), 'utf-8').split('\n').slice(-12).join('\n')); } catch { /* */ }
    if (process.env.VF_TEST_KEEP !== '1') fs.rmSync(WORK, { recursive: true, force: true }); else console.log('临时目录', WORK);
  }
  const n = res.filter((x) => x[1]).length;
  console.log(`\n${n}/${res.length} 通过`);
  process.exit(n === res.length ? 0 : 1);
})();
