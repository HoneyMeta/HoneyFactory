"""4.5 "为什么没反应"：用 PLC 的实时值解释程序——哪个梯级断在哪个元件、为什么；ST 里哪条赋值、哪个条件为假。

    snap = snapshot(plc)                                   # 现在的在线值（梯形图每个元件的通断、变量值）
    why_not(program, snap, io, 'M1_RUN', True)             # 期望 M1_RUN=1 却没有：{msg, cause, rung, elems, line, tips}
    explain_rung(program, snap, io, 0)                     # 梯级 1 现在的能流（"解释这个梯级"）
    explain_line(program, snap, io, 3)                     # ST 第 3 行的条件值

snap = {'ld': {元件 id: [左边有电, 右边有电, 触点闭合]}, 'vars': {大写名: 值}, 'rungs': [梯级通断], 'state': 'RUN'}。
io 是 I/O 表（带 contact NO/NC 和 idle：没人操作时的值），用来说清楚"常闭输入没按下时为 1"。
只读分析，不改 PLC。文字给初学者看：说现象、说原因、说怎么改。
"""
from ..i18n import _tr, label
from . import st as stmod
from .ld import COILS, CONTACTS, iter_elements, norm_t

T_CN = {'NO': '常开触点', 'NC': '常闭触点', 'P': '上升沿触点', 'N': '下降沿触点', 'COIL': '线圈', 'NCOIL': '取反线圈', 'SET': '置位线圈',
        'RESET': '复位线圈', 'FB': '功能块', 'CMP': '比较', 'MATH': '运算', 'MOVE': '传送'}


# ---------------------------------------------------------------- 快照
def _jv(v):
    try:
        from .runtime import _json_val
        return _json_val(v)
    except Exception:                                   # noqa: BLE001
        return v


def snapshot(plc):
    """PlcRuntime → 轻量快照（只读）。没有程序时 ld/vars 为空。"""
    p = getattr(plc, 'prog', None)
    m = getattr(plc, 'mem', None)
    out = {'state': str(getattr(plc, 'state', '') or ''), 'ld': {}, 'vars': {}, 'rungs': [], 'hash': getattr(p, 'hash', None) if p else None,
           'lang': getattr(p, 'lang', None) if p else None}
    if p is None or m is None:
        return out
    out['ld'] = {k: [bool(a), bool(b), bool(c)] for k, (a, b, c) in m.ld.items()}
    out['rungs'] = [bool(x) for x in m.rungs]
    vs = {}
    for s in p.syms:
        vs[s.name.upper()] = _jv(m.v.get(s.key))
    for a in getattr(p, 'used_addrs', {}) or {}:
        vs.setdefault(a.upper(), m.v.get(a))
    out['vars'] = vs
    outs = getattr(plc, 'outputs', None) or {}
    out['outputs'] = {k: v for k, v in outs.items() if not str(k).startswith('%')}
    return out


# ---------------------------------------------------------------- 工具
def _io(io, name):
    up = str(name or '').upper()
    for e in io or []:
        if str(e.get('name', '')).upper() == up:
            return e
    return None


def _val(snap, expr):
    """操作数（变量名 / T1.Q / 地址 / 常量）的当前值；复杂表达式求不出来返回 None。"""
    s = str(expr or '').strip()
    if not s:
        return None
    vs = snap.get('vars') or {}
    up = s.upper()
    if up in vs:
        return vs[up]
    if up in ('TRUE', 'FALSE'):
        return up == 'TRUE'
    if '.' in s and not s.startswith('%'):
        b, f = s.split('.', 1)
        v = vs.get(b.upper())
        if isinstance(v, dict):
            for k, x in v.items():
                if k.upper() == f.upper():
                    return x
    try:
        return _eval(stmod.parse_expr(s), vs)
    except Exception:                                   # noqa: BLE001
        return None


def _b(v):
    if v is None:
        return '?'
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, float):
        return f'{v:.3g}'
    if isinstance(v, dict):
        return '{…}'
    return str(v)


def _desc_io(e):
    """'输入 %I0.3，常闭，没人按时为 1'。"""
    if not e:
        return ''
    parts = [(_tr('输入') if e.get('dir') == 'in' else _tr('输出')) + (f" {e['addr']}" if e.get('addr') else '')]
    if e.get('dir') == 'in' and e.get('contact') == 'NC':
        parts.append(_tr('常闭输入，没按下/没动作时为 1'))
    return _tr('，').join(parts)


