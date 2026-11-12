"""课程里"预算"规则用的成本表（万元，教学用的示意价格）。

每类块：固定价 + 按参数计价（如缓存按容量、车队按车辆数、人员池按人数、输送线按长度）。
课程里每一课可以用 lesson.costs 覆盖：{"processor": {"base": 40}, "transporter": {"per": {"count": 10}}}。
"""
import copy

COSTS = {
    'source': {'base': 0, 'label': '来料'},
    'sink': {'base': 0, 'label': '出口'},
    'storage': {'base': 10, 'label': '仓库'},
    'processor': {'base': 30, 'label': '加工设备', 'per': {'capacity': 0}},
    'batch': {'base': 25, 'label': '批处理设备'},
    'assembly': {'base': 15, 'label': '装配工位'},
    'split': {'base': 2, 'label': '拆分工位'},
    'inspect': {'base': 20, 'label': '检测设备'},
    'rework': {'base': 5, 'label': '返修台'},
    'buffer': {'base': 0.5, 'label': '缓存', 'per': {'capacity': 0.1}},
    'conveyor': {'base': 1, 'label': '输送线', 'per': {'length_m': 0.4}},
    'transporter': {'base': 0, 'label': '搬运车队', 'per': {'count': 8}},
    'operators': {'base': 0, 'label': '人员（年）', 'per': {'count': 10}},
    'cell': {'base': 20, 'label': '控制单元'},
}
DEFAULT_PARAM = {'capacity': {'buffer': 50, 'processor': 1}, 'count': {'transporter': 2, 'operators': 2}, 'length_m': {'conveyor': 10}}


def table(overrides=None):
    t = copy.deepcopy(COSTS)
    for k, v in (overrides or {}).items():
        cur = t.setdefault(k, {'base': 0, 'label': k})
        if 'base' in v:
            cur['base'] = float(v['base'])
        if 'per' in v:
            cur.setdefault('per', {}).update({p: float(x) for p, x in v['per'].items()})
        if 'label' in v:
            cur['label'] = v['label']
    return t


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def block_cost(b, t):
    c = t.get(b.get('type'))
    if not c:
        return 0.0
    params = b.get('params') or {}
    total = float(c.get('base', 0))
    for p, unit in (c.get('per') or {}).items():
        total += unit * _num(params.get(p, DEFAULT_PARAM.get(p, {}).get(b.get('type'), 0)))
    return round(total, 2)


def model_cost(model, overrides=None):
    """模型总成本（万元）和按块明细。"""
    t = table(overrides)
    rows = []
    for b in model.get('blocks') or []:
        c = block_cost(b, t)
        if c:
            rows.append({'id': b['id'], 'name': b.get('name') or b['id'], 'type': b.get('type'), 'label': t.get(b.get('type'), {}).get('label', b.get('type')),
                         'cost': c})
    return round(sum(r['cost'] for r in rows), 2), rows
