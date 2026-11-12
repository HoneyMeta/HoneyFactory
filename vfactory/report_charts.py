"""方案报告用的服务端图表（Pillow 画 PNG，不依赖 matplotlib）：时间构成堆叠条、瓶颈时间占比、小时产出、在制品、
物料流向（桑基图）、能耗环图与设备排行、实验均值 + 95% 置信区间、优化候选散点。

每个函数返回 PNG 字节；数据为空时返回 None（调用方跳过这张图）。图里的文字用正文墨色，颜色只用来区分系列；
单一纵轴（不画双纵轴），多系列都有图例。
"""
from .i18n import _tr, variants
import io
import math
import os

INK, INK2, MUTED, GRID, AXIS, BG = '#1f2933', '#4b5563', '#6b7680', '#e6e9ee', '#9aa4ae', '#ffffff'
ACCENT, BASE_C, HILITE = '#3b82c4', '#8a94a0', '#2e9d5b'
CAT = ['#3b82c4', '#d99a16', '#2e9d5b', '#7a6cc4', '#c8553a', '#1c9aa8', '#b5527e', '#6b7680']   # 分类色，按顺序用
S = 2                       # 画布倍率：按 2 倍画，Word/PPT 里缩到版面宽度，打印清楚


def _font(size, bold=False):
    from PIL import ImageFont
    cands = ([r'C:\Windows\Fonts\msyhbd.ttc'] if bold else []) + [
        r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf']
    for f in cands:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, int(size * S))
            except OSError:
                pass
    return ImageFont.load_default()


class Canvas:
    def __init__(self, w, h, title=None, subtitle=None):
        from PIL import Image, ImageDraw
        self.w, self.h = w, h
        self.img = Image.new('RGB', (w * S, h * S), BG)
        self.d = ImageDraw.Draw(self.img)
        self.f = {k: _font(v) for k, v in (('s', 11), ('m', 12.5), ('l', 15))}
        self.fb = _font(15, True)
        self.top = 10
        if title:
            self.text(16, 10, title, self.fb, INK)
            self.top = 34
        if subtitle:
            self.text(16, self.top - 2, subtitle, self.f['s'], MUTED)
            self.top += 18

    def text(self, x, y, s, font=None, fill=INK, anchor='la'):
        self.d.text((x * S, y * S), str(s), font=font or self.f['m'], fill=fill, anchor=anchor)

    def tw(self, s, font=None):
        return self.d.textlength(str(s), font=font or self.f['m']) / S

    def rect(self, x0, y0, x1, y1, fill, r=0, outline=None):
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        if r and min(x1 - x0, y1 - y0) > 2 * r:
            self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill, outline=outline)
        else:
            self.d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, outline=outline)

    def line(self, pts, fill=INK, width=1.0):
        self.d.line([(x * S, y * S) for x, y in pts], fill=fill, width=max(1, int(width * S)), joint='curve')

    def fit(self, s, width, font=None):
        s = str(s)
        if self.tw(s, font) <= width:
            return s
        while s and self.tw(s + '…', font) > width:
            s = s[:-1]
        return s + '…'

    def legend(self, items, x, y, maxw=None):
        """items = [(名称, 颜色)]，从 (x, y) 横排，超宽换行。返回占用高度。"""
        cx, cy = x, y
        for name, col in items:
            w = 14 + self.tw(name, self.f['s']) + 16
            if maxw and cx + w > x + maxw:
                cx, cy = x, cy + 18
            self.rect(cx, cy + 2, cx + 10, cy + 12, col, 2)
            self.text(cx + 14, cy, name, self.f['s'], INK2)
            cx += w
        return cy - y + 18

    def png(self):
        b = io.BytesIO()
        self.img.save(b, 'PNG', optimize=True)
        return b.getvalue()


