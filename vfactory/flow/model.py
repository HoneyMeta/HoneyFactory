"""项目模型 2.0：块 + 连线 + 分组。旧版配置（stations/buffers）自动转换。

model = {
  version: 2, plant: {...}, areas: [...], plan: {...},
  blocks: [{id, type, name, pos:[x,y], size:[L,W], rot, area, node:[gx,gy], group, params:{...}, signals:[...], bindings:[...]}],
  links:  [{id, kind:'material'|'signal', from, from_port, to, to_port, via, capacity, products, cond, weight, fixed}],
  groups: [{id, name, color, node:[x,y], size:[w,h], collapsed}],
  notes:  [{id, text, node:[x,y], size:[w,h]}],
}
"""
from ..i18n import _tr, label
import copy
import json
import math
import os
import re
from collections import defaultdict

from .catalog import BLOCK_TYPES, IMPLICIT_PORTS, LEGACY_PORTS

STAGE = {'induction_furnace': 0, 'sand_system': 0, 'treatment': 1, 'molding_line': 2, 'cooling_line': 3, 'buf:shot_in': 4, 'shot_blast': 5, 'receiving': 5,
         'buf:raw': 6, 'buf:cnc_in': 7, 'cnc': 8, 'buf:deb_in': 9, 'deburr_cell': 10, 'buf:ins_in': 11, 'inspection': 12, 'buf:fg': 13, 'warehouse': 14,
         'agv_fleet': 7, 'worker_crew': 3}
BUF_NAMES = {'shot_in': '待抛丸', 'raw': '毛坯暂存', 'cnc_in': '机加线边库', 'deb_in': '待去毛刺', 'ins_in': '待检测', 'fg': '成品待入库'}
BASE_KEYS = ('id', 'type', 'name', 'pos', 'size', 'rot', 'area')


def is_v2(cfg):
    return 'blocks' in cfg


def to_v2(cfg: dict) -> dict:
    """旧版 → 2.0。连线按旧版设备之间的固定物料关系推出来，卡片按工序自动排版。"""
    if is_v2(cfg):
        return cfg
    c = copy.deepcopy(cfg)
    sts = c.get('stations', [])
    agv = next((s for s in sts if s['type'] == 'agv_fleet'), None)
    nodes = (agv or {}).get('nodes', {})
    blocks = []
    for s in sts:
        params = {k: v for k, v in s.items() if k not in BASE_KEYS}
        blocks.append({'id': s['id'], 'type': s['type'], 'name': s.get('name', s['id']), 'pos': s.get('pos', [0, 0]), 'size': s.get('size', [4, 4]),
                       'rot': s.get('rot', 0), 'params': params})
    by_type = defaultdict(list)
    for b in blocks:
        by_type[b['type']].append(b)
    for name, cap in (c.get('buffers') or {}).items():
        pos = nodes.get(name)
        if pos is None:
            owner = {'shot_in': 'shot_blast', 'deb_in': 'deburr_cell', 'ins_in': 'inspection', 'cnc_in': 'cnc', 'fg': 'inspection', 'raw': 'shot_blast'}.get(name)
            o = by_type.get(owner, [None])[0]
            pos = [o['pos'][0] - o['size'][0] / 2 - 2, o['pos'][1]] if o else [0, 0]
        blocks.append({'id': name, 'type': 'buffer', 'name': label(BUF_NAMES.get(name, name)), 'pos': list(pos), 'size': [3, 3], 'rot': 0,
                       'params': {'capacity': cap}})
    bufs = set((c.get('buffers') or {}).keys())
    links = []

    def L(a, ap, b, bp, **kw):
        links.append({'id': f'L{len(links) + 1}', 'kind': 'material', 'from': a, 'from_port': ap, 'to': b, 'to_port': bp, **kw})
    for f in by_type['induction_furnace']:
        for t in by_type['treatment']:
            L(f['id'], 'melt', t['id'], 'melt', fixed=True)
    for t in by_type['treatment']:
        for m in by_type['molding_line']:
            L(t['id'], 'ladle', m['id'], 'ladle', fixed=True)
    for s in by_type['sand_system']:
        for m in by_type['molding_line']:
            L(s['id'], 'sand', m['id'], 'sand', fixed=True)
    for m in by_type['molding_line']:
        for cl in by_type['cooling_line']:
            L(m['id'], 'mold', cl['id'], 'mold', fixed=True)
    for cl in by_type['cooling_line']:
        if 'shot_in' in bufs:
            L(cl['id'], 'out', 'shot_in', 'in')
    for sb in by_type['shot_blast']:
        if 'shot_in' in bufs:
            L('shot_in', 'out', sb['id'], 'in')
        if 'raw' in bufs:
            L(sb['id'], 'out', 'raw', 'in')
    for r in by_type['receiving']:
        if 'raw' in bufs:
            L(r['id'], 'out', 'raw', 'in')
    for cn in by_type['cnc']:
        if 'cnc_in' in bufs:
            L('cnc_in', 'out', cn['id'], 'in')
        if 'deb_in' in bufs:
            L(cn['id'], 'out', 'deb_in', 'in')
    for d in by_type['deburr_cell']:
        if 'deb_in' in bufs:
            L('deb_in', 'out', d['id'], 'in')
        if 'ins_in' in bufs:
            L(d['id'], 'out', 'ins_in', 'in')
    for i in by_type['inspection']:
        if 'ins_in' in bufs:
            L('ins_in', 'out', i['id'], 'in')
        if 'fg' in bufs:
            L(i['id'], 'out', 'fg', 'in')
        if 'deb_in' in bufs:
            L(i['id'], 'rework', 'deb_in', 'in', cond=_tr('返修'))
    if agv:
        if 'raw' in bufs and 'cnc_in' in bufs:
            L('raw', 'out', 'cnc_in', 'in', via=agv['id'], fixed=True)
        for w in by_type['warehouse']:
            if 'fg' in bufs:
                L('fg', 'out', w['id'], 'in', via=agv['id'], fixed=True)
    # 卡片自动排版
    col = defaultdict(int)
    for b in blocks:
        key = 'buf:' + b['id'] if b['type'] == 'buffer' else b['type']
        st = STAGE.get(key, 15)
        row = col[st]
        col[st] += 1
        if b['type'] in ('agv_fleet', 'worker_crew'):
            b['node'] = [STAGE[b['type']] * 230, 620 + row * 120]
        else:
            b['node'] = [st * 230, 40 + row * 120 + (240 if b['type'] == 'sand_system' else 0)]
    out = {k: v for k, v in c.items() if k not in ('stations', 'buffers')}
    out.update(version=2, blocks=blocks, links=links, groups=[], notes=[])
    return out


