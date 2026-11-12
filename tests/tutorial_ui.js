// 4.5 跟随教程 / 实时检查表 / 运行日志 / "为什么没反应"诊断 界面验收（B 机，先启动 serve）：node tests/tutorial_ui.js
// 一个新学生做第一课「电机启停自锁」：
//   开始这一课 → 选"跟着教程做" → 按教程一步一步：打开编程窗口、写梯形图（故意把 STOP 写成常闭触点，教程当场提示"做错了"，学生跳过）、
//   下载、按启动 → 没反应：操作台和编程窗口都给出诊断（STOP 常闭输入 + 常闭触点），梯形图上 STOP 标红；日志里有按下/松开、输入/输出变化；
//   改成常开触点重新下载 → 按启动/自锁/停止/同时按/过载演示 → 检查表逐项打勾 → 全部通过 → 提交评分：检查表和最终得分逐项一致。
// 最后开一个新窗口把教程、诊断、日志、检查表成功状态再走一遍、截图（5.0.1 起只有浅色）。截图在 SHOT_DIR（默认系统临时目录下的 vf-shots/）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'tutorial');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 260)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = (await api(admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('tu_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'tu_teacher', name: '教程老师', role: 'teacher', password: 'teach123' });
  const T = await login('tu_teacher', 'teach123');
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `教程测试班 ${stamp}` });
  const stu = `tu${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},教程同学\n`, default_password: '123456' });
  const asg = await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's01_motor_latch', title: '电机启停自锁（教程测试）' });
  const S = await login(stu, '123456');

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); sessionStorage.setItem('vf_pw_later', '1'); }, S);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  const wait = (ms) => p.waitForTimeout(ms);
  const shot = (n, pg = p) => pg.screenshot({ path: `${OUT}/${n}.png` });
  const stepId = async (pg = p) => pg.locator('[data-k="tour-overlay"]').getAttribute('data-step-id').catch(() => '');
  const waitStep = async (id, ms = 20000, pg = p) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if ((await stepId(pg)) === id) return true; await pg.waitForTimeout(250); } return false; };
  const ed = p.locator('.pw');
  const typeOp = async (text) => { const i = ed.locator('.opedit input'); await i.waitFor({ timeout: 4000 }); await i.fill(text); await i.press('Enter'); await wait(250); };
  const hold = async (sel, ms = 500, pg = p) => { const el = pg.locator(sel).first(); await el.hover(); await pg.mouse.down(); await pg.waitForTimeout(ms); await pg.mouse.up(); };

  // ---------------- 开始这一课：问"跟着教程做 / 自己做" ----------------
  await p.goto(B + '/teach', { waitUntil: 'networkidle' }); await wait(1500);
  await p.locator(`.task-card[data-aid="${asg.id}"]`).click(); await wait(1500);
  await p.locator('[data-k="enter-lesson"]').click();
  await p.waitForSelector('.tour-ask', { timeout: 10000 }).catch(() => null);
  ok('点"开始这一课"先问：跟着教程做 / 自己做', (await p.locator('.tour-ask button:has-text("跟着教程做")').count()) === 1 && (await p.locator('.tour-ask button:has-text("自己做")').count()) === 1);
  await shot('t00_ask_light');
  await p.locator('.tour-ask button:has-text("跟着教程做")').click();
  await p.waitForURL(/\/p\/sb-[^/]+\/workbench$/, { timeout: 60000 }).catch(() => null);
  const sb = decodeURIComponent((p.url().match(/\/p\/([^/]+)\/workbench/) || [])[1] || '');
  ok('进了沙箱工作台', sb.startsWith('sb-'), p.url());
  await p.waitForSelector('[data-k="tour-card"]', { timeout: 30000 }).catch(() => null);
  await wait(6000);
  ok('跟随教程开始：第 1 步"先看这一课要做什么"，有做什么 / 为什么 / 进度', (await stepId()) === 'read' && /做对了是这样/.test(await p.locator('[data-k="tour-do"]').innerText().catch(() => ''))
     && (await p.locator('.vt-why').count()) === 1 && (await p.locator('.vt-prog').count()) === 1, await stepId());
  ok('教程卡片不挡操作：整层不接鼠标，只有卡片能点', await p.evaluate(() => getComputedStyle(document.querySelector('.vt-root')).pointerEvents === 'none'));
  ok('五步旧引导卡没有同时出现', !(await p.locator('.task-panel .tour-card').count()));
  await shot('t01_tour_read_light');
  await p.locator('[data-k="tour-next"]').click(); await wait(800);
  ok('第 2 步讲常闭按钮（聚光在操作台的"常闭"说明上）', (await stepId()) === 'nc' && (await p.locator('.vt-spot').count()) === 1, await stepId());
  await shot('t02_tour_nc_light');
  await p.locator('[data-k="tour-next"]').click(); await wait(800);
  ok('第 3 步：打开 PLC 编程窗口，有"带我去"', (await stepId()) === 'open-editor' && (await p.locator('[data-k="tour-goto"]').count()) === 1);
  await shot('t03_tour_open_editor_light');
  await p.locator('[data-k="tour-goto"]').click();
  await p.waitForSelector('.pw .lde', { timeout: 30000 }).catch(() => null);
  ok('"带我去"打开了编程窗口，做到后自动进入下一步（放常开触点 START）', await waitStep('start'), await stepId());
  await wait(600);
  const spot = await p.locator('.vt-spot').boundingBox().catch(() => null);
  const tool = await ed.locator('.lde-tools [data-tool="NO"]').boundingBox().catch(() => null);
  ok('聚光圈住工具条上的"常开"', !!spot && !!tool && Math.abs(spot.x + 6 - tool.x) < 4 && Math.abs(spot.y + 6 - tool.y) < 4, JSON.stringify([spot, tool]));
  await shot('t04_tour_start_spot_light');

  // ---------------- 写梯形图（STOP 故意写成常闭） ----------------
  await ed.locator('.rung').first().locator('.rh').click();
  await p.keyboard.press('c'); await typeOp('START');
  ok('放了 START 常开触点 → 教程自动进入"串联停止按钮"', await waitStep('stop'), await stepId());
  await p.keyboard.press('x'); await typeOp('STOP');
  await p.waitForSelector('[data-k="tour-wrong"]', { timeout: 6000 }).catch(() => null);
  const wrongTxt = await p.locator('[data-k="tour-wrong"]').innerText().catch(() => '');
  ok('写成常闭触点：教程当场提示"做错了"，说清楚原因', /常闭/.test(wrongTxt) && /取反|永远不通|没反应/.test(wrongTxt) && (await stepId()) === 'stop', wrongTxt);
  await shot('t05_tour_wrong_nc_light');
  await p.locator('[data-k="tour-skip"]').click(); await wait(500);          // 新手没听提示，跳过
  ok('跳过这一步', (await stepId()) === 'ol');
  await ed.locator('.rung').first().locator('g.el', { hasText: 'STOP' }).first().click();      // 点回编辑器（选中 STOP，新元件放在它右边）
  await p.keyboard.press('c'); await typeOp('M1_OL_OK');
  ok('放了 M1_OL_OK → 下一步线圈', await waitStep('coil'), await stepId());
  await p.keyboard.press('o'); await typeOp('M1_RUN');
  ok('放了线圈 M1_RUN → 下一步并联自锁', await waitStep('latch'), await stepId());
  await ed.locator('.rung').first().locator('g.el', { hasText: 'START' }).first().click();
  await p.keyboard.press('v'); await typeOp('M1_RUN');
  ok('并联了 M1_RUN → 下一步运行灯梯级', await waitStep('lamp'), await stepId());
  await ed.locator('.lde-tools [data-tool="RUNG"]').click(); await wait(300);
  await p.keyboard.press('c'); await typeOp('M1_RUN');
  await p.keyboard.press('o'); await typeOp('LAMP_RUN');
  ok('第二个梯级写好 → 下一步下载', await waitStep('download'), await stepId());
  await shot('t06_tour_download_light');
  await ed.locator('span[data-act="download"]').click();
  ok('下载、PLC 运行 → 下一步"按一下启动"', await waitStep('press-start', 20000), await stepId());
  await wait(1500);
  await shot('t07_tour_press_start_light');

  // ---------------- 按启动没反应：诊断 + 日志 ----------------
  await hold('[data-tour="btn-START"]', 600);
  await p.waitForSelector('[data-k="console-diag"]', { timeout: 12000 }).catch(() => null);
  await wait(1500);
  const diag = await p.locator('[data-k="console-diag"]').innerText().catch(() => '');
  ok('按启动没反应：操作台上自动给出诊断（STOP 是常闭输入，你用了常闭触点，改成常开）', /STOP/.test(diag) && /常闭/.test(diag) && /常开/.test(diag), diag);
  const logTxt = await p.locator('.cco .rlog').innerText().catch(() => '');
  ok('运行日志：按下/松开 启动、输入 I0.2 START 0→1 / 1→0', /按下 启动/.test(logTxt) && /松开 启动/.test(logTxt) && /START 0→1/.test(logTxt) && /START 1→0/.test(logTxt), logTxt.slice(-400));
  ok('运行日志里有"诊断："一条', /诊断：/.test(logTxt));
  const red = ed.locator('g.el.dg');
  ok('梯形图上断开的 STOP 触点标红', (await red.count()) >= 1 && /STOP/.test(await red.first().evaluate((e) => e.textContent).catch(() => '')), await red.count());
  ok('编程窗口顶上有诊断条，指到梯级 1', /梯级 1/.test(await ed.locator('[data-k="plc-diag"]').innerText().catch(() => '')));
  ok('教程这一步显示"没做到"/诊断（不是一直等着）', (await p.locator('[data-k="tour-wrong"], [data-k="tour-diag"]').count()) >= 1, await p.locator('[data-k="tour-card"]').innerText().catch(() => ''));
  const st0 = await p.locator('[data-k="console-state"]').innerText().catch(() => '');
  ok('操作台状态写实话："PLC 运行中 · 所有输出都没得电"（不再是"待机"）', /PLC 运行中/.test(st0) && !/待机/.test(st0), st0);
  await shot('t08_diag_light');
  await ed.locator('.rexp[data-act="explain-0"]').click(); await wait(1200);
  const expl = await ed.locator('[data-k="rung-explain"]').innerText().catch(() => '');
  ok('"解释这个梯级"：一句一句说能流，指出 STOP 常闭触点断开', /左母线/.test(expl) && /STOP/.test(expl) && /断开/.test(expl), expl.slice(0, 300));
  await shot('t09_explain_light');
  await ed.locator('.rexp[data-act="explain-0"]').click(); await wait(300);
  // 日志页签（编程窗口里）。教程卡片可能盖在编程窗口上：学生会把它收起（或拖开）
  await p.locator('.vt-x').click(); await wait(300);
  ok('教程卡片可以收起成一个小条', (await p.locator('[data-k="tour-pill"]').count()) === 1);
  await ed.locator('.tab[data-tab="log"]').click(); await wait(800);
  ok('编程窗口有"日志"页签，内容和操作台一样', /START 0→1/.test(await ed.locator('.rlog').innerText().catch(() => '')));
  await ed.locator('.rlog .rl-f[data-filter="io"]').click(); await wait(300);
  const ioOnly = await ed.locator('.rlog .rl-e').evaluateAll((es) => es.map((e) => e.getAttribute('data-k')));
  ok('日志能按类型筛选（只看输入输出）', ioOnly.length > 0 && ioOnly.every((k) => k === 'in' || k === 'out'), ioOnly.join(','));
  await shot('t10_plc_log_light');
  await ed.locator('.rlog .rl-f[data-filter="all"]').click();
  await ed.locator('.tab[data-tab="prog"]').click(); await wait(500);
  await p.locator('[data-k="tour-pill"]').click(); await wait(400);

  // ---------------- 改成常开，重新下载 ----------------
  ok('教程卡片上有"去改程序"', (await p.locator('[data-k="tour-fix"]').count()) === 1);
  await p.locator('[data-k="tour-fix"]').click(); await wait(1200);
  ok('"去改程序"：卡片收起，编程窗口定位到标红的 STOP', (await p.locator('[data-k="tour-pill"]').count()) === 1 && (await ed.locator('g.el.dg.sel').count()) === 1);
  await ed.locator('g.el.dg').first().click({ button: 'right' }); await wait(300);
  await ed.locator('.ctx .it', { hasText: '改为常开触点' }).click(); await wait(300);
  await ed.locator('span[data-act="download"]').click(); await wait(2500);
  ok('改好重新下载：红色诊断消失', !(await ed.locator('g.el.dg').count()) && !(await ed.locator('[data-k="plc-diag"]').count()));
  await p.locator('[data-k="tour-pill"]').click(); await wait(400);
  await hold('[data-tour="btn-START"]', 500);
  ok('再按启动：检查表"按启动电机运行"打勾，教程自动进入下一步', await waitStep('latch-check', 12000), await stepId());
  const st1 = await p.locator('[data-k="console-state"]').innerText().catch(() => '');
  ok('操作台状态："PLC 运行中 · 得电：M1_RUN…"', /得电/.test(st1) && /M1_RUN/.test(st1), st1);
  const log2 = await p.locator('.cco .rlog').innerText().catch(() => '');
  ok('日志：输出 Q0.0 M1_RUN 0→1、检查 ✓', /M1_RUN 0→1/.test(log2) && /✓ 按启动电机运行/.test(log2), log2.slice(-300));
  ok('等 3 秒自锁打勾 → 下一步"按停止"', await waitStep('press-stop', 15000), await stepId());
  await shot('t11_log_light');
  await hold('[data-tour="btn-STOP"]', 400);
  ok('按停止：打勾 → 下一步"同时按：停止优先"', await waitStep('priority', 15000), await stepId());
  await hold('[data-tour="btn-START"]', 400); await wait(1200);                // 先转起来
  await p.locator('[data-tour="btn-START"]').click({ modifiers: ['Shift'] }); await wait(500);   // Shift 锁住启动
  ok('Shift+点击把启动"锁住按下"', /按住中/.test(await p.locator('[data-tour="btn-START"]').innerText()));
  await hold('[data-tour="btn-STOP"]', 700); await wait(400);
  await p.locator('[data-tour="btn-START"]').click({ modifiers: ['Shift'] }); await wait(300);
  ok('同时按启动和停止 → 停止优先打勾 → 下一步过载演示', await waitStep('overload', 12000), await stepId());
  await p.locator('[data-k="tour-goto"]').click(); await wait(1200);           // 带我去：任务面板"检查表"
  await shot('t12_checklist_light');
  await p.locator('[data-act="trial-overload_ok"]').click();
  const t0tr = Date.now();
  while (Date.now() - t0tr < 60000 && !['all', 'submit'].includes(await stepId())) await wait(500);
  ok('点"演示"：系统在沙箱里演示过载 → 打勾', ['all', 'submit'].includes(await stepId()), await stepId());
  ok('检查表全部打勾 → 下一步提交评分', await waitStep('submit', 20000), await stepId());
  await p.waitForSelector('[data-k="checklist-success"]', { timeout: 10000 }).catch(() => null);
  ok('检查表全部通过：清楚的成功提示 + "提交评分"按钮', /全部做到了/.test(await p.locator('.task-panel [data-k="checklist-success"]').first().innerText().catch(() => '')));   // 4.6：操作台的检查表页签（第 12 步切过去的）里也有一份
  await shot('t13_success_light');
  const cl = await api(S, 'GET', `/api/p/${encodeURIComponent(sb)}/coach?since=999999999`);
  await p.locator('[data-act="checklist-submit"]').click();
  await p.waitForSelector('[data-k="tour-close"]', { timeout: 60000 }).catch(() => null);
  ok('提交评分后教程走完', (await p.locator('[data-k="tour-close"]').count()) === 1);
  await shot('t14_tour_done_light');
  const task = await api(S, 'GET', `/api/teach/assignments/${asg.id}/task`);
  const sub = task.submissions?.[0] || {};
  ok('最终得分 100', sub.score === 100, JSON.stringify({ score: sub.score, status: sub.status }));
  const items = cl.checklist?.items || [];
  const same = items.length && items.every((it) => { const d = (sub.details || []).find((x) => x.key === it.key); return d && (d.ok === (it.state === 'ok')); });
  ok('检查表和最终评分逐项一致', !!same, items.map((i) => `${i.key}:${i.state}`).join(' ') + ' | ' + (sub.details || []).map((d) => `${d.key}:${d.ok}`).join(' '));
  const ents = (await api(S, 'GET', `/api/p/${encodeURIComponent(sb)}/coach?since=0`)).entries || [];
  const kinds = new Set(ents.map((e) => e.k));
  ok('日志覆盖：操作、输入、输出、PLC、检查、诊断', ['act', 'in', 'out', 'plc', 'check', 'diag'].every((k) => kinds.has(k)), [...kinds].join(','));
  ok('日志条目同时有仿真时间和电脑时间', ents.every((e) => typeof e.wall === 'number') && ents.some((e) => typeof e.t === 'number'));
  await p.locator('[data-k="tour-close"]').click(); await wait(500);
  ok('关闭教程后浮层消失', !(await p.locator('[data-k="tour-overlay"]').count()));
  ok('页面没有报错（浅色）', errs.length === 0, errs.slice(0, 4).join(' | '));

  // ---------------- "重来"清空日志 ----------------
  await p.locator('[data-panel="teach-task"]').click().catch(() => null); await wait(800);
  const seqBefore = (await api(S, 'GET', `/api/p/${encodeURIComponent(sb)}/coach?since=999999999`)).seq;
  await api(S, 'POST', `/api/teach/assignments/${asg.id}/sandbox/reset`, { clear_program: false });
  await wait(1500);
  const after = await api(S, 'GET', `/api/p/${encodeURIComponent(sb)}/coach?since=0`);
  ok('"重来"以后日志清空（新沙箱新日志）', after.entries.length <= 3 && after.seq < seqBefore, `${after.entries.length} 条，seq ${seqBefore} → ${after.seq}`);

  await ctx.close();                                                   // 第一个页面关掉（两个页面同时渲染三维太慢）
  // ---------------- 重新打开（5.0.1 起只有浅色，原来的深色一遍改成新窗口再走一遍）：教程、诊断、日志、检查表成功 ----------------
  const ctx2 = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
  await ctx2.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); sessionStorage.setItem('vf_pw_later', '1'); }, S);
  const q = await ctx2.newPage();
  const errs2 = [];
  q.on('pageerror', (e) => errs2.push(e.message.slice(0, 200)));
  await q.goto(`${B}/p/${encodeURIComponent(sb)}/workbench`, { waitUntil: 'domcontentloaded' }); await q.waitForTimeout(9000);
  await q.locator('[data-k="start-tour"]').click().catch(() => null);
  await q.waitForSelector('[data-k="tour-card"]', { timeout: 20000 }).catch(() => null); await q.waitForTimeout(1500);
  ok('重新打开：任务面板"跟着教程做"重新开始教程', (await stepId(q)) === 'read', await stepId(q));
  await shot('t01_tour_read_again', q);
  await q.locator('[data-k="tour-next"]').click(); await q.waitForTimeout(500); await q.locator('[data-k="tour-next"]').click(); await q.waitForTimeout(500);
  await q.locator('[data-k="tour-goto"]').click(); await q.waitForSelector('.pw .lde', { timeout: 30000 }).catch(() => null); await q.waitForTimeout(2500);
  await shot('t04_tour_start_spot_again', q);
  // 错误程序 → 按启动 → 诊断
  const bad = { lang: 'LD', vars: [], source: { rungs: [{ comment: '启保停（STOP 写成了常闭触点）', elements: [{ par: [[{ t: 'NO', var: 'START' }], [{ t: 'NO', var: 'M1_RUN' }]] }, { t: 'NC', var: 'STOP' }, { t: 'NO', var: 'M1_OL_OK' }, { t: 'COIL', var: 'M1_RUN' }] },
    { comment: '运行灯', elements: [{ t: 'NO', var: 'M1_RUN' }, { t: 'COIL', var: 'LAMP_RUN' }] }] } };
  await api(S, 'POST', `/api/p/${encodeURIComponent(sb)}/cells/PLC1/program/download`, { program: bad, cold: true });
  await q.locator('.pw [data-act="reload"], .pw').first().waitFor({ timeout: 5000 }).catch(() => null);
  await q.evaluate(() => window.dispatchEvent(new CustomEvent('vf:plc-tab', { detail: { tab: 'prog' } })));
  const qed = q.locator('.pw');
  await qed.locator('.el-dropdown .plc-btn').last().click().catch(() => null); await q.waitForTimeout(300);
  await q.locator('.el-dropdown-menu__item:has-text("重新读取工程")').click().catch(() => null); await q.waitForTimeout(1500);
  const P2 = `/api/p/${encodeURIComponent(sb)}/cells/CELL1/panel`;
  await api(S, 'POST', P2, { comp: 'START', action: 'set', value: 1 }); await q.waitForTimeout(800); await api(S, 'POST', P2, { comp: 'START', action: 'release' });
  await q.waitForSelector('[data-k="console-diag"]', { timeout: 12000 }).catch(() => null); await q.waitForTimeout(2500);
  ok('重新打开：诊断出现在操作台和编程窗口', (await q.locator('[data-k="console-diag"]').count()) === 1 && (await qed.locator('g.el.dg').count()) >= 1);
  await shot('t08_diag_again', q);
  await qed.locator('.rexp[data-act="explain-0"]').click().catch(() => null); await q.waitForTimeout(1200);
  await shot('t09_explain_again', q);
  await qed.locator('.tab[data-tab="log"]').click().catch(() => null); await q.waitForTimeout(800);
  await shot('t10_plc_log_again', q);
  // 正确程序 → 演示全部 → 检查表成功
  const task0 = await api(T, 'GET', '/api/teach/scenes/s01_motor_latch');
  await api(S, 'POST', `/api/p/${encodeURIComponent(sb)}/cells/PLC1/program/download`, { program: task0.reference.ld, cold: true });
  await q.locator('[data-k="tour-exit"]').count();
  await q.evaluate(() => window.dispatchEvent(new CustomEvent('vf:teach-tab', { detail: { tab: 'goals' } }))); await q.waitForTimeout(1500);
  await q.locator('[data-act="trial-all"]').click().catch(() => null);
  await q.waitForSelector('[data-k="checklist-success"]', { timeout: 40000 }).catch(() => null); await q.waitForTimeout(800);
  ok('重新打开："演示全部"把整套测试在沙箱里跑一遍，检查表全部通过', (await q.locator('[data-k="checklist-success"]').count()) >= 1);
  await shot('t13_success_again', q);
  await q.locator('[data-tab="console-check"]').click().catch(() => null); await q.waitForTimeout(500);
  await shot('t12_console_checklist_again', q);
  ok('页面没有报错（重新打开）', errs2.length === 0, errs2.slice(0, 4).join(' | '));

  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
