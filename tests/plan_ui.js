// 平面图 CAD 级编辑（4.1，助手 V）界面验收（B 机，先启动 serve）：node tests/plan_ui.js
// 键入长度 / Shift 正交 / 矩形墙与矩形区域 / 顶点与边中点手柄 / 整体拖动 / 中点与垂足吸附 / 复制粘贴阵列 / 路网站点绑定、限速、连通性检查 /
// 厂房外墙与门洞 / F2 改名、双击进设备内部 / 设备图标与名称 / 标尺、比例尺、指北针 / 浅色画布对比度
// 4.4：布局元素的属性在右侧属性面板（不再有画布上的浮动属性卡）/ 连线落在边框端口、正交走线、不穿过别的设备 /
//      悬停连接点拖线连物料线和信号线 / "+" 加一台并连好 / 拖动对齐参考线 / 多选对齐条
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'pv');
const PID = 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 260)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const { checkRoutes } = require('./scripts/route_check');
const near = (a, b, e = 0.011) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) < e);
const nearPts = (A, Bp, e) => A && A.length === Bp.length && A.every((q, i) => near(q, Bp[i], e));
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  await api(tok, 'POST', `/api/p/${PID}/ctl/reset`);
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => {
    localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN');
    if (!sessionStorage.getItem('i')) { sessionStorage.setItem('i', '1'); localStorage.removeItem('vf_wb2_sizes'); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_theme', 'light'); localStorage.removeItem('vf_pv_card'); localStorage.removeItem('vf_plan_clip'); }
  }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push(m.text().slice(0, 200)); });
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
  await p.goto(B + `/p/${PID}/workbench`, { waitUntil: 'networkidle' }); await wait(7000);
  await p.click('.ed-views >> text=平面'); await wait(1500);

  // ---------- 看图：设备图标 + 名称、标尺、比例尺、指北针 ----------
  const nIcon = await p.locator('.pv-svg .lbls .bico').count(), nTxt = await p.locator('.pv-svg .lbls text').count();
  const names = (await p.locator('.pv-svg .lbls text').allTextContents()).join(' ');
  ok('设备画类型图标 + 名称（#29）', nIcon >= 20 && nTxt >= 12 && /中频炉|加工中心|造型线/.test(names), `${nIcon} 个图标，${nTxt} 个名称：${names.slice(0, 80)}`);
  const minFont = await p.evaluate(() => { const k = +document.querySelector('.pv-svg > g').getAttribute('transform').match(/scale\(([-\d.e]+)\)/)[1]; return Math.min(...[...document.querySelectorAll('.pv-svg .lbls text:not(.wtxt)')].map((t) => +t.getAttribute('font-size') * k)); });
  ok('设备名称字号不小于 11 px', minFont >= 10.9, minFont.toFixed(1) + ' px');
  ok('标尺、比例尺、指北针（#36）', (await p.locator('.pv-svg .pr-t').count()) > 20 && /\d+ m/.test(await p.locator('.pv-svg .pr-scale').textContent()) && (await p.locator('.pv-svg .pr-north').count()) === 1,
    await p.locator('.pv-svg .pr-scale').textContent());
  await shot('p01_overview');
  const barH0 = (await p.locator('.pv-bar').boundingBox()).height;
  { // 4.4：连线两头落在设备边框上，只有横竖段，不穿过别的设备
    const r = await checkRoutes(p, 'plan');
    ok('连线：端点在设备边框上、只有横竖段、不穿过别的设备（全图）', r.n >= 20 && r.endsOk === r.ends && r.diag === 0 && r.cross === 0, `${r.n} 条线，端点 ${r.endsOk}/${r.ends}，斜段 ${r.diag}，穿过 ${r.cross} ${r.bad.slice(0, 3).join('；')}`);
  }

  // 放大到空白处（厂房下半部）
  let t;
  const T = async () => { t = await p.evaluate(() => { const svg = document.querySelector('.pv-svg'); const r = svg.getBoundingClientRect(); const m = svg.querySelector(':scope > g').getAttribute('transform').match(/translate\(([-\d.e]+),([-\d.e]+)\) scale\(([-\d.e]+)\)/); return { x: r.x, y: r.y, tx: +m[1], ty: +m[2], k: +m[3] }; }); };
  const S = (x, y) => [t.x + t.tx + x * t.k, t.y + t.ty + y * t.k];
  await T();
  { const [x, y] = S(60, 48); await p.mouse.move(x, y); for (let i = 0; i < 4; i++) { await p.mouse.wheel(0, -150); await wait(60); } await wait(300); }
  await T();
  { // 平移：让 (61, 50) 落在画布中间（中键拖动）
    const r = await p.locator('.pv-svg').boundingBox(), [x, y] = S(61, 50);
    await p.mouse.move(x, y); await p.mouse.down({ button: 'middle' }); await p.mouse.move(r.x + r.width / 2, r.y + r.height / 2, { steps: 5 }); await p.mouse.up({ button: 'middle' }); await wait(300);
  }
  await T();
  const mv = async (x, y, steps = 3) => { const [a, c] = S(x, y); await p.mouse.move(a, c, { steps }); await wait(60); };
  const click = async (x, y, o) => { await mv(x, y); const [a, c] = S(x, y); await p.mouse.click(a, c, o); await wait(180); };
  const lay = () => p.evaluate(() => JSON.parse(JSON.stringify(window.__vfEd.model.plant.layout || {})));
  const tool = async (name) => { await p.locator('.pv-tools .el-radio-button').filter({ has: p.locator(`.pv-lb:text-is("${name}")`) }).click(); await wait(250); };
  const handle = async (h) => { const bb = await p.locator(`.pv-svg [data-h="${h}"]`).first().boundingBox(); return [bb.x + bb.width / 2, bb.y + bb.height / 2]; };
  const dragTo = async ([a, c], [d, e]) => { await p.mouse.move(a, c); await p.mouse.down(); await p.mouse.move((a + d) / 2, (c + e) / 2, { steps: 4 }); await p.mouse.move(d, e, { steps: 4 }); await wait(100); await p.mouse.up(); await wait(400); };
  ok('放大后比例变大', t.k > 12, t.k.toFixed(1) + ' px/m');

  // ---------- 键入长度、角度（#31） ----------
  await tool('墙');
  await click(30, 44); await mv(36, 44);
  await p.keyboard.type('12.5'); await wait(150);
  const hudTxt = await p.locator('.pv-hud').innerText().catch(() => '');
  await p.keyboard.press('Enter'); await wait(150);
  await mv(42, 47);
  await p.keyboard.type('6<-90'); await p.keyboard.press('Enter'); await wait(150);
  await p.keyboard.press('Enter'); await wait(600);
  let L = await lay();
  const wA = (L.walls || [])[0];
  ok('画墙时显示长度 / 角度读数和键入框', /长 [\d.]+ m/.test(hudTxt) && /角/.test(hudTxt) && /输入 12\.5/.test(hudTxt), hudTxt.replace(/\n/g, ' '));
  ok('键入长度回车定长："12.5"、"6<-90"', wA && nearPts(wA.pts, [[30, 44], [42.5, 44], [42.5, 50]]), JSON.stringify(wA?.pts));
  // Shift 正交
  await click(46, 44);
  await p.keyboard.down('Shift'); await mv(52, 45.3); { const [a, c] = S(52, 45.3); await p.mouse.click(a, c); } await p.keyboard.up('Shift'); await wait(150);
  await p.keyboard.press('Enter'); await wait(500);
  L = await lay();
  ok('Shift 正交', nearPts(L.walls?.[1]?.pts, [[46, 44], [52, 44]]), JSON.stringify(L.walls?.[1]?.pts));

  // ---------- 矩形墙、矩形区域（#27） ----------
  await tool('矩形墙');
  await click(56, 43); await click(64, 50); await wait(500);
  L = await lay();
  ok('矩形墙：一圈闭合的墙', nearPts(L.walls?.[2]?.pts, [[56, 43], [64, 43], [64, 50], [56, 50], [56, 43]]), JSON.stringify(L.walls?.[2]?.pts));
  await tool('矩形区域');
  await click(70, 43); await mv(75, 46); await p.keyboard.type('10,6'); await p.keyboard.press('Enter'); await wait(500);
  L = await lay();
  const zid = L.zones?.[0]?.id;
  ok('矩形区域：键入"长,宽"', nearPts(L.zones?.[0]?.pts, [[70, 43], [80, 43], [80, 49], [70, 49]]), JSON.stringify(L.zones?.[0]?.pts));

  // ---------- 选中区域：右侧属性面板、顶点手柄、边中点加点、双击删点、整体拖动 ----------
  await tool('选择');
  await click(75, 46); await wait(400);
  const barH1 = (await p.locator('.pv-bar').boundingBox()).height;
  ok('选中区域：属性在右侧属性面板（画布上没有浮动属性卡），工具条高度不变', (await p.locator('.pv-card').count()) === 0 && (await p.locator('.ed-right .dt-lay').count()) === 1
    && Math.abs(barH1 - barH0) < 1 && (await p.locator('.dt-lay .dl-pts tr').count()) === 5,
    `工具条 ${barH0}→${barH1}px，顶点表 ${await p.locator('.dt-lay .dl-pts tr').count()} 行`);
  { // 右侧面板里改顶点坐标、改段长
    const L0 = (await lay()).zones[0].pts;
    const xin = p.locator('.dt-lay .dl-pts tr').nth(2).locator('td').nth(1).locator('input');
    await xin.fill('81'); await xin.press('Enter'); await wait(500);
    let Lz = (await lay()).zones[0].pts;
    const okX = near(Lz[1], [81, L0[1][1]]);
    const lin = p.locator('.dt-lay .dl-pts tr').nth(1).locator('td').nth(3).locator('input');
    await lin.fill('12'); await lin.press('Enter'); await wait(500);
    Lz = (await lay()).zones[0].pts;
    ok('右侧面板：改顶点坐标、改段长（沿段方向移动下一个顶点）', okX && near(Lz[1], [82, L0[1][1]]), JSON.stringify(Lz));
    await p.evaluate(() => document.activeElement?.blur()); await wait(100);
    await p.keyboard.press('Control+z'); await wait(400); await p.keyboard.press('Control+z'); await wait(500);
    ok('改顶点可撤销', nearPts((await lay()).zones[0].pts, L0), JSON.stringify((await lay()).zones[0].pts));
    await click(75, 46); await wait(300);
  }
  ok('选中后显示 4 个顶点手柄、4 个边中点手柄', (await p.locator('.pv-svg .lh-v').count()) === 4 && (await p.locator('.pv-svg .lh-m').count()) === 4);
  await shot('p02_zone_selected');
  await dragTo(await handle('v2'), S(83, 51));
  L = await lay();
  ok('拖顶点改形状', near(L.zones[0].pts[2], [83, 51]), JSON.stringify(L.zones[0].pts));
  await dragTo(await handle('m0'), S(75, 41));
  L = await lay();
  ok('拖边中点 = 加一个顶点', L.zones[0].pts.length === 5 && near(L.zones[0].pts[1], [75, 41]), JSON.stringify(L.zones[0].pts));
  await shot('p03_zone_vertex');
  { const [a, c] = await handle('v1'); await p.mouse.dblclick(a, c); await wait(500); }
  L = await lay();
  ok('双击顶点删除', L.zones[0].pts.length === 4, JSON.stringify(L.zones[0].pts));
  const before = L.zones[0].pts.map((q) => [...q]);
  { const [a, c] = S(74, 46); await dragTo([a, c], S(76, 47)); }
  L = await lay();
  ok('整体拖动区域', nearPts(L.zones[0].pts, before.map((q) => [q[0] + 2, q[1] + 1])), JSON.stringify(L.zones[0].pts));
  // 墙也能拖顶点（闭合墙首尾一起动）
  await click(64, 46.5); await wait(300);
  await dragTo(await handle('v0'), S(55, 42));
  L = await lay();
  ok('闭合墙拖第一个顶点，首尾一起改', near(L.walls[2].pts[0], [55, 42]) && near(L.walls[2].pts[4], [55, 42]), JSON.stringify(L.walls[2].pts));

  // ---------- 中点 / 垂足吸附（#31） ----------
  await tool('标注');
  await mv(36.4, 44.2); const midKind = await p.locator('.pv-svg .lsnap text').textContent().catch(() => '');
  await click(36.4, 44.2); await click(36.25, 52.5); await wait(500);
  L = await lay();
  ok('中点吸附', near(L.dims?.[0]?.a, [36.25, 44]) && /中点/.test(midKind), JSON.stringify(L.dims?.[0]) + ' ' + midKind);
  await click(46, 48.5); await mv(42.75, 48.7); const perpKind = await p.locator('.pv-svg .lsnap text').textContent().catch(() => '');
  await click(42.75, 48.7); await wait(500);
  L = await lay();
  ok('垂足吸附', near(L.dims?.[1]?.b, [42.5, 48.5]) && /垂足/.test(perpKind), JSON.stringify(L.dims?.[1]) + ' ' + perpKind);
  await shot('p04_snap');

  // ---------- 复制 / 粘贴 / 复制一份 / 阵列（#32） ----------
  await tool('选择'); await p.keyboard.press('Escape');
  await click(78, 46); await wait(300);
  ok('选中区域时右侧属性面板显示区域属性（名称、颜色、面积）', /区域/.test(await p.locator('.dt-lay .dt-head').innerText().catch(() => '')) && (await p.locator('.dt-lay .el-color-picker').count()) === 1);
  await p.keyboard.press('Control+c'); await mv(90, 60); await p.keyboard.press('Control+v'); await wait(600);
  L = await lay();
  const pasted = L.zones?.[1];
  const pc = pasted ? [pasted.pts.reduce((s, q) => s + q[0], 0) / pasted.pts.length, pasted.pts.reduce((s, q) => s + q[1], 0) / pasted.pts.length] : null;
  ok('Ctrl+C / Ctrl+V 粘贴区域到鼠标处', L.zones.length === 2 && pc && Math.abs(pc[0] - 90) < 3 && Math.abs(pc[1] - 60) < 3, JSON.stringify(pc));
  await p.keyboard.press('Control+d'); await wait(600);
  L = await lay();
  ok('Ctrl+D 复制一份', L.zones.length === 3);
  await p.locator('.dt-lay button:has-text("阵列")').click(); await wait(400);
  const dlg = p.locator('.el-dialog:has-text("阵列复制")');
  const nums = dlg.locator('.el-input-number input');
  await nums.nth(0).fill('3'); await nums.nth(2).fill('2'); await nums.nth(2).press('Tab'); await wait(200);
  await dlg.locator('button:has-text("阵列")').last().click(); await wait(800);
  L = await lay();
  ok('阵列 3 列 × 2 行（新增 5 份）', L.zones.length === 8, L.zones.length + ' 个区域');
  await shot('p05_array');
  await p.keyboard.press('Control+z'); await wait(600);
  L = await lay();
  ok('阵列一步撤销', L.zones.length === 3, L.zones.length + ' 个区域');
  // 墙 + 设备一起复制（框选）
  await click(64, 46.5); await p.keyboard.press('Control+d'); await wait(600);
  L = await lay();
  ok('墙也能复制一份', L.walls.length === 4, L.walls.length + ' 道墙');

  // ---------- 路网：站点绑定设备、边限速、连通性检查（#33） ----------
  await tool('路网');
  for (const [x, y] of [[32, 58], [40, 58], [48, 58]]) await click(x, y);
  await click(48, 58, { button: 'right' }); await wait(300);
  await p.keyboard.press('Escape'); await tool('选择');
  L = await lay();
  const [n1, n2, n3] = L.paths.nodes.map((n) => n.id), [e1, e2] = L.paths.edges.map((e) => e.id);
  await click(48, 58); await wait(300);
  await p.locator('.dt-lay .el-select').first().click(); await wait(200);
  await p.locator('.el-select-dropdown:visible .el-select-dropdown__item:has-text("站点")').click(); await wait(500);
  await p.locator('.dt-lay .el-select').nth(1).click(); await wait(200);
  await p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'CNC1' }).first().click(); await wait(600);
  L = await lay();
  ok('站点绑定设备（取放点）', L.paths.nodes[2].kind === 'station' && L.paths.nodes[2].block === 'CNC1' && (await p.locator('.pv-svg .lsl').count()) === 1, JSON.stringify(L.paths.nodes[2]));
  { const ln = L.paths.nodes; const [a, c] = S((ln[0].x + ln[1].x) / 2, ln[0].y); await p.mouse.click(a, c); await wait(300); }
  await p.locator('.dt-lay .el-checkbox:has-text("单向")').click(); await wait(300);
  const vin = p.locator('.dt-lay .f:has-text("限速") input'); await vin.fill('0.5'); await vin.press('Enter'); await wait(500);
  L = await lay();
  const E1 = L.paths.edges.find((e) => e.id === e1);
  ok('路网连线：单向 + 限速', E1.oneway && E1.vmax === 0.5 && (await p.locator('.pv-svg .le-v').count()) === 1, JSON.stringify(E1));
  { const ln = L.paths.nodes; const [a, c] = S((ln[1].x + ln[2].x) / 2, ln[1].y); await p.mouse.click(a, c); await wait(300); }
  await p.locator('.dt-lay .el-checkbox:has-text("单向")').click(); await wait(1500);
  for (let i = 0; i < 20 && !(await p.evaluate(() => (window.__vfEd.validation?.issues || []).some((x) => /单向死路/.test(x.msg)))); i++) await wait(500);   // 等草稿保存、模型检查回来
  const iss = await p.evaluate(() => (window.__vfEd.validation?.issues || []).filter((i) => i.cat === '路网').map((i) => i.msg + ' @' + i.id));
  ok('模型检查：单向死路 / 只出不进', iss.some((m) => /单向死路/.test(m) && m.includes('path:' + n3)) && iss.some((m) => /开不进去/.test(m)), iss.join(' | '));
  ok('平面图标出有问题的节点', (await p.locator('.pv-svg .ln2.iss').count()) >= 2);
  await click(48, 58); await wait(300);
  ok('右侧属性面板里显示该节点的问题', (await p.locator('.dt-lay .dl-iss').count()) >= 1, await p.locator('.dt-lay .dl-iss').first().innerText().catch(() => ''));
  await shot('p06_paths');

  // ---------- 厂房外墙（#34）、门洞 ----------
  await p.click('.pv-hallbtn'); await wait(400);
  await p.locator('.el-popover:visible button:has-text("生成外墙")').click(); await wait(700);
  L = await lay();
  const ow = (L.walls || []).find((w) => w.outer);
  ok('生成厂房外墙（可编辑的普通墙，前墙开大门）', ow && ow.pts.length === 5 && near(ow.pts[2], [150, 56]) && ow.doors?.length === 1, JSON.stringify(ow));
  const inp = p.locator('.el-popover:visible .pv-hall .el-input-number input').first();
  await inp.fill('160'); await inp.press('Enter'); await wait(700);
  L = await lay();
  const ow2 = (L.walls || []).find((w) => w.outer), fl = await p.evaluate(() => window.__vfEd.model.plant.floor);
  ok('改厂房长度，外墙跟着改', near(ow2.pts[1], [160, 0]) && fl[0] === 160 && Math.abs(ow2.doors[0].s - (160 + 56 + 80)) < 0.05, JSON.stringify(ow2.pts) + ' 门 ' + JSON.stringify(ow2.doors));
  await inp.fill('150'); await inp.press('Enter'); await wait(600);
  await p.keyboard.press('Escape'); await p.mouse.click(t.x + 600, t.y + 5); await wait(300);
  await T();
  // 右键矩形墙的上边 → 在这里开门洞
  await click(64, 46.5, { button: 'right' }); await wait(400);
  await p.locator('.xm .xm-i:has-text("在这里开门洞")').click(); await wait(600);
  L = await lay();
  ok('右键墙：在这里开门洞', (L.walls[2].doors || []).length === 1 && (await p.locator('.pv-svg .ldoor').count()) >= 2, JSON.stringify(L.walls[2].doors));
  await click(64, 47.5); await wait(300);
  ok('门洞手柄、右侧面板里的门洞（宽度可改）', (await p.locator('.pv-svg .lh-d').count()) === 1 && (await p.locator('.dt-lay .dl-door').count()) === 1);
  { const win = p.locator('.dt-lay .dl-door input').nth(1); await win.fill('1.6'); await win.press('Enter'); await wait(500);
    ok('右侧面板改门洞宽度', Math.abs(((await lay()).walls[2].doors || [])[0]?.w - 1.6) < 1e-6, JSON.stringify((await lay()).walls[2].doors)); }
  await shot('p07_door');
  // Backspace 删除选中的布局元素
  const nd0 = (await lay()).dims.length;
  await click(36.25, 48); await wait(200); await p.keyboard.press('Backspace'); await wait(500);
  ok('Backspace 删除选中的标注', (await lay()).dims.length === nd0 - 1);

  // ---------- 双击设备 = 设备内部；F2 = 改名（右侧属性面板的名称框） ----------
  await p.keyboard.press('Home'); await wait(800);
  const cb = await p.locator('.pv-svg .blk[data-id="CNC3"]').boundingBox();
  await p.evaluate(() => { window.__vfEd.leftPanel = 'outliner'; });
  await p.mouse.dblclick(cb.x + cb.width / 2, cb.y + cb.height / 2); await wait(700);
  ok('双击设备：打开"设备内部"，留在平面图', (await p.evaluate(() => window.__vfEd.leftPanel)) === 'cell-editor' && (await p.evaluate(() => window.__vfEd.view)) === 'plan' && (await p.evaluate(() => window.__vfEd.sel.join(','))) === 'CNC3',
    await p.evaluate(() => window.__vfEd.leftPanel));
  await p.evaluate(() => { window.__vfEd.leftPanel = 'outliner'; }); await wait(300);
  await p.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2); await p.keyboard.press('F2'); await wait(500);
  const focused = await p.evaluate(() => !!document.activeElement?.closest('.dt-name') && document.activeElement.tagName === 'INPUT');
  ok('F2：右侧属性面板的名称框获得焦点', focused && (await p.evaluate(() => window.__vfEd.rightTab)) === 'props');
  await p.keyboard.type('3#加工中心（改）'); await p.keyboard.press('Enter'); await wait(500);
  const nm = await p.evaluate(() => window.__vfEd.model.blocks.find((x) => x.id === 'CNC3').name);
  ok('就地改名', nm === '3#加工中心（改）', nm);
  await shot('p08_rename');
  await p.mouse.click(t.x + 600, t.y + 30); await wait(200);
  await p.keyboard.press('Control+z'); await wait(400);
  // 两台设备：对齐条浮在画布上方（和流程图一样），工具条高度不变
  await p.evaluate(() => { window.__vfEd.sel = ['CNC1', 'CNC2']; }); await wait(400);
  const barH2 = (await p.locator('.pv-bar').boundingBox()).height;
  ok('多选设备：画布上方出现对齐 / 旋转条，工具条不变', (await p.locator('.pv-align button:has-text("⤒")').count()) === 1 && Math.abs(barH2 - barH0) < 1, `${barH2}px`);
  await p.evaluate(() => { window.__vfEd.sel = []; });

  // ---------- 4.4 和流程图一样的操作：连接点、拖线连物料线、"+"、拖动对齐参考线、放大后的关键数字 ----------
  await p.evaluate(() => { window.__vfEd.focusReq = { id: 'CNC5', n: 9002 }; }); await wait(400);
  { const r0 = await p.locator('.pv-svg').boundingBox(); for (let i = 0; i < 2; i++) { await p.mouse.move(r0.x + r0.width / 2, r0.y + r0.height / 2); await p.mouse.wheel(0, -200); await wait(80); } }
  await wait(600);
  const bb = async (id) => p.locator(`.pv-svg [data-id="${id}"] .body, .pv-svg [data-id="${id}"] .sym-hit`).first().boundingBox();
  const hoverOn = async (id) => { const q = await bb(id); await p.mouse.move(q.x + q.width / 2, q.y + q.height / 2, { steps: 3 }); await wait(300); return q; };
  { const r = await checkRoutes(p, 'plan');
    ok('放大后连线仍然落在边框、横竖走线、不穿设备', r.n >= 5 && r.endsOk === r.ends && r.diag === 0 && r.cross === 0, `${r.n} 条，端点 ${r.endsOk}/${r.ends}，斜段 ${r.diag}，穿过 ${r.cross} ${r.bad.slice(0, 3).join('；')}`); }
  await hoverOn('CNC6');
  ok('悬停设备：四条边出现连接点、右上角出现"+"', (await p.locator('.pv-svg .pv-port').count()) === 4 && (await p.locator('.pv-svg .pv-plus[data-plus="CNC6"]').count()) === 1);
  ok('放大后设备显示关键数字（OEE / 件数）', (await p.locator('.pv-svg .lbls .kfig').count()) >= 3, (await p.locator('.pv-svg .lbls .kfig').allTextContents()).slice(0, 4).join(','));
  await shot('p13_hover_ports');
  let M = await p.evaluate(() => JSON.parse(JSON.stringify(window.__vfEd.model)));
  const nL0 = M.links.length;
  { // 从 CNC6 的连接点拖到 CNC5：物料线
    const src = await p.locator('.pv-svg .pv-port[data-port="CNC6:2"]').boundingBox(), tg = await bb('CNC5');
    await p.mouse.move(src.x + src.width / 2, src.y + src.height / 2); await p.mouse.down();
    await p.mouse.move(tg.x + tg.width / 2, tg.y + tg.height / 2, { steps: 12 }); await wait(200);
    const tip = await p.locator('.pv-svg .pv-conn-tip text').textContent().catch(() => '');
    await shot('p14_connecting');
    await p.mouse.up(); await wait(700);
    M = await p.evaluate(() => JSON.parse(JSON.stringify(window.__vfEd.model)));
    const nl = M.links.find((l) => l.from === 'CNC6' && l.to === 'CNC5' && (l.kind || 'material') === 'material');
    ok('拖连接点到另一台设备：生产设备之间连成物料线（拖动中提示"物料线"）', M.links.length === nL0 + 1 && !!nl && nl.from_port === 'out' && nl.to_port === 'in' && /物料线/.test(tip), JSON.stringify(nl) + ' ' + tip);
    const r = await checkRoutes(p, 'plan');
    ok('新连线也走边框端口、横竖线', r.endsOk === r.ends && r.diag === 0, `${r.endsOk}/${r.ends} 斜段 ${r.diag}`);
  }
  { // "+"：在 CNC6 后面加一台并连好
    await hoverOn('CNC6');
    await p.locator('.pv-svg .pv-plus[data-plus="CNC6"]').click(); await wait(400);
    ok('"+" 打开快速添加（只列能接在后面的类型）', (await p.locator('.pv-qa').count()) === 1 && (await p.locator('.pv-qa .qa-i').count()) >= 3, await p.locator('.pv-qa .pv-qa-t').textContent().catch(() => ''));
    await p.keyboard.type('buffer'); await wait(200); await p.keyboard.press('Enter'); await wait(800);
    const M2 = await p.evaluate(() => JSON.parse(JSON.stringify(window.__vfEd.model)));
    const nb = M2.blocks.find((x) => !M.blocks.some((y) => y.id === x.id));
    ok('"+"：新加一台放在它出口方向，并连好物料线', nb && nb.type === 'buffer' && M2.links.some((l) => l.from === 'CNC6' && l.to === nb.id) && nb.pos[0] > M.blocks.find((x) => x.id === 'CNC6').pos[0],
      JSON.stringify(nb && { id: nb.id, type: nb.type, pos: nb.pos }));
    await p.keyboard.press('Control+z'); await wait(500);
    ok('"+" 一步撤销（块和线一起）', (await p.evaluate(() => window.__vfEd.model.blocks.length)) === M.blocks.length && (await p.evaluate(() => window.__vfEd.model.links.length)) === M.links.length);
  }
  { // 拖动设备：和相邻设备对齐时出现参考线
    const q = await hoverOn('CNC6'), o = await bb('CNC3');
    await p.mouse.down(); await p.mouse.move(q.x + q.width / 2 + 9, q.y + q.height / 2 + 3, { steps: 4 });
    await p.mouse.move(q.x + q.width / 2 + (o.x - q.x) + 4, q.y + q.height / 2 - 30, { steps: 6 }); await wait(150);
    const ng = await p.locator('.pv-svg .pv-guides line').count();
    await shot('p15_align_guides');
    await p.mouse.up(); await wait(500);
    const c6 = await p.evaluate(() => window.__vfEd.model.blocks.find((x) => x.id === 'CNC6').pos), c3 = M.blocks.find((x) => x.id === 'CNC3').pos;
    ok('拖动设备：和别的设备对齐时出现参考线并吸附', ng >= 1 && Math.abs(c6[0] - c3[0]) < 0.011, `${ng} 条参考线，CNC6 x=${c6[0]} / CNC3 x=${c3[0]}`);
    await p.keyboard.press('Control+z'); await wait(400);
  }
  await p.keyboard.press('Control+z'); await wait(400);   // 撤掉刚连的物料线
  ok('撤销后连线恢复', (await p.evaluate(() => window.__vfEd.model.links.length)) === nL0);
  await p.mouse.move(t.x + 5, t.y + 300); await wait(200);

  // ---------- 浅色画布（5.0.1 只有浅色）：底色、网格、物料线 / 墙 / 设备名对比度 ----------
  { const lc = await lightCheck('.pv-svg', [['.pv-svg .ln', 'stroke'], ['.pv-svg .lw', 'stroke'], ['.pv-svg .lbls text', 'fill'], ['.pv-svg .floor', 'stroke']]);
    ok('平面图：浅色画布、有网格、线条和标签对比度 ≥ 3', lc && lc.lum > 0.85 && await p.locator('.pv-svg .grid').count() >= 1 && lc.min >= 3 && Object.keys(lc.c).length >= 2, JSON.stringify(lc));
    await shot('p09_light'); }

  // ---------- 4.3 图纸化：控制 / 通讯 / 信息系统符号、信号线与网络线、分层过滤、悬停关联高亮 ----------
  await wait(1500);
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  await require('./scripts/control_fixture').addControl(api, tok, PID);
  await p.reload({ waitUntil: 'networkidle' }); await wait(5000);
  await p.click('.ed-views >> text=平面'); await wait(1500);
  await p.evaluate(() => { window.__vfEd.filter = { layers: { process: true, control: true, network: true, it: true }, links: { material: true, signal: true, network: true } }; }); await wait(400);
  const symN = async (t) => p.locator(`.pv-svg .symb .lsym-${t}`).count();
  ok('按层画符号：PLC 柜、HMI、交换机、网关、MES', (await symN('plc')) >= 2 && (await symN('hmi')) >= 1 && (await symN('switch')) >= 1 && (await symN('gateway')) >= 1 && (await symN('mes')) >= 1,
    `plc ${await symN('plc')} hmi ${await symN('hmi')} switch ${await symN('switch')} gateway ${await symN('gateway')} mes ${await symN('mes')}`);
  await p.evaluate(() => { window.__vfEd.focusReq = { id: 'FUR1', n: 9001 }; }); await wait(600);   // 放大一点：太小时不标"N 路"
  const sigTags = await p.locator('.pv-svg .lc-signal .lc-tag text').allTextContents();
  ok('信号线：橙色虚线，一束标"6 路"', (await p.locator('.pv-svg .lc-signal').count()) >= 4 && sigTags.filter((x) => x === '6 路').length >= 3 && sigTags.every((x) => / 路$/.test(x)), sigTags.join(','));
  { // 网络线不铺满图纸：平时只画有故障的；选中交换机时画出它的全部网络线（4.3 集成）
    const net0 = await p.locator('.pv-svg .lc-network').count();
    const sw = await p.evaluate(() => (window.__vfEd.model.blocks.find((b) => b.type === 'switch') || {}).id);
    await p.evaluate((id) => { window.__vfEd.sel = [id]; }, sw); await wait(400);
    const net1 = await p.locator('.pv-svg .lc-network').count();
    ok('网络线（紫色）：平时不铺满，选中交换机时画出它的网络线', net1 >= 5 && net0 < net1, `${net0} → ${net1}`);
    await p.evaluate(() => { window.__vfEd.sel = []; }); await wait(300);
  }
  await shot('p10_layers_light');
  // 悬停 PLC：它控制的设备、信号线、网络路径高亮，其余淡化
  { const bb = await p.locator('.pv-svg .symb[data-id="PLCT1"] .sym-hit').boundingBox(); await p.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await wait(400); }
  const relOk = await p.evaluate(() => {
    const c = (sel) => document.querySelector(sel)?.getAttribute('class') || '';
    return { fur: c('.pv-svg .blk[data-id="FUR1"]'), cnc: c('.pv-svg .blk[data-id="CNC1"]'), sigRel: document.querySelectorAll('.pv-svg .lc-signal.rel').length, dim: document.querySelectorAll('.pv-svg .blk.dim').length };
  });
  ok('悬停 PLC：高亮它控制的设备和信号线，其余淡化', /\brel\b/.test(relOk.fur) && /\bdim\b/.test(relOk.cnc) && relOk.sigRel === 2 && relOk.dim > 10, JSON.stringify(relOk));
  await shot('p11_hover_plc');
  await p.mouse.move(t.x + 5, t.y + 300); await wait(300);
  // 点信号线 = 选中连线（右栏对象面板）
  { const bb = await p.locator('.pv-svg .lc-signal[data-link^="ST"] .lc-tag').first().boundingBox(); await p.mouse.click(bb.x + bb.width / 2, bb.y + bb.height / 2); await wait(400); }
  ok('点信号线选中连线', /^ST\d$/.test(await p.evaluate(() => window.__vfEd.selLink)), await p.evaluate(() => window.__vfEd.selLink));
  // 分层过滤
  await p.evaluate(() => { const f = JSON.parse(JSON.stringify(window.__vfEd.filter)); f.layers.control = false; window.__vfEd.filter = f; }); await wait(400);
  ok('过滤：关掉控制层，PLC/HMI 和它们的线都不画', (await symN('plc')) === 0 && (await symN('hmi')) === 0 && (await p.locator('.pv-svg .lc-signal').count()) === 0 && (await symN('switch')) >= 1);
  await p.evaluate(() => { const f = JSON.parse(JSON.stringify(window.__vfEd.filter)); f.layers.control = true; f.links.signal = false; f.links.material = false; window.__vfEd.filter = f; }); await wait(400);
  ok('过滤：只关信号线 / 物料线', (await symN('plc')) >= 2 && (await p.locator('.pv-svg .lc-signal').count()) === 0 && (await p.locator('.pv-svg .ln').count()) === 0);
  await p.evaluate(() => { window.__vfEd.filter = { layers: { process: true, control: true, network: true, it: true }, links: { material: true, signal: true, network: true } }; }); await wait(300);
  { // 4.4：拖连接点 设备 → PLC = 信号线（默认映射）；有控制层时连线仍然落在边框、横竖走线
    await p.evaluate(() => { window.__vfEd.sel = []; window.__vfEd.selLink = ''; window.__vfEd.focusReq = { id: 'CNC3', n: 9003 }; }); await wait(500);
    { const r0 = await p.locator('.pv-svg').boundingBox(); for (let i = 0; i < 3; i++) { await p.mouse.move(r0.x + r0.width / 2, r0.y + r0.height / 2); await p.mouse.wheel(0, -200); await wait(80); } }
    await wait(700);   // 放大到符号不和设备重叠（PLC 符号是屏幕恒定大小，缩小时会盖住旁边的设备）
    const r = await checkRoutes(p, 'plan');
    ok('有信号线 / 网络线时：端点在边框上、横竖走线、不穿设备', r.n >= 8 && r.endsOk === r.ends && r.diag === 0 && r.cross === 0, `${r.n} 条，端点 ${r.endsOk}/${r.ends}，斜段 ${r.diag}，穿过 ${r.cross} ${r.bad.slice(0, 3).join('；')}`);
    const sigLine = await p.evaluate(() => { const g = document.querySelector('.pv-svg .lc-signal[data-a="CNC1"], .pv-svg .lc-signal[data-b="CNC1"]'); return g ? g.querySelector('path').getAttribute('d') : ''; });
    ok('信号线进 PLC 是折线（不是穿过设备中心的斜线）', /Q/.test(sigLine) || /^M [\d.-]+ [\d.-]+ L [\d.-]+ [\d.-]+$/.test(sigLine.trim()), sigLine.slice(0, 80));
    const nS = await p.evaluate(() => window.__vfEd.model.links.filter((l) => l.kind === 'signal').length);
    const q = await (async () => { const b2 = await p.locator('.pv-svg .blk[data-id="CNC3"] .body').boundingBox(); await p.mouse.move(b2.x + b2.width / 2, b2.y + b2.height / 2, { steps: 3 }); await wait(300); return b2; })();
    const port = await p.locator('.pv-svg .pv-port[data-port="CNC3:1"]').boundingBox();
    const plc = await p.locator('.pv-svg .symb[data-id="PLCT2"] .sym-hit').boundingBox();
    await p.mouse.move(port.x + port.width / 2, port.y + port.height / 2); await p.mouse.down();
    await p.mouse.move(plc.x + plc.width / 2, plc.y + plc.height / 2, { steps: 12 }); await wait(200);
    const tip = await p.locator('.pv-svg .pv-conn-tip text').textContent().catch(() => '');
    await p.mouse.up(); await wait(800);
    const sl = await p.evaluate(() => window.__vfEd.model.links.filter((l) => l.kind === 'signal'));
    const nw = sl.find((l) => [l.from, l.to].includes('CNC3') && [l.from, l.to].includes('PLCT2'));
    ok('拖连接点：设备 → PLC 连成信号线（默认映射 Running/Fault/Enable…）', sl.length === nS + 1 && nw && (nw.signals || []).length >= 4 && /信号线/.test(tip), JSON.stringify(nw && { from: nw.from, to: nw.to, n: (nw.signals || []).length }) + ' ' + tip + ' ' + q.width);
    await p.keyboard.press('Control+z'); await wait(400);
  }
  { const lc = await lightCheck('.pv-svg', [['.pv-svg .lc-signal .lc-l', 'stroke'], ['.pv-svg .lc-network .lc-l', 'stroke'], ['.pv-svg .symb .sym-name', 'fill']]);
    ok('平面图分层：信号线、网络线、符号名称在浅色画布上对比度 ≥ 3', lc && lc.min >= 3 && Object.keys(lc.c).length >= 2, JSON.stringify(lc));
    await shot('p12_layers_light'); }

  await wait(1500);
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((r) => !r[1]).map((r) => r[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
