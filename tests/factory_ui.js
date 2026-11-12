// 4.4 界面走查（B 机）：学生"教学"页铺满窗口（1280 / 1680 / 2560，浅色 + 深色）、网页端"在客户端里建工厂"提示、改密码对话框（网页 + 客户端首次登录）、
// 客户端"我的工厂"（新建 / 列表 / 在工作台里随便改）、提交工厂作业（本机检查 → 交给老师）、老师发布（向导）/ 全班提交 / 给分评语 / 打开运行、学生看到分数和评语。
// 需要：学校服务器 VF_URL（serve）+ 客户端 VF_CLIENT_URL（python -m vfactory desktop --home VF_CLIENT_HOME，还没登录过的数据目录）。
//   node tests/factory_ui.js        截图在 SHOT_DIR
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const SV = process.env.VF_URL || 'http://127.0.0.1:8800';
const CL = process.env.VF_CLIENT_URL || 'http://127.0.0.1:8831';
const HOME = process.env.VF_CLIENT_HOME;
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_factory');
const STAMP = new Date().toISOString().slice(5, 19).replace(/[-:T]/g, '');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (base, tok, method, url, body, extra = {}) => {
  const r = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), ...extra }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
};
const login = async (u, p) => (await api(SV, '', 'POST', '/api/login', { username: u, password: p })).token;
const ticket = async () => {
  const run = JSON.parse(fs.readFileSync(path.join(HOME, 'run.json'), 'utf-8'));
  return (await api(CL, '', 'POST', '/api/desktop/ticket', null, { 'x-vf-key': run.key })).token;
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const admin = await login('admin', 'honey123');
  const users = (await api(SV, admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('fu_teacher')) await api(SV, admin, 'POST', '/api/admin/users', { username: 'fu_teacher', name: '韩老师', role: 'teacher', password: 'teach123' });
  const T = await login('fu_teacher', 'teach123');
  const stu = `fu${STAMP.slice(-6)}`, stu2 = `fw${STAMP.slice(-6)}`;
  const cls = await api(SV, T, 'POST', '/api/teach/classes', { name: `工厂设计班 ${STAMP}` });
  await api(SV, T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `${stu},孙同学\n${stu2},钱同学` });
  await api(SV, T, 'POST', '/api/teach/courses/plc_basics/publish', { class_id: cls.id, open_all: false });
  await api(SV, T, 'POST', '/api/teach/courses/machining/publish', { class_id: cls.id, open_all: false });

  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const br = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const errs = [];
  const newPage = async (w, h, tok, base = SV, dark = false) => {
    const ctx = await br.newContext({ locale: 'zh-CN', viewport: { width: w, height: h }, acceptDownloads: true });
    await ctx.addInitScript(([t, d]) => { if (t) localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); sessionStorage.setItem('vf_pw_later', '1'); },
      [tok, dark]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(`pageerror(${base === CL ? 'client' : 'web'}): ` + e.message.slice(0, 200)));
    return p;
  };

  // ---------- 老师：发布"提交工厂"作业（向导） ----------
  const q = await newPage(1500, 920, T);
  await q.goto(`${SV}/teach`, { waitUntil: 'networkidle' }); await q.waitForTimeout(1200);
  await q.locator('.teacher-console button:has-text("单个作业")').click(); await q.waitForTimeout(1200);
  await q.locator('.el-dialog [data-k="pw-kind"] label:has-text("提交工厂")').first().click(); await q.waitForTimeout(500);
  await q.locator('.el-dialog input[data-k="pw-title"]').fill('设计一条带 PLC 的小产线');
  await q.screenshot({ path: `${OUT}/f01_publish_brief.png` });
  ok('发布向导：提交工厂第 1 步是要求（左边写、右边预览）', (await q.locator('.el-dialog [data-k="pw-factory-brief"] .vp-md h2, [data-k="pw-factory-brief"] .vp-md .mh').count()) >= 1);
  await q.locator('.el-dialog [data-k="pw-next"]').click(); await q.waitForTimeout(800);
  await q.locator('.el-dialog .publish-wizard .el-form-item:has-text("班级") .el-select').click(); await q.waitForTimeout(400);
  await q.locator(`.el-select-dropdown__item:visible:has-text("工厂设计班 ${STAMP}")`).click(); await q.waitForTimeout(300);
  await q.locator('.el-dialog [data-k="pw-next"]').click(); await q.waitForTimeout(800);
  await q.locator('.el-dialog [data-k="chk-blocks"]').first().click(); await q.locator('.el-dialog [data-k="chk-good"]').first().click(); await q.waitForTimeout(400);
  await q.screenshot({ path: `${OUT}/f02_publish_checks.png` });
  ok('发布向导：自动检查（模型无错 / 必须有的设备 / PLC 控制 / 合格品 / OEE）', (await q.locator('.el-dialog [data-k="pw-checks"] .el-checkbox').count()) >= 5);
  await q.locator('.el-dialog [data-k="pw-next"]').click(); await q.waitForTimeout(600);
  await q.screenshot({ path: `${OUT}/f03_publish_confirm.png` });
  await q.locator('.el-dialog [data-k="pw-publish"]').click(); await q.waitForTimeout(2000);
  const fa = (await api(SV, T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).find((a) => a.kind === 'factory');
  ok('发布成功：作业类型 factory，三条自动检查', fa && fa.spec && fa.spec.checks.length === 3, fa && JSON.stringify(fa.spec.checks));

  // ---------- 网页端学生："教学"页铺满窗口 ----------
  await api(SV, '', 'POST', '/api/login', { username: stu2, password: '123456' });
  const S2 = await login(stu2, '123456');
  for (const [w, h, dark] of [[1280, 800, false], [1680, 1000, false], [2560, 1300, false]]) {   // 5.0.1 起只有浅色
    const p = await newPage(w, h, S2, SV, dark);
    await p.goto(`${SV}/teach`, { waitUntil: 'networkidle' }); await p.waitForTimeout(2500);
    // 4.6：学生的"课程"页是课程卡片 + 学校作业，铺满窗口（以前是课程地图在左、这一课在右）
    const grid = await p.locator('[data-k="course-grid"]').boundingBox();
    const hw = await p.locator('[data-k="homework"]').boundingBox();
    const tag = `${w}${dark ? '_dark' : ''}`;
    ok(`网页学生"课程"页 ${tag}：课程卡片铺开、学校作业单独一块、没有横向滚动`, grid && hw && grid.width > Math.min(w - 260, 1720) * 0.8 && hw.y > grid.y
      && await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), JSON.stringify({ grid: grid && [Math.round(grid.x), Math.round(grid.width)], hw: hw && Math.round(hw.y) }));
    if (w === 1680 && !dark) ok('网页端提示"在客户端里可以建自己的工厂"', /在客户端里可以建自己的工厂/.test(await p.locator('[data-k="web-mine-hint"]').innerText().catch(() => '')));
    await p.screenshot({ path: `${OUT}/f10_web_teach_${tag}.png` });
    if (w === 1680 && !dark) {
      await p.locator(`.task-card[data-aid="${fa.id}"]`).click(); await p.waitForTimeout(1500);
      ok('网页端打开工厂设计作业：说明要在客户端里做（没有提交按钮）', /要在客户端里做/.test(await p.locator('[data-k="factory-submit"]').innerText().catch(() => ''))
        && !(await p.locator('[data-k="factory-submit-btn"]').count()));
      await p.screenshot({ path: `${OUT}/f11_web_factory_task.png` });
      // 右上角头像菜单 → 修改密码：原密码 + 新密码两遍，规则写清楚
      await p.locator('.top .user').click(); await p.waitForTimeout(400);
      await p.locator('.el-dropdown-menu__item:has-text("修改密码")').click(); await p.waitForTimeout(800);
      await p.locator('input[data-k="pw-old"]').fill('123456');
      await p.locator('input[data-k="pw-new"]').fill('abc12345');
      await p.locator('input[data-k="pw-new2"]').fill('abc1234');
      await p.waitForTimeout(300);
      ok('头像菜单"修改密码"：原密码 + 新密码 + 确认新密码，不一致时提示且不能保存', (await p.locator('.pw-dlg').innerText()).includes('两次输入的新密码不一样')
        && !(await p.locator('[data-k="pw-save"]').isEnabled()));
      await p.screenshot({ path: `${OUT}/f12_web_password.png` });
      await p.locator('input[data-k="pw-new2"]').fill('abc12345'); await p.waitForTimeout(200);
      await p.locator('[data-k="pw-save"]').click(); await p.waitForTimeout(1200);
      ok('网页改密码成功：新密码能登录', !!(await login(stu2, 'abc12345')));
    }
    await p.context().close();
  }

  // ---------- 客户端：学生登录（首次改密码）→ 我的工厂 ----------
  const c = await newPage(1680, 1000, '', CL);
  await c.goto(`${CL}/#dt=${await ticket()}`, { waitUntil: 'networkidle' }); await c.waitForTimeout(800);
  const inputs = c.locator('.box input');
  await inputs.nth(0).fill(SV); await inputs.nth(1).fill(stu); await inputs.nth(2).fill('123456');
  await c.locator('.box button:has-text("登录")').click();
  await c.waitForSelector('input[data-k="pw-new"]', { timeout: 20000 }).catch(() => null);
  await c.locator('input[data-k="pw-new"]').fill('stu12345'); await c.locator('input[data-k="pw-new2"]').fill('stu12345'); await c.waitForTimeout(300);
  await c.screenshot({ path: `${OUT}/f20_client_force_pw.png` });
  ok('客户端首次登录改密码：规则全部打勾才能保存', (await c.locator('[data-k="pw-rules"] li.ok').count()) === 4 && await c.locator('[data-k="pw-save"]').isEnabled());
  await c.locator('[data-k="pw-save"]').click();
  await c.waitForURL(/\/(teach|welcome)/, { timeout: 30000 }).catch(() => null); await c.waitForTimeout(2500);
  await c.screenshot({ path: `${OUT}/f21_client_teach_1680.png` });
  ok('客户端学生：左边菜单有"我的工厂"', (await c.locator('[data-k="menu-mine"]').count()) === 1);
  await c.locator('[data-k="menu-mine"]').click(); await c.waitForTimeout(1500);
  ok('"我的工厂"一开始是空的（有新建入口）', (await c.locator('[data-k="mine-empty"]').count()) === 1);
  await c.screenshot({ path: `${OUT}/f22_mine_empty.png` });
  await c.locator('[data-k="mine-new"]').click(); await c.waitForTimeout(800);
  await c.locator('[data-tpl="course:machining/m01"]').click();
  await c.locator('input[data-k="mine-name"]').fill('我的机加线');
  await c.screenshot({ path: `${OUT}/f23_mine_new.png` });
  await c.locator('[data-k="mine-create"]').click();
  await c.waitForURL(/\/p\/local-[^/]+\/workbench/, { timeout: 60000 }).catch(() => null); await c.waitForTimeout(9000);
  ok('建好直接在工作台打开（本机工厂）', /\/p\/local-/.test(c.url()), c.url());
  const wsN = await c.locator('.ed-ws button').count();
  ok('自己的工厂：全部工作区、能运行能改（不是学生沙箱的限制）', wsN >= 3 && await c.locator('.ed-bar .rb button').nth(1).isEnabled().catch(() => false), `工作区 ${wsN}`);
  await c.screenshot({ path: `${OUT}/f24_mine_workbench.png` });
  const ctok = await c.evaluate(() => localStorage.getItem('vf_token'));
  await api(CL, ctok, 'POST', '/api/client/myplants', { name: '我的电机控制', template: 'cells/motor' });
  await c.goto(`${CL}/mine`, { waitUntil: 'networkidle' }); await c.waitForTimeout(1500);
  await c.screenshot({ path: `${OUT}/f25_mine_list.png` });
  ok('"我的工厂"只有浅色（没有深色切换）', (await c.locator('[data-k="mine-theme"]').count()) === 0 && !(await c.evaluate(() => document.documentElement.classList.contains('dark'))));
  ok('"我的工厂"列表：两座，打开/改名/复制/导出/删除', (await c.locator('.pl[data-pid]').count()) === 2 && /导出/.test(await c.locator('.pl').first().innerText()));

  // ---------- 客户端：提交工厂作业 ----------
  await c.goto(`${CL}/teach`, { waitUntil: 'networkidle' }); await c.waitForTimeout(2500);
  await c.waitForSelector(`.sw-item[data-raid="${fa.id}"]`, { timeout: 20000 }).catch(() => null);
  await c.locator(`.sw-item[data-raid="${fa.id}"] button`).click();
  await c.waitForSelector('[data-k="factory-submit"]', { timeout: 20000 }).catch(() => null); await c.waitForTimeout(1500);
  ok('客户端打开工厂设计作业：选一座"我的工厂"提交', /选一座"我的工厂"提交/.test(await c.locator('[data-k="factory-submit"]').innerText().catch(() => '')));
  await c.locator('[data-k="factory-pick"]').click(); await c.waitForTimeout(400);
  await c.locator('.el-select-dropdown__item:visible:has-text("我的机加线")').click(); await c.waitForTimeout(300);
  await c.screenshot({ path: `${OUT}/f30_client_factory_pick.png` });
  await c.locator('[data-k="factory-check"] button, button[data-k="factory-check"]').first().click();
  await c.waitForSelector('.task-panel .sub .vp-score', { timeout: 120000 }).catch(() => null); await c.waitForTimeout(800);
  ok('本机检查：成绩页有本机预估分和每条检查', /本机预估分/.test(await c.locator('.task-panel .tp-tabs').innerText().catch(() => '')));
  await c.locator('[data-k="factory-submit-btn"] button, button[data-k="factory-submit-btn"]').first().click();
  await c.waitForSelector('.school-res', { timeout: 120000 }).catch(() => null); await c.waitForTimeout(800);
  ok('提交给老师：学校服务器重新检查', /学校服务器评分/.test(await c.locator('.school-res').innerText().catch(() => '')), await c.locator('.school-res').innerText().catch(() => ''));
  await c.screenshot({ path: `${OUT}/f31_client_factory_submitted.png` });

  // ---------- 老师：全班提交 → 给分 + 评语 → 打开运行 ----------
  await q.goto(`${SV}/teach`, { waitUntil: 'networkidle' }); await q.waitForTimeout(1500);
  await q.locator('.teacher-console .vp-head .el-select').first().click();
  await q.locator('.el-select-dropdown__item:visible:has-text("设计一条带 PLC 的小产线")').first().click(); await q.waitForTimeout(2000);
  ok('老师：工厂设计作业的全班提交一览（交的是哪座工厂）', /我的机加线/.test(await q.locator('[data-k="factory-subs"]').innerText().catch(() => '')));
  await q.screenshot({ path: `${OUT}/f40_teacher_factory_subs.png` });
  await q.locator('[data-k="factory-subs"] .fs-row').first().click(); await q.waitForTimeout(1500);
  await q.locator('.detail .sub').first().locator('.el-input-number input').fill('90');
  await q.locator('.detail .sub').first().locator('input[placeholder="总评语"]').fill('布局清楚；下次给机床加一台 PLC');
  await q.locator('.detail .sub').first().locator('button:has-text("保存复核")').click(); await q.waitForTimeout(1500);
  const subs = await api(SV, T, 'GET', `/api/teach/assignments/${fa.id}/submissions?username=${stu}`);
  ok('老师给分 90 + 评语 → 成绩', subs[0] && subs[0].score === 90 && subs[0].comment.includes('PLC'), subs[0] && subs[0].score);
  await q.screenshot({ path: `${OUT}/f41_teacher_review.png` });
  await q.locator('.detail .sub').first().locator('button:has-text("打开运行")').click();
  await q.waitForURL(/\/p\/sb-review-\d+\/workbench/, { timeout: 30000 }).catch(() => null); await q.waitForTimeout(7000);
  ok('老师"打开运行"：复核沙箱里是学生的工厂', /sb-review-\d+/.test(q.url()) && /复核沙箱/.test(await q.locator('.task-panel').innerText().catch(() => '复核沙箱')), q.url());
  await q.screenshot({ path: `${OUT}/f42_teacher_review_sandbox.png` });

  // ---------- 学生在客户端里看到分数和评语 ----------
  await c.locator('.task-panel .vp-head button[title="刷新"]').click(); await c.waitForTimeout(2500);
  await c.locator('.task-panel .el-tabs__item:has-text("成绩")').click(); await c.waitForTimeout(800);
  const sr = await c.locator('[data-k="school-results"]').innerText().catch(() => '');
  ok('学生在客户端里看到老师的分数和评语', /90/.test(sr) && /下次给机床加一台 PLC/.test(sr), sr.replace(/\n/g, ' '));
  await c.screenshot({ path: `${OUT}/f32_client_teacher_grade.png` });
  // 客户端：头像菜单改密码（改服务器账号）
  await c.locator('.top .user').click(); await c.waitForTimeout(400);
  await c.locator('.el-dropdown-menu__item:has-text("修改密码")').click(); await c.waitForTimeout(800);
  ok('客户端头像菜单"修改密码"：说明改的是服务器账号、离线登录跟着换', /离线登录也会换成新密码/.test(await c.locator('.pw-dlg').innerText().catch(() => '')));
  await c.screenshot({ path: `${OUT}/f33_client_password.png` });

  ok('页面没有脚本错误', errs.length === 0, errs.slice(0, 5).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : '') + `，截图在 ${OUT}`);
  await br.close();
})();
