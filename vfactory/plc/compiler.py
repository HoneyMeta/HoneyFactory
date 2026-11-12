"""编译器：ST / LD 程序 → 中间表示（指令表 + Python 闭包）。

不使用 exec / eval：每个表达式编译成一个闭包 fn(m)，m 是 PLC 内存（Mem）；闭包只捕获编译期常量和子闭包，
所以同一份编译结果可以被多个内存副本共享（工厂 deepcopy 时安全）。

指令表（每条是一个元组 (op, a, b, c, 行号)）：
  STMT  a=fn(m)                       一条语句（赋值、功能块调用、梯形图的一个梯级）
  JF    a=cond(m), b=目标             条件为假就跳转
  J     b=目标                        无条件跳转
  CASE  a=sel(m), b=[(lo,hi,目标)], c=ELSE 目标
  RET                                 结束本次扫描
行号：ST 是源程序行号；LD 是 梯级序号+1（断点、单步按这个停）。0 表示不能停。
"""
from ..i18n import _tr
import difflib
import math

from . import st
from .fb import FB_DEFS, FUNC_CN, MATH1, FBInst, _round_half_away

STMT, JF, J, CASE, RET = range(5)
WATCHDOG = 200000            # 一次扫描最多执行的指令数，超过视为死循环

INT_RANGE = {'SINT': (-128, 127), 'INT': (-32768, 32767), 'DINT': (-2 ** 31, 2 ** 31 - 1), 'LINT': (-2 ** 63, 2 ** 63 - 1),
             'USINT': (0, 255), 'UINT': (0, 65535), 'UDINT': (0, 2 ** 32 - 1), 'ULINT': (0, 2 ** 64 - 1),
             'BYTE': (0, 255), 'WORD': (0, 65535), 'DWORD': (0, 2 ** 32 - 1), 'LWORD': (0, 2 ** 64 - 1)}
REALS = {'REAL', 'LREAL'}
BITSTR = {'BYTE', 'WORD', 'DWORD', 'LWORD'}
ELEMENTARY = set(INT_RANGE) | REALS | {'BOOL', 'TIME', 'STRING'}
TYPE_CN = {'BOOL': '布尔', 'INT': '整数', 'DINT': '双整数', 'REAL': '实数', 'TIME': '时间'}


class PlcError(Exception):
    """运行时错误（除数为零、下标越界、看门狗…）。"""
    def __init__(self, msg, line=0):
        super().__init__(msg)
        self.msg, self.line = msg, line


class CompileError(Exception):
    def __init__(self, msg, line=0, col=0, **extra):
        super().__init__(msg)
        self.msg, self.line, self.col, self.extra = msg, line, col, extra


def is_int(t):
    return t in INT_RANGE or t == 'ANY_INT'


def is_real(t):
    return t in REALS or t == 'ANY_REAL'


def is_num(t):
    return is_int(t) or is_real(t)


def tname(t):
    if isinstance(t, tuple):
        return f'ARRAY[{t[1]}..{t[2]}] OF {tname(t[3])}'
    return {'ANY_INT': _tr('整数常量'), 'ANY_REAL': _tr('实数常量')}.get(t, t)


def wrapper(t):
    """把一个值规整成类型 t 的取值（整数按位宽回绕，和真实 PLC 一样溢出）。"""
    if t == 'BOOL':
        return bool
    if t in INT_RANGE:
        lo, hi = INT_RANGE[t]
        span = hi - lo + 1

        def w(v, lo=lo, hi=hi, span=span):
            v = int(v)
            if lo <= v <= hi:
                return v
            return (v - lo) % span + lo
        return w
    if t in REALS:
        return float
    if t == 'TIME':
        def wt(v):
            v = int(v)
            return v if -2 ** 31 <= v < 2 ** 31 else (v + 2 ** 31) % 2 ** 32 - 2 ** 31
        return wt
    if t == 'STRING':
        return str
    return lambda v: v


def zero(t):
    if isinstance(t, tuple):
        return [zero(t[3]) for _ in range(t[2] - t[1] + 1)]
    if t in FB_DEFS:
        return FBInst(t)
    return False if t == 'BOOL' else 0.0 if t in REALS else '' if t == 'STRING' else 0


def type_sig(t):
    return tname(t)


# ---------------------------------------------------------------- 内存
class Mem:
    """PLC 内存：变量值、时钟（微秒）、梯形图元件通断和沿记忆。可 deepcopy。"""
    def __init__(self):
        self.v = {}
        self.now = 0
        self.ld = {}          # 元件编号 → (左侧能流, 右侧能流, 触点闭合/条件)
        self.edge = {}        # 沿触点的上一次值
        self.rungs = []       # 每个梯级末端能流


class Sym:
    __slots__ = ('name', 'key', 'type', 'addr', 'section', 'constant', 'retain', 'init', 'comment', 'io', 'line', 'implicit')

    def __init__(self, name, key, typ, addr=None, section='VAR', constant=False, retain=False, init=None, comment='', io=None, line=0,
                 implicit=False):
        self.name, self.key, self.type, self.addr, self.section = name, key, typ, addr, section
        self.constant, self.retain, self.init, self.comment, self.io, self.line = constant, retain, init, comment, io, line
        self.implicit = implicit


def addr_type(addr):
    na = st.norm_addr(addr)
    if not na:
        return None
    return {'X': 'BOOL', 'B': 'BYTE', 'W': 'INT', 'D': 'DINT', 'L': 'LINT'}[na[2]]


