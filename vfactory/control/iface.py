"""生产设备的控制接口（4.3）：每台生产设备对 PLC 暴露一组点，PLC 块通过信号线读写。

  st.ctl_points()          → [{name, dir:'in'|'out', type:'BOOL'|'INT'|'REAL', label, unit?}]
                             dir 以 PLC 为准：in = 设备 → PLC（状态/传感器），out = PLC → 设备（命令/设定）
                             = catalog.CONTROL_POINTS + 块类型自己的点（BLOCK_TYPES[type]['control']）；控制单元 = 它的 I/O 表
  st.ctl_get(point)        → 当前值（in 点：Running / Fault / PartIn / Count / 类型自有点；out 点返回 PLC 最近写入的值）
  st.ctl_set(point, value) → '' 或错误说明（out 点：Enable / Reset / 类型自有点）
  st._plc_wired            = {'Enable', …}：PLC 层在第一次扫描前写入"接了线的 out 点"；没有这个属性 = 没接 PLC，设备照旧自己运行

规则
- 没接 PLC（_plc_wired 为空）时设备行为与以前完全一样。
- 接了 Enable：只有 Enable=1 才开始新的工作；正在加工的这一件做完（通用块在取料处判断）。
  连续过程类设备（高级模型）、来料、输送线在 Enable=0 时整体暂停。状态 WaitPLC（"等待 PLC 允许"），时间类别 wait_plc。
- 输送线另有 Run（运行命令）：接了 Run 时只有 Run=1 才走带。
- Reset 上升沿：清故障（与"清除故障"相同：人工注入的故障、报警、正在修复的故障）。
- Count = 累计完成件数；PartIn = 有工件在等待加工或正在加工。
"""
from __future__ import annotations

from ..i18n import _tr
from ..flow.catalog import BLOCK_TYPES, CONTROL_POINTS

GATES = ('Enable', 'Run')            # 门控点：接了线且为 0 时设备不开始新工作
WAIT_STATE, WAIT_CLS = 'WaitPLC', 'wait_plc'
WAIT_LABEL = '等待 PLC 允许'


def _spec(typ):
    return (BLOCK_TYPES.get(typ) or {}).get('control') or {}


def points_of_type(typ) -> list:
    """块类型的控制点（默认点 + 类型自有点，同名时类型的覆盖默认的）。"""
    sp = _spec(typ)
    if sp.get('none'):
        return []
    skip = set(sp.get('exclude') or [])
    out, seen = [], {}
    for d in ('in', 'out'):
        for p in list(CONTROL_POINTS.get(d) or []) + list(sp.get(d) or []):
            if p['name'] in skip:
                continue
            e = {'name': p['name'], 'dir': d, 'type': p.get('type', 'BOOL'), 'label': p.get('label', p['name'])}
            if p.get('unit'):
                e['unit'] = p['unit']
            if p.get('help'):
                e['help'] = p['help']
            if p['name'] in seen:
                out[seen[p['name']]] = e
            else:
                seen[p['name']] = len(out)
                out.append(e)
    return out


def _tag_of(st, name):
    for d in ('in', 'out'):
        for p in _spec(st.cfg.get('type')).get(d) or []:
            if p['name'] == name and p.get('tag'):
                return p['tag']
    return None


def _cast(typ, v):
    try:
        if typ == 'BOOL':
            return bool(v) if not isinstance(v, str) else v.strip().lower() in ('1', 'true', 'on', 'yes')
        if typ == 'INT':
            return int(float(v or 0))
        return float(v or 0)
    except (TypeError, ValueError):
        return False if typ == 'BOOL' else 0


def _outs(st) -> dict:
    d = st.__dict__.get('_ctl_out')
    if d is None:
        d = st.__dict__['_ctl_out'] = {}
    return d


# ---------------- 需要换算的类型自有点 ----------------
def _digits(v):
    s = ''.join(ch for ch in str(v or '') if ch.isdigit())
    return int(s) if s else 0


def _buf_full(st):
    q = st.plant.buffers.get(st.id)
    return bool(q is not None and q.full())


SPECIAL = {('cnc', 'ProgramNo'): lambda st: _digits(st.get('Production/ActiveProgram/Name')),
           ('cnc', 'ToolNo'): lambda st: _digits(st.get('Tools/ActiveTool')),
           ('inspection', 'LastOK'): lambda st: st.get('Result/Last') == 'OK',
           ('buffer', 'Full'): _buf_full}


# ---------------- 默认的 in 点 ----------------
def _count(st):
    sp = _spec(st.cfg.get('type'))
    tags = sp.get('count')
    if tags:
        tags = [tags] if isinstance(tags, str) else tags
        n = 0
        for t in tags:
            v = st.tags.get(t)
            if v is not None and isinstance(v.value, (int, float)):
                n += v.value
        return int(n)
    c = getattr(st, 'count', None)
    if isinstance(c, int) and not isinstance(c, bool):
        return c
    t = st.tags.get('Production/Count')
    return int(t.value) if t is not None and isinstance(t.value, (int, float)) else 0


