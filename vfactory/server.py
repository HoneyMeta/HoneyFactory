"""实时服务：多工厂 × (仿真循环 + OPC UA + Modbus + MQTT) + HTTP/WebSocket + 三维界面。

工厂配置放在 plants/*.yaml（文件名即工厂编号），模板在 templates/*.yaml。
"""
from .i18n import _tr
from . import i18n
import asyncio
import contextvars
import copy
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time

import uvicorn
import yaml
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import store, tracking
from .comm import Recorder
from .core import Plant
from .scenario import Runner

log = logging.getLogger('vfactory')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web', 'dist')
from . import paths  # noqa: E402
PLANTS = paths.PLANTS                     # 可写（VF_HOME 可挪走）；WEB / TEMPLATES 是程序目录里的只读资源
TEMPLATES = os.path.join(ROOT, 'templates')
TEMPLATE_NAMES = {'showcase': '某转向器壳体铸造厂（完整示范）', 'integrated': '铸造 + 机加一体', 'foundry': '铸造厂', 'machining': '机加工厂', 'blank': '空白工厂（在建模编辑器里从零搭）'}


def _cell_templates():
    """控制单元演示模板 templates/cells/*.yaml（模板键 cells/<文件名>，名称取工厂名）。"""
    d = os.path.join(TEMPLATES, 'cells')
    out = {}
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith('.yaml'):
            try:
                with open(os.path.join(d, f), encoding='utf-8') as fh:
                    out['cells/' + f[:-5]] = (yaml.safe_load(fh) or {}).get('plant', {}).get('name') or f[:-5]
            except Exception:
                continue
    return out


TEMPLATE_NAMES.update(_cell_templates())
TEMPLATE_DESC = {'showcase': '熔炼 → 造型浇注 → 清理 → 机加 → 检测 → 分拣控制单元（PLC + HMI）→ 立库，含 AGV 和班组，最完整的示范',
                 'integrated': '熔炼 → 造型浇注 → 清理 → 机加 → 检测 → 立库，含 AGV 和班组（不含控制单元，仿真更快）',
                 'foundry': '熔炼、造型、冷却落砂、抛丸清理的铸造车间', 'machining': '毛坯库 → 加工中心 → 去毛刺 → 检测的机加车间',
                 'blank': '只有厂房，从资源库拖设备自己搭'}
_tpl_infos: dict = {}


def template_info():
    """新建工厂对话框用：每个模板的名称、说明、设备数、分组（整厂 / 控制单元演示）。每种语言读一次缓存。"""
    lg = i18n.lang()
    if lg not in _tpl_infos:
        from .sketch import plan_sketch
        _tpl_info = _tpl_infos[lg] = {}
        for k, name in TEMPLATE_NAMES.items():
            n, desc, sk = 0, i18n.label(TEMPLATE_DESC.get(k, '')), None
            name = i18n.label(name)
            try:
                c = read_plant(os.path.join(TEMPLATES, f'{k}.yaml'), lg)
                n = len(c.get('blocks') or c.get('stations') or [])
                desc = desc or (c.get('plant') or {}).get('desc') or ''
                sk = plan_sketch(c)                  # 开始页"新建"卡片上的布局预览
            except Exception:
                pass
            grp = _tr('控制单元演示（PLC 实训）') if k.startswith('cells/') else _tr('整厂')
            _tpl_info[k] = {'name': name, 'desc': desc or (_tr('控制单元：传感器、执行器和 PLC 程序') if k.startswith('cells/') else ''), 'blocks': n, 'group': grp, 'sketch': sk}
    return _tpl_infos[lg]

# 编辑模式里可以新增的设备类型：编号前缀、名称、默认尺寸和参数
CATALOG = {
    'induction_furnace': ('FUR', '中频炉', [4, 4], {'capacity_kg': 3000, 'power_kw': 2000, 'mtbf_h': 300, 'mttr_min': 45}),
    'treatment': ('TRT', '球化孕育站', [4, 3], {'ladles': 2, 'ladle_kg': 520, 'mtbf_h': 500, 'mttr_min': 20}),
    'sand_system': ('SAND', '砂处理系统', [10, 6], {'mtbf_h': 200, 'mttr_min': 30}),
    'molding_line': ('MOLD', '造型线', [26, 4], {'cycle_s': 40, 'castings_per_mold': 2, 'pour_kg': 45, 'mtbf_h': 80, 'mttr_min': 25}),
    'cooling_line': ('COOL', '冷却输送线', [32, 3], {'cool_min': 45, 'capacity_molds': 80}),
    'shot_blast': ('SHOT', '抛丸机', [6, 6], {'mtbf_h': 150, 'mttr_min': 30, 'batch': 24}),
    'receiving': ('RCV', '毛坯来料', [6, 6], {'pcs_per_hour': 34, 'porosity_pct': 3.0}),
    'cnc': ('CNC', '加工中心', [4, 3.4], {'mtbf_h': 120, 'mttr_min': 40, 'group': 'CNC'}),
    'deburr_cell': ('DEB', '机器人去毛刺单元', [5, 5], {'mtbf_h': 200, 'mttr_min': 20}),
    'inspection': ('INS', '自动内窥检测站', [4, 4], {'mtbf_h': 300, 'mttr_min': 20}),
    'warehouse': ('ASRS', '立体仓库', [12, 18], {'slots': 600, 'ship_every_h': 4}),
}
EDITABLE = {'name': '名称', 'capacity_kg': '容量 kg', 'power_kw': '额定功率 kW', 'cycle_s': '节拍 s', 'castings_per_mold': '每型件数', 'pour_kg': '每型浇注重量 kg',
            'cool_min': '冷却时间 min', 'capacity_molds': '冷却线容量（型）', 'batch': '抛丸批量', 'ladles': '浇包数', 'ladle_kg': '浇包容量 kg',
            'mtbf_h': '平均故障间隔 h', 'mttr_min': '平均修复时间 min', 'slots': '库位数', 'ship_every_h': '发运间隔 h', 'pcs_per_hour': '到货节拍 件/h',
            'porosity_pct': '来料气孔率 %', 'count': 'AGV 台数', 'speed': 'AGV 速度 m/s'}


def read_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


AREA_KINDS = {'熔炼区': 'melting', '造型区': 'molding', '清理区': 'cleaning', '机加区': 'machining', '检测区': 'inspection', '仓储区': 'warehouse',
              '收货区': 'receiving'}


def area_kind(name):
    """Area code from its display name (Chinese or English), for logic that must not depend on the language."""
    for zh, k in AREA_KINDS.items():
        if name in (zh, i18n.en_text(zh)):
            return k
    return ''


def read_plant(path, language=None):
    """A plant / template model with its display texts (names, descriptions, areas) in `language` (default: the server language
    VF_LANG; the running simulation has one language). Texts come from the content map next to the file (<dir>/i18n/<name>.en.json)
    or, for plants copied from a template earlier, from the merged content maps. Read-modify-write code keeps using read_yaml."""
    return i18n.content(read_yaml(path), path, language or i18n.default_lang())


class _Dumper(yaml.SafeDumper):
    pass


def _scalar(v):
    return not isinstance(v, (dict, list))


def _rep_list(d, data):
    # 数字/字符串短列表写成 [a, b]，和手写配置一个风格
    return d.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=all(_scalar(x) for x in data))


