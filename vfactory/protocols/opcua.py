"""OPC UA：一个服务端承载多个工厂。

目录：Objects/VirtualFactory/<工厂编号>/<区域>/<工位>/<点位分层>
NodeId：ns=2;s=<工厂编号>/<工位>/<点位>，例如 ns=2;s=foundry-housing/CNC1/Monitoring/Spindle/Load

有网关的工厂（4.3）：网关对象下面挂它采集的设备，NodeId ns=2;s=<工厂>/<网关>/<设备>/<点位>；旧 NodeId 保留，是主网关的别名。
网络线 / 交换机 / 网关 / PLC 故障按"设备 → 网关"的路径作用：断开 = BadNotConnected（写入同样拒绝），冻结 / 坏质量 / 丢包照样。

像真实设备的地方：
- 每次值变化都写 SourceTimestamp（对外时间：仿真时钟或墙钟，见协议设置）和 ServerTimestamp（墙钟）；
- 数值点是 AnalogItemType（有量程）/ AnalogUnitType（有单位无量程）/ BaseAnalogType，带 EngineeringUnits（UNECE 单位）和 EURange；
- 设备对象的类型是 VFStationType 的子类型（按设备种类），不是裸 BaseObjectType；
- 客户端写入在服务端当场校验：越界 BadOutOfRange、类型不对 BadTypeMismatch（宽松模式下按点位类型转换）、只读 BadUserAccessDenied；
- HistoryRead（原始值）：数值点最近 24 小时（仿真）每 30 秒一个值，来自仿真内核的点位环形缓冲；
- 设备报警按 AlarmConditionType 事件发出（Server 对象和工厂对象上都能订阅），报警变量照旧保留；
- Plant/SimTime 是 DateTime（UTC），Plant/SimTimeText 是原来的文字。
- 5.0 动作级信号（Actions/…）：每个变化单独写一次，SourceTimestamp 是动作的精确时刻（毫秒），不是同步时刻。
- 5.0 原始现场模式（plant.raw_site，见 vfactory/rawsite.py）：没有按设备组织的目录，改成 <工厂>/<通道>/<设备>/<地址>，
  NodeId ns=2;s=<工厂>/S7.PLC2.DB10.DBD4、…/CNC.M3.M3_ZZFZ；不发设备报警事件（报警文字里有设备名），不建网关目录。
"""
from ..i18n import _tr
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from asyncua import Server, ua
from asyncua.server.history import HistoryDict
from asyncua.server.internal_session import InternalSession

from .. import comm, rawsite
from ..actions import events_since

log = logging.getLogger('vfactory.opcua')
VT = {'float': ua.VariantType.Double, 'int': ua.VariantType.Int32, 'bool': ua.VariantType.Boolean, 'str': ua.VariantType.String,
      'datetime': ua.VariantType.DateTime}
DT = {'float': ua.ObjectIds.Double, 'int': ua.ObjectIds.Int32, 'bool': ua.ObjectIds.Boolean, 'str': ua.ObjectIds.String, 'datetime': ua.ObjectIds.DateTime}
NS_URI = 'http://honeymeta.cn/vfactory'
UNECE_NS = 'http://www.opcfoundation.org/UA/units/un/cefact'
# 工程单位 → (UNECE 代码, 显示, 说明)
UNITS = {'°C': ('CEL', '°C', '摄氏度'), 'kW': ('KWT', 'kW', '千瓦'), 'kWh': ('KWH', 'kWh', '千瓦时'), '%': ('P1', '%', '百分比'),
         'mm': ('MMT', 'mm', '毫米'), 'm': ('MTR', 'm', '米'), 'kg': ('KGM', 'kg', '千克'), 't': ('TNE', 't', '吨'), 's': ('SEC', 's', '秒'),
         'min': ('MIN', 'min', '分钟'), 'h': ('HUR', 'h', '小时'), 'rpm': ('RPM', 'r/min', '转每分'), 'r/min': ('RPM', 'r/min', '转每分'),
         'Hz': ('HTZ', 'Hz', '赫兹'), 'V': ('VLT', 'V', '伏'), 'A': ('AMP', 'A', '安'), 'mA': ('4K', 'mA', '毫安'), 'kPa': ('KPA', 'kPa', '千帕'),
         'MPa': ('MPA', 'MPa', '兆帕'), 'Pa': ('PAL', 'Pa', '帕'), 'bar': ('BAR', 'bar', '巴'), 'm³/h': ('MQH', 'm³/h', '立方米每小时'),
         'L/min': ('L2', 'L/min', '升每分'), 'L': ('LTR', 'L', '升'), 'm/s': ('MTS', 'm/s', '米每秒'), 'mm/s': ('C16', 'mm/s', '毫米每秒'),
         '°': ('DD', '°', '度'), '件': ('H87', '件', '件'), '个': ('H87', '个', '个'), '台': ('H87', '台', '台'), '人': ('IE', '人', '人'),
         '次': ('C62', '次', '次'), '批': ('C62', '批', '批'), 'g': ('GRM', 'g', '克'), 'N': ('NEU', 'N', '牛'), 'Nm': ('NU', 'N·m', '牛米')}
STATE_CODE = {'Idle': 0, 'Executing': 1, 'Starved': 2, 'Blocked': 3, 'Stopped': 4, 'Setup': 5, 'Planned': 6}


def unece_id(code):
    n = 0
    for ch in code:
        n = (n << 8) | ord(ch)
    return n


def eu_info(unit):
    code, disp, desc = UNITS.get(unit, (None, unit, unit))
    return ua.EUInformation(NamespaceUri=UNECE_NS, UnitId=unece_id(code) if code else -1,
                            DisplayName=ua.LocalizedText(disp), Description=ua.LocalizedText(desc))


