"""梯形图（LD）：JSON 串并联树 → 与 ST 相同的中间表示。

格式：{"rungs": [{"comment": "启停自锁", "elements": [ …串联… ]}]}
元素（"t" 字段）：
  NO / NC            常开 / 常闭触点            {"t":"NO","var":"Start"}
  P / N              上升沿 / 下降沿触点         {"t":"P","var":"Btn"}
  COIL / NCOIL       线圈 / 取反线圈             {"t":"COIL","var":"Motor"}
  SET / RESET        置位 / 复位线圈             {"t":"SET","var":"Lamp"}
  FB                 功能块盒子（TON/TOF/TP/CTU/CTD/CTUD/R_TRIG/F_TRIG/SR/RS）
                     {"t":"FB","fb":"TON","inst":"T1","in":{"PT":"T#2s"},"out":{"ET":"Elapsed"}}
                     左侧能流接第一个布尔输入（IN / CU / CD / CLK / S1 / S），右侧送出 Q（或 Q1 / QU）
  CMP                比较盒子 {"t":"CMP","op":">=","a":"C1.CV","b":"10"}（op：> >= = <> < <= 或 GT GE EQ NE LT LE）
  MATH               算术盒子 {"t":"MATH","op":"ADD","a":"x","b":"1","out":"x"}（ADD SUB MUL DIV MOD），有能流才执行，ENO=EN
  MOVE               传送 {"t":"MOVE","in":"10","out":"x"}
分支：{"par": [分支1, 分支2, …]}（每个分支是元素列表），串联：{"ser": [ … ]} 或直接写列表。
每个元素可带 "id"（界面高亮用）；没有就按位置编号 r<梯级>e<序号>，并写回元素。
操作数都是 ST 表达式（变量名、地址 %IX0.0、T1.ET、常量、x + 1 …）。
"""
from ..i18n import _tr
from . import st
from .compiler import (STMT, CompileError, compile_expr, compile_fb_call, compile_target, check_assign, tname)
from .fb import FB_DEFS

CONTACTS = {'NO', 'NC', 'P', 'N'}
COILS = {'COIL', 'NCOIL', 'SET', 'RESET'}
CMP_OPS = {'GT': '>', 'GE': '>=', 'EQ': '=', 'NE': '<>', 'LT': '<', 'LE': '<=', '>': '>', '>=': '>=', '=': '=', '==': '=', '<>': '<>',
           '!=': '<>', '<': '<', '<=': '<='}
MATH_OPS = {'ADD': '+', 'SUB': '-', 'MUL': '*', 'DIV': '/', 'MOD': 'MOD', '+': '+', '-': '-', '*': '*', '/': '/'}
TYPES_CN = {'NO': '常开触点', 'NC': '常闭触点', 'P': '上升沿触点', 'N': '下降沿触点', 'COIL': '线圈', 'NCOIL': '取反线圈', 'SET': '置位线圈',
            'RESET': '复位线圈', 'FB': '功能块', 'CMP': '比较', 'MATH': '运算', 'MOVE': '传送'}


ALIASES = {'CONTACT': 'NO', 'CONTACT_NO': 'NO', 'CONTACT_NC': 'NC', 'RISING': 'P', 'FALLING': 'N', 'OUT': 'COIL', 'S': 'SET', 'R': 'RESET'}


def norm_t(t):
    """元素类型规整。手写 YAML 里不加引号的 NO 会被读成布尔 False，这里按常开触点处理（下降沿请写 'N' 或 FALLING）。"""
    if t is False:
        return 'NO'
    t = str(t or '').strip().upper()
    return ALIASES.get(t, t)


def iter_elements(tree):
    """遍历所有元素（dict，含 t 字段）。"""
    if isinstance(tree, list):
        for x in tree:
            yield from iter_elements(x)
    elif isinstance(tree, dict):
        if 'par' in tree:
            if isinstance(tree['par'], list):
                for b in tree['par']:
                    yield from iter_elements(b)
        elif 'ser' in tree:
            yield from iter_elements(tree['ser'])
        else:
            yield tree


def fb_instances(source):
    """梯形图里用到的功能块实例：{实例名: 类型}（编译前自动声明用）。"""
    out = {}
    rungs = source.get('rungs') if isinstance(source, dict) else None
    for r in rungs if isinstance(rungs, list) else []:
        if not isinstance(r, dict):
            continue
        for el in iter_elements(r.get('elements', [])):
            if norm_t(el.get('t')) == 'FB' and el.get('inst') and el.get('fb'):
                out.setdefault(str(el['inst']), str(el['fb']).upper())
    return out


