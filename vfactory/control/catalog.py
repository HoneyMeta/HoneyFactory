"""控制单元部件目录：编辑器的部件库、属性面板、I/O 表自动生成都从这里来。

坐标约定（单元局部坐标，单位 m）：原点在单元中心，x 向右（单元长度方向），y 向前（单元宽度方向），z 向上。
pos = [x, y, z]，rot = 绕竖直轴的转角（度，逆时针）。部件自身的"前方"：
  - 输送类：局部 +x 是正转方向；
  - 侧装类（传感器、推杆、摆臂、挡停）：动作/光束方向是局部 -y（装在输送线 +y 一侧、rot=0 时朝输送线中心）。
I/O 方向以 PLC 为准：传感器、按钮 = in（%I）；执行器、灯 = out（%Q）。
"""

from ..i18n import _tr
P = lambda label, t, default, unit='', help='', **kw: {'label': label, 't': t, 'default': default, 'unit': unit, 'help': help, **kw}  # noqa: E731

CONV = {'speed': P('速度', 'num', 0.3, 'm/s'), 'height': P('台面高度', 'num', 0.25, 'm', '台面离单元底面的高度'),
        'reversible': P('可反转', 'bool', False), 'motor': P('由电机驱动', 'text', '', help='填电机部件编号：输送速度跟随该电机；空表示自带正/反转输出'),
        'kw': P('电机功率', 'num', 0.37, 'kW')}
SENSOR = {'nc': P('常闭输出', 'bool', False, help='勾选后检测到物体时输出 0（常闭接法）')}
PANEL = {'label': P('铭牌文字', 'text', ''), 'color': P('颜色', 'enum', 'green', options={'green': '绿', 'red': '红', 'yellow': '黄', 'blue': '蓝', 'white': '白', 'black': '黑'})}
ACCEPT = P('接收条件', 'json', {}, help='只接收这些零件（分拣是否正确的依据）：{"color":"blue"}、{"material":"metal"}、{"kind":["box","part"]}、'
                                        '{"min_h":0.15}、{"max_h":0.15}；空表示都算正确')
PART_TPL = P('零件', 'json', [{'kind': 'box', 'color': 'blue', 'material': 'plastic', 'h': 0.2, 'w': 0.25, 'weight': 1}],
             help='按权重随机选一种：kind 种类（box/part/pallet/tote）、color 颜色、material 材质（metal/plastic）、h 高度 m、w 边长 m、weight 权重')

