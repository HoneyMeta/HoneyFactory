// 5.0.1 只有浅色（B 机，先启动 serve）：node tests/light_only_ui.js
// 以前存过深色（localStorage vf_theme = dark、mes_theme = dark）的浏览器打开各页面：悄悄变成浅色、旧记录被删掉；
// 页面上没有深浅色切换按钮 / 菜单项，命令面板里搜"深色"没有切换命令；外壳、主区、工作台、三维和平面画布的底色都是浅色；
// 外壳是和蜂元 MES 同一套样子（玻璃白侧栏、钴蓝选中、面包屑行）。截图在 SHOT_DIR。
// Pinned to zh-CN (browser locale + localStorage vf_lang + X-Lang on API calls): the assertions use the Chinese UI texts; tests/i18n_ui.js covers English.
const path = require('path');
const pw = require(path.join(process.env.APPDATA, 'npm', 'node_modules', 'playwright'));
const B = process.env.VF_URL || 'http://127.0.0.1:8800', OUT = process.env.SHOT_DIR || require('path').join(require('os').tmpdir(), 'vf-shots', 'light_only');
const PLANT = process.env.VF_PLANT || 'foundry-housing';
const res = [];
const ok = (name, cond, detail = '') => { res.push([name, !!cond]); console.log((cond ? 'PASS ' : 'FAIL ') + name, String(detail).slice(0, 1500)); };
const lum = (c) => {            // 'rgb(a)(r, g, b[, a])' → 相对亮度（透明当白）
  const m = String(c).match(/rgba?\(([^)]+)\)/); if (!m) return 1;
  const v = m[1].split(',').map((x) => parseFloat(x)); if (v.length > 3 && v[3] === 0) return 1;
  const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(v[0]) + 0.7152 * f(v[1]) + 0.0722 * f(v[2]);
};

