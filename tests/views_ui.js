// 三张核心图的新工具（B 机，先启动 serve）：node tests/views_ui.js
// 平面图：画墙、区域、通道、AGV 路网、标注，楼层；三维：布局显示、测距、书签、漫游、右键菜单、框选；流程图：自动排版、连线流量、零件逐步追踪
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'vw');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  await api(tok, 'DELETE', '/api/p/foundry-housing/model/draft');
  await api(tok, 'POST', '/api/p/foundry-housing/ctl/reset');           // 从已保存的模型开始，去掉上次留下的运行中改动
  await api(tok, 'POST', '/api/p/foundry-housing/ctl', { action: 'play', speed: 60 });
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); if (!sessionStorage.getItem('i')) { sessionStorage.setItem('i', '1'); localStorage.removeItem('vf_wb2_sizes'); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0'); } }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  await p.goto(B + '/p/foundry-housing/workbench', { waitUntil: 'networkidle' }); await wait(8000);

  // ---------- 平面图 ----------
  await p.click('.ed-views >> text=平面'); await wait(1500);
  const svg = await p.locator('.pv-svg').boundingBox();
  const at = (fx, fy) => [svg.x + svg.width * fx, svg.y + svg.height * fy];
  const tool = async (name) => { await p.click(`.pv-tools .el-radio-button:has-text("${name}")`); await wait(300); };
  await tool('墙');
  for (const [fx, fy] of [[0.15, 0.15], [0.85, 0.15], [0.85, 0.85]]) { const [x, y] = at(fx, fy); await p.mouse.click(x, y); await wait(150); }
  { const [x, y] = at(0.15, 0.85); await p.mouse.dblclick(x, y); await wait(1200); }
  await tool('区域');
  for (const [fx, fy] of [[0.2, 0.25], [0.4, 0.25], [0.4, 0.45]]) { const [x, y] = at(fx, fy); await p.mouse.click(x, y); await wait(150); }
  { const [x, y] = at(0.2, 0.45); await p.mouse.dblclick(x, y); await wait(1200); }
  await tool('通道');
  { const [x, y] = at(0.1, 0.6); await p.mouse.click(x, y); await wait(150); const [x2, y2] = at(0.9, 0.6); await p.mouse.dblclick(x2, y2); await wait(1200); }
  await tool('路网');
  for (const [fx, fy] of [[0.3, 0.7], [0.5, 0.7], [0.7, 0.7], [0.7, 0.5]]) { const [x, y] = at(fx, fy); await p.mouse.click(x, y); await wait(500); }
  await tool('标注');
  { const [x, y] = at(0.15, 0.9); await p.mouse.click(x, y); await wait(200); const [x2, y2] = at(0.85, 0.9); await p.mouse.click(x2, y2); await wait(1000); }
  await tool('选择');
  await wait(1500);
  const m = await api(tok, 'GET', '/api/p/foundry-housing/model');
  const L = m.model.plant.layout || {};
  ok('平面图：画墙/区域/通道/路网/标注', (L.walls || []).length === 1 && (L.zones || []).length === 1 && (L.aisles || []).length === 1 && (L.paths?.nodes || []).length === 4 && (L.paths?.edges || []).length === 3 && (L.dims || []).length === 1,
    JSON.stringify({ w: (L.walls || []).length, z: (L.zones || []).length, a: (L.aisles || []).length, n: (L.paths?.nodes || []).length, e: (L.paths?.edges || []).length, d: (L.dims || []).length }));
  await shot('v01_plan_layout');
  // 选中一条路网连线设成单向
  await p.locator('.le .le-hit').first().click({ force: true }); await wait(500);
  await p.click('.dt-lay .el-checkbox:has-text("单向")'); await wait(1200);   // 布局元素的属性在右侧属性面板（4.4）
  const m2 = await api(tok, 'GET', '/api/p/foundry-housing/model');
  ok('路网连线设为单向', (m2.model.plant.layout.paths.edges || []).some((e) => e.oneway));
  await p.keyboard.press('Control+z'); await wait(800);
  // ---------- 三维 ----------
  await p.click('.ed-views >> text=三维'); await wait(4000);
  await shot('v02_3d_layout');
  const ms = p.locator('.v3-bar .el-button-group').last().locator('button').first();
  await ms.click(); await wait(300);
  const host = await p.locator('.scene-host').boundingBox();
  await p.mouse.click(host.x + host.width * 0.35, host.y + host.height * 0.6); await wait(300);
  await p.mouse.click(host.x + host.width * 0.65, host.y + host.height * 0.6); await wait(800);
  ok('三维测距', (await p.locator('.meas3').count()) === 1, await p.locator('.meas3').innerText().catch(() => ''));
  await shot('v03_3d_measure');
  await ms.click(); await wait(300);
  // 书签
  await p.click('.v3-bar button:has-text("书签")'); await wait(300);
  await p.click('.el-dropdown-menu__item:has-text("把当前视角存为书签")'); await wait(400);
  await p.click('.el-message-box__btns .el-button--primary'); await wait(1200);
  const m3 = await api(tok, 'GET', '/api/p/foundry-housing/model');
  ok('视角书签', (m3.model.plant.cameras || []).length === 1);
  // 漫游
  const walkBtn = p.locator('.v3-bar .el-button-group').last().locator('button').nth(1);
  await walkBtn.click(); await wait(500);
  await p.keyboard.down('w'); await wait(1200); await p.keyboard.up('w'); await wait(300);
  await shot('v04_3d_walk');
  ok('第一人称漫游', (await p.locator('.v3-tip:has-text("漫游中")').count()) === 1);
  await p.keyboard.press('Escape'); await wait(500);
  // 右键菜单
  await p.click('.v3-bar button:has-text("视角")'); await wait(300); await p.click('.el-dropdown-menu__item:has-text("俯视")'); await wait(1500);
  let menuOk = false;
  for (const [fx, fy] of [[0.5, 0.5], [0.45, 0.5], [0.55, 0.5], [0.6, 0.45], [0.4, 0.55], [0.5, 0.4], [0.7, 0.5], [0.3, 0.5]]) {
    await p.mouse.click(host.x + host.width * fx, host.y + host.height * fy, { button: 'right' }); await wait(400);
    if (await p.locator('.xm .xm-i').filter({ hasText: /^\s*断点/ }).count()) { menuOk = true; break; }   // 设备菜单（空地上右键是视角菜单）
    await p.keyboard.press('Escape');
  }
  ok('三维右键菜单', menuOk);
  await shot('v05_3d_ctx');
  await p.keyboard.press('Escape');
  // ---------- 流程图 ----------
  await p.click('.ed-views >> text=流程'); await wait(2500);
  await p.click('.gv-mini button:has-text("自动排版")'); await wait(2000);
  await shot('v06_graph_autolayout');
  const m4 = await api(tok, 'GET', '/api/p/foundry-housing/model');
  const xs = new Set(m4.model.blocks.map((x) => x.node[0]));
  ok('自动排版（按工序分层）', xs.size >= 6, `${xs.size} 层`);
  await wait(31000);
  const labels = await p.locator('.vue-flow__edge-text').allTextContents();
  ok('连线上显示流量/排队', labels.some((t) => /\/h/.test(t)), labels.slice(0, 4).join(' | '));
  await shot('v07_graph_wire');
  // 零件追踪
  await p.locator('.ed-act button').nth(4).click(); await wait(1500);
  const fg = (await api(tok, 'GET', '/api/p/foundry-housing/parts?limit=1&status=FG'))[0] || (await api(tok, 'GET', '/api/p/foundry-housing/parts?limit=1&status=GOOD'))[0];
  await p.locator('.sp-body input[placeholder*="零件编号"]').fill(fg.id); await p.keyboard.press('Enter'); await wait(1500);
  await p.click('.el-dialog__footer button:has-text("在流程图中逐步追踪")'); await wait(1500);
  for (let i = 0; i < 3; i++) { await p.locator('.gv-trace button').nth(1).click(); await wait(500); }
  ok('流程图里逐步追踪零件', (await p.locator('.gv-trace').count()) === 1 && (await p.locator('.vue-flow__node.n-tr, .vue-flow__node.n-trcur').count()) > 0, await p.locator('.gv-trace').innerText().catch(() => ''));
  await shot('v08_graph_trace');
  await api(tok, 'DELETE', '/api/p/foundry-housing/model/draft');
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((r) => !r[1]).map((r) => r[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
