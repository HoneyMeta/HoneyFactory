// 画布易用性与"以图为中心"（B 机，先启动 serve）：node tests/graph_ui.js
// 浅色默认；资源库单击放置 / 拖进三维；Delete、Backspace、方向键、F9；三个视图的右键菜单；图上断点、观察值、注入故障；图上点选（课程作业用）；快捷键表
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'gu'), PID = process.env.VF_PLANT || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const tok = (await api('', 'POST', '/api/login', { username: 'admin', password: 'honey123' })).token;
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  for (const b of await api(tok, 'GET', `/api/p/${PID}/breakpoints`)) await api(tok, 'DELETE', `/api/p/${PID}/breakpoints/${b.id}`);
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); if (!sessionStorage.getItem('i')) { sessionStorage.setItem('i', '1'); for (const k of ['vf_wb2_sizes', 'vf_theme', 'vf_lib_tip']) localStorage.removeItem(k); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0'); } }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404|Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  const lightCheck = (sel, items) => p.evaluate(([sel, items]) => {
    const rgb = (c) => (String(c).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const L = (c) => { const [r, g, b] = rgb(c).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const cr = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const el = document.querySelector(sel); if (!el) return null;
    const cs = getComputedStyle(el), bg = cs.backgroundColor;
    const out = { bg, lum: +L(bg).toFixed(3), img: cs.backgroundImage.slice(0, 40), c: {} };
    for (const [s, prop] of items) { const e = document.querySelector(s); if (e) out.c[s] = +cr(getComputedStyle(e)[prop], bg).toFixed(2); }
    out.min = Math.min(99, ...Object.values(out.c));
    return out;
  }, [sel, items]);
  let fq = 1000;
  const center = async (id) => { await p.evaluate(([i, n]) => { window.__vfEd.focusReq = { id: i, n }; }, [id, ++fq]); await wait(900); };
  const nBlocks = () => p.evaluate(() => window.__vfEd.model.blocks.length);
  await p.goto(`${B}/p/${PID}/workbench`, { waitUntil: 'networkidle' }); await wait(9000);
  ok('只有浅色：工作台没有深色 / 浅色切换', await p.locator('.ed').count() === 1 && !(await p.evaluate(() => document.documentElement.classList.contains('dark'))));
  await shot('g01_light_3d');

  {   // 流程图画布：浅色底 + 细网格，连线对画布对比度 ≥ 3
    await p.evaluate(() => { window.__vfEd.view = 'graph'; }); await wait(2500);
    const lc = await lightCheck('.gv .vue-flow', [['.gv .vue-flow__edge-path', 'stroke'], ['.gv .bn-h b', 'color']]);
    ok('流程图：浅色画布、有网格、连线和卡片标题看得清', lc && lc.lum > 0.85 && await p.locator('.gv .vue-flow__background').count() >= 1 && lc.min >= 3, JSON.stringify(lc));
    await p.evaluate(() => { window.__vfEd.view = '3d'; }); await wait(1500);
  }

  // ---------- 资源库：提示、单击放置 ----------
  await p.click('.ed-act button[data-panel="library"]'); await wait(800);
  ok('资源库有用法提示', (await p.locator('.lib-tip').innerText().catch(() => '')).includes('单击'));
  await p.click('.ed-views >> text=流程'); await wait(2500);
  const n0 = await nBlocks();
  await p.locator('.lib .tile').filter({ hasText: '缓存' }).first().click(); await wait(400);
  ok('单击资源进入放置模式', (await p.locator('.ed-modebar').innerText().catch(() => '')).includes('放置'));
  await shot('g02_placing');
  const pane = await p.locator('.vue-flow__pane').boundingBox();
  await p.mouse.click(pane.x + pane.width * 0.5, pane.y + pane.height * 0.85); await wait(1200);
  ok('在流程图上点一下放下', (await nBlocks()) === n0 + 1 && (await p.locator('.ed-modebar').count()) === 0);
  await p.keyboard.press('Backspace'); await wait(800);
  ok('Backspace 删除', (await nBlocks()) === n0);
  await p.click('.ed-views >> text=平面'); await wait(1500);
  await p.locator('.lib .tile').filter({ hasText: '缓存' }).first().click(); await wait(300);
  const svg = await p.locator('.pv-svg').boundingBox();
  await p.mouse.click(svg.x + svg.width * 0.5, svg.y + svg.height * 0.9); await wait(1200);
  ok('平面图上点一下放下', (await nBlocks()) === n0 + 1);
  await p.keyboard.press('Backspace'); await wait(800);
  ok('平面图里 Backspace 也能删设备', (await nBlocks()) === n0);
  // 拖进三维
  await p.click('.ed-views >> text=三维'); await wait(2500);
  const host = await p.locator('.scene-host').boundingBox();
  const dt = await p.evaluateHandle(() => { const d = new DataTransfer(); d.setData('vf/type', 'buffer'); return d; });
  await p.dispatchEvent('.scene-host', 'drop', { dataTransfer: dt, clientX: host.x + host.width * 0.5, clientY: host.y + host.height * 0.6 });
  await wait(1200);
  ok('拖进三维也能放', (await nBlocks()) === n0 + 1);
  await p.keyboard.press('Delete'); await wait(800);

  // ---------- 流程图：右键菜单、断点、观察值、方向键 ----------
  await p.click('.ed-views >> text=流程'); await wait(2500);
  await p.evaluate(() => { window.__vfEd.sel = []; });
  await center('CNC3');
  const node = p.locator('.vue-flow__node-block').filter({ hasText: 'CNC3' }).first();
  await node.click({ button: 'right' }); await wait(800);
  ok('流程图右键设备菜单', (await p.locator('.xm .xm-t').first().innerText().catch(() => '')).includes('3#加工中心'));
  await shot('g03_graph_ctx');
  await p.locator('.xm-i').filter({ hasText: /^\s*断点/ }).first().hover(); await wait(500);
  await shot('g04_graph_bp_sub');
  await p.locator('.xm-subm .xm-i').filter({ hasText: '进入停机' }).first().click(); await wait(1500);
  ok('右键加断点 → 节点上有红点', (await node.locator('.bn-bp.on').count()) === 1);
  const bps = await api(tok, 'GET', `/api/p/${PID}/breakpoints`);
  ok('断点已建到后端', bps.some((x) => x.cond.id === 'CNC3' && x.cond.state === 'Stopped'), JSON.stringify(bps.map((x) => x.name)));
  await center('CNC3'); await node.click({ button: 'right' }); await wait(1500);
  await p.locator('.xm-i').filter({ hasText: /^\s*观察数值/ }).first().hover(); await wait(1500);
  const wi = p.locator('.xm-subm .xm-i').filter({ hasText: 'Spindle' }).first();
  if (await wi.count()) await wi.click(); else await p.locator('.xm-subm .xm-i').first().click();
  await wait(3500);
  ok('观察数值显示在节点上', (await node.locator('.bn-w').innerText().catch(() => '')).length > 3, await node.locator('.bn-w').innerText().catch(() => ''));
  await shot('g05_graph_bp_watch');
  // F9：选中另一台，加默认断点
  const node2 = p.locator('.vue-flow__node-block').filter({ hasText: 'CNC4' }).first();
  await center('CNC4'); await node2.click(); await wait(300); await p.keyboard.press('F9'); await wait(1500);
  ok('F9 加断点', (await node2.locator('.bn-bp').count()) === 1);
  await p.keyboard.press('F9'); await wait(1500);
  ok('再按 F9 删除', (await node2.locator('.bn-bp').count()) === 0);
  // 方向键
  const before = await p.evaluate(() => window.__vfEd.model.blocks.find((x) => x.id === 'CNC4').node.slice());
  await p.keyboard.press('ArrowRight'); await wait(500);
  const after = await p.evaluate(() => window.__vfEd.model.blocks.find((x) => x.id === 'CNC4').node.slice());
  ok('方向键微调', after[0] === before[0] + 10, `${before} → ${after}`);
  await p.keyboard.press('Control+z'); await wait(500);
  // 连线右键（直接在连线的命中区域上触发）
  const edge = p.locator('.vue-flow__edge:not([data-id^="op:"])').first();
  const eb = await edge.boundingBox();
  await edge.dispatchEvent('contextmenu', { button: 2, clientX: eb.x + eb.width / 2, clientY: eb.y + eb.height / 2 }); await wait(600);
  ok('连线右键菜单', (await p.locator('.xm .xm-t').first().innerText().catch(() => '')).includes('连线'));
  await p.keyboard.press('Escape'); await wait(300);
  // 空白处右键：找一个真正落在画布空白上的点
  const spot = await p.evaluate(() => {
    const r = document.querySelector('.vue-flow__pane').getBoundingClientRect();
    for (let fy = 0.2; fy < 0.9; fy += 0.07) for (let fx = 0.3; fx < 0.95; fx += 0.07) {
      const x = r.left + r.width * fx, y = r.top + r.height * fy, el = document.elementFromPoint(x, y);
      if (el && el.classList.contains('vue-flow__pane')) return [x, y];
    }
    return null;
  });
  if (spot) await p.mouse.click(spot[0], spot[1], { button: 'right' }); await wait(500);
  ok('流程图空白处右键', (await p.locator('.xm-i').filter({ hasText: '添加块' }).count()) === 1);
  await p.keyboard.press('Escape');

  // ---------- 平面图 / 三维 右键也有同样的断点 ----------
  await p.click('.ed-views >> text=平面'); await wait(1500);
  await p.evaluate(() => { window.__vfEd.focusReq = { id: 'CNC3', n: 99 }; }); await wait(800);
  ok('平面图上断点标记', (await p.locator('.pv-svg .bpm.on').count()) >= 1);
  const blk = await p.locator('.pv-svg .blk[data-id="CNC3"]').boundingBox();
  if (blk) await p.mouse.click(blk.x + blk.width / 2, blk.y + blk.height / 2, { button: 'right' });
  await wait(600);
  ok('平面图右键设备菜单', (await p.locator('.xm .xm-i').filter({ hasText: /^\s*断点/ }).count()) === 1);
  await shot('g06_plan_ctx');
  await p.keyboard.press('Escape');
  await p.click('.ed-views >> text=三维'); await wait(2500);
  ok('三维标签上的断点标记', (await p.locator('.lbl.bp').count()) >= 1);
  await shot('g07_3d_marks');

  // ---------- 图上点选 ----------
  await p.click('.ed-views >> text=流程'); await wait(2000);
  await p.evaluate(() => { window.__picked = ''; window.__vfEd.pick = { prompt: '请点出瓶颈设备', onPick: (id) => { window.__picked = id; } }; }); await wait(300);
  ok('点选提示条', (await p.locator('.ed-modebar.pick').innerText().catch(() => '')).includes('瓶颈'));
  await center('INS1'); await p.locator('.vue-flow__node-block').filter({ hasText: 'INS1' }).first().click(); await wait(500);
  ok('图上点选得到设备', (await p.evaluate(() => window.__picked)) === 'INS1');

  // ---------- 快捷键表 ----------
  await p.keyboard.press('Control+/'); await wait(500);
  ok('Ctrl+/ 快捷键表', (await p.locator('.kb-table tr').count()) > 10);
  await shot('g08_shortcuts');
  await p.keyboard.press('Escape');

  for (const x of await api(tok, 'GET', `/api/p/${PID}/breakpoints`)) await api(tok, 'DELETE', `/api/p/${PID}/breakpoints/${x.id}`);
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((r) => !r[1]).map((r) => r[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
