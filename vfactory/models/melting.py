"""熔炼区：中频感应电炉、球化孕育处理（含浇包）。

电炉能量平衡（每步积分比焓 h，kJ/kg）：
    m·dh/dt = η·P − Q_rad − Q_wall
    固态 cp=0.75，液态 cp=0.85 kJ/(kg·K)，熔化区间 1150–1200 °C 吸收潜热 230 kJ/kg
    Q_rad = ε·σ·A·(T⁴−T∞⁴)，Q_wall = U·A_wall·(T−T∞)
按 3 t 炉、2000 kW、η=0.72 算，一炉从冷料到 1500 °C 约 45–55 分钟、吨耗约 540–600 kWh，和真实中频炉一致。
浇包：牛顿冷却 dT/dt = −k(T−T∞)；球化后残余镁按 Mg(t)=Mg₀·e^(−k_Mg·t) 衰退。
"""
from ..i18n import _tr
import math

from ..core import AMBIENT, Station

CP_S, CP_L, LATENT, T_SOL, T_LIQ = 0.75, 0.85, 230.0, 1150.0, 1200.0
H_SOL = CP_S * (T_SOL - AMBIENT)
H_LIQ = H_SOL + LATENT
SIGMA = 5.67e-11  # kW/(m²K⁴)


def temp_from_h(h):
    if h <= H_SOL:
        return AMBIENT + h / CP_S
    if h <= H_LIQ:
        return T_SOL + (T_LIQ - T_SOL) * (h - H_SOL) / LATENT
    return T_LIQ + (h - H_LIQ) / CP_L


def h_from_temp(t):
    if t <= T_SOL:
        return CP_S * (t - AMBIENT)
    if t <= T_LIQ:
        return H_SOL + LATENT * (t - T_SOL) / (T_LIQ - T_SOL)
    return H_LIQ + CP_L * (t - T_LIQ)


