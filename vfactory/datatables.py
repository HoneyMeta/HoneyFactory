"""全局数据表：模型里的 tables 段，随模型保存、进版本、进实验和推演副本。

model['tables'] = [{name, desc, columns: [列名...], rows: [{列名: 值}...]}]

用途
- 来料块参数 table=表名：按表里的 时间/产品/数量/订单 放料（订单表、排程表驱动），repeat_h>0 时循环；
- 表达式 tbl('表名', 键, '列名')：按第一列查值，例如 tbl('工时', item.get('type'), '时间')；
- 工艺路线表 → 各加工块的"按产品用时"、换型矩阵；BOM 表 → 装配块的 BOM（生成编辑命令，写入草稿后在编辑器里应用）。
"""
from .i18n import _tr
import csv
import io
import re
from datetime import datetime

ALIAS = {
    'time': ('time_h', 't_h', 'time', '时间', '到达时间', '投产时间', '开始时间', 'release'),
    'product': ('product', '产品', 'type', '物料', '型号', '零件'),
    'qty': ('qty', '数量', 'quantity', '件数'),
    'order': ('order', '订单', '订单号', 'so'),
    'station': ('station', '设备', '工位', 'block', '工序设备', '资源'),
    'seq': ('seq', '工序号', '序号', 'step', 'op'),
    'cycle': ('cycle', '工时', '用时', '加工时间', 'time_s', 'cycle_s', '节拍'),
    'setup': ('setup_min', '换型', '换型时间', 'setup'),
    'parent': ('parent', '父件', '成品', '总成', '产品'),
    'child': ('child', '子件', '零件', '组件', '物料'),
    'bom_station': ('station', '装配工位', '工位', '设备'),
}


def tables_of(cfg) -> list:
    return list(cfg.get('tables') or []) if isinstance(cfg, dict) else []


def find(cfg, name):
    return next((t for t in tables_of(cfg) if t.get('name') == name), None)


def col(table, key, exclude=()):
    cols = table.get('columns') or (list(table['rows'][0].keys()) if table.get('rows') else [])
    low = {str(c).strip().lower(): c for c in cols}
    for a in ALIAS[key]:
        if a.lower() in low and low[a.lower()] not in exclude:
            return low[a.lower()]
    return None


def _num(v, default=None):
    if v is None or v == '':
        return default
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() else f
    except ValueError:
        return default


def normalize(columns, rows):
    """统一成 {columns, rows:[{列: 值}]}；数字字符串转成数字。"""
    columns = [str(c).strip() for c in columns if c is not None and str(c).strip() != '']
    out = []
    for r in rows:
        if isinstance(r, dict):
            d = {c: r.get(c) for c in columns}
        else:
            d = {c: (r[i] if i < len(r) else None) for i, c in enumerate(columns)}
        if all(v in (None, '') for v in d.values()):
            continue
        for k, v in d.items():
            if isinstance(v, str):
                v = v.strip()
                n = _num(v)
                d[k] = n if n is not None and re.fullmatch(r'-?\d+(\.\d+)?', v) else v
            elif isinstance(v, datetime):
                d[k] = v.strftime('%Y-%m-%d %H:%M')
        out.append(d)
    return {'columns': columns, 'rows': out}


def parse_file(filename: str, raw: bytes) -> dict:
    """CSV（UTF-8 / GBK）或 Excel 第一张表 → {columns, rows}。"""
    fn = (filename or '').lower()
    if fn.endswith(('.xlsx', '.xlsm')):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        head = next(it, None) or []
        return normalize(list(head), [list(r) for r in it])
    for enc in ('utf-8-sig', 'gbk'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(_tr('无法识别文件编码（请用 UTF-8 或 GBK 的 CSV，或 Excel）'))
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=',\t;') if text.strip() else csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ValueError(_tr('文件是空的'))
    return normalize(rows[0], rows[1:])


def to_csv(table) -> str:
    s = io.StringIO()
    w = csv.writer(s)
    cols = table.get('columns') or []
    w.writerow(cols)
    for r in table.get('rows') or []:
        w.writerow([r.get(c, '') for c in cols])
    return '﻿' + s.getvalue()


# ---------------- 仿真里用 ----------------
def schedule_rows(plant, name):
    """来料排程：[(仿真秒, 产品, 数量, 订单)]，按时间排序。时间列可以是小时数或日期时间。"""
    t = find(plant.cfg, name)
    if not t:
        plant.log('PLANT', 'alarm', _tr('来料引用的数据表「{name}」不存在', name=name))
        return []
    ct, cp, cq, co = col(t, 'time'), col(t, 'product'), col(t, 'qty'), col(t, 'order')
    out = []
    for r in t.get('rows') or []:
        tv = r.get(ct) if ct else 0
        ts = None
        n = _num(tv)
        if n is not None:
            ts = float(n) * 3600
        elif tv:
            try:
                ts = (datetime.fromisoformat(str(tv).replace('/', '-').replace(' ', 'T')) - plant.t0).total_seconds()
            except ValueError:
                ts = None
        if ts is None:
            continue
        qty = int(_num(r.get(cq), 1) or 0) if cq else 1
        out.append((max(0.0, ts), (str(r.get(cp)) if cp and r.get(cp) not in (None, '') else None), qty, (str(r.get(co)) if co and r.get(co) not in (None, '') else None)))
    out.sort(key=lambda x: x[0])
    return out


