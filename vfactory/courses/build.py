"""生成内置课程：vfactory/courses/<课程>.json 和课里的工厂 vfactory/courses/plants/<工厂>.yaml。

    python -m vfactory.courses.build          # 改了这里的定义后重新生成
    python -m vfactory.courses.verify         # 每课：起始模型低分、参考答案满分

课程：
  plc_basics   PLC 控制基础（15 个控制单元场景，4 章）
  machining    生产线仿真与优化（机加工）：8 课，从一台机床到完整机加车间
  foundry      铸造厂运营（综合）：6 课，从某小型铸造厂到某转向器壳体铸造厂
工厂里只用 2.0 通用块（来料、加工、批处理、缓存、输送线、检测、出口、搬运车队、人员池），每课评分几秒内跑完。
"""
import copy
import json
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PLANTS = os.path.join(HERE, 'plants')
ROOT = os.path.dirname(os.path.dirname(HERE))
START = '2026-11-02T07:00:00'

AREA_COLORS = {'收货区': '#F2EEE3', '机加区': '#E3ECF2', '检测区': '#E8E3F2', '仓储区': '#E3F0E6', '熔炼区': '#F4E3D7', '造型区': '#EDE6DA',
               '清理区': '#E6E9EC', '生产区': '#E3ECF2'}


# ---------------------------------------------------------------- 搭模型的小工具
class M:
    def __init__(self, name, product, floor, areas, speed=60, plan=None, layout=None):
        self.blocks, self.links = [], []
        self.plant = {'name': name, 'product': product, 'seed': 7, 'start': START, 'dt': 1.0, 'speed': speed, 'warmup_h': 0, 'floor': list(floor)}
        if layout:
            self.plant['layout'] = layout
        self.areas = [{'name': n, 'x': list(x), 'color': AREA_COLORS.get(n, '#E3ECF2')} for n, x in areas]
        self.plan = plan
        self.col = 0

    def b(self, bid, typ, name, pos, size=(4, 3.4), node=None, **params):
        if node is None:
            node = [80 + 200 * self.col, 160]
            self.col += 1
        self.blocks.append({'id': bid, 'type': typ, 'name': name, 'pos': list(pos), 'size': list(size), 'node': list(node), 'params': params})
        return bid

    def l(self, a, b, ap='out', bp='in', **kw):
        lid = f'L{len(self.links) + 1}'
        self.links.append({'id': lid, 'from': a, 'from_port': ap, 'to': b, 'to_port': bp, **kw})
        return lid

    def model(self):
        m = {'version': 2, 'plant': copy.deepcopy(self.plant), 'areas': self.areas, 'blocks': self.blocks, 'links': self.links, 'groups': [], 'notes': []}
        if self.plan:
            m['plan'] = self.plan
        return m


def add_block_ops(model, src_id, new_id, name, dpos=(0, 5), dnode=(0, 140), links=()):
    """参考答案：复制一台设备（参数相同）并接上连线。links: [(from, to)]"""
    src = next(b for b in model['blocks'] if b['id'] == src_id)
    nb = copy.deepcopy(src)
    nb.update(id=new_id, name=name, pos=[src['pos'][0] + dpos[0], src['pos'][1] + dpos[1]], node=[src['node'][0] + dnode[0], src['node'][1] + dnode[1]])
    ops = [{'op': 'add_block', 'block': nb}]
    for i, (a, b) in enumerate(links):
        ops.append({'op': 'add_link', 'link': {'id': f'LR{new_id}{i}', 'from': a, 'from_port': 'out', 'to': b, 'to_port': 'in'}})
    return ops


def setp(bid, **kv):
    return {'op': 'update_block', 'id': bid, 'set': {f'params.{k}': v for k, v in kv.items()}}


PROC_LOCK = ['time', 'capacity', 'mtbf_h', 'mttr_min', 'setup_min', 'setup_matrix', 'times_by_product', 'defects', 'run_kw', 'idle_kw', 'load_s',
             'operator_mode']


def choice(key, label, choices, answer, weight):
    return {'key': key, 'kind': 'answer', 'label': label, 'choices': choices, 'answer': answer, 'weight': weight}


def pick(key, label, answer, weight, kinds=None):
    return {'key': key, 'kind': 'answer', 'label': label, 'pick': True, 'kinds': kinds or ['processor', 'batch', 'inspect', 'conveyor', 'buffer'],
            'answer': answer if isinstance(answer, list) else [answer], 'weight': weight}


def kpi(key, metric, op, value, weight, label=None):
    r = {'key': key, 'kind': 'kpi', 'metric': metric, 'op': op, 'value': value, 'weight': weight}
    if label:
        r['label'] = label
    return r


def budget(value, weight, label=None):
    return {'key': 'budget', 'kind': 'budget', 'metric': 'cost', 'op': '<=', 'value': value, 'weight': weight, 'label': label or f'投资合计 ≤ {value} 万元'}


def limit(key, metric, op, value, weight, label):
    return {'key': key, 'kind': 'limit', 'metric': metric, 'op': op, 'value': value, 'weight': weight, 'label': label}


# ================================================================ 机加工课程
def mc01():
    m = M('某精密机加厂·单机工位', 'HSG-200 壳体', (30, 14), [('收货区', (0, 10)), ('机加区', (10, 22)), ('仓储区', (22, 30))])
    m.b('SRC', 'source', '毛坯来料', (2, 5), (4, 4), interval='expo(45)')
    m.b('B0', 'buffer', '待加工', (7, 5), (3, 3), capacity=200)
    m.b('M1', 'processor', '1#加工中心', (13, 5), time='normal(75,3)', run_kw=12, idle_kw=2)
    m.b('OUT', 'sink', '成品库', (24, 5), (4, 4))
    m.l('SRC', 'B0'), m.l('B0', 'M1'), m.l('M1', 'OUT')
    lesson = {
        'id': 'm01', 'title': '单机节拍与产能', 'kind': 'plant', 'plant': 'mc01_single', 'time_h': 8, 'seed': 7,
        'brief_md': """### 任务：让一台加工中心"刚好吃饱"

车间只有一台 **1#加工中心（M1）**，加工一件壳体平均 **75 秒**（正态分布，标准差 3 秒）。
毛坯由 **来料（SRC）** 送进 **待加工（B0）** 缓存，现在来料间隔是 `expo(45)`：平均 45 秒来一件。

1. 先运行 10 分钟（仿真时间），看看 B0 里的件数和 M1 的状态，想一想为什么在制品越堆越多。
2. 回答：M1 每小时最多能加工多少件？
3. 改 **SRC 的到达间隔**（选中 SRC → 右边属性面板 → 节拍），让 M1 尽量满负荷、又不让毛坯在 B0 里排长队（间隔要比 75 秒稍大一点：太小会排队、周期超标，太大产量不够）：
   - 小时产出 ≥ 43 件；
   - 平均生产周期（从到货到入库）≤ 6 分钟。

> 只能改来料的到达间隔，加工中心的节拍是设备能力，评分时按原值计算。""",
        'hints': ['产能 = 3600 秒 ÷ 单件用时。', '来得比做得快，多出来的件只能排队，排队时间全算在生产周期里。',
                  '到达间隔可以写固定值，例如 `80` 表示每 80 秒来一件；写 `expo(80)` 是平均 80 秒、随机波动。'],
        'rules': [choice('q_cap', 'M1 每小时最多能加工多少件', ['约 36 件', '约 48 件', '约 60 件', '约 75 件'], 1, 30),
                  kpi('thr', 'good_per_h', '>=', 43, 30), kpi('lead', 'lead_mean_min', '<=', 6, 40)],
        'lock': {'blocks': ['M1', 'B0', 'OUT'], 'params': {'processor': PROC_LOCK}, 'plan': True},
        'reference': {'ops': [setp('SRC', interval='80')], 'answers': {'q_cap': 1}},
    }
    return m, lesson


