// PLC 面板的空白页与示例数据（B 机；先启动 serve，PLC 开发页 vite --config web/vite.plc.config.ts，以及构建好的 web/dist）：
//   node tests/plc_empty_ui.js [没有控制单元的工厂，默认 foundry-housing]
// 没有控制单元时：侧栏/编程窗/HMI/外接 PLC 都给出“新建控制单元”“从实训场景载入…”按钮；练习 PLC 有示范程序和示范画面；
// 在真正的工作台里点“新建控制单元”会在模型里加一个控制单元块并打开控制单元编辑器。浅色截图（5.0.1 只有浅色）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const API = process.env.VF_URL || 'http://127.0.0.1:8820';
const DEV = process.env.PLC_DEV || 'http://127.0.0.1:5182';
const OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'shots');
const PID = process.argv[2] || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const tok = (await (await fetch(API + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const api = async (m, u, body) => (await fetch(API + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: body ? JSON.stringify(body) : undefined })).json();
  const cells = (await api('GET', `/api/p/${PID}/plc/cells`)).cells;
  ok(`工厂 ${PID} 没有控制单元（这个测试的前提）`, !cells.length, cells.map((c) => c.id));
  await api('POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'reset_program' });
  const errs = [];
  for (const theme of ['light']) {   // 5.0.1 只有浅色
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
    await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.removeItem('vf_plc_tip'); }, tok);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    const go = async (view) => { await p.goto(`${DEV}/plc-dev.html?pid=${PID}&view=${view}`, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500); };
    await go('all');
    const side = p.locator('.dv-side');
    ok(`[${theme}] 侧栏：没有控制单元时给出按钮`, await side.locator('[data-empty="cells"] [data-act="new-cell"]').count() === 1 && await side.locator('[data-act="from-scene"]').count() === 1);
    ok(`[${theme}] 编程窗：提示条带“新建控制单元”`, await p.locator('.dv-body .ecb [data-act="new-cell"]').count() === 1);
    ok(`[${theme}] 练习 PLC 示范程序在运行、梯形图有内容`, (await p.locator('.dv-body [data-state]').innerText()).includes('运行') && await p.locator('.dv-body .rung').count() >= 5);
    ok(`[${theme}] 调试提示条`, await p.locator('.dv-body .plc-banner.tip').count() === 1);
    await p.screenshot({ path: `${OUT}/e01_plc_${theme}.png` });
    await side.locator('[data-act="from-scene"]').click(); await p.waitForTimeout(1200);
    const n = await p.locator('.el-dialog .sc').count();
    ok(`[${theme}] 从实训场景载入：列出场景`, n >= 10, n);
    await p.locator('.el-dialog .sc').nth(3).click(); await p.waitForTimeout(200);
    await p.screenshot({ path: `${OUT}/e02_scenes_${theme}.png` });
    await p.locator('.el-dialog .el-button', { hasText: '取消' }).click(); await p.waitForTimeout(300);
    await go('hmi');
    ok(`[${theme}] HMI：没有控制单元时显示示范画面`, await p.locator('.cv .w').count() >= 8 && await p.locator('.ecb').count() === 1);
    ok(`[${theme}] HMI：画面来源标签“示范”`, (await p.locator('.hb .src').innerText()).includes('示范'));
    await p.locator('.w-button .hbtn').first().dispatchEvent('pointerdown'); await p.waitForTimeout(700);
    await p.locator('.w-button .hbtn').first().dispatchEvent('pointerup'); await p.waitForTimeout(1200);
    const on = await api('GET', `/api/p/${PID}/cells/_sandbox/online`);
    ok(`[${theme}] 示范画面按“启动”→ 电机运行`, on.vars.Motor === true, JSON.stringify(on.vars).slice(0, 120));
    await p.screenshot({ path: `${OUT}/e03_hmi_${theme}.png` });
    await api('POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'force', name: 'Stop', value: true }); await p.waitForTimeout(300);
    await api('POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'force', name: 'Stop', value: null });
    await go('ext');
    const ext = p.locator('.dv-side');
    ok(`[${theme}] 外接 PLC：空白页有按钮不只是提示`, await ext.locator('[data-empty="cells"] [data-act="new-cell"]').count() === 1 && (await ext.innerText()).includes('外接 PLC 要替换工厂里的一台 PLC'));
    await p.screenshot({ path: `${OUT}/e04_ext_${theme}.png` });
    await ctx.close();
  }
  // ---- 真正的工作台里新建控制单元
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ws', 'teach'); localStorage.setItem('vf_ai_open', '0'); }, tok);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  await api('DELETE', `/api/p/${PID}/model/draft`);
  await p.goto(`${API}/p/${PID}/workbench`, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(9000);
  // 用外壳的 vf:open-panel 事件打开 PLC 侧栏（活动栏按钮顺序会变，还有跳到帮助页的按钮）
  await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } })));
  await p.waitForTimeout(2500);
  const found = await p.locator('.ed-left .ps').count() > 0;
  ok('工作台：打开 PLC 侧栏', found);
  await p.waitForTimeout(1500);
  await p.screenshot({ path: `${OUT}/e05_workbench_plc.png` });
  const before = (await api('GET', `/api/p/${PID}/model`)).model.blocks.filter((x) => x.type === 'cell').length;
  await p.locator('.ed-left [data-act="new-cell"]').click(); await p.waitForTimeout(4500);
  await p.screenshot({ path: `${OUT}/e06_new_cell.png` });
  const leftTitle = await p.locator('.ed-left .sp-h b').innerText().catch(() => '');
  ok('工作台：点“新建控制单元”打开控制单元编辑器', /控制单元|设备内部/.test(leftTitle), leftTitle);
  const m = await api('GET', `/api/p/${PID}/model`);
  const after = (m.model.blocks || []).filter((x) => x.type === 'cell').length;
  ok('工作台：模型草稿里多了一个控制单元块', after === before + 1 || (await p.evaluate(() => document.body.innerText.includes('CELL'))), `${before} → ${after}`);
  const nc = (m.model.blocks || []).filter((x) => x.type === 'cell').pop();
  const np = (m.model.blocks || []).find((x) => x.type === 'plc' && x.params?.migrated_from === nc?.id);
  const sl = (m.model.links || []).find((l) => l.kind === 'signal' && l.from === nc?.id && l.to === np?.id);
  ok('工作台：新建的控制单元同时配了一台 PLC 和一条信号线（单元里不再内置 PLC）', np && sl && sl.all_io && !('plc' in (nc.params?.cell || {})),
    JSON.stringify({ cell: nc?.id, plc: np?.id, link: sl?.id }));
  await api('DELETE', `/api/p/${PID}/model/draft`);
  ok('页面没有脚本错误', !errs.length, errs.join(' | '));
  await b.close();
  const k = res.filter((r) => r[1]).length;
  console.log(`\n${k}/${res.length} 通过`);
  process.exit(k === res.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