def _rep_dict(d, data):
    # 只含标量和短列表的字典（一台设备、一个区域）写成一行
    flat = all(_scalar(v) or isinstance(v, list) and all(_scalar(x) for x in v) for v in data.values())
    return d.represent_mapping('tag:yaml.org,2002:map', data.items(), flow_style=flat and len(data) > 1)


_Dumper.add_representer(list, _rep_list)
_Dumper.add_representer(dict, _rep_dict)


def _dump(x):
    return yaml.dump(x, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=400).rstrip()


def write_yaml(path, data):
    out = []
    for k, v in data.items():
        if isinstance(v, dict):                  # plant / buffers 段逐行写，便于手改
            out.append(f'{k}:')
            out += ['  ' + _dump({kk: vv}).replace('\n', '\n  ') for kk, vv in v.items()]
        else:
            out.append(_dump({k: v}))
        out.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))


SANDBOXES = paths.data('sandboxes')
MB_TABLE_EN = {'coil': 'coil', 'hr': 'holding_register'}


def _endpoints(rt):
    from . import comm as _comm
    return _comm.endpoints(rt)


def _mb_text(port, m):
    """点表里 Modbus 一栏的中文说明（CSV/XLSX 和旧版 /points 用）。"""
    s = _tr('端口 {port} Unit {unit_id} {table} {address}', port=port, unit_id=m['unit_id'], table=m['table'], address=m['address'])
    if m.get('kind') == 'hr' and m.get('datatype') and m['datatype'] != 'int16':
        s += f" {m['datatype']}" + (f" {m['order']}" if m.get('order') else '')
    if isinstance(m.get('scale'), (int, float)) and m['scale'] not in (0, 1):
        s += f" ÷{m['scale']}"
    return s


def _mb_struct(port, m):
    return {'port': port, 'unit': m['unit_id'], 'table': MB_TABLE_EN.get(m.get('kind'), m.get('kind')), 'address': m['address'],
            'count': m.get('count', 1), 'type': m.get('datatype'), 'order': m.get('order'),
            'scale': m['scale'] if isinstance(m.get('scale'), (int, float)) else None, 'writable': bool(m.get('writable')),
            'mirror': {'coil': 'discrete_input', 'hr': 'input_register'}.get(m.get('kind'))}


class _NoOpcUa:
    """沙箱模式下的协议占位：不发布端口，点表/信号接口照常可用（地址为空）。"""
    top = None

    def points(self):
        return {}


class _NoModbus:
    port = None
    server = None

    def points(self):
        return []

    def rebuild(self):
        pass