def _partin(st):
    sp = _spec(st.cfg.get('type'))
    if sp.get('partin'):
        t = st.tags.get(sp['partin'])
        return bool(t is not None and t.value)
    f = getattr(st, 'ctl_partin', None)
    if f is not None:
        return bool(f())
    t = st.tags.get('Production/InProcess')
    if t is not None and isinstance(t.value, (int, float)) and t.value > 0:
        return True
    av = getattr(st, 'available', None)
    if callable(av) and getattr(st, 'ins', None) is not None:
        try:
            if av() > 0:
                return True
        except (TypeError, KeyError):
            pass
    if getattr(st, 'part', None) is not None:
        return True
    t = st.tags.get('Production/CurrentPart')
    return bool(t is not None and t.value)


def _fault(st):
    return bool(st.failure.repair_left > 0 or (st.state == 'Stopped' and st.enabled))


# ---------------- 装到 Station 上的方法 ----------------
def ctl_points(self) -> list:
    return points_of_type(self.cfg.get('type'))


def ctl_get(self, name):
    o = _outs(self)
    if name in o:
        return o[name]
    if name == 'Running':
        return self.state == 'Executing'
    if name == 'Fault':
        return _fault(self)
    if name == 'PartIn':
        return _partin(self)
    if name == 'Count':
        return _count(self)
    sp = SPECIAL.get((self.cfg.get('type'), name))
    if sp is not None:
        return sp(self)
    tag = _tag_of(self, name)
    if tag and tag in self.tags:
        v = self.tags[tag].value
        typ = next((p['type'] for p in self.ctl_points() if p['name'] == name), 'REAL')
        return _cast(typ, v)
    if name in GATES or name == 'Reset':
        return False
    return None


def ctl_set(self, name, value) -> str:
    pts = {p['name']: p for p in self.ctl_points()}
    p = pts.get(name)
    if p is None:
        return _tr('{name} 没有控制点 {name2}', name=self.name, name2=name)
    if p['dir'] != 'out':
        return _tr('{name} 是设备发给 PLC 的点，不能写', name=name)
    v = _cast(p['type'], value)
    o = _outs(self)
    prev = o.get(name)
    o[name] = v
    if name == 'Reset':
        if v and not prev and (_fault(self) or self.alarm):
            self.inject('clear')
            self.plant.log(self.id, 'repair', _tr('PLC 故障复位'))
        return ''
    tag = _tag_of(self, name)
    if tag and tag in self.tags:
        t = self.tags[tag]
        if t.dtype == 'bool':
            v = bool(v)
        if t.dtype in ('int', 'float'):
            if t.lo is not None:
                v = max(t.lo, v)
            if t.hi is not None:
                v = min(t.hi, v)
        if t.value != v:
            t.value = v
            self.on_write(tag, v)
    return ''


def ctl_hold(self) -> bool:
    """接了 Enable（或 Run）且为 0：不开始新的工作。"""
    w = self._plc_wired
    if not w:
        return False
    o = _outs(self)
    return any(g in w and not o.get(g) for g in GATES)


def ctl_hold_tick(self) -> bool:
    """整步暂停（Station.tick 调用）。在取料处门控的通用块这里不暂停，正在加工的件照常做完。"""
    if self._ctl_gate == 'take':
        self._ctl_refused = False
        return False
    return self.ctl_hold()


def ctl_after_step(self):
    """通用块：本步因为没给允许而没取料、又没有别的事做 → 状态记为"等待 PLC 允许"。"""
    if self._ctl_gate == 'take' and self.__dict__.get('_ctl_refused') and self.state in ('Starved', 'Idle'):
        self.state = WAIT_STATE


def ctl_bind(self, out_points):
    """（便捷）声明 PLC 接了哪些 out 点；None / 空 = 不接 PLC。与直接设置 _plc_wired 等价。"""
    self._plc_wired = set(out_points or ())
    if not self._plc_wired:
        _outs(self).clear()


def bind_plant(plant, model=None):
    """按模型里的信号线给每台设备设 _plc_wired（PLC 层可以直接用；测试也用）。"""
    links = (model if isinstance(model, list) else (model or plant.cfg).get('links')) or []
    wired: dict = {}
    for l in links:
        if l.get('kind') != 'signal':
            continue
        for s in l.get('signals') or []:
            if s.get('dir') == 'out' and s.get('point'):
                dev = l['from'] if (plant.find(l['from']) is not None and plant.find(l['from']).cfg.get('type') != 'plc') else l['to']
                wired.setdefault(dev, set()).add(s['point'])
    for st in plant.all_stations():
        if st.cfg.get('type') == 'plc':
            continue
        if st.id in wired or st._plc_wired:
            st.ctl_bind(wired.get(st.id))
    return wired


def install(Station):
    Station._plc_wired = ()
    Station._ctl_gate = 'freeze'          # freeze：Enable=0 时整体暂停；take：通用块在取料处门控
    Station._ctl_refused = False
    for f in (ctl_points, ctl_get, ctl_set, ctl_hold, ctl_hold_tick, ctl_after_step, ctl_bind):
        if not hasattr(Station, f.__name__):
            setattr(Station, f.__name__, f)
