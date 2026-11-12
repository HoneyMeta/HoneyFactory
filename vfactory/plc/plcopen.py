"""PLCopen XML（IEC 61131-10 / TC6 0200）导入导出：LD / ST 子集。

导出：一个 program POU（变量表 + ST 文本或 LD 图），I/O 表作为配置里的全局变量（带地址）。
      LD 按 TC6 图形格式输出（左/右母线、触点、线圈、功能块、输入/输出变量、注释，带坐标），
      另外在 addData 里附上本软件的梯形图 JSON，导回来时能原样还原。
导入：取第一个 program POU；ST 取文本；LD 优先用 addData，没有就把图（连接关系）还原成串并联树。
限制：只支持 BOOL/整数/REAL/TIME/STRING/一维数组和标准功能块；SFC、FBD、用户自定义功能块/函数、结构体不导入（给出提示）。
"""
from ..i18n import _tr
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from .compiler import FB_DEFS, parse_type, tname
from .ld import CMP_OPS, MATH_OPS
from .st import fmt_time

TC6 = 'http://www.plcopen.org/xml/tc6_0200'
XHTML = 'http://www.w3.org/1999/xhtml'
VENDOR = 'http://honeymeta.cn/vfactory/ld'
ET.register_namespace('', TC6)
ET.register_namespace('xhtml', XHTML)
ET.register_namespace('vf', VENDOR)
N = '{%s}' % TC6
XN = '{%s}' % XHTML


class ImportError_(Exception):
    pass


def _sub(parent, tag, **attrs):
    return ET.SubElement(parent, N + tag, {k: str(v) for k, v in attrs.items() if v is not None})


def _xhtml(parent, text):
    x = ET.SubElement(parent, XN + 'xhtml')
    x.text = text
    return x


def _type_el(parent, typ_text):
    t = _sub(parent, 'type')
    try:
        typ = parse_type(typ_text)
    except Exception:
        typ = str(typ_text).upper()
    _type_inner(t, typ)
    return t


def _type_inner(t, typ):
    if isinstance(typ, tuple):
        a = _sub(t, 'array')
        _sub(a, 'dimension', lower=typ[1], upper=typ[2])
        bt = _sub(a, 'baseType')
        _type_inner(bt, typ[3])
    elif typ in FB_DEFS:
        _sub(t, 'derived', name=typ)
    elif typ == 'STRING':
        _sub(t, 'string')
    else:
        _sub(t, typ)


def _init_text(v):
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    return str(v)


def _var(parent, v):
    el = _sub(parent, 'variable', name=v['name'], address=v.get('addr') or None)
    _type_el(el, v.get('type') or 'BOOL')
    if v.get('init') not in (None, ''):
        iv = _sub(el, 'initialValue')
        _sub(iv, 'simpleValue', value=_init_text(v['init']))
    if v.get('comment'):
        d = _sub(el, 'documentation')
        _xhtml(d, v['comment'])
    return el


