"""机加区：CNC 加工中心、机器人去毛刺单元、自动内窥检测。

CNC 切削模型
- 切削力（Kienzle）：Fc = kc1.1·b·h^(1−mc)·(1 + 1.6·VB)，球铁 kc1.1≈1200 N/mm²，mc≈0.25
- 切削功率 Pc = z·Fc·vc/60000 (kW)，主轴负载 % = Pc / (η·P额定)
- 刀具寿命（Taylor 扩展）：T = T_ref·(vc_ref/vc)^(1/n)·(f_ref/f)^(a/n)，n=0.25，a=0.5
- 后刀面磨损三段曲线：VB = 0.06(1−e^(−t/2)) + 0.18·t/T + 0.9·max(0, t/T−0.85)²（t：累计切削分钟）
  VB > 0.42 mm 后每次切削有断刀风险
- 缸孔直径 = 程序值 + 主轴热伸长 δ(1−e^(−t/τ)) − 精镗刀磨损·0.03 + 噪声；开启自动补偿时每 10 件按测头结果修正
- 交叉孔毛刺高度 ~ LogNormal(ln(0.10·(1+5·VB_钻头)), 0.35)
"""
from ..i18n import _tr
import math

from ..core import Station

KC11, MC = 1200.0, 0.25
TOOLS = {  # 刀号: 名称, 直径, vc_ref, f_ref, T_ref(min), 默认寿命件数
    'T01': ('Φ80 面铣刀', 80, 160, 0.20, 240, 400),
    'T02': ('Φ38 粗镗刀', 38, 150, 0.25, 200, 300),
    'T03': ('Φ8 钻头', 8, 90, 0.15, 150, 100),
    'T04': ('Φ40 精镗刀', 40, 200, 0.10, 180, 250),
    'T05': ('M10 丝锥', 10, 15, 1.50, 300, 600),
}
OPS = [  # 工步: 刀号, 时长(s), ap/b(mm), 参与刃数, 切削占比
    ('OP10 粗铣端面', 'T01', 70, 2.0, 3, 0.85),
    ('OP20 粗镗缸孔', 'T02', 85, 2.0, 1, 0.9),
    ('OP30 钻油道孔×8', 'T03', 110, 4.0, 2, 0.7),
    ('OP40 精镗缸孔', 'T04', 60, 0.25, 1, 0.9),
    ('OP50 攻丝×6', 'T05', 55, 0.75, 1, 0.6),
    ('OP60 测头测量', None, 25, 0, 0, 0),
]
HANDLING_S = 40


