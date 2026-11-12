// 开始页 / 命令面板 / F1 帮助 / 新功能（4.5）界面测试（B 机，先启动 serve）：node tests/welcome_ui.js
// 四个角色的开始页、最近打开（进过工作台后有缩略图）、从模板新建、Ctrl+K 找到并执行操作、F1 打开对应的帮助、版本变了弹"新功能"、页面没有报错。
// 截图：1280 / 1680 / 2560（5.0.1 起只有浅色）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'welcome');
const CELL = process.env.VF_CELL_PLANT || 'plctest';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, m, u, b) => { const r = await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); };
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const admin = await login('admin', 'honey123');
  const users = ((await api(admin, 'GET', '/api/admin/users')).users || []).map((u) => u.username);
  for (const [u, n, r, p] of [['wc_teacher', '周老师', 'teacher', 'teach123'], ['wc_eng', '吴工', 'engineer', 'eng12345']])
    if (!users.includes(u)) await api(admin, 'POST', '/api/admin/users', { username: u, name: n, role: r, password: p });
  const T = await login('wc_teacher', 'teach123'), E = await login('wc_eng', 'eng12345');
  let cls = (await api(T, 'GET', '/api/teach/classes')).find((c) => c.name === '开始页测试班');
  if (!cls) { const r = await api(T, 'POST', '/api/teach/classes', { name: '开始页测试班' }); cls = { id: r.id }; }
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: '账号,姓名\nwc_stu1,郑同学\n', default_password: '123456' });
  await api(T, 'POST', '/api/teach/courses/plc_basics/publish', { class_id: cls.id, open_all: false });
  const due = new Date(Date.now() + 86400e3).toISOString().slice(0, 16).replace('T', ' ');
  let hw = (await api(T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).find((a) => !a.course);
  if (!hw) { const r = await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's03_conveyor', title: '传送带启停（开始页测试）', due }); hw = { id: r.id }; }
  const S = await login('wc_stu1', '123456');
  // 学生交一次（给老师的"待复核"）：建沙箱再提交，评分失败也算一份提交
  try { await api(S, 'POST', `/api/teach/assignments/${hw.id}/sandbox`, {}); await api(S, 'POST', `/api/teach/assignments/${hw.id}/submit`, {}); } catch { /* */ }
  const health = await (await fetch(B + '/api/health')).json();

  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const br = await pw.chromium.launch({ channel: 'chrome', args });
  const errs = [];
  const page = async (tok, { w = 1680, h = 960, dark = false, seen = 'current' } = {}) => {
    const ctx = await br.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
    await ctx.addInitScript(([t, d, s]) => {
      if (sessionStorage.getItem('wc_init')) return; sessionStorage.setItem('wc_init', '1');
      localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); sessionStorage.setItem('vf_pw_later', '1');
      localStorage.setItem('vf_teach_tour', '1'); localStorage.setItem('vf_guide_off', '1');
      if (s) localStorage.setItem('vf_seen_version', s);
    }, [tok, dark, seen === 'current' ? health.version : seen]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
    p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404|Failed to load resource|ResizeObserver/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
    p.on('response', (r) => { if (r.status() >= 500) errs.push(`${r.status()} ${r.url().replace(B, '')}`); });
    return p;
  };
  const shot = (p, n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const palette = async (p, q) => {
    if (!(await p.locator('[data-k="cmdp"]').count())) await p.keyboard.press('Control+K');
    await p.waitForSelector('[data-k="cmdp"]', { timeout: 5000 }).catch(() => null);
    await p.fill('[data-k="cmdp-q"]', q); await p.waitForTimeout(350);
    return p.locator('.cmdp-i').first().innerText().catch(() => '');
  };
  const helpId = async (p) => { await p.waitForTimeout(900); return p.locator('.help-drawer [data-help-id]').getAttribute('data-help-id').catch(() => ''); };

  // ---------- 管理员：打开 / → 开始页；服务器状态 ----------
  const a = await page(admin);
  await a.goto(B + '/', { waitUntil: 'networkidle' }); await a.waitForTimeout(1500);
  ok('管理员：打开首页先到开始页', /\/welcome$/.test(a.url()) && (await a.locator('[data-k="welcome"][data-role="admin"]').count()) === 1, a.url());
  ok('管理员：服务器状态（版本、工厂、沙箱）', /\d+\.\d+/.test(await a.locator('[data-k="wc-server"]').innerText().catch(() => '')), (await a.locator('[data-k="wc-server"]').innerText().catch(() => '')).replace(/\s+/g, ' '));
  ok('管理员：学习 / 资源 / 提示', (await a.locator('[data-k="wc-learn"] .wc-li').count()) >= 2 && (await a.locator('[data-k="wc-res"] a').count()) >= 3 && (await a.locator('[data-k="welcome-tip"] p').innerText()).length > 10);
  ok('页面标题：蜂元虚拟工厂 · 开始', (await a.title()) === '蜂元虚拟工厂 · 开始', await a.title());
  ok('侧栏有"开始"并选中', (await a.locator('.side .el-menu-item.is-active[data-k="menu-welcome"]').count()) === 1);
  await shot(a, 'w01_admin_1680');
  // 最近打开：进一次工作台，再用命令面板回开始页（应用内跳转，离开时截缩略图）
  await a.goto(`${B}/p/foundry-housing/workbench`, { waitUntil: 'networkidle' }); await a.waitForTimeout(9000);
  ok('工作台标题带工厂名', /蜂元虚拟工厂 · 工作台 · /.test(await a.title()), await a.title());
  const first = await palette(a, '开始页');
  ok('Ctrl+K：找到"开始页"', /开始页/.test(first), first);
  await a.keyboard.press('Enter'); await a.waitForTimeout(2000);
  const rc = a.locator('[data-k="wc-recent"] .wc-pc[data-pid="foundry-housing"]');
  const src = await rc.locator('img').getAttribute('src').catch(() => '');
  ok('最近打开：刚进过的工厂排第一，有缩略图', /\/welcome$/.test(a.url()) && (await a.locator('[data-k="wc-recent"] .wc-pc').first().getAttribute('data-pid')) === 'foundry-housing' && /^data:image\/(jpeg|svg)/.test(src || ''),
    (src || '').slice(0, 30));
  ok('缩略图是三维截图（不是草图）', /^data:image\/jpeg/.test(src || ''), (src || '').slice(0, 30));
  await shot(a, 'w02_admin_recent');

  // ---------- 新功能：版本变了才弹 ----------
  const n1 = await page(admin, { seen: '4.2.0' });
  await n1.goto(B + '/welcome', { waitUntil: 'networkidle' }); await n1.waitForTimeout(1800);
  const vers = await n1.locator('[data-k="whatsnew"] .wn-ver').evaluateAll((xs) => xs.map((x) => x.getAttribute('data-ver')));
  ok('版本变了：弹出"新功能"，列出看过之后的版本', vers.length >= 1 && vers.includes('4.3') && !vers.includes('4.2'), vers.join(','));
  await shot(n1, 'w03_whatsnew');
  await n1.click('[data-k="whatsnew-ok"]'); await n1.waitForTimeout(500);
  ok('"知道了"之后记住当前版本', (await n1.evaluate(() => localStorage.getItem('vf_seen_version'))) === health.version);
  await n1.reload({ waitUntil: 'networkidle' }); await n1.waitForTimeout(1500);
  ok('再打开不再弹', (await n1.locator('[data-k="whatsnew"]:visible').count()) === 0);
  await n1.locator('[data-k="wc-whatsnew"]').click(); await n1.waitForTimeout(600);
  ok('开始页"资源"里能再打开新功能', (await n1.locator('[data-k="whatsnew"]:visible').count()) === 1);
  await n1.click('[data-k="whatsnew-ok"]');
  const n0 = await page(admin, { seen: '' });
  await n0.goto(B + '/welcome', { waitUntil: 'networkidle' }); await n0.waitForTimeout(1800);
  ok('第一次用（没记过版本）不弹', (await n0.locator('[data-k="whatsnew"]:visible').count()) === 0 && (await n0.evaluate(() => localStorage.getItem('vf_seen_version'))) === health.version);
  await n0.context().close(); await n1.context().close();

  // ---------- 工程师：从模板新建 ----------
  const e = await page(E);
  await e.goto(B + '/', { waitUntil: 'networkidle' }); await e.waitForTimeout(1500);
  const tpl = await e.locator('[data-k="wc-new"] .wc-tpl').count();
  const sk = await e.locator('[data-k="wc-new"] .wc-tpl[data-tpl="showcase"] img').getAttribute('src').catch(() => '');
  ok('工程师：开始页有"新建"，模板带布局预览', /\/welcome$/.test(e.url()) && tpl >= 5 && /^data:image\/svg/.test(sk || ''), `${tpl} 个模板`);
  await shot(e, 'w04_engineer_1680');
  await e.locator('[data-k="wc-new"] .wc-tpl[data-tpl^="cells/"]').first().click(); await e.waitForTimeout(500);
  await e.fill('input[data-k="wc-new-name"]', '开始页新建测试');
  await e.click('[data-k="wc-new-create"]');
  await e.waitForURL(/\/p\/[^/]+\/workbench/, { timeout: 60000 }).catch(() => null); await e.waitForTimeout(6000);
  const newPid = (e.url().match(/\/p\/([^/]+)\/workbench/) || [])[1] || '';
  ok('从模板新建：建好直接进工作台', !!newPid && (await e.evaluate(() => (window).__vfEd?.model?.plant?.name)) === '开始页新建测试', e.url());
  // 工作台里的命令面板
  await e.evaluate(() => { (window).__vfEd.view = '3d'; });
  let t1 = await palette(e, '切换到平面');
  await shot(e, 'w05_palette_wb');
  await e.keyboard.press('Enter'); await e.waitForTimeout(800);
  ok('Ctrl+K "切换到平面" → 平面图', /切换到平面/.test(t1) && (await e.evaluate(() => (window).__vfEd.view)) === 'plan', t1);
  t1 = await palette(e, '打开 PLC 编程');
  await e.keyboard.press('Enter'); await e.waitForTimeout(1500);
  ok('Ctrl+K "打开 PLC 编程" → PLC 侧栏', /PLC 编程/.test(t1) && (await e.evaluate(() => (window).__vfEd.leftPanel)) === 'plc-editor', t1);
  // F1：鼠标在 PLC 侧栏上 → PLC；在平面图上 → 分层与视图
  const left = await e.locator('.ed-left').boundingBox().catch(() => null);
  if (left) await e.mouse.move(left.x + left.width / 2, left.y + left.height / 2);
  await e.keyboard.press('F1');
  ok('F1（PLC 编程里）→ 帮助"PLC 编程"', (await helpId(e)) === 'plc', await helpId(e));
  await shot(e, 'w06_f1_plc');
  await e.keyboard.press('F1'); await e.waitForTimeout(300);
  const vb = await e.locator('.vp-b').boundingBox().catch(() => null);
  if (vb) await e.mouse.move(vb.x + vb.width / 2, vb.y + vb.height / 2);
  await e.keyboard.press('F1');
  ok('F1（平面图上）→ 帮助"分层"', (await helpId(e)) === 'layers', await helpId(e));
  ok('F1 是抽屉，不跳页面', /\/workbench$/.test(e.url()));
  await e.keyboard.press('Escape'); await e.waitForTimeout(300);
  // 运行：先暂停，再用命令面板"运行"
  await api(E, 'POST', `/api/p/${newPid}/ctl`, { action: 'pause' }); await e.waitForTimeout(1500);
  t1 = await palette(e, '运行');
  await e.keyboard.press('Enter'); await e.waitForTimeout(3500);
  const md = await e.evaluate(() => (window).__vfEd.runtime?.ctl?.mode);
  ok('Ctrl+K "运行" → 运行中', /^运行/.test(t1) && md === 'running', `${t1} / ${md}`);
  t1 = await palette(e, '暂停');
  ok('运行中时命令变成"暂停"，标出快捷键', /暂停/.test(t1) && /F6/.test(t1), t1.replace(/\s+/g, ' '));
  await e.keyboard.press('Escape');
  // 最近用过的排最前
  await e.keyboard.press('Control+K'); await e.waitForTimeout(400);
  const rec = await e.locator('.cmdp-g').first().innerText().catch(() => '');
  const r1 = await e.locator('.cmdp-i').first().getAttribute('data-cmd').catch(() => '');
  ok('没输入时"最近使用"在最前', rec === '最近使用' && /^wb\./.test(r1 || ''), `${rec} ${r1}`);
  await e.keyboard.press('Escape');
  // 设备搜索 / 帮助搜索
  const bid = await e.evaluate(() => (window).__vfEd.model.blocks[0]?.id || '');
  t1 = await palette(e, bid);
  ok('Ctrl+K 输入设备编号 → 定位', /定位/.test(t1), t1);
  t1 = await palette(e, '断点');
  ok('Ctrl+K 能搜到面板和帮助', (await e.locator('.cmdp-i[data-cmd^="wb.panel.breakpoints"]').count()) === 1 && (await e.locator('.cmdp-i[data-cmd^="help."]').count()) >= 1, t1);
  await e.keyboard.press('Escape');
  if (newPid) await api(admin, 'DELETE', '/api/plants/' + newPid);

  // ---------- 学生：继续上次的课、作业 ----------
  const s = await page(S);
  await s.goto(B + '/', { waitUntil: 'networkidle' }); await s.waitForTimeout(2000);
  ok('学生：打开首页先到开始页', /\/welcome$/.test(s.url()) && (await s.locator('[data-k="welcome"][data-role="student"]').count()) === 1, s.url());
  ok('学生："继续上次的课"指向 PLC 第一课', /电机启停自锁/.test(await s.locator('[data-k="wc-continue"]').innerText().catch(() => '')));
  ok('学生：快到期的作业', /传送带启停/.test(await s.locator('[data-k="wc-homework"]').innerText().catch(() => '')));
  ok('学生（网页端）：没有"新建"，没有"全部工厂"', (await s.locator('[data-k="wc-new"]').count()) === 0 && (await s.locator('[data-k="wc-allplants"]').count()) === 0);
  await shot(s, 'w07_student_1680');
  const sp = await palette(s, '全部工厂');
  ok('学生的命令面板里没有"全部工厂"', !/^全部工厂/.test(sp), sp);
  await s.keyboard.press('Escape');
  await s.locator('[data-k="wc-continue-btn"]').click(); await s.waitForTimeout(3500);
  ok('点"开始"进到教学页的这一课', /\/teach/.test(s.url()) && /电机启停自锁/.test(await s.locator('.teach-page').innerText().catch(() => '')), s.url());
  await s.mouse.move(800, 500); await s.keyboard.press('F1');
  ok('F1（学生在教学页）→ "学生五步"', (await helpId(s)) === 'stu', await helpId(s));
  await s.keyboard.press('F1');

  // ---------- 老师：班级进度、待复核；教学页 F1 ----------
  const t = await page(T);
  await t.goto(B + '/', { waitUntil: 'networkidle' }); await t.waitForTimeout(3000);
  ok('老师：打开首页先到开始页', /\/welcome$/.test(t.url()) && (await t.locator('[data-k="welcome"][data-role="teacher"]').count()) === 1, t.url());
  ok('老师：班级进度', /开始页测试班/.test(await t.locator('[data-k="wc-classes"]').innerText().catch(() => '')));
  const rv = await t.locator('[data-k="wc-review"]').innerText().catch(() => '');
  ok('老师：待复核（列表或空状态）', /份|没有等着复核/.test(rv), rv.replace(/\s+/g, ' ').slice(0, 80));
  await shot(t, 'w08_teacher_1680');
  await t.locator('[data-k="wc-cta-console"]').click(); await t.waitForTimeout(2500);
  await t.mouse.move(800, 500); await t.keyboard.press('F1');
  ok('F1（老师在教学页）→ 帮助"教学"', (await helpId(t)) === 'teach', await helpId(t));
  await shot(t, 'w09_teacher_f1_teach');
  await t.keyboard.press('Escape');
  // 关掉"启动时显示欢迎页"：下次打开直接进教学
  await t.goto(B + '/welcome', { waitUntil: 'networkidle' }); await t.waitForTimeout(1200);
  await t.locator('[data-k="welcome-onstart"]').click(); await t.waitForTimeout(300);
  await t.goto(B + '/', { waitUntil: 'networkidle' }); await t.waitForTimeout(1500);
  ok('关掉"启动时显示欢迎页"后首页不再跳开始页', !/\/welcome$/.test(t.url()), t.url());
  await t.evaluate(() => localStorage.setItem('vf_welcome_on_start', '1'));

  // ---------- 截图（5.0.1 起只有浅色）：1280 / 1680 / 2560 ----------
  for (const [w, h] of [[1280, 720], [1680, 960], [2560, 1440]]) {
    for (const [tok, who] of [[admin, 'admin'], [S, 'student']]) {
      const p = await page(tok, { w, h });
      await p.goto(B + '/welcome', { waitUntil: 'networkidle' }); await p.waitForTimeout(2200);
      if (who === 'admin' && w === 1680) {
        ok('开始页没有深色切换、页面不是深色', (await p.locator('[data-k="wc-theme"]').count()) === 0 && !(await p.evaluate(() => document.documentElement.classList.contains('dark'))));
        ok('开始页卡片是白底细边框（浅色）', await p.locator('[data-k="wc-recent"]').evaluate((e) => { const s = getComputedStyle(e); return s.backgroundColor === 'rgb(255, 255, 255)' && parseFloat(s.borderTopWidth) === 1; }));
      }
      await shot(p, `s_${who}_${w}`);
      if (who === 'admin' && w === 1680) {
        await palette(p, ''); await p.waitForTimeout(300); await shot(p, 's_palette'); await p.keyboard.press('Escape');
        await p.mouse.move(900, 500); await p.keyboard.press('F1'); await p.waitForTimeout(1000); await shot(p, 's_help'); await p.keyboard.press('F1');
      }
      await p.context().close();
    }
    const lc = await br.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
    const lp = await lc.newPage(); lp.on('pageerror', (x) => errs.push('pageerror(login): ' + x.message.slice(0, 200)));
    await lp.goto(B + '/login', { waitUntil: 'networkidle' }); await lp.waitForTimeout(1200);
    await shot(lp, `s_login_${w}`);
    await lc.close();
  }
  // 空状态：工程师的"全部工厂"在没有搜索结果的帮助里
  const hp = await page(E);
  await hp.goto(B + '/help', { waitUntil: 'networkidle' }); await hp.waitForTimeout(800);
  await hp.fill('.page-head input', 'zzzz没有这个'); await hp.waitForTimeout(400);
  ok('帮助搜索没结果：空状态插画', (await hp.locator('[data-k="empty-search"] img').count()) === 1);
  await shot(hp, 'w10_help_empty');
  const fav = await hp.evaluate(() => [...document.querySelectorAll('link[rel="icon"]')].map((l) => l.getAttribute('href')).join(' '));
  ok('favicon 用品牌图标', /\/brand\/favicon/.test(fav), fav);
  ok('侧栏是品牌标志（蜂元标志 + 产品名）', /logo-mark|\/logo\.png/.test(await hp.locator('.side .brand img').getAttribute('src') || '') && /蜂元虚拟工厂/.test(await hp.locator('.side .brand').innerText().catch(() => '')));

  ok('页面没有报错', errs.length === 0, errs.slice(0, 6).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await br.close();
})();