class _LdCompiler:
    def __init__(self, ctx, ri):
        self.ctx, self.ri = ctx, ri
        self.n = 0
        self.outputs = 0

    def err(self, msg, el):
        raise CompileError(msg, 0, 0, rung=self.ri, elem=el.get('id'))

    def expr(self, text, el, what):
        if text is None or str(text).strip() == '':
            self.err(_tr('{get}缺少{what}', get=TYPES_CN.get(el.get("t"), "元素"), what=what), el)
        try:
            return st.parse_expr(text)
        except st.StError as e:
            self.err(_tr('{what}“{text}”写法不对：{msg}', what=what, text=text, msg=e.msg), el)

    def node(self, x):
        if isinstance(x, list):
            fs = tuple(self.node(y) for y in x)

            def ser(m, pin, fs=fs):
                for f in fs:
                    pin = f(m, pin)
                return pin
            return ser
        if not isinstance(x, dict):
            raise CompileError(_tr('梯形图结构不对：元素应该是对象或列表'), 0, 0, rung=self.ri)
        if 'par' in x:
            if not isinstance(x['par'], list):
                raise CompileError(_tr('梯形图结构不对：并联分支 par 应该是分支列表'), 0, 0, rung=self.ri)
            bs = tuple(self.node(b if isinstance(b, list) else [b]) for b in x['par'])
            if not bs:
                return lambda m, pin: pin

            def par(m, pin, bs=bs):
                out = False
                for f in bs:
                    if f(m, pin):
                        out = True
                return out
            return par
        if 'ser' in x:
            if not isinstance(x['ser'], list):
                raise CompileError(_tr('梯形图结构不对：串联 ser 应该是元件列表'), 0, 0, rung=self.ri)
            return self.node(list(x['ser']))
        return self.element(x)

    def element(self, el):
        t = norm_t(el.get('t'))
        el['t'] = t
        if not el.get('id'):
            el['id'] = f'r{self.ri}e{self.n}'
        self.n += 1
        eid = el['id']
        ctx = self.ctx
        ctx.loc = {'rung': self.ri, 'elem': eid}
        try:
            return self._element(el, t, eid, ctx)
        except CompileError as e:
            if 'rung' not in e.extra:
                e.extra.update(rung=self.ri, elem=eid)
            raise

    def _element(self, el, t, eid, ctx):
        if t in CONTACTS:
            g, gt = compile_expr(self.expr(el.get('var'), el, _tr('变量')), ctx)
            if gt != 'BOOL':
                self.err(_tr('触点 {get} 应该是布尔量，这里是 {tname}（数值比较用“比较”盒子）', get=el.get("var"), tname=tname(gt)), el)
            if t == 'NO':
                def f(m, pin, g=g, eid=eid):
                    c = g(m)
                    po = pin and c
                    m.ld[eid] = (pin, po, c)
                    return po
            elif t == 'NC':
                def f(m, pin, g=g, eid=eid):
                    c = not g(m)
                    po = pin and c
                    m.ld[eid] = (pin, po, c)
                    return po
            elif t == 'P':
                def f(m, pin, g=g, eid=eid):
                    v = g(m)
                    c = v and not m.edge.get(eid, False)
                    m.edge[eid] = v
                    po = pin and c
                    m.ld[eid] = (pin, po, c)
                    return po
            else:
                def f(m, pin, g=g, eid=eid):
                    v = g(m)
                    c = m.edge.get(eid, False) and not v
                    m.edge[eid] = v
                    po = pin and c
                    m.ld[eid] = (pin, po, c)
                    return po
            return f
        if t in COILS:
            self.outputs += 1
            tgt = self.expr(el.get('var'), el, _tr('变量'))
            ctx.wkind = {'SET': 'S', 'RESET': 'RS'}.get(t, 'W')
            try:
                sf, tt = compile_target(tgt, ctx)
            finally:
                ctx.wkind = 'W'
            ctx.noref = True
            try:
                gf, _ = compile_expr(tgt, ctx)
            finally:
                ctx.noref = False
            if tt != 'BOOL':
                self.err(_tr('线圈 {get} 应该是布尔量，这里是 {tname}（数值赋值用“传送”或“运算”盒子）', get=el.get("var"), tname=tname(tt)), el)
            if t == 'COIL':
                def f(m, pin, sf=sf, eid=eid):
                    sf(m, pin)
                    m.ld[eid] = (pin, pin, pin)
                    return pin
            elif t == 'NCOIL':
                def f(m, pin, sf=sf, eid=eid):
                    sf(m, not pin)
                    m.ld[eid] = (pin, pin, not pin)
                    return pin
            elif t == 'SET':
                def f(m, pin, sf=sf, gf=gf, eid=eid):
                    if pin:
                        sf(m, True)
                    m.ld[eid] = (pin, pin, gf(m))
                    return pin
            else:
                def f(m, pin, sf=sf, gf=gf, eid=eid):
                    if pin:
                        sf(m, False)
                    m.ld[eid] = (pin, pin, gf(m))
                    return pin
            return f
        if t == 'FB':
            self.outputs += 1
            typ = str(el.get('fb', '')).upper()
            if typ not in FB_DEFS:
                self.err(_tr('不认识的功能块 {get}（可用：{join}）', get=el.get("fb"), join=_tr('、').join(FB_DEFS)), el)
            inst = str(el.get('inst') or '').strip()
            if not inst:
                self.err(_tr('{typ} 功能块缺少实例名（例如 T1）', typ=typ), el)
            s = ctx.lookup(inst)
            if s.type != typ:
                self.err(_tr('{inst} 的类型是 {tname}，不是 {typ}', inst=inst, tname=tname(s.type), typ=typ), el)
            d = FB_DEFS[typ]
            pin_name, pout_name = d['pin'], d['pout']
            ins = [(pin_name, ((lambda m: m.p), 'BOOL'))]
            for k, v in (el.get('in') or {}).items():
                k = str(k).upper()
                if k == pin_name or v is None or str(v).strip() == '':
                    continue
                ins.append((k, self.expr(v, el, _tr('参数 {k}', k=k))))
            outs = []
            for k, v in (el.get('out') or {}).items():
                if v is None or str(v).strip() == '':
                    continue
                outs.append((str(k).upper(), self.expr(v, el, _tr('输出 {k}', k=k))))
            call = compile_fb_call(inst, ins, outs, ctx, None)
            key = s.key

            def f(m, pin, call=call, key=key, po_=pout_name, eid=eid):
                m.p = pin
                call(m)
                po = bool(m.v[key].f[po_])
                m.ld[eid] = (pin, po, po)
                return po
            return f
        if t == 'CMP':
            op = CMP_OPS.get(str(el.get('op', '')).upper())
            if not op:
                self.err(_tr('比较盒子的运算符不对：{get}（可用：> >= = <> < <=）', get=el.get("op")), el)
            node = st.Bin(op, self.expr(el.get('a'), el, _tr('左边操作数')), self.expr(el.get('b'), el, _tr('右边操作数')))
            g, _ = compile_expr(node, ctx)

            def f(m, pin, g=g, eid=eid):
                c = g(m)
                po = pin and c
                m.ld[eid] = (pin, po, c)
                return po
            return f
        if t in ('MATH', 'MOVE'):
            self.outputs += 1
            if t == 'MATH':
                op = MATH_OPS.get(str(el.get('op', '')).upper())
                if not op:
                    self.err(_tr('运算盒子的运算符不对：{get}（可用：ADD SUB MUL DIV MOD）', get=el.get("op")), el)
                vnode = st.Bin(op, self.expr(el.get('a'), el, _tr('操作数 A')), self.expr(el.get('b'), el, _tr('操作数 B')))
            else:
                vnode = self.expr(el.get('in'), el, _tr('输入值'))
            vf, vt = compile_expr(vnode, ctx)
            sf, tt = compile_target(self.expr(el.get('out'), el, _tr('输出变量')), ctx)
            check_assign(tt, vt, ctx, None)

            def f(m, pin, vf=vf, sf=sf, eid=eid):
                if pin:
                    sf(m, vf(m))
                m.ld[eid] = (pin, pin, pin)
                return pin
            return f
        self.err(_tr('不认识的梯形图元素类型：{get}', get=el.get("t")), el)


