"""造型区：砂处理、造型线 + 浇注、冷却线、抛丸清理。

砂处理：混砂机按"水分设定值"用 PI 控制加水；回砂温度越高水分蒸发越快。
    紧实率 ≈ 40 + 25·(水分 − 3.4)，湿压强度随水分先升后降（经验曲线）。
铸件缺陷（每件抽样，作为后工序的"真值"）：
    气孔概率 p = σ(β0 + β1·水分偏高 + β2·浇注温度偏低/偏高 + β3·紧实率偏离)
    缩松概率 p = σ(γ0 + γ1·残镁不足 + γ2·碳当量偏离)，冷隔：浇注温度 < 1340 °C 时急剧上升
    球化不良：残镁 < 0.030 % 时按整包判废（实际靠炉前三角试块/金相发现）
"""
from ..i18n import _tr
import math

from ..core import AMBIENT, Station


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


class SandSystem(Station):
    kind = 'sand'
    area = '造型区'
    fault_kinds = {'failure': '设备故障停机', 'valve_stuck': '加水阀卡死', 'sensor_drift': '水分仪漂移'}

    def build_tags(self):
        self.moist = 3.4
        self.ret_T = 40.0
        self.level = 70.0
        self.integ = 0.0
        self.valve_stuck = None
        self.drift = 0.0
        u = self.cfg.get('modbus_unit', 1)
        A = self.add_tag
        A('Setpoint/Moisture', 3.40, '%', _tr('型砂水分设定'), writable=True, lo=2.5, hi=4.5, modbus={'kind': 'hr', 'addr': 100, 'scale': 100, 'unit': u})
        A('Setpoint/AutoControl', True, '', _tr('水分自动控制'), writable=True, modbus={'kind': 'coil', 'addr': 0, 'unit': u})
        A('Setpoint/WaterManual', 20.0, 'L/min', _tr('手动加水量'), writable=True, lo=0, hi=80, modbus={'kind': 'hr', 'addr': 101, 'scale': 10, 'unit': u})
        A('Sand/Moisture', 3.4, '%', _tr('型砂水分（在线水分仪）'), modbus={'kind': 'hr', 'addr': 0, 'scale': 100, 'unit': u})
        A('Sand/Compactability', 40.0, '%', _tr('紧实率'), modbus={'kind': 'hr', 'addr': 1, 'scale': 10, 'unit': u})
        A('Sand/GreenStrength', 150.0, 'kPa', _tr('湿压强度'), modbus={'kind': 'hr', 'addr': 2, 'scale': 10, 'unit': u})
        A('Sand/ReturnTemp', 40.0, '°C', _tr('回砂温度'), modbus={'kind': 'hr', 'addr': 3, 'scale': 10, 'unit': u})
        A('Mixer/WaterFlow', 20.0, 'L/min', _tr('加水流量'), modbus={'kind': 'hr', 'addr': 4, 'scale': 10, 'unit': u})
        A('Mixer/Current', 0.0, 'A', _tr('混砂机电流'), modbus={'kind': 'hr', 'addr': 5, 'scale': 10, 'unit': u})
        A('Hopper/Level', 70.0, '%', _tr('砂斗料位'), modbus={'kind': 'hr', 'addr': 6, 'scale': 10, 'unit': u})
        A('Mixer/Running', True, '', _tr('混砂机运行'), modbus={'kind': 'coil', 'addr': 10, 'unit': u})

    def history_tags(self):
        return ['Sand/Moisture', 'Sand/Compactability', 'Sand/ReturnTemp', 'Mixer/WaterFlow']

    def on_fault(self, kind):
        if kind == 'valve_stuck':
            self.valve_stuck = self.get('Mixer/WaterFlow')
            return ''
        if kind == 'sensor_drift':
            self.drift = 0.25
            return ''
        return super().on_fault(kind)

    def consume(self, kg):
        need = kg / 6000 * 100                            # 砂斗 6 t
        if self.level < need:
            return False
        self.level -= need
        return True

    def step(self, dt):
        mold = self.plant.of_kind('molding')
        rate = mold[0].molds_per_h if mold else 90
        self.ret_T += ((32 + rate * 0.18) - self.ret_T) * dt / 1800 + self.rng.normal(0, 0.02)
        running = self.level < 95
        meas = self.moist + self.drift + self.rng.normal(0, 0.03)
        if self.get('Setpoint/AutoControl'):
            err = self.get('Setpoint/Moisture') - meas
            self.integ = max(-200, min(200, self.integ + err * dt))
            water = max(0.0, min(80.0, 22 + 35 * err + 0.04 * self.integ + (self.ret_T - 40) * 0.6))
        else:
            water = self.get('Setpoint/WaterManual')
        if self.valve_stuck is not None:
            water = self.valve_stuck
        sand_tph = 60.0 if running else 0.0
        # 水分平衡：加水使水分上升，回砂热量导致蒸发；砂流量越大单位水的影响越小
        if running:
            target = 2.0 + 0.065 * water - 0.02 * (self.ret_T - 40)   # 稳态水分：加水越多越湿，回砂越热蒸发越多
            self.moist += (target - self.moist) * dt / 240 + self.rng.normal(0, 0.004)
            self.level = min(100.0, self.level + sand_tph * 1000 / 3600 * dt / 6000 * 100)
        comp = 40 + 25 * (self.moist - 3.4) + self.rng.normal(0, 0.6)
        gs = 155 - 90 * (self.moist - 3.25) ** 2 + self.rng.normal(0, 2)
        self.set('Sand/Moisture', round(meas, 2))
        self.set('Sand/Compactability', round(comp, 1))
        self.set('Sand/GreenStrength', round(gs, 1))
        self.set('Sand/ReturnTemp', round(self.ret_T, 1))
        self.set('Mixer/WaterFlow', round(water, 1))
        self.set('Mixer/Current', round((180 if running else 40) + self.rng.normal(0, 3), 1))
        self.set('Hopper/Level', round(self.level, 1))
        self.set('Mixer/Running', running)
        self.truth = {'moisture': round(self.moist, 3), 'sensor_drift': self.drift}
        self.state = 'Executing' if running else 'Idle'
        self.power_kw = 132 if running else 25
        self.alarm = _tr('型砂水分超限') if abs(self.moist - 3.4) > 0.45 else ''

    def view(self):
        return {'level': self.get('Hopper/Level'), 'moist': self.get('Sand/Moisture')}