def serial_line(name, source='expo(50)', bufcap=1):
    m = M(name, 'HSG-200 壳体', (52, 16), [('收货区', (0, 10)), ('机加区', (10, 44)), ('仓储区', (44, 52))])
    m.b('SRC', 'source', '毛坯来料', (2, 6), (4, 4), interval=source)
    m.b('B0', 'buffer', '毛坯库', (7, 6), (3, 3), capacity=100)
    m.b('M1', 'processor', '1#车削', (12, 6), time='expo(55)', run_kw=12, idle_kw=2)
    m.b('B1', 'buffer', '缓存 1', (18, 6.5), (2.5, 2.5), capacity=bufcap)
    m.b('M2', 'processor', '2#钻孔', (22, 6), time='expo(55)', run_kw=10, idle_kw=2)
    m.b('B2', 'buffer', '缓存 2', (28, 6.5), (2.5, 2.5), capacity=bufcap)
    m.b('M3', 'processor', '3#铣削', (32, 6), time='expo(55)', run_kw=14, idle_kw=2)
    m.b('OUT', 'sink', '成品库', (46, 6), (4, 4))
    for a, b in (('SRC', 'B0'), ('B0', 'M1'), ('M1', 'B1'), ('B1', 'M2'), ('M2', 'B2'), ('B2', 'M3'), ('M3', 'OUT')):
        m.l(a, b)
    return m


def mc02():
    m = serial_line('某精密机加厂·三工序串行线')
    lesson = {
        'id': 'm02', 'title': '串行线与缓存', 'kind': 'plant', 'plant': 'mc02_serial', 'time_h': 8, 'seed': 11,
        'brief_md': """### 任务：用缓存"吸收"波动

三台机床 **M1 → M2 → M3** 串成一条线，平均节拍都是 55 秒（每小时约 65 件），但每件的用时波动很大（指数分布）。
两台机床之间的缓存 **B1、B2** 现在只能放 **1 件**。

1. 运行一段时间，观察 M1、M2 的状态构成：它们经常"堵料"（做好了放不出去）或"缺料"（等上游）。
2. 回答：缓存只有 1 件时，M1 损失时间最多的状态是什么？
3. 调整 **B1、B2 的容量**，让小时产出 ≥ 53 件，同时投资不超过预算（缓存每个库位 0.1 万元）。

> 不能加机床、不能改机床节拍。""",
        'hints': ['节拍一样的机床串起来，产量反而低于单台——因为波动会互相传递。',
                  '缓存越大越能吸收波动，但边际效果递减：从 1 到 5 提升明显，从 10 到 50 几乎没变化。',
                  '在"分析"里看每台设备的时间构成，堵料比例下降说明缓存起作用了。'],
        'rules': [choice('q_state', '缓存只有 1 件时，M1 损失时间最多的状态', ['缺料（等上游）', '堵料（做好放不出去）', '故障', '换型'], 1, 20),
                  kpi('thr', 'good_per_h', '>=', 53, 50), budget(104, 30)],
        'lock': {'blocks': ['SRC', 'B0', 'M1', 'M2', 'M3', 'OUT'], 'params': {'processor': PROC_LOCK}, 'plan': True},
        'reference': {'ops': [setp('B1', capacity=10), setp('B2', capacity=10)], 'answers': {'q_state': 1}},
    }
    return m, lesson


def four_station(name, source):
    m = M(name, 'HSG-200 壳体', (64, 20), [('收货区', (0, 10)), ('机加区', (10, 56)), ('仓储区', (56, 64))])
    m.b('SRC', 'source', '毛坯来料', (2, 7), (4, 4), interval=source)
    m.b('B0', 'buffer', '毛坯库', (7, 7), (3, 3), capacity=200)
    m.b('M1', 'processor', '1#车削', (12, 7), time='normal(48,3)', run_kw=12, idle_kw=2)
    m.b('B1', 'buffer', '缓存 1', (17.5, 7.5), (2.5, 2.5), capacity=10)
    m.b('M2', 'processor', '2#钻孔', (22, 7), time='normal(58,3)', run_kw=10, idle_kw=2)
    m.b('B2', 'buffer', '缓存 2', (27.5, 7.5), (2.5, 2.5), capacity=10)
    m.b('M3', 'processor', '3#铣削', (32, 7), time='normal(74,4)', run_kw=15, idle_kw=2)
    m.b('B3', 'buffer', '缓存 3', (37.5, 7.5), (2.5, 2.5), capacity=10)
    m.b('M4', 'processor', '4#去毛刺', (42, 7), time='normal(52,3)', run_kw=6, idle_kw=1)
    m.b('OUT', 'sink', '成品库', (58, 7), (4, 4))
    for a, b in (('SRC', 'B0'), ('B0', 'M1'), ('M1', 'B1'), ('B1', 'M2'), ('M2', 'B2'), ('B2', 'M3'), ('M3', 'B3'), ('B3', 'M4'), ('M4', 'OUT')):
        m.l(a, b)
    return m


