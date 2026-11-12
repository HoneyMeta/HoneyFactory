"""外接 PLC：控制单元的 I/O 交给外部 PLC（实体 PLC、PLCSIM Advanced、CODESYS 软 PLC…）读写。

ExternalPlc 和 PlcRuntime 接口相同（scan(inputs, dt) -> outputs），控制单元不用区分。
真正的通讯由驱动在后台完成（vfactory/plc/drivers/）：
  modbus_server  虚拟工厂当 Modbus TCP 服务器：传感器 → 离散输入 DI / 输入寄存器 IR，执行器 ← 线圈 CO / 保持寄存器 HR（和 Factory I/O 一样）
  modbus         虚拟工厂当 Modbus TCP 客户端，连外部 PLC 的 Modbus 服务器：传感器写到对方线圈/保持寄存器，执行器从对方读
  opcua_server   在虚拟工厂自己的 OPC UA 服务器上发布本单元 I/O：Inputs 只读、Outputs 可写，外部 PLC 用 OPC UA 客户端读写
  opcua          虚拟工厂当 OPC UA 客户端，按节点号读写外部服务器（CODESYS、TIA PLCSIM Advanced 的 OPC UA）
  s7             虚拟工厂当 S7 客户端（自带 S7comm 实现），读写 S7-1200/1500 或 PLCSIM Advanced 的 I/Q/M/DB 区
信号映射表 mapping：[{name: I/O 名, addr: 外部地址}]，没写的按默认规则自动分配（default_mapping）。
实时模式（realtime，默认开）：外接 PLC 连上后把工厂仿真速度限制为 1×，否则外部 PLC 的扫描跟不上仿真时间。
"""
from ..i18n import _tr
import asyncio
import copy
import logging
import time

from .compiler import zero, wrapper
from .st import norm_addr

log = logging.getLogger('vfactory.plc')
PROTOCOLS = {'modbus_server': 'Modbus TCP（虚拟工厂做服务器）', 'modbus': 'Modbus TCP（虚拟工厂做客户端）',
             'opcua_server': 'OPC UA（发布到虚拟工厂的服务器）', 'opcua': 'OPC UA（虚拟工厂做客户端）', 's7': '西门子 S7（S7-1200/1500、PLCSIM Advanced）'}


def _is_bool(ent):
    return (ent.get('type') or 'BOOL').upper() == 'BOOL'


def default_mapping(io, protocol, cfg=None):
    """按协议给每个 I/O 分配外部地址。"""
    cfg = cfg or {}
    out = []
    counters = {}

    def nxt(k, start=0):
        counters[k] = counters.get(k, start)
        v = counters[k]
        return v

    for ent in io:
        nm, d, b = ent.get('name'), ent.get('dir'), _is_bool(ent)
        typ = (ent.get('type') or 'BOOL').upper()
        width = 2 if typ in ('REAL', 'DINT', 'UDINT', 'DWORD') else 1
        if protocol == 'modbus_server':
            k = ('DI' if b else 'IR') if d == 'in' else ('CO' if b else 'HR')
            a = nxt(k)
            counters[k] += 1 if b else width
            addr = f'{k}{a}'
        elif protocol == 'modbus':
            off = int(cfg.get('out_offset', 64)) if d == 'out' else int(cfg.get('in_offset', 0))
            k = 'CO' if b else 'HR'
            key = (k, d)
            a = nxt(key, off)
            counters[key] += 1 if b else width
            addr = f'{k}{a}'
        elif protocol == 'opcua_server':
            addr = f"{'Inputs' if d == 'in' else 'Outputs'}/{nm}"
        elif protocol == 'opcua':
            addr = f"ns=2;s={cfg.get('node_prefix', '')}{nm}"
        elif protocol == 's7':
            na = norm_addr(ent.get('addr') or '')
            if na and na[1] in ('I', 'Q'):
                area = na[1]
                if na[2] == 'X':
                    addr = f'{area}{na[3]}.{na[4]}'
                else:
                    addr = f'{area}{na[2]}{na[3]}'
            else:
                area = 'I' if d == 'in' else 'Q'
                k = (area, b)
                a = nxt(k, 0 if b else 64)
                counters[k] += 1 if b else 2 * width
                addr = f'{area}{a // 8}.{a % 8}' if b else f"{area}{'D' if width == 2 else 'W'}{a}"
        else:
            addr = ''
        out.append({'name': nm, 'dir': d, 'type': typ, 'addr': addr})
    return out


