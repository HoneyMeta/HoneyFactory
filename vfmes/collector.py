"""数据采集：按"数据源 + 采集点"配置连接 MQTT（统一命名空间）、OPC UA、Modbus TCP。

MQTT 数据源订阅 <前缀>#：
  <前缀><区域>/<设备>/<点位>      点位值 {"value", "ts"}
  <前缀>_mes/part | _mes/event   网关上送的零件事件和生产日志
OPC UA / Modbus 数据源按采集点表（地址）订阅或轮询。
"""
from .i18n import _tr, en_text, variants
import asyncio
import json
import logging
import re
import urllib.request
from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import HTTPException

from . import db
from .crud import action
from .db import clock, parse_dt
from .ingest import ING
from .schema import TABLES

log = logging.getLogger('mes.collector')
ETYPE = {'furnace': 'furnace', 'treatment': 'treatment', 'sand': 'sand', 'molding': 'molding', 'cooling': 'cooling', 'shotblast': 'shotblast', 'cnc': 'cnc',
         'deburr': 'deburr', 'inspection': 'inspection', 'warehouse': 'warehouse', 'agv': 'agv', 'crew': 'crew', 'receiving': 'receiving'}
IDEAL = {'cnc': 430, 'molding': 20, 'shotblast': 25, 'deburr': 65, 'inspection': 60, 'receiving': 106, 'cooling': 20}
PROC = {'furnace': 'P10', 'treatment': 'P20', 'molding': 'P30', 'sand': 'P30', 'cooling': 'P40', 'shotblast': 'P50', 'cnc': 'P60', 'deburr': 'P70', 'inspection': 'P80',
        'warehouse': 'P90', 'receiving': 'P05'}


def role_of(name):
    n = name.lower()
    if name == 'Common/State':
        return 'state'
    if name == 'Common/Alarm':
        return 'alarm'
    if name == 'Common/PowerKW' or name == 'Electrical/Power':
        return 'power'
    if name == 'Common/EnergyKWh':
        return 'energy'
    if 'spindle/load' in n:
        return 'load'
    if 'temp' in n:
        return 'temp'
    if 'count' in n or 'produced' in n or 'parts' in n:
        return 'count'
    if 'quality/' in n or 'moisture' in n or 'chemistry' in n:
        return 'quality'
    return 'other'


