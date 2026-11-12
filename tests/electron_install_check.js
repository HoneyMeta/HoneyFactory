// 装好的 Electron 客户端端到端：用 Playwright 启动安装目录里的 HoneyVF.exe（临时数据目录），登录服务器、打开服务器上的工厂、检查更新、退出。
// 安装 / 卸载由外面的脚本做（tests/electron_install_check.ps1）。
//   VF_ELECTRON_EXE=<安装目录>\HoneyVF.exe VF_URL=http://127.0.0.1:8840 node tests/electron_install_check.js
// 服务器上要有 admin/honey123（新数据目录的默认账号）；会往服务器上传一份假的更新说明（99.0.0），测完删掉。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const os = require('os');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));

const EXE = process.env.VF_ELECTRON_EXE;
const SV = process.env.VF_URL || 'http://127.0.0.1:8840';
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_electron_install');
const HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'vf-inst-home-'));
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(typeof detail === 'string' ? detail : JSON.stringify(detail)).slice(0, 260)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = async (p, n) => { try { await p.screenshot({ path: path.join(OUT, n) }); console.log('  截图', n); } catch (e) { console.log('  截图失败', n, e.message); } };
const api = async (m, u, tok, body, raw) => {
  const r = await fetch(SV + u, { method: m, headers: { 'X-Lang': 'zh-CN', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), 'Content-Type': raw ? 'application/octet-stream' : 'application/json' },
    body: raw || (body ? JSON.stringify(body) : undefined) });
  return r.headers.get('content-type')?.includes('json') ? r.json() : r.text();
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const env = { ...process.env, VF_HOME: HOME, VF_POLL_MS: '1500', VF_UPDATE_NO_DOWNLOAD: '1', VF_UPDATE_DELAY_MS: '600000' };
  for (const k of ['VF_PYTHON', 'VF_ENTRY', 'VF_SOURCE', 'VF_UPDATE_URL', 'ELECTRON_RUN_AS_NODE']) delete env[k];
  // 临时服务器：先把 admin 的初始密码改掉（用初始密码登录时客户端会强制改密码）
  const PW = 'Vf-e2e-' + Date.now().toString(36);
  let admin = (await api('POST', '/api/login', '', { username: 'admin', password: 'honey123' })).token;
  if (admin) await api('POST', '/api/me/password', admin, { old: 'honey123', new: PW });
  admin = (await api('POST', '/api/login', '', { username: 'admin', password: PW })).token;
  ok('服务器在（admin 能登录）', !!admin, SV);
  let app;
  try {
    app = await pw._electron.launch({ executablePath: EXE, args: ['--lang=zh-CN'], env, timeout: 180000 });
    let page = null;
    for (let i = 0; i < 600 && !page; i++) { page = app.windows().find((w) => w.url().startsWith('http://127.0.0.1')) || null; if (!page) await sleep(250); }
    ok('装好的客户端启动：主窗口出来', !!page);
    const info = await app.evaluate(({ app: a }) => ({ packaged: a.isPackaged, version: a.getVersion(), exe: process.execPath, res: process.resourcesPath }));
    ok('是安装目录里的打包版', info.packaged && info.exe.toLowerCase() === EXE.toLowerCase(), info);
    await page.waitForSelector('text=不连服务器', { timeout: 120000 });
    await shot(page, 'i01-login.png');
    // ---------- 登录服务器 ----------
    const inputs = page.locator('.el-input__inner');
    await inputs.nth(0).fill(SV);
    await inputs.nth(1).fill('admin');
    await inputs.nth(2).fill(PW);
    await page.locator('button:has-text("登录")').first().click();
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60000 });
    await sleep(2500);
    for (const t of ['以后再说', '稍后', '取消', '关闭']) {                 // 初始密码提示 / 欢迎页之类的弹窗
      const b = page.locator(`.el-dialog button:has-text("${t}"), .el-message-box button:has-text("${t}")`).first();
      if (await b.isVisible().catch(() => false)) { await b.click().catch(() => {}); await sleep(400); }
    }
    ok('登录服务器后进了首页', !page.url().includes('/login'), page.url());
    await shot(page, 'i02-home.png');
    const n1 = await app.evaluate(async () => { await global.__vf.poll(); return global.__vf.nativeInfo; });
    ok('外壳知道：联网模式、账号 admin、更新地址是这台服务器', n1.mode === 'server' && n1.user === 'admin' && n1.update_url === SV + '/api/client/update/', { mode: n1.mode, u: n1.update_url });
    // ---------- 打开服务器上的工厂 ----------
    const plants = (await api('GET', '/api/overview', admin)).plants || [];
    const pid = (plants[0] || {}).id;
    ok('服务器上有工厂', !!pid, plants.map((p) => p.id));
    await page.goto(new URL(page.url()).origin + `/p/${encodeURIComponent(pid)}/workbench`);
    await page.waitForSelector('canvas', { timeout: 90000 }).catch(() => {});
    await sleep(5000);
    const wb = await page.evaluate(() => ({ canvas: document.querySelectorAll('canvas').length, title: document.title }));
    ok('打开服务器上的工厂：工作台出来（经本地服务转发）', wb.canvas > 0, wb);
    await shot(page, 'i03-workbench.png');
    await app.evaluate(async () => global.__vf.poll());
    await sleep(500);
    const rc = await app.evaluate(() => global.__vf.trayItems());
    const recent = await app.evaluate(() => (global.__vf.nativeInfo.recent || []).map((r) => r.pid));
    ok('托盘"最近的工厂"里有这个服务器工厂', recent[0] === pid, { recent, menu: rc });
    // ---------- 自动更新：从这台服务器 ----------
    const s0 = await page.evaluate(() => window.vfNative.checkForUpdates());
    ok('服务器上没放更新：检查更新报"没有找到"一类的错误（不崩）', s0.status === 'error' || s0.status === 'latest', s0);
    const yml = ['version: 99.0.0', 'files:', '  - url: HoneyVF-Setup-99.0.0.exe', '    sha512: ' + 'A'.repeat(86) + '==', '    size: 1024',
      'path: HoneyVF-Setup-99.0.0.exe', 'sha512: ' + 'A'.repeat(86) + '==', ''].join('\n');
    await api('PUT', '/api/admin/client-update/latest.yml', admin, null, Buffer.from(yml));
    const s1 = await page.evaluate(() => window.vfNative.checkForUpdates());
    ok('服务器放了 99.0.0：装好的客户端发现新版本', s1.status === 'available' && s1.version === '99.0.0' && s1.url === SV + '/api/client/update/', s1);
    await api('DELETE', '/api/admin/client-update/latest.yml', admin);
    await shot(page, 'i04-after-update-check.png');
    // ---------- 退出 ----------
    const run = JSON.parse(fs.readFileSync(path.join(HOME, 'run.json'), 'utf-8'));
    await app.close();
    app = null;
    await sleep(1500);
    let alive = true;
    try { process.kill(run.pid, 0); } catch { alive = false; }
    ok('退出后本地服务也退出了', !alive, run.pid);

    // ---------- 真的更新一次：服务器放上新版本（VF_NEXT_DIR = 另一次构建的 dist 目录）→ 后台下载 → 静默安装 → 安装目录变成新版本 ----------
    const ND = process.env.VF_NEXT_DIR;
    if (ND) {
      const yml2 = fs.readFileSync(path.join(ND, 'latest.yml'), 'utf-8');
      const nextVer = yml2.match(/^version:\s*(\S+)/m)[1], nextExe = yml2.match(/^path:\s*(.+)$/m)[1].trim();
      for (const f of [nextExe, nextExe + '.blockmap', 'latest.yml']) {
        if (fs.existsSync(path.join(ND, f))) await api('PUT', `/api/admin/client-update/${f}`, admin, null, fs.readFileSync(path.join(ND, f)));
      }
      const env2 = { ...env, VF_UPDATE_NO_PROMPT: '1' };
      delete env2.VF_UPDATE_NO_DOWNLOAD;
      app = await pw._electron.launch({ executablePath: EXE, args: ['--lang=zh-CN'], env: env2, timeout: 180000 });
      let p2 = null;
      for (let i = 0; i < 600 && !p2; i++) { p2 = app.windows().find((w) => w.url().startsWith('http://127.0.0.1')) || null; if (!p2) await sleep(250); }
      await p2.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60000 }).catch(() => {});
      ok('再打开：记住的服务器登录直接进', !p2.url().includes('/login'), p2.url());
      const t0 = Date.now();
      await app.evaluate(() => global.__vf.updater.check(true));
      let st = {};
      for (let i = 0; i < 360; i++) { st = await app.evaluate(() => global.__vf.updater.state); if (['downloaded', 'error'].includes(st.status)) break; await sleep(500); }
      ok(`从服务器后台下载了新版本 ${nextVer}（${((Date.now() - t0) / 1000).toFixed(1)} 秒）`, st.status === 'downloaded' && st.version === nextVer, st);
      if (st.status === 'downloaded') {
        const vfile = path.join(path.dirname(EXE), 'resources', 'vf', 'version.txt');
        const proc = app.process();
        const gone = new Promise((r) => proc.once('exit', r));
        await app.evaluate(async () => { await global.__vf.updater.o.beforeInstall(); global.__vf.updater.u.quitAndInstall(true, false); }).catch(() => {});
        await Promise.race([gone, sleep(30000)]);
        app = null;
        let v = '';
        for (let i = 0; i < 180; i++) { try { v = fs.readFileSync(vfile, 'utf-8').trim(); } catch { v = ''; } if (v === nextVer) break; await sleep(1000); }
        ok('"现在重启更新"：静默装好，安装目录里是新版本', v === nextVer, v);
        await sleep(5000);                                   // 安装程序收尾（写注册表）
      }
      for (const f of [nextExe, nextExe + '.blockmap', 'latest.yml']) await api('DELETE', `/api/admin/client-update/${f}`, admin);
    }
  } catch (e) {
    ok('意外出错', false, e.stack || e.message);
  } finally {
    if (app) await app.close().catch(() => {});
    try { console.log('--- electron.log\n' + fs.readFileSync(path.join(HOME, 'logs', 'electron.log'), 'utf-8').split('\n').slice(-10).join('\n')); } catch { /* */ }
    fs.rmSync(HOME, { recursive: true, force: true });
  }
  const n = res.filter((x) => x[1]).length;
  console.log(`\n${n}/${res.length} 通过`);
  process.exit(n === res.length ? 0 : 1);
})();
