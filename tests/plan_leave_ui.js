// 4.7 生产计划：没应用的修改不再悄悄丢掉（B 机，先启动 serve）：node tests/plan_leave_ui.js
// 1280×720 和 1680×960：
//   页面写"点击「应用计划」后生效"；改了以后显示"有未应用的修改"；
//   切到别的页面（场景）→ 弹出"应用 / 放弃 / 继续编辑"：继续编辑留在本页、修改还在；放弃 → 离开，回来是原来的计划；应用 → 离开，计划生效；
//   应用后显示"已应用到运行中的工厂，尚未保存到工厂配置"，点「保存到工厂配置」后写进配置（接口 saved = true）；
//   刷新页面（beforeunload）会提示；工作台里的"生产计划"浮窗：关浮窗、切工作区时同样提示。
// 最后把计划恢复原样（应用 + 保存）。截图在 SHOT_DIR。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'plan_leave');
const PLANT = process.env.VF_PLANT || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(typeof detail === 'string' ? detail : JSON.stringify(detail)).slice(0, 800)); };
const api = async (tok, m, u, b) => { const r = await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); };

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const tok = (await api('', 'POST', '/api/login', { username: 'admin', password: 'honey123' })).token;
  const P = `/api/p/${PLANT}`;
  const orig = await api(tok, 'GET', P + '/plan');
  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const nBreaks = async () => ((await api(tok, 'GET', P + '/plan')).cfg.breaks || []).length;
  try {
    for (const [W, H] of [[1280, 720], [1680, 960]]) {
      const sz = `${W}×${H}`;
      const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: W, height: H } });
      await ctx.addInitScript((t) => {
        if (sessionStorage.getItem('pl_init')) return; sessionStorage.setItem('pl_init', '1');
        localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); localStorage.setItem('vf_ws', 'all');
        sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_guide_off', '1'); localStorage.setItem('vf_whatsnew_seen', '9.9.9');
      }, tok);
      const p = await ctx.newPage();
      p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
      const dialogs = [];
      p.on('dialog', (d) => { dialogs.push(d.type()); d.dismiss().catch(() => null); });
      const wait = (ms) => p.waitForTimeout(ms);
      const dirty = () => p.locator('[data-k="plan-dirty"]').isVisible().catch(() => false);
      const leaveDlg = () => p.locator('.el-dialog:visible:has([data-k="plan-leave-apply"])');
      const addBreak = async (scope = '') => { await p.locator(`${scope} .card:has(h3:has-text("休息")) button:has-text("+ 休息"), ${scope} h3:has-text("休息") button:has-text("+ 休息")`).first().click(); await wait(400); };
      const base = await nBreaks();

      await p.goto(`${B}/p/${PLANT}/plan`, { waitUntil: 'networkidle' }); await wait(1500);
      const head = await p.locator('.page-head .sub').innerText();
      ok(`${sz} 页面写"点击「应用计划」后生效"（不再说"修改后立即生效"）`, head.includes('点击「应用计划」后生效') && !head.includes('立即生效'), head);
      ok(`${sz} 没改的时候不显示"有未应用的修改"`, !(await dirty()));
      await addBreak();
      ok(`${sz} 改了以后显示"有未应用的修改"`, await dirty());
      await p.screenshot({ path: `${OUT}/plan_dirty_${W}x${H}.png` });

      // 切到"场景"：弹出确认；继续编辑
      await p.locator(`.side .el-menu-item:has-text("场景")`).first().click(); await wait(800);
      ok(`${sz} 离开页面时弹出"应用 / 放弃 / 继续编辑"`, await leaveDlg().isVisible().catch(() => false));
      await p.screenshot({ path: `${OUT}/plan_leave_dialog_${W}x${H}.png` });
      await p.locator('[data-k="plan-leave-stay"]').click(); await wait(800);
      ok(`${sz} 继续编辑：还在生产计划页，修改还在`, p.url().endsWith('/plan') && (await dirty()), p.url());
      // 放弃
      await p.locator(`.side .el-menu-item:has-text("场景")`).first().click(); await wait(800);
      await p.locator('[data-k="plan-leave-discard"]').click(); await wait(1500);
      ok(`${sz} 放弃：去了场景页，计划没变`, p.url().endsWith('/scenarios') && (await nBreaks()) === base, p.url());
      await p.goto(`${B}/p/${PLANT}/plan`, { waitUntil: 'networkidle' }); await wait(1200);
      ok(`${sz} 回来是原来的计划（没有未应用的修改）`, !(await dirty()) && (await p.evaluate(() => window.__vfPlan?.dirty?.() === false)));
      // 应用
      await addBreak();
      await p.locator(`.side .el-menu-item:has-text("场景")`).first().click(); await wait(800);
      await p.locator('[data-k="plan-leave-apply"]').click(); await wait(2000);
      ok(`${sz} 应用：计划生效后离开`, p.url().endsWith('/scenarios') && (await nBreaks()) === base + 1, await nBreaks());
      const g1 = await api(tok, 'GET', P + '/plan');
      ok(`${sz} 接口：已应用、还没保存到工厂配置`, g1.saved === false, g1.saved);
      await p.goto(`${B}/p/${PLANT}/plan`, { waitUntil: 'networkidle' }); await wait(1200);
      const note = await p.locator('[data-k="plan-unsaved"]').innerText().catch(() => '');
      ok(`${sz} 页面提示"已应用到运行中的工厂，尚未保存到工厂配置"，有保存按钮`, note.includes('已应用到运行中的工厂') && note.includes('尚未保存到工厂配置') && (await p.locator('[data-k="plan-save"]').isVisible()), note);
      await p.screenshot({ path: `${OUT}/plan_unsaved_${W}x${H}.png` });
      await p.locator('[data-k="plan-save"]').click(); await wait(1500);
      const g2 = await api(tok, 'GET', P + '/plan');
      ok(`${sz} 保存到工厂配置：接口 saved = true，页面显示已保存`, g2.saved === true && (await p.locator('[data-k="plan-saved"]').isVisible().catch(() => false)), g2.saved);
      await p.screenshot({ path: `${OUT}/plan_saved_${W}x${H}.png` });
      // 刷新：beforeunload
      await addBreak();
      dialogs.length = 0;
      await p.reload({ waitUntil: 'domcontentloaded', timeout: 8000 }).catch(() => null); await wait(1200);
      ok(`${sz} 有未应用的修改时刷新页面会提示（beforeunload）`, dialogs.includes('beforeunload'), dialogs.join(','));
      await p.locator('[data-k="plan-discard"]').click().catch(() => null); await wait(500);       // 选了"留下"：放弃修改再走
      ok(`${sz} 「放弃修改」按钮：恢复成已应用的计划`, !(await dirty()));

      // 工作台里的"生产计划"浮窗
      await p.goto(`${B}/p/${PLANT}/workbench`, { waitUntil: 'domcontentloaded' });
      await p.waitForSelector('.ed-act button[data-panel]', { timeout: 60000 }); await wait(5000);
      await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plan' } }))); await wait(2500);
      const fw = '.fw[data-float="plan"]';
      ok(`${sz} 工作台：生产计划浮窗打开`, await p.locator(fw).isVisible().catch(() => false));
      await addBreak(fw);
      ok(`${sz} 浮窗里改了：显示"有未应用的修改"`, await p.locator(`${fw} [data-k="plan-dirty"]`).isVisible().catch(() => false));
      await p.locator(`${fw} .fw-b[title="关闭"]`).click(); await wait(800);
      const askedClose = await leaveDlg().isVisible().catch(() => false);
      await p.screenshot({ path: `${OUT}/plan_float_close_${W}x${H}.png` });
      await p.locator('[data-k="plan-leave-stay"]').click().catch(() => null); await wait(800);
      ok(`${sz} 关浮窗时提示；继续编辑 → 浮窗还开着`, askedClose && (await p.locator(fw).isVisible().catch(() => false)));
      // 点活动栏的"生产计划"图标（再点一下 = 收起浮窗）：提示；放弃 → 浮窗关掉
      await p.locator('.ed-act button[data-panel="plan"]').first().click(); await wait(800);
      const askedAct = await leaveDlg().isVisible().catch(() => false);
      await p.locator('[data-k="plan-leave-discard"]').click().catch(() => null); await wait(1200);
      const st = await p.evaluate(() => ({ floats: window.__vfEd.floats.map((f) => f.id) }));
      ok(`${sz} 点活动栏图标收起浮窗时提示；放弃 → 浮窗关掉`, askedAct && !st.floats.includes('plan'), JSON.stringify(st));
      // 浮窗开着、改了，再离开工作台（路由）：同样提示
      await p.evaluate(() => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plan' } }))); await wait(2000);
      await addBreak(fw);
      await p.locator('.ed-brand').first().click(); await wait(800);
      const askedRoute = await leaveDlg().isVisible().catch(() => false);
      await p.locator('[data-k="plan-leave-stay"]').click().catch(() => null); await wait(800);
      ok(`${sz} 浮窗里有没应用的修改时离开工作台：提示；继续编辑 → 留在工作台`, askedRoute && p.url().endsWith('/workbench'), p.url());
      await p.locator(`${fw} [data-k="plan-discard"]`).click().catch(() => null); await wait(400);
      ok(`${sz} 浮窗里放弃的修改没有生效`, (await nBreaks()) === base + 1, await nBreaks());
      await ctx.close();
      // 恢复：把测试加的休息去掉并保存
      await api(tok, 'PUT', P + '/plan', orig.cfg); await api(tok, 'POST', P + '/plan/save', {});
    }
  } finally {
    await api(tok, 'PUT', P + '/plan', orig.cfg).catch(() => null);
    if (orig.saved !== false) await api(tok, 'POST', P + '/plan/save', {}).catch(() => null);
  }
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