# ---------------------------------------------------------------- 编译上下文
class Ctx:
    def __init__(self, io=None):
        self.syms: dict[str, Sym] = {}         # 大写名 → 符号
        self.addr_syms: dict[str, Sym] = {}    # 地址 → 符号
        self.errors, self.warnings = [], []
        self.io = io or []
        self.loc = {}                          # 当前位置附加信息（梯形图：rung / elem）
        self.used_addrs = {}
        self.xref = {}                         # 交叉引用：变量名 → [{k: R 读 / W 写 / S 置位 / R 复位 / C 调用, line|rung, elem, f}]
        self.wkind = 'W'                       # compile_target 记录的写入种类（梯形图置位/复位线圈临时改成 S / RS）
        self.noref = False

    def ref(self, name, kind, node=None, field=None):
        if self.noref or not name:
            return
        if self.loc.get('rung') is not None:
            d = {'k': kind, 'rung': self.loc['rung'], 'elem': self.loc.get('elem')}
        else:
            d = {'k': kind, 'line': getattr(node, 'line', 0) or 0}
        if field:
            d['f'] = field
        lst = self.xref.setdefault(name, [])
        if d not in lst:
            lst.append(d)

    # -- 报错
    def error(self, msg, node=None, line=0, col=0, **kw):
        line = getattr(node, 'line', line) if node is not None else line
        col = getattr(node, 'col', col) if node is not None else col
        raise CompileError(msg, line, col, **kw)

    def warn(self, msg, node=None, line=0):
        d = {'line': getattr(node, 'line', line) if node is not None else line, 'msg': msg}
        d.update(self.loc)
        self.warnings.append(d)

    # -- 符号
    def declare(self, sym: Sym, node=None):
        up = sym.name.upper()
        if up in self.syms and not self.syms[up].implicit:
            prev = self.syms[up]
            if prev.io is not None and sym.io is None:
                # 程序里重新声明了 I/O 表里的同名变量：以程序为准，但地址类型必须一致
                if sym.addr and sym.addr != prev.addr:
                    self.warn(_tr('变量 {name} 在 I/O 表里是 {addr}，程序里声明成了 {addr2}，按程序的地址', name=sym.name, addr=prev.addr, addr2=sym.addr))
            else:
                self.error(_tr('变量 {name} 重复声明', name=sym.name) + (_tr('（第 {line} 行已经声明过）', line=prev.line) if prev.line else ''), node)
        if sym.addr:
            other = self.addr_syms.get(sym.addr)
            if other and other.name.upper() != up and other.io is None and sym.io is None:
                self.warn(_tr('地址 {addr} 同时给了 {name} 和 {name2}，两个名字指向同一个存储单元', addr=sym.addr, name=other.name, name2=sym.name))
            self.addr_syms[sym.addr] = sym
        self.syms[up] = sym

    def lookup(self, name, node=None):
        s = self.syms.get(name.upper())
        if s is None:
            cands = difflib.get_close_matches(name.upper(), list(self.syms), n=1, cutoff=0.6)
            hint = _tr('，是不是 {name}？', name=self.syms[cands[0]].name) if cands else _tr('，请先在变量表里声明')
            self.error(_tr('没有声明变量 {name}{hint}', name=name, hint=hint), node)
        return s

    def addr_sym(self, addr):
        s = self.addr_syms.get(addr)
        if s:
            return s
        t = addr_type(addr)
        s = Sym(addr, addr, t, addr=addr, implicit=True)
        self.addr_syms[addr] = s
        return s


def parse_type(text, ctx=None, node=None):
    """'BOOL' / 'TON' / 'ARRAY[0..9] OF INT' → 类型（字符串或元组）。"""
    if isinstance(text, st.Node):
        tr = text
    else:
        s = str(text or '').strip()
        if not s:
            raise CompileError(_tr('缺少数据类型'), getattr(node, 'line', 0))
        try:
            p = st.Parser(s)
            tr = p.type_ref()
            if not p.is_('EOF'):
                raise st.StError(_tr('类型写法不对'))
        except st.StError:
            raise CompileError(_tr('不认识的数据类型：{s}', s=s), getattr(node, 'line', 0))
    return _type_of_ref(tr)


def _type_of_ref(tr):
    if tr.name == 'ARRAY':
        e = _type_of_ref(tr.elem)
        if e in FB_DEFS:
            raise CompileError(_tr('暂不支持功能块数组'), tr.line, tr.col)
        if tr.hi < tr.lo:
            raise CompileError(_tr('数组上界小于下界'), tr.line, tr.col)
        if tr.hi - tr.lo > 10000:
            raise CompileError(_tr('数组太大（最多 10001 个元素）'), tr.line, tr.col)
        return ('ARRAY', tr.lo, tr.hi, e)
    n = tr.name.upper()
    if n in ELEMENTARY or n in FB_DEFS:
        return n
    cands = difflib.get_close_matches(n, list(ELEMENTARY | set(FB_DEFS)), n=1, cutoff=0.6)
    raise CompileError(_tr('不认识的数据类型：{name}', name=tr.name) + (_tr('，是不是 {v}？', v=cands[0]) if cands else _tr('（可用：BOOL、INT、DINT、REAL、TIME、TON、TOF、TP、CTU、CTD…）')),
                       tr.line, tr.col)


# ---------------------------------------------------------------- 类型运算
def unify(a, b, ctx, node, what='运算'):
    if a == b:
        return a
    if a == 'ANY_INT' and is_num(b):
        return b
    if b == 'ANY_INT' and is_num(a):
        return a
    if a == 'ANY_REAL' and is_num(b):
        return b if is_real(b) else 'REAL'
    if b == 'ANY_REAL' and is_num(a):
        return a if is_real(a) else 'REAL'
    if is_int(a) and is_int(b):
        ra, rb = INT_RANGE[a], INT_RANGE[b]
        if ra[0] <= rb[0] and ra[1] >= rb[1]:
            return a
        if rb[0] <= ra[0] and rb[1] >= ra[1]:
            return b
        return 'LINT' if 'LINT' in (a, b) or 'ULINT' in (a, b) or 'UDINT' in (a, b) or 'DWORD' in (a, b) else 'DINT'
    if is_num(a) and is_num(b):
        return 'LREAL' if 'LREAL' in (a, b) else 'REAL'
    ctx.error(_tr('{what}两边类型不一致：{tname} 和 {tname2}', what=what, tname=tname(a), tname2=tname(b)), node)


