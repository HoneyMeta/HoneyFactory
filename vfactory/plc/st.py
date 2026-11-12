"""结构化文本（IEC 61131-3 ST）词法和语法分析 → 抽象语法树。

支持：PROGRAM 头（可省略）、VAR / VAR_INPUT / VAR_OUTPUT / VAR_IN_OUT / VAR_GLOBAL / VAR_TEMP（可带 RETAIN / CONSTANT）、
变量声明（a, b : BOOL := TRUE;  x AT %IX0.0 : BOOL;  arr : ARRAY[0..9] OF INT;）、
赋值、IF/ELSIF/ELSE、CASE（含范围 1..5 和多值 1,2,3）、FOR/WHILE/REPEAT、EXIT/CONTINUE/RETURN、
功能块调用（命名参数 IN:=x，输出 Q=>y）、函数调用、成员 T1.Q、数组下标、直接地址 %IX0.0 / %I0.0 / %QW2 / %MD4、
注释 (* *)、/* */、//。所有节点带行列号，错误信息是中文。
"""
from ..i18n import _tr
import re

KEYWORDS = {
    'PROGRAM', 'END_PROGRAM', 'VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'VAR_IN_OUT', 'VAR_GLOBAL', 'VAR_TEMP', 'VAR_EXTERNAL', 'END_VAR',
    'RETAIN', 'NON_RETAIN', 'PERSISTENT', 'CONSTANT', 'AT', 'IF', 'THEN', 'ELSIF', 'ELSE', 'END_IF', 'CASE', 'OF', 'END_CASE',
    'FOR', 'TO', 'BY', 'DO', 'END_FOR', 'WHILE', 'END_WHILE', 'REPEAT', 'UNTIL', 'END_REPEAT', 'EXIT', 'CONTINUE', 'RETURN',
    'AND', 'OR', 'XOR', 'NOT', 'MOD', 'TRUE', 'FALSE', 'ARRAY',
}


class StError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__(msg)
        self.msg, self.line, self.col = msg, line, col

    def as_dict(self):
        return {'line': self.line, 'col': self.col, 'msg': self.msg}


# ---------------------------------------------------------------- 词法
class Tok:
    __slots__ = ('k', 'v', 'line', 'col', 'end')

    def __init__(self, k, v, line, col, end=0):
        self.k, self.v, self.line, self.col, self.end = k, v, line, col, end

    def __repr__(self):
        return f'{self.k}:{self.v!r}@{self.line}:{self.col}'


_TIME_RE = re.compile(r'(?i)(?:T|TIME|LT|LTIME)#(-?)((?:\d+(?:\.\d+)?(?:ms|d|h|m|s|us|ns)_?)+)')
_TIME_PART = re.compile(r'(?i)(\d+(?:\.\d+)?)(ms|us|ns|d|h|m|s)')
_UNIT_MS = {'d': 86400000, 'h': 3600000, 'm': 60000, 's': 1000, 'ms': 1, 'us': 0.001, 'ns': 0.000001}
_ADDR_RE = re.compile(r'(?i)%([IQM])([XBWDL]?)(\d+)(?:\.(\d+))?')
_TYPED_RE = re.compile(r'(?i)(BOOL|SINT|INT|DINT|LINT|USINT|UINT|UDINT|ULINT|BYTE|WORD|DWORD|LWORD|REAL|LREAL)#')
OPS = [':=', '=>', '<>', '<=', '>=', '**', '..', '=', '<', '>', '+', '-', '*', '/', '(', ')', '[', ']', ',', ';', ':', '.', '&']


def parse_time(text):
    """T#1h2m3s500ms → 毫秒（浮点）。不合法返回 None。"""
    m = _TIME_RE.fullmatch(text.strip())
    if not m:
        return None
    ms = 0.0
    for num, unit in _TIME_PART.findall(m.group(2)):
        ms += float(num) * _UNIT_MS[unit.lower()]
    return -ms if m.group(1) else ms