def merged_mapping(io, protocol, cfg):
    """默认映射 + 用户改过的地址。"""
    user = {m.get('name'): m for m in cfg.get('mapping') or [] if m.get('name')}
    out = []
    for m in default_mapping(io, protocol, cfg):
        u = user.get(m['name'])
        if u and str(u.get('addr') or '').strip():
            m = {**m, 'addr': str(u['addr']).strip()}
        out.append(m)
    return out


class ExternalPlc:
    kind = 'external'

    def __init__(self, cfg, io, scan_ms=20):
        self.cfg = dict(cfg or {})
        self.protocol = self.cfg.get('protocol') or 'modbus_server'
        self.io = list(io or [])
        self.scan_ms = float(scan_ms or 20)
        self.mapping = merged_mapping(self.io, self.protocol, self.cfg)
        self.inputs = {e['name']: zero((e.get('type') or 'BOOL').upper()) for e in self.io if e.get('dir') == 'in'}
        self.outputs = {e['name']: zero((e.get('type') or 'BOOL').upper()) for e in self.io if e.get('dir') == 'out'}
        self.forces = {}
        self.status = {'connected': False, 'error': '', 'polls': 0, 'errors': 0, 'last_ms': 0.0, 'since': None, 'peer': ''}
        self.scan_count = 0
        self._drv = None
        from .trace import Tracer
        self.tracer = Tracer([e.get('name') for e in self.io if e.get('name')])
        self._clock = 0.0

    @property
    def state(self):
        """给控制单元看的状态：外部 PLC 连上了算 RUN，没连上算 STOP。"""
        return 'RUN' if self.status.get('connected') else 'STOP'

    def __deepcopy__(self, memo):
        n = ExternalPlc(copy.deepcopy(self.cfg), copy.deepcopy(self.io), self.scan_ms)
        n.tracer = copy.deepcopy(self.tracer, memo)
        n.inputs, n.outputs, n.forces = dict(self.inputs), dict(self.outputs), dict(self.forces)
        return n

    def __getstate__(self):
        d = dict(self.__dict__)
        d['_drv'] = None
        return d

    # -- 与控制单元的接口
    def scan(self, inputs=None, dt=None):
        if inputs:
            for k, v in inputs.items():
                if k in self.inputs:
                    self.inputs[k] = v
        for k, v in self.forces.items():
            if k in self.inputs:
                self.inputs[k] = v
        self.scan_count += 1
        drv = self._drv
        if drv is not None:
            try:
                drv.on_scan()
            except Exception as e:                  # 驱动出错不影响仿真
                self.status['error'] = str(e)
        out = dict(self.outputs)
        for k, v in self.forces.items():
            if k in out:
                out[k] = v
        self._clock += float(dt or self.scan_ms / 1000)
        self.tracer.record(int(self._clock * 1000), tuple(self.inputs.get(e.get('name')) if e.get('dir') != 'out' else out.get(e.get('name'))
                                                         for e in self.io if e.get('name')))
        return out

    def label(self):
        return _tr('外接 PLC') + (_tr('（已连接）') if self.status.get('connected') else _tr('（未连接）'))

    def halt_info(self):
        return None

    def cycle(self, inputs, dt):
        return self.scan(inputs, dt)

    def typ(self, name):
        for e in self.io:
            if e.get('name') == name:
                return (e.get('type') or 'BOOL').upper()
        return None

    def set_output(self, name, value):
        t = self.typ(name)
        if t:
            try:
                self.outputs[name] = wrapper(t)(value)
            except (TypeError, ValueError):
                pass

    def force(self, name, value):
        t = self.typ(name)
        if not t:
            return _tr('没有 I/O {name}', name=name)
        if value is None:
            self.forces.pop(name, None)
            return ''
        from .runtime import _coerce
        try:
            self.forces[name] = _coerce(t, value)
        except (TypeError, ValueError):
            return _tr('值 {value} 不是 {t}', value=value, t=t)
        return ''

    def unforce_all(self):
        self.forces.clear()

    def online(self, ld=True):
        io = []
        maddr = {m['name']: m['addr'] for m in self.mapping}
        for e in self.io:
            nm = e.get('name')
            v = self.forces.get(nm, self.inputs.get(nm) if e.get('dir') == 'in' else self.outputs.get(nm))
            io.append({'name': nm, 'addr': e.get('addr'), 'dir': e.get('dir'), 'type': e.get('type') or 'BOOL', 'value': v,
                       'forced': nm in self.forces, 'ext': maddr.get(nm, ''), 'comment': e.get('comment') or e.get('desc') or ''})
        return {'state': 'EXTERNAL', 'state_cn': _tr('外接 PLC') + (_tr('（已连接）') if self.status.get('connected') else _tr('（未连接）')), 'external': {'protocol': self.protocol, 'protocol_cn': PROTOCOLS.get(self.protocol, ''),
                                                                             'endpoint': self.endpoint(), **self.status},
                'vars': {**self.inputs, **self.outputs}, 'forced': dict(self.forces), 'io': io, 'scan': {'count': self.scan_count, 'cycle_ms': self.scan_ms},
                'ld': {}, 'rungs': [], 'bps': []}

    def info(self):
        return {'state': 'EXTERNAL', 'label': self.label(), 'run': self.state, 'protocol': self.protocol, 'connected': self.status['connected'], 'error': self.status['error']}

    def endpoint(self):
        c = self.cfg
        if self.protocol == 'modbus_server':
            return _tr('0.0.0.0:{get}（Unit {get2}）', get=c.get('port', 1502), get2=c.get('unit', 1))
        if self.protocol == 'opcua_server':
            return _tr('虚拟工厂 OPC UA 服务器')
        return str(c.get('endpoint') or c.get('host') or '')

    # -- 驱动
    async def start(self, ctx):
        await self.stop()
        from .drivers import make_driver
        self._drv = make_driver(self, ctx)
        await self._drv.start()

    async def stop(self):
        d, self._drv = self._drv, None
        if d is not None:
            try:
                await d.stop()
            except Exception:
                log.exception(_tr('外接 PLC 驱动停止失败'))
        self.status['connected'] = False


