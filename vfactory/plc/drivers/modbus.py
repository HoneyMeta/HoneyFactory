"""Modbus TCP 外接驱动。

地址写法：CO12 线圈(0x)、DI3 离散输入(1x)、IR4 输入寄存器(3x)、HR10 保持寄存器(4x)；地址从 0 开始（协议地址）。
寄存器编码：BOOL → 0/1；INT → 16 位有符号；DINT/UDINT/DWORD → 两个寄存器（高字在前）；REAL → float32（ABCD，高字在前）。
"""
from ...i18n import _tr
import re
import struct

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import ModbusTcpServer

from ..external import PollingDriver

ADDR = re.compile(r'^(CO|DI|IR|HR)(\d+)$', re.I)
FC = {'CO': 1, 'DI': 2, 'HR': 3, 'IR': 4}
WIDE = {'DINT', 'UDINT', 'DWORD', 'REAL', 'LREAL'}


def parse_addr(a):
    m = ADDR.match(str(a or '').strip())
    if not m:
        raise ValueError(_tr('Modbus 地址写法不对：{a}（例：CO0 线圈、DI0 离散输入、IR0 输入寄存器、HR0 保持寄存器）', a=a))
    return m.group(1).upper(), int(m.group(2))


def width(t):
    return 2 if t in WIDE else 1


def encode(t, v):
    if t == 'BOOL':
        return [1 if v else 0]
    if t in ('REAL', 'LREAL'):
        hi, lo = struct.unpack('>HH', struct.pack('>f', float(v or 0)))
        return [hi, lo]
    if t in WIDE:
        x = int(v or 0) & 0xFFFFFFFF
        return [x >> 16, x & 0xFFFF]
    return [int(v or 0) & 0xFFFF]


def decode(t, regs):
    if t == 'BOOL':
        return bool(regs[0])
    if t in ('REAL', 'LREAL'):
        return struct.unpack('>f', struct.pack('>HH', regs[0] & 0xFFFF, regs[1] & 0xFFFF))[0]
    if t in WIDE:
        x = ((regs[0] & 0xFFFF) << 16) | (regs[1] & 0xFFFF)
        return x - (1 << 32) if t == 'DINT' and x >= 1 << 31 else x
    x = regs[0] & 0xFFFF
    return x - 65536 if t in ('INT', 'SINT') and x > 32767 else x


def plan(mapping):
    """→ (写出列表, 读入列表)：[(名称, 类型, 区, 地址)]"""
    w, r = [], []
    for m in mapping:
        area, a = parse_addr(m['addr'])
        t = (m.get('type') or 'BOOL').upper()
        (w if m['dir'] == 'in' else r).append((m['name'], t, area, a))
    return w, r


class ModbusServerDriver:
    """虚拟工厂当服务器：外部 PLC（客户端）读传感器（DI/IR），写执行器（CO/HR）。每次扫描直接读写数据区。"""
    SIZE = 2048

    def __init__(self, ext, ctx):
        self.ext, self.ctx = ext, ctx or {}
        self.port = int(ext.cfg.get('port') or 1502)
        z = lambda: ModbusSequentialDataBlock(0, [0] * self.SIZE)  # noqa: E731
        self.slave = ModbusSlaveContext(di=z(), co=z(), hr=z(), ir=z())
        self.context = ModbusServerContext(slaves=self.slave, single=True)
        self.writes, self.reads = plan(ext.mapping)
        for _, _, area, a in self.writes + self.reads:
            if a + 2 >= self.SIZE:
                raise ValueError(_tr('Modbus 地址 {area}{a} 超出范围 0..{v}', area=area, a=a, v=self.SIZE - 3))
        for _, _, area, _ in self.writes:
            if area not in ('DI', 'IR', 'CO', 'HR'):
                raise ValueError(_tr('传感器只能映射到 DI/IR（或 CO/HR）'))
        self.clients = 0
        self.server = None
        self.task = None

    def _count(self):
        n = len(getattr(self.server, 'active_connections', None) or {}) if self.server is not None else 0
        if n != self.clients:
            self.clients = n
            self.ext.status['peer'] = _tr('{n} 个客户端', n=n)
        if n:
            rt = self.ctx.get('rt')
            if rt is not None and self.ext.cfg.get('realtime', True) and rt.plant.speed > 1:
                rt.plant.speed = 1.0
                try:
                    rt.plant.log(self.ctx.get('bid', 'PLC'), 'info', _tr('外接 PLC 已连接：实时模式，仿真速度限制为 1×'))
                except Exception:
                    pass

    async def start(self):
        import asyncio
        self.server = ModbusTcpServer(context=self.context, address=('0.0.0.0', self.port))
        self.task = asyncio.create_task(self.server.serve_forever())
        await asyncio.sleep(0.05)
        self.ext.status.update(connected=True, error='', peer=_tr('0 个客户端'))
        self.on_scan()

    async def stop(self):
        if self.server is not None:
            try:
                await self.server.shutdown()
            except Exception:
                pass
        if self.task:
            self.task.cancel()
        self.server = None

    def on_scan(self):
        ext, sl = self.ext, self.slave
        for name, t, area, a in self.writes:
            v = ext.inputs.get(name)
            if area in ('DI', 'CO'):
                sl.setValues(FC[area], a, [bool(v)])
            else:
                sl.setValues(FC[area], a, encode(t, v))
        for name, t, area, a in self.reads:
            if area in ('CO', 'DI'):
                ext.set_output(name, bool(sl.getValues(FC[area], a, 1)[0]))
            else:
                ext.set_output(name, decode(t, sl.getValues(FC[area], a, width(t))))
        ext.status['polls'] += 1
        self._count()


