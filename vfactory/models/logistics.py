"""物流：AGV 车队（毛坯配送、成品入库、毛坯转储）和立体仓库。

AGV 按"先横后纵"的折线行驶，梯形速度近似为匀速 + 起停时间；
电量 dSoC/dt = −(P_行驶 + P_负载)/E，低于阈值自动去充电桩，充到 95% 再接任务。
"""
from ..i18n import _tr
import math

from ..core import Station


class AGVFleet(Station):
    kind = 'agv'
    area = '物流'
    fault_kinds = {'failure': '调度系统故障', 'agv_block': '一台 AGV 被障碍物挡住 10 分钟', 'battery_aging': '电池老化（容量 −40%）'}

    def build_tags(self):
        c = self.cfg
        self.nodes = {k: list(v) for k, v in c['nodes'].items()}
        self.speed = c.get('speed', 1.2)
        self.agvs = []
        for i in range(c.get('count', 3)):
            x, y = self.nodes['charger']
            self.agvs.append(dict(id=f'AGV{i + 1}', x=x + i * 2.2, y=y, soc=90.0 - i * 7, state='Idle', task='', path=[], load=[], wait=0.0,
                                  block=0.0, cap_factor=1.0, odo=0.0))
        A = self.add_tag
        A('Fleet/TasksDone', 0, '', _tr('累计完成任务'))
        A('Fleet/Queue', 0, '', _tr('待执行任务'))
        A('Setpoint/BinSize', 10, _tr('件'), _tr('每车装载件数'), writable=True, lo=1, hi=40)
        A('Setpoint/ChargeBelow', 25.0, '%', _tr('低于此电量去充电'), writable=True, lo=10, hi=60)
        for a in self.agvs:
            for k, u, d in (('X', 'm', _tr('X 坐标')), ('Y', 'm', _tr('Y 坐标')), ('Battery', '%', _tr('电量')), ('State', '', _tr('状态')), ('Task', '', _tr('任务'))):
                A(f"{a['id']}/{k}", '' if u == '' else 0.0, u, f"{a['id']} {d}", dtype='str' if u == '' else 'float')
        self.done = 0

    def history_tags(self):
        return [f"{a['id']}/Battery" for a in self.agvs]

    def on_fault(self, kind):
        if kind == 'agv_block':
            a = next((a for a in self.agvs if a['state'] == 'Moving'), self.agvs[0])
            a['block'] = 600
            self.plant.log(self.id, 'alarm', _tr('{id} 前方有障碍物，停车等待', id=a['id']))
            return ''
        if kind == 'battery_aging':
            for a in self.agvs:
                a['cap_factor'] = 0.6
            return ''
        return super().on_fault(kind)

    def _route(self, a, dest):
        x, y = a['x'], a['y']
        tx, ty = self.nodes[dest]
        corridor = self.cfg.get('corridor_y', 0)
        pts = [(x, corridor), (tx, corridor), (tx, ty)] if abs(y - ty) > 0.5 else [(tx, ty)]
        a['path'] = pts

    def _new_tasks(self):
        P = self.plant.buffers
        n = self.get('Setpoint/BinSize')
        taken = {a['task'] for a in self.agvs}
        tasks = []
        raw, cin, fg = P.get('raw'), P.get('cnc_in'), P.get('fg')
        if raw is not None and cin is not None and len(raw) >= n and cin.capacity - len(cin) - self._inflight('cnc_in') >= n and 'raw→cnc' not in taken:
            tasks.append(('raw', 'cnc_in', 'raw→cnc'))
        if fg is not None and self.plant.of_kind('warehouse') and len(fg) >= n * 2 and 'fg→asrs' not in taken:
            tasks.append(('fg', 'asrs', 'fg→asrs'))
        th = self.cfg.get('store_when', 0.8)
        if raw is not None and 'store' in self.nodes and len(raw) >= max(n, raw.capacity * th) and 'raw→store' not in taken:
            tasks.append(('raw', 'store', 'raw→store'))
        return tasks

    def _inflight(self, dest):
        return sum(len(a['load']) for a in self.agvs if a.get('dest') == dest)

    def step(self, dt):
        P = self.plant.buffers
        moving = 0
        for a in self.agvs:
            E = 25.0 * a['cap_factor']                     # kWh
            if a['block'] > 0:
                a['block'] -= dt
                a['state'] = 'Blocked'
                a['soc'] -= 0.15 / E * dt / 3600 * 100
                continue
            if a['wait'] > 0:
                a['wait'] -= dt
                if a['wait'] <= 0 and a['state'] == 'Loading':
                    self._route(a, a['dest'])
                    a['state'] = 'Moving'
                elif a['wait'] <= 0 and a['state'] == 'Unloading':
                    dest = a['dest']
                    if dest == 'asrs':
                        asrs = self.plant.of_kind('warehouse')[0]
                        for p in a['load']:
                            asrs.store(p)
                    elif dest == 'store':
                        for p in a['load']:
                            p['status'] = 'RAW_STORE'
                            p.event(self.plant, self.id, 'to_raw_store')
                        self.plant.kpi['to_raw_store'] = self.plant.kpi.get('to_raw_store', 0) + len(a['load'])
                    else:
                        for p in a['load']:
                            P[dest].put(p)
                            p.event(self.plant, self.id, 'delivered', to=dest, agv=a['id'])
                    a.update(load=[], task='', dest=None, state='Idle')
                    self.done += 1
                continue
            if a['state'] == 'Moving' and a['path']:
                tx, ty = a['path'][0]
                dx, dy = tx - a['x'], ty - a['y']
                dist = math.hypot(dx, dy)
                step = self.speed * dt
                if dist <= step:
                    a['x'], a['y'] = tx, ty
                    a['path'].pop(0)
                else:
                    a['x'] += dx / dist * step
                    a['y'] += dy / dist * step
                a['odo'] += min(step, dist)
                p_kw = 1.2 + 0.08 * len(a['load'])
                a['soc'] -= p_kw / E * dt / 3600 * 100
                moving += 1
                if not a['path']:
                    if a.get('phase') == 'pickup':
                        src = a['src']
                        n = self.get('Setpoint/BinSize') if a['task'] != 'raw→store' else 40
                        for _ in range(min(n, len(P[src]))):
                            p = P[src].get()
                            a['load'].append(p)
                        a['phase'], a['state'], a['wait'] = 'deliver', 'Loading', 25
                    elif a.get('phase') == 'deliver':
                        a['state'], a['wait'], a['phase'] = 'Unloading', 25, None
                    elif a['state'] == 'Moving' and a['task'] == 'charge':
                        a['state'], a['task'] = 'Charging', 'charge'
            elif a['state'] == 'Charging':
                a['soc'] = min(100.0, a['soc'] + 0.09 * dt)
                if a['soc'] >= 95:
                    a.update(state='Idle', task='')
            elif a['state'] == 'Idle':
                a['soc'] -= 0.05 / E * dt / 3600 * 100
                if a['soc'] < self.get('Setpoint/ChargeBelow'):
                    a.update(task='charge', state='Moving')
                    self._route(a, 'charger')
                else:
                    tasks = self._new_tasks()
                    if tasks:
                        src, dest, name = tasks[0]
                        a.update(task=name, src=src, dest=dest, phase='pickup', state='Moving')
                        self._route(a, src)
            a['soc'] = max(0.0, a['soc'])
            if a['soc'] <= 0.5 and a['state'] == 'Moving':
                a['state'] = 'Blocked'
                self.alarm = _tr('{id} 电量耗尽', id=a['id'])
        for a in self.agvs:
            i = a['id']
            self.set(f'{i}/X', round(a['x'], 2)); self.set(f'{i}/Y', round(a['y'], 2))
            self.set(f'{i}/Battery', round(a['soc'], 1)); self.set(f'{i}/State', a['state']); self.set(f'{i}/Task', a['task'])
        self.set('Fleet/TasksDone', self.done)
        self.set('Fleet/Queue', len(self._new_tasks()))
        self.state = 'Executing' if moving or any(a['state'] in ('Loading', 'Unloading') for a in self.agvs) else 'Idle'
        self.power_kw = sum(1.2 for a in self.agvs if a['state'] == 'Moving') + sum(3.0 for a in self.agvs if a['state'] == 'Charging')
        self.truth = {a['id']: {'odometer_m': round(a['odo'], 1), 'capacity_kwh': 25 * a['cap_factor']} for a in self.agvs}

    def view(self):
        return {'agvs': [{'id': a['id'], 'x': round(a['x'], 2), 'y': round(a['y'], 2), 'soc': round(a['soc']), 'state': a['state'],
                          'load': len(a['load'])} for a in self.agvs]}


