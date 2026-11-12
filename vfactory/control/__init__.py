"""控制层：设备级场景仿真（CellSim）、控制单元部件目录、场景库、评分。

  from vfactory.control import CellSim, auto_io, validate_cell
  sim = CellSim(cell_def, rng)       # 见 sim.py
"""
from ..i18n import _tr
import re

from . import catalog
from .catalog import auto_io, signals
from .sim import DT, CellSim

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def validate_cell(cell) -> list:
    """检查单元定义，返回 [(级别 'error'|'warn', 说明)]。"""
    out = []
    if not isinstance(cell, dict):
        return [('error', _tr('单元定义格式不对'))]
    comps = cell.get('components') or []
    ids = {}
    for c in comps:
        cid = str(c.get('id') or '')
        if not IDENT.match(cid):
            out.append(('error', _tr('部件编号“{cid}”只能用字母开头的字母、数字、下划线', cid=cid)))
        if cid in ids:
            out.append(('error', _tr('部件编号 {cid} 重复', cid=cid)))
        ids[cid] = c
        if c.get('type') not in catalog.COMP_TYPES:
            out.append(('error', _tr('部件 {cid} 的类型 {get} 不存在', cid=cid, get=c.get("type"))))
    for c in comps:
        t, p = c.get('type'), c.get('params') or {}
        if t in catalog.CONVEYORS and p.get('motor') and (ids.get(p['motor']) or {}).get('type') != 'motor':
            out.append(('error', _tr('输送机 {id} 指定的电机 {motor} 不存在', id=c["id"], motor=p["motor"])))
        if t == 'encoder' and (ids.get(p.get('conveyor') or '') or {}).get('type') not in catalog.CONVEYORS:
            out.append(('warn', _tr('编码器 {id} 没有指定要测的输送机', id=c["id"])))
        if t == 'stacker_crane' and not p.get('targets') and (ids.get(p.get('rack') or '') or {}).get('type') != 'rack':
            out.append(('warn', _tr('堆垛机 {id} 没有指定货架，也没有自定义目标点', id=c["id"])))
    names, addrs = {}, {}
    for e in cell.get('io') or []:
        nm = str(e.get('name') or '')
        if not IDENT.match(nm):
            out.append(('error', _tr('I/O 名称“{nm}”只能用字母开头的字母、数字、下划线（PLC 里当变量名用）', nm=nm)))
        if nm in names:
            out.append(('error', _tr('I/O 名称 {nm} 重复', nm=nm)))
        names[nm] = e
        a = str(e.get('addr') or '').upper().replace('%IX', '%I').replace('%QX', '%Q')
        if a:
            if a in addrs:
                out.append(('error', _tr('地址 {get} 被 {v} 和 {nm} 重复使用', get=e.get("addr"), v=addrs[a], nm=nm)))
            addrs[a] = nm
            if e.get('dir') == 'in' and not a.startswith('%I') or e.get('dir') == 'out' and not a.startswith('%Q'):
                out.append(('warn', _tr('{nm}：{v}点的地址一般用 {v2}', nm=nm, v=_tr('输入') if e.get("dir") == "in" else _tr('输出'), v2="%I" if e.get("dir") == "in" else "%Q")))
        c = ids.get(e.get('comp'))
        if c is None:
            out.append(('error', _tr('I/O {nm} 对应的部件 {get} 不存在', nm=nm, get=e.get("comp"))))
            continue
        sg = signals(c)
        have = {s[0]: (d, s[1]) for d in ('in', 'out') for s in sg[d]}
        if e.get('signal') not in have:
            out.append(('error', _tr('I/O {nm}：部件 {id} 没有信号 {get}（可用：{v}）', nm=nm, id=c["id"], get=e.get("signal"), v=_tr('、').join(have) or _tr('无'))))
        elif have[e['signal']][0] != e.get('dir'):
            out.append(('error', _tr('I/O {nm}：信号 {signal} 的方向应该是 {v}', nm=nm, signal=e["signal"], v=have[e["signal"]][0])))
    plc = cell.get('plc') or {}
    if plc.get('mode') not in (None, '', 'internal', 'external'):
        out.append(('error', _tr('PLC 方式 {get} 不对（internal 内置 / external 外接）', get=plc.get("mode"))))
    if not comps:
        out.append(('warn', _tr('单元里还没有部件')))
    return out


__all__ = ['CellSim', 'DT', 'auto_io', 'signals', 'validate_cell', 'catalog']