def block_class(t):
    from ..models import REGISTRY
    return REGISTRY.get(t)


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def submodel_def(model, ref):
    """子模型定义：先找模型里的 submodels 段（按编号或名称），再找编辑器保存的模板（T 开头的编号）。

    定义 = {id, name, blocks, links, entry:{block, port}, exit:{block, port}, expose:[{name, label, default, targets:['M1.time', ...]}]}"""
    if not ref:
        return None
    for d in model.get('submodels') or []:
        if d.get('id') == ref or d.get('name') == ref:
            return d
    if re.match(r'^T\d+$', str(ref)):
        from .. import paths as _paths
        path = _paths.data('templates', f'{ref}.json')
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, ValueError):
                return None
    return None


def submodel_ports(d):
    """入口/出口：定义里写了就用；否则取内部没有来料连线的第一个块、没有出料连线的最后一个块。"""
    bl = [b for b in d.get('blocks') or [] if b.get('type') not in ('operators', 'transporter')]
    ml = [l for l in d.get('links') or [] if l.get('kind', 'material') == 'material']
    has_in = {l['to'] for l in ml}
    has_out = {l['from'] for l in ml}

    def norm(x, port):
        if isinstance(x, dict) and x.get('block'):
            return (x['block'], x.get('port') or port)
        if isinstance(x, str) and x:
            return (x, port)
        return None
    entry = norm(d.get('entry'), 'in') or next(((b['id'], 'in') for b in bl if b['id'] not in has_in and b.get('type') != 'source'), None)
    exit_ = norm(d.get('exit'), 'out') or next(((b['id'], 'out') for b in reversed(bl) if b['id'] not in has_out and b.get('type') != 'sink'), None)
    return entry, exit_


