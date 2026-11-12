// 4.6 弹出层被裁剪检查（B 机，先启动 serve）：node tests/popup_clip_ui.js
// 管理员打开示范工厂工作台，四个工作区里活动栏的每个侧栏 / 浮窗都打开一遍，在里面点开下拉选择、下拉菜单、日期选择、悬停提示、
// 在 ECharts 图表上移动鼠标出提示框，然后检查每个看得见的弹出层：没被浮窗 / 面板的边裁掉、没被别的东西盖住、整个在窗口里。
// 另外：右栏页签、左边活动栏的提示文字不带"（浮窗）"。截图在 SHOT_DIR（每个出问题的地方一张）。
// 4.7：两种窗口各跑一遍——1440×900 和最小支持分辨率 1280×720（紧凑布局自动打开；第二行的"更多"菜单也点开看）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const { SCAN } = require('./ui_scan');
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'popup_clip');
const PLANT = process.env.VF_PLANT || 'foundry-housing';
const SIZES = [[1440, 900], [1280, 720]];
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 1500)); };

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  for (const [W, H] of SIZES) {
    const sz = `${W}×${H}`;
    const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: W, height: H } });
    await ctx.addInitScript((t) => {
      if (sessionStorage.getItem('pc_init')) return; sessionStorage.setItem('pc_init', '1');
      localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_ws', 'all');
      sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_guide_off', '1'); localStorage.removeItem('vf_wb2_sizes');
      localStorage.removeItem('vf_right_open'); localStorage.removeItem('vf_tl_open'); localStorage.removeItem('vf_compact');
    }, tok);
    await ctx.addInitScript({ content: SCAN });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
    const wait = (ms) => p.waitForTimeout(ms);
    await p.goto(`${B}/p/${PLANT}/workbench`, { waitUntil: 'domcontentloaded' });
    await p.waitForSelector('.ed-act button[data-panel]', { timeout: 60000 });
    await wait(6000);

    const problems = [];
    let triggers = 0, popped = 0, shots = 0;
    async function check(scopeName, what) {
      const ps = await p.evaluate(() => window.__vfScan.poppers());
      if (ps.length) popped++;
      const bad = ps.filter((x) => x.clipped || x.covered || x.outOfView);
      for (const x of bad) problems.push(`${scopeName} · ${what} → ${x.what} @${x.where} clipped=${x.clipped}(${x.frac}) covered=${x.covered}${x.by ? '(' + x.by + ')' : ''} out=${x.outOfView} ${JSON.stringify(x.rect)}`);
      if (bad.length && shots < 25) await p.screenshot({ path: `${OUT}/bad_${W}x${H}_${String(++shots).padStart(2, '0')}_${scopeName.replace(/[^\w-]/g, '_')}.png` });
      return ps;
    }
    /** 收起弹出层：点一下作用域的标题栏（点外面）。 */
    async function away(scope) {
      const h = await p.$(scope === '.ed-left' ? '.ed-left .sp-h b' : scope === '.ed-right' ? '.ed-status' : scope === '.ed-bar' ? '.ed-status' : `${scope} .fw-h b`);
      if (h) await h.click({ force: true }).catch(() => null); else await p.mouse.click(W - 5, H - 5);
      await wait(250);
    }
    /** 一个作用域（浮窗 / 侧栏 / 右栏）里的弹出层都点开看一遍。 */
    async function probe(scope, name) {
      const visible = async (sel, n) => {
        const hs = await p.$$(`${scope} ${sel}`);
        const out = [];
        for (const h of hs) { if (out.length >= n) break; const bb = await h.boundingBox().catch(() => null); if (bb && bb.width > 4 && bb.height > 4 && bb.y > 0 && bb.y + bb.height < H) out.push(h); }
        return out;
      };
      for (const h of await visible('.el-select__wrapper, .el-select .el-input__wrapper', 4)) {
        triggers++; await h.click().catch(() => null); await wait(450); await check(name, 'select'); await away(scope);
      }
      for (const h of await visible('.el-dropdown', 3)) {
        triggers++; await h.hover().catch(() => null); await wait(350); await h.click().catch(() => null); await wait(450); await check(name, 'dropdown'); await away(scope);
      }
      for (const h of await visible('.el-date-editor', 2)) {
        triggers++; await h.click().catch(() => null); await wait(500); await check(name, 'date'); await away(scope);
      }
      for (const h of await visible('.el-tooltip__trigger', 4)) {
        triggers++; await h.hover().catch(() => null); await wait(500); await check(name, 'tooltip');
      }
      for (const h of await visible('[_echarts_instance_]', 4)) {
        const bb = await h.boundingBox(); if (!bb) continue;
        for (const [fx, fy] of [[0.5, 0.5], [0.85, 0.5], [0.96, 0.3], [0.96, 0.85], [0.6, 0.92], [0.15, 0.6]]) {
          triggers++; await p.mouse.move(bb.x + bb.width * fx, bb.y + bb.height * fy, { steps: 3 }); await wait(350); await check(name, `chart(${fx},${fy})`);
        }
        await p.mouse.move(2, H / 2); await wait(200);
      }
    }

    // ---------------- 四个工作区 × 活动栏 ----------------
    const done = new Set();
    const wsN = await p.locator('.ed-ws button').count();
    const tipBad = [];
    for (let wi = 0; wi < wsN; wi++) {
      await p.locator('.ed-ws button').nth(wi).click(); await wait(1500);
      const ids = await p.$$eval('.ed-act button[data-panel]', (bs) => bs.map((x) => [x.getAttribute('data-panel'), x.classList.contains('float')]));
      for (const [id, isFloat] of ids) {
        if (done.has(id)) continue;
        done.add(id);
        const btn = p.locator(`.ed-act button[data-panel="${id}"]`).first();
        await btn.hover(); await wait(450);
        const tip = await p.evaluate(() => [...document.querySelectorAll('.el-popper')].filter((e) => getComputedStyle(e).display !== 'none').map((e) => e.innerText.trim()).pop() || '');
        if (/浮窗/.test(tip)) tipBad.push(`${id}:${tip}`);
        await btn.click(); await wait(isFloat ? 3500 : 2200);
        if (!isFloat && !(await p.evaluate((id) => window.__vfEd.leftOpen && window.__vfEd.leftPanel === id, id))) { await btn.click(); await wait(2000); }   // 本来就开着：第一下是收起
        const scope = isFloat ? `.fw[data-float="${id}"]` : '.ed-left';
        if (!(await p.$(scope))) { problems.push(`${id}: 打不开`); continue; }
        await probe(scope, id);
        if (isFloat) { await p.locator(`${scope} .fw-b[title="关闭"]`).click().catch(() => null); await wait(300); }
      }
    }
    ok(`${sz} 活动栏提示文字不带"（浮窗）"`, tipBad.length === 0, tipBad.join(' | '));
    // ---------------- 右栏每个页签 ----------------
    await p.locator('.ed-ws button').nth(0).click(); await wait(800);
    await p.evaluate(() => { const e = window.__vfEd; e.sel = [(e.model.blocks.find((b) => b.type === 'processor') || e.model.blocks[0]).id]; }); await wait(800);
    const tabs = await p.$$eval('.ed-right .el-tabs__item', (ts) => ts.map((t) => t.id));
    for (const t of tabs) { await p.locator(`.ed-right #${t}`).click().catch(() => null); await wait(1500); await probe('.ed-right', 'right:' + t); }
    // ---------------- 工具栏（紧凑布局下有"更多"菜单） ----------------
    await probe('.ed-bar', 'bar');
    // ---------------- 分析浮窗：重点看图表提示框 ----------------
    await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'analysis' } }))); await wait(4000);
    const an = await p.$('.fw[data-float="analysis"] [_echarts_instance_]');
    if (an) {
      const bb = await an.boundingBox();
      let seen = 0, clip = 0;
      for (const fx of [0.6, 0.8, 0.95]) for (const fy of [0.2, 0.5, 0.9]) {
        await p.mouse.move(bb.x + bb.width * fx, bb.y + bb.height * fy, { steps: 3 }); await wait(400);
        const ps = (await p.evaluate(() => window.__vfScan.poppers())).filter((x) => x.what === 'echarts-tooltip');
        if (ps.length) seen++;
        if (ps.some((x) => x.clipped || !x.inBody)) clip++;
      }
      await p.screenshot({ path: `${OUT}/analysis_tooltip_light_${W}x${H}.png` });
      ok(`${sz} 分析浮窗：图表提示框出现、挂在 body 上、不被浮窗边裁掉`, seen > 0 && clip === 0, `看到 ${seen} 次，被裁 ${clip} 次`);
    } else ok(`${sz} 分析浮窗里有图表`, false);

    ok(`${sz} 弹出层没有被裁掉 / 盖住 / 跑出窗口（${done.size} 个面板，${triggers} 次触发，${popped} 次出了弹出层）`, problems.length === 0, problems.slice(0, 30).join('\n'));
    ok(`${sz} 确实点出了弹出层（检查不是空跑）`, popped >= 20, popped);
    await ctx.close();
  }
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