COMP_TYPES = {
    # ---------------- 输送 ----------------
    'belt_conveyor': {'label': '皮带输送机', 'cat': '输送', 'size': [2.0, 0.6], 'params': dict(CONV), 'surface': True,
                      'help': '零件沿局部 +x 方向输送；端头没有接续部件时零件会掉到地上'},
    'roller_conveyor': {'label': '滚筒输送机', 'cat': '输送', 'size': [2.0, 0.6], 'params': dict(CONV), 'surface': True},
    'curved_conveyor': {'label': '弯道输送机', 'cat': '输送', 'size': [1.2, 0.6], 'surface': True,
                        'params': {**CONV, 'radius': P('中心线半径', 'num', 0.9, 'm'), 'angle': P('转角', 'num', 90, '°', '正数左转（逆时针），负数右转')},
                        'help': 'pos 是弯道入口中心；rot 是入口处的输送方向；size[1] 是带宽'},
    'chain_transfer': {'label': '链式移载机', 'cat': '输送', 'size': [0.6, 0.6], 'surface': True,
                       'params': {'speed': P('移载速度', 'num', 0.3, 'm/s'), 'height': P('台面高度', 'num', 0.25, 'm'), 'reversible': P('可反向', 'bool', True),
                                  'kw': P('电机功率', 'num', 0.25, 'kW')},
                       'help': '放在滚筒线上：顶升后链条把零件沿局部 +y（或 -y）横移到旁边的线上；落下时零件随下面的滚筒走'},
    # ---------------- 出入口 ----------------
    'emitter': {'label': '发料器', 'cat': '出入口', 'size': [0.4, 0.4],
                'params': {'interval': P('发料间隔', 'expr', '6', 's', '可用分布函数，如 uniform(5,7)、expo(8)'), 'parts': PART_TPL,
                           'max': P('最多发料件数', 'int', 0, '件', '0 表示不限'), 'start_delay': P('首件延时', 'num', 1.0, 's'),
                           'trigger': P('触发方式', 'enum', 'auto', options={'auto': '按间隔自动', 'signal': 'PLC 输出上升沿放一件（料仓）'}),
                           'yaw': P('零件朝向', 'num', 0, '°')},
                'help': '在 pos 处放出零件（零件底面在 pos 的高度，之后自由落到下面的台面上）；出料口被占用时等待'},
    'remover': {'label': '收料器', 'cat': '出入口', 'size': [0.6, 0.6], 'params': {'accept': ACCEPT, 'depth': P('收料区高度', 'num', 0.6, 'm'), 'label': P('名称', 'text', '')},
                'help': '零件中心进入收料区（pos 起往上 depth 高的立方区域）就被收走并计数；可当分拣料箱'},
    'cell_entry': {'label': '单元入口', 'cat': '出入口', 'size': [0.4, 0.4],
                   'params': {'assign': P('零件属性', 'json', {}, help='整厂零件进入单元时的属性：{"by_type":{"A":{"color":"blue"}},"random":[{"color":"blue","weight":3},{"color":"green","weight":1}],"default":{"kind":"box"},"defect":{"color":"red"}}；defect 是带真实缺陷的整厂零件（如上道检测漏检）的外观'),
                              'trigger': P('触发方式', 'enum', 'auto', options={'auto': '上游有料就放', 'signal': 'PLC 输出上升沿放一件'}),
                              'min_gap': P('最小间隔', 'num', 2.0, 's')},
                   'help': '整厂上游的零件从这里进入单元'},
    'cell_exit': {'label': '单元出口', 'cat': '出入口', 'size': [0.6, 0.6],
                  'params': {'port': P('整厂出口', 'enum', 'out', options={'out': '合格出口 out', 'ng': '不合格出口 ng'}), 'accept': ACCEPT, 'depth': P('出口区高度', 'num', 0.6, 'm')},
                  'help': '零件到这里交回整厂下游队列；下游满时零件停在出口（单元"堵料"）'},
    # ---------------- 传感器 ----------------
    'diffuse_sensor': {'label': '漫反射光电', 'cat': '传感器', 'size': [0.06, 0.06], 'params': {'range': P('检测距离', 'num', 0.8, 'm'), **SENSOR},
                       'help': '光束从 pos 沿局部 -y 射出，零件挡住光束（且光束高度在零件高度范围内）就输出 1'},
    'retro_sensor': {'label': '对射/反射光电', 'cat': '传感器', 'size': [0.06, 0.06], 'params': {'range': P('光束长度', 'num', 0.8, 'm'), **SENSOR},
                     'help': '发射器在 pos，反射板在局部 -y 方向 range 处；光束被挡输出 1'},
    'capacitive': {'label': '电容接近开关', 'cat': '传感器', 'size': [0.05, 0.05], 'params': {'range': P('检测距离', 'num', 0.12, 'm'), **SENSOR},
                   'help': '近距离检测任何材质的零件'},
    'inductive': {'label': '电感接近开关', 'cat': '传感器', 'size': [0.05, 0.05], 'params': {'range': P('检测距离', 'num', 0.12, 'm'), **SENSOR},
                  'help': '只检测金属零件'},
    'vision_sensor': {'label': '视觉传感器', 'cat': '传感器', 'size': [0.12, 0.12],
                      'params': {'radius': P('视野半径', 'num', 0.1, 'm', '零件中心进入视野才识别'),
                                 'mode': P('输出编码', 'enum', 'color', options={'color': '颜色码', 'kind': '种类码', 'id': '种类×10+颜色'})},
                      'help': '装在输送线上方朝下看。颜色码：1 蓝 2 绿 3 灰 4 红 5 黄 6 橙 7 白 8 黑；种类码：1 箱 2 工件 3 托盘 4 周转箱；没有零件时为 0'},
    'height_sensor': {'label': '测高传感器', 'cat': '传感器', 'size': [0.1, 0.1], 'params': {'radius': P('测量范围半径', 'num', 0.08, 'm')},
                      'help': '装在上方朝下测量：输出零件高度（mm），没有零件时为 0'},
    'encoder': {'label': '编码器', 'cat': '传感器', 'size': [0.08, 0.08],
                'params': {'conveyor': P('所测输送机', 'text', ''), 'ppm': P('每米脉冲数', 'num', 1000, '脉冲/m')},
                'help': '输出所测输送机皮带走过的累计脉冲数（DINT，反转时递减）'},
    # ---------------- 执行器 ----------------
    'pusher': {'label': '推杆（气缸）', 'cat': '执行器', 'size': [0.3, 0.12],
               'params': {'stroke': P('行程', 'num', 0.8, 'm'), 'speed': P('速度', 'num', 1.0, 'm/s'), 'head': P('推板宽度', 'num', 0.4, 'm'),
                          'mode': P('控制方式', 'enum', 'single', options={'single': '单电控（伸出信号保持=伸出，断开=缩回）', 'double': '双电控（伸出/缩回两个信号）'})},
               'help': '推板沿局部 -y 伸出；装在输送线侧面，pos 是缩回时推板面的位置'},
    'stopper': {'label': '挡停', 'cat': '执行器', 'size': [0.06, 0.6],
                'params': {'width': P('挡板宽度', 'num', 0.6, 'm'), 'normally_up': P('常态升起', 'bool', False, help='勾选后输出信号为"落下"（得电放行）'),
                           'time': P('升降时间', 'num', 0.15, 's')},
                'help': '挡板横在输送线上（沿局部 y），升起时挡住零件'},
    'pivot_arm': {'label': '摆臂分拣', 'cat': '执行器', 'size': [0.9, 0.08],
                  'params': {'length': P('摆臂长度', 'num', 0.85, 'm'), 'angle': P('摆角', 'num', 45, '°'), 'speed': P('摆动速度', 'num', 180, '°/s')},
                  'help': '转轴在 pos，缩回时摆臂沿局部 +x 贴在输送线边上；摆出后斜挡在输送线上，把零件导向局部 -y 一侧'},
    'turntable': {'label': '转台', 'cat': '执行器', 'size': [0.9, 0.9],
                  'params': {'angle': P('转角', 'num', 90, '°'), 'speed': P('转速', 'num', 90, '°/s'), 'roll_speed': P('台面滚筒速度', 'num', 0.3, 'm/s'),
                             'height': P('台面高度', 'num', 0.25, 'm')},
                  'help': '圆形台面带滚筒：转动时带着零件一起转；滚筒沿台面当前方向输送'},
    'lift': {'label': '升降台', 'cat': '执行器', 'size': [0.8, 0.7],
             'params': {'height': P('下位台面高度', 'num', 0.25, 'm'), 'z_high': P('上位台面高度', 'num', 1.0, 'm'), 'speed': P('升降速度', 'num', 0.4, 'm/s'),
                        'roll_speed': P('台面滚筒速度', 'num', 0.3, 'm/s')},
             'help': '台面在两个高度之间升降，台面滚筒沿局部 ±x 输送'},
    'pick_place': {'label': '两轴取放机械手', 'cat': '执行器', 'size': [1.6, 0.3],
                   'params': {'mode': P('轴控制', 'enum', 'pneumatic', options={'pneumatic': '气动两位（伸出/下降）', 'servo': '伺服定位（输出目标位置 mm）'}),
                              'x_stroke': P('水平行程', 'num', 1.2, 'm'), 'z_stroke': P('垂直行程', 'num', 0.6, 'm'), 'z_top': P('吸盘最高点高度', 'num', 1.1, 'm'),
                              'x_speed': P('水平速度', 'num', 0.8, 'm/s'), 'z_speed': P('垂直速度', 'num', 0.5, 'm/s')},
                   'help': '横梁沿局部 +x 布置，pos 是 X=0 时吸盘中心的地面投影；吸盘从上方吸住零件'},
    'stacker_crane': {'label': '堆垛机', 'cat': '执行器', 'size': [3.0, 0.5],
                      'params': {'travel': P('行走长度', 'num', 3.0, 'm'), 'x_speed': P('行走速度', 'num', 1.0, 'm/s'), 'z_speed': P('升降速度', 'num', 0.6, 'm/s'),
                                 'fork_stroke': P('货叉行程', 'num', 0.7, 'm'), 'fork_speed': P('货叉速度', 'num', 0.5, 'm/s'),
                                 'rack': P('货架', 'text', ''), 'station_in': P('入库口 [x, z]', 'json', None, help='目标 0：沿轨道距离 x，货叉高度 z'),
                                 'station_out': P('出库口 [x, z]', 'json', None, help='目标 N+1'), 'targets': P('自定义目标点', 'json', [], help='[[x,z],...] 填了就不用货架自动生成')},
                      'help': '沿局部 +x 行走；目标号 0 = 入库口，1…N = 货架库位（从下往上逐层、每层从左往右），N+1 = 出库口；货叉向局部 +y（左叉）或 -y（右叉）伸出，"顶升"把货叉抬高 8 cm 托起货物'},
    'gripper': {'label': '夹爪', 'cat': '执行器', 'size': [0.3, 0.7], 'params': {'width': P('夹持区宽度', 'num', 0.7, 'm'), 'time': P('开合时间', 'num', 0.2, 's')},
                'help': '固定在输送线上方的夹紧装置：夹紧后零件不随输送线移动'},
    'motor': {'label': '电机', 'cat': '执行器', 'size': [0.4, 0.3],
              'params': {'reversible': P('正反转', 'bool', False), 'ramp': P('启动时间', 'num', 0.5, 's'), 'kw': P('功率', 'num', 1.5, 'kW')},
              'help': '交流电机 + 接触器 + 热继电器。输入 running 是接触器辅助触点，ol_ok 是热继电器常闭触点（过载时为 0）'},
    # ---------------- 面板 ----------------
    'button': {'label': '按钮', 'cat': '面板', 'size': [0.08, 0.08], 'params': {**PANEL, 'nc': P('常闭触点', 'bool', False, help='常闭：没按时为 1，按下为 0（停止按钮常用）')}},
    'switch': {'label': '旋钮开关', 'cat': '面板', 'size': [0.08, 0.08], 'params': {**PANEL, 'positions': P('档位', 'enum', 2, options={2: '两档', 3: '三档（左-中-右）'})}},
    'estop': {'label': '急停按钮', 'cat': '面板', 'size': [0.1, 0.1], 'params': {'label': P('铭牌文字', 'text', '急停'),
                                                                        'hardwired': P('硬线切断', 'bool', False, help='勾选后按下急停直接切断所有执行器（不经过 PLC）')},
              'help': '常闭触点：正常为 1，按下为 0；按下后自锁，需旋转复位'},
    'lamp': {'label': '指示灯', 'cat': '面板', 'size': [0.06, 0.06], 'params': dict(PANEL)},
    'display': {'label': '数码管', 'cat': '面板', 'size': [0.2, 0.08], 'params': {'label': P('铭牌文字', 'text', ''), 'digits': P('位数', 'int', 4)}},
    'potentiometer': {'label': '电位器', 'cat': '面板', 'size': [0.08, 0.08], 'params': {'label': P('铭牌文字', 'text', ''), 'max': P('满量程', 'int', 1000)}},
    # ---------------- 货架/托盘 ----------------
    'rack': {'label': '货架', 'cat': '货架托盘', 'size': [2.4, 0.6], 'surface': True,
             'params': {'cols': P('列数', 'int', 4), 'rows': P('层数', 'int', 3), 'cell_h': P('层高', 'num', 0.5, 'm'), 'base': P('底层高度', 'num', 0.3, 'm'),
                        'fill': P('初始库存', 'json', [], help='[[列, 层, {"color":"blue"}], ...]（从 0 数起）')},
             'help': '库位沿局部 +x 排列，货架深度方向是局部 y'},
    'pallet': {'label': '托盘台', 'cat': '货架托盘', 'size': [0.9, 0.7], 'surface': True, 'params': {'height': P('台面高度', 'num', 0.3, 'm')},
               'help': '固定的码垛托盘：取放机械手把零件放在上面（可叠放）'},
}
CATS = ['输送', '出入口', '传感器', '执行器', '面板', '货架托盘']
ID_PREFIX = {'belt_conveyor': 'C', 'roller_conveyor': 'C', 'curved_conveyor': 'CC', 'chain_transfer': 'CT', 'emitter': 'E', 'remover': 'R', 'cell_entry': 'IN',
             'cell_exit': 'OUT', 'diffuse_sensor': 'S', 'retro_sensor': 'S', 'capacitive': 'CAP', 'inductive': 'IND', 'vision_sensor': 'V', 'height_sensor': 'H',
             'encoder': 'ENC', 'pusher': 'P', 'stopper': 'ST', 'pivot_arm': 'PA', 'turntable': 'T', 'lift': 'L', 'pick_place': 'PP', 'stacker_crane': 'SC',
             'gripper': 'G', 'motor': 'M', 'button': 'B', 'switch': 'SW', 'estop': 'ES', 'lamp': 'LP', 'display': 'D', 'potentiometer': 'POT', 'rack': 'RK',
             'pallet': 'PL'}