def mc03():
    m = four_station('某精密机加厂·四工序线', 'expo(45)')
    lesson = {
        'id': 'm03', 'title': '找瓶颈', 'kind': 'plant', 'plant': 'mc03_bottleneck', 'time_h': 8, 'seed': 13,
        'brief_md': """### 任务：找出限制整线产量的那台设备

四道工序：**车削 M1 → 钻孔 M2 → 铣削 M3 → 去毛刺 M4**，中间各有 10 件缓存。来料比整线做得快，毛坯库一直有料。

1. 运行至少 1 小时（仿真时间）。看三维/流程图上各设备的颜色、各缓存的件数，再打开"分析"看时间构成。
2. 在图上 **点选瓶颈设备**（左侧任务面板里点"在图上点选"，再点设备）。
3. 回答整线的最大产能和最有效的改进办法。

> 判断瓶颈的两个线索：瓶颈前面的缓存总是满的、后面的总是空的；瓶颈自己的"运行"比例最高、几乎不缺料也不堵料。""",
        'hints': ['看 B1、B2、B3 三个缓存：哪个总是满的？满缓存的下游就是嫌疑设备。',
                  '整线产能由最慢的工序决定：3600 ÷ 瓶颈的单件用时。',
                  '提高非瓶颈设备的速度不会让整线变快。'],
        'rules': [pick('q_bn', '瓶颈是哪台设备', 'M3', 40, ['processor']),
                  choice('q_cap', '整线每小时最多约能产出', ['约 48 件', '约 62 件', '约 69 件', '约 75 件'], 0, 30),
                  choice('q_fix', '提高整线产量最有效的办法', ['给 M1 提速', '加大 B1 的容量', '给 M3 并联一台同样的铣床', '给 M4 并联一台'], 2, 30)],
        'lock': {'blocks': ['SRC', 'M1', 'M2', 'M3', 'M4', 'OUT'], 'params': {'processor': PROC_LOCK}, 'plan': True},
        'reference': {'ops': [], 'answers': {'q_bn': 'M3', 'q_cap': 0, 'q_fix': 2}},
    }
    return m, lesson


def mc04():
    m = four_station('某精密机加厂·线平衡', 'expo(45)')
    ref = add_block_ops(m.model(), 'M3', 'M3B', '3#铣削（二）', dpos=(0, 6), links=[('B2', 'M3B'), ('M3B', 'B3')])
    lesson = {
        'id': 'm04', 'title': '并行机与线平衡', 'kind': 'plant', 'plant': 'mc04_balance', 'time_h': 8, 'seed': 17,
        'brief_md': """### 任务：花最少的钱把产量提上去

上一课找到了瓶颈——**3#铣削（M3）**，单件 74 秒。现在订单要求 **小时产出 ≥ 56 件**。
一台同型号机床投资 **30 万元**，预算只够再买一台。

1. 想清楚该给哪道工序加机床，以及加完以后新的瓶颈会变成谁。
2. 在模型里加一台和瓶颈设备一样的机床（选中设备 → 复制 / 粘贴，参数会一起复制），把它接到前后缓存上（与原设备并联）：在流程图里从前面缓存卡片右侧的"出"拖一条线到新机床的"入"，再从新机床的"出"拖到后面的缓存。
3. 运行验证：小时产出 ≥ 56 件，投资不超过预算。

> 新加的机床必须是已有型号（参数和原设备一致），评分时会按原设备的节拍计算。""",
        'hints': ['并联：新机床从同一个上游缓存取料，做完放到同一个下游缓存。',
                  '两台 M3 并联后，铣削工序每小时能做约 97 件，这时最慢的是谁？',
                  '如果产量没上去，检查新机床的连线是否接对了（流程图里应该是 B2 → 新机床 → B3）。'],
        'rules': [kpi('thr', 'good_per_h', '>=', 56, 50), budget(181, 30),
                  choice('q_next', '给瓶颈并联一台后，新的瓶颈是', ['1#车削 M1', '2#钻孔 M2', '3#铣削 M3', '4#去毛刺 M4'], 1, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'M1', 'M2', 'M3', 'M4', 'OUT'], 'params': {'processor': PROC_LOCK}, 'plan': True},
        'reference': {'ops': ref, 'answers': {'q_next': 1}},
    }
    return m, lesson


def mc05():
    layout = {'paths': {'nodes': [{'id': 'P1', 'x': 8, 'y': 3}, {'id': 'P2', 'x': 8, 'y': 26}, {'id': 'P3', 'x': 40, 'y': 26}, {'id': 'P4', 'x': 40, 'y': 3},
                                  {'id': 'P5', 'x': 72, 'y': 26}, {'id': 'P6', 'x': 72, 'y': 3}],
                        'edges': [{'a': 'P1', 'b': 'P2'}, {'a': 'P2', 'b': 'P3'}, {'a': 'P3', 'b': 'P4'}, {'a': 'P3', 'b': 'P5'}, {'a': 'P5', 'b': 'P6'}]}}
    m = M('某精密机加厂·物流', 'HSG-200 壳体', (80, 30), [('收货区', (0, 16)), ('机加区', (16, 60)), ('仓储区', (60, 80))], layout=layout)
    m.b('SRC', 'source', '毛坯到货', (2, 6), (4, 4), interval='expo(55)')
    m.b('B0', 'buffer', '收货暂存', (8, 6), (3, 3), capacity=200)
    m.b('TR1', 'transporter', 'AGV 车队', (20, 22), (2, 2), count=1, speed_mps=1.0, capacity=2, load_s=30)
    m.b('B1', 'buffer', '线边库', (36, 6), (3, 3), capacity=20)
    m.b('M1', 'processor', '1#加工中心', (42, 4), time='normal(100,5)', run_kw=14, idle_kw=2)
    m.b('M2', 'processor', '2#加工中心', (42, 10), time='normal(100,5)', run_kw=14, idle_kw=2)
    m.b('B2', 'buffer', '下线暂存', (50, 6), (3, 3), capacity=20)
    m.b('OUT', 'sink', '成品库', (72, 6), (5, 5))
    m.l('SRC', 'B0'), m.l('B0', 'B1', via='TR1'), m.l('B1', 'M1'), m.l('B1', 'M2'), m.l('M1', 'B2'), m.l('M2', 'B2'), m.l('B2', 'OUT', via='TR1')
    ref = [setp('TR1', count=3)]
    lesson = {
        'id': 'm05', 'title': 'AGV 物流与路网', 'kind': 'plant', 'plant': 'mc05_agv', 'time_h': 8, 'seed': 19,
        'brief_md': """### 任务：别让机床等车

收货区、机加区、成品库离得很远，毛坯和成品都靠 **AGV 车队（TR1）** 运送：现在只有 **1 台车**，每车装 2 件，沿平面图里画好的路网行驶（绕了远路）。
两台加工中心每小时一共能做约 72 件，但实际产量远远不到。

1. 运行一段时间，看看 AGV 的利用率和两台加工中心"缺料"的比例。
2. 回答：判断"运输是瓶颈"的依据。
3. 让 **小时产出 ≥ 52 件**，投资不超过预算。可以：增加 AGV 台数（每台 8 万元），或在平面图的路网里画一条近路（把 P1 和 P4 直接连起来，不花钱）。

> AGV 的速度、载重、装卸时间是车型参数，不能改。""",
        'hints': ['一辆车既要送毛坯又要运成品，一趟来回要多久？用距离 ÷ 速度 + 装卸时间估一下。',
                  '车不够时，加工中心大部分时间在"缺料"。',
                  '路网里 P1→P2→P3→P4 绕了一个大弯；直接连 P1 和 P4 能省不少路。'],
        'rules': [kpi('thr', 'good_per_h', '>=', 52, 50), budget(85, 30),
                  choice('q_why', '哪个现象最能说明"运输是瓶颈"', ['加工中心运行比例很高', '加工中心大部分时间缺料，而收货暂存里堆满毛坯', '成品库发运很慢', '加工中心经常故障'], 1, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'M1', 'M2', 'OUT'], 'params': {'processor': PROC_LOCK, 'transporter': ['speed_mps', 'capacity', 'load_s']}, 'plan': True},
        'costs': {'buffer': {'base': 0, 'per': {'capacity': 0}}},
        'reference': {'ops': ref, 'answers': {'q_why': 1}},
    }
    return m, lesson


