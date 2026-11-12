// UI language walk-through (Playwright, machine B, server running): node tests/i18n_ui.js
// - Default language: Chinese browsers get zh-CN, others English; the login page and the top bar switch it; the choice persists (localStorage vf_lang).
// - Requests carry the language: fetch -> X-Lang header, WebSocket URL -> lang=.
// - Every main route (and the workbench views / workspaces / panels) is visited in en and zh-CN. In English, visible CJK text is reported:
//   text that also occurs in API responses / WebSocket frames is BACKEND data (listed, not a failure, until the backend is localized),
//   anything else is a UI string that escaped translation (failure).
// - Layout in English: horizontal page scroll, clipped buttons / tabs, overflowing top bars at 1680 and 1280 wide.
// Env: VF_URL (default http://127.0.0.1:8800), SHOT_DIR / SHOTS_DIR (screenshots: <dir>/en, <dir>/zh), VF_PLANT (default foundry-housing),
//      VF_CELL_PLANT (default plctest), I18N_REPORT (json report path, default <shots>/i18n_report.json).
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));

const B = (process.env.VF_URL || 'http://127.0.0.1:8800').replace(/\/$/, '');
const OUT = process.env.SHOTS_DIR || process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_shots', 'i18n');
const PID = process.env.VF_PLANT || 'foundry-housing';
const CELL = process.env.VF_CELL_PLANT || 'plctest';
const REPORT = process.env.I18N_REPORT || path.join(OUT, 'i18n_report.json');
for (const d of ['en', 'zh']) fs.mkdirSync(path.join(OUT, d), { recursive: true });
const results = [];
const ok = (name, cond, detail = '') => { results.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 400)); };
const CJK_SRC = '[\\u3000-\\u303f\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\uff00-\\uffef]';
const CJK = new RegExp(CJK_SRC);
const RUNS = new RegExp(CJK_SRC + '+', 'g');
const ZH_NAME = /^\s*(\u4e2d|\u4e2d\u6587)\s*$/;   // language names in the switcher

const ROUTES = ['/welcome', '/', `/p/${PID}/plan`, `/p/${PID}/scenarios`, `/p/${PID}/experiments`, `/p/${PID}/reports`, `/p/${PID}/signals`,
  `/p/${PID}/dataset`, `/p/${PID}/tables`, '/courses', '/teach', '/progress', '/org', '/mes', '/tokens', '/users', '/audit', '/help'];

async function api(method, p, body, token, lang = 'zh-CN') {
  const r = await fetch(B + p, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': lang, ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
}

// visible text lines with CJK (+ placeholders)
const visibleCjk = (page) => page.evaluate((src) => {
  const R = new RegExp(src);
  const out = new Set();
  const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false; const cs = getComputedStyle(el); return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0'; };
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n.nodeValue || '';
    if (!R.test(t)) continue;
    const el = n.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName) || !vis(el)) continue;
    if (el.closest('[data-test=lang-switch]')) continue;
    for (const line of t.split('\n')) if (R.test(line)) out.add(line.trim().slice(0, 100));
  }
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) if (vis(el) && R.test(el.placeholder)) out.add('[placeholder] ' + el.placeholder.slice(0, 100));
  return [...out];
}, CJK_SRC);

// English layout problems
const layoutIssues = (page) => page.evaluate(() => {
  const iss = [];
  const de = document.documentElement;
  if (de.scrollWidth > innerWidth + 2) iss.push('page scrolls horizontally ' + de.scrollWidth + '>' + innerWidth);
  const main = document.querySelector('.shell .main');
  if (main && main.scrollWidth > main.clientWidth + 4) iss.push('main area overflows ' + main.scrollWidth + '>' + main.clientWidth);
  for (const sel of ['.shell .top', '.ed-menu', '.ops .bar', '.shell .side .brand']) {
    const el = document.querySelector(sel);
    if (el && el.scrollWidth > el.clientWidth + 2) iss.push(sel + ' overflows ' + el.scrollWidth + '>' + el.clientWidth);
  }
  const clipped = [];
  for (const b of document.querySelectorAll('.el-button, .el-tabs__item, .el-radio-button__inner, .el-segmented__item')) {
    const r = b.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(b); if (cs.visibility === 'hidden') continue;
    const span = b.querySelector('span') || b;
    if (span.scrollWidth > b.clientWidth + 6 || b.scrollHeight > b.clientHeight + 6) clipped.push((b.innerText || b.getAttribute('aria-label') || '?').trim().replace(/\s+/g, ' ').slice(0, 30));
  }
  if (clipped.length) iss.push('clipped: ' + [...new Set(clipped)].slice(0, 8).join(', '));
  return iss;
});