def nice_ticks(lo, hi, n=5):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag * 10)
    v = math.floor(lo / step) * step
    out = [round(v, 10)]
    while v < hi - step * 1e-6 and len(out) < 50:      # 最后一个刻度不小于最大值
        v += step
        out.append(round(v, 10))
    return out


def _fmt(v, pct=False, d=None):
    if v is None:
        return '—'
    if pct:
        return f'{v * 100:.{1 if d is None else d}f}%'
    if abs(v) >= 100:
        return f'{v:,.0f}'
    if abs(v) >= 10:
        return f'{v:.1f}'.rstrip('0').rstrip('.')
    return f'{v:.2f}'.rstrip('0').rstrip('.')


# ---------------- 横向堆叠条：时间构成 ----------------
def time_breakdown(objs, classes, title='主要设备时间构成', subtitle=None, w=900):
    """objs = [{name, share: {类别: 占比}, oee}]；classes = [{key, label, color}]。"""
    if not objs:
        return None
    cls = [c for c in classes if any(o['share'].get(c['key']) for o in objs)]
    row_h = 22
    lw = min(190, max(90, max(Canvas(10, 10).tw(o['name']) for o in objs) + 12))
    c0 = Canvas(w, 10)
    leg_h = c0.legend([(c['label'], c['color']) for c in cls], 0, 0, w - 40)
    h = 50 + (24 if subtitle else 0) + leg_h + 12 + row_h * len(objs) + 26
    c = Canvas(w, int(h), title, subtitle)
    y = c.top + 4
    y += c.legend([(x['label'], x['color']) for x in cls], 16, y, w - 32) + 6
    x0, x1 = 16 + lw, w - 64
    for t in (0, 0.25, 0.5, 0.75, 1):
        xx = x0 + (x1 - x0) * t
        c.line([(xx, y), (xx, y + row_h * len(objs))], GRID)
        c.text(xx, y + row_h * len(objs) + 4, f'{int(t * 100)}%', c.f['s'], MUTED, 'ma')
    for i, o in enumerate(objs):
        yy = y + i * row_h
        c.text(x0 - 8, yy + row_h / 2, c.fit(o['name'], lw - 12), c.f['m'], INK, 'rm')
        cx = x0
        for k in cls:
            v = o['share'].get(k['key'], 0) or 0
            if v <= 0:
                continue
            ww = (x1 - x0) * v
            c.rect(cx, yy + 4, cx + ww - (1 if ww > 3 else 0), yy + row_h - 4, k['color'])
            if ww > 34:
                c.text(cx + ww / 2, yy + row_h / 2, f'{v * 100:.0f}%', c.f['s'], '#ffffff' if k['key'] in ('run', 'failed', 'setup', 'planned', 'disabled', 'blocked') else INK, 'mm')
            cx += ww
        if o.get('oee') is not None:
            c.text(x1 + 6, yy + row_h / 2, f"OEE {o['oee'] * 100:.0f}%", c.f['s'], MUTED, 'lm')
    return c.png()