def lookup(plant, name, key, column):
    """tbl('表名', 键, '列名')：在第一列（或名为 key/键 的列）里找键，返回该行指定列。"""
    cache = plant.__dict__.setdefault('_tbl_cache', {})
    tabs = plant.cfg.get('tables')
    stamp = id(tabs)
    if cache.get('_stamp') != stamp:
        cache.clear()
        cache['_stamp'] = stamp
    idx = cache.get(name)
    if idx is None:
        t = find(plant.cfg, name) or {'columns': [], 'rows': []}
        cols = t.get('columns') or []
        kc = cols[0] if cols else None
        idx = {}
        for r in t.get('rows') or []:
            k = r.get(kc)
            idx.setdefault(str(k), r)
        cache[name] = idx
    r = idx.get(str(key))
    if r is None:
        return 0.0
    v = r.get(column)
    return 0.0 if v is None or v == '' else v


# ---------------- 工艺路线 / BOM → 编辑命令 ----------------
def _block_ref(model, ref):
    ref = str(ref).strip()
    for b in model.get('blocks', []):
        if b['id'] == ref:
            return b
    for b in model.get('blocks', []):
        if b.get('name') == ref:
            return b
    return None


def _reach(model):
    nxt = {}
    for l in model.get('links', []):
        if l.get('kind', 'material') == 'material':
            nxt.setdefault(l['from'], set()).add(l['to'])

    def ok(a, b):
        seen, stack = {a}, [a]
        while stack:
            x = stack.pop()
            for y in nxt.get(x, ()):
                if y == b:
                    return True
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return False
    return ok


def routing_ops(model, table):
    """工艺路线表（产品、工序号、设备、工时、换型）→ 每台设备的 times_by_product（和 setup_matrix 的 * 行）。"""
    cp, cs, cst, cc, cu = col(table, 'product'), col(table, 'seq'), col(table, 'station'), col(table, 'cycle'), col(table, 'setup')
    issues = []
    if not (cp and cst and cc):
        return {'ops': [], 'issues': [{'level': 'error', 'msg': _tr('工艺路线表需要列：产品、设备（编号或名称）、工时（秒或表达式）；可选：工序号、换型（分钟）')}], 'routes': {}}
    per = {}
    routes = {}
    setups = {}
    rows = list(table.get('rows') or [])
    if cs:
        rows.sort(key=lambda r: (str(r.get(cp)), _num(r.get(cs), 0) or 0))
    for r in rows:
        b = _block_ref(model, r.get(cst))
        prod = str(r.get(cp))
        if b is None:
            issues.append({'level': 'error', 'msg': _tr('产品 {prod}：设备「{get}」在模型里找不到', prod=prod, get=r.get(cst))})
            continue
        if b['type'] not in ('processor', 'batch', 'inspect', 'assembly', 'rework'):
            issues.append({'level': 'warn', 'msg': _tr('{name} 是「{type}」类型，工时只对加工块生效', name=b["name"], type=b["type"])})
        v = r.get(cc)
        per.setdefault(b['id'], {})[prod] = v if isinstance(v, (int, float)) else str(v)
        routes.setdefault(prod, []).append(b['id'])
        if cu and r.get(cu) not in (None, ''):
            setups.setdefault(b['id'], {})[prod] = _num(r.get(cu), 0)
    reach = _reach(model)
    for prod, seq in routes.items():
        for a, b in zip(seq, seq[1:]):
            if a != b and not reach(a, b):
                issues.append({'level': 'warn', 'msg': _tr('产品 {prod}：{a} → {b} 之间没有物料连线，零件走不到下一道', prod=prod, a=a, b=b)})
    ops = []
    for bid, m in per.items():
        b = _block_ref(model, bid)
        cur = dict((b.get('params') or {}).get('times_by_product') or {})
        cur.update(m)
        st = {'params.times_by_product': cur}
        if bid in setups:
            mx = dict((b.get('params') or {}).get('setup_matrix') or {})
            star = dict(mx.get('*') or {})
            star.update(setups[bid])
            mx['*'] = star
            st['params.setup_matrix'] = mx
        ops.append({'op': 'update_block', 'id': bid, 'set': st})
    return {'ops': ops, 'issues': issues, 'routes': routes}


def bom_ops(model, table):
    """BOM 表（父件、子件、数量，可选装配工位）→ 装配块的 bom 与 out_product。"""
    cpar, cch, cq = col(table, 'parent'), None, col(table, 'qty')
    cch = col(table, 'child', exclude=(cpar,))
    cst = col(table, 'bom_station', exclude=(cpar, cch))
    issues = []
    if not (cpar and cch):
        return {'ops': [], 'issues': [{'level': 'error', 'msg': _tr('BOM 表需要列：父件（成品）、子件、数量；可选：装配工位')}], 'boms': {}}
    boms, where = {}, {}
    for r in table.get('rows') or []:
        par, ch = str(r.get(cpar)), str(r.get(cch))
        boms.setdefault(par, {})[ch] = int(_num(r.get(cq), 1) or 1) if cq else 1
        if cst and r.get(cst):
            where[par] = r.get(cst)
    asm = [b for b in model.get('blocks', []) if b['type'] == 'assembly']
    ops = []
    for i, (par, bom) in enumerate(boms.items()):
        b = _block_ref(model, where[par]) if par in where else next((x for x in asm if (x.get('params') or {}).get('out_product') == par), None)
        if b is None and len(asm) > i:
            b = asm[i]
        if b is None:
            issues.append({'level': 'error', 'msg': _tr('{par} 没有对应的装配块（在表里加"装配工位"列，或先在模型里放一个装配块）', par=par)})
            continue
        if b['type'] != 'assembly':
            issues.append({'level': 'warn', 'msg': _tr('{name} 不是装配块', name=b["name"])})
        ops.append({'op': 'update_block', 'id': b['id'], 'set': {'params.bom': bom, 'params.out_product': par, 'params.parts': sum(bom.values())}})
    return {'ops': ops, 'issues': issues, 'boms': boms}