class Collector:
    def __init__(self):
        self.tasks: dict[int, asyncio.Task] = {}
        self.status: dict[int, str] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self):
        self.loop = asyncio.get_running_loop()
        ING.reload()
        with db.engine.connect() as c:
            dss = db.rows(c, 'datasource', enabled=True)
        for ds in dss:
            self.launch(ds)
        asyncio.create_task(self.housekeeping())

    def launch(self, ds):
        self.stop(ds['id'])
        fn = {'mqtt': self.mqtt_loop, 'opcua': self.opcua_loop, 'modbus': self.modbus_loop}.get(ds['protocol'])
        if fn:
            self.tasks[ds['id']] = asyncio.create_task(fn(ds))

    def stop(self, dsid):
        t = self.tasks.pop(dsid, None)
        if t:
            t.cancel()

    def restart_threadsafe(self, dsid):
        """从接口线程里重连某个数据源。"""
        def go():
            ING.reload()
            with db.engine.connect() as c:
                ds = db.get(c, 'datasource', dsid)
            if ds and ds['enabled']:
                self.launch(ds)
            else:
                self.stop(dsid)
        if self.loop:
            # 调用方通常还在事务里：等提交后再重连
            self.loop.call_soon_threadsafe(lambda: self.loop.call_later(1.5, go))

    def set_status(self, ds, s):
        if self.status.get(ds['id']) == s:
            return
        self.status[ds['id']] = s
        with db.engine.begin() as c:
            c.execute(TABLES['datasource'].update().where(TABLES['datasource'].c.id == ds['id']).values(status=s[:190]))

    async def housekeeping(self):
        n = 0
        while True:
            await asyncio.sleep(2)
            try:
                ING.flush()
                n += 1
                if n % 30 == 0:
                    from .services.machining import refresh_tools
                    await asyncio.get_running_loop().run_in_executor(None, refresh_tools)
            except Exception:
                log.exception('housekeeping')

    # ---------- MQTT ----------
    async def mqtt_loop(self, ds):
        from amqtt.client import MQTTClient
        prefix = ds['prefix'] or ''
        url = ds['endpoint'] or 'mqtt://127.0.0.1:1883'
        if not url.startswith('mqtt'):
            url = 'mqtt://' + url
        while True:
            cli = MQTTClient(client_id=f"vfmes-{ds['code']}")
            try:
                await cli.connect(url.rstrip('/') + '/')
                await cli.subscribe([(prefix + '#', 0)])
                self.set_status(ds, _tr('已连接'))
                n = 0
                while True:
                    msg = await cli.deliver_message()
                    try:
                        self.on_mqtt(ds, prefix, msg.topic, msg.data)
                    except Exception:
                        log.exception('mqtt message %s', msg.topic)
                    n += 1
                    if n % 200 == 0:
                        await asyncio.sleep(0)
            except asyncio.CancelledError:
                try:
                    await cli.disconnect()
                except Exception:
                    pass
                raise
            except Exception as ex:
                self.set_status(ds, _tr('连接失败：{ex}', ex=ex)[:150])
                log.warning('mqtt %s: %s', url, ex)
                try:
                    await cli.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(5)

    def on_mqtt(self, ds, prefix, topic, data):
        rest = topic[len(prefix):] if topic.startswith(prefix) else topic
        hit = ING.by_addr.get((ds['id'], topic)) if not rest.startswith('_') else None
        if hit:                                 # 点表里登记了这个主题（原始现场的 PLC 地址式主题，载荷也可能是纯文本数值）
            txt = data.decode('utf-8', 'replace').strip()
            if not txt:                         # 清掉 retain 的空消息
                return
            try:
                payload = json.loads(txt) if txt else None
            except ValueError:
                payload = txt
            if isinstance(payload, dict):
                val, ts = payload.get('value'), parse_dt(payload.get('ts'))
            else:
                val, ts = payload, None
            eid, name = hit
            ING.on_tag(eid, name, val, ts, f"{ds['code']}:{ING.equip_code.get(eid, eid)}/{name}")
            return
        payload = json.loads(data.decode('utf-8', 'replace') or 'null')
        if rest.startswith('_mes/part'):
            ING.on_part(ds['code'], payload)
            return
        if rest.startswith('_mes/event'):
            ING.on_event(ds['code'], payload)
            return
        parts = rest.split('/')
        if len(parts) < 3:
            return
        sid, tag = parts[1], '/'.join(parts[2:])
        val, ts = (payload.get('value'), parse_dt(payload.get('ts'))) if isinstance(payload, dict) else (payload, None)
        ING.on_tag(ING.equip(f"{ds['code']}:{sid}"), tag, val, ts, f"{ds['code']}:{sid}/{tag}")

    # ---------- OPC UA ----------
    async def opcua_loop(self, ds):
        from asyncua import Client
        while True:
            try:
                with db.engine.connect() as c:
                    pts = db.rows(c, 'tag_point', datasource=ds['id'], enabled=True)
                async with Client(ds['endpoint']) as cli:
                    nodes = {cli.get_node(p['address']): p for p in pts if p['address']}
                    coll = self

                    class H:
                        def datachange_notification(self, node, val, data):
                            p = nodes.get(node)
                            if p:
                                ING.on_tag(p['equipment'], p['name'], val, None, f"{ds['code']}:{p['equipment']}/{p['name']}")
                    sub = await cli.create_subscription(500, H())
                    if nodes:
                        await sub.subscribe_data_change(list(nodes))
                    self.set_status(ds, _tr('已连接，订阅 {len} 点', len=len(nodes)))
                    while True:
                        await asyncio.sleep(5)
                        await cli.check_connection()
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                self.set_status(ds, _tr('连接失败：{ex}', ex=ex)[:150])
                await asyncio.sleep(5)

    # ---------- Modbus ----------
    async def modbus_loop(self, ds):
        from pymodbus.client import AsyncModbusTcpClient
        host, _, port = (ds['endpoint'] or '127.0.0.1:502').replace('modbus://', '').partition(':')
        while True:
            cli = AsyncModbusTcpClient(host, port=int(port or 502))
            try:
                await cli.connect()
                if not cli.connected:
                    raise ConnectionError(_tr('无法连接'))
                with db.engine.connect() as c:
                    pts = db.rows(c, 'tag_point', datasource=ds['id'], enabled=True)
                self.set_status(ds, _tr('已连接，轮询 {len} 点', len=len(pts)))
                while True:
                    for p in pts:
                        try:
                            unit, table, addr = (p['address'] or '').split(':')
                            unit, addr = int(unit), int(addr)
                            if table in ('coil', 'co'):
                                r = await cli.read_coils(addr, count=1, slave=unit)
                                val = bool(r.bits[0])
                            else:
                                r = await (cli.read_input_registers if table in ('ir',) else cli.read_holding_registers)(addr, count=1, slave=unit)
                                raw = r.registers[0]
                                raw = raw - 65536 if raw > 32767 else raw
                                val = raw / (p['scale'] or 1)
                            ING.on_tag(p['equipment'], p['name'], val, None, f"{ds['code']}:{p['equipment']}/{p['name']}")
                        except (ValueError, AttributeError, IndexError):
                            continue
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                cli.close()
                raise
            except Exception as ex:
                self.set_status(ds, _tr('连接失败：{ex}', ex=ex)[:150])
                cli.close()
                await asyncio.sleep(5)


