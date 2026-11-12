"""零件定位与工艺路线：给"跟踪一件产品"和"工艺流转线"用。"""


from .i18n import _tr
def _station_pos(st):
    return [float(st.pos[0]), float(st.pos[1])]


def buffer_pos(plant, name):
    """缓存在厂区里的位置：AGV 节点优先，其次放在消费它的设备旁边。"""
    agv = next((s for s in plant.stations.values() if s.kind == 'agv'), None)
    nodes = agv.nodes if agv else {}
    if name in nodes:
        return list(nodes[name])
    owner = {'shot_in': 'shotblast', 'deb_in': 'deburr', 'ins_in': 'inspection', 'raw': 'shotblast', 'cnc_in': 'cnc', 'fg': 'inspection'}.get(name)
    st = next((s for s in plant.stations.values() if s.kind == owner), None)
    if st:
        x, y = _station_pos(st)
        return [x - st.size[0] / 2 - 2, y]
    return [0.0, 0.0]


def locate(plant, pid):
    p = plant.parts.get(pid)
    if p is None:
        return None
    out = {'id': pid, 'status': p.get('status'), 'where': '', 'station': '', 'pos': None, 'moving': False}
    if p.get('status') in ('SCRAP', 'SHIPPED', 'RAW_STORE'):
        last = (p.get('history') or [{}])[-1]
        st = plant.stations.get(last.get('station', ''))
        out.update(where={'SCRAP': _tr('已报废'), 'SHIPPED': _tr('已发运'), 'RAW_STORE': _tr('已转入毛坯库')}[p['status']], station=last.get('station', ''),
                   pos=_station_pos(st) if st else None)
        return out
    for st in plant.stations.values():
        k = st.kind
        if k in ('cnc', 'deburr', 'inspection') and st.part is p:
            out.update(where=_tr('{name}加工中', name=st.name), station=st.id, pos=_station_pos(st))
            return out
        if k == 'shotblast' and any(x is p for x in st.batch):
            out.update(where=_tr('{name}抛丸中', name=st.name), station=st.id, pos=_station_pos(st))
            return out
        if k == 'cooling':
            cool_s = st.get('Setpoint/CoolMin') * 60
            for m in st.molds:
                if any(x is p for x in m[1]):
                    f = min(1.0, m[2] / cool_s)
                    x0 = st.pos[0] - st.size[0] / 2 + 0.5
                    out.update(where=_tr('{name}冷却中（{v:.0f}%）', name=st.name, v=f * 100), station=st.id, pos=[x0 + f * (st.size[0] - 1), float(st.pos[1])], moving=True)
                    return out
        if k == 'agv':
            for a in st.agvs:
                if any(x is p for x in a['load']):
                    out.update(where=_tr('{id} 运输中', id=a['id']), station=st.id, pos=[a['x'], a['y']], moving=True, agv=a['id'])
                    return out
        if k == 'warehouse':
            if any(x is p for x in st.queue) or any(x is p for x in st.stock):
                out.update(where=_tr('{name}库存', name=st.name), station=st.id, pos=_station_pos(st))
                return out
    g = _generic_locate(plant, p)              # 4.6：2.0 通用块（来料、加工、批处理、检测、返修、输送线、缓存、出口）
    if g:
        out.update(g)
        return out
    for name, b in plant.buffers.items():
        if any(x is p for x in b.items):
            out.update(where=_tr('缓存 {name}', name=name), station=name, pos=buffer_pos(plant, name))
            return out
    out['where'] = _tr('未知')
    return out


