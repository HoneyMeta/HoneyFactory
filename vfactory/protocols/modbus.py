"""Modbus TCP 从站：模拟国产 PLC / 仪表的"点表"风格。

- 每台设备一个从站地址（Unit ID）：设备参数 modbus_unit 固定；没写的按设备顺序从 11 起自动分配（跳过 10）；
- 模型里写死的点位（例如砂处理 Unit1 HR0 水分 ÷100）保持原地址不变；
- 其余所有数值点自动分配到保持寄存器（协议设置 modbus.base 起，默认 1000），数据类型和字序可选：
  int16 / uint16（×缩放）、int32 / uint32、float32（默认）、float64；字序 ABCD / CDAB / BADC / DCBA；
  开关量 → 线圈（同址镜像到离散输入）；运行状态 Common/State → int16 状态码；Common/Alarm → "有报警"线圈（只读）；
  保持寄存器同址镜像到输入寄存器（功能码 04 也能读）；
- 可写点位（设定值）映射到可写保持寄存器 / 线圈：写入当场校验，越界返回异常码 03（可在协议设置里允许越界），写只读地址返回 02；
- 读写时按需从模型取值（没有轮询比对），数据冻结 / 卡死 / 漂移按通讯故障规则变换；
- 标准异常码：地址越界 02、值非法 03、从站故障 04（坏质量故障）、不存在的从站 0B（或按设置不响应）；
- 通讯故障：延迟 / 抖动推迟应答，丢包不应答，断开关闭端口（设备级断开 = 该从站返回 0B）；
- 4.3 有网关的工厂：单元地址不变（兼容），每台设备的读写经它的主网关；网络线 / 交换机 / 网关故障按路径作用（断开 = 异常码 0B）；
- Unit 10 是全厂电能表：每个区域 4 个寄存器 = float32 实时功率 kW + float32 累计电能 kWh（字序按设置，默认 ABCD）。
"""
from ..i18n import _tr
import asyncio
import logging
import struct
import time

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.exceptions import NoSuchSlaveException
from pymodbus.pdu.pdu import ExceptionResponse
from pymodbus.server import ModbusTcpServer
from pymodbus.server.requesthandler import ServerRequestHandler

from .. import comm

log = logging.getLogger('vfactory.modbus')
METER_UNIT = 10
STATE_CODE = {'Idle': 0, 'Executing': 1, 'Starved': 2, 'Blocked': 3, 'Stopped': 4, 'Setup': 5, 'Planned': 6}
WRITE_FC = (5, 6, 15, 16, 22, 23)
COIL_FC = (1, 2, 5, 15)


class ModbusFault(Exception):
    def __init__(self, code, msg=''):
        super().__init__(msg)
        self.code = code


def f32(x):
    hi, lo = struct.unpack('>HH', struct.pack('>f', float(x)))
    return [hi, lo]


def _order(b: bytes, order):
    """大端字节串 → 按字序排列（ABCD 原样，CDAB 字交换，BADC 字内字节交换，DCBA 全反）。"""
    if order == 'CDAB':
        w = [b[i:i + 2] for i in range(0, len(b), 2)]
        return b''.join(reversed(w))
    if order == 'BADC':
        return b''.join(b[i:i + 2][::-1] for i in range(0, len(b), 2))
    if order == 'DCBA':
        return b[::-1]
    return b


