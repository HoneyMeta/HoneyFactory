// 架构图（4.3 第四张图）界面验收（B 机，先启动 serve）：node tests/arch_ui.js
// 泳道（信息系统 → 通讯 → 控制 → 生产设备）、自动布局（PLC 在它控制的设备上方）、网络线、信号束"N 路"及展开、悬停关联高亮、
// 选中、拖动手动排列（arch）、右键菜单、"＋ 新增"、拖圆点连信号线、传感器/执行器展开、只看接了 PLC 的设备、过滤、浅色画布对比度
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const { addControl } = require('./scripts/control_fixture');
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'arch');
const PID = 'foundry-housing';
const res = [];
const { checkRoutes } = require('./scripts/route_check');
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 260)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  await addControl(api, tok, PID);
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => {
    localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN');
    if (!sessionStorage.getItem('i')) {
      sessionStorage.setItem('i', '1'); localStorage.removeItem('vf_wb2_sizes'); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0');
      localStorage.setItem('vf_theme', 'light'); localStorage.removeItem('vf_arch_only'); localStorage.removeItem('vf_filter');
    }
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
  const model = () => p.evaluate(() => JSON.parse(JSON.stringify(window.__vfEd.model)));
  await p.goto(B + `/p/${PID}/workbench`, { waitUntil: 'networkidle' }); await wait(6000);
  await p.click('.ed-views >> text=架构'); await wait(2500);
  ok('架构图打开', (await p.locator('.av-svg').count()) === 1);
  const m0 = await model();
  const ctlDevs = (mm) => new Set(mm.links.filter((l) => l.kind === 'signal').flatMap((l) => [l.from, l.to]).filter((id) => { const t = mm.blocks.find((x) => x.id === id)?.type; return t && !['plc', 'hmi'].includes(t); })).size;
  const nCtlWant = ctlDevs(m0), nPlc = m0.blocks.filter((x) => x.type === 'plc').length;
  ok('有信号线时默认只看接了 PLC 的设备', (await p.locator('.av-n.ly-process').count()) === nCtlWant, `${await p.locator('.av-n.ly-process').count()} / ${nCtlWant}`);

  // ---------- 泳道与布局 ----------
  const laneT = await p.locator('.av-lane-t').allTextContents();
  ok('四条泳道，自上而下：信息系统 → 通讯 → 控制 → 生产设备', laneT.join(',') === '信息系统,通讯,控制,生产设备', laneT.join(','));
  const box = async (id) => p.locator(`.av-n[data-id="${id}"] .av-nb`).boundingBox();
  const [mes, sw, plc1, plc2, fur1, fur2, cnc1] = await Promise.all(['MES1', 'SW1', 'PLCT1', 'PLCT2', 'FUR1', 'FUR2', 'CNC1'].map(box));
  ok('分层自上而下：MES 在交换机上方，交换机在 PLC 上方，PLC 在设备上方', mes && sw && plc1 && fur1 && mes.y < sw.y && sw.y < plc1.y && plc1.y < fur1.y,
    JSON.stringify([mes?.y, sw?.y, plc1?.y, fur1?.y].map((x) => Math.round(x || 0))));
  const cx = (q) => q.x + q.width / 2;
  ok('PLC 放在它控制的设备上方附近', Math.abs(cx(plc1) - (cx(fur1) + cx(fur2)) / 2) < plc1.width * 1.6 && cx(plc2) > cx(plc1) && Math.abs(cx(plc2) - cx(cnc1)) < plc2.width * 2.2,
    `PLC1 ${Math.round(cx(plc1))} / 熔炉 ${Math.round((cx(fur1) + cx(fur2)) / 2)}；PLC2 ${Math.round(cx(plc2))} / CNC1 ${Math.round(cx(cnc1))}`);
  ok('PLC 和网关等显示图纸符号', (await p.locator('.av-n .lsym-plc').count()) === nPlc && (await p.locator('.av-n .lsym-gateway').count()) >= 1 && (await p.locator('.av-n .lsym-mes').count()) >= 1);
  const tags = await p.locator('.av-signal .av-tag text').allTextContents();
  ok('信号线按设备 ⇄ PLC 合成一束，标"N 路"', tags.filter((x) => x === '6 路').length === 4 && tags.every((x) => /^\d+ 路$/.test(x)), tags.join(','));
  ok('网络线', (await p.locator('.av-network').count()) >= 4, await p.locator('.av-network .av-tag text').allTextContents().then((x) => x.join(',')));
  { // 4.4：端口在卡片边框上、正交走线、不穿过别的卡片；标签不互相压
    const r = await checkRoutes(p, 'arch');
    ok('连线：端点在卡片边框上、只有横竖段、不穿过别的卡片', r.n >= 8 && r.endsOk === r.ends && r.diag === 0 && r.cross === 0, `${r.n} 条，端点 ${r.endsOk}/${r.ends}，斜段 ${r.diag}，穿过 ${r.cross} ${r.bad.slice(0, 3).join('；')}`);
    const ov = await p.evaluate(() => { const bs = [...document.querySelectorAll('.av-tag rect')].map((e) => e.getBoundingClientRect()); let n = 0;
      for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) { const a = bs[i], b = bs[j]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) n++; } return [bs.length, n]; });
    ok('线上的标签（N 路、协议）互不重叠', ov[0] >= 4 && ov[1] === 0, `${ov[0]} 个标签，${ov[1]} 处重叠`);
  }
  await shot('a01_overview');

  // ---------- 展开一束信号 ----------
  await p.locator('.av-tag[data-bundle="signal:FUR1|PLCT1"]').click(); await wait(400);
  const sigRows = await p.locator('.av-sigs text').allTextContents();
  ok('点"6 路"展开每一路信号（通道、方向、点位）', sigRows.length === 6 && sigRows.some((x) => /I\d+\.0.*Running/.test(x)) && sigRows.some((x) => /Q\d+\.0.*Enable/.test(x)), sigRows.slice(0, 3).join(' | '));
  await shot('a02_bundle_open');
  await p.locator('.av-tag[data-bundle="signal:FUR1|PLCT1"]').click(); await wait(300);

  // ---------- 悬停高亮 ----------
  { const q = await box('PLCT1'); await p.mouse.move(q.x + 30, q.y + 10); await wait(400); }
  const hov = await p.evaluate(() => {
    const c = (id) => document.querySelector(`.av-n[data-id="${id}"]`)?.getAttribute('class') || '';
    return { fur: c('FUR1'), sw: c('SW1'), mes: c('MES1'), cnc: c('CNC1'), dim: document.querySelectorAll('.av-n.dim').length, rel: document.querySelectorAll('.av-w.rel').length };
  });
  ok('悬停 PLC：高亮它控制的设备、网络路径到 MES，其余淡化', /\brel\b/.test(hov.fur) && /\brel\b/.test(hov.sw) && /\brel\b/.test(hov.mes) && /\bdim\b/.test(hov.cnc) && hov.dim >= 3 && hov.rel >= 3, JSON.stringify(hov));
  await shot('a03_hover');

  // ---------- 选中、拖动（手动位置存在 arch） ----------
  { const q = await box('PLCT1'); await p.mouse.click(q.x + 30, q.y + 10); await wait(300); }
  ok('单击选中（ed.sel）', (await p.evaluate(() => window.__vfEd.sel.join(','))) === 'PLCT1');
  { const q = await box('PLCT1'); await p.mouse.move(q.x + 30, q.y + 10); await p.mouse.down(); await p.mouse.move(q.x + 120, q.y + 14, { steps: 6 }); await p.mouse.up(); await wait(700); }
  let m = await model();
  const arch = m.blocks.find((x) => x.id === 'PLCT1').arch;
  ok('拖动手动排列，位置存在 arch: [x, 泳道内 y]', Array.isArray(arch) && arch.length === 2, JSON.stringify(arch));
  const plc1b = await box('PLCT1');
  ok('拖动后卡片留在新位置', Math.abs(plc1b.x - plc1.x) > 40, `${Math.round(plc1.x)} → ${Math.round(plc1b.x)}`);

  // ---------- 右键 ----------
  { const q = await box('PLCT1'); await p.mouse.click(q.x + 30, q.y + 10, { button: 'right' }); await wait(400); }
  const items = await p.locator('.xm .xm-i').allTextContents();
  ok('右键 PLC：共用菜单 + 打开程序 / 接入网络 / 恢复自动位置', items.some((x) => x.includes('打开 PLC 程序')) && items.some((x) => x.includes('接入网络')) && items.some((x) => x.includes('恢复自动位置')) && items.some((x) => x.includes('删除')),
    items.slice(0, 8).join(' | '));
  await p.locator('.xm .xm-i:has-text("恢复自动位置")').click(); await wait(600);
  m = await model();
  ok('恢复自动位置（清掉 arch）', !m.blocks.find((x) => x.id === 'PLCT1').arch);
  { const q = await box('FUR1'); await p.mouse.click(q.x + 40, q.y + 10, { button: 'right' }); await wait(400); }
  const items2 = await p.locator('.xm .xm-i').allTextContents();
  ok('右键设备：加 PLC 控制', items2.some((x) => x.includes('加 PLC 控制')), items2.slice(0, 6).join(' | '));
  await p.keyboard.press('Escape'); await wait(200);

  // ---------- ＋ 新增（控制泳道加一台 HMI） ----------
  const nHmi = m.blocks.filter((x) => x.type === 'hmi').length;
  await p.locator('.av-add[data-add="control"]').click(); await wait(400);
  await p.locator('.xm .xm-i:has-text("HMI 触摸屏")').click(); await wait(800);
  m = await model();
  const newHmi = m.blocks.filter((x) => x.type === 'hmi');
  ok('控制泳道"＋ 新增" HMI', newHmi.length === nHmi + 1 && (await p.evaluate(() => window.__vfEd.sel[0])) === newHmi[newHmi.length - 1].id, newHmi.map((x) => x.id).join(','));

  // ---------- 传感器 / 执行器 ----------
  await p.locator('.av-fx[data-field="FUR1"]').click(); await wait(500);
  ok('展开设备的传感器 / 执行器（信号线上的每一路）', (await p.locator('.av-n[data-id="FUR1"] .av-field > g').count()) === 6);
  await shot('a04_field');
  await p.locator('.av-fx[data-field="FUR1"]').click(); await wait(300);

  // ---------- 显示全部设备 / 只看接了 PLC 的设备 ----------
  const nCtl0 = await p.locator('.av-n.ly-process').count();
  await p.evaluate(() => { window.__vfEd.sel = []; window.__vfEd.selLink = ''; }); await wait(200); await p.locator('.av-bar .el-checkbox:has-text("只看接了 PLC 的设备")').click(); await wait(800);
  const nAll = await p.locator('.av-n.ly-process').count();
  ok('取消"只看接了 PLC 的设备"：全部设备', nAll > 15 && nCtl0 === nCtlWant, `${nCtl0} → ${nAll}`);
  await p.click('.av-bar button:has-text("显示全部")'); await wait(500);
  await shot('a05_all_devices');
  // ---------- 悬停卡片出现四个连接点；拖到另一张卡片上连线：PLC2 → CNC3 = 信号线 ----------
  const nSig = m.links.filter((l) => l.kind === 'signal').length;
  { const q = await box('PLCT2'); await p.mouse.move(q.x + 40, q.y + 10); await wait(300); }
  ok('悬停卡片：四条边中点出现连接点', (await p.locator('.av-svg .av-port').count()) === 4);
  { const pt = await p.locator('.av-svg .av-port[data-port="PLCT2:1"]').boundingBox(), z = await box('CNC3');
    await p.mouse.move(pt.x + pt.width / 2, pt.y + pt.height / 2); await p.mouse.down(); await p.mouse.move(z.x + 30, z.y + 20, { steps: 10 }); await wait(200);
    const tip = await p.locator('.av-conn-tip text').textContent().catch(() => '');
    await shot('a07_connecting');
    await p.mouse.up(); await wait(800);
    m = await model();
    const sl = m.links.filter((l) => l.kind === 'signal');
    ok('拖连接点：设备 ⇄ PLC 自动成信号线（默认映射，拖动中提示"信号线"）', sl.length === nSig + 1 && sl.some((l) => [l.from, l.to].includes('CNC3') && [l.from, l.to].includes('PLCT2') && (l.signals || []).length >= 6) && /信号线/.test(tip), sl.length + ' ' + tip);
  }
  { // PLC2 → 网关：网络线
    const nNet = m.links.filter((l) => l.kind === 'network').length;
    const q = await box('PLCT2'); await p.mouse.move(q.x + 40, q.y + 10); await wait(300);
    const pt = await p.locator('.av-svg .av-port[data-port="PLCT2:3"]').boundingBox(), z = await box('GW1');
    await p.mouse.move(pt.x + pt.width / 2, pt.y + pt.height / 2); await p.mouse.down(); await p.mouse.move(z.x + 40, z.y + 15, { steps: 10 }); await p.mouse.up(); await wait(800);
    m = await model();
    const nl = m.links.filter((l) => l.kind === 'network');
    ok('拖连接点：PLC → 网关 自动成网络线', nl.length === nNet + 1 && nl.some((l) => [l.from, l.to].includes('PLCT2') && [l.from, l.to].includes('GW1')), nl.length);
    const r = await checkRoutes(p, 'arch');
    ok('新连线也走边框端口、横竖线、不穿卡片', r.endsOk === r.ends && r.diag === 0 && r.cross === 0, `端点 ${r.endsOk}/${r.ends} 斜段 ${r.diag} 穿过 ${r.cross} ${r.bad.slice(0, 2).join('；')}`);
  }

  await p.evaluate(() => { window.__vfEd.sel = []; window.__vfEd.selLink = ''; }); await wait(200); await p.locator('.av-bar .el-checkbox:has-text("只看接了 PLC 的设备")').click(); await wait(800);
  ok('只看接了 PLC 的设备（新接的 CNC3 也在）', (await p.locator('.av-n.ly-process').count()) === nCtlWant + 1, await p.locator('.av-n.ly-process').count());
  await p.click('.av-bar button:has-text("显示全部")'); await wait(400);
  // ---------- 过滤（共用 ed.filter） ----------
  await p.evaluate(() => { window.__vfEd.filter = { layers: { process: true, control: true, network: true, it: false }, links: { material: true, signal: false, network: true } }; }); await wait(500);
  ok('过滤：关掉信息系统层和信号线', (await p.locator('.av-lane-t').count()) === 3 && (await p.locator('.av-signal').count()) === 0 && (await p.locator('.av-n[data-id="MES1"]').count()) === 0);
  await p.evaluate(() => { window.__vfEd.filter = { layers: { process: true, control: true, network: true, it: true }, links: { material: true, signal: true, network: true } }; }); await wait(400);

  // ---------- 删除选中（工作台 Del） ----------
  await p.evaluate(() => { window.__vfEd.sel = []; });
  { const id = newHmi[newHmi.length - 1].id, q = await box(id); await p.mouse.click(q.x + 30, q.y + 10); await wait(200); await p.keyboard.press('Delete'); await wait(600); }
  m = await model();
  ok('选中后 Del 删除', m.blocks.filter((x) => x.type === 'hmi').length === nHmi);

  // ---------- 浅色画布（5.0.1 只有浅色）：底色、网格、网络线 / 信号线 / 卡片名称对比度 ----------
  { const lc = await lightCheck('.av-svg', [['.av-network .av-wl', 'stroke'], ['.av-signal .av-wl', 'stroke'], ['.av-nm', 'fill'], ['.av-lane-t', 'fill']]);
    ok('架构图：浅色画布、有网格、连线和文字对比度 ≥ 3', lc && lc.lum > 0.85 && /gradient/.test(lc.img) && lc.min >= 3 && Object.keys(lc.c).length >= 3, JSON.stringify(lc));
    await shot('a06_light'); }

  await wait(1500);
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((r) => !r[1]).map((r) => r[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