def _spans(items):
    """把同一区的地址合并成连续块：[(区, 起始, 长度)]。"""
    by = {}
    for name, t, area, a in items:
        w = 1 if area in ('CO', 'DI') else width(t)
        by.setdefault(area, []).append((a, a + w))
    out = []
    for area, rs in by.items():
        rs.sort()
        s, e = rs[0]
        for a, b in rs[1:]:
            if a <= e + 8 and b - s <= 120:
                e = max(e, b)
            else:
                out.append((area, s, e - s))
                s, e = a, b
        out.append((area, s, e - s))
    return out


class ModbusClientDriver(PollingDriver):
    """虚拟工厂当客户端：把传感器写到外部服务器的线圈/保持寄存器，从外部读执行器。"""
    def __init__(self, ext, ctx):
        super().__init__(ext, ctx)
        ep = str(ext.cfg.get('endpoint') or ext.cfg.get('host') or '127.0.0.1:502')
        host, _, port = ep.rpartition(':') if ':' in ep else (ep, '', '502')
        self.host, self.port = host or '127.0.0.1', int(port or 502)
        self.unit = int(ext.cfg.get('unit') or 1)
        self.writes, self.reads = plan(ext.mapping)
        for name, t, area, a in self.writes:
            if area not in ('CO', 'HR'):
                raise ValueError(_tr('客户端模式下传感器 {name} 只能写到线圈 CO 或保持寄存器 HR', name=name))
        self.client = None
        self.ext.status['peer'] = f'{self.host}:{self.port}'

    async def connect(self):
        self.client = AsyncModbusTcpClient(self.host, port=self.port, timeout=2, retries=0)
        ok = await self.client.connect()
        if not ok:
            raise ConnectionError(_tr('连不上 {host}:{port}', host=self.host, port=self.port))

    async def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    async def exchange(self):
        c, ext, u = self.client, self.ext, self.unit
        # 写传感器：按区合并
        for area, start, n in _spans(self.writes):
            if area == 'CO':
                vals = [False] * n
                for name, t, ar, a in self.writes:
                    if ar == 'CO' and start <= a < start + n:
                        vals[a - start] = bool(ext.inputs.get(name))
                if n == 1:
                    r = await c.write_coil(start, vals[0], slave=u)
                else:
                    r = await c.write_coils(start, vals, slave=u)
            else:
                vals = [0] * n
                for name, t, ar, a in self.writes:
                    if ar == 'HR' and start <= a < start + n:
                        enc = encode(t, ext.inputs.get(name))
                        vals[a - start:a - start + len(enc)] = enc
                r = await c.write_registers(start, vals, slave=u)
            if r.isError():
                raise IOError(_tr('写 {area}{start} 失败：{r}', area=area, start=start, r=r))
        for area, start, n in _spans(self.reads):
            if area == 'CO':
                r = await c.read_coils(start, count=n, slave=u)
            elif area == 'DI':
                r = await c.read_discrete_inputs(start, count=n, slave=u)
            elif area == 'HR':
                r = await c.read_holding_registers(start, count=n, slave=u)
            else:
                r = await c.read_input_registers(start, count=n, slave=u)
            if r.isError():
                raise IOError(_tr('读 {area}{start} 失败：{r}', area=area, start=start, r=r))
            data = r.bits if area in ('CO', 'DI') else r.registers
            for name, t, ar, a in self.reads:
                if ar == area and start <= a < start + n:
                    if area in ('CO', 'DI'):
                        ext.set_output(name, bool(data[a - start]))
                    else:
                        ext.set_output(name, decode(t, data[a - start:a - start + width(t)]))