# ---------------------------------------------------------------- 导出
class _LdWriter:
    def __init__(self, body):
        self.ld = _sub(body, 'LD')
        self.id = 0
        self.y = 20
        self.row = 0

    def nid(self):
        self.id += 1
        return self.id

    def pos(self, el, x, y):
        _sub(el, 'position', x=x, y=y)

    def conn_in(self, el, refs, name='connectionPointIn'):
        cp = _sub(el, name)
        for r in refs:
            rid, fp = r
            _sub(cp, 'connection', refLocalId=rid, formalParameter=fp)
        return cp

    def rung(self, r):
        y0 = self.y
        if r.get('comment'):
            c = _sub(self.ld, 'comment', localId=self.nid(), height=30, width=600)
            self.pos(c, 20, self.y)
            _xhtml(_sub(c, 'content'), r['comment'])
            self.y += 40
        left = _sub(self.ld, 'leftPowerRail', localId=self.nid(), height=40, width=3)
        self.pos(left, 20, self.y)
        _sub(_sub(left, 'connectionPointOut', formalParameter=''), 'relPosition', x=3, y=20)
        self.rows = 1
        self.x = 60
        outs = self.series(r.get('elements') or [], [(left.get('localId'), None)], 60, self.y)
        right = _sub(self.ld, 'rightPowerRail', localId=self.nid(), height=40, width=3)
        self.pos(right, self.maxx + 60 if hasattr(self, 'maxx') else 400, y0)
        self.conn_in(right, outs)
        self.y += 60 * max(1, self.rows) + 20

    def series(self, els, ins, x, y):
        self.maxx = max(getattr(self, 'maxx', 0), x)
        for e in els:
            ins, x = self.node(e, ins, x, y)
        return ins

    def node(self, e, ins, x, y):
        if isinstance(e, list):
            for s in e:
                ins, x = self.node(s, ins, x, y)
            return ins, x
        if 'par' in e:
            outs, mx = [], x
            for i, b in enumerate(e['par']):
                yy = y + i * 60
                self.rows = max(self.rows, (yy - self.y) // 60 + 1)
                o, bx = self.node(b if isinstance(b, list) else [b], ins, x, yy)
                outs += o
                mx = max(mx, bx)
            return outs, mx
        if 'ser' in e:
            return self.node(e['ser'], ins, x, y)
        t = str(e.get('t', '')).upper()
        lid = self.nid()
        self.maxx = max(getattr(self, 'maxx', 0), x + 80)
        if t in ('NO', 'NC', 'P', 'N'):
            el = _sub(self.ld, 'contact', localId=lid, height=20, width=40, negated='true' if t == 'NC' else 'false',
                      edge={'P': 'rising', 'N': 'falling'}.get(t, 'none'))
            self.pos(el, x, y)
            self.conn_in(el, ins)
            _sub(el, 'connectionPointOut')
            v = _sub(el, 'variable')
            v.text = str(e.get('var', ''))
            return [(lid, None)], x + 80
        if t in ('COIL', 'NCOIL', 'SET', 'RESET'):
            el = _sub(self.ld, 'coil', localId=lid, height=20, width=40, negated='true' if t == 'NCOIL' else 'false',
                      storage={'SET': 'set', 'RESET': 'reset'}.get(t, 'none'))
            self.pos(el, x, y)
            self.conn_in(el, ins)
            _sub(el, 'connectionPointOut')
            v = _sub(el, 'variable')
            v.text = str(e.get('var', ''))
            return [(lid, None)], x + 80
        # 盒子
        if t == 'FB':
            typ = str(e.get('fb', '')).upper()
            d = FB_DEFS.get(typ, {'in': {}, 'out': {}, 'pin': 'IN', 'pout': 'Q'})
            blk = _sub(self.ld, 'block', localId=lid, typeName=typ, instanceName=e.get('inst') or None, height=80, width=80)
            pin, pout = d['pin'], d['pout']
            inputs = [(pin, None)] + [(k, (e.get('in') or {}).get(k)) for k in d['in'] if k != pin]
            outputs = list(d['out'])
            outmap = {str(k).upper(): v for k, v in (e.get('out') or {}).items()}
        elif t == 'CMP':
            op = CMP_OPS.get(str(e.get('op', '')).upper(), '=')
            typ = {'>': 'GT', '>=': 'GE', '=': 'EQ', '<>': 'NE', '<': 'LT', '<=': 'LE'}[op]
            blk = _sub(self.ld, 'block', localId=lid, typeName=typ, height=60, width=60)
            pin, pout = 'EN', 'OUT'
            inputs = [('EN', None), ('IN1', e.get('a')), ('IN2', e.get('b'))]
            outputs, outmap = ['OUT'], {}
        else:
            if t == 'MATH':
                op = MATH_OPS.get(str(e.get('op', '')).upper(), '+')
                typ = {'+': 'ADD', '-': 'SUB', '*': 'MUL', '/': 'DIV', 'MOD': 'MOD'}[op]
                inputs = [('EN', None), ('IN1', e.get('a')), ('IN2', e.get('b'))]
            else:
                typ = 'MOVE'
                inputs = [('EN', None), ('IN', e.get('in'))]
            blk = _sub(self.ld, 'block', localId=lid, typeName=typ, height=60, width=60)
            pin, pout = 'EN', 'ENO'
            outputs, outmap = ['ENO', 'OUT'], {'OUT': e.get('out')}
        self.pos(blk, x, y)
        iv = _sub(blk, 'inputVariables')
        extra = []
        for k, val in inputs:
            v = _sub(iv, 'variable', formalParameter=k)
            if k == pin:
                self.conn_in(v, ins)
            elif val not in (None, ''):
                vid = self.nid()
                extra.append(('in', vid, val, k))
                self.conn_in(v, [(vid, None)])
            else:
                _sub(v, 'connectionPointIn')
        _sub(blk, 'inOutVariables')
        ov = _sub(blk, 'outputVariables')
        for k in outputs:
            _sub(_sub(ov, 'variable', formalParameter=k), 'connectionPointOut')
            if outmap.get(k) not in (None, ''):
                extra.append(('out', self.nid(), outmap[k], k))
        for i, (kind, vid, val, k) in enumerate(extra):
            if kind == 'in':
                el = _sub(self.ld, 'inVariable', localId=vid, height=20, width=60)
                self.pos(el, x - 70, y + 20 + i * 20)
                _sub(el, 'connectionPointOut')
                ex = _sub(el, 'expression')
                ex.text = str(val)
            else:
                el = _sub(self.ld, 'outVariable', localId=vid, height=20, width=60)
                self.pos(el, x + 90, y + 20 + i * 20)
                self.conn_in(el, [(lid, k)])
                ex = _sub(el, 'expression')
                ex.text = str(val)
        return [(lid, pout)], x + 120


def export_xml(program, io=None, name=None, vendor_data=True):
    lang = str(program.get('lang') or 'ST').upper()
    root = ET.Element(N + 'project')
    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    _sub(root, 'fileHeader', companyName='HoneyMeta', productName=_tr('蜂元虚拟工厂'), productVersion='4.0', creationDateTime=now)
    ch = _sub(root, 'contentHeader', name=name or program.get('name') or 'VirtualFactory', modificationDateTime=now)
    ci = _sub(ch, 'coordinateInfo')
    for k in ('fbd', 'ld', 'sfc'):
        _sub(_sub(ci, k), 'scaling', x=1, y=1)
    types = _sub(root, 'types')
    _sub(types, 'dataTypes')
    pous = _sub(types, 'pous')
    pname = re.sub(r'[^A-Za-z0-9_]', '_', str(program.get('id') or 'Main')) or 'Main'
    if pname[0].isdigit():
        pname = 'P_' + pname
    pou = _sub(pous, 'pou', name=pname, pouType='program')
    itf = _sub(pou, 'interface')
    groups = {}
    for v in program.get('vars') or []:
        sec = str(v.get('section') or 'VAR').upper()
        tag = {'VAR_INPUT': 'inputVars', 'VAR_OUTPUT': 'outputVars', 'VAR_IN_OUT': 'inOutVars', 'VAR_TEMP': 'tempVars'}.get(sec, 'localVars')
        groups.setdefault((tag, bool(v.get('retain')), bool(v.get('constant'))), []).append(v)
    for (tag, ret, const), vs in groups.items():
        g = _sub(itf, tag, retain='true' if ret else None, constant='true' if const else None)
        for v in vs:
            _var(g, v)
    body = _sub(pou, 'body')
    if lang == 'ST':
        _xhtml(_sub(body, 'ST'), program.get('source') or '')
    else:
        src = program.get('source') or {'rungs': []}
        w = _LdWriter(body)
        for r in src.get('rungs') or []:
            w.rung(r)
        if vendor_data:
            ad = _sub(pou, 'addData')
            d = _sub(ad, 'data', name=VENDOR, handleUnknown='discard')
            x = ET.SubElement(d, '{%s}ld' % VENDOR)
            x.text = json.dumps(src, ensure_ascii=False)
    if program.get('name'):
        _xhtml(_sub(pou, 'documentation'), program['name'])
    inst = _sub(root, 'instances')
    cfgs = _sub(inst, 'configurations')
    cfg = _sub(cfgs, 'configuration', name='Config')
    res = _sub(cfg, 'resource', name='Resource')
    task = _sub(res, 'task', name='MainTask', interval=f"T#{int(program.get('scan_ms') or 20)}ms", priority=1)
    _sub(task, 'pouInstance', name='MainInst', typeName=pname)
    if io:
        gv = _sub(res, 'globalVars')
        for ent in io:
            _var(gv, {'name': ent.get('name'), 'type': ent.get('type') or 'BOOL', 'addr': ent.get('addr'),
                      'comment': ent.get('comment') or ent.get('desc') or (_tr('输入') if ent.get('dir') == 'in' else _tr('输出'))})
    ET.indent(root, '  ')
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode')


# ---------------------------------------------------------------- 导入
def _local(tag):
    return tag.split('}', 1)[-1]


def _find(el, *path):
    for p in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == p), None)
    return el


