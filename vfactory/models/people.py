"""人员：按岗位配置的班组，以及纯机加工厂用的"毛坯来料"站。

工人不是装饰：设了岗位的设备（例如 CNC 上下料），要等工人走到位才能继续，人手不够时产量会掉。
每个工人的位置、状态通过 OPC UA / MQTT 发布，相当于工厂里的 UWB 人员定位标签。
"""
from ..i18n import _tr
import math

from ..core import Station

ROLE_NEED = {
    # 设备类型 -> 判断"现在需要人"的函数
    'furnace': lambda s: getattr(s, 'phase', '') in ('Charging', 'Sampling'),
    'treatment': lambda s: any(l['state'] in ('Tapping', 'Treating') for l in s.ladles),
    'molding': lambda s: s.pour_left > 0,
    'shotblast': lambda s: s.left > 0 and s.left > s.get('Setpoint/BlastMin') * 60 - 120,
    'cnc': lambda s: s.part is not None and s.handling > 0,
    'deburr': lambda s: s.setup > 0,
    'inspection': lambda s: s.get('Result/Last') == 'NG',
    'warehouse': lambda s: s.crane_left > 0,
}


class WorkerCrew(Station):
    kind = 'crew'
    area = '人员'
    fault_kinds = {'absent': '一名工人缺勤（2 小时）'}

    def build_tags(self):
        self.workers = []
        n = 0
        for r in self.cfg.get('roles', []):
            for i in range(int(r.get('count', 1))):
                n += 1
                home = r.get('home') or self._station_xy(r['stations'][0])
                self.workers.append(dict(id=f'W{n:02d}', role=r['name'], stations=list(r['stations']), patrol=r.get('patrol'),
                                         x=home[0] + i * 1.2, y=home[1] + 2.5, home=list(home), state='idle', target=None, task=None,
                                         serving=None, carry=False, absent=0.0, wp=0, look=0.0))
        A = self.add_tag
        A('Crew/OnDuty', len(self.workers), _tr('人'), _tr('在岗人数'))
        A('Crew/Busy', 0, _tr('人'), _tr('正在作业人数'))
        for w in self.workers:
            for k, u, d in (('X', 'm', _tr('X 坐标')), ('Y', 'm', _tr('Y 坐标')), ('State', '', _tr('状态')), ('Role', '', _tr('岗位')), ('Station', '', _tr('服务设备'))):
                A(f"{w['id']}/{k}", '' if u == '' else 0.0, u, f"{w['id']} {d}", dtype='str' if u == '' else 'float')
            self.set(f"{w['id']}/Role", w['role'])

    def _station_xy(self, sid):
        st = self.plant.stations.get(sid)
        if st:
            return [st.pos[0], st.pos[1]]
        b = self.plant.buffers.get(sid)
        if b is not None:
            from ..tracking import buffer_pos
            return buffer_pos(self.plant, sid)
        return [0.0, 0.0]

    def service_point(self, sid):
        st = self.plant.stations.get(sid)
        if not st:
            return self._station_xy(sid)
        return [st.pos[0], st.pos[1] + st.size[1] / 2 + 0.9]

    def present(self, sid) -> bool:
        """这台设备如果配了岗位，是否有人在旁边作业；没配岗位的设备视为不需要人。"""
        covered = [w for w in self.workers if sid in w['stations']]
        if not covered:
            return True
        return any(w['serving'] == sid and w['state'] in ('work',) for w in covered)

    def on_fault(self, kind):
        if kind == 'absent':
            w = next((w for w in self.workers if not w['absent']), None)
            if w:
                w['absent'] = 7200
                w['serving'] = None
                self.plant.log(self.id, 'crew', _tr('{id}（{role}）缺勤', id=w['id'], role=w['role']))
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        busy = 0
        on_break = bool(self.plant.plan.in_break or self.plant.plan.off_reason)
        claimed = {w['serving'] for w in self.workers if w['serving']}
        for w in self.workers:
            if w['absent'] > 0:
                w['absent'] -= dt
                w['state'] = 'absent'
                w['x'], w['y'] = -999, -999
                continue
            if w['x'] < -900:
                w['x'], w['y'] = w['home'][0], w['home'][1] + 2.5
            if on_break and w['serving']:
                claimed.discard(w['serving'])
                w['serving'] = None
                w['target'] = None
            # 当前服务的设备不再需要人 → 释放
            if w['serving']:
                st = self.plant.stations.get(w['serving'])
                need = ROLE_NEED.get(st.kind) if st else None
                if not st or not need or not need(st):
                    claimed.discard(w['serving'])
                    w['serving'] = None
                    w['target'] = None
            # 找需要人的设备（休息时不接活）
            if not w['serving'] and not on_break:
                for sid in w['stations']:
                    st = self.plant.stations.get(sid)
                    need = ROLE_NEED.get(st.kind) if st else None
                    if st and need and need(st) and sid not in claimed:
                        w['serving'] = sid
                        claimed.add(sid)
                        w['target'] = self.service_point(sid)
                        w['carry'] = st.kind in ('cnc', 'shotblast')
                        break
            if not w['serving'] and w['patrol']:
                if w['target'] is None:
                    pts = w['patrol']
                    w['wp'] = (w['wp'] + 1) % len(pts)
                    w['target'] = list(pts[w['wp']])
            elif not w['serving'] and w['target'] is None:
                hx, hy = w['home']
                if math.hypot(w['x'] - hx, w['y'] - hy - 2.5) > 1.5:
                    w['target'] = [hx, hy + 2.5]
            # 移动
            if w['target']:
                tx, ty = w['target']
                d = math.hypot(tx - w['x'], ty - w['y'])
                spd = 1.3 * dt
                if d <= spd:
                    w['x'], w['y'] = tx, ty
                    w['target'] = None if not w['serving'] else w['target']
                    w['state'] = 'work' if w['serving'] else 'idle'
                    if w['serving']:
                        w['carry'] = False
                    if not w['serving'] and w['patrol']:
                        w['target'] = None
                else:
                    w['x'] += (tx - w['x']) / d * spd
                    w['y'] += (ty - w['y']) / d * spd
                    w['state'] = 'carry' if w['carry'] else 'walk'
                    w['look'] = math.atan2(ty - w['y'], tx - w['x'])
            elif w['serving']:
                w['state'] = 'work'
            else:
                w['state'] = 'idle'
            if w['state'] == 'work':
                busy += 1
            i = w['id']
            self.set(f'{i}/X', round(w['x'], 2)); self.set(f'{i}/Y', round(w['y'], 2))
            self.set(f'{i}/State', w['state']); self.set(f'{i}/Station', w['serving'] or '')
        self.set('Crew/OnDuty', sum(1 for w in self.workers if not w['absent']))
        self.set('Crew/Busy', busy)
        self.state = 'Executing' if busy else 'Idle'
        self.power_kw = 0.0

    def view(self):
        return {'workers': [{'id': w['id'], 'role': w['role'], 'lead': any(x in str(w['role']) for x in ('班长', '组长', 'Lead', 'lead', 'Leader')), 'x': round(w['x'], 2), 'y': round(w['y'], 2), 'state': w['state'],
                             'look': round(w['look'], 2), 'serving': w['serving'] or ''} for w in self.workers if not w['absent']]}