class CNC(Station):
    kind = 'cnc'
    area = '机加区'
    fault_kinds = {'failure': '设备故障停机', 'tool_break': '钻头断刀', 'chatter': '主轴轴承磨损（振动增大）'}
    action_profile = 'cnc'          # 5.0 动作级信号：门 / 夹具 / 主轴 / 程序段（vfactory/actions.py）

    def build_tags(self):
        self.part = None
        self.op_i = -1
        self.op_left = 0.0
        self.handling = 0.0
        self.setup_left = 0.0
        self.cut_min = {t: 0.0 for t in TOOLS}
        self.vb = {t: 0.0 for t in TOOLS}
        self.count = {t: 0 for t in TOOLS}
        self.thermal = 0.0
        self.comp = 0.0
        self.since_comp = 0
        self.good = self.bad = 0
        self.cycle_t = 0.0
        self.bearing = 0.0
        self.x = self.y = self.z = 0.0
        A = self.add_tag
        A('Identification/Manufacturer', 'VirtualFactory', '', _tr('制造商'), dtype='str')
        A('Identification/Model', self.cfg.get('model', 'VMC-850'), '', _tr('型号'), dtype='str')
        A('Identification/SerialNumber', f"VF-{self.id}", '', _tr('序列号'), dtype='str')
        A('Monitoring/MachineTool/OperationMode', 'AUTOMATIC', '', _tr('运行模式'), dtype='str')
        A('Monitoring/MachineTool/PowerOnDuration', 0.0, 'h', _tr('开机时长'))
        A('Monitoring/Stacklight', 'YELLOW', '', _tr('三色灯'), dtype='str')
        A('Monitoring/Spindle/ActualSpeed', 0.0, 'rpm', _tr('主轴转速'))
        A('Monitoring/Spindle/Load', 0.0, '%', _tr('主轴负载'))
        A('Monitoring/Spindle/Override', 100.0, '%', _tr('主轴倍率'), writable=True, lo=50, hi=120)
        A('Monitoring/Feed/Override', 100.0, '%', _tr('进给倍率'), writable=True, lo=50, hi=120)
        A('Monitoring/Vibration/RMS', 0.0, 'mm/s', _tr('主轴振动有效值'))
        A('Monitoring/Axes/X', 0.0, 'mm', _tr('X 轴位置'))
        A('Monitoring/Axes/Y', 0.0, 'mm', _tr('Y 轴位置'))
        A('Monitoring/Axes/Z', 0.0, 'mm', _tr('Z 轴位置'))
        A('Production/ActiveProgram/Name', 'O1201', '', _tr('当前程序'), dtype='str')
        A('Production/ActiveProgram/Step', '', '', _tr('当前工步'), dtype='str')
        A('Production/CurrentPart', '', '', _tr('当前工件'), dtype='str')
        A('Production/PartsProduced', 0, '', _tr('累计加工件数'))
        A('Production/PartsGood', 0, '', _tr('合格件'))
        A('Production/PartsBad', 0, '', _tr('不合格件'))
        A('Production/LastCycleTime', 0.0, 's', _tr('上一件节拍'))
        A('Quality/BoreDiameter', 0.0, 'mm', _tr('缸孔直径（测头）'))
        A('Setpoint/AutoComp', True, '', _tr('尺寸自动补偿'), writable=True)
        A('Tools/ActiveTool', '', '', _tr('当前刀号'), dtype='str')
        for t, (nm, *_rest, life) in TOOLS.items():
            A(f'Tools/{t}/LifeCount', 0, _tr('件'), _tr('{nm} 已用件数', nm=nm))
            A(f'Tools/{t}/LifeLimit', life, _tr('件'), _tr('{nm} 寿命设定（到数换刀）', nm=nm), writable=True, lo=10, hi=3000)

    def history_tags(self):
        return ['Monitoring/Spindle/Load', 'Monitoring/Vibration/RMS', 'Quality/BoreDiameter', 'Tools/T03/LifeCount']

    def quality_rate(self):
        return self.good / max(1, self.good + self.bad)

    def on_fault(self, kind):
        if kind == 'tool_break':
            self._break('T03')
            return ''
        if kind == 'chatter':
            self.bearing = 0.6
            return ''
        return super().on_fault(kind)

    def _break(self, tool):
        self.alarm = _tr('{tool} {v} 断刀', tool=tool, v=TOOLS[tool][0])
        self.plant.log(self.id, 'alarm', self.alarm, tool=tool, broken=True, used=self.count.get(tool, 0))
        if self.part:
            self.plant.scrap(self.part, self.id, _tr('断刀报废'))
            self.bad += 1
            self.part = None
            if self.acts is not None and (self.op_i >= 0 or getattr(self, '_pre', False)):
                self.acts.cnc_end(self.plant.t)          # 中止：主轴停、松开、开门、循环结束
        self.failure.repair_left = float(self.rng.lognormal(math.log(20 * 60), 0.3))
        self._change(tool, log=False)

    def _change(self, tool, log=True):
        used = self.count.get(tool, 0) if hasattr(self, 'count') else 0
        self.cut_min[tool] = 0.0
        self.vb[tool] = 0.0
        self.count[tool] = 0
        self.set(f'Tools/{tool}/LifeCount', 0)
        if log:
            self.setup_left = max(self.setup_left, 180)
            self.plant.log(self.id, 'tool', _tr('{tool} {v} 到寿命换刀', tool=tool, v=TOOLS[tool][0]), tool=tool, tool_name=TOOLS[tool][0], used=used)

    def on_remove(self):
        if self.part:
            self.buf('in', 'cnc_in').put(self.part)

    def tool_life_min(self, tool, vc, f):
        nm, D, vc_ref, f_ref, T_ref, _ = TOOLS[tool]
        return T_ref * (vc_ref / vc) ** 4 * (f_ref / f) ** 2

    def step(self, dt):
        so = self.get('Monitoring/Spindle/Override') / 100
        fo = self.get('Monitoring/Feed/Override') / 100
        load = 0.0
        rpm = 0.0
        self.alarm = '' if not self.failure.repair_left else self.alarm
        if self.setup_left > 0:
            self.setup_left -= dt
            self.state = 'Setup'
        elif self.part is None:
            src = self.buf('in', 'cnc_in')
            if self.buf('out', 'deb_in').full():
                self.state, self.alarm = 'Idle', _tr('下游缓存满（堵料）')
                self.power_kw = 4.5
                return
            p = src.get()
            if p:
                self.part, self.op_i, self.handling, self.cycle_t = p, -1, HANDLING_S, 0.0
                self._pre = False
                if self.acts is not None:
                    self.handling += self.acts.take_pending()     # 上一件松开 / 开门因故障慢了：这件上料跟着晚
                p.event(self.plant, self.id, 'machining_start')
                self.set('Production/CurrentPart', p['id'])
            self.state = 'Idle' if self.part is None else 'Executing'
        else:
            self.state = 'Executing'
            self.cycle_t += dt
            if self.handling > 0:
                if not self.plant.crew_present(self.id):
                    self.alarm = _tr('等待上下料（操作工未到位）')
                    self.state = 'Idle'
                    self.power_kw = 4.5
                    return
                if self.acts is not None and not getattr(self, '_pre', True) and self.handling <= self.acts.PRE_WINDOW:
                    self._pre = True                          # 关门、夹紧占上下料的最后几秒；故障慢的部分加到上下料时间上
                    self.handling += self.acts.cnc_pre(self.plant.t + self.handling)
                self.handling -= dt
                if self.handling <= 0:
                    if self.acts is not None:
                        self.acts.cnc_start(self.plant.t + dt + self.handling)
                    self.op_i, self.op_left = 0, OPS[0][2] / fo * self.plant.cycle_factor()
            elif self.op_i < len(OPS):
                name, tool, dur, b, z, frac = OPS[self.op_i]
                self.set('Production/ActiveProgram/Step', _tr(name))
                self.set('Tools/ActiveTool', tool or '')
                if tool:
                    _nm, D, vc_ref, f_ref, *_ = TOOLS[tool]
                    vc, f = vc_ref * so, f_ref * fo
                    rpm = vc * 1000 / (math.pi * D)
                    h = f * (0.9 if z != 2 else 0.5)
                    Fc = KC11 * b * h ** (1 - MC) * (1 + 1.6 * self.vb[tool])
                    cutting = self.rng.random() < frac
                    Pc = z * Fc * vc / 60000 if cutting else 0.3
                    load = Pc / (0.85 * 15) * 100
                    TL = self.tool_life_min(tool, vc, f)
                    if cutting:
                        self.cut_min[tool] += dt / 60
                    r = self.cut_min[tool] / TL
                    self.vb[tool] = 0.06 * (1 - math.exp(-self.cut_min[tool] / 2)) + 0.18 * r + 0.9 * max(0, r - 0.85) ** 2
                    if self.vb[tool] > 0.42 and cutting and self.rng.random() < (self.vb[tool] - 0.42) * 0.02 * dt:
                        self._break(tool)
                        return
                    self.thermal += (1 - self.thermal) * dt / 2400
                self.op_left -= dt
                if self.op_left <= 0:
                    tx = self.plant.t + dt + self.op_left          # 这一段结束的精确时刻（动作信号用）
                    self.op_i += 1
                    if self.op_i < len(OPS):
                        self.op_left = OPS[self.op_i][2] / (fo if OPS[self.op_i][1] else 1) * self.plant.cycle_factor()
                        if self.acts is not None:
                            self.acts.cnc_op(tx, self.op_i)
                    else:
                        self._finish()
                        if self.acts is not None:
                            self.acts.cnc_end(tx)
        if self.state != 'Executing' or load == 0:
            self.thermal -= self.thermal * dt / 3600
        vib = 0.6 + 0.004 * load * 10 + 2.5 * self.bearing + 3.0 * self.vb['T03'] * (load > 5) + self.rng.normal(0, 0.05)
        t = self.plant.t
        if rpm > 0:
            self.x = 250 * math.sin(t / 7); self.y = 150 * math.cos(t / 11); self.z = -80 - 40 * math.sin(t / 3)
        self.set('Monitoring/Spindle/ActualSpeed', round(rpm + (self.rng.normal(0, 2) if rpm else 0), 0))
        self.set('Monitoring/Spindle/Load', round(max(0.0, load + (self.rng.normal(0, 1.2) if load else 0)), 1))
        self.set('Monitoring/Vibration/RMS', round(max(0.1, vib), 2))
        self.set('Monitoring/Axes/X', round(self.x, 1)); self.set('Monitoring/Axes/Y', round(self.y, 1)); self.set('Monitoring/Axes/Z', round(self.z, 1))
        self.set('Monitoring/MachineTool/PowerOnDuration', round(t / 3600, 2))
        self.set('Monitoring/Stacklight', {'Executing': 'GREEN', 'Idle': 'YELLOW', 'Setup': 'YELLOW'}.get(self.state, 'RED'))
        for tl in TOOLS:
            self.set(f'Tools/{tl}/LifeCount', self.count[tl])
        self.power_kw = 4.5 + (load / 100 * 15 * 1.15 if load else 0) + (1.2 if self.state == 'Executing' else 0)
        self.truth = {'VB_mm': {k: round(v, 4) for k, v in self.vb.items()}, 'thermal_um': round(self.thermal * 12, 2),
                      'bearing_wear': self.bearing, 'tool_life_min': {k: round(self.tool_life_min(k, TOOLS[k][2] * so, TOOLS[k][3] * fo), 1) for k in TOOLS}}

    def _finish(self):
        p = self.part
        r = self.rng
        vb_d, vb_b = self.vb['T03'], self.vb['T04']
        dia = 40.0125 + self.thermal * 0.0096 - vb_b * 0.03 - self.comp + r.normal(0, 0.0016)
        self.since_comp += 1
        if self.get('Setpoint/AutoComp') and self.since_comp >= 10:
            self.comp += (dia - 40.0125) * 0.8
            self.since_comp = 0
        burrs = [round(float(r.lognormal(math.log(0.10 * (1 + 5 * vb_d)), 0.35)), 3) for _ in range(4)]
        d = p['defects']
        if d.get('porosity_mm') and r.random() < 0.7:
            d['machined_porosity_mm'] = d['porosity_mm']
        if d.get('shrinkage_mm') and r.random() < 0.5:
            d['bore_shrinkage_mm'] = d['shrinkage_mm']
        p['machining'] = {'cnc': self.id, 'bore_dia': round(dia, 4), 'drill_vb': round(vb_d, 3), 'burrs_mm': burrs,
                          'cycle_s': round(self.cycle_t, 0), 'tool_counts': dict(self.count)}
        p['burrs_mm'] = burrs
        self.set('Quality/BoreDiameter', round(dia + r.normal(0, 0.0005), 4))
        self.set('Production/LastCycleTime', round(self.cycle_t, 0))
        self.set('Production/PartsProduced', self.get('Production/PartsProduced') + 1)
        self.plant.kpi['machined'] += 1
        for tl in TOOLS:
            self.count[tl] += 1
        if not (40.0 <= dia <= 40.025):
            self.bad += 1
            self.set('Production/PartsBad', self.bad)
            self.plant.scrap(p, self.id, _tr('缸孔尺寸超差'))
        else:
            self.good += 1
            self.set('Production/PartsGood', self.good)
            p.event(self.plant, self.id, 'machined', bore=round(dia, 4), cycle=round(self.cycle_t))
            self.buf('out', 'deb_in').put(p)
        self.part = None
        self.set('Production/CurrentPart', '')
        self.set('Production/ActiveProgram/Step', '')
        for tl in TOOLS:
            if self.count[tl] >= self.get(f'Tools/{tl}/LifeLimit'):
                self._change(tl)

    def view(self):
        return {'part': self.part['id'] if self.part else '', 'load': self.get('Monitoring/Spindle/Load'),
                'light': self.get('Monitoring/Stacklight'), 'step': self.get('Production/ActiveProgram/Step')}


