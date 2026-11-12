// 三维悬停反馈（4.4，B 机，先启动 serve）：node tests/hover3d_ui.js
// 悬停一台设备 → 描边 + 信息卡（名称、状态）+ 手形光标 + ed.hoverId；移开 → 全部消失；悬停 PLC → 它控制的单元描淡边；
// 单击 → 选中描边 + 地面选择框；双击 PLC → PLC 编程浮窗；双击控制单元 → 设备内部；浅色场景对比度（5.0.1 只有浅色）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'hv');
const PID = 'foundry-housing';
const STATE_CN = { Executing: '运行', Idle: '待机', Starved: '缺料', Blocked: '堵料', Setup: '换型', Stopped: '停机', Planned: '计划停', Moving: '行驶', WaitPLC: '等待 PLC' };
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  await api(tok, 'DELETE', `/api/p/${PID}/model/draft`);
  await api(tok, 'POST', `/api/p/${PID}/ctl/reset`);
  await api(tok, 'POST', `/api/p/${PID}/ctl`, { action: 'play', speed: 10 });
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); if (!sessionStorage.getItem('i')) { sessionStorage.setItem('i', '1'); localStorage.removeItem('vf_wb2_sizes'); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_theme', 'light'); } }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  const wait = (ms) => p.waitForTimeout(ms);
  await p.goto(B + `/p/${PID}/workbench`, { waitUntil: 'networkidle' }); await wait(8000);
  if (!(await p.evaluate(() => window.__vfEd.view === '3d'))) { await p.click('.ed-views >> text=三维'); await wait(4000); }
  await p.waitForFunction(() => window.__vfScene && window.__vfScene.hover && window.__vfScene.items.size > 10, null, { timeout: 30000 });
  const st = () => p.evaluate(() => window.__vfScene.hover.state());
  const host = await p.locator('.scene-host').boundingBox();
  // 摆相机对准设备，在它投影附近找一个确实拾取到它的屏幕点（不点到操作台按钮）
  const aim = async (id, fill = 0.45) => {
    await p.evaluate(([i, f]) => { const s = window.__vfScene; s.frameItem ? s.frameItem(i, f) : s.focusClose(i); }, [id, fill]);
    await wait(900);
    return p.evaluate((i) => {
      const s = window.__vfScene, c = s.screenOf(i, 0.3); if (!c) return null;
      for (let r = 0; r <= 160; r += 8) for (let a = 0; a < 16; a++) {
        const x = c.x + Math.cos(a / 16 * Math.PI * 2) * r, y = c.y + Math.sin(a / 16 * Math.PI * 2) * r;
        const h = s.hover.hitAt(x, y);
        if (h && h.id === i && !(s.cellPanelAt && s.cellPanelAt({ clientX: x, clientY: y }))) return { x, y };
        if (r === 0) break;
      }
      return null;
    }, id);
  };
  const empty = () => p.evaluate(([x0, y0, w, h]) => {
    const s = window.__vfScene;
    for (let fy = 0.92; fy > 0.2; fy -= 0.04) for (let fx = 0.05; fx < 0.95; fx += 0.05) { const x = x0 + w * fx, y = y0 + h * fy; if (!s.hover.hitAt(x, y)) return { x, y }; }
    return null;
  }, [host.x, host.y, host.width, host.height]);
  const moveTo = async (pt) => { await p.mouse.move(pt.x - 30, pt.y - 10); await wait(60); await p.mouse.move(pt.x, pt.y, { steps: 4 }); await wait(650); };
  const card = () => p.evaluate(() => { const c = document.querySelector('.v3-hc'); if (!c || getComputedStyle(c).display === 'none') return null; return { id: c.dataset.id, name: c.querySelector('.hc-n')?.textContent, state: c.querySelector('.hc-s b')?.textContent, figs: [...c.querySelectorAll('.hc-k div')].map((d) => d.textContent), hint: c.querySelector('.hc-hint')?.textContent, layer: c.querySelector('.hc-l')?.textContent, r: c.getBoundingClientRect().toJSON() }; });
  const shot = async (n, pt) => {
    await p.screenshot({ path: `${OUT}/${n}.png` });
    if (pt) await p.screenshot({ path: `${OUT}/${n}_zoom.png`, clip: { x: Math.max(0, pt.x - 380), y: Math.max(0, pt.y - 250), width: 760, height: 480 } });
  };

  // ---------- 悬停一台加工中心 ----------
  const M = 'CNC3';
  const pt = await aim(M);
  ok('找到设备的屏幕点', !!pt, JSON.stringify(pt));
  await moveTo(pt);
  let s1 = await st(), c1 = await card();
  const exp = await p.evaluate((i) => ({ name: window.__vfEd.model.blocks.find((x) => x.id === i).name, state: (window.__vfEd.runtime.stations.find((x) => x.id === i) || {}).state }), M);
  ok('悬停：拾取到设备', s1.hovered === M, JSON.stringify(s1));
  ok('悬停：描边', s1.outlined.hover.includes(M), JSON.stringify(s1.outlined));
  ok('悬停：手形光标', s1.cursor === 'pointer', s1.cursor);
  ok('悬停：联动 ed.hoverId', (await p.evaluate(() => window.__vfEd.hoverId)) === M);
  ok('信息卡：名称', c1 && c1.name === exp.name, JSON.stringify(c1));
  ok('信息卡：状态', c1 && c1.state === (STATE_CN[exp.state] || exp.state), `${c1?.state} vs ${exp.state}`);
  ok('信息卡：关键数字和提示', c1 && c1.figs.length >= 1 && /单击选中/.test(c1.hint || ''), JSON.stringify(c1?.figs) + ' ' + c1?.hint);
  await shot('h01_machine_light', pt);
  // ---------- 移开 ----------
  const e0 = await empty();
  await moveTo(e0);
  const s2 = await st(), c2 = await card();
  ok('移开：没有悬停 / 描边', !s2.hovered && !s2.outlined.hover.length, JSON.stringify(s2));
  ok('移开：信息卡隐藏', !c2, JSON.stringify(c2));
  ok('移开：光标恢复', s2.cursor === '', s2.cursor);
  ok('移开：ed.hoverId 清空', (await p.evaluate(() => window.__vfEd.hoverId)) === '');
  // ---------- 拖动时隐藏 ----------
  await moveTo(pt);
  await p.mouse.down(); await p.mouse.move(pt.x + 40, pt.y + 10, { steps: 5 }); await wait(200);
  ok('拖动：信息卡隐藏', !(await card()));
  await p.mouse.up(); await wait(300);
  // ---------- PLC：关联描边、卡片 ----------
  const plcPt = await aim('PLC1', 0.4);
  await moveTo(plcPt);
  const s3 = await st(), c3 = await card();
  ok('悬停 PLC：卡片显示 RUN / 控制设备', c3 && c3.name && c3.figs.some((f) => /RUN|STOP|HALT/.test(f)) && c3.figs.some((f) => /控制设备/.test(f)), JSON.stringify(c3));
  ok('悬停 PLC：它控制的单元描淡边', s3.outlined.related.includes('CELL1'), JSON.stringify(s3.outlined));
  await shot('h02_plc_light', plcPt);
  // ---------- 缓冲区 ----------
  const bufPt = await aim('cnc_in', 0.5);
  if (bufPt) { await moveTo(bufPt); const c4 = await card(); ok('悬停缓冲区：在库数量', c4 && c4.figs.some((f) => /在库/.test(f)), JSON.stringify(c4)); await shot('h03_buffer_light', bufPt); }
  else ok('悬停缓冲区：找到屏幕点', false);
  // ---------- 单辆 AGV：只描这一辆 ----------
  {
    await api(tok, 'POST', `/api/p/${PID}/ctl`, { action: 'pause' }); await wait(1500);     // 车停住再测
    let q = null, at = null;
    const ids = await p.evaluate(() => [...(window.__vfScene.items.get('AGV')?.agvs.values() || [])].filter((g) => g.visible).map((g) => g.userData.agv));
    for (const a of ids) {                            // 停在线边库旁的车可能被货箱挡住：换一辆，在投影附近找确实拾取到它的点
      await p.evaluate((a) => { const s = window.__vfScene, g = [...s.items.get('AGV').agvs.values()].find((x) => x.userData.agv === a); s.focusObject(g); s.controls.update(); }, a);
      await wait(500);
      at = await p.evaluate((a) => {
        const s = window.__vfScene, g = [...s.items.get('AGV').agvs.values()].find((x) => x.userData.agv === a);
        const v = g.position.clone(); v.y += 0.35; v.project(s.camera); const r = s.renderer.domElement.getBoundingClientRect();
        const c = { x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height };
        for (let rr = 0; rr <= 60; rr += 4) for (let k = 0; k < 12; k++) {
          const x = c.x + Math.cos(k / 12 * Math.PI * 2) * rr, y = c.y + Math.sin(k / 12 * Math.PI * 2) * rr, h = s.hover.hitAt(x, y);
          if (h && h.agv === a) return { x, y };
          if (rr === 0) break;
        }
        return null;
      }, a);
      if (at) { q = a; break; }
    }
    ok('找到一辆 AGV 的屏幕点', !!at, JSON.stringify(ids));
    if (!at) at = { x: host.x + 10, y: host.y + 10 };
    await moveTo(at);
    const sa = await st(), ca = await card();
    ok('悬停 AGV：拾取到这一辆', sa.hovered === 'AGV' && sa.agv === q && ca && ca.name === q, JSON.stringify({ sa: sa.agv, ca }));
    ok('悬停 AGV：卡片显示电量', ca && ca.figs.some((f) => /电量/.test(f)), JSON.stringify(ca?.figs));
    await shot('h07_agv_light', at);
    await api(tok, 'POST', `/api/p/${PID}/ctl`, { action: 'play', speed: 10 });
  }
  // ---------- 单击选中 ----------
  const mp = await aim(M);
  await moveTo(mp); await p.mouse.click(mp.x, mp.y); await wait(700);
  const s5 = await st();
  ok('单击：选中描边 + 地面选择框', s5.outlined.selected.includes(M) && s5.rings >= 1, JSON.stringify(s5));
  await shot('h04_selected_light', mp);
  const e1 = await empty(); await moveTo(e1); await wait(300);
  await shot('h05_selected_nohover_light', mp);
  // ---------- 浅色场景（5.0.1 只有浅色）：浅色天空、选中 / 悬停描边对天空和地面对比度 ----------
  { const lc = await p.evaluate(() => {
      const s = window.__vfScene, L = (c) => { const f = (v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); const h = c.getHex(), r = ((h >> 16) & 255) / 255, g = ((h >> 8) & 255) / 255, bl = (h & 255) / 255; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl); };
      const cr = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const bg = L(s.scene.background), u = s.hover.fsMat.uniforms;
      return { bg: +bg.toFixed(3), sel: +cr(bg, L(u.cSel.value)).toFixed(2), hov: +cr(bg, L(u.cHov.value)).toFixed(2), dark: document.documentElement.classList.contains('dark') };
    });
    ok('三维：浅色天空，选中 / 悬停描边对比度 ≥ 3', lc.bg > 0.75 && lc.sel >= 3 && lc.hov >= 3 && !lc.dark, JSON.stringify(lc)); }
  { const q = await aim('PLC1', 0.4); await moveTo(q); await shot('h12_plc_light', q); }
  { const q = await aim('cnc_in', 0.5); if (q) { await moveTo(q); await shot('h13_buffer_light', q); } }
  // ---------- 双击 PLC → 编程浮窗 ----------
  const q1 = await aim('PLC1', 0.4); await moveTo(q1);
  await p.mouse.dblclick(q1.x, q1.y); await wait(1500);
  const fl = await p.evaluate(() => window.__vfEd.floats.map((w) => w.id));
  ok('双击 PLC：打开 PLC 编程浮窗', fl.some((id) => id.startsWith('plc-editor-float')), JSON.stringify(fl));
  ok('双击后信息卡让开', !(await card()));
  await p.evaluate(() => { window.__vfEd.floats = []; }); await wait(500);
  // ---------- 双击控制单元 → 设备内部 ----------
  const q2 = await aim('CELL1', 0.7); await moveTo(q2);
  const h2 = await p.evaluate(([x, y]) => JSON.stringify(window.__vfScene.hover.hitAt(x, y), (k, v) => (k === 'obj' ? undefined : v)), [q2.x, q2.y]);
  await p.mouse.dblclick(q2.x, q2.y);
  await p.waitForFunction(() => /检测后分拣段|CELL1/.test(document.querySelector('.ce .ce-sel')?.textContent || ''), null, { timeout: 8000 }).catch(() => {});
  // ed.interior 被设备内部面板接走后清空：看面板里选中的单元
  const ins = await p.evaluate(() => ({ left: window.__vfEd.leftPanel, open: window.__vfEd.leftOpen, sel: document.querySelector('.ce .ce-sel')?.textContent || '' }));
  ok('双击控制单元：打开设备内部', ins.left === 'cell-editor' && ins.open && /检测后分拣段|CELL1/.test(ins.sel), h2 + ' ' + JSON.stringify(ins) + ' ' + (await p.evaluate(() => (document.querySelector('.ce')?.innerText || '').slice(0, 80))));
  await shot('h06_cell_interior');
  // 普通设备 → 它的控制点（设备内部的 I/O 板）
  await p.evaluate(() => { window.__vfEd.leftPanel = 'outliner'; }); await wait(400);
  const q3 = await aim('CNC2'); await moveTo(q3);
  await p.mouse.dblclick(q3.x, q3.y);
  await p.waitForFunction(() => !!document.querySelector('.ce .ce-dev'), null, { timeout: 8000 }).catch(() => {});
  const dv = await p.evaluate(() => ({ left: window.__vfEd.leftPanel, dev: !!document.querySelector('.ce .ce-dev'), txt: (document.querySelector('.ce .ce-dev')?.textContent || '').slice(0, 60) }));
  ok('双击加工中心：打开它的设备内部', dv.left === 'cell-editor' && dv.dev, JSON.stringify(dv));
  // ---------- 其他视图悬停 → 三维也描边 ----------
  await p.evaluate(() => { window.__vfEd.hoverId = 'CNC1'; }); await wait(300);
  const s6 = await st();
  ok('外部悬停联动三维描边', s6.outlined.hover.includes('CNC1'), JSON.stringify(s6.outlined));
  await p.evaluate(() => { window.__vfEd.hoverId = ''; });
  ok('无页面错误', errs.length === 0, errs.join(' | '));
  const perf = (await st()).perf;
  console.log('perf', JSON.stringify(perf), 'avg pick ms', (perf.pickMs / Math.max(1, perf.picks)).toFixed(2), 'avg fx ms', (perf.fxMs / Math.max(1, perf.fxFrames)).toFixed(2));
  const n = res.filter((r) => r[1]).length;
  console.log(`\n${n}/${res.length} passed`);
  await b.close();
  process.exit(n === res.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
