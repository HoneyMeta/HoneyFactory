"""生产计划：班次日历、休息、计划停机、产品与订单、换型。

配置在工厂 yaml 的 plan 段（都可省略，省略时 7×24 连续生产、单一产品）：
  shifts:   [{name: 早班, start: '07:00', end: '15:00'}, ...]     不在任何班次内 = 非生产时间
  workdays: [1, 2, 3, 4, 5, 6]                                     周一=1 … 周日=7
  breaks:   [{name: 午餐, start: '11:30', end: '12:00'}]           休息时操作工离岗，要人的设备会停
  downtime: [{station: CNC3, start: '2026-11-03 08:00', hours: 4, reason: 计划保养}]
  products: [{code: SGH-450, name: …, cycle_factor: 1.0, changeover_min: 30}]
  orders:   [{code: SO-001, product: SGH-450, qty: 600, due: '2026-11-05 18:00', customer: …}]
"""
from .i18n import _tr
from datetime import datetime, timedelta

PAUSABLE = {'molding', 'treatment', 'cnc', 'deburr', 'inspection', 'shotblast', 'receiving'}
# 通用加工类块默认也跟班次走（参数 follow_shifts=false 可改成连续运行，如热处理炉）
GENERIC_PAUSABLE = {'processor', 'batch', 'inspect', 'rework', 'assembly', 'split'}
CHANGEOVER_KINDS = ('molding', 'cnc')


def _hm(s):
    h, m = str(s).split(':')[:2]
    return int(h) * 60 + int(m)


def _in(minute, start, end):
    a, b = _hm(start), _hm(end)
    return a <= minute < b if a < b else (minute >= a or minute < b)


class Plan:
    def __init__(self, plant, cfg: dict | None):
        self.plant = plant
        self.cfg = cfg = dict(cfg or {})
        self.shifts = cfg.get('shifts') or []
        self.workdays = set(cfg.get('workdays') or [1, 2, 3, 4, 5, 6, 7])
        self.breaks = cfg.get('breaks') or []
        self.downtime = [dict(d) for d in cfg.get('downtime') or []]
        name = plant.cfg['plant'].get('product', 'SGH-450')
        self.products = cfg.get('products') or [{'code': name.split()[0], 'name': name, 'cycle_factor': 1.0, 'changeover_min': 30}]
        self.orders = [dict(o, done=int(o.get('done', 0)), born=int(o.get('born', 0))) for o in cfg.get('orders') or []]
        self.product = self.products[0]
        self.order = None
        self.off_reason = ''
        self.in_break = ''
        self.station_off: dict[str, str] = {}
        self._first = True

    # ---------- 状态 ----------
    def product_by(self, code):
        return next((p for p in self.products if p['code'] == code), self.products[0])

    def shift_name(self, now: datetime | None = None):
        now = now or self.plant.now()
        m = now.hour * 60 + now.minute
        for s in self.shifts:
            if _in(m, s['start'], s['end']):
                return s['name']
        return '' if self.shifts else _tr('连续生产')

    def update(self):
        p = self.plant
        now = p.now()
        m = now.hour * 60 + now.minute
        working = now.isoweekday() in self.workdays and (not self.shifts or any(_in(m, s['start'], s['end']) for s in self.shifts))
        off = '' if working else (_tr('休息日') if now.isoweekday() not in self.workdays else _tr('非生产时间'))
        if off != self.off_reason:
            p.log('PLAN', 'plan', _tr('{off}，产线暂停', off=off) if off else _tr('开班：{shift_name}', shift_name=self.shift_name(now)))
            if off:
                p.label_open('PLANT', 'planned', off)
            else:
                p.label_close('PLANT', 'planned')
        self.off_reason = off
        br = next((b.get('name') or _tr('休息') for b in self.breaks if _in(m, b['start'], b['end'])), '') if working else ''
        if br != self.in_break:
            p.log('PLAN', 'plan', _tr('{br}开始，操作工离岗', br=br) if br else _tr('休息结束'))
        self.in_break = br
        # 计划停机
        active = {}
        for d in self.downtime:
            st = datetime.fromisoformat(str(d['start']).replace(' ', 'T'))
            if st <= now < st + timedelta(hours=float(d.get('hours', 1))):
                active[d['station']] = _tr('计划停机：{get}', get=d.get('reason') or _tr('保养'))
        for sid in set(active) - set(self.station_off):
            p.log(sid, 'plan', active[sid])
            p.label_open(sid, 'planned', active[sid])
        for sid in set(self.station_off) - set(active):
            p.log(sid, 'plan', _tr('计划停机结束'))
            p.label_close(sid, 'planned')
        self.station_off = active
        # 订单 → 当前产品
        # 按投产数切换订单（多投 3% 抵报废），入库数显示完成进度
        o = next((o for o in self.orders if o['born'] < o['qty'] * 1.03), None)
        if o is not self.order:
            self.order = o
            if o:
                p.log('PLAN', 'plan', _tr('开始订单 {code}（{product} × {qty}）', code=o['code'], product=o['product'], qty=o['qty']))
        want = self.product_by(o['product']) if o else self.product
        if want['code'] != self.product['code']:
            mins = float(want.get('changeover_min', 30))
            if not self._first:
                for s in p.stations.values():
                    if s.kind in CHANGEOVER_KINDS:
                        s.changeover_left = mins * 60
                        s.changeover_to = want['code']
                p.log('PLAN', 'plan', _tr('产品切换 {code} → {code2}，造型线和加工中心换型 {mins:g} 分钟', code=self.product['code'], code2=want['code'], mins=mins))
                p.label_open('PLANT', 'changeover', _tr('换型 → {code}', code=want['code']), minutes=mins)
            self.product = want
        self._first = False

    def blocked(self, st) -> str:
        if st.id in self.station_off:
            return self.station_off[st.id]
        if self.off_reason and (st.kind in PAUSABLE or (st.kind in GENERIC_PAUSABLE and st.cfg.get('follow_shifts', True) is not False)):
            return self.off_reason
        return ''

    def on_born(self, part):
        if self.order:
            part['order'] = self.order['code']
            self.order['born'] += 1

    def on_stored(self, part):
        code = part.get('order')
        o = next((x for x in self.orders if x['code'] == code), None)
        if o:
            o['done'] += 1
            if o['done'] == o['qty']:
                self.plant.log('PLAN', 'plan', _tr('订单 {code} 完成', code=o['code']))

    def view(self):
        p = self.plant
        rate = p.recent_rate()
        out = []
        t = p.now()
        for o in self.orders:
            left = max(0, o['qty'] - o['done'])
            eta = None
            if left and rate > 0:
                t = t + timedelta(hours=left / rate)
                eta = t.strftime('%Y-%m-%d %H:%M')
            due = o.get('due')
            out.append({**o, 'left': left, 'eta': eta if left else _tr('已完成'),
                        'late': bool(eta and due and eta > str(due)[:16])})
        return {'product': self.product, 'order': self.order['code'] if self.order else None, 'shift': self.shift_name(), 'off': self.off_reason,
                'break': self.in_break, 'station_off': self.station_off, 'orders': out, 'rate_per_h': round(rate, 1), 'cfg': self.export()}

    def export(self):
        return {'shifts': self.shifts, 'workdays': sorted(self.workdays), 'breaks': self.breaks, 'downtime': self.downtime, 'products': self.products,
                'orders': [{k: v for k, v in o.items() if k not in ('left', 'eta', 'late')} for o in self.orders]}
