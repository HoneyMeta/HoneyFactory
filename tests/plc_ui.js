// PLC 编程环境界面验收（B 机；先启动 serve 和 PLC 开发页 vite --config web/vite.plc.config.ts）：
//   node tests/plc_ui.js [工厂] [控制单元]
// 从空白程序开始，在梯形图编辑器里用键盘和拖放写出“启停自锁 + 运行灯”，编译、下载、运行；按下启动后看在线通电高亮；
// 再测 ST 编辑器（错误标注、在线值）、变量表、I/O 监视、HMI、外接 PLC 面板。截图在 SHOT_DIR（默认系统临时目录下的 vf-shots/）。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const API = process.env.VF_URL || 'http://127.0.0.1:8820';
const DEV = process.env.PLC_DEV || 'http://127.0.0.1:5182';
const OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'shots');
const PID = process.argv[2] || 'plctest', BID = process.argv[3] || 'CELL1';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 300)); };
const api = async (tok, method, url, body) => (await fetch(API + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: body ? JSON.stringify(body) : undefined })).json();

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const tok = (await (await fetch(API + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const C = `/api/p/${PID}/cells/${BID}`;
  // 从空白开始
  await api(tok, 'PUT', C + '/plc/external', { mode: 'internal' });
  await api(tok, 'PUT', C + '/program', { id: 'main', name: '主程序', lang: 'LD', vars: [], source: { rungs: [{ comment: '', elements: [] }] } });
  await api(tok, 'POST', C + '/plc', { action: 'stop' });
  await api(tok, 'POST', C + '/plc', { action: 'unforce_all' });
  await api(tok, 'POST', C + '/plc', { action: 'breakpoint', clear: true });
  await api(tok, 'POST', `/api/p/${PID}/ctl`, { action: 'play' });
  await api(tok, 'POST', `/api/p/${PID}/sim`, { speed: 1 });
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1600, height: 940 } });
  await ctx.addInitScript((t) => localStorage.setItem('vf_token', t), tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 300)));
  p.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errs.push('console: ' + m.text().slice(0, 300)); });
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}${process.env.PLC_THEME ? '_' + process.env.PLC_THEME : ''}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  const main = p.locator('.dv-body');
  const typeOp = async (text) => { const i = main.locator('.opedit input'); await i.waitFor({ timeout: 3000 }); await i.fill(text); await i.press('Enter'); await wait(150); };

  await p.goto(`${DEV}/plc-dev.html?pid=${PID}&view=all`, { waitUntil: 'domcontentloaded' });
  await wait(1500);
  ok('开发页加载，梯形图编辑器出现', await main.locator('.lde').count() === 1, await p.title());
  await shot('p01_blank');

  // ---- 键盘写第一个梯级：B1（启动） ‖ C1_FWD（自锁） — B2（停止按钮常闭接法，用常开触点） — (C1_FWD)
  await main.locator('.rung').first().locator('.rh').click();
  await p.keyboard.press('c'); await typeOp('B1');
  await p.keyboard.press('c'); await typeOp('B2');
  await p.keyboard.press('o'); await typeOp('C1_FWD');
  // 选中 B1，加并联分支
  await main.locator('.rung').first().locator('g.el[data-t="NO"]').first().click();
  await p.keyboard.press('v'); await typeOp('C1');
  await wait(200);
  await shot('p02_rung1');
  // 撤销/重做
  await main.locator('.lde-body').focus();
  await p.keyboard.press('Control+z'); await p.keyboard.press('Control+z'); await wait(150);      // 撤销“填变量”和“加并联”两步
  const nAfterUndo = await main.locator('.rung').first().locator('g.el').count();
  await p.keyboard.press('Control+y'); await p.keyboard.press('Control+y'); await wait(150);
  const nAfterRedo = await main.locator('.rung').first().locator('g.el').count();
  ok('撤销/重做', nAfterUndo === 3 && nAfterRedo === 4, `${nAfterUndo} → ${nAfterRedo}`);
  // 梯级注释
  await main.locator('.rung').first().locator('.cmt').dblclick();
  await main.locator('.cmt-in').fill('启停自锁：按启动输送线运行，按停止停');
  await main.locator('.cmt-in').press('Enter');

  // ---- 第二个梯级用拖放：常开 C1_FWD → 线圈 LP1
  await main.locator('.rung-add').click(); await wait(200);
  const tbNO = main.locator('.lde-tools button[data-tool="NO"]');
  const rung2 = main.locator('.rung').nth(1);
  await tbNO.dispatchEvent('dragstart', { dataTransfer: await p.evaluateHandle(() => new DataTransfer()) });
  await wait(150);
  const drop = rung2.locator('rect.drop').first();
  const nd = await drop.count();
  if (nd) { await drop.dispatchEvent('dragover', { dataTransfer: await p.evaluateHandle(() => new DataTransfer()) }); await drop.dispatchEvent('drop', { dataTransfer: await p.evaluateHandle(() => new DataTransfer()) }); }
  await typeOp('C1_FWD');
  const tbCoil = main.locator('.lde-tools button[data-tool="COIL"]');
  await tbCoil.dispatchEvent('dragstart', { dataTransfer: await p.evaluateHandle(() => new DataTransfer()) });
  await wait(150);
  const drops2 = rung2.locator('rect.drop');
  const last = drops2.nth((await drops2.count()) - 1);
  await last.dispatchEvent('dragover', { dataTransfer: await p.evaluateHandle(() => new DataTransfer()) });
  await last.dispatchEvent('drop', { dataTransfer: await p.evaluateHandle(() => new DataTransfer()) });
  await typeOp('LP1');
  ok('拖放：工具条拖到梯级上放下元件', nd > 0 && await rung2.locator('g.el').count() === 2, `drop 目标 ${nd} 个，元件 ${await rung2.locator('g.el').count()}`);
  await shot('p03_two_rungs');

  // ---- 编译、下载、运行
  await main.locator('button[data-act="compile"]').click(); await wait(800);
  const foot = await main.locator('.pw-foot').innerText();
  ok('编译通过', foot.includes('编译通过'), foot);
  await main.locator('span[data-act="download"]').click(); await wait(1200);
  await main.locator('button[data-act="run"]').click(); await wait(800);
  const state = await main.locator('[data-state]').innerText();
  ok('下载后运行', state.includes('运行'), state);
  const prog = (await api(tok, 'GET', C + '/program')).program;
  const r0 = prog.source.rungs[0];
  ok('程序结构：并联(B1‖C1_FWD) + B2 + 线圈', JSON.stringify(r0.elements.map((x) => x.par ? 'par' : x.t + ':' + x.var)) === JSON.stringify(['par', 'NO:B2', 'COIL:C1_FWD']) &&
    r0.elements[0].par.map((b) => b[0].var).join(',') === 'B1,C1_FWD' && r0.comment.startsWith('启停自锁'), JSON.stringify(r0));
  await shot('p04_online_idle');

  // ---- 按启动（单元面板按钮），看通电高亮
  await api(tok, 'POST', `/api/p/${PID}/station/${BID}/write`, { tag: 'Panel/B1', value: true });
  await wait(1600);
  await shot('p05_start_pressed');
  await api(tok, 'POST', `/api/p/${PID}/station/${BID}/write`, { tag: 'Panel/B1', value: false });
  await wait(1600);
  const on = await api(tok, 'GET', C + '/online');
  ok('启动后自锁：C1_FWD 和 LP1 都为 1', on.vars.C1_FWD === true && on.vars.LP1 === true, JSON.stringify(on.vars));
  const green = await main.locator('.rung').first().locator('line.wire.p').count();
  const closed = await main.locator('.rung').first().locator('.sym.closed').count();
  ok('在线：通电导线高亮、触点闭合显示', green >= 4 && closed >= 2, `通电导线 ${green}，闭合 ${closed}`);
  await shot('p06_online_running');
  // 右键强制
  await main.locator('.rung').nth(1).locator('g.el[data-t="COIL"]').click({ button: 'right' });
  await wait(200);
  await shot('p07_context_menu');
  const forceItem = main.locator('.ctx .it', { hasText: '强制 LP1 = FALSE' });
  ok('右键菜单有强制项', await forceItem.count() === 1);
  if (await forceItem.count()) await forceItem.click();
  await wait(900);
  const on2 = await api(tok, 'GET', C + '/online');
  ok('右键强制 LP1 = FALSE 生效', on2.forced.LP1 === false && on2.io.find((r) => r.name === 'LP1').value === false, JSON.stringify(on2.forced));
  ok('强制标记 F 显示', await main.locator('.fbadge').count() >= 1);
  await shot('p08_forced');
  await api(tok, 'POST', C + '/plc', { action: 'unforce_all' });
  // 断点
  await main.locator('.rung').nth(1).locator('.bpdot').click(); await wait(900);
  const halted = await main.locator('.rung.halt').count();
  ok('梯级断点：暂停在梯级 2', halted === 1 && (await main.locator('[data-state]').innerText()).includes('暂停'));
  await wait(1300);
  const bar = p.locator('[data-plc-halt]');
  ok('S29：断点命中时编辑器外有提示条（停在梯级 2，继续/单步）', await bar.count() === 1 && (await bar.innerText()).includes('梯级 2') && await bar.locator('[data-act="halt-continue"]').count() === 1,
    await bar.count() ? await bar.innerText() : '');
  await shot('p09_breakpoint');
  const stt = await api(tok, 'GET', `/api/p/${PID}/plc/status`);
  ok('S29：状态接口给外壳列 PLC 断点', (stt.plcs || stt.cells).find((c) => c.bid === BID || (c.devices || []).includes(BID))?.bps?.[0]?.label?.startsWith('梯级 2'), JSON.stringify(stt.cells.map((c) => c.bps)));
  await main.locator('.rung').nth(1).locator('.bpdot').click(); await wait(300);
  await bar.locator('[data-act="halt-continue"]').click(); await wait(1500);
  ok('取消断点后点提示条“继续”运行', (await main.locator('[data-state]').innerText()).includes('运行') && await p.locator('[data-plc-halt]').count() === 0);
  // S25：右键把常开改成常闭再改回来
  await main.locator('.rung').nth(1).locator('g.el[data-t="NO"]').click({ button: 'right' }); await wait(200);
  const toNc = main.locator('.ctx .it', { hasText: '改为常闭触点' });
  ok('S25：右键菜单有“改为常闭触点”', await toNc.count() === 1);
  await shot('p09b_context_change');
  if (await toNc.count()) await toNc.click();
  await wait(200);
  ok('S25：改为常闭后元件变成 NC', await main.locator('.rung').nth(1).locator('g.el[data-t="NC"]').count() === 1);
  await main.locator('.lde-body').focus(); await p.keyboard.press('Control+z'); await wait(200);
  ok('S25：撤销后改回常开', await main.locator('.rung').nth(1).locator('g.el[data-t="NO"]').count() === 1);
  // 停止按钮（常闭）
  await api(tok, 'POST', `/api/p/${PID}/station/${BID}/write`, { tag: 'Panel/B2', value: true });
  await wait(1500);
  await api(tok, 'POST', `/api/p/${PID}/station/${BID}/write`, { tag: 'Panel/B2', value: false });
  await wait(1200);
  const on3 = await api(tok, 'GET', C + '/online');
  ok('按停止后输送线停', on3.vars.C1_FWD === false, JSON.stringify(on3.vars));

  // ---- 功能块盒子
  await main.locator('.rung').nth(1).locator('g.el[data-t="NO"]').click();
  await p.keyboard.press('b'); await wait(200);
  const inp = main.locator('.opedit input');
  if (await inp.count()) { await inp.fill('T#3s'); await inp.press('Enter'); }
  await wait(300);
  await shot('p10_fb_box');
  ok('功能块盒子（TON）插入、自动建实例', await main.locator('g.el[data-t="FB"]').count() === 1 && await main.locator('text.inst').first().textContent() === 'T1');

  // ---- 变量表、I/O 监视
  await main.locator('button[data-tab="vars"]').click(); await wait(500);
  await shot('p11_vars');
  const vtNames = await main.locator('.vt').evaluate((el) => [...el.querySelectorAll('input')].map((i) => i.value).join(',') + '|' + el.innerText);
  ok('变量表显示 I/O 和实例', vtNames.includes('C1_FWD') && vtNames.includes('T1') && vtNames.includes('TON'), vtNames.slice(0, 200));
  await main.locator('button[data-tab="io"]').click(); await wait(600);
  ok('S5：I/O 表有触点类型和静止值（停止按钮 常闭（1））', (await main.locator('.iot').innerText()).includes('常闭（1）'), (await main.locator('.iot').innerText()).slice(0, 200));
  await shot('p12_io');
  await main.locator('button[data-tab="timing"]').click(); await wait(1800);
  ok('时序图：画出波形', await main.locator('[data-timing] path.wave').count() >= 3, await main.locator('[data-timing] path.wave').count());
  const tb = await main.locator('.tc-body').boundingBox();
  await p.mouse.click(tb.x + tb.width * 0.6, tb.y + 20); await wait(300);
  ok('时序图：点一下放游标并冻结', (await main.locator('.tc-bar').innerText()).includes('A '));
  await shot('p12b_timing');
  await main.locator('button[data-tab="xref"]').click(); await wait(1200);
  ok('交叉引用：列出变量和读写位置', await main.locator('[data-xref="C1_FWD"] .loc').count() >= 2, await main.locator('[data-xref]').count());
  await shot('p12c_xref');
  await main.locator('button[data-tab="prog"]').click(); await wait(300);
  await main.locator('span[data-act="download"]').click(); await wait(1200);

  // ---- ST 编辑器（练习 PLC）
  await main.locator('.cellsel').click(); await wait(300);
  await p.locator('.el-select-dropdown__item', { hasText: '练习 PLC' }).last().click(); await wait(1200);
  await api(tok, 'PUT', `/api/p/${PID}/cells/_sandbox/program`, { lang: 'ST', vars: [{ name: 'T1', type: 'TON' }, { name: 'n', type: 'INT', comment: '计数' }],
    source: 'PROGRAM Main\n(* 启停自锁 + 每秒计数 *)\nMotor := (Start OR Motor) AND NOT Stop;\nLamp_Run := Motor\nT1(IN := Motor AND NOT T1.Q, PT := T#1s);\nIF T1.Q THEN\n    n := n + 1;\nEND_IF;\nDisplay := n;\nEND_PROGRAM\n' });
  // 重新读取工程
  await main.locator('.pw-bar .el-dropdown').last().click(); await wait(200);
  await p.locator('.el-dropdown-menu__item', { hasText: '重新读取工程' }).last().click(); await wait(1000);
  ok('ST 编辑器出现（CodeMirror）', await main.locator('.cm-editor').count() === 1);
  await main.locator('button[data-act="compile"]').click(); await wait(800);
  ok('ST 编译错误标在第 4 行', (await main.locator('.pw-foot').innerText()).includes('第 4 行') && await main.locator('.cm-lintRange-error').count() >= 1, await main.locator('.pw-foot').innerText());
  await shot('p13_st_error');
  // 改正：在第 4 行末尾补分号
  await main.locator('.cm-line').nth(3).click();
  await p.keyboard.press('End'); await p.keyboard.type(';');
  // 自动补全
  await p.keyboard.press('End'); await p.keyboard.press('Enter'); await p.keyboard.type('Lamp_F');
  await wait(500);
  const acShown = await p.locator('.cm-tooltip-autocomplete').count();
  await p.keyboard.press('Enter'); await p.keyboard.type(' := n > 5;');
  ok('ST 自动补全弹出', acShown === 1);
  await main.locator('span[data-act="download"]').click(); await wait(1500);
  ok('ST 下载运行', (await main.locator('[data-state]').innerText()).includes('运行'), await main.locator('.pw-foot').innerText());
  await api(tok, 'POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'force', name: 'Start', value: true }); await wait(400);
  await api(tok, 'POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'force', name: 'Start', value: null }); await wait(2600);
  ok('ST 在线值显示在变量后面', await main.locator('.st-val.t').count() >= 2, await main.locator('.st-val').count());
  await shot('p14_st_online');
  // ST 断点：点第 7 行的断点栏
  const gb = await main.locator('.st-bpg').boundingBox();
  const lb = await main.locator('.cm-line').nth(6).boundingBox();          // 第 7 行：T1(…) 调用
  await p.mouse.click(gb.x + gb.width / 2, lb.y + lb.height / 2); await wait(900);
  ok('ST 断点命中、暂停行高亮', await main.locator('.st-halt').count() === 1 && (await main.locator('[data-state]').innerText()).includes('暂停'));
  await shot('p15_st_breakpoint');
  await api(tok, 'POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'breakpoint', clear: true });
  await api(tok, 'POST', `/api/p/${PID}/cells/_sandbox/plc`, { action: 'run' });

  // ---- 侧栏（紧凑）
  const side = p.locator('.dv-side');
  ok('侧栏：状态、I/O 监视', (await side.innerText()).includes('输入') && await side.locator('.plc-chip').count() >= 1);

  // ---- HMI
  await p.goto(`${DEV}/plc-dev.html?pid=${PID}&view=hmi`, { waitUntil: 'domcontentloaded' }); await wait(1200);
  for (const h of (await api(tok, 'GET', `/api/p/${PID}/hmi`)).items) if (String(h.source).startsWith('user')) await api(tok, 'DELETE', `/api/p/${PID}/hmi/${h.id}`);
  await p.reload({ waitUntil: 'domcontentloaded' }); await wait(1000);
  await api(tok, 'PUT', `/api/p/${PID}/hmi/panel1`, { name: '输送线操作面板', cell: BID, size: [900, 480], widgets: [
    { id: 'w0', type: 'rect', x: 20, y: 20, w: 400, h: 200, label: '操作', color: '#7d8893' },
    { id: 'w1', type: 'button', x: 40, y: 50, w: 120, h: 50, label: '启动', var: 'B1', mode: 'momentary', color: '#1f9d55' },
    { id: 'w2', type: 'button', x: 180, y: 50, w: 120, h: 50, label: '停止', var: 'B2', mode: 'momentary', color: '#c83a3a' },
    { id: 'w3', type: 'lamp', x: 40, y: 130, w: 140, h: 50, label: '运行', var: 'LP1', color: '#22c55e' },
    { id: 'w4', type: 'lamp', x: 200, y: 130, w: 160, h: 50, label: '光电 S1', var: 'S1', color: '#f2b632' },
    { id: 'w5', type: 'number', x: 460, y: 40, w: 160, h: 60, label: 'T1 已计时', var: 'T1.ET', unit: '' },
    { id: 'w6', type: 'trend', x: 460, y: 130, w: 400, h: 200, label: '输送线 / 光电', vars: ['C1_FWD', 'S1'], min: 0, max: 1.2 },
    { id: 'w7', type: 'text', x: 40, y: 250, w: 380, h: 30, label: '蜂元虚拟工厂 · 输送线', size: 18 }] });
  await p.reload({ waitUntil: 'domcontentloaded' }); await wait(1500);
  const btn = p.locator('.w-button .hbtn').first();
  await btn.dispatchEvent('pointerdown'); await wait(900);
  await btn.dispatchEvent('pointerup'); await wait(1500);
  const on4 = await api(tok, 'GET', C + '/online');
  ok('HMI 点动按钮（输入强制）启动输送线', on4.vars.C1_FWD === true && !Object.keys(on4.forced || {}).length, JSON.stringify(on4.vars) + JSON.stringify(on4.forced));
  await wait(1500);
  ok('HMI 指示灯亮', await p.locator('.w-lamp .bulb[style*="box-shadow"]').count() >= 1);
  await shot('p16_hmi_run');
  await p.locator('.hb .el-radio-button', { hasText: '组态' }).click(); await wait(400);
  await p.locator('.w-lamp').first().click(); await wait(300);
  await shot('p17_hmi_edit');
  ok('HMI 组态：属性面板', (await p.locator('.props').innerText()).includes('绑定变量'));

  // ---- 外接 PLC 面板
  await p.goto(`${DEV}/plc-dev.html?pid=${PID}&view=ext`, { waitUntil: 'domcontentloaded' }); await wait(1500);
  await shot('p18_external');
  ok('外接 PLC 面板：映射表', (await p.locator('.xp').innerText()).includes('信号映射') || (await p.locator('.xp').innerText()).includes('控制方式'));
  // 浅色主题
  await p.goto(`${DEV}/plc-dev.html?pid=${PID}&view=all`, { waitUntil: 'domcontentloaded' }); await wait(2000);
  await shot('p19_light');

  // ---- 场景单元：参考答案（只读对比）、期望时序
  if (process.argv[4]) {
    const SPID = process.argv[4];
    await api(tok, 'POST', `/api/p/${SPID}/ctl`, { action: 'play' });
    await api(tok, 'POST', `/api/p/${SPID}/sim`, { speed: 1 });
    await p.goto(`${DEV}/plc-dev.html?pid=${SPID}&view=workbench`, { waitUntil: 'domcontentloaded' }); await wait(2500);
    await main.locator('.pw-bar .el-dropdown').last().click(); await wait(300);
    await p.locator('.el-dropdown-menu__item[data-act="reference"]').last().click(); await wait(1500);
    ok('T18：载入参考答案（只读对比）', await main.locator('.refv').count() === 1 && await main.locator('.refv .lde-ro, .refv .cm-editor').count() >= 1);
    await shot('p20_reference');
    await main.locator('button[data-tab="timing"]').click(); await wait(1500);
    const specBox = main.locator('[data-act="tc-spec"]');
    ok('期望时序：场景单元可以叠加', await specBox.count() === 1);
    if (await specBox.count()) await specBox.click();
    const io = (await api(tok, 'GET', `/api/p/${SPID}/cells/CELL1/program`)).io;
    const startName = io.find((e) => /START/i.test(e.name))?.name || 'START';
    await api(tok, 'POST', `/api/p/${SPID}/cells/CELL1/panel`, { comp: startName, action: 'press', hold: 0.3 });
    await wait(3500);
    ok('期望时序：对齐后显示检查结果', /期望检查|已对齐/.test(await main.locator('.tc-bar').innerText()), await main.locator('.tc-bar').innerText());
    await shot('p21_timing_spec');
  }
  ok('页面没有脚本错误', !errs.length, errs.join(' | '));
  await b.close();
  const n = res.filter((r) => r[1]).length;
  console.log(`\n${n}/${res.length} 通过`);
  process.exit(n === res.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