def mc06():
    plan = {'shifts': [{'name': '早班', 'start': '07:00', 'end': '15:00'}, {'name': '中班', 'start': '15:00', 'end': '23:00'}],
            'products': [{'code': 'HSG-A', 'name': '壳体 A', 'cycle_factor': 1.0}, {'code': 'HSG-B', 'name': '壳体 B', 'cycle_factor': 1.0},
                         {'code': 'HSG-C', 'name': '壳体 C', 'cycle_factor': 1.0}],
            'orders': [{'code': 'SO-01', 'product': 'HSG-A', 'qty': 130, 'due': '2026-11-02 21:00'},
                       {'code': 'SO-02', 'product': 'HSG-B', 'qty': 130, 'due': '2026-11-02 21:00'},
                       {'code': 'SO-03', 'product': 'HSG-A', 'qty': 130, 'due': '2026-11-02 21:00'},
                       {'code': 'SO-04', 'product': 'HSG-C', 'qty': 130, 'due': '2026-11-02 21:00'},
                       {'code': 'SO-05', 'product': 'HSG-B', 'qty': 130, 'due': '2026-11-02 21:00'},
                       {'code': 'SO-06', 'product': 'HSG-C', 'qty': 130, 'due': '2026-11-02 21:00'}]}
    m = M('某精密机加厂·多品种', 'HSG 壳体（A/B/C）', (36, 14), [('收货区', (0, 10)), ('机加区', (10, 28)), ('仓储区', (28, 36))], plan=plan)
    m.b('SRC', 'source', '按订单投料', (2, 5), (4, 4), interval='40')
    m.b('B0', 'buffer', '待加工', (7, 5), (3, 3), capacity=12)
    m.b('M1', 'processor', '1#柔性加工中心', (14, 5), time='normal(50,2)', setup_min=45, run_kw=14, idle_kw=2)
    m.b('OUT', 'sink', '成品库', (29, 5), (4, 4))
    m.l('SRC', 'B0'), m.l('B0', 'M1'), m.l('M1', 'OUT')
    o = plan['orders']
    grouped = [o[0], o[2], o[1], o[4], o[3], o[5]]
    lesson = {
        'id': 'm06', 'title': '班次、换型与订单', 'kind': 'plant', 'plant': 'mc06_orders', 'time_h': 16, 'seed': 23,
        'brief_md': """### 任务：排好订单顺序，按时交货

一台柔性加工中心做三种壳体 A、B、C，单件约 50 秒；**每换一次产品要换型 45 分钟**。两个班（07:00–23:00）。
今天有 6 张订单，每张 130 件，**全部要在 21:00 前完成**。现在按接单顺序排产：A、B、A、C、B、C。

1. 在"生产计划"里看订单进度和预计完成时间，运行一个班看看能不能按时交。
2. 回答：按现在的顺序一天要换型几次？
3. 只调整 **订单顺序**（不能改数量、产品和交期），让所有订单按时完成。

> 设备节拍和换型时间不能改，也不能加班或加设备。""",
        'hints': ['每次产品不同就要换型：A→B、B→A……数一数。', '同一种产品的订单排在一起，换型次数最少。',
                  '换型 45 分钟 ≈ 少做 54 件。6 张单共 780 件，光加工就要约 11 小时。'],
        'rules': [kpi('late', 'orders_late', '==', 0, 50, '延期订单数 = 0'), kpi('done', 'orders_done', '>=', 6, 30, '完成订单数 ≥ 6'),
                  choice('q_co', '按原顺序（A、B、A、C、B、C）要换型几次（开班第一次准备不算）', ['2 次', '3 次', '5 次', '6 次'], 2, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'M1', 'OUT'], 'params': {'processor': PROC_LOCK}, 'plan': ['orders']},
        'reference': {'ops': [{'op': 'update_plant', 'set': {'plan.orders': grouped}}], 'answers': {'q_co': 2}},
    }
    return m, lesson


def mc07():
    m = M('某精密机加厂·看机人员', 'HSG-200 壳体', (48, 22), [('收货区', (0, 10)), ('机加区', (10, 40)), ('仓储区', (40, 48))])
    m.b('SRC', 'source', '毛坯来料', (2, 8), (4, 4), interval='expo(48)')
    m.b('B0', 'buffer', '毛坯库', (7, 8), (3, 3), capacity=200)
    m.b('OP1', 'operators', '操作工', (24, 18), (2, 2), count=1)
    for i, y in enumerate((2, 7, 12, 17), 1):
        m.b(f'M{i}', 'processor', f'{i}#加工中心', (18 if i <= 2 else 28, y if i <= 2 else y - 10), node=[300, 40 + 120 * i], time='normal(170,6)',
            operator='OP1', operator_mode='load', load_s=70, mtbf_h=3, mttr_min=25, run_kw=14, idle_kw=2)
    m.b('OUT', 'sink', '成品库', (42, 8), (4, 4), node=[560, 300])
    m.l('SRC', 'B0')
    for i in range(1, 5):
        m.l('B0', f'M{i}'), m.l(f'M{i}', 'OUT')
    lesson = {
        'id': 'm07', 'title': '设备故障与人员配置', 'kind': 'plant', 'plant': 'mc07_crew', 'time_h': 8, 'seed': 29,
        'brief_md': """### 任务：配多少个操作工合适

四台加工中心并联，每台单件约 170 秒，其中**前 70 秒**是上下料，需要操作工在场。设备平均每 3 小时坏一次，平均修 25 分钟。
现在只有 **1 名操作工（OP1）** 看四台机床。

1. 运行一段时间，看加工中心报警里"等待操作工"出现得多不多，看操作工的忙闲。
2. 回答：只考虑故障时，单台设备的可用率大约是多少？
3. 调整 **操作工人数**（每人每年 10 万元），让小时产出 ≥ 64 件，人员和设备投资不超过预算。

> 设备台数、节拍、故障参数和上下料时间不能改。""",
        'hints': ['可用率 ≈ MTBF ÷ (MTBF + MTTR)。', '1 个人每小时最多上下料 3600 ÷ 70 ≈ 51 次，而来料每小时约 75 件、每件上下料一次，就是每小时约 75 次。',
                  '人加多了也浪费：第 3 个人大部分时间在等。'],
        'rules': [kpi('thr', 'good_per_h', '>=', 64, 50), budget(165, 30),
                  choice('q_av', 'MTBF 3 小时、MTTR 25 分钟时，单台设备的可用率约', ['78%', '88%', '92%', '97%'], 1, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'M1', 'M2', 'M3', 'M4', 'OUT'], 'params': {'processor': PROC_LOCK + ['operator']}, 'plan': True},
        'reference': {'ops': [setp('OP1', count=2)], 'answers': {'q_av': 1}},
    }
    return m, lesson


