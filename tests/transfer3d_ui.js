// 三维"物料输送（自动）"图层（4.6，B 机，先启动 serve）：node tests/transfer3d_ui.js
// 示范工厂：冷却线 → 待抛丸有输送段（短辊道）、机加区有输送段、AGV 连线画行驶线；图层菜单里关掉 → 隐藏，再打开 → 显示；
// 运行中有箱子沿输送段走（两次采样位置在变）；设备离得远时自动出现输送段（改位置的模型副本，不改工厂）；
// 小型铸造厂（课程布局）：冷却线一直铺到落砂（两头 ≤ 1.5 m）；全程没有页面错误；浅色截图（5.0.1 只有浅色）。
// 环境变量：VF_URL（默认 http://127.0.0.1:8800）、SHOT_DIR、VF_PID_MINI（小型铸造厂的工厂编号，没有就跳过那几项）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'tr3');
const PID = process.env.VF_PID || 'foundry-housing', MINI = process.env.VF_PID_MINI || '';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json().catch(() => null);
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const errs = [];
  const open = async (pid, theme = 'light') => {
    await api(tok, 'DELETE', `/api/p/${pid}/model/draft`);
    await api(tok, 'POST', `/api/p/${pid}/ctl`, { action: 'play', speed: 10 });
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 900 } });
    await ctx.addInitScript(([t, th]) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); if (!sessionStorage.getItem('i')) { sessionStorage.setItem('i', '1'); localStorage.removeItem('vf_wb2_sizes'); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_theme', th); } }, [tok, theme]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404|WebSocket/.test(m.text())) errs.push(m.text().slice(0, 200)); });
    await p.goto(B + `/p/${pid}/workbench`, { waitUntil: 'networkidle' }); await p.waitForTimeout(7000);
    if (!(await p.evaluate(() => window.__vfEd.view === '3d'))) { await p.click('.ed-views >> text=三维'); await p.waitForTimeout(4000); }
    await p.waitForFunction(() => window.__vfScene && window.__vfScene.transfer && window.__vfScene.transfer.rev > 0, null, { timeout: 30000 });
    return { ctx, p };
  };
  const look = (p, cam) => p.evaluate((c) => { const s = window.__vfScene; s.setCam(c); s.autoView = false; }, cam);
  const shot = async (p, n) => { const host = await p.locator('.scene-host').boundingBox(); await p.waitForTimeout(1500); await p.screenshot({ path: `${OUT}/${n}.png`, clip: host }); };

  // ---------- 示范工厂 ----------
  const { ctx, p } = await open(PID);
  const secs = await p.evaluate(() => window.__vfScene.transfer.sections());
  const by = Object.fromEntries(secs.map((s) => [s.link, s]));
  const cool = secs.find((s) => s.from === 'COOL1');
  ok('冷却线出口到待抛丸有输送段', cool && cool.to === 'shot_in' && cool.kind === 'roller' && cool.len > 0.3, JSON.stringify(cool));
  ok('机加区有输送段（CNC 上下料）', secs.filter((s) => /^CNC/.test(s.from) || /^CNC/.test(s.to)).length >= 6, secs.filter((s) => /^CNC/.test(s.to)).map((s) => s.link).join(','));
  ok('AGV 连线画行驶线、不铺输送机', by.L26?.kind === 'agv' && by.L27?.kind === 'agv', JSON.stringify([by.L26?.kind, by.L27?.kind]));
  ok('铁水 / 浇包连线不铺输送机', !by.L1 && !by.L2 && !by.L3, Object.keys(by).join(','));
  const st = await p.evaluate(() => window.__vfScene.transfer.stats());
  ok('实例化：绘制调用少', st.drawCalls <= 20 && st.instances > 100, JSON.stringify(st));
  // 零件沿输送段走：同一个箱子两次采样位置不同
  let moved = null;
  for (let k = 0; k < 40 && !moved; k++) {
    const a = await p.evaluate(() => window.__vfScene.transfer.moversNow());
    await p.waitForTimeout(250);
    const c = await p.evaluate(() => window.__vfScene.transfer.moversNow());
    for (const x of a) { const y = c.find((q) => q.link === x.link && q.f > x.f); if (y && Math.hypot(y.x - x.x, y.y - x.y) > 0.05) { moved = [x, y]; break; } }
    if (!moved) await p.waitForTimeout(250);
  }
  ok('运行中零件沿输送段移动', moved, JSON.stringify(moved));
  await look(p, { pos: [60, 18, 36], target: [70, 0, 12] }); await shot(p, 'tr_cool_light');
  await look(p, { pos: [100, 22, 40], target: [104, 0, 12] }); await shot(p, 'tr_machining_light');
  // 图层菜单：关掉 / 打开
  await p.click('.v3-bar >> text=图层'); await p.waitForTimeout(400);
  const cb = p.locator('.v3-lay .el-checkbox', { hasText: '物料输送（自动）' });
  ok('图层菜单里有"物料输送（自动）"', await cb.count() === 1);
  await cb.click(); await p.waitForTimeout(500);
  const off = await p.evaluate(() => ({ g: window.__vfScene.transfer.group.visible, n: window.__vfScene.transfer.moverMesh.count }));
  ok('关掉图层 → 输送设备和箱子都隐藏', !off.g && off.n === 0, JSON.stringify(off));
  await shot(p, 'tr_machining_off');
  await cb.click(); await p.waitForTimeout(500);
  ok('再打开 → 显示', await p.evaluate(() => window.__vfScene.transfer.group.visible));
  await p.keyboard.press('Escape');
  // 设备离远了自动补输送段（模型副本，不改工厂）
  const pv = await p.evaluate(() => {
    const m = JSON.parse(JSON.stringify(window.__vfEd.model)), s = m.blocks.find((x) => x.id === 'shot_in'); s.pos = [s.pos[0], s.pos[1] + 9];
    return window.__vfScene.transfer.preview(m).find((x) => x.link === 'L6');
  });
  ok('拉开距离后自动出现输送段', pv && pv.len > 8, JSON.stringify(pv));
  // 穿过通道的段架高（过道桥）：在模型副本里画一条横穿冷却线出口的竖向通道
  const ov = await p.evaluate(() => {
    const m = JSON.parse(JSON.stringify(window.__vfEd.model)), s = m.blocks.find((x) => x.id === 'shot_in'); s.pos = [s.pos[0], s.pos[1] + 9];
    m.plant = m.plant || {}; m.plant.layout = { ...(m.plant.layout || {}), aisles: [{ pts: [[60, -2], [60, 40]], w: 3 }, { pts: [[0, 18], [150, 18]], w: 3 }] };
    return window.__vfScene.transfer.preview(m).find((x) => x.link === 'L6');
  });
  ok('穿过通道的输送段架高', ov && ov.over, JSON.stringify(ov));
  // 架高的样子（截图）：内存里临时加一条横穿机加区上料段的通道（不保存），看完还原
  const aisleOn = await p.evaluate(async () => {
    const L = window.__vfEd.model.plant.layout || (window.__vfEd.model.plant.layout = {}), keep = L.aisles;
    L.aisles = [{ pts: [[86, 6], [112, 6]], w: 2.4 }];
    const r0 = window.__vfScene.transfer.rev; for (let i = 0; i < 40 && window.__vfScene.transfer.rev === r0; i++) await new Promise((r) => setTimeout(r, 100));
    const n = window.__vfScene.transfer.sections().filter((s) => s.over).length;
    window.__vfKeepAisles = keep === undefined ? null : keep; return n;
  });
  ok('临时通道：穿过的上料段架高', aisleOn > 0, aisleOn);
  await look(p, { pos: [92, 14, 26], target: [98, 1, 6] }); await shot(p, 'tr_bridge_light');
  await p.evaluate(() => { const L = window.__vfEd.model.plant.layout; if (window.__vfKeepAisles === null) delete L.aisles; else L.aisles = window.__vfKeepAisles; });
  await p.waitForTimeout(1200);
  ok('通道去掉后恢复', (await p.evaluate(() => window.__vfScene.transfer.sections().filter((s) => s.over).length)) === 0);
  // 语义缩放：拉远隐藏辊子 / 支腿
  await p.evaluate(() => window.__vfScene.viewPreset('top')); await p.waitForTimeout(800);
  ok('拉远隐藏细节（辊子、支腿）', !(await p.evaluate(() => window.__vfScene.transfer.detail.visible)));
  await shot(p, 'tr_top_light');
  await ctx.close();

  // ---------- 小型铸造厂（课程布局）：冷却线铺到落砂 ----------
  if (MINI) {
    const m = await open(MINI);
    const g = await m.p.evaluate(() => {
      const bl = Object.fromEntries(window.__vfEd.model.blocks.map((x) => [x.id, x])), C = bl.COOL, S = bl.SHAKE;
      return S.pos[0] - S.size[0] / 2 - (C.pos[0] + C.size[0] / 2);
    });
    ok('小型铸造厂：冷却线一直铺到落砂（≤ 1.5 m）', g >= 0 && g <= 1.5, g);
    const secs2 = await m.p.evaluate(() => window.__vfScene.transfer.sections());
    ok('小型铸造厂：没有超过 6 m 的空隙输送段', secs2.every((s) => s.len <= 6), secs2.map((s) => `${s.link}:${s.len}`).join(' '));
    await look(m.p, { pos: [48, 16, 34], target: [58, 0, 8] }); await shot(m.p, 'tr_mini_cool_shake');
    await m.ctx.close();
  }
  ok('没有页面错误', !errs.length, errs.join(' | '));
  await b.close();
  const pass = res.filter((r) => r[1]).length;
  console.log(`\n${pass}/${res.length} passed`);
  process.exit(pass === res.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