def _instantiate(d, sb):
    """把定义复制成一份实例：编号加前缀、位置跟着子模型块走、暴露参数写进内部块。"""
    pre = sb['id'] + '_'
    inner = {b['id'] for b in d.get('blocks') or []}
    bl = d.get('blocks') or []
    cx = sum(b.get('pos', [0, 0])[0] for b in bl) / max(1, len(bl))
    cy = sum(b.get('pos', [0, 0])[1] for b in bl) / max(1, len(bl))
    sx, sy = (sb.get('pos') or [0, 0])[:2]
    sp = sb.get('params') or {}
    vals = dict(sp.get('values') or {}) if isinstance(sp.get('values'), dict) else {}
    out_b = []
    for b in bl:
        c = copy.deepcopy(b)
        c['id'] = pre + b['id']
        c['name'] = f"{sb.get('name', sb['id'])}/{b.get('name', b['id'])}"
        px, py = b.get('pos', [0, 0])[:2]
        c['pos'] = [round(sx + px - cx, 2), round(sy + py - cy, 2)]
        prm = c.setdefault('params', {})
        if prm.get('operator') in inner:
            prm['operator'] = pre + prm['operator']
        out_b.append(c)
    by = {c['id']: c for c in out_b}
    for e in d.get('expose') or []:
        nm = e.get('name')
        v = sp.get(nm) if sp.get(nm) not in (None, '') else vals.get(nm, e.get('default'))
        if v in (None, ''):
            continue
        for tg in e.get('targets') or []:
            bid, _, key = str(tg).partition('.')
            c = by.get(pre + bid)
            if c is not None and key:
                c.setdefault('params', {})[key] = copy.deepcopy(v)
    out_l = []
    for l in d.get('links') or []:
        c = copy.deepcopy(l)
        c['id'] = pre + l['id']
        c['from'], c['to'] = pre + l['from'], pre + l['to']
        if l.get('via') in inner:
            c['via'] = pre + l['via']
        out_l.append(c)
    entry, exit_ = submodel_ports(d)
    entry = (pre + entry[0], entry[1]) if entry else None
    exit_ = (pre + exit_[0], exit_[1]) if exit_ else None
    return out_b, out_l, entry, exit_


def flatten(model, blocks=None, links=None, depth=0, stack=()):
    """展开子模型（可多层）：返回 (块, 连线, 入口重定向, 出口重定向)。内部块带 _parent，子模型块带 _exit。"""
    blocks = model.get('blocks', []) if blocks is None else blocks
    links = model.get('links', []) if links is None else links
    out_b, out_l, rin, rout = [], [], {}, {}
    for b in blocks:
        b = dict(b)
        out_b.append(b)
        if b.get('type') != 'submodel':
            continue
        ref = (b.get('params') or {}).get('def')
        d = submodel_def(model, ref)
        key = (d or {}).get('id') or ref
        if d is None or key in stack or depth >= 6:
            continue
        ib, il, entry, exit_ = _instantiate(d, b)
        for x in ib:
            x['_parent'] = b['id']
        fb, fl, nin, nout = flatten(model, ib, il, depth + 1, stack + (key,))
        for _ in range(8):
            if entry and nin.get(entry[0]):
                entry = nin[entry[0]]
            if exit_ and nout.get(exit_[0]):
                exit_ = nout[exit_[0]]
        rin[b['id']], rout[b['id']] = entry, exit_
        b['_exit'] = exit_[0] if exit_ else None
        out_b += fb
        out_l += fl
    for l in links:
        l = dict(l)
        if rin.get(l['to']):
            l['to'], l['to_port'] = rin[l['to']]
        if rout.get(l['from']):
            l['from'], l['from_port'] = rout[l['from']]
        out_l.append(l)
    return out_b, out_l, rin, rout