class InductionFurnace(Station):
    kind = 'furnace'
    area = '熔炼区'
    fault_kinds = {'failure': '设备故障停机', 'lining_wear': '炉衬加速侵蚀（漏炉预警）', 'cooling_low': '冷却水流量偏低'}

    def build_tags(self):
        c = self.cfg
        self.cap = c.get('capacity_kg', 3000)
        self.m = c.get('heel_kg', 300)                  # 炉内铁水/炉料质量
        self.h = h_from_temp(1350)                       # 留铁水"起熔"
        self.heat_no = 0
        self.charge_left = 0.0
        self.phase_t = 0.0
        self.heat_energy = 0.0
        self.lining = c.get('lining_mm', 110.0)
        self.cool_flow_nom = 36.0                        # 2 MW 中频炉冷却水约 36 m³/h，满功率温升 ~12 °C
        self.cool_fault = False
        self.lining_fault = False
        self.chem = {'C': 3.70, 'Si': 1.60, 'Mn': 0.25, 'S': 0.012, 'P': 0.030}
        self.phase = 'Charging'
        A = self.add_tag
        A('Setpoint/PowerKW', float(c.get('power_kw', 2000)), 'kW', _tr('功率设定'), writable=True, lo=0, hi=c.get('power_kw', 2000) * 1.1)
        A('Setpoint/TapTemp', 1500.0, '°C', _tr('出铁温度设定'), writable=True, lo=1420, hi=1560)
        A('Setpoint/CarbonRaiserKg', 0.0, 'kg', _tr('每炉增碳剂加入量'), writable=True, lo=0, hi=60)
        A('Bath/Temperature', 25.0, '°C', _tr('铁水温度（测温枪/热电偶）'))
        A('Bath/Weight', self.m, 'kg', _tr('炉内重量'))
        A('Electrical/Power', 0.0, 'kW', _tr('有功功率'))
        A('Electrical/Frequency', 0.0, 'Hz', _tr('中频频率'))
        A('Electrical/Voltage', 0.0, 'V', _tr('中频电压'))
        A('Electrical/PowerFactor', 0.0, '', _tr('功率因数'))
        A('Cooling/FlowRate', self.cool_flow_nom, 'm³/h', _tr('冷却水流量'), modbus={'kind': 'hr', 'addr': 0, 'scale': 10})
        A('Cooling/InletTemp', 30.0, '°C', _tr('进水温度'), modbus={'kind': 'hr', 'addr': 1, 'scale': 10})
        A('Cooling/OutletTemp', 30.0, '°C', _tr('出水温度'), modbus={'kind': 'hr', 'addr': 2, 'scale': 10})
        A('Lining/Thickness', self.lining, 'mm', _tr('炉衬剩余厚度（估算）'), modbus={'kind': 'hr', 'addr': 3, 'scale': 10})
        A('Lining/EarthLeakage', 0.5, 'mA', _tr('漏炉报警仪电流'), modbus={'kind': 'hr', 'addr': 4, 'scale': 10})
        A('Heat/Number', '', '', _tr('炉次号'), dtype='str')
        A('Heat/Phase', _tr('加料'), '', _tr('工艺阶段'), dtype='str')
        A('Heat/EnergyKWh', 0.0, 'kWh', _tr('本炉电耗'))
        A('Chemistry/C', self.chem['C'], '%', _tr('碳（光谱）'))
        A('Chemistry/Si', self.chem['Si'], '%', _tr('硅（光谱）'))
        A('Chemistry/Mn', self.chem['Mn'], '%', _tr('锰（光谱）'))
        A('Chemistry/S', self.chem['S'], '%', _tr('硫（光谱）'))
        A('Chemistry/CE', 0.0, '%', _tr('碳当量 C+(Si+P)/3'))
        self.truth = {'bath_temp': 25.0}
        self.unit = c.get('modbus_unit')
        for t in self.tags.values():
            if t.modbus:
                t.modbus['unit'] = self.unit

    def history_tags(self):
        return ['Bath/Temperature', 'Electrical/Power', 'Bath/Weight', 'Cooling/OutletTemp']

    @property
    def T(self):
        return temp_from_h(self.h)

    def ready(self):
        return self.phase == 'Holding' and self.m > 600 and self.T >= self.get('Setpoint/TapTemp') - 15

    def tap(self, kg):
        kg = min(kg, self.m - 250)
        self.m -= kg
        self.plant.kpi['melt_kg'] += kg
        return kg, self.T, dict(self.chem), self.get('Heat/Number')

    def on_fault(self, kind):
        if kind == 'lining_wear':
            self.lining_fault = True
            return ''
        if kind == 'cooling_low':
            self.cool_fault = True
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        T = self.T
        p_set = self.get('Setpoint/PowerKW')
        P = 0.0
        if self.phase == 'Charging':
            self.phase_t += dt
            rate = self.cap / 900                           # 15 分钟加满
            add = min(rate * dt, self.charge_left if self.charge_left > 0 else 0)
            if self.charge_left <= 0 and self.m < self.cap * 0.95:
                self.charge_left = self.cap - self.m
                self.heat_no += 1
                self.set('Heat/Number', f"L{self.plant.now():%y%m%d}-{self.id[-1]}{self.heat_no:02d}")
                self.heat_energy = 0.0
                self.plant.log(self.id, 'heat', _tr('开始新炉次 {get}', get=self.get('Heat/Number')), heat=self.get('Heat/Number'), phase='start')
                add = 0
            if add > 0:                                   # 冷料加入，混合比焓
                self.h = (self.h * self.m + h_from_temp(AMBIENT) * 0 + 0) / (self.m + add)
                self.m += add
                self.charge_left -= add
            P = p_set * 0.6                                # 边加料边送电
            if self.charge_left <= 0.5:
                self.phase, self.phase_t = 'Melting', 0
                base = self.rng.normal
                self.chem = {'C': base(3.55, 0.06) + 0.9 * self.get('Setpoint/CarbonRaiserKg') / self.cap * 100 * 0.9,
                             'Si': base(1.55, 0.05), 'Mn': base(0.28, 0.02), 'S': abs(base(0.013, 0.002)), 'P': abs(base(0.028, 0.003))}
        elif self.phase == 'Melting':
            P = p_set
            if T >= self.get('Setpoint/TapTemp') - 25:
                self.phase, self.phase_t = 'Sampling', 0
        elif self.phase == 'Sampling':                    # 取样、光谱分析、成分微调（自动补碳）
            self.phase_t += dt
            P = self._hold_power(T)
            if self.phase_t >= 180:
                if self.chem['C'] < 3.62:
                    self.chem['C'] += 3.70 - self.chem['C'] + self.rng.normal(0, 0.02)
                    self.plant.log(self.id, 'chem', _tr('光谱 C 偏低，自动补加增碳剂'))
                self.phase, self.phase_t = 'Holding', 0
                for k in ('C', 'Si', 'Mn', 'S'):
                    self.set(f'Chemistry/{k}', round(self.chem[k], 3))
                self.set('Chemistry/CE', round(self.chem['C'] + (self.chem['Si'] + self.chem['P']) / 3, 3))
                self.plant.log(self.id, 'chem', _tr('光谱 C {C:.2f} Si {Si:.2f}', C=self.chem['C'], Si=self.chem['Si']), heat=self.get('Heat/Number'),
                               **{k: round(self.chem[k], 3) for k in ('C', 'Si', 'Mn', 'S', 'P')}, CE=self.get('Chemistry/CE'), temp=round(T, 1))
        elif self.phase == 'Holding':
            P = self._hold_power(T)
            if self.m <= 600:                              # 铁水出完，留底再加料
                self.phase, self.phase_t = 'Charging', 0
                self.lining -= self.rng.uniform(0.25, 0.4) * (3 if self.lining_fault else 1) + max(0, T - 1520) * 0.01
                self.plant.log(self.id, 'heat', _tr('炉次 {get} 结束，电耗 {heat_energy:.0f} kWh', get=self.get('Heat/Number'), heat_energy=self.heat_energy), heat=self.get('Heat/Number'),
                               phase='end', kwh=round(self.heat_energy, 1), kg=round(self.cap - 600, 0), lining=round(self.lining, 2))
        P = min(P, p_set)
        # 能量平衡
        eta = 0.72
        A_rad = 1.2
        q_rad = 0.12 * SIGMA * A_rad * ((T + 273) ** 4 - (AMBIENT + 273) ** 4)
        q_wall = 0.06 * (T - AMBIENT)                     # 炉壁、炉盖导热损失约 90 kW @1500°C
        self.h += (eta * P - q_rad - q_wall) * dt / max(self.m, 1)
        self.power_kw = P + 15                             # 加上辅机
        self.heat_energy += P * dt / 3600
        T = self.T
        self.truth['bath_temp'] = round(T, 1)
        # 电气量：频率随炉料从固态到液态逐渐上升，功率因数靠电容补偿
        frac_liquid = min(1, max(0, (self.h - H_SOL) / LATENT))
        self.set('Electrical/Power', round(P + self.rng.normal(0, 3) if P > 0 else 0, 1))
        self.set('Electrical/Frequency', round((480 + 40 * frac_liquid + self.rng.normal(0, 0.5)) if P > 0 else 0, 1))
        self.set('Electrical/Voltage', round(750 * math.sqrt(P / max(p_set, 1)) if P > 0 else 0, 0))
        self.set('Electrical/PowerFactor', round(0.92 + 0.05 * frac_liquid if P > 0 else 0, 3))
        meas = T + self.rng.normal(0, 2.5)
        self.set('Bath/Temperature', round(meas, 1))
        self.set('Bath/Weight', round(self.m, 0))
        flow = self.cool_flow_nom * (0.55 if self.cool_fault else 1) + self.rng.normal(0, 0.15)
        q_coil = P * (1 - eta) * 0.9
        t_in = 30 + 2 * math.sin(self.plant.t / 7200)
        t_out = t_in + q_coil / (max(flow, 1) / 3.6 * 4.18)
        self.set('Cooling/FlowRate', round(flow, 2))
        self.set('Cooling/InletTemp', round(t_in, 1))
        self.set('Cooling/OutletTemp', round(t_out, 1))
        self.set('Lining/Thickness', round(self.lining, 1))
        leak = 0.4 + max(0, 80 - self.lining) * 0.6 + self.rng.normal(0, 0.05)
        self.set('Lining/EarthLeakage', round(max(0, leak), 2))
        self.set('Heat/EnergyKWh', round(self.heat_energy, 1))
        self.alarm = ''
        if t_out > 55:
            self.alarm = _tr('冷却水出水温度高')
        if leak > 10:
            self.alarm = _tr('漏炉报警：炉衬过薄')
        self.state = 'Executing' if P > 0 else 'Idle'
        self.set('Heat/Phase', {'Charging': _tr('加料'), 'Melting': _tr('熔化'), 'Sampling': _tr('取样分析'), 'Holding': _tr('保温待出铁')}[self.phase])

    def _hold_power(self, T):
        err = self.get('Setpoint/TapTemp') - T
        return max(0.0, min(self.get('Setpoint/PowerKW'), 250 + 40 * err))

    def idle_power(self):
        return 10

    def view(self):
        return {'temp': self.get('Bath/Temperature'), 'fill': round(self.m / self.cap, 3), 'heat': self.get('Heat/Number'), 'phase': self.get('Heat/Phase')}


