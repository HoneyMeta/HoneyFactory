// 4.6 文字重叠检查（B 机，先启动 serve）：node tests/overlap_ui.js
// 浅色 / 深色 × 1280×720（4.7 最小分辨率，紧凑布局）/ 1680×960，扫描主要页面和面板里看得见的文字，找出两段字压在一起的地方（ui_scan.js 的 overlaps）：
//   开始页、教学页（老师 / 学生）、工作台右栏每个页签、每个浮窗、分析浮窗、
//   学生产线课的任务面板（任务书 / 目标与作答 / 成绩，运行中有"目标：… 当前 …（估计）"）、PLC 课的任务面板（任务书 / 检查表 / 日志 / I/O 表 / 成绩）。
// 每处重叠打印"在哪个页面、哪两段字、位置"，并截图。截图在 SHOT_DIR。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const { SCAN } = require('./ui_scan');
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'overlap');
const PLANT = process.env.VF_PLANT || 'foundry-housing';
const QUICK = process.argv.includes('quick');                  // 只跑浅色 1280
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 3000)); };
const api = async (tok, m, u, b) => { const r = await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); };
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = ((await api(admin, 'GET', '/api/admin/users')).users || []).map((u) => u.username);
  if (!users.includes('ov_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'ov_teacher', name: '重叠老师', role: 'teacher', password: 'teach123' });
  const T = await login('ov_teacher', 'teach123');
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `重叠测试班 ${stamp}` });
  const stu = `ov${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},重叠同学\n`, default_password: '123456' });
  const cellAid = (await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's01_motor_latch', title: '电机启停自锁（重叠测试）' })).id;
  await api(T, 'POST', '/api/teach/courses/machining/publish', { class_id: cls.id, open_all: true });
  const S = await login(stu, '123456');
  // 学生的两个沙箱：PLC 课、产线课（第 1 课）
  const cellSb = (await api(S, 'POST', `/api/teach/assignments/${cellAid}/sandbox`, {})).pid;
  const lessons = await api(T, 'GET', `/api/teach/assignments?class_id=${cls.id}`);
  const plantAid = (Array.isArray(lessons) ? lessons : []).find((a) => a.course === 'machining' && /m01/.test(a.lesson || a.scene || ''))?.id;

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const found = new Map();
  let scans = 0, shotN = 0, labelOver = 0;
  const labelInfo = [];
  async function page(tok, w, h, theme) {
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
    await ctx.addInitScript(([t, th]) => {
      if (sessionStorage.getItem('ov_init')) return; sessionStorage.setItem('ov_init', '1');
      localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_ws', 'all');
      sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_guide_off', '1'); localStorage.setItem('vf_teach_tour', '1'); localStorage.removeItem('vf_wb2_sizes');
      localStorage.setItem('vf_whatsnew_seen', '9.9.9');
    }, [tok, theme]);
    await ctx.addInitScript({ content: SCAN });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    p.on('dialog', (d) => d.dismiss());
    return p;
  }
  const dismiss = async (p) => { for (const t of ['以后再说', '跳过', '知道了', '自己做']) { const x = p.locator(`.el-dialog .el-button:has-text("${t}"), .tour-ask button:has-text("${t}")`).first(); if (await x.isVisible().catch(() => false)) await x.click().catch(() => null); } };
  async function scan(p, view, combo) {
    scans++;
    const os = await p.evaluate(() => window.__vfScan.overlaps()).catch((e) => [{ a: 'scan error', b: String(e).slice(0, 80), ea: '', eb: '', rect: [] }]);
    let fresh = false;
    for (const o of os) {
      const k = `${view} | ${o.ea} | ${o.eb}`;
      if (!found.has(k)) { found.set(k, { ...o, view, combos: [combo] }); fresh = true; } else found.get(k).combos.push(combo);
    }
    if (fresh && shotN < 40) await p.screenshot({ path: `${OUT}/ov_${String(++shotN).padStart(2, '0')}_${combo}_${view.replace(/[^\w-]/g, '_')}.png` });
  }

  // 4.7：最小支持分辨率 1280×720（紧凑布局自动打开），1680×960 是常见的大屏
  const combos = QUICK ? [['light', 1280, 720]] : [['light', 1280, 720], ['light', 1680, 960], ['light', 1680, 1050]]   // 5.0.1 只有浅色;
  for (const [theme, w, h] of combos) {
    const combo = `${theme}${w}`;
    // ---- 开始页（管理员）、教学页（老师） ----
    let p = await page(admin, w, h, theme);
    await p.goto(B + '/', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500); await dismiss(p);
    await scan(p, 'welcome', combo);
    await p.context().close();
    p = await page(T, w, h, theme);
    await p.goto(B + '/teach', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500); await dismiss(p);
    await scan(p, 'teach-teacher', combo);
    const ttabs = await p.$$eval('.el-tabs__item', (ts) => ts.map((t) => t.id).filter(Boolean));
    for (const t of ttabs.slice(0, 8)) { await p.locator('#' + t).click().catch(() => null); await p.waitForTimeout(1000); await scan(p, 'teach-teacher:' + t, combo); }
    await p.context().close();

    // ---- 工作台（管理员）：右栏页签、每个浮窗 ----
    p = await page(admin, w, h, theme);
    await p.goto(`${B}/p/${PLANT}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.ed-act button[data-panel]', { timeout: 60000 }); await p.waitForTimeout(6000); await dismiss(p);
    await p.evaluate(() => { const e = window.__vfEd; e.sel = [(e.model.blocks.find((x) => x.type === 'processor') || e.model.blocks[0]).id]; }); await p.waitForTimeout(800);
    for (const t of await p.$$eval('.ed-right .el-tabs__item', (ts) => ts.map((x) => x.id))) {
      await p.locator(`.ed-right #${t}`).click().catch(() => null); await p.waitForTimeout(1300); await scan(p, 'wb-right:' + t.replace('tab-', ''), combo);
    }
    // 三维设备标签：总览视角下带底色的标签不互相压住（相机拉远时会挤，只在 1680 宽检查，报出来供参考）
    await p.evaluate(() => window.__vfScene?.viewPreset?.('overview')); await p.waitForTimeout(2500);
    const lb = await p.evaluate(() => window.__vfScan.labels());
    labelInfo.push(`${combo}: ${lb.n} 个标签，${lb.over.length} 对压住 ${JSON.stringify(lb.over.slice(0, 5))}`);
    if (w >= 1680) labelOver += lb.over.length;
    const floats = await p.$$eval('.ed-act button.float[data-panel]', (bs) => bs.map((x) => x.getAttribute('data-panel')));
    for (const id of floats) {
      await p.locator(`.ed-act button[data-panel="${id}"]`).click(); await p.waitForTimeout(3500);
      await scan(p, 'float:' + id, combo);
      await p.locator(`.fw[data-float="${id}"] .fw-b[title="关闭"]`).click().catch(() => null); await p.waitForTimeout(300);
    }
    const lefts = await p.$$eval('.ed-act button:not(.float)[data-panel]', (bs) => bs.map((x) => x.getAttribute('data-panel')));
    for (const id of lefts) {
      await p.evaluate((id) => { const e = window.__vfEd; e.leftPanel = id; e.leftOpen = true; }, id); await p.waitForTimeout(1500);
      await scan(p, 'left:' + id, combo);
    }
    await p.context().close();

    // ---- 学生：PLC 课任务面板每个页签 ----
    p = await page(S, w, h, theme);
    await p.goto(`${B}/p/${encodeURIComponent(cellSb)}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.task-panel', { timeout: 60000 }).catch(() => null); await p.waitForTimeout(6000); await dismiss(p);
    for (const t of await p.$$eval('.task-panel .el-tabs__item', (ts) => ts.map((x) => x.id))) {
      await p.locator(`.task-panel #${t}`).click().catch(() => null); await p.waitForTimeout(1300); await scan(p, 'task-cell:' + t.replace('tab-', ''), combo);
    }
    await p.context().close();
    // ---- 学生：产线课（运行中：目标与作答里有"目标：… 当前 …（估计）"） ----
    if (plantAid) {
      const sb = (await api(S, 'POST', `/api/teach/assignments/${plantAid}/sandbox`, {})).pid;
      await api(S, 'POST', `/api/p/${encodeURIComponent(sb)}/ctl`, { action: 'play', speed: 300 });
      p = await page(S, w, h, theme);
      await p.goto(`${B}/p/${encodeURIComponent(sb)}/workbench`, { waitUntil: 'domcontentloaded' });
      await p.waitForSelector('.task-panel', { timeout: 60000 }).catch(() => null); await p.waitForTimeout(7000); await dismiss(p);
      for (const t of await p.$$eval('.task-panel .el-tabs__item', (ts) => ts.map((x) => x.id))) {
        await p.locator(`.task-panel #${t}`).click().catch(() => null); await p.waitForTimeout(2500); await scan(p, 'task-plant:' + t.replace('tab-', ''), combo);
      }
      if (combo === 'light1280') await p.screenshot({ path: `${OUT}/task_plant_goals_light1280.png` });
      if (combo === 'light1680') await p.screenshot({ path: `${OUT}/task_plant_goals_light1680.png` });
      // 分析浮窗（学生产线课里也有）
      await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'analysis' } }))); await p.waitForTimeout(3500);
      await scan(p, 'task-plant:analysis', combo);
      await p.context().close();
    }
  }
  ok('产线课找到了第 1 课', !!plantAid, plantAid);
  const list = [...found.values()];
  ok(`没有文字压在一起（扫了 ${scans} 个画面）`, list.length === 0,
    list.map((o) => `\n  [${o.view}] 「${o.a}」×「${o.b}」 ${o.ea} / ${o.eb} @${o.where} ${JSON.stringify(o.rect)} (${[...new Set(o.combos)].join(',')})`).join(''));
  ok('三维设备标签（总览、1680 宽）不互相压住', labelOver === 0, labelInfo.join(' | '));
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
