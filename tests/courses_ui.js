// 4.6 课程界面走查：学生课程页（卡片默认收起、筛选搜索、详情抽屉、这一课）、老师在编辑器里做一门课（PLC + 测验 + 产线）→ 预览 → 发布到班级、
// 客户端离线做测验得本机分 → 交给老师服务器重评一致、改过的课程包被拒、AI 评分建议（假模型）→ 老师确认。截图（5.0.1 起只有浅色）。
// 需要：学校服务器 VF_URL（serve，带 VF_LLM_FAKE=1）+ 客户端 VF_CLIENT_URL（desktop --home VF_CLIENT_HOME，还没登录过）。VF_PY = 能跑 vfactory 的 python（改包用）。
//   node tests/courses_ui.js
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const SV = process.env.VF_URL || 'http://127.0.0.1:8800';
const CL = process.env.VF_CLIENT_URL || 'http://127.0.0.1:8831';
const HOME = process.env.VF_CLIENT_HOME;
const PY = process.env.VF_PY || 'python';
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_courses');
const STAMP = new Date().toISOString().slice(5, 19).replace(/[-:T]/g, '');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 260)); };
const api = async (base, tok, method, url, body, extra = {}) => {
  const r = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), ...extra }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  try { return Object.assign(JSON.parse(t), r.ok ? {} : { _status: r.status }); } catch { return { _status: r.status, _text: t }; }
};
const login = async (u, p) => (await api(SV, '', 'POST', '/api/login', { username: u, password: p })).token;
const ticket = async () => {
  const run = JSON.parse(fs.readFileSync(path.join(HOME, 'run.json'), 'utf-8'));
  return (await api(CL, '', 'POST', '/api/desktop/ticket', null, { 'x-vf-key': run.key })).token;
};
const wait = (p, ms) => p.waitForTimeout(ms);
// Element Plus 的 el-input 把 data-k 放在 <input> 上，el-input-number 放在外层：两种都认
const I = (k) => `input[data-k="${k}"], [data-k="${k}"] input`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const admin = await login('admin', 'honey123');
  const users = (await api(SV, admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('ku_teacher')) await api(SV, admin, 'POST', '/api/admin/users', { username: 'ku_teacher', name: '孔老师', role: 'teacher', password: 'teach123' });
  const T = await login('ku_teacher', 'teach123');
  const stu = `ku${STAMP.slice(-6)}`;
  const cls = await api(SV, T, 'POST', '/api/teach/classes', { name: `课程界面班 ${STAMP}` });
  await api(SV, T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `${stu},赵同学`, default_password: '123456' });
  await api(SV, T, 'POST', '/api/teach/courses/machining/publish', { class_id: cls.id, open_all: false });
  await api(SV, T, 'POST', '/api/teach/courses/plc_basics/publish', { class_id: cls.id, open_all: false });
  await api(SV, T, 'POST', '/api/teach/courses/mes_intro/publish', { class_id: cls.id, open_all: false });     // M 的 MES 入门（kind=mes）

  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const br = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const errs = [];
  const page = async (tok, w = 1680, h = 1000, dark = false, base = SV) => {
    const ctx = await br.newContext({ locale: 'zh-CN', viewport: { width: w, height: h }, acceptDownloads: true });
    await ctx.addInitScript(([t]) => {
      if (t) localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN');
      localStorage.setItem('vf_teach_tour', '1'); localStorage.setItem('vf_guide_off', '1'); sessionStorage.setItem('vf_pw_later', '1');
      localStorage.setItem('vf_welcome_off', '1');
    }, [tok]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(`pageerror ${e.message.slice(0, 200)}`));
    p.on('console', (m) => { if (m.type() === 'error' && !/favicon|40[0-9]|Failed to load resource/.test(m.text())) errs.push('console ' + m.text().slice(0, 200)); });
    return p;
  };
  const shot = async (p, n) => p.screenshot({ path: `${OUT}/${n}.png` });

  // ================= 老师：做一门课 =================
  const t = await page(T);
  await t.goto(SV + '/courses', { waitUntil: 'networkidle' }); await wait(t, 1500);
  ok('老师菜单有"课程"和"教学"两项', (await t.locator('[data-k="menu-courses"]').count()) === 1 && (await t.locator('[data-k="menu-teach"]').count()) === 1);
  ok('老师的"课程"页：课程库里有内置课程', (await t.locator('[data-k="library"] .cc').count()) >= 3, await t.locator('[data-k="library"] .cc').count());
  await shot(t, 'k01_teacher_studio');
  await t.locator('[data-k="new-course"]').click(); await wait(t, 500);
  const cname = `PLC 入门小课 ${STAMP}`;
  await t.locator('.el-message-box input').fill(cname);
  await t.locator('.el-message-box button:has-text("建好去编辑")').click();
  await t.waitForSelector('[data-k="course-editor"]', { timeout: 15000 }).catch(() => null);
  await wait(t, 1200);
  ok('新建课程后进到编辑器', (await t.locator('[data-k="course-editor"]').count()) === 1);
  await shot(t, 'k02_editor_meta');
  const addLesson = async (tpl) => {
    await t.locator('[data-k="add-lesson-0"]').click(); await wait(t, 300);
    await t.locator(`.el-dropdown-menu__item[data-tpl="${tpl}"]:visible`).click(); await wait(t, 600);
  };
  // 1) PLC 实训：场景默认第一个，评分项全选，加一条自加检查
  await addLesson('plc');
  await t.locator(I('ce-l-title')).fill('电机启停（老师版）');
  await t.locator('.ltabs .el-tabs__item:has-text("场景与评分")').click(); await wait(t, 500);
  await t.locator('[data-k="ce-add-check"]').click(); await wait(t, 400);
  ok('PLC 课：场景评分项可以勾选、有"自加检查"', (await t.locator('.rubric .el-checkbox').count()) >= 2 && (await t.locator('.xt-row').count()) === 1);
  await shot(t, 'k03_editor_plc');
  // 2) 测验：一道单选 + 一道填数
  await addLesson('quiz');
  await t.locator(I('ce-l-title')).fill('安全小测');
  await t.locator('.ltabs .el-tabs__item:has-text("题目")').click(); await wait(t, 400);
  const q1 = t.locator('.rl').nth(0);
  await q1.locator(I('rule-label')).fill('急停按钮一般接成');
  await q1.locator(I('choice-0')).fill('常开触点');
  await q1.locator(I('choice-1')).fill('常闭触点');
  await q1.locator(I('choice-2')).fill('都可以');
  await q1.locator('.choices-ed .el-radio').nth(1).click();
  await q1.locator('textarea[data-k="rule-explain"], [data-k="rule-explain"] textarea').first().fill('急停要失效偏向安全：线断了也等于按下，所以接常闭触点。');     // 4.6.2 解析
  await t.locator('[data-k="ce-add-rule"]').click(); await wait(t, 300);
  await t.locator('.el-dropdown-menu__item[data-rt="number"]:visible').click(); await wait(t, 400);
  const q2 = t.locator('.rl').nth(1);
  await q2.locator(I('rule-label')).fill('节拍 60 秒的机床每小时最多加工几件');
  await q2.locator(I('num-answer')).fill('60'); await q2.locator(I('num-answer')).blur();
  await shot(t, 'k04_editor_quiz');
  // 3) 产线任务：默认工厂 + 一条指标
  await addLesson('line');
  await t.locator(I('ce-l-title')).fill('两台机床串联');
  await t.locator('.ltabs .el-tabs__item:has-text("工厂")').click(); await wait(t, 400);
  await shot(t, 'k05_editor_line');
  await t.locator('.ltabs .el-tabs__item:has-text("目标与题目")').click(); await wait(t, 400);
  await shot(t, 'k05b_editor_line_goals');
  await t.locator('[data-k="ce-save"]').click(); await wait(t, 1500);
  const draft = (await api(SV, T, 'GET', '/api/teach/authoring')).find((c) => c.name === cname);
  const cid = draft.id;
  // 4.6.1 出题检查：两课任务书是空的（错误）、测验两题合计 20 分、产线目标没名称、产线课没约束；后台试运行起始模型
  const d0 = await api(SV, T, 'GET', `/api/teach/authoring/${cid}`);
  const [plcId, quizId, lineId] = d0.course.chapters[0].lessons.map((l) => l.id);
  await t.waitForSelector('[data-k="ce-checks"]', { timeout: 8000 }).catch(() => null);
  const CK = '[data-k="ce-checks"]';
  const nCode = async (lid, code, lvl = '') => t.locator(`${CK} .ck-group[data-lesson="${lid}"] .ck-item${lvl ? '.lv-' + lvl : ''}[data-code="${code}"]`).count();
  ok('出题检查面板：测验和产线课"任务书是空的"是错误（PLC 课用场景的任务书，不报）', (await nCode(quizId, 'brief', 'error')) === 1 && (await nCode(lineId, 'brief', 'error')) === 1
    && (await nCode(plcId, 'brief')) === 0, await t.locator(CK).innerText().catch(() => '').then((x) => x.slice(0, 200)));
  ok('出题检查面板：测验合计 20 分（提醒，带"按比例凑成 100"）、产线目标没名称（带"用作名称"）、产线课没约束',
    (await nCode(quizId, 'weights', 'warn')) === 1 && (await t.locator(`${CK} .ck-group[data-lesson="${quizId}"] [data-k="fix-weights"]`).count()) === 1
    && (await nCode(lineId, 'label', 'warn')) === 1 && (await t.locator(`${CK} .ck-group[data-lesson="${lineId}"] [data-k="fix-label"]`).count()) === 1
    && (await nCode(lineId, 'unconstrained', 'warn')) === 1);
  ok('有错误时"发布"按钮不能点，"按学生预览"可以', await t.locator('[data-k="ce-publish"]').isDisabled() && !(await t.locator('[data-k="ce-preview"]').isDisabled()));
  const pub0 = await api(SV, T, 'POST', `/api/teach/authoring/${cid}/publish`, {});
  ok('有错误时服务器也不让发布', pub0._status === 400 && /任务书/.test(pub0.detail || ''), pub0.detail);
  for (let i = 0; i < 90 && ((await t.locator('[data-k="ck-running"]').count()) || !(await nCode(lineId, 'baseline'))); i++) await wait(t, 1000);
  const bTxt = await t.locator(`${CK} .ck-group[data-lesson="${lineId}"] .ck-item[data-code="baseline"]`).innerText().catch(() => '');
  ok('试运行（后台）：产线课"学生什么都不改就能得 100 分：合格品 8 小时约 … 件，目标 ≥ 100"，下面有起始模型的结果表',
    /学生什么都不改就能得 100 分/.test(bTxt) && /合格品 8 小时约 \d+ 件，目标 ≥ 100/.test(bTxt) && (await t.locator(`${CK} .ck-group[data-lesson="${lineId}"] [data-k="ck-baseline"]`).count()) === 1, bTxt);
  ok('试运行：PLC 课不写程序的分数、场景自带参考程序的分数', (await t.locator(`${CK} .ck-group[data-lesson="${plcId}"] [data-k="ck-ref-score"]`).count()) === 1,
    await t.locator(`${CK} .ck-group[data-lesson="${plcId}"]`).innerText().catch(() => ''));
  await t.locator(`${CK} .ck-group[data-lesson="${lineId}"]`).scrollIntoViewIfNeeded().catch(() => null);
  await shot(t, 'k05c_checks');
  await t.locator(CK).evaluate((e) => { e.scrollTop = 0; }).catch(() => null); await wait(t, 200);
  await shot(t, 'k05d_checks_top');
  await t.locator(`${CK} .ck-group[data-lesson="${quizId}"] [data-k="fix-weights"]`).click(); await wait(t, 1500);
  const dq = await api(SV, T, 'GET', `/api/teach/authoring/${cid}`);
  const qw = dq.course.chapters[0].lessons[1].rules.map((r) => r.weight);
  ok('点"按比例凑成 100"：测验两题变成 50 + 50，提醒消失', qw.join('+') === '50+50' && (await nCode(quizId, 'weights')) === 0, qw.join('+'));
  // 写任务书（两课）
  for (const lid of [quizId, lineId]) {
    await t.locator(`[data-k="course-editor"] .tn.ls[data-lesson="${lid}"]`).click(); await wait(t, 400);
    await t.locator('.ltabs .el-tabs__item:has-text("基本")').click(); await wait(t, 300);
    await t.locator('[data-k="ce-brief"] textarea, textarea[data-k="ce-brief"]').first().fill(lid === quizId ? '答两道安全小题。' : '### 任务\n两台机床串联：8 小时内做出至少 100 件合格品。');
  }
  await t.locator(`[data-k="course-editor"] .tn.ls[data-lesson="${lineId}"]`).click(); await wait(t, 300);
  await t.locator('.ltabs .el-tabs__item:has-text("目标与题目")').click(); await wait(t, 300);
  await t.locator('[data-k="ce-save"]').click(); await wait(t, 1800);
  ok('编辑器里每个目标下面写着"学生看到：8 小时合格品 ≥ 100 件"', /学生看到：8 小时合格品 ≥ 100 件/.test(await t.locator('[data-k="rule-goal"]').first().innerText().catch(() => '')),
    await t.locator('[data-k="rule-goal"]').first().innerText().catch(() => ''));
  ok('写好任务书以后：没有错误了，"发布"可以点', (await t.locator(`${CK} .ck-item.lv-error`).count()) === 0 && !(await t.locator('[data-k="ce-publish"]').isDisabled()));
  const dv = await api(SV, T, 'GET', `/api/teach/authoring/${cid}`);
  const kinds = dv.course.chapters[0].lessons.map((l) => l.kind).join(',');
  ok('编辑器保存：三课（PLC + 测验 + 产线），没有错误', kinds === 'cell,quiz,plant' && dv.errors === 0, kinds + ' ' + JSON.stringify(dv.issues).slice(0, 200));
  const quizL = dv.course.chapters[0].lessons[1];
  ok('测验题按编辑器里设的保存（单选答案 = 第 2 项，填数 = 60）', quizL.rules[0].answer === 1 && quizL.rules[1].answer === 60 && quizL.rules[1].qtype === 'number', JSON.stringify(quizL.rules));
  ok('4.6.2 编辑器里写的解析存进题目', quizL.rules[0].explain === '急停要失效偏向安全：线断了也等于按下，所以接常闭触点。', quizL.rules[0].explain);
  const plcL = dv.course.chapters[0].lessons[0];
  ok('PLC 课的自加检查存成声明式测试步骤 + 评分项', (plcL.tests || []).some((s) => s.check) && (plcL.extra_rules || []).length === 1, JSON.stringify(plcL.tests));
  // 预览：按学生的样子做测验
  await t.locator('[data-k="ce-preview"]').click();
  await t.waitForSelector('[data-k="course-preview"] .lesson', { timeout: 20000 }).catch(() => null); await wait(t, 800);
  ok('按学生预览：三课', (await t.locator('[data-k="course-preview"] .lesson').count()) === 3);
  await t.locator('[data-k="course-preview"] .lesson').nth(1).click(); await wait(t, 1800);
  await t.locator('.task-panel .goal').nth(0).locator('.el-radio').nth(1).click(); await wait(t, 500);
  await t.locator('.task-panel [data-k="q-number"] input').fill('60'); await t.locator('.task-panel [data-k="q-number"] input').blur(); await wait(t, 800);
  await t.locator('.task-panel [data-k="submit-score"]').click(); await wait(t, 3000);
  const pvScore = await t.locator('.task-panel .vp-score').first().innerText().catch(() => '');
  ok('预览里老师试做测验 = 100', /^100/.test(pvScore.trim()), pvScore);
  await shot(t, 'k06_preview');
  // 产线课（目标没写名称）：学生看到的标题是生成的说明，介绍说的是"你的方案（模型和参数）"，不是"程序"
  await t.locator('[data-k="course-preview"] .lesson').nth(2).click(); await wait(t, 1800);
  await t.locator('.task-panel .el-tabs__item:has-text("目标与作答")').click(); await wait(t, 700);
  const gTitle = await t.locator('.task-panel .goal [data-k="goal-title"]').first().innerText().catch(() => '');
  const gIntro = await t.locator('.task-panel [data-k="goals-intro"]').innerText().catch(() => '');
  ok('学生的"目标与作答"：目标标题是"8 小时合格品 ≥ 100 件"（老师没写名称）', /8 小时合格品 ≥ 100 件/.test(gTitle), gTitle);
  ok('产线课的说明是"你的方案（模型和参数）"，没有"你的程序"', /你的方案（模型和参数）/.test(gIntro) && !/你的程序/.test(await t.locator('.task-panel').first().innerText().catch(() => '')), gIntro);
  ok('预览里有"存为参考做法"', (await t.locator('.task-panel [data-k="save-reference"]').count()) === 1);
  await shot(t, 'k06b_student_goals');
  await t.locator('[data-k="course-preview"] button:has-text("回到编辑器")').click(); await wait(t, 1200);
  await t.locator('[data-k="ce-publish"]').click(); await wait(t, 500);
  await t.locator('.el-message-box button:has-text("发布")').click(); await wait(t, 2500);
  ok('发布 v1', /已发布 v1/.test(await t.locator('[data-k="ce-status"]').innerText().catch(() => '')), await t.locator('[data-k="ce-status"]').innerText().catch(() => ''));
  await t.locator('.ce-top button:has-text("课程")').first().click(); await wait(t, 1500);
  await t.locator(`[data-k="my-courses"] .cc[data-course="${cid}"] button:has-text("发布到班级")`).click(); await wait(t, 1200);
  await t.locator('.course-publish .cp-foot .el-select').first().click(); await wait(t, 400);
  await t.locator(`.el-select-dropdown__item:visible:has-text("课程界面班 ${STAMP}")`).click(); await wait(t, 300);
  // 4.6.2 正确答案"截止后显示"，截止时间在以后：学生交了也先看不到
  const dueIn = t.locator('.course-publish .cp-foot .el-date-editor input').first();
  await dueIn.click(); await dueIn.fill('2099-01-01 08:00'); await dueIn.press('Enter'); await wait(t, 300);
  await t.locator('.course-publish .cp-foot').click({ position: { x: 5, y: 5 } }).catch(() => null);
  await t.locator('.course-publish .cp-foot .el-select').nth(1).click(); await wait(t, 400);
  await t.locator('.el-select-dropdown__item:visible:has-text("截止后显示")').click(); await wait(t, 300);
  ok('4.6.2 发布课程：可以选正确答案"截止后显示"，下面说明什么时候显示', /截止（2099-01-01 08:00）以后/.test(await t.locator('[data-k="cp-reveal-hint"]').innerText().catch(() => '')),
    await t.locator('[data-k="cp-reveal-hint"]').innerText().catch(() => ''));
  await shot(t, 'k07_publish_dialog');
  await t.locator('.course-publish .cp-foot button:has-text("发布课程")').click(); await wait(t, 2000);
  const asg = (await api(SV, T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).filter((a) => a.course === cid);
  // MES 入门（M 的课）在编辑器里：复制一份来改 → 课的类型"MES 操作任务"、MES 检查项
  await t.goto(SV + '/courses', { waitUntil: 'networkidle' }); await wait(t, 1200);
  await t.locator('[data-k="library"] .cc[data-course="mes_intro"] button:has-text("复制一份来改")').click();
  await t.waitForSelector('[data-k="course-editor"] .tn.ls', { timeout: 15000 }).catch(() => null); await wait(t, 800);
  await t.locator('[data-k="course-editor"] .tn.ls').first().click(); await wait(t, 500);
  await t.locator('.ltabs .el-tabs__item:has-text("MES 检查")').click(); await wait(t, 500);
  ok('MES 入门在编辑器里：类型"MES 操作任务"、MES 检查项可编辑', /MES 操作任务/.test(await t.locator('.ce-form .lh').innerText().catch(() => ''))
    && (await t.locator('.ce-form .rl').count()) >= 2 && (await t.locator('[data-k="course-editor"] .tn.ls').count()) === 4);
  await shot(t, 'k08_editor_mes');
  ok('发布到班级：三课都成了作业', asg.length === 3, asg.length);
  ok('4.6.2 每一课：截止 2099-01-01 08:00、截止后显示正确答案', asg.every((a) => a.reveal === 'due' && a.due === '2099-01-01 08:00'), asg.map((a) => `${a.reveal} ${a.due}`).join(' | '));
  const quizAid = asg.find((a) => a.lesson === quizL.id).id;

  // ================= 学生（网页）：课程卡片 =================
  const S = await login(stu, '123456');
  for (const [w, h, dark] of [[1280, 800, false], [1680, 1000, false], [2560, 1300, false]]) {   // 5.0.1 起只有浅色
    const p = await page(S, w, h, dark);
    await p.goto(SV + '/courses', { waitUntil: 'networkidle' });
    await p.waitForSelector('[data-k="course-grid"] .course-card', { timeout: 30000 }).catch(() => null); await wait(p, 800);
    const tag = `${w}${dark ? '_dark' : ''}`;
    const cards = await p.locator('[data-k="course-grid"] .course-card').count();
    if (w === 1680 && !dark) {
      ok('学生菜单是"课程"（不是"教学"）', (await p.locator('.el-menu-item:has-text("课程")').count()) === 1 && (await p.locator('.el-menu-item:has-text("教学")').count()) === 0);
      ok('学生课程页：四门课的卡片，默认收起（看不到课的列表）', cards === 4 && (await p.locator('[data-k="course-grid"] .lesson').count()) === 0, cards);
      ok('MES 入门的卡片：类型是"MES 操作任务"、有封面', /MES 操作任务/.test(await p.locator('.course-card[data-course="mes_intro"] .cc-kinds').innerText().catch(() => ''))
        && (await p.locator('.course-card[data-course="mes_intro"] .cc-cover img').count()) === 1);
      ok('卡片有封面、进度和下一课', (await p.locator(`.course-card[data-course="${cid}"] .cc-cover img`).count()) === 1 && /安全小测|电机启停/.test(await p.locator(`.course-card[data-course="${cid}"] .cc-next`).innerText()));
      await p.locator(I('course-search')).fill('串联'); await wait(p, 400);
      ok('搜索课名：只剩这门课', (await p.locator('[data-k="course-grid"] .course-card').count()) === 1);
      await p.locator(I('course-search')).fill(''); await wait(p, 300);
      await p.locator('[data-k="course-filter"] label:has-text("已完成")').click(); await wait(p, 400);
      ok('筛选"已完成"：还没有学完的课（空状态）', (await p.locator('[data-k="course-empty"]').count()) === 1);
      await shot(p, 'k10_student_filter_done');
      await p.locator('[data-k="course-filter"] label:has-text("全部")').click(); await wait(p, 400);
    }
    const sw = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    ok(`学生课程页 ${tag}：卡片铺开、没有横向滚动`, cards >= 4 && sw[0] <= sw[1] + 1, `${cards} 张卡片，宽 ${sw.join('/')}`);
    await shot(p, `k11_student_courses_${tag}`);
    await p.locator(`.course-card[data-course="${cid}"]`).click(); await wait(p, 900);
    const det = p.locator(`[data-k="course-detail"].course[data-course="${cid}"]`);
    if (w === 1680 && !dark) {
      const st = await det.locator('.lesson').evaluateAll((els) => els.map((e) => e.className));
      ok('课程详情：章节里三课，第一课可做、后面按顺序锁定', st.length === 3 && /open/.test(st[0]) && /locked/.test(st[1]), st.join(' | '));
    }
    await shot(p, `k12_student_detail_${tag}`);
    if (w === 1680) {
      await det.locator('.lesson').nth(0).click();
      await p.waitForSelector('.task-panel [data-k="lesson-detail"] .tp-tabs', { timeout: 30000 }).catch(() => null); await wait(p, 600);
      const nc = await p.locator('.task-panel .course').count();
      ok(`这一课：左边只有这门课的章节，有"全部课程"${dark ? '（深色）' : ''}`, nc === 1 && (await p.locator('[data-k="back-home"]').count()) === 1 && /\?l=\d+/.test(p.url()), `${nc} 门 ${p.url()}`);
      await shot(p, `k13_student_lesson_${tag}`);
      if (!dark) {
        await p.reload({ waitUntil: 'networkidle' });
        await p.waitForSelector('[data-k="back-home"]', { timeout: 30000 }).catch(() => null);
        ok('刷新后还是这一课', (await p.locator('[data-k="back-home"]').count()) === 1);
        await p.locator('[data-k="back-home"]').click();
        await p.waitForSelector('[data-k="course-grid"]', { timeout: 30000 }).catch(() => null);
        ok('"全部课程"回到卡片页', (await p.locator('[data-k="course-grid"]').count()) === 1);
        ok('"学校作业"是单独一块', (await p.locator('[data-k="homework"]').count()) === 1);
      }
    }
    await p.context().close();
  }

  // ================= 学生（网页）：课程卡片上的按钮 = 开始学习 / 继续学习 / 复习（5.0.1） =================
  {
    const p = await page(S, 1680, 1000);
    const my = await api(SV, S, 'GET', '/api/teach/my/courses');
    const mc = (my.courses || []).find((x) => x.course === cid);
    const first = mc.chapters[0].lessons[0];
    await p.goto(SV + '/courses', { waitUntil: 'networkidle' });
    await p.waitForSelector(`.course-card[data-course="${cid}"] [data-k="card-continue"]`, { timeout: 30000 }).catch(() => null); await wait(p, 600);
    const btn = p.locator(`.course-card[data-course="${cid}"] [data-k="card-continue"]`);
    ok('卡片按钮（没有进度）：「开始学习」→ 第一课', (await btn.getAttribute('data-mode')) === 'start' && /开始学习/.test(await btn.innerText()) && Number(await btn.getAttribute('data-aid')) === first.aid,
      `${await btn.getAttribute('data-mode')} ${await btn.innerText().catch(() => '')} ${await btn.getAttribute('data-aid')} / ${first.aid}`);
    await shot(p, 'k14_card_start');
    await btn.click();
    // 和点「开始这一课」一样：这一课有跟随教程时先问「跟着教程做 / 自己做」
    await p.waitForSelector('.tour-ask', { timeout: 8000 }).catch(() => null);
    if (await p.locator('.tour-ask').count()) { await shot(p, 'k14b_card_start_ask'); await p.locator('.tour-ask button:has-text("自己做")').click(); }
    await p.waitForURL(/\/p\/sb-[^/]+\/workbench/, { timeout: 60000 }).catch(() => null); await wait(p, 1500);
    const sb1 = (await api(SV, S, 'GET', '/api/teach/my/courses')).courses.find((x) => x.course === cid).chapters[0].lessons[0];
    ok('「开始学习」= 打开第一课并开始（和「开始这一课」一样：进沙箱、到工作台）', /\/p\/sb-[^/]+-\d+\/workbench/.test(p.url()) && new RegExp(`-${first.aid}/workbench`).test(p.url()) && sb1.sandbox !== 'none',
      `${p.url()} sandbox=${sb1.sandbox}`);
    // 有进度：回到课程页 → 「继续学习」→ 正在做的那一课，同样直接开始
    await p.goto(SV + '/courses', { waitUntil: 'networkidle' });
    await p.waitForSelector(`.course-card[data-course="${cid}"] [data-k="card-continue"]`, { timeout: 30000 }).catch(() => null); await wait(p, 600);
    ok('卡片按钮（有进度）：「继续学习」→ 正在做的那一课', (await btn.getAttribute('data-mode')) === 'continue' && /继续学习/.test(await btn.innerText()) && Number(await btn.getAttribute('data-aid')) === first.aid,
      `${await btn.getAttribute('data-mode')} ${await btn.innerText().catch(() => '')} ${await btn.getAttribute('data-aid')}`);
    await shot(p, 'k15_card_continue');
    await btn.click();
    await p.waitForURL(/\/p\/sb-[^/]+\/workbench/, { timeout: 60000 }).catch(() => null); await wait(p, 1000);
    ok('「继续学习」= 打开那一课并直接进沙箱', new RegExp(`-${first.aid}/workbench`).test(p.url()), p.url());
    // 全部学完（接口返回改成全部完成）：「复习」→ 打开第一课，不进沙箱
    await p.route('**/api/teach/my/courses', async (route) => {
      const r = await route.fetch(); const j = await r.json();
      for (const c of j.courses || []) if (c.course === cid) { for (const ch of c.chapters) for (const l of ch.lessons) { l.state = 'done'; l.locked = false; l.best = 100; } c.done = c.total; c.next = null; }
      await route.fulfill({ response: r, json: j });
    });
    await p.goto(SV + '/courses', { waitUntil: 'networkidle' });
    await p.locator('[data-k="course-filter"] label:has-text("全部")').click().catch(() => null);
    await p.waitForSelector(`.course-card[data-course="${cid}"] [data-k="card-continue"]`, { timeout: 30000 }).catch(() => null); await wait(p, 600);
    ok('卡片按钮（全部学完）：「复习」', (await btn.getAttribute('data-mode')) === 'review' && /复习/.test(await btn.innerText()), `${await btn.getAttribute('data-mode')} ${await btn.innerText().catch(() => '')}`);
    await shot(p, 'k16_card_review');
    await btn.click();
    await p.waitForSelector('.task-panel [data-k="lesson-detail"]', { timeout: 30000 }).catch(() => null); await wait(p, 800);
    ok('「复习」= 打开第一课（课程页里，不进沙箱）', new RegExp(`[?&]l=${first.aid}\\b`).test(p.url()) && !/\/workbench/.test(p.url()), p.url());
    await p.context().close();
  }

  // ================= 学生（客户端）：离线做测验 → 本机分 → 交给老师 → 服务器重评一致 =================
  // 老师把这门课全部开放（测验在第 2 课）
  await api(SV, T, 'PATCH', `/api/teach/courses/${cid}/classes/${cls.id}`, { open_all: true });
  const c = await page('', 1500, 920, false, CL);
  await c.goto(`${CL}/#dt=${await ticket()}`, { waitUntil: 'networkidle' }); await wait(c, 800);
  const inputs = c.locator('.box input');
  await inputs.nth(0).fill(SV); await inputs.nth(1).fill(stu); await inputs.nth(2).fill('123456');
  await c.locator('.box button:has-text("登录")').click();
  await c.waitForSelector('input[data-k="pw-new"]', { timeout: 20000 }).catch(() => null);
  if (await c.locator('input[data-k="pw-new"]').count()) {
    await c.locator('input[data-k="pw-new"]').fill('stu12345'); await c.locator('input[data-k="pw-new2"]').fill('stu12345');
    await c.locator('[data-k="pw-save"]').click();
  }
  await c.waitForURL(/\/(teach|welcome|courses)/, { timeout: 30000 }).catch(() => null);
  await c.goto(`${CL}/courses`, { waitUntil: 'networkidle' }); await wait(c, 2500);
  const tok = await c.evaluate(() => localStorage.getItem('vf_token'));
  await c.waitForSelector(`.sw-item[data-raid="${quizAid}"]`, { timeout: 20000 }).catch(() => null);
  ok('客户端"课程"：学校作业里有老师做的测验', (await c.locator(`.sw-item[data-raid="${quizAid}"]`).count()) === 1);
  await shot(c, 'k20_client_courses');
  await c.locator(`.sw-item[data-raid="${quizAid}"] button`).click();
  await c.waitForSelector('.task-panel [data-k="quiz-tag"]', { timeout: 30000 }).catch(() => null); await wait(c, 1000);
  const inst = await api(CL, tok, 'GET', '/api/client/courses');
  const me = (inst.courses || []).find((x) => x.id === cid);
  ok('"在本机做"：签名的课程包装到本机、验过', me && me.ok && me.version === 1 && inst.keys.length >= 1, JSON.stringify(inst).slice(0, 220));
  // 断开学校服务器（离线）：本机照样判分
  await api(CL, tok, 'POST', '/api/client/school/logout', {});
  await c.locator('.task-panel .goal').nth(0).locator('.el-radio').nth(1).click(); await wait(c, 400);
  await c.locator('.task-panel [data-k="q-number"] input').fill('59'); await c.locator('.task-panel [data-k="q-number"] input').blur(); await wait(c, 800);
  await c.locator('.task-panel .acts button:has-text("本机评分")').click();
  await c.waitForSelector('.task-panel .vp-score', { timeout: 30000 }).catch(() => null); await wait(c, 800);
  const local = await c.locator('.task-panel .vp-score').first().innerText().catch(() => '');
  ok('离线：本机马上判分（一题对一题错 = 50，标着本机预估分）', /^50/.test(local.trim()) && /本机预估分/.test(await c.locator('.task-panel .tp-tabs').innerText()), local);
  await shot(c, 'k21_client_quiz_local');
  ok('4.6.2 本机预估分：有"你的答案"，没有正确答案和解析，说明交给老师以后按老师的设置显示',
    (await c.locator('.task-panel .sub [data-k="reveal-note"][data-state="local"]').count()) === 1 && (await c.locator('.task-panel .sub [data-k="your-answer"]').count()) === 2
    && (await c.locator('.task-panel .sub [data-k="correct-answer"], .task-panel .sub [data-k="answer-explain"]').count()) === 0,
    await c.locator('.task-panel .sub').first().innerText().catch(() => ''));
  // 改过的课程包被拒：改分值并重算清单哈希（签名对不上）
  const pkgPath = path.join(HOME, 'data', 'client', 'courses', `${cid}.vfcourse`);
  const orig = fs.readFileSync(pkgPath);
  const tampered = path.join(OUT, 'tampered.vfcourse');
  const code = `import sys,zipfile,io,json,hashlib
z=zipfile.ZipFile(sys.argv[1]);f={n:z.read(n) for n in z.namelist()}
c=json.loads(f['course.json']);c['chapters'][0]['lessons'][1]['rules'][1]['weight']=5;f['course.json']=json.dumps(c,ensure_ascii=False).encode()
m=json.loads(f['manifest.json']);m['files']['course.json']=hashlib.sha256(f['course.json']).hexdigest()
m['content_sha256']=hashlib.sha256(''.join(k+':'+m['files'][k]+'\\n' for k in sorted(m['files'])).encode()).hexdigest()
f['manifest.json']=json.dumps(m,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
o=io.BytesIO();w=zipfile.ZipFile(o,'w');[w.writestr(k,v) for k,v in f.items()];w.close();open(sys.argv[2],'wb').write(o.getvalue())`;
  execFileSync(PY, ['-c', code, pkgPath, tampered]);
  const tb = fs.readFileSync(tampered);
  const r1 = await api(CL, tok, 'POST', '/api/client/courses/install', { data: tb.toString('base64') });
  ok('改过的课程包（改分值、重算哈希）装不上：签名不对', r1._status === 400 && /签名/.test(r1.detail || ''), r1.detail);
  fs.writeFileSync(pkgPath, tb);
  await wait(c, 300);
  const r2 = await api(CL, tok, 'GET', '/api/client/courses');
  const bad = (r2.courses || []).find((x) => x.id === cid);
  ok('本机的课程包被人改了：不加载，说明原因', bad && !bad.ok && /签名/.test(bad.error || ''), JSON.stringify(bad));
  fs.writeFileSync(pkgPath, orig);
  const r3 = await api(CL, tok, 'GET', '/api/client/courses');
  ok('换回原包：又能加载', ((r3.courses || []).find((x) => x.id === cid) || {}).ok);
  // 联网，交给老师：服务器用同一套规则重评
  const relog = await api(CL, tok, 'POST', '/api/client/school/login', { url: SV, username: stu, password: 'stu12345' });
  ok('重新连上学校服务器', relog.connected, JSON.stringify(relog).slice(0, 120));
  await c.locator('.task-panel .vp-head button[title="刷新"]').click(); await wait(c, 1500);
  await c.locator('.task-panel .acts button:has-text("提交给老师")').click();
  await c.waitForSelector('.school-res', { timeout: 60000 }).catch(() => null); await wait(c, 800);
  const sr = await c.locator('.school-res').innerText().catch(() => '');
  ok('交给老师：学校服务器重评 = 本机分（50 / 50）', /学校服务器评分/.test(sr) && /^\s*学校服务器评分[\s\S]*?50/.test(sr) && /本机预估分 50/.test(sr), sr.replace(/\n/g, ' '));
  const subs = await api(SV, T, 'GET', `/api/teach/assignments/${quizAid}/submissions?username=${stu}`);
  ok('服务器上的提交来源 = 客户端、分数 50', subs[0] && subs[0].source === 'client' && subs[0].score === 50, JSON.stringify(subs[0] || {}).slice(0, 160));
  await shot(c, 'k22_client_submitted');
  // 4.6.2 截止后显示：截止前学校那边的成绩里没有正确答案；老师把截止时间改到已经过去，刷新后显示正确答案和解析
  const schoolBox = c.locator('.task-panel [data-k="school-results"]');
  await schoolBox.waitFor({ timeout: 20000 }).catch(() => null);
  ok('4.6.2 截止前："老师那边的成绩"说明截止以后才显示，没有正确答案', (await schoolBox.locator('[data-k="reveal-note"][data-state="due"]').count()) >= 1
    && (await schoolBox.locator('[data-k="correct-answer"]').count()) === 0, (await schoolBox.innerText().catch(() => '')).replace(/\n/g, ' ').slice(0, 200));
  await api(SV, T, 'PATCH', `/api/teach/assignments/${quizAid}`, { due: '2020-01-01 08:00' });
  await c.locator('.task-panel .vp-head button[title="刷新"]').click(); await wait(c, 2500);
  await c.locator('.task-panel .el-tabs__item:has-text("成绩")').first().click().catch(() => null); await wait(c, 800);
  const sbTxt = (await schoolBox.innerText().catch(() => '')).replace(/\s+/g, ' ');
  ok('4.6.2 过了截止时间：学校那边的成绩里有正确答案和老师写的解析', (await schoolBox.locator('[data-k="correct-answer"]').count()) >= 1 && /急停要失效偏向安/.test(sbTxt), sbTxt.slice(0, 240));
  await schoolBox.locator('[data-k="answer-explain"]').first().scrollIntoViewIfNeeded().catch(() => null);
  await shot(c, 'k23_client_reveal');
  await c.context().close();

  // ================= 老师：AI 评分建议 → 确认 =================
  const q = await page(T, 1680, 1000);
  await q.goto(SV + '/teach', { waitUntil: 'networkidle' }); await wait(q, 1500);
  await q.locator('.teacher-console .vp-head .el-select').first().click(); await wait(q, 400);
  await q.locator('.el-select-dropdown__item:visible:has-text("安全小测")').first().click(); await wait(q, 2000);
  await q.locator(`.teacher-console .stu[data-user="${stu}"]`).click(); await wait(q, 800);
  await q.locator('.detail .el-tabs__item:has-text("提交与复核")').click(); await wait(q, 1000);
  await q.locator('.detail .sub').first().locator('[data-k="ai-suggest"]').click(); await wait(q, 2500);
  const box = q.locator('.detail .sub').first().locator('[data-k="ai-box"]');
  ok('AI 建议：每个评分项一条，标明"仅供参考"', (await box.locator('.ai-c').count()) === 2 && /仅供参考/.test(await box.innerText()), (await box.innerText()).replace(/\n/g, ' ').slice(0, 200));
  const before = await api(SV, T, 'GET', `/api/teach/assignments/${quizAid}/submissions?username=${stu}`);
  ok('只生成建议不改成绩', before[0].override_score === null && before[0].status === 'scored');
  await shot(q, 'k30_ai_suggest');
  const sug = Number(await box.locator('[data-k="ai-score"]').innerText());
  await box.locator('[data-k="ai-accept"]').click(); await wait(q, 500);
  await q.locator('.detail .sub').first().locator('input[placeholder="总评语"]').fill('（老师）思路对，填数题再算一遍');
  await q.locator('.detail .sub').first().locator('button:has-text("保存复核")').click(); await wait(q, 1500);
  const after = await api(SV, T, 'GET', `/api/teach/assignments/${quizAid}/submissions?username=${stu}`);
  ok('老师采用建议分并改了评语、点保存复核：才成为成绩', after[0].status === 'reviewed' && Math.abs(after[0].score - sug) < 0.01 && /老师/.test(after[0].comment)
    && Object.keys(after[0].rule_comments || {}).length === 2, JSON.stringify({ s: after[0].score, o: after[0].override_score, sug, c: after[0].comment }));
  // 给全班生成建议（批量，进度）
  await q.locator('[data-k="ai-all"]').click(); await wait(q, 400);
  await q.locator('.el-message-box button:has-text("开始")').click();
  await q.waitForFunction(() => /完成/.test(document.querySelector('[data-k="ai-job-text"]')?.textContent || ''), null, { timeout: 30000 }).catch(() => null);
  ok('给全班生成 AI 建议：有进度，跑完显示完成', /完成 1\/1/.test(await q.locator('[data-k="ai-job-text"]').innerText().catch(() => '')), await q.locator('[data-k="ai-job-text"]').innerText().catch(() => ''));
  await shot(q, 'k31_ai_batch');
  await q.context().close();

  ok('页面没有报错', errs.length === 0, errs.slice(0, 5).join(' | '));
  const badList = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badList.length}/${res.length} 通过` + (badList.length ? '；失败：' + badList.join('、') : ''));
  await br.close();
})().catch((e) => { console.log('FAIL 脚本出错', e.stack); console.log(`\n${res.filter((x) => x[1]).length}/${res.length + 1} 通过`); process.exit(1); });