COLLECTOR = Collector()


@action('datasource', 'restart')
def ds_restart(c, ds, body, user):
    COLLECTOR.restart_threadsafe(ds['id'])
    return {'msg': _tr('正在重连')}


def _get(url, token=''):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token} if token else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _tool_name(desc):
    """Tool name from the Virtual Factory's tag description "<tool> 寿命设定（到数换刀）" (Chinese or English)."""
    for v in variants('{nm} 寿命设定（到数换刀）'):
        suffix = v.replace('{nm}', '')
        if suffix.strip() and desc.endswith(suffix):
            return desc[:-len(suffix)]
    return desc


@action('datasource', 'import_vf')
def import_vf(c, ds, body, user):
    """从虚拟工厂导入设备、产线、工位、采集点、刀具（相当于现场"导入设备清单 + 点表"）。"""
    base = (body.get('url') or db.setting(c, 'vf_http') or 'http://127.0.0.1:8800/api/p/foundry-housing').rstrip('/')
    tok = (body.get('token') or db.setting(c, 'vf_token') or '').strip()
    try:
        meta = _get(base + '/meta', tok)
        points = _get(base + '/points', tok)
    except Exception as ex:
        hint = _tr('（虚拟工厂需要 API 令牌：在虚拟工厂"API 令牌"页面创建后填入）') if '401' in str(ex) else ''
        raise HTTPException(400, _tr('连不上虚拟工厂 {base}：{ex}{hint}', base=base, ex=ex, hint=hint))
    db.set_setting(c, 'vf_http', base, _tr('虚拟工厂接口地址（演示用，取刀具真值对照）'))
    if tok:
        db.set_setting(c, 'vf_token', tok, _tr('虚拟工厂 API 令牌'))
    pid = meta['id']
    plant = db.get(c, 'plant', code=pid.upper()) or db.get(c, 'plant', id=1)
    if not plant:
        db.insert(c, 'plant', {'code': pid.upper(), 'name': meta['name'], 'vf_source': base}, raw=True)
        plant = db.get(c, 'plant', code=pid.upper())
    ws_map = {'熔炼区': ('WS-F', _tr('铸造车间'), 'foundry'), '造型区': ('WS-F', _tr('铸造车间'), 'foundry'), '清理区': ('WS-F', _tr('铸造车间'), 'foundry'),
              '机加区': ('WS-M', _tr('机加车间'), 'machining'), '检测区': ('WS-M', _tr('机加车间'), 'machining'), '收货区': ('WS-M', _tr('机加车间'), 'machining'),
              '仓储区': ('WS-W', _tr('仓储物流'), 'warehouse'), '物流': ('WS-W', _tr('仓储物流'), 'warehouse'), '人员': ('WS-W', _tr('仓储物流'), 'warehouse')}
    line_code = {'熔炼区': 'MELT', '造型区': 'MOLD', '清理区': 'CLEAN', '机加区': 'MACH', '检测区': 'INSP', '仓储区': 'WH', '物流': 'LOG', '人员': 'CREW', '收货区': 'RCV'}
    # area names come from the plant model in the Virtual Factory's language: match the Chinese names and their English translations
    for zh in list(ws_map):
        ws_map.setdefault(en_text(zh), ws_map[zh])
        line_code.setdefault(en_text(zh), line_code[zh])
    lines = {}
    for area in {s['area'] for s in meta['stations']}:
        wcode, wname, wtype = ws_map.get(area, ('WS-O', _tr('其他'), 'other'))
        w = db.get(c, 'workshop', code=wcode) or {'id': db.insert(c, 'workshop', {'code': wcode, 'name': wname, 'plant': plant['id'], 'wtype': wtype}, raw=True)}
        lcode = 'L-' + line_code.get(area, area)
        lname = (area.replace('区', '') + _tr('线') if area.endswith('区') else re.sub(r'(?i)\s*area$', '', area) + ' ' + _tr('线') if area.lower().endswith(' area') else area)
        ln = db.get(c, 'line', code=lcode) or {'id': db.insert(c, 'line', {'code': lcode, 'name': lname,
                                                                             'workshop': w['id']}, raw=True)}
        lines[area] = ln['id']
    n_eq = n_pt = n_tool = 0
    procs = {p['code']: p['id'] for p in db.rows(c, 'process')}
    eq_id = {}
    for s in meta['stations']:
        et = ETYPE.get(s['kind'], 'other')
        row = {'name': s['name'], 'etype': et, 'line': lines.get(s['area']), 'source': f"{ds['code']}:{s['id']}", 'model': {'cnc': 'VMC-850'}.get(et),
               'ideal_cycle_s': IDEAL.get(et), 'location': s['area']}
        e = db.get(c, 'equipment', code=s['id'])
        if e:
            db.update(c, 'equipment', e['id'], {k: v for k, v in row.items() if v is not None}, raw=True)
            eq_id[s['id']] = e['id']
        else:
            eq_id[s['id']] = db.insert(c, 'equipment', {'code': s['id'], 'status': 'offline', 'install_date': clock.now().date(), **row}, raw=True)
            n_eq += 1
        if et not in ('crew', 'agv') and not db.get(c, 'workstation', code='WS-' + s['id']):
            db.insert(c, 'workstation', {'code': 'WS-' + s['id'], 'name': s['name'], 'line': lines.get(s['area']), 'process': procs.get(PROC.get(et)),
                                         'equipment': eq_id[s['id']], 'group': s.get('group') if et == 'cnc' else s['id']}, raw=True)
    tp = TABLES['tag_point']
    c.execute(tp.delete().where(tp.c.datasource == ds['id']))
    for r in points:
        sid = r['工位'].split(' ')[0]
        if sid not in eq_id:
            continue
        addr = r['MQTT 主题'] if ds['protocol'] == 'mqtt' else r['OPC UA NodeId'] if ds['protocol'] == 'opcua' else ''
        if ds['protocol'] == 'modbus':
            m = r.get('Modbus') or ''
            if not m:
                continue
            # "端口 5020 Unit 1 保持寄存器 4x 100 ÷100"
            try:
                toks = m.split()
                unit = toks[toks.index('Unit') + 1]
                table = 'coil' if ('线圈' in m or 'coil' in m.lower() or '0x' in toks) else 'hr'
                a = toks[toks.index('4x') + 1] if '4x' in toks else toks[toks.index('0x') + 1]
                addr = f'{unit}:{table}:{a}'
            except (ValueError, IndexError):
                continue
        c.execute(tp.insert().values(equipment=eq_id[sid], datasource=ds['id'], name=r['点位'], address=addr, dtype=r['类型'], unit=r['单位'],
                                     scale=float(r['Modbus'].split('÷')[1]) if ds['protocol'] == 'modbus' and '÷' in (r.get('Modbus') or '') else None,
                                     role=role_of(r['点位']), desc=r['说明'], enabled=True, created_at=clock.now(), updated_at=clock.now()))
        n_pt += 1
    # 刀具台账
    for s in meta['stations']:
        if s['kind'] != 'cnc':
            continue
        try:
            st = _get(f"{base}/station/{s['id']}", tok)
        except Exception:
            continue
        for k, t in st['tags'].items():
            if k.startswith('Tools/') and k.endswith('/LifeLimit'):
                code = k.split('/')[1]
                name = _tool_name(t['d'])
                tt = TABLES['tool']
                ex = c.execute(sa.select(tt.c.id).where((tt.c.equipment == eq_id[s['id']]) & (tt.c.code == code))).scalar()
                if not ex:
                    db.insert(c, 'tool', {'code': code, 'name': name, 'equipment': eq_id[s['id']], 'ttype': name.split()[-1] if ' ' in name else name,
                                          'life_limit': int(t['v']), 'used': int(st['tags'].get(f'Tools/{code}/LifeCount', {}).get('v') or 0), 'changes': 0,
                                          'status': 'ok', 'last_change': clock.now()}, raw=True)
                    n_tool += 1
    from .seed import after_import
    after_import(c)
    COLLECTOR.restart_threadsafe(ds['id'])
    return {'msg': _tr('已导入：新设备 {n_eq} 台、采集点 {n_pt} 个、刀具 {n_tool} 把；数据源正在重连', n_eq=n_eq, n_pt=n_pt, n_tool=n_tool)}
