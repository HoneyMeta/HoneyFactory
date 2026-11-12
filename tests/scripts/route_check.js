// 连线几何检查（平面图 / 架构图，4.4）：在页面里读每条连线的路径，换算成屏幕坐标，检查
//   1. 端点落在两头对象的边框上（容差 tol px）；2. 只有水平 / 竖直段；3. 不穿过别的对象（端点那两个除外）。
// 用法：const { checkRoutes } = require('./scripts/route_check'); const r = await checkRoutes(page, 'plan'|'arch');
async function checkRoutes(page, view, tol = 1.6) {
  return page.evaluate(({ view, tol }) => {
    const plan = view === 'plan';
    const root = document.querySelector(plan ? '.pv-svg' : '.av-svg');
    if (!root) return { n: 0, bad: ['没有画布'] };
    const lines = [...root.querySelectorAll(plan ? '.pv-links [data-link]' : '.av-w[data-link], .av-mw[data-link]')];
    const rectOf = (id) => {
      const g = root.querySelector(`[data-id="${CSS.escape(id)}"]`); if (!g) return null;
      const el = plan ? (g.querySelector('.body') || g.querySelector('.sym-hit')) : g.querySelector('.av-nb');
      const r = (el || g).getBoundingClientRect(); return { x0: r.left, y0: r.top, x1: r.right, y1: r.bottom };
    };
    const ids = [...root.querySelectorAll('[data-id]')].map((g) => g.getAttribute('data-id'));
    const rects = Object.fromEntries(ids.map((id) => [id, rectOf(id)]).filter((x) => x[1]));
    const out = { n: 0, ends: 0, endsOk: 0, segs: 0, diag: 0, cross: 0, bad: [] };
    for (const g of lines) {
      const path = g.querySelector('path'); const d = path.getAttribute('d') || '';
      const a = g.getAttribute('data-a'), b = g.getAttribute('data-b');
      // 折线顶点：M 点、Q 的控制点（拐角）、最后一个 L 点
      const tk = d.trim().split(/\s+/); const pts = []; let i = 0;
      while (i < tk.length) {
        const c = tk[i];
        if (c === 'M' || c === 'L') { pts.push([+tk[i + 1], +tk[i + 2], c]); i += 3; }
        else if (c === 'Q') { pts.push([+tk[i + 1], +tk[i + 2], 'Q']); i += 5; }
        else i++;
      }
      const verts = [pts[0], ...pts.filter((p) => p[2] === 'Q'), pts[pts.length - 1]];
      const m = path.getScreenCTM(); if (!m) continue;
      const sc = verts.map((p) => [p[0] * m.a + p[1] * m.c + m.e, p[0] * m.b + p[1] * m.d + m.f]);
      out.n++;
      for (const [p, id] of [[sc[0], a], [sc[sc.length - 1], b]]) {
        const R = rects[id]; out.ends++;
        if (!R) { out.bad.push(`${g.getAttribute('data-link')}：找不到 ${id}`); continue; }
        const onX = (Math.abs(p[0] - R.x0) <= tol || Math.abs(p[0] - R.x1) <= tol) && p[1] >= R.y0 - tol && p[1] <= R.y1 + tol;
        const onY = (Math.abs(p[1] - R.y0) <= tol || Math.abs(p[1] - R.y1) <= tol) && p[0] >= R.x0 - tol && p[0] <= R.x1 + tol;
        if (onX || onY) out.endsOk++; else if (out.bad.length < 12) out.bad.push(`${g.getAttribute('data-link')} 端点不在 ${id} 边框上 (${p.map((x) => x.toFixed(1))} vs ${[R.x0, R.y0, R.x1, R.y1].map((x) => x.toFixed(1))})`);
      }
      for (let k = 0; k < sc.length - 1; k++) {
        const p = sc[k], q = sc[k + 1]; out.segs++;
        if (Math.abs(p[0] - q[0]) > 0.6 && Math.abs(p[1] - q[1]) > 0.6) { out.diag++; if (out.bad.length < 12) out.bad.push(`${g.getAttribute('data-link')} 第 ${k + 1} 段是斜线`); }
        const L = Math.hypot(q[0] - p[0], q[1] - p[1]), n = Math.max(2, Math.ceil(L / 3));
        for (let s = 1; s < n; s++) {
          const x = p[0] + (q[0] - p[0]) * s / n, y = p[1] + (q[1] - p[1]) * s / n;
          const hit = Object.entries(rects).find(([id, R]) => id !== a && id !== b && x > R.x0 + 1.5 && x < R.x1 - 1.5 && y > R.y0 + 1.5 && y < R.y1 - 1.5);
          if (hit) { out.cross++; if (out.bad.length < 12) out.bad.push(`${g.getAttribute('data-link')} 穿过 ${hit[0]}`); break; }
        }
      }
    }
    return out;
  }, { view, tol });
}
module.exports = { checkRoutes };