def mc08():
    m = M('某精密机加厂·机加车间', 'HSG-200 壳体', (70, 30), [('收货区', (0, 12)), ('机加区', (12, 48)), ('检测区', (48, 58)), ('仓储区', (58, 70))])
    m.b('SRC', 'source', '毛坯到货', (2, 8), (4, 4), interval='expo(62)', defects=[{'name': '气孔', 'prob': '0.02'}])
    m.b('B0', 'buffer', '收货暂存', (7, 8), (3, 3), capacity=200)
    m.b('TR1', 'transporter', '叉车', (12, 2), (2, 2), count=1, speed_mps=1.2, capacity=6, load_s=40)
    m.b('B1', 'buffer', '线边库', (15, 8), (3, 3), capacity=30)
    m.b('OP1', 'operators', '车削操作工', (20, 24), (2, 2), count=1)
    m.b('M1', 'processor', '1#数控车床', (20, 8), time='normal(95,4)', operator='OP1', operator_mode='load', load_s=40, mtbf_h=8, mttr_min=20, run_kw=12, idle_kw=2)
    m.b('B2', 'buffer', '车铣之间', (27, 8.5), (2.5, 2.5), capacity=4)
    m.b('M2', 'processor', '1#加工中心', (31, 8), time='normal(115,5)', mtbf_h=8, mttr_min=25, run_kw=16, idle_kw=2,
        defects=[{'name': '毛刺', 'prob': '0.05'}])
    m.b('B3', 'buffer', '待检', (40, 8.5), (2.5, 2.5), capacity=20)
    m.b('QC', 'inspect', '在线检测', (49, 8), (4, 4), time='30', pod_pct=95, false_pct=1)
    m.b('RW', 'rework', '返修台', (49, 16), (4, 4), time='normal(240,20)', fixes=['毛刺'], max_rework=1)
    m.b('OUT', 'sink', '成品库', (61, 8), (5, 5))
    for a, b in (('SRC', 'B0'), ('B1', 'M1'), ('M1', 'B2'), ('B2', 'M2'), ('M2', 'B3'), ('B3', 'QC'), ('QC', 'OUT'), ('RW', 'B3')):
        m.l(a, b)
    m.l('B0', 'B1', via='TR1')
    m.l('QC', 'RW', ap='ng')
    mdl = m.model()
    ref = add_block_ops(mdl, 'M1', 'M1B', '2#数控车床', dpos=(0, 6), links=[('B1', 'M1B'), ('M1B', 'B2')])
    ref += add_block_ops(mdl, 'M2', 'M2B', '2#加工中心', dpos=(0, 6), links=[('B2', 'M2B'), ('M2B', 'B3')])
    ref += [setp('B2', capacity=8)]
    lesson = {
        'id': 'm08', 'title': '综合：在预算内达成产能目标', 'kind': 'plant', 'plant': 'mc08_capstone', 'time_h': 8, 'seed': 31,
        'brief_md': """### 综合任务：一个真实的扩产方案

某精密机加厂接了新订单，壳体毛坯每小时到货约 58 件（产能至少要跟上到货，否则毛坯越堆越多，生产周期一定超标），要求：

| 指标 | 要求 |
|---|---|
| 小时产出 | ≥ 48 件 |
| 平均生产周期 | ≤ 60 分钟（毛坯不能在收货区堆积） |
| 新增投资 | 预算以内（见评分标准） |

车间现状：叉车把毛坯从收货区运到线边 → **数控车床 M1**（95 秒，要操作工上下料）→ **加工中心 M2**（115 秒）→ **在线检测 QC**（不合格去返修）→ 成品库。

你可以：加同型号设备（数控车床 30 万、加工中心 30 万）、调缓存容量、调操作工人数（10 万/人/年）、调叉车台数（8 万/台）。
先用前几课的方法找出瓶颈，再一步步扩产，每改一次运行验证。

> 设备节拍、故障、质量参数不能改；新加设备必须是已有型号。""",
        'hints': ['先算：车床每小时约 38 件、加工中心约 31 件、检测 120 件——哪道工序必须加设备？',
                  '加了加工中心以后，车床会不会变成新瓶颈？',
                  '车床加到两台时，一个操作工还忙得过来吗？看报警里的"等待操作工"。'],
        'rules': [kpi('thr', 'good_per_h', '>=', 48, 40), kpi('lead', 'lead_mean_min', '<=', 60, 30), budget(200, 30)],
        'lock': {'blocks': ['SRC', 'B0', 'QC', 'RW', 'OUT'], 'params': {'processor': PROC_LOCK + ['operator'], 'transporter': ['speed_mps', 'capacity', 'load_s'],
                                                                         'inspect': ['time', 'pod_pct', 'false_pct'], 'rework': ['time', 'success_pct', 'max_rework', 'fixes']},
                 'plan': True},
        'reference': {'ops': ref, 'answers': {}},
    }
    return m, lesson