# ---------------- 横向条：瓶颈时间占比（独占 + 交替） ----------------
def bottleneck_bars(items, title='瓶颈时间占比（活跃期法）', subtitle=None, w=900, top_n=8):
    items = [it for it in items if it.get('share') is not None][:top_n]
    if not items or not any(it['share'] for it in items):
        return None
    row_h = 26
    c0 = Canvas(10, 10)
    lw = min(220, max(90, max(c0.tw(it['name'], c0.fb) for it in items) + 14))
    h = 70 + (20 if subtitle else 0) + row_h * len(items) + 30
    c = Canvas(w, int(h), title, subtitle)
    y = c.top + 4
    y += c.legend([(_tr('独占'), '#c8553a'), (_tr('与其他设备交替'), '#e6a58f'), (_tr('（右侧数字：运行占比）'), '#ffffff')], 16, y) + 6
    mx = max(1e-9, max(it['share'] for it in items))
    top = 1.0 if mx > 0.6 else nice_ticks(0, mx, 4)[-1]
    x0, x1 = 16 + lw, w - 120
    for t in nice_ticks(0, top, 4):
        xx = x0 + (x1 - x0) * t / top
        c.line([(xx, y), (xx, y + row_h * len(items))], GRID)
        c.text(xx, y + row_h * len(items) + 4, f'{t * 100:.0f}%', c.f['s'], MUTED, 'ma')
    for i, it in enumerate(items):
        yy = y + i * row_h
        fnt = c.fb if (it.get('tie') or i == 0) and it['share'] > 0 else c.f['m']
        c.text(x0 - 8, yy + row_h / 2, c.fit(it['name'], lw - 12, fnt), fnt, INK, 'rm')
        a = (x1 - x0) * it['sole'] / top
        b = (x1 - x0) * it['shifting'] / top
        if a > 0:
            c.rect(x0, yy + 5, x0 + a, yy + row_h - 5, '#c8553a', 3)
        if b > 0:
            c.rect(x0 + a + (1 if a else 0), yy + 5, x0 + a + b, yy + row_h - 5, '#e6a58f', 3)
        lab = f"{it['share'] * 100:.0f}%" + (_tr('  并列') if it.get('tie') else '')
        c.text(x0 + a + b + 6, yy + row_h / 2, lab, c.f['m'], INK, 'lm')
        c.text(w - 16, yy + row_h / 2, _tr('运行 {v:.0f}%', v=it['run'] * 100), c.f['s'], MUTED, 'rm')
    return c.png()


# ---------------- 竖条：每小时产出（合格 + 报废堆叠） ----------------
def hourly_output(series, title='每小时产出', subtitle=None, w=900, h=300):
    if not series or not any((x.get('good') or 0) + (x.get('scrap') or 0) for x in series):
        return None
    c = Canvas(w, h, title, subtitle)
    y0 = c.top + 4
    y0 += c.legend([(_tr('合格入库'), ACCENT), (_tr('报废'), '#c8553a')], 16, y0) + 6
    x0, x1, yb = 56, w - 16, h - 30
    mx = max((x['good'] or 0) + (x['scrap'] or 0) for x in series)
    ticks = nice_ticks(0, mx, 4)
    top = ticks[-1] or 1
    for t in ticks:
        yy = yb - (yb - y0) * t / top
        c.line([(x0, yy), (x1, yy)], GRID)
        c.text(x0 - 6, yy, _fmt(t), c.f['s'], MUTED, 'rm')
    n = len(series)
    bw = (x1 - x0) / n
    step = max(1, math.ceil(n / 16))
    for i, x in enumerate(series):
        cx = x0 + bw * i
        g, sc = x.get('good') or 0, x.get('scrap') or 0
        hg = (yb - y0) * g / top
        hs = (yb - y0) * sc / top
        pad = max(1, bw * 0.18)
        if hg > 0:
            c.rect(cx + pad, yb - hg, cx + bw - pad, yb, ACCENT)
        if hs > 0:
            c.rect(cx + pad, yb - hg - hs, cx + bw - pad, yb - hg - (1 if hg else 0), '#c8553a')
        if i % step == 0:
            c.text(cx + bw / 2, yb + 5, str(x['time'])[6:] if len(str(x['time'])) > 6 else x['time'], c.f['s'], MUTED, 'ma')
    c.line([(x0, yb), (x1, yb)], AXIS)
    return c.png()


