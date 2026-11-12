// 5.0 交付包按钮（B 机，先启动 serve）：node tests/delivery_ui.js
// 信号中心 / 工作台的"交付包"按钮、对话框、浏览器导出三维模型打包下载、原始现场模式开关（确认框）
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'vw'), PID = process.env.VF_PLANT || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const api = async (tok, m, u, b) => (await fetch(B + u, { method: m, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok }, body: b ? JSON.stringify(b) : undefined })).json();
const zipNames = (buf) => { const out = []; for (let i = 0; i < buf.length - 46; i++) if (buf.readUInt32LE(i) === 0x02014b50) { const n = buf.readUInt16LE(i + 28); out.push(buf.slice(i + 46, i + 46 + n).toString('utf8')); i += 45 + n; } return out; };
const zipSize = (buf, name) => { for (let i = 0; i < buf.length - 46; i++) if (buf.readUInt32LE(i) === 0x02014b50) { const n = buf.readUInt16LE(i + 28); if (buf.slice(i + 46, i + 46 + n).toString('utf8') === name) return buf.readUInt32LE(i + 24); } return -1; };
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const b = await pw.chromium.launch({ channel: 'chrome', args });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  if ((await api(tok, 'GET', `/api/p/${PID}/delivery/raw_site`)).on) await api(tok, 'PUT', `/api/p/${PID}/delivery/raw_site`, { on: false });
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 960 }, acceptDownloads: true });
  await ctx.addInitScript((t) => { localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); }, tok);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  const wait = (ms) => p.waitForTimeout(ms);
  try {
    await p.goto(`${B}/p/${PID}/signals`, { waitUntil: 'networkidle' }); await wait(2500);
    const btn = p.locator('[data-k=delivery-btn]').first();
    ok('信号中心有"交付包"按钮', await btn.isVisible());
    await btn.click(); await wait(1500);
    const dlg = p.locator('.delivery-dlg');
    ok('交付包对话框：设备数、点数、动作设备', await dlg.isVisible() && /设备 \d+ 台、点位 \d+ 个/.test(await dlg.innerText()) && /CNC1/.test(await dlg.innerText()), (await dlg.innerText()).slice(0, 160));
    await shot('d01_dialog');
    const t0 = Date.now();
    const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 180000 }), p.click('[data-k=delivery-go]')]);
    const f = `${OUT}/delivery-ui.zip`;
    await dl.saveAs(f);
    const buf = fs.readFileSync(f);
    const names = zipNames(buf);
    const simple = Buffer.from(await (await fetch(`${B}/api/p/${PID}/delivery.zip`, { headers: { 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + tok } })).arrayBuffer());
    ok('浏览器导出界面三维模型并打包下载', names.includes('models/scene.glb') && names.includes('points.xlsx') && names.includes('layout.dxf') && names.includes('models/cnc.glb'),
      `${names.length} 个文件，${(buf.length / 1024).toFixed(0)} KB，${((Date.now() - t0) / 1000).toFixed(1)} s`);
    ok('界面模型比服务端简化模型细（场景 GLB 更大）', zipSize(buf, 'models/scene.glb') > zipSize(simple, 'models/scene.glb'), `${zipSize(buf, 'models/scene.glb')} vs ${zipSize(simple, 'models/scene.glb')}`);
    await wait(800); await shot('d02_downloaded');
    // 原始现场模式开关（确认框）
    await p.click('[data-k=raw-site]'); await wait(800);
    await shot('d03_raw_confirm');
    const tSw = Date.now();
    await p.click('.el-message-box__btns .el-button--primary');
    await p.waitForSelector('.el-message--success', { timeout: 60000 }).catch(() => {});      // 切换完成（协议层重建好）才弹"已打开"
    ok('打开原始现场模式（界面开关 → 接口）', (await api(tok, 'GET', `/api/p/${PID}/delivery/raw_site`)).on === true, `${((Date.now() - tSw) / 1000).toFixed(1)} s`);
    await wait(1500);
    await shot('d04_raw_on');
    await p.keyboard.press('Escape'); await wait(800);
    await p.fill('.tree input', 'Spindle/Load').catch(() => {}); await wait(3500);
    await shot('d05_signals_raw');
    const pts = await api(tok, 'GET', `/api/p/${PID}/points`);
    const row = pts.find((r) => r['工位'].startsWith('CNC1 ') && r['点位'] === 'Monitoring/Spindle/Load');
    ok('原始现场：信号中心的点表接口显示原始地址', row && /\/jj\/M1_ZZFZ$/.test(row['MQTT 主题']), row && row['MQTT 主题']);
    await api(tok, 'PUT', `/api/p/${PID}/delivery/raw_site`, { on: false });
    // 工作台里的按钮
    await p.goto(`${B}/p/${PID}/workbench`, { waitUntil: 'networkidle' }); await wait(6000);
    const wb = p.locator('[data-k=delivery-btn]').first();
    ok('工作台工具栏有"交付包"按钮', await wb.isVisible());
    await shot('d06_workbench');
    await wb.click(); await wait(1200);
    ok('工作台打开交付包对话框', await p.locator('.delivery-dlg').isVisible());
    await shot('d07_workbench_dialog');
    ok('没有页面错误', !errs.length, errs.slice(0, 3).join(' | '));
  } catch (e) {
    ok('脚本没有异常', false, e.message);
    await shot('d99_error').catch(() => {});
  } finally {
    await api(tok, 'PUT', `/api/p/${PID}/delivery/raw_site`, { on: false }).catch(() => {});
    await b.close();
  }
  const bad = res.filter(([, g]) => !g).map(([n]) => n);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : ''));
  process.exit(bad.length ? 1 : 0);
})();
