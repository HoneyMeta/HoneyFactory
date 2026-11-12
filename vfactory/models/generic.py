"""通用行为块：用户在流程图里自由组合，不写代码就能搭出任意离散制造车间。

物料通过"队列"流动：缓存块本身是一个队列；两个非缓存块直接相连时，连线自带一个小队列。
每个块的输入/输出队列由流程图连线决定（cfg['_in'] / cfg['_out']，由 flow.model.expand 填好）。

状态：Executing 运行 / Starved 饥饿（没有来料）/ Blocked 阻塞（下游满）/ Setup 换型 / Stopped 故障 / Planned 计划停机
"""
from ..i18n import _tr
import math

from ..core import Station
from ..flow.expr import Ctx, ExprError, evaluate


class Block(Station):
    kind = 'block'
    area = ''
    fault_kinds = {'failure': '设备故障停机'}
    split_streams = True        # 每个块：节拍表达式、故障、路由、产品比例、质量各用一条独立随机流（公共随机数）
    _ctl_gate = 'take'          # 4.3：接了 PLC 的 Enable 时在取料处门控（正在加工的件做完）

    def __init__(self, plant, cfg):
        self.ins = list(cfg.get('_in') or [])
        self.outs = list(cfg.get('_out') or [])
        self.ctx = Ctx(plant.child_rng(cfg['id'] + ':x'), None, plant)
        self.rng_route = plant.child_rng(cfg['id'] + ':route')
        self.rng_mix = plant.child_rng(cfg['id'] + ':mix')
        super().__init__(plant, cfg)
        self.ctx.st = self
        self.count = 0
        self.ng = 0
        self.last_product = None
        self.blocked_s = self.starved_s = 0.0

    # ---- 参数与表达式 ----
    def p(self, k, default=None):
        v = self.cfg.get(k)
        return default if v in (None, '') else v

    def ev(self, src, default=0.0, **extra):
        if src in (None, ''):
            return default
        if isinstance(src, (int, float)):
            return src
        try:
            return evaluate(str(src), self.ctx, **extra)
        except ExprError as e:
            if self.alarm != _tr('表达式错误：{e}', e=e):
                self.alarm = _tr('表达式错误：{e}', e=e)
                self.plant.log(self.id, 'alarm', self.alarm)
            return default

    def secs(self, src, default):
        return max(0.1, float(self.ev(src, default)))

    def secs_item(self, src, default, item):
        """带零件属性的用时表达式（可写 item['type'] 或 tbl('工时', item.get('type'), '时间')）。"""
        if isinstance(src, str) and 'item' in src:
            return max(0.1, float(self.ev(src, default, item=item)))
        return self.secs(src, default)

    # ---- 队列 ----
    def take(self, n=1):
        if self._plc_wired and self.ctl_hold():       # 4.3：PLC 没给"允许运行"，不取新料
            self._ctl_refused = self._ctl_refused or self.available() > 0
            return None
        for key in self.ins:
            q = self.plant.buffers.get(key)
            if q is not None and len(q):
                return q.get()
        return None

    def take_where(self, pred):
        """从来料队列里挑第一件满足条件的（装配按 BOM 取料用）。"""
        if self._plc_wired and self.ctl_hold():
            self._ctl_refused = self._ctl_refused or self.available() > 0
            return None
        for key in self.ins:
            q = self.plant.buffers.get(key)
            if q is None:
                continue
            for it in q.items:
                if pred(it):
                    q.items.remove(it)
                    return it
        return None

    def available(self):
        return sum(len(self.plant.buffers[k]) for k in self.ins if k in self.plant.buffers)

    def put(self, item, port='out') -> bool:
        cands = []
        for o in self.outs:
            if (o.get('port') or 'out') != port:
                continue
            q = self.plant.buffers.get(o['buf'])
            if q is None or q.full():
                continue
            if o.get('products') and item.get('type') not in o['products']:
                continue
            if o.get('cond'):
                ok = self.ev(o['cond'], False, item=item)
                if not ok:
                    continue
            cands.append((o, q))
        if not cands:
            return False
        rule = self.p('route', 'seq')
        if rule == 'ratio' and len(cands) > 1:
            w = [float(o.get('weight') or 1) for o, _ in cands]
            i = int(self.rng_route.choice(len(cands), p=[x / sum(w) for x in w]))
            o, q = cands[i]
        elif rule == 'shortest':
            o, q = min(cands, key=lambda c: len(c[1]) / max(1, c[1].capacity))
        else:
            o, q = cands[0]
        q.put(item)
        return True

    def has_out(self, port='out'):
        return any((o.get('port') or 'out') == port for o in self.outs)

    # ---- 质量 ----
    def apply_quality(self, item):
        for d in self.p('defects', []) or []:
            pr = self.ev(d.get('prob'), 0.0, item=item)
            if self.rng.random() < float(pr):
                item.setdefault('defects', {})[d.get('name') or _tr('缺陷')] = round(float(self.ev(d.get('size', 1.0), 1.0, item=item)), 3)
        for k, src in (self.p('attrs', {}) or {}).items():
            item[k] = self.ev(src, None, item=item)

    def setup_needed(self, item):
        """换型时间（秒）。有换型矩阵时按"上一个产品 → 这个产品"查（顺序相关），查不到用 * 通配，再查不到用统一换型时间。"""
        prod = item.get('type')
        prev, self.last_product = self.last_product, prod
        if prev is None or prod == prev:
            return 0.0
        v = None
        mx = self.p('setup_matrix')
        if isinstance(mx, dict) and mx:
            for a, b in ((prev, prod), (prev, '*'), ('*', prod), ('*', '*')):
                row = mx.get(a)
                if isinstance(row, dict) and row.get(b) not in (None, ''):
                    v = row[b]
                    break
        if v is None:
            v = self.p('setup_min', 0)
        try:
            return max(0.0, float(v or 0)) * 60
        except (TypeError, ValueError):
            return 0.0

    def operator_pool(self):
        pid = self.p('operator')
        return self.plant.find(pid) if pid else None

    def idle_power(self):
        return float(self.p('idle_kw', 1.0))

    def base_tags(self):
        A = self.add_tag
        A('Production/Count', 0, _tr('件'), _tr('累计完成'))
        A('Production/InProcess', 0, _tr('件'), _tr('在加工'))
        A('Production/NG', 0, _tr('件'), _tr('不合格'))
        A('Production/LastCycle', 0.0, 's', _tr('上一件用时'))
        A('Queue/Input', 0, _tr('件'), _tr('待加工（上游队列）'))

    def sync_tags(self, inproc=0, last=None):
        self.set('Production/Count', self.count)
        self.set('Production/InProcess', inproc)
        self.set('Production/NG', self.ng)
        if last is not None:
            self.set('Production/LastCycle', round(last, 1))
        self.set('Queue/Input', self.available())

    def quality_rate(self):
        return (self.count - self.ng) / self.count if self.count else 1.0


