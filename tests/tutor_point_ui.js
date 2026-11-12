// 4.6 AI 助教"看这里"界面验收（B 机，先启动 serve）：node tests/tutor_point_ui.js
// 学生在 PLC 课沙箱里问右下角 AI 助教。/api/tutor/ask 用假回答（page.route 拦下来，和 tutor.py 的 points 格式一样，不依赖大模型），
// 回答下面出"看这里"按钮；点一个就用跟随教程的聚光层圈出来：检查表（先打开任务面板的检查表页签）、梯形图里的 STOP 常闭触点（先打开编程窗口）、
// 操作台按钮、平面图 / 三维里的设备；找不到的目标不画空圈、卡片上说清楚。最后真问一次服务器（接了大模型才问），回答里的 points 格式对。
// 截图在 SHOT_DIR（5.0.1 起只有浅色）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'tutor_point');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 600)); };
const api = async (tok, m, u, b) => { const r = await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); };
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;

// 和 vfactory/tutor.py point_catalog 产生的一样
const ED = { panel: 'plc-editor-float', plc_tab: 'prog' };
const POINTS = [
  { key: 'checklist', label: '检查表', target: [{ sel: '.task-panel [data-tour="checklist"]' }, { tour: 'checklist' }], goto: { teach_tab: 'goals' } },
  { key: 'ld:STOP/NC', label: 'STOP 触点', target: [{ ld: { var: 'STOP', t: 'NC' } }, { sel: '.pw .lde' }], goto: ED, plc: 'PLC1' },
  { key: 'btn:STOP', label: '操作台「停止」', target: { tour: 'btn-STOP' }, goto: { console: true } },
];
const FAKE = { answer: '按了启动没反应，先别急着改程序。看「检查表」里哪一项是红的，再看「STOP 触点」：没按停止的时候 STOP 是 1 还是 0？常闭触点在输入为 1 时是断开的。', filtered: false, points: POINTS };

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = ((await api(admin, 'GET', '/api/admin/users')).users || []).map((u) => u.username);
  if (!users.includes('tp_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'tp_teacher', name: '助教老师', role: 'teacher', password: 'teach123' });
  const T = await login('tp_teacher', 'teach123');
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `看这里测试班 ${stamp}` });
  const stu = `tp${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},看这里同学\n`, default_password: '123456' });
  const aid = (await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's01_motor_latch', title: '电机启停自锁（看这里测试）', tutor: true })).id;
  await api(T, 'PATCH', `/api/teach/assignments/${aid}`, { tutor: true });
  const S = await login(stu, '123456');
  const sb = (await api(S, 'POST', `/api/teach/assignments/${aid}/sandbox`, {})).pid;
  // 学生的程序：STOP 写成了常闭（助教要指着它）
  const bad = { lang: 'LD', vars: [], source: { rungs: [{ comment: '启保停', elements: [{ par: [[{ t: 'NO', var: 'START' }], [{ t: 'NO', var: 'M1_RUN' }]] }, { t: 'NC', var: 'STOP' }, { t: 'NO', var: 'M1_OL_OK' }, { t: 'COIL', var: 'M1_RUN' }] }] } };
  await api(S, 'POST', `/api/p/${encodeURIComponent(sb)}/cells/PLC1/program/download`, { program: bad, cold: true });

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  for (const theme of ['light']) {   // 5.0.1 起只有浅色
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
    await ctx.addInitScript(([t]) => {
      if (sessionStorage.getItem('tp_init')) return; sessionStorage.setItem('tp_init', '1');
      localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); sessionStorage.setItem('vf_pw_later', '1');
    }, [S, theme]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    const asked = [];
    await p.route('**/api/tutor/ask', async (r) => { asked.push(r.request().postDataJSON()); await r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE) }); });
    const wait = (ms) => p.waitForTimeout(ms);
    const ov = async () => p.evaluate(() => {
      const o = document.querySelector('[data-k="tour-overlay"]'), s = document.querySelector('[data-k="tour-spot"]')?.getBoundingClientRect();
      return { on: !!o, found: o?.getAttribute('data-found'), step: o?.getAttribute('data-step-id'), spot: s && [s.x + 6, s.y + 6, s.width - 12, s.height - 12],
        card: !!document.querySelector('[data-k="point-card"]'), miss: document.querySelector('[data-k="point-miss"]')?.textContent || '', title: document.querySelector('[data-k="point-title"]')?.textContent || '' };
    });
    const near = (a, r) => a && r && Math.abs(a[0] - r.x) < 4 && Math.abs(a[1] - r.y) < 4 && Math.abs(a[2] - r.width) < 6 && Math.abs(a[3] - r.height) < 6;
    await p.goto(`${B}/p/${encodeURIComponent(sb)}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.task-panel', { timeout: 60000 }).catch(() => null); await wait(6000);
    for (const t of ['跳过', '以后再说', '自己做']) { const x = p.locator(`.el-button:has-text("${t}"), .tour-ask button:has-text("${t}")`).first(); if (await x.isVisible().catch(() => false)) await x.click().catch(() => null); }
    await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:teach-tab', { detail: { tab: 'task' } }))); await wait(500);
    await p.locator('.aid-pill').click(); await wait(600);
    await p.locator('.aid-row textarea').fill('我按了启动电机不转，为什么？'); await p.keyboard.press('Enter');
    await p.waitForSelector('[data-k="tutor-points"] .aid-lk', { timeout: 20000 }).catch(() => null); await wait(500);
    const btns = await p.locator('[data-k="tutor-points"] .aid-lk').allInnerTexts();
    ok(`${theme}：助教回答下面有"看这里"按钮（检查表、STOP 触点、操作台停止）`, btns.length === 3 && /检查表/.test(btns[0]) && /STOP/.test(btns[1]), btns.join(' / '));
    ok(`${theme}：问的是 /api/tutor/ask（带任务号和问题）`, asked.length === 1 && asked[0].assignment_id === aid && /不转/.test(asked[0].question), JSON.stringify(asked[0] || {}));
    await p.screenshot({ path: `${OUT}/tp01_answer_${theme}.png` });

    // 检查表：先打开任务面板的检查表页签再圈
    await p.locator('[data-k="tutor-points"] .aid-lk[data-key="checklist"]').click(); await wait(2500);
    let o = await ov();
    const ck = await p.evaluate(() => { const e = [...document.querySelectorAll('.task-panel [data-tour="checklist"]')].find((x) => x.getClientRects().length); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: Math.min(r.bottom, innerHeight) - r.y }; });
    const tab = await p.locator('.task-panel .el-tabs__item.is-active').innerText().catch(() => '');
    ok(`${theme}：点"看这里：检查表"→ 任务面板切到检查表页签，聚光圈住检查表，卡片写"看这里"`, o.on && o.found === '1' && o.card && /检查表/.test(o.title) && /检查表/.test(tab) && !!ck && o.spot && Math.abs(o.spot[0] - ck.x) < 4,
      JSON.stringify({ o, ck, tab }));
    await p.screenshot({ path: `${OUT}/tp02_checklist_${theme}.png` });
    await p.locator('[data-k="point-ok"]').click(); await wait(400);
    ok(`${theme}："知道了"关掉聚光`, !(await ov()).on);

    // 梯形图元件：先打开编程窗口（程序页）
    if (!(await p.locator('.aid-panel').isVisible().catch(() => false))) { await p.locator('.aid-pill').click(); await wait(500); }
    await p.locator('[data-k="tutor-points"] .aid-lk[data-key="ld:STOP/NC"]').click(); await wait(3500);
    o = await ov();
    const el = await p.evaluate(() => { const prog = [...document.querySelectorAll('.lde g.el')].find((g) => /STOP/.test(g.textContent || '')); if (!prog) return null; const r = prog.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; });
    ok(`${theme}：点"看这里：STOP 触点"→ 打开编程窗口，聚光圈住梯形图里的 STOP`, o.found === '1' && !!el && near(o.spot, el), JSON.stringify({ o, el }));
    await p.screenshot({ path: `${OUT}/tp03_ld_${theme}.png` });
    // 操作台按钮
    if (!(await p.locator('.aid-panel').isVisible().catch(() => false))) { await p.locator('.aid-pill').click(); await wait(500); }
    await p.locator('[data-k="tutor-points"] .aid-lk[data-key="btn:STOP"]').click(); await wait(2500);
    o = await ov();
    const pb = await p.locator('[data-tour="btn-STOP"]').first().boundingBox().catch(() => null);
    ok(`${theme}：点"看这里：操作台「停止」"→ 操作台在最前，聚光圈住停止按钮`, o.found === '1' && !!pb && near(o.spot, pb), JSON.stringify({ o, pb }));
    // 设备：平面图 / 三维（直接调 pointAt，和点按钮一样）
    const r2 = await p.evaluate(async () => { const T = window.__vfTour; const f = await T.pointAt({ label: 'PLC1', target: { block: 'PLC1' }, goto: { select: 'PLC1', view: 'plan' } }); await new Promise((x) => setTimeout(x, 1500));
      const e = document.querySelector('.pv-svg [data-id="PLC1"]')?.getBoundingClientRect(); return { f, view: window.__vfEd.view, sel: window.__vfEd.sel, e: e && { x: e.x, y: e.y, width: e.width, height: e.height } }; });
    o = await ov();
    ok(`${theme}：指设备（平面图）：切到平面图、选中、聚光圈住那台设备`, r2.f && r2.view === 'plan' && r2.sel.includes('PLC1') && o.found === '1' && o.spot && Math.abs(o.spot[0] - r2.e.x) < 6, JSON.stringify({ r2, o }));
    await p.screenshot({ path: `${OUT}/tp04_block_plan_${theme}.png` });
    const r3 = await p.evaluate(async () => { const T = window.__vfTour; const f = await T.pointAt({ label: '实训单元', target: { block: 'CELL1' }, goto: { select: 'CELL1', view: '3d' } }); await new Promise((x) => setTimeout(x, 2500));
      return { f, view: window.__vfEd.view, rect: !!window.__vf3dRect?.('CELL1') }; });
    o = await ov();
    ok(`${theme}：指设备（三维）：切到三维，聚光圈住设备的投影框`, r3.view === '3d' && r3.rect && o.found === '1' && !!o.spot, JSON.stringify({ r3, o }));
    await p.screenshot({ path: `${OUT}/tp05_block_3d_${theme}.png` });
    // 找不到：不画空圈，说清楚
    await p.evaluate(async () => { await window.__vfTour.pointAt({ label: '不存在的东西', target: { sel: '.no-such-thing' } }); }); await wait(800);
    o = await ov();
    ok(`${theme}：目标找不到：不画空的聚光圈，卡片上说"现在不在屏幕上"`, o.card && o.found === '0' && !o.spot && /不在屏幕上/.test(o.miss), JSON.stringify(o));
    await p.screenshot({ path: `${OUT}/tp06_missing_${theme}.png` });
    await p.locator('[data-k="point-close"]').click(); await wait(300);
    await ctx.close();
  }

  // ---- 真问一次服务器：回答里有 points（格式对，编号都在目录里）。没接大模型时走兜底回答，也有 points ----
  const st = await api(S, 'GET', '/api/tutor/status');
  const t0 = Date.now();
  const real = await api(S, 'POST', '/api/tutor/ask', { assignment_id: aid, question: '我按启动电机不转，帮我看看该检查哪里？' });
  ok(`服务器 /api/tutor/ask 回答带 points 数组（${st.configured ? '接了大模型' : '兜底回答'}，${Math.round((Date.now() - t0) / 1000)} 秒）`,
    typeof real.answer === 'string' && Array.isArray(real.points) && real.points.every((x) => x.key && x.label && x.target), JSON.stringify(real).slice(0, 500));
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
