// 建模（工作台里的流程图/平面图）界面验收（B 机，先启动 serve）：node tests/editor_ui.js [tour,build,ai]
// tour  ：示范工厂的流程图 / 选中 / 平面图 / 三维截图
// build ：新建空白工厂，只用鼠标键盘搭一条机加线（来料→缓存→加工×2→检测→返修→出口 + 人员池），试运行、应用，计时
// ai    ：选中设备问 AI、让 AI 提修改并写进草稿，然后撤销
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'ed');
const only = process.argv[2] ? process.argv[2].split(',') : ['tour', 'build'];
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const api = async (tok, method, url, body) => (await fetch(B + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: body ? JSON.stringify(body) : undefined })).json();

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 } });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.removeItem('vf_ed_sizes'); }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  const node = (id) => p.locator(`.vue-flow__node[data-id="${id}"]`);
  const tile = (label) => p.locator('.tile', { has: p.locator('span', { hasText: new RegExp(`^${label}$`) }) });
  const field = (label) => p.locator('.dt .f', { has: p.locator('label', { hasText: new RegExp(`^${label}`) }) });

  if (only.includes('tour')) {
    await api(tok, 'DELETE', '/api/p/foundry-housing/model/draft');
    await p.goto(B + '/p/foundry-housing/editor', { waitUntil: 'networkidle' }); await wait(4000);
    await p.click('.ed-views >> text=流程'); await wait(2500);
    ok('编辑器打开（流程图）', await p.locator('.vue-flow__node').count() > 20, `${await p.locator('.vue-flow__node').count()} 个卡片`);
    await shot('e01_graph');
    await p.dblclick('.ol-i:has-text("CNC3")'); await wait(1500);
    ok('选中卡片显示细节', await p.locator('.dt-name input').inputValue().then((v) => v.length > 0), await p.locator('.dt-name input').inputValue());
    await shot('e02_select');
    await p.click('.ed-views >> text=平面'); await wait(1500);
    ok('平面图', await p.locator('.pv-svg .blk').count() > 20);
    await shot('e03_plan');
    await p.click('.ed-views >> text=三维'); await wait(9000);
    ok('三维视图', await p.locator('.scene-host canvas').count() === 1);
    await shot('e04_3d');
    await p.click('.ed-views >> text=流程'); await wait(1200);
    await p.keyboard.press('Control+k'); await wait(400); await p.keyboard.type('INS'); await wait(400);
    await shot('e05_palette');
    await p.keyboard.press('Enter'); await wait(1200);
    ok('命令面板跳转', (await p.locator('.dt-name input').inputValue()).length > 0, await p.locator('.dt-name input').inputValue());
  }

  if (only.includes('build')) {
    const c = await api(tok, 'POST', '/api/plants', { name: '界面搭建测试', template: 'blank' });
    ok('新建空白工厂', c.id, c.id);
    const pid = c.id;
    const t0 = Date.now();
    await p.goto(`${B}/p/${pid}/workbench`, { waitUntil: 'networkidle' }); await wait(2500);
    await p.click('.ed-views >> text=流程'); await wait(1200);
    await shot('b01_blank');
    // 空工厂打开时资源库已经展开（4.1 新手引导）；没展开才点
    if (!(await p.locator('.ed-act button[data-panel="library"].on').count())) await p.click('.ed-act button[data-panel="library"]');
    await wait(400);
    // 选中谁就接在谁后面：双击资源库里的块，自动连线
    for (const lab of ['来料', '缓存', '加工', '检测', '出口']) { await tile(lab).dblclick(); await wait(500); }
    await wait(1500);
    const m1 = await api(tok, 'GET', `/api/p/${pid}/model`);
    ok('双击资源库成链', m1.model.blocks.length === 5 && m1.model.links.length === 4, `${m1.model.blocks.length} 块 ${m1.model.links.length} 线`);
    // 第二台加工：选中缓存再双击加工，然后把它连到检测
    await p.click('.ed-act button[data-panel="outliner"]'); await wait(300);
    await p.click('.ol-i:has-text("B1")'); await wait(300);
    await p.click('.ed-act button[data-panel="library"]'); await wait(300);
    await tile('加工').dblclick(); await wait(700);
    await p.keyboard.press('Home'); await wait(800);
    const drag = async (fromSel, toSel) => {
      const a = await p.locator(fromSel).boundingBox(), z = await p.locator(toSel).boundingBox();
      await p.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await p.mouse.down();
      await p.mouse.move((a.x + z.x) / 2, (a.y + z.y) / 2 + 30, { steps: 8 });
      await p.mouse.move(z.x + z.width / 2, z.y + z.height / 2, { steps: 8 }); await p.mouse.up(); await wait(600);
    };
    await drag('.vue-flow__node[data-id="M2"] .vue-flow__handle[data-handleid="out"]', '.vue-flow__node[data-id="QC1"] .vue-flow__handle[data-handleid="in"]');
    // 从检测的 NG 拖到空白处 → 快速添加返修
    const ng = await p.locator('.vue-flow__node[data-id="QC1"] .vue-flow__handle[data-handleid="ng"]').boundingBox();
    await p.mouse.move(ng.x + ng.width / 2, ng.y + ng.height / 2); await p.mouse.down(); await p.mouse.move(ng.x + 60, ng.y + 160, { steps: 12 }); await p.mouse.up(); await wait(700);
    ok('拖到空白处弹出快速添加', await p.locator('.qa').isVisible());
    await p.keyboard.type('返修'); await wait(300); await shot('b02_quickadd'); await p.keyboard.press('Enter'); await wait(800);
    await p.keyboard.press('Home'); await wait(800);
    await drag('.vue-flow__node[data-id="RW1"] .vue-flow__handle[data-handleid="out"]', '.vue-flow__node[data-id="QC1"] .vue-flow__handle[data-handleid="in"]');
    // 人员池
    await p.click('.vue-flow__pane', { position: { x: 30, y: 30 } }); await wait(200);
    await tile('人员池').dblclick(); await wait(600);
    // 参数：两台加工都用人员池、加工时间 normal(150,8)
    await p.keyboard.press('Home'); await wait(800);
    await node('M1').click(); await node('M2').click({ modifiers: ['Shift'] }); await wait(500);
    ok('多选批量编辑', await p.locator('.dt-head b:has-text("已选 2 个块")').count() === 1);
    await field('加工时间').locator('input').fill('normal(150,8)'); await field('加工时间').locator('input').press('Enter'); await wait(800);
    await field('人员池').locator('.el-select').click(); await wait(300); await p.locator('.el-select-dropdown__item:visible', { hasText: 'OP1' }).first().click(); await wait(600);
    await node('SRC1').click(); await wait(400);
    await field('到达间隔').locator('input').fill('expo(80)'); await field('到达间隔').locator('input').press('Enter'); await wait(800);
    await p.keyboard.press('Home'); await wait(800);
    await shot('b03_built');
    const m2 = await api(tok, 'GET', `/api/p/${pid}/model`);
    const v = m2.validation;
    ok('搭好的模型校验通过', v.ok, JSON.stringify(v.summary) + ' ' + v.issues.map((i) => i.msg).join('；').slice(0, 200));
    ok('块和连线齐全', m2.model.blocks.length === 8 && m2.model.links.length === 8, `${m2.model.blocks.length} 块 ${m2.model.links.length} 线`);
    // 平面图里对齐：全选 → 顶对齐 → 水平等距
    await p.click('.ed-views >> text=平面'); await wait(1200);
    await p.keyboard.press('Control+a'); await wait(300);
    await p.click('.pv-align button:has-text("⤒")'); await wait(400); await p.click('.pv-align button:has-text("⋯")'); await wait(600);   // 多选时画布上方的对齐条（4.4，和流程图一样）
    await shot('b04_plan');
    await p.click('.ed-views >> text=流程'); await wait(800);
    // 试运行 2 小时
    // 试运行在左侧"检查与改动"面板里（外壳 4.0）
    if (!(await p.locator('.ed-act button[data-panel="model"].on').count())) await p.click('.ed-act button[data-panel="model"]');
    await wait(500);
    await p.click('.sp-body .el-radio-button:has-text("试运行")'); await wait(400);
    await p.click('.sp-body button.el-button:has-text("试运行")'); await wait(500);
    await p.locator('.tt').waitFor({ timeout: 120000 }).catch(() => {});
    ok('试运行出结果', await p.locator('.tt').count() === 1);
    await shot('b05_tryrun');
    // 应用到工厂
    await p.click('.ed-menu button:has-text("保存")'); await wait(600);
    await p.click('.el-dialog__footer button:has-text("保存")'); await wait(6000);
    const secs = Math.round((Date.now() - t0) / 1000);
    const st = await api(tok, 'GET', `/api/p/${pid}/state`);
    ok('应用后工厂运行', st.stations && st.stations.length === 8, `${st.stations?.length} 个工位，用时 ${secs} 秒（含等待）`);
    await wait(8000);
    await shot('b06_running');
    const st2 = await api(tok, 'GET', `/api/p/${pid}/state`);
    ok('运行叠加可见', await p.locator('.bn-rt').count() >= 6, `${await p.locator('.bn-rt').count()} 张卡片有状态；合格 ${st2.kpi?.good}`);
    await api(tok, 'DELETE', `/api/plants/${pid}`);
  }

  ok('页面没有报错', errs.length === 0, errs.slice(0, 5).join(' | '));
  const bad = res.filter((r) => !r[1]).map((r) => r[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  await b.close();
})();