class PlantRuntime:
    def __init__(self, mgr, pid, sandbox=False, path=None):
        self.mgr, self.pid = mgr, pid
        self.sandbox = sandbox                   # 学生沙箱（vfactory/teach）：独立实例、不挂 OPC UA/Modbus/MQTT，空闲休眠
        self.path = path or os.path.join(SANDBOXES if sandbox else PLANTS, f'{pid}.yaml')
        self.clients: set[WebSocket] = set()
        self.tasks = []
        self.dirty = False
        self.hibernating = False
        self.last_access = time.time()
        self.noproto = False                     # 桌面模式关了协议服务：普通工厂也不挂 OPC UA/Modbus/MQTT

    async def start(self):
        self.cfg = read_plant(self.path)
        if 'blocks' not in self.cfg:               # 旧版配置：内存里转成 2.0，下次保存时写成新格式
            from .flow.model import to_v2
            self.cfg = to_v2(self.cfg)
        # 预热后的工厂按"模型内容"缓存在内存里：重置时模型没变就直接复制一份（结果和重新预热完全一样，但不用再跑几秒）
        # Modbus 端口不影响仿真：换端口（打开协议、本机 MES）时也用得上预热缓存
        kcfg = {**self.cfg, 'plant': {k: v for k, v in (self.cfg.get('plant') or {}).items() if k not in ('modbus_port', 'raw_site')}}   # 原始现场模式只影响协议层
        key = hashlib.sha1(json.dumps(kcfg, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        use_warm = not self.sandbox or getattr(self.mgr, 'warm_sandbox', False)   # 命令行测试（无协议）也用预热缓存
        cached = self.mgr.warm.get(self.pid) if use_warm else None
        wh = float(self.cfg['plant'].get('warmup_h', 0))
        if cached and cached[0] == key:
            self.plant = copy.deepcopy(cached[1])
            self.plant.cfg.setdefault('plant', {})['raw_site'] = bool((self.cfg.get('plant') or {}).get('raw_site'))
        else:
            self.plant = Plant(self.cfg)
            if wh > 0:
                self.plant.run_for(wh * 3600)
                self.plant.log('PLANT', 'info', _tr('已预热 {wh:g} 小时，进入稳态', wh=wh))
            try:
                if use_warm:
                    self.mgr.warm[self.pid] = (key, copy.deepcopy(self.plant))
            except Exception:
                log.warning(_tr('预热状态无法缓存，重置时会重新预热'), exc_info=True)
        from . import comm as _comm
        _comm.load_settings(self)                 # 协议设置（对外时间、宽松类型、越界写入、Modbus 地址分配）
        from . import netmodel
        netmodel.attach(self)                     # 4.3 通讯层：网关 / 交换机 / MES、网络线（协议地址按网关组织，见 netmodel.py）
        self.scenario = Runner(self)
        self.rec = Recorder(self)
        self.plant.step_hooks.append(self._comm_tick)
        from .runctl import Ctl
        self.ctl = Ctl(self)
        from .protocols.modbus import ModbusAdapter
        from .protocols.mqtt import MqttAdapter
        self.mqtt = None
        wp = getattr(self.mgr, 'wants_proto', None)   # 桌面模式可以按工厂打开协议（本机的蜂元教学 MES 用，见 vfactory/mes）
        self.noproto = (not wp(self.pid, self.sandbox)) if wp else (self.sandbox or not getattr(self.mgr, 'protocols', True))
        if self.noproto:
            self.opcua, self.modbus = _NoOpcUa(), _NoModbus()
        else:
            self.opcua = await self.mgr.opcua.attach(self.pid, self.plant)
            self.modbus = ModbusAdapter(self.plant, self.cfg['plant']['modbus_port'])
            await self.modbus.start()
            if self.mgr.mqtt:
                try:
                    self.mqtt = MqttAdapter(self.pid, self.plant, self.mgr.args.mqtt)
                    await self.mqtt.start()
                except Exception:
                    log.exception(_tr('MQTT 未启动'))
                    self.mqtt = None
        self._loop = asyncio.get_running_loop()
        self.hibernating = False
        # the simulation runs in the server language (VF_LANG), not in the language of the request that started it
        self.tasks = [asyncio.create_task(self.sim_loop(), context=contextvars.Context()), asyncio.create_task(self.ws_loop(), context=contextvars.Context())]
        self.dirty = False
        log.info(_tr('工厂 %s（%s）已启动，%s'), self.pid, self.plant.name, _tr('沙箱（无协议端口）') if self.sandbox else _tr('协议服务未开') if self.noproto
                 else f"Modbus :{self.cfg['plant']['modbus_port']}")

    async def stop(self):
        self.rec.stop()
        self.rec.stop_replay()
        for t in self.tasks:
            t.cancel()
        # 断开网页的实时连接：页面会在 1.5 秒后重连，连到重建后的新工厂（否则停在旧的上面，看起来像卡住）
        for ws in list(getattr(self, 'clients', [])):
            try:
                await ws.close(code=1012)
            except Exception:
                pass
        if getattr(self, 'clients', None) is not None:
            self.clients.clear()
        if self.noproto:
            return
        await self.mgr.opcua.detach(self.pid)
        await self.modbus.stop()
        if self.mqtt:
            await self.mqtt.stop()

    # ---------- 沙箱休眠：停掉仿真循环，下次访问时恢复 ----------
    @property
    def asleep(self):                            # 控制层实时泵按这个名字跳过休眠的沙箱
        return self.hibernating

    def hibernate(self):
        if self.hibernating or not self.tasks:
            return
        self.hibernating = True
        self.tasks[0].cancel()

    def touch(self):
        self.last_access = time.time()
        if not self.hibernating:
            return

        def wake():
            if self.hibernating:
                self.hibernating = False
                self.tasks[0] = asyncio.create_task(self.sim_loop(), context=contextvars.Context())
        try:
            asyncio.get_running_loop()
            wake()
        except RuntimeError:                      # 从工作线程访问：交给事件循环去唤醒
            self._loop.call_soon_threadsafe(wake)

    async def sim_loop(self):
        p = self.plant
        acc, last = 0.0, time.perf_counter()
        behind = False
        while True:
            await asyncio.sleep(0.01 if behind else 0.05)     # 跟不上设定速度时少睡一点（4.3：高倍速）
            now = time.perf_counter()
            el, last = now - last, now
            if p.paused:
                continue
            acc += el * p.speed
            n, t0 = 0, time.perf_counter()
            while acc >= p.dt and n < 4000 and not p.paused:      # 断点命中会把 paused 置真
                p.step()
                acc -= p.dt
                n += 1
                if time.perf_counter() - t0 > 0.03:
                    acc = min(acc, p.dt * 50)
                    break
            behind = acc >= p.dt and not p.paused

    async def ws_loop(self):
        while True:
            await asyncio.sleep(0.25)
            if not self.clients:
                continue
            data = self.plant.snapshot()
            data['ctl'] = self.ctl.status()
            msg = json.dumps({'type': 'state', 'data': data}, ensure_ascii=False, default=str)
            for ws in list(self.clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    self.clients.discard(ws)

    # ---------- 通讯故障 ----------
    def comm_set(self, proto, mode, latency=5.0, minutes=0.0, station=None, tag=None, **params):
        """通讯故障：协议 × 设备 × 点位（规则引擎在 vfactory/comm.py）。mode 为空 = 恢复。参数不对抛 ValueError。"""
        from . import comm as _comm
        return _comm.set_fault(self, proto, mode, latency=latency, minutes=minutes, station=station, tag=tag, **params)

    def _comm_tick(self):
        if int(self.plant.t) % 5:
            return
        from . import comm as _comm
        _comm.tick(self)

    # ---------- 查询 ----------
    def meta(self):
        p, c = self.plant, self.cfg
        return {'id': self.pid, 'name': p.name, 'product': c['plant'].get('product', ''), 'floor': c['plant'].get('floor', [150, 56]),
                'areas': [{**a, 'kind': area_kind(a.get('name'))} if isinstance(a, dict) else a for a in c.get('areas', [])], 'buffers': {k: b.capacity for k, b in p.buffers.items()}, 'dirty': self.dirty,
                'stations': [{'id': s.id, 'name': s.name, 'kind': s.kind, 'type': s.cfg['type'], 'area': s.area, 'pos': s.pos, 'size': s.size,
                              'rot': s.rot, 'group': s.group,
                              'cfg': {k: v for k, v in s.cfg.items() if k in ('nodes', 'pour_point', 'corridor_y', 'roles')}}
                             for s in p.stations.values()],
                'route': tracking.route(p),
                'endpoints': _endpoints(self),
                'catalog': {k: {'prefix': v[0], 'name': v[1]} for k, v in CATALOG.items()}, 'editable': EDITABLE}

    def points(self):
        rows = []
        opc = self.opcua.points()
        mq = self.mqtt.points() if self.mqtt else {}
        mb = {(r['station'], r['tag']): r for r in self.modbus.points()}
        for st in list(self.plant.stations.values()):
            for t, tag in st.tags.items():
                m = mb.get((st.id, t))
                rows.append({'工位': f'{st.id} {st.name}', '点位': t, '说明': tag.desc, '单位': tag.unit, '类型': tag.dtype, '可写': _tr('是') if tag.writable else '',
                             'OPC UA NodeId': opc.get(f'{st.id}/{t}', ''), 'MQTT 主题': mq.get(f'{st.id}/{t}', ''),
                             'Modbus': _mb_text(self.modbus.port, m) if m else ''})
        for r in self.modbus.points():
            if r['station'] in i18n.variants('电能表'):
                rows.append({'工位': _tr('全厂电能表'), '点位': r['tag'], '说明': r['desc'], '单位': '', '类型': 'float32', '可写': '', 'OPC UA NodeId': '',
                             'MQTT 主题': '', 'Modbus': _tr('端口 {port} Unit {unit_id} {table} {address}', port=self.modbus.port, unit_id=r['unit_id'], table=r['table'], address=r['address'])})
        return rows

    def points_v2(self):
        """点表（英文键、结构化字段，给程序用）：GET /api/p/{pid}/points/v2。"""
        opc = self.opcua.points()
        mq = self.mqtt.points() if self.mqtt else {}
        mb = {(r['station'], r['tag']): r for r in self.modbus.points()}
        net = getattr(self.plant, 'net', None)
        gws = {sid: net.gateways_of(sid) for sid in self.plant.stations} if net is not None and net.gateways else {}
        gopc = self.opcua.gw_points() if hasattr(self.opcua, 'gw_points') else {}
        out = []
        for st in list(self.plant.stations.values()):
            for t, tag in st.tags.items():
                m = mb.get((st.id, t))
                topic = mq.get(f'{st.id}/{t}') or None
                row = {'station': st.id, 'station_name': st.name, 'area': st.area, 'tag': t, 'key': f'{st.id}/{t}', 'description': tag.desc,
                       'unit': tag.unit, 'datatype': tag.dtype, 'writable': bool(tag.writable), 'low': tag.lo, 'high': tag.hi,
                       'opcua_nodeid': opc.get(f'{st.id}/{t}') or None, 'mqtt_topic': topic,
                       'mqtt_set_topic': topic + '/set' if topic and tag.writable else None,
                       'modbus': _mb_struct(self.modbus.port, m) if m else None}
                if gws.get(st.id):                # 4.3：经哪些网关上报；主网关排第一，旧地址是它的别名
                    row['gateway'] = gws[st.id][0]
                    row['via'] = [{'gateway': g, 'opcua_nodeid': gopc.get((g, f'{st.id}/{t}')),
                                   'mqtt_topic': f'vfactory/{self.pid}/{g}/{st.id}/{t}' if self.mqtt and 'mqtt' in net.north(g) else None}
                                  for g in gws[st.id]]
                out.append(row)
        for r in self.modbus.points():
            if r['station'] in i18n.variants('电能表'):
                out.append({'station': '_meter', 'station_name': _tr('全厂电能表'), 'area': '', 'tag': r['tag'], 'key': f"_meter/{r['tag']}", 'description': r['desc'],
                            'unit': 'kW,kWh', 'datatype': 'float32', 'writable': False, 'low': None, 'high': None, 'opcua_nodeid': None, 'mqtt_topic': None,
                            'mqtt_set_topic': None, 'modbus': _mb_struct(self.modbus.port, r)})
        return out

    # ---------- 编辑 ----------
    def station(self, sid):
        st = self.plant.stations.get(sid)
        if not st:
            raise HTTPException(404, _tr('没有设备 {sid}', sid=sid))
        return st

    def new_id(self, prefix):
        n = 1
        while f'{prefix}{n}' in self.plant.stations:
            n += 1
        return f'{prefix}{n}'

    def _join_crew(self, new_id, like_ids):
        crew = next((s for s in self.plant.stations.values() if s.kind == 'crew'), None)
        if not crew:
            return
        for r in crew.cfg.get('roles', []):
            if any(x in r['stations'] for x in like_ids) and new_id not in r['stations']:
                r['stations'].append(new_id)
        for w in crew.workers:
            if any(x in w['stations'] for x in like_ids) and new_id not in w['stations']:
                w['stations'].append(new_id)

    def add_station(self, typ, pos=None, template=None):
        p = self.plant
        if template:
            src = self.station(template)
            typ = src.cfg['type']
        if typ not in CATALOG:
            raise HTTPException(400, _tr('这类设备不能新增（班组和 AGV 车队每个工厂只有一个，请改它的属性）'))
        prefix, base, size, extra = CATALOG[typ]
        cfg = copy.deepcopy(src.cfg) if template else {'type': typ, 'size': list(size), **copy.deepcopy(extra)}
        if pos:
            cfg['pos'] = [round(float(pos[0]), 2), round(float(pos[1]), 2)]
        elif template:
            cfg['pos'] = [src.pos[0], src.pos[1] + src.size[1] + 3]
        else:
            cfg['pos'] = [10, 10]
        if typ == 'treatment':
            cfg['pour_point'] = [cfg['pos'][0] + 12, cfg['pos'][1] - 5]
        if typ in ('induction_furnace', 'sand_system', 'shot_blast'):
            used = {s.cfg.get('modbus_unit') for s in p.stations.values()}
            cfg['modbus_unit'] = next(u for u in range(1, 250) if u not in used and u != 10)
        cfg['id'] = self.new_id(prefix)
        cfg['name'] = f"{cfg['id'][len(prefix):]}#{base}"
        try:
            st = p.add_station(cfg)
        except ValueError as e:
            raise HTTPException(400, str(e))
        self._join_crew(st.id, [s.id for s in p.stations.values() if s.cfg['type'] == typ and s.id != st.id])
        self.modbus.rebuild()
        self.dirty = True
        return st

    def patch_station(self, sid, body):
        st = self.station(sid)
        restart = False
        for k in ('pos', 'size'):
            if k in body:
                v = [round(float(x), 2) for x in body[k]]
                setattr(st, k, v)
                st.cfg[k] = v
        if 'rot' in body:
            st.rot = st.cfg['rot'] = round(float(body['rot']), 1)
        if 'name' in body:
            st.name = st.cfg['name'] = str(body['name'])[:40]
        for k, v in (body.get('cfg') or {}).items():
            if k not in EDITABLE or k == 'name':
                continue
            try:
                v = float(v) if '.' in str(v) else int(v)
            except ValueError:
                raise HTTPException(400, _tr('{v} 需要数字', v=EDITABLE[k]))
            st.cfg[k] = v
            if k == 'mtbf_h':
                st.failure.mtbf_h = v
            elif k == 'mttr_min':
                st.failure.mttr_min = v
            else:
                restart = True
        if 'nodes' in body and st.kind == 'agv':
            st.nodes.update({k: [float(a), float(b)] for k, (a, b) in body['nodes'].items()})
            st.cfg['nodes'] = st.nodes
        if 'roles' in body and st.kind == 'crew':
            st.cfg['roles'] = body['roles']
            restart = True
        self.dirty = True
        return restart

    def remove_station(self, sid):
        err = self.plant.remove_station_any(sid)
        if err:
            raise HTTPException(400, err)
        crew = next((s for s in self.plant.stations.values() if s.kind == 'crew'), None)
        if crew:
            for r in crew.cfg.get('roles', []):
                if sid in r['stations']:
                    r['stations'].remove(sid)
            for w in crew.workers:
                if sid in w['stations']:
                    w['stations'].remove(sid)
                if w['serving'] == sid:
                    w['serving'] = None
        self.modbus.rebuild()
        self.dirty = True

    def patch_plant(self, body):
        c = self.cfg
        if 'name' in body:
            c['plant']['name'] = self.plant.name = str(body['name'])[:40]
        if 'product' in body:
            c['plant']['product'] = str(body['product'])[:60]
        if 'areas' in body:
            c['areas'] = body['areas']
        if 'buffers' in body:
            for k, v in body['buffers'].items():
                if k in self.plant.buffers:
                    self.plant.buffers[k].capacity = int(v)
        self.dirty = True

    def save(self):
        c = self.build_cfg()
        if os.path.exists(self.path):
            shutil.copy(self.path, self.path + '.bak')
        write_yaml(self.path, c)
        self.cfg = c
        self.dirty = False

    def build_cfg(self):
        """当前运行中的工厂（含运行时的修改）→ 2.0 项目模型。"""
        c = copy.deepcopy(self.cfg)
        if 'blocks' in c:                       # 4.3：旧控制单元的内置 PLC 和运行中的工厂一样拆成 PLC 块
            from .plc.migrate import migrate_model
            migrate_model(c)
        c['plan'] = self.plant.plan.export()
        c['plant']['name'] = self.plant.name
        blocks = {b['id']: b for b in c.get('blocks', [])}
        links = c.get('links', [])
        skip = ('id', 'type', 'name', 'pos', 'size', 'rot', 'area', 'ports', '_in', '_out', '_routes', 'signals', 'bindings')
        out = []
        for st in self.plant.stations.values():
            b = blocks.get(st.id)
            if b is None:                       # 运行时通过旧接口新增的设备：参照同类设备补连线
                b = {'id': st.id, 'type': st.cfg['type'], 'name': st.name, 'params': {k: copy.deepcopy(v) for k, v in st.cfg.items() if k not in skip}}
                sib = next((x for x in c.get('blocks', []) if x['type'] == b['type']), None)
                if sib:
                    b['node'] = [sib.get('node', [0, 0])[0], sib.get('node', [0, 0])[1] + 120]
                    for l in [l for l in links if sib['id'] in (l['from'], l['to'])]:
                        l2 = copy.deepcopy(l)
                        l2['id'] = f"L{st.id}{len(links)}"
                        l2['from'] = st.id if l['from'] == sib['id'] else l['from']
                        l2['to'] = st.id if l['to'] == sib['id'] else l['to']
                        links.append(l2)
            b['name'], b['pos'], b['size'] = st.name, list(st.pos), list(st.size)
            if st.rot:
                b['rot'] = st.rot
            params = b.setdefault('params', {})
            for k in list(params):
                if k in st.cfg and k not in skip:
                    params[k] = copy.deepcopy(st.cfg[k])
            if st.kind == 'agv':
                params['nodes'] = {k: list(v) for k, v in st.nodes.items()}
            if st.kind == 'buffer' and st.id in self.plant.buffers:
                params['capacity'] = self.plant.buffers[st.id].capacity
            out.append(b)
        gone = set(blocks) - set(self.plant.stations)
        c['blocks'] = out
        c['links'] = [l for l in links if l['from'] not in gone and l['to'] not in gone and l.get('via') not in gone]
        return c


def _port_free(port):
    """这个 TCP 端口现在能不能独占绑定（不带 SO_REUSEADDR）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('0.0.0.0', int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Manager:
    def __init__(self, args):
        self.args = args
        self.rts: dict[str, PlantRuntime] = {}
        self.mqtt = None
        self.warm: dict[str, tuple] = {}          # 工厂 → (模型摘要, 预热后的工厂副本)
        self.sandboxes: dict[str, PlantRuntime] = {}   # 学生沙箱（vfactory/teach 管理），不出现在工厂列表里
        self.protocols = True                    # 桌面模式可以关掉 OPC UA / Modbus / MQTT（见 vfactory/desktop.py）
        self.seed_showcase = True                # 没有工厂时复制完整示范（桌面学生版不需要）
        self.desktop = None                      # 桌面模式：vfactory.desktop.Desktop
        self.opcua = None
        self.proto_pids: set[str] = set()        # 桌面模式：协议总开关关着时也挂协议的工厂/沙箱（本机的蜂元教学 MES，vfactory/mes/sidecar.py）

    def wants_proto(self, pid, sandbox=False):
        """这个工厂挂不挂 OPC UA / Modbus / MQTT：总开关开着的普通工厂，或按工厂打开的（proto_pids，沙箱也可以）。"""
        return pid in self.proto_pids or (not sandbox and self.protocols)

    async def ensure_hubs(self):
        """OPC UA / MQTT 服务没开时开起来。桌面模式下默认端口被占（比如同一台机器上的服务器版）就换一个空闲端口，
        不能退回去连别人的 Broker。"""
        from .protocols.mqtt import MqttHub
        from .protocols.opcua import OpcUaHub
        if self.desktop:
            from .desktop import free_port
            if self.opcua is None and not _port_free(self.args.opcua):
                self.args.opcua = free_port()
            if self.mqtt is None and not _port_free(self.args.mqtt):
                self.args.mqtt = free_port()
        if self.opcua is None:
            self.opcua = OpcUaHub(self.args.opcua)
            await self.opcua.start()
        if self.mqtt is None and not self.args.no_mqtt:
            self.mqtt = MqttHub(self.args.mqtt)
            await self.mqtt.start()

    async def enable_proto(self, pid):
        """按工厂打开协议（总开关不动，别的工厂不受影响）：开协议服务、分配 Modbus 端口、重建这个工厂（仿真从头运行）。
        返回 {'mqtt', 'opcua', 'modbus'} 端口。"""
        rt = self.get(pid)
        if rt.noproto:
            self.proto_pids.add(pid)
            try:
                await self.ensure_hubs()
                self._ensure_port(pid, rt.path)
                await self.restart(pid)
            except Exception:
                self.proto_pids.discard(pid)
                raise
            rt = self.get(pid)
        return {'mqtt': self.args.mqtt if rt.mqtt else None, 'opcua': self.args.opcua, 'modbus': rt.cfg['plant'].get('modbus_port')}

    async def start(self):
        from .protocols.mqtt import MqttHub
        from .protocols.opcua import OpcUaHub
        os.makedirs(PLANTS, exist_ok=True)
        from . import tenancy
        if tenancy.saas() and not self.desktop:  # 5.0 SaaS：服务器不跑工厂，也不开 OPC UA / Modbus / MQTT（工厂都在客户端本机）
            self.protocols, self.seed_showcase = False, False
            log.info(_tr('SaaS 模式：不启动工厂和协议服务'))
            return
        if self.protocols:
            self.opcua = OpcUaHub(self.args.opcua)
            await self.opcua.start()
            if not self.args.no_mqtt:
                self.mqtt = MqttHub(self.args.mqtt)
                await self.mqtt.start()
        files = sorted(f[:-5] for f in os.listdir(PLANTS) if f.endswith('.yaml'))
        if not files and self.seed_showcase:
            src = os.path.join(TEMPLATES, 'showcase.yaml')                          # 完整示范（含分拣控制单元）
            if i18n.default_lang() == 'en':                                         # display texts in the server language
                write_yaml(os.path.join(PLANTS, 'foundry-housing.yaml'), read_plant(src))
            else:
                shutil.copy(src, os.path.join(PLANTS, 'foundry-housing.yaml'))
            files = ['foundry-housing']
        for pid in files:
            await self.launch(pid)

    async def set_protocols(self, on):
        """桌面模式：在运行中打开/关闭协议服务（OPC UA / Modbus / MQTT）。所有工厂按新设置重建（仿真从头运行）。失败抛 RuntimeError。"""
        on = bool(on)
        if on == self.protocols:
            return
        olds = list(self.rts.items())
        for _pid, rt in olds:
            await rt.stop()
        err = None
        if on:
            from .protocols.mqtt import MqttHub
            from .protocols.opcua import OpcUaHub
            try:
                if self.opcua is None:                # 按工厂打开协议时已经开着（proto_pids）
                    self.opcua = OpcUaHub(self.args.opcua)
                    await self.opcua.start()
                if self.mqtt is None and not self.args.no_mqtt:
                    self.mqtt = MqttHub(self.args.mqtt)
                    await self.mqtt.start()
                self.protocols = True
            except Exception as e:                # 端口被占用等
                log.exception(_tr('协议服务启动失败'))
                err = _tr('协议服务启动失败：{e}', e=e)
                await self._stop_hubs()
        else:
            if not self.proto_pids:
                await self._stop_hubs()
            self.protocols = False
        for pid, rt in olds:
            nrt = PlantRuntime(self, pid, path=rt.path)
            if self.wants_proto(pid):
                self._ensure_port(pid)
            await nrt.start()
            nrt.clients = rt.clients
            nrt.ctl.bps = rt.ctl.bps
            self.rts[pid] = nrt
        if err:
            raise RuntimeError(err)

    async def _stop_hubs(self):
        for stop in (lambda: self.opcua.server.stop(), lambda: self.mqtt.broker.shutdown()):
            try:
                await asyncio.wait_for(stop(), 5)
            except Exception:
                pass
        self.opcua, self.mqtt = None, None

    def _ensure_port(self, pid, path=None):
        path = path or os.path.join(PLANTS, f'{pid}.yaml')
        c = read_yaml(path)
        used = {rt.cfg['plant'].get('modbus_port') for rt in list(self.rts.values()) + list(self.sandboxes.values()) if rt.pid != pid and getattr(rt, 'cfg', None)}
        port = c['plant'].get('modbus_port')
        # 端口被别的程序占着（比如同一台机器上另一套虚拟工厂）也换一个：Windows 上 pymodbus 能"重复绑定"同一端口，连接会被随机分走
        free = (lambda p: _port_free(p)) if self.wants_proto(pid, os.path.normcase(path).startswith(os.path.normcase(SANDBOXES))) else (lambda p: True)
        if not port or port in used or not free(port):
            port = next(p for p in range(self.args.modbus, self.args.modbus + 200) if p not in used and free(p))
            c['plant']['modbus_port'] = port
            write_yaml(path, c)

    async def launch(self, pid):
        self._ensure_port(pid)
        rt = PlantRuntime(self, pid)
        try:
            await rt.start()
        except Exception:
            log.exception(_tr('工厂 %s 启动失败'), pid)
            return None
        self.rts[pid] = rt
        return rt

    def get(self, pid) -> PlantRuntime:
        rt = self.rts.get(pid) or self.sandboxes.get(pid)
        if not rt:
            raise HTTPException(404, _tr('没有工厂 {pid}', pid=pid))
        if rt.sandbox:
            rt.touch()
        return rt

    def list(self):
        return [{'id': pid, 'name': rt.plant.name, 'product': rt.cfg['plant'].get('product', ''), 'modbus_port': rt.cfg['plant']['modbus_port'],
                 'paused': rt.plant.paused, 'speed': rt.plant.speed,
                 'stations': len(rt.plant.stations), 'time': rt.plant.clock_str(), 'dirty': rt.dirty} for pid, rt in self.rts.items()]

    async def create(self, name, template=None, copy_from=None, want_id=None):
        name = (name or '').strip()[:40] or _tr('新工厂')
        if want_id:   # 用户自己起的编号（网址、OPC UA、MQTT 里都用它）
            pid = str(want_id).strip().lower()
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,39}', pid) or pid.startswith('sb-'):
                raise HTTPException(400, _tr('工厂编号只能用小写字母、数字和短横线，2～40 个字符'))
            if os.path.exists(os.path.join(PLANTS, f'{pid}.yaml')) or pid in self.rts:
                raise HTTPException(400, _tr('编号 {pid} 已经有了', pid=pid))
        else:
            base = copy_from or template or 'integrated'
            pid = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-') or 'plant'
            n = 1
            while os.path.exists(os.path.join(PLANTS, f'{pid}-{n}.yaml')):
                n += 1
            pid = f'{pid}-{n}'
        if copy_from:
            src = self.get(copy_from)
            src.save() if src.dirty else None
            c = read_yaml(src.path)
        else:
            if template not in TEMPLATE_NAMES:
                raise HTTPException(400, _tr('没有这个模板'))
            c = read_plant(os.path.join(TEMPLATES, f'{template}.yaml'), i18n.lang())     # the creator's language
        c['plant']['name'] = name
        c['plant'].pop('modbus_port', None)
        clear_editor_state(pid)
        write_yaml(os.path.join(PLANTS, f'{pid}.yaml'), c)
        rt = await self.launch(pid)
        if not rt:
            raise HTTPException(500, _tr('工厂启动失败，请看服务日志'))
        return pid

    async def delete(self, pid):
        rt = self.get(pid)
        if rt.sandbox:
            raise HTTPException(400, _tr('学生沙箱请在教学模块里重置或删除'))
        if len(self.rts) <= 1:
            raise HTTPException(400, _tr('至少保留一个工厂'))
        await rt.stop()
        del self.rts[pid]
        trash = os.path.join(PLANTS, '.trash')
        os.makedirs(trash, exist_ok=True)
        stamp = int(time.time())
        shutil.move(rt.path, os.path.join(trash, f'{pid}-{stamp}.yaml'))
        clear_editor_state(pid, os.path.join(trash, f'{pid}-{stamp}'))

    async def restart(self, pid):
        rt = self.get(pid)
        clients = rt.clients
        await rt.stop()
        nrt = PlantRuntime(self, pid, sandbox=rt.sandbox, path=rt.path)
        await nrt.start()
        nrt.clients = clients
        nrt.ctl.bps = rt.ctl.bps                 # 断点跟着工厂走
        (self.sandboxes if rt.sandbox else self.rts)[pid] = nrt


def clear_editor_state(pid, keep_to=None):
    """删除或新建同名工厂时，清掉编辑器草稿；版本历史随配置一起挪进回收目录。"""
    from .editor_api import DATA
    d = os.path.join(DATA, 'drafts', f'{pid}.json')
    if os.path.exists(d):
        os.remove(d)
    v = os.path.join(DATA, 'versions', pid)
    if os.path.isdir(v):
        if keep_to:
            shutil.move(v, keep_to + '-versions')
        else:
            shutil.rmtree(v)


def build_app(mgr: Manager) -> FastAPI:
    from . import apidocs
    app = FastAPI(title=_tr('蜂元虚拟工厂 API'), version='1.0.0', description=apidocs.DESCRIPTION, openapi_tags=apidocs.TAGS,
                  docs_url=None, redoc_url=None)        # 接口文档用本地打包的 Swagger UI / ReDoc（内网、离线可用），见 apidocs.py
    OPEN = {'/api/login', '/api/health', '/api/setup/admin'}
    if mgr.desktop:                               # 桌面模式：一次性令牌换会话、启动器接口（只认本机，见 vfactory/desktop.py）
        OPEN |= mgr.desktop.OPEN
    from .client_update import OPEN_PREFIXES      # 客户端自动更新的下载地址（electron-updater 不带登录）
    from .teach import guard as teach_guard      # 教师/学生角色的访问范围（学生只能进自己的沙箱）
    from .teach.myplants import own_context      # 客户端"我的工厂"（学生自己的本机工厂）

    from .tenancy import policy as tenant_policy   # 5.0 单位隔离、SaaS 不跑工厂（vfactory/tenancy/policy.py）

    @app.middleware('http')
    async def auth_mw(request, call_next):
        path = request.url.path
        u = None
        # /api/ops/…：平台运维后台，自己的账号和 Cookie 会话（tenancy/ops.py），不走单位账号的令牌
        if path.startswith('/api/') and path not in OPEN and not path.startswith(OPEN_PREFIXES) and not path.startswith('/api/ops/'):
            tok = request.headers.get('authorization', '').removeprefix('Bearer ').strip() or request.query_params.get('token', '')
            u, why = store.check_token(tok, request.client.host if request.client else '')
            if not u:
                return JSONResponse({'detail': why or _tr('请先登录')}, 401)
            u = tenant_policy.effective(u, mgr)
            tdeny = tenant_policy.check(u, request.method, path, mgr)
            if tdeny:
                return JSONResponse({'detail': tdeny}, 403)
            local_ui = mgr.desktop and path.startswith(('/api/client/', '/api/desktop/', '/api/mes/'))   # 客户端本机的接口（含本机 MES 的转发）：学生账号也要能用
            # 客户端里学生自己的"我的工厂"（4.4）：不受教学角色范围限制
            local_ui = local_ui or own_context(mgr, u, path, request.headers.get('x-vf-plant', ''), request.query_params.get('vfp', ''))
            deny = store.token_deny(u, request.method, path) or (None if local_ui else teach_guard(u, request.method, path))   # 令牌范围 / 限定工厂；教学角色范围
            if deny:
                return JSONResponse({'detail': deny}, 403)
            if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and u['role'] == 'viewer' and path != '/api/me/password':
                return JSONResponse({'detail': _tr('只读账号不能修改')}, 403)
            request.state.user = u
            from . import comm as _comm
            _comm.set_viewer(u.get('role'), request.url.hostname)      # 接入地址：非管理员不暴露网卡和主机名
        resp = await call_next(request)
        if u and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            try:
                store.audit(u['username'] + (_tr('（令牌 {via_token}）', via_token=u['via_token']) if u.get('via_token') else ''), request.method, path, resp.status_code,
                            str(request.url.query or ''), request.client.host if request.client else '')
            except Exception:
                log.exception('audit')
        return resp

    @app.get('/api/health')
    async def health():
        from . import __version__
        from . import tenancy
        d = {'ok': True, 'plants': list(mgr.rts), 'version': __version__, 'desktop': bool(mgr.desktop),
             'deploy': 'desktop' if mgr.desktop else tenancy.mode()}         # 5.0：selfhost / saas（客户端据此决定 AI 助教、进度上报怎么走）
        if mgr.desktop:
            d.update(mgr.desktop.health())        # edition、protocols
        # i18n: server default language, available languages, demo mode, first-run administrator still to be created
        d.update({'lang': i18n.default_lang(), 'langs': list(i18n.LANGS), 'demo': i18n.demo_mode(),
                  'setup_needed': (not mgr.desktop) and store.admin_needed()})
        return d

    @app.get('/api/setup/admin')
    async def setup_admin_info():
        """First run (production): {needed, demo, lang}. needed = no active administrator yet (not in SaaS / the desktop client)."""
        return {'needed': (not mgr.desktop) and store.admin_needed(), 'demo': i18n.demo_mode(), 'lang': i18n.default_lang()}

    @app.post('/api/setup/admin')
    async def setup_admin(request: Request, body: dict = Body(...)):
        """Create the first administrator {username, password (>= 8, not a well-known initial password), name} -> {token, user}
        like /api/login. Only while no active administrator exists (400 otherwise)."""
        if mgr.desktop or not store.admin_needed():
            raise HTTPException(400, _tr('管理员账号已存在'))
        try:
            u = store.create_admin(body.get('username'), body.get('password') or '', (body.get('name') or '').strip()[:40])
        except ValueError as e:
            raise HTTPException(400, str(e))
        ip = request.client.host if request.client else ''
        store.audit(u['username'], 'SETUP', '/api/setup/admin', 200, ip=ip)
        return {'token': store.make_session(u['username'], ip=ip, agent=request.headers.get('user-agent', '')),
                'user': {'username': u['username'], 'name': u['name'], 'role': u['role']}}

    if mgr.desktop:
        mgr.desktop.register(app)
    from . import client_update
    client_update.register(app, mgr)             # 客户端自动更新：/api/client/update/latest.yml + 安装包（data/client-updates/）

    from .api2 import register
    register(app, mgr)
    from . import sim_api
    sim_api.register(app, mgr)
    from . import editor_api, copilot
    editor_api.register(app, mgr)
    from . import runctl
    runctl.register(app, mgr)
    copilot.register(app, mgr)
    from . import assistant
    assistant.register(app, mgr)
    from . import teach
    teach.register(app, mgr)                     # 教学：班级、实训任务、学生沙箱、评分、AI 助教
    from . import report_export
    report_export.register(app, mgr)             # 设计：方案报告 Word/PPT 导出、SOP 漫游
    from . import testing
    testing.register(app, mgr)                   # 联调：测试剧本、报文监视
    from .plc import api as plc_api; plc_api.register(app, mgr)   # PLC：程序、编译下载、在线监视、外接 PLC、HMI
    from .control import api as control_api; control_api.register(app, mgr)   # 控制层：控制单元定义、I/O、强制、面板、故障、统计、场景库
    from . import delivery; delivery.register(app, mgr)   # 5.0 标准交付包（点表 / DXF / GLB / README）、原始现场模式、动作级信号
    from . import tenancy; tenancy.register(app, mgr)     # 5.0 单位、席位、授权、运维后台 /api/ops、单位管理 /api/org、进度上报、AI 代理

    @app.get('/api/plants')
    async def plants(request: Request):
        lst, only = mgr.list(), store.token_plants(getattr(request.state, 'user', None))
        return {'plants': [x for x in lst if x['id'] in only] if only else lst, 'templates': TEMPLATE_NAMES, 'template_info': template_info()}

    @app.post('/api/plants')
    async def create(body: dict = Body(...)):
        pid = await mgr.create(body.get('name'), body.get('template'), body.get('copy_from'), body.get('id'))
        return {'ok': True, 'id': pid}

    @app.delete('/api/plants/{pid}')
    async def delete(pid: str):
        await mgr.delete(pid)
        return {'ok': True}

    @app.get('/api/p/{pid}/meta')
    async def meta(pid: str):
        return mgr.get(pid).meta()

    @app.get('/api/p/{pid}/state')
    async def state(pid: str):
        return mgr.get(pid).plant.snapshot()

    @app.get('/api/p/{pid}/station/{sid}')
    async def station(pid: str, sid: str):
        rt = mgr.get(pid)
        st = rt.station(sid)
        d = st.snapshot(full=True)
        d['history'] = {k: list(st.tags[k].history) for k in st.history_tags() if k in st.tags}
        d['oee'] = rt.plant.oee(st)
        d['cfg'] = {k: v for k, v in st.cfg.items() if k in EDITABLE}
        d['pos'], d['size'], d['rot'], d['type'] = st.pos, st.size, st.rot, st.cfg['type']
        if st.acts is not None:                   # 5.0 动作级信号：模板、当前动作故障
            d['actions'] = {'profile': st.acts.profile, 'cylinders': st.acts.prof['cyls'], 'door': st.acts.prof['door'], 'faults': st.acts.fault_info()}
        return d

    @app.post('/api/p/{pid}/station/{sid}/write')
    async def write(pid: str, sid: str, body: dict = Body(...)):
        err = mgr.get(pid).station(sid).write(body['tag'], body['value'])
        if err:
            raise HTTPException(400, err)
        return {'ok': True}

    @app.post('/api/p/{pid}/station/{sid}/fault')
    async def fault(pid: str, sid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        st = rt.station(sid)
        kind = str(body['kind'])
        if isinstance(body.get('params'), dict) and body['params']:   # 5.0 动作故障参数：{"cyl": "clamp", "extra_s": 2, "drift_s_per_day": 0.5}
            kind = kind.split(':')[0] + ':' + ','.join(f'{k}={v}' for k, v in body['params'].items())
        err = st.inject(kind)
        if err:
            raise HTTPException(400, err)
        rt.plant.log(sid, 'inject', _tr('注入：{get}', get=st.fault_kinds.get(kind.split(':')[0], kind)) + (_tr('（{v}）', v=kind.split(':', 1)[1]) if ':' in kind else ''))
        return {'ok': True}

    @app.post('/api/p/{pid}/station/{sid}/enable')
    async def enable(pid: str, sid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        st = rt.station(sid)
        st.enabled = bool(body.get('enabled', True))
        rt.plant.log(sid, 'layout', (_tr('启用 ') if st.enabled else _tr('停用 ')) + st.name)
        return {'ok': True}

    # 编辑
    @app.post('/api/p/{pid}/station')
    async def add_station(pid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        st = rt.add_station(body.get('type'), body.get('pos'), body.get('template'))
        return {'ok': True, 'id': st.id, 'meta': rt.meta()}

    @app.patch('/api/p/{pid}/station/{sid}')
    async def patch_station(pid: str, sid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        restart = rt.patch_station(sid, body)
        return {'ok': True, 'needs_restart': restart, 'meta': rt.meta()}

    @app.delete('/api/p/{pid}/station/{sid}')
    async def del_station(pid: str, sid: str):
        rt = mgr.get(pid)
        rt.remove_station(sid)
        return {'ok': True, 'meta': rt.meta()}

    @app.patch('/api/p/{pid}/plant')
    async def patch_plant(pid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        rt.patch_plant(body)
        return {'ok': True, 'meta': rt.meta()}

    @app.post('/api/p/{pid}/save')
    async def save(pid: str):
        rt = mgr.get(pid)
        rt.save()
        return {'ok': True}

    @app.post('/api/p/{pid}/restart')
    async def restart(pid: str):
        rt = mgr.get(pid)
        if rt.dirty:
            rt.save()
        await mgr.restart(pid)
        return {'ok': True}

    @app.post('/api/p/{pid}/sim')
    async def sim(pid: str, body: dict = Body(...)):
        p = mgr.get(pid).plant
        if 'speed' in body:
            p.speed = max(0.1, min(3600.0, float(body['speed'])))
        if 'paused' in body:
            p.paused = bool(body['paused'])
        return {'speed': p.speed, 'paused': p.paused}

    @app.get('/api/p/{pid}/parts')
    async def parts(pid: str, status: str = '', limit: int = 50):
        items = [p for p in reversed(list(mgr.get(pid).plant.parts.values())) if not status or p.get('status') == status]
        return [{k: p.get(k) for k in ('id', 'status', 'heat', 'mold', 'pour_temp', 'scrap_cause')} for p in items[:limit]]

    @app.get('/api/p/{pid}/part/{part}')
    async def part(pid: str, part: str):
        p = mgr.get(pid).plant.parts.get(part)
        if not p:
            raise HTTPException(404, _tr('没有这个编号'))
        return p

    @app.get('/api/p/{pid}/track/suggest')
    async def suggest(pid: str):
        return {'id': tracking.suggest(mgr.get(pid).plant)}

    @app.get('/api/p/{pid}/track/{part}')
    async def track(pid: str, part: str):
        plant = mgr.get(pid).plant
        loc = tracking.locate(plant, part)
        if loc is None:
            raise HTTPException(404, _tr('没有这个编号'))
        p = plant.parts[part]
        loc['history'] = p.get('history', [])
        loc['info'] = {k: p.get(k) for k in ('heat', 'ladle', 'mold', 'pour_temp', 'mg', 'sand_moisture', 'scrap_cause')}
        return loc

    @app.get('/api/p/{pid}/events')
    async def events(pid: str, since: int = 0, limit: int = 200):
        return [e for e in mgr.get(pid).plant.events if e['seq'] > since][-limit:]

    @app.get('/api/p/{pid}/points')
    async def points(pid: str):
        """点表（旧版，中文键；界面和导出用）。程序对接请用 /points/v2。"""
        return mgr.get(pid).points()

    @app.get('/api/p/{pid}/points/v2')
    async def points_v2(pid: str):
        """点表（英文键、结构化字段）：station, tag, unit, datatype, writable, low/high, opcua_nodeid, mqtt_topic, mqtt_set_topic,
        modbus{port, unit, table, address, count, type, order, scale, writable, mirror}。"""
        rt = mgr.get(pid)
        return {'plant': pid, 'name': rt.plant.name, 'endpoints': rt.meta()['endpoints'], 'points': rt.points_v2()}

    @app.get('/api/p/{pid}/points.csv', response_class=PlainTextResponse)
    async def points_csv(pid: str):
        rows = mgr.get(pid).points()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        return PlainTextResponse('﻿' + buf.getvalue(), media_type='text/csv; charset=utf-8',
                                 headers={'Content-Disposition': f'attachment; filename=points-{pid}.csv'})

    @app.websocket('/ws/{pid}')
    async def ws(sock: WebSocket, pid: str):
        await sock.accept()
        rt = mgr.rts.get(pid) or mgr.sandboxes.get(pid)
        u = store.user_from_token(sock.query_params.get('token', ''), sock.client.host if sock.client else '')
        if not rt or not u or store.token_deny(u, 'GET', f'/ws/{pid}') or (teach_guard(u, 'GET', f'/api/p/{pid}/ws') and not own_context(mgr, u, f'/ws/{pid}')):
            await sock.close()
            return
        if rt.sandbox:
            rt.touch()
        rt.clients.add(sock)
        try:
            while True:
                await sock.receive_text()
        except WebSocketDisconnect:
            for r in list(mgr.rts.values()) + list(mgr.sandboxes.values()):
                r.clients.discard(sock)

    apidocs.register(app)                        # /docs、/redoc（静态资源本地打包）+ 接口按模块分组
    if os.path.isdir(WEB):
        # 4.6.2 缓存：assets/ 里的文件名带内容哈希（换了内容就换名字），浏览器可以一直缓存；index.html 每次都要问服务器（no-cache），
        # 发新版以后刷新一下就拿到新的入口。构建时保留上一次构建的 assets（web/vite.config.ts），开着的旧页面照样能按需加载面板。
        class HashedFiles(StaticFiles):
            async def get_response(self, path, scope):
                r = await super().get_response(path, scope)
                if r.status_code == 200:
                    r.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
                return r
        for sub in ('assets', 'models'):
            if os.path.isdir(os.path.join(WEB, sub)):
                app.mount(f'/{sub}', (HashedFiles if sub == 'assets' else StaticFiles)(directory=os.path.join(WEB, sub)), name=sub)
        NO_CACHE = {'Cache-Control': 'no-cache'}

        @app.get('/{path:path}')
        async def spa(path: str):
            if path.startswith('api/'):
                raise HTTPException(404)
            f = os.path.join(WEB, path)
            # 5.0 路径穿越：必须真的在 WEB 目录里面（startswith 会放过同名前缀的兄弟目录，例如 dist-old）
            inside = os.path.commonpath([os.path.realpath(f), os.path.realpath(WEB)]) == os.path.realpath(WEB) if path else False
            if path and inside and os.path.isfile(f):
                return FileResponse(f, headers=NO_CACHE if f.endswith('.html') else None)
            return FileResponse(os.path.join(WEB, 'index.html'), headers=NO_CACHE)
    i18n.install(app)                            # last = outermost: request language (X-Lang > ?lang= > Accept-Language > VF_LANG), English JSON texts
    return app


def serve(cfg_unused, args):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    for noisy in ('asyncua', 'amqtt', 'pymodbus', 'transitions'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    mgr = Manager(args)
    app = build_app(mgr)

    async def main():
        await mgr.start()
        server = uvicorn.Server(uvicorn.Config(app, host='0.0.0.0', port=args.http, log_level='warning'))
        log.info(_tr('Web/API http://0.0.0.0:%s  OPC UA :%s  MQTT :%s  工厂：%s'), args.http, args.opcua, args.mqtt,
                 ', '.join(f"{p}(Modbus :{r.cfg['plant']['modbus_port']})" for p, r in mgr.rts.items()))
        await server.serve()

    asyncio.run(main())