def fmt_time(ms):
    """毫秒 → T#1h2m3s500ms 这种写法（显示用）。"""
    ms = int(round(ms or 0))
    if ms == 0:
        return 'T#0ms'
    neg, ms = ms < 0, abs(ms)
    out = ''
    for u, k in (('d', 86400000), ('h', 3600000), ('m', 60000), ('s', 1000)):
        if ms >= k:
            out += f'{ms // k}{u}'
            ms %= k
    if ms:
        out += f'{ms}ms'
    return 'T#' + ('-' if neg else '') + out


def norm_addr(text):
    """%I0.0 → %IX0.0，%Q1.3 → %QX1.3，%IW2 → %IW2；返回 (规范写法, 区, 宽度, 字节/字号, 位号)，不合法返回 None。"""
    m = _ADDR_RE.fullmatch(text.strip())
    if not m:
        return None
    area, size, n, bit = m.group(1).upper(), (m.group(2) or '').upper(), int(m.group(3)), m.group(4)
    if not size:
        size = 'X' if bit is not None else 'W'
    if size == 'X':
        if bit is None:
            return None
        b = int(bit)
        if b > 7:
            return None
        return f'%{area}X{n}.{b}', area, 'X', n, b
    if bit is not None:
        return None
    return f'%{area}{size}{n}', area, size, n, None


def lex(src):
    """词法分析。对任何输入都只会抛 StError（意外错误也转成带行号的中文错误），不会让编译接口 500。"""
    st = {'line': 1}
    try:
        return _lex(src, st)
    except StError:
        raise
    except Exception as e:                    # noqa: BLE001
        raise StError(_tr('这一行有无法识别的内容（{v}），请检查拼写和符号', v=type(e).__name__), st['line'], 1)