def line_chart(xs, ys, title, unit='', subtitle=None, w=900, h=230, color=ACCENT):
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if len(pts) < 2:
        return None
    c = Canvas(w, h, title, subtitle)
    y0 = c.top + 8
    x0, x1, yb = 56, w - 16, h - 30
    vs = [y for _, y in pts]
    ticks = nice_ticks(0, max(vs), 4)
    top = ticks[-1] or 1
    for t in ticks:
        yy = yb - (yb - y0) * t / top
        c.line([(x0, yy), (x1, yy)], GRID)
        c.text(x0 - 6, yy, _fmt(t), c.f['s'], MUTED, 'rm')
    n = len(pts)
    P = [(x0 + (x1 - x0) * i / (n - 1), yb - (yb - y0) * y / top) for i, (_, y) in enumerate(pts)]
    c.line(P, color, 2)
    step = max(1, math.ceil(n / 12))
    for i, (x, _) in enumerate(pts):
        if i % step == 0:
            c.text(P[i][0], yb + 5, str(x)[6:] if len(str(x)) > 6 else x, c.f['s'], MUTED, 'ma')
    c.line([(x0, yb), (x1, yb)], AXIS)
    if unit:
        c.text(x0, y0 - 14, unit, c.f['s'], MUTED, 'la')
    return c.png()


# ---------------- 环图 + 图例 ----------------
def donut(items, title, unit='', subtitle=None, w=640, h=300):
    items = [(k, float(v), col) for k, v, col in items if v and v > 0]
    if not items:
        return None
    c = Canvas(w, h, title, subtitle)
    tot = sum(v for _, v, _ in items)
    cx, cy, r = 150, (c.top + h) / 2, min(110, (h - c.top) / 2 - 12)
    a = -90.0
    for k, v, col in items:
        b = a + 360 * v / tot
        c.d.pieslice([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], a, b, fill=col, outline=BG, width=2 * S)
        a = b
    ri = r * 0.58
    c.d.ellipse([(cx - ri) * S, (cy - ri) * S, (cx + ri) * S, (cy + ri) * S], fill=BG)
    c.text(cx, cy - 8, _fmt(tot), c.fb, INK, 'mm')
    c.text(cx, cy + 12, unit, c.f['s'], MUTED, 'mm')
    y = cy - len(items) * 13
    lw = max(c.tw(k) for k, _, _ in items)
    for k, v, col in items:
        c.rect(300, y + 3, 312, y + 15, col, 2)
        c.text(320, y, f'{k}', c.f['m'], INK)
        c.text(320 + lw + 24, y, _tr('{v} {unit}（{v2:.0f}%）', v=_fmt(v), unit=unit, v2=v / tot * 100), c.f['m'], INK2)
        y += 26
    return c.png()


def hbars(rows, title, unit='', subtitle=None, w=900, color=ACCENT):
    """rows = [(名称, 数值)] 从大到小。"""
    rows = [(k, v) for k, v in rows if v is not None]
    if not rows:
        return None
    row_h = 24
    lw = min(200, max(80, max(Canvas(10, 10).tw(k) for k, _ in rows) + 12))
    h = 40 + (20 if subtitle else 0) + row_h * len(rows) + 28
    c = Canvas(w, int(h), title, subtitle)
    y = c.top + 6
    x0, x1 = 16 + lw, w - 110
    mx = max(v for _, v in rows) or 1
    ticks = nice_ticks(0, mx, 4)
    top = ticks[-1] or 1
    for t in ticks:
        xx = x0 + (x1 - x0) * t / top
        c.line([(xx, y), (xx, y + row_h * len(rows))], GRID)
        c.text(xx, y + row_h * len(rows) + 4, _fmt(t), c.f['s'], MUTED, 'ma')
    for i, (k, v) in enumerate(rows):
        yy = y + i * row_h
        c.text(x0 - 8, yy + row_h / 2, c.fit(k, lw - 12), c.f['m'], INK, 'rm')
        ww = (x1 - x0) * v / top
        c.rect(x0, yy + 5, x0 + max(1, ww), yy + row_h - 5, color, 3)
        c.text(x0 + ww + 6, yy + row_h / 2, f'{_fmt(v)} {unit}', c.f['s'], INK2, 'lm')
    return c.png()