class TreatmentStation(Station):
    """球化孕育站，管理浇包：接铁水 → 喂丝/冲入法球化 → 运到浇注机 → 浇完回来。"""
    kind = 'treatment'
    area = '熔炼区'
    fault_kinds = {'failure': '设备故障停机', 'mg_low': '球化剂加入量偏少'}

    def build_tags(self):
        c = self.cfg
        self.ladle_kg = c.get('ladle_kg', 520)
        n = c.get('ladles', 2)
        self.ladles = [dict(id=f'LD{i + 1}', state='Empty', kg=0.0, T=AMBIENT, mg=0.0, age=0.0, heat='', chem={}, phase=0.0, pos=0.0,
                            no=0) for i in range(n)]
        self.mg_fault = False
        A = self.add_tag
        A('Setpoint/MgAlloyPct', 1.50, '%', _tr('球化剂加入比例'), writable=True, lo=0.6, hi=2.0)
        A('Setpoint/InoculantPct', 0.40, '%', _tr('孕育剂加入比例'), writable=True, lo=0.1, hi=1.0)
        A('Setpoint/MaxPourMinutes', 12.0, 'min', _tr('球化后最长浇注时间（超时报废）'), writable=True, lo=5, hi=25)
        A('Ladle/Active', '', '', _tr('当前浇包'), dtype='str')
        A('Ladle/Temperature', 0.0, '°C', _tr('浇包铁水温度'))
        A('Ladle/Weight', 0.0, 'kg', _tr('浇包剩余铁水'))
        A('Ladle/ResidualMg', 0.0, '%', _tr('残余镁（估算）'))
        A('Ladle/AgeMin', 0.0, 'min', _tr('球化后已过时间'))
        A('Treatment/Count', 0, '', _tr('累计球化处理包数'))
        self.truth = {}

    def history_tags(self):
        return ['Ladle/Temperature', 'Ladle/ResidualMg']

    def on_fault(self, kind):
        if kind == 'mg_low':
            self.mg_fault = True
            return ''
        return super().on_fault(kind)

    def pour_ladle(self):
        for l in self.ladles:
            if l['state'] == 'AtPour' and l['kg'] >= 40:
                return l
        return None

    def step(self, dt):
        k_T = 1.15e-4 * (520 / max(self.ladle_kg, 1)) ** 0.33
        k_mg = 1.5e-4
        busy = False
        for l in self.ladles:
            if l['state'] in ('Treating', 'ToPour', 'AtPour', 'Return', 'Tapping'):
                l['T'] -= k_T * (l['T'] - AMBIENT) * dt
            if l['state'] in ('ToPour', 'AtPour'):
                l['age'] += dt
                l['mg'] *= math.exp(-k_mg * dt)
            if l['state'] == 'Empty':
                mold = self.plant.of_kind('molding')
                cyc = mold[0].get('Setpoint/CycleSec') if mold else 40
                pouring = next((x for x in self.ladles if x['state'] == 'AtPour'), None)
                lead_kg = (60 + 90 + 75) / cyc * 45 * 1.1      # 出铁+球化+运输期间会浇掉的铁水
                need = not any(x['state'] in ('ToPour', 'Tapping', 'Treating') for x in self.ladles) and (pouring is None or pouring['kg'] < lead_kg)
                fur = None if not need else next((f for f in sorted(self.plant.of_kind('furnace'), key=lambda f: -f.m) if f.ready()), None)
                if fur and not busy and not any(x['state'] in ('Tapping', 'Treating') for x in self.ladles):
                    kg, T, chem, heat = fur.tap(self.ladle_kg)
                    l.update(state='Tapping', kg=kg, T=T - 15, chem=chem, heat=heat, phase=0.0, src=fur.id, age=0.0)
                    l['no'] += 1
                    busy = True
            elif l['state'] == 'Tapping':
                l['phase'] += dt
                if l['phase'] >= 60:
                    l['state'], l['phase'] = 'Treating', 0.0
            elif l['state'] == 'Treating':
                busy = True
                l['phase'] += dt
                if l['phase'] >= 90:
                    pct = self.get('Setpoint/MgAlloyPct') * (0.6 if self.mg_fault else 1)
                    rec = self.rng.normal(0.45, 0.04)       # 镁回收率
                    l['mg'] = max(0.0, pct / 100 * 0.06 * rec * 100 + self.rng.normal(0, 0.002))   # 球化剂含 Mg 6%
                    l['T'] -= self.rng.normal(38, 4)          # 球化、孕育温降
                    l['state'], l['phase'], l['age'] = 'ToPour', 0.0, 0.0
                    self.set('Treatment/Count', self.get('Treatment/Count') + 1)
                    self.plant.log(self.id, 'treat', _tr('{id} 球化完成 T={T:.0f}°C Mg={mg:.3f}%', id=l['id'], T=l['T'], mg=l['mg']), ladle=f"{l['id']}#{l['no']}",
                                   heat=l.get('heat'), temp=round(l['T'], 1), mg=round(l['mg'], 4), kg=round(l['kg'], 1))
            elif l['state'] == 'ToPour':
                l['phase'] += dt
                l['pos'] = min(1.0, l['phase'] / 75)
                if l['phase'] >= 75 and not any(x['state'] == 'AtPour' for x in self.ladles):
                    l['state'], l['phase'] = 'AtPour', 0.0
            elif l['state'] == 'AtPour':
                if l['kg'] < 40 or l['age'] > self.get('Setpoint/MaxPourMinutes') * 60:
                    if l['kg'] >= 40:
                        self.plant.log(self.id, 'treat', _tr('{id} 超过最长浇注时间，剩余 {kg:.0f} kg 回炉', id=l['id'], kg=l['kg']))
                    l['state'], l['phase'] = 'Return', 0.0
            elif l['state'] == 'Return':
                l['phase'] += dt
                l['pos'] = max(0.0, 1 - l['phase'] / 60)
                if l['phase'] >= 60:
                    l.update(state='Empty', kg=0.0, mg=0.0, pos=0.0)
        self.state = 'Executing' if any(l['state'] != 'Empty' for l in self.ladles) else 'Idle'
        self.power_kw = 8 if self.state == 'Executing' else 2
        act = next((l for l in self.ladles if l['state'] in ('AtPour', 'ToPour', 'Treating', 'Tapping')), None)
        if act:
            self.set('Ladle/Active', act['id'])
            self.set('Ladle/Temperature', round(act['T'] + self.rng.normal(0, 2), 1))
            self.set('Ladle/Weight', round(act['kg'], 0))
            self.set('Ladle/ResidualMg', round(act['mg'], 4))
            self.set('Ladle/AgeMin', round(act['age'] / 60, 1))
        self.truth = {l['id']: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in l.items() if k != 'chem'} for l in self.ladles}

    def view(self):
        return {'ladles': [{'id': l['id'], 'state': l['state'], 'pos': round(l['pos'], 3), 'kg': round(l['kg'])} for l in self.ladles]}