SENSORS = {'diffuse_sensor', 'retro_sensor', 'capacitive', 'inductive', 'vision_sensor', 'height_sensor', 'encoder'}
PANEL_IN = {'button', 'switch', 'estop', 'potentiometer'}
CONVEYORS = {'belt_conveyor', 'roller_conveyor', 'curved_conveyor'}
ACTUATORS = {'pusher', 'stopper', 'pivot_arm', 'turntable', 'lift', 'pick_place', 'stacker_crane', 'gripper', 'motor', 'chain_transfer'} | CONVEYORS

FAULTS = {'sensor_stuck_on': '传感器常通（一直为 1）', 'sensor_stuck_off': '传感器常断（一直为 0）', 'sensor_flicker': '传感器信号抖动',
          'wire_break': '断线（信号恒为 0）', 'actuator_jam': '执行器卡滞', 'actuator_slow': '执行器动作变慢', 'motor_overload': '电机过载跳闸'}


def faults_for(typ):
    """这类部件可以注入的故障。"""
    if typ in SENSORS or typ in PANEL_IN:
        return ['sensor_stuck_on', 'sensor_stuck_off', 'sensor_flicker', 'wire_break']
    if typ in ('motor',) or typ in CONVEYORS or typ == 'chain_transfer':
        return ['actuator_jam', 'actuator_slow', 'motor_overload', 'wire_break']
    if typ in ACTUATORS:
        return ['actuator_jam', 'actuator_slow', 'wire_break']
    if typ in ('lamp', 'display', 'emitter', 'cell_entry', 'cell_exit'):
        return ['wire_break']
    return []