def _children(el, name=None):
    return [c for c in (el if el is not None else []) if name is None or _local(c.tag) == name]


def _text_of(el):
    if el is None:
        return ''
    return ''.join(el.itertext())


def _type_text(t):
    if t is None or not len(t):
        return 'BOOL'
    c = t[0]
    nm = _local(c.tag)
    if nm == 'derived':
        return c.get('name', '').upper()
    if nm == 'array':
        dim = _find(c, 'dimension')
        bt = _find(c, 'baseType')
        return f"ARRAY[{dim.get('lower')}..{dim.get('upper')}] OF {_type_text(bt)}"
    if nm in ('string', 'wstring'):
        return 'STRING'
    return nm.upper()


def _vars_of(container, warn):
    out = []
    for g in container:
        tag = _local(g.tag)
        sec = {'localVars': 'VAR', 'inputVars': 'VAR_INPUT', 'outputVars': 'VAR_OUTPUT', 'inOutVars': 'VAR_IN_OUT', 'tempVars': 'VAR_TEMP',
               'globalVars': 'VAR_GLOBAL', 'externalVars': 'VAR_EXTERNAL'}.get(tag)
        if not sec:
            continue
        for v in _children(g, 'variable'):
            d = {'name': v.get('name'), 'type': _type_text(_find(v, 'type')), 'addr': v.get('address') or None,
                 'comment': _text_of(_find(v, 'documentation')).strip()}
            sv = _find(v, 'initialValue', 'simpleValue')
            if sv is not None:
                d['init'] = sv.get('value')
            if sec != 'VAR':
                d['section'] = sec
            if g.get('retain') == 'true':
                d['retain'] = True
            if g.get('constant') == 'true':
                d['constant'] = True
            try:
                parse_type(d['type'])
            except Exception:
                warn.append(_tr('变量 {name} 的类型 {type} 不支持，已跳过', name=d['name'], type=d['type']))
                continue
            out.append(d)
    return out


