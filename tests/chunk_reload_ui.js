// 4.6.2 发新版不打断开着的页面（B 机，先启动 serve；会在 WEB_DIR 里重新构建两次 web/dist）：node tests/chunk_reload_ui.js
//   1. 开着一个旧页面（工作台）→ 用 VF_BUILD_TAG 重新构建一个"内容变了"的新版本（文件名全换了）→ 旧页面再打开一个没加载过的面板、进一个懒加载的页面：
//      旧版本的文件还在（emptyOutDir: false + 只删最近 2 次构建以外的旧文件），照常加载，不刷新、不报错。
//   2. 缓存头：index.html 是 no-cache，assets 里带哈希的文件是长期缓存（immutable）。
//   3. 模拟文件真拿不到（拦截返回 404）：面板（defineAsyncComponent）和路由懒加载都提示"已更新到新版本，正在刷新…"并刷新一次；
//      1 分钟内再失败不再刷新（不会死循环），改成提示手动刷新。
//   4. 再构建一次：最早那次构建的文件删掉了，清单里只留最近 2 次。最后不带标记再构建一次，把 dist 恢复成平常的样子。
// 环境变量：VF_URL（默认 http://127.0.0.1:8800）、WEB_DIR（默认 tests/../web）、SHOT_DIR。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800';
const WEB = process.env.WEB_DIR || path.join(__dirname, '..', 'web');
const DIST = path.join(WEB, 'dist');
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_chunk_reload');
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 260)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const login = async (u, p) => (await api('', 'POST', '/api/login', { username: u, password: p })).token;
const build = (tag) => {
  const t0 = Date.now();
  const out = execSync('npx vite build', { cwd: WEB, env: { ...process.env, VF_BUILD_TAG: tag || '' }, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
  const line = (out.match(/\[vf\] 构建[^\n]*/) || [''])[0];
  console.log(`   构建 ${tag || '（不带标记）'}：${Math.round((Date.now() - t0) / 1000)} 秒 ${line}`);
  return JSON.parse(fs.readFileSync(path.join(DIST, '.vf-builds.json'), 'utf-8'));
};
const buildId = () => (fs.readFileSync(path.join(DIST, 'index.html'), 'utf-8').match(/name="vf-build" content="([^"]+)"/) || [])[1];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const A = await login('admin', 'honey123');
  const plant = process.env.VF_PLANT || 'foundry-housing';          // 有设备的工厂（空工厂一打开就自动开资源库）
  const PANELS = [['outliner', 'Outliner', '对象'], ['model', 'ModelPanel', '检查与改动'], ['library', 'Library', '资源库'], ['breakpoints', 'Breakpoints', '断点']];
  const tag = 't' + String(Date.now()).slice(-6);
  const m0 = build(tag + 'a');
  const id0 = buildId();
  ok('构建 1：清单记下这次构建的文件', m0.builds.length >= 1 && m0.builds[m0.builds.length - 1].files.length > 20, m0.builds.map((b) => `${b.id}:${b.files.length}`).join(' '));

  const br = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const ctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1500, height: 900 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_theme', 'light'); localStorage.setItem('vf_welcome_off', '1');
    localStorage.setItem('vf_guide_off', '1'); localStorage.setItem('vf_teach_tour', '1'); }, A);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  let navs = 0;
  p.on('load', () => { navs++; });
  const failed = [];
  p.on('response', (r) => { if (/\/assets\//.test(r.url()) && r.status() >= 400) failed.push(`${r.status()} ${r.url().split('/').pop()}`); });
  const wait = (ms) => p.waitForTimeout(ms);
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });

  // ---- 1. 旧页面 + 新版本
  await p.goto(`${B}/p/${plant}/workbench`, { waitUntil: 'networkidle' }); await wait(2500);
  const tag0 = await p.evaluate(() => window.__vfStale?.tag);
  ok('页面是构建 1（带标记）', tag0 === tag + 'a', tag0);
  const loadedBefore = await p.evaluate(() => performance.getEntriesByType('resource').map((e) => e.name.split('/').pop()).filter((n) => /\.js$/.test(n)));
  const m1 = build(tag + 'b');
  const id1 = buildId();
  const files0 = new Set(m0.builds[m0.builds.length - 1].files), files1 = new Set(m1.builds[m1.builds.length - 1].files);
  const fresh = PANELS.filter(([, c]) => !loadedBefore.some((n) => n.startsWith(c + '-')));
  const [pid1, chunk1, title1] = fresh[0] || PANELS[0];
  const [pid2, chunk2] = fresh[1] || PANELS[1];
  const re1 = new RegExp('assets/' + chunk1 + '-[A-Za-z0-9_-]+[.]js$');
  const outl0 = [...files0].find((f) => re1.test(f)), outl1 = [...files1].find((f) => re1.test(f));
  ok(`构建 2：内容变了，懒加载的文件换了名字（${chunk1}-xxx.js）`, id1 !== id0 && outl0 && outl1 && outl0 !== outl1, `${outl0} → ${outl1}`);
  ok('构建 2 以后构建 1 的文件还在（清单里留着最近 2 次）', m1.builds.length === 2 && fs.existsSync(path.join(DIST, outl0)), m1.builds.map((b) => `${b.id}:${b.files.length}`).join(' '));
  ok(`旧页面还没加载过「${title1}」面板`, fresh.length >= 2, `没加载过的：${fresh.map((x) => x[0]).join(',')}`);
  const navs0 = navs;
  await p.evaluate((id) => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id } })), pid1);
  await p.waitForFunction((t) => (document.querySelector('.ed-left .sp-h b')?.textContent || '') === t, title1, { timeout: 15000 }).catch(() => null); await wait(2500);
  const outlTxt = await p.locator('.ed-left .sp-body').innerText().catch(() => '');
  const got = await p.evaluate((c) => performance.getEntriesByType('resource').map((e) => e.name.split('/').pop()).filter((n) => n.startsWith(c + '-')), chunk1);
  ok(`旧页面打开没加载过的「${title1}」面板：用的是旧版本的文件，照常显示、没刷新`, got.includes(outl0.split('/').pop()) && navs === navs0 && outlTxt.trim().length > 4
     && !(await p.locator('[data-k="stale-note"]').count()), `${got.join(',')} navs ${navs0}→${navs} ${outlTxt.replace(/\s+/g, ' ').slice(0, 60)}`);
  await shot('c01_old_page_new_panel');
  ok('没有 404 的文件', failed.length === 0, failed.join(', '));

  // ---- 2. 缓存头
  const hi = await fetch(B + '/'), ha = await fetch(`${B}/${outl1}`);
  ok('index.html：no-cache（发新版后刷新就拿到新入口）', /no-cache/.test(hi.headers.get('cache-control') || ''), hi.headers.get('cache-control'));
  ok('assets 里带哈希的文件：长期缓存（immutable）', /immutable/.test(ha.headers.get('cache-control') || '') && /max-age=31536000/.test(ha.headers.get('cache-control') || ''), ha.headers.get('cache-control'));
  const h404 = await fetch(`${B}/assets/Nope-zzzzzz.js`);
  ok('不存在的 assets 文件返回 404（不是 index.html）', h404.status === 404, h404.status);

  // ---- 3. 文件真拿不到：面板 → 提示并刷新一次
  const q = await ctx.newPage();
  q.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  let qn = 0;
  q.on('load', () => { qn++; });                       // 整页加载的次数（路由的 pushState 不算）
  await q.route(new RegExp('/assets/(' + chunk2 + '|Help)-[A-Za-z0-9_-]+[.]js$'), (r) => r.fulfill({ status: 404, body: 'gone' }));
  await q.goto(`${B}/p/${plant}/workbench`, { waitUntil: 'networkidle' }); await q.waitForTimeout(2500);
  await q.evaluate(() => { sessionStorage.removeItem('vf_stale_reload'); window.__mark = 1; });
  const qn0 = qn;
  await q.evaluate((id) => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id } })), pid2);
  await q.waitForSelector('[data-k="stale-note"]', { timeout: 8000 }).catch(() => null);
  const note = await q.locator('[data-k="stale-note"]').innerText().catch(() => '');
  ok('面板文件拿不到：提示"已更新到新版本，正在刷新…"', /已更新到新版本，正在刷新/.test(note), note);
  await q.screenshot({ path: `${OUT}/c02_stale_notice.png` });
  await q.waitForFunction(() => !window.__mark, null, { timeout: 15000 }).catch(() => null);
  await q.waitForLoadState('networkidle').catch(() => null); await q.waitForTimeout(2500);
  ok('自动刷新了一次', qn === qn0 + 1 && !(await q.evaluate(() => window.__mark)), `导航 ${qn - qn0} 次`);
  // 刷新以后还是拿不到（比如服务器真的没有这个文件）：1 分钟内不再刷新
  await q.evaluate(() => { window.__mark = 2; });
  const qn1 = qn;
  await q.evaluate((id) => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id } })), pid2);
  await q.waitForTimeout(4000);
  const note2 = await q.locator('[data-k="stale-note"]').innerText().catch(() => '');
  ok('刚刷新过又失败：不再刷新（不死循环），提示手动刷新', qn === qn1 && (await q.evaluate(() => window.__mark)) === 2 && /Ctrl\+F5/.test(note2)
     && (await q.locator('[data-k="stale-note"]').getAttribute('data-bad')) === '1', `导航 ${qn - qn1} 次：${note2}`);
  await q.screenshot({ path: `${OUT}/c03_stale_no_loop.png` });
  // 路由懒加载（帮助中心）也一样
  await q.evaluate(() => { sessionStorage.removeItem('vf_stale_reload'); window.__mark = 3; });
  await q.goto(`${B}/`, { waitUntil: 'networkidle' }); await q.waitForTimeout(2000);
  await q.evaluate(() => { sessionStorage.removeItem('vf_stale_reload'); window.__mark = 3; });
  const qn2 = qn;
  await q.locator('.el-menu-item:has-text("帮助中心")').first().click().catch(() => null);
  await q.waitForFunction(() => !window.__mark, null, { timeout: 15000 }).catch(() => null);
  await q.waitForTimeout(1500);
  ok('路由懒加载的页面文件拿不到：也刷新一次', qn === qn2 + 1, `导航 ${qn - qn2} 次`);
  await q.close();

  // ---- 4. 再构建：最早那次的文件删掉
  const m2 = build(tag + 'c');
  ok('构建 3：只留最近 2 次构建，构建 1 独有的文件删掉了', m2.builds.length === 2 && !fs.existsSync(path.join(DIST, outl0)) && fs.existsSync(path.join(DIST, outl1)),
     m2.builds.map((b) => `${b.id}:${b.files.length}`).join(' '));
  const left = fs.readdirSync(path.join(DIST, 'assets')).length;
  const keep = new Set(m2.builds.flatMap((b) => b.files));
  ok('assets 里没有清单以外的文件', fs.readdirSync(path.join(DIST, 'assets')).every((f) => keep.has('assets/' + f)), `${left} 个文件`);
  build('');
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await br.close();
  process.exit(bad.length ? 1 : 0);
})();