class PollingDriver:
    """客户端类驱动的公共部分：周期交换、断线重连、实时模式。"""
    def __init__(self, ext: ExternalPlc, ctx):
        self.ext, self.ctx = ext, ctx or {}
        self.task = None
        self.period = max(0.01, float(ext.cfg.get('poll_ms') or ext.scan_ms) / 1000)

    async def start(self):
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        await self.close()

    def on_scan(self):
        pass

    async def connect(self):
        raise NotImplementedError

    async def exchange(self):
        raise NotImplementedError

    async def close(self):
        pass

    def realtime(self):
        rt = self.ctx.get('rt')
        if rt is not None and self.ext.cfg.get('realtime', True) and self.ext.status['connected']:
            p = rt.plant
            if p.speed > 1:
                p.speed = 1.0
                try:
                    p.log(self.ctx.get('bid', 'PLC'), 'info', _tr('外接 PLC 已连接：实时模式，仿真速度限制为 1×'))
                except Exception:
                    pass

    async def _loop(self):
        st = self.ext.status
        while True:
            try:
                if not st['connected']:
                    await self.connect()
                    st['connected'] = True
                    st['error'] = ''
                    st['since'] = time.time()
                t0 = time.perf_counter()
                await self.exchange()
                st['polls'] += 1
                st['last_ms'] = round((time.perf_counter() - t0) * 1000, 2)
                self.realtime()
                await asyncio.sleep(self.period)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                st['errors'] += 1
                st['error'] = f'{type(e).__name__}: {e}' if str(e) else type(e).__name__
                st['connected'] = False
                try:
                    await self.close()
                except Exception:
                    pass
                await asyncio.sleep(2.0)