def rungs_of(program):
    src = (program or {}).get('source')
    if isinstance(src, dict):
        r = src.get('rungs')
        return r if isinstance(r, list) else []
    return []


def _coils(program, name):
    """写变量 name 的线圈：[(梯级序号, 元件)]。"""
    up = str(name).upper()
    out = []
    for ri, r in enumerate(rungs_of(program)):
        for el in iter_elements((r or {}).get('elements') or []):
            if norm_t(el.get('t')) in COILS and str(el.get('var') or '').strip().upper() == up:
                out.append((ri, el))
    return out


def _st(snap, el):
    v = (snap.get('ld') or {}).get(el.get('id'))
    return v if isinstance(v, (list, tuple)) and len(v) == 3 else None


# ---------------------------------------------------------------- 梯形图：找断点
def _blockers(node, snap):
    """一段串并联（左边有电）里第一个挡住能流的地方 → [元件…]（并联时每条分支各一个）。没挡住返回 []。"""
    if isinstance(node, list):
        for x in node:
            b = _blockers(x, snap)
            if b:
                return b
            if not _passes(x, snap):
                return []                     # 求不出来（没执行到）：别乱报
        return []
    if not isinstance(node, dict):
        return []
    if 'par' in node:
        if _passes(node, snap):
            return []
        out = []
        for br in node.get('par') or []:
            out += _blockers(br if isinstance(br, list) else [br], snap)
        return out
    if 'ser' in node:
        return _blockers(list(node.get('ser') or []), snap)
    s = _st(snap, node)
    if s and s[0] and not s[1]:
        return [node]
    return []


def _passes(node, snap):
    """这一段右边有没有电（求不出来时 None 当作 False）。"""
    if isinstance(node, list):
        ok = True
        for x in node:
            ok = _passes(x, snap)
            if not ok:
                return False
        return ok
    if not isinstance(node, dict):
        return False
    if 'par' in node:
        return any(_passes(b if isinstance(b, list) else [b], snap) for b in node.get('par') or [])
    if 'ser' in node:
        return _passes(list(node.get('ser') or []), snap)
    s = _st(snap, node)
    return bool(s and s[1])


def _path_on(node, snap):
    """能流实际走过的元件（并联取通着的那条）。"""
    if isinstance(node, list):
        out = []
        for x in node:
            out += _path_on(x, snap)
        return out
    if not isinstance(node, dict):
        return []
    if 'par' in node:
        for b in node.get('par') or []:
            bb = b if isinstance(b, list) else [b]
            if _passes(bb, snap):
                return _path_on(bb, snap)
        return []
    if 'ser' in node:
        return _path_on(list(node.get('ser') or []), snap)
    return [node]