def param(c, k):
    """部件参数（含目录默认值）。"""
    p = c.get('params') or {}
    if k in p and p[k] is not None:
        return p[k]
    spec = COMP_TYPES.get(c.get('type'), {}).get('params', {}).get(k)
    return spec['default'] if spec else None


def signals(c):
    """部件的信号：{'in': [(信号, 类型, 说明)], 'out': [...]}，in/out 以 PLC 为准。"""
    t = c.get('type')
    g = lambda k: param(c, k)  # noqa: E731
    I, O = [], []
    if t in CONVEYORS:
        if not g('motor'):
            O.append(('fwd', 'BOOL', _tr('正转')))
            if g('reversible'):
                O.append(('rev', 'BOOL', _tr('反转')))
    elif t == 'chain_transfer':
        O += [('up', 'BOOL', _tr('顶升')), ('fwd', 'BOOL', _tr('链条正向（局部 +y）'))]
        if g('reversible'):
            O.append(('rev', 'BOOL', _tr('链条反向（局部 -y）')))
        I.append(('is_up', 'BOOL', _tr('已顶升')))
    elif t in ('emitter', 'cell_entry'):
        if g('trigger') == 'signal':
            O.append(('release', 'BOOL', _tr('放料（上升沿放一件）')))
        if t == 'cell_entry':
            I.append(('ready', 'BOOL', _tr('上游有料')))
    elif t == 'cell_exit':
        I.append(('busy', 'BOOL', _tr('出口占用（下游满）')))
    elif t in ('diffuse_sensor', 'retro_sensor', 'capacitive', 'inductive'):
        I.append(('detect', 'BOOL', _tr('检测到')))
    elif t == 'vision_sensor':
        I += [('detect', 'BOOL', _tr('视野内有零件')), ('code', 'INT', _tr('识别码'))]
    elif t == 'height_sensor':
        I.append(('value', 'INT', _tr('高度 mm')))
    elif t == 'encoder':
        I.append(('count', 'DINT', _tr('累计脉冲')))
    elif t == 'pusher':
        O.append(('extend', 'BOOL', _tr('伸出')))
        if g('mode') == 'double':
            O.append(('retract', 'BOOL', _tr('缩回')))
        I += [('front', 'BOOL', _tr('伸出到位')), ('back', 'BOOL', _tr('缩回到位'))]
    elif t == 'stopper':
        O.append(('lower', 'BOOL', _tr('落下放行')) if g('normally_up') else ('raise', 'BOOL', _tr('升起挡料')))
    elif t == 'pivot_arm':
        O.append(('turn', 'BOOL', _tr('摆出')))
        I += [('turned', 'BOOL', _tr('摆出到位')), ('home', 'BOOL', _tr('回位'))]
    elif t == 'turntable':
        O += [('turn', 'BOOL', _tr('转到转角位')), ('roll_fwd', 'BOOL', _tr('滚筒正转')), ('roll_rev', 'BOOL', _tr('滚筒反转'))]
        I += [('home', 'BOOL', _tr('在 0° 位')), ('turned', 'BOOL', _tr('在转角位')), ('part', 'BOOL', _tr('台面中央有零件'))]
    elif t == 'lift':
        O += [('up', 'BOOL', _tr('上升（断开下降）')), ('roll_fwd', 'BOOL', _tr('滚筒正转')), ('roll_rev', 'BOOL', _tr('滚筒反转'))]
        I += [('bottom', 'BOOL', _tr('在下位')), ('top', 'BOOL', _tr('在上位')), ('part', 'BOOL', _tr('台面中央有零件'))]
    elif t == 'pick_place':
        if g('mode') == 'servo':
            O += [('x_set', 'INT', _tr('水平目标 mm')), ('z_set', 'INT', _tr('下降目标 mm')), ('grip', 'BOOL', _tr('吸取'))]
            I += [('x_pos', 'INT', _tr('水平位置 mm')), ('z_pos', 'INT', _tr('下降位置 mm')), ('x_at', 'BOOL', _tr('水平到位')), ('z_at', 'BOOL', _tr('垂直到位（或已接触）')),
                  ('gripped', 'BOOL', _tr('已吸住'))]
        else:
            O += [('x_ext', 'BOOL', _tr('水平伸出')), ('z_down', 'BOOL', _tr('下降')), ('grip', 'BOOL', _tr('吸取'))]
            I += [('x_back', 'BOOL', _tr('水平缩回到位')), ('x_front', 'BOOL', _tr('水平伸出到位')), ('z_top', 'BOOL', _tr('上升到位')), ('z_bottom', 'BOOL', _tr('下降到位（或已接触）')),
                  ('gripped', 'BOOL', _tr('已吸住'))]
    elif t == 'stacker_crane':
        O += [('target', 'INT', _tr('目标号')), ('fork_left', 'BOOL', _tr('货叉左伸（+y）')), ('fork_right', 'BOOL', _tr('货叉右伸（-y）')), ('lift', 'BOOL', _tr('货叉顶升'))]
        I += [('at_target', 'BOOL', _tr('到达目标')), ('moving', 'BOOL', _tr('行走/升降中')), ('fork_home', 'BOOL', _tr('货叉在中位')), ('fork_left_end', 'BOOL', _tr('左伸到位')),
              ('fork_right_end', 'BOOL', _tr('右伸到位')), ('loaded', 'BOOL', _tr('货叉上有货')), ('pos', 'INT', _tr('当前所在目标号（不在目标点为 -1）'))]
    elif t == 'gripper':
        O.append(('close', 'BOOL', _tr('夹紧')))
        I += [('closed', 'BOOL', _tr('已夹紧')), ('holding', 'BOOL', _tr('夹住零件'))]
    elif t == 'motor':
        if g('reversible'):
            O += [('fwd', 'BOOL', _tr('正转接触器')), ('rev', 'BOOL', _tr('反转接触器'))]
        else:
            O.append(('run', 'BOOL', _tr('接触器')))
        I += [('running', 'BOOL', _tr('运行反馈')), ('ol_ok', 'BOOL', _tr('热继电器正常（常闭）'))]
    elif t in ('button', 'estop'):
        I.append(('value', 'BOOL', _tr('触点')))
    elif t == 'switch':
        if int(g('positions') or 2) == 3:
            I += [('left', 'BOOL', _tr('左档')), ('right', 'BOOL', _tr('右档'))]
        else:
            I.append(('value', 'BOOL', _tr('接通')))
    elif t == 'potentiometer':
        I.append(('value', 'INT', _tr('旋钮值')))
    elif t == 'lamp':
        O.append(('on', 'BOOL', _tr('点亮')))
    elif t == 'display':
        O.append(('value', 'INT', _tr('显示值')))
    return {'in': I, 'out': O}


