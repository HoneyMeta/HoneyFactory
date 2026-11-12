// 教学 / 设计 / 联调面板的界面走查（B 机，先启动 serve 并构建面板开发页）：
//   cd web && npx vite build && npx vite build --config vite.panels.config.ts
//   node tests/panels_ui.js          截图在 SHOT_DIR（默认 data/ui_panels）
// 外壳还没接好，所以用临时开发页 /_panels/panels-dev.html?panel=<面板编号>&pid=<工厂> 单独挂面板。
// 流程：老师建班并导入名单 → 发布任务向导 → 学生打开任务、进沙箱、下载程序、提交 → 自动评分 → 老师控制台看到成绩、旁观、注入故障、复核 →
//       课程：发布课程 → 学生课程地图（解锁）→ 产线课目标与作答（选择题、图上点选）→ 提交满分 → 老师课程总览（浅色）→
//       成绩册；设计：报告导出（截图 + Word/PPT 下载）、SOP 编辑与播放；联调台：点表、连接、报文、测试剧本运行。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800';
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_panels');
const DEV = B + '/_panels/panels-dev.html';
const PID = process.env.VF_PLANT || 'foundry-housing';
const STAMP = new Date().toISOString().slice(5, 19).replace(/[-:T]/g, '');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, method, url, body) => {
  const r = await fetch(B + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', ...(tok ? { Authorization: 'Bearer ' + tok } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
};
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;

// 4.5：第一次"开始这一课"有跟随教程的课会先问"跟着教程做 / 自己做"——这里选"自己做"（教程本身在 tutorial_ui.js 里测）
const selfDo = async (pg) => { const b = pg.locator('.tour-ask button:has-text("自己做")'); await b.waitFor({ state: 'visible', timeout: 2500 }).catch(() => null); if (await b.isVisible().catch(() => false)) { await b.click(); await pg.waitForTimeout(400); } };

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const br = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const errs = [];
  async function page(tok, w = 1600, h = 940) {
    const ctx = await br.newContext({ locale: 'zh-CN', viewport: { width: w, height: h }, acceptDownloads: true });
    await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); }, tok);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
    p.on('console', (m) => { if (m.type() === 'error' && !/favicon|40[34]|409/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
    return p;
  }
  const open = async (p, panel, pid = 'foundry-housing', extra = '') => { await p.goto(`${DEV}?panel=${panel}&pid=${pid}${extra}`, { waitUntil: 'networkidle' }); await p.waitForTimeout(900); };
  const shot = (p, n) => p.screenshot({ path: `${OUT}/${n}.png` });
  // 新导入的学生用初始密码登录会弹"先改一下密码"：截图后点"以后再说"
  const later = async (p, n) => {
    const b = p.locator('.el-dialog button:has-text("以后再说")');
    await b.first().waitFor({ state: 'visible', timeout: 4000 }).catch(() => null);
    if (await b.first().isVisible().catch(() => false)) { if (n) await shot(p, n); await b.first().click(); await p.waitForTimeout(500); return true; }
    return false;
  };
  const frame = (p) => p.locator('.frame');

  const admin = await login('admin', 'honey123');
  const users = (await api(admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('tt_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'tt_teacher', name: '王老师', role: 'teacher', password: 'teach123' });
  const T = await login('tt_teacher', 'teach123');

  // ---------- 1. 班级与名单 ----------
  const tp = await page(T);
  await open(tp, 'teach-classes');
  await tp.click('button:has-text("新建班级")');
  await tp.fill('.el-message-box input', `2026 级电气 1 班 ${STAMP}`);
  await tp.click('.el-message-box button:has-text("确定")');
  await tp.waitForTimeout(800);
  await tp.click('button:has-text("导入名单")');
  const names = ['张伟', '李娜', '王强', '刘洋', '陈静', '杨帆'];
  // 像从 Excel 复制：制表符分隔、带表头，再混一行中文逗号和一行有问题的
  const csv = '学号\t姓名\n' + names.map((n, i) => `tt_u${String(i + 1).padStart(2, '0')}${i === 2 ? '，' : '\t'}${n}`).join('\n') + '\n张 三\t张三';
  await tp.fill('.el-dialog textarea', csv);
  await tp.waitForTimeout(1500);
  const pvTxt = await tp.locator('.el-dialog .prev').innerText().catch(() => '');
  ok('粘贴后自动预览，问题行标出来（T2）', /有问题 1/.test(pvTxt) && (await tp.locator('.el-dialog tr.st-error').count()) === 1, pvTxt.replace(/\s+/g, ' ').slice(0, 160));
  await shot(tp, 'p01a_roster_preview');
  await tp.click('.el-dialog button:has-text("导入（6 人）")');
  await tp.waitForTimeout(1200);
  const resTxt = await tp.locator('.el-dialog .vp-card').innerText().catch(() => '');
  ok('界面导入名单', /加入本班 6/.test(resTxt), resTxt);
  await shot(tp, 'p01_roster_import');
  await tp.click('.el-dialog button:has-text("关闭")');
  await tp.waitForTimeout(500);
  const rows = await frame(tp).locator('.vp-tbl tr').count();
  ok('名单表格', rows >= 7, rows);
  await shot(tp, 'p02_classes');
  const classes = await api(T, 'GET', '/api/teach/classes');
  const cls = classes.find((c) => c.name.includes(STAMP));

  // ---------- 2. 发布任务向导 ----------
  await open(tp, 'teach-publish');
  await tp.locator('[data-scene="s04_sort_color"]').click();
  await tp.waitForTimeout(1200);
  ok('向导：右边显示所选场景的任务书和评分（T6）', /任务书/.test(await tp.locator('.frame').innerText()) && (await tp.locator('.frame .el-tabs__item:has-text("评分")').count()) >= 1);
  await shot(tp, 'p03_wizard_scene');
  await tp.click('button:has-text("下一步")');
  await tp.locator('.frame .el-select').first().click();
  await tp.locator(`.el-select-dropdown__item:has-text("${cls.name}")`).click();
  await tp.locator('.frame input[placeholder="不限时"]').fill('2030-06-30 18:00');
  await tp.keyboard.press('Enter');
  await tp.click('.frame >> text=作业名称');
  await tp.click('button:has-text("下一步")');
  await shot(tp, 'p04_wizard_faults');
  await tp.click('button:has-text("下一步")');
  await shot(tp, 'p05_wizard_confirm');
  await tp.click('button:has-text("发布")');
  await tp.waitForTimeout(1200);
  const asg = (await api(T, 'GET', `/api/teach/assignments?class_id=${cls.id}`))[0];
  ok('向导发布任务', asg && asg.scene === 's04_sort_color' && asg.due === '2030-06-30 18:00' && asg.faults.length >= 3, asg && [asg.title, asg.due, asg.faults.length]);

  // ---------- 3. 学生：任务面板 → 进沙箱 → 下载程序 → 提交 ----------
  const S1 = await login('tt_u01', '123456');
  const sp = await page(S1);
  await open(sp, 'teach-task', 'foundry-housing', '&w=420');
  ok('初始密码登录提示改密码', await later(sp, 'p05b_student_pw'));
  ok('学生看到任务', (await sp.locator(`[data-aid="${asg.id}"]`).count()) === 1);
  await shot(sp, 'p06_student_list');
  await sp.locator(`[data-aid="${asg.id}"]`).click();
  await sp.waitForTimeout(800);
  await shot(sp, 'p07_student_taskbook');
  ok('没进沙箱时"提交评分"是灰的（S7）', await sp.locator('.acts .el-button--success').first().isDisabled());
  await sp.click('[data-k="enter-lesson"]'); await selfDo(sp);
  await sp.waitForTimeout(1500);
  const st = JSON.parse(await sp.locator('.state pre').innerText());
  ok('进沙箱：ed.teach.open 给外壳', st.teach && st.teach.open && st.teach.open.pid === `sb-tt_u01-${asg.id}`, JSON.stringify(st.teach));
  const sb = st.teach.pid;
  const ref = (await api(T, 'GET', '/api/teach/scenes/s04_sort_color')).reference.st;
  const dl = await api(S1, 'POST', `/api/p/${sb}/cells/CELL1/program/download`, { program: ref });
  ok('学生下载程序到沙箱 PLC（模拟 PLC 编辑器）', dl.ok, dl.state);
  await sp.locator('.el-tabs__item:has-text("I/O 表")').click();
  await sp.waitForTimeout(4500);
  await shot(sp, 'p08_student_io_live');
  await sp.click('button:has-text("提交评分")');
  await sp.waitForTimeout(4000);
  const score = await sp.locator('.vp-score').first().innerText().catch(() => '');
  ok('提交后显示自动评分', /^100/.test(score.trim()), score);
  await shot(sp, 'p09_student_score');
  const tut = await api(S1, 'GET', '/api/tutor/status');
  // AI 助教只在右下角一个入口（S8）：任务面板没有助教页签，"问助教"按钮打开右下角
  ok('任务面板没有 AI 助教页签', (await sp.locator('.el-tabs__item:has-text("AI 助教")').count()) === 0);
  await sp.evaluate(() => { window.__tg = 0; window.addEventListener('vf:assistant-toggle', () => { window.__tg++; }); });
  await sp.click('button:has-text("问助教")');
  ok('"问助教"打开右下角助教（vf:assistant-toggle）', (await sp.evaluate(() => window.__tg)) === 1);
  if (tut.configured) {
    const h = await api(S1, 'GET', `/api/tutor/hint?assignment_id=${asg.id}`);
    ok('助教等待时可先显示的提示 1', h.hint && h.total >= 1, h.hint);
  }
  // 第二个学生交一个错的
  const S2 = await login('tt_u02', '123456');
  const s2 = await api(S2, 'POST', `/api/teach/assignments/${asg.id}/sandbox`);
  const bad = { ...ref, source: ref.source.replace(/P1_EXTEND\s*:=\s*PUSH\s*;/, 'P1_EXTEND := FALSE;').replace('(START OR RUN)', 'START') };
  await api(S2, 'POST', `/api/p/${s2.pid}/cells/CELL1/program/download`, { program: bad });
  await api(S2, 'POST', `/api/teach/assignments/${asg.id}/submit`, {});
  // 第二次只多一行注释：分数不变，老师能看到两次程序的差别
  await api(S2, 'POST', `/api/p/${s2.pid}/cells/CELL1/program/download`, { program: { ...bad, source: bad.source.replace('END_PROGRAM', '(* 第二次提交：检查了推杆 *)\nEND_PROGRAM') } });
  const sub2 = await api(S2, 'POST', `/api/teach/assignments/${asg.id}/submit`, {});
  for (const u of ['tt_u03', 'tt_u04']) { const t = await login(u, '123456'); await api(t, 'POST', `/api/teach/assignments/${asg.id}/sandbox`); }

  // ---------- 4. 老师控制台 ----------
  await open(tp, 'teach-console');
  await tp.locator('.frame .vp-head .el-select').first().click();
  await tp.locator(`.el-select-dropdown__item:has-text("${asg.title}")`).first().click();
  await tp.waitForTimeout(1500);
  const cards = await tp.locator('.stu').count();
  ok('控制台显示全班学生卡片', cards === 6, cards);
  const u1card = await tp.locator('[data-user="tt_u01"]').innerText();
  ok('控制台看到学生成绩', /100/.test(u1card) && /已满分/.test(u1card), u1card.replace(/\n/g, ' '));
  await shot(tp, 'p11_console_grid');
  await tp.locator('[data-user="tt_u02"]').click();
  await tp.waitForTimeout(2800);
  ok('旁观：学生 I/O 表', (await tp.locator('.detail .vp-tbl tr').count()) > 5);
  await shot(tp, 'p12_console_watch');
  await tp.locator('.detail .el-tabs__item:has-text("注入故障")').click();
  await tp.locator('.detail .fault button:has-text("注入")').first().click();
  await tp.waitForTimeout(800);
  const live2 = await api(S2, 'GET', `/api/teach/assignments/${asg.id}/live`);
  ok('界面注入故障进了学生沙箱', live2.stats && live2.stats.faults === 1, live2.stats && live2.stats.faults);
  await shot(tp, 'p13_console_fault');
  await tp.waitForTimeout(4500);
  const u2card = await tp.locator('[data-user="tt_u02"]').innerText();
  ok('学生卡片显示"故障中"（T13）', /故障中/.test(u2card), u2card.replace(/\n/g, ' '));
  await shot(tp, 'p13a_console_faulty');
  // 学生端：排故卡片
  const sp2 = await page(S2);
  await open(sp2, 'teach-task', 'foundry-housing', '&w=420');
  await later(sp2);
  await sp2.locator(`[data-aid="${asg.id}"]`).click();
  await sp2.waitForTimeout(3500);
  ok('学生端出现"设备出故障了"排故卡片', (await sp2.locator('.fault-card').count()) === 1);
  await shot(sp2, 'p13b_student_diagnose');
  const fl = (await api(T, 'GET', `/api/teach/assignments/${asg.id}/progress`)).rows.find((r) => r.username === 'tt_u02').faults[0];
  const hit = asg.faults.find((f) => f.label === fl.label) || asg.faults[0];
  const dg = await api(S2, 'POST', `/api/teach/assignments/${asg.id}/diagnose`, { comp: hit.comp, kind: hit.kind });
  ok('学生排故答对', dg.ok, dg.msg);
  await sp2.close();
  await tp.waitForSelector('.el-notification', { timeout: 12000 }).catch(() => null);
  const nt = await tp.locator('.el-notification').first().innerText().catch(() => '');
  ok('老师收到"学生排除了故障"通知', /排除/.test(nt), nt.replace(/\n/g, ' '));
  await shot(tp, 'p13c_teacher_notice');
  await tp.locator('.detail .el-tabs__item:has-text("提交与复核")').click();
  await tp.waitForTimeout(600);
  await tp.locator('.detail .sub .el-input-number input').first().fill('70');
  await tp.locator('.detail .sub input[placeholder="总评语"]').first().fill('推杆输出接错了，自锁也没做');
  await tp.locator('.detail .sub button:has-text("保存复核")').first().click();
  await tp.waitForTimeout(1200);
  const subs = await api(T, 'GET', `/api/teach/assignments/${asg.id}/submissions?username=tt_u02`);
  ok('界面复核改分', subs[0].override_score === 70 && subs[0].comment.includes('自锁'), [sub2.auto_score, subs[0].override_score]);
  await shot(tp, 'p14_console_review');
  await tp.locator('.detail .sub').first().locator('.el-radio-button:has-text("和上一次比")').click();
  await tp.waitForTimeout(400);
  const df = await tp.locator('.detail .sub .prog.diff').first().innerText().catch(() => '');
  ok('两次提交的程序对比（T11）', /\+ \(\* 第二次提交/.test(df), df.split('\n').filter((l) => /^[+-]/.test(l)).join(' | '));
  await tp.locator('.detail .sub .prog.diff').first().scrollIntoViewIfNeeded();
  await shot(tp, 'p14b_console_diff');
  await tp.locator('.vp-head .el-dropdown button:has-text("任务")').first().click();
  await tp.locator('.el-dropdown-menu__item:has-text("学情分析")').click();
  await tp.waitForTimeout(1000);
  ok('学情分析：每个评分项的得分率', (await tp.locator('.el-dialog .bar').count()) >= 3);
  await shot(tp, 'p14c_analytics');
  await tp.locator('.el-dialog__headerbtn').last().click();
  await tp.waitForTimeout(400);

  // 成绩册
  await open(tp, 'teach-classes');
  await tp.locator(`[data-class="${cls.id}"]`).click();
  await tp.locator('.el-tabs__item:has-text("成绩册")').click();
  await tp.waitForTimeout(800);
  const gb = await tp.locator('.gb-wrap').innerText();
  ok('成绩册显示最高分和改分', /100/.test(gb) && /70/.test(gb), gb.replace(/\s+/g, ' ').slice(0, 160));
  const [dlx] = await Promise.all([tp.waitForEvent('download'), tp.click('button:has-text("导出 Excel")')]);
  const xp = path.join(OUT, 'gradebook.xlsx');
  await dlx.saveAs(xp);
  ok('成绩册 Excel 下载', fs.statSync(xp).size > 4000, fs.statSync(xp).size);
  await shot(tp, 'p16_gradebook');

  // ---------- 5. 设计：报告导出、SOP ----------
  const ap = await page(admin);
  await open(ap, 'design-report');
  await ap.click('button:has-text("截取当前视图")');
  await ap.waitForTimeout(500);
  ok('报告面板截取画布', (await ap.locator('img.thumb').count()) === 1);
  await shot(ap, 'p17_report_panel');
  const [dw] = await Promise.all([ap.waitForEvent('download', { timeout: 60000 }), ap.click('button:has-text("导出 Word")')]);
  const wp = path.join(OUT, 'report_ui.docx');
  await dw.saveAs(wp);
  const [dp] = await Promise.all([ap.waitForEvent('download', { timeout: 60000 }), ap.click('button:has-text("导出 PPT")')]);
  const pp = path.join(OUT, 'report_ui.pptx');
  await dp.saveAs(pp);
  await ap.waitForTimeout(500);
  const last = await ap.locator('.frame .foot .last').innerText().catch(() => '');
  ok('界面导出 Word 和 PPT（带画布截图）', fs.statSync(wp).size > 20000 && fs.statSync(pp).size > 20000 && /画布截图/.test(last), `${fs.statSync(wp).size} ${fs.statSync(pp).size} ${last}`);
  await open(ap, 'design-sop', 'foundry-housing', '&w=400');
  await ap.click('button:has-text("新建")');
  await ap.fill('.frame input[placeholder^="步骤标题"]', '确认电炉冷却水');
  await ap.fill('.frame textarea[placeholder^="操作说明"]', '查看 **冷却水流量**，低于下限时不得开炉。');
  await ap.locator('.frame .step .el-select').first().click();
  await ap.locator('.el-select-dropdown__item:has-text("FUR1")').first().click();
  await ap.click('.frame button:has-text("加一步")');
  await ap.fill('.frame .step.on input[placeholder^="步骤标题"]', '到造型线确认砂型');
  await ap.locator('.frame .step.on .el-select').first().click();
  await ap.locator('.el-select-dropdown__item:visible:has-text("MOLD1")').first().click();
  await ap.locator('.frame .el-form input').first().fill('新员工熟悉熔炼造型');
  await shot(ap, 'p18_sop_edit');
  await ap.click('.frame button:has-text("保存")');
  await ap.waitForTimeout(800);
  await ap.locator('.frame button:has-text("开始漫游")').last().click();
  await ap.waitForTimeout(600);
  let est = JSON.parse(await ap.locator('.state pre').innerText());
  ok('SOP 播放：ed.sop 第 1 步 + 高亮目标设备', est.sop && est.sop.index === 0 && est.sop.step.target.block === 'FUR1' && est.highlight[0] === 'FUR1' && est.focusReq.id === 'FUR1',
    JSON.stringify(est.sop && est.sop.step.target));
  await ap.click('.frame button:has-text("下一步")');
  await ap.waitForTimeout(400);
  est = JSON.parse(await ap.locator('.state pre').innerText());
  ok('SOP 下一步', est.sop.index === 1 && est.highlight[0] === 'MOLD1', est.sop.index);
  await shot(ap, 'p19_sop_play');

  // ---------- 6. 联调台 ----------
  await open(ap, 'debug-console', 'foundry-housing', '&w=460');
  await ap.waitForTimeout(2500);
  const prow = await ap.locator('.pts tr').count();
  ok('联调台点表有实时值和地址', prow > 50 && /ns=2;s=foundry-housing/.test(await ap.locator('.pts').innerText()), prow);
  await shot(ap, 'p20_debug_points');
  await ap.locator('.el-tabs__item:has-text("连接")').click();
  await ap.waitForTimeout(800);
  await shot(ap, 'p21_debug_conn');
  await ap.locator('.el-tabs__item:has-text("报文")').click();
  await ap.waitForTimeout(3500);
  const nmsg = await ap.locator('.msg').count();
  ok('报文监视滚动', nmsg > 10, nmsg);
  await ap.locator('.msg').first().click();
  await shot(ap, 'p22_debug_msgs');
  await ap.locator('.el-tabs__item:has-text("测试剧本")').click();
  await ap.waitForTimeout(400);
  const script = { name: `界面试跑 ${STAMP}`, speed: 30, steps: [
    { kind: 'setpoint', station: 'CNC2', tag: 'Monitoring/Feed/Override', value: 95 },
    { kind: 'assert', via: 'opcua', station: 'CNC2', tag: 'Monitoring/Feed/Override', op: '==', value: 95, within: 6 },
    { kind: 'assert', via: 'mqtt', station: 'CNC2', tag: 'Monitoring/Feed/Override', op: '==', value: 95, within: 6 },
    { kind: 'fault', station: 'CNC2', fault: 'failure' },
    { kind: 'assert_mes', topic: 'event', match: { station: 'CNC2', kind: 'fault' }, within: 60 }] };
  // 联调台归助手 P 维护，界面改了就跳过这一段（P 有自己的测试）
  if (await ap.locator('.mono-ta textarea').first().waitFor({ timeout: 5000 }).then(() => true).catch(() => false)) {
    await ap.fill('.mono-ta textarea', JSON.stringify(script, null, 2));
    await ap.click('.frame button:has-text("保存")');
    await ap.waitForTimeout(600);
    await ap.click('.frame button:has-text("运行")');
    await ap.waitForSelector('.frame .res', { timeout: 20000 });
    await ap.waitForFunction(() => /通过|失败|出错/.test(document.querySelector('.frame .run-card b')?.textContent || ''), null, { timeout: 90000 }).catch(() => null);
    const verdict = await ap.locator('.frame .run-card b').first().innerText();
    ok('联调台运行测试剧本', verdict === '通过', verdict + ' ' + (await ap.locator('.frame .run-card').innerText()).replace(/\n/g, ' ').slice(0, 200));
    await shot(ap, 'p23_debug_tests');
  } else console.log('SKIP 联调台测试剧本：界面已改（助手 P 维护）');
  await open(ap, 'debug-console-float');
  await ap.waitForTimeout(2500);
  await shot(ap, 'p24_debug_float');

  // ---------- 7. 课程 ----------
  await open(tp, 'teach-console');
  await tp.click('.vp-head button:has-text("发布课程")');
  await tp.waitForTimeout(900);
  await tp.locator('.course-publish [data-course="machining"]').click();
  await tp.locator('.course-publish .cp-foot .el-select').first().click();
  await tp.locator(`.el-select-dropdown__item:visible:has-text("${cls.name}")`).first().click();
  await tp.waitForTimeout(300);
  await shot(tp, 'p30_course_publish');
  await tp.click('.course-publish .cp-foot button:has-text("发布课程")');
  await tp.waitForSelector('.course-progress .mx', { timeout: 20000 }).catch(() => null);
  ok('界面发布课程后显示课程总览', (await tp.locator('.course-progress .mx').count()) === 1, await tp.locator('.course-progress b').first().innerText().catch(() => ''));
  await shot(tp, 'p31_course_matrix');

  const sc = await page(S1);
  await open(sc, 'teach-task', PID, '&w=420');
  await later(sc);
  const cm = sc.locator(`.course[data-course="machining"]`).last();
  // 4.6：课程多于 3 门时窄面板只展开第一门没学完的课，其余折叠；先展开机加工这门
  if (await cm.evaluate((e) => e.classList.contains('folded')).catch(() => false)) { await cm.locator('.cname').first().click(); await sc.waitForTimeout(400); }
  const lessons = cm.locator('.lesson');
  const st0 = await lessons.evaluateAll((els) => els.map((e) => e.className));
  ok('学生课程地图：第 1 课可做、第 2 课锁定', /open/.test(st0[0]) && /locked/.test(st0[1]), st0.slice(0, 3).join(' | '));
  await shot(sc, 'p32_course_map');
  const aidM1 = Number(await lessons.first().getAttribute('data-aid'));
  await lessons.first().click();
  await sc.waitForTimeout(900);
  await sc.click('[data-k="enter-lesson"]'); await selfDo(sc);
  await sc.waitForTimeout(1500);
  const sbM1 = JSON.parse(await sc.locator('.state pre').innerText()).teach.pid;
  await sc.locator('.el-tabs__item:has-text("目标与作答")').click();
  await sc.locator('.goal[data-rule="q_cap"] .el-radio').nth(1).click();
  await sc.waitForTimeout(600);
  const mdl = (await api(S1, 'GET', `/api/p/${sbM1}/model`)).model;
  mdl.blocks.find((b) => b.id === 'SRC').params.interval = '80';
  await api(S1, 'PUT', `/api/p/${sbM1}/model`, { model: mdl });
  await sc.waitForTimeout(2600);
  const goalTxt = await sc.locator('.goal').allInnerTexts();
  ok('目标与作答：显示目标和实时进度', goalTxt.length === 3 && /[≥≤]\s*\d/.test(goalTxt[1]) && /当前/.test(goalTxt[1]), goalTxt.join(' / ').replace(/\n/g, ' ').slice(0, 200));
  await shot(sc, 'p33_lesson_goals');
  await sc.click('button:has-text("提交评分")');
  await sc.waitForTimeout(9000);
  const sc1 = await sc.locator('.vp-score').first().innerText().catch(() => '');
  ok('产线课提交 = 满分，出现"下一课"', /^100/.test(sc1.trim()) && (await sc.locator('.next-card').count()) === 1, sc1);
  await shot(sc, 'p34_lesson_score');
  // 点选题（第 3 课：找瓶颈）——老师先全部开放
  await api(T, 'PATCH', `/api/teach/courses/machining/classes/${cls.id}`, { open_all: true });
  await sc.click('.vp-head button:has-text("课程地图")');
  await sc.waitForTimeout(1200);
  await sc.locator(`.course[data-course="machining"]`).last().locator('.lesson').nth(2).click();
  await sc.waitForTimeout(900);
  await sc.click('[data-k="enter-lesson"]'); await selfDo(sc);
  await sc.waitForTimeout(1500);
  await sc.locator('.el-tabs__item:has-text("目标与作答")').click();
  await sc.locator('.goal[data-rule="q_bn"] button:has-text("在图上点选")').click();
  await sc.waitForSelector('[data-pickbar] [data-pick="M3"]', { timeout: 8000 });
  await shot(sc, 'p35_pick_prompt');
  await sc.locator('[data-pickbar] [data-pick="M3"]').click();
  await sc.waitForTimeout(800);
  const pickTxt = await sc.locator('.goal[data-rule="q_bn"]').innerText();
  ok('图上点选（ed.pick 约定）：选中 M3 并保存', /已选：\s*M3/.test(pickTxt), pickTxt.replace(/\n/g, ' '));
  await shot(sc, 'p36_pick_done');
  await sc.click('.vp-head button:has-text("课程地图")');
  await sc.waitForTimeout(1200);
  await shot(sc, 'p37_course_map');

  await open(tp, 'teach-console');
  await tp.waitForTimeout(1500);
  if ((await tp.locator('.course-progress').count()) === 0) {
    const btn = tp.locator('.vp-head button:has-text("课程总览")');
    if (await btn.count()) await btn.click();
  }
  await tp.waitForTimeout(1200);
  const mxTxt = await tp.locator('.course-progress').innerText().catch(() => '');
  ok('老师课程总览看到学生成绩', /100/.test(mxTxt), mxTxt.replace(/\s+/g, ' ').slice(0, 120));
  await shot(tp, 'p38_course_matrix_after');

  // SOP 空白页：新建 / 看示例（学生沙箱里还没有 SOP）
  await open(ap, 'design-sop', sbM1, '&w=400');
  ok('SOP 空白页给出"新建"和"看示例"', (await ap.locator('.vp-empty button:has-text("看示例")').count()) === 1);
  await shot(ap, 'p40_sop_empty');
  await ap.click('.vp-empty button:has-text("看示例")');
  await ap.waitForTimeout(800);
  ok('看示例：按设备顺序生成步骤', (await ap.locator('.frame .step').count()) >= 3, await ap.locator('.frame .step').count());
  await shot(ap, 'p41_sop_sample');
  await open(ap, 'design-sop', PID, '&w=400');
  ok('示范工厂自带示例 SOP', /新员工熟悉产线/.test(await ap.locator('.frame').innerText()));
  await open(ap, 'design-report');
  ok('报告面板有示例实验', /示例：/.test(await ap.locator('.frame').innerText()));
  await shot(ap, 'p42_report_sample');

  ok('页面没有脚本错误', errs.length === 0, errs.slice(0, 5).join(' | '));
  await br.close();
  const n = res.filter((x) => x[1]).length;
  console.log(`\n${n}/${res.length} 通过，截图在 ${OUT}`);
  process.exit(n === res.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