def expand(model: dict) -> dict:
    """2.0 → 仿真用：stations（带端口/队列）和 buffers（名称 → 容量）。子模型内部的块嵌在子模型的 _children 里。"""
    if any(b.get('type') == 'submodel' for b in model.get('blocks', [])):
        fb, fl, _, _ = flatten(model)
    else:
        fb, fl = model.get('blocks', []), model.get('links', [])
    blocks = {b['id']: b for b in fb}
    buffers = {}
    ins, outs, routes, ports = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(dict)
    for b in blocks.values():
        if b['type'] == 'buffer':
            buffers[b['id']] = int((b.get('params') or {}).get('capacity', 50) or 50)

    def legacy(b):
        return b['type'] in LEGACY_PORTS or BLOCK_TYPES.get(b['type'], {}).get('legacy')
    for l in fl:
        if l.get('kind', 'material') != 'material':
            continue
        A, B = blocks.get(l['from']), blocks.get(l['to'])
        if A is None or B is None:
            continue
        if l.get('from_port') in IMPLICIT_PORTS or l.get('to_port') in IMPLICIT_PORTS:
            continue          # 高级模型之间的内部耦合（铁水、浇包、型砂、砂型），只用于显示
        rule = {k: l[k] for k in ('products', 'cond', 'weight') if l.get(k) not in (None, '', [])}
        if rule.get('cond') == '返修':
            rule.pop('cond')
        via = blocks.get(l.get('via')) if l.get('via') else None
        if via is not None:
            if via['type'] == 'agv_fleet':
                continue      # 旧版 AGV 车队按固定任务运行
            src = A['id'] if A['type'] == 'buffer' else f"{l['id']}@a"
            dst = B['id'] if B['type'] == 'buffer' else f"{l['id']}@b"
            for q in (src, dst):
                if q not in buffers:
                    buffers[q] = int(l.get('capacity') or 10)
            if A['type'] != 'buffer':
                outs[A['id']].append({'buf': src, 'port': l.get('from_port') or 'out', **rule})
                ports[A['id']][l.get('from_port') or 'out'] = src
            if B['type'] != 'buffer':
                ins[B['id']].append(dst)
                ports[B['id']][l.get('to_port') or 'in'] = dst
            routes[via['id']].append({'id': l['id'], 'src': src, 'dst': dst, 'a': list(A['pos']), 'b': list(B['pos']),
                                      'an': A.get('name') or A['id'], 'bn': B.get('name') or B['id']})
            continue
        if A['type'] == 'buffer' and B['type'] == 'buffer':
            continue
        q = A['id'] if A['type'] == 'buffer' else B['id'] if B['type'] == 'buffer' else l['id']
        if q == l['id']:
            buffers[q] = int(l.get('capacity') or 2)
        if A['type'] != 'buffer':
            outs[A['id']].append({'buf': q, 'port': l.get('from_port') or 'out', **rule})
            ports[A['id']][l.get('from_port') or 'out'] = q
        if B['type'] != 'buffer':
            ins[B['id']].append(q)
            ports[B['id']][l.get('to_port') or 'in'] = q
    stations = []
    for b in blocks.values():
        sc = {'id': b['id'], 'type': b['type'], 'name': b.get('name', b['id']), 'pos': list(b.get('pos', [0, 0])), 'size': list(b.get('size', [4, 4])),
              'rot': b.get('rot', 0), **copy.deepcopy(b.get('params') or {})}
        if b.get('area'):
            sc['area'] = b['area']
        if b.get('signals'):
            sc['signals'] = b['signals']
        if b.get('bindings'):
            sc['bindings'] = b['bindings']
        if legacy(b):
            if ports.get(b['id']):
                sc['ports'] = {k: v for k, v in ports[b['id']].items()}
        else:
            sc['_in'], sc['_out'], sc['_routes'] = ins.get(b['id'], []), outs.get(b['id'], []), routes.get(b['id'], [])
        if b.get('_parent'):
            sc['_parent'] = b['_parent']
        if b['type'] == 'submodel':
            sc['_exit'] = b.get('_exit')
            sc['_children'] = []
        stations.append(sc)
    if any('_parent' in sc for sc in stations):
        by = {sc['id']: sc for sc in stations}
        top = []
        for sc in stations:
            par = sc.pop('_parent', None)
            if par and par in by:
                by[par].setdefault('_children', []).append(sc)
            else:
                top.append(sc)
        stations = top
    return {'stations': stations, 'buffers': buffers}


# ---------------- 编辑命令（与前端命令总线一致） ----------------
def _get(model, coll, id_):
    return next((x for x in model.get(coll, []) if x['id'] == id_), None)


def _set_path(obj, path, value):
    keys = path.split('.')
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    old = obj.get(keys[-1])
    if value is None:
        obj.pop(keys[-1], None)
    else:
        obj[keys[-1]] = value
    return old