def why_open(el, snap, io, ri, trigger=None):
    """一个断开的元件为什么断开 → (原因文字, cause 代码)。trigger：刚才按的按钮/输入名（判断"已经松开了"）。"""
    t = norm_t(el.get('t'))
    var = str(el.get('var') or '').strip()
    v = _val(snap, var)
    e = _io(io, var)
    rn = _tr('梯级 {v}', v=ri + 1)
    if t in ('NO', 'NC') and e is not None and e.get('dir') == 'in' and isinstance(v, bool):
        nc_in = e.get('contact') == 'NC'
        if t == 'NC' and nc_in and v:
            return (_tr('{var} 是常闭输入，没按下时为 1；你用了常闭触点，等于又取反成 0，所以{rn} 断开。把它改成常开触点（-| |-）：没按时接通、按下停止时断开。', var=var, rn=rn), 'nc_on_nc')
        if t == 'NO' and not v:
            if nc_in:
                return (_tr('{var} 现在是 0：常闭按钮/触点被按下了（或者断线），{rn} 在这里断开。', var=var, rn=rn), 'nc_pressed')
            if trigger and var.upper() == str(trigger).upper():
                return (_tr('{var} 已经松开（现在 0），{rn} 在这里断开。', var=var, rn=rn), 'released')
            return (_tr('{var} 现在是 0（{v}），常开触点断开。', var=var, v=e.get("comment") or _tr('没有信号')), 'input_off')
        if t == 'NC' and v:
            return (_tr('{var} 现在是 1，常闭触点断开。', var=var), 'input_on_nc')
    if t in ('NO', 'NC', 'P', 'N'):
        if t == 'P':
            return (_tr('{var} 是上升沿触点：只在 {var} 从 0 变 1 的那一个扫描周期接通。', var=var), 'edge')
        if t == 'N':
            return (_tr('{var} 是下降沿触点：只在 {var} 从 1 变 0 的那一个扫描周期接通。', var=var), 'edge')
        kind = _tr('输出') if e is not None and e.get('dir') == 'out' else _tr('变量')
        return (_tr('{kind} {var} 现在是 {v}，{v2}断开。', kind=kind, var=var, v=_b(v), v2=T_CN[t]), 'var')
    if t == 'CMP':
        a, b = el.get('a'), el.get('b')
        return (_tr('比较 {a} {get} {b} 不成立（{a} = {v}，{b} = {v2}）。', a=a, get=el.get("op"), b=b, v=_b(_val(snap, a)), v2=_b(_val(snap, b))), 'cmp')
    if t == 'FB':
        inst = el.get('inst') or ''
        fv = (snap.get('vars') or {}).get(str(inst).upper())
        if isinstance(fv, dict) and 'ET' in fv:
            return (_tr('定时器 {inst} 还没到时间（ET = {get} ms，PT = {get2} ms），Q 还是 0。', inst=inst, get=fv.get("ET"), get2=fv.get("PT")), 'timer')
        return (_tr('功能块 {inst} 的输出还是 0。', inst=inst), 'fb')
    return (_tr('{get} {var} 断开。', get=T_CN.get(t, t), var=var), 'other')


def _el_name(el):
    t = norm_t(el.get('t'))
    nm = el.get('var') or el.get('inst') or ''
    if t == 'CMP':
        nm = f"{el.get('a')} {el.get('op')} {el.get('b')}"
    return _tr('{nm}（{get}）', nm=nm, get=T_CN.get(t, t))