def _generic_locate(plant, p):
    """通用块里找这件零件：{where, station, pos, moving}；找不到返回 None。课程里的工厂全是通用块，"跟踪一件"靠这里定位。"""
    for st in plant.stations.values():
        k = getattr(st, 'kind', '')
        name = st.name or st.id
        if any(isinstance(s, dict) and s.get('item') is p for s in getattr(st, 'slots', None) or []):
            return {'where': _tr('{name}加工中', name=name), 'station': st.id, 'pos': _station_pos(st)}
        if k in ('inspect', 'rework') and getattr(st, 'cur', None) is p:
            return {'where': f"{name}{_tr('检测中') if k == 'inspect' else _tr('返修中')}", 'station': st.id, 'pos': _station_pos(st)}
        if k == 'batch' and (any(x is p for x in getattr(st, 'load', None) or []) or any(x is p for x in getattr(st, 'done', None) or [])):
            return {'where': _tr('{name}（本批 {len} 件）', name=name, len=len(st.load)), 'station': st.id, 'pos': _station_pos(st)}
        if k == 'conveyor':
            L = max(1e-6, float(st.cfg.get('length_m', 10) or 10))
            for it, x in getattr(st, 'items', None) or []:
                if it is p:
                    f = min(1.0, max(0.0, x / L))
                    w = float((getattr(st, 'size', None) or [L, 1])[0])
                    return {'where': _tr('{name}上（走了 {v:.0f}%）', name=name, v=f * 100), 'station': st.id, 'moving': True,
                            'pos': [float(st.pos[0]) - w / 2 + f * w, float(st.pos[1])]}
        if k == 'source' and any(x is p for x in getattr(st, 'waiting', None) or []):
            return {'where': _tr('{name}：等下游有空位', name=name), 'station': st.id, 'pos': _station_pos(st)}
    for bid, b in plant.buffers.items():
        st = plant.stations.get(bid)
        if st is not None and any(x is p for x in b.items):
            return {'where': _tr('{v}里排队（{len} 件）', v=st.name or bid, len=len(b.items)), 'station': bid, 'pos': _station_pos(st)}
    if p.get('status') == 'FG':
        last = (p.get('history') or [{}])[-1]
        st = plant.stations.get(last.get('station', ''))
        if st is not None:
            return {'where': _tr('已入库：{v}', v=st.name or st.id), 'station': st.id, 'pos': _station_pos(st)}
    return None


def route(plant):
    """工艺路线：按工序顺序给出各步的位置和名称（铸造段 → 机加段 → 仓储）。"""
    order = ['receiving', 'furnace', 'treatment', 'molding', 'cooling', 'shotblast', 'buf:raw', 'buf:cnc_in', 'cnc', 'deburr', 'inspection', 'buf:fg', 'warehouse']
    names = {'buf:raw': _tr('毛坯暂存'), 'buf:cnc_in': _tr('机加线边库'), 'buf:fg': _tr('成品待入库')}
    steps = []
    for key in order:
        if key.startswith('buf:'):
            b = key[4:]
            if b in plant.buffers:
                steps.append({'name': names[key], 'pos': buffer_pos(plant, b), 'kind': 'buffer', 'ids': [b]})
            continue
        sts = [s for s in plant.stations.values() if s.kind == key]
        if not sts:
            continue
        if key == 'molding':
            m = sts[0]
            trt = next((s for s in plant.stations.values() if s.kind == 'treatment'), None)
            pp = trt.cfg.get('pour_point') if trt else None
            steps.append({'name': _tr('浇注'), 'pos': list(pp) if pp else _station_pos(m), 'kind': key, 'station': m.id, 'ids': [m.id]})
            continue
        if key == 'cooling':
            c = sts[0]
            steps.append({'name': _tr('冷却线入口'), 'pos': [c.pos[0] - c.size[0] / 2, c.pos[1]], 'kind': key, 'station': c.id, 'ids': [c.id]})
            steps.append({'name': _tr('落砂'), 'pos': [c.pos[0] + c.size[0] / 2, c.pos[1]], 'kind': key, 'station': c.id, 'ids': []})
            continue
        xs = [s.pos[0] for s in sts]
        ys = [s.pos[1] for s in sts]
        label = {'furnace': _tr('熔炼'), 'treatment': _tr('球化孕育'), 'shotblast': _tr('抛丸清理'), 'cnc': _tr('CNC 机加'), 'deburr': _tr('去毛刺'), 'inspection': _tr('内窥检测'),
                 'warehouse': _tr('入库'), 'receiving': _tr('来料收货')}.get(key, key)
        steps.append({'name': label, 'pos': [sum(xs) / len(xs), sum(ys) / len(ys)], 'kind': key, 'station': sts[0].id, 'ids': [s.id for s in sts]})
    return steps


def suggest(plant):
    """挑一件刚浇注、后面路程最长的铸件来跟踪。"""
    for p in reversed(list(plant.parts.values())):
        if p.get('status') == 'WIP' and len(p.get('history', [])) <= 1 and not p.get('defects'):
            return p['id']
    for p in reversed(list(plant.parts.values())):
        if p.get('status') == 'WIP':
            return p['id']
    return None