def apply_ops(model: dict, ops: list) -> tuple[dict, list]:
    """应用一组命令，返回 (新模型, 逆命令列表)。命令：
    add_block{block} remove_block{id} update_block{id,set:{路径:值}} add_link{link} remove_link{id} update_link{id,set}
    add_group{group} remove_group{id} update_group{id,set} add_note{note} remove_note{id} update_note{id,set} update_plant{set}"""
    m = copy.deepcopy(model)
    inv = []
    for op in ops:
        t = op['op']
        if t == 'add_block':
            m.setdefault('blocks', []).append(copy.deepcopy(op['block']))
            inv.insert(0, {'op': 'remove_block', 'id': op['block']['id']})
        elif t == 'remove_block':
            b = _get(m, 'blocks', op['id'])
            if not b:
                continue
            gone = [l for l in m.get('links', []) if op['id'] in (l['from'], l['to'], l.get('via'))]
            m['links'] = [l for l in m.get('links', []) if l not in gone]
            m['blocks'] = [x for x in m['blocks'] if x['id'] != op['id']]
            inv.insert(0, {'op': 'add_block', 'block': b})
            for l in gone:
                inv.insert(1, {'op': 'add_link', 'link': l})
        elif t in ('update_block', 'update_link', 'update_group', 'update_note'):
            coll = {'update_block': 'blocks', 'update_link': 'links', 'update_group': 'groups', 'update_note': 'notes'}[t]
            x = _get(m, coll, op['id'])
            if not x:
                continue
            old = {}
            for path, v in op['set'].items():
                old[path] = copy.deepcopy(_set_path(x, path, copy.deepcopy(v)))
            inv.insert(0, {'op': t, 'id': op['id'], 'set': old})
        elif t == 'add_link':
            m.setdefault('links', []).append(copy.deepcopy(op['link']))
            inv.insert(0, {'op': 'remove_link', 'id': op['link']['id']})
        elif t == 'remove_link':
            l = _get(m, 'links', op['id'])
            if l:
                m['links'] = [x for x in m['links'] if x['id'] != op['id']]
                inv.insert(0, {'op': 'add_link', 'link': l})
        elif t == 'add_group':
            m.setdefault('groups', []).append(copy.deepcopy(op['group']))
            inv.insert(0, {'op': 'remove_group', 'id': op['group']['id']})
        elif t == 'remove_group':
            g = _get(m, 'groups', op['id'])
            if g:
                m['groups'] = [x for x in m['groups'] if x['id'] != op['id']]
                inv.insert(0, {'op': 'add_group', 'group': g})
        elif t in ('add_note', 'remove_note'):
            if t == 'add_note':
                m.setdefault('notes', []).append(copy.deepcopy(op['note']))
                inv.insert(0, {'op': 'remove_note', 'id': op['note']['id']})
            else:
                g = _get(m, 'notes', op['id'])
                if g:
                    m['notes'] = [x for x in m['notes'] if x['id'] != op['id']]
                    inv.insert(0, {'op': 'add_note', 'note': g})
        elif t == 'update_plant':
            old = {}
            for path, v in op['set'].items():
                old[path] = copy.deepcopy(_set_path(m, path, copy.deepcopy(v)))
            inv.insert(0, {'op': 'update_plant', 'set': old})
        else:
            raise ValueError(_tr('未知命令 {t}', t=t))
    return m, inv


def new_id(model, prefix):
    used = {b['id'] for b in model.get('blocks', [])} | {l['id'] for l in model.get('links', [])} | {g['id'] for g in model.get('groups', [])} | {g['id'] for g in model.get('notes', [])}
    n = 1
    while f'{prefix}{n}' in used:
        n += 1
    return f'{prefix}{n}'


# ---------------- 校验 ----------------
# issue categories: display text (message id) -> stable code (issues[].cat_code; the frontend matches codes, not texts)
ISSUE_CATS = {'布局': 'layout', '连线': 'wiring', '人员': 'crew', '信号': 'signal', '协议': 'protocol', '子模型': 'submodel', '工艺': 'process',
              '模型': 'model', '物流': 'logistics', '表达式': 'expression', '数据': 'data', '计划': 'plan', '能耗': 'energy'}


def issue_cat_code(cat):
    from ..i18n import variants
    for zh, code in ISSUE_CATS.items():
        if cat in variants(zh):
            return code
    return 'other'


