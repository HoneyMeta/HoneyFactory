// 三门入门课程界面走查（4.6，B 机，先启动 serve）：node tests/basic_courses_ui.js
// 一个新学生，老师把「工厂与设备认知」「传感器与执行器」「生产运营基础」发布到班里（按顺序解锁）。学生在「课程」页点课程卡片 → 第 1 课，
// 选"跟着教程做"，按教程一步一步用参考做法完成：
//   i01 一条生产线长什么样：运行 → 三维 → 选中检测 → 流程图 → 答 3 题 → 提交
//   x01 输入和输出：打开 PLC 面板看 I/O（STOP 平时是 TRUE）→ 在操作台按住启动（M1_RUN 得电）→ 按停止（M1_RUN 断电）→ 答 5 题 → 提交
//   o01 节拍：填节拍（60 秒） → 按原投料跑半小时 → 投料间隔改成节拍 60 秒 → 重置、运行 → 两个目标变 ✓ → 提交
// 每课都要满分，满分后第 2 课解锁。截图在 SHOT_DIR（默认系统临时目录下的 vf-shots/）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'basic_courses');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 260)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;
const COURSES = ['intro_factory', 'intro_io', 'intro_ops'];

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = (await api(admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('bc_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'bc_teacher', name: '入门课老师', role: 'teacher', password: 'teach123' });
  const T = await login('bc_teacher', 'teach123');
  const cat = await api(T, 'GET', '/api/teach/courses');
  ok('课程库里有三门入门课（各 5 课）', COURSES.every((c) => (cat.find((x) => x.id === c) || {}).lessons === 5), cat.map((c) => `${c.id}:${c.lessons}`).join(' '));
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `入门课测试班 ${stamp}` });
  const stu = `bc${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},入门同学\n`, default_password: '123456' });
  for (const c of COURSES) {
    const r = await api(T, 'POST', `/api/teach/courses/${c}/publish`, { class_id: cls.id });
    ok(`发布 ${c} 到班级`, r.created === 5, JSON.stringify(r));
  }
  const S = await login(stu, '123456');
  const map = async () => {
    const mp = await api(S, 'GET', '/api/teach/my/courses');
    const out = {};
    for (const c of mp.courses.filter((x) => x.class_id === cls.id)) out[c.course] = c.chapters.flatMap((ch) => ch.lessons);
    return out;
  };
  const m0 = await map();
  ok('学生地图：三门课都是第 1 课可做、第 2 课锁定', COURSES.every((c) => m0[c] && m0[c][0].state === 'open' && m0[c][1].state === 'locked'),
     COURSES.map((c) => (m0[c] || []).slice(0, 2).map((l) => l.state).join('/')).join(' '));

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_theme', 'light'); sessionStorage.setItem('vf_pw_later', '1'); }, S);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  const wait = (ms) => p.waitForTimeout(ms);
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const stepId = async () => p.locator('[data-k="tour-overlay"]').getAttribute('data-step-id').catch(() => '');
  const waitStep = async (id, ms = 30000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if ((await stepId()) === id) return true; await wait(300); } return false; };
  const nextStep = async () => { await p.locator('[data-k="tour-next"]').click(); await wait(700); };
  // 目标卡片随实时进度刷新、高度会变：直接点 DOM 上的单选（等同于用户点它），不靠坐标
  const radio = async (key, i) => { const r = p.locator(`.task-panel .goal[data-rule="${key}"] .el-radio`).nth(i); await r.scrollIntoViewIfNeeded().catch(() => null);
    await r.evaluate((e) => e.click()); await wait(600); };
  const covered = [];
  /** 按住操作台按钮。被别的东西挡住（点不到）时记一条、截图，再用操作台接口按（和点按钮发的是同一个请求）。 */
  const hold = async (sel, ms = 700, sb = '', comp = '') => {
    const el = p.locator(sel).first();
    try { await el.hover({ timeout: 4000 }); await p.mouse.down(); await wait(ms); await p.mouse.up(); return true; } catch {
      covered.push(sel); await shot('covered_' + comp);
      const P2 = `/api/p/${encodeURIComponent(sb)}/cells/CELL1/panel`;
      await api(S, 'POST', P2, { comp, action: 'set', value: 1 }); await wait(ms); await api(S, 'POST', P2, { comp, action: 'release' });
      return false;
    }
  };
  const runBtn = (t) => p.locator('.ed-bar .rb button', { hasText: t }).first();
  const score = async () => { await p.waitForFunction(() => /\d/.test(document.querySelector('.task-panel .vp-score')?.textContent || ''), null, { timeout: 60000 }).catch(() => null);
    return (await p.locator('.task-panel .vp-score').first().innerText().catch(() => '')).trim(); };
  const submit = async () => {
    await p.locator('[data-k="submit-score"]').first().click();
    await wait(1500);
    return score();
  };

  /** 从"教学"页进某门课的第 1 课，选"跟着教程做"，返回沙箱编号。 */
  const enter = async (course, title) => {
    // 4.6 课程页：课程卡片（有封面）→ 课程详情（章节和课）→ 点第 1 课 → 这一课 →「开始这一课」
    await p.goto(B + '/courses', { waitUntil: 'networkidle' }); await wait(1500);
    const aid = m0[course][0].aid;
    const card = p.locator(`.course-card[data-course="${course}"]`).first();
    await card.waitFor({ timeout: 30000 }).catch(() => null);
    const cover = await card.locator('img').first().getAttribute('src').catch(() => '');
    ok(`[${course}] 课程卡片用的是这门课自己的封面`, new RegExp(`course-${course}`).test(cover || ''), cover);
    await card.click(); await wait(1000);
    const det = p.locator(`[data-k="course-detail"].course[data-course="${course}"]`).first();
    ok(`[${course}] 课程详情里是 5 课`, (await det.locator('.lesson').count()) === 5, await det.locator('.lesson').count());
    if (course === 'intro_factory') await shot('c00_course_detail');
    await det.locator(`.lesson[data-aid="${aid}"]`).first().click().catch(async () => { await det.locator('.lesson').first().click(); });
    await wait(1800);
    await p.locator('.task-panel [data-k="enter-lesson"]').first().click();
    await p.waitForSelector('.tour-ask', { timeout: 10000 }).catch(() => null);
    ok(`[${course}] 开始第 1 课：先问"跟着教程做 / 自己做"`, (await p.locator('.tour-ask button:has-text("跟着教程做")').count()) === 1);
    await p.locator('.tour-ask button:has-text("跟着教程做")').click();
    await p.waitForURL(/\/p\/sb-[^/]+\/workbench$/, { timeout: 60000 }).catch(() => null);
    await p.waitForSelector('[data-k="tour-card"]', { timeout: 30000 }).catch(() => null);
    await p.waitForFunction((t) => (document.querySelector('.task-panel .vp-head .ttl')?.textContent || '').includes(t), title, { timeout: 30000 }).catch(() => null);
    await wait(3000);
    const sb = decodeURIComponent((p.url().match(/\/p\/([^/]+)\/workbench/) || [])[1] || '');
    ok(`[${course}] 进了沙箱，左栏是「${title}」，教程第 1 步`, sb.startsWith('sb-') && (await stepId()) === 'read'
       && new RegExp(title).test(await p.locator('.task-panel .vp-head .ttl').first().innerText().catch(() => '')), `${sb} ${await stepId()}`);
    return sb;
  };
  const finish = async (course, tag) => {
    const sc = await submit();
    ok(`[${course}] 提交评分 = 满分`, /^100/.test(sc), sc);
    await wait(1200);
    await shot(`${tag}_score`);
    const m1 = await map();
    ok(`[${course}] 满分后第 2 课解锁`, m1[course][0].state === 'done' && m1[course][1].state === 'open', m1[course].slice(0, 3).map((l) => l.state).join('/'));
  };

  // ================= 工厂与设备认知 i01 =================
  await enter('intro_factory', '一条生产线长什么样');
  await shot('i01_tour_read');
  await nextStep();
  ok('[i01] 第 2 步：让仿真跑起来', (await stepId()) === 'run', await stepId());
  if (await runBtn('运行').isVisible().catch(() => false)) await runBtn('运行').click();
  ok('[i01] 仿真跑过 5 分钟 → 自动进入"在三维里看零件走"', await waitStep('see3d', 90000), await stepId());
  await p.locator('.ed-views label:has-text("三维")').click(); await wait(2500);
  await shot('i01_tour_3d');
  await nextStep();
  ok('[i01] 第 4 步：检测有两个出口（带我去 = 选中在线检测）', (await stepId()) === 'qc', await stepId());
  await p.locator('[data-k="tour-goto"]').click().catch(() => null); await wait(1500);
  ok('[i01] 选中了在线检测 QC', await p.evaluate(() => (window.__vfEd?.sel || []).includes('QC')));
  await nextStep();
  await p.locator('.ed-views label:has-text("流程")').click(); await wait(2500);
  ok('[i01] 切到流程图，图上有检测和废品箱', (await p.locator('.vue-flow__node[data-id="QC"]').count()) === 1 && (await p.locator('.vue-flow__node[data-id="NG"]').count()) === 1);
  await shot('i01_tour_flow');
  await nextStep();
  ok('[i01] 第 6 步：回答 3 道题', await waitStep('answer', 5000), await stepId());
  await p.locator('.task-panel .el-tabs__item:has-text("目标与作答")').click(); await wait(1500);
  // 4.6.2 教程不和学生抢滚动：教程开着、聚光整张题目列表；学生自己滚到第 3 题、用鼠标真点选项（以前一滚就被拉回第 1 题，第 3 题点不到）
  await p.evaluate(() => { const w = window; w.__sivN = 0; const o = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (...a) { if (this.closest && this.closest('.task-panel')) w.__sivN++; return o.apply(this, a); }; });
  const scroller = '.task-panel .tp-tabs .el-tabs__content';
  const spotOnList = await p.evaluate(() => { const s = document.querySelector('[data-k="tour-spot"]')?.getBoundingClientRect(), l = document.querySelector('.task-panel [data-tour="goal-list"]');
    const r = l && window.__vfTour.resolveTarget({ sel: '.task-panel [data-tour="goal-list"]' }); return !!(s && r && Math.abs(s.top - (r.rect.top - 6)) < 3 && s.height > 100); });
  ok('[i01] 第 6 步聚光整张题目列表（不是只圈第 1 题）', spotOnList);
  const box6 = await p.locator(scroller).first().boundingBox();
  await p.mouse.move(box6.x + box6.width / 2, box6.y + Math.min(box6.height / 2, 150));
  for (let k = 0; k < 8; k++) { await p.mouse.wheel(0, 160); await wait(120); }
  const top1 = await p.locator(scroller).first().evaluate((e) => e.scrollTop);
  await wait(3000);                                      // 教程每 0.4 秒检查一次、聚光层每帧重新定位：都不能把滚动拉回去
  const top2 = await p.locator(scroller).first().evaluate((e) => e.scrollTop);
  ok('[i01] 教程开着时学生往下滚，3 秒后还停在原处（不被拉回第 1 题）', top1 > 40 && Math.abs(top2 - top1) < 2, `${top1} → ${top2}`);
  const pickR = async (key, i) => {                      // 用鼠标点（真点在选项上，不是 DOM click）：被挡住、被滚走都会失败
    const r = p.locator(`.task-panel .goal[data-rule="${key}"] .el-radio`).nth(i);
    await r.scrollIntoViewIfNeeded().catch(() => null);
    await r.click({ timeout: 5000 }).catch((e) => console.log('   click ' + key + ': ' + e.message.split('\n')[0]));
    await wait(700);
  };
  await pickR('q_ng', 1);
  const a3 = await api(S, 'GET', `/api/teach/assignments/${m0.intro_factory[0].aid}/answers`);
  ok('[i01] 教程开着时用鼠标选中第 3 题的选项', a3.answers?.q_ng === 1, JSON.stringify(a3.answers));
  await pickR('q_order', 0);
  const wrap = await p.locator('.task-panel .goal[data-rule="q_buf"] .el-radio').nth(1).evaluate((e) => {
    const l = e.querySelector('.el-radio__label'); const ri = e.querySelector('.el-radio__input').getBoundingClientRect(), lr = l.getBoundingClientRect();
    return { h: Math.round(lr.height), lines: Math.round(lr.height / parseFloat(getComputedStyle(l).lineHeight)), clip: l.scrollWidth > l.clientWidth + 1, dot: Math.round(ri.top - lr.top) };
  });
  ok('[i01] 长选项折行显示、不被裁掉，圆圈和第一行对齐', wrap.lines >= 2 && !wrap.clip && wrap.dot >= 0 && wrap.dot <= 6, JSON.stringify(wrap));
  await pickR('q_buf', 0);                               // 先故意答错一题：看提交以后的正确答案和解析
  await shot('i01_options_wrapped');
  const siv = await p.evaluate(() => window.__sivN);
  ok('[i01] 学生滚动、作答期间教程没有再滚任务面板', siv === 0, `scrollIntoView ${siv} 次`);
  const i01sub = await waitStep('submit', 40000);
  if (!i01sub) await shot('i01_answer_stuck');
  ok('[i01] 3 题答完 → 教程进入"提交评分"', i01sub, await stepId());
  // 4.6.2 提交以后看到每道题：你的答案、正确答案、解析（老师发布时默认"提交后显示"）
  const sc65 = await submit();
  ok('[i01] 答错一题提交 = 65', /^65/.test(sc65), sc65);
  await wait(800);
  const rv = p.locator('.task-panel .sub .det[data-rule="q_buf"]').first();
  const rvTxt = (await rv.innerText().catch(() => '')).replace(/\s+/g, ' ');
  ok('[i01] 答错的题：你的答案、正确答案、解析都显示', /你的答案 ?A\. 存放做好的成品/.test(rvTxt) && /正确答案 ?B\. 临时放几件零件/.test(rvTxt) && /解析 ?缓存自己不加工/.test(rvTxt), rvTxt.slice(0, 200));
  ok('[i01] 答对的题也给解析', /解析/.test(await p.locator('.task-panel .sub .det[data-rule="q_ng"]').first().innerText().catch(() => '')));
  await rv.scrollIntoViewIfNeeded().catch(() => null);
  await shot('i01_reveal_light');
  await p.locator('.task-panel .el-tabs__item:has-text("目标与作答")').first().click().catch(() => null); await wait(1000);
  await p.locator('.task-panel .goal[data-rule="q_buf"]').first().scrollIntoViewIfNeeded().catch(() => null);
  await shot('i01_options_wrapped');
  await pickR('q_buf', 1);
  await finish('intro_factory', 'i01');

  // ================= 传感器与执行器 x01 =================
  const sbx = await enter('intro_io', '输入和输出');
  const st = await api(S, 'GET', `/api/p/${encodeURIComponent(sbx)}/state`);
  ok('[x01] 观察模式：PLC1 里预装了程序、进课就在运行（不用写程序）', (st.stations || []).some((s) => s.id === 'PLC1' && s.state === 'Executing'),
     JSON.stringify((st.stations || []).map((s) => [s.id, s.state])));
  await p.waitForSelector('.cco', { timeout: 20000 }).catch(() => null);
  ok('[x01] 操作台自动打开，有启动 / 停止', (await p.locator('[data-tour="btn-START"]').count()) >= 1 && (await p.locator('[data-tour="btn-STOP"]').count()) >= 1);
  ok('[x01] 操作台不显示 PLC 课的检查表（本课按答题评分）', !/检查表/.test(await p.locator('.cco').innerText().catch(() => '')));
  await shot('x01_tour_read');
  await nextStep();
  ok('[x01] 第 2 步：打开 PLC 面板', (await stepId()) === 'open-plc', await stepId());
  await p.locator('[data-panel="plc-editor"]').click();
  ok('[x01] 打开 PLC 面板 → 自动进入"先什么都别按"', await waitStep('idle', 15000), await stepId());
  await p.waitForFunction(() => /STOP/.test(document.querySelector('.ed-left')?.innerText || ''), null, { timeout: 20000 }).catch(() => null);
  await wait(1000);
  const ioTxt = await p.locator('.ed-left').innerText().catch(() => '');
  ok('[x01] I/O 监视表：STOP 没按时是 TRUE，START 是 FALSE', /STOP[\s\S]{0,40}TRUE/.test(ioTxt) && /START[\s\S]{0,40}FALSE/.test(ioTxt), ioTxt.replace(/\s+/g, ' ').slice(0, 260));
  await shot('x01_tour_io');
  await nextStep();
  ok('[x01] 第 4 步：按一下启动', (await stepId()) === 'press-start', await stepId());
  await hold('[data-tour="btn-START"]', 800, sbx, 'START');
  ok('[x01] 按住启动 → M1_RUN 得电 → 教程进入"再按一下停止"', await waitStep('press-stop', 15000), await stepId());
  const logTxt = await p.locator('.cco .rlog').innerText().catch(() => '');
  ok('[x01] 运行日志记下了 START 0→1 和 M1_RUN 0→1', /START 0→1/.test(logTxt) && /M1_RUN 0→1/.test(logTxt), logTxt.replace(/\s+/g, ' ').slice(-300));
  await shot('x01_tour_started');
  await hold('[data-tour="btn-STOP"]', 800, sbx, 'STOP');
  ok('[x01] 按停止 → M1_RUN 断电 → 教程进入"回答 5 道题"', await waitStep('answer', 15000), await stepId());
  await p.locator('[data-k="tour-goto"]').click().catch(() => null); await wait(1200);
  await p.locator('.task-panel .el-tabs__item:has-text("目标与作答")').click().catch(() => null); await wait(800);
  await radio('q_in', 2); await radio('q_out', 1); await radio('q_press', 1); await radio('q_fb', 1); await radio('q_addr', 1);
  ok('[x01] 5 题答完 → 教程进入"提交评分"', await waitStep('submit', 15000), await stepId());
  await finish('intro_io', 'x01');

  // ================= 生产运营基础 o01 =================
  const sbo = await enter('intro_ops', '节拍');
  await nextStep();
  ok('[o01] 第 2 步：算节拍', (await stepId()) === 'takt', await stepId());
  await p.locator('.task-panel .el-tabs__item:has-text("目标与作答")').click().catch(() => null); await wait(800);
  { const n = p.locator('.task-panel .goal[data-rule="q_takt"] [data-k="q-number"] input').first();
    await n.scrollIntoViewIfNeeded().catch(() => null); await n.fill('60'); await n.press('Enter'); await n.blur().catch(() => null); await wait(800); }
  ok('[o01] 答了节拍题 → 教程进入"按现在的投料跑半小时"', await waitStep('run', 15000), await stepId());
  if (await runBtn('运行').isVisible().catch(() => false)) await runBtn('运行').click();
  ok('[o01] 跑过 30 分钟 → 教程进入"把投料间隔改成节拍"', await waitStep('change', 120000), await stepId());
  const lv0 = await api(S, 'GET', `/api/teach/assignments/${m0.intro_ops[0].aid}/live`);
  const lead0 = (lv0.progress.rules.find((r) => r.key === 'lead') || {}).value;
  await shot('o01_tour_before');
  // 和学生一样：教程"带我去"选中投料 SRC → 右边属性「节拍」→ 到达间隔改成 60、回车
  await p.locator('[data-k="tour-goto"]').click().catch(() => null); await wait(1500);
  await p.locator('.ed-right .el-tabs__item:has-text("属性")').first().click().catch(() => null); await wait(800);
  const row = p.locator('.ed-right .f:has(label:has-text("到达间隔"))').first();
  if (!(await row.isVisible().catch(() => false))) { await p.locator('.ed-right .el-collapse-item__header:has-text("节拍")').first().click().catch(() => null); await wait(800); }
  const inp = row.locator('input').first();
  await inp.fill('60'); await inp.press('Enter'); await wait(2500);
  await shot('o01_set_interval');
  ok('[o01] 投料间隔改成 60 → 教程进入"重置后再跑"', await waitStep('rerun', 20000), await stepId());
  await runBtn('重置').click(); await wait(1200);
  const box = p.locator('.el-message-box');
  if (await box.isVisible().catch(() => false)) {
    console.log('   重置确认：' + (await box.innerText()).replace(/\s+/g, ' ').slice(0, 200));
    await shot('o01_reset_confirm');
    await box.locator('.el-button--primary').first().click(); await wait(2500);
  }
  if (await runBtn('运行').isVisible().catch(() => false)) await runBtn('运行').click();
  ok('[o01] 重置后再跑：小时产出、生产周期两个目标变 ✓ → 教程进入"提交评分"', await waitStep('submit', 150000), await stepId());
  const lv1 = await api(S, 'GET', `/api/teach/assignments/${m0.intro_ops[0].aid}/live`);
  const lead1 = (lv1.progress.rules.find((r) => r.key === 'lead') || {}).value;
  ok('[o01] 按节拍投料后生产周期缩短到 5 分钟以内', lead1 !== null && lead1 < 5 && lead1 < lead0, `改前 ${lead0} 分钟 → 改后 ${lead1} 分钟`);
  await shot('o01_tour_goals');
  await finish('intro_ops', 'o01');
  await shot('o01_done');

  ok('操作台按钮没有被教程卡片等挡住（能直接点到）', covered.length === 0, covered.join(', '));
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
  process.exit(bad.length ? 1 : 0);
})();