def io_name(c, sig, n_total):
    """I/O 名：只有一个信号的传感器/面板件直接用部件编号，其余用 编号_信号。"""
    if n_total == 1 and (c['type'] in SENSORS or c['type'] in PANEL_IN or c['type'] in ('lamp', 'display')):
        return c['id']
    return f"{c['id']}_{sig.upper()}"


# 静止时为 1 的到位/状态信号（设备在初始位置时接通）
IDLE_ON = {('pusher', 'back'), ('pivot_arm', 'home'), ('turntable', 'home'), ('lift', 'bottom'), ('stacker_crane', 'fork_home'),
           ('pick_place', 'x_back'), ('pick_place', 'z_top'), ('pick_place', 'x_at'), ('pick_place', 'z_at'), ('stacker_crane', 'at_target'),
           ('motor', 'ol_ok')}


def contact_of(c, sig, typ='BOOL', d='in'):
    """输入点的触点形式和"未操作时的值"：→ (contact 'NO'|'NC'|None, idle)。
    按钮按参数 nc；急停、热继电器是常闭；传感器按参数 nc（常闭输出 = 没检测到时为 1）；到位开关按设备初始位置。"""
    if d != 'in':
        return None, (False if typ == 'BOOL' else 0)
    if typ != 'BOOL':
        return None, 0
    t = c.get('type')
    nc = bool(param(c, 'nc')) if t in ('button',) or t in SENSORS else False
    if t == 'estop' or (t == 'motor' and sig == 'ol_ok'):
        nc = True
    idle = nc or (t, sig) in IDLE_ON
    return ('NC' if nc else 'NO'), (1 if idle else 0)