# ================================================================ 铸造课程
def mini_foundry(name, *, cool_len=60, cool_v=0.025, shot_batch=12, pour_temp='normal(1440,10)', grind='normal(70,4)', source='expo(52)', pod=92):
    m = M(name, '球铁铸件', (96, 26), [('熔炼区', (0, 14)), ('造型区', (14, 60)), ('清理区', (60, 84)), ('仓储区', (84, 96))])
    # 布局（4.6）：一条线排下来，相邻设备之间留 1~1.5 m（三维里自动补短输送段）；冷却线从浇注一直铺到落砂（铸型在线上冷却后直接落砂），
    # 占地长度固定 35 m（不随 length_m 变：实际冷却线长了会盘成多股，占地不变）；清理段在厂房尾部折成 U 形：打磨 → 终检 → 毛坯库。
    m.b('SRC', 'source', '砂型下芯', (5, 8), (4, 4), interval=source)
    m.b('B0', 'buffer', '待造型', (9.5, 8), (3, 3), capacity=60)
    m.b('MOLD', 'processor', '造型机', (15, 8), (6, 4), time='normal(44,2)', run_kw=30, idle_kw=5)
    m.b('POUR', 'processor', '浇注', (21, 8), (4, 4), time='normal(30,2)', run_kw=8, idle_kw=2, attrs={'temp': pour_temp})
    m.b('COOL', 'conveyor', '冷却线', (41.5, 8), (35, 2.5), length_m=cool_len, speed_mps=cool_v, pitch_m=1, run_kw=4, idle_kw=1)
    m.b('SHAKE', 'processor', '落砂', (62, 8), (4, 4), time='normal(38,2)', run_kw=15, idle_kw=2,
        defects=[{'name': '冷隔', 'prob': "0.01 + 0.35*(item.get('temp',1440) < 1415)"}])
    m.b('B1', 'buffer', '待抛丸', (67, 8), (3, 3), capacity=80)
    m.b('SHOT', 'batch', '吊钩抛丸机', (71.5, 8), (5, 5), batch=shot_batch, time='600', max_wait_min=20, run_kw=45, idle_kw=4)
    m.b('B2', 'buffer', '待打磨', (76.5, 8), (2.5, 2.5), capacity=120)
    m.b('GRIND', 'processor', '清理打磨', (80.5, 8), (3, 3), time=grind, capacity=2, run_kw=6, idle_kw=1)
    m.b('QC', 'inspect', '终检', (80.5, 13), (4, 4), time='20', pod_pct=pod, false_pct=1)
    m.b('OUT', 'sink', '毛坯库', (86.5, 13), (5, 5))
    for a, b in (('SRC', 'B0'), ('B0', 'MOLD'), ('MOLD', 'POUR'), ('POUR', 'COOL'), ('COOL', 'SHAKE'), ('SHAKE', 'B1'), ('B1', 'SHOT'), ('SHOT', 'B2'), ('B2', 'GRIND'),
                 ('GRIND', 'QC'), ('QC', 'OUT')):
        m.l(a, b)
    return m


FD_LOCK = {'processor': PROC_LOCK, 'conveyor': ['speed_mps', 'pitch_m', 'run_kw', 'idle_kw'], 'batch': ['time', 'run_kw', 'idle_kw'],
           'inspect': ['time', 'pod_pct', 'false_pct']}


def fd01():
    m = mini_foundry('某小型铸造厂', cool_len=24, cool_v=0.01, source='expo(48)')
    lock = copy.deepcopy(FD_LOCK)
    lock['conveyor'] = ['pitch_m', 'run_kw', 'idle_kw']
    lesson = {
        'id': 'f01', 'title': '冷却线决定产能', 'kind': 'plant', 'plant': 'fd01_cooling', 'time_h': 8, 'warmup_h': 1, 'seed': 37,
        'brief_md': """### 任务：铸型必须冷够 40 分钟

某小型铸造厂：造型机约 44 秒造一型（每小时 80 多型），浇注后的铸型放上 **冷却线（COOL）** 冷却，再落砂、抛丸、打磨、终检。
工艺要求：**每型在冷却线上至少冷却 40 分钟**，每型占 1 米。冷却线现在 **24 米长、速度 0.01 m/s**——刚好冷 40 分钟，
但它每秒只能"吐出"0.01 米，也就是每 100 秒才下线一型。

1. 运行 1 小时，看造型机和浇注是不是经常"堵料"。
2. 回答：冷却线现在每小时最多能通过多少型？
3. 改造冷却线（加长每米 0.4 万元，速度可以调），让 **小时产出 ≥ 65 件**，并且 **冷却时间仍然 ≥ 40 分钟**，投资不超过预算。

> 冷却时间 = 长度 ÷ 速度；通过能力 = 速度 ÷ 每型间距。间距是工艺要求，不能改。""",
        'hints': ['只提速不加长，冷却时间就不够；只加长不提速，通过能力不变。两个一起改。',
                  '要每小时通过 80 型，速度至少 80 × 1 米 ÷ 3600 秒 ≈ 0.022 m/s；冷 40 分钟需要多长？',
                  '在"分析"里看造型机的堵料比例，改完以后应该明显下降。'],
        'rules': [kpi('thr', 'good_per_h', '>=', 65, 40), limit('cool', 'cool_min.COOL', '>=', 40, 20, '冷却时间 ≥ 40 分钟'), budget(220, 20),
                  choice('q_cap', '冷却线现在（24 米、0.01 m/s）每小时最多通过几型', ['24 型', '36 型', '60 型', '90 型'], 1, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'MOLD', 'POUR', 'SHAKE', 'SHOT', 'GRIND', 'QC', 'OUT'], 'params': lock, 'plan': True},
        'reference': {'ops': [setp('COOL', length_m=60, speed_mps=0.025)], 'answers': {'q_cap': 1}},
    }
    return m, lesson


def fd02():
    m = mini_foundry('某小型铸造厂·清理工段', shot_batch=60)
    m.blocks = [b for b in m.blocks]
    for b in m.blocks:
        if b['id'] == 'SHOT':
            b['params']['max_wait_min'] = 90
    lesson = {
        'id': 'f02', 'title': '抛丸批量与在制品', 'kind': 'plant', 'plant': 'fd02_shot', 'time_h': 8, 'warmup_h': 1, 'seed': 41,
        'brief_md': """### 任务：批量不是越大越好

**吊钩抛丸机（SHOT）** 一次挂一批铸件，抛一批固定 10 分钟。现在每批要凑够 **60 件**才开机（最长等 90 分钟），
结果铸件在"待抛丸"里一等就是很久，在制品多、生产周期长。

1. 运行一段时间，看待抛丸缓存的件数怎么变化、抛丸机的运行比例。
2. 回答：批量太大时，铸件大部分时间在做什么？
3. 调整 **每批件数** 和 **凑批最长等待**，让：平均生产周期 ≤ 70 分钟，同时小时产出 ≥ 65 件。

> 抛一批的时间（10 分钟）是工艺参数，不能改。""",
        'hints': ['抛丸机能力 = 每批件数 × 6 批/小时；来料约每小时 69 件，批量至少要多大？',
                  '批量越大，第一件要等后面的件凑齐，平均等待约 批量 ÷ 2 个到达间隔。',
                  '凑批最长等待也要跟着改小，否则来料少时会一直等。'],
        'rules': [kpi('lead', 'lead_mean_min', '<=', 70, 40), kpi('thr', 'good_per_h', '>=', 65, 40),
                  choice('q_wait', '批量太大时，铸件大部分时间在', ['抛丸', '等着凑够一批', '打磨', '冷却'], 1, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'MOLD', 'POUR', 'COOL', 'SHAKE', 'GRIND', 'QC', 'OUT'], 'params': FD_LOCK, 'plan': True},
        'reference': {'ops': [setp('SHOT', batch=16, max_wait_min=15)], 'answers': {'q_wait': 1}},
    }
    return m, lesson