class MoldingLine(Station):
    """水平分型造型线 + 自动浇注机。每型 N 件铸件。"""
    kind = 'molding'
    area = '造型区'
    fault_kinds = {'failure': '设备故障停机', 'pour_low': '浇注机测温偏差 −40 °C'}
    action_profile = 'press'        # 5.0 动作级信号：射砂 / 压实气缸 / 推型气缸（vfactory/actions.py）

    def build_tags(self):
        c = self.cfg
        self.per_mold = c.get('castings_per_mold', 2)
        self.pour_kg = c.get('pour_kg', 45.0)
        self.cast_kg = c.get('casting_kg', 18.5)
        self.cycle_left = 0.0
        self.pour_left = 0.0
        self.pour_queue = []                               # 已造型、等待浇注的砂型
        self.mold_seq = 0
        self.pour_bias = 0.0
        A = self.add_tag
        A('Setpoint/CycleSec', float(c.get('cycle_s', 40)), 's', _tr('造型节拍'), writable=True, lo=25, hi=120)
        A('Production/MoldCount', 0, '', _tr('累计造型数'))
        A('Production/PouredCount', 0, '', _tr('累计浇注型数'))
        A('Production/WaitingMolds', 0, '', _tr('等待浇注的砂型'))
        A('Pouring/LastTemp', 0.0, '°C', _tr('最近一型浇注温度'))
        A('Pouring/LastWeight', 0.0, 'kg', _tr('最近一型浇注重量'))
        A('Pouring/LastMg', 0.0, '%', _tr('最近一型对应残镁'))
        A('Pouring/Ladle', '', '', _tr('浇注中的浇包'), dtype='str')
        A('Mold/Hardness', 85.0, '', _tr('砂型硬度（B 型硬度计）'))
        A('Mold/SqueezePressure', 0.0, 'MPa', _tr('压实压力'))

    @property
    def molds_per_h(self):
        return 3600 / self.get('Setpoint/CycleSec')

    def history_tags(self):
        return ['Pouring/LastTemp', 'Production/WaitingMolds', 'Mold/Hardness']

    def on_fault(self, kind):
        if kind == 'pour_low':
            self.pour_bias = -40
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        sand = self.plant.of_kind('sand')[0]
        trt = self.plant.of_kind('treatment')[0]
        cool = self.plant.of_kind('cooling')[0]
        executing = False
        # 造型
        if len(self.pour_queue) < self.cfg.get('pour_buffer', 8):
            if self.cycle_left <= 0:
                if sand.consume(self.cfg.get('sand_per_mold_kg', 160)):
                    self.cycle_left = self.get('Setpoint/CycleSec')
                    if self.acts is not None:
                        self.cycle_left += self.acts.cycle(self.plant.t, self.cycle_left + dt)   # 开始这一步也算在节拍里
                    self.mold_seq += 1
                    comp = sand.get('Sand/Compactability')
                    hard = 88 - abs(comp - 40) * 0.8 + self.rng.normal(0, 1.2)
                    self.pour_queue.append({'mold': f'M{self.mold_seq:06d}', 'moist': sand.truth['moisture'], 'comp': comp, 'hard': hard})
                    self.set('Production/MoldCount', self.get('Production/MoldCount') + 1)
                    self.set('Mold/Hardness', round(hard, 1))
                    self.set('Mold/SqueezePressure', round(1.1 + self.rng.normal(0, 0.03), 2))
            else:
                self.cycle_left -= dt
                executing = True
        # 浇注
        ladle = trt.pour_ladle()
        if self.pour_left > 0:
            self.pour_left -= dt
            executing = True
        elif self.pour_queue and ladle and not cool.full():
            mold = self.pour_queue.pop(0)
            T = ladle['T'] + self.pour_bias
            ladle['kg'] -= self.pour_kg
            self.pour_left = 14
            parts = []
            for k in range(self.per_mold):
                parts.append(self._cast(mold, ladle, T, k))
            cool.load(mold['mold'], parts)
            self.set('Production/PouredCount', self.get('Production/PouredCount') + 1)
            self.set('Pouring/LastTemp', round(T + self.rng.normal(0, 3), 1))
            self.set('Pouring/LastWeight', round(self.pour_kg + self.rng.normal(0, 0.4), 2))
            self.set('Pouring/LastMg', round(ladle['mg'], 4))
            self.set('Pouring/Ladle', ladle['id'])
            executing = True
        self.set('Production/WaitingMolds', len(self.pour_queue))
        self.state = 'Executing' if executing else 'Idle'
        self.alarm = _tr('等待铁水') if len(self.pour_queue) >= self.cfg.get('pour_buffer', 8) else ''
        self.power_kw = 95 if executing else 30

    def _cast(self, mold, ladle, T, k):
        r = self.rng
        moist_hi = max(0.0, mold['moist'] - 3.55) / 0.15
        cold = max(0.0, 1385 - T) / 20
        hot = max(0.0, T - 1460) / 20
        comp_off = abs(mold['comp'] - 40) / 5
        p_gas = sigmoid(-4.4 + 1.4 * moist_hi + 0.7 * cold + 0.5 * hot + 0.4 * comp_off)
        ce = ladle['chem'].get('C', 3.7) + (ladle['chem'].get('Si', 1.6) + 1.0 + ladle['chem'].get('P', 0.03)) / 3   # 孕育后 Si 约 +1.0
        mg_low = max(0.0, 0.034 - ladle['mg']) / 0.004
        p_shr = sigmoid(-4.6 + 1.1 * mg_low + 1.2 * abs(ce - 4.45) / 0.1)
        p_cold = sigmoid(-6 + 0.35 * max(0.0, 1350 - T))
        d = {}
        if r.random() < p_gas:
            d['porosity_mm'] = round(float(r.lognormal(math.log(0.6), 0.6)), 3)
        if r.random() < p_shr:
            d['shrinkage_mm'] = round(float(r.lognormal(math.log(1.0), 0.5)), 3)
        if r.random() < p_cold:
            d['cold_shut'] = True
        if ladle['mg'] < 0.030:
            d['poor_nodularity'] = True
        p = self.plant.new_part(heat=ladle['heat'], ladle=f"{ladle['id']}#{ladle['no']}", mold=mold['mold'], cavity=k + 1,
                                pour_temp=round(T, 1), mg=round(ladle['mg'], 4), sand_moisture=round(mold['moist'], 3),
                                compactability=round(mold['comp'], 1), ce=round(ce, 3), defects=d,
                                probs={'gas': round(p_gas, 4), 'shrink': round(p_shr, 4)}, rework=0)
        p.event(self.plant, self.id, 'poured', mold=mold['mold'], temp=round(T, 1))
        self.plant.kpi['castings'] += 1
        return p

    def view(self):
        return {'waiting': len(self.pour_queue), 'molds': self.get('Production/MoldCount')}