def why_not(program, snap, io, out, want=True, trigger=None, wired=None):
    """期望输出 out 为 want，实际不是 → 诊断。返回 {msg, cause, rung?, elems?, line?, tips?}；分析不出来返回 None。
    wired：设备那边实际收到的值（PLC 输出对了设备却没反应 → 信号线/断线）。"""
    st = str(snap.get('state') or '')
    if not program or not snap.get('hash'):
        return {'msg': _tr('PLC 里还没有程序：先在编程窗口写好程序，点工具栏上的"下载"。'), 'cause': 'no_program'}
    if st == 'STOP':
        return {'msg': _tr('PLC 现在是停止（STOP）状态，所有输出都是 0：在 PLC 面板或编程窗口点"运行"。'), 'cause': 'plc_stop'}
    if st == 'ERROR':
        return {'msg': _tr('PLC 运行出错停下了（输出都是 0）：看编程窗口顶上的红色错误，改好后重新下载。'), 'cause': 'plc_error'}
    if st == 'HALT':
        return {'msg': _tr('PLC 停在断点/单步上，输出保持不变：点"运行"继续，或者去掉断点。'), 'cause': 'plc_halt'}
    e = _io(io, out)
    if e is None:
        return {'msg': _tr('{out} 不在这台 PLC 的 I/O 表里，程序写了也送不到设备。', out=out), 'cause': 'not_io'}
    cur = (snap.get('outputs') or {}).get(e['name'], (snap.get('vars') or {}).get(str(out).upper()))
    if bool(cur) == bool(want) and wired is not None and bool(wired) != bool(want):
        return {'msg': _tr('PLC 的输出 {out} 已经是 {v}，但设备那边收到的是 {v2}：这一路信号线没接上或者断线了（看 I/O 表 / 故障）。', out=out, v=_b(bool(want)), v2=_b(wired)),
                'cause': 'not_wired', 'var': out}
    lang = str((program or {}).get('lang') or snap.get('lang') or 'LD').upper()
    if lang == 'ST':
        return _st_why(program, snap, io, out, want)
    coils = _coils(program, out)
    if not coils:
        return {'msg': _tr('程序里没有写 {out} 的线圈：在梯级最右边放一个线圈 -( )-，变量填 {out}。', out=out), 'cause': 'no_coil', 'var': out}
    rungs = rungs_of(program)
    plain = [(ri, el) for ri, el in coils if norm_t(el.get('t')) in ('COIL', 'NCOIL')]
    if len(plain) > 1:
        rs = _tr('、').join(str(ri + 1) for ri, _ in plain)
        on = [ri for ri, el in plain if (_st(snap, el) or [0, 0, 0])[2]]
        last = plain[-1][0]
        msg = (_tr('{out} 有 {len} 个线圈（梯级 {rs}）：每个扫描周期后面的梯级会把前面的结果覆盖掉，最后算数的是梯级 {v}。把条件合并到一个梯级里（并联），只留一个线圈。', out=out, len=len(plain), rs=rs, v=last + 1))
        if on and on[-1] != last:
            msg = _tr('梯级 {v} 让 {out} 通电了，但 ', v=on[-1] + 1, out=out) + msg
        return {'msg': msg, 'cause': 'dup_coil', 'rung': last, 'elems': [plain[-1][1].get('id')], 'var': out}
    ri, coil = coils[-1]
    r = rungs[ri] if ri < len(rungs) else {}
    els = list((r or {}).get('elements') or [])
    t = norm_t(coil.get('t'))
    s = _st(snap, coil)
    if s is None:
        return {'msg': _tr('梯级 {v} 这一个扫描周期没有执行到（前面有断点或跳转）。', v=ri + 1), 'cause': 'not_run', 'rung': ri}
    pin = s[0]
    if want:
        if t == 'RESET':
            return {'msg': _tr('梯级 {v} 用的是复位线圈 (R)，它只会把 {out} 变 0。要让它变 1 用普通线圈或置位线圈 (S)。', v=ri + 1, out=out), 'cause': 'reset_coil',
                    'rung': ri, 'elems': [coil.get('id')]}
        if pin:
            if t == 'NCOIL':
                return {'msg': _tr('梯级 {v} 通了，但你用的是取反线圈 -(/)-：通电时 {out} 反而是 0。改成普通线圈。', v=ri + 1, out=out), 'cause': 'ncoil', 'rung': ri,
                        'elems': [coil.get('id')]}
            return None
        idx = next((i for i, x in enumerate(els) if x is coil), len(els))
        bl = _blockers(els[:idx], snap)
        if not bl:
            return {'msg': _tr('梯级 {v} 到线圈 {out} 之前没有通电。', v=ri + 1, out=out), 'cause': 'open', 'rung': ri}
        reasons, causes = [], []
        for el in bl[:3]:
            txt, c = why_open(el, snap, io, ri, trigger)
            reasons.append(txt)
            causes.append(c)
        cause = 'nc_on_nc' if 'nc_on_nc' in causes else causes[0]
        if cause == 'released' and any(_io(io, x.get('var')) and str(x.get('var', '')).upper() == str(out).upper() for x in bl):
            cause = 'no_latch'
        if len(bl) > 1 and cause in ('released', 'no_latch', 'var', 'input_off'):
            names = _tr('、').join(_el_name(x) for x in bl)
            msg = _tr('梯级 {v} 的并联分支都断开（{names}）：', v=ri + 1, names=names) + ' '.join(reasons)
            if cause == 'no_latch' or any(str(x.get('var', '')).upper() == str(out).upper() for x in bl):
                msg += _tr(' 自锁分支 {out} 要先通电才能保持；按住启动时线圈应该先得电，看看启动那一路是不是被别的触点挡住。', out=out)
        else:
            msg = _tr('梯级 {v} 断开：', v=ri + 1) + ' '.join(reasons)
        return {'msg': msg, 'cause': cause, 'rung': ri, 'elems': [x.get('id') for x in bl], 'var': out}
    # 期望 0 却是 1
    if t == 'SET':
        return {'msg': _tr('梯级 {v} 用的是置位线圈 (S)：{out} 置 1 以后会一直保持，要另外用复位线圈 (R) 把它清 0。', v=ri + 1, out=out), 'cause': 'set_no_reset',
                'rung': ri, 'elems': [coil.get('id')]}
    if not pin:
        if t == 'NCOIL':
            return {'msg': _tr('梯级 {v} 断开时取反线圈让 {out} = 1。改成普通线圈。', v=ri + 1, out=out), 'cause': 'ncoil', 'rung': ri, 'elems': [coil.get('id')]}
        return None
    idx = next((i for i, x in enumerate(els) if x is coil), len(els))
    path = _path_on(els[:idx], snap)
    names = ' → '.join(f'{_el_name(x)}={_b(_val(snap, x.get("var")) if x.get("var") else (_st(snap, x) or [0, 0, 0])[2])}' for x in path[:6])
    tip = ''
    if trigger:
        hit = [x for x in path if str(x.get('var') or '').upper() == str(trigger).upper()]
        te = _io(io, trigger)
        if not any(str(x.get('var') or '').upper() == str(trigger).upper() for x in iter_elements(els)):
            tip = _tr(' 这条梯级里没有 {trigger} 的触点，按 {trigger} 断不开它：把 {trigger} 串联进去。', trigger=trigger)
        elif hit and te and te.get('contact') == 'NC' and norm_t(hit[0].get('t')) == 'NC':
            tip = _tr(' {trigger} 是常闭输入，按下时变 0，你用的常闭触点反而闭合了。改成常开触点。', trigger=trigger)
    return {'msg': _tr('梯级 {v} 还通着，线圈 {out} 一直得电：{names}。{tip}', v=ri + 1, out=out, names=names, tip=tip).strip(), 'cause': 'still_on', 'rung': ri,
            'elems': [x.get('id') for x in path[:6]], 'var': out}