def validate(model: dict) -> dict:
    from .expr import ExprError, check
    issues = []

    def add(level, cat, msg, obj=None):
        issues.append({'level': level, 'cat': cat, 'cat_code': issue_cat_code(cat), 'msg': msg, 'id': obj})
    blocks = {b['id']: b for b in model.get('blocks', [])}
    ids = [b['id'] for b in model.get('blocks', [])]
    for d in {x for x in ids if ids.count(x) > 1}:
        add('error', _tr('模型'), _tr('编号 {d} 重复', d=d), d)
    for b in blocks.values():
        if not re.match(r'^[A-Za-z][A-Za-z0-9_\-]{0,31}$', b['id']):
            add('error', _tr('模型'), _tr('编号 {id} 只能用字母开头的字母、数字、下划线', id=b["id"]), b['id'])
        if b['type'] not in BLOCK_TYPES:
            add('error', _tr('模型'), _tr('{id} 的类型 {type} 不存在', id=b["id"], type=b["type"]), b['id'])
    links = model.get('links', [])
    for l in links:
        if l['from'] not in blocks or l['to'] not in blocks:
            add('error', _tr('连线'), _tr('连线 {id} 的端点不存在', id=l["id"]), l['id'])
            continue
        A, B = blocks[l['from']], blocks[l['to']]
        if l.get('kind', 'material') == 'material' and A['type'] == 'buffer' and B['type'] == 'buffer' and not l.get('via'):
            add('error', _tr('连线'), _tr('{name} → {name2}：两个缓存之间要指定搬运（AGV/叉车）', name=A["name"], name2=B["name"]), l['id'])
        if l.get('via') and l['via'] not in blocks:
            add('error', _tr('连线'), _tr('连线 {id} 指定的搬运车队不存在', id=l["id"]), l['id'])
        if l.get('cond') and l['cond'] != '返修':
            try:
                check(l['cond'], ('item',))
            except ExprError as e:
                add('error', _tr('表达式'), _tr('连线 {id} 路由条件：{e}', id=l["id"], e=e), l['id'])
    conn_in = defaultdict(int)
    conn_out = defaultdict(int)
    for l in links:
        if l.get('kind', 'material') == 'material':
            conn_out[l['from']] += 1
            conn_in[l['to']] += 1
    for b in blocks.values():
        spec = BLOCK_TYPES.get(b['type'], {})
        if spec.get('legacy'):
            continue
        if spec.get('needs_in') and not conn_in[b['id']]:
            add('warn', _tr('连线'), _tr('{name} 没有来料连线，会一直"饥饿"', name=b["name"]), b['id'])
        if spec.get('needs_out') and not conn_out[b['id']]:
            add('warn', _tr('连线'), _tr('{name} 没有出料连线，做完的件会堵住', name=b["name"]), b['id'])
        p = b.get('params') or {}
        for key, ps in (spec.get('params') or {}).items():
            if ps.get('t') == 'expr' and p.get(key) not in (None, ''):
                try:
                    check(str(p[key]), ('item',))
                except ExprError as e:
                    add('error', _tr('表达式'), _tr('{name} 的"{label}"：{e}', name=b["name"], label=ps["label"], e=e), b['id'])
        for d in p.get('defects') or []:
            try:
                check(str(d.get('prob', '0')), ('item',))
            except ExprError as e:
                add('error', _tr('表达式'), _tr('{name} 缺陷"{get}"概率：{e}', name=b["name"], get=d.get("name"), e=e), b['id'])
        if b['type'] == 'submodel':
            d = submodel_def(model, p.get('def'))
            if d is None:
                add('error', _tr('子模型'), _tr('{name} 引用的子模型定义「{v}」不存在', name=b["name"], v=p.get("def") or _tr('（未填）')), b['id'])
            else:
                en, ex_ = submodel_ports(d)
                if not en or not ex_:
                    add('warn', _tr('子模型'), _tr('{name}：子模型「{get}」找不到入口或出口块', name=b["name"], get=d.get("name")), b['id'])
        if b['type'] == 'cell':
            from ..control import validate_cell
            cdef = p.get('cell') or {}
            for lv, msg in validate_cell(cdef):
                add(lv, _tr('控制单元'), _tr('{name}：{msg}', name=b["name"], msg=msg), b['id'])
            ctypes = {c.get('type') for c in cdef.get('components') or []}
            if 'cell_entry' in ctypes and not conn_in[b['id']]:
                add('warn', _tr('连线'), _tr('{name} 有单元入口但没有来料连线', name=b["name"]), b['id'])
            if 'cell_exit' in ctypes and not conn_out[b['id']]:
                add('warn', _tr('连线'), _tr('{name} 有单元出口但没有出料连线，出口的零件会直接收走', name=b["name"]), b['id'])
        if p.get('operator') and p['operator'] not in blocks:
            add('error', _tr('人员'), _tr('{name} 指定的人员池 {operator} 不存在', name=b["name"], operator=p["operator"]), b['id'])
        for s in b.get('signals') or []:
            if s.get('expr'):
                try:
                    check(str(s['expr']))
                except ExprError as e:
                    add('error', _tr('信号'), _tr('{name} 点位 {get}：{e}', name=b["name"], get=s.get("name"), e=e), b['id'])
    # 占地重叠
    bs = [b for b in blocks.values() if b['type'] not in ('agv_fleet', 'worker_crew', 'operators', 'transporter')]
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            a, b = bs[i], bs[j]
            ra, rb = _rect(a), _rect(b)
            ox, oy = min(ra[1], rb[1]) - max(ra[0], rb[0]), min(ra[3], rb[3]) - max(ra[2], rb[2])
            if ox > 0.2 and oy > 0.2:
                add('warn', _tr('布局'), _tr('{name} 与 {name2} 占地重叠', name=a["name"], name2=b["name"]), a['id'])
    units = {}
    for b in blocks.values():
        u = (b.get('params') or {}).get('modbus_unit')
        if u:
            if u in units:
                add('error', _tr('协议'), _tr('Modbus 从站地址 {u} 被 {v} 和 {name} 重复使用', u=u, v=units[u], name=b["name"]), b['id'])
            units[u] = b['name']
    try:      # 平面图 AGV 路网：站点绑定、不可达、单向死路（vfactory/models/generic.py）
        from ..models.generic import network_issues
        for lv, msg, obj in network_issues(model):
            add(lv, _tr('路网'), msg, obj)
    except Exception:      # noqa: BLE001  路网检查出错不影响其他检查
        pass
    return {'ok': not any(i['level'] == 'error' for i in issues), 'issues': issues,
            'summary': {'error': sum(i['level'] == 'error' for i in issues), 'warn': sum(i['level'] == 'warn' for i in issues)}}


