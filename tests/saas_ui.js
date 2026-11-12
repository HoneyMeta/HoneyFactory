// 5.0 SaaS 界面走查（Playwright）：运维后台登录（TOTP 在测试里算）→ 开户 → 单位管理员建老师、导入学生 → 席位用完的提示 →
// 老师在"班级进度"里看到学生（客户端）上报的进度 → SaaS 模式下学生的客户端不能在服务器上跑工厂（本机照常）。
// 需要：SaaS 服务器 VF_URL（VF_MODE=saas，全新的 VF_HOME）、客户端 VF_CLIENT_URL（desktop --home VF_CLIENT_HOME，还没登录过）；
//       VF_HOME（服务器的数据目录：用 tools/ops_admin.py 建第一个运维账号）、VF_PY + VF_LAUNCHER（跑 python 的方式）。
//       VF_CLIENT2_URL / VF_CLIENT2_HOME：第二个客户端（老师用，课程在客户端里做）；服务器设 VF_STUCK_MIN=0.2（12 秒算卡住，测试用）。
//   node tests/saas_ui.js        截图在 SHOT_DIR
// 最后一段是"走一遍每个页面"：浏览器（单位管理员、老师、学生）和客户端（老师、学生）各页面，记下所有 403（死胡同），一个都不能有。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const SV = process.env.VF_URL || 'http://127.0.0.1:8820';
const CL = process.env.VF_CLIENT_URL || 'http://127.0.0.1:8826';
const CHOME = process.env.VF_CLIENT_HOME;
const CL2 = process.env.VF_CLIENT2_URL || 'http://127.0.0.1:8829';
const CHOME2 = process.env.VF_CLIENT2_HOME;
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'data', 'ui_saas');
const STAMP = new Date().toISOString().slice(11, 19).replace(/:/g, '');
const ORG = 'ui' + STAMP.slice(-4);
const res = [];
let ORG_T1 = '';
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 240)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (base, tok, method, url, body, extra = {}) => {
  const r = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), ...extra }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  j._status = r.status;
  return j;
};
const login = async (u, p) => (await api(SV, '', 'POST', '/api/login', { username: u, password: p })).token;

