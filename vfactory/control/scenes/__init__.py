"""场景库：vfactory/control/scenes/*.json（由 build.py 生成）。

    from vfactory.control import scenes
    scenes.list_scenes()                 # 摘要列表（不含参考答案）
    scenes.get_scene('s04_sort_color')   # 完整场景（含参考答案，老师/评分用）
    scenes.scene_plant(scene)            # 只含这个控制单元（+ 有单元入口/出口时的来料和出口）的独立工厂模型，给学生沙箱用
"""
from ...i18n import _tr, content
import copy
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_cache: dict = {}


def scene_ids():
    return [os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(HERE, '*.json')))]


def get_scene(sid):
    path = os.path.join(HERE, f'{os.path.basename(str(sid))}.json')
    if not os.path.exists(path):
        return None
    mt = os.path.getmtime(path)
    c = _cache.get(path)
    if c and c[0] == mt:
        return content(copy.deepcopy(c[1]), path)
    with open(path, encoding='utf-8') as f:
        s = json.load(f)
    _cache[path] = (mt, s)
    return content(copy.deepcopy(s), path)          # display texts in the current language (i18n/<scene>.en.json)


def summary(s):
    comps = (s.get('cell') or {}).get('components') or []
    return {'id': s['id'], 'name': s['name'], 'level': s.get('level'), 'desc': s.get('desc', ''), 'io_count': len(s.get('io') or []),
            'comp_count': len(comps), 'types': sorted({c['type'] for c in comps}), 'faults': s.get('faults', []),
            'rules': [{k: r.get(k) for k in ('key', 'label', 'op', 'value', 'weight')} for r in (s.get('scoring') or {}).get('rules', [])],
            'has_ld': 'ld' in (s.get('reference') or {}), 'duration': (s.get('test') or {}).get('duration')}


def list_scenes():
    out = []
    for sid in scene_ids():
        s = get_scene(sid)
        if s:
            out.append(summary(s))
    out.sort(key=lambda x: (x.get('level') or 99, x['id']))
    return out


def public_scene(s, reference=False):
    """去掉参考答案（学生看到的版本）。"""
    d = copy.deepcopy(s)
    if not reference:
        d.pop('reference', None)
    return d


def scene_plant(s, title='', with_reference=False, speed=1):
    """场景 → 独立的 2.0 工厂模型：一个控制单元块 CELL1；单元里有入口/出口时再加来料和出口块。"""
    if isinstance(s, str):
        s = get_scene(s)
    cell = copy.deepcopy(s['cell'])
    cell['plc'] = copy.deepcopy(s.get('plc') or cell.get('plc') or {'mode': 'internal', 'scan_ms': 20})
    if with_reference and (s.get('reference') or {}).get('st'):
        cell['plc']['program'] = copy.deepcopy(s['reference']['st'])
    L, W = (cell.get('size') or [8, 4])[:2]
    types = {c['type'] for c in cell.get('components') or []}
    fx, fy = L + 14, max(W + 8, 12)
    blocks = [{'id': 'CELL1', 'type': 'cell', 'name': s['name'], 'pos': [fx / 2, fy / 2], 'size': [L, W], 'rot': 0, 'node': [300, 120],
               'params': {'cell': cell}}]
    links = []
    if 'cell_entry' in types:
        feed = (s.get('test') or {}).get('feed') or {}
        blocks.append({'id': 'SRC', 'type': 'source', 'name': _tr('上游来料'), 'pos': [3, fy / 2], 'size': [3, 3], 'node': [40, 120],
                       'params': {'interval': str(feed.get('interval', 8))}})
        links.append({'id': 'L1', 'kind': 'material', 'from': 'SRC', 'from_port': 'out', 'to': 'CELL1', 'to_port': 'in'})
    if 'cell_exit' in types:
        blocks.append({'id': 'OUT', 'type': 'sink', 'name': _tr('下游'), 'pos': [fx - 3, fy / 2], 'size': [3, 3], 'node': [560, 80], 'params': {}})
        links.append({'id': 'L2', 'kind': 'material', 'from': 'CELL1', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'})
        if any(c.get('type') == 'cell_exit' and (c.get('params') or {}).get('port') == 'ng' for c in cell.get('components') or []):
            blocks.append({'id': 'NG', 'type': 'sink', 'name': _tr('不合格品'), 'pos': [fx - 3, fy / 2 + 4], 'size': [3, 3], 'node': [560, 200],
                           'params': {'scrap': True, 'scrap_cause': _tr('单元剔除')}})
            links.append({'id': 'L3', 'kind': 'material', 'from': 'CELL1', 'from_port': 'ng', 'to': 'NG', 'to_port': 'in'})
    m = {'version': 2,
            'plant': {'name': (title or s['name'])[:40], 'product': _tr('实训零件'), 'seed': 7, 'start': '2026-11-02T08:00:00', 'dt': 1.0, 'speed': speed,
                      'warmup_h': 0, 'floor': [fx, fy]},
            'areas': [{'name': _tr('实训区'), 'x': [0, fx], 'color': '#E3ECF2'}],
            'blocks': blocks, 'links': links, 'groups': [], 'notes': [], 'scene': s['id']}
    # 4.3：PLC 是独立设备——单元 CELL1 + PLC 块 PLC1（程序在 PLC1.params.program）+ 信号线 SIG1（单元的全部 I/O）
    from ...plc.migrate import migrate_model
    migrate_model(m)
    return m


# 教学模块按这些名字找构造函数
build_plant = plant_for_scene = standalone_plant = scene_plant