(async () => {
  const tok = (await api('POST', '/api/login', { username: 'admin', password: 'honey123' })).token;
  if (!tok) { console.error('login failed'); process.exit(1); }
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errors = [];
  const report = { backend: {}, ui: {}, layout: {} };

  // ---------- 1. login page: browser language decides the default; switch + persistence ----------
  for (const [loc, want] of [['zh-CN', 'zh-CN'], ['en-US', 'en']]) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: loc });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push('login ' + String(e)));
    await page.goto(B + '/login');
    await page.waitForSelector('[data-test=lang-switch]');
    const lang = await page.evaluate(() => document.documentElement.lang);
    const box = await page.locator('.box').innerText();
    ok(`login: ${loc} browser defaults to ${want}`, lang === want && (want === 'en' ? !CJK.test(box) : CJK.test(box)), box.slice(0, 50).replace(/\n/g, ' '));
    if (want === 'en') {
      await page.screenshot({ path: path.join(OUT, 'en', 'login.png') });
      await Promise.all([page.waitForEvent('load'), page.click('[data-test="lang-zh-CN"]')]);
      await page.waitForSelector('[data-test=lang-switch]');
      ok('login: switch to Chinese', CJK.test(await page.locator('.box').innerText()) && (await page.evaluate(() => localStorage.getItem('vf_lang'))) === 'zh-CN');
      await page.screenshot({ path: path.join(OUT, 'zh', 'login.png') });
      await Promise.all([page.waitForEvent('load'), page.click('[data-test="lang-en"]')]);
      await page.waitForSelector('[data-test=lang-switch]');
      ok('login: switch back to English', !CJK.test(await page.locator('.box').innerText()) && (await page.evaluate(() => localStorage.getItem('vf_lang'))) === 'en');
      await page.goto(B + '/login?lang=zh-CN');
      await page.waitForSelector('[data-test=lang-switch]');
      ok('?lang=zh-CN switches and persists', (await page.evaluate(() => document.documentElement.lang + '|' + localStorage.getItem('vf_lang'))) === 'zh-CN|zh-CN');
    }
    await ctx.close();
  }

  for (const lang of ['en', 'zh-CN']) {
    const L = lang === 'en' ? 'EN' : 'ZH', dir = lang === 'en' ? 'en' : 'zh';
    const ctx = await browser.newContext({ viewport: { width: 1680, height: 1000 }, locale: 'en-US' });
    await ctx.addInitScript(([t, l]) => {
      if (!sessionStorage.getItem('i18n_init')) {
        sessionStorage.setItem('i18n_init', '1');
        localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', l); localStorage.setItem('vf_ai_open', '0');
        sessionStorage.setItem('vf_pw_later', '1');
      }
    }, [tok, lang]);
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(lang + ' ' + String(e).slice(0, 200)));
    page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|favicon|WebSocket/.test(m.text())) errors.push(lang + ' ' + m.text().slice(0, 200)); });
    const hdr = [], wsUrls = [];
    let backendText = '';
    page.on('request', (r) => { if (r.url().startsWith(B + '/api/') && r.resourceType() === 'fetch') hdr.push(r.headers()['x-lang'] || ''); });
    page.on('response', async (r) => {
      try {
        if (!r.url().startsWith(B + '/api/')) return;
        const ct = r.headers()['content-type'] || '';
        // read the body first: `backendText += await ...` reads backendText before the await and drops concurrent appends
        const t = ct.includes('json') ? JSON.stringify(await r.json()) : ct.includes('text') ? await r.text() : '';
        if (t && CJK.test(t)) backendText += t + '\n';
      } catch { /* body gone */ }
    });
    page.on('websocket', (ws) => { wsUrls.push(ws.url()); ws.on('framereceived', (f) => { if (typeof f.payload === 'string' && CJK.test(f.payload)) backendText += f.payload.slice(0, 200000) + '\n'; }); });

    const check = async (name, shot) => {
      await page.waitForTimeout(400);
      if (lang === 'en') {
        const lines = await visibleCjk(page);
        const ui = [], be = [];
        for (const l of lines) ((l.match(RUNS) || []).every((run) => backendText.includes(run)) ? be : ui).push(l);
        if (be.length) report.backend[name] = be.slice(0, 30);
        if (ui.length) report.ui[name] = ui.slice(0, 30);
        ok(`EN ${name}: no UI Chinese`, !ui.length, ui.slice(0, 6).join(' | ') + (be.length ? `   (backend data: ${be.length})` : ''));
        const iss = await layoutIssues(page);
        if (iss.length) report.layout[name] = iss;
        ok(`EN ${name}: layout`, !iss.length, iss.join('; '));
      } else {
        const t = await page.locator('body').innerText();
        ok(`ZH ${name}: Chinese UI`, CJK.test(t));
      }
      if (shot) await page.screenshot({ path: path.join(OUT, dir, shot + '.png') });
    };

    // ---------- 2. main routes ----------
    for (const vp of [[1680, 1000], [1280, 720]]) {
      await page.setViewportSize({ width: vp[0], height: vp[1] });
      for (const r of ROUTES) {
        await page.goto(B + r);
        await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(900);
        const name = (r === '/' ? 'plants' : r.slice(1).replace(new RegExp('p/' + PID + '/'), '').replace(/\//g, '_'));
        await check(`${name} @${vp[0]}`, `${name}_${vp[0]}`);
      }
    }
    ok(`${L} html lang`, (await page.evaluate(() => document.documentElement.lang)) === lang);
    ok(`${L} fetch sends X-Lang`, hdr.length > 5 && hdr.every((h) => h === lang), `${hdr.length} calls, values ${[...new Set(hdr)].join('/')}`);

    // ---------- 3. workbench: views, workspaces, panels ----------
    await page.setViewportSize({ width: 1680, height: 1000 });
    for (const [pid, tag] of [[PID, 'wb'], [CELL, 'cell']]) {
      await page.goto(`${B}/p/${pid}/workbench`);
      await page.waitForSelector('.ed-menu', { timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(6000);
      await check(`${tag} workbench`, `${tag}_workbench`);
      const views = await page.locator('.ed-views .el-radio-button').count();
      for (let i = 0; i < views; i++) {
        await page.locator('.ed-views .el-radio-button').nth(i).click().catch(() => {});
        await page.waitForTimeout(2500);
        await check(`${tag} view ${i}`, `${tag}_view${i}`);
      }
      const ws = await page.locator('.ed-ws button').count();
      for (let i = 0; i < ws; i++) {
        await page.locator('.ed-ws button').nth(i).click().catch(() => {});
        await page.waitForTimeout(1500);
        const ids = await page.$$eval('.ed-act button[data-panel]', (bs) => bs.map((x) => x.getAttribute('data-panel')));
        for (const id of ids) {
          if (!(await page.locator(`.ed-act button[data-panel="${id}"].on`).count())) await page.click(`.ed-act button[data-panel="${id}"]`).catch(() => {});
          await page.waitForTimeout(1800);
          await check(`${tag} ws${i} ${id}`, i === 0 || tag === 'cell' ? `${tag}_ws${i}_${id}` : '');
          while (await page.locator('.fl-layer .fw-b').count()) {
            const c = page.locator('.fl-layer .fw-b').last();
            if (!(await c.isVisible().catch(() => false))) break;
            await c.click().catch(() => {}); await page.waitForTimeout(150);
            if (await page.locator('.fl-layer .fw').count() === 0) break;
          }
        }
      }
    }
    ok(`${L} WebSocket URL carries lang`, wsUrls.length > 0 && wsUrls.every((u) => u.includes('lang=' + encodeURIComponent(lang))), wsUrls.slice(0, 2).join(' '));
    await page.screenshot({ path: path.join(OUT, dir, 'workbench_end.png') });

    // ---------- 4. top-bar switch ----------
    await page.goto(B + '/welcome');
    await page.waitForSelector('.shell [data-test=lang-switch]');
    const other = lang === 'en' ? 'zh-CN' : 'en';
    await Promise.all([page.waitForEvent('load'), page.click(`.shell [data-test="lang-${other}"]`)]);
    await page.waitForSelector('.shell .top');
    ok(`${L} top-bar switch -> ${other}`, (await page.evaluate(() => document.documentElement.lang + '|' + localStorage.getItem('vf_lang'))) === `${other}|${other}` && page.url().includes('/welcome'));
    await ctx.close();
  }

  ok('no page errors', !errors.length, errors.slice(0, 5).join(' | '));
  await browser.close();
  fs.writeFileSync(REPORT, JSON.stringify(report, null, 1));
  const be = Object.keys(report.backend).length;
  console.log(`backend-sourced Chinese in English mode on ${be} views (not failures; see ${REPORT})`);
  const pass = results.filter((r) => r[1]).length;
  console.log(`${pass}/${results.length} passed`);
  process.exit(pass === results.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