def check_assign(target_t, value_t, ctx, node, what='赋值'):
    """能否把 value_t 赋给 target_t；不行就报错，可能丢精度就警告。"""
    if target_t == value_t:
        return
    if isinstance(target_t, tuple) or isinstance(value_t, tuple):
        if isinstance(target_t, tuple) and isinstance(value_t, tuple) and target_t[3] == value_t[3] and target_t[2] - target_t[1] == value_t[2] - value_t[1]:
            return
        ctx.error(_tr('{what}类型不匹配：不能把 {tname} 赋给 {tname2}', what=what, tname=tname(value_t), tname2=tname(target_t)), node)
    if target_t in FB_DEFS or value_t in FB_DEFS:
        ctx.error(_tr('功能块实例不能直接赋值（{tname} → {tname2}）', tname=tname(value_t), tname2=tname(target_t)), node)
    if value_t == 'ANY_INT' and (is_num(target_t)):
        return
    if value_t == 'ANY_INT' and target_t == 'TIME':
        ctx.error(_tr('{what}类型不匹配：时间要写成 T#2s 这种格式，或者用 DINT_TO_TIME(...)', what=what), node)
    if value_t == 'ANY_REAL' and is_real(target_t):
        return
    if is_int(value_t) and is_int(target_t):
        rv, rt = INT_RANGE.get(value_t, (0, 0)), INT_RANGE[target_t]
        if rv[0] < rt[0] or rv[1] > rt[1]:
            ctx.warn(_tr('把 {tname} 赋给 {tname2} 可能溢出（隐式转换）', tname=tname(value_t), tname2=tname(target_t)), node)
        return
    if is_int(value_t) and is_real(target_t):
        return
    if is_real(value_t) and is_real(target_t):
        return
    if is_real(value_t) and is_int(target_t):
        ctx.error(_tr('{what}类型不匹配：不能把 {tname} 赋给 {tname2}（会丢掉小数），请用 REAL_TO_{v}(...)', what=what, tname=tname(value_t), tname2=tname(target_t), v=target_t if target_t != "ANY_INT" else "INT"), node)
    if value_t == 'BOOL' or target_t == 'BOOL':
        ctx.error(_tr('{what}类型不匹配：不能把 {tname} 赋给 {tname2}', what=what, tname=tname(value_t), tname2=tname(target_t)) +
                  (_tr('（布尔量转数值用 BOOL_TO_INT(...)）') if value_t == 'BOOL' else _tr('（数值转布尔可以写成 x <> 0）')), node)
    if value_t == 'TIME' or target_t == 'TIME':
        ctx.error(_tr('{what}类型不匹配：不能把 {tname} 赋给 {tname2}（时间和数值互转用 TIME_TO_DINT / DINT_TO_TIME）', what=what, tname=tname(value_t), tname2=tname(target_t)), node)
    ctx.error(_tr('{what}类型不匹配：不能把 {tname} 赋给 {tname2}', what=what, tname=tname(value_t), tname2=tname(target_t)), node)


def concrete(t):
    return {'ANY_INT': 'DINT', 'ANY_REAL': 'REAL'}.get(t, t)


