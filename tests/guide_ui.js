// 新手五步引导走查（4.4，B 机，先启动 serve）：node tests/guide_ui.js
// PLC 课沙箱里，引导每一步说到的按钮都要真有、能点：PLC 面板的"编程"、对象面板的"编程"/"操作台"、编程窗口的"下载"、操作台的"启动"、"提交评分"。
// 同时看：PLC 还没有程序时不算报警（工作台没有报警数、操作台和任务面板写清楚"先编程并下载"），下载以后提示消失、可以提交。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'guide');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;
/** 看得见、没禁用（element-plus 按钮禁用时有 disabled 属性或 is-disabled 类）。 */
const usable = async (loc) => {
  const l = loc.first();
  if (!(await l.isVisible().catch(() => false))) return false;
  const btn = (await l.evaluate((e) => e.tagName)) === 'BUTTON' ? l : l.locator('xpath=ancestor-or-self::button[1]');
  if (!(await btn.count())) return true;
  return (await btn.isEnabled().catch(() => false)) && !(await btn.evaluate((e) => e.classList.contains('is-disabled')).catch(() => true));
};

// 4.5：第一次"开始这一课"有跟随教程的课会先问"跟着教程做 / 自己做"——这里选"自己做"（教程本身在 tutorial_ui.js 里测）
const selfDo = async (pg) => { const b = pg.locator('.tour-ask button:has-text("自己做")'); await b.waitFor({ state: 'visible', timeout: 2500 }).catch(() => null); if (await b.isVisible().catch(() => false)) { await b.click(); await pg.waitForTimeout(400); } };

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = (await api(admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('gd_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'gd_teacher', name: '引导老师', role: 'teacher', password: 'teach123' });
  const T = await login('gd_teacher', 'teach123');
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `引导测试班 ${stamp}` });
  const stu = `gd${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},引导同学\n`, default_password: '123456' });
  const asg = await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's01_motor_latch', title: '电机启停（引导测试）' });
  const ref = (await api(T, 'GET', '/api/teach/scenes/s01_motor_latch')).reference.st;
  const S = await login(stu, '123456');

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); sessionStorage.setItem('vf_pw_later', '1'); }, S);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  const wait = (ms) => p.waitForTimeout(ms);
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });

  await p.goto(B + '/teach', { waitUntil: 'networkidle' }); await wait(1500);
  await p.locator(`.task-card[data-aid="${asg.id}"]`).click(); await wait(1500);
  ok('"教学"页：这一课的状态写"还没开始"，按钮是"开始这一课"', (await p.locator('[data-k="lesson-status"]').innerText()).includes('还没开始')
     && (await p.locator('[data-k="enter-lesson"]').innerText()).includes('开始这一课'), await p.locator('[data-k="lesson-status"]').innerText());
  await p.locator('[data-k="enter-lesson"]').click();
  await selfDo(p);
  await p.waitForURL(/\/p\/sb-[^/]+\/workbench$/, { timeout: 60000 }).catch(() => null);
  await wait(9000);
  const sb = decodeURIComponent((p.url().match(/\/p\/([^/]+)\/workbench/) || [])[1] || '');
  ok('进了 PLC 课沙箱', sb.startsWith('sb-'), p.url());
  await p.waitForSelector('.tour-card', { timeout: 20000 }).catch(() => null);
  ok('第一次进沙箱：五步引导（PLC 课版）', (await p.locator('.tour-card[data-tour-kind="cell"]').count()) === 1);
  await shot('g00_tour1');

  // ---- PLC 还没有程序：正常的起点，不算报警 ----
  const st0 = await api(S, 'GET', `/api/p/${encodeURIComponent(sb)}/state`);
  const alarmed = (st0.stations || []).filter((s) => s.alarm).map((s) => `${s.id}:${s.alarm}`);
  ok('新沙箱里 PLC 没程序：没有报警（单元和 PLC 都不报）', alarmed.length === 0, alarmed.join(','));
  await p.waitForSelector('[data-k="next-step"]', { timeout: 10000 }).catch(() => null);
  ok('任务面板写清楚下一步："先给 PLC 编程并下载"', /先给 PLC 编程并下载/.test(await p.locator('[data-k="next-step"]').innerText().catch(() => '')));
  await p.waitForSelector('.cco', { timeout: 15000 }).catch(() => null);
  ok('操作台写清楚下一步（不是红色报警）', /编程并下载/.test(await p.locator('[data-k="console-hint"]').innerText().catch(() => ''))
     && !(await p.locator('.cco .st .warn').count()), await p.locator('.cco').innerText().catch(() => ''));

  // ---- 第 1 步：读任务书（三个页签都在） ----
  const step = async () => Number(await p.locator('.tour-card').getAttribute('data-tour-step'));
  const text = async () => p.locator('.tour-card .tour').innerText();
  ok('第 1 步：任务书 / 评分标准 / I/O 表 三个页签都在', (await step()) === 0 && await usable(p.locator('.task-panel .el-tabs__item:has-text("任务书")'))
     && await usable(p.locator('.task-panel .el-tabs__item:has-text("评分标准")')) && await usable(p.locator('.task-panel .el-tabs__item:has-text("I/O 表")')), await text());

  // ---- 第 2 步：打开 PLC 编程：左边竖排图标"PLC" → 面板里"编程"；或者画布上点 PLC1 → 浮出的工具条 / 右边"属性"页里"编程" ----
  await p.locator('[data-k="tour-next"]').click(); await wait(400);
  const t2 = await text();
  ok('第 2 步说的是"PLC"图标和"编程"按钮', (await step()) === 1 && /"PLC"/.test(t2) && /"编程"/.test(t2), t2);
  ok('左边竖排图标里有"PLC"', await usable(p.locator('[data-panel="plc-editor"]')));
  await p.locator('[data-panel="plc-editor"]').click(); await wait(1500);
  ok('PLC 面板里的"编程"按钮看得见、能点', await usable(p.locator('.ps-btns [data-act="open-editor"]')));
  await shot('g01_plc_side');
  // 学生的 PLC 课没有"对象"列表：在画布上点 PLC1（等价于选中它：ed.sel）
  await p.evaluate(() => { window.__vfEd.sel = ['PLC1']; }); await wait(1200);
  ok('选中 PLC1：画布上浮出的工具条里"编程"看得见、能点', await usable(p.locator('.selbar button:has-text("编程")')),
     await p.locator('.selbar').innerText().catch(() => '（没有工具条）'));
  await p.locator('.el-tabs__item:has-text("属性")').first().click(); await wait(800);
  ok('选中 PLC1：右边"属性"页（对象面板）里的"编程"看得见、能点', await usable(p.locator('.op-acts button:has-text("编程")')),
     await p.locator('.op-acts').innerText().catch(() => '（没有对象面板）'));
  await shot('g02_object_plc');
  await p.locator('[data-panel="teach-task"]').click(); await wait(1500);
  ok('回到"我的课程"：引导接着第 2 步（没有从头来）', (await p.locator('.tour-card').count()) === 1 && (await step()) === 1, await step().catch(() => '无'));

  // ---- 第 3 步：写程序并下载：编程窗口工具栏上的"下载" ----
  await p.locator('[data-k="tour-next"]').click(); await wait(400);
  const t3 = await text();
  ok('第 3 步说的是编程窗口里的"下载"', (await step()) === 2 && /"下载"/.test(t3), t3);
  ok('引导里的"打开编程窗口"按钮能点', await usable(p.locator('[data-k="tour-go"]')));
  await p.locator('[data-k="tour-go"]').click();
  await p.waitForSelector('[data-act="download"]', { timeout: 30000 }).catch(() => null); await wait(800);
  ok('编程窗口里的"下载"看得见、能点', await usable(p.locator('[data-act="download"]')));
  ok('打开编程窗口后引导还在（左栏没换走）', (await p.locator('.tour-card').count()) === 1 && (await step()) === 2);
  await shot('g03_editor');
  // 编程窗口浮在画布右边、盖住了"属性"页：学生写完程序会关掉它（右上角 ×）
  const ed = p.locator('.fw', { has: p.locator('.fw-h', { hasText: 'PLC 编程' }) });
  await ed.locator('.fw-h button[title="关闭"]').first().click({ timeout: 10000 }).catch(() => null); await wait(800);
  ok('（关掉编程窗口）', !(await ed.count()), await ed.count());

  // ---- 第 4 步：按操作台：画布右下角的操作台，关掉了从对象面板"操作台"再开 ----
  await p.locator('[data-k="tour-next"]').click(); await wait(400);
  const t4 = await text();
  ok('第 4 步说的是"操作台"和"启动"', (await step()) === 3 && /"操作台"/.test(t4) && /"启动"/.test(t4), t4);
  await p.evaluate(() => { window.__vfEd.sel = ['CELL1']; }); await wait(1200);
  await p.locator('.el-tabs__item:has-text("属性")').first().click(); await wait(800);
  ok('选中实训单元：右边"属性"页里的"操作台"看得见、能点', await usable(p.locator('.op-acts button:has-text("操作台")')),
     await p.locator('.op-acts').innerText().catch(() => '（没有对象面板）'));
  await p.locator('.op-acts button:has-text("操作台")').first().click().catch(() => null); await wait(1500);
  ok('操作台上的"启动"按钮看得见、能点', await usable(p.locator('.cco button:has-text("启动"), .cco [title*="启动"]')),
     await p.locator('.cco').innerText().catch(() => ''));
  await shot('g04_console');

  // ---- 第 5 步：提交评分（下载过程序以后才能点） ----
  await p.locator('[data-k="tour-next"]').click(); await wait(400);
  const t5 = await text();
  ok('第 5 步说的是"提交评分"', (await step()) === 4 && /"提交评分"/.test(t5), t5);
  ok('还没下载程序时"提交评分"不能点（提示先下载）', !(await usable(p.locator('[data-k="submit-score"]'))));
  const dl = await api(S, 'POST', `/api/p/${encodeURIComponent(sb)}/cells/PLC1/program/download`, { program: ref });
  ok('（学生把程序下载到 PLC1，第一次下载后自动运行）', dl.ok && dl.state === 'RUN', JSON.stringify(dl).slice(0, 120));
  await wait(4500);
  ok('下载以后"提交评分"能点了', await usable(p.locator('[data-k="submit-score"]')));
  ok('下载以后"先编程并下载"的提示不见了', !(await p.locator('[data-k="next-step"]').count()) && !(await p.locator('[data-k="console-hint"]').count()));
  await shot('g05_ready');
  await p.locator('[data-k="tour-next"]').click(); await wait(400);
  ok('点"知道了"引导关掉', !(await p.locator('.tour-card').count()));
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