# ---------------- 实验：均值 + 95% 置信区间 ----------------
def ci_chart(rows, title, unit='', percent=False, subtitle=None, w=900):
    """rows = [{name, mean, lo, hi, base?, best?}]：横向，点 = 均值，横线 = 95% 区间；基准灰色，推荐方案绿色。"""
    rows = [r for r in rows if r.get('mean') is not None]
    if not rows:
        return None
    row_h = 30
    c0 = Canvas(10, 10)
    lw = min(250, max(90, max(c0.tw(r['name'], c0.fb if r.get('best') else None) for r in rows) + 14))
    h = 64 + (20 if subtitle else 0) + row_h * len(rows) + 30
    c = Canvas(w, int(h), title + (_tr('（{unit}）', unit=unit) if unit else ''), subtitle)
    y = c.top + 4
    y += c.legend([(_tr('基准'), BASE_C), (_tr('其他方案'), ACCENT), (_tr('推荐方案'), HILITE), (_tr('横线：95% 置信区间'), INK2)], 16, y) + 6
    vs = [v for r in rows for v in (r['mean'], r.get('lo'), r.get('hi')) if v is not None]
    lo, hi = min(vs), max(vs)
    pad = (hi - lo) * 0.1 or abs(hi) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    if min(vs) >= 0 and lo < 0:
        lo = 0.0
    if percent and hi > 1 and max(vs) <= 1:
        hi = 1.0
    ticks = [t for t in nice_ticks(lo, hi, 5) if lo - 1e-12 <= t <= hi + 1e-12]
    x0, x1 = 16 + lw, w - 110

    def X(v):
        return x0 + (x1 - x0) * (v - lo) / (hi - lo)
    for t in ticks:
        c.line([(X(t), y), (X(t), y + row_h * len(rows))], GRID)
        c.text(X(t), y + row_h * len(rows) + 4, _fmt(t, percent), c.f['s'], MUTED, 'ma')
    base_mean = rows[0]['mean']
    c.line([(X(base_mean), y), (X(base_mean), y + row_h * len(rows))], '#c9ced6', 1)
    for i, r in enumerate(rows):
        yy = y + i * row_h + row_h / 2
        col = BASE_C if i == 0 else HILITE if r.get('best') else ACCENT
        fnt = c.fb if r.get('best') else c.f['m']
        c.text(x0 - 8, yy, c.fit(r['name'], lw - 12, fnt), fnt, INK, 'rm')
        if r.get('lo') is not None and r.get('hi') is not None:
            c.line([(X(r['lo']), yy), (X(r['hi']), yy)], INK2, 1.5)
            for v in (r['lo'], r['hi']):
                c.line([(X(v), yy - 6), (X(v), yy + 6)], INK2, 1.5)
        rr = 5.5
        c.d.ellipse([(X(r['mean']) - rr) * S, (yy - rr) * S, (X(r['mean']) + rr) * S, (yy + rr) * S], fill=col, outline=BG, width=2 * S)
        txt = _fmt(r['mean'], percent, 2 if percent else None)
        if r.get('lo') is not None:
            txt += f"  [{_fmt(r['lo'], percent, 2 if percent else None)}, {_fmt(r['hi'], percent, 2 if percent else None)}]"
        c.text(w - 16, yy, txt, c.f['s'], INK2, 'rm')
    return c.png()