(async () => {
  require('fs').mkdirSync(OUT, { recursive: true });
  const tok = (await (await fetch(B + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': 'zh-CN' }, body: JSON.stringify({ username: 'admin', password: 'honey123' }) })).json()).token;
  const b = await pw.chromium.launch({ channel: 'chrome', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errs = [];
  const ctx = await b.newContext({ locale: 'zh-CN', viewport: { width: 1680, height: 1050 } });
  await ctx.addInitScript((t) => {
    if (sessionStorage.getItem('lo_init')) return; sessionStorage.setItem('lo_init', '1');
    localStorage.setItem('vf_token', t); localStorage.setItem('vf_lang', 'zh-CN'); localStorage.setItem('vf_ai_open', '0'); sessionStorage.setItem('vf_pw_later', '1'); localStorage.setItem('vf_whatsnew_seen', '9.9.9');
    localStorage.setItem('vf_theme', 'dark'); localStorage.setItem('mes_theme', 'dark');          // 老版本存下的深色
  }, tok);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(e.message.slice(0, 200)));
  const state = () => p.evaluate(() => {
    const cs = (e) => (e ? getComputedStyle(e).backgroundColor : '');
    return { dark: document.documentElement.classList.contains('dark'), vt: localStorage.getItem('vf_theme'), mt: localStorage.getItem('mes_theme'),
      body: cs(document.body), side: cs(document.querySelector('.shell > .side')), top: cs(document.querySelector('.shell .top')), main: cs(document.querySelector('.shell .main')),
      themeBtns: [...document.querySelectorAll('[data-k*="theme"], .wc-theme')].filter((e) => /深色|浅色/.test(e.textContent || '') || /theme/.test(e.getAttribute('data-k') || '')).length,
      themeText: [...document.querySelectorAll('button, .el-dropdown-menu__item, [role="menuitem"]')].filter((e) => /^(深色|浅色|换成深色|换成浅色)$/.test((e.textContent || '').trim())).length,
      primary: getComputedStyle(document.documentElement).getPropertyValue('--el-color-primary').trim() };
  });

  for (const [name, url] of [['welcome', '/welcome'], ['plants', '/'], ['courses', '/teach'], ['experiments', `/p/${PLANT}/experiments`], ['help', '/help'], ['mes', '/mes']]) {
    await p.goto(B + url, { waitUntil: 'networkidle' }).catch(() => {}); await p.waitForTimeout(1800);
    const s = await state();
    ok(`${name}：没有 html.dark、旧的深色设置已删掉`, !s.dark && s.vt === null && s.mt === null, JSON.stringify(s));
    ok(`${name}：外壳和主区是浅色（侧栏、顶栏、主区亮度 > 0.85）`, [s.body, s.side, s.top, s.main].every((c) => lum(c) > 0.85), JSON.stringify([s.body, s.side, s.top, s.main]));
    ok(`${name}：没有深浅色切换按钮`, s.themeBtns === 0 && s.themeText === 0, JSON.stringify(s));
    ok(`${name}：主色是钴蓝（和蜂元 MES 一样）`, /^#1463d6$/i.test(s.primary), s.primary);
    await p.screenshot({ path: `${OUT}/${name}.png` });
  }
  // 用户菜单里没有主题项
  await p.goto(B + '/welcome', { waitUntil: 'networkidle' }); await p.waitForTimeout(1200);
  await p.locator('.top .user').click(); await p.waitForTimeout(500);
  const um = await p.evaluate(() => [...document.querySelectorAll('.el-dropdown-menu')].filter((m) => m.offsetParent).map((m) => m.textContent).join(' | '));
  ok('用户菜单里没有深色 / 浅色', um && !/深色|浅色|主题/.test(um), um);
  await p.keyboard.press('Escape');
  // 外壳：和蜂元 MES 同一套样子
  const sh = await p.evaluate(() => {
    const act = document.querySelector('.side .el-menu-item.is-active');
    return { crumbs: !!document.querySelector('.main .crumbs'), cmd: !!document.querySelector('.top .cmd'), act: act ? getComputedStyle(act).backgroundColor : '', actColor: act ? getComputedStyle(act).color : '' };
  });
  ok('外壳：顶栏命令条、主区面包屑、选中菜单是钴蓝浅底', sh.crumbs && sh.cmd && /rgb\(232, 240, 253\)/.test(sh.act), JSON.stringify(sh));
  // 命令面板：搜"深色"没有切换主题的命令
  await p.keyboard.press('Control+k'); await p.waitForTimeout(500); await p.keyboard.type('深色'); await p.waitForTimeout(600);
  const cmds = await p.evaluate(() => [...document.querySelectorAll('.cmdp-i')].map((e) => e.textContent.trim()).filter((t) => /深色|浅色/.test(t)));
  ok('命令面板里没有切换深色 / 浅色的命令', cmds.length === 0, cmds.join(' | '));
  await p.keyboard.press('Escape');
  // 工作台：外框、三维画布、平面图都是浅色
  await p.goto(`${B}/p/${PLANT}/workbench`, { waitUntil: 'domcontentloaded' });
  await p.waitForSelector('.ed-act button[data-panel]', { timeout: 60000 }).catch(() => null); await p.waitForTimeout(7000);
  const wb = await p.evaluate(() => {
    const ed = document.querySelector('.ed'); const c = document.querySelector('.scene-host canvas');
    let px = null;
    if (c) { try { const g = document.createElement('canvas'); g.width = c.width; g.height = c.height; const x = g.getContext('2d'); x.drawImage(c, 0, 0); px = [...x.getImageData(4, 4, 1, 1).data]; } catch { px = null; } }
    return { dark: document.documentElement.classList.contains('dark'), ed: ed ? getComputedStyle(ed).backgroundColor : '', edCls: ed?.className || '', px,
      bg: window.__vfScene?.scene?.background?.getHexString?.() || '' };
  });
  const bgLum = wb.bg ? lum(`rgb(${parseInt(wb.bg.slice(0, 2), 16)}, ${parseInt(wb.bg.slice(2, 4), 16)}, ${parseInt(wb.bg.slice(4, 6), 16)})`) : (wb.px ? lum(`rgb(${wb.px.slice(0, 3).join(',')})`) : 1);
  ok('工作台：没有深色、外框是浅色', !wb.dark && lum(wb.ed) > 0.8 && !/\bdark\b/.test(wb.edCls), JSON.stringify(wb));
  ok('工作台：三维画布底色是浅色', bgLum > 0.7, JSON.stringify({ bg: wb.bg, px: wb.px }));
  const wbt = await p.evaluate(() => [...document.querySelectorAll('.ed button, .ed [role="button"]')].filter((e) => /深色|浅色/.test((e.getAttribute('aria-label') || '') + (e.title || '') + (e.textContent || ''))).length);
  ok('工作台：没有深浅色切换按钮', wbt === 0, wbt);
  await p.screenshot({ path: `${OUT}/workbench.png` });
  ok('页面没有报错', errs.length === 0, errs.slice(0, 4).join(' | '));
  const badr = res.filter((x) => !x[1]).map((x) => x[0]);
  console.log(`\n${res.length - badr.length}/${res.length} 通过` + (badr.length ? '；失败：' + badr.join('、') : ''));
  await b.close();
})();