def explain_rung(program, snap, io, ri):
    """"解释这个梯级"：现在的能流，一句一句说。返回 {rung, lines:[…], summary, elems:{id: on/off}}。"""
    rungs = rungs_of(program)
    if not (0 <= ri < len(rungs)):
        return {'rung': ri, 'lines': [], 'summary': _tr('没有这个梯级')}
    els = list((rungs[ri] or {}).get('elements') or [])
    if not snap.get('hash'):
        return {'rung': ri, 'lines': [_tr('PLC 里还没有程序（或不是现在编辑器里这一份）：下载后才能看实时能流。')], 'summary': _tr('还没下载')}
    lines = []
    marks = {}

    def say(node, depth):
        pad = _tr('\u3000') * depth
        if isinstance(node, list):
            for x in node:
                say(x, depth)
            return
        if not isinstance(node, dict):
            return
        if 'par' in node:
            ok = _passes(node, snap)
            lines.append(_tr('{pad}并联 {len} 条分支（任意一条通就通）：{v}', pad=pad, len=len(node.get("par") or []), v=_tr('通') if ok else _tr('都不通')))
            for i, b in enumerate(node.get('par') or []):
                bb = b if isinstance(b, list) else [b]
                lines.append(_tr('{pad}\u3000分支 {v}：{v2}', pad=pad, v=i + 1, v2=_tr('通') if _passes(bb, snap) else _tr('断')))
                say(bb, depth + 2)
            return
        if 'ser' in node:
            say(list(node.get('ser') or []), depth)
            return
        t = norm_t(node.get('t'))
        s = _st(snap, node)
        var = node.get('var') or node.get('inst') or ''
        e = _io(io, var)
        extra = _desc_io(e)
        if s is None:
            lines.append(_tr('{pad}{v}：这个周期没有执行到', pad=pad, v=_el_name(node)))
            return
        marks[node.get('id')] = bool(s[1])
        if t in CONTACTS:
            v = _val(snap, var)
            state = _tr('闭合') if s[2] else _tr('断开')
            lines.append(f'{pad}{label(T_CN[t])} {var} = {_b(v)}{(_tr('（') + extra + _tr('）')) if extra else ""} → {state}' + ('' if s[0] else _tr('（左边已经没电）')))
            if not s[2] and s[0]:
                why, _ = why_open(node, snap, io, ri)
                lines.append(_tr('{pad}\u3000↳ {why}', pad=pad, why=why))
        elif t in COILS:
            lines.append(_tr('{pad}{v} {var}：{v2} → {var} = {v3}', pad=pad, v=T_CN[t], var=var, v2=_tr('通电') if s[0] else _tr('没电'), v3=_b(_val(snap, var))))
        elif t == 'FB':
            fv = (snap.get('vars') or {}).get(str(node.get('inst') or '').upper())
            det = ''
            if isinstance(fv, dict):
                det = _tr('，') + _tr('，').join(f'{k}={_b(v)}' for k, v in fv.items() if k in ('IN', 'Q', 'ET', 'PT', 'CV', 'PV'))
            lines.append(_tr('{pad}功能块 {get} {get2}：输入 {v}，输出 {v2}{det}', pad=pad, get=node.get("fb"), get2=node.get("inst"), v=_tr('有电') if s[0] else _tr('没电'), v2=_tr('有电') if s[1] else _tr('没电'), det=det))
        elif t == 'CMP':
            a, b = node.get('a'), node.get('b')
            lines.append(_tr('{pad}比较 {a} {get} {b}（{v} {get} {v2}）→ {v3}', pad=pad, a=a, get=node.get("op"), b=b, v=_b(_val(snap, a)), v2=_b(_val(snap, b)), v3=_tr('成立') if s[2] else _tr('不成立')))
        else:
            lines.append(_tr('{pad}{v}：{v2}', pad=pad, v=_el_name(node), v2=_tr('执行') if s[0] else _tr('没执行（没电）')))

    lines.append(_tr('从左母线（一直有电）往右看：'))
    say(els, 0)
    on = bool((snap.get('rungs') or [])[ri]) if ri < len(snap.get('rungs') or []) else _passes(els, snap)
    summary = _tr('梯级 {v} 现在{v2}。', v=ri + 1, v2=_tr('通') if on else _tr('断'))
    coils = [x for x in iter_elements(els) if norm_t(x.get('t')) in COILS]
    if coils and not on:
        bl = _blockers(els, snap)
        if bl:
            summary += _tr('断在：') + _tr('、').join(_el_name(x) for x in bl[:3]) + _tr('。')
    return {'rung': ri, 'lines': lines, 'summary': summary, 'elems': marks}


