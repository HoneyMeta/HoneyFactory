// 4.6 按钮悬停 / 按下时字和底色撞色检查（B 机，先启动 serve）：node tests/hover_contrast_ui.js
// 浅色 / 深色，开始页、教学页（老师）、工作台（管理员，顺便打开分析浮窗）、学生沙箱（跟随教程卡片 + 任务面板 + 检查表）：
// 对每个看得见的按钮（Element Plus 主要 / 朴素 / 文字按钮、单选按钮、页签、我们自己的按钮……）用 CDP 强制 :hover 和 :hover:active，
// 算字的颜色和实际底色的对比度，低于 1.6（基本是同一个颜色、看不见字）就报出来。截图在 SHOT_DIR。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const { SCAN } = require('./ui_scan');
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'hover_contrast');
const PLANT = process.env.VF_PLANT || 'foundry-housing';
const MIN = 1.6;
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 3000)); };
const api = async (tok, m, u, b) => { const r = await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); };
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;
const SEL = 'button, .el-button, .el-radio-button__inner, .el-tabs__item, .el-dropdown-menu__item, .el-menu-item, .el-segmented__item, [role="button"], a[href], a.lnk, .vt-b, .ck-btn, .aid-lk';

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const stamp = String(Date.now()).slice(-6);
  const admin = await login('admin', 'honey123');
  const users = ((await api(admin, 'GET', '/api/admin/users')).users || []).map((u) => u.username);
  if (!users.includes('hc_teacher')) await api(admin, 'POST', '/api/admin/users', { username: 'hc_teacher', name: '对比老师', role: 'teacher', password: 'teach123' });
  const T = await login('hc_teacher', 'teach123');
  const cls = await api(T, 'POST', '/api/teach/classes', { name: `对比测试班 ${stamp}` });
  const stu = `hc${stamp}`;
  await api(T, 'POST', `/api/teach/classes/${cls.id}/roster`, { csv: `账号,姓名\n${stu},对比同学\n`, default_password: '123456' });
  const aid = (await api(T, 'POST', '/api/teach/assignments', { class_id: cls.id, scene: 's01_motor_latch', title: '电机启停自锁（对比测试）' })).id;
  const S = await login(stu, '123456');
  const sb = (await api(S, 'POST', `/api/teach/assignments/${aid}/sandbox`, {})).pid;

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [], bad = new Map();
  let checked = 0, shots = 0;
  async function page(tok, theme) {
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
    await ctx.addInitScript(([t, th]) => {
      if (sessionStorage.getItem('hc_init')) return; sessionStorage.setItem('hc_init', '1');
      localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_ws', 'all');
      sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_guide_off', '1'); localStorage.setItem('vf_teach_tour', '1'); localStorage.setItem('vf_whatsnew_seen', '9.9.9');
    }, [tok, theme]);
    await ctx.addInitScript({ content: SCAN });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    p.on('dialog', (d) => d.dismiss());
    return p;
  }
  async function audit(p, view) {
    await p.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' });
    const n = await p.evaluate((sel) => {
      let i = 0;
      for (const e of document.querySelectorAll(sel)) {
        e.removeAttribute('data-hc');
        const r = e.getBoundingClientRect();
        if (r.width < 6 || r.height < 6 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        if (!(e.innerText || '').trim() || getComputedStyle(e).visibility === 'hidden' || e.closest('[aria-hidden="true"]')) continue;
        if (e.matches(':disabled, .is-disabled, [aria-disabled="true"]') || e.closest('.is-disabled, :disabled')) continue;   // 禁用的按钮本来就是灰的、不响应悬停
        if (i >= 260) break;
        e.setAttribute('data-hc', String(i++));
      }
      return i;
    }, SEL);
    const cdp = await p.context().newCDPSession(p);
    await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
    const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
    for (let i = 0; i < n; i++) {
      const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: `[data-hc="${i}"]` }).catch(() => ({ nodeId: 0 }));
      if (!nodeId) continue;
      for (const st of [['hover'], ['hover', 'active']]) {
        await cdp.send('CSS.forcePseudoState', { nodeId, forcedPseudoClasses: st }).catch(() => null);
        const c = await p.evaluate((i) => { const e = document.querySelector(`[data-hc="${i}"]`); return e ? { ...window.__vfScan.contrastOf(e), who: window.__vfScan.label(e), where: window.__vfScan.where(e) } : null; }, i);
        checked++;
        if (c && c.ratio < MIN) {
          const k = `${view.split('@')[0]} | ${c.who}`;
          if (!bad.has(k)) bad.set(k, { ...c, view, st: st.join('+') });
          if (shots < 20) { const h = await p.$(`[data-hc="${i}"]`); await h?.screenshot({ path: `${OUT}/bad_${String(++shots).padStart(2, '0')}.png` }).catch(() => null); }
        }
      }
      await cdp.send('CSS.forcePseudoState', { nodeId, forcedPseudoClasses: [] }).catch(() => null);
    }
    await cdp.detach().catch(() => null);
  }

  // 5.0.1 只有浅色（和蜂元 MES 同一套设计系统）：只查浅色一遍
  for (const theme of ['light']) {
    let p = await page(admin, theme);
    await p.goto(B + '/', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500);
    await audit(p, 'welcome@' + theme);
    await p.context().close();
    p = await page(T, theme);
    await p.goto(B + '/teach', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500);
    await audit(p, 'teach@' + theme);
    await p.context().close();
    p = await page(admin, theme);
    await p.goto(`${B}/p/${PLANT}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.ed-act button[data-panel]', { timeout: 60000 }); await p.waitForTimeout(6000);
    await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'analysis' } }))); await p.waitForTimeout(3000);
    await audit(p, 'workbench@' + theme);
    // 三维设备标签跟随主题：字和标签底色对比度 ≥ 3
    await p.evaluate(() => { const s = window.__vfScene; s?.viewPreset?.('overview'); }); await p.waitForTimeout(2500);
    const lb = await p.evaluate(() => window.__vfScan.labels());
    ok(`${theme}：三维设备标签的字看得清（${lb.n} 个标签，对比度 ≥ 3）`, lb.n > 5 && lb.low.length === 0, JSON.stringify(lb.low.slice(0, 6)));
    await p.screenshot({ path: `${OUT}/labels3d_${theme}.png` });
    await p.screenshot({ path: `${OUT}/workbench_${theme}.png` });
    await p.context().close();
    // 学生沙箱：跟随教程卡片、任务面板、检查表
    p = await page(S, theme);
    await p.goto(`${B}/p/${encodeURIComponent(sb)}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.task-panel', { timeout: 60000 }).catch(() => null); await p.waitForTimeout(5000);
    await p.locator('[data-k="start-tour"]').click().catch(() => null); await p.waitForTimeout(2500);
    await p.evaluate(() => { const T = window.__vfTour; if (T?.tour?.def) { T.tour.hold = true; T.go(T.tour.def.steps.findIndex((s) => s.id === 'download')); } }); await p.waitForTimeout(800);
    await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:teach-tab', { detail: { tab: 'goals' } }))); await p.waitForTimeout(1500);
    await audit(p, 'student@' + theme);
    await p.screenshot({ path: `${OUT}/student_${theme}.png` });
    await p.context().close();
  }
  const list = [...bad.values()];
  ok(`按钮悬停 / 按下时字看得见（对比度 ≥ ${MIN}，查了 ${checked} 次）`, list.length === 0,
    list.map((c) => `\n  [${c.view} ${c.st}] ${c.who} @${c.where} 对比度 ${c.ratio} 字 ${c.color} 底 ${c.bg}`).join(''));
  ok('确实查了足够多的按钮', checked > 200, checked);
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
