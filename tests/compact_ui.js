// 4.7 最小分辨率 1280×720 与紧凑布局（B 机，先启动 serve；客户端页面要 VF_CLIENT_URL）：node tests/compact_ui.js
// 1280×720 下逐页扫描主要页面：开始页、全部工厂、课程页（老师 / 学生）、教学控制台（老师）、生产计划、实验、信号中心、帮助、
// 工作台四个视图（三维 / 平面 / 流程 / 架构）；有 VF_CLIENT_URL 时再扫客户端的设置页和 MES 页。每页检查：
//   紧凑布局自动打开（html.compact）；页面没有横向滚动条；工具栏里的按钮都在工具栏和窗口里（没被挤出去 / 裁掉）；
//   看得见的文字不互相压住（ui_scan.js 的 overlaps）；看得见的弹出层没被裁掉。
// 另外：1680×960 时紧凑布局自动关闭；设置里"紧凑布局：总是开 / 总是关"能覆盖自动判断；工作台的右栏能收起、时间轴能隐藏、
// 第二行工具栏放不下的按钮收进"更多"菜单。浅色 + 深色截图（1280×720 和 1680×960）在 SHOT_DIR。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const { SCAN } = require('./ui_scan');
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'compact');
const CL = process.env.VF_CLIENT_URL || '';
const PLANT = process.env.VF_PLANT || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(typeof detail === 'string' ? detail : JSON.stringify(detail)).slice(0, 3000)); };
const api = async (base, tok, m, u, b) => { const r = await fetch(base + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); };
const login = async (u, p) => (await api(B, '', 'POST', '/api/login', { username: u, password: p })).token;

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = ((await api(B, admin, 'GET', '/api/admin/users')).users || []).map((u) => u.username);
  if (!users.includes('cp_teacher')) await api(B, admin, 'POST', '/api/admin/users', { username: 'cp_teacher', name: '紧凑老师', role: 'teacher', password: 'teach123' });
  const T = await login('cp_teacher', 'teach123');
  const cls = await api(B, T, 'POST', '/api/teach/classes', { name: `紧凑测试班 ${stamp}` });
  const stu = `cp${stamp}`;
  await api(B, T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},紧凑同学\n`, default_password: '123456' });
  await api(B, T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's01_motor_latch', title: '电机启停自锁（紧凑测试）' });
  await api(B, T, 'POST', '/api/teach/courses/machining/publish', { class_id: cls.id, open_all: true });
  const S = await login(stu, '123456');
  let CT = '';
  if (CL) CT = (await api(CL, '', 'POST', '/api/desktop/standalone', {})).token || '';

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  async function page(tok, w, h, theme = 'light', extra = {}) {
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
    await ctx.addInitScript(([t, th, ex]) => {
      if (sessionStorage.getItem('cp_init')) return; sessionStorage.setItem('cp_init', '1');
      localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_ws', 'all');
      sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_guide_off', '1'); localStorage.setItem('vf_teach_tour', '1'); localStorage.removeItem('vf_wb2_sizes');
      localStorage.setItem('vf_whatsnew_seen', '9.9.9'); localStorage.setItem('vf_start_tour_done', '1');
      for (const [k, v] of Object.entries(ex)) { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); }
    }, [tok, theme, extra]);
    await ctx.addInitScript({ content: SCAN });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    p.on('dialog', (d) => d.dismiss());
    return p;
  }
  const dismiss = async (p) => { for (const t of ['以后再说', '跳过', '知道了', '自己做', '关闭']) { const x = p.locator(`.el-dialog .el-button:has-text("${t}"), .tour-ask button:has-text("${t}")`).first(); if (await x.isVisible().catch(() => false)) await x.click().catch(() => null); } };
  /** 一页的检查结果：紧凑开没开、横向滚动、工具栏挤出、文字重叠、弹出层裁剪。 */
  const probe = (p) => p.evaluate(() => {
    const de = document.documentElement;
    const hscroll = de.scrollWidth > innerWidth + 1 || document.body.scrollWidth > innerWidth + 1;
    const out = [];
    for (const bar of document.querySelectorAll('.ed-menu, .ed-bar, .page-head, .tp-head, .v3-bar, .pv-tools, .tc-head, .cs-head, .mes-bar')) {
      const br = bar.getBoundingClientRect();
      if (br.width < 2 || br.height < 2 || !bar.getClientRects().length) continue;
      for (const c of bar.querySelectorAll(':scope > *')) {
        const r = c.getBoundingClientRect(), cs = getComputedStyle(c);
        if (r.width < 2 || r.height < 2 || cs.visibility === 'hidden' || cs.display === 'none') continue;
        if (r.right > Math.min(innerWidth, br.right) + 1 || r.left < Math.max(0, br.left) - 1 || r.bottom > innerHeight + 1)
          out.push(`${bar.className.split(' ')[0]} > ${String(c.className || c.tagName).split(' ')[0]} "${(c.innerText || '').trim().slice(0, 16)}" [${Math.round(r.left)},${Math.round(r.right)}] bar [${Math.round(br.left)},${Math.round(br.right)}]`);
      }
    }
    // 输入框 / 按钮横向被裁掉一截（父容器 overflow: hidden 或窗口边；能横向滚动的容器不算）
    const cut = [];
    for (const e of document.querySelectorAll('.el-input, .el-input-number, .el-select, .el-button, .el-radio-button, .el-switch, .el-date-editor')) {
      if (!e.getClientRects().length || e.closest('.el-popper, .vt-root, .labels, .el-table, .vue-flow')) continue;
      const r = e.getBoundingClientRect(); if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight) continue;
      let x0 = 0, x1 = innerWidth, scroller = false;
      for (let q = e.parentElement; q && q !== document.body; q = q.parentElement) {
        const cs = getComputedStyle(q);
        if (cs.display === 'none' || cs.visibility === 'hidden') { scroller = true; break; }
        if (/(auto|scroll)/.test(cs.overflowX) && !q.classList.contains('el-scrollbar__wrap')) { scroller = true; break; }   // el-scrollbar 的横向滚动条几乎看不见：当裁剪算
        if (q.classList.contains('el-scrollbar__wrap')) { const b = q.getBoundingClientRect(); x0 = Math.max(x0, b.left); x1 = Math.min(x1, b.right); continue; }
        if (/(hidden|clip)/.test(cs.overflowX)) { const b = q.getBoundingClientRect(); x0 = Math.max(x0, b.left); x1 = Math.min(x1, b.right); }
        if (cs.position === 'fixed') break;
      }
      if (!scroller && (r.right > x1 + 2 || r.left < x0 - 2) && Math.min(r.right, x1) - Math.max(r.left, x0) > 0)
        cut.push(`${String(e.className).split(' ')[0]} "${(e.innerText || e.querySelector('input')?.value || '').trim().slice(0, 14)}" [${Math.round(r.left)},${Math.round(r.right)}] 可见到 ${Math.round(x1)}`);
    }
    const pops = window.__vfScan.poppers().filter((x) => x.clipped || x.outOfView);
    return { compact: de.classList.contains('compact'), hscroll, sw: de.scrollWidth, toolbar: out, cut, overlaps: window.__vfScan.overlaps().map((o) => `「${o.a}」×「${o.b}」 ${o.ea} / ${o.eb} ${JSON.stringify(o.rect)}`), pops: pops.map((x) => x.what) };
  });
  const bad = [];
  let pages = 0;
  async function check(p, name, W, H, theme, shotIt = true) {
    await p.waitForTimeout(600);
    const r = await probe(p);
    pages++;
    const wantCompact = W < 1366 || H < 800;
    const probs = [];
    if (r.compact !== wantCompact) probs.push(`紧凑=${r.compact}`);
    if (r.hscroll) probs.push(`横向滚动 ${r.sw}`);
    if (r.toolbar.length) probs.push('工具栏挤出：' + r.toolbar.slice(0, 6).join(' ; '));
    if (r.cut.length) probs.push('控件被裁掉：' + r.cut.slice(0, 6).join(' ; '));
    if (r.overlaps.length) probs.push('文字重叠：' + r.overlaps.slice(0, 6).join(' ; '));
    if (r.pops.length) probs.push('弹出层裁剪：' + r.pops.slice(0, 4).join(' ; '));
    if (probs.length) bad.push(`[${name} ${W}×${H} ${theme}] ${probs.join(' | ')}`);
    if (shotIt) await p.screenshot({ path: `${OUT}/${name.replace(/[^\w-]/g, '_')}_${W}x${H}_${theme}.png` });
    return r;
  }

  for (const [W, H, theme] of [[1280, 720, 'light'], [1680, 960, 'light']]) {   // 5.0.1 只有浅色
    // ---- 管理员：开始页、全部工厂、生产计划、实验、信号中心、帮助 ----
    let p = await page(admin, W, H, theme);
    for (const [name, url] of [['welcome', '/welcome'], ['plants', '/'], ['plan', `/p/${PLANT}/plan`], ['experiments', `/p/${PLANT}/experiments`], ['signals', `/p/${PLANT}/signals`], ['help', '/help']]) {
      await p.goto(B + url, { waitUntil: 'networkidle' }).catch(() => null); await p.waitForTimeout(2200); await dismiss(p);
      await check(p, name, W, H, theme);
    }
    // ---- 工作台四个视图 ----
    await p.goto(`${B}/p/${PLANT}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.ed-act button[data-panel]', { timeout: 60000 }); await p.waitForTimeout(6000); await dismiss(p);
    for (const v of ['3d', 'plan', 'graph', 'arch']) {
      await p.evaluate((v) => { window.__vfEd.view = v; }, v); await p.waitForTimeout(2500);
      await check(p, 'workbench-' + v, W, H, theme);
    }
    if (W === 1280 && theme === 'light') {
      // 右栏收起 / 展开、时间轴隐藏 / 显示、第二行放不下的收进"更多"
      const r0 = await p.evaluate(() => ({ right: !!document.querySelector('.ed-right'), tl: !!document.querySelector('.ed-bottom .tl, .ed-bottom') }));
      await p.locator('[data-k="right-toggle"]').first().click().catch(() => null); await p.waitForTimeout(800);
      const r1 = await p.evaluate(() => ({ right: !!document.querySelector('.ed-right'), btn: !!document.querySelector('[data-k="right-toggle"]') }));
      ok('1280×720 工作台：右栏可以收起（按钮还在，可再展开）', r0.right && !r1.right && r1.btn, JSON.stringify([r0, r1]));
      await p.screenshot({ path: `${OUT}/workbench_right_folded_1280x720.png` });
      await p.locator('[data-k="right-toggle"]').first().click().catch(() => null); await p.waitForTimeout(600);
      await p.locator('[data-k="timeline-toggle"]').first().click().catch(() => null); await p.waitForTimeout(800);
      const t1 = await p.evaluate(() => ({ tl: !!document.querySelector('.ed-bottom'), btn: !!document.querySelector('[data-k="timeline-toggle"]') }));
      ok('1280×720 工作台：时间轴可以隐藏', !t1.tl && t1.btn, JSON.stringify(t1));
      await p.screenshot({ path: `${OUT}/workbench_timeline_hidden_1280x720.png` });
      await p.locator('[data-k="timeline-toggle"]').first().click().catch(() => null); await p.waitForTimeout(600);
      const more = p.locator('[data-k="bar-more"]');
      const hasMore = await more.isVisible().catch(() => false);
      let items = [];
      if (hasMore) { await more.click(); await p.waitForTimeout(500); items = await p.$$eval('.el-dropdown-menu:visible .el-dropdown-menu__item, .bar-more-pop .el-dropdown-menu__item', (xs) => xs.filter((x) => x.getClientRects().length).map((x) => x.innerText.trim())); await p.keyboard.press('Escape'); }
      ok('1280×720 工作台：第二行放不下的按钮收进"更多"菜单', hasMore && items.length >= 2, items.join('、'));
    }
    await p.context().close();
    // ---- 老师：教学控制台、课程页 ----
    p = await page(T, W, H, theme);
    await p.goto(B + '/teach', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500); await dismiss(p);
    await check(p, 'teach-console', W, H, theme);
    // 发布课程向导（"开一节课"：选班级 → 学生名单 → 选课程并发布）和"发布课程"：整个弹窗（背景板）在窗口里，内容不跑出背景板，底部按钮看得见
    const dlgCheck = async (label) => p.evaluate(() => {
      const d = [...document.querySelectorAll('.el-dialog')].filter((x) => x.getClientRects().length && getComputedStyle(x).display !== 'none').pop();
      if (!d) return { found: false };
      const r = d.getBoundingClientRect();
      const out = [...d.querySelectorAll('.el-dialog__body *')].filter((e) => e.getClientRects().length && getComputedStyle(e).position !== 'fixed').map((e) => [e, e.getBoundingClientRect()])
        .filter(([, q]) => q.width > 1 && q.height > 1 && (q.right > r.right + 1 || q.left < r.left - 1 || q.bottom > r.bottom + 1))
        .map(([e, q]) => `${String(e.className).split(' ')[0] || e.tagName} [${Math.round(q.left)},${Math.round(q.top)},${Math.round(q.right)},${Math.round(q.bottom)}]`);
      const btns = [...d.querySelectorAll('button')].filter((b) => /发布课程|下一步|发布/.test(b.innerText) && b.getClientRects().length);
      const btnOk = btns.length > 0 && btns.every((b) => { const q = b.getBoundingClientRect(); return q.bottom <= innerHeight && q.top >= 0; });
      const bg = getComputedStyle(d).backgroundColor;
      return { found: true, inView: r.top >= -1 && r.bottom <= innerHeight + 1, rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], out: out.slice(0, 5), btnOk, bg,
        opaque: !/rgba\(.*,\s*0\)$/.test(bg) && bg !== 'transparent' };
    });
    const lw = p.locator('button:has-text("开一节课")').first();
    if (await lw.isVisible().catch(() => false)) {
      await lw.click(); await p.waitForTimeout(1200);
      const steps = [];
      steps.push(await dlgCheck('step1'));
      for (let i = 0; i < 2; i++) {
        const nx = p.locator('.el-dialog .lw-foot button:has-text("下一步")').first();
        if (!(await nx.isVisible().catch(() => false))) break;
        if (i === 1 && await nx.isDisabled()) {            // 第二步：这个班已有学生就能直接下一步；没有就粘贴一个
          await p.locator('.el-dialog textarea').first().fill(`学号\t姓名\ncpx${stamp}\t补充同学`); await p.waitForTimeout(1500);
          await p.locator('.el-dialog button:has-text("导入名单")').first().click().catch(() => null); await p.waitForTimeout(1500);
        }
        await nx.click().catch(() => null); await p.waitForTimeout(1500);
        steps.push(await dlgCheck('step' + (i + 2)));
      }
      await p.screenshot({ path: `${OUT}/lesson_wizard_step3_${W}x${H}_${theme}.png` });
      const bad3 = steps.filter((s) => !s.found || !s.inView || s.out.length || !s.btnOk || !s.opaque);
      ok(`"开一节课"向导三步（${W}×${H} ${theme}）：背景板整个在窗口里、内容不出背景板、按钮看得见`, steps.length === 3 && !bad3.length, JSON.stringify(steps));
      await p.keyboard.press('Escape'); await p.waitForTimeout(600);
    } else ok(`"开一节课"按钮（${W}×${H}）`, false, '没找到');
    const cpb = p.locator('button:has-text("发布课程")').first();
    if (await cpb.isVisible().catch(() => false)) {
      await cpb.click(); await p.waitForTimeout(1500);
      const s = await dlgCheck('course-publish');
      await p.screenshot({ path: `${OUT}/course_publish_${W}x${H}_${theme}.png` });
      ok(`"发布课程"弹窗（${W}×${H} ${theme}）：背景板整个在窗口里、内容不出背景板、按钮看得见`, s.found && s.inView && !s.out.length && s.btnOk && s.opaque, JSON.stringify(s));
      await p.keyboard.press('Escape'); await p.waitForTimeout(600);
    }
    await p.goto(B + '/courses', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500); await dismiss(p);
    await check(p, 'courses-teacher', W, H, theme);
    await p.context().close();
    // ---- 学生：课程页 ----
    p = await page(S, W, H, theme);
    await p.goto(B + '/courses', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500); await dismiss(p);
    await check(p, 'courses-student', W, H, theme);
    await p.context().close();
    // ---- 客户端：设置、MES ----
    if (CL && CT) {
      const cp = await page(CT, W, H, theme);
      for (const [name, url] of [['client-settings', '/settings'], ['client-mes', '/mes'], ['client-mine', '/mine']]) {
        await cp.goto(CL + url, { waitUntil: 'networkidle' }).catch(() => null); await cp.waitForTimeout(2500); await dismiss(cp);
        await check(cp, name, W, H, theme);
      }
      await cp.context().close();
    }
  }

  // ---- 设置覆盖自动判断 ----
  {
    const p = await page(admin, 1680, 960, 'light', { vf_compact: 'on' });
    await p.goto(B + '/welcome', { waitUntil: 'networkidle' }); await p.waitForTimeout(1500);
    const on = await p.evaluate(() => document.documentElement.classList.contains('compact'));
    await p.context().close();
    const q = await page(admin, 1280, 720, 'light', { vf_compact: 'off' });
    await q.goto(B + '/welcome', { waitUntil: 'networkidle' }); await q.waitForTimeout(1500);
    const off = await q.evaluate(() => document.documentElement.classList.contains('compact'));
    await q.context().close();
    ok('设置"紧凑布局：总是开 / 总是关"覆盖自动判断', on && !off, JSON.stringify({ on, off }));
  }

  ok(`1280×720 / 1680×960 主要页面没有横向滚动、工具栏挤出、文字重叠、弹出层裁剪，紧凑布局按窗口大小自动开关（${pages} 个画面）`, bad.length === 0, '\n  ' + bad.join('\n  '));
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  console.log('截图：', OUT);
  await b.close();
})();
