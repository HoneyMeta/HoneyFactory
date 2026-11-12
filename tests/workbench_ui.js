// 工作台界面验收（B 机，先启动 serve）：node tests/workbench_ui.js [run,ai]
// run：运行/暂停/单步、暂停中改参数立即生效、断点命中定位、回放、重置、瓶颈着色、分屏、旧地址跳转
// shell（4.6）：选中设备后右栏切到"属性"；右键拖动不弹菜单；右键菜单"快捷键一览"；测距时右键第一项"取消测距"
// ai ：右下角助手（页面上下文、人话进度、先试算再提议、应用到草稿可撤销、带去看）
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'wb');
const only = process.argv[2] ? process.argv[2].split(',') : ['run', 'shell', 'ai'];
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const api = async (tok, method, url, body) => (await fetch(B + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: body ? JSON.stringify(body) : undefined })).json();

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); if (!sessionStorage.getItem('vf_t')) { sessionStorage.setItem('vf_t', '1'); localStorage.removeItem('vf_wb_sizes'); localStorage.removeItem('vf_ai_thread'); localStorage.setItem('vf_ai_open', '0'); } }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404|409/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  const badge = () => p.locator('.ed-mode').innerText();
  const runBtn = () => p.locator('.ed-bar .rb > .el-button').nth(1);
  await api(tok, 'DELETE', '/api/p/foundry-housing/model/draft');
  for (const x of await api(tok, 'GET', '/api/p/foundry-housing/breakpoints')) await api(tok, 'DELETE', `/api/p/foundry-housing/breakpoints/${x.id}`);
  await api(tok, 'POST', '/api/p/foundry-housing/ctl', { action: 'play', speed: 60 });

  if (only.includes('run')) {
    await p.goto(B + '/p/foundry-housing/cockpit', { waitUntil: 'networkidle' }); await wait(9000);
    ok('旧驾驶舱地址跳到工作台', p.url().endsWith('/p/foundry-housing/workbench'), p.url());
    ok('默认三维视图、运行中', (await p.locator('.scene-host canvas').count()) === 1 && (await badge()) === '运行中', await badge());
    await shot('w01_run');
    await runBtn().click(); await wait(1500);
    ok('暂停', (await badge()) === '已暂停', await badge());
    const t0 = (await api(tok, 'GET', '/api/p/foundry-housing/state')).t;
    await p.locator('.ed-bar .rb .el-dropdown').first().click(); await wait(300);
    await p.click('.el-dropdown-menu__item:has-text("前进 10 分钟")'); await wait(1500);
    const t1 = (await api(tok, 'GET', '/api/p/foundry-housing/state')).t;
    ok('单步 10 分钟', Math.abs(t1 - t0 - 600) < 2, `${t0} → ${t1}`);
    // 暂停中改参数：立即作用到运行中的工厂
    await p.dblclick('.ol-i:has-text("CNC2")'); await wait(800);
    await p.click('.ed-right .el-tabs__item:has-text("属性")'); await wait(300);
    const mttr = p.locator('.dt .f', { has: p.locator('label', { hasText: /^平均修复时间/ }) }).locator('input');
    await mttr.fill('33'); await mttr.press('Enter'); await wait(2500);
    const live = await api(tok, 'GET', '/api/p/foundry-housing/station/CNC2');
    ok('暂停中改参数立即生效', live.cfg.mttr_min === 33 && (await p.locator('.ed-chip.warn').count()) === 1, `运行中 mttr=${live.cfg.mttr_min}；${await p.locator('.ed-chip.warn').innerText().catch(() => '')}`);
    await shot('w02_edit_paused');
    // 实时页 + 断点
    await p.dblclick('.ol-i:has-text("CNC3")'); await wait(600);
    await p.click('.ed-right .el-tabs__item:has-text("实时")'); await wait(2500);
    ok('实时页（原设备抽屉）', await p.locator('.lp .lp-kv b').count() > 3);
    await p.click('.lp button:has-text("故障时暂停")'); await wait(600);
    await shot('w03_live');
    await runBtn().click(); await wait(2000);
    const faults = (await api(tok, 'GET', '/api/p/foundry-housing/station/CNC3')).faults;
    await api(tok, 'POST', '/api/p/foundry-housing/station/CNC3/fault', { kind: Object.keys(faults)[0] }); await wait(3500);
    ok('断点命中：暂停并通知、定位', (await badge()) === '已暂停' && (await p.locator('.el-notification').count()) > 0, await p.locator('.el-notification').first().innerText().catch(() => ''));
    await shot('w04_breakpoint');
    await api(tok, 'POST', '/api/p/foundry-housing/station/CNC3/fault', { kind: 'clear' });
    // 回放
    await wait(1500);   // 时间轴常驻底部（外壳 4.0）
    const sl = await p.locator('.tl .el-slider__runway').boundingBox();
    await p.mouse.click(sl.x + sl.width * 0.4, sl.y + sl.height / 2); await wait(2500);
    ok('拖时间轴进入回放', (await badge()) === '回放' && (await p.locator('.tl-badge').count()) === 1, await p.locator('.tl-h b').innerText().catch(() => ''));
    await shot('w05_replay');
    await p.click('.tl button:has-text("回到实时")'); await wait(800);
    // 瓶颈着色、分屏
    await p.click('.v3-bar button:has-text("瓶颈分析")'); await wait(2500);
    ok('瓶颈着色', (await p.locator('.v3-legend').count()) === 1);
    await shot('w06_bottleneck');
    await p.click('.split-btn'); await wait(2500);
    ok('三维 + 流程图分屏', (await p.locator('.vp.split .vue-flow__node').count()) > 10 && (await p.locator('.vp.split canvas').count()) >= 1);
    await shot('w06b_split');
    await p.click('.split-btn'); await wait(800);
    // 重置：放弃改动 → 编辑状态
    await p.click('.ed-bar .rb > .el-button >> nth=0'); await wait(800);
    const tr0 = Date.now();
    await p.click('.el-message-box__btns button:has-text("放弃这些改动")');
    for (let i = 0; i < 60 && !(await badge()).startsWith('编辑'); i++) await wait(1000);
    await wait(1000);
    console.log('  重置用时', Math.round((Date.now() - tr0) / 1000), '秒');
    const cnc2 = await api(tok, 'GET', '/api/p/foundry-housing/station/CNC2');
    ok('重置：放弃改动后进入编辑状态', (await badge()).startsWith('编辑') && cnc2.cfg.mttr_min !== 33, `${await badge()}；mttr=${cnc2.cfg.mttr_min}`);
    await shot('w07_reset');
    await runBtn().click(); await wait(2000);
    ok('从编辑状态开始运行', (await badge()) === '运行中', await badge());
    for (const x of await api(tok, 'GET', '/api/p/foundry-housing/breakpoints')) await api(tok, 'DELETE', `/api/p/foundry-housing/breakpoints/${x.id}`);
  }

  if (only.includes('shell')) {
    if (!p.url().includes('/workbench')) { await p.goto(B + '/p/foundry-housing/workbench', { waitUntil: 'networkidle' }); await wait(8000); }
    const edv = (k) => p.evaluate((k) => window.__vfEd[k], k);
    /** 流程图里把这张卡片移到视野中间，再用鼠标点它（卡片可能在画面外）。 */
    const clickNode = async (id, button = 'left') => {
      await p.evaluate((id) => { const e = window.__vfEd; e.focusReq = { id, keepZoom: false, n: Date.now() }; }, id); await wait(1500);
      const bb = await p.locator(`.vue-flow__node[data-id="${id}"]`).first().boundingBox();
      if (bb) await p.mouse.click(bb.x + bb.width / 2, bb.y + 14, { button });
    };
    const setv = (o) => p.evaluate((o) => Object.assign(window.__vfEd, o), o);
    const menuShown = () => p.locator('.xm').isVisible().catch(() => false);
    // ---- 选中后右栏切到"属性"：三维 / 平面 / 流程 / 架构 ----
    await setv({ view: '3d', split: false }); await wait(2500);
    await p.waitForFunction(() => window.__vfScene && window.__vfScene.items.size > 10, null, { timeout: 30000 }).catch(() => null);
    await setv({ sel: [], rightTab: 'live' }); await wait(300);
    await p.evaluate(() => { const s = window.__vfScene; s.frameItem ? s.frameItem('CNC2') : s.focusClose('CNC2'); }); await wait(1500);
    const c2 = await p.evaluate(() => window.__vfScene.screenOf('CNC2', 0.3));
    if (c2) { await p.mouse.click(c2.x, c2.y); await wait(800); }
    ok('三维里点设备 → 右栏切到"属性"', (await edv('sel')).includes('CNC2') && (await edv('rightTab')) === 'props', `${JSON.stringify(await edv('sel'))} ${await edv('rightTab')}`);
    await setv({ view: 'plan', sel: [], rightTab: 'live' }); await wait(2500);
    await p.locator('.pv-svg [data-id="CNC3"]').first().click({ force: true }); await wait(600);
    ok('平面图里点设备 → 右栏切到"属性"', (await edv('sel')).includes('CNC3') && (await edv('rightTab')) === 'props', `${JSON.stringify(await edv('sel'))} ${await edv('rightTab')}`);
    await setv({ view: 'graph', sel: [], rightTab: 'live' }); await wait(2500);
    await clickNode('CNC4'); await wait(600);
    ok('流程图里点设备 → 右栏切到"属性"', (await edv('sel')).includes('CNC4') && (await edv('rightTab')) === 'props', `${JSON.stringify(await edv('sel'))} ${await edv('rightTab')}`);
    await setv({ view: 'arch', sel: [], rightTab: 'live' }); await wait(3000);
    const aid = await p.evaluate(() => { const e = [...document.querySelectorAll('.av-svg [data-id]')].find((x) => window.__vfEd.model.blocks.some((b) => b.id === x.getAttribute('data-id'))); return e?.getAttribute('data-id'); });
    if (aid) { await p.locator(`.av-svg [data-id="${aid}"]`).first().click({ force: true }); await wait(600); }
    ok('架构图里点设备 → 右栏切到"属性"', !!aid && (await edv('sel')).includes(aid) && (await edv('rightTab')) === 'props', `${aid} ${JSON.stringify(await edv('sel'))} ${await edv('rightTab')}`);
    // 右键"看实时数据"：选中以后又指定了页签，以它为准
    await setv({ view: 'graph', sel: [] }); await wait(2000);
    await clickNode('CNC5', 'right'); await wait(500);
    await p.locator('.xm-i:has-text("看实时数据")').click().catch(() => null); await wait(500);
    ok('右键"看实时数据"：右栏停在"实时"（不被切回属性）', (await edv('rightTab')) === 'live', await edv('rightTab'));
    await shot('w08_select_props');
    // ---- 右键拖动（转视角 / 平移）不弹菜单；不动的右键照常弹 ----
    async function rdrag(sel, label) {
      const bb = await p.locator(sel).first().boundingBox();
      const x = bb.x + bb.width * 0.62, y = bb.y + bb.height * 0.7;
      await p.keyboard.press('Escape'); await wait(200);
      await p.mouse.move(x, y); await p.mouse.down({ button: 'right' });
      for (let i = 1; i <= 8; i++) { await p.mouse.move(x + i * 10, y + i * 4); await wait(30); }
      await p.mouse.up({ button: 'right' }); await wait(500);
      const afterDrag = await menuShown();
      await p.mouse.move(x, y); await p.mouse.down({ button: 'right' }); await wait(60); await p.mouse.up({ button: 'right' }); await wait(500);
      const afterClick = await menuShown();
      ok(`${label}：右键拖动不弹菜单，原地右键弹菜单`, !afterDrag && afterClick, `拖动后 ${afterDrag}，原地 ${afterClick}`);
      await p.keyboard.press('Escape'); await wait(300);
    }
    await setv({ view: '3d', sel: [] }); await wait(2000); await rdrag('.scene-host canvas', '三维');
    await setv({ view: 'plan', sel: [] }); await wait(2000); await rdrag('.pv-svg', '平面图');
    await setv({ view: 'graph', sel: [] }); await wait(2000); await rdrag('.vue-flow__pane', '流程图');
    // ---- 右键菜单"快捷键一览" ----
    // 找一块真正的空白（不是卡片、连线、缩放按钮、小地图）
    const blank = await p.evaluate(() => {
      const r = document.querySelector('.vue-flow__pane').getBoundingClientRect();
      for (let fy = 0.15; fy < 0.95; fy += 0.08) for (let fx = 0.1; fx < 0.95; fx += 0.08) {
        const x = r.left + r.width * fx, y = r.top + r.height * fy, e = document.elementFromPoint(x, y);
        if (e && e.classList.contains('vue-flow__pane')) return { x, y };
      }
      return { x: r.left + 30, y: r.top + 30 };
    });
    await p.mouse.click(blank.x, blank.y, { button: 'right' }); await wait(400);
    await p.locator('.xm-i:has-text("快捷键一览")').click().catch(() => null); await wait(700);
    ok('右键菜单"快捷键一览"打开快捷键表', await p.locator('.el-dialog:has(.kb-table)').isVisible().catch(() => false));
    await shot('w09_shortcuts');
    await p.locator('.el-dialog:has(.kb-table) .el-dialog__headerbtn').click().catch(() => null); await wait(400);
    // ---- 测距时右键第一项"取消测距" ----
    await setv({ view: '3d', sel: [] }); await wait(2000);
    // 三维里找一块地面（不是设备）：右键是"空白处"菜单
    const g3 = await p.evaluate(() => {
      const s = window.__vfScene, r = document.querySelector('.scene-host canvas').getBoundingClientRect();
      for (let fy = 0.35; fy < 0.95; fy += 0.06) for (let fx = 0.1; fx < 0.95; fx += 0.06) {
        const e = { clientX: r.left + r.width * fx, clientY: r.top + r.height * fy };
        const top = document.elementFromPoint(e.clientX, e.clientY);
        if (!top?.closest('.scene-host') || top.closest('.lbl')) continue;
        if (!s.pickId(e) && s.groundAt(e)) return { x: e.clientX, y: e.clientY };
      }
      return null;
    });
    const cv = await p.locator('.scene-host canvas').boundingBox();
    const gx = g3 ? g3.x : cv.x + cv.width * 0.5, gy = g3 ? g3.y : cv.y + cv.height * 0.8;
    await p.mouse.click(gx, gy, { button: 'right' }); await wait(400);
    await p.locator('.xm-i:has-text("测距")').first().click().catch(() => null); await wait(500);
    ok('三维：右键"测距"进入测距', /点两下测距离/.test(await p.locator('.v3-tip').innerText().catch(() => '')));
    await p.mouse.click(gx, gy, { button: 'right' }); await wait(400);
    const first3 = await p.locator('.xm .xm-i').first().innerText().catch(() => '');
    ok('三维测距中：右键菜单第一项是"取消测距"', /取消测距/.test(first3), first3);
    await shot('w10_cancel_measure_3d');
    await p.locator('.xm .xm-i').first().click(); await wait(400);
    ok('点"取消测距"：退出测距', !/点两下测距离/.test(await p.locator('.v3-tip').innerText().catch(() => '')));
    await p.mouse.click(gx, gy, { button: 'right' }); await wait(400);
    ok('退出测距后右键菜单没有"取消测距"', !/取消测距/.test(await p.locator('.xm').innerText().catch(() => '')));
    await p.keyboard.press('Escape'); await wait(300);
    await setv({ view: 'plan', sel: [] }); await wait(2000);
    const pv = await p.locator('.pv-svg').boundingBox();
    await p.mouse.move(pv.x + pv.width / 2, pv.y + pv.height / 2); await p.keyboard.press('m'); await wait(400);
    await p.mouse.click(pv.x + pv.width * 0.3, pv.y + pv.height * 0.85, { button: 'right' }); await wait(400);
    const firstP = await p.locator('.xm .xm-i').first().innerText().catch(() => '');
    ok('平面图测距中：右键菜单第一项是"取消测距"', /取消测距/.test(firstP), firstP);
    await shot('w11_cancel_measure_plan');
    await p.locator('.xm .xm-i').first().click().catch(() => null); await wait(400);
    await p.mouse.click(pv.x + pv.width * 0.3, pv.y + pv.height * 0.85, { button: 'right' }); await wait(400);
    ok('平面图取消测距后菜单恢复', !/取消测距/.test(await p.locator('.xm').innerText().catch(() => '')));
    await p.keyboard.press('Escape'); await setv({ view: '3d' }); await wait(1500);
  }

  if (only.includes('ai')) {
    if (!p.url().includes('/workbench')) { await p.goto(B + '/p/foundry-housing/workbench', { waitUntil: 'networkidle' }); await wait(8000); }
    await p.dblclick('.ol-i:has-text("CNC3")'); await wait(600);
    await p.click('.aid-pill'); await wait(600);
    ok('助手面板打开、显示当前选中', (await p.locator('.aid-in .aid-ctx').innerText().catch(() => '')).includes('3#'));
    await p.locator('.aid-row textarea').fill('它现在什么状态？'); await p.keyboard.press('Enter');
    await p.locator('.aid-prog').waitFor({ timeout: 20000 }).catch(() => {});
    const prog = await p.locator('.aid-prog').innerText().catch(() => '');
    await p.locator('.aid-m.assistant .aid-b.md').first().waitFor({ timeout: 180000 }).catch(() => {});
    const a1 = await p.locator('.aid-m.assistant .aid-b.md').first().innerText().catch(() => '');
    ok('助手：人话进度 + 回答', a1.length > 20 && !a1.startsWith('没能完成') && !/get_runtime/.test(prog), `进度「${prog}」 ${a1.slice(0, 100)}`);
    await shot('a01_answer');
    await p.locator('.aid-row textarea').fill('把它的平均修复时间改成 25 分钟，看看对产量的影响');
    await p.keyboard.press('Enter');
    await p.locator('.aid-card.proposal').waitFor({ timeout: 300000 }).catch(() => {});
    ok('助手：先试算再提议（卡片带 KPI 对比）', await p.locator('.aid-card.proposal .aid-meas tr').count() > 3, await p.locator('.aid-card.proposal .aid-ch b').innerText().catch(() => ''));
    await p.locator('.aid-m.assistant').last().locator('.aid-b.md').waitFor({ timeout: 120000 }).catch(() => {});
    await shot('a02_proposal');
    const depth0 = await p.evaluate(() => window.__vfUndoDepth());
    await p.click('.aid-card.proposal button:has-text("应用到草稿")'); await wait(2500);
    const m = await api(tok, 'GET', '/api/p/foundry-housing/model');
    const cnc3 = m.model.blocks.find((x) => x.id === 'CNC3');
    ok('应用到草稿（一步，可撤销）', cnc3.params.mttr_min === 25 && (await p.evaluate(() => window.__vfUndoDepth())) === depth0 + 1, `mttr=${cnc3.params.mttr_min}`);
    await shot('a03_applied');
    await p.click('.aid-card.proposal button:has-text("撤销")'); await wait(2000);
    const m2 = await api(tok, 'GET', '/api/p/foundry-housing/model');
    ok('卡片上撤销', m2.model.blocks.find((x) => x.id === 'CNC3').params.mttr_min !== 25);
    await p.locator('.aid-row textarea').fill('带我去平面图看 5#加工中心');
    await p.keyboard.press('Enter');
    await p.locator('.aid-went').waitFor({ timeout: 180000 }).catch(() => {});
    await wait(1500);
    ok('助手：带去看（切视图并选中）', (await p.locator('.ed-views .is-active').innerText()).includes('平面') && (await p.locator('.ol-i.sel').innerText().catch(() => '')).includes('CNC5'),
      await p.locator('.aid-went').innerText().catch(() => ''));
    await shot('a04_navigate');
    // 其他页面也有助手
    await p.locator('.aid-m.assistant').nth(2).locator('.aid-b.md').waitFor({ timeout: 120000 }).catch(() => {});
    await wait(1500);
    await p.goto(B + '/p/foundry-housing/reports', { waitUntil: 'networkidle' }); await wait(3000);
    ok('报表页也有助手（会话保留）', (await p.locator('.aid-panel').count()) === 1 && (await p.locator('.aid-m').count()) >= 6);
    await shot('a05_other_page');
    await api(tok, 'DELETE', '/api/p/foundry-housing/model/draft');
  }
  ok('页面没有报错', errs.length === 0, errs.slice(0, 5).join(' | '));
  const bad = res.filter((r) => !r[1]).map((r) => r[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