def compile_ld(source, ctx, emit):
    """把每个梯级编成一条 STMT 指令（行号 = 梯级序号 + 1）。返回梯级数。"""
    rungs = source.get('rungs') if isinstance(source, dict) else None
    if not isinstance(rungs, list):
        if source:
            ctx.errors.append({'rung': 0, 'msg': _tr('梯形图格式不对：应该是 {"rungs": [梯级, …]}')})
        return 0
    for ri, r in enumerate(rungs):
        c = _LdCompiler(ctx, ri)
        try:
            if not isinstance(r, dict) or not isinstance(r.get('elements') or [], list):
                raise CompileError(_tr('梯级 {v} 格式不对：应该是 {{"comment": …, "elements": [元件, …]}}', v=ri + 1), 0, 0, rung=ri)
            els = r.get('elements') or []
            if not els:
                emit(STMT, (lambda m, ri=ri: _set_rung(m, ri, False)), None, None, ri + 1)
                continue
            f = c.node(list(els))
            if not c.outputs:
                ctx.warnings.append({'rung': ri, 'msg': _tr('梯级 {v} 没有线圈或功能块，不会产生任何输出', v=ri + 1)})

            def rung(m, f=f, ri=ri):
                _set_rung(m, ri, f(m, True))
            emit(STMT, rung, None, None, ri + 1)
        except CompileError as e:
            d = {'rung': ri, 'msg': e.msg}
            if e.extra.get('elem'):
                d['elem'] = e.extra['elem']
            ctx.errors.append(d)
        finally:
            ctx.loc = {}
    return len(rungs)


def _set_rung(m, ri, v):
    r = m.rungs
    if len(r) <= ri:
        r.extend([False] * (ri + 1 - len(r)))
    r[ri] = v
