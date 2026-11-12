"""数据入库：把采集到的点位和网关事件变成 MES 业务记录。

点位（on_tag）：运行状态 → 设备状态记录与 OEE；累计电能 → 小时电耗；报警 → 报警记录；刀具计数 → 刀具寿命；主轴负载 → 趋势。
网关事件（on_part / on_event）：零件事件 → 一件一码、自动报工、检验、不合格品、返修、库存、AGV；
生产日志 → 炉次、光谱、球化、换刀、发运。
"""
from .i18n import _tr
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

import sqlalchemy as sa

from . import db
from .db import clock, parse_dt
from .schema import TABLES

log = logging.getLogger('mes.ingest')

STATE_MAP = {'Executing': 'running', 'Idle': 'idle', 'Setup': 'setup', 'Stopped': 'down', 'Planned': 'offline'}
# 零件事件 → 工序类型
EVENT_PROC = {'poured': 'molding', 'received': 'receiving', 'shakeout': 'cooling', 'cleaned': 'cleaning', 'machined': 'machining',
              'deburred': 'deburr', 'inspected': 'inspection', 'stored': 'storage'}
SAMPLE_TAGS = ('Monitoring/Spindle/Load', 'Monitoring/Vibration/RMS', 'Bath/Temperature', 'Sand/Moisture', 'Quality/BoreDiameter', 'Brush/Wear',
               'Cooling/OutletTemp', 'Lining/EarthLeakage', 'Ladle/ResidualMg', 'Sand/Compactability')


