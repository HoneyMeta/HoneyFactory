// 5.0.2 验收：课程卡片按钮刚进页面就点也要打开课程；非管理员看不到真实网卡和主机名；课程编辑器工具栏不被面包屑挡住（页面不多出可滚动的一截）。
// 先启动 serve（VF_DEMO=1 建好演示账号）：node tests/v502_ui.js
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const login = async (username, password) => {
  const r = await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username, password }) });
  return (await r.json()).token;
};
const meta = async (tok) => {
  const r = await fetch(B + '/api/p/foundry-housing/meta', { headers: { 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok } });
  return { status: r.status, body: r.ok ? await r.json() : null };
};
const page4 = async (b, tok, w, h) => {
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: w, height: h } });
  await ctx.addInitScript((t) => {
    localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); sessionStorage.setItem('vf_pw_later', '1');
    localStorage.setItem('vf_guide_off', '1'); localStorage.setItem('vf_teach_tour', '1'); localStorage.setItem('vf_whatsnew_seen', '9.9.9'); localStorage.setItem('vf_start_tour_done', '1');
  }, tok);
  return ctx.newPage();
};

(async () => {
  const admin = await login('admin', 'honey123'), teacher = await login('demo_teacher', 'teach123'), student = await login('demo_s01', '123456');
  // ---- 接入地址
  const a = await meta(admin), t = await meta(teacher);
  ok('管理员看得到主机名和网卡', a.body && a.body.endpoints.hostname && (a.body.endpoints.hosts || []).length >= 1, JSON.stringify(a.body && a.body.endpoints.hosts));
  if (t.status === 200) {
    const e = t.body.endpoints, text = JSON.stringify(e);
    ok('老师的接入地址只用访问服务器的地址', e.hostname == null && JSON.stringify(e.hosts) === '["127.0.0.1"]' && (e.opcua || '').includes('127.0.0.1'), text);
    ok('老师拿不到真实 IP', !(a.body.endpoints.hosts || []).some((h) => h !== '127.0.0.1' && text.includes(h)));
  } else ok('老师读 meta 被拒（也不泄露）', t.status === 403 || t.status === 401, t.status);

  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  // ---- 课程卡片按钮：刚进页面就用真实鼠标点（点之前重新量坐标）
  const pg = await page4(b, student, 1680, 1050);
  let tries = 0, fails = [];
  for (const round of [1, 2]) {
    for (const delay of [0, 100, 300, 600, 1000, 1500]) {
      await pg.goto(B + '/welcome'); await pg.waitForTimeout(800);
      await pg.evaluate(() => { history.pushState({}, '', '/courses'); dispatchEvent(new PopStateEvent('popstate')); });
      const btn = pg.locator('[data-k="card-continue"]').first();
      await btn.waitFor({ state: 'visible', timeout: 15000 });
      await pg.waitForTimeout(delay);
      const bb = await btn.boundingBox();
      await pg.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await pg.mouse.down(); await pg.mouse.up();
      tries++;
      const opened = await pg.waitForFunction(() => /[?&]l=\d+/.test(location.search) || !!document.querySelector('.lesson-wrap'), null, { timeout: 15000 }).then(() => true).catch(() => false);
      if (!opened) fails.push(`第 ${round} 轮 延迟 ${delay}ms`);
    }
  }
  ok(`课程卡片按钮点 ${tries} 次都打开课程`, !fails.length, fails.join('；'));
  await pg.context().close();

  // ---- 课程编辑器：多种窗口下工具栏不被面包屑挡住，页面没有多余滚动
  for (const [w, h] of [[1680, 1050], [1280, 720]]) {
    const p = await page4(b, teacher, w, h);
    await p.goto(B + '/courses');
    await p.locator('button:has-text("新建课程")').first().click();
    await p.locator('.el-message-box input, .el-dialog input').first().fill('验收课程 ' + w);
    await p.locator('button:has-text("建好去编辑")').click();
    await p.locator('[data-k="course-editor"]').waitFor({ state: 'visible', timeout: 20000 }).catch(async (e) => { await p.screenshot({ path: require('path').join(process.env.SHOT_DIR || require('os').tmpdir(), 'editor_fail.png') }); console.log('DBG', p.url(), (await p.locator('body').innerText()).slice(0, 300).split(String.fromCharCode(10)).join(' | ')); throw e; });
    await p.waitForTimeout(800);
    const m = await p.evaluate(() => {
      const main = document.querySelector('.main'), top = document.querySelector('.ce-top').getBoundingClientRect(), cr = document.querySelector('.crumbs');
      main.scrollTop = 9999;
      const after = document.querySelector('.ce-top').getBoundingClientRect(), crb = cr ? cr.getBoundingClientRect().bottom : 0;
      return { over: main.scrollHeight - main.clientHeight, scrolled: main.scrollTop, topBefore: top.top, topAfter: after.top, crumbsBottom: crb };
    });
    ok(`${w}×${h} 编辑器工具栏不被面包屑挡住`, m.topAfter >= m.crumbsBottom - 0.5 && m.scrolled <= 1, JSON.stringify(m));
    await p.context().close();
  }
  await b.close();
  const passed = res.filter((r) => r[1]).length;
  console.log(`\n${passed}/${res.length} 通过`);
  process.exit(passed === res.length ? 0 : 1);
})().catch((e) => { console.error('FAIL 走查中断', e); process.exit(1); });