def fd03():
    m = mini_foundry('某小型铸造厂·质量追溯', pour_temp='normal(1412,10)')
    lesson = {
        'id': 'f03', 'title': '质量追溯：缺陷从哪来', 'kind': 'plant', 'plant': 'fd03_quality', 'time_h': 8, 'warmup_h': 1, 'seed': 43,
        'brief_md': """### 任务：废品率突然升到 10% 以上

终检（QC）发现大量 **冷隔** 缺陷，被判废。冷隔是在落砂后才看得出来的，但它不是落砂造成的。

1. 运行后打开"零件"面板，挑几件被判废的铸件看履历：它们经过了哪些设备、每道工序记下了什么数据（比如浇注温度 temp）。
2. 在图上 **点选缺陷的来源工序**，并回答原因。
3. 改该工序的工艺设定，让 **废品率 ≤ 3%**。

> 提示：浇注工序的"写入零件属性"里有浇注温度的设定（`normal(均值, 标准差)`），铁水温度标准是 1440 ℃（不要低于 1435 ℃）。""",
        'hints': ['一件铸件的履历里有每道工序的时间和属性，被判废的件和合格件比一比，哪个属性不一样？',
                  '冷隔：铁水温度太低，两股铁水汇合时没融合好。',
                  '温度平均值调回 1440 ℃（不要低于 1435），标准差 10 不变。'],
        'rules': [pick('q_src', '冷隔缺陷来自哪道工序', 'POUR', 25, ['processor', 'batch', 'conveyor', 'inspect']),
                  choice('q_cause', '冷隔的直接原因', ['砂型水分高', '浇注温度偏低', '打磨用力过猛', '终检太严'], 1, 25),
                  kpi('scrap', 'scrap_rate', '<=', 0.03, 50, '废品率 ≤ 3%')],
        'lock': {'blocks': ['SRC', 'B0', 'MOLD', 'COOL', 'SHAKE', 'SHOT', 'GRIND', 'QC', 'OUT'], 'params': FD_LOCK, 'plan': True},
        'reference': {'ops': [setp('POUR', attrs={'temp': 'normal(1440,10)'})], 'answers': {'q_src': 'POUR', 'q_cause': 1}},
    }
    return m, lesson


def fd04():
    m = M('某小型铸造厂·熔炼', '球铁铸件', (60, 24), [('熔炼区', (0, 20)), ('造型区', (20, 50)), ('仓储区', (50, 60))])
    m.b('SRC', 'source', '炉料', (2, 9), (4, 4), interval='expo(40)')
    m.b('B0', 'buffer', '炉料堆场', (7, 9), (3, 3), capacity=300)
    m.b('FUR1', 'processor', '1#中频炉', (12, 4), (4, 4), node=[400, 80], time='normal(52,2)', run_kw=640, idle_kw=150, follow_shifts=False)
    m.b('FUR2', 'processor', '2#中频炉', (12, 14), (4, 4), node=[400, 240], time='normal(52,2)', run_kw=640, idle_kw=150, follow_shifts=False)
    m.b('B1', 'buffer', '保温包', (19, 9.5), (3, 3), capacity=6)
    m.b('MOLD', 'processor', '造型浇注', (25, 8), (8, 4), time='normal(60,2)', run_kw=40, idle_kw=6)
    m.b('OUT', 'sink', '铸件', (52, 9), (4, 4))
    m.l('SRC', 'B0'), m.l('B0', 'FUR1'), m.l('B0', 'FUR2'), m.l('FUR1', 'B1'), m.l('FUR2', 'B1'), m.l('B1', 'MOLD'), m.l('MOLD', 'OUT')
    lesson = {
        'id': 'f04', 'title': '能耗：别让电炉空等', 'kind': 'plant', 'plant': 'fd04_energy', 'time_h': 8, 'warmup_h': 1, 'seed': 47,
        'brief_md': """### 任务：把单件电耗降下来

熔炼是铸造厂的用电大户。两台中频炉（每台熔一包约 52 秒 —— 这里一"件"代表一型所需的铁水）都开着，
但下游造型浇注 60 秒才要一包铁水。炉子没活干时也要 **保温，待机功率 150 kW**。

1. 运行后打开"能耗"分析，看两台电炉各自的运行比例和用电。
2. 回答：两台炉同时开时，每台炉的利用率大约是多少？
3. 在不降低产量的前提下，让 **单件电耗 ≤ 13 kWh**，**小时产出 ≥ 55 件**。

> 电炉的熔化时间和功率是设备参数，不能改。""",
        'hints': ['造型每小时要约 60 包铁水，一台炉每小时能熔约 69 包。', '多开的那台炉大部分时间在保温空耗。',
                  '删除一台炉（只断开连线的话它还在保温耗电，单耗下不来）。'],
        'rules': [kpi('kwh', 'kwh_per_good', '<=', 13, 40, '单件电耗 ≤ 13 kWh'), kpi('thr', 'good_per_h', '>=', 55, 40),
                  choice('q_util', '两台炉同时开时，每台炉的利用率约', ['约 25%', '约 45%', '约 80%', '约 100%'], 1, 20)],
        'lock': {'blocks': ['SRC', 'B0', 'MOLD', 'OUT'], 'params': {'processor': PROC_LOCK}, 'plan': True},
        'reference': {'ops': [{'op': 'remove_block', 'id': 'FUR2'}], 'answers': {'q_util': 1}},
    }
    return m, lesson


def fd05():
    m = mini_foundry('某小型铸造厂·排故')
    lesson = {
        'id': 'f05', 'title': '排故：产量突然下降', 'kind': 'diagnose', 'plant': 'fd05_diagnose', 'time_h': 8, 'warmup_h': 1, 'seed': 53,
        'faults': [{'block': 'GRIND', 'param': 'time', 'value': 'normal(150,6)', 'label': '清理打磨变慢（砂轮磨损）'}],
        'brief_md': """### 任务：昨天还好好的

某小型铸造厂昨天每小时产出 65 件以上，今天只有四十多件。现场反映"哪儿都没坏"。请你当一回设备工程师：

1. 运行后找出现在的瓶颈设备（看缓存堆积、设备状态构成）。
2. 对照下面的 **设备档案**，找出哪台设备的参数和档案不一致。
3. 在图上 **点选出问题的设备**，回答故障类型，然后把参数改回正常值。

| 设备 | 档案节拍 | 说明 |
|---|---|---|
| 造型机 MOLD | normal(44,2) 秒 | |
| 浇注 POUR | normal(30,2) 秒 | 浇注温度 normal(1440,10) |
| 冷却线 COOL | 60 米，0.025 m/s | 冷却 40 分钟 |
| 落砂 SHAKE | normal(38,2) 秒 | |
| 抛丸 SHOT | 每批 12 件，600 秒 | |
| 清理打磨 GRIND | normal(70,4) 秒，2 个工位 | |
| 终检 QC | 20 秒，检出率 92% | |""",
        'hints': ['整线变慢，先找"前面堆满、自己一直在干活"的设备。', '找到可疑设备后打开属性面板，和档案逐项对照。',
                  '故障类型看是哪个参数变了：节拍变长是"加工变慢"。'],
        'rules': [pick('q_dev', '出问题的设备', 'GRIND', 30, ['processor', 'batch', 'conveyor', 'inspect']),
                  choice('q_type', '故障类型', ['供应中断', '加工变慢', '检出率下降', '缓存被改小'], 1, 20),
                  kpi('thr', 'good_per_h', '>=', 60, 50, '修好后小时产出 ≥ 60 件')],
        'lock': {'blocks': ['SRC', 'B0', 'MOLD', 'POUR', 'COOL', 'SHAKE', 'SHOT', 'GRIND', 'QC', 'OUT'], 'params': FD_LOCK, 'plan': True},
        'reference': {'ops': [setp('GRIND', time='normal(70,4)')], 'answers': {'q_dev': 'GRIND', 'q_type': 1}},
    }
    return m, lesson


