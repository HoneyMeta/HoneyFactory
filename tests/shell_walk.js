// 工作台全量走查（B 机，先启动 serve）：node tests/shell_walk.js
// 四个工作区 × 活动栏里的每个面板：逐个打开、确认有内容、截图；带控制单元的工厂（VF_CELL_PLANT，默认 plctest）再走一遍单元编辑器和 PLC。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'walk');
const CELL = process.env.VF_CELL_PLANT || 'plctest';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 200)); };
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
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404|Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  p.on('response', (r) => { if (r.status() >= 500) errs.push(`${r.status()} ${r.url().replace(B, '')}`); });
  const wait = (ms) => p.waitForTimeout(ms);
  const closeFloats = async () => { while (await p.locator('.fl-layer .fw-b[title="关闭"]').count()) { await p.locator('.fl-layer .fw-b[title="关闭"]').first().click(); await wait(200); } };

  async function walk(pid, tag) {
    await p.goto(`${B}/p/${pid}/workbench`, { waitUntil: 'networkidle' }); await wait(8000);
    for (const [ws, label] of [['all', '通用'], ['teach', '教学'], ['design', '设计'], ['debug', '联调']]) {
      await p.click(`.ed-ws button:has-text("${label}")`); await wait(2500);
      await p.screenshot({ path: `${OUT}/${tag}_${ws}_00.png` });
      const ids = await p.$$eval('.ed-act button[data-panel]', (bs) => bs.map((x) => x.getAttribute('data-panel')));
      for (const id of ids) {
        if (ws !== 'all' && !['teach-task', 'plc-editor', 'plc-editor-float', 'plc-hmi', 'plc-external', 'cell-editor', 'cell-editor-float', 'design-report', 'design-sop', 'debug-console', 'debug-console-float', 'teach-console', 'teach-classes', 'teach-publish'].includes(id)) continue;
        const e0 = errs.length;
        // 已经打开的侧栏再点会收起，所以只在没打开时点
        if (!(await p.locator(`.ed-act button[data-panel="${id}"].on`).count())) await p.click(`.ed-act button[data-panel="${id}"]`);
        await wait(2200);
        const fl = await p.locator('.fl-layer .fw').count();
        const txt = fl ? await p.locator('.fl-layer .fw').last().innerText().catch(() => '') : await p.locator('.sp-body').innerText().catch(() => '');
        ok(`${tag} ${label}：${id}`, txt.trim().length > 5 && errs.length === e0, (fl ? '浮窗 ' : '侧栏 ') + txt.replace(/\s+/g, ' ').slice(0, 80) + (errs.length > e0 ? ' | ' + errs.slice(e0).join(' | ') : ''));
        await p.screenshot({ path: `${OUT}/${tag}_${ws}_${id}.png` });
        await closeFloats();
      }
    }
  }
  await walk('foundry-housing', 'g');
  await walk(CELL, 'c');
  // 三维里能看到控制单元
  await p.click('.ed-ws button:has-text("通用")'); await wait(1500);
  await p.click('.ed-views >> text=三维'); await wait(3000);
  ok('三维里有控制单元', await p.evaluate(() => !!(window).__vfCellScene), '');
  await p.screenshot({ path: `${OUT}/c_3d.png` });
  ok('页面没有报错', errs.length === 0, errs.slice(0, 6).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
