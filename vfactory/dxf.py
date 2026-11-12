"""DXF 底图导入：不依赖第三方库的 ASCII DXF 解析器。

支持 LINE、LWPOLYLINE（含凸度圆弧）、POLYLINE/VERTEX、CIRCLE、ARC、ELLIPSE、SPLINE（按控制点/拟合点折线近似）、
TEXT、MTEXT、POINT，以及 INSERT 块引用（平移、缩放、旋转，可嵌套）。单位按 $INSUNITS 换算到米，没写单位时按图幅大小猜。
输出：折线（米，平面图坐标：x 向右，y 向下）、文字、SVG（用作平面图底图），折线同时可用于吸附。
"""
from .i18n import _tr
import math
import re

UNIT_M = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 8: 2.54e-8, 9: 2.54e-5, 10: 0.9144, 14: 0.1, 15: 10.0}
UNIT_NAME = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'in': 0.0254, 'ft': 0.3048}


class DxfError(ValueError):
    pass


def _pairs(text):
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if len(lines) < 4:
        raise DxfError(_tr('不是 DXF 文件'))
    out = []
    for i in range(0, len(lines) - 1, 2):
        c = lines[i].strip()
        if not c:
            continue
        try:
            out.append((int(c), lines[i + 1].strip()))
        except ValueError:
            raise DxfError(_tr('第 {v} 行不是 DXF 组码（只支持 ASCII DXF，二进制 DXF 请在 CAD 里另存为 ASCII）', v=i + 1))
    return out


def _entities(pairs, i, end_marks):
    """从 i 开始读实体直到遇到 end_marks 之一（0/ENDSEC、0/ENDBLK）。返回 (实体列表, 新位置)。"""
    ents = []
    cur = None
    n = len(pairs)
    while i < n:
        c, v = pairs[i]
        if c == 0:
            if cur is not None:
                ents.append(cur)
                cur = None
            if v in end_marks:
                return ents, i
            cur = {'type': v, 'g': []}
        elif cur is not None:
            cur['g'].append((c, v))
        i += 1
    if cur is not None:
        ents.append(cur)
    return ents, i


def parse(text):
    pairs = _pairs(text)
    header, blocks, entities = {}, {}, []
    i, n = 0, len(pairs)
    while i < n:
        c, v = pairs[i]
        if c == 0 and v == 'SECTION' and i + 1 < n:
            name = pairs[i + 1][1]
            i += 2
            if name == 'HEADER':
                var = None
                while i < n and not (pairs[i][0] == 0 and pairs[i][1] == 'ENDSEC'):
                    cc, vv = pairs[i]
                    if cc == 9:
                        var = vv
                    elif var:
                        header.setdefault(var, vv)
                    i += 1
            elif name == 'BLOCKS':
                while i < n and not (pairs[i][0] == 0 and pairs[i][1] == 'ENDSEC'):
                    if pairs[i] == (0, 'BLOCK'):
                        j = i + 1
                        bname, base = None, [0.0, 0.0]
                        while j < n and pairs[j][0] != 0:
                            if pairs[j][0] == 2:
                                bname = pairs[j][1]
                            elif pairs[j][0] == 10:
                                base[0] = float(pairs[j][1])
                            elif pairs[j][0] == 20:
                                base[1] = float(pairs[j][1])
                            j += 1
                        ents, j = _entities(pairs, j, ('ENDBLK', 'ENDSEC'))
                        if bname:
                            blocks[bname] = {'base': base, 'ents': ents}
                        i = j
                    i += 1
            elif name == 'ENTITIES':
                entities, i = _entities(pairs, i, ('ENDSEC',))
            else:
                while i < n and not (pairs[i][0] == 0 and pairs[i][1] == 'ENDSEC'):
                    i += 1
        i += 1
    if not entities and not blocks:
        raise DxfError(_tr('文件里没有图元（ENTITIES 段为空）'))
    return header, blocks, entities


def _g(e, code, default=None, cast=float):
    for c, v in e['g']:
        if c == code:
            try:
                return cast(v)
            except ValueError:
                return default
    return default


def _all(e, code, cast=float):
    out = []
    for c, v in e['g']:
        if c == code:
            try:
                out.append(cast(v))
            except ValueError:
                out.append(None)
    return out


def _arc_pts(cx, cy, r, a0, a1, seg=None):
    if a1 < a0:
        a1 += 360
    span = a1 - a0
    k = seg or max(4, int(span / 10))
    return [[cx + r * math.cos(math.radians(a0 + span * t / k)), cy + r * math.sin(math.radians(a0 + span * t / k))] for t in range(k + 1)]