class Source(Block):
    kind = 'source'
    area = '收货区'
    _ctl_gate = 'freeze'        # 4.3：Enable=0 时不放料

    def ctl_partin(self):
        return bool(self.waiting)
    fault_kinds = {'failure': '供应中断'}

    def build_tags(self):
        A = self.add_tag
        A('Production/Count', 0, _tr('件'), _tr('累计到货'))
        A('Setpoint/Enabled', True, '', _tr('放料开关'), writable=True)
        A('Queue/Waiting', 0, _tr('件'), _tr('因下游满等待放行'))
        self.next_t = 0.0
        self.waiting = []
        self.sched = self._load_schedule()
        self.si, self.rep = 0, 0

    def _load_schedule(self):
        """来料按数据表（订单/排程）：列 时间(小时或日期时间)、产品、数量、订单。"""
        name = self.p('table')
        if not name:
            return None
        from ..datatables import schedule_rows
        return schedule_rows(self.plant, name)

    def _release(self, prod=None, order=None):
        if prod is None:
            mix = self.p('products') or []
            if mix:
                w = [float(m.get('weight', 1)) for m in mix]
                prod = mix[int(self.rng_mix.choice(len(mix), p=[x / sum(w) for x in w]))]['code']
        part = self.plant.new_part(heat=self.p('lot_prefix', self.name), mold='', defects={}, rework=0)
        if prod:
            part['type'] = prod
        if order:
            part['order'] = order
        self.apply_quality(part)
        part.event(self.plant, self.id, 'received')
        self.plant.kpi['castings'] += 1
        self.count += 1
        self.waiting.append(part)

    def step(self, dt):
        if self.sched is not None:
            period = float(self.p('repeat_h', 0) or 0) * 3600
            while self.sched and self.get('Setpoint/Enabled'):
                if self.si >= len(self.sched):
                    if period <= 0:
                        break
                    self.si, self.rep = 0, self.rep + 1
                t, prod, qty, order = self.sched[self.si]
                if t + self.rep * period > self.plant.t:
                    break
                for _ in range(qty):
                    self._release(prod, order)
                self.si += 1
        else:
            self.next_t -= dt
            if self.next_t <= 0 and self.get('Setpoint/Enabled'):
                self.next_t = self.secs(self.p('interval', 'expo(120)'), 120)
                for _ in range(int(self.p('batch', 1) or 1)):
                    self._release()
        while self.waiting and self.put(self.waiting[0]):
            self.waiting.pop(0)
        self.state = 'Blocked' if self.waiting else 'Executing'
        self.power_kw = 0.0
        self.set('Production/Count', self.count)
        self.set('Queue/Waiting', len(self.waiting))


class Processor(Block):
    """加工：capacity 个工位并行；节拍表达式；产品换型；可要求操作工。"""
    kind = 'processor'
    area = '加工区'
    fault_kinds = {'failure': '设备故障停机', 'slow': '节拍变慢 30%（刀具/模具磨损）'}

    def build_tags(self):
        self.base_tags()
        self.add_tag('Setpoint/SpeedPct', 100.0, '%', _tr('速度倍率'), writable=True, lo=30, hi=150)
        self.slots = [{'item': None, 'left': 0.0, 'phase': '', 'total': 0.0, 'op': False} for _ in range(max(1, int(self.p('capacity', 1) or 1)))]
        self.setup_left = 0.0
        self.slow = 1.0

    def on_fault(self, kind):
        if kind == 'slow':
            self.slow = 1.3
            return ''
        return super().on_fault(kind)

    def inject(self, kind):
        if kind == 'clear':
            self.slow = 1.0
        return super().inject(kind)

    def on_failure(self):
        for s in self.slots:
            if s['item'] is not None and s['phase'] == 'run' and self.p('scrap_on_failure'):
                self.plant.scrap(s['item'], self.id, _tr('故障报废'))
                s.update(item=None, phase='')

    def step(self, dt):
        pool = self.operator_pool()
        speed = self.get('Setpoint/SpeedPct') / 100
        if self.setup_left > 0:
            self.setup_left -= dt
            self.state, self.alarm = 'Setup', _tr('换型中')
            self.power_kw = self.idle_power()
            if self.setup_left <= 0:
                self.alarm = ''
            return
        running = blocked = 0
        for s in self.slots:
            if s['item'] is None:
                it = self.take()
                if it is None:
                    continue
                st = self.setup_needed(it)
                src = None
                tbp = self.p('times_by_product')
                if isinstance(tbp, dict) and tbp:
                    src = tbp.get(it.get('type'), tbp.get('*'))
                if src in (None, ''):
                    src = self.p('time', 'normal(60,3)')
                s.update(item=it, left=self.secs_item(src, 60, it) * (self.plant.cycle_factor() if self.p('product_factor', True) else 1) * self.slow,
                         phase='run', op=False)
                s['total'] = s['left']
                if self.acts is not None and s is self.slots[0]:      # 5.0 动作级信号（参数 actions: cnc / press / robot），只跟第一个工位
                    ex = self.acts.cycle(self.plant.t, s['left'] / max(speed, 1e-3))
                    s['left'] += ex * max(speed, 1e-3)
                    s['total'] = s['left']
                it.event(self.plant, self.id, 'start')
                if st > 0:
                    self.setup_left = st
                    self.plant.log(self.id, 'plan', _tr('换型 → {get}', get=it.get('type')))
                    return
            if s['phase'] == 'run':
                if pool is not None and s['op'] is False:
                    got = pool.acquire(self.id, self.p('skill') or self.id)
                    if not got:
                        self.alarm = _tr('等待操作工')
                        continue
                    s['op'] = True
                    self.alarm = ''
                    eff = got if isinstance(got, float) else 1.0
                    if eff > 0 and abs(eff - 1.0) > 1e-9:      # 操作工熟练度：效率 0.8 → 用时 ÷0.8
                        s['left'] /= eff
                        s['total'] /= eff
                s['left'] -= dt * speed
                running += 1
                if pool is not None and s['op'] and self.p('operator_mode', 'load') == 'load' and s['total'] - s['left'] >= float(self.p('load_s', 20)):
                    pool.release(self.id)
                    s['op'] = None
                if s['left'] <= 0:
                    if pool is not None and s['op']:
                        pool.release(self.id)
                    self.apply_quality(s['item'])
                    self.count += 1
                    s['item'].event(self.plant, self.id, 'processed', cycle=round(s['total'] / max(speed, 1e-3)))
                    self.set('Production/LastCycle', round(s['total'], 1))
                    s['phase'] = 'done'
            if s['phase'] == 'done':
                if self.put(s['item']):
                    s.update(item=None, phase='')
                else:
                    blocked += 1
        busy = sum(1 for s in self.slots if s['item'] is not None)
        self.state = 'Executing' if running else 'Blocked' if blocked else 'Starved' if not busy else 'Idle'
        n = len(self.slots)
        self.power_kw = self.idle_power() + float(self.p('run_kw', 10)) * running / n
        self.sync_tags(busy)