class CoolingLine(Station):
    kind = 'cooling'
    area = '造型区'

    def build_tags(self):
        self.molds = []                                    # [mold_id, parts, elapsed]
        self.cap = self.cfg.get('capacity_molds', 80)
        A = self.add_tag
        A('Setpoint/CoolMin', float(self.cfg.get('cool_min', 45)), 'min', _tr('冷却时间'), writable=True, lo=20, hi=120)
        A('Line/Molds', 0, '', _tr('冷却线上的砂型数'))
        A('Line/ShakeoutCount', 0, '', _tr('累计落砂型数'))
        A('Line/ShakeoutTemp', 0.0, '°C', _tr('落砂时铸件温度'))

    def full(self):
        return len(self.molds) >= self.cap

    def load(self, mold_id, parts):
        self.molds.append([mold_id, parts, 0.0])

    def step(self, dt):
        cool_s = self.get('Setpoint/CoolMin') * 60
        shot = self.buf('out', 'shot_in')
        for m in self.molds:
            m[2] += dt
        while self.molds and self.molds[0][2] >= cool_s and len(shot) + len(self.molds[0][1]) <= shot.capacity:
            mid, parts, el = self.molds.pop(0)
            Tc = AMBIENT + 1150 * math.exp(-el / 1500)
            for p in parts:
                p['shakeout_temp'] = round(Tc, 0)
                if Tc > 650:
                    p['defects']['hot_shakeout'] = True
                p.event(self.plant, self.id, 'shakeout', temp=round(Tc))
                shot.put(p)
            self.set('Line/ShakeoutCount', self.get('Line/ShakeoutCount') + 1)
            self.set('Line/ShakeoutTemp', round(Tc + self.rng.normal(0, 8), 0))
        self.set('Line/Molds', len(self.molds))
        self.state = 'Executing' if self.molds else 'Idle'
        self.power_kw = 22 if self.molds else 5

    def view(self):
        cool_s = self.get('Setpoint/CoolMin') * 60
        return {'molds': [round(min(1.0, m[2] / cool_s), 3) for m in self.molds]}