def _ld_from_graph(ld, warn):
    els = {}
    order = []
    for c in ld:
        lid = c.get('localId')
        if lid is not None:
            els[lid] = c
            order.append(lid)

    def ypos(e):
        p = _find(e, 'position')
        return float(p.get('y', 0)) if p is not None else 0.0

    def conns(cp):
        return [(c.get('refLocalId'), c.get('formalParameter')) for c in _children(cp, 'connection')] if cp is not None else []

    def power_in(e):
        k = _local(e.tag)
        if k in ('contact', 'coil', 'rightPowerRail'):
            return conns(_find(e, 'connectionPointIn'))
        if k == 'block':
            for v in _children(_find(e, 'inputVariables'), 'variable'):
                if _is_power_param(e, v.get('formalParameter')):
                    return conns(_find(v, 'connectionPointIn'))
        return []

    def block_inputs(e):
        out = {}
        for v in _children(_find(e, 'inputVariables'), 'variable'):
            fp = (v.get('formalParameter') or '').upper()
            if _is_power_param(e, fp):
                continue
            cs = conns(_find(v, 'connectionPointIn'))
            if cs:
                src = els.get(cs[0][0])
                if src is not None and _local(src.tag) == 'inVariable':
                    out[fp] = _text_of(_find(src, 'expression')).strip()
        return out

    def block_outputs(e):
        out = {}
        lid = e.get('localId')
        for o in els.values():
            if _local(o.tag) == 'outVariable':
                for rid, fp in conns(_find(o, 'connectionPointIn')):
                    if rid == lid and fp:
                        out[fp.upper()] = _text_of(_find(o, 'expression')).strip()
        return out

    memo = {}
    counter = [0]

    def to_el(e):
        k = _local(e.tag)
        counter[0] += 1
        eid = f'x{e.get("localId")}_{counter[0]}'
        if k == 'contact':
            neg = e.get('negated') == 'true'
            edge = e.get('edge') or 'none'
            t = 'P' if edge == 'rising' else 'N' if edge == 'falling' else 'NC' if neg else 'NO'
            return {'id': eid, 't': t, 'var': _text_of(_find(e, 'variable')).strip()}
        if k == 'coil':
            st_ = e.get('storage') or 'none'
            t = 'SET' if st_ == 'set' else 'RESET' if st_ == 'reset' else 'NCOIL' if e.get('negated') == 'true' else 'COIL'
            return {'id': eid, 't': t, 'var': _text_of(_find(e, 'variable')).strip()}
        if k == 'block':
            typ = (e.get('typeName') or '').upper()
            ins, outs = block_inputs(e), block_outputs(e)
            if typ in FB_DEFS:
                return {'id': eid, 't': 'FB', 'fb': typ, 'inst': e.get('instanceName') or '', 'in': ins, 'out': outs}
            if typ in ('GT', 'GE', 'EQ', 'NE', 'LT', 'LE'):
                return {'id': eid, 't': 'CMP', 'op': typ, 'a': ins.get('IN1', ''), 'b': ins.get('IN2', '')}
            if typ in ('ADD', 'SUB', 'MUL', 'DIV', 'MOD'):
                return {'id': eid, 't': 'MATH', 'op': typ, 'a': ins.get('IN1', ''), 'b': ins.get('IN2', ''), 'out': outs.get('OUT', '')}
            if typ == 'MOVE':
                return {'id': eid, 't': 'MOVE', 'in': ins.get('IN', ''), 'out': outs.get('OUT', '')}
            warn.append(_tr('梯形图里的功能块 {typ} 不支持，已跳过', typ=typ))
            return None
        return None

    def path_to(ref, depth=0):
        """到 ref 输出端为止的能流 → 串联列表。"""
        if depth > 200:
            raise ImportError_(_tr('梯形图连接有环'))
        e = els.get(ref)
        if e is None:
            return []
        k = _local(e.tag)
        if k == 'leftPowerRail':
            return []
        me = to_el(e)
        before = inputs_tree(power_in(e), depth + 1)
        return before + ([me] if me else [])

    def inputs_tree(cs, depth=0):
        refs = [r for r, _ in cs]
        if not refs:
            return []
        if len(refs) == 1:
            return path_to(refs[0], depth)
        branches = [path_to(r, depth) for r in refs]
        # 公共前缀不提取（等价），直接并联
        return [{'par': branches}]

    # 汇点：输出没有被任何元件（右母线除外）引用的线圈/盒子
    consumed = set()
    for e in els.values():
        if _local(e.tag) in ('contact', 'coil', 'block'):
            for r, _ in power_in(e):
                consumed.add(r)
    sinks = [lid for lid in order if _local(els[lid].tag) in ('coil', 'block') and lid not in consumed]
    groups = {}
    for lid in sinks:
        key = tuple(sorted(r for r, _ in power_in(els[lid])))
        groups.setdefault(key, []).append(lid)
    rungs = []
    for key, lids in groups.items():
        e0 = els[lids[0]]
        pre = inputs_tree(power_in(e0))
        tails = []
        for lid in lids:
            me = to_el(els[lid])
            if me:
                tails.append(me)
        if not tails:
            continue
        elements = pre + (tails if len(tails) == 1 else [{'par': [[t] for t in tails]}])
        rungs.append({'y': min(ypos(els[l]) for l in lids), 'comment': '', 'elements': elements})
    rungs.sort(key=lambda r: r['y'])
    comments = sorted(((ypos(e), _text_of(_find(e, 'content')).strip()) for e in els.values() if _local(e.tag) == 'comment'))
    for cy, text in comments:
        nxt = next((r for r in rungs if r['y'] >= cy and not r['comment']), None)
        if nxt:
            nxt['comment'] = text
    for r in rungs:
        r.pop('y')
    return {'rungs': rungs}