class Batch(Block):
    """批处理：凑够一批（或等待超时）一起处理，如抛丸、热处理、清洗。"""
    kind = 'batch'
    area = '加工区'

    def build_tags(self):
        self.base_tags()
        self.add_tag('Batch/Loaded', 0, _tr('件'), _tr('本批已装'))
        self.add_tag('Batch/Count', 0, _tr('批'), _tr('累计批数'))
        self.load, self.left, self.wait, self.done = [], 0.0, 0.0, []
        self.batches = 0

    def step(self, dt):
        size = int(self.p('batch', 10) or 10)
        if self.done:
            while self.done and self.put(self.done[0]):
                self.done.pop(0)
            self.state = 'Blocked' if self.done else 'Idle'
        elif self.left > 0:
            self.left -= dt
            self.state = 'Executing'
            if self.left <= 0:
                for it in self.load:
                    self.apply_quality(it)
                    it.event(self.plant, self.id, 'processed', batch=self.batches + 1)
                self.count += len(self.load)
                self.batches += 1
                self.done, self.load = self.load, []
        else:
            while len(self.load) < size:
                it = self.take()
                if it is None:
                    break
                self.load.append(it)
            self.wait = self.wait + dt if self.load else 0.0
            if len(self.load) >= size or (self.load and self.wait >= float(self.p('max_wait_min', 30)) * 60):
                self.left = self.secs(self.p('time', '600'), 600)
                self.state = 'Executing'
            else:
                self.state = 'Starved'
        self.power_kw = self.idle_power() + (float(self.p('run_kw', 30)) if self.state == 'Executing' else 0)
        self.set('Batch/Loaded', len(self.load))
        self.set('Batch/Count', self.batches)
        self.sync_tags(len(self.load) + len(self.done))


class BufferBlock(Block):
    """缓存：本身就是一个队列（plant.buffers[id]），只负责发布点位。"""
    kind = 'buffer'
    area = '物流'
    fault_kinds = {}

    def build_tags(self):
        A = self.add_tag
        A('Queue/Count', 0, _tr('件'), _tr('当前数量'))
        A('Queue/Capacity', int(self.p('capacity', 50)), _tr('件'), _tr('容量'))
        A('Queue/Utilization', 0.0, '%', _tr('占用率'))

    def step(self, dt):
        q = self.plant.buffers.get(self.id)
        n = len(q) if q is not None else 0
        self.set('Queue/Count', n)
        if q is not None:
            self.set('Queue/Capacity', q.capacity)
            self.set('Queue/Utilization', round(n / max(1, q.capacity) * 100, 1))
        self.state = 'Executing' if n else 'Idle'
        self.power_kw = 0.0

    def view(self):
        q = self.plant.buffers.get(self.id)
        return {'count': len(q) if q is not None else 0, 'cap': q.capacity if q is not None else 0}


class Conveyor(Block):
    kind = 'conveyor'
    area = '物流'
    _ctl_gate = 'freeze'        # 4.3：Enable / Run 为 0 时整条带停

    def ctl_partin(self):
        return bool(self.items) or self.available() > 0

    def build_tags(self):
        A = self.add_tag
        A('Conveyor/Count', 0, _tr('件'), _tr('线上件数'))
        A('Conveyor/Speed', float(self.p('speed_mps', 0.2)), 'm/s', _tr('速度'), writable=True, lo=0, hi=2)
        A('Production/Count', 0, _tr('件'), _tr('累计输送'))
        self.items = []   # [item, 位置 m]

    def step(self, dt):
        L, pitch = float(self.p('length_m', self.size[0])), float(self.p('pitch_m', 1.0))
        v = self.get('Conveyor/Speed')
        head_blocked = False
        for i, pair in enumerate(self.items):
            limit = L if i == 0 else self.items[i - 1][1] - pitch
            pair[1] = min(limit, pair[1] + v * dt)
        if self.items and self.items[0][1] >= L:
            if self.put(self.items[0][0]):
                self.items.pop(0)
                self.count += 1
            else:
                head_blocked = True
        if (not self.items or self.items[-1][1] >= pitch) and len(self.items) < int(L / pitch):
            it = self.take()
            if it is not None:
                self.items.append([it, 0.0])
        self.state = 'Blocked' if head_blocked else 'Executing' if self.items and v > 0 else 'Starved'
        self.power_kw = self.idle_power() + (float(self.p('run_kw', 2)) if self.state == 'Executing' else 0)
        self.set('Conveyor/Count', len(self.items))
        self.set('Production/Count', self.count)

    def view(self):
        L = float(self.p('length_m', self.size[0]))
        return {'items': [round(x[1] / max(L, 1e-6), 3) for x in self.items][:200]}