def _bulge(p0, p1, b):
    """LWPOLYLINE 凸度段 → 圆弧折线点（不含起点）。"""
    if not b:
        return [p1]
    ang = 4 * math.atan(b)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    chord = math.hypot(dx, dy)
    if chord < 1e-12:
        return [p1]
    r = chord / (2 * math.sin(ang / 2))
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    h = r * math.cos(ang / 2)
    nx, ny = -dy / chord, dx / chord
    cx, cy = mx + nx * h, my + ny * h
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    k = max(2, int(abs(ang) / math.radians(10)))
    return [[cx + abs(r) * math.cos(a0 + ang * t / k), cy + abs(r) * math.sin(a0 + ang * t / k)] for t in range(1, k + 1)]


def _geom(e, blocks, xf, depth, out):
    t = e['type']
    layer = _g(e, 8, '0', str)

    def T(pts):
        return [xf(x, y) for x, y in pts]

    def poly(pts, closed=False):
        if len(pts) >= 2:
            out['polylines'].append({'layer': layer, 'pts': T(pts), 'closed': closed})
    if t == 'LINE':
        poly([[_g(e, 10, 0), _g(e, 20, 0)], [_g(e, 11, 0), _g(e, 21, 0)]])
    elif t == 'LWPOLYLINE':
        xs, ys = _all(e, 10), _all(e, 20)
        bul = {}
        k = -1
        for c, v in e['g']:
            if c == 10:
                k += 1
            elif c == 42 and k >= 0:
                try:
                    bul[k] = float(v)
                except ValueError:
                    pass
        pts = [[x, y] for x, y in zip(xs, ys) if x is not None and y is not None]
        closed = bool(int(_g(e, 70, 0) or 0) & 1)
        if pts:
            res = [pts[0]]
            seq = list(range(len(pts) - 1)) + ([len(pts) - 1] if closed else [])
            for a in seq:
                b = (a + 1) % len(pts)
                res += _bulge(pts[a], pts[b], bul.get(a, 0))
            poly(res, closed)
    elif t == 'POLYLINE':
        pass                       # 顶点在后续 VERTEX 里，由调用方合并
    elif t == 'CIRCLE':
        poly(_arc_pts(_g(e, 10, 0), _g(e, 20, 0), _g(e, 40, 0), 0, 360, 36), True)
    elif t == 'ARC':
        poly(_arc_pts(_g(e, 10, 0), _g(e, 20, 0), _g(e, 40, 0), _g(e, 50, 0), _g(e, 51, 360)))
    elif t == 'ELLIPSE':
        cx, cy, mx, my, ratio = _g(e, 10, 0), _g(e, 20, 0), _g(e, 11, 1), _g(e, 21, 0), _g(e, 40, 1)
        s0, s1 = _g(e, 41, 0), _g(e, 42, 2 * math.pi)
        a = math.hypot(mx, my)
        rot = math.atan2(my, mx)
        if s1 < s0:
            s1 += 2 * math.pi
        k = 36
        pts = []
        for i in range(k + 1):
            u = s0 + (s1 - s0) * i / k
            x, y = a * math.cos(u), a * ratio * math.sin(u)
            pts.append([cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot)])
        poly(pts, abs(s1 - s0 - 2 * math.pi) < 1e-6)
    elif t == 'SPLINE':
        xs, ys = _all(e, 11), _all(e, 21)
        if len(xs) < 2:
            xs, ys = _all(e, 10), _all(e, 20)
        poly([[x, y] for x, y in zip(xs, ys) if x is not None and y is not None], bool(int(_g(e, 70, 0) or 0) & 1))
    elif t in ('TEXT', 'MTEXT'):
        s = ''.join(v for c, v in e['g'] if c in (3,)) + (_g(e, 1, '', str) or '')
        s = re.sub(r'\\[A-Za-z][^;]*;|\\P|[{}]', ' ', s).strip()
        if s:
            x, y = xf(_g(e, 10, 0), _g(e, 20, 0))
            h = _g(e, 40, 2.5) * out['_scale_now']
            out['texts'].append({'layer': layer, 'x': x, 'y': y, 'h': h, 'text': s[:200]})
    elif t == 'POINT':
        pass
    elif t == 'INSERT' and depth < 8:
        b = blocks.get(_g(e, 2, '', str))
        if not b:
            return
        ix, iy = _g(e, 10, 0), _g(e, 20, 0)
        sx, sy = _g(e, 41, 1) or 1, _g(e, 42, 1) or 1
        rot = math.radians(_g(e, 50, 0) or 0)
        bx, by = b['base']
        c, s = math.cos(rot), math.sin(rot)

        def xf2(x, y, _xf=xf):
            x, y = (x - bx) * sx, (y - by) * sy
            return _xf(ix + x * c - y * s, iy + x * s + y * c)
        prev = out['_scale_now']
        out['_scale_now'] = prev * abs(sx)
        _walk(b['ents'], blocks, xf2, depth + 1, out)
        out['_scale_now'] = prev