def _idiv(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _imod(a, b):
    return a - _idiv(a, b) * b


# ---------------------------------------------------------------- 表达式
def compile_expr(e, ctx: Ctx):
    """→ (fn(m) -> 值, 类型)"""
    if isinstance(e, st.Num):
        v = e.value
        k = e.kind
        if k == 'INT':
            return (lambda m, v=v: v), 'ANY_INT'
        if k == 'REAL':
            return (lambda m, v=v: v), 'ANY_REAL'
        if k == 'BOOL':
            return (lambda m, v=v: v), 'BOOL'
        if k == 'TIME':
            iv = int(round(v))
            return (lambda m, v=iv: v), 'TIME'
        if k in INT_RANGE or k in REALS:             # 带类型的常量 WORD#16#FF
            tv = wrapper(k)(v)
            return (lambda m, v=tv: v), k
        return (lambda m, v=v: v), 'STRING'
    if isinstance(e, st.Name):
        s = ctx.lookup(e.name, e)
        if s.type in FB_DEFS:
            ctx.error(_tr('{name} 是功能块实例，要读它的输出，例如 {name}.{pout}', name=s.name, pout=FB_DEFS[s.type]["pout"]), e)
        ctx.ref(s.name, 'R', e)
        key = s.key
        return (lambda m, k=key: m.v[k]), s.type
    if isinstance(e, st.Addr):
        s = ctx.addr_sym(e.addr)
        ctx.used_addrs[e.addr] = s.type
        ctx.ref(s.name, 'R', e)
        key = s.key
        return (lambda m, k=key: m.v[k]), s.type
    if isinstance(e, st.Member):
        return _member(e, ctx)
    if isinstance(e, st.Index):
        return _index(e, ctx)
    if isinstance(e, st.Unary):
        f, t = compile_expr(e.e, ctx)
        if e.op == 'NOT':
            if t == 'BOOL':
                return (lambda m, f=f: not f(m)), 'BOOL'
            if t in BITSTR or is_int(t):
                w = wrapper(concrete(t))
                return (lambda m, f=f, w=w: w(~f(m))), t
            ctx.error(_tr('NOT 只能用于布尔量或整数，这里是 {tname}', tname=tname(t)), e)
        if not (is_num(t) or t == 'TIME'):
            ctx.error(_tr('负号只能用于数值，这里是 {tname}', tname=tname(t)), e)
        w = wrapper(concrete(t))
        return (lambda m, f=f, w=w: w(-f(m))), t
    if isinstance(e, st.Bin):
        return _binop(e, ctx)
    if isinstance(e, st.Call):
        return _call(e, ctx)
    ctx.error(_tr('无法编译的表达式'), e)


def _member(e, ctx):
    base = e.base
    if isinstance(base, st.Name):
        s = ctx.lookup(base.name, base)
        if s.type in FB_DEFS:
            d = FB_DEFS[s.type]
            fld = e.field
            ft = d['out'].get(fld) or d['in'].get(fld)
            if not ft:
                ctx.error(_tr('{type} 没有成员 {fld}（可用：{join}）', type=s.type, fld=fld, join=_tr('、').join(list(d["in"]) + list(d["out"]))), e)
            ctx.ref(s.name, 'R', e, fld)
            key = s.key
            return (lambda m, k=key, f=fld: m.v[k].f[f]), ft
    bf, bt = compile_expr(base, ctx)
    if e.field.isdigit() and (is_int(bt)):
        bit = int(e.field)
        lo, hi = INT_RANGE.get(bt, (0, 0))
        if bit >= (hi - lo + 1).bit_length() - 1:
            ctx.error(_tr('{tname} 没有第 {bit} 位', tname=tname(bt), bit=bit), e)
        return (lambda m, bf=bf, b=bit: bool((bf(m) >> b) & 1)), 'BOOL'
    ctx.error(_tr('“.{field}”只能用在功能块实例上（例如 T1.Q）或整数取位（例如 w.3）', field=e.field), e)


def _index(e, ctx):
    bf, bt = compile_expr(e.base, ctx) if not isinstance(e.base, st.Name) else _arr_ref(e.base, ctx)
    if not isinstance(bt, tuple):
        ctx.error(_tr('{getattr} 不是数组，不能用下标', getattr=getattr(e.base, "name", "")), e)
    xf, xt = compile_expr(e.index, ctx)
    if not is_int(xt):
        ctx.error(_tr('数组下标必须是整数，这里是 {tname}', tname=tname(xt)), e.index)
    lo, hi = bt[1], bt[2]
    nm = getattr(e.base, 'name', _tr('数组'))

    def get(m, bf=bf, xf=xf, lo=lo, hi=hi, nm=nm):
        i = xf(m)
        if i < lo or i > hi:
            raise PlcError(_tr('数组下标越界：{nm}[{i}]（范围 {lo}..{hi}）', nm=nm, i=i, lo=lo, hi=hi))
        return bf(m)[i - lo]
    return get, bt[3]


def _arr_ref(name_node, ctx):
    s = ctx.lookup(name_node.name, name_node)
    ctx.ref(s.name, 'R', name_node)
    key = s.key
    return (lambda m, k=key: m.v[k]), s.type


_CMP = {'=': lambda a, b: a == b, '<>': lambda a, b: a != b, '<': lambda a, b: a < b, '>': lambda a, b: a > b,
        '<=': lambda a, b: a <= b, '>=': lambda a, b: a >= b}


def _binop(e, ctx):
    op = e.op
    fa, ta = compile_expr(e.a, ctx)
    fb_, tb = compile_expr(e.b, ctx)
    if op in ('AND', 'OR', 'XOR'):
        if ta == 'BOOL' and tb == 'BOOL':
            if op == 'AND':
                return (lambda m, a=fa, b=fb_: bool(a(m) and b(m))), 'BOOL'      # 短路求值不影响结果（表达式无副作用）
            if op == 'OR':
                return (lambda m, a=fa, b=fb_: bool(a(m) or b(m))), 'BOOL'
            return (lambda m, a=fa, b=fb_: a(m) != b(m)), 'BOOL'
        if is_int(ta) and is_int(tb):
            t = unify(ta, tb, ctx, e)
            w = wrapper(concrete(t))
            f = {'AND': lambda x, y: x & y, 'OR': lambda x, y: x | y, 'XOR': lambda x, y: x ^ y}[op]
            return (lambda m, a=fa, b=fb_, f=f, w=w: w(f(a(m), b(m)))), t
        ctx.error(_tr('{op} 两边应该都是布尔量（或都是整数），这里是 {tname} 和 {tname2}', op=op, tname=tname(ta), tname2=tname(tb)), e)
    if op in _CMP:
        if ta == 'BOOL' and tb == 'BOOL' and op in ('=', '<>'):
            pass
        elif ta == 'TIME' and tb == 'TIME' or ta == 'STRING' and tb == 'STRING':
            pass
        elif is_num(ta) and is_num(tb):
            unify(ta, tb, ctx, e, _tr('比较'))
        else:
            hint = _tr('（时间要和 T#… 比较，例如 T1.ET >= T#2s）') if 'TIME' in (ta, tb) else ''
            ctx.error(_tr('不能比较 {tname} 和 {tname2}{hint}', tname=tname(ta), tname2=tname(tb), hint=hint), e)
        c = _CMP[op]
        return (lambda m, a=fa, b=fb_, c=c: c(a(m), b(m))), 'BOOL'
    # 算术
    if 'BOOL' in (ta, tb):
        ctx.error(_tr('布尔量不能做算术运算“{op}”（逻辑运算用 AND / OR / NOT）', op=op), e)
    if ta == 'TIME' or tb == 'TIME':
        if op in ('+', '-') and ta == tb == 'TIME':
            t = 'TIME'
        elif op in ('*', '/') and ta == 'TIME' and is_num(tb):
            t = 'TIME'
        elif op == '*' and tb == 'TIME' and is_num(ta):
            t = 'TIME'
        else:
            ctx.error(_tr('时间不能和 {tname} 做“{op}”运算', tname=tname(tb if ta == "TIME" else ta), op=op), e)
        w = wrapper('TIME')
        if op == '+':
            return (lambda m, a=fa, b=fb_, w=w: w(a(m) + b(m))), t
        if op == '-':
            return (lambda m, a=fa, b=fb_, w=w: w(a(m) - b(m))), t
        if op == '*':
            return (lambda m, a=fa, b=fb_, w=w: w(round(a(m) * b(m)))), t

        def tdiv(m, a=fa, b=fb_, w=w):
            y = b(m)
            if y == 0:
                raise PlcError(_tr('除数为零'))
            return w(int(a(m) / y))
        return tdiv, t
    if not (is_num(ta) and is_num(tb)):
        ctx.error(_tr('“{op}”两边应该是数值，这里是 {tname} 和 {tname2}', op=op, tname=tname(ta), tname2=tname(tb)), e)
    t = unify(ta, tb, ctx, e)
    real = is_real(t)
    w = wrapper(concrete(t))
    if op == '+':
        return (lambda m, a=fa, b=fb_, w=w: w(a(m) + b(m))), t
    if op == '-':
        return (lambda m, a=fa, b=fb_, w=w: w(a(m) - b(m))), t
    if op == '*':
        return (lambda m, a=fa, b=fb_, w=w: w(a(m) * b(m))), t
    if op == '/':
        if real:
            def rdiv(m, a=fa, b=fb_):
                y = b(m)
                if y == 0:
                    raise PlcError(_tr('除数为零'))
                return a(m) / y
            return rdiv, t

        def idiv(m, a=fa, b=fb_, w=w):
            y = b(m)
            if y == 0:
                raise PlcError(_tr('除数为零'))
            return w(_idiv(a(m), y))
        return idiv, t
    if op == 'MOD':
        if real:
            ctx.error(_tr('MOD 只能用于整数'), e)

        def imod(m, a=fa, b=fb_, w=w):
            y = b(m)
            if y == 0:
                raise PlcError(_tr('MOD 的除数为零'))
            return w(_imod(a(m), y))
        return imod, t
    if op == '**':
        def pw(m, a=fa, b=fb_):
            try:
                return float(a(m)) ** float(b(m))
            except (OverflowError, ZeroDivisionError, ValueError):
                raise PlcError(_tr('乘方运算溢出或无意义'))
        return pw, 'REAL'
    ctx.error(_tr('不支持的运算符 {op}', op=op), e)


_CONV_TYPES = set(INT_RANGE) | REALS | {'BOOL', 'TIME', 'STRING'}


def _conv(src_t, dst_t, ctx, node):
    """类型转换函数 X_TO_Y 的实现。"""
    w = wrapper(dst_t)
    if dst_t == 'BOOL':
        return lambda v: bool(v)
    if dst_t == 'STRING':
        return lambda v: ('TRUE' if v else 'FALSE') if isinstance(v, bool) else str(v)
    if src_t == 'STRING':
        def fs(v, w=w, real=dst_t in REALS):
            try:
                return w(float(v) if real else int(float(v)))
            except ValueError:
                return w(0)
        return fs
    if is_real(src_t) and (dst_t in INT_RANGE or dst_t == 'TIME'):
        return lambda v, w=w: w(_round_half_away(v))
    if dst_t in REALS:
        return lambda v: float(v)
    return lambda v, w=w: w(int(v))


def _call(e, ctx):
    name = e.name
    args = [compile_expr(a, ctx) for a in e.args]
    named = {k: compile_expr(v, ctx) for k, v in e.named}
    if name == '__ARRAY__':
        ctx.error(_tr('数组初值只能用在变量声明里'), e)
    if name in FB_DEFS:
        ctx.error(_tr('{name} 是功能块类型，要先声明实例（例如 T1 : {name};），再调用 T1(…)', name=name), e)
    # 类型转换 X_TO_Y / TO_Y
    if '_TO_' in name or name.startswith('TO_'):
        if name.startswith('TO_'):
            src, dst = None, name[3:]
        else:
            src, dst = name.split('_TO_', 1)
        if dst in _CONV_TYPES and (src is None or src in _CONV_TYPES) and len(args) == 1 and not named:
            f, t = args[0]
            if src and src != concrete(t) and not (t == 'ANY_INT' and is_int(src) or t == 'ANY_REAL' and is_real(src)) \
                    and not (is_int(src) and is_int(t)) and not (is_real(src) and is_real(t)):
                ctx.error(_tr('{name} 的参数应该是 {src}，这里是 {tname}', name=name, src=src, tname=tname(t)), e)
            c = _conv(src or concrete(t), dst, ctx, e)
            return (lambda m, f=f, c=c: c(f(m))), dst
    if named:
        order = {'LIMIT': ['MN', 'IN', 'MX'], 'SEL': ['G', 'IN0', 'IN1']}.get(name)
        if not order or set(named) - set(order):
            ctx.error(_tr('函数 {name} 不支持按名称传参', name=name), e)
        args = args + [named[k] for k in order[len(args):] if k in named]

    def need(n, lo=None):
        if (lo is None and len(args) != n) or (lo is not None and len(args) < lo):
            ctx.error(_tr('{name}（{get}）需要 {v} 个参数，这里给了 {len} 个', name=name, get=FUNC_CN.get(name, ""), v=n if lo is None else _tr('至少 {lo}', lo=lo), len=len(args)), e)

    if name == 'ABS':
        need(1)
        f, t = args[0]
        if not is_num(t):
            ctx.error(_tr('ABS 的参数应该是数值'), e)
        w = wrapper(concrete(t))
        return (lambda m, f=f, w=w: w(abs(f(m)))), t
    if name in ('MIN', 'MAX'):
        need(0, 2)
        t = args[0][1]
        for _, tt in args[1:]:
            t = unify(t, tt, ctx, e, name) if t != tt else t
        if t == 'BOOL':
            ctx.error(_tr('{name} 的参数应该是数值或时间', name=name), e)
        fs = tuple(f for f, _ in args)
        g = min if name == 'MIN' else max
        return (lambda m, fs=fs, g=g: g(f(m) for f in fs)), t
    if name == 'LIMIT':
        need(3)
        (fmn, a), (fin, b), (fmx, c) = args
        t = unify(unify(a, b, ctx, e, 'LIMIT') if a != b else a, c, ctx, e, 'LIMIT') if not (a == b == c) else a
        return (lambda m, lo=fmn, x=fin, hi=fmx: min(max(x(m), lo(m)), hi(m))), t
    if name == 'SEL':
        need(3)
        (fg, tg), (f0, t0), (f1, t1) = args
        if tg != 'BOOL':
            ctx.error(_tr('SEL 的第一个参数应该是布尔量'), e)
        t = unify(t0, t1, ctx, e, 'SEL') if t0 != t1 else t0
        return (lambda m, g=fg, a=f0, b=f1: b(m) if g(m) else a(m)), t
    if name == 'MUX':
        need(0, 2)
        fk, tk = args[0]
        if not is_int(tk):
            ctx.error(_tr('MUX 的第一个参数应该是整数'), e)
        t = args[1][1]
        for _, tt in args[2:]:
            t = unify(t, tt, ctx, e, 'MUX') if t != tt else t
        fs = tuple(f for f, _ in args[1:])

        def mux(m, k=fk, fs=fs):
            i = k(m)
            if i < 0 or i >= len(fs):
                raise PlcError(_tr('MUX 选择号 {i} 超出范围 0..{v}', i=i, v=len(fs) - 1))
            return fs[i](m)
        return mux, t
    if name in MATH1:
        need(1)
        f, t = args[0]
        if not is_num(t):
            ctx.error(_tr('{name} 的参数应该是数值', name=name), e)
        g = MATH1[name]

        def mf(m, f=f, g=g, nm=name):
            try:
                return float(g(float(f(m))))
            except (ValueError, OverflowError):
                raise PlcError(_tr('{nm} 的参数超出定义域', nm=nm))
        return mf, 'REAL'
    if name == 'EXPT':
        need(2)
        (fa, ta), (fb_, tb) = args

        def ex(m, a=fa, b=fb_):
            try:
                return float(a(m)) ** float(b(m))
            except (OverflowError, ZeroDivisionError, ValueError):
                raise PlcError(_tr('EXPT 溢出或无意义'))
        return ex, 'REAL'
    if name == 'TRUNC':
        need(1)
        f, t = args[0]
        return (lambda m, f=f, w=wrapper('DINT'): w(math.trunc(f(m)))), 'DINT'
    if name in ('SHL', 'SHR', 'ROL', 'ROR'):
        need(2)
        (fi, ti), (fn, tn) = args
        if not is_int(ti) or not is_int(tn):
            ctx.error(_tr('{name} 的参数应该是整数（位串）', name=name), e)
        t = concrete(ti)
        bits = (INT_RANGE[t][1] - INT_RANGE[t][0] + 1).bit_length() - 1
        mask = (1 << bits) - 1
        w = wrapper(t)

        def sh(m, fi=fi, fn=fn, op=name, bits=bits, mask=mask, w=w):
            x, n = fi(m) & mask, fn(m) % (bits if op in ('ROL', 'ROR') else 10 ** 6)
            if op == 'SHL':
                r = (x << n) & mask
            elif op == 'SHR':
                r = x >> n
            elif op == 'ROL':
                r = ((x << n) | (x >> (bits - n))) & mask
            else:
                r = ((x >> n) | (x << (bits - n))) & mask
            return w(r)
        return sh, ti
    if name == 'MOVE':
        need(1)
        return args[0]
    cands = difflib.get_close_matches(name, list(FUNC_CN) + list(FB_DEFS), n=1, cutoff=0.6)
    ctx.error(_tr('不认识的函数 {name}', name=name) + (_tr('，是不是 {v}？', v=cands[0]) if cands else ''), e)


def const_value(e, ctx, typ):
    """声明里的初值：必须是常量表达式；按类型 typ 规整。"""
    if isinstance(e, st.Call) and e.name == '__ARRAY__':
        if not isinstance(typ, tuple):
            ctx.error(_tr('只有数组才能用 [ … ] 初值'), e)
        n = typ[2] - typ[1] + 1
        vals = []
        for x in e.args:
            if isinstance(x, tuple) and x[0] == 'rep':
                cnt = const_value(x[1], ctx, 'DINT')
                v = const_value(x[2], ctx, typ[3])
                vals += [v] * int(cnt)
            else:
                vals.append(const_value(x, ctx, typ[3]))
        if len(vals) > n:
            ctx.error(_tr('数组初值有 {len} 个，超过数组长度 {n}', len=len(vals), n=n), e)
        z = zero(typ)
        z[:len(vals)] = vals
        return z
    if isinstance(typ, tuple):
        ctx.error(_tr('数组初值写成 [1, 2, 3]'), e)
    if typ in FB_DEFS:
        ctx.error(_tr('功能块实例不能写初值'), e)
    sub = Ctx()
    sub.syms = {k: s for k, s in ctx.syms.items() if s.constant}
    f, t = compile_expr(e, sub)
    check_assign(typ, t, ctx, e, _tr('初值'))
    m = Mem()
    for s in sub.syms.values():
        m.v[s.key] = s.init if s.init is not None else zero(s.type)
    try:
        return wrapper(typ)(f(m))
    except PlcError as ex:
        ctx.error(_tr('初值计算出错：') + ex.msg, e)


# ---------------------------------------------------------------- 赋值目标
def compile_target(e, ctx, allow_fb_input=True):
    """→ (setter(m, v), 类型)。v 在 setter 里按目标类型规整。"""
    if isinstance(e, st.Name):
        s = ctx.lookup(e.name, e)
        if s.constant:
            ctx.error(_tr('{name} 是常量（CONSTANT），不能赋值', name=s.name), e)
        if s.type in FB_DEFS:
            ctx.error(_tr('{name} 是功能块实例，不能直接赋值；调用写成 {name}(…);', name=s.name), e)
        if isinstance(s.type, tuple):
            key = s.key

            def sa(m, v, k=key):
                m.v[k] = list(v)
            return sa, s.type
        if s.io and s.io.get('dir') == 'in':
            ctx.warn(_tr('给输入 {name}（{addr}）赋值：下一个扫描周期开始时会被现场信号覆盖', name=s.name, addr=s.addr), e)
        ctx.ref(s.name, ctx.wkind, e)
        w = wrapper(s.type)
        key = s.key

        def setv(m, v, k=key, w=w):
            m.v[k] = w(v)
        return setv, s.type
    if isinstance(e, st.Addr):
        s = ctx.addr_sym(e.addr)
        ctx.used_addrs[e.addr] = s.type
        ctx.ref(s.name, ctx.wkind, e)
        w = wrapper(s.type)
        key = s.key

        def seta(m, v, k=key, w=w):
            m.v[k] = w(v)
        return seta, s.type
    if isinstance(e, st.Member) and isinstance(e.base, st.Name):
        s = ctx.lookup(e.base.name, e.base)
        if s.type in FB_DEFS:
            d = FB_DEFS[s.type]
            if e.field in d['out']:
                ctx.error(_tr('{name}.{field} 是功能块输出，只能读不能写', name=s.name, field=e.field), e)
            if e.field not in d['in']:
                ctx.error(_tr('{type} 没有输入 {field}', type=s.type, field=e.field), e)
            ft = d['in'][e.field]
            ctx.ref(s.name, 'W', e, e.field)
            w = wrapper(ft)
            key = s.key

            def setf(m, v, k=key, f=e.field, w=w):
                m.v[k].f[f] = w(v)
            return setf, ft
    if isinstance(e, st.Member) and e.field.isdigit():
        gf, gt = compile_expr(e.base, ctx)
        sf, _ = compile_target(e.base, ctx)
        if not is_int(gt):
            ctx.error(_tr('只能给整数变量的某一位赋值'), e)
        bit = int(e.field)

        def setbit(m, v, gf=gf, sf=sf, b=bit):
            x = gf(m)
            sf(m, (x | (1 << b)) if v else (x & ~(1 << b)))
        return setbit, 'BOOL'
    if isinstance(e, st.Index):
        if not isinstance(e.base, st.Name):
            ctx.error(_tr('只支持一维数组'), e)
        s = ctx.lookup(e.base.name, e.base)
        if not isinstance(s.type, tuple):
            ctx.error(_tr('{name} 不是数组，不能用下标', name=s.name), e)
        if s.constant:
            ctx.error(_tr('{name} 是常量，不能赋值', name=s.name), e)
        xf, xt = compile_expr(e.index, ctx)
        if not is_int(xt):
            ctx.error(_tr('数组下标必须是整数'), e.index)
        lo, hi, et = s.type[1], s.type[2], s.type[3]
        ctx.ref(s.name, 'W', e)
        w = wrapper(et)
        key = s.key

        def seti(m, v, k=key, xf=xf, lo=lo, hi=hi, w=w, nm=s.name):
            i = xf(m)
            if i < lo or i > hi:
                raise PlcError(_tr('数组下标越界：{nm}[{i}]（范围 {lo}..{hi}）', nm=nm, i=i, lo=lo, hi=hi))
            m.v[k][i - lo] = w(v)
        return seti, et
    ctx.error(_tr('赋值号左边应该是变量'), e)


# ---------------------------------------------------------------- 功能块调用
def compile_fb_call(inst_name, inputs, outputs, ctx, node, power=None):
    """inputs [(参数, 表达式节点 或 (fn, 类型))]，outputs [(参数, 目标节点)]。返回 fn(m)。"""
    s = ctx.lookup(inst_name, node)
    ctx.ref(s.name, 'C', node)
    if s.type not in FB_DEFS:
        ctx.error(_tr('{name} 不是功能块实例（类型是 {tname}），不能调用', name=s.name, tname=tname(s.type)), node)
    d = FB_DEFS[s.type]
    sets = []
    for pn, ex, *pos in inputs:
        if pn not in d['in']:
            if pn in d['out']:
                ctx.error(_tr('{pn} 是 {type} 的输出，要写成 {pn}=>变量', pn=pn, type=s.type), node, *pos[:1])
            ctx.error(_tr('{type} 没有输入参数 {pn}（输入：{join}）', type=s.type, pn=pn, join=_tr('、').join(d["in"])), node)
        f, t = ex if isinstance(ex, tuple) else compile_expr(ex, ctx)
        check_assign(d['in'][pn], t, ctx, ex if not isinstance(ex, tuple) else node, _tr('参数 {pn} ', pn=pn))
        sets.append((pn, f, wrapper(d['in'][pn])))
    gets = []
    for pn, tg, *pos in outputs:
        if pn not in d['out']:
            ctx.error(_tr('{type} 没有输出参数 {pn}（输出：{join}）', type=s.type, pn=pn, join=_tr('、').join(d["out"])), node)
        sf, tt = compile_target(tg, ctx)
        check_assign(tt, d['out'][pn], ctx, tg, _tr('输出 {pn} ', pn=pn))
        gets.append((pn, sf))
    run = d['run']
    key = s.key
    sets, gets = tuple(sets), tuple(gets)

    def call(m, k=key, sets=sets, gets=gets, run=run):
        inst = m.v[k]
        f = inst.f
        for pn, fn, w in sets:
            f[pn] = w(fn(m))
        run(f, m.now)
        for pn, sf in gets:
            sf(m, f[pn])
    return call


# ---------------------------------------------------------------- 语句 → 指令
class Emitter:
    def __init__(self, ctx):
        self.ctx = ctx
        self.code = []
        self.loops = []          # [(exit 补丁表, continue 补丁表)]

    def emit(self, *ins):
        self.code.append(list(ins))
        return len(self.code) - 1

    def here(self):
        return len(self.code)

    def stmts(self, ss):
        for s in ss:
            try:
                self.stmt(s)
            except CompileError as e:
                self.ctx.errors.append({'line': e.line, 'col': e.col, 'msg': e.msg, **e.extra})

    def stmt(self, s):
        ctx = self.ctx
        if isinstance(s, st.Assign):
            sf, tt = compile_target(s.target, ctx)
            vf, vt = compile_expr(s.value, ctx)
            check_assign(tt, vt, ctx, s.value)
            self.emit(STMT, (lambda m, sf=sf, vf=vf: sf(m, vf(m))), None, None, s.line)
        elif isinstance(s, st.FbCall):
            fn = compile_fb_call(s.inst.name, s.inputs, s.outputs, ctx, s.inst)
            self.emit(STMT, fn, None, None, s.line)
        elif isinstance(s, st.If):
            ends = []
            for cond, body in s.arms:
                cf, ct = compile_expr(cond, ctx)
                if ct != 'BOOL':
                    ctx.errors.append({'line': cond.line, 'col': cond.col, 'msg': _tr('IF 条件应该是布尔量，这里是 {tname}', tname=tname(ct))})
                jf = self.emit(JF, cf, None, None, cond.line or s.line)
                self.stmts(body)
                ends.append(self.emit(J, None, None, None, 0))
                self.code[jf][2] = self.here()
            self.stmts(s.else_)
            for j in ends:
                self.code[j][2] = self.here()
        elif isinstance(s, st.Case):
            sf, stt = compile_expr(s.sel, ctx)
            if not is_int(stt):
                ctx.error(_tr('CASE 的选择量应该是整数，这里是 {tname}', tname=tname(stt)), s.sel)
            ci = self.emit(CASE, sf, [], None, s.line)
            ends = []
            table = []
            for labels, body, ln in s.arms:
                start = self.here()
                for lo, hi in labels:
                    table.append((self._case_const(lo), self._case_const(hi), start))
                self.stmts(body)
                ends.append(self.emit(J, None, None, None, 0))
            self.code[ci][3] = self.here()
            self.stmts(s.else_)
            for j in ends:
                self.code[j][2] = self.here()
            self.code[ci][2] = table
        elif isinstance(s, st.For):
            vs = ctx.lookup(s.var.name, s.var)
            if not is_int(vs.type):
                ctx.error(_tr('FOR 循环变量 {name} 应该是整数', name=vs.name), s.var)
            sf, _ = compile_target(s.var, ctx)
            gf, _ = compile_expr(s.var, ctx)
            af, at = compile_expr(s.start, ctx)
            bf, bt = compile_expr(s.end, ctx)
            stf, stt = compile_expr(s.step, ctx) if s.step is not None else ((lambda m: 1), 'ANY_INT')
            for x, tt in ((s.start, at), (s.end, bt), (s.step, stt)):
                if not is_int(tt):
                    ctx.error(_tr('FOR 的起止值和步长应该是整数'), x)
            self.emit(STMT, (lambda m, sf=sf, af=af: sf(m, af(m))), None, None, s.line)
            top = self.emit(JF, (lambda m, g=gf, b=bf, st_=stf: (g(m) <= b(m)) if st_(m) >= 0 else (g(m) >= b(m))), None, None, 0)
            self.loops.append(([], []))
            self.stmts(s.body)
            exits, conts = self.loops.pop()
            inc = self.emit(STMT, (lambda m, sf=sf, g=gf, st_=stf: sf(m, g(m) + st_(m))), None, None, 0)
            self.emit(J, None, top, None, 0)
            self.code[top][2] = self.here()
            for j in exits:
                self.code[j][2] = self.here()
            for j in conts:
                self.code[j][2] = inc
        elif isinstance(s, st.While):
            cf, ct = compile_expr(s.cond, ctx)
            if ct != 'BOOL':
                ctx.error(_tr('WHILE 条件应该是布尔量'), s.cond)
            top = self.emit(JF, cf, None, None, s.line)
            self.loops.append(([], []))
            self.stmts(s.body)
            exits, conts = self.loops.pop()
            self.emit(J, None, top, None, 0)
            self.code[top][2] = self.here()
            for j in exits:
                self.code[j][2] = self.here()
            for j in conts:
                self.code[j][2] = top
        elif isinstance(s, st.Repeat):
            top = self.here()
            self.loops.append(([], []))
            self.stmts(s.body)
            exits, conts = self.loops.pop()
            cf, ct = compile_expr(s.cond, ctx)
            if ct != 'BOOL':
                ctx.error(_tr('UNTIL 条件应该是布尔量'), s.cond)
            chk = self.emit(JF, cf, top, None, s.cond.line)
            for j in exits:
                self.code[j][2] = self.here()
            for j in conts:
                self.code[j][2] = chk
        elif isinstance(s, (st.Exit, st.Continue)):
            if not self.loops:
                ctx.error(('EXIT' if isinstance(s, st.Exit) else 'CONTINUE') + _tr(' 只能用在循环里'), s)
            j = self.emit(J, None, None, None, s.line)
            self.loops[-1][0 if isinstance(s, st.Exit) else 1].append(j)
        elif isinstance(s, st.Return):
            self.emit(RET, None, None, None, s.line)
        else:
            ctx.error(_tr('无法编译的语句'), s)

    def _case_const(self, n):
        if isinstance(n, st.Num):
            return n.value
        s = self.ctx.lookup(n.name, n)
        if not s.constant or not is_int(s.type):
            self.ctx.error(_tr('CASE 标签 {name} 必须是整数常量', name=n.name), n)
        return s.init


def finalize(code):
    return tuple(tuple(i) for i in code)


# ---------------------------------------------------------------- 执行
def execute(code, m, pc, bps, stmt_mode=False, skip_first=False):
    """从 pc 开始执行；遇到断点（或单步模式下的下一条语句）返回 ('halt', pc)，执行完返回 ('done', 0)。"""
    n = len(code)
    count = 0
    skip = skip_first
    line = 0
    try:
        while pc < n:
            op, a, b, c, line = code[pc]
            if line:
                if not skip and (stmt_mode or line in bps):
                    return 'halt', pc
                skip = False
            count += 1
            if count > WATCHDOG:
                raise PlcError(_tr('看门狗超时：一次扫描执行了超过 {WATCHDOG} 条指令，可能是死循环', WATCHDOG=WATCHDOG))
            if op == STMT:
                a(m)
                pc += 1
            elif op == JF:
                pc = pc + 1 if a(m) else b
            elif op == J:
                pc = b
            elif op == CASE:
                v = a(m)
                for lo, hi, tgt in b:
                    if lo <= v <= hi:
                        pc = tgt
                        break
                else:
                    pc = c
            else:
                return 'done', 0
    except PlcError as e:
        e.line = e.line or line
        raise
    except RecursionError:
        raise PlcError(_tr('表达式嵌套太深'), line)
    except (TypeError, ValueError, OverflowError, KeyError, AttributeError, IndexError) as e:
        raise PlcError(_tr('运行错误：{e}', e=e), line)
    return 'done', 0