def fd06():
    lesson = {
        'id': 'f06', 'title': '综合：某转向器壳体铸造厂', 'kind': 'plant', 'plant': 'fd06_full', 'time_h': 4, 'seed': 59,
        'brief_md': """### 综合任务：读懂一座完整的铸造 + 机加工厂

这是完整的 **某转向器壳体铸造厂**：中频炉熔炼 → 球化孕育 → 造型浇注 → 冷却 → 抛丸 → 数控加工 → 去毛刺 → 内窥检测 → 立体仓库，
设备都用了精细的工艺模型（炉温、球化衰退、砂处理水分、刀具磨损……），点位和真实工厂一样多。

运行至少 4 小时（仿真），用这门课学过的方法回答：

1. 整厂的瓶颈是哪台设备？（在图上点选）
2. 全厂用电最多的是哪类设备？（在图上点选其中一台）
3. 机加工以后才发现的气孔缺陷，应该追溯到哪个工段去改进？""",
        'hints': ['"分析"里的时间构成和瓶颈排名；也可以看"运行报表"。', '"能耗"分析按设备列出了用电。',
                  '零件履历里记录了炉次、浇包、浇注温度、型砂水分等，缺陷和这些数据有关。'],
        'rules': [pick('q_bn', '整厂瓶颈', 'MOLD1', 35, ['molding_line', 'cnc', 'induction_furnace', 'treatment', 'shot_blast', 'inspection', 'deburr_cell']),
                  pick('q_energy', '用电最多的设备（任选一台）', ['FUR1', 'FUR2'], 30, ['induction_furnace', 'processor', 'batch', 'inspect', 'conveyor', 'buffer']),
                  choice('q_trace', '机加后发现的气孔缺陷，应该追溯到', ['熔炼、浇注与砂处理', '数控加工', '内窥检测', '立体仓库'], 0, 35)],
        'reference': {'ops': [], 'answers': {'q_bn': 'MOLD1', 'q_energy': 'FUR1', 'q_trace': 0}},
    }
    return None, lesson


# ================================================================ PLC 课程
PLC_CHAPTERS = [
    ('c1', '基本逻辑', ['s01_motor_latch', 's02_fwd_rev', 's03_conveyor', 's08_timed_feed']),
    ('c2', '分拣与计数', ['s04_sort_color', 's05_sort_material', 's06_sort_height', 's07_count_box']),
    ('c3', '搬运与仓储', ['s09_palletize', 's10_turntable', 's11_lift', 's12_pick_place', 's13_asrs']),
    ('c4', '联锁与整线', ['s14_dual_station', 's15_full_line']),
]


def plc_course():
    sc_dir = os.path.join(ROOT, 'vfactory', 'control', 'scenes')
    chapters = []
    for cid, title, ids in PLC_CHAPTERS:
        lessons = []
        for sid in ids:
            p = os.path.join(sc_dir, f'{sid}.json')
            name = sid
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    name = json.load(f).get('name', sid)
            lessons.append({'id': sid.split('_')[0], 'title': name, 'kind': 'cell', 'scene': sid})
        chapters.append({'id': cid, 'title': title, 'lessons': lessons})
    return {'id': 'plc_basics', 'name': 'PLC 控制基础', 'level': 1, 'order': 1,
            'desc': '15 个设备级控制任务：从电机启停自锁到整线联动。每课在自己的沙箱里写梯形图或结构化文本，提交后用自动测试序列评分。',
            'chapters': chapters}


def write_plant(pid, m):
    os.makedirs(PLANTS, exist_ok=True)
    from ..server import write_yaml
    write_yaml(os.path.join(PLANTS, f'{pid}.yaml'), m.model() if isinstance(m, M) else m)


def course_of(cid, name, desc, level, chapters):
    out = []
    for ch_id, ch_title, makers in chapters:
        lessons = []
        for mk in makers:
            m, lesson = mk()
            if m is not None:
                write_plant(lesson['plant'], m)
            lessons.append(lesson)
        out.append({'id': ch_id, 'title': ch_title, 'lessons': lessons})
    return {'id': cid, 'name': name, 'desc': desc, 'level': level, 'order': level, 'chapters': out}


def build():
    courses = [
        plc_course(),
        course_of('machining', '生产线仿真与优化（机加工）',
                  '从一台机床到完整的机加车间：节拍与产能、缓存、瓶颈、线平衡、物流、排产换型、人员与故障，最后在预算内做一个扩产方案。'
                  '每课一个工厂，改模型、跑仿真、按指标自动评分。', 2,
                  [('c1', '节拍与流动', [mc01, mc02, mc03]), ('c2', '产能提升', [mc04, mc05]), ('c3', '计划与资源', [mc06, mc07]), ('c4', '综合', [mc08])]),
        course_of('foundry', '铸造厂运营（综合）',
                  '从某小型铸造厂到完整的某转向器壳体铸造厂：冷却与产能、批处理、质量追溯、熔炼能耗、排故，最后读懂一座完整工厂。', 3,
                  [('c1', '流程与产能', [fd01, fd02]), ('c2', '质量与能耗', [fd03, fd04]), ('c3', '排故与综合', [fd05, fd06])]),
    ]
    # 综合课用示范工厂（铸造 + 机加）的副本
    src = os.path.join(ROOT, 'plants', 'foundry-housing.yaml')
    if os.path.exists(src):
        with open(src, encoding='utf-8') as f:
            full = yaml.safe_load(f)
        full['plant']['name'] = '某转向器壳体铸造厂（课程）'
        full['plant'].pop('modbus_port', None)
        full['plant']['speed'] = 60
        full['plant']['warmup_h'] = 2
        write_plant('fd06_full', full)
    from .explain import apply as add_explain       # 4.6.2 作答题的解析（explain.py）
    for c in courses:
        add_explain(c)
        with open(os.path.join(HERE, f"{c['id']}.json"), 'w', encoding='utf-8') as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    n = sum(len(ch['lessons']) for c in courses for ch in c['chapters'])
    print(f'已生成 {len(courses)} 门课程、{n} 课')


if __name__ == '__main__':
    build()