class Receiving(Station):
    """毛坯来料（纯机加工厂）：按节拍到货，铸件缺陷按配置的概率抽样。"""
    kind = 'receiving'
    area = '收货区'
    fault_kinds = {'failure': '供应商断供', 'bad_lot': '来料批次质量差（气孔率 ×5）'}

    def build_tags(self):
        self.left = 0.0
        self.bad = 0.0
        A = self.add_tag
        A('Setpoint/PcsPerHour', float(self.cfg.get('pcs_per_hour', 60)), _tr('件/h'), _tr('到货节拍'), writable=True, lo=1, hi=600)
        A('Setpoint/PorosityPct', float(self.cfg.get('porosity_pct', 3.0)), '%', _tr('来料气孔率'), writable=True, lo=0, hi=50)
        A('Received/Count', 0, _tr('件'), _tr('累计到货'))

    def on_fault(self, kind):
        if kind == 'bad_lot':
            self.bad = 3600
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        out = self.plant.buffers.get(self.port('out', 'raw'))
        self.left -= dt
        self.bad = max(0.0, self.bad - dt)
        if self.left <= 0 and out is not None and not out.full():
            self.left = 3600 / self.get('Setpoint/PcsPerHour')
            pct = self.get('Setpoint/PorosityPct') * (5 if self.bad > 0 else 1) / 100
            d = {}
            if self.rng.random() < pct:
                d['porosity_mm'] = round(float(self.rng.lognormal(math.log(0.6), 0.6)), 3)
            p = self.plant.new_part(heat=self.cfg.get('supplier') or _tr('外购毛坯'), mold='', pour_temp=None, defects=d, rework=0)
            p.event(self.plant, self.id, 'received')
            out.put(p)
            self.plant.kpi['castings'] += 1
            self.set('Received/Count', self.get('Received/Count') + 1)
        self.state = 'Executing' if self.left > 0 else 'Idle'
        self.power_kw = 1.0

    def view(self):
        return {'count': self.get('Received/Count')}
