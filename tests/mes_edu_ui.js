// 本机 MES（蜂元教学 MES，本仓库 vfmes/；5.0.1 页面并进虚拟工厂的界面 web/src/mes/）界面走查：Electron 客户端（开发版跑源码，或 VF_ELECTRON_EXE 指定的打包版）
// → 单机使用 → 左侧「MES」→ 本机 MES 自动启动（只有一座示范工厂）→ MES 页面就在虚拟工厂的界面里（侧栏 MES 菜单、面包屑，没有 iframe、没有第二套侧栏）
// → 新增工单、下达 → 「回到工厂」看工作台 → 左下角标记回到 MES → 报工、OEE → 停止 → 选工厂再打开 → 退出时 MES 跟着退出。只有浅色。
//   node tests/mes_edu_ui.js
// 环境变量：VF_ELECTRON_EXE / VF_PYTHON / VF_ENTRY / VF_SOURCE（同 electron_smoke.js）、SHOT_DIR 截图目录、VF_TEST_KEEP=1 保留临时目录
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const os = require('os');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));

const ROOT = path.resolve(__dirname, '..');
const DESK = path.join(ROOT, 'desktop');
const EXE = process.env.VF_ELECTRON_EXE || '';
const OUT = process.env.SHOT_DIR || path.join(ROOT, 'data', 'ui_mes');
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'vf-mesui-'));
const HOME = path.join(WORK, 'home');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(typeof detail === 'string' ? detail : JSON.stringify(detail)).slice(0, 260)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pidAlive = (pid) => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
const shot = async (page, name) => { try { await page.screenshot({ path: path.join(OUT, name) }); console.log('  截图', name); } catch (e) { console.log('  截图失败', name, e.message); } };

