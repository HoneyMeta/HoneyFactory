"""程序 = {"id","name","lang":"LD"|"ST","vars":[…],"source": ST 文本 或 LD JSON} → 编译结果。

变量来源（按优先级）：程序 vars 表、ST 源程序里的 VAR 段、控制单元的 I/O 表（自动成为全局变量，名字就是 I/O 名）。
LD 里用到但没声明的功能块实例会自动声明（和博途放功能块时自动建背景数据一样）。
"""
from ..i18n import _tr
import copy
import hashlib
import json
import re

from . import st
from .compiler import (Ctx, CompileError, Emitter, Mem, Sym, check_assign, const_value, execute, finalize, parse_type, tname, wrapper,
                       zero, STMT)
from .fb import FB_DEFS, FBInst
from .ld import compile_ld, fb_instances

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def blank_program(lang='LD', name='主程序'):
    return {'id': 'main', 'name': name, 'lang': lang, 'vars': [],
            'source': {'rungs': [{'comment': '', 'elements': []}]} if lang == 'LD' else 'PROGRAM Main\nVAR\nEND_VAR\n\nEND_PROGRAM\n'}


def program_hash(program):
    p = {k: program.get(k) for k in ('lang', 'vars', 'source')}
    return hashlib.sha1(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


class Compiled:
    def __init__(self):
        self.ok = False
        self.errors, self.warnings = [], []
        self.code = ()
        self.syms: list[Sym] = []
        self.lang = 'ST'
        self.lines = []          # 可以设断点的行（LD：梯级号+1）
        self.rungs = 0
        self.hash = ''
        self.program = None      # 编译时的程序（LD 已补齐元素 id）
        self.used_addrs = {}
        self.in_map, self.out_map = [], []
        self.xref = {}

    def result(self):
        return {'ok': self.ok, 'errors': self.errors, 'warnings': self.warnings, 'lang': self.lang, 'hash': self.hash, 'xref': self.xref,
                'lines': self.lines, 'rungs': self.rungs,
                'symbols': [sym_info(s) for s in self.syms]}

    def new_memory(self):
        m = Mem()
        for s in self.syms:
            if s.key not in m.v:
                m.v[s.key] = copy.deepcopy(s.init) if s.init is not None else zero(s.type)
        for a, t in self.used_addrs.items():
            m.v.setdefault(a, zero(t))
        m.rungs = [False] * self.rungs
        return m


def sym_info(s: Sym):
    return {'name': s.name, 'type': tname(s.type), 'addr': s.addr, 'section': s.section, 'constant': s.constant, 'retain': s.retain,
            'comment': s.comment, 'io': (s.io or {}).get('dir'), 'implicit': s.implicit, 'line': s.line}


def _var_error(errs, name, msg, line=0):
    d = {'var': name, 'msg': msg}
    if line:
        d['line'] = line
    errs.append(d)


def compile_program(program, io=None):
    """编译。不论程序写成什么样都返回 Compiled（意外异常转成一条中文错误），不会让接口 500。"""
    try:
        return _compile_program(program, io)
    except RecursionError:
        c = Compiled()
        c.errors.append({'line': 0, 'msg': _tr('程序嵌套太深（括号或 IF/FOR 套了太多层），请拆开写')})
        return c
    except Exception as e:                    # noqa: BLE001
        import logging
        logging.getLogger('vfactory.plc').exception(_tr('编译器内部错误'))
        c = Compiled()
        c.errors.append({'line': 0, 'msg': _tr('编译器没能处理这个程序（{v}），请检查最近改动的地方；这是软件的问题，欢迎反馈', v=type(e).__name__)})
        return c


def _compile_program(program, io=None):
    c = Compiled()
    program = copy.deepcopy(program or {})
    lang = str(program.get('lang') or 'ST').upper()
    if lang not in ('ST', 'LD'):
        c.errors.append({'msg': _tr('不支持的语言 {lang}（支持 LD 梯形图、ST 结构化文本）', lang=lang)})
        return c
    c.lang = lang
    ctx = Ctx(io)
    # 1) I/O 表
    for ent in io or []:
        nm = str(ent.get('name') or '').strip()
        if not IDENT.match(nm):
            _var_error(c.errors, nm, _tr('I/O 名称“{nm}”不能当变量名（只能用字母、数字、下划线，且不以数字开头）', nm=nm))
            continue
        addr = None
        if ent.get('addr'):
            na = st.norm_addr(str(ent['addr']))
            if not na:
                _var_error(c.errors, nm, _tr('I/O {nm} 的地址 {addr} 写法不对', nm=nm, addr=ent["addr"]))
                continue
            addr = na[0]
        try:
            typ = parse_type(ent.get('type') or 'BOOL')
        except CompileError as e:
            _var_error(c.errors, nm, _tr('I/O {nm}：{msg}', nm=nm, msg=e.msg))
            continue
        s = Sym(nm, addr or nm.upper(), typ, addr=addr, section='IO', comment=ent.get('comment') or ent.get('desc') or '', io=ent)
        try:
            ctx.declare(s)
        except CompileError as e:
            _var_error(c.errors, nm, e.msg)
    # 2) 变量表 + ST 声明段
    decls = []
    for v in program.get('vars') or []:
        nm = str(v.get('name') or '').strip()
        if not IDENT.match(nm):
            _var_error(c.errors, nm, _tr('变量名“{nm}”不合法（只能用字母、数字、下划线，且不以数字开头）', nm=nm))
            continue
        if nm.upper() in st.KEYWORDS:
            _var_error(c.errors, nm, _tr('“{nm}”是关键字，不能当变量名', nm=nm))
            continue
        decls.append(('json', v, nm))
    body = []
    if lang == 'ST':
        try:
            prog = st.parse(program.get('source') or '')
            body = prog.body
            for d in prog.decls:
                decls.append(('st', d, d.name))
        except st.StError as e:
            c.errors.append(e.as_dict())
    pending = []
    for kind, d, nm in decls:
        try:
            if kind == 'json':
                typ = parse_type(d.get('type') or 'BOOL')
                addr = None
                if d.get('addr'):
                    na = st.norm_addr(str(d['addr']))
                    if not na:
                        raise CompileError(_tr('地址 {addr} 写法不对（例：%IX0.0、%QX0.1、%MX2.0、%MW10）', addr=d["addr"]))
                    addr = na[0]
                sec = str(d.get('section') or 'VAR').upper()
                init_node = None
                iv = d.get('init')
                if iv is not None and str(iv).strip() != '':
                    if isinstance(iv, bool):
                        init_node = st.Num(iv, 'BOOL')
                    elif isinstance(iv, (int, float)) and not isinstance(iv, bool):
                        init_node = st.Num(iv, 'INT' if isinstance(iv, int) else 'REAL')
                        if typ == 'TIME':
                            init_node = st.Num(iv, 'TIME')
                    else:
                        try:
                            init_node = st.Parser(str(iv)).init_value()
                        except st.StError as e:
                            raise CompileError(_tr('初值“{iv}”写法不对：{msg}', iv=iv, msg=e.msg))
                s = Sym(nm, None, typ, addr=addr, section=sec, constant=bool(d.get('constant')), retain=bool(d.get('retain')),
                        comment=d.get('comment') or '')
                line = 0
            else:
                typ = parse_type(d.type, node=d)
                s = Sym(nm, None, typ, addr=d.addr, section=d.section, constant=d.constant, retain=d.retain, comment=d.comment, line=d.line)
                init_node = d.init
                line = d.line
            if s.addr and typ in FB_DEFS or s.addr and isinstance(typ, tuple):
                raise CompileError(_tr('功能块实例和数组不能分配地址'))
            io_sym = ctx.syms.get(nm.upper())
            if io_sym is not None and io_sym.io is not None:
                if not s.addr:
                    s.addr = io_sym.addr
                if s.addr == io_sym.addr and typ != io_sym.type:
                    raise CompileError(_tr('{nm} 在 I/O 表里是 {tname}，这里声明成了 {tname2}', nm=nm, tname=tname(io_sym.type), tname2=tname(typ)))
            if s.addr:
                prev = ctx.addr_syms.get(s.addr)
                if prev is not None and prev.type != typ and not prev.implicit:
                    raise CompileError(_tr('地址 {addr} 已经是 {tname}（{name}），不能再声明成 {tname2}', addr=s.addr, tname=tname(prev.type), name=prev.name, tname2=tname(typ)))
            s.key = s.addr or nm.upper()
            if s.addr and s.addr[2] != 'X' and typ == 'BOOL':
                raise CompileError(_tr('布尔量要用位地址（例如 %MX0.0），{addr} 是字地址', addr=s.addr))
            if s.addr and s.addr[2] == 'X' and typ != 'BOOL':
                raise CompileError(_tr('位地址 {addr} 只能放布尔量，{nm} 是 {tname}', addr=s.addr, nm=nm, tname=tname(typ)))
            ctx.declare(s, d if kind == 'st' else None)
            pending.append((s, init_node, d if kind == 'st' else None, nm, line))
        except CompileError as e:
            if kind == 'st':
                c.errors.append({'line': e.line or d.line, 'col': e.col or d.col, 'msg': e.msg})
            else:
                _var_error(c.errors, nm, e.msg)
    # 初值：常量先算（后面的初值可以引用前面的常量）
    for s, init_node, node, nm, line in pending:
        if init_node is None:
            continue
        try:
            s.init = const_value(init_node, ctx, s.type)
        except CompileError as e:
            if node is not None:
                c.errors.append({'line': e.line or line, 'col': e.col, 'msg': e.msg})
            else:
                _var_error(c.errors, nm, e.msg)
    # 3) LD 自动声明功能块实例
    if lang == 'LD':
        src = program.get('source')
        if isinstance(src, str):
            try:
                src = json.loads(src) if src.strip() else {'rungs': []}
            except ValueError:
                c.errors.append({'rung': 0, 'msg': _tr('梯形图内容不是合法的 JSON')})
                src = {'rungs': []}
            program['source'] = src
        if not isinstance(src, dict):
            if src not in (None, [], ''):
                c.errors.append({'rung': 0, 'msg': _tr('梯形图格式不对：应该是 {"rungs": [梯级, …]}')})
            src = {'rungs': []}
            program['source'] = src
        for inst, typ in fb_instances(src).items():
            if not IDENT.match(inst):
                c.errors.append({'rung': 0, 'msg': _tr('功能块实例名“{inst}”不合法', inst=inst)})
                continue
            if inst.upper() not in ctx.syms and typ in FB_DEFS:
                ctx.declare(Sym(inst, inst.upper(), typ, comment=_tr('{cn}（自动声明）', cn=FB_DEFS[typ]["cn"])))
    # 4) 程序体
    em = Emitter(ctx)
    if lang == 'ST':
        em.stmts(body)
        c.rungs = 0
    else:
        c.rungs = compile_ld(program['source'], ctx, em.emit)
    # 双线圈：同一个变量在两个以上梯级里用普通线圈（或运算/传送输出）赋值，后面的会覆盖前面的
    if lang == 'LD':
        for nm, refs in ctx.xref.items():
            rs = sorted({r['rung'] for r in refs if r['k'] == 'W' and r.get('rung') is not None and not r.get('f')})
            if len(rs) > 1:
                ctx.warnings.append({'rung': rs[-1], 'msg': _tr('双线圈：{nm} 在梯级 {join} 都有输出，后面的梯级会覆盖前面的结果（要分开控制请用中间变量，或用置位/复位线圈）', nm=nm, join=_tr('、').join(str(x + 1) for x in rs)), 'var': nm})
    c.xref = ctx.xref
    c.errors += ctx.errors
    c.warnings += ctx.warnings
    c.code = finalize(em.code)
    c.lines = sorted({ins[4] for ins in c.code if ins[4]})
    seen = set()
    c.syms = []
    for s in ctx.syms.values():
        if id(s) not in seen:
            seen.add(id(s))
            c.syms.append(s)
    c.used_addrs = {a: t for a, t in ctx.used_addrs.items()}
    c.hash = program_hash(program)
    c.program = program
    c.errors.sort(key=lambda e: (e.get('rung', -1), e.get('line', 0), e.get('col', 0)))
    c.ok = not c.errors
    # I/O 映射
    for ent in io or []:
        nm = str(ent.get('name') or '').strip()
        s = ctx.syms.get(nm.upper())
        if not s:
            continue
        if ent.get('dir') == 'out':
            c.out_map.append((nm, s.key, s.type))
        else:
            c.in_map.append((nm, s.key, wrapper(s.type)))
    if not io:
        for s in c.syms:
            if (s.addr and s.addr.startswith('%Q')) or s.section == 'VAR_OUTPUT':
                c.out_map.append((s.name, s.key, s.type))
    return c


def check(program, io=None):
    """compile(program) -> {ok, errors:[{line|rung, msg}], warnings}"""
    return compile_program(program, io).result()
