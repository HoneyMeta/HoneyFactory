// 4.6 跟随教程的聚光目标验收（B 机，先启动 serve）：node tests/tour_targets_ui.js
// 四个教程（s01 电机启停自锁、s02 正反转、s03 输送带、机加工 m01）逐步走一遍：每一步先执行"带我去"（goto），
// 然后断言要点的目标在页面上、看得见（没被父容器裁掉、没被浮窗盖住）、整个在视口里，聚光圈就画在它上面。
// 另外测：目标看不到时不画空圈、卡片上提示"点「带我去」"；进入一步时目标看不到会自动"带我去"；
// 第 15 步"过载保护"从任务面板关着开始，"带我去"打开任务面板的检查表页签并把「演示」按钮滚出来。
// 小屏（1280×720）跑全部步骤，大屏（1680×960）再跑 s01；第 15 步浅色 / 深色截图。截图在 SHOT_DIR。
// 4.7：再把操作导览（web/src/panels/teach/tour/guides.ts 的注册表）每个导览的每一步在 1280×720（浅色）和 1680×960（深色）上走一遍，
// 外加「?」按钮、Ctrl+K、收起、退出后"从第 N 步继续"、刷新后接着、F1 抽屉里的导览。只跑导览部分：GUIDES_ONLY=1。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'tour_targets');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 2400)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = (await api(admin, 'GET', '/api/admin/users')).users.map((u) => u.username);
  if (!users.includes('tt_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'tt_teacher', name: '聚光老师', role: 'teacher', password: 'teach123' });
  const T = await login('tt_teacher', 'teach123');
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `聚光测试班 ${stamp}` });
  const stu = `tt${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},聚光同学\n`, default_password: '123456' });
  const SCENES = ['s01_motor_latch', 's02_fwd_rev', 's03_conveyor'];
  const asg = {};
  for (const sc of SCENES) asg[sc] = (await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: sc, title: `${sc}（聚光测试）` })).id;
  await api(T, 'POST', '/api/teach/courses/machining/publish', { class_id: cls.id, open_all: true });
  const S = await login(stu, '123456');

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  async function page(w, h, theme = 'light') {
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
    await ctx.addInitScript(([t, th]) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_ai_open', '0'); }, [S, theme]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    p.on('dialog', (d) => d.accept());
    return p;
  }
  const wait = (p, ms) => p.waitForTimeout(ms);

  /** 进一课（跟着教程做），下载参考程序（梯形图元件、检查表的"演示"按钮都要有程序才出来）。 */
  async function enter(p, kind, key) {
    await p.goto(B + '/teach', { waitUntil: 'networkidle' }); await wait(p, 1500);
    if (kind === 'scene') await p.locator(`.task-card[data-aid="${asg[key]}"]`).click();
    else {
      // 4.6 课程页：课程卡片 → 课程详情（章节和课）→ 第 1 课（老版本的课程地图直接列出各课）
      await p.waitForSelector('.course-card[data-course="machining"], .course[data-course="machining"] .lesson', { timeout: 30000 }).catch(() => null);
      if (await p.locator('.course-card[data-course="machining"]').count()) {
        await p.locator('.course-card[data-course="machining"]').first().click(); await wait(p, 1000);
        await p.locator('[data-k="course-detail"].course[data-course="machining"] .lesson').first().click();
      } else await p.locator('.course[data-course="machining"]').first().locator('.lesson').nth(0).click();
    }
    await wait(p, 1200);
    await p.locator('.task-panel [data-k="enter-lesson"]').first().click();
    await p.waitForSelector('.tour-ask', { timeout: 10000 }).catch(() => null);
    await p.locator('.tour-ask button:has-text("跟着教程做")').click().catch(() => null);
    await p.waitForURL(/\/p\/sb-[^/]+\/workbench$/, { timeout: 60000 }).catch(() => null);
    const sb = decodeURIComponent((p.url().match(/\/p\/([^/]+)\/workbench/) || [])[1] || '');
    await p.waitForSelector('[data-k="tour-card"]', { timeout: 30000 }).catch(() => null);
    await wait(p, 5000);
    for (const t of ['跳过', '以后再说']) { const x = p.locator(`.el-button:has-text("${t}")`).first(); if (await x.isVisible().catch(() => false)) await x.click().catch(() => null); }
    if (!(await p.evaluate(() => !!window.__vfTour?.tour?.on).catch(() => false))) {          // 第二次进同一课不再问：在任务面板里点"跟着教程做"
      await p.locator('[data-k="start-tour"]').click().catch(() => null);
      await p.waitForSelector('[data-k="tour-card"]', { timeout: 20000 }).catch(() => null); await wait(p, 1500);
    }
    if (kind === 'scene') {
      const sc = await api(T, 'GET', `/api/teach/scenes/${key}`);
      if (sc.reference?.ld) await api(S, 'POST', `/api/p/${encodeURIComponent(sb)}/cells/PLC1/program/download`, { program: sc.reference.ld, cold: true });
      await wait(p, 1500);
    }
    return sb;
  }

  /** 走完一个教程的每一步：go(i) → goto → 检查目标。 */
  async function walk(p, label, W, H, shotStep = null) {
    const n = await p.evaluate(() => window.__vfTour.tour.def.steps.length);
    let good = 0;
    const bad = [];
    for (let i = 0; i < n; i++) {
      let r = null;
      for (let attempt = 0; attempt < 3; attempt++) {     // 面板打开、浮窗挪动有动画：量到稳定为止（最多三次）
      r = await p.evaluate(async ([i, again]) => {
        const T = window.__vfTour; T.tour.hold = true; T.tour.min = false;
        if (!again) T.go(i);
        const s = T.tour.def.steps[i];
        await T.goto(s.goto, s.target);
        await new Promise((x) => setTimeout(x, 900));
        const h = T.resolveTarget(s.target);
        const full = h?.el ? h.el.getBoundingClientRect() : h?.rect;
        const ov = document.querySelector('[data-k="tour-overlay"]');
        const spot = document.querySelector('[data-k="tour-spot"]')?.getBoundingClientRect();
        const cr = document.querySelector('[data-k="tour-card"]')?.getBoundingClientRect();
        const cover = !!(cr && h && Math.min(cr.right, h.rect.right) - Math.max(cr.left, h.rect.left) > 2 && Math.min(cr.bottom, h.rect.bottom) - Math.max(cr.top, h.rect.top) > 2
          && h.rect.width * h.rect.height < 40000);           // 卡片不能压住要点的小目标（按钮、元件）
        return { id: s.id, goto: !!s.goto, found: !!h, step: T.tour.i, cover, overlayFound: ov?.getAttribute('data-found'),
          full: full && { x: full.x, y: full.y, r: full.right, b: full.bottom, w: full.width, h: full.height },
          shown: h && { x: h.rect.x, y: h.rect.y, w: h.rect.width, h: h.rect.height },
          spot: spot && { x: spot.x, y: spot.y, w: spot.width, h: spot.height }, tag: h?.el ? (h.el.className?.baseVal ?? h.el.className) + '' : '' };
      }, [i, attempt > 0]);
      const good1 = r.found && r.spot && r.shown && Math.abs(r.spot.x + 6 - r.shown.x) < 3 && Math.abs(r.spot.y + 6 - r.shown.y) < 3;
      if (good1) break;
      }
      const inView = r.full && r.full.x >= -1 && r.full.y >= -1 && r.full.r <= W + 1 && r.full.b <= H + 1;
      // 大容器（任务书、整张检查表、右栏）：露出来的一块够大、在视口里就行（任务书本身就比屏幕长）
      const big = r.full && r.full.w * r.full.h > 40000 && r.shown && r.shown.w >= 60 && r.shown.h >= 30 && r.shown.x >= 0 && r.shown.y >= 0 && r.shown.x + r.shown.w <= W && r.shown.y + r.shown.h <= H;
      const spotOk = r.spot && r.shown && Math.abs(r.spot.x + 6 - r.shown.x) < 3 && Math.abs(r.spot.y + 6 - r.shown.y) < 3;
      const pass = r.found && (inView || big) && spotOk && r.overlayFound === '1' && !r.cover;
      if (pass) good++; else bad.push(`${i + 1}.${r.id}:${JSON.stringify(r)}`);
      if (shotStep === r.id) await p.screenshot({ path: `${OUT}/${label}_${r.id}.png` });
    }
    ok(`${label}：${n} 步每一步"带我去"以后目标都在、看得见、在视口里，聚光圈在它上面、卡片不压住它`, good === n, `${good}/${n} ${bad.join(' | ')}`);
    return n;
  }

  // ---------------- 小屏：四个教程 ----------------
  const W = 1280, H = 720;
  for (const [kind, key, label] of (process.env.GUIDES_ONLY ? [] : [['scene', 's01_motor_latch', 's01'], ['scene', 's02_fwd_rev', 's02'], ['scene', 's03_conveyor', 's03'], ['course', 'machining/m01', 'm01']])) {
    const p = await page(W, H);
    const sb = await enter(p, kind, key);
    const has = await p.evaluate(() => !!window.__vfTour?.tour?.def?.steps?.length).catch(() => false);
    ok(`${label}：进了沙箱，跟随教程开始`, sb.startsWith('sb-') && has, sb);
    if (!has) { await p.context().close(); continue; }
    await walk(p, `${label}_1280`, W, H, label === 's01' ? 'overload' : label === 'm01' ? 'answer' : null);

    if (label === 's01') {
      // 目标看不到：不画空圈，卡片上说"点「带我去」"
      const miss = await p.evaluate(async () => {
        const T = window.__vfTour, ed = window.__vfEd; T.tour.hold = true;
        ed.leftOpen = false; ed.floats = [];
        const i = T.tour.def.steps.findIndex((s) => s.id === 'overload'); T.go(i);
        await new Promise((x) => setTimeout(x, 900));
        return { spot: !!document.querySelector('[data-k="tour-spot"]'), miss: document.querySelector('[data-k="tour-miss"]')?.textContent || '',
          hot: document.querySelector('[data-k="tour-goto"]')?.classList.contains('hot') };
      });
      ok('目标看不到：不画空的聚光圈，卡片上提示"点「带我去」"，按钮高亮', !miss.spot && /点「带我去」/.test(miss.miss) && miss.hot, JSON.stringify(miss));
      await p.screenshot({ path: `${OUT}/s01_overload_missing_light.png` });
      await p.locator('[data-k="tour-goto"]').click();
      await p.waitForFunction(() => document.querySelector('[data-k="tour-overlay"]')?.getAttribute('data-found') === '1' && !!document.querySelector('[data-act="trial-overload_ok"]'), null, { timeout: 10000 }).catch(() => null);
      await wait(p, 800);
      const after = await p.evaluate(() => ({ spot: !!document.querySelector('[data-k="tour-spot"]'), left: window.__vfEd.leftOpen && window.__vfEd.leftPanel,
        btn: (() => { const e = document.querySelector('[data-act="trial-overload_ok"]'); if (!e) return null; const r = e.getBoundingClientRect(); return [r.x, r.y, r.right, r.bottom]; })(),
        tab: document.querySelector('.task-panel .el-tabs__item.is-active')?.textContent || '' }));
      ok('点"带我去"：打开任务面板、切到检查表页签、「演示」按钮在屏幕里，聚光圈住它', after.spot && after.left === 'teach-task' && /检查表/.test(after.tab) && after.btn && after.btn[3] <= H && after.btn[2] <= W,
        JSON.stringify(after));
      await p.screenshot({ path: `${OUT}/s01_overload_goto_light.png` });
      // 进入一步时目标看不到：自动"带我去"
      const auto = await p.evaluate(async () => {
        const T = window.__vfTour, ed = window.__vfEd; T.tour.hold = false;
        ed.leftOpen = false;
        const i = T.tour.def.steps.findIndex((s) => s.id === 'all'); T.go(i);
        await new Promise((x) => setTimeout(x, 3500));
        return { left: ed.leftOpen && ed.leftPanel, found: document.querySelector('[data-k="tour-overlay"]')?.getAttribute('data-found'), step: T.tour.def.steps[T.tour.i]?.id };
      });
      ok('进入一步时要点的地方看不到：自动"带我去"（任务面板打开，聚光到检查表）', auto.left === 'teach-task' && auto.found === '1', JSON.stringify(auto));
      // "为什么"展开：卡片仍在屏幕里，正文可滚动
      const why = await p.evaluate(async () => {
        const T = window.__vfTour; T.tour.hold = true;
        const i = T.tour.def.steps.findIndex((s) => s.id === 'priority'); T.go(i);
        await new Promise((x) => setTimeout(x, 600));
        document.querySelector('.vt-why summary')?.click();
        await new Promise((x) => setTimeout(x, 900));
        const c = document.querySelector('[data-k="tour-card"]').getBoundingClientRect(), b = document.querySelector('[data-k="tour-body"]');
        return { top: c.top, bottom: c.bottom, h: innerHeight, open: document.querySelector('.vt-why')?.open, scrollable: b.scrollHeight > b.clientHeight + 1, oy: getComputedStyle(b).overflowY,
          btn: document.querySelector('[data-k="tour-next"], [data-k="tour-skip"]')?.getBoundingClientRect().bottom };
      });
      ok('展开"为什么"：卡片整个在屏幕里（高度不超过窗口），按钮看得见，正文可滚动', why.open && why.top >= 0 && why.bottom <= why.h && why.btn <= why.h && why.oy === 'auto', JSON.stringify(why));
      await p.screenshot({ path: `${OUT}/s01_why_open_light.png` });
      // 悬停"下一步"：字不能和底色一样
      await p.locator('[data-k="tour-next"], [data-k="tour-skip"]').first().hover(); await wait(p, 300);
      const hov = await p.evaluate(() => { const e = document.querySelector('.vt-b.pri') || document.querySelector('.vt-b'); const cs = getComputedStyle(e); return [cs.color, cs.backgroundColor]; });
      ok('悬停蓝色按钮：字和底色不一样', hov[0] !== hov[1], hov.join(' / '));
    }
    await p.context().close();
  }

  // ---------------- 大屏 + 深色：s01 再走一遍 ----------------
  if (!process.env.GUIDES_ONLY) {
    const W2 = 1680, H2 = 960;
    const q = await page(W2, H2, 'light');   // 5.0.1 只有浅色（以前这里查深色）
    await enter(q, 'scene', 's01_motor_latch');
    const has = await q.evaluate(() => !!window.__vfTour?.tour?.def?.steps?.length).catch(() => false);
    if (has) await walk(q, 's01_1680_b', W2, H2, 'overload');
    else ok('深色大屏：s01 教程开始', false);
    await q.context().close();
  }

  // ---------------- 4.7 操作导览：注册表里每个导览逐步走一遍（1280×720 浅色、1680×960 深色） ----------------
  // 每个导览在它该在的页面上开始（管理员：工作台、实验、信号中心；学生：课程页；老师：教学页；MES：把 /api/health 伪装成客户端），
  // 每一步执行 goto 以后断言目标在、看得见、在视口里、聚光圈在它上面、卡片不压住它（和上面的跟随教程同一套断言）。
  // 另外：每个地方都有「?」按钮并能列出导览；Ctrl+K 搜"操作导览"列出导览、点一条就开始；收起成小条；退出后重新打开问"从第 N 步继续"；
  // 刷新页面导览接着上次那一步（不请求 /api/teach）；走完显示"导览结束"；F1 抽屉里有相关导览。
  {
    const PLANT = (await api(admin, 'GET', '/api/overview')).plants?.[0]?.id || 'foundry-housing';
    const gstats = { guides: 0, steps: 0, sizes: [] };
    async function gpage(w, h, tok, theme = 'light', deskStub = false) {
      const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
      await ctx.addInitScript(([t, th]) => {
        localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_ai_open', '0');
        localStorage.setItem('vf_guide_off', '1');
      }, [tok, theme]);
      if (deskStub) {
        await ctx.route('**/api/health', async (r) => {
          const res = await r.fetch(); const j = await res.json().catch(() => ({}));
          await r.fulfill({ json: { ...j, desktop: true, mode: 'server', server: B, online: true } });
        });
      }
      const p = await ctx.newPage();
      p.on('pageerror', (e) => errs.push('[guide] ' + e.message.slice(0, 200)));
      p.on('dialog', (d) => d.accept());
      return p;
    }
    /** 关掉"新功能"之类自动弹出的对话框。 */
    async function calm(p) {
      for (let k = 0; k < 3; k++) {
        const x = p.locator('.el-dialog__headerbtn:visible').first();
        if (await x.isVisible().catch(() => false)) { await x.click().catch(() => null); await wait(p, 400); } else break;
      }
    }
    const WHO = { workbench: 'admin', experiments: 'admin', signals: 'admin', courses: 'student', teach: 'teacher', mes: 'mes' };
    const URLS = { workbench: `/p/${PLANT}/workbench`, experiments: `/p/${PLANT}/experiments`, signals: `/p/${PLANT}/signals`, courses: '/courses', teach: '/teach', mes: '/mes' };
    const TOK = { admin, student: S, teacher: T, mes: admin };
    const READY = { workbench: '.ed-bar', experiments: '[data-tour="exp-head"]', signals: '[data-tour="sig-head"]', courses: '[data-tour="ch-hero"]', teach: '.teacher-console',
      mes: '[data-tour="mes-head"], [data-tour="mes-bar"]' };
    const BTN = { workbench: '.ed-menu [data-k="guide-btn"]', experiments: '[data-tour="exp-head"] [data-k="guide-btn"]', signals: '[data-tour="sig-head"] [data-k="guide-btn"]',
      courses: '.ch-toolbar [data-k="guide-btn"]', teach: '.teacher-console .vp-head [data-k="guide-btn"]', mes: '[data-tour="mes-head"] [data-k="guide-btn"], [data-tour="mes-bar"] [data-k="guide-btn"]' };
    const SHOTS = { 1280: ['plan-draw', 'task-line', 'plc', 'courses', 'mes', 'signals'], 1680: ['wb-arch', 'task-plc', 'experiments', 'teacher', 'analysis'] };
    const reg = await (async () => {
      const p = await gpage(1280, 720, admin); await p.goto(B + '/welcome', { waitUntil: 'networkidle' });
      await p.waitForFunction(() => !!window.__vfTour?.guides, null, { timeout: 20000 }).catch(() => null);
      const r = await p.evaluate(() => window.__vfTour.guides.map((g) => ({ key: g.key, where: g.where, n: g.steps.length, task: !!g.task })));
      await p.context().close(); return r;
    })();
    ok(`导览注册表：${reg.length} 个导览（${reg.filter((g) => g.task).length} 个完整任务），共 ${reg.reduce((a, g) => a + g.n, 0)} 步`, reg.length >= 12, reg.map((g) => `${g.key}:${g.n}`).join(' '));

    for (const [W, H, theme] of [[1280, 720, 'light'], [1680, 960, 'light']]) {
      let good = 0;
      for (const where of Object.keys(WHO)) {
        const list = reg.filter((g) => g.where === where);
        if (!list.length) continue;
        const who = WHO[where];
        const p = await gpage(W, H, TOK[who], theme, who === 'mes');
        await p.goto(B + URLS[where], { waitUntil: 'networkidle' }).catch(() => null);
        await p.waitForSelector(READY[where], { timeout: 40000 }).catch(() => null);
        await wait(p, where === 'workbench' ? 5000 : 2000);
        await calm(p);
        const here = p.url().replace(B, '');
        // 「?」按钮：在、看得见，点开列出导览
        const btnOk = await p.locator(BTN[where]).first().isVisible().catch(() => false);
        let items = 0;
        if (btnOk) {
          await p.locator(BTN[where]).first().click(); await wait(p, 700);
          items = await p.locator('[data-k="guide-menu"]:visible [data-k="guide-item"]').count();
          if (W === 1280 && ['workbench', 'courses'].includes(where)) await p.screenshot({ path: `${OUT}/guide_menu_${where}_${W}x${H}_${theme}.png` });
          await p.locator(BTN[where]).first().click().catch(() => null); await wait(p, 400);
        }
        ok(`${W}：${where}（${here}）有「?」，点开列出 ${items} 个导览`, btnOk && items > 0, `btn=${btnOk} items=${items}`);
        for (const g of list) {
          if (where === 'workbench') await p.evaluate(() => { const ed = window.__vfEd; ed.floats = []; ed.sel = []; ed.selLink = ''; ed.split = false; });
          const started = await p.evaluate(async (k) => window.__vfTour.startGuide(k, 0), g.key).catch((e) => String(e));
          await p.waitForSelector('[data-k="tour-card"]', { timeout: 15000 }).catch(() => null);
          const isGuide = await p.evaluate((k) => document.querySelector('[data-k="tour-overlay"]')?.getAttribute('data-guide') === k, g.key).catch(() => false);
          if (!(started === true && isGuide)) { ok(`${W}：导览 ${g.key} 开始`, false, `started=${started} overlay=${isGuide} url=${p.url()}`); continue; }
          const n = await walk(p, `导览 ${g.key} ${W}×${H}`, W, H, null);
          if (res[res.length - 1][1]) good++;
          gstats.steps += n; gstats.guides++;
          if ((SHOTS[W] || []).includes(g.key)) {        // 截一张：第 2 步（有聚光和卡片）
            const s1 = await p.evaluate(() => { const T = window.__vfTour; T.tour.hold = true; T.go(Math.min(1, T.tour.def.steps.length - 1)); return T.tour.def.steps[T.tour.i]; });
            await p.evaluate(async (s) => window.__vfTour.goto(s.goto, s.target), s1); await wait(p, 1200);
            await p.screenshot({ path: `${OUT}/guide_${g.key}_${W}x${H}_${theme}.png` });
          }
          await p.evaluate(() => { window.__vfTour.tour.hold = false; }).catch(() => null);
        }
        // 功能检查（只在小屏的工作台上跑一次）
        if (W === 1280 && where === 'workbench') {
          const sub = await p.evaluate(async () => {
            const ed = window.__vfEd, sl = (ms) => new Promise((r) => setTimeout(r, ms));
            const vis = (sel) => { const e = document.querySelector(sel); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; };
            window.__vfTour.tour.on = false; ed.floats = []; ed.view = 'plan'; await sl(1200);
            const plan = vis('.pv-bar [data-k="guide-btn"]');
            window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'analysis' } })); await sl(2500);
            const an = vis('.an-bar [data-k="guide-btn"]');
            ed.floats = []; ed.sel = ['PLC1'];
            window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor-float' } })); await sl(3500);
            const plc = vis('.pw-bar [data-k="guide-btn"]');
            ed.floats = []; ed.sel = []; ed.view = '3d'; await sl(500);
            return { plan, an, plc };
          });
          ok('平面图工具条、分析窗口、PLC 编程窗口里都有「?」', sub.plan && sub.an && sub.plc, JSON.stringify(sub));
          // Ctrl+K：搜"操作导览"列出导览命令，点一条就开始
          await p.keyboard.press('Control+k'); await p.waitForSelector('[data-k="cmdp"]', { timeout: 5000 }).catch(() => null);
          await p.locator('[data-k="cmdp-q"]').fill('操作导览'); await wait(p, 600);
          const cmds = await p.evaluate(() => [...document.querySelectorAll('.cmdp-i[data-cmd^="guide."]')].map((e) => e.getAttribute('data-cmd')));
          const want = reg.filter((g) => !['mes', 'courses'].includes(g.where)).map((g) => 'guide.' + g.key);   // 网页里的管理员：没有 MES（客户端）和学生的课程页
          await p.screenshot({ path: `${OUT}/guide_palette_${W}x${H}.png` });
          ok(`Ctrl+K 搜"操作导览"列出 ${cmds.length} 条导览命令（应有 ${want.length} 条）`, want.every((k) => cmds.includes(k)), cmds.join(','));
          await p.locator('.cmdp-i[data-cmd="guide.wb-graph"]').click().catch(() => null);
          await p.waitForFunction(() => document.querySelector('[data-k="tour-overlay"]')?.getAttribute('data-guide') === 'wb-graph', null, { timeout: 10000 }).catch(() => null);
          await wait(p, 1500);
          const fromCmd = await p.evaluate(() => ({ guide: document.querySelector('[data-k="tour-overlay"]')?.getAttribute('data-guide'), view: window.__vfEd.view,
            btns: ['tour-prev', 'tour-skip', 'tour-next', 'tour-exit'].filter((k) => document.querySelector(`[data-k="${k}"]`)) }));
          ok('点命令开始导览：卡片上有 上一步 / 跳过 / 下一步 / 退出，并切到流程视图', fromCmd.guide === 'wb-graph' && fromCmd.btns.length === 4 && fromCmd.view === 'graph', JSON.stringify(fromCmd));
          await p.locator('[data-k="tour-min"]').click().catch(() => null); await wait(p, 400);
          const pill = await p.locator('[data-k="tour-pill"]').innerText().catch(() => '');
          ok('导览可以收起成左下角的小条（"导览 1/N · …"）', /导览 1\/\d/.test(pill), pill);
          await p.locator('[data-k="tour-pill"]').click().catch(() => null); await wait(p, 400);
          // 退出 → 重新打开：问"从第 N 步继续 / 从头开始"
          await p.evaluate(() => { window.__vfTour.tour.hold = true; window.__vfTour.go(2); }); await wait(p, 500);
          await p.locator('[data-k="tour-exit"]').click(); await wait(p, 600);
          const memo = await p.evaluate(() => ({ on: window.__vfTour.tour.on, at: window.__vfTour.guideAt('wb-graph') }));
          ok('退出导览：导览关掉，记住停在第 3 步', !memo.on && memo.at === 2, JSON.stringify(memo));
          await p.evaluate(() => { window.__vfTour.startGuide('wb-graph'); });
          await p.waitForSelector('.vf-guide-resume', { timeout: 6000 }).catch(() => null); await wait(p, 400);
          const ask = await p.locator('.vf-guide-resume').innerText().catch(() => '');
          await p.screenshot({ path: `${OUT}/guide_resume_ask_${W}x${H}.png` });
          await p.locator('.vf-guide-resume .el-button--primary').click().catch(() => null);
          await p.waitForSelector('[data-k="tour-card"]', { timeout: 10000 }).catch(() => null); await wait(p, 800);
          const resumed = await p.evaluate(() => ({ on: window.__vfTour.tour.on, i: window.__vfTour.tour.i, guide: window.__vfTour.tour.guide }));
          ok('重新打开：问"从第 3 步继续 / 从头开始"，选继续就从第 3 步开始', /从第 3 步继续/.test(ask) && /从头开始/.test(ask) && resumed.on && resumed.i === 2,
            ask.replace(/\s+/g, ' ') + ' ' + JSON.stringify(resumed));
          // 刷新页面：导览接着这一步（本地定义，不请求 /api/teach/tours）
          const teachCalls = [];
          p.on('request', (r) => { if (/\/api\/teach\/tours\//.test(r.url())) teachCalls.push(r.url()); });
          await p.reload({ waitUntil: 'networkidle' }); await p.waitForSelector('[data-k="tour-card"]', { timeout: 30000 }).catch(() => null); await wait(p, 2500);
          const after = await p.evaluate(() => ({ on: window.__vfTour?.tour?.on, i: window.__vfTour?.tour?.i, guide: document.querySelector('[data-k="tour-overlay"]')?.getAttribute('data-guide') }));
          ok('刷新页面：导览还在、停在同一步，没有请求 /api/teach/tours', after.on && after.i === 2 && after.guide === 'wb-graph' && !teachCalls.length, JSON.stringify(after) + ' ' + teachCalls.join(','));
          // 走到最后：显示"导览结束"，关闭后不再问继续
          await p.evaluate(() => { const T = window.__vfTour; T.go(T.tour.def.steps.length); }); await wait(p, 500);
          const fin = await p.locator('[data-k="tour-card"]').innerText().catch(() => '');
          await p.locator('[data-k="tour-close"]').click().catch(() => null); await wait(p, 400);
          const cleared = await p.evaluate(() => ({ on: window.__vfTour.tour.on, at: window.__vfTour.guideAt('wb-graph') }));
          ok('走完：卡片写"导览结束"，关闭后不再提示继续', /导览结束/.test(fin) && !cleared.on && cleared.at === 0, fin.replace(/\s+/g, ' ').slice(0, 80) + ' ' + JSON.stringify(cleared));
          // F1 帮助抽屉里列出相关导览
          await p.evaluate(() => { window.__vfEd.view = 'plan'; }); await wait(p, 800);
          await p.mouse.move(Math.round(W / 2), Math.round(H / 2)); await p.keyboard.press('F1'); await wait(p, 1200);
          const hg = await p.evaluate(() => [...document.querySelectorAll('[data-k="help-guides"] [data-guide]')].map((e) => e.getAttribute('data-guide')));
          await p.screenshot({ path: `${OUT}/guide_help_drawer_${W}x${H}.png` });
          ok('F1 帮助抽屉里列出这一节相关的操作导览', hg.length > 0, hg.join(','));
          await p.keyboard.press('Escape');
        }
        await p.context().close();
      }
      gstats.sizes.push(`${W}×${H}: ${good}/${reg.length} 个导览全部步骤通过`);
    }
    console.log(`操作导览：走了 ${gstats.guides} 次导览、${gstats.steps} 步；${gstats.sizes.join('；')}`);
  }

  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