def _lex(src, st):
    toks = []
    i, line, col0 = 0, 1, 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == '\n':
            line += 1
            st['line'] = line
            col0 = i + 1
            i += 1
            continue
        if c in ' \t\r﻿':
            i += 1
            continue
        col = i - col0 + 1
        if src.startswith('(*', i) or src.startswith('/*', i):
            # 注释可以嵌套（和 CODESYS 一样）：(* 外 (* 内 *) 外 *)
            opn, close = ('(*', '*)') if c == '(' else ('/*', '*/')
            depth, j = 1, i + 2
            while depth and j < n:
                if src.startswith(opn, j):
                    depth += 1
                    j += 2
                elif src.startswith(close, j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth:
                more = _tr('（注释里还套了注释，每个 {opn} 都要有对应的 {close}）', opn=opn, close=close) if depth > 1 else ''
                raise StError(_tr('注释没有结束：从这里开始的注释缺少 {close}{more}', close=close, more=more), line, col)
            j -= 2
            seg = src[i:j + 2]
            line += seg.count('\n')
            st['line'] = line
            if '\n' in seg:
                col0 = i + seg.rfind('\n') + 1
            i = j + 2
            continue
        if src.startswith('//', i):
            j = src.find('\n', i)
            i = n if j < 0 else j
            continue
        if c == "'" or c == '"':
            j = src.find(c, i + 1)
            if j < 0:
                raise StError(_tr('字符串没有结束'), line, col)
            toks.append(Tok('STR', src[i + 1:j], line, col, j + 1 - col0 + 1))
            i = j + 1
            continue
        if c == '%':
            m = re.compile(r'%[A-Za-z]+[\d.]*').match(src, i)
            txt = m.group(0) if m else '%'
            na = norm_addr(txt)
            if not na:
                raise StError(_tr('地址写法不对：{txt}（例：%IX0.0、%I0.0、%QX1.2、%MW10、%IW2）', txt=txt), line, col)
            toks.append(Tok('ADDR', na[0], line, col, col + len(txt)))
            i += len(txt)
            continue
        if not c.isascii():
            raise StError(_tr('不认识的字符“{c}”（中文和全角符号只能写在注释 (* … *) 或字符串里；全角括号、冒号、分号要改成半角）', c=c), line, col)
        if c.isalpha() or c == '_':
            m = re.compile(r'[A-Za-z_][A-Za-z0-9_]*').match(src, i)
            word = m.group(0)
            if src.startswith('#', i + len(word)):
                tm = _TIME_RE.match(src, i)
                if tm:
                    ms = parse_time(tm.group(0))
                    toks.append(Tok('TIME', ms, line, col, col + len(tm.group(0))))
                    i += len(tm.group(0))
                    continue
                tt = _TYPED_RE.match(src, i)
                if tt:                         # 带类型的常量 INT#5、WORD#16#FF、REAL#1.5、BOOL#1
                    toks.append(Tok('TPFX', tt.group(1).upper(), line, col, col + len(tt.group(0))))
                    i += len(tt.group(0))
                    continue
                raise StError(_tr('不认识的常量写法：{v}…（时间写法例：T#2s、T#500ms、T#1m30s）', v=src[i:i + len(word) + 6]), line, col)
            up = word.upper()
            toks.append(Tok('KW' if up in KEYWORDS else 'ID', up if up in KEYWORDS else word, line, col, col + len(word)))
            i += len(word)
            continue
        if c.isdigit():
            m = re.compile(r'(?i)(2|8|16)#([0-9A-F_]+)').match(src, i)
            if m:
                try:
                    iv = int(m.group(2).replace('_', ''), int(m.group(1)))
                except ValueError:
                    raise StError(_tr('{group} 进制常量 {group2} 里有不合法的数字', group=m.group(1), group2=m.group(0)), line, col)
                toks.append(Tok('INT', iv, line, col, col + len(m.group(0))))
                i += len(m.group(0))
                continue
            m = re.compile(r'(?i)\d[\d_]*(?:\.\d[\d_]*)?(?:E[+-]?\d+)?').match(src, i)
            txt = m.group(0)
            t = txt.replace('_', '')
            if re.search(r'[.Ee]', t):
                toks.append(Tok('REAL', float(t), line, col, col + len(txt)))
            else:
                toks.append(Tok('INT', int(t), line, col, col + len(txt)))
            i += len(txt)
            continue
        for op in OPS:
            if src.startswith(op, i):
                toks.append(Tok('OP', op, line, col, col + len(op)))
                i += len(op)
                break
        else:
            raise StError(_tr('不认识的字符：{c!r}', c=c), line, col)
    toks.append(Tok('EOF', None, line, (n - col0) + 1))
    return toks


# ---------------------------------------------------------------- 语法树
class Node:
    __slots__ = ('line', 'col')


def node(cls_name, *fields):
    def init(self, *args, line=0, col=0):
        for f, a in zip(fields, args):
            setattr(self, f, a)
        self.line, self.col = line, col

    def rep(self):
        return f"{cls_name}({', '.join(repr(getattr(self, f)) for f in fields)})"
    return type(cls_name, (Node,), {'__slots__': fields, '__init__': init, '__repr__': rep, 'fields': fields})


Num = node('Num', 'value', 'kind')               # kind: INT / REAL / BOOL / TIME / STR
Name = node('Name', 'name')
Addr = node('Addr', 'addr')
Member = node('Member', 'base', 'field')
Index = node('Index', 'base', 'index')
Unary = node('Unary', 'op', 'e')
Bin = node('Bin', 'op', 'a', 'b')
Call = node('Call', 'name', 'args', 'named')     # 函数：args 位置参数；named [(名, 表达式)]
Assign = node('Assign', 'target', 'value')
FbCall = node('FbCall', 'inst', 'inputs', 'outputs')   # inputs [(名, 表达式)]；outputs [(名, 目标)]
If = node('If', 'arms', 'else_')                 # arms [(条件, [语句])]
Case = node('Case', 'sel', 'arms', 'else_')      # arms [([(lo, hi)], [语句])]
For = node('For', 'var', 'start', 'end', 'step', 'body')
While = node('While', 'cond', 'body')
Repeat = node('Repeat', 'body', 'cond')
Exit = node('Exit')
Continue = node('Continue')
Return = node('Return')
TypeRef = node('TypeRef', 'name', 'lo', 'hi', 'elem')   # 数组：name='ARRAY'
VarDecl = node('VarDecl', 'name', 'type', 'addr', 'init', 'section', 'retain', 'constant', 'comment')


class Program:
    def __init__(self, name, decls, body):
        self.name, self.decls, self.body = name, decls, body


# ---------------------------------------------------------------- 语法分析
_PREC = [('OR',), ('XOR',), ('AND', '&'), ('=', '<>'), ('<', '>', '<=', '>='), ('+', '-'), ('*', '/', 'MOD'), ('**',)]
_SECTIONS = {'VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'VAR_IN_OUT', 'VAR_GLOBAL', 'VAR_TEMP', 'VAR_EXTERNAL'}
_END_OF = {'IF': ('ELSIF', 'ELSE', 'END_IF'), 'CASE': ('ELSE', 'END_CASE'), 'FOR': ('END_FOR',), 'WHILE': ('END_WHILE',),
           'REPEAT': ('UNTIL',)}
_KW_CN = {'END_IF': 'END_IF', 'THEN': 'THEN', 'DO': 'DO', 'OF': 'OF', 'END_VAR': 'END_VAR'}


class Parser:
    def __init__(self, src):
        self.src = src
        self.toks = lex(src)
        self.i = 0
        self.lines = src.split('\n')

    # -- 工具
    @property
    def t(self):
        return self.toks[self.i]

    def peek(self, k=1):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def is_(self, k, v=None):
        t = self.t
        return t.k == k and (v is None or t.v == v)

    def isop(self, v):
        return self.t.k == 'OP' and self.t.v == v

    def iskw(self, *v):
        return self.t.k == 'KW' and self.t.v in v

    def adv(self):
        t = self.t
        self.i += 1
        return t

    def desc(self, t):
        if t.k == 'EOF':
            return _tr('程序结尾')
        if t.k == 'OP':
            return f'“{t.v}”'
        if t.k == 'TIME':
            return f'“{fmt_time(t.v)}”'
        return f'“{t.v}”'

    def err(self, msg, t=None):
        t = t or self.t
        raise StError(msg, t.line, t.col)

    def expect_op(self, v, what=''):
        if not self.isop(v):
            prev = self.toks[self.i - 1] if self.i else self.t
            if v == ';':
                # 漏分号：报在上一个记号之后，和 CODESYS 一样指向行尾
                raise StError(_tr('缺少分号“;”') + (_tr('（{what}）', what=what) if what else ''), prev.line, prev.end or prev.col)
            self.err(_tr('这里应该是“{v}”', v=v) + (_tr('（{what}）', what=what) if what else '') + _tr('，实际是 {desc}', desc=self.desc(self.t)))
        return self.adv()

    def expect_kw(self, v, what=''):
        if not self.iskw(v):
            self.err(_tr('这里应该是 {v}', v=v) + (_tr('（{what}）', what=what) if what else '') + _tr('，实际是 {desc}', desc=self.desc(self.t)))
        return self.adv()

    def ident(self, what='名称'):
        if self.t.k != 'ID':
            if self.t.k == 'KW':
                self.err(_tr('“{v}”是关键字，不能用作{what}', v=self.t.v, what=what))
            self.err(_tr('这里应该是{what}，实际是 {desc}', what=what, desc=self.desc(self.t)))
        return self.adv()

    # -- 程序
    def program(self):
        name = 'Main'
        decls = []
        had_header = False
        if self.iskw('PROGRAM'):
            self.adv()
            name = self.ident(_tr('程序名')).v
            had_header = True
        while self.t.k == 'KW' and self.t.v in _SECTIONS:
            decls += self.var_block()
        body = self.stmts(('END_PROGRAM',) if had_header else ())
        if had_header:
            self.expect_kw('END_PROGRAM', _tr('程序结尾'))
        if not self.is_('EOF'):
            if self.t.k == 'KW' and self.t.v in _SECTIONS:
                self.err(_tr('变量声明（VAR … END_VAR）要写在程序最前面'))
            self.err(_tr('多余的 {desc}（是不是少了对应的开头，比如 IF / FOR / CASE？）', desc=self.desc(self.t)))
        return Program(name, decls, body)

    def var_block(self):
        sect = self.adv().v
        retain = constant = False
        while self.iskw('RETAIN', 'NON_RETAIN', 'PERSISTENT', 'CONSTANT'):
            w = self.adv().v
            retain = retain or w in ('RETAIN', 'PERSISTENT')
            constant = constant or w == 'CONSTANT'
        out = []
        while not self.iskw('END_VAR'):
            if self.is_('EOF'):
                self.err(_tr('变量声明没有结束：缺少 END_VAR'))
            first = self.ident(_tr('变量名'))
            names = [first]
            while self.isop(','):
                self.adv()
                names.append(self.ident(_tr('变量名')))
            addr = None
            if self.iskw('AT'):
                self.adv()
                if self.t.k != 'ADDR':
                    self.err(_tr('AT 后面应该是地址，例如 %IX0.0'))
                addr = self.adv().v
            self.expect_op(':', _tr('变量名后面写冒号和类型，例如 Start : BOOL;'))
            typ = self.type_ref()
            init = None
            if self.isop(':='):
                self.adv()
                init = self.init_value()
            line_no = first.line
            self.expect_op(';', _tr('每个变量声明以分号结束'))
            cm = self._trailing_comment(line_no)
            for nt in names:
                out.append(VarDecl(nt.v, typ, addr, init, sect, retain, constant, cm, line=nt.line, col=nt.col))
        self.expect_kw('END_VAR')
        if self.isop(';'):
            self.adv()
        return out

    def _trailing_comment(self, line_no):
        s = self.lines[line_no - 1] if 0 < line_no <= len(self.lines) else ''
        m = re.search(r'\(\*(.*?)\*\)|//(.*)$', s)
        return (m.group(1) or m.group(2) or '').strip() if m else ''

    def init_value(self):
        if self.isop('['):                     # 数组初值 [1, 2, 3] 或 [3(0)]
            t = self.adv()
            vals = []
            while not self.isop(']'):
                e = self.expr()
                if self.isop('('):
                    self.adv()
                    v = self.expr()
                    self.expect_op(')')
                    vals.append(('rep', e, v))
                else:
                    vals.append(e)
                if self.isop(','):
                    self.adv()
                elif not self.isop(']'):
                    self.err(_tr('数组初值写法：[1, 2, 3]'))
            self.adv()
            return Call('__ARRAY__', vals, [], line=t.line, col=t.col)
        return self.expr()

    def type_ref(self):
        t = self.t
        if self.iskw('ARRAY'):
            self.adv()
            self.expect_op('[')
            lo = self.signed_int()
            self.expect_op('..', _tr('数组范围写法：ARRAY[0..9] OF INT'))
            hi = self.signed_int()
            self.expect_op(']')
            self.expect_kw('OF')
            elem = self.type_ref()
            if elem.name == 'ARRAY':
                self.err(_tr('暂不支持多维数组'), t)
            return TypeRef('ARRAY', lo, hi, elem, line=t.line, col=t.col)
        if t.k != 'ID':
            self.err(_tr('这里应该是数据类型（BOOL、INT、REAL、TIME、TON…），实际是 {desc}', desc=self.desc(t)))
        self.adv()
        name = t.v.upper()
        if name == 'STRING' and self.isop('('):     # STRING(80)
            self.adv()
            while not self.isop(')') and not self.is_('EOF'):
                self.adv()
            self.adv()
        return TypeRef(name, None, None, None, line=t.line, col=t.col)

    def signed_int(self):
        neg = False
        if self.isop('-'):
            self.adv()
            neg = True
        if self.t.k != 'INT':
            self.err(_tr('这里应该是整数'))
        v = self.adv().v
        return -v if neg else v

    # -- 语句
    def stmts(self, stop):
        out = []
        while True:
            t = self.t
            if t.k == 'EOF' or (t.k == 'KW' and t.v in stop):
                return out
            if t.k == 'KW' and t.v in ('END_IF', 'END_FOR', 'END_WHILE', 'END_CASE', 'END_REPEAT', 'ELSIF', 'ELSE', 'UNTIL', 'END_PROGRAM'):
                if not stop:
                    self.err(_tr('多余的 {v}（前面没有对应的开头）', v=t.v))
                return out
            if self.isop(';'):
                self.adv()
                continue
            out.append(self.stmt())

    def stmt(self):
        t = self.t
        if t.k == 'KW':
            v = t.v
            if v == 'IF':
                return self.if_stmt()
            if v == 'CASE':
                return self.case_stmt()
            if v == 'FOR':
                return self.for_stmt()
            if v == 'WHILE':
                self.adv()
                c = self.expr()
                self.expect_kw('DO', _tr('WHILE 条件后面要写 DO'))
                body = self.stmts(('END_WHILE',))
                self.expect_kw('END_WHILE', _tr('WHILE 循环缺少 END_WHILE'))
                self._semi()
                return While(c, body, line=t.line, col=t.col)
            if v == 'REPEAT':
                self.adv()
                body = self.stmts(('UNTIL',))
                self.expect_kw('UNTIL', _tr('REPEAT 循环缺少 UNTIL'))
                c = self.expr()
                self.expect_kw('END_REPEAT', _tr('REPEAT 循环缺少 END_REPEAT'))
                self._semi()
                return Repeat(body, c, line=t.line, col=t.col)
            if v in ('EXIT', 'CONTINUE', 'RETURN'):
                self.adv()
                self.expect_op(';')
                return {'EXIT': Exit, 'CONTINUE': Continue, 'RETURN': Return}[v](line=t.line, col=t.col)
            if v in _SECTIONS:
                self.err(_tr('变量声明（VAR … END_VAR）要写在程序最前面'))
            self.err(_tr('语句不能以 {v} 开头', v=v))
        if t.k not in ('ID', 'ADDR'):
            self.err(_tr('语句不能以 {desc} 开头', desc=self.desc(t)))
        if t.k == 'ID' and self.peek().k == 'OP' and self.peek().v == '(':
            self.adv()
            return self.fb_call(Name(t.v, line=t.line, col=t.col), t)
        target = self.postfix(self.primary())
        if self.isop('('):
            self.err(_tr('只能调用功能块实例，例如 T1(IN:=Start, PT:=T#2s);'))
        if self.isop(':='):
            self.adv()
            if not isinstance(target, (Name, Addr, Member, Index)):
                self.err(_tr('赋值号左边应该是变量'), t)
            val = self.expr()
            self.expect_op(';', _tr('每条语句以分号结束'))
            return Assign(target, val, line=t.line, col=t.col)
        if self.isop('='):
            self.err(_tr('赋值要用“:=”，“=”是比较'))
        if isinstance(target, Name) and (self.t.k in ('ID', 'KW') and self.t.line == t.line):
            self.err(_tr('看不懂这条语句：{v} {desc}（赋值写成 x := …;）', v=t.v, desc=self.desc(self.t)))
        if isinstance(target, Name) and self.t.line != t.line:
            raise StError(_tr('缺少分号“;”或者赋值号“:=”'), t.line, t.end)
        self.err(_tr('这里应该是赋值号“:=”或者功能块调用“(”'), self.t)

    def _semi(self):
        if self.isop(';'):
            self.adv()

    def fb_call(self, target, t):
        self.adv()
        ins, outs = [], []
        while not self.isop(')'):
            if self.is_('EOF'):
                self.err(_tr('功能块调用缺少右括号“)”'))
            pn = self.ident(_tr('参数名（例如 IN、PT）'))
            if self.isop(':='):
                self.adv()
                ins.append((pn.v.upper(), self.expr(), pn.line, pn.col))
            elif self.isop('=>'):
                self.adv()
                tg = self.postfix(self.primary())
                if not isinstance(tg, (Name, Addr, Member, Index)):
                    self.err(_tr('“=>”右边应该是变量'))
                outs.append((pn.v.upper(), tg, pn.line, pn.col))
            else:
                self.err(_tr('功能块参数要写成 名称:=值（输入）或 名称=>变量（输出），例如 T1(IN:=Start, PT:=T#2s);'))
            if self.isop(','):
                self.adv()
            elif not self.isop(')'):
                self.err(_tr('参数之间用逗号分隔'))
        self.adv()
        self.expect_op(';', _tr('每条语句以分号结束'))
        return FbCall(target, ins, outs, line=t.line, col=t.col)

    def if_stmt(self):
        t = self.adv()
        arms = []
        c = self.expr()
        self.expect_kw('THEN', _tr('IF 条件后面要写 THEN'))
        arms.append((c, self.stmts(('ELSIF', 'ELSE', 'END_IF'))))
        else_ = []
        while True:
            if self.iskw('ELSIF'):
                self.adv()
                c = self.expr()
                self.expect_kw('THEN', _tr('ELSIF 条件后面要写 THEN'))
                arms.append((c, self.stmts(('ELSIF', 'ELSE', 'END_IF'))))
            elif self.iskw('ELSE'):
                self.adv()
                else_ = self.stmts(('END_IF',))
                if not self.iskw('END_IF'):
                    self.err(_tr('IF（第 {line} 行）缺少 END_IF', line=t.line))
            elif self.iskw('END_IF'):
                self.adv()
                self._semi()
                return If(arms, else_, line=t.line, col=t.col)
            else:
                self.err(_tr('IF（第 {line} 行）缺少 END_IF', line=t.line))

    def case_stmt(self):
        t = self.adv()
        sel = self.expr()
        self.expect_kw('OF', _tr('CASE 表达式后面要写 OF'))
        arms, else_ = [], []
        while True:
            if self.iskw('END_CASE'):
                self.adv()
                self._semi()
                return Case(sel, arms, else_, line=t.line, col=t.col)
            if self.iskw('ELSE'):
                self.adv()
                else_ = self.stmts(('END_CASE',))
                continue
            if self.is_('EOF'):
                self.err(_tr('CASE（第 {line} 行）缺少 END_CASE', line=t.line))
            labels = []
            lt = self.t
            while True:
                lo = self.case_label()
                hi = lo
                if self.isop('..'):
                    self.adv()
                    hi = self.case_label()
                labels.append((lo, hi))
                if self.isop(','):
                    self.adv()
                    continue
                break
            self.expect_op(':', _tr('CASE 分支写成 1: 语句;  或 2..5: 语句;'))
            body = self._case_body()
            arms.append((labels, body, lt.line))

    def _case_body(self):
        # 分支语句一直到下一个"标签:"、ELSE 或 END_CASE
        out = []
        while True:
            if self.iskw('END_CASE', 'ELSE') or self.is_('EOF'):
                return out
            if self._at_case_label():
                return out
            if self.isop(';'):
                self.adv()
                continue
            out.append(self.stmt())

    def _at_case_label(self):
        j = self.i
        toks = self.toks
        if toks[j].k == 'OP' and toks[j].v == '-':
            j += 1
        if toks[j].k not in ('INT', 'ID'):
            return False
        j += 1
        while True:
            tk = toks[j]
            if tk.k == 'OP' and tk.v == ':':
                return True
            if tk.k == 'OP' and tk.v in (',', '..', '-'):
                j += 1
                continue
            if tk.k in ('INT', 'ID'):
                j += 1
                continue
            return False

    def case_label(self):
        t = self.t
        neg = False
        if self.isop('-'):
            self.adv()
            neg = True
        if self.t.k == 'INT':
            v = self.adv().v
            return Num(-v if neg else v, 'INT', line=t.line, col=t.col)
        if self.t.k == 'ID' and not neg:
            n = self.adv()
            return Name(n.v, line=n.line, col=n.col)
        self.err(_tr('CASE 分支标签应该是整数常量'))

    def for_stmt(self):
        t = self.adv()
        v = self.ident(_tr('循环变量'))
        self.expect_op(':=', 'FOR i := 1 TO 10 DO')
        a = self.expr()
        self.expect_kw('TO', 'FOR i := 1 TO 10 DO')
        b = self.expr()
        step = None
        if self.iskw('BY'):
            self.adv()
            step = self.expr()
        self.expect_kw('DO', _tr('FOR 循环缺少 DO'))
        body = self.stmts(('END_FOR',))
        self.expect_kw('END_FOR', _tr('FOR（第 {line} 行）缺少 END_FOR', line=t.line))
        self._semi()
        return For(Name(v.v, line=v.line, col=v.col), a, b, step, body, line=t.line, col=t.col)

    # -- 表达式
    def expr(self, lvl=0):
        if lvl == len(_PREC):
            return self.unary()
        ops = _PREC[lvl]
        a = self.expr(lvl + 1)
        while (self.t.k == 'OP' and self.t.v in ops) or (self.t.k == 'KW' and self.t.v in ops):
            t = self.adv()
            op = 'AND' if t.v == '&' else t.v
            b = self.expr(lvl + 1) if op != '**' else self.expr(lvl)
            a = Bin(op, a, b, line=t.line, col=t.col)
        return a

    def unary(self):
        t = self.t
        if self.isop('-'):
            self.adv()
            e = self.unary()
            if isinstance(e, Num) and e.kind in ('INT', 'REAL', 'TIME'):
                return Num(-e.value, e.kind, line=t.line, col=t.col)
            return Unary('-', e, line=t.line, col=t.col)
        if self.isop('+'):
            self.adv()
            return self.unary()
        if self.iskw('NOT'):
            self.adv()
            return Unary('NOT', self.unary(), line=t.line, col=t.col)
        return self.postfix(self.primary())

    def primary(self):
        t = self.t
        if t.k in ('INT', 'REAL', 'TIME', 'STR'):
            self.adv()
            return Num(t.v, t.k, line=t.line, col=t.col)
        if t.k == 'TPFX':
            self.adv()
            neg = self.isop('-')
            if neg:
                self.adv()
            v = self.t
            if v.k not in ('INT', 'REAL') and not self.iskw('TRUE', 'FALSE'):
                self.err(_tr('{v}# 后面应该是常量', v=t.v))
            self.adv()
            val = (v.v == 'TRUE') if v.k == 'KW' else (-v.v if neg else v.v)
            if t.v == 'BOOL':
                val = bool(val)
            return Num(val, t.v, line=t.line, col=t.col)
        if self.iskw('TRUE', 'FALSE'):
            self.adv()
            return Num(t.v == 'TRUE', 'BOOL', line=t.line, col=t.col)
        if t.k == 'ADDR':
            self.adv()
            return Addr(t.v, line=t.line, col=t.col)
        if self.isop('('):
            self.adv()
            e = self.expr()
            self.expect_op(')', _tr('括号不配对'))
            return e
        if t.k == 'ID':
            self.adv()
            if self.isop('(') and self._looks_like_func_call():
                return self.func_call(t)
            return Name(t.v, line=t.line, col=t.col)
        if t.k == 'EOF':
            self.err(_tr('表达式没有写完'))
        if t.k == 'OP' and t.v == ';':
            self.err(_tr('这里缺少表达式'))
        self.err(_tr('这里应该是变量、常量或表达式，实际是 {desc}', desc=self.desc(t)))

    def _looks_like_func_call(self):
        # 在表达式里：NAME( 一定是函数调用；语句开头的 NAME( 由 stmt 处理为功能块调用
        return True

    def func_call(self, t):
        self.adv()
        args, named = [], []
        while not self.isop(')'):
            if self.is_('EOF'):
                self.err(_tr('函数调用缺少右括号“)”'))
            if self.t.k == 'ID' and self.peek().k == 'OP' and self.peek().v == ':=':
                pn = self.adv()
                self.adv()
                named.append((pn.v.upper(), self.expr()))
            else:
                args.append(self.expr())
            if self.isop(','):
                self.adv()
            elif not self.isop(')'):
                self.err(_tr('参数之间用逗号分隔'))
        self.adv()
        return Call(t.v.upper(), args, named, line=t.line, col=t.col)

    def postfix(self, e):
        while True:
            if self.isop('.'):
                t = self.adv()
                if self.t.k == 'INT':            # x.3 位访问
                    b = self.adv()
                    e = Member(e, str(b.v), line=t.line, col=t.col)
                    continue
                f = self.ident(_tr('成员名（例如 T1.Q、C1.CV）'))
                e = Member(e, f.v.upper(), line=t.line, col=t.col)
            elif self.isop('['):
                t = self.adv()
                idx = self.expr()
                self.expect_op(']', _tr('数组下标缺少“]”'))
                e = Index(e, idx, line=t.line, col=t.col)
            else:
                return e

    # -- 只解析一个表达式（梯形图操作数用）
    def only_expr(self):
        e = self.expr()
        if not self.is_('EOF'):
            self.err(_tr('表达式后面多了 {desc}', desc=self.desc(self.t)))
        return e


def parse(src):
    return Parser(src or '').program()


def parse_expr(text):
    return Parser(str(text)).only_expr()


def parse_decls(text):
    """只解析 VAR … END_VAR 段（导入用）。"""
    p = Parser(text)
    out = []
    while p.t.k == 'KW' and p.t.v in _SECTIONS:
        out += p.var_block()
    return out