class Inspection(Block):
    """检测：每种缺陷按检出率判 NG，另有误判率；结果走 ok / ng 两个出口。"""
    kind = 'inspect'
    area = '检测区'

    def build_tags(self):
        self.base_tags()
        A = self.add_tag
        A('Result/Last', '', '', _tr('最近一件结果'), dtype='str')
        A('Result/OK', 0, _tr('件'), _tr('累计合格'))
        A('Result/NG', 0, _tr('件'), _tr('累计不合格'))
        A('Setpoint/PodPct', float(self.p('pod_pct', 95)), '%', _tr('检出率'), writable=True, lo=0, hi=100)
        A('Setpoint/FalsePct', float(self.p('false_pct', 1)), '%', _tr('误判率'), writable=True, lo=0, hi=50)
        self.cur, self.left, self.ok = None, 0.0, 0

    def step(self, dt):
        if self.cur is None:
            self.cur = self.take()
            if self.cur is not None:
                self.left = self.secs(self.p('time', '30'), 30)
        if self.cur is None:
            self.state, self.power_kw = 'Starved', self.idle_power()
            self.sync_tags(0)
            return
        if self.left > 0:
            self.left -= dt
            self.state = 'Executing'
            if self.left <= 0:
                it = self.cur
                real = [k for k, v in (it.get('defects') or {}).items() if v]
                pod = self.get('Setpoint/PodPct') / 100
                found = [k for k in real if self.rng.random() < pod]
                if not real and self.rng.random() < self.get('Setpoint/FalsePct') / 100:
                    found = [_tr('误判')]
                ng = bool(found)
                it['result'] = 'NG' if ng else 'OK'
                it['inspection'] = {'result': it['result'], 'found': found, 'truth': real}
                if real and not ng:
                    self.plant.kpi['escape'] += 1
                if ng and not real:
                    self.plant.kpi['overkill'] += 1
                self.count += 1
                if ng:
                    self.ng += 1
                else:
                    self.ok += 1
                it.event(self.plant, self.id, 'inspected', result=it['result'], cause=_tr('、').join(found))
                self.set('Result/Last', it['result'])
                self.set('Result/OK', self.ok)
                self.set('Result/NG', self.ng)
        else:
            it = self.cur
            port = 'ng' if it.get('result') == 'NG' and self.has_out('ng') else 'out'
            if it.get('result') == 'NG' and not self.has_out('ng'):
                self.plant.scrap(it, self.id, _tr('检测不合格'))
                self.cur = None
            elif self.put(it, port):
                if it.get('result') == 'OK':
                    it['status'] = 'GOOD'
                self.cur = None
            else:
                self.state = 'Blocked'
        self.power_kw = self.idle_power() + (float(self.p('run_kw', 2)) if self.state == 'Executing' else 0)
        self.sync_tags(1 if self.cur else 0)


class Rework(Block):
    """返修：修好可修复的缺陷后送回；超过返修次数直接报废。"""
    kind = 'rework'
    area = '检测区'

    def build_tags(self):
        self.base_tags()
        self.cur, self.left = None, 0.0

    def step(self, dt):
        if self.cur is None:
            it = self.take()
            if it is not None:
                it['rework'] = it.get('rework', 0) + 1
                if it['rework'] > int(self.p('max_rework', 1)):
                    self.plant.scrap(it, self.id, _tr('返修次数超限'))
                    self.ng += 1
                else:
                    self.cur = it
                    self.left = self.secs(self.p('time', '120'), 120)
                    it.event(self.plant, self.id, 'rework')
        if self.cur is not None:
            if self.left > 0:
                self.left -= dt
                self.state = 'Executing'
                if self.left <= 0:
                    fix = self.p('fixes') or None
                    d = self.cur.get('defects') or {}
                    for k in list(d):
                        if (fix is None or k in fix) and self.rng.random() < float(self.p('success_pct', 90)) / 100:
                            d.pop(k)
                    self.count += 1
            elif self.put(self.cur):
                self.cur = None
            else:
                self.state = 'Blocked'
        else:
            self.state = 'Starved'
        self.power_kw = self.idle_power() + (float(self.p('run_kw', 3)) if self.state == 'Executing' else 0)
        self.sync_tags(1 if self.cur else 0)


class Assembly(Block):
    """装配：凑够 parts 件合成 1 件（第一件为主件，其余记为子件）。"""
    kind = 'assembly'
    area = '加工区'

    def build_tags(self):
        self.base_tags()
        self.kit, self.left, self.out = [], 0.0, None

    def step(self, dt):
        n = int(self.p('parts', 2) or 2)
        if self.out is not None:
            if self.put(self.out):
                self.out = None
            self.state = 'Blocked' if self.out is not None else 'Idle'
        elif self.left > 0:
            self.left -= dt
            self.state = 'Executing'
            if self.left <= 0:
                main = self.kit[0]
                main['children'] = [x['id'] for x in self.kit[1:]]
                for x in self.kit[1:]:
                    x['status'] = 'CONSUMED'
                    x.event(self.plant, self.id, 'assembled', into=main['id'])
                    for k, v in (x.get('defects') or {}).items():
                        main.setdefault('defects', {})[k] = v
                self.apply_quality(main)
                main.event(self.plant, self.id, 'processed', parts=len(self.kit))
                self.count += 1
                self.out, self.kit = main, []
        else:
            bom = self.p('bom')
            if isinstance(bom, dict) and bom:            # 按 BOM 取料：{"子件A":2,"子件B":1}
                need = {k: int(v) for k, v in bom.items()}
                for it in self.kit:
                    if need.get(it.get('type'), 0) > 0:
                        need[it.get('type')] -= 1
                while any(v > 0 for v in need.values()):
                    it = self.take_where(lambda x: need.get(x.get('type'), 0) > 0)
                    if it is None:
                        break
                    need[it.get('type')] -= 1
                    self.kit.append(it)
                ready = not any(v > 0 for v in need.values())
            else:
                while len(self.kit) < n:
                    it = self.take()
                    if it is None:
                        break
                    self.kit.append(it)
                ready = len(self.kit) >= n
            if ready and self.kit:
                self.left = self.secs(self.p('time', '60'), 60)
                if isinstance(bom, dict) and bom:           # 主件 = BOM 里第一个子件类型
                    first = next(iter(bom))
                    self.kit.sort(key=lambda x: x.get('type') != first)
                if self.p('out_product'):
                    self.kit[0]['type'] = self.p('out_product')
            self.state = 'Executing' if self.left > 0 else 'Starved'
        self.power_kw = self.idle_power() + (float(self.p('run_kw', 3)) if self.state == 'Executing' else 0)
        self.sync_tags(len(self.kit))