def _is_power_param(block, fp):
    fp = (fp or '').upper()
    typ = (block.get('typeName') or '').upper()
    if typ in FB_DEFS:
        return fp == FB_DEFS[typ]['pin']
    return fp == 'EN'


def import_xml(text):
    """→ (program, io_globals, warnings)。"""
    warn = []
    try:
        root = ET.fromstring(text.encode('utf-8') if isinstance(text, str) else text)
    except ET.ParseError as e:
        raise ImportError_(_tr('不是合法的 XML：{e}', e=e))
    if _local(root.tag) != 'project':
        raise ImportError_(_tr('不是 PLCopen XML（根元素应该是 project）'))
    pous = _find(root, 'types', 'pous')
    progs = [p for p in _children(pous, 'pou') if (p.get('pouType') or '') == 'program']
    if not progs:
        raise ImportError_(_tr('文件里没有程序（pouType="program" 的 POU）'))
    others = [p.get('name') for p in _children(pous, 'pou') if p not in progs]
    if others:
        warn.append(_tr('用户自定义的功能块/函数暂不支持，已忽略：{join}', join=_tr('、').join(others)))
    if len(progs) > 1:
        warn.append(_tr('文件里有 {len} 个程序，只导入第一个 {get}', len=len(progs), get=progs[0].get("name")))
    pou = progs[0]
    itf = _find(pou, 'interface')
    vars_ = _vars_of(itf if itf is not None else [], warn)
    body = _find(pou, 'body')
    lang = None
    source = None
    if body is not None and len(body):
        b = body[0]
        k = _local(b.tag)
        if k == 'ST':
            xh = next(iter(b), None)
            lang, source = 'ST', _text_of(xh) if xh is not None else (b.text or '')
        elif k == 'LD':
            lang = 'LD'
            vd = None
            for d in pou.iter():
                if _local(d.tag) == 'data' and d.get('name') == VENDOR and len(d):
                    vd = d[0].text
            if vd:
                source = json.loads(vd)
            else:
                source = _ld_from_graph(b, warn)
        else:
            raise ImportError_(_tr('暂不支持 {k} 语言（支持 LD、ST）', k=k))
    if lang is None:
        raise ImportError_(_tr('程序没有内容'))
    io_globals = []
    for gv in root.iter(N + 'globalVars'):
        io_globals += _vars_of([gv], warn)
    interval = None
    for t in root.iter(N + 'task'):
        interval = t.get('interval')
    prog = {'id': 'main', 'name': _text_of(_find(pou, 'documentation')).strip() or pou.get('name') or _tr('导入的程序'), 'lang': lang,
            'vars': vars_, 'source': source}
    if interval:
        from .st import parse_time
        ms = parse_time(interval)
        if ms:
            prog['scan_ms'] = int(ms)
    return prog, io_globals, warn


__all__ = ['export_xml', 'import_xml', 'ImportError_', 'fmt_time', 'tname']
