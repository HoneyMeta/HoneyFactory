// 外壳走查截图（B 机，先启动 serve）：node tests/shell_shots.js
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'sh');
(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); if (!sessionStorage.getItem('i')) { sessionStorage.setItem('i', '1'); localStorage.removeItem('vf_wb2_sizes'); localStorage.setItem('vf_ws', 'all'); localStorage.setItem('vf_ai_open', '0'); } }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  const act = (title) => p.locator('.ed-act button').nth(titles.indexOf(title));
  let titles = [];
  await p.goto(B + '/p/foundry-housing/workbench', { waitUntil: 'networkidle' }); await wait(9000);
  titles = await p.$$eval('.ed-act button', (bs) => bs.map((x) => x.getAttribute('aria-describedby') || ''));
  await shot('s01_shell');
  const btns = p.locator('.ed-act button');
  const n = await btns.count();
  console.log('activity buttons', n);
  // 依次点前 6 个（侧栏）
  for (let i = 0; i < Math.min(n - 2, 7); i++) { await btns.nth(i).click(); await wait(900); await shot(`s02_left_${i}`); }
  // 浮窗：分析、报表
  for (let i = 7; i < Math.min(n - 2, 16); i++) { await btns.nth(i).click(); await wait(2500); }
  await shot('s03_floats');
  await p.click('.ed-ws button:has-text("设计")'); await wait(2500); await shot('s04_design');
  await p.click('.ed-ws button:has-text("联调")'); await wait(2500); await shot('s05_debug');
  await p.click('.ed-ws button:has-text("教学")'); await wait(2500); await shot('s06_teach');
  console.log(errs.length ? 'ERRORS ' + errs.join(' | ') : 'no errors');
  await b.close();
})();