class Ingest:
    def __init__(self):
        self.equip_by_src: dict[str, int] = {}        # 'VF:CNC1' -> equipment.id
        self.equip_code: dict[int, str] = {}
        self.state: dict[int, tuple] = {}             # equipment -> (state, since, row id)
        self.alarm: dict[int, tuple] = {}             # equipment -> (msg, row id)
        self.energy_last: dict[int, float] = {}
        self.energy_acc: dict[tuple, float] = defaultdict(float)
        self.latest: dict[str, tuple] = {}            # key -> (equipment, name, value, num, ts)
        self.dirty_latest: set = set()
        self.sample_last: dict[str, datetime] = {}
        self.active_tool: dict[int, str] = {}
        self.wo_born: dict[int, int] = {}
        self.cache_wo: dict[int, int] = {}            # product -> 当前投产工单
        self.stats = defaultdict(int)
        self.products: list[tuple] = []
        self.reloaded = 0.0
        self.missing: set = set()
        self.pending_state: dict[int, tuple] = {}
        self.by_addr: dict[tuple, tuple] = {}

    # ---------- 基础映射 ----------
    def reload(self):
        import time
        self.reloaded = time.time()
        self.missing = set()
        with db.engine.connect() as c:
            eq = db.rows(c, 'equipment')
            self.equip_by_src = {e['source']: e['id'] for e in eq if e['source']}
            self.equip_code = {e['id']: e['code'] for e in eq}
            # 采集点地址 → (设备, 点位名)：主题 / 地址不是 <区域>/<设备>/<点位> 结构时（虚拟工厂的"原始现场"模式）按点表查
            self.by_addr = {(t['datasource'], t['address']): (t['equipment'], t['name']) for t in db.rows(c, 'tag_point', enabled=True) if t['address']}
            mats = db.rows(c, 'material', mtype='fg')
            self.products = sorted(((m['code'], m['id']) for m in mats), key=lambda x: -len(x[0]))
            for e in eq:
                last = c.execute(sa.select(TABLES['equip_state']).where(TABLES['equip_state'].c.equipment == e['id'])
                                 .order_by(TABLES['equip_state'].c.id.desc()).limit(1)).mappings().first()
                if last and last['end'] is None:
                    self.state[e['id']] = (last['state'], last['start'], last['id'])
        self.cache_wo.clear()
        self.wo_born.clear()

    def equip(self, src_key: str) -> int | None:
        eid = self.equip_by_src.get(src_key)
        if eid is None and src_key not in self.missing:
            # 设备是后来导入的：限频重新加载映射
            import time
            if time.time() - self.reloaded > 5:
                self.reload()
                eid = self.equip_by_src.get(src_key)
            if eid is None:
                self.missing.add(src_key)
        return eid

    def product_of(self, ptype: str | None) -> int | None:
        ptype = ptype or ''
        for code, mid in self.products:
            if ptype.startswith(code) or code in ptype:
                return mid
        return self.products[0][1] if self.products else None

    # ---------- 点位 ----------
    def on_tag(self, eid: int | None, name: str, value, ts: datetime | None, key: str):
        if ts:
            clock.feed(ts)
        ts = ts or clock.now()
        num = None
        if isinstance(value, bool):
            num = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            num = float(value)
        self.latest[key] = (eid, name, '' if value is None else str(value)[:200], num, ts)
        self.dirty_latest.add(key)
        if eid is None:
            return
        if name == 'Common/State':
            self._state(eid, str(value), ts)
        elif name == 'Common/Alarm':
            self._alarm(eid, str(value or ''), ts)
        elif name == 'Common/EnergyKWh' and num is not None:
            last = self.energy_last.get(eid)
            self.energy_last[eid] = num
            if last is not None and 0 <= num - last < 10000:
                self.energy_acc[(eid, ts.replace(minute=0, second=0, microsecond=0))] += num - last
        elif name == 'Tools/ActiveTool':
            self.active_tool[eid] = str(value or '')
        elif name.startswith('Tools/') and name.endswith('/LifeCount') and num is not None:
            self._tool_count(eid, name.split('/')[1], int(num))
        if name in SAMPLE_TAGS and num is not None:
            skey = f'{eid}|{name}'
            last = self.sample_last.get(skey)
            if last is None or (ts - last).total_seconds() >= 10 or ts < last:
                self.sample_last[skey] = ts
                sname = name
                if name == 'Monitoring/Spindle/Load' and self.active_tool.get(eid):
                    sname = f'{name}@{self.active_tool[eid]}'
                with db.engine.begin() as c:
                    c.execute(sa.insert(db.metadata.tables['tag_sample']).values(equipment=eid, name=sname, ts=ts, num=num))

    def _state(self, eid, st, ts):
        cur = self.state.get(eid)
        if cur is None:
            # 第一次看到这台设备：MQTT 保留消息的时间可能是很久以前，等时钟稳定后（flush 时）从"开始观测"算起
            self.pending_state[eid] = (st, ts)
            return
        if cur[0] == st:
            return
        es = TABLES['equip_state']
        with db.engine.begin() as c:
            if cur:
                dur = max(0.0, (ts - cur[1]).total_seconds())
                c.execute(es.update().where(es.c.id == cur[2]).values(end=ts, dur_s=dur))
            rid = c.execute(es.insert().values(equipment=eid, state=st, start=ts, created_at=ts, updated_at=ts)).inserted_primary_key[0]
            c.execute(TABLES['equipment'].update().where(TABLES['equipment'].c.id == eid).values(status=STATE_MAP.get(st, 'idle')))
        self.state[eid] = (st, ts, rid)

    def _alarm(self, eid, msg, ts):
        cur = self.alarm.get(eid)
        if (cur[0] if cur else '') == msg:
            return
        t = TABLES['alarm']
        with db.engine.begin() as c:
            if cur:
                st = c.execute(sa.select(t.c.start).where(t.c.id == cur[1])).scalar()
                c.execute(t.update().where(t.c.id == cur[1]).values(end=ts, dur_s=(ts - st).total_seconds() if st else None))
            rid = c.execute(t.insert().values(equipment=eid, msg=msg, start=ts, created_at=ts, updated_at=ts)).inserted_primary_key[0] if msg else None
        self.alarm[eid] = (msg, rid) if msg else None

    def _tool_count(self, eid, tool, n):
        t = TABLES['tool']
        with db.engine.begin() as c:
            c.execute(t.update().where((t.c.equipment == eid) & (t.c.code == tool)).values(used=n))

    def flush(self):
        """定期把最新值和电耗写库。"""
        if self.pending_state:
            pend, self.pending_state = self.pending_state, {}
            now = clock.now()
            es = TABLES['equip_state']
            with db.engine.begin() as c:
                for eid, (st, ts) in pend.items():
                    if eid in self.state:
                        continue
                    start = ts if (now - ts).total_seconds() < 120 else now
                    rid = c.execute(es.insert().values(equipment=eid, state=st, start=start, created_at=start, updated_at=start)).inserted_primary_key[0]
                    c.execute(TABLES['equipment'].update().where(TABLES['equipment'].c.id == eid).values(status=STATE_MAP.get(st, 'idle')))
                    self.state[eid] = (st, start, rid)
        if self.dirty_latest:
            tl = db.metadata.tables['tag_latest']
            keys, self.dirty_latest = self.dirty_latest, set()
            with db.engine.begin() as c:
                for k in keys:
                    eid, name, val, num, ts = self.latest[k]
                    r = c.execute(tl.update().where(tl.c.key == k).values(value=val, num=num, ts=ts, equipment=eid, name=name))
                    if r.rowcount == 0:
                        c.execute(tl.insert().values(key=k, equipment=eid, name=name, value=val, num=num, ts=ts))
        if self.energy_acc:
            acc, self.energy_acc = self.energy_acc, defaultdict(float)
            t = TABLES['energy_hour']
            with db.engine.begin() as c:
                for (eid, hour), kwh in acc.items():
                    r = c.execute(t.update().where((t.c.equipment == eid) & (t.c.hour == hour)).values(kwh=t.c.kwh + kwh))
                    if r.rowcount == 0:
                        c.execute(t.insert().values(equipment=eid, hour=hour, kwh=kwh, created_at=hour, updated_at=hour))

    # ---------- 网关：零件事件 ----------
    def active_wo(self, c, product: int | None) -> int | None:
        if product is None:
            return None
        wid = self.cache_wo.get(product)
        if wid:
            wo = db.get(c, 'work_order', wid)
            if wo and wo['status'] in ('released', 'in_progress') and self.wo_born.get(wid, 0) < wo['qty']:
                return wid
        t = TABLES['work_order']
        cands = db.rows(c, 'work_order', t.c.status.in_(('released', 'in_progress')), order=(t.c.priority, t.c.start_plan, t.c.id), product=product)
        for wo in cands:
            if wo['id'] not in self.wo_born:
                pt = TABLES['part']
                self.wo_born[wo['id']] = c.execute(sa.select(sa.func.count()).select_from(pt).where(pt.c.work_order == wo['id'])).scalar()
            if self.wo_born[wo['id']] < wo['qty']:
                self.cache_wo[product] = wo['id']
                return wo['id']
        return None

    def on_part(self, src: str, m: dict):
        ts = parse_dt(m.get('t')) or clock.now()
        clock.feed(ts)
        sn, ev, station, data = m['sn'], m['event'], m.get('station', ''), m.get('data') or {}
        self.stats['part_events'] += 1
        pt = TABLES['part']
        with db.engine.begin() as c:
            part = db.get(c, 'part', sn=sn)
            if ev in ('poured', 'received') and part and part['born_at'] and (ts - part['born_at']).total_seconds() > 60:
                # 编号重复（仿真重启或扫码错误）：旧记录改名归档
                c.execute(pt.update().where(pt.c.id == part['id']).values(sn=f"{sn}~{part['id']}"))
                pe = TABLES['part_event']      # 旧件的履历跟着一起改名，追溯不丢
                c.execute(pe.update().where(pe.c.sn == sn).values(sn=f"{sn}~{part['id']}"))
                part = None
            if part is None:
                prod = self.product_of(m.get('type'))
                wo = self.active_wo(c, prod)
                a = m.get('attrs') or {}
                row = {'sn': sn, 'product': prod, 'work_order': wo, 'status': 'wip', 'station': station, 'born_at': ts, 'rework_count': 0,
                       **{k: a.get(k) for k in ('heat', 'ladle', 'mold', 'cavity', 'pour_temp', 'mg', 'sand_moisture', 'compactability', 'ce')}}
                if a.get('supplier'):
                    row['heat'] = a['supplier']
                pid = db.insert(c, 'part', row, raw=True)
                part = db.get(c, 'part', pid)
                if wo:
                    self.wo_born[wo] = self.wo_born.get(wo, 0) + 1
                    wot = TABLES['work_order']
                    c.execute(wot.update().where((wot.c.id == wo) & (wot.c.status == 'released')).values(status='in_progress'))
                if row.get('heat') and ev == 'poured':
                    ht = TABLES['heat']
                    c.execute(ht.update().where(ht.c.code == row['heat']).values(castings=sa.func.coalesce(ht.c.castings, 0) + 1))
            c.execute(TABLES['part_event'].insert().values(sn=sn, t=ts, station=station, event=ev, data=data, created_at=ts, updated_at=ts))
            upd = {'station': station}
            eid = self.equip(f'{src}:{station}')
            if ev == 'machined':
                upd['machine'] = station
            elif ev == 'inspected':
                if data.get('result') == 'OK':
                    upd['status'] = 'good'
            elif ev == 'rework':
                upd['status'] = 'rework'
                upd['rework_count'] = (part['rework_count'] or 0) + 1
            elif ev == 'scrap':
                upd.update(status='scrap', scrap_cause=data.get('cause'), finished_at=ts)
            elif ev == 'stored':
                upd['status'] = 'fg'
            elif ev == 'shipped':
                upd.update(status='shipped', finished_at=ts)
            elif ev == 'to_raw_store':
                upd['status'] = 'raw_store'
            elif ev == 'delivered' and part['status'] == 'raw_store':
                upd['status'] = 'wip'
            c.execute(pt.update().where(pt.c.id == part['id']).values(updated_at=ts, **upd))
            part.update(upd)
            # 自动报工
            proc = EVENT_PROC.get(ev)
            if proc and part['work_order']:
                ok = not (ev == 'inspected' and data.get('result') == 'NG')
                self._auto_report(c, part['work_order'], proc, eid, ok, ts)
                if ev == 'poured':        # 熔炼、球化没有单件事件：按浇注出的铸件一并计入
                    for up in ('melting', 'treatment'):
                        self._auto_report(c, part['work_order'], up, None, True, ts)
            if ev == 'scrap' and part['work_order']:
                wot = TABLES['work_order']
                c.execute(wot.update().where(wot.c.id == part['work_order']).values(qty_scrap=sa.func.coalesce(wot.c.qty_scrap, 0) + 1))
            if ev == 'stored' and part['work_order']:
                self._wo_done(c, part['work_order'], ts)
            # 质量
            from .services import quality
            if ev == 'machined' and data.get('bore') is not None:
                quality.auto_measure(c, part, station, 'BORE_DIA', float(data['bore']), ts)
            elif ev == 'inspected':
                quality.auto_inspection(c, part, station, data.get('result'), data.get('cause') or '', ts)
            elif ev == 'rework':
                quality.on_rework(c, part, station, data.get('reason') or '', ts)
            elif ev == 'scrap':
                quality.on_scrap(c, part, station, data.get('cause') or '', ts)
                if part.get('heat'):
                    ht = TABLES['heat']
                    c.execute(ht.update().where(ht.c.code == part['heat']).values(scrap=sa.func.coalesce(ht.c.scrap, 0) + 1))
            # 库存 / 物流
            from .services import warehouse
            if ev in ('to_raw_store', 'stored', 'shipped') or (ev == 'delivered' and data.get('from_store')):
                warehouse.on_part_move(c, part, ev, ts)
            if ev == 'delivered':
                warehouse.on_agv_delivery(c, data.get('agv'), data.get('to'), ts)

    def _auto_report(self, c, wo_id, proc, eid, ok, ts):
        ops = TABLES['wo_op']
        prt = TABLES['process']
        op = c.execute(sa.select(ops).join(prt, prt.c.id == ops.c.process).where((ops.c.work_order == wo_id) & (prt.c.ptype == proc))
                       .order_by(ops.c.seq).limit(1)).mappings().first()
        if not op:
            return
        vals = {'qty_good': (op['qty_good'] or 0) + (1 if ok else 0), 'qty_ng': (op['qty_ng'] or 0) + (0 if ok else 1), 'updated_at': ts}
        if not op['act_start']:
            vals['act_start'] = ts
        if op['status'] in ('waiting', 'ready'):
            vals['status'] = 'running'
        if vals['qty_good'] >= (op['qty_plan'] or 0) > 0:
            vals.update(status='done', act_end=ts)
        c.execute(ops.update().where(ops.c.id == op['id']).values(**vals))
        # 自动报工按小时汇总成一条，避免每件一条
        rt = TABLES['report']
        hour = ts.replace(minute=0, second=0, microsecond=0)
        r = c.execute(sa.select(rt.c.id).where((rt.c.wo_op == op['id']) & (rt.c.source == 'auto') & (rt.c.start == hour)
                                              & ((rt.c.equipment == eid) if eid else rt.c.equipment.is_(None)))).scalar()
        if r:
            c.execute(rt.update().where(rt.c.id == r).values(qty_good=rt.c.qty_good + (1 if ok else 0), qty_ng=rt.c.qty_ng + (0 if ok else 1), end=ts,
                                                          updated_at=ts))
        else:
            db.insert(c, 'report', {'work_order': wo_id, 'wo_op': op['id'], 'process': op['process'], 'equipment': eid, 'qty_good': 1 if ok else 0,
                                    'qty_ng': 0 if ok else 1, 'start': hour, 'end': ts, 'source': 'auto'}, raw=True)

    def _wo_done(self, c, wo_id, ts):
        wot = TABLES['work_order']
        c.execute(wot.update().where(wot.c.id == wo_id).values(qty_done=sa.func.coalesce(wot.c.qty_done, 0) + 1, updated_at=ts))
        wo = db.get(c, 'work_order', wo_id)
        if wo['qty_done'] >= wo['qty'] and wo['status'] == 'in_progress':
            c.execute(wot.update().where(wot.c.id == wo_id).values(status='completed', completed_at=ts))

    # ---------- 网关：生产日志 ----------
    def on_event(self, src: str, ev: dict):
        ts = parse_dt(ev.get('t')) or clock.now()
        clock.feed(ts)
        kind, station = ev.get('kind'), ev.get('station', '')
        self.stats['events'] += 1
        eid = self.equip(f'{src}:{station}')
        from .services import foundry
        with db.engine.begin() as c:
            if kind == 'heat' and ev.get('heat'):
                foundry.on_heat(c, eid, ev, ts)
            elif kind == 'chem' and ev.get('heat') and ev.get('C') is not None:
                foundry.on_chem(c, ev, ts)
            elif kind == 'treat' and ev.get('mg') is not None:
                db.insert(c, 'treatment_rec', {'ladle': ev.get('ladle'), 'heat_code': ev.get('heat'), 'temp': ev.get('temp'), 'mg': ev.get('mg'),
                                               'kg': ev.get('kg'), 'time': ts}, raw=True)
            elif kind == 'tool' and ev.get('tool'):
                self._tool_change(c, eid, ev['tool'], ev.get('tool_name'), ev.get('used'), 'life', ts)
            elif kind == 'alarm' and ev.get('broken') and ev.get('tool'):
                self._tool_change(c, eid, ev['tool'], None, ev.get('used'), 'broken', ts)
            elif kind == 'ship' and ev.get('qty'):
                db.insert(c, 'shipment', {'qty': ev['qty'], 'time': ts, 'customer': _tr('主机厂')}, raw=True)

    def _tool_change(self, c, eid, tool, name, used, reason, ts):
        db.insert(c, 'tool_change', {'equipment': eid, 'tool': tool, 'tool_name': name, 'used': used, 'reason': reason, 'time': ts}, raw=True)
        t = TABLES['tool']
        c.execute(t.update().where((t.c.equipment == eid) & (t.c.code == tool)).values(
            used=0, changes=sa.func.coalesce(t.c.changes, 0) + 1, last_change=ts, status='ok', updated_at=ts))


ING = Ingest()
