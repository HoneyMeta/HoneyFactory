"""西门子 S7 外接驱动：自带最小 S7comm 客户端（ISO-on-TCP，端口 102），不依赖 snap7（LGPL 动态库）。

支持：COTP 连接（rack/slot）、通讯设置（协商 PDU）、读写 I/Q/M/DB 区（位、字节、字、双字，多项合并请求）。
地址写法（博途风格，也接受德文 E/A）：I0.0  Q0.1  M10.2  IB0  IW64  ID0  QW64  MW10  MD20  DB1.DBX0.0  DB1.DBB0  DB1.DBW2  DB1.DBD4
类型：BOOL ↔ 位；INT ↔ 字（16 位有符号）；DINT ↔ 双字；REAL ↔ 双字（IEEE754）。字节序大端（和 S7 一致）。
限制：
  - S7-1200/1500 要在博途里打开"允许来自远程对象的 PUT/GET 通信访问"，并且只能访问"非优化"的 DB（取消"优化的块访问"）；
  - 实体 PLC 的输入区 I 每个周期被硬件输入刷新，往 I 区写只对没有硬件模块的地址有效；PLCSIM Advanced 可以写 I 区。
    稳妥的做法是传感器映射到 M 区或 DB 区，在 PLC 程序里使用；
  - 只用了 S7comm（经典协议），不支持 S7comm-plus 的加密访问，不支持 S7-200/LOGO 的 TSAP 变体以外的自定义 TSAP（可在配置里填 local_tsap / remote_tsap）。
"""
from ...i18n import _tr
import asyncio
import re
import struct

from ..external import PollingDriver

AREA = {'I': 0x81, 'E': 0x81, 'Q': 0x82, 'A': 0x82, 'M': 0x83, 'DB': 0x84}
_BIT = re.compile(r'^([IEQAM])(\d+)\.([0-7])$', re.I)
_WRD = re.compile(r'^([IEQAM])([BWD])(\d+)$', re.I)
_DBX = re.compile(r'^DB(\d+)\.DBX(\d+)\.([0-7])$', re.I)
_DBW = re.compile(r'^DB(\d+)\.DB([BWD])(\d+)$', re.I)
SIZE = {'X': 0, 'B': 1, 'W': 2, 'D': 4}
RET = {0xFF: '成功', 0x01: '硬件错误', 0x03: '没有访问权限（检查 PUT/GET 设置）', 0x05: '地址超出范围', 0x06: '数据类型不支持', 0x07: '数据类型不一致',
       0x0A: '对象不存在（DB 不存在或是优化访问的 DB）'}


class S7Error(Exception):
    pass


def parse_addr(a):
    """→ (区代码, DB 号, 字节, 位或None, 宽度 X/B/W/D)"""
    s = str(a or '').strip().upper().replace(' ', '')
    m = _BIT.match(s)
    if m:
        return AREA[m.group(1)], 0, int(m.group(2)), int(m.group(3)), 'X'
    m = _WRD.match(s)
    if m:
        return AREA[m.group(1)], 0, int(m.group(3)), None, m.group(2)
    m = _DBX.match(s)
    if m:
        return AREA['DB'], int(m.group(1)), int(m.group(2)), int(m.group(3)), 'X'
    m = _DBW.match(s)
    if m:
        return AREA['DB'], int(m.group(1)), int(m.group(3)), None, m.group(2)
    raise ValueError(_tr('S7 地址写法不对：{a}（例：I0.0、Q0.1、M10.2、MW10、DB1.DBX0.0、DB1.DBW2、DB1.DBD4）', a=a))


def encode(t, size, v):
    if size == 'B':
        return bytes([int(v or 0) & 0xFF])
    if size == 'W':
        return struct.pack('>H', int(v or 0) & 0xFFFF)
    if t in ('REAL', 'LREAL'):
        return struct.pack('>f', float(v or 0))
    return struct.pack('>I', int(v or 0) & 0xFFFFFFFF)


def decode(t, size, b):
    if size == 'B':
        return b[0]
    if size == 'W':
        x = struct.unpack('>H', b[:2])[0]
        return x - 65536 if t in ('INT',) and x > 32767 else x
    if t in ('REAL', 'LREAL'):
        return struct.unpack('>f', b[:4])[0]
    x = struct.unpack('>I', b[:4])[0]
    return x - (1 << 32) if t == 'DINT' and x >= 1 << 31 else x