def _rect(b):
    L, W = b.get('size', [4, 4])
    if (b.get('rot') or 0) % 180:
        L, W = W, L
    x, y = b.get('pos', [0, 0])
    return x - L / 2, x + L / 2, y - W / 2, y + W / 2


# ---------------- 差异 ----------------
def diff(a: dict, b: dict) -> list:
    """两个版本的差异：新增/删除/修改的块和连线，修改给出字段前后值。"""
    out = []
    for coll, label in (('blocks', _tr('设备')), ('links', _tr('连线')), ('groups', _tr('分组'))):
        A = {x['id']: x for x in a.get(coll, [])}
        B = {x['id']: x for x in b.get(coll, [])}
        for k in B.keys() - A.keys():
            out.append({'kind': 'add', 'coll': coll, 'id': k, 'label': label, 'name': B[k].get('name', k)})
        for k in A.keys() - B.keys():
            out.append({'kind': 'remove', 'coll': coll, 'id': k, 'label': label, 'name': A[k].get('name', k)})
        for k in A.keys() & B.keys():
            ch = _changes(A[k], B[k])
            if ch:
                out.append({'kind': 'change', 'coll': coll, 'id': k, 'label': label, 'name': B[k].get('name', k), 'changes': ch})
    for key in ('plant', 'plan', 'areas'):
        if a.get(key) != b.get(key):
            out.append({'kind': 'change', 'coll': key, 'id': key, 'label': {'plant': _tr('工厂'), 'plan': _tr('计划'), 'areas': _tr('分区')}[key], 'name': key, 'changes': []})
    return out


def _changes(x, y, prefix=''):
    out = []
    for k in set(x) | set(y):
        if k in ('node',) and not prefix:
            continue
        a, b = x.get(k), y.get(k)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            out += _changes(a, b, prefix + k + '.')
        else:
            out.append({'path': prefix + k, 'old': a, 'new': b})
    return out


def area_of(model, pos):
    for a in model.get('areas', []):
        if a['x'][0] <= pos[0] < a['x'][1]:
            return a['name']
    return None


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])