// ---------- TOTP（RFC 6238）：服务器不认用过的时间片，每次取比上次大的（±1 窗口内） ----------
function b32(s) {
  const A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = ''; const out = [];
  for (const c of s.replace(/=+$/, '').toUpperCase()) bits += A.indexOf(c).toString(2).padStart(5, '0');
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}
function totpAt(secret, counter) {
  const b = Buffer.alloc(8); b.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac('sha1', b32(secret)).update(b).digest();
  const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, '0');
}
let SECRET = '', LAST = 0;
async function totp() {
  for (;;) {
    const cur = Math.floor(Date.now() / 30000);
    for (const c of [cur - 1, cur, cur + 1]) if (c > LAST) { LAST = c; return totpAt(SECRET, c); }
    await sleep(1000);
  }
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const h = await api(SV, '', 'GET', '/api/health');
  ok('服务器是 SaaS 模式、不跑工厂', h.deploy === 'saas' && Array.isArray(h.plants) && h.plants.length === 0, JSON.stringify(h));
  // 第一个运维账号：命令行（tools/ops_admin.py），和部署文档里一样
  const OPW = 'OpsUi' + STAMP + 'x7';
  const py = process.env.VF_PY || 'python', launcher = process.env.VF_LAUNCHER;
  const out = execFileSync(py, [...(launcher ? [launcher] : []), 'tools/ops_admin.py', 'create', '--username', 'ops.ui' + STAMP, '--name', '界面测试运维', '--password', OPW],
    { cwd: path.join(__dirname, '..'), env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).toString();
  ok('命令行建第一个运维账号', /已建运维账号/.test(out), out);

  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
  const br = await pw.chromium.launch({ channel: 'chrome', args }).catch(() => pw.chromium.launch({ args }));
  const errs = [];
  const watch = (p) => {
    p.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
    p.on('console', (m) => { if (m.type() === 'error' && !/favicon|40[0-9]|Failed to load resource/.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
  };
  const prompt = async (p, value) => {        // Element Plus 的 ElMessageBox.prompt
    await p.waitForSelector('.el-message-box input', { timeout: 10000 });
    await p.locator('.el-message-box input').fill(value);
    await p.locator('.el-message-box__btns .el-button--primary').click();
  };

  // ================================================================ 1. 运维后台：登录、绑定 TOTP、恢复码
  const octx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 900 } });
  const o = await octx.newPage(); watch(o);
  await o.goto(`${SV}/ops`, { waitUntil: 'networkidle' });
  await o.locator('input[data-k="ops-user"]').fill('ops.ui' + STAMP);
  await o.locator('input[data-k="ops-pw"]').fill(OPW);
  await o.screenshot({ path: `${OUT}/s01_ops_login.png` });
  await o.locator('[data-k="ops-login"]').click();
  await o.waitForSelector('[data-k="ops-qr"] svg', { timeout: 15000 });
  SECRET = (await o.locator('[data-k="ops-secret"]').innerText()).trim();
  ok('第一次登录：显示二维码和密钥', SECRET.length >= 16 && (await o.locator('[data-k="ops-qr"] svg').count()) === 1, SECRET);
  await o.screenshot({ path: `${OUT}/s02_ops_enroll_qr.png` });
  await o.locator('input[data-k="ops-code"]').fill(await totp());
  await o.locator('[data-k="ops-enroll"]').click();
  await o.waitForSelector('[data-k="ops-codes"] code', { timeout: 15000 });
  const codes = await o.locator('[data-k="ops-codes"] code').count();
  ok('绑定成功：10 个恢复码（只显示一次）', codes === 10, codes);
  await o.screenshot({ path: `${OUT}/s03_ops_recovery_codes.png` });
  await o.locator('[data-k="ops-codes-ok"]').click();
  await o.waitForSelector('[data-k="ops-orgs"]', { timeout: 15000 });
  ok('进入运维后台：单位列表', (await o.locator('[data-k="ops-who"]').innerText()).includes('ops.ui'));

  // ================================================================ 2. 开户（敏感操作：再输验证码）
  await o.locator('[data-k="ops-new-org"]').click();
  await o.locator('input[data-k="ops-org-id"]').fill(ORG);
  await o.locator('input[data-k="ops-org-name"]').fill(`界面测试学院 ${STAMP}`);
  await o.locator('[data-k="ops-org-teachers"] input').fill('2');
  await o.locator('[data-k="ops-org-students"] input').fill('3');
  await o.locator('input[data-k="ops-org-admin"]').fill(`${ORG}.admin`);
  await o.screenshot({ path: `${OUT}/s04_ops_new_org.png` });
  await o.locator('[data-k="ops-org-save"]').click();
  await prompt(o, await totp());
  await o.waitForSelector('[data-k="ops-new-pw"]', { timeout: 15000 });
  const adminPw = (await o.locator('[data-k="ops-new-pw"]').innerText()).trim();
  ok('开户成功：单位管理员的初始密码只显示这一次', adminPw.length >= 10, adminPw.length);
  await o.screenshot({ path: `${OUT}/s05_ops_org_created.png` });
  await o.locator('[data-k="ops-secret-ok"]').click();
  await o.waitForTimeout(800);
  ok('单位列表里有新单位：老师 0/2、学生 0/3', /0 \/ 2/.test(await o.locator('[data-k="ops-orgs"]').innerText()) && /0 \/ 3/.test(await o.locator('[data-k="ops-orgs"]').innerText()));
  await o.locator('.el-tabs__item:has-text("审计")').click();
  await o.locator('[data-k="ops-verify-chain"]').click();
  await o.waitForTimeout(800);
  ok('审计页：哈希链完整', /完整/.test(await o.locator('[data-k="ops-chain"]').innerText().catch(() => '')));
  await o.screenshot({ path: `${OUT}/s06_ops_audit.png` });

  // ================================================================ 3. 单位管理员：改初始密码 → 单位管理 → 建老师 → 席位满
  const actx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const a = await actx.newPage(); watch(a);
  await a.goto(`${SV}/login`, { waitUntil: 'networkidle' });
  await a.locator('.box input').nth(0).fill(`${ORG}.admin`);
  await a.locator('.box input').nth(1).fill(adminPw);
  await a.locator('.box button:has-text("登录")').click();
  await a.waitForSelector('input[data-k="pw-new"]', { timeout: 20000 });
  const APW = 'Admin' + STAMP + 'k9';
  await a.locator('input[data-k="pw-new"]').fill(APW); await a.locator('input[data-k="pw-new2"]').fill(APW);
  await a.locator('[data-k="pw-save"]').click();
  await a.waitForURL(/\/org/, { timeout: 20000 }).catch(() => null);
  await a.waitForSelector('[data-k="org-page"]', { timeout: 20000 }).catch(() => null);
  ok('单位管理员：临时密码必须先改，然后到"单位管理"', /\/org/.test(a.url()), a.url());
  ok('SaaS 网页端：侧栏没有"全部工厂"', (await a.locator('.el-menu-item:has-text("全部工厂")').count()) === 0);
  for (const [u, n] of [['t1', '王老师'], ['t2', '李老师']]) {
    await a.locator('[data-k="org-new-teacher"]').click();
    await prompt(a, `${ORG}.${u},${n}`);
    await a.waitForSelector('[data-k="org-accounts"]', { timeout: 10000 });
    if (u === 't1') ORG_T1 = (await a.locator('[data-k="org-accounts"] tbody td').nth(2).innerText()).trim();
    await a.locator('.el-dialog__footer button:has-text("关闭")').click();
    await a.waitForTimeout(500);
  }
  ok('建了 2 名老师', (await a.locator('[data-k="org-teachers"] tbody tr').count()) === 2);
  await a.locator('[data-k="org-new-teacher"]').click();
  await prompt(a, `${ORG}.t3,赵老师`);
  await a.waitForSelector('.el-message--error', { timeout: 10000 }).catch(() => null);
  const err = await a.locator('.el-message--error').first().innerText().catch(() => '');
  ok('第 3 名老师：席位满了，提示还剩 0 个、怎么办', /席位不够/.test(err) && /还剩 0/.test(err), err);
  await a.screenshot({ path: `${OUT}/s07_org_teacher_seat_full.png` });

  // 班级、课程（接口；单位管理员能管本单位的班）
  const AT = await login(`${ORG}.admin`, APW);
  let T = await login(`${ORG}.t1`, ORG_T1);
  const cls = await api(SV, T, 'POST', '/api/teach/classes', { name: `界面测试班 ${STAMP}` });
  await api(SV, T, 'POST', '/api/teach/courses/intro_factory/publish', { class_id: cls.id, open_all: true });
  const asg = (await api(SV, T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).find((x) => x.lesson === 'i01');

  // 导入学生（界面）：3 个 → 加进班级
  await a.locator('.el-tabs__item:has-text("学生")').click();
  await a.locator('[data-k="org-import"]').click();
  await a.waitForTimeout(800);
  await a.locator('textarea[data-k="org-import-csv"]').fill('s1,张同学\ns2,李同学\ns3,王同学');
  await a.locator('.el-dialog .el-select').first().click();
  await a.locator('.el-select-dropdown__item:visible', { hasText: `界面测试班 ${STAMP}` }).click();
  await a.locator('[data-k="org-import-preview-btn"]').click();
  await a.waitForSelector('[data-k="org-import-preview"]', { timeout: 10000 });
  ok('导入预览：3 个新账号，席位够', /新账号 3 个/.test(await a.locator('[data-k="org-import-preview"]').innerText()));
  await a.locator('[data-k="org-import-go"]').click();
  await a.waitForSelector('[data-k="org-accounts"]', { timeout: 15000 });
  const rows = await a.locator('[data-k="org-accounts"] tbody tr').count();
  const stu = (await a.locator('[data-k="org-accounts"] tbody tr').first().locator('td').nth(0).innerText()).trim();
  const stuPw = (await a.locator('[data-k="org-accounts"] tbody tr').first().locator('td').nth(2).innerText()).trim();
  ok('导入 3 个学生（加了单位前缀），每人一个临时密码', rows === 3 && stu.startsWith(ORG + '.'), stu);
  await a.screenshot({ path: `${OUT}/s08_org_import_accounts.png` });
  await a.locator('.el-dialog__footer button:has-text("关闭")').click();
  await a.waitForTimeout(600);
  // 再导 2 个：席位不够
  await a.locator('[data-k="org-import"]').click();
  await a.locator('textarea[data-k="org-import-csv"]').fill('s4,赵同学\ns5,钱同学');
  await a.locator('[data-k="org-import-preview-btn"]').click();
  await a.waitForSelector('[data-k="org-import-preview"]', { timeout: 10000 });
  const pv = await a.locator('[data-k="org-import-preview"]').innerText();
  ok('学生席位用完：预览就提示席位不够（要 2 个、剩 0 个）', /席位不够/.test(pv) && /只剩 0/.test(pv), pv);
  await a.screenshot({ path: `${OUT}/s09_org_student_seat_full.png` });
  await a.locator('[data-k="org-import-go"]').click();
  await a.waitForSelector('.el-message--error', { timeout: 10000 }).catch(() => null);
  ok('硬导也不行：服务器拒绝整批（403）', /席位不够/.test(await a.locator('.el-message--error').first().innerText().catch(() => '')));
  await a.keyboard.press('Escape');
  await a.waitForTimeout(400);
  await a.goto(`${SV}/org`, { waitUntil: 'networkidle' });
  await a.waitForTimeout(800);
  ok('席位卡片：学生 3 / 3', /3 \/ 3/.test(await a.locator('[data-k="org-seat-students"]').innerText()));
  await a.screenshot({ path: `${OUT}/s10_org_overview.png` });

  // ================================================================ 4. 学生的客户端（SaaS）：登录、上报进度；服务器上跑不了工厂
  const run = JSON.parse(fs.readFileSync(path.join(CHOME, 'run.json'), 'utf-8'));
  const ticket = async () => (await api(CL, '', 'POST', '/api/desktop/ticket', null, { 'x-vf-key': run.key })).token;
  const info = await api(CL, '', 'GET', '/api/desktop/login_info');
  ok('客户端登录页：默认是蜂元云（地址可配置 VF_CLOUD_URL）', info.cloud && info.server === info.cloud, JSON.stringify(info));
  const cctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 900 } });
  const c = await cctx.newPage(); watch(c);
  await c.goto(`${CL}/#dt=${await ticket()}`, { waitUntil: 'networkidle' });
  await c.waitForSelector('[data-k="login-srv-pick"]', { timeout: 20000 });
  ok('客户端登录页：蜂元云 / 自己的服务器 两个选项，默认选中蜂元云', (await c.locator('[data-k="login-cloud"].on').count()) === 1);
  await c.screenshot({ path: `${OUT}/s11_client_login_cloud.png` });
  await c.locator('[data-k="login-own"]').click();
  const ins = c.locator('.box input');
  await ins.nth(0).fill(SV); await ins.nth(1).fill(stu); await ins.nth(2).fill(stuPw);
  await c.screenshot({ path: `${OUT}/s12_client_login_custom.png` });
  await c.locator('.box button:has-text("登录")').click();
  await c.waitForSelector('input[data-k="pw-new"]', { timeout: 20000 }).catch(() => null);
  const SPW = 'Stu' + STAMP + 'q7';
  await c.locator('input[data-k="pw-new"]').fill(SPW); await c.locator('input[data-k="pw-new2"]').fill(SPW);
  await c.locator('[data-k="pw-save"]').click();
  await c.waitForURL(/\/(teach|welcome|courses)/, { timeout: 30000 }).catch(() => null);
  ok('学生用临时密码登录客户端：先改密码，再进课程', /\/(teach|welcome|courses)/.test(c.url()), c.url());
  const CT = await c.evaluate(() => localStorage.getItem('vf_token'));
  // 客户端经代理访问服务器上的工厂：服务器拒绝（SaaS 不跑工厂）
  const st = await api(SV, await login(stu, SPW), 'GET', '/api/p/foundry-housing/state');
  ok('SaaS：直接去服务器上开工厂 → 服务器拒绝，说明去客户端', st._status === 403 && /客户端/.test(st.detail || ''), JSON.stringify(st).slice(0, 200));
  const st2 = await api(CL, CT, 'GET', '/api/p/foundry-housing/state');
  ok('SaaS：客户端里的工厂接口都在本机处理（不转给服务器）', st2._status >= 400 && !/SaaS 云服务/.test(st2.detail || ''), JSON.stringify(st2).slice(0, 200));
  const mk = await api(CL, CT, 'POST', '/api/client/myplants', { name: '我的练习厂', template: 'blank' });
  ok('SaaS：学生在客户端里建"我的工厂"（本机，local-…）', String(mk.pid || mk.id || '').startsWith('local-'), JSON.stringify(mk).slice(0, 200));
  const ov = await api(CL, CT, 'GET', '/api/overview');
  ok('工厂列表：服务器那边是空的（工厂都在本机）', ov._status === 200 && (ov.plants || []).every((p) => p.local), JSON.stringify(ov.plants || []).slice(0, 200));
  // 学生在客户端里打开学校作业（本机建沙箱）→ 客户端上报进度
  const op = await api(CL, CT, 'POST', '/api/client/school/open', { remote_aid: asg.id });
  ok('学校作业装到本机', op.local_aid, JSON.stringify(op).slice(0, 200));
  const sb = await api(CL, CT, 'POST', `/api/teach/assignments/${op.local_aid}/sandbox`, {});
  ok('本机沙箱照常能跑（工厂在学生电脑上）', sb.pid && sb.pid.startsWith('sb-'), JSON.stringify(sb).slice(0, 200));
  let reported = null;
  for (let i = 0; i < 40 && !reported; i++) {
    await sleep(3000);
    const r = await api(SV, T, 'GET', `/api/teach/classes/${cls.id}/reported`);
    const me = (r.students || []).find((s) => s.username === stu);
    const it = me && (me.items[asg.id] || me.items[String(asg.id)]);
    if (it && it.at) reported = it;
  }
  ok('客户端自动上报进度到服务器（事件 + 定时）', reported && ['working', 'done', 'submitted'].includes(reported.state), JSON.stringify(reported));

  // ================================================================ 5. 老师：班级进度（网页）
  const tctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 900 } });
  const t = await tctx.newPage(); watch(t);
  await t.goto(`${SV}/login`, { waitUntil: 'networkidle' });
  await t.locator('.box input').nth(0).fill(`${ORG}.t1`); await t.locator('.box input').nth(1).fill(ORG_T1);
  await t.locator('.box button:has-text("登录")').click();
  await t.waitForSelector('input[data-k="pw-new"]', { timeout: 20000 }).catch(() => null);
  const TPW = 'Teach' + STAMP + 'w3';
  await t.locator('input[data-k="pw-new"]').fill(TPW); await t.locator('input[data-k="pw-new2"]').fill(TPW);
  await t.locator('[data-k="pw-save"]').click();
  await t.waitForTimeout(1500);
  T = await login(`${ORG}.t1`, TPW);                 // 改密码以后别处的登录作废了，接口用新登录
  await t.locator('.el-menu-item[data-k="menu-progress"]').click();
  await t.waitForSelector('[data-k="progress-table"]', { timeout: 20000 });
  await t.waitForTimeout(1200);
  const cellSel = `[data-k="pc-${stu}-${asg.id}"]`;
  const cellTxt = await t.locator(cellSel).innerText().catch(() => '');
  ok('老师的"班级进度"：看到这个学生在客户端里的进度和当前步骤', /在做|已达标|已提交/.test(cellTxt), cellTxt.replace(/\n/g, ' '));
  await t.screenshot({ path: `${OUT}/s13_teacher_progress.png` });
  ok('SaaS 网页端的老师：打开工作台地址会被转走（服务器不跑工厂）', await (async () => { await t.goto(`${SV}/p/foundry-housing/workbench`); await t.waitForTimeout(1500); return !/\/p\//.test(t.url()); })(), t.url());

  // ================================================================ 6. 老师的实时看板：在线、卡住、教学控制台（SaaS 没有旁观 / 注入故障）
  let stuckOk = false;
  for (let i = 0; i < 12 && !stuckOk; i++) {
    await t.goto(`${SV}/progress`, { waitUntil: 'networkidle' });
    await t.waitForTimeout(1500);
    stuckOk = (await t.locator(`[data-k="pc-stuck-${stu}"]`).count()) === 1 && (await t.locator(`[data-k="pc-online-${stu}"].on`).count()) === 1;
    if (!stuckOk) await sleep(5000);
  }
  ok('班级进度：学生在线（客户端每分钟报一声）、同一步停太久标"卡住"', stuckOk);
  ok('班级进度：上面一排是在线 / 卡住 / 在做 / 还没开始 / 全部交了的人数', /在线/.test(await t.locator('[data-k="progress-summary"]').innerText()) && /卡住/.test(await t.locator('[data-k="progress-summary"]').innerText()));
  await t.locator('[data-k="pf-stuck"]').click(); await t.waitForTimeout(400);
  ok('"卡住"筛选：只剩卡住的学生', (await t.locator('[data-k="progress-table"] .el-table__body-wrapper tbody tr').count()) === 1);
  await t.screenshot({ path: `${OUT}/s14_teacher_live_stuck.png` });
  await t.evaluate((id) => localStorage.setItem('vf_teach_console_aid', String(id)), asg.id);   // 控制台打开学生正在做的那一课
  await t.goto(`${SV}/teach`, { waitUntil: 'networkidle' });
  await t.waitForSelector('.teacher-console', { timeout: 20000 }).catch(() => null);
  await t.waitForTimeout(2500);
  ok('教学控制台（SaaS）：说明状态来自客户端上报；没有"创建演示班级"', (await t.locator('[data-k="tc-saas-note"]').count()) === 1);
  await t.locator(`.stu[data-user="${stu}"]`).click().catch(() => null);
  await t.waitForTimeout(1500);
  const tabsTxt = await t.locator('.detail .el-tabs__header').innerText().catch(() => '');
  ok('教学控制台（SaaS）：学生详情没有"旁观""注入故障"，有"进度"', !/旁观|注入故障/.test(tabsTxt) && /进度/.test(tabsTxt), tabsTxt.replace(/\n/g, ' '));
  ok('教学控制台（SaaS）：进度页签显示在线、当前步骤', /在线/.test(await t.locator('[data-k="tc-live"]').innerText().catch(() => '')));
  ok('教学控制台：学生卡片上有上报的在线状态和步骤', (await t.locator(`.stu[data-user="${stu}"] [data-k="tc-reported"]`).count()) === 1);
  await t.screenshot({ path: `${OUT}/s15_teacher_console_saas.png` });

  // ================================================================ 7. SaaS 里做课程：老师的客户端本机做、试运行、预览，发布时课程包签名传到云端
  const run2 = JSON.parse(fs.readFileSync(path.join(CHOME2, 'run.json'), 'utf-8'));
  const ticket2 = async () => (await api(CL2, '', 'POST', '/api/desktop/ticket', null, { 'x-vf-key': run2.key })).token;
  const lg2 = await api(CL2, '', 'POST', '/api/desktop/login', { server: SV, username: `${ORG}.t1`, password: TPW });
  ok('老师登录客户端（连蜂元云）', !!lg2.token, JSON.stringify(lg2).slice(0, 200));
  const TC = lg2.token;
  const kctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 900 } });
  const k = await kctx.newPage(); watch(k);
  await k.goto(`${CL2}/#dt=${await ticket2()}`, { waitUntil: 'networkidle' });
  await k.waitForTimeout(1500);
  await k.goto(`${CL2}/courses`, { waitUntil: 'networkidle' });
  await k.waitForSelector('[data-k="course-studio"]', { timeout: 30000 }).catch(() => null);
  ok('客户端里的课程页：说明在本机做、发布时传到云端', (await k.locator('[data-k="studio-client-note"]').count()) === 1);
  await k.locator('.cc.lib[data-course="intro_factory"] [data-k="copy-course"]').click();
  await k.waitForSelector('[data-k="course-editor"]', { timeout: 30000 }).catch(() => null);
  ok('客户端里"复制一份来改"：本机的课程编辑器打开了', (await k.locator('[data-k="course-editor"]').count()) === 1);
  await k.screenshot({ path: `${OUT}/s16_client_course_editor.png` });
  const drafts = await api(CL2, TC, 'GET', '/api/teach/authoring');
  const dr = (drafts || []).find((x) => !x.remote);
  ok('草稿在老师自己的电脑上（编号够长，不和别的单位撞）', dr && /^tc-[0-9a-f]{12}$/.test(dr.id), JSON.stringify(drafts).slice(0, 200));
  const full = await api(CL2, TC, 'GET', `/api/teach/authoring/${dr.id}`);
  const course = full.course;
  course.name = `界面测试课 ${STAMP}`;
  course.chapters = [{ ...course.chapters[0], lessons: course.chapters[0].lessons.slice(0, 1) }];
  await api(CL2, TC, 'PUT', `/api/teach/authoring/${dr.id}`, { course });
  const pvw = await api(CL2, TC, 'POST', `/api/teach/authoring/${dr.id}/preview`, {});
  const pvAid = pvw.chapters?.[0]?.lessons?.[0]?.aid;
  ok('按学生预览：在本机建预览作业（编号 ≥ 10 亿，不和服务器的作业撞）', pvAid >= 1e9, JSON.stringify(pvw).slice(0, 200));
  const pvTask = await api(CL2, TC, 'GET', `/api/teach/assignments/${pvAid}/task`);
  ok('预览作业由本机处理（客户端的代理按编号分流）', pvTask._status === 200 && pvTask.assignment?.id === pvAid, JSON.stringify(pvTask).slice(0, 160));
  const pub = await fetch(`${CL2}/api/teach/authoring/${dr.id}/publish`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN', Authorization: 'Bearer ' + TC }, body: '{}',
    signal: AbortSignal.timeout(600000) }).then(async (r) => ({ ...(await r.json().catch(() => ({}))), _status: r.status }));
  ok('发布：本机试运行通过 → 签名 → 传到云端（服务器验过签名，不跑工厂）', pub._status === 200 && pub.uploaded?.version >= 1 && pub.uploaded?.id === dr.id, JSON.stringify(pub).slice(0, 300));
  const lib = await api(SV, T, 'GET', '/api/teach/courses');
  ok('云端课程库里有这门课（老师做的）', (lib || []).some((x) => x.id === dr.id && x.origin === 'authored'), (lib || []).map((x) => x.id).join(','));
  await api(SV, T, 'POST', `/api/teach/courses/${dr.id}/publish`, { class_id: cls.id, open_all: true });
  const asg2 = (await api(SV, T, 'GET', `/api/teach/assignments?class_id=${cls.id}`)).find((x) => x.course === dr.id);
  ok('发布到班级（云端，不用跑工厂）', !!asg2, '');
  const op2 = await api(CL, CT, 'POST', '/api/client/school/open', { remote_aid: asg2.id });
  ok('学生的客户端：从云端下课程包（服务器签名、本机验签）装到本机', op2.local_aid && op2._status === 200, JSON.stringify(op2).slice(0, 200));
  const inst = await api(CL, CT, 'GET', '/api/client/courses');
  ok('学生本机装好了这门课（签名验过）', (inst.courses || []).some((x) => x.id === dr.id && x.ok), JSON.stringify(inst).slice(0, 200));
  const sb2 = await api(CL, CT, 'POST', `/api/teach/assignments/${op2.local_aid}/sandbox`, {});
  ok('学生在本机沙箱里做老师做的课', sb2.pid && sb2.pid.startsWith('sb-'), JSON.stringify(sb2).slice(0, 160));
  // 浏览器里的老师：课程页没有死胡同——"新建 / 编辑 / 复制"都给"在客户端中打开"
  await t.goto(`${SV}/courses`, { waitUntil: 'networkidle' });
  await t.waitForSelector('[data-k="course-studio"]', { timeout: 20000 }).catch(() => null);
  await t.waitForTimeout(1500);
  ok('浏览器的课程页（SaaS）：说明课程在客户端里做；我做的课里有刚传上来的', (await t.locator('[data-k="studio-saas-note"]').count()) === 1
     && (await t.locator(`[data-k="my-courses"] .cc[data-course="${dr.id}"]`).count()) === 1);
  await t.locator(`[data-k="my-courses"] .cc[data-course="${dr.id}"] [data-k="edit-course"]`).click();
  await t.waitForSelector('[data-k="client-link-open"]', { timeout: 10000 }).catch(() => null);
  const href = await t.locator('[data-k="client-link-open"]').getAttribute('href').catch(() => '');
  ok('浏览器里点"在客户端里编辑"：给 vfactory:// 链接（直接打开客户端的编辑器）+ 步骤', href === `vfactory://open?path=${encodeURIComponent('/courses?edit=' + dr.id)}`, href);
  await t.waitForTimeout(700);
  await t.screenshot({ path: `${OUT}/s17_browser_studio_client_link.png` });
  await t.keyboard.press('Escape');
  await t.locator('[data-k="new-course"]').click();
  ok('浏览器里"新建课程"：也是"在客户端中打开"', (await t.locator('[data-k="client-link-open"]:visible').getAttribute('href').catch(() => '')) === `vfactory://open?path=${encodeURIComponent('/courses?new=1')}`);
  await t.keyboard.press('Escape');
  // 客户端收到链接（vfactory://open?path=/courses?edit=…）：直接进编辑器
  await k.goto(`${CL2}/courses?edit=${dr.id}`, { waitUntil: 'networkidle' });
  await k.waitForSelector('[data-k="course-editor"]', { timeout: 30000 }).catch(() => null);
  ok('客户端打开 /courses?edit=<课程>（深链接）：直接进这门课的编辑器', (await k.locator('[data-k="course-editor"]').count()) === 1);
  // 浏览器里的学生：点一课 → "在客户端中打开"；客户端收到 /courses?school=<作业> 直接打开这一课
  const sctx = await br.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 900 } });
  const s = await sctx.newPage(); watch(s);
  await s.goto(`${SV}/login`, { waitUntil: 'networkidle' });
  await s.locator('.box input').nth(0).fill(stu); await s.locator('.box input').nth(1).fill(SPW);
  await s.locator('.box button:has-text("登录")').click();
  await s.waitForTimeout(2500);
  await s.goto(`${SV}/courses?l=${asg.id}`, { waitUntil: 'networkidle' });
  await s.waitForSelector('[data-k="lesson-client-dialog"] [data-k="client-link-open"]', { timeout: 15000 }).catch(() => null);
  ok('浏览器里的学生（SaaS）：点一课 → "在客户端中打开这一课"，不是 403',
     (await s.locator('[data-k="client-link-open"]:visible').getAttribute('href').catch(() => '')) === `vfactory://open?path=${encodeURIComponent('/courses?school=' + asg.id)}`
     && (await s.locator('[data-k="learner-saas-banner"]').count()) === 1);
  await s.screenshot({ path: `${OUT}/s18_browser_student_client_link.png` });
  await c.goto(`${CL}/courses?school=${asg.id}`, { waitUntil: 'networkidle' });
  await c.waitForTimeout(4000);
  ok('学生的客户端打开 /courses?school=<作业>（深链接）：直接进这一课（进了这一课的沙箱）', /[?&]l=\d+|\/p\/sb-L-/.test(c.url()), c.url());
  // 5.0.1 课程卡片按钮（开始学习 / 继续学习 / 复习）：浏览器里（SaaS）给"在客户端中打开这一课"；客户端里直接开始
  await s.goto(`${SV}/courses`, { waitUntil: 'networkidle' });
  await s.locator('[data-k="course-filter"] label:has-text("全部")').click().catch(() => null);
  await s.waitForSelector('[data-k="card-continue"]', { timeout: 15000 }).catch(() => null); await s.waitForTimeout(600);
  const sbtn = s.locator('[data-k="card-continue"]').first();
  const said = await sbtn.getAttribute('data-aid').catch(() => '');
  ok('浏览器里的学生（SaaS）：课程卡片有「开始学习 / 继续学习 / 复习」按钮', /^(start|continue|review)$/.test(await sbtn.getAttribute('data-mode').catch(() => '') || '') && /开始学习|继续学习|复习/.test(await sbtn.innerText().catch(() => '')),
    await sbtn.innerText().catch(() => ''));
  await sbtn.click(); await s.waitForTimeout(800);
  ok('浏览器里（SaaS）点卡片按钮：给"在客户端中打开这一课"（这一课的作业号）',
    (await s.locator('[data-k="client-link-open"]:visible').getAttribute('href').catch(() => '')) === `vfactory://open?path=${encodeURIComponent('/courses?school=' + said)}`, said);
  await s.keyboard.press('Escape');
  await c.goto(`${CL}/courses`, { waitUntil: 'networkidle' });
  await c.locator('[data-k="course-filter"] label:has-text("全部")').click().catch(() => null);
  const cbtn = c.locator(`.course-card[data-course="${dr.id}"] [data-k="card-continue"]`);
  await cbtn.waitFor({ timeout: 20000 }).catch(() => null); await c.waitForTimeout(600);
  ok('学生的客户端（SaaS）：老师做的课（装到本机）有进度 → 卡片是「继续学习」', (await cbtn.getAttribute('data-mode').catch(() => '')) === 'continue' && /继续学习/.test(await cbtn.innerText().catch(() => '')),
    `${await cbtn.getAttribute('data-mode').catch(() => '')} ${await cbtn.innerText().catch(() => '')}`);
  await c.screenshot({ path: `${OUT}/s18b_client_card_continue.png` });
  await cbtn.click().catch(() => null);
  await c.waitForURL(/\/p\/sb-[^/]+\/workbench/, { timeout: 60000 }).catch(() => null);
  ok('客户端「继续学习」= 打开这一课并直接进沙箱（工作台）', /\/p\/sb-[^/]+\/workbench/.test(c.url()), c.url());

  // ================================================================ 8. 走一遍每个页面（SaaS）：记下所有 403，一个都不能有
  const walk = async (pg, who, base, paths, extra) => {
    const hits = [];
    const on = (r) => { if (r.status() === 403 && r.url().includes('/api/')) hits.push(`${who} ${new URL(pg.url()).pathname}: ${r.request().method()} ${new URL(r.url()).pathname}`); };
    pg.on('response', on);
    for (const p of paths) {
      await pg.goto(base + p, { waitUntil: 'networkidle' }).catch(() => null);
      await pg.waitForTimeout(1800);
      if (extra && extra[p]) await extra[p](pg).catch(() => null);
    }
    pg.off('response', on);
    return hits;
  };
  const clickTabs = async (pg) => { for (const n of ['班级与名单', '单个作业', '教学控制台']) { await pg.locator(`.el-tabs__item:has-text("${n}")`).first().click().catch(() => null); await pg.waitForTimeout(1500); } };
  const dead = [
    ...await walk(a, '单位管理员（网页）', SV, ['/org', '/users', '/audit', '/teach', '/courses', '/progress', '/help', '/tokens', '/welcome', '/'], { '/teach': clickTabs }),
    ...await walk(t, '老师（网页）', SV, ['/teach', '/courses', '/progress', '/help', '/tokens', '/welcome', '/', '/p/foundry-housing/workbench'], { '/teach': clickTabs }),
    ...await walk(s, '学生（网页）', SV, ['/courses', '/teach', '/help', '/welcome', '/'], {}),
    ...await walk(k, '老师（客户端）', CL2, ['/', '/welcome', '/courses', '/teach', '/progress', '/mine', '/settings', '/help'], { '/teach': clickTabs }),
    ...await walk(c, '学生（客户端）', CL, ['/', '/welcome', '/courses', '/mine', '/settings', '/help'], {}),
  ];
  console.log('  走查：' + (dead.length ? '\n    ' + [...new Set(dead)].join('\n    ') : '没有 403'));
  ok('走一遍每个页面（网页 3 个角色 + 客户端 2 个角色）：没有一个 403 死胡同', dead.length === 0, [...new Set(dead)].slice(0, 6).join(' | '));
  await k.goto(`${CL2}/courses`, { waitUntil: 'networkidle' }); await k.waitForTimeout(1500);
  await k.screenshot({ path: `${OUT}/s19_client_teacher_courses.png` });
  // 5.0.1 评审截图（浅色，和蜂元 MES 一套）：运维后台、单位管理 × 1680 / 1280
  for (const [w, h] of [[1680, 1050], [1280, 720]]) {
    await o.setViewportSize({ width: w, height: h }); await o.goto(`${SV}/ops`, { waitUntil: 'networkidle' }); await o.waitForTimeout(1500);
    await o.screenshot({ path: `${OUT}/r_ops_console-${w}x${h}.png` });
    await a.setViewportSize({ width: w, height: h }); await a.goto(`${SV}/org`, { waitUntil: 'networkidle' }); await a.waitForTimeout(1500);
    await a.screenshot({ path: `${OUT}/r_org-${w}x${h}.png` });
  }

  ok('页面没有脚本错误', errs.length === 0, errs.slice(0, 5).join(' | '));
  const bad = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - bad.length}/${res.length} 通过` + (bad.length ? '；失败：' + bad.join('、') : '') + `，截图在 ${OUT}`);
  await br.close();
})().catch((e) => { console.error('Error:', e); process.exit(1); });