class DeburrCell(Station):
    """机器人去毛刺：浮动主轴带刷/刀逐孔处理交叉孔口。"""
    kind = 'deburr'
    area = '机加区'
    fault_kinds = {'failure': '设备故障停机', 'brush_worn': '毛刷异常磨损'}
    action_profile = 'robot'        # 5.0 动作级信号：夹爪 / 工装夹紧 / 机器人程序步

    def build_tags(self):
        self.part = None
        self.left = 0.0
        self.wear = 0.0
        self.setup = 0.0
        self.done = 0
        A = self.add_tag
        A('Setpoint/SpindleRPM', 8000.0, 'rpm', _tr('去毛刺主轴转速'), writable=True, lo=3000, hi=15000)
        A('Setpoint/BrushLife', 1500, _tr('件'), _tr('毛刷寿命（到数更换）'), writable=True, lo=100, hi=10000)
        A('Setpoint/CycleSec', 65.0, 's', _tr('单件节拍'), writable=True, lo=30, hi=200)
        A('Brush/Wear', 0.0, '%', _tr('毛刷磨损'))
        A('Robot/Program', 'DEBURR_SGH450', '', _tr('机器人程序'), dtype='str')
        A('Robot/J1', 0.0, '°', _tr('关节1')); A('Robot/J2', 0.0, '°', _tr('关节2')); A('Robot/J3', 0.0, '°', _tr('关节3'))
        A('Production/PartsDone', 0, '', _tr('累计去毛刺件数'))
        A('Production/CurrentPart', '', '', _tr('当前工件'), dtype='str')

    def history_tags(self):
        return ['Brush/Wear']

    def on_fault(self, kind):
        if kind == 'brush_worn':
            self.wear = 0.85
            return ''
        return super().on_fault(kind)

    def step(self, dt):
        src = self.buf('in', 'deb_in')
        if self.setup > 0:
            self.setup -= dt
            self.state = 'Setup'
        elif self.part is None:
            self.part = None if self.buf('out', 'ins_in').full() else src.get()
            if self.part:
                self.left = self.get('Setpoint/CycleSec')
                if self.acts is not None:
                    self.left += self.acts.cycle(self.plant.t, self.left + dt)   # 取件这一步也算在节拍里
                self.set('Production/CurrentPart', self.part['id'])
            self.state = 'Executing' if self.part else 'Idle'
        else:
            self.state = 'Executing'
            self.left -= dt
            if self.left <= 0:
                cap = 0.30 * (1 - 0.6 * self.wear) * (self.get('Setpoint/SpindleRPM') / 8000) ** 0.3
                res = []
                for h in (self.part.get('residual_burrs_mm') if self.part.get('rework') else self.part.get('burrs_mm', [])) or []:
                    res.append(round(h * 0.05 if h <= cap else h - cap * 0.8 + float(self.rng.normal(0, 0.01)), 3))
                self.part['residual_burrs_mm'] = [max(0.0, x) for x in res]
                self.part.event(self.plant, self.id, 'deburred', residual_max=max(res) if res else 0)
                self.buf('out', 'ins_in').put(self.part)
                self.part = None
                self.done += 1
                self.wear = min(1.0, self.wear + 1 / self.get('Setpoint/BrushLife'))
                self.set('Production/PartsDone', self.done)
                self.set('Production/CurrentPart', '')
                if self.wear >= 1.0:
                    self.wear, self.setup = 0.0, 300
                    self.plant.log(self.id, 'tool', _tr('更换毛刷'))
        t = self.plant.t
        busy = self.state == 'Executing'
        self.set('Robot/J1', round(40 * math.sin(t / 4) if busy else 0, 1))
        self.set('Robot/J2', round(-30 + 25 * math.sin(t / 3) if busy else -30, 1))
        self.set('Robot/J3', round(60 + 20 * math.cos(t / 2.5) if busy else 60, 1))
        self.set('Brush/Wear', round(self.wear * 100, 1))
        self.truth = {'capability_mm': round(0.30 * (1 - 0.6 * self.wear) * (self.get('Setpoint/SpindleRPM') / 8000) ** 0.3, 3)}
        self.power_kw = 6.5 if busy else 1.2

    def view(self):
        return {'j': [self.get('Robot/J1'), self.get('Robot/J2'), self.get('Robot/J3')], 'busy': self.state == 'Executing'}