def _walk(ents, blocks, xf, depth, out):
    i = 0
    while i < len(ents):
        e = ents[i]
        if e['type'] == 'POLYLINE':
            pts = []
            j = i + 1
            while j < len(ents) and ents[j]['type'] == 'VERTEX':
                pts.append([_g(ents[j], 10, 0), _g(ents[j], 20, 0)])
                j += 1
            if j < len(ents) and ents[j]['type'] == 'SEQEND':
                j += 1
            if len(pts) >= 2:
                out['polylines'].append({'layer': _g(e, 8, '0', str), 'pts': [xf(x, y) for x, y in pts], 'closed': bool(int(_g(e, 70, 0) or 0) & 1)})
            i = j
            continue
        _geom(e, blocks, xf, depth, out)
        i += 1
        if len(out['polylines']) > 200000:
            raise DxfError(_tr('图元太多（超过 20 万条折线），请在 CAD 里先删掉不需要的图层'))


def convert(text, unit=None, layers=None, origin=(0.0, 0.0), flip_y=True, max_points=200000):
    """DXF 文本 → {polylines, texts, bbox, w, h, unit, scale, layers}；坐标为米，左上角对齐 origin。"""
    header, blocks, ents = parse(text)
    if layers:
        keep = set(layers)
        ents = [e for e in ents if _g(e, 8, '0', str) in keep or e['type'] in ('VERTEX', 'SEQEND')]
    raw = {'polylines': [], 'texts': [], '_scale_now': 1.0}
    _walk(ents, blocks, lambda x, y: (x, y), 0, raw)
    pts = [p for pl in raw['polylines'] for p in pl['pts']]
    if not pts:
        raise DxfError(_tr('没有可显示的线条（支持直线、多段线、圆、圆弧、椭圆、样条、块引用）'))
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    ins = int(float(header.get('$INSUNITS', 0) or 0))
    if unit and unit in UNIT_NAME:
        scale, uname = UNIT_NAME[unit], unit
    elif ins in UNIT_M:
        scale, uname = UNIT_M[ins], {1: 'in', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm'}.get(ins, f'INSUNITS={ins}')
    else:                                                # 没写单位：厂房图宽度一般 20–500 m
        span = max(x1 - x0, y1 - y0)
        scale, uname = (0.001, _tr('mm（按图幅推断）')) if span > 2000 else (1.0, _tr('m（按图幅推断）'))
    ox, oy = origin

    def to_m(p):
        x = (p[0] - x0) * scale + ox
        y = ((y1 - p[1]) if flip_y else (p[1] - y0)) * scale + oy
        return [round(x, 4), round(y, 4)]
    polys = []
    total = 0
    for pl in raw['polylines']:
        q = [to_m(p) for p in pl['pts']]
        total += len(q)
        if total > max_points:
            break
        polys.append({'layer': pl['layer'], 'pts': q, 'closed': pl['closed']})
    texts = []
    for t in raw['texts']:
        x, y = to_m([t['x'], t['y']])
        texts.append({'layer': t['layer'], 'x': x, 'y': y, 'h': round(t['h'] * scale, 4), 'text': t['text']})
    lay = {}
    for pl in polys:
        lay[pl['layer']] = lay.get(pl['layer'], 0) + 1
    return {'polylines': polys, 'texts': texts[:5000], 'unit': uname, 'scale': scale, 'insunits': ins,
            'bbox': [ox, oy, round(ox + (x1 - x0) * scale, 4), round(oy + (y1 - y0) * scale, 4)],
            'w': round((x1 - x0) * scale, 4), 'h': round((y1 - y0) * scale, 4), 'layers': lay, 'blocks': len(blocks),
            'truncated': total > max_points}


def to_svg(res, stroke='#3a4a5a'):
    """折线 → SVG（viewBox 单位为米，线宽不随缩放变化）。"""
    x0, y0, x1, y1 = res['bbox']
    w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
    px = 2000 if w >= h else max(200, int(2000 * w / h))
    py = max(200, int(px * h / w))
    esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{py}" viewBox="{x0} {y0} {w} {h}" preserveAspectRatio="none">',
             f'<g fill="none" stroke="{stroke}" stroke-width="1" vector-effect="non-scaling-stroke" stroke-linejoin="round">']
    for pl in res['polylines']:
        d = ' '.join(f'{p[0]},{p[1]}' for p in pl['pts'])
        tag = 'polygon' if pl['closed'] else 'polyline'
        parts.append(f'<{tag} points="{d}" vector-effect="non-scaling-stroke"/>')
    parts.append('</g><g fill="#3a4a5a" font-family="sans-serif">')
    for t in res['texts'][:2000]:
        parts.append(f'<text x="{t["x"]}" y="{t["y"]}" font-size="{max(t["h"], 0.05)}">{esc(t["text"])}</text>')
    parts.append('</g></svg>')
    return '\n'.join(parts)