def _val(tag):
    v = tag.value
    try:
        if tag.dtype == 'float':
            f = float(v or 0)
            return f if f == f else 0.0
        if tag.dtype == 'int':
            return int(v or 0)
        if tag.dtype == 'bool':
            return bool(v)
    except (TypeError, ValueError, OverflowError):
        return 0.0 if tag.dtype == 'float' else 0 if tag.dtype == 'int' else False
    return str(v if v is not None else '')


def _utc(d: datetime) -> datetime:
    return d.astimezone(timezone.utc)


class PlantHistory(HistoryDict):
    """HistoryRead：本厂数值点从仿真内核的环形缓冲读（24 小时、30 秒一个点）；其它节点交给 asyncua 自带的内存历史。"""

    def __init__(self, hub):
        super().__init__()
        self.hub = hub

    async def read_node_history(self, node_id, start, end, nb_values):
        ref = self.hub.hist.get(node_id)
        if ref is None:
            return await super().read_node_history(node_id, start, end, nb_values)
        pa, key, dtype = ref
        p = pa.plant
        ts, vs = p.tagring.series(key)
        epoch = ua.get_win_epoch()
        start = None if start in (None, epoch) else start
        end = None if end in (None, epoch) else end
        backward = start is not None and end is not None and start > end
        lo, hi = (end, start) if backward else (start, end)
        rows = []
        for t, v in zip(ts, vs):
            d = pa.ts_of(t)
            if lo is not None and d < lo or hi is not None and d > hi:
                continue
            val = bool(v) if dtype == 'bool' else int(round(v)) if dtype == 'int' else float(v)
            rows.append(ua.DataValue(ua.Variant(val, VT[dtype]), SourceTimestamp=d, ServerTimestamp=d))
        if backward or (start is None and end is not None):
            rows.reverse()
        cont = None
        if nb_values and len(rows) > nb_values:
            cont = rows[nb_values].SourceTimestamp
            rows = rows[:nb_values]
        return rows, cont


class OpcUaHub:
    instance = None

    def __init__(self, port=4840):
        self.port = port
        self.plants = {}
        self.writers = {}             # NodeId → (工厂适配器, 记录)：客户端写入在这里当场处理
        self.hist = {}                # NodeId → (工厂适配器, 点位键, 类型)
        self.types = {}

    @property
    def endpoint(self):
        return f'opc.tcp://0.0.0.0:{self.port}/vfactory/'

    async def start(self):
        s = self.server = Server()
        await s.init()
        s.set_endpoint(self.endpoint)
        s.set_server_name('VirtualFactory OPC UA Server (HoneyMeta)')
        s.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        self.idx = await s.register_namespace(NS_URI)
        self.root = await s.nodes.objects.add_folder(ua.NodeId('VirtualFactory', self.idx), ua.QualifiedName('VirtualFactory', self.idx))
        self.base_type = await s.nodes.base_object_type.add_object_type(ua.NodeId('Types/VFStationType', self.idx), ua.QualifiedName('VFStationType', self.idx))
        await self.base_type.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(ua.LocalizedText(_tr('蜂元虚拟工厂设备（按设备种类派生子类型）')))))
        self.history = PlantHistory(self)
        s.iserver.history_manager.set_storage(self.history)
        await self.history.init()
        await s.start()
        self.aspace = s.iserver.aspace
        self.iserver = s.iserver
        svc = s.iserver.attribute_service
        self._orig_write = svc.write
        svc.write = self._write
        OpcUaHub.instance = self
        _patch_sessions()
        self.alarm_gens = [await s.get_event_generator(ua.ObjectIds.AlarmConditionType, ua.ObjectIds.Server)]
        log.info('OPC UA listening on %s', self.endpoint)

    async def station_type(self, kind):
        if kind not in self.types:
            name = ''.join(x.capitalize() for x in str(kind or 'station').replace('-', '_').split('_')) + 'StationType'
            nid = ua.NodeId(f'Types/{name}', self.idx)
            try:
                self.types[kind] = await self.base_type.add_object_type(nid, ua.QualifiedName(name, self.idx))
            except ua.UaStatusCodeError:
                self.types[kind] = self.server.get_node(nid)
        return self.types[kind].nodeid

    async def attach(self, pid, plant):
        a = PlantOpcUa(self, pid, plant)
        await a.build()
        self.plants[pid] = a
        a.task = asyncio.create_task(a.loop())
        return a

    async def detach(self, pid):
        a = self.plants.pop(pid, None)
        if a:
            a.task.cancel()
            for nid in [k for k, v in self.writers.items() if v[0] is a]:
                del self.writers[nid]
            for nid in [k for k, v in self.hist.items() if v[0] is a]:
                del self.hist[nid]
            await a.teardown()

    # ---------- 客户端写入 ----------
    async def _write(self, params, user=None):
        """包一层 AttributeService.write：本厂可写点位当场写进模型，失败返回对应的状态码（不再靠轮询比对）。"""
        mine = [i for i, wv in enumerate(params.NodesToWrite) if wv.AttributeId == ua.AttributeIds.Value and wv.NodeId in self.writers]
        if not mine:
            return await (self._orig_write(params, user) if user is not None else self._orig_write(params))
        res = [None] * len(params.NodesToWrite)
        rest = [wv for i, wv in enumerate(params.NodesToWrite) if i not in mine]
        if rest:
            sub = ua.WriteParameters(NodesToWrite=rest)
            r2 = await (self._orig_write(sub, user) if user is not None else self._orig_write(sub))
            it = iter(r2)
            for i in range(len(res)):
                if i not in mine:
                    res[i] = next(it)
        for i in mine:
            wv = params.NodesToWrite[i]
            pa, rec = self.writers[wv.NodeId]
            try:
                res[i] = await pa.client_write(rec, wv.Value)
            except Exception:
                log.exception(_tr('OPC UA 写入出错'))
                res[i] = ua.StatusCode(ua.StatusCodes.BadInternalError)
        return res

    # ---------- 断开：关掉碰本厂节点的会话 ----------
    def disconnected_pid(self, nodeid):
        s = nodeid.Identifier if isinstance(nodeid.Identifier, str) and nodeid.NamespaceIndex == getattr(self, 'idx', -1) else None
        if not s:
            return None
        pid = s.split('/', 1)[0]
        a = self.plants.get(pid)
        return pid if a and a.disconnected else None

    def kick(self, session, why=''):
        for proto in list(getattr(self.server.bserver, 'clients', [])):
            if getattr(proto.processor, 'session', None) is session and proto.transport is not None:
                log.info(_tr('OPC UA 断开会话 %s（%s）'), proto.peer_name, why)
                proto.transport.close()

    def kick_plant(self, pid):
        """关闭订阅了本厂节点的会话。"""
        subs = self.iserver.subscription_service.subscriptions
        sessions = {}
        for proto in list(getattr(self.server.bserver, 'clients', [])):
            se = getattr(proto.processor, 'session', None)
            if se is not None:
                sessions[se.session_id] = se
        for sub in list(subs.values()):
            mis = getattr(sub.monitored_item_srv, '_monitored_items', {})
            if any(str(getattr(m.read_value_id.NodeId, 'Identifier', '')).startswith(pid + '/') for m in mis.values() if getattr(m, 'read_value_id', None)):
                se = sessions.get(sub.session_id)
                if se is not None:
                    self.kick(se, _tr('{pid} 通讯断开', pid=pid))

    async def alarm(self, pa, st, active, text):
        """报警按 AlarmConditionType 发事件。"""
        now = _utc(comm.ext_dt(pa.plant))
        for gen in self.alarm_gens + ([pa.alarm_gen] if pa.alarm_gen else []):
            ev = gen.event
            ev.SourceNode = pa.objs[st.id].nodeid if st.id in pa.objs else pa.top.nodeid
            ev.SourceName = f'{pa.pid}/{st.id}'
            ev.ConditionName = 'Alarm'
            ev.Message = ua.LocalizedText(_tr('{name}：{text}', name=st.name, text=text) if text else _tr('{name}：报警解除', name=st.name))
            ev.Severity = 800 if ('故障' in (text or '') or 'fault' in (text or '').lower() or 'failure' in (text or '').lower()) else 500
            ev.Time = now
            ev.ReceiveTime = datetime.now(timezone.utc)
            ev.Retain = bool(active)
            ev.ActiveState = ua.LocalizedText('Active' if active else 'Inactive')
            setattr(ev, 'ActiveState/Id', bool(active))
            ev.AckedState = ua.LocalizedText('Unacknowledged' if active else 'Acknowledged')
            setattr(ev, 'AckedState/Id', not active)
            ev.EnabledState = ua.LocalizedText('Enabled')
            setattr(ev, 'EnabledState/Id', True)
            try:
                await gen.trigger(time_attr=now)
            except TypeError:
                await gen.trigger()
            except Exception:
                log.exception(_tr('OPC UA 报警事件'))


