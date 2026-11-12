// 客户端（桌面模式）教学界面走查：登录页（服务器账号）→ 本机课程地图 + 学校作业（PLC 课）→ 在本机做 → 提交给老师 / 导出作业包 → 双击自己的作业包接着做；
// 老师在学校服务器网页上看到来源、下载作业包、打开运行、导入作业包。
// 需要：学校服务器 VF_URL（serve）+ 客户端 VF_CLIENT_URL（python -m vfactory desktop --home VF_CLIENT_HOME，还没登录过的数据目录）。这里自己建数据。
//   node tests/client_ui.js        截图在 SHOT_DIR
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const SV = process.env.VF_URL || 'http://127.0.0.1:8800';
const CL = process.env.VF_CLIENT_URL || 'http://127.0.0.1:8831';
const HOME = process.env.VF_CLIENT_HOME;
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_client');
const STAMP = new Date().toISOString().slice(5, 19).replace(/[-:T]/g, '');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (base, tok, method, url, body, extra = {}) => {
  const r = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), ...extra }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
};
const login = async (u, p) => (await api(SV, '', 'POST', '/api/login', { username: u, password: p })).token;
/** 启动器的做法：用 run.json 里的 key 换一个一次性令牌，地址带 #dt=… */
const ticket = async () => {
  const run = JSON.parse(fs.readFileSync(path.join(HOME, 'run.json'), 'utf-8'));
  return (await api(CL, '', 'POST', '/api/desktop/ticket', null, { 'x-vf-key': run.key })).token;
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  // ---------- 学校服务器准备 ----------
  const admin = await login('admin', 'honey123');
  const users = (await api(SV, admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('cu_teacher')) await api(SV, admin, 'POST', '/api/admin/users', { username: 'cu_teacher', name: '周老师', role: 'teacher', password: 'teach123' });
  const T = await login('cu_teacher', 'teach123');
  const stu = `cu${STAMP.slice(-6)}`;
  const cls = await api(SV, T, 'POST', '/api/teach/classes', { name: `客户端界面班 ${STAMP}` });
  await api(SV, T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `${stu},王同学` });
  // 作业用 PLC 课第 1 课（电机启停自锁）：学生给 PLC 块（独立设备，信号线控制单元）下载程序，本机评分、交给老师
  await api(SV, T, 'POST', '/api/teach/courses/plc_basics/publish', { class_id: cls.id, open_all: true });
  const asg = (await api(SV, T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).filter((a) => a.course === 'plc_basics').sort((a, b) => (a.seq || 0) - (b.seq || 0))[0];
  const ref = (await api(SV, T, 'GET', `/api/teach/scenes/${asg.scene || 's01_motor_latch'}`)).reference.st;

  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const br = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const errs = [];
  const ctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1500, height: 920 }, acceptDownloads: true });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|40[0-9]|Failed to load resource/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });

  // ---------- 客户端：登录页（服务器地址 + 服务器账号）→ 学生的"我的课程" ----------
  await p.goto(`${CL}/#dt=${await ticket()}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(800);
  ok('客户端打开先到登录页（服务器地址 + 账号，可以单机使用）', /\/login/.test(p.url()) && (await p.locator('text=不连服务器，单机使用').count()) === 1, p.url());
  const inputs = p.locator('.box input');
  await inputs.nth(0).fill(SV); await inputs.nth(1).fill(stu); await inputs.nth(2).fill('123456');
  await shot('c00_login');
  await p.locator('.box button:has-text("登录")').click();
  // 初始密码：要求改密码（改到服务器上）。新密码输两遍，规则逐条打勾；两次不一样时"保存"不能点（4.4）
  await p.waitForSelector('input[data-k="pw-new"]', { timeout: 20000 }).catch(() => null);
  await p.locator('input[data-k="pw-new"]').fill('stu12345');
  await p.locator('input[data-k="pw-new2"]').fill('stu12346');
  await p.waitForTimeout(300);
  ok('首次改密码：有"确认新密码"，两次不一样时提示且不能保存', (await p.locator('.pw-dlg').innerText()).includes('两次输入的新密码不一样')
     && !(await p.locator('[data-k="pw-save"]').isEnabled()) && (await p.locator('[data-k="pw-rules"] li').count()) === 4);
  await shot('c00b_force_pw');
  await p.locator('input[data-k="pw-new2"]').fill('stu12345');
  await p.locator('[data-k="pw-save"]').click();
  // 4.5：登录后先到"开始"页（欢迎页），再从侧栏进"教学"
  await p.waitForURL(/\/(teach|welcome)/, { timeout: 30000 }).catch(() => null);
  const landed = p.url();
  if (/\/welcome/.test(landed)) { await p.locator('.el-menu-item', { hasText: '课程' }).first().click().catch(() => null); await p.waitForURL(/\/(teach|courses)/, { timeout: 20000 }).catch(() => null); }
  await p.waitForSelector('.school-work', { timeout: 30000 }).catch(() => null);
  await p.waitForTimeout(2000);
  ok('学生登录后到开始页，侧栏进"课程"', /\/(teach|welcome|courses)/.test(landed) && /\/(teach|courses)/.test(p.url()), landed + ' → ' + p.url());
  ok('新密码在服务器上生效', !!(await login(stu, 'stu12345')));
  ok('本机课程页：自带课程的卡片，离线能做', (await p.locator('.course-card').count()) >= 3, await p.locator('.course-card').count());
  ok('顶栏显示连着的服务器', new RegExp(SV.replace(/^https?:\/\//, '').replace(/[.]/g, '\.')).test(await p.locator('.local-badge').innerText().catch(() => '')));
  await shot('c01_client_map');
  await p.waitForSelector(`.sw-item[data-raid="${asg.id}"]`, { timeout: 20000 }).catch(() => null);
  ok('学校作业：登录的账号就是学校账号，直接列出', (await p.locator(`.sw-item[data-raid="${asg.id}"]`).count()) === 1, await p.locator('.school-work').innerText().catch(() => ''));
  await shot('c03_school_list');

  // ---------- 在本机做 → 进沙箱 → 本机评分 → 提交给老师 ----------
  await p.locator(`.sw-item[data-raid="${asg.id}"] button`).click();
  await p.waitForSelector('.task-panel .acts', { timeout: 20000 }).catch(() => null);
  await p.waitForTimeout(800);
  const acts = await p.locator('.task-panel .acts').innerText().catch(() => '');
  ok('学校作业在本机打开：有"本机评分""提交给老师""导出作业包"', /本机评分/.test(acts) && /提交给老师/.test(acts) && /导出作业包/.test(acts), acts.replace(/\n/g, ' '));
  await shot('c04_lesson');
  const tok = await p.evaluate(() => localStorage.getItem('vf_token'));
  const lid = Number(await p.evaluate(() => localStorage.getItem('vf_teach_aid')));
  const sb = await api(CL, tok, 'POST', `/api/teach/assignments/${lid}/sandbox`);
  ok('学校作业的沙箱建在本机', (await api(CL, tok, 'GET', `/api/desktop/where/${sb.pid}`)).local, sb.pid);
  const dl = await api(CL, tok, 'POST', `/api/p/${sb.pid}/cells/${(sb.plc_block || {}).id || sb.bid}/program/download`, { program: ref });
  ok('程序下载到沙箱里的 PLC 块（独立设备）', dl.ok && dl.state === 'RUN' && (sb.plc_block || {}).id === 'PLC1', JSON.stringify(sb.plc_block));
  await p.locator('.task-panel .vp-head button[title="刷新"]').click();
  await p.waitForTimeout(4500);
  await p.locator('.task-panel .acts button:has-text("本机评分")').click();
  await p.waitForSelector('.task-panel .vp-score', { timeout: 60000 }).catch(() => null);
  await p.waitForTimeout(800);
  ok('本机评分：成绩页写明是本机预估分', /本机预估分/.test(await p.locator('.task-panel .tp-tabs').innerText().catch(() => '')));
  await p.locator('.task-panel .acts button:has-text("提交给老师")').click();
  await p.waitForSelector('.school-res', { timeout: 120000 }).catch(() => null);
  const sr = await p.locator('.school-res').innerText().catch(() => '');
  ok('提交给老师：显示学校服务器评分', /学校服务器评分/.test(sr), sr.replace(/\n/g, ' '));
  await shot('c05_submitted');
  const [d1] = await Promise.all([p.waitForEvent('download', { timeout: 20000 }), p.locator('.task-panel .acts button:has-text("导出作业包")').click()]);
  const pkPath = path.join(HOME, `ui-${STAMP}.vfhw`);
  await d1.saveAs(pkPath);
  ok('导出作业包（.vfhw 下载）', fs.statSync(pkPath).size > 300 && /\.vfhw$/.test(d1.suggestedFilename()), `${d1.suggestedFilename()} ${fs.statSync(pkPath).size}`);
  await p.evaluate(() => document.documentElement.classList.add('dark'));
  await p.waitForTimeout(300);
  await shot('c05b_submitted_dark');
  await p.evaluate(() => document.documentElement.classList.remove('dark'));

  // ---------- 双击作业包：启动器打开 /?open=<路径> ----------
  await p.goto(`${CL}/teach?open=${encodeURIComponent(pkPath)}#dt=${await ticket()}`, { waitUntil: 'networkidle' });
  await p.waitForSelector('.el-dialog:has-text("作业包") .pk-kv', { timeout: 20000 }).catch(() => null);
  const pkTxt = await p.locator('.el-dialog .pk-kv').innerText().catch(() => '');
  ok('双击作业包：显示作业、学生、学校、本机预估分', new RegExp(stu).test(pkTxt) && pkTxt.includes(asg.title) && /本机预估分/.test(pkTxt), pkTxt.replace(/\n/g, ' '));
  await shot('c06_package_open');
  // 学生打开的是自己的包：装进自己这个作业的沙箱接着做（复核沙箱只给老师）
  await p.locator('.el-dialog button:has-text("装进我的沙箱接着做")').click();
  await p.waitForURL(/\/p\/sb-L-[^/]+\/workbench/, { timeout: 30000 }).catch(() => null);
  await p.waitForTimeout(6000);
  ok('学生双击自己的作业包：装进自己的作业沙箱（不是复核沙箱）', /\/p\/sb-L-/.test(p.url()) && !/sb-review/.test(p.url()), p.url());
  if (!(await p.locator('.task-panel').count())) {
    await p.locator('.ed-ws button:has-text("教学")').click().catch(() => null);
    await p.waitForTimeout(1500);
  }
  const tpTxt = await p.locator('.task-panel').innerText().catch(() => '');
  ok('左栏是这一课（可以接着做、再提交），不是复核沙箱', !/复核沙箱/.test(tpTxt) && /提交给老师/.test(tpTxt), tpTxt.replace(/\s+/g, ' ').slice(0, 120));
  const lv = await api(CL, tok, 'GET', `/api/teach/assignments/${lid}/live`);
  ok('作业包里的程序已在 PLC 块里运行', lv.has_program && lv.plc === 'RUN' && (lv.plc_block || {}).id === 'PLC1', `${lv.has_program} ${lv.plc}`);
  await shot('c07_package_own');

  // ---------- 5.0.1 MES 在客户端的界面里（不再内嵌另一个网页）：学生只有 PLC 课的沙箱（MES 认不全）→ 不自动启动，让人选 ----------
  await p.goto(`${CL}/mes`, { waitUntil: 'networkidle' });
  await p.waitForSelector('[data-tour="mes-head"], [data-k="mes-bar"]', { timeout: 30000 }).catch(() => null);
  await p.waitForTimeout(1500);
  const mesSt = await api(CL, await p.evaluate(() => localStorage.getItem('vf_token')), 'GET', '/api/desktop/mes');
  ok('客户端 /mes：MES 页面在虚拟工厂的界面里（侧栏有 MES、没有 iframe）', (await p.locator('[data-k="menu-mes"]').count()) === 1
     && (await p.locator('iframe').count()) === 0 && (await p.locator('[data-k="mes-page"]').count()) === 1, p.url());
  ok('客户端 /mes：没有 MES 认得的本机工厂时不自动启动，显示选工厂', mesSt.state === 'stopped' && (await p.locator('[data-tour="mes-head"]').count()) === 1, mesSt.state);
  await shot('c07b_client_mes');
  await ctx.close();

  // ---------- 老师：学校服务器网页 ----------
  const tctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1500, height: 920 }, acceptDownloads: true });
  await tctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); }, T);
  const q = await tctx.newPage();
  q.on('pageerror', (e) => errs.push('teacher pageerror: ' + e.message.slice(0, 200)));
  await q.goto(`${SV}/teach`, { waitUntil: 'networkidle' });
  await q.waitForTimeout(1500);
  await q.locator('.teacher-console .vp-head .el-select').first().click();
  await q.locator(`.el-select-dropdown__item:has-text("${asg.title}")`).first().click();
  await q.waitForTimeout(1500);
  await q.locator(`[data-user="${stu}"]`).click();
  await q.waitForTimeout(1500);
  await q.locator('.detail .el-tabs__item:has-text("提交与复核")').click();
  await q.waitForTimeout(800);
  const subTxt = await q.locator('.detail .sub').first().innerText().catch(() => '');
  ok('老师：提交显示来源"客户端"，有"打开运行""作业包"', /客户端/.test(subTxt) && /打开运行/.test(subTxt) && /作业包/.test(subTxt), subTxt.replace(/\n/g, ' ').slice(0, 120));
  ok('老师：有"导入作业包"', (await q.locator('.detail button:has-text("导入作业包")').count()) === 1);
  await q.screenshot({ path: `${OUT}/c08_teacher_subs.png` });
  const [d2] = await Promise.all([q.waitForEvent('download', { timeout: 20000 }), q.locator('.detail .sub').first().locator('button:has-text("作业包")').click()]);
  ok('老师下载作业包', /\.vfhw$/.test(d2.suggestedFilename()), d2.suggestedFilename());
  // 导入作业包（替学生）
  await q.locator('.detail input[type="file"][accept=".vfhw"]').setInputFiles(pkPath);
  await q.locator('.el-message-box button:has-text("确定"), .el-message-box button:has-text("OK")').first().click();
  await q.waitForTimeout(6000);
  const subs = await api(SV, T, 'GET', `/api/teach/assignments/${asg.id}/submissions?username=${stu}`);
  ok('老师在界面上导入作业包：多一次"导入"的提交', subs[0] && subs[0].source === 'import', subs.map((s) => s.source).join(','));
  await q.locator('.detail .sub').first().locator('button:has-text("打开运行")').click();
  await q.waitForURL(/\/p\/sb-review-\d+\/workbench/, { timeout: 30000 }).catch(() => null);
  await q.waitForTimeout(6000);
  ok('老师"打开运行"：复核沙箱工作台', /sb-review-\d+/.test(q.url()), q.url());
  ok('复核沙箱：运行按钮可用', await q.locator('.ed-bar .rb button').nth(1).isEnabled().catch(() => false));
  await q.screenshot({ path: `${OUT}/c09_teacher_review.png` });

  // 5.0.1 学校服务器网页上的 MES：说明 + 在客户端中打开（同一个页面）
  for (const path of ['/mes', '/mes/e/work_order']) {
    await q.goto(`${SV}${path}`, { waitUntil: 'networkidle' });
    await q.waitForSelector('[data-k="mes-client-only"]', { timeout: 20000 }).catch(() => null);
    const href = await q.locator('[data-k="client-link-open"]').getAttribute('href').catch(() => '');
    ok(`服务器网页 ${path}：MES 只在客户端里，给"在客户端中打开"`, q.url().endsWith(path) && href === `vfactory://open?path=${encodeURIComponent(path)}`
       && (await q.locator('[data-k="menu-mes"]').count()) === 1, `${q.url()} ${href}`);
  }
  await q.screenshot({ path: `${OUT}/c10_server_mes.png` });

  ok('页面没有脚本错误', errs.length === 0, errs.slice(0, 5).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : '') + `，截图在 ${OUT}`);
  await br.close();
})();