def encode(v, fmt, order='ABCD', scale=1):
    v = 0 if v is None or (isinstance(v, float) and v != v) else v
    if isinstance(v, bool):
        v = int(v)
    if fmt in ('int16', 'uint16', 'int32', 'uint32'):
        n = int(round(float(v) * (scale or 1)))
        if fmt == 'int16':
            b = struct.pack('>h', max(-32768, min(32767, n)))
        elif fmt == 'uint16':
            b = struct.pack('>H', max(0, min(65535, n)))
        elif fmt == 'int32':
            b = struct.pack('>i', max(-2 ** 31, min(2 ** 31 - 1, n)))
        else:
            b = struct.pack('>I', max(0, min(2 ** 32 - 1, n)))
    elif fmt == 'float64':
        b = struct.pack('>d', float(v))
    else:
        b = struct.pack('>f', float(v))
    if len(b) > 2:
        b = _order(b, order)
    return list(struct.unpack('>' + 'H' * (len(b) // 2), b))


def decode(regs, fmt, order='ABCD', scale=1):
    b = struct.pack('>' + 'H' * len(regs), *[r & 0xFFFF for r in regs])
    if len(b) > 2:
        b = _order(b, order)              # 四种字序都是自逆的
    if fmt == 'int16':
        return struct.unpack('>h', b)[0] / (scale or 1)
    if fmt == 'uint16':
        return struct.unpack('>H', b)[0] / (scale or 1)
    if fmt == 'int32':
        return struct.unpack('>i', b)[0] / (scale or 1)
    if fmt == 'uint32':
        return struct.unpack('>I', b)[0] / (scale or 1)
    if fmt == 'float64':
        return struct.unpack('>d', b)[0]
    return struct.unpack('>f', b)[0]


class Point:
    __slots__ = ('st', 'tag', 'unit', 'kind', 'addr', 'n', 'fmt', 'order', 'scale', 'writable', 'auto', 'conv', 'desc', 'eng_unit')

    def __init__(self, st, tag, unit, kind, addr, fmt='int16', order='ABCD', scale=1, writable=False, auto=False, conv=None):
        self.st, self.tag, self.unit, self.kind, self.addr = st, tag, unit, kind, addr
        self.fmt, self.order, self.scale, self.auto, self.conv = fmt, order, scale, auto, conv
        self.n = 1 if kind == 'coil' else comm.FMTS.get(fmt, 1)
        self.writable = writable
        t = st.tags.get(tag)
        self.desc = (t.desc if t else '') + (_tr('（状态码：') + _tr('、').join(f'{v}={k}' for k, v in STATE_CODE.items()) + _tr('）') if conv == 'state' else
                                             _tr('（有报警 = 1）') if conv == 'alarm' else '')
        self.eng_unit = t.unit if t else ''


class UnitContext(ModbusSlaveContext):
    """一个从站：读时按需从模型刷新，写时当场写进模型。"""

    def __init__(self, adapter, unit, n_co, n_hr):
        self.adapter, self.unit = adapter, unit
        super().__init__(di=ModbusSequentialDataBlock(0, [0] * (n_co + 1)), co=ModbusSequentialDataBlock(0, [0] * (n_co + 1)),
                         hr=ModbusSequentialDataBlock(0, [0] * (n_hr + 1)), ir=ModbusSequentialDataBlock(0, [0] * (n_hr + 1)))
        self.regs: dict[int, Point] = {}
        self.coils: dict[int, Point] = {}

    def validate(self, fc_as_hex, address, count=1):
        if not super().validate(fc_as_hex, address, count):
            return False
        if fc_as_hex in WRITE_FC:
            table = self.coils if fc_as_hex in (5, 15) else self.regs
            for a in range(address, address + count):
                pt = table.get(a)
                if pt is None or not pt.writable:
                    return False                  # 写只读或没有映射的地址 → 异常码 02
        return True

    async def async_getValues(self, fc_as_hex, address, count=1):
        self.adapter.refresh(self, fc_as_hex, address, count)
        return self.getValues(fc_as_hex, address, count)

    async def async_setValues(self, fc_as_hex, address, values):
        self.setValues(fc_as_hex, address, values)
        self.adapter.apply_write(self, fc_as_hex, address, len(values))


class VfRequestHandler(ServerRequestHandler):
    """应答带上正确的功能码（原版对不存在的从站回 0x80 畸形包），并实现延迟 / 抖动 / 丢包 / 坏质量。"""

    def callback_data(self, data, addr=None):
        try:
            used = super(ServerRequestHandler, self).callback_data(data, addr)
        except Exception:
            self.server_send(ExceptionResponse(0x01, exception_code=ExceptionResponse.ILLEGAL_FUNCTION), 0)
            return len(data)
        if self.last_pdu:
            pdu, a = self.last_pdu, self.last_addr
            self.loop.create_task(self._handle(pdu, a))
        return used

    async def _handle(self, pdu, addr):
        ad = self.server.vf
        fc = pdu.function_code
        unit = pdu.dev_id
        response = None
        try:
            delay, drop, exc = ad.request_fault(unit, fc, getattr(pdu, 'address', 0), getattr(pdu, 'count', 1))
            if delay > 0:
                await asyncio.sleep(delay)
            if drop:
                return
            if exc:
                response = ExceptionResponse(fc, exc)
            else:
                try:
                    ctx = self.server.context[unit]
                except NoSuchSlaveException:
                    if comm.settings(ad.plant)['modbus'].get('missing_unit') == 'silent':
                        return
                    response = ExceptionResponse(fc, ExceptionResponse.GATEWAY_NO_RESPONSE)
                else:
                    response = await pdu.update_datastore(ctx)
        except ModbusFault as e:
            response = ExceptionResponse(fc, e.code)
        except Exception:
            log.exception(_tr('Modbus 处理请求出错'))
            response = ExceptionResponse(fc, ExceptionResponse.SLAVE_FAILURE)
        if response is None:
            return
        response.transaction_id = pdu.transaction_id
        response.dev_id = pdu.dev_id
        try:
            self.server_send(response, addr)
        except Exception:
            pass


class VfTcpServer(ModbusTcpServer):
    def __init__(self, adapter, **kw):
        super().__init__(**kw)
        self.vf = adapter

    def callback_new_connection(self):
        return VfRequestHandler(self, self.trace_packet, self.trace_pdu, self.trace_connect)


class ModbusAdapter:
    def __init__(self, plant, port=5020, period=0.5):
        self.plant, self.port, self.period = plant, port, period
        self.slaves = {}
        self.server = None
        self.ctx = ModbusServerContext(slaves={0: None}, single=False)
        self.rebuild()

    # ---------- 点表 ----------
    def _units(self):
        """设备 → 从站地址。配置里写了的固定；其余从 11 起按设备顺序分配。"""
        used = {METER_UNIT}
        fixed = {}
        for st in self.plant.stations.values():
            u = st.cfg.get('modbus_unit')
            if not u:
                u = next((t.modbus.get('unit') for t in st.tags.values() if t.modbus and t.modbus.get('unit')), None)
            try:
                u = int(u) if u else None
            except (TypeError, ValueError):
                u = None
            if u and 1 <= u <= 247:
                fixed[st.id] = u
                used.add(u)
        out = {}
        nxt = 11
        for st in self.plant.stations.values():
            if st.id in fixed:
                out[st.id] = fixed[st.id]
                continue
            while nxt in used and nxt <= 247:
                nxt += 1
            if nxt > 247:
                continue
            out[st.id] = nxt
            used.add(nxt)
        return out

    def rebuild(self):
        """按当前工位和协议设置重建点表（运行中的服务端直接换上新的从站表）。"""
        s = comm.settings(self.plant)['modbus']
        fmt, order, base, auto = s.get('fmt', 'float32'), s.get('order', 'ABCD'), int(s.get('base', 1000)), s.get('auto', True)
        self.order = order
        units = self._units()
        self.unit_of = units
        self.station_of = {u: sid for sid, u in units.items()}
        pts: list[Point] = []
        used = {}                                  # 从站 → (已用寄存器, 已用线圈)；同一从站上的多台设备共用
        cursor = {}
        for st in self.plant.stations.values():   # 第一遍：模型里写死的地址
            for tname, tag in st.tags.items():
                m = tag.modbus
                if m and m.get('unit') is not None:
                    kind = 'coil' if m.get('kind') == 'coil' else 'hr'
                    mf = m.get('fmt') or ('float32' if m.get('kind') == 'float32' else 'int16')
                    p = Point(st, tname, int(m['unit']), kind, int(m['addr']), mf, m.get('order') or order, m.get('scale', 1), tag.writable)
                    pts.append(p)
                    ur, uc = used.setdefault(p.unit, (set(), set()))
                    (uc if kind == 'coil' else ur).update(range(p.addr, p.addr + p.n))
        for st in self.plant.stations.values():   # 第二遍：其余点位自动分配
            u = units.get(st.id)
            if u is None or not auto:
                continue
            used_r, used_c = used.setdefault(u, (set(), set()))
            rc, cc = cursor.get(u, (base, base))
            for tname, tag in st.tags.items():
                if tag.modbus and tag.modbus.get('unit') is not None:
                    continue
                conv = None
                if tag.dtype == 'bool':
                    kind = 'coil'
                elif tag.dtype in ('float', 'int'):
                    kind = 'hr'
                elif tname == 'Common/State':
                    kind, conv = 'hr', 'state'
                elif tname == 'Common/Alarm':
                    kind, conv = 'coil', 'alarm'
                else:
                    continue
                pf = 'int16' if conv == 'state' else fmt
                scale = 1 if conv or tag.dtype == 'int' or pf in ('float32', 'float64') else 10
                n = 1 if kind == 'coil' else comm.FMTS[pf]
                if kind == 'coil':
                    while cc in used_c:
                        cc += 1
                    a = cc
                    cc += 1
                    used_c.add(a)
                else:
                    while any(x in used_r for x in range(rc, rc + n)):
                        rc += 1
                    a = rc
                    rc += n
                    used_r.update(range(a, a + n))
                pts.append(Point(st, tname, u, kind, a, pf, order, scale, tag.writable and not conv, auto=True, conv=conv))
            cursor[u] = (rc, cc)
        self.areas = [a['name'] for a in self.plant.cfg.get('areas', [])]
        size = {}
        for p in pts:
            co, hr = size.get(p.unit, (0, 0))
            size[p.unit] = (max(co, p.addr + 1), hr) if p.kind == 'coil' else (co, max(hr, p.addr + p.n))
        size[METER_UNIT] = (0, 4 + 4 * len(self.areas))
        slaves = {}
        for u, (nco, nhr) in size.items():
            slaves[u] = UnitContext(self, u, max(nco, 1), max(nhr, 1))
        for p in pts:
            ctx = slaves[p.unit]
            if p.kind == 'coil':
                ctx.coils[p.addr] = p
            else:
                for a in range(p.addr, p.addr + p.n):
                    ctx.regs[a] = p
        self.points_list = pts
        self.slaves = slaves
        self.ctx._slaves = slaves
        self.map = [[p.st, p.tag, {'unit': p.unit, 'kind': p.kind, 'addr': p.addr, 'scale': p.scale}, None] for p in pts]   # 旧字段，兼容
        for ctx in slaves.values():
            self.refresh(ctx, 3, 0, None)
            self.refresh(ctx, 1, 0, None)

    # ---------- 值 ----------
    def _value(self, p: Point):
        st = p.st
        tag = st.tags.get(p.tag)
        if tag is None:
            return 0
        v = tag.value
        if p.conv == 'state':
            v = STATE_CODE.get(str(v), 9)
        elif p.conv == 'alarm':
            v = bool(v)
        r = comm.effective(self.plant, 'modbus', st.id, p.tag)          # 含网关路径上的网络故障（4.3）
        return comm.view(self.plant, r, f'{st.id}/{p.tag}', v, 'bool' if p.kind == 'coil' else 'float' if isinstance(v, float) else 'int')

    def refresh(self, ctx, fc, address, count):
        """把 [address, address+count) 涉及的点位按模型当前值写进寄存器 / 线圈（count=None 表示整张表）。"""
        coil = fc in COIL_FC
        table = ctx.coils if coil else ctx.regs
        if count is None:
            pts = {id(p): p for p in table.values()}.values()
        else:
            seen = {}
            for a in range(address, address + count):
                p = table.get(a)
                if p is not None:
                    seen[id(p)] = p
            pts = seen.values()
        for p in pts:
            try:
                v = self._value(p)
                if coil:
                    ctx.setValues(1, p.addr, [bool(v)])
                    ctx.setValues(2, p.addr, [bool(v)])
                else:
                    regs = encode(v, p.fmt, p.order, p.scale)
                    ctx.setValues(3, p.addr, regs)
                    ctx.setValues(4, p.addr, regs)
            except Exception:
                log.debug('modbus refresh %s', p.tag, exc_info=True)
        if ctx.unit == METER_UNIT and not coil:
            self.meter(ctx)

    def meter(self, ctx):
        regs = []
        tot_kw = tot_kwh = 0.0
        for a in self.areas:
            kw = sum(s.power_kw for s in self.plant.stations.values() if s.area == a)
            kwh = sum(s.energy_kwh for s in self.plant.stations.values() if s.area == a)
            tot_kw += kw
            tot_kwh += kwh
            regs += encode(kw, 'float32', self.order) + encode(kwh, 'float32', self.order)
        regs = encode(tot_kw, 'float32', self.order) + encode(tot_kwh, 'float32', self.order) + regs
        pr = comm.protocol_rule(self.plant, 'modbus')
        if pr and pr.get('mode') in ('freeze', 'stuck'):
            fz = pr.setdefault('_frozen', {})
            regs = fz.setdefault('_meter', regs)
        ctx.setValues(3, 0, regs)
        ctx.setValues(4, 0, regs)

    def apply_write(self, ctx, fc, address, count):
        """客户端写入寄存器 / 线圈后：把涉及的点位解码写进模型；失败抛 ModbusFault(03)。"""
        coil = fc in (5, 15)
        table = ctx.coils if coil else ctx.regs
        seen = {}
        for a in range(address, address + count):
            p = table.get(a)
            if p is not None:
                seen[id(p)] = p
        for p in seen.values():
            if coil:
                v = bool(ctx.getValues(1, p.addr, 1)[0])
            else:
                v = decode(ctx.getValues(3, p.addr, p.n), p.fmt, p.order, p.scale)
            code, msg = comm.write_tag(self.plant, p.st, p.tag, v, 'Modbus')
            if code:
                log.info(_tr('Modbus 写入被拒绝：Unit %s 地址 %s %s'), ctx.unit, p.addr, msg)
                self.refresh(ctx, fc, p.addr, p.n)
                raise ModbusFault(ExceptionResponse.ILLEGAL_VALUE if code in ('range', 'type') else ExceptionResponse.ILLEGAL_ADDRESS, msg)

    def request_fault(self, unit, fc, address, count):
        """按通讯故障规则决定这次请求：(推迟秒数, 是否不应答, 异常码)。"""
        p = self.plant
        pr = comm.protocol_rule(p, 'modbus')
        sid = self.station_of.get(unit)
        r = None
        if sid:
            sr = comm.station_rules(p, 'modbus', sid)
            r = next((x for x in reversed(sr) if not x.get('tag')), None)
            if r is None:
                tr = [x for x in sr if x.get('tag')]
                if tr:
                    ctx = self.slaves.get(unit)
                    table = (ctx.coils if fc in COIL_FC else ctx.regs) if ctx else {}
                    tags = {table[a].tag for a in range(address, address + (count or 1)) if a in table}
                    r = next((x for x in reversed(tr) if any(t == x['tag'] or t.startswith(x['tag'].rstrip('/') + '/') for t in tags)), None)
        r = r or pr
        net = getattr(p, 'net', None)
        if sid and net is not None and net.gateways:      # 经主网关：路径断了 → 0B（网关目标无响应），坏质量 → 04，丢包 / 延迟照样
            from ..netmodel import worse
            r = worse(r, net.path_rule(None, sid))
        if not r:
            return 0.0, False, 0
        m = r.get('mode')
        if m == 'disconnect':
            return 0.0, False, ExceptionResponse.GATEWAY_NO_RESPONSE
        if m == 'bad':
            return 0.0, False, ExceptionResponse.SLAVE_FAILURE
        if m == 'drop':
            return 0.0, comm.dropped(r), 0
        return comm.delay_of(r), False, 0

    # ---------- 服务 ----------
    def _new_server(self):
        self._t_new = time.time()
        return VfTcpServer(self, context=self.ctx, address=('0.0.0.0', self.port))

    async def start(self):
        self.server = self._new_server()
        self.tasks = [asyncio.create_task(self.server.serve_forever()), asyncio.create_task(self.loop())]
        log.info('Modbus TCP listening on :%s units=%s', self.port, sorted(self.slaves))

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        try:
            if self.server is not None:
                await self.server.shutdown()
        except Exception:
            log.exception('modbus shutdown')

    async def loop(self):
        """只管"断开"：关闭 / 重开端口。数值在读写时按需刷新。"""
        ver = -1
        sig = self._sig()
        while True:
            try:
                s = self._sig()
                if s != sig:                      # 增删设备、控制单元改了 I/O：重建点表
                    sig = s
                    self.rebuild()
                pr = comm.protocol_rule(self.plant, 'modbus')
                cf = pr.get('mode') if pr else None
                if cf == 'disconnect' and self.server is not None:
                    await self.server.shutdown()
                    self.server = None
                elif cf != 'disconnect' and self.server is None:
                    self.server = self._new_server()
                    self.tasks.append(asyncio.create_task(self.server.serve_forever()))
                elif cf != 'disconnect' and getattr(self.server, 'transport', None) is None and time.time() - self._t_new > 5:
                    # 端口没绑上（例如重启时旧进程还占着端口）：每 5 秒重试，不要一直没有 Modbus
                    log.warning(_tr('Modbus 端口 %s 没有在监听，重试'), self.port)
                    try:
                        await self.server.shutdown()
                    except Exception:
                        pass
                    self.server = self._new_server()
                    self.tasks.append(asyncio.create_task(self.server.serve_forever()))
                v = comm.version(self.plant)
                if v != ver:                      # 故障规则变了（例如冻结开始）：先按当前值刷新一遍，冻结值从这一刻算
                    ver = v
                    for ctx in self.slaves.values():
                        self.refresh(ctx, 3, 0, None)
                        self.refresh(ctx, 1, 0, None)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('modbus loop')
            await asyncio.sleep(self.period)

    def _sig(self):
        p = self.plant
        return (p.layout_version, sum(len(st.tags) for st in p.stations.values()), len(p.stations))

    def sync(self, first=False):
        """兼容旧调用：整表刷新一次。"""
        for ctx in self.slaves.values():
            self.refresh(ctx, 3, 0, None)
            self.refresh(ctx, 1, 0, None)

    # ---------- 点表导出 ----------
    TABLE_CN = {'coil': '线圈 0x', 'hr': '保持寄存器 4x'}

    def points(self):
        out = []
        for p in self.points_list:
            out.append({'station': p.st.id, 'tag': p.tag, 'unit_id': p.unit, 'table': self.TABLE_CN[p.kind], 'address': p.addr,
                        'scale': (p.scale if p.fmt in ('int16', 'uint16', 'int32', 'uint32') else None) if p.kind != 'coil' else None,
                        'writable': p.writable, 'desc': p.desc, 'eng_unit': p.eng_unit, 'kind': p.kind, 'datatype': 'bool' if p.kind == 'coil' else p.fmt,
                        'count': p.n, 'order': p.order if p.n > 1 else None, 'auto': p.auto, 'mirror': _tr('离散输入 1x') if p.kind == 'coil' else _tr('输入寄存器 3x')})
        out.append({'station': _tr('电能表'), 'tag': '全厂', 'unit_id': METER_UNIT, 'table': _tr('保持寄存器 4x'), 'address': 0, 'scale': 'float32 ×2', 'writable': False,
                    'desc': _tr('全厂实时功率 kW(0-1)、累计电能 kWh(2-3)'), 'eng_unit': '', 'kind': 'hr', 'datatype': 'float32', 'count': 4, 'order': self.order,
                    'auto': False, 'mirror': _tr('输入寄存器 3x')})
        for i, a in enumerate(self.areas):
            out.append({'station': _tr('电能表'), 'tag': a, 'unit_id': METER_UNIT, 'table': _tr('保持寄存器 4x'), 'address': 4 + i * 4, 'scale': 'float32 ×2',
                        'writable': False, 'desc': _tr('{a} 功率 kW、电能 kWh', a=a), 'eng_unit': '', 'kind': 'hr', 'datatype': 'float32', 'count': 4,
                        'order': self.order, 'auto': False, 'mirror': _tr('输入寄存器 3x')})
        return out