def _patch_sessions():
    """会话级拦截：访问"断开"中的工厂节点 → 返回 BadNotConnected 并关闭该会话。只装一次。"""
    if getattr(InternalSession, '_vf_patched', False):
        return
    InternalSession._vf_patched = True
    orig_read, orig_cmi = InternalSession.read, InternalSession.create_monitored_items

    async def read(self, params):
        hub = OpcUaHub.instance
        if hub and self.external and any(hub.disconnected_pid(r.NodeId) for r in params.NodesToRead):
            hub.kick(self, _tr('读取断开中的工厂'))
            return [ua.DataValue(StatusCode=ua.StatusCode(ua.StatusCodes.BadNotConnected)) for _ in params.NodesToRead]
        return await orig_read(self, params)

    async def create_monitored_items(self, params):
        hub = OpcUaHub.instance
        if hub and self.external and any(hub.disconnected_pid(i.ItemToMonitor.NodeId) for i in params.ItemsToCreate):
            hub.kick(self, _tr('订阅断开中的工厂'))
        return await orig_cmi(self, params)

    InternalSession.read = read
    InternalSession.create_monitored_items = create_monitored_items


class PlantOpcUa:
    def __init__(self, hub, pid, plant, period=0.5):
        self.hub, self.pid, self.plant, self.period = hub, pid, plant, period
        self.vars, self.objs, self.folders, self.pending = [], {}, {}, []
        self.alarms = {}
        self.alarm_gen = None
        self.disconnected = False
        self.walls = []               # (仿真秒, 墙钟)：墙钟模式下把历史值的仿真时刻换成墙钟
        self._drops = 0
        self.raw = rawsite.enabled(plant)          # 原始现场模式（切换时整个工厂的节点重建）
        self.act_seq = getattr(plant, 'act_seq', 0)
        self._idx, self._idx_n = {}, -1

    def nid(self, s):
        return ua.NodeId(f'{self.pid}/{s}', self.hub.idx)

    def qn(self, s):
        return ua.QualifiedName(s, self.hub.idx)

    def ts_of(self, t):
        """仿真秒 → 对外时间戳（UTC）。墙钟模式按记录的 (仿真秒, 墙钟) 对照插值。"""
        p = self.plant
        if comm.settings(p)['time'] != 'wall' or not self.walls:
            return _utc(comm.sim_dt(p, t))
        w = self.walls
        if t <= w[0][0]:
            return w[0][1] - timedelta(seconds=(w[0][0] - t) / max(0.1, p.speed))
        for (t0, d0), (t1, d1) in zip(w, w[1:]):
            if t0 <= t <= t1:
                f = (t - t0) / (t1 - t0) if t1 > t0 else 0
                return d0 + (d1 - d0) * f
        return w[-1][1] + timedelta(seconds=(t - w[-1][0]) / max(0.1, p.speed))

    def stamp(self):
        return {'SourceTimestamp': _utc(comm.ext_dt(self.plant)), 'ServerTimestamp': datetime.now(timezone.utc)}

    async def build(self):
        s = self.hub.server
        self.top = await self.hub.root.add_object(self.nid('_plant'), self.qn(self.pid))
        await self.top.write_attribute(ua.AttributeIds.DisplayName, ua.DataValue(ua.Variant(ua.LocalizedText(f'{self.pid} {self.plant.name}'))))
        info = await self.top.add_folder(self.nid('Plant'), self.qn('Plant'))
        self.plant_vars = {}
        p = self.plant
        for name, val, vt, w, desc in (('SimTime', _utc(comm.sim_dt(p)), 'datetime', False, _tr('仿真时间（UTC）')),
                                       ('SimTimeText', p.clock_str(), 'str', False, _tr('仿真时间（本地，文字）')),
                                       ('TimeMode', comm.settings(p)['time'], 'str', False, _tr('对外时间：sim = 仿真时钟，wall = 墙钟')),
                                       ('Speed', float(p.speed), 'float', True, _tr('仿真倍速（0.1–3600）')), ('Paused', False, 'bool', True, _tr('暂停')),
                                       ('Castings', 0, 'int', False, _tr('累计浇注/投料')), ('GoodParts', 0, 'int', False, _tr('累计合格入库')),
                                       ('ScrapParts', 0, 'int', False, _tr('累计报废')), ('EnergyKWh', 0.0, 'float', False, _tr('全厂累计电能 kWh'))):
            v = await info.add_variable(self.nid(f'Plant/{name}'), self.qn(name), ua.Variant(val, VT[vt]))
            await v.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(ua.LocalizedText(desc))))
            if w:
                await v.set_writable()
                self.hub.writers[v.nodeid] = (self, ('plant', name))
            await s.write_attribute_value(v.nodeid, ua.DataValue(ua.Variant(val, VT[vt]), **self.stamp()))
            self.plant_vars[name] = [v, vt, val]
        try:
            self.alarm_gen = await s.get_event_generator(ua.ObjectIds.AlarmConditionType, self.top)
        except Exception:
            log.exception(_tr('OPC UA 工厂对象事件源'))
        for st in list(self.plant.stations.values()):
            await self.add_station(st)
        await self.build_gateways()
        self.plant.listeners.append(lambda op, st: self.pending.append((op, st)))

    async def teardown(self):
        """删掉本厂的全部节点。节点编号都在自己的账本里，直接一次删，不用逐层浏览（递归删上千个节点很慢，会卡住"删除工厂"请求）。"""
        s = self.hub.server
        nids = [self.top.nodeid, self.nid('Plant')] + [v[0].nodeid for v in getattr(self, 'plant_vars', {}).values()]
        nids += list(self.folders.values()) + [o.nodeid for o in self.objs.values()] + [v[0] for v in getattr(self, 'gw_pairs', {}).values()]
        for x in self.vars:
            nids += [x[0], ua.NodeId(f'{x[0].Identifier}#EngineeringUnits', x[0].NamespaceIndex), ua.NodeId(f'{x[0].Identifier}#EURange', x[0].NamespaceIndex)]
        try:
            items = [ua.DeleteNodesItem(NodeId=n, DeleteTargetReferences=True) for n in dict.fromkeys(nids)]
            for i in range(0, len(items), 2000):
                await s.iserver.isession.delete_nodes(ua.DeleteNodesParameters(NodesToDelete=items[i:i + 2000]))
                await asyncio.sleep(0)
            if self.top.nodeid in s.iserver.aspace:                # 账本没删干净：兜底递归删
                await s.delete_nodes([self.top], recursive=True)
        except Exception:
            log.exception('opcua teardown')
            try:
                await s.delete_nodes([self.top], recursive=True)
            except Exception:
                pass

    def _folder_item(self, parent_nid, key, name):
        it = ua.AddNodesItem()
        it.RequestedNewNodeId = self.nid(key)
        it.BrowseName = self.qn(name)
        it.NodeClass = ua.NodeClass.Object
        it.ParentNodeId = parent_nid
        it.ReferenceTypeId = ua.NodeId(ua.ObjectIds.Organizes)
        it.TypeDefinition = ua.NodeId(ua.ObjectIds.FolderType)
        a = ua.ObjectAttributes()
        a.DisplayName = ua.LocalizedText(name)
        a.Description = ua.LocalizedText(name)
        a.EventNotifier = 0
        it.NodeAttributes = a
        return it

    def _var_item(self, parent_nid, key, name, tag):
        dtype = tag.dtype if tag.dtype in VT else 'str'
        numeric = dtype in ('float', 'int')
        lo, hi = tag.lo, tag.hi
        if numeric and lo is None and hi is None and tag.unit == '%':
            lo, hi = 0.0, 100.0
        has_range = numeric and lo is not None and hi is not None
        it = ua.AddNodesItem()
        it.RequestedNewNodeId = self.nid(key)
        it.BrowseName = self.qn(name)
        it.NodeClass = ua.NodeClass.Variable
        it.ParentNodeId = parent_nid
        it.ReferenceTypeId = ua.NodeId(ua.ObjectIds.HasComponent)
        if numeric:
            it.TypeDefinition = ua.NodeId(ua.ObjectIds.AnalogItemType if has_range else ua.ObjectIds.AnalogUnitType if tag.unit else ua.ObjectIds.BaseAnalogType)
        else:
            it.TypeDefinition = ua.NodeId(ua.ObjectIds.BaseDataVariableType)
        a = ua.VariableAttributes()
        a.DisplayName = ua.LocalizedText(name)
        a.Description = ua.LocalizedText(tag.desc or name)
        a.DataType = ua.NodeId(DT[dtype])
        a.Value = ua.Variant(_val(tag) if tag.dtype in VT else str(tag.value), VT[dtype])
        a.ValueRank = ua.ValueRank.Scalar
        a.ArrayDimensions = None
        a.WriteMask = a.UserWriteMask = 0
        hist = dtype in ('float', 'int', 'bool')
        lvl = ua.AccessLevel.CurrentRead.mask | (ua.AccessLevel.CurrentWrite.mask if tag.writable else 0) | (ua.AccessLevel.HistoryRead.mask if hist else 0)
        a.AccessLevel = a.UserAccessLevel = lvl
        a.Historizing = hist
        it.NodeAttributes = a
        items = [it]
        if numeric and (tag.unit or not has_range):
            items.append(self._prop_item(it.RequestedNewNodeId, key + '#EngineeringUnits', 'EngineeringUnits', ua.Variant(eu_info(tag.unit or ''), ua.VariantType.ExtensionObject),
                                         ua.ObjectIds.EUInformation))
        if has_range:
            items.append(self._prop_item(it.RequestedNewNodeId, key + '#EURange', 'EURange', ua.Variant(ua.Range(Low=float(lo), High=float(hi)), ua.VariantType.ExtensionObject),
                                         ua.ObjectIds.Range))
        return items

    def _prop_item(self, parent_nid, key, name, variant, dtype):
        it = ua.AddNodesItem()
        it.RequestedNewNodeId = self.nid(key)
        it.BrowseName = ua.QualifiedName(name, 0)
        it.NodeClass = ua.NodeClass.Variable
        it.ParentNodeId = parent_nid
        it.ReferenceTypeId = ua.NodeId(ua.ObjectIds.HasProperty)
        it.TypeDefinition = ua.NodeId(ua.ObjectIds.PropertyType)
        a = ua.VariableAttributes()
        a.DisplayName = ua.LocalizedText(name)
        a.Description = ua.LocalizedText(name)
        a.DataType = ua.NodeId(dtype)
        a.Value = variant
        a.ValueRank = ua.ValueRank.Scalar
        a.AccessLevel = a.UserAccessLevel = ua.AccessLevel.CurrentRead.mask
        it.NodeAttributes = a
        return it

    async def add_station_raw(self, st):
        """原始现场：<工厂>/<通道>/<设备>/<地址>，NodeId <工厂>/<通道>.<设备>.<地址>。"""
        s = self.hub.server
        names = rawsite.names(self.plant)
        items, recs = [], []
        for tname, tag in st.tags.items():
            r = names.get((st.id, tname))
            if not r:
                continue
            path = r['path']
            parent = self.top.nodeid
            for i in range(len(path) - 1):
                key = '.'.join(path[:i + 1])
                fk = '@raw/' + key
                if fk not in self.folders:
                    items.append(self._folder_item(parent, key, path[i]))
                    self.folders[fk] = self.nid(key)
                parent = self.folders[fk]
            items += self._var_item(parent, r['opc'], path[-1], tag)
            recs.append([self.nid(r['opc']), st, tname, None, None, None])
        res = await s.iserver.isession.add_nodes(items)
        for it, rr in zip(items, res):
            if not rr.StatusCode.is_good() and rr.StatusCode.value != ua.StatusCodes.BadNodeIdExists:
                log.warning(_tr('OPC UA 建节点 %s 失败：%s'), it.RequestedNewNodeId.Identifier, rr.StatusCode.name)
        for rec in recs:
            tag = st.tags[rec[2]]
            if tag.writable:
                self.hub.writers[rec[0]] = (self, rec)
            if tag.dtype in ('float', 'int', 'bool'):
                self.hub.hist[rec[0]] = (self, f'{st.id}/{rec[2]}', tag.dtype)
            self.vars.append(rec)
        self.alarms[st.id] = st.alarm or ''
        await self.sync_station(st, force=True)

    async def add_station(self, st):
        if self.raw:
            return await self.add_station_raw(st)
        s = self.hub.server
        items = []
        area_key = f'Area/{st.area}'
        if area_key not in self.folders:
            items.append(self._folder_item(self.top.nodeid, area_key, st.area or 'Other'))
            self.folders[area_key] = self.nid(area_key)
        o = ua.AddNodesItem()
        o.RequestedNewNodeId = self.nid(st.id)
        o.BrowseName = self.qn(st.id)
        o.NodeClass = ua.NodeClass.Object
        o.ParentNodeId = self.folders[area_key]
        o.ReferenceTypeId = ua.NodeId(ua.ObjectIds.Organizes)
        o.TypeDefinition = await self.hub.station_type(getattr(st, 'kind', 'station'))
        oa = ua.ObjectAttributes()
        oa.DisplayName = ua.LocalizedText(f'{st.id} {st.name}')
        oa.Description = ua.LocalizedText(_tr('{name}（{get}）', name=st.name, get=st.cfg.get('type', st.kind)))
        oa.EventNotifier = 1
        o.NodeAttributes = oa
        items.append(o)
        recs = []
        for tname, tag in st.tags.items():
            parts = tname.split('/')
            parent = o.RequestedNewNodeId
            for i in range(len(parts) - 1):
                key = f'{st.id}/' + '/'.join(parts[:i + 1])
                if key not in self.folders:
                    items.append(self._folder_item(parent, key, parts[i]))
                    self.folders[key] = self.nid(key)
                parent = self.folders[key]
            items += self._var_item(parent, f'{st.id}/{tname}', parts[-1], tag)
            recs.append([self.nid(f'{st.id}/{tname}'), st, tname, None, None, None])
        res = await s.iserver.isession.add_nodes(items)
        for it, r in zip(items, res):
            if not r.StatusCode.is_good() and r.StatusCode.value != ua.StatusCodes.BadNodeIdExists:
                log.warning(_tr('OPC UA 建节点 %s 失败：%s'), it.RequestedNewNodeId.Identifier, r.StatusCode.name)
        self.objs[st.id] = s.get_node(self.nid(st.id))
        for rec in recs:
            nid, _st, tname = rec[0], rec[1], rec[2]
            tag = st.tags[tname]
            if tag.writable:
                self.hub.writers[nid] = (self, rec)
            if tag.dtype in ('float', 'int', 'bool'):
                self.hub.hist[nid] = (self, f'{st.id}/{tname}', tag.dtype)
            self.vars.append(rec)
        self.alarms[st.id] = st.alarm or ''
        await self.sync_station(st, force=True)

    # ---------- 按网关组织（4.3）：<厂>/<网关>/<设备>/<点位>，挂在网关对象下 ----------
    async def build_gateways(self):
        """有网关的工厂：每个北向含 opcua 的网关下面建它采集的设备（同一份点位，经网关路径受网络故障影响）。旧地址保留为主网关的别名。
        增量：只删掉不再采集的（网关, 设备），只新建新增的；设备的点位变了（例如控制单元改了 I/O）整台重建。"""
        net = getattr(self.plant, 'net', None)
        self.net_ver = net.version if net is not None else -1
        if not hasattr(self, 'gw_pairs'):
            self.gw_pairs = {}                    # (网关, 设备) → (对象 NodeId, 点位名集合)
        if self.raw:                              # 原始现场模式：没有按网关组织的目录
            return
        want = {}
        if net is not None:
            for g in net.gateways:
                if 'opcua' in net.north(g) and g in self.objs:
                    for d in net.served(g):
                        st = self.plant.stations.get(d)
                        if st is not None:
                            want[(g, d)] = st
        gone = [k for k, v in self.gw_pairs.items() if k not in want or set(want[k].tags) != v[1]]
        if gone:
            drop = set(gone)
            dead = [x for x in self.vars if x[5] is not None and (x[5], x[1].id) in drop]
            self.vars = [x for x in self.vars if not (x[5] is not None and (x[5], x[1].id) in drop)]
            for x in dead:
                self.hub.writers.pop(x[0], None)
                self.hub.hist.pop(x[0], None)
            for g, d in gone:
                pre = f'@gw/{g}/{d}/'
                for k in [k for k in self.folders if k.startswith(pre)]:
                    del self.folders[k]
            try:
                await self.hub.server.delete_nodes([self.hub.server.get_node(self.gw_pairs[k][0]) for k in gone], recursive=True)
            except Exception:
                log.exception(_tr('OPC UA 删除网关节点'))
            for k in gone:
                self.gw_pairs.pop(k, None)
        new = [k for k in want if k not in self.gw_pairs]
        if not new:
            return
        s = self.hub.server
        items, recs = [], []
        for g, d in sorted(new):
            st = want[(g, d)]
            o = ua.AddNodesItem()
            o.RequestedNewNodeId = self.nid(f'{g}/{d}')
            o.BrowseName = self.qn(d)
            o.NodeClass = ua.NodeClass.Object
            o.ParentNodeId = self.nid(g)
            o.ReferenceTypeId = ua.NodeId(ua.ObjectIds.Organizes)
            o.TypeDefinition = await self.hub.station_type(getattr(st, 'kind', 'station'))
            oa = ua.ObjectAttributes()
            oa.DisplayName = ua.LocalizedText(f'{d} {st.name}')
            oa.Description = ua.LocalizedText(_tr('{name}（经网关 {g} 采集）', name=st.name, g=g))
            oa.EventNotifier = 0
            o.NodeAttributes = oa
            items.append(o)
            self.gw_pairs[(g, d)] = (o.RequestedNewNodeId, set(st.tags))
            for tname, tag in st.tags.items():
                parts = tname.split('/')
                parent = o.RequestedNewNodeId
                for i in range(len(parts) - 1):
                    key = f'{g}/{d}/' + '/'.join(parts[:i + 1])
                    fk = '@gw/' + key
                    if fk not in self.folders:
                        items.append(self._folder_item(parent, key, parts[i]))
                        self.folders[fk] = self.nid(key)
                    parent = self.folders[fk]
                items += self._var_item(parent, f'{g}/{d}/{tname}', parts[-1], tag)
                recs.append([self.nid(f'{g}/{d}/{tname}'), st, tname, None, None, g])
        res = await s.iserver.isession.add_nodes(items)
        for it, r in zip(items, res):
            if not r.StatusCode.is_good() and r.StatusCode.value != ua.StatusCodes.BadNodeIdExists:
                log.warning(_tr('OPC UA 建网关节点 %s 失败：%s'), it.RequestedNewNodeId.Identifier, r.StatusCode.name)
        for rec in recs:
            tag = rec[1].tags[rec[2]]
            if tag.writable:
                self.hub.writers[rec[0]] = (self, rec)
            if tag.dtype in ('float', 'int', 'bool'):
                self.hub.hist[rec[0]] = (self, f'{rec[1].id}/{rec[2]}', tag.dtype)
            self.vars.append(rec)
            await self._push(rec, force=True)

    def _tags_changed(self):
        """网关下设备的点位集合变了（例如控制单元改了 I/O）：每 10 秒查一次。"""
        now = time.time()
        if now - getattr(self, '_tc_t', 0) < 10:
            return False
        self._tc_t = now
        return any(self.plant.stations.get(d) is not None and set(self.plant.stations[d].tags) != v[1] for (g, d), v in getattr(self, 'gw_pairs', {}).items())

    async def remove_station(self, st):
        obj = self.objs.pop(st.id, None)
        gone = [x for x in self.vars if x[1] is st]
        self.vars = [x for x in self.vars if x[1] is not st]
        for x in gone:
            self.hub.writers.pop(x[0], None)
            self.hub.hist.pop(x[0], None)
        for k in [k for k in self.folders if k.startswith(st.id + '/')]:
            del self.folders[k]
        self.alarms.pop(st.id, None)
        if obj:
            await self.hub.server.delete_nodes([obj], recursive=True)
        elif self.raw and gone:                   # 原始现场：设备目录是共用的（同一台 PLC），只删这台设备的变量
            try:
                await self.hub.server.delete_nodes([self.hub.server.get_node(x[0]) for x in gone], recursive=True)
            except Exception:
                log.exception(_tr('OPC UA 删除原始现场节点'))

    # ---------- 客户端写入（OpcUaHub._write 调过来） ----------
    async def client_write(self, rec, dv):
        if self.disconnected:
            return ua.StatusCode(ua.StatusCodes.BadNotConnected)
        val = dv.Value.Value if dv is not None and dv.Value is not None else None
        p = self.plant
        if rec[0] == 'plant':
            name = rec[1]
            v, vt, _last = self.plant_vars[name]
            try:
                if name == 'Speed':
                    f = float(val)
                    if not 0.1 <= f <= 3600:
                        return ua.StatusCode(ua.StatusCodes.BadOutOfRange)
                    p.speed = f
                    nv = f
                else:
                    if isinstance(val, str):
                        nv = val.strip().lower() in ('1', 'true', 'on', 'yes')
                    else:
                        nv = bool(val)
                    p.paused = nv
            except (TypeError, ValueError):
                return ua.StatusCode(ua.StatusCodes.BadTypeMismatch)
            self.plant_vars[name][2] = nv
            await self.hub.server.write_attribute_value(v.nodeid, ua.DataValue(ua.Variant(nv, VT[vt]), **self.stamp()))
            return ua.StatusCode()
        nid, st, tname = rec[0], rec[1], rec[2]
        if st.id not in p.stations and st.id not in getattr(p, 'sub_index', {}):
            return ua.StatusCode(ua.StatusCodes.BadNodeIdUnknown)
        if (comm.effective(p, 'opcua', st.id, tname, rec[5] if len(rec) > 5 else None) or {}).get('mode') == 'disconnect':
            return ua.StatusCode(ua.StatusCodes.BadNotConnected)          # 网络路径断了：写不到设备
        if val is None:
            return ua.StatusCode(ua.StatusCodes.BadTypeMismatch)
        tag = st.tags.get(tname)
        if tag is not None and not comm.settings(p)['lenient_types']:
            want = VT.get(tag.dtype)
            if dv.Value.VariantType != want:
                return ua.StatusCode(ua.StatusCodes.BadTypeMismatch)
            val = {'float': float, 'int': int, 'bool': bool, 'str': str}[tag.dtype](val)
        elif isinstance(val, (bytes, bytearray)):
            val = val.decode('utf-8', 'replace')
        code, msg = comm.write_tag(p, st, tname, val, 'OPC UA')
        if code:
            log.info(_tr('OPC UA 写入被拒绝：%s/%s %s'), st.id, tname, msg)
            return ua.StatusCode({'range': ua.StatusCodes.BadOutOfRange, 'type': ua.StatusCodes.BadTypeMismatch, 'readonly': ua.StatusCodes.BadUserAccessDenied,
                                  'notfound': ua.StatusCodes.BadNodeIdUnknown}.get(code, ua.StatusCodes.BadInvalidArgument))
        await self._push(rec, force=True)
        return ua.StatusCode()

    # ---------- 发布 ----------
    async def loop(self):
        while True:
            try:
                while self.pending:
                    op, st = self.pending.pop(0)
                    await (self.add_station(st) if op == 'add' else self.remove_station(st))
                net = getattr(self.plant, 'net', None)
                if net is not None:
                    net.ensure()
                    if net.version != getattr(self, 'net_ver', -1) or self._tags_changed():
                        await self.build_gateways()
                t0 = time.perf_counter()
                await self.sync()
                self.sync_ms = round((time.perf_counter() - t0) * 1000, 1)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('opcua sync')
            await asyncio.sleep(self.period)

    async def _push(self, rec, force=False):
        """按故障规则算出对外值/质量，变了才写（带时间戳）。"""
        nid, st, tname = rec[0], rec[1], rec[2]
        tag = st.tags.get(tname)
        if tag is None:
            return
        p = self.plant
        r = comm.effective(p, 'opcua', st.id, tname, rec[5] if len(rec) > 5 else None)
        mode = r.get('mode') if r else None
        if mode == 'drop' and not force and comm.dropped(r):
            return
        val = comm.view(p, r, f'{st.id}/{tname}', _val(tag), tag.dtype)
        q = 'bad' if mode == 'bad' else 'off' if mode == 'disconnect' or self.disconnected else 'good'
        if not force and rec[3] == val and rec[4] == q:
            return
        rec[3], rec[4] = val, q
        vt = VT.get(tag.dtype, ua.VariantType.String)
        if q == 'good':
            dv = ua.DataValue(ua.Variant(val, vt), **self.stamp())
        else:
            code = ua.StatusCodes.BadCommunicationError if q == 'bad' else ua.StatusCodes.BadNotConnected
            dv = ua.DataValue(ua.Variant(val, vt), StatusCode=ua.StatusCode(code), **self.stamp())
        await self.hub.server.write_attribute_value(nid, dv)

    async def sync_station(self, st, force=False):
        for rec in self.vars:
            if rec[1] is st:
                await self._push(rec, force)

    async def sync(self):
        p = self.plant
        pr = comm.protocol_rule(p, 'opcua')
        pmode = pr.get('mode') if pr else None
        was = self.disconnected
        self.disconnected = pmode == 'disconnect'
        if self.disconnected and not was:
            self.hub.kick_plant(self.pid)
        walls = self.walls
        if not walls or p.t - walls[-1][0] >= 30:
            walls.append((p.t, datetime.now(timezone.utc)))
            if len(walls) > 4000:
                del walls[:1000]
        if pmode != 'freeze':
            k = p.kpi
            new = {'SimTime': _utc(comm.sim_dt(p)), 'SimTimeText': p.clock_str(), 'TimeMode': comm.settings(p)['time'], 'Speed': float(p.speed),
                   'Paused': bool(p.paused), 'Castings': int(k['castings']), 'GoodParts': int(k['good']), 'ScrapParts': int(k['scrap']),
                   'EnergyKWh': round(sum(s.energy_kwh for s in p.stations.values()), 1)}
            q = 'off' if self.disconnected else 'bad' if pmode == 'bad' else 'good'
            for name, val in new.items():
                rec = self.plant_vars[name]
                if val != rec[2] or q != (rec[3] if len(rec) > 3 else 'good'):
                    dv = ua.DataValue(ua.Variant(val, VT[rec[1]]), **self.stamp()) if q == 'good' else \
                        ua.DataValue(ua.Variant(val, VT[rec[1]]), StatusCode=ua.StatusCode(ua.StatusCodes.BadCommunicationError if q == 'bad' else ua.StatusCodes.BadNotConnected),
                                     **self.stamp())
                    await self.hub.server.write_attribute_value(rec[0].nodeid, dv)
                    rec[2] = val
                    if len(rec) > 3:
                        rec[3] = q
                    else:
                        rec.append(q)
        if not self.disconnected:
            await self.push_events()
        # 报警事件先发（断开时不发，恢复后补发当前状态的变化）；原始现场模式不发（报警文字里有设备名）
        if not self.disconnected and not self.raw:
            for st in list(p.stations.values()):
                cur = st.alarm or ''
                old = self.alarms.get(st.id, '')
                if cur != old:
                    self.alarms[st.id] = cur
                    await self.hub.alarm(self, st, bool(cur), cur)
        for i, rec in enumerate(self.vars):
            await self._push(rec)
            if i % 400 == 399:
                await asyncio.sleep(0)            # 点位多（有网关时翻倍）时让出事件循环，别卡住 HTTP / Modbus

    async def push_events(self):
        """动作级信号：每个变化写一次，SourceTimestamp 用动作的精确时刻。"""
        p = self.plant
        self.act_seq, evs = events_since(p, self.act_seq)
        if not evs:
            return
        if self._idx_n != len(self.vars):
            self._idx, self._idx_n = {}, len(self.vars)
            for rec in self.vars:
                if rec[5] is None:                 # 只有设备自己的 NodeId（点表里的那个）按事件写；网关下的别名照常按周期同步
                    self._idx.setdefault((rec[1].id, rec[2]), []).append(rec)
        srv = self.hub.server
        tss = {}
        for i, (_seq, t, sid, tname, v) in enumerate(evs):
            recs = self._idx.get((sid, tname))
            if not recs:
                continue
            tag = recs[0][1].tags.get(tname)
            if tag is None:
                continue
            src = tss.get(t)
            if src is None:
                src = tss[t] = self.ts_of(t)
            for rec in recs:
                r = comm.effective(p, 'opcua', sid, tname, rec[5] if len(rec) > 5 else None)
                mode = r.get('mode') if r else None
                if mode in ('disconnect', 'bad'):
                    continue                       # 坏质量 / 断开：交给 _push 按规则写状态码
                if mode == 'drop' and comm.dropped(r):
                    continue
                val = comm.view(p, r, f'{sid}/{tname}', v, tag.dtype)
                if rec[3] == val and rec[4] == 'good':
                    continue
                rec[3], rec[4] = val, 'good'
                await srv.write_attribute_value(rec[0], ua.DataValue(ua.Variant(val, VT.get(tag.dtype, ua.VariantType.String)), SourceTimestamp=src,
                                                                     ServerTimestamp=datetime.now(timezone.utc)))
            if i % 200 == 199:
                await asyncio.sleep(0)

    def points(self):
        return {f'{x[1].id}/{x[2]}': f'ns={self.hub.idx};s={x[0].Identifier}' for x in self.vars if x[5] is None}

    def gw_points(self):
        """网关地址：{(网关, 设备/点位): NodeId}"""
        return {(x[5], f'{x[1].id}/{x[2]}'): f'ns={self.hub.idx};s={self.pid}/{x[5]}/{x[1].id}/{x[2]}' for x in self.vars if x[5] is not None}