class Warehouse(Station):
    """立体仓库：堆垛机入库，按发运计划出库。"""
    kind = 'warehouse'
    area = '仓储区'
    fault_kinds = {'failure': '堆垛机故障'}

    def build_tags(self):
        self.slots = self.cfg.get('slots', 600)
        self.stock = []
        self.queue = []
        self.crane_left = 0.0
        self.crane_pos = 0.0
        self.next_ship = self.cfg.get('ship_every_h', 4) * 3600
        A = self.add_tag
        A('Stock/Count', 0, _tr('件'), _tr('库存件数'))
        A('Stock/Utilization', 0.0, '%', _tr('库位利用率'))
        A('Crane/Position', 0.0, 'm', _tr('堆垛机位置'))
        A('Shipping/Shipped', 0, _tr('件'), _tr('累计发运'))
        A('Setpoint/ShipEveryH', float(self.cfg.get('ship_every_h', 4)), 'h', _tr('发运间隔'), writable=True, lo=1, hi=24)

    def store(self, p):
        self.queue.append(p)

    def step(self, dt):
        if self.crane_left > 0:
            self.crane_left -= dt
            self.crane_pos = 10 + 9 * math.sin(self.plant.t / 9)
            if self.crane_left <= 0 and self.queue:
                p = self.queue.pop(0)
                p['status'] = 'FG'
                p.event(self.plant, self.id, 'stored')
                self.stock.append(p)
        elif self.queue and len(self.stock) < self.slots:
            self.crane_left = 45
        self.next_ship -= dt
        if self.next_ship <= 0:
            n = len(self.stock)
            for p in self.stock:
                p['status'] = 'SHIPPED'
                p.event(self.plant, self.id, 'shipped')
            self.stock = []
            self.plant.kpi['shipped'] += n
            self.next_ship = self.get('Setpoint/ShipEveryH') * 3600
            if n:
                self.plant.log(self.id, 'ship', _tr('发运 {n} 件', n=n), qty=n)
        self.set('Stock/Count', len(self.stock))
        self.set('Stock/Utilization', round(len(self.stock) / self.slots * 100, 1))
        self.set('Crane/Position', round(self.crane_pos, 2))
        self.set('Shipping/Shipped', self.plant.kpi['shipped'])
        self.state = 'Executing' if self.crane_left > 0 else 'Idle'
        self.power_kw = 11 if self.crane_left > 0 else 1.5

    def view(self):
        return {'stock': len(self.stock), 'crane': round(self.crane_pos, 2)}
