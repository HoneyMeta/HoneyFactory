// 4.3 分层与对象化操作验收（B 机，先启动 serve）：node tests/layer_ui.js
// 选中设备 → 浮动工具条 / 对象面板；加 PLC 控制 → 信号线、通道表；点关联跳转、Alt+← 返回；Ctrl+F 查通道；分层过滤；简单/专业模式
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'ly');
const PID = process.env.VF_PID || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const api = async (tok, method, url, body) => (await fetch(B + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: body ? JSON.stringify(body) : undefined })).json();

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.removeItem('vf_filter'); localStorage.removeItem('vf_expert'); }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  const selName = () => p.locator('.dt-name input').inputValue().catch(() => '');

  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  await p.goto(`${B}/p/${PID}/editor`, { waitUntil: 'networkidle' }); await wait(4000);
  await p.click('.ed-views >> text=流程'); await wait(2500);
  const n0 = await p.locator('.vue-flow__node').count();
  ok('流程图打开', n0 > 10, n0);

  // 选中一台加工设备
  await p.dblclick('.ol-i:has-text("CNC3")'); await wait(1500);
  const dev = await selName();
  ok('选中设备：浮动工具条', await p.locator('.selbar').isVisible(), await p.locator('.selbar').innerText().catch(() => ''));
  ok('选中设备：对象面板（层 + 快捷操作）', await p.locator('.op .op-layer').isVisible(), await p.locator('.op-layer').innerText().catch(() => ''));
  await shot('l01_select');

  // 加 PLC 控制（工具条上的按钮）
  const plcBefore = await p.locator('.vue-flow__node .bn.ly-control').count();
  await p.locator('.selbar button', { hasText: /加 PLC|再接 PLC/ }).first().click(); await wait(2500);
  const plcAfter = await p.locator('.vue-flow__node .bn.ly-control').count();
  ok('加 PLC：画布上多了一台 PLC', plcAfter > plcBefore, `${plcBefore} → ${plcAfter}`);
  ok('加 PLC：有信号线', await p.locator('.vue-flow__edge.e-sig, .vue-flow__edge[data-id^="sig:"]').count() > 0, await p.locator('.vue-flow__edge[data-id^="sig:"]').count());
  await p.dblclick('.ol-i:has-text("CNC3")'); await wait(1200);
  const opText = await p.locator('.op').innerText().catch(() => '');
  ok('对象面板：列出控制它的 PLC 和通道', /PLC/.test(opText) && /I0\.\d|Q0\.\d/.test(opText), opText.replace(/\s+/g, ' ').slice(0, 200));
  await shot('l02_plc');

  // 点关联的 PLC 跳过去，再 Alt+← 返回
  const chip = p.locator('.op .op-chip.ctl').first();
  if (await chip.count()) {
    await chip.click(); await wait(1200);
    const now = await selName();
    ok('点关联 PLC：跳转并选中', now && now !== dev, `${dev} → ${now}`);
    await shot('l03_goto_plc');
    await p.keyboard.press('Alt+ArrowLeft'); await wait(1200);
    ok('Alt+← 返回设备', (await selName()) === dev, await selName());
  } else ok('点关联 PLC：找到 PLC 链接', false, '没有 chip');

  // Ctrl+F 查通道
  await p.locator('.vue-flow').click({ position: { x: 30, y: 30 } }); await wait(300);
  await p.keyboard.press('Control+f'); await wait(600);
  await p.keyboard.type('I0.0'); await wait(500);
  const hits = await p.locator('.sd-i').count();
  ok('查找 I0.0：有结果', hits > 0, hits);
  await shot('l04_search');
  await p.keyboard.press('Enter'); await wait(1200);
  if (await p.locator('.el-overlay-dialog[aria-label="查找"]').isVisible().catch(() => false)) await p.keyboard.press('Escape');
  ok('查找回车：选中设备', (await selName()).length > 0, await selName());

  // 分层过滤：关掉控制层
  await p.click('.fb-btn'); await wait(500);
  await p.locator('.fb-row', { hasText: '控制' }).first().locator('.el-checkbox').click(); await wait(1200);
  const plcHidden = await p.locator('.vue-flow__node .bn.ly-control').count();
  ok('过滤掉控制层：PLC 不显示', plcHidden === 0, plcHidden);
  await shot('l05_filter');
  await p.locator('.fb button', { hasText: '全部显示' }).click(); await wait(1000);
  ok('全部显示：PLC 回来', (await p.locator('.vue-flow__node .bn.ly-control').count()) === plcAfter);
  await p.keyboard.press('Escape');

  // 简单 / 专业模式
  await p.dblclick('.ol-i:has-text("CNC3")'); await wait(1000);
  const simpleSecs = await p.locator('.dt .el-collapse-item').count();
  await p.locator('.dt-mode .el-switch').click(); await wait(600);
  const expSecs = await p.locator('.dt .el-collapse-item').count();
  ok('专业模式显示更多内容', expSecs > simpleSecs, `${simpleSecs} → ${expSecs}`);

  // 4.4：操作台关掉以后能从控制单元 / 它的 PLC 重新打开；锁定的课（只改程序）里"编程""操作台"照样能点
  const cell = await p.evaluate(() => (window.__vfEd.model.blocks.find((b) => b.type === 'cell') || {}).id);
  if (cell) {
    await p.evaluate(() => { window.__vfEd.floats = (window.__vfEd.floats || []).filter((w) => w.id !== 'cell-console'); });
    await p.evaluate((id) => { window.__vfEd.sel = [id]; }, cell); await wait(800);
    await p.locator('.selbar button', { hasText: '操作台' }).click(); await wait(1500);
    ok('选中控制单元：工具条"操作台"打开操作台', await p.evaluate(() => (window.__vfEd.floats || []).some((w) => w.id === 'cell-console')));
    await p.evaluate(() => { window.__vfEd.floats = (window.__vfEd.floats || []).filter((w) => w.id !== 'cell-console'); }); await wait(300);
    const plc = await p.evaluate((id) => { const l = window.__vfEd.model.links.find((x) => x.kind === 'signal' && x.from === id); return l && l.to; }, cell);
    await p.evaluate(() => { window.__vfEd.modelLocked = true; });
    await p.evaluate((id) => { window.__vfEd.sel = [id]; }, plc); await wait(800);
    const prog = p.locator('.dt .op-acts button', { hasText: '编程' });
    ok('锁定的课：选中 PLC，"编程"可点', (await prog.count()) > 0 && await prog.first().isEnabled());
    const con = p.locator('.dt .op-acts button', { hasText: '操作台' });
    ok('锁定的课：选中 PLC，"操作台"可点', (await con.count()) > 0 && await con.first().isEnabled());
    await con.first().click(); await wait(1500);
    ok('从 PLC 打开操作台', await p.evaluate(() => (window.__vfEd.floats || []).some((w) => w.id === 'cell-console')));
    await shot('l09_locked_plc');
    await p.evaluate(() => { window.__vfEd.modelLocked = false; });
  } else ok('示范工厂有控制单元', false);

  // 三维 / 平面不报错
  await p.click('.ed-views >> text=平面'); await wait(1500); await shot('l06_plan');
  await p.click('.ed-views >> text=三维'); await wait(2500); await shot('l07_3d');
  await p.click('.ed-views >> text=架构'); await wait(1500); await shot('l08_arch');

  ok('没有前端报错', errs.length === 0, errs.join(' | '));
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  await b.close();
  const fail = res.filter((r) => !r[1]).length;
  console.log(`\n${res.length - fail}/${res.length} 通过`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