# ---------------------------------------------------------------- ST
def _eval(n, vs):
    if isinstance(n, stmod.Num):
        return n.value
    if isinstance(n, stmod.Name):
        nm = n.name.upper()
        if nm in ('TRUE', 'FALSE'):
            return nm == 'TRUE'
        return vs.get(nm)
    if isinstance(n, stmod.Addr):
        return vs.get(str(n.addr).upper())
    if isinstance(n, stmod.Member):
        b = _eval(n.base, vs)
        if isinstance(b, dict):
            for k, x in b.items():
                if k.upper() == str(n.field).upper():
                    return x
        return None
    if isinstance(n, stmod.Unary):
        v = _eval(n.e, vs)
        if v is None:
            return None
        if n.op == 'NOT':
            return not v if isinstance(v, bool) else ~v
        if n.op == '-':
            return -v
        return v
    if isinstance(n, stmod.Bin):
        a, b = _eval(n.a, vs), _eval(n.b, vs)
        if a is None or b is None:
            return None
        op = n.op
        try:
            if op in ('AND', '&'):
                return a and b if isinstance(a, bool) else a & b
            if op == 'OR':
                return a or b if isinstance(a, bool) else a | b
            if op == 'XOR':
                return a != b if isinstance(a, bool) else a ^ b
            return {'=': a == b, '<>': a != b, '<': a < b, '>': a > b, '<=': a <= b, '>=': a >= b}.get(op, None) if op in ('=', '<>', '<', '>', '<=', '>=') else \
                {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b, '/': lambda: a / b, 'MOD': lambda: a % b}[op]()
        except Exception:                               # noqa: BLE001
            return None
    return None


def _src_text(n, src_lines):
    try:
        return _fmt(n)
    except Exception:                                   # noqa: BLE001
        return '…'