class Split(Block):
    """拆分：1 件拆成 n 件（新件继承属性）。"""
    kind = 'split'
    area = '加工区'

    def build_tags(self):
        self.base_tags()
        self.pending = []

    def step(self, dt):
        while self.pending and self.put(self.pending[0]):
            self.pending.pop(0)
        if not self.pending:
            it = self.take()
            if it is not None:
                for i in range(int(self.p('pieces', 2) or 2)):
                    c = self.plant.new_part(**{k: v for k, v in it.items() if k not in ('id', 'history', 't0', 'type', 'status', 'order')})
                    c['type'] = it.get('type')
                    c['parent'] = it['id']
                    c.event(self.plant, self.id, 'split', parent=it['id'])
                    self.pending.append(c)
                it['status'] = 'CONSUMED'
                self.count += 1
        self.state = 'Blocked' if self.pending else 'Starved'
        self.power_kw = self.idle_power()
        self.sync_tags(len(self.pending))


class Sink(Block):
    """出口：成品入库 / 发运；scrap=true 时作为报废出口。"""
    kind = 'sink'
    area = '仓储区'
    fault_kinds = {}

    def build_tags(self):
        A = self.add_tag
        A('Production/Count', 0, _tr('件'), _tr('累计接收'))
        A('Stock/Count', 0, _tr('件'), _tr('库存'))
        self.stock = []
        self.next_ship = float(self.p('ship_every_h', 0) or 0) * 3600

    def step(self, dt):
        while True:
            it = self.take()
            if it is None:
                break
            self.count += 1
            if self.p('scrap'):
                if it.get('status') != 'SCRAP':
                    self.plant.scrap(it, self.id, self.p('scrap_cause', _tr('判废')))
                continue
            it['status'] = 'FG'
            self.plant.kpi['good'] += 1
            it.event(self.plant, self.id, 'stored')
            self.stock.append(it)
        ev = float(self.p('ship_every_h', 0) or 0)
        if ev > 0:
            self.next_ship -= dt
            if self.next_ship <= 0:
                self.next_ship = ev * 3600
                n = len(self.stock)
                for it in self.stock:
                    it['status'] = 'SHIPPED'
                    it.event(self.plant, self.id, 'shipped')
                self.stock = []
                self.plant.kpi['shipped'] += n
                if n:
                    self.plant.log(self.id, 'ship', _tr('发运 {n} 件', n=n), qty=n)
        self.state = 'Idle'
        self.power_kw = 0.0
        self.set('Production/Count', self.count)
        self.set('Stock/Count', len(self.stock))

    def view(self):
        return {'stock': len(self.stock)}


class Operators(Block):
    """人员池：加工块可指定从这里要人；休息、非生产时间不可用。"""
    kind = 'operators'
    area = '人员'
    fault_kinds = {'absent': '一人缺勤（2 小时）'}

    def build_tags(self):
        A = self.add_tag
        A('Crew/OnDuty', self.headcount(), _tr('人'), _tr('在岗'))
        A('Crew/Busy', 0, _tr('人'), _tr('作业中'))
        self.busy: list[str] = []
        self.busy_w: list[int] = []          # 与 busy 对应：占用的是第几个人
        self.absent = 0.0

    def workers(self):
        """操作工技能：workers=[{"name":"张三","skills":["M1","车削"],"eff":1.1}]；skills 为空表示什么都会。"""
        w = self.p('workers')
        return w if isinstance(w, list) and w else None

    def headcount(self):
        w = self.workers()
        return len(w) if w else int(self.p('count', 2))

    def available(self):
        n = self.headcount() - (1 if self.absent > 0 else 0)
        if self.plant.plan.in_break or self.plant.plan.off_reason:
            return 0
        return n - len(self.busy)

    def acquire(self, who, skill=None):
        """要一个人。没有技能表时返回 True；有技能表时返回该操作工的效率（float，>0）或 False。"""
        if self.available() <= 0:
            return False
        ws = self.workers()
        if not ws:
            self.busy.append(who)
            self.busy_w.append(-1)
            return True
        n_ok = len(ws) - (1 if self.absent > 0 else 0)
        for i, w in enumerate(ws[:n_ok]):
            if i in self.busy_w:
                continue
            sk = w.get('skills') or []
            if sk and skill not in sk and who not in sk and '*' not in sk:
                continue
            self.busy.append(who)
            self.busy_w.append(i)
            try:
                return max(0.05, float(w.get('eff', 1.0) or 1.0))
            except (TypeError, ValueError):
                return 1.0
        return False

    def release(self, who):
        if who in self.busy:
            i = self.busy.index(who)
            self.busy.pop(i)
            self.busy_w.pop(i)

    def on_fault(self, kind):
        if kind == 'absent':
            self.absent = 7200
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        if self.absent > 0:
            self.absent -= dt
        self.set('Crew/OnDuty', self.headcount() - (1 if self.absent > 0 else 0))
        self.set('Crew/Busy', len(self.busy))
        self.state = 'Executing' if self.busy else 'Idle'
        self.power_kw = 0.0