function env() {
  const e = { ...process.env, VF_HOME: HOME, VF_NO_REGISTER: '1', VF_POLL_MS: '1500', VF_UPDATE_NO_DOWNLOAD: '1' };
  if (!EXE) Object.assign(e, { VF_SOURCE: process.env.VF_SOURCE || ROOT, VF_PYTHON: process.env.VF_PYTHON || 'python', VF_ENTRY: process.env.VF_ENTRY || '' });
  else for (const k of ['VF_PYTHON', 'VF_ENTRY', 'VF_SOURCE']) delete e[k];
  delete e.VF_MES_SOURCE;                          // 4.6 的旧变量（指向 HoneyMES 仓库），已不用
  delete e.ELECTRON_RUN_AS_NODE;
  return e;
}
async function mainPage(app, ms = 240000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    for (const w of app.windows()) if (w.url().startsWith('http://127.0.0.1')) return w;
    await sleep(250);
  }
  throw new Error('主窗口没出来');
}
const vfApi = (page, method, url, body) => page.evaluate(async ([m, u, b]) => {
  const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + localStorage.getItem('vf_token') }, body: b ? JSON.stringify(b) : undefined });
  return r.json().catch(() => ({}));
}, [method, url, body]);
/** 侧栏 MES 菜单里点一页：先展开分组 */
async function side(page, group, item) {
  const g = page.locator('[data-k="menu-mes"] .el-sub-menu__title', { hasText: group }).first();
  const it = page.locator('[data-k="menu-mes"] .el-menu-item', { hasText: item }).first();
  if (!(await it.isVisible().catch(() => false))) { await g.click(); await sleep(400); }
  await it.click();
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  let app;
  try {
    app = await pw._electron.launch({ executablePath: EXE || require(path.join(DESK, 'node_modules', 'electron')), args: EXE ? ['--lang=zh-CN'] : [DESK, '--lang=zh-CN'], env: env(), timeout: 180000 });
    const page = await mainPage(app);
    await app.evaluate(({ screen }) => {
      const wa = screen.getPrimaryDisplay().workArea, m = global.__vf.main;
      m.unmaximize(); m.setBounds({ x: wa.x + 10, y: wa.y + 10, width: Math.max(1280, Math.min(1440, wa.width - 20)), height: Math.max(800, Math.min(900, wa.height - 20)) });
    }).catch(() => {});
    await page.waitForSelector('text=不连服务器', { timeout: 180000 });
    await page.click('text=不连服务器');
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 90000 });
    ok('单机使用：进了首页', !page.url().includes('/login'), page.url());

    // ---------- 左侧菜单「MES」→ 本机 MES 自动启动 ----------
    const menu = page.locator('[data-k="menu-mes"]');
    ok('左侧菜单有「MES」', await menu.count() > 0);
    const t0 = Date.now();
    const title = page.locator('[data-k="menu-mes"] > .el-sub-menu__title');
    if (await title.count()) await title.first().click(); else await menu.first().click();
    await page.waitForURL((u) => u.pathname === '/mes', { timeout: 20000 });
    await page.waitForSelector('[data-k="mes-bar"], [data-pid]', { timeout: 150000 });
    if (!(await page.locator('[data-k="mes-bar"]').count())) {        // 选不出来（不止一座 MES 认得的工厂）：选推荐的
      const cards = await page.locator('[data-pid]').evaluateAll((els) => els.map((e) => ({ pid: e.getAttribute('data-pid'), text: e.textContent })));
      await page.click(`[data-pid="${(cards.find((c) => c.text.includes('推荐')) || cards[0]).pid}"]`);
      await page.click('[data-k="mes-open"]');
    }
    await page.waitForSelector('[data-k="mes-bar"]', { timeout: 150000 });
    ok(`MES 启动并打开（${((Date.now() - t0) / 1000).toFixed(1)} 秒）`, true);
    const st = await vfApi(page, 'GET', '/api/desktop/mes');
    const pid = st.pid;
    ok('只有一座示范工厂：点「MES」就自动给它启动', st.state === 'running' && st.plants.filter((p) => p.fit).length === 1, { pid, plants: st.plants.map((p) => p.id) });
    ok('没有 iframe、没有第二套侧栏（MES 页面就在虚拟工厂的界面里）', page.frames().length === 1 && (await page.locator('iframe').count()) === 0
       && (await page.locator('.el-aside').count()) <= 1, page.frames().length);
    const menuText = (await menu.first().textContent()) || '';
    ok('侧栏 MES 菜单：核心页面都在，没有 AI / 智能体 / 审批 / 配料优化', ['生产工单', '排产与进度', '报工记录', '质量追溯', 'SPC 分析', '不合格品', 'OEE 分析', '实时监控', '库存', '能耗分析'].every((x) => menuText.includes(x))
       && !/AI|智能体|审批中心|问数|日报|知识库|配料优化|缺陷回溯|协同排产/.test(menuText), menuText.replace(/\s+/g, ' ').slice(0, 200));
    ok('右下角没有 AI 助手（教学 MES 不带 AI）', (await page.locator('.aid-root').count()) === 0);
    ok('面包屑：MES / 工作台', /MES/.test(await page.locator('[data-k="crumbs"]').textContent().catch(() => '')), await page.locator('[data-k="crumbs"]').textContent().catch(() => ''));
    const bar = await page.locator('[data-k="mes-bar"]').textContent();
    ok('状态行：运行中、工厂名', bar.includes('运行中') && bar.includes(st.plant_name), bar.replace(/\s+/g, ' ').slice(0, 160));
    let eq = 0;
    for (let i = 0; i < 40 && eq < 10; i++) { await sleep(1500); eq = Number((await page.locator('[data-k="mes-bar"]').textContent()).match(/设备 (\d+)/)?.[1] || 0); }
    ok('自动导入了设备', eq >= 10, `${eq} 台`);
    await page.waitForSelector('.page-head h2:has-text("工作台")', { timeout: 30000 });
    await sleep(2500);
    // 钥匙、令牌不在页面里；页面只和本地服务说话；只有浅色
    const cur = JSON.parse(fs.readFileSync(path.join(HOME, 'mes', 'current.json'), 'utf-8'));
    const leak = await page.evaluate((k) => {
      const ls = Object.keys(localStorage).map((x) => localStorage.getItem(x)).join(' ');
      const urls = performance.getEntriesByType('resource').map((e) => e.name);
      return { html: document.documentElement.outerHTML.includes(k), ls: ls.includes(k), mesPort: urls.filter((u) => !u.startsWith(location.origin)).length,
        dark: document.documentElement.classList.contains('dark'), theme: location.search.includes('theme=') };
    }, cur.key);
    ok('MES 的钥匙不在页面和本地存储里；页面不直接访问 MES 端口', !leak.html && !leak.ls && leak.mesPort === 0, leak);
    ok('只有浅色（没有 ?theme=、没有 html.dark）', !leak.dark && !leak.theme, leak);
    await shot(page, 'mes-02-home.png');
    for (const [w, h] of [[1280, 720], [1680, 960]]) {
      await app.evaluate(({ }, [w, h]) => { const m = global.__vf.main; m.unmaximize(); m.setContentSize(w, h); }, [w, h]).catch(() => {});
      await sleep(2500);
      await shot(page, `mes-02-home-${w}x${h}.png`);
    }
    await app.evaluate(({ screen }) => {
      const wa = screen.getPrimaryDisplay().workArea, m = global.__vf.main;
      m.setBounds({ x: wa.x + 10, y: wa.y + 10, width: Math.max(1280, Math.min(1440, wa.width - 20)), height: Math.max(800, Math.min(900, wa.height - 20)) });
    }).catch(() => {});
    await sleep(1500);

    // ---------- 新增工单 → 下达 ----------
    await side(page, '生产管理', '生产工单');
    await page.waitForURL((u) => u.pathname === '/mes/e/work_order', { timeout: 20000 });
    await page.waitForSelector('button:has-text("新增")', { timeout: 30000 });
    await page.click('button:has-text("新增")');
    const dlg = page.locator('.el-dialog:visible');
    await dlg.waitFor({ timeout: 10000 });
    const pickRef = async (label, text) => {
      await dlg.locator(`.el-form-item:has(label:text-is("${label}")) .el-select`).click();
      await page.keyboard.type(text, { delay: 30 });
      const opt = page.locator('.el-select-dropdown__item:visible', { hasText: text }).first();
      await opt.waitFor({ timeout: 10000 });
      await opt.click();
    };
    await pickRef('产品', 'SGH-450 转向器壳体');
    await pickRef('工艺路线', 'RT-SGH450');
    await dlg.locator('.el-form-item:has(label:text-is("计划数量")) input').fill('40');
    await dlg.locator('.el-form-item:has(label:text-is("客户")) input').fill('实训客户');
    await shot(page, 'mes-03-new-wo.png');
    await dlg.locator('button:has-text("保存")').click();
    await sleep(1200);
    const rowCnt = await page.locator('.el-table__row').count();
    ok('工单保存（列表里有了）', rowCnt >= 1, rowCnt);
    await page.locator('.el-table__row').first().click();
    await page.waitForSelector('.el-drawer:visible', { timeout: 10000 });
    await page.locator('.el-drawer:visible button:has-text("下达")').first().click();
    for (let i = 0; i < 10; i++) {
      await sleep(500);
      const b = page.locator('.el-message-box button:has-text("确定"), .el-dialog:visible button:has-text("确定")');
      if (await b.count()) { await b.first().click(); break; }
    }
    await sleep(1500);
    const drawerText = await page.locator('.el-drawer:visible').last().textContent().catch(() => '');
    ok('工单已下达（生成工序）', /已下达|生产中|P10|熔炼/.test(drawerText), drawerText.replace(/\s+/g, ' ').slice(0, 160));
    await shot(page, 'mes-04-wo-released.png');
    await page.keyboard.press('Escape');
    await sleep(500);
    // 导出 CSV：新窗口经本地服务转发下载（?token= 是虚拟工厂的登录）
    const csv = await page.evaluate(async () => { const r = await fetch('/api/mes/e/work_order.csv?token=' + encodeURIComponent(localStorage.getItem('vf_token'))); return [r.status, (await r.text()).slice(0, 60)]; });
    ok('导出 CSV 走本地服务转发', csv[0] === 200 && csv[1].length > 5, csv);

    // ---------- 回到工厂（让它跑起来）→ 左下角标记回到 MES ----------
    await page.click('[data-k="mes-back"]');
    await page.waitForURL((u) => u.pathname.endsWith('/workbench'), { timeout: 20000 });
    ok('「回到工厂」打开这个工厂的工作台', page.url().includes(`/p/${encodeURIComponent(pid)}/workbench`) || page.url().includes(`/p/${pid}/workbench`), page.url());
    const runRes = await page.evaluate(async (p) => {
      const r = await fetch(`/api/p/${encodeURIComponent(p)}/sim`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + localStorage.getItem('vf_token') }, body: JSON.stringify({ speed: 60, paused: false }) });
      return r.status;
    }, pid);
    ok('虚拟工厂 60× 运行', runRes === 200, runRes);
    await sleep(9000);
    const chip = page.locator('[data-k="mes-chip"]');
    ok('工作台左下角有"MES 运行中"标记（点它回到 MES）', await chip.count() > 0, await chip.textContent().catch(() => ''));
    await shot(page, 'mes-05-workbench.png');
    await sleep(40000);
    await chip.first().click();
    await page.waitForURL((u) => u.pathname === '/mes', { timeout: 20000 });
    await page.waitForSelector('[data-k="mes-bar"]', { timeout: 30000 });
    await side(page, '生产管理', '报工记录');
    await page.waitForURL((u) => u.pathname === '/mes/e/report', { timeout: 20000 });
    await page.waitForSelector('.el-table__row', { timeout: 60000 }).catch(() => {});
    const reps = await page.locator('.el-table__row').count();
    ok('回到 MES：工单在虚拟工厂里被执行（有设备自动报工）', reps > 0, `${reps} 行`);
    await shot(page, 'mes-06-reports.png');
    await side(page, '设备管理', 'OEE 分析');
    await page.waitForURL((u) => u.pathname === '/mes/equipment/oee', { timeout: 20000 });
    await sleep(4000);
    ok('OEE 页（图表）', (await page.locator('.page canvas').count()) > 0);
    await shot(page, 'mes-07-oee.png');
    await side(page, '工作台', '车间大屏');
    await page.waitForSelector('[data-k="mes-screen"] .k', { timeout: 30000 }).catch(() => {});
    await sleep(3000);
    const scrBg = await page.locator('[data-k="mes-screen"] .panel').first().evaluate((e) => getComputedStyle(e).backgroundColor).catch(() => '');
    ok('车间大屏是浅色的', /rgb\(255, 255, 255\)/.test(scrBg), scrBg);
    await shot(page, 'mes-08-screen.png');

    // ---------- 停止 → 选择页 → 再打开 → 退出 ----------
    const st1 = await vfApi(page, 'GET', '/api/desktop/mes');
    await page.click('[data-k="mes-stop"]');
    await page.waitForSelector('[data-pid]', { timeout: 20000 });
    await sleep(800);
    await shot(page, 'mes-09-pick.png');
    const st2 = await vfApi(page, 'GET', '/api/desktop/mes');
    ok('停止 MES（停了不再自动启动，显示选工厂）', st2.state === 'stopped' && !pidAlive(st1.process), { state: st2.state, proc: st1.process });
    await page.click('[data-k="mes-open"]');
    await page.waitForSelector('[data-k="mes-bar"]', { timeout: 120000 });
    const st3 = await vfApi(page, 'GET', '/api/desktop/mes');
    ok('再打开 MES', st3.state === 'running', st3.state);
    const run = JSON.parse(fs.readFileSync(path.join(HOME, 'run.json'), 'utf-8'));
    await app.close();
    app = null;
    await sleep(4000);
    ok('退出客户端：本地服务和 MES 都退出', !pidAlive(run.pid) && st3.process && !pidAlive(st3.process), { vf: run.pid, mes: st3.process });
  } catch (e) {
    ok('走查没有出错', false, e.stack || e.message);
  } finally {
    if (app) await app.close().catch(() => {});
    const bad = res.filter((r) => !r[1]).map((r) => r[0]);
    console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
    console.log('截图：', OUT);
    if (process.env.VF_TEST_KEEP !== '1') fs.rmSync(WORK, { recursive: true, force: true });
    else console.log('临时目录：', WORK);
    process.exit(bad.length ? 1 : 0);
  }
})();
