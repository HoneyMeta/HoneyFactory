// 教学与外壳的衔接（B 机，先启动 serve）：node tests/teach_ui.js
// 学生登录落到"教学"页、进沙箱后工作台在教学工作区、能改能跑、右下角是 AI 助教；老师旁观沙箱是只读；SOP 播放时三维相机跟随
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'tu');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;
// 4.5：第一次"开始这一课"有跟随教程的课会先问"跟着教程做 / 自己做"——这里选"自己做"（教程本身在 tutorial_ui.js 里测）
const selfDo = async (pg) => { const b = pg.locator('.tour-ask button:has-text("自己做")'); await b.waitFor({ state: 'visible', timeout: 2500 }).catch(() => null); if (await b.isVisible().catch(() => false)) { await b.click(); await pg.waitForTimeout(400); } };

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const admin = await login('admin', 'honey123');
  const users = (await api(admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('ui_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'ui_teacher', name: '李老师', role: 'teacher', password: 'teach123' });
  const T = await login('ui_teacher', 'teach123');
  let cls = (await api(T, 'GET', '/api/teach/classes')).find((c) => c.name === '界面测试班');
  if (!cls) { const r = await api(T, 'POST', '/api/teach/classes', { name: '界面测试班' }); cls = { id: r.id }; }
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: '账号,姓名\nui_stu1,张同学\n', default_password: '123456' });
  let asg = (await api(T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).find((a) => !a.course);
  if (!asg) { const r = await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's03_conveyor', title: '传送带启停（界面测试）' }); asg = { id: r.id }; }
  const S = await login('ui_stu1', '123456');

  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const errs = [];
  const page = async (tok) => {
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
    await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '1'); }, tok);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404|403|Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
    // 接口出错单独记录（没配大模型时助教返回 4xx 属正常，见下面的判断）
    p.on('response', (r) => { if (r.status() >= 400 && !/tutor\/ask|favicon/.test(r.url()) && r.status() !== 404) errs.push(`${r.status()} ${r.request().method()} ${r.url().replace(B, '')}`); });
    return p;
  };
  const wait = (p, ms) => p.waitForTimeout(ms);
  // 初始密码"先改一下密码"弹窗（点"以后再说"）、第一次进沙箱左栏的五步引导卡片（点"跳过"）
  const dismiss = async (p, label, n) => {
    const b = p.locator(`${label === '跳过' ? '.tour-card' : '.el-dialog'} button:has-text("${label}")`);
    await b.first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => null);
    if (!(await b.first().isVisible().catch(() => false))) return false;
    if (n) await p.screenshot({ path: `${OUT}/${n}.png` });
    await b.first().click(); await wait(p, 600);
    return true;
  };

  // ---------- 学生 ----------
  const p = await page(S);
  await p.goto(B + '/p/foundry-housing/workbench', { waitUntil: 'networkidle' }); await wait(p, 2500);
  ok('学生打开普通工厂被转到"教学"页', /\/teach$/.test(p.url()), p.url());
  await dismiss(p, '以后再说', 't00_student_pw');
  await p.screenshot({ path: `${OUT}/t01_student_home.png` });
  await p.locator(`.vp-item[data-aid="${asg.id}"]`).click(); await wait(p, 1500);
  await p.locator('.task-panel [data-k="enter-lesson"]').first().click(); await selfDo(p); await wait(p, 9000);
  ok('进入沙箱打开工作台', /\/p\/sb-[^/]+\/workbench$/.test(p.url()), p.url());
  await wait(p, 1500);
  { // 引导是左栏里的卡片，不遮画布：画布上的东西照常能点（没有遮罩层）
    const masks = await p.locator('.el-overlay:visible, .el-overlay-dialog:visible').count();
    ok('第一次进沙箱有五步引导，且不遮挡画布', (await p.locator('.task-panel .tour-card').count()) === 1 && masks === 0, `遮罩 ${masks}`);
  }
  await dismiss(p, '跳过', 't01b_student_tour');
  await dismiss(p, '以后再说');
  ok('沙箱里不再显示"开始这一课"按钮，改成状态标签（S12）', (await p.locator('.task-panel [data-k="enter-lesson"]').count()) === 0 && (await p.locator('.task-panel .acts .el-tag').count()) === 1);
  const sb = decodeURIComponent(p.url().match(/\/p\/([^/]+)\/workbench/)[1]);
  ok('沙箱默认教学工作区', (await p.locator('.ed-ws button.on').innerText()).includes('教学'));
  ok('左栏是实训任务', (await p.locator('.task-panel').count()) === 1);
  ok('学生在沙箱里运行/暂停按钮可用', await p.locator('.ed-bar .rb button').nth(1).isEnabled().catch(() => false));
  { // 真的点一下：以前后端对学生返回 403（运行控制只认工程师）
    const m0 = await p.locator('.ed-mode').innerText();
    const r403 = []; const onResp = (r) => { if (/\/ctl|\/model/.test(r.url()) && r.status() >= 400) r403.push(r.status() + ' ' + r.url().replace(B, '')); };
    p.on('response', onResp);
    await p.locator('.ed-bar .rb button').nth(1).click(); await wait(p, 2500);
    const m1 = await p.locator('.ed-mode').innerText();
    await p.locator('.ed-bar .rb button').nth(1).click(); await wait(p, 2500);   // 再点一次：运行和暂停两个方向都要通（运行前外壳会先存草稿）
    const m2 = await p.locator('.ed-mode').innerText();
    p.off('response', onResp);
    ok('学生点运行/暂停真的生效（两个方向）', !r403.length && m0 !== m1 && m1 !== m2, `${m0} → ${m1} → ${m2} ${r403.join(',')}`);
  }
  ok('右下角是 AI 助教', (await p.locator('.aid-h b').innerText().catch(() => '')).includes('助教'));
  await p.screenshot({ path: `${OUT}/t02_student_sandbox.png` });
  await p.locator('.aid-open span').first().click(); await wait(p, 1000);
  for (let i = 0; i < 60 && (await p.locator('.aid-m.assistant .aid-b').count()) === 0; i++) await wait(p, 1000);
  const ans = await p.locator('.aid-m.assistant .aid-b').first().innerText().catch(() => '');
  ok('助教回答了（走 /api/tutor/ask）', ans.length > 5 || (await p.locator('.aid-err').innerText().catch(() => '')).includes('没能完成'), ans.slice(0, 120));
  await p.screenshot({ path: `${OUT}/t03_student_tutor.png` });

  // ---------- 课程：课程地图 → 进课 → 目标与作答 → 图上点选（外壳 ed.pick）→ 提交 ----------
  await api(T, 'POST', '/api/teach/courses/machining/publish', { class_id: cls.id, open_all: true });
  const c = await page(S);
  await p.close();                                          // 关掉前面的工作台页（软件渲染三维很吃 CPU）
  await c.goto(B + '/teach', { waitUntil: 'networkidle' });
  await dismiss(c, '以后再说');
  // 4.6：学生的"课程"页是课程卡片（默认收起），点卡片打开课程详情（章节和课），点一课进到这一课
  await c.waitForSelector('.course-card[data-course="machining"]', { timeout: 30000 }).catch(() => null);
  ok('学生"课程"页：课程卡片默认收起', (await c.locator('.course-card[data-course="machining"]').count()) === 1 && (await c.locator('[data-k="course-grid"] .lesson').count()) === 0);
  await c.locator('.course-card[data-course="machining"]').click(); await wait(c, 900);
  const cm = c.locator('[data-k="course-detail"].course[data-course="machining"]').first();
  ok('点卡片：课程详情里是这门课的 8 课', (await cm.count()) === 1 && (await cm.locator('.lesson').count()) === 8);
  await c.screenshot({ path: `${OUT}/t05_course_map.png` });
  await cm.locator('.lesson').nth(2).click(); await wait(c, 1800);
  await c.locator('.task-panel [data-k="enter-lesson"]').first().click(); await selfDo(c); await wait(c, 9000);
  ok('进课打开沙箱工作台', /\/p\/sb-[^/]+\/workbench$/.test(c.url()), c.url());
  await dismiss(c, '跳过'); await dismiss(c, '以后再说');
  await c.waitForFunction(() => /找瓶颈/.test(document.querySelector('.task-panel .vp-head .ttl')?.textContent || ''), null, { timeout: 30000 }).catch(() => null);
  ok('沙箱左栏直接是这一课', /找瓶颈/.test(await c.locator('.task-panel .vp-head .ttl').first().innerText().catch(() => '')));
  await c.locator('.task-panel .el-tabs__item:has-text("目标与作答")').click(); await wait(c, 800);
  await c.locator('.task-panel .goal[data-rule="q_bn"] button:has-text("在图上点选")').click(); await wait(c, 800);
  const pk = await c.evaluate(() => !!window.__vfEd.pick && window.__vfEd.pick.prompt);
  ok('点选题设置了 ed.pick（外壳显示提示条）', !!pk, pk);
  await c.screenshot({ path: `${OUT}/t06_course_pick.png` });
  // 外壳的"点设备"交给 onPick；这里直接调用它，等价于在图上点了 M3
  await c.evaluate(() => { const f = window.__vfEd.pick?.onPick; window.__vfEd.pick = null; f?.('M3'); }); await wait(c, 1200);
  ok('点选结果保存', /已选：\s*M3/.test(await c.locator('.task-panel .goal[data-rule="q_bn"]').innerText()));
  await c.locator('.task-panel .goal[data-rule="q_cap"] .el-radio').nth(0).click(); await wait(c, 400);
  await c.locator('.task-panel .goal[data-rule="q_fix"] .el-radio').nth(2).click(); await wait(c, 800);
  await c.locator('.task-panel button:has-text("提交评分")').click(); await wait(c, 6000);
  const sc = await c.locator('.task-panel .vp-score').first().innerText().catch(() => '');
  ok('找瓶颈课提交 = 满分', /^100/.test(sc.trim()), sc);
  await c.screenshot({ path: `${OUT}/t07_course_score.png` });

  // ---------- 老师旁观 ----------
  const q = await page(T);
  await c.close();
  await q.goto(B + '/teach', { waitUntil: 'networkidle' });
  await q.waitForSelector('.el-tabs__item:has-text("教学控制台")', { timeout: 30000 }).catch(() => null);
  ok('老师的教学页有控制台', (await q.locator('.el-tabs__item:has-text("教学控制台")').count()) === 1);
  // 走外壳约定：设置 ed.teach.open（等同于控制台里点"旁观"），外壳负责跳到沙箱并只读打开
  await q.evaluate(([pid]) => { const ed = window.__vfEd; ed.teach = { ...(ed.teach || {}), student: 'ui_stu1', open: { pid, readonly: true, n: Date.now() } }; }, [sb]);
  await wait(q, 9000);
  ok('老师旁观：跳到学生沙箱', q.url().includes(encodeURIComponent(sb)), q.url());
  ok('老师旁观：只读标记', (await q.locator('.ed-chip:has-text("只读")').count()) === 1);
  ok('老师旁观：运行按钮禁用', !(await q.locator('.ed-bar .rb button').nth(1).isEnabled()));
  ok('老师旁观：左栏是这个学生的任务（只读横幅）', (await q.locator('.task-panel .banner.watch').count()) === 1, await q.locator('.task-panel .banner.watch').innerText().catch(() => ''));
  { // 后端也只读（T14）：不接管就写学生沙箱 → 403
    const r = await fetch(B + `/api/p/${encodeURIComponent(sb)}/cells/CELL1/program/download`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + T }, body: JSON.stringify({ program: { lang: 'ST', source: 'PROGRAM X\nEND_PROGRAM' } }) });
    ok('老师旁观：后端拒绝写学生沙箱', r.status === 403, r.status);
  }
  await q.screenshot({ path: `${OUT}/t04_teacher_watch.png` });

  // ---------- SOP 跟随（管理员在普通工厂） ----------
  const r = await page(admin);
  await r.goto(B + '/p/foundry-housing/workbench', { waitUntil: 'networkidle' }); await wait(r, 8000);
  const blk = (await api(admin, 'GET', '/api/p/foundry-housing/model')).model.blocks.find((x) => x.type !== 'transporter').id;
  const cam0 = await r.evaluate(() => JSON.stringify(window.__vfEd.camera));
  await r.evaluate(([bid]) => { window.__vfEd.sop = { id: 't', name: '测试', index: 0, total: 1, playing: false, n: 1,
    step: { title: '测试', target: { block: bid }, camera: { mode: 'orbit', pos: [5, 12, 5], look: [20, 0, 15] } } }; }, [blk]);
  await wait(r, 1500);
  const cam1 = await r.evaluate(() => JSON.parse(JSON.stringify(window.__vfEd.camera)));
  ok('SOP 一步：相机移到记录的视角', cam1 && Math.abs(cam1.pos[1] - 12) < 0.5 && Math.abs(cam1.look[0] - 20) < 0.5, cam0 + ' → ' + JSON.stringify(cam1));
  const shot = await r.evaluate(() => (window.__vfEd.capture?.() || '').slice(0, 22));
  ok('ed.capture() 返回 PNG', shot.startsWith('data:image/png'), shot);
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