class Transporter(Block):
    """搬运车队：负责所有 via=本块 的连线，从起点队列取一车送到终点队列。"""
    kind = 'transporter'
    area = '物流'
    fault_kinds = {'failure': '调度系统故障'}

    def build_tags(self):
        A = self.add_tag
        A('Fleet/Vehicles', int(self.p('count', 2)), _tr('台'), _tr('车辆数'))
        A('Fleet/Busy', 0, _tr('台'), _tr('执行任务中'))
        A('Fleet/Trips', 0, _tr('次'), _tr('累计任务'))
        self.routes = list(self.cfg.get('_routes') or [])
        hx, hy = self.pos
        self.vehicles = [{'id': f'{self.id}-{i + 1}', 'x': hx + i * 1.5, 'y': hy, 'state': 'Idle', 'task': None, 'load': [], 'left': 0.0, 'phase': '',
                          'from': None, 'to': None, 'soc': 100.0} for i in range(int(self.p('count', 2)))]
        self.trips = 0

    def _network(self):
        """平面图里画的 AGV 路网（plant.layout.paths）；没有或本车队关掉"按路网行驶"时返回 None。
        返回 (节点坐标, 邻接表 {节点: [(下一节点, 长度 m, 该边车速 m/s)]}, 站点绑定 {设备编号: 节点})。
        边可以限速（vmax，m/s），车速取车队速度和限速中较小的；单向边只能顺着走。"""
        if self.p('network', True) in (False, 'false', 0):
            return None
        net = ((self.plant.cfg.get('plant') or {}).get('layout') or {}).get('paths') or {}
        nodes = {n['id']: (float(n['x']), float(n['y'])) for n in net.get('nodes') or []}
        if len(nodes) < 2 or not net.get('edges'):
            return None
        spd = max(0.1, float(self.p('speed_mps', 1.2) or 1.2))
        adj = {k: [] for k in nodes}
        for e in net['edges']:
            a, b = e.get('a'), e.get('b')
            if a in nodes and b in nodes:
                w = math.dist(nodes[a], nodes[b])
                v = spd
                try:
                    vm = float(e.get('vmax') or 0)
                    if vm > 0:
                        v = min(spd, vm)
                except (TypeError, ValueError):
                    pass
                adj[a].append((b, w, v))
                if not e.get('oneway'):
                    adj[b].append((a, w, v))
        bound = {}
        for n in net.get('nodes') or []:
            if n.get('block') and n.get('id') in nodes:
                bound.setdefault(n['block'], n['id'])
        return nodes, adj, bound

    def _route(self, x0, y0, x, y):
        """起点到终点的行驶折线和每段车速：有路网就走用时最短的路（单向边只能顺着走，限速边按限速算）。
        终点是某台设备、且路网里有站点绑定了这台设备时，车停在那个站点（取放点）上。
        4.7：没画路网（或本车队关掉"按路网行驶"）才走直线；画了路网却走不通时返回 None——车停下报警，不再直线穿墙。"""
        spd = max(0.1, float(self.p('speed_mps', 1.2) or 1.2))
        net = self._network()
        if not net:
            return [(x0, y0), (x, y)], [spd]
        nodes, adj, bound = net
        near = lambda px, py: min(nodes, key=lambda k: (nodes[k][0] - px) ** 2 + (nodes[k][1] - py) ** 2)
        s = near(x0, y0)
        t = None
        for bid, nid in bound.items():
            st = self.plant.stations.get(bid)
            if st is not None and math.dist(tuple(st.pos[:2]), (x, y)) < 0.01:
                t = nid
                break
        at_station = t is not None
        if t is None:
            t = near(x, y)
        import heapq
        dist, prev, q = {s: 0.0}, {}, [(0.0, s)]
        while q:
            d, u = heapq.heappop(q)
            if u == t:
                break
            if d > dist.get(u, 1e18):
                continue
            for w, c, v in adj[u]:
                dt = c / v
                if d + dt < dist.get(w, 1e18):
                    dist[w], prev[w] = d + dt, (u, v)
                    heapq.heappush(q, (d + dt, w))
        if t not in dist:
            return None
        chain, speeds, k = [t], [], t
        while k != s:
            k, v = prev[k]
            chain.append(k)
            speeds.append(v)
        chain.reverse()
        speeds.reverse()
        pts = [(x0, y0)] + [nodes[k] for k in chain]
        sp = [spd] + speeds
        if not at_station:
            pts.append((x, y))
            sp.append(spd)
        return pts, sp

    def _path(self, x0, y0, x, y):
        """起点到终点的行驶折线（见 _route）；路网上走不通返回 None。"""
        r = self._route(x0, y0, x, y)
        return r[0] if r else None

    def _travel(self, v, x, y):
        """规划一段行程，返回 (用时 s, 距离 m)；路网上走不通返回 None（车不动）。"""
        r = self._route(v['x'], v['y'], x, y)
        if r is None:
            return None
        pts, sp = r
        segs = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        segt = [L / max(0.1, s) for L, s in zip(segs, sp)]
        v['path'], v['segs'], v['segt'] = pts, segs, segt
        return sum(segt), sum(segs)

    STUCK_RETRY_S = 60.0

    def _stuck(self, v, msg, leg):
        """4.7 路网走不通：车原地停下（Blocked）并报警，每分钟（仿真时间）重试一次（路网改好后自动继续）。"""
        first = v.get('stuck') != msg
        v.update(phase='stuck', state='Blocked', stuck=msg, leg=leg, retry=self.STUCK_RETRY_S)
        if first:
            self.plant.log(self.id, 'alarm', _tr('{id}：{msg}', id=v['id'], msg=msg), agv=v['id'], route=(v.get('route') or {}).get('id'))

    def _leg_msg(self, v, r, leg):
        an, bn = r.get('an') or r['src'], r.get('bn') or r['dst']
        if leg == 'to_dst':
            return _tr('{an}无法到达{bn}，请补充道路', an=an, bn=bn)
        if v.get('at'):
            return _tr('{at}无法返回{an}，请补充返回道路', at=v['at'], an=an)
        return _tr('{name}的停车位置开不到{an}，请补充道路', name=self.name, an=an)

    def _start_leg(self, v, leg):
        """开始一段行程（to_src 空车去取料 / to_dst 送料）。走不通返回 False（车已停下报警）。"""
        r = v['route']
        tgt = r['a'] if leg == 'to_src' else r['b']
        tr = self._travel(v, *tgt)
        if tr is None:
            self._stuck(v, self._leg_msg(v, r, leg), leg)
            return False
        v['phase'] = leg
        v['from'], v['to'] = (v['x'], v['y']), tgt
        v['left'] = tr[0]
        v['dwell'] = float(self.p('load_s', 30)) if leg == 'to_dst' else 0.0     # 装卸时间：原地停着，不算行驶
        v['left'] += v['dwell']
        v['T'] = v['left']
        v.pop('stuck', None)
        return True

    def _place(self, v, f):
        """按行驶用时的进度 f（0~1）把车放到折线上（限速段走得慢）。"""
        pts, segs = v.get('path'), v.get('segs')
        if not pts or len(pts) < 2:
            v['x'] = v['from'][0] + (v['to'][0] - v['from'][0]) * f
            v['y'] = v['from'][1] + (v['to'][1] - v['from'][1]) * f
            return
        tt = v.get('segt') or segs
        want, acc = f * sum(tt), 0.0
        for i, T in enumerate(tt):
            if acc + T >= want or i == len(tt) - 1:
                g = 0.0 if T <= 1e-9 else min(1.0, max(0.0, (want - acc) / T))
                v['x'] = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * g
                v['y'] = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * g
                return
            acc += T

    def step(self, dt):
        cap = int(self.p('capacity', 4) or 4)
        busy = stuck = 0
        for v in self.vehicles:
            if v['phase'] == 'stuck':                  # 4.7 路网走不通：原地等，定时重试（路网改好就继续）
                stuck += 1
                v['state'] = 'Blocked'
                v['retry'] = v.get('retry', 0) - dt
                if v['retry'] > 0:
                    continue
                leg = v.get('leg') or 'to_src'
                if leg == 'to_dst':
                    r = v['route']
                    if self._route(v['x'], v['y'], *r['b']) is None:
                        v['retry'] = self.STUCK_RETRY_S
                        continue
                    src = self.plant.buffers[r['src']]
                    while len(v['load']) < cap and len(src):
                        v['load'].append(src.get())
                if not self._start_leg(v, leg):
                    continue
                stuck -= 1
            if v['phase'] == '':
                for r in self.routes:
                    src, dst = self.plant.buffers.get(r['src']), self.plant.buffers.get(r['dst'])
                    if src is None or dst is None or not len(src) or dst.full():
                        continue
                    if any(o['task'] == r['id'] for o in self.vehicles if o is not v) and len(src) < cap * 2:
                        continue
                    v.update(task=r['id'], route=r)
                    if not self._start_leg(v, 'to_src'):
                        stuck += 1
                    break
            if v['phase'] == 'stuck':
                continue
            if v['phase']:
                busy += 1
                v['left'] -= dt
                f = 1 - max(0.0, v['left'] - v.get('dwell', 0.0)) / max(1e-6, v.get('T', 1) - v.get('dwell', 0.0))
                self._place(v, min(1.0, f))
                v['state'] = 'Moving'
                if v['left'] <= 0:
                    r = v['route']
                    if v['phase'] == 'to_src':
                        v['at'] = r.get('an') or r['src']
                        if self._route(v['x'], v['y'], *r['b']) is None:      # 送不过去：先别装车，停在取料点报警
                            self._stuck(v, self._leg_msg(v, r, 'to_dst'), 'to_dst')
                            busy -= 1
                            stuck += 1
                            continue
                        src = self.plant.buffers[r['src']]
                        while len(v['load']) < cap and len(src):
                            v['load'].append(src.get())
                        self._start_leg(v, 'to_dst')
                    else:
                        v['at'] = r.get('bn') or r['dst']
                        dst = self.plant.buffers[r['dst']]
                        while v['load'] and not dst.full():
                            it = v['load'].pop(0)
                            dst.put(it)
                            it.event(self.plant, self.id, 'delivered', to=r['dst'], agv=v['id'])
                        if not v['load']:
                            v.update(phase='', task=None, state='Idle')
                            self.trips += 1
            else:
                v['state'] = 'Idle'
        msgs = [v['stuck'] for v in self.vehicles if v['phase'] == 'stuck' and v.get('stuck')]
        if msgs:
            self.alarm = self._path_alarm = msgs[0]
        elif getattr(self, '_path_alarm', '') and self.alarm == self._path_alarm:
            self.alarm = self._path_alarm = ''
        self.state = 'Executing' if busy else 'Blocked' if stuck else 'Idle'
        self.power_kw = busy * 1.5
        self.set('Fleet/Busy', busy)
        self.set('Fleet/Trips', self.trips)

    def view(self):
        return {'agvs': [{'id': v['id'], 'x': round(v['x'], 2), 'y': round(v['y'], 2), 'state': v['state'], 'soc': 100, 'load': len(v['load']), 'task': v['task'] or ''}
                         for v in self.vehicles]}