class ShotBlast(Station):
    """吊钩式抛丸清理 + 目视检查（冷隔、明显缺陷在这里挑出）。"""
    kind = 'shotblast'
    area = '清理区'
    fault_kinds = {'failure': '设备故障停机', 'shot_low': '钢丸不足'}

    def build_tags(self):
        u = self.cfg.get('modbus_unit', 2)
        self.batch = []
        self.left = 0.0
        self.shot_kg = 1800.0
        A = self.add_tag
        A('Setpoint/BlastMin', 8.0, 'min', _tr('抛丸时间'), writable=True, lo=3, hi=20, modbus={'kind': 'hr', 'addr': 100, 'scale': 10, 'unit': u})
        A('Turbine/Current', 0.0, 'A', _tr('抛头电流'), modbus={'kind': 'hr', 'addr': 0, 'scale': 10, 'unit': u})
        A('Shot/Amount', self.shot_kg, 'kg', _tr('钢丸量'), modbus={'kind': 'hr', 'addr': 1, 'scale': 1, 'unit': u})
        A('Batch/Count', 0, '', _tr('累计抛丸批数'), modbus={'kind': 'hr', 'addr': 2, 'scale': 1, 'unit': u})
        A('Dust/Pressure', 0.0, 'Pa', _tr('除尘器压差'), modbus={'kind': 'hr', 'addr': 3, 'scale': 1, 'unit': u})

    def on_fault(self, kind):
        if kind == 'shot_low':
            self.shot_kg = 700
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        src = self.buf('in', 'shot_in')
        out = self.buf('out', 'raw')
        if self.left > 0:
            self.left -= dt
            self.shot_kg -= 0.0025 * dt
            if self.left <= 0:
                for p in self.batch:
                    d = p['defects']
                    if d.get('cold_shut') or d.get('hot_shakeout') and self.rng.random() < 0.3:
                        self.plant.scrap(p, self.id, _tr('冷隔/开裂（目视）'))
                    elif d.get('poor_nodularity'):
                        self.plant.scrap(p, self.id, _tr('球化不良（试块）'))
                    else:
                        p.event(self.plant, self.id, 'cleaned')
                        out.put(p)
                self.batch = []
                self.set('Batch/Count', self.get('Batch/Count') + 1)
        elif len(src) >= self.cfg.get('batch', 24) or (len(src) > 0 and self.plant.stations.get(self.cfg.get('feed_from', 'COOL1')) and
                                not self.plant.stations[self.cfg.get('feed_from', 'COOL1')].molds):
            n = self.cfg.get('batch', 24)
            if len(out) + n <= out.capacity:
                self.batch = [src.get() for _ in range(min(n, len(src)))]
                self.left = self.get('Setpoint/BlastMin') * 60 * (1.4 if self.shot_kg < 1000 else 1)
        if self.shot_kg < 900 and self.rng.random() < dt / 3600:
            self.shot_kg = 1800
            self.plant.log(self.id, 'maint', _tr('补加钢丸'))
        running = self.left > 0
        self.set('Turbine/Current', round((62 * min(1, self.shot_kg / 1500) if running else 0) + self.rng.normal(0, 0.8), 1))
        self.set('Shot/Amount', round(self.shot_kg))
        self.set('Dust/Pressure', round((1250 if running else 300) + self.rng.normal(0, 20)))
        self.state = 'Executing' if running else 'Idle'
        self.alarm = _tr('钢丸不足') if self.shot_kg < 1000 else ''
        self.power_kw = 75 if running else 6

    def view(self):
        return {'busy': self.left > 0, 'in': len(self.buf('in', 'shot_in'))}