class Inspection(Station):
    """自动内窥检测：逐孔插入探头拍照，判定 OK/NG。检出概率 POD(a)=1/(1+exp(−(ln a − ln a50)/s))。"""
    kind = 'inspection'
    area = '检测区'
    fault_kinds = {'failure': '设备故障停机', 'led_degrade': 'LED 光源衰减'}
    BURR_LIMIT = 0.10       # 残余毛刺 > 0.10 mm 判不合格
    PORE_LIMIT = 0.30

    def build_tags(self):
        self.part = None
        self.left = 0.0
        self.ok = self.ng = 0
        self.led_factor = 1.0
        A = self.add_tag
        A('Setpoint/LedBrightness', 70.0, '%', _tr('光源亮度'), writable=True, lo=10, hi=100)
        A('Setpoint/Holes', 10, _tr('个'), _tr('每件检测孔数'), writable=True, lo=1, hi=30)
        A('Setpoint/SecPerHole', 5.0, 's', _tr('每孔检测时间'), writable=True, lo=2, hi=30)
        A('Setpoint/Sensitivity', 0.6, '', _tr('判定灵敏度（0 宽松–1 严格）'), writable=True, lo=0, hi=1)
        A('Result/Last', '', '', _tr('最近一件结果'), dtype='str')
        A('Result/LastPart', '', '', _tr('最近一件编号'), dtype='str')
        A('Result/LastDefect', '', '', _tr('最近一件缺陷'), dtype='str')
        A('Result/OK', 0, '', _tr('累计合格'))
        A('Result/NG', 0, '', _tr('累计不合格'))
        A('Probe/Depth', 0.0, 'mm', _tr('探头插入深度'))
        A('Probe/HoleIndex', 0, '', _tr('当前孔号'))

    def on_fault(self, kind):
        if kind == 'led_degrade':
            self.led_factor = 0.55
            return ''
        return super().on_fault(kind)

    def pod(self, a, a50, s=0.25):
        if a <= 0:
            return 0.0
        return 1 / (1 + math.exp(-(math.log(a) - math.log(a50)) / s))

    def step(self, dt):
        src = self.buf('in', 'ins_in')
        holes = self.get('Setpoint/Holes')
        per = self.get('Setpoint/SecPerHole')
        if self.part is None:
            self.part = None if self.buf('out', 'fg').full() else src.get()
            if self.part:
                self.left = 20 + holes * per
            self.state = 'Executing' if self.part else 'Idle'
        else:
            self.state = 'Executing'
            self.left -= dt
            done_frac = 1 - max(0, self.left - 10) / (holes * per)
            hi = min(holes, int(done_frac * holes) + 1)
            self.set('Probe/HoleIndex', hi)
            self.set('Probe/Depth', round(abs(math.sin(self.plant.t / per * math.pi)) * 95, 1))
            if self.left <= 0:
                self._judge()
        self.power_kw = 2.2 if self.state == 'Executing' else 0.6

    def _judge(self):
        p = self.part
        r = self.rng
        light = self.get('Setpoint/LedBrightness') * self.led_factor
        lf = 1 + ((light - 70) / 30) ** 2
        sens = self.get('Setpoint/Sensitivity')
        a50_b = 0.06 * lf * (1.3 - 0.6 * sens)
        a50_p = 0.25 * lf * (1.3 - 0.6 * sens)
        pfa = min(0.5, 0.006 * lf * (0.4 + 1.6 * sens))
        d = p['defects']
        lim = 1.2 - 0.4 * sens                          # 灵敏度越高，判定界限越低
        real, found = [], []
        for b in p.get('residual_burrs_mm', []):
            if b > self.BURR_LIMIT:
                real.append(_tr('毛刺{b:.2f}mm', b=b))
            if b > 0.02 and r.random() < self.pod(b, a50_b):
                est = b * math.exp(r.normal(0, 0.2))         # 图像估计尺寸，有误差
                if est > self.BURR_LIMIT * lim:
                    found.append(('burr', est))
        for key in ('machined_porosity_mm', 'bore_shrinkage_mm'):
            a = d.get(key)
            if a:
                if a > self.PORE_LIMIT:
                    real.append((_tr('气孔') if 'poro' in key else _tr('缩松')) + f'{a:.2f}mm')
                if r.random() < self.pod(a, a50_p):
                    est = a * math.exp(r.normal(0, 0.2))
                    if est > self.PORE_LIMIT * lim:
                        found.append(('pore', est))
        if not found and r.random() < pfa:
            found.append(('false', 0))
        ng = bool(found)
        if real and not ng:
            self.plant.kpi['escape'] += 1
        if ng and not real:
            self.plant.kpi['overkill'] += 1
        cause = _tr('、').join(sorted({ {'burr': _tr('残余毛刺'), 'pore': _tr('内腔气孔/缩松'), 'false': _tr('误报')}[k] for k, _ in found})) or ''
        p['inspection'] = {'result': 'NG' if ng else 'OK', 'found': [k for k, _ in found], 'truth': real,
                           'led': round(light, 1), 'sens': sens}
        p.event(self.plant, self.id, 'inspected', result='NG' if ng else 'OK', cause=cause)
        self.set('Result/Last', 'NG' if ng else 'OK')
        self.set('Result/LastPart', p['id'])
        self.set('Result/LastDefect', cause)
        if ng:
            self.ng += 1
            only_burr = all(k in ('burr', 'false') for k, _ in found)
            if only_burr and p.get('rework', 0) < 1:
                p['rework'] = p.get('rework', 0) + 1
                p.event(self.plant, self.id, 'rework', reason=cause)
                self.buf('rework', 'deb_in').put(p)
            else:
                self.plant.scrap(p, self.id, _tr('内腔缺陷') if any(k == 'pore' for k, _ in found) else _tr('毛刺返修后仍不合格'))
        else:
            self.ok += 1
            p['status'] = 'GOOD'
            self.plant.kpi['good'] += 1
            self.buf('out', 'fg').put(p)
        self.set('Result/OK', self.ok)
        self.set('Result/NG', self.ng)
        self.part = None

    def view(self):
        return {'last': self.get('Result/Last'), 'hole': self.get('Probe/HoleIndex')}