class S7Client:
    def __init__(self, host, port=102, rack=0, slot=1, timeout=3.0, local_tsap=0x0100, remote_tsap=None):
        self.host, self.port, self.rack, self.slot, self.timeout = host, port, rack, slot, timeout
        self.local_tsap = local_tsap
        self.remote_tsap = remote_tsap if remote_tsap is not None else (0x0100 | (rack * 0x20 + slot))
        self.r = self.w = None
        self.pdu = 240
        self.ref = 0

    async def connect(self):
        self.r, self.w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), self.timeout)
        lt, rt = self.local_tsap, self.remote_tsap
        cotp = bytes([0x11, 0xE0, 0, 0, 0, 1, 0, 0xC0, 1, 0x0A, 0xC1, 2, lt >> 8, lt & 0xFF, 0xC2, 2, rt >> 8, rt & 0xFF])
        await self._send_raw(cotp)
        resp = await self._recv_raw()
        if len(resp) < 2 or resp[1] != 0xD0:
            raise S7Error(_tr('PLC 拒绝了连接（检查 rack/slot：S7-1200/1500 是 0/1，S7-300 是 0/2）'))
        params = bytes([0xF0, 0, 0, 1, 0, 1]) + struct.pack('>H', 960)
        r = await self._job(params, b'')
        p = r['params']
        if len(p) >= 8:
            self.pdu = struct.unpack('>H', p[6:8])[0]

    async def close(self):
        if self.w is not None:
            try:
                self.w.close()
            except Exception:
                pass
        self.r = self.w = None

    async def _send_raw(self, payload):
        self.w.write(struct.pack('>BBH', 3, 0, len(payload) + 4) + payload)
        await self.w.drain()

    async def _recv_raw(self):
        hdr = await asyncio.wait_for(self.r.readexactly(4), self.timeout)
        if hdr[0] != 3:
            raise S7Error(_tr('收到的不是 ISO-on-TCP 报文'))
        n = struct.unpack('>H', hdr[2:4])[0]
        return await asyncio.wait_for(self.r.readexactly(n - 4), self.timeout)

    async def _job(self, params, data):
        self.ref = (self.ref + 1) & 0xFFFF
        s7 = struct.pack('>BBHHHH', 0x32, 1, 0, self.ref, len(params), len(data)) + params + data
        await self._send_raw(bytes([2, 0xF0, 0x80]) + s7)
        resp = await self._recv_raw()
        if len(resp) < 3 or resp[1] != 0xF0:
            raise S7Error(_tr('收到的不是 COTP 数据报文'))
        s = resp[3:]
        if len(s) < 12 or s[0] != 0x32:
            raise S7Error(_tr('收到的不是 S7 报文'))
        rosctr = s[1]
        if rosctr not in (2, 3):
            raise S7Error(_tr('S7 应答类型不对：{rosctr}', rosctr=rosctr))
        plen, dlen = struct.unpack('>HH', s[6:10])
        ec, eco = s[10], s[11]
        if ec or eco:
            raise S7Error(_tr('S7 错误 class=0x{ec:02X} code=0x{eco:02X}', ec=ec, eco=eco))
        return {'params': s[12:12 + plen], 'data': s[12 + plen:12 + plen + dlen]}

    @staticmethod
    def _item(area, db, start_bit, count, tsize):
        return bytes([0x12, 0x0A, 0x10, tsize]) + struct.pack('>HH', count, db) + bytes([area]) + (start_bit & 0xFFFFFF).to_bytes(3, 'big')

    async def read_multi(self, reqs):
        """reqs [(区, DB, 起始字节, 字节数)] → [bytes]。按 PDU 大小分批。"""
        out = []
        i = 0
        while i < len(reqs):
            batch, size = [], 0
            while i < len(reqs) and len(batch) < 18:
                a, db, st, n = reqs[i]
                if n + 5 + size + 19 > self.pdu and batch:
                    break
                if n + 18 > self.pdu:
                    raise S7Error(_tr('一次读取 {n} 字节超过 PDU 大小 {pdu}，请缩小地址范围', n=n, pdu=self.pdu))
                batch.append(reqs[i])
                size += n + 5
                i += 1
            params = bytes([4, len(batch)]) + b''.join(self._item(a, db, st * 8, n, 0x02) for a, db, st, n in batch)
            r = await self._job(params, b'')
            d = r['data']
            pos = 0
            for k, (a, db, st, n) in enumerate(batch):
                if pos + 4 > len(d):
                    raise S7Error(_tr('读应答长度不对'))
                rc, ts = d[pos], d[pos + 1]
                ln = struct.unpack('>H', d[pos + 2:pos + 4])[0]
                if rc != 0xFF:
                    raise S7Error(_tr('读 {v}{st} 失败：{get}', v=_area_name(a, db), st=st, get=RET.get(rc, hex(rc))))
                nb = ln // 8 if ts in (4, 5) else max(1, (ln + 7) // 8) if ts == 3 else ln
                out.append(bytes(d[pos + 4:pos + 4 + nb]))
                pos += 4 + nb + (nb % 2 if k < len(batch) - 1 else 0)
        return out

    async def write_multi(self, items):
        """items [(区, DB, 起始字节, 位或None, bytes)]，位写入时 bytes 是 b'\\x00'/b'\\x01'。"""
        i = 0
        while i < len(items):
            batch = items[i:i + 10]
            i += 10
            params = bytes([5, len(batch)])
            data = b''
            for k, (a, db, st, bit, val) in enumerate(batch):
                if bit is not None:
                    params += self._item(a, db, st * 8 + bit, 1, 0x01)
                    part = bytes([0, 3]) + struct.pack('>H', 1) + val[:1]
                else:
                    params += self._item(a, db, st * 8, len(val), 0x02)
                    part = bytes([0, 4]) + struct.pack('>H', len(val) * 8) + val
                if k < len(batch) - 1 and len(part) % 2:
                    part += b'\x00'
                data += part
            r = await self._job(params, data)
            d = r['data']
            for k, (a, db, st, bit, val) in enumerate(batch):
                if k < len(d) and d[k] != 0xFF:
                    raise S7Error(_tr('写 {v}{st}{v2} 失败：{get}', v=_area_name(a, db), st=st, v2="." + str(bit) if bit is not None else "", get=RET.get(d[k], hex(d[k]))))