def annotate_io(cell: dict, io: list) -> list:
    """给 I/O 表每一行补上 contact（触点：NO 常开 / NC 常闭，只有开关量输入有）和 idle（未操作时的值），由部件参数决定。"""
    comps = {c['id']: c for c in cell.get('components') or []}
    for e in io:
        c = comps.get(e.get('comp'))
        if c is None:
            continue
        ct, idle = contact_of(c, e.get('signal'), e.get('type') or 'BOOL', e.get('dir'))
        if ct:
            e['contact'] = ct
        else:
            e.pop('contact', None)
        e['idle'] = idle
    return io


def nc_inputs(io: list) -> list:
    """常闭输入的名称（任务书里要专门说明）。"""
    return [e['name'] for e in io if e.get('dir') == 'in' and e.get('contact') == 'NC']


def auto_io(cell: dict, keep: list | None = None) -> list:
    """按部件生成 I/O 表；keep 里已有的条目（按 部件+信号 匹配）保留名称和地址。
    BOOL 输入 %I0.0 起、输出 %Q0.0 起；INT/DINT 输入 %IW100 起、输出 %QW100 起（DINT 占 4 字节）。"""
    keep = keep if keep is not None else (cell.get('io') or [])
    old = {(e.get('comp'), e.get('signal')): e for e in keep}
    used = {e.get('addr') for e in keep if e.get('addr')}
    names = {e.get('name') for e in keep}
    out = []
    nb = {'in': 0, 'out': 0}
    nw = {'in': 100, 'out': 100}

    def next_bool(d):
        while True:
            a = f"%{'I' if d == 'in' else 'Q'}{nb[d] // 8}.{nb[d] % 8}"
            nb[d] += 1
            if a not in used:
                return a

    def next_word(d, size):
        while True:
            a = f"%{'I' if d == 'in' else 'Q'}{'D' if size == 4 else 'W'}{nw[d]}"
            nw[d] += size
            if a not in used:
                return a
    for c in cell.get('components') or []:
        s = signals(c)
        n = len(s['in']) + len(s['out'])
        for d in ('in', 'out'):
            for sig, typ, desc in s[d]:
                e = old.get((c['id'], sig))
                if e:
                    out.append(dict(e, dir=d, type=e.get('type') or typ))
                    continue
                nm = io_name(c, sig, n)
                while nm in names:
                    nm += '_'
                names.add(nm)
                addr = next_bool(d) if typ == 'BOOL' else next_word(d, 4 if typ == 'DINT' else 2)
                used.add(addr)
                out.append({'name': nm, 'dir': d, 'type': typ, 'addr': addr, 'comp': c['id'], 'signal': sig,
                            'comment': f"{c.get('label') or COMP_TYPES.get(c['type'], {}).get('label', c['type'])} {c['id']} {desc}"})
    return annotate_io(cell, out)


def public():
    return {'types': COMP_TYPES, 'cats': CATS, 'prefix': ID_PREFIX, 'faults': FAULTS,
            'signals': {t: signals({'type': t, 'id': 'X'}) for t in COMP_TYPES},
            'fault_kinds': {t: faults_for(t) for t in COMP_TYPES}}