class Storage(Sink):
    kind = 'storage'


class Submodel(Block):
    """子模型：把一段产线封装成一个块（可多层）。内部的块由 flow.model.expand 展开成 cfg['_children']，
    在这里建成真正的设备并每步推进；它们不在 plant.stations 里（不影响模型结构），用 plant.find / all_stations 可以找到。"""
    kind = 'submodel'
    area = '子模型'
    fault_kinds = {}

    def build_tags(self):
        A = self.add_tag
        A('Production/Count', 0, _tr('件'), _tr('子模型出口累计'))
        A('Sub/Running', 0, _tr('台'), _tr('内部运行中的块'))
        A('Sub/Stopped', 0, _tr('台'), _tr('内部故障的块'))
        self.children = []
        from . import REGISTRY
        for sc in self.cfg.get('_children') or []:
            cls = REGISTRY.get(sc.get('type'))
            if cls is None:
                continue
            ch = cls(self.plant, sc)
            ch._child = True
            self.children.append(ch)
            self.plant.sub_index[ch.id] = ch
            self.plant.sub_parent[ch.id] = self.id
        self.exit_id = self.cfg.get('_exit')

    def step(self, dt):
        run = stop = 0
        pw = 0.0
        for ch in self.children:
            ch.tick(dt)
            pw += ch.power_kw
            run += ch.state == 'Executing'
            stop += ch.state == 'Stopped'
        ex = self.plant.sub_index.get(self.exit_id) if self.exit_id else None
        self.count = getattr(ex, 'count', 0) if ex is not None else 0
        self.state = 'Stopped' if stop and not run else 'Executing' if run else 'Starved'
        self.power_kw = pw
        self.set('Production/Count', self.count)
        self.set('Sub/Running', run)
        self.set('Sub/Stopped', stop)

    def view(self):
        return {'children': [{'id': c.id, 'name': c.name, 'state': c.state} for c in self.children[:40]]}


GENERIC = {'source': Source, 'processor': Processor, 'batch': Batch, 'buffer': BufferBlock, 'conveyor': Conveyor, 'inspect': Inspection,
           'rework': Rework, 'assembly': Assembly, 'split': Split, 'sink': Sink, 'storage': Storage, 'operators': Operators, 'transporter': Transporter,
           'submodel': Submodel}