def _area_name(a, db):
    return {0x81: 'I', 0x82: 'Q', 0x83: 'M'}.get(a, f'DB{db}.')


class S7Driver(PollingDriver):
    def __init__(self, ext, ctx):
        super().__init__(ext, ctx)
        c = ext.cfg
        ep = str(c.get('endpoint') or c.get('host') or '127.0.0.1')
        host, _, port = ep.partition(':')
        self.client_args = dict(host=host, port=int(port or 102), rack=int(c.get('rack') or 0), slot=int(c.get('slot') if c.get('slot') is not None else 1))
        if c.get('local_tsap'):
            self.client_args['local_tsap'] = int(str(c['local_tsap']), 0)
        if c.get('remote_tsap'):
            self.client_args['remote_tsap'] = int(str(c['remote_tsap']), 0)
        self.writes, self.reads = [], []
        for m in ext.mapping:
            a, db, byte, bit, size = parse_addr(m['addr'])
            t = (m.get('type') or 'BOOL').upper()
            if (size == 'X') != (t == 'BOOL'):
                raise ValueError(_tr('{name} 是 {t}，地址 {addr} 的宽度不匹配（布尔量用位地址，数值用 W/D）', name=m["name"], t=t, addr=m["addr"]))
            (self.writes if m['dir'] == 'in' else self.reads).append((m['name'], t, a, db, byte, bit, size))
        # 读：按 (区, DB) 合并成连续字节块
        self.read_blocks = []
        by = {}
        for name, t, a, db, byte, bit, size in self.reads:
            by.setdefault((a, db), []).append((byte, byte + max(1, SIZE[size])))
        for (a, db), rs in by.items():
            rs.sort()
            s, e = rs[0]
            for x, y in rs[1:]:
                if x <= e + 16 and y - s <= 200:
                    e = max(e, y)
                else:
                    self.read_blocks.append((a, db, s, e - s))
                    s, e = x, y
            self.read_blocks.append((a, db, s, e - s))
        self.client = None
        self.ext.status['peer'] = f"{host}:{self.client_args['port']} rack {self.client_args['rack']} slot {self.client_args['slot']}"

    async def connect(self):
        self.client = S7Client(**self.client_args)
        await self.client.connect()

    async def close(self):
        if self.client is not None:
            await self.client.close()
            self.client = None

    async def exchange(self):
        ext = self.ext
        items = []
        for name, t, a, db, byte, bit, size in self.writes:
            v = ext.inputs.get(name)
            if size == 'X':
                items.append((a, db, byte, bit, b'\x01' if v else b'\x00'))
            else:
                items.append((a, db, byte, None, encode(t, size, v)))
        if items:
            await self.client.write_multi(items)
        if self.read_blocks:
            data = await self.client.read_multi(self.read_blocks)
            for (a, db, s, n), buf in zip(self.read_blocks, data):
                for name, t, a2, db2, byte, bit, size in self.reads:
                    if a2 == a and db2 == db and s <= byte < s + n:
                        off = byte - s
                        if size == 'X':
                            ext.set_output(name, bool((buf[off] >> bit) & 1))
                        else:
                            ext.set_output(name, decode(t, size, buf[off:off + SIZE[size]]))