# ---------------- 优化：候选散点 + 帕累托前沿 ----------------
def pareto_scatter(evals, kx, ky, lx, ly, best_i=None, percent_x=False, percent_y=False, title='优化候选', subtitle=None, w=900, h=380):
    pts = [(e['kpi'].get(kx), e['kpi'].get(ky), e) for e in evals if e['kpi'].get(kx) is not None and e['kpi'].get(ky) is not None]
    if len(pts) < 2:
        return None
    c = Canvas(w, h, title, subtitle)
    y0 = c.top + 4
    y0 += c.legend([(_tr('满足约束'), ACCENT), (_tr('帕累托前沿'), '#d99a16'), (_tr('推荐'), HILITE), (_tr('不满足约束'), '#c9ced6')], 16, y0) + 10
    x0, x1, yb = 70, w - 20, h - 44
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]

    def rng(v):
        a, b = min(v), max(v)
        pad = (b - a) * 0.1 or abs(b) * 0.05 or 1
        return a - pad, b + pad
    (ax, bx), (ay, by) = rng(xs), rng(ys)

    def X(v):
        return x0 + (x1 - x0) * (v - ax) / (bx - ax)

    def Y(v):
        return yb - (yb - y0) * (v - ay) / (by - ay)
    for t in nice_ticks(ay, by, 4):
        if ay <= t <= by:
            c.line([(x0, Y(t)), (x1, Y(t))], GRID)
            c.text(x0 - 6, Y(t), _fmt(t, percent_y), c.f['s'], MUTED, 'rm')
    for t in nice_ticks(ax, bx, 5):
        if ax <= t <= bx:
            c.text(X(t), yb + 5, _fmt(t, percent_x), c.f['s'], MUTED, 'ma')
    c.line([(x0, yb), (x1, yb)], AXIS)
    c.text((x0 + x1) / 2, h - 18, lx, c.f['s'], INK2, 'ma')
    c.text(x0, y0 - 16, ly, c.f['s'], INK2, 'la')
    fr = sorted([(X(p[0]), Y(p[1])) for p in pts if p[2].get('front')])
    if len(fr) > 1:
        c.line(fr, '#d99a16', 1.5)
    for x, y, e in sorted(pts, key=lambda p: (p[2].get('front', False), p[2]['i'] == best_i)):
        col = HILITE if e['i'] == best_i else '#d99a16' if e.get('front') else ACCENT if e.get('feasible', True) else '#c9ced6'
        r = 7 if e['i'] == best_i else 5
        c.d.ellipse([(X(x) - r) * S, (Y(y) - r) * S, (X(x) + r) * S, (Y(y) + r) * S], fill=col, outline=BG, width=2 * S)
    if best_i is not None:
        b = next((p for p in pts if p[2]['i'] == best_i), None)
        if b:
            c.text(X(b[0]) + 9, Y(b[1]) - 9, _tr('推荐 #{v}', v=best_i + 1), c.f['s'], INK, 'lm')
    return c.png()