def _fmt(n):
    if isinstance(n, stmod.Num):
        v = n.value
        return ('TRUE' if v else 'FALSE') if isinstance(v, bool) else str(v)
    if isinstance(n, stmod.Name):
        return n.name
    if isinstance(n, stmod.Addr):
        return str(n.addr)
    if isinstance(n, stmod.Member):
        return f'{_fmt(n.base)}.{n.field}'
    if isinstance(n, stmod.Unary):
        return f'NOT {_fmt(n.e)}' if n.op == 'NOT' else f'{n.op}{_fmt(n.e)}'
    if isinstance(n, stmod.Bin):
        def side(x):
            s = _fmt(x)
            return f'({s})' if isinstance(x, stmod.Bin) and x.op != n.op else s
        return f'{side(n.a)} {n.op} {side(n.b)}'
    return '…'


def _conj(n, op):
    """把 a AND b AND c 拆成 [a, b, c]。"""
    if isinstance(n, stmod.Bin) and n.op in ((op,) if op != 'AND' else ('AND', '&')):
        return _conj(n.a, op) + _conj(n.b, op)
    return [n]


def _names(n):
    if isinstance(n, stmod.Name):
        return [n.name]
    out = []
    for f in getattr(n, 'fields', ()):
        x = getattr(n, f, None)
        if isinstance(x, stmod.Node):
            out += _names(x)
    return out


def _term_why(term, vs, io):
    """一个为假的条件项：说清楚为什么（特别是 NOT 常闭输入）。"""
    v = _eval(term, vs)
    txt = _fmt(term)
    if isinstance(term, stmod.Unary) and term.op == 'NOT' and isinstance(term.e, stmod.Name):
        e = _io(io, term.e.name)
        x = _eval(term.e, vs)
        if e and e.get('contact') == 'NC' and x:
            return (_tr('{txt} 为假：{name} 是常闭输入，没按下时为 1，NOT {name} 就成了 0。直接写 AND {name}（不要 NOT）。', txt=txt, name=term.e.name), 'nc_on_nc')
    if isinstance(term, stmod.Name):
        e = _io(io, term.name)
        if e and e.get('dir') == 'in' and e.get('contact') == 'NC' and not v:
            return (_tr('{txt} 为假：常闭输入 {name} 现在是 0（按下了或断线）。', txt=txt, name=term.name), 'nc_pressed')
        return (_tr('{txt} 现在是 {v}。', txt=txt, v=_b(v)), 'var')
    names = sorted(set(_names(term)))
    vals = _tr('，').join(f'{n} = {_b(vs.get(n.upper()))}' for n in names[:6])
    return (_tr('{txt} 为假（{vals}）。', txt=txt, vals=vals), 'expr')


def _walk_assign(stmts, out_up, path=()):
    """找写 out 的赋值：[(赋值语句, 外层 IF 条件列表 [(条件, 是否取反)])]。"""
    res = []
    for s in stmts or []:
        if isinstance(s, stmod.Assign):
            tg = s.target
            if isinstance(tg, stmod.Name) and tg.name.upper() == out_up:
                res.append((s, list(path)))
        elif isinstance(s, stmod.If):
            neg = []
            for cond, body in s.arms:
                res += _walk_assign(body, out_up, path + tuple(neg) + ((cond, False),))
                neg.append((cond, True))
            if s.else_:
                res += _walk_assign(s.else_, out_up, path + tuple(neg))
        elif isinstance(s, stmod.Case):
            for _, body in s.arms:
                res += _walk_assign(body, out_up, path)
            if s.else_:
                res += _walk_assign(s.else_, out_up, path)
        elif isinstance(s, (stmod.For, stmod.While, stmod.Repeat)):
            res += _walk_assign(s.body, out_up, path)
    return res


def _parse(program):
    try:
        return stmod.parse(str((program or {}).get('source') or ''))
    except Exception:                                   # noqa: BLE001
        return None