def network_issues(model: dict) -> list:
    """AGV 路网检查（平面图里画的 plant.layout.paths），给模型检查用。返回 [(级别, 说明, 对象编号)]，
    对象编号写成 path:节点或连线编号，平面图据此标出有问题的节点。检查：端点缺失、站点绑定的设备不存在、
    孤立站点、单向死路（只进不出 / 只出不进）、站点之间不可达、走搬运车队的连线在路网上走不通（4.7 起是错误：车会停下报警，并指出缺哪一段路）。"""
    net = (((model.get('plant') or {}).get('layout') or {}).get('paths')) or {}
    nodes = {n['id']: n for n in net.get('nodes') or [] if n.get('id')}
    edges = net.get('edges') or []
    out = []
    if not nodes:
        return out
    blocks = {b['id']: b for b in model.get('blocks') or []}
    succ = {k: set() for k in nodes}
    pred = {k: set() for k in nodes}
    for e in edges:
        a, b = e.get('a'), e.get('b')
        if a not in nodes or b not in nodes:
            out.append(('warn', _tr('路网连线 {get} 的端点不存在', get=e.get("id")), f'path:{e.get("id")}'))
            continue
        succ[a].add(b)
        pred[b].add(a)
        if not e.get('oneway'):
            succ[b].add(a)
            pred[a].add(b)
        vm = e.get('vmax')
        if vm not in (None, ''):
            try:
                bad = float(vm) <= 0
            except (TypeError, ValueError):
                bad = True
            if bad:
                out.append(('warn', _tr('路网连线 {get} 的限速必须是大于 0 的数（m/s）', get=e.get("id")), f'path:{e.get("id")}'))
    label = lambda k: (_tr('站点 ') if nodes[k].get('kind') == 'station' else _tr('充电点 ') if nodes[k].get('kind') == 'charger' else _tr('节点 ')) + k + (
        _tr('（{get}）', get=blocks[nodes[k]["block"]].get("name", nodes[k]["block"])) if nodes[k].get('block') in blocks else '')
    for k, n in nodes.items():
        if n.get('block') and n['block'] not in blocks:
            out.append(('warn', _tr('{label} 绑定的设备 {block} 不存在', label=label(k), block=n["block"]), f'path:{k}'))
        if not succ[k] and not pred[k] and len(nodes) > 1:
            out.append(('warn', _tr('{label} 没有连到路网上', label=label(k)), f'path:{k}'))
    for k in nodes:
        if pred[k] and not succ[k]:
            out.append(('warn', _tr('单向死路：车开到 {label} 后出不来（连到它的都是单向驶入的线）', label=label(k)), f'path:{k}'))
        elif succ[k] and not pred[k]:
            out.append(('warn', _tr('{label} 只能驶出、开不进去（单向线的方向可能画反了）', label=label(k)), f'path:{k}'))

    def reach(s):
        seen, st = {s}, [s]
        while st:
            for w in succ[st.pop()]:
                if w not in seen:
                    seen.add(w)
                    st.append(w)
        return seen
    cache = {}
    R = lambda s: cache.setdefault(s, reach(s))
    stations = [k for k, n in nodes.items() if (n.get('kind') in ('station', 'charger') or n.get('block')) and (succ[k] or pred[k])]
    for t in stations:
        miss = [s for s in stations if s != t and t not in R(s)]
        if miss:
            more = _tr(' 等 {len} 处', len=len(miss)) if len(miss) > 3 else ''
            out.append(('warn', _tr('{label} 从 {join}{more} 开不过去（路网不连通或单向线挡住了）', label=label(t), join=_tr('、').join(miss[:3]), more=more), f'path:{t}'))
    # 搬运车队的连线：起点设备到终点设备、再空车返回，路网上都要走得通
    if len(nodes) >= 2 and edges:
        xy = {k: (float(n.get('x', 0)), float(n.get('y', 0))) for k, n in nodes.items()}
        bound = {}
        for k, n in nodes.items():
            if n.get('block'):
                bound.setdefault(n['block'], k)

        def node_for(b):
            if b['id'] in bound:
                return bound[b['id']]
            p = b.get('pos') or [0, 0]
            return min(xy, key=lambda k: (xy[k][0] - p[0]) ** 2 + (xy[k][1] - p[1]) ** 2)

        def near(p):
            return min(xy, key=lambda k: (xy[k][0] - p[0]) ** 2 + (xy[k][1] - p[1]) ** 2)

        def missing(s, t):
            """s 开不到 t 时，最该补的一段路：从 s 能到的节点里、离"能开到 t 的节点"最近的一对；那里正好有一条反向的单向线就建议改成双向。"""
            fr = R(s)
            to = [k for k in nodes if t in R(k)]
            u, w = min(((a, b) for a in fr for b in to), key=lambda ab: math.dist(xy[ab[0]], xy[ab[1]]))
            rev = next((e for e in edges if e.get('oneway') and e.get('a') == w and e.get('b') == u), None)
            tip = _tr('，或把单向线 {get}（{w}→{u}）改成双向', get=rev.get("id"), w=w, u=u) if rev else ''
            return _tr('缺少从 {label} 到 {label2} 的道路（约 {dist:.0f} m）{tip}', label=label(u), label2=label(w), dist=math.dist(xy[u], xy[w]), tip=tip)
        homes, legs = set(), {}
        for l in model.get('links') or []:
            tr = blocks.get(l.get('via') or '')
            A, B = blocks.get(l.get('from')), blocks.get(l.get('to'))
            if not tr or tr.get('type') != 'transporter' or not A or not B:
                continue
            if (tr.get('params') or {}).get('network', True) in (False, 'false', 0):
                continue
            an, bn, tn = A.get('name', A['id']), B.get('name', B['id']), tr.get('name', tr['id'])
            na, nb = node_for(A), node_for(B)
            # 4.7：画了路网却走不通，车会停下报警（不再直线穿行）——模型检查里是错误，并指出缺哪一段路
            if nb not in R(na):
                out.append(('error', _tr('{an}无法到达{bn}（{tn}）：{missing}', an=an, bn=bn, tn=tn, missing=missing(na, nb)), l.get('id')))
            elif na not in R(nb):
                out.append(('error', _tr('{bn}无法返回{an}（{tn} 空车返回）：{missing}，请补充返回道路', bn=bn, an=an, tn=tn, missing=missing(nb, na)), l.get('id')))
            hn = near(tr.get('pos') or [0, 0])
            if tr['id'] not in homes and na not in R(hn):
                homes.add(tr['id'])
                out.append(('error', _tr('{tn}的停车位置开不到{an}：{missing}', tn=tn, an=an, missing=missing(hn, na)), tr['id']))
            legs.setdefault(tr['id'], []).append((na, nb, an, bn, l.get('id'), tn))
        # 同一车队有几条搬运任务：送完一单（停在某个终点）以后要能开到任何一单的起点
        for tid, ls in legs.items():
            seen = set()
            for i, (_, nb, _, bn, lid, tn) in enumerate(ls):
                for j, (na2, _, an2, _, _, _) in enumerate(ls):
                    if i == j or (nb, na2) in seen or na2 in R(nb):
                        continue
                    seen.add((nb, na2))
                    out.append(('error', _tr('{bn}无法开到{an2}（{tn} 接下一单）：{missing}', bn=bn, an2=an2, tn=tn, missing=missing(nb, na2)), lid))
    return out