# ---------------- 桑基图 ----------------
def sankey(sk, title='物料流向', subtitle=None, w=1100, h=None, max_links=40):
    """sk = analysis.sankey 的返回。节点按最长路径分层，线宽 = 件数；AGV、搬运这类节点并掉（直接连起点和终点），图更清楚。"""
    links = [dict(l) for l in (sk or {}).get('links') or [] if l['value'] > 0]
    if not links:
        return None
    for x in [n['name'] for n in sk['nodes'] if n.get('kind') in ('agv', 'transporter')]:
        ins = [l for l in links if l['target'] == x]
        outs = [l for l in links if l['source'] == x]
        tout = sum(l['value'] for l in outs)
        merged = {}
        for i in ins:
            for o in outs:
                if tout and i['source'] != o['target']:
                    k = (i['source'], o['target'])
                    merged[k] = merged.get(k, 0) + i['value'] * o['value'] / tout
        links = [l for l in links if x not in (l['source'], l['target'])]
        for (a, b), v in merged.items():
            ex = next((l for l in links if l['source'] == a and l['target'] == b), None)
            if ex:
                ex['value'] += v
            else:
                links.append({'source': a, 'target': b, 'value': v})
    links = sorted([l for l in links if l['value'] >= 0.5], key=lambda l: -l['value'])[:max_links]
    if not links:
        return None
    label = {n['name']: n['label'] for n in sk['nodes']}
    names = list(dict.fromkeys([l['source'] for l in links] + [l['target'] for l in links]))
    succ = {n: [] for n in names}
    for l in links:
        succ[l['source']].append(l['target'])
    layer = {n: 0 for n in names}
    for _ in range(len(names)):                          # 无环图上的最长路径分层
        ch = False
        for l in links:
            if layer[l['target']] < layer[l['source']] + 1:
                layer[l['target']] = layer[l['source']] + 1
                ch = True
        if not ch:
            break
    nl = max(layer.values()) + 1
    inflow = {n: sum(l['value'] for l in links if l['target'] == n) for n in names}
    outflow = {n: sum(l['value'] for l in links if l['source'] == n) for n in names}
    val = {n: max(inflow[n], outflow[n]) for n in names}
    cols = [[n for n in names if layer[n] == i] for i in range(nl)]
    h = h or max(380, 110 + 34 * max(len(col) for col in cols))
    c = Canvas(w, h, title, subtitle)
    y0, yb = c.top + 6, h - 12
    gap = 10
    colsum = max(sum(val[n] for n in col) for col in cols if col)
    maxn = max(len(col) for col in cols)
    k = (yb - y0 - gap * (maxn - 1)) / max(1, colsum)
    nw = 12
    x0, x1 = 16, w - 130
    pos = {}
    for i, col in enumerate(cols):
        x = x0 + (x1 - x0 - nw) * (i / max(1, nl - 1))
        tot = sum(val[n] for n in col) * k + gap * (len(col) - 1)
        y = y0 + (yb - y0 - tot) / 2
        for n in col:
            hh = max(2, val[n] * k)
            pos[n] = [x, y, hh, y, y]           # x, y, 高, 出口游标, 入口游标
            y += hh + gap
    color = {}
    for i, n in enumerate(names):
        color[n] = '#c8553a' if n in variants('报废') else '#2e9d5b' if n in variants('发运') else CAT[i % 6]
    from PIL import Image, ImageDraw
    over = Image.new('RGBA', c.img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for l in sorted(links, key=lambda l: -l['value']):
        a, b = pos[l['source']], pos[l['target']]
        th = l['value'] * k
        sx, sy = a[0] + nw, a[3]
        tx, ty = b[0], b[4]
        a[3] += th
        b[4] += th
        poly = []
        N = 24
        for j in range(N + 1):
            t = j / N
            u = t * t * (3 - 2 * t)
            poly.append(((sx + (tx - sx) * t) * S, (sy + (ty - sy) * u) * S))
        for j in range(N, -1, -1):
            t = j / N
            u = t * t * (3 - 2 * t)
            poly.append(((sx + (tx - sx) * t) * S, (sy + th + (ty - sy) * u) * S))
        rgb = tuple(int(color[l['source']][i:i + 2], 16) for i in (1, 3, 5))
        od.polygon(poly, fill=rgb + (95,))
    c.img.paste(over, (0, 0), over)
    for n in names:
        x, y, hh = pos[n][:3]
        c.rect(x, y, x + nw, y + hh, color[n])
    lab_bg = Image.new('RGBA', c.img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(lab_bg)
    texts = []
    for n in names:                                   # 标签带半透明白底，压在色带上也看得清
        x, y, hh = pos[n][:3]
        t = f"{c.fit(label.get(n, n), 104)} {round(val[n])}"
        tw = c.tw(t, c.f['s'])
        tx = x + nw + 4 if layer[n] < nl - 1 or x + nw + 4 + tw < w else x - 4 - tw
        ld.rounded_rectangle([(tx - 2) * S, (y + hh / 2 - 8) * S, (tx + tw + 2) * S, (y + hh / 2 + 8) * S], radius=3 * S, fill=(255, 255, 255, 215))
        texts.append((tx, y + hh / 2, t))
    c.img.paste(lab_bg, (0, 0), lab_bg)
    for tx, ty, t in texts:
        c.text(tx, ty, t, c.f['s'], INK, 'lm')
    return c.png()