def _st_why(program, snap, io, out, want):
    p = _parse(program)
    if p is None:
        return {'msg': _tr('程序有语法错误，先在"编译信息"里改好。'), 'cause': 'syntax'}
    vs = snap.get('vars') or {}
    asg = _walk_assign(p.body, str(out).upper())
    if not asg:
        return {'msg': _tr('程序里没有给 {out} 赋值的语句：加一行  {out} := 条件;', out=out), 'cause': 'no_assign', 'var': out}
    if len([a for a in asg if not a[1]]) > 1:
        lines = _tr('、').join(str(a[0].line) for a in asg if not a[1])
        return {'msg': _tr('{out} 在第 {lines} 行被赋值了好几次：最后一次赋值算数，前面的被覆盖。把条件合并成一条。', out=out, lines=lines), 'cause': 'dup_assign',
                'line': asg[-1][0].line, 'var': out}
    for s, conds in reversed(asg):
        # 外层 IF：哪个条件不满足
        for cond, neg in conds:
            cv = _eval(cond, vs)
            if cv is None:
                continue
            if bool(cv) == neg:                       # 这条路径没走进来
                why = []
                if not neg:
                    for term in _conj(cond, 'AND'):
                        tv = _eval(term, vs)
                        if tv is not None and not tv:
                            why.append(_term_why(term, vs, io))
                txt = ' '.join(w[0] for w in why) if why else _tr('条件 {v} 现在是 {v2}。', v=_fmt(cond), v2=_b(cv))
                break
        else:
            val = _eval(s.value, vs)
            if val is None or bool(val) == bool(want):
                continue
            if want:
                terms = _conj(s.value, 'AND')
                bad = [t for t in terms if _eval(t, vs) is False]
                if bad:
                    whys = [_term_why(t, vs, io) for t in bad[:3]]
                    cause = 'nc_on_nc' if any(w[1] == 'nc_on_nc' for w in whys) else whys[0][1]
                    return {'msg': _tr('第 {line} 行 {out} := {v}; 算出来是 0：', line=s.line, out=out, v=_fmt(s.value)) + ' '.join(w[0] for w in whys), 'cause': cause,
                            'line': s.line, 'var': out}
                return {'msg': _tr('第 {line} 行 {out} := {v}; 现在算出来是 0。', line=s.line, out=out, v=_fmt(s.value)), 'cause': 'expr', 'line': s.line, 'var': out}
            terms = _conj(s.value, 'OR') if isinstance(s.value, stmod.Bin) and s.value.op == 'OR' else [s.value]
            return {'msg': _tr('第 {line} 行 {out} := {v}; 现在算出来还是 1（', line=s.line, out=out, v=_fmt(s.value)) +
                    _tr('，').join(f'{n} = {_b(vs.get(n.upper()))}' for n in sorted(set(_names(s.value)))[:6]) + _tr('）。'), 'cause': 'still_on',
                    'line': s.line, 'var': out}
        if conds:
            return {'msg': _tr('第 {line} 行给 {out} 赋值，但外面的 IF 没进来：{txt}', line=s.line, out=out, txt=txt), 'cause': 'if_false', 'line': s.line, 'var': out}
    return None


def explain_line(program, snap, io, line):
    """ST 第 line 行（赋值或 IF）现在的值。"""
    p = _parse(program)
    if p is None:
        return {'line': line, 'lines': [_tr('程序有语法错误')], 'summary': ''}
    vs = snap.get('vars') or {}
    found = []

    def walk(stmts):
        for s in stmts or []:
            if getattr(s, 'line', 0) == line:
                found.append(s)
            for f in ('arms',):
                for arm in getattr(s, f, None) or []:
                    if isinstance(arm, tuple) and len(arm) == 2:
                        if isinstance(arm[0], stmod.Node) and getattr(arm[0], 'line', 0) == line and s not in found:
                            found.append(s)
                        walk(arm[1])
            for f in ('else_', 'body'):
                b = getattr(s, f, None)
                if isinstance(b, list):
                    walk(b)
    walk(p.body)
    out = []
    for s in found[:2]:
        if isinstance(s, stmod.Assign):
            v = _eval(s.value, vs)
            out.append(_tr('{v} := {v2} → 现在算出来 {v3}', v=_fmt(s.target), v2=_fmt(s.value), v3=_b(v)))
            for n in sorted(set(_names(s.value)))[:8]:
                e = _io(io, n)
                out.append(_tr('\u3000{n} = {v}', n=n, v=_b(vs.get(n.upper()))) + (_tr('（{v}）', v=_desc_io(e)) if e else ''))
        elif isinstance(s, stmod.If):
            for cond, _ in s.arms:
                out.append(f'IF {_fmt(cond)} → {_b(_eval(cond, vs))}')
    return {'line': line, 'lines': out or [_tr('这一行不是赋值或 IF，没有可解释的条件')], 'summary': out[0] if out else ''}
