"""通讯层对象化（4.3 · A4）：网关 / 交换机 / SCADA / MES 的运行时模型、网络拓扑、网络线故障、MES 连接状态、架构图数据。

拓扑
  网络线 {id, kind:'network', from, to, protocol, fault?} 把 PLC / HMI / 网关 / 交换机 / SCADA / MES / 联网设备连起来；
  信号线 {id, kind:'signal', from: 设备, to: PLC, signals:[…]} 把设备接到 PLC。
  网关从自己出发沿网络线走（只能穿过交换机），走到的
    - PLC：它和经信号线接到它的设备都由这个网关采集（路径 = 信号线 + 网络线）；
    - 直接联网的生产设备：由这个网关采集；
    - SCADA / MES：这个网关的北向用户（"上报"给它们）。
  一台设备可以被多个网关采集；编号最小的是它的"主网关"。
地址（有网关的工厂）
  OPC UA  ns=2;s=<厂>/<网关>/<设备>/<点位>（挂在网关对象下面）；旧地址 <厂>/<设备>/<点位> 保留，是主网关地址的别名（同样受网络故障影响）。
  MQTT    vfactory/<厂>/<网关>/<设备>/<点位>，写入 …/set、回执 …/set/ack；网关状态 vfactory/<厂>/<网关>/_status；旧主题照发（别名）。
  Modbus  单元地址不变；读写经设备的主网关：路径断开 → 异常码 0B（网关目标无响应），坏质量 → 04。
  没有网关的工厂和以前完全一样。
网络线故障
  运行时注入（POST /api/p/<厂>/signals/comm {link, mode, …} 或架构图上点线注入），或模型里 link.fault（设计时就带故障，常用于实训）。
  模式：disconnect 断开 / latency 延迟 / jitter 抖动 / drop（loss）丢包 / bad 坏质量 / freeze 冻结。作用于经过这条线的数据：
  例如 PLC→交换机 的线断了，这台 PLC 控制的设备在网关北向（三种协议）全部变成断开 / 停止更新。
  交换机、网关、PLC 本身故障（注入"设备故障"或停用）等同于经过它的线全部断开。
"""
from .i18n import _tr
import json
import threading
import time
import urllib.request

from . import comm as _comm
from .core import Station

NET_TYPES = ('gateway', 'switch', 'scada', 'mes')
INFRA_TYPES = NET_TYPES + ('plc', 'hmi')            # 不参与产能、瓶颈统计的"设备"
LINK_MODES = {'disconnect': '断开', 'latency': '延迟', 'jitter': '抖动', 'drop': '丢包', 'bad': '坏质量', 'freeze': '冻结'}
SEVERITY = ('disconnect', 'bad', 'freeze', 'stuck', 'drift', 'drop', 'jitter', 'latency')
RT = {}                                               # 工厂编号 → PlantRuntime（取最新模型里的连线；热更新时 rt.cfg 会换成新对象）
_DOWN = {'mode': 'disconnect', 'id': 'node', '_node': True}


def _btype(st):
    return st.cfg.get('type') if st is not None else None


# ---------------------------------------------------------------- 运行时模型
class NetNode(Station):
    """通讯/信息系统设备：没有物料口；只有在线状态和少量自身点位。故障（断电/死机）= 经过它的数据全部中断。"""
    kind = 'netnode'
    area = ''
    infra = True
    fault_kinds = {'failure': '设备故障（断电/死机）'}

    def build_tags(self):
        self.add_tag('Status/Online', True, '', _tr('在线（没有故障、没有停用）'), dtype='bool')
        self.extra_tags()

    def extra_tags(self):
        pass

    def idle_power(self):
        return 0.05

    def step(self, dt):
        self.state = 'Idle'
        self.power_kw = self.idle_power()
        self.set('Status/Online', True)
        net = getattr(self.plant, 'net', None)
        if net is not None and int(self.plant.t) % 2 == 0:
            # 4.3 性能：高倍速时每 2 仿真秒一次太密（300 倍速每秒 150 次）；墙钟 0.25 s 内、故障规则和拓扑都没变就不重算状态点位
            key = (_comm.version(self.plant), self.plant.layout_version, net.version)
            now = time.monotonic()
            last = self.__dict__.get('_net_upd')
            if last is not None and last[1] == key and now - last[0] < 0.25:
                return
            self._net_upd = (now, key)
            try:
                self.update(net)
            except Exception:          # noqa: BLE001  统计出错不能拖垮仿真
                pass

    def on_failure(self):
        self.set('Status/Online', False)

    def update(self, net):
        pass

    def view(self):
        return {'online': bool(self.tags['Status/Online'].value) and self.failure.repair_left <= 0 and self.enabled}


class Gateway(NetNode):
    kind = 'gateway'

    def extra_tags(self):
        A = self.add_tag
        A('Status/Devices', 0, _tr('台'), _tr('采集的设备数'), dtype='int')
        A('Status/Points', 0, _tr('个'), _tr('上报的点位数'), dtype='int')
        A('Status/DevicesDown', 0, _tr('台'), _tr('链路中断的设备数'), dtype='int')
        A('Status/Consumers', 0, _tr('个'), _tr('北向用户（SCADA / MES）'), dtype='int')

    def update(self, net):
        sv = net.served(self.id)
        self.set('Status/Devices', len(sv))
        self.set('Status/Points', sum(len(net.plant.stations[d].tags) for d in sv if d in net.plant.stations))
        self.set('Status/DevicesDown', sum(1 for d in sv if (net.path_rule(self.id, d) or {}).get('mode') == 'disconnect'))
        self.set('Status/Consumers', len(net.consumers(self.id)))


class Switch(NetNode):
    kind = 'switch'

    def extra_tags(self):
        self.add_tag('Status/PortsUsed', 0, _tr('个'), _tr('已用端口'), dtype='int')

    def update(self, net):
        self.set('Status/PortsUsed', len(net.adj.get(self.id, [])))


class Scada(NetNode):
    kind = 'scada'

    def idle_power(self):
        return 0.3


class Mes(NetNode):
    kind = 'mes'

    def extra_tags(self):
        A = self.add_tag
        A('Status/Connected', False, '', _tr('在接收数据（有客户端在读本厂数据或 MES 网关主题在发）'), dtype='bool')
        A('Status/Clients', 0, _tr('个'), _tr('外部客户端（MQTT 订阅 / OPC UA 会话）'), dtype='int')
        A('Status/MesMsgPerMin', 0, _tr('条/分'), _tr('MES 网关报文（_mes）每分钟'), dtype='int')
        A('Status/Reachable', False, '', _tr('MES 地址能访问（每 30 秒探测一次）'), dtype='bool')
        A('Status/PathUp', True, '', _tr('到网关的网络通'), dtype='bool')

    def idle_power(self):
        return 0.4

    def update(self, net):
        s = net.mes_status(self.id)
        self.set('Status/Connected', bool(s['connected']))
        self.set('Status/Clients', int(s['clients']))
        self.set('Status/MesMsgPerMin', int(s['mes_per_min']))
        self.set('Status/Reachable', bool(s['reachable']))
        self.set('Status/PathUp', bool(s['path_up']))


MODELS = {'gateway': Gateway, 'switch': Switch, 'scada': Scada, 'mes': Mes}


def register(registry):
    for k, cls in MODELS.items():
        registry.setdefault(k, cls)


# ---------------------------------------------------------------- 拓扑与故障
class Network:
    def __init__(self, rt):
        self.rt = rt
        self.plant = rt.plant
        self.pid = rt.pid
        self.sig = None
        self.version = 0
        self.gateways: list = []
        self.serve: dict = {}          # 网关 → {设备: {'links': [...], 'nodes': [...], 'via': plc 或 None}}
        self.cons: dict = {}           # 网关 → {北向节点: 路径}
        self.primary: dict = {}        # 设备 → 主网关
        self.adj: dict = {}
        self.links: dict = {}
        self.sig_of: dict = {}         # 设备 → [(plc, 信号线)]
        self._memo, self._memo_key = {}, None
        self._probe = {}               # MES 地址探测：节点 → {t, ok}
        self.ensure()

    # ---- 拓扑 ----
    def _links(self):
        cfg = getattr(RT.get(self.pid), 'cfg', None) or self.plant.cfg
        return cfg.get('links') or []

    def ensure(self):
        links = self._links()
        p = self.plant
        # 4.3 性能：协议层每个点位每次推送都会调到这里。连线表对象/条数、布局版本、设备数、仿真秒、墙钟半秒都没变时
        # 不再序列化比较（原地改连线端点最迟半秒或下一仿真秒后生效）
        fk = (id(links), len(links), p.layout_version, len(p.stations), int(p.t), int(time.monotonic() * 2))
        if fk == self.__dict__.get('_fast') and self.sig is not None:
            return False
        self._fast = fk
        sig = (p.layout_version, len(p.stations), json.dumps([(l.get('id'), l.get('kind'), l.get('from'), l.get('to'), l.get('protocol')) for l in links
                                                              if l.get('kind') in ('network', 'signal')], ensure_ascii=False))
        if sig == self.sig:
            return False
        self.sig = sig
        old = self.shape()
        self.build(links)
        if self.shape() != old:                   # 只有"哪个网关采集哪些设备"变了才算拓扑变化（协议地址空间按这个重建）
            self.version += 1
        return True

    def shape(self):
        return tuple((g, tuple(sorted(self.serve.get(g, {}))), tuple(self.north(g)) if g in self.plant.stations else ()) for g in self.gateways)

    def build(self, links):
        p = self.plant
        sts = p.stations
        self.links = {l['id']: l for l in links if l.get('kind') in ('network', 'signal') and l.get('id')}
        adj, sig_of = {}, {}
        for l in self.links.values():
            a, b = l.get('from'), l.get('to')
            if a not in sts or b not in sts:
                continue
            if l['kind'] == 'network':
                adj.setdefault(a, []).append((b, l['id']))
                adj.setdefault(b, []).append((a, l['id']))
            else:
                plc, dev = (b, a) if _btype(sts[b]) == 'plc' else (a, b) if _btype(sts[a]) == 'plc' else (b, a)
                sig_of.setdefault(dev, []).append((plc, l['id']))
        self.adj, self.sig_of = adj, sig_of
        plc_devs = {}
        for dev, lst in sig_of.items():
            for plc, lid in lst:
                plc_devs.setdefault(plc, []).append((dev, lid))
        self.gateways = sorted(sid for sid, st in sts.items() if _btype(st) == 'gateway')
        self.serve, self.cons, self.primary = {}, {}, {}
        for g in self.gateways:
            seen, q = {g: ([], [])}, [g]
            ends = []
            while q:
                n = q.pop(0)
                for m, lid in adj.get(n, []):
                    if m in seen:
                        continue
                    path = (seen[n][0] + [lid], seen[n][1] + ([n] if n != g else []))
                    seen[m] = path
                    if _btype(sts[m]) == 'switch':
                        q.append(m)
                    else:
                        ends.append(m)
            serve, cons = {}, {}
            for e in ends:
                t = _btype(sts[e])
                lk, nd = seen[e]
                if t in ('mes', 'scada'):
                    cons[e] = {'links': lk, 'nodes': nd}
                elif t == 'gateway':
                    continue
                else:
                    serve.setdefault(e, {'links': lk, 'nodes': nd, 'via': None})
                    if t == 'plc':
                        for dev, slid in plc_devs.get(e, []):
                            if dev not in serve:
                                serve[dev] = {'links': [slid] + lk, 'nodes': [e] + nd, 'via': e}
            self.serve[g], self.cons[g] = serve, cons
            for d in serve:
                self.primary.setdefault(d, g)
        self._memo_key = None

    def served(self, g):
        self.ensure()
        return self.serve.get(g, {})

    def consumers(self, g):
        self.ensure()
        return self.cons.get(g, {})

    def gateways_of(self, sid):
        self.ensure()
        return [g for g in self.gateways if sid in self.serve.get(g, {})]

    def north(self, g):
        st = self.plant.stations.get(g)
        n = (st.cfg.get('north') if st is not None else None) or ['opcua', 'mqtt']
        if isinstance(n, str):
            n = [x.strip() for x in n.replace('，', ',').split(',') if x.strip()]
        return [x for x in n if x in ('opcua', 'mqtt', 'modbus')]

    # ---- 状态 ----
    def node_down(self, sid):
        st = self.plant.stations.get(sid)
        return st is None or st.failure.repair_left > 0 or not st.enabled

    def link_rules(self, lid):
        """这条线上生效的故障：运行时注入的规则 + 模型里的 link.fault。"""
        from . import comm
        out = [r for r in comm.rules(self.plant) if r.get('protocol') == 'link' and r.get('link') == lid]
        lf = (self.links.get(lid) or {}).get('fault')
        if isinstance(lf, dict) and lf.get('mode'):
            mode = {'loss': 'drop'}.get(lf['mode'], lf['mode'])
            if mode in LINK_MODES:
                key = ('model', lid, json.dumps(lf, sort_keys=True, default=str))
                mf = getattr(self, '_model_rules', {})
                if key not in mf:
                    r = {'id': f'm:{lid}', 'protocol': 'link', 'link': lid, 'mode': mode, 'latency': float(lf.get('latency', 5) or 5),
                         'drop_pct': float(lf.get('drop_pct', lf.get('loss', 30)) or 30), 't0': self.plant.t, 'model': True}
                    if mode == 'freeze':
                        r['_frozen'] = self.snapshot(lid)
                    mf = {k: v for k, v in mf.items() if k[1] != lid}
                    mf[key] = r
                    self._model_rules = mf
                out.append(mf[key])
        return out

    def path_rule(self, g, sid):
        """设备 sid 经网关 g（None = 主网关）到北向的路径上最严重的故障；没有网关 / 不经网关的设备返回 None。"""
        self.ensure()
        g = g or self.primary.get(sid)
        if not g:
            return None
        key = (int(self.plant.t), _comm.version(self.plant))
        if key != self._memo_key:
            self._memo, self._memo_key = {}, key
        mk = (g, sid)
        if mk in self._memo:
            return self._memo[mk]
        path = self.serve.get(g, {}).get(sid)
        best = None
        if path is None:
            best = None
        elif self.node_down(g) or any(self.node_down(n) for n in path['nodes']):
            best = _DOWN
        else:
            for lid in path['links']:
                for r in self.link_rules(lid):
                    best = worse(best, r)
        self._memo[mk] = best
        return best

    def gateway_up(self, g):
        return not self.node_down(g)

    def snapshot(self, lid):
        """冻结开始时，经过这条线的设备的全部点位值（冻结值从这一刻算）。"""
        fz = {}
        for g in self.gateways:
            for d, path in self.serve.get(g, {}).items():
                if lid in path['links'] and d in self.plant.stations:
                    for k, t in self.plant.stations[d].tags.items():
                        fz[f'{d}/{k}'] = t.value
        return fz

    def link_status(self, lid):
        l = self.links.get(lid) or {}
        rs = self.link_rules(lid)
        r = None
        for x in rs:
            r = worse(r, x)
        ends_down = [n for n in (l.get('from'), l.get('to')) if n and self.node_down(n)]
        st = 'down' if (r and r['mode'] == 'disconnect') or ends_down else 'degraded' if r else 'ok'
        return {'status': st, 'fault': _pub(r) if r else None, 'ends_down': ends_down}

    # ---- MES ----
    def mes_status(self, mid):
        rt = self.rt
        mq = getattr(rt, 'mqtt', None)
        clients = 0
        mgr = rt.mgr
        try:
            from .protocols.mqtt import topic_match
            b = mgr.mqtt.broker if mgr.mqtt else None
            subs = set()
            for flt, lst in list(getattr(b, '_subscriptions', {}).items()) if b else []:
                if any(topic_match(flt, t) for t in (f'vfactory/{self.pid}/_mes/part', f'vfactory/{self.pid}/x/ST/Tag')):
                    for sess, _q in lst:
                        if not (sess.client_id or '').startswith('vfactory-') and getattr(getattr(sess, 'transitions', None), 'state', 'connected') == 'connected':
                            subs.add(sess.client_id)
            clients += len(subs)
        except Exception:          # noqa: BLE001
            pass
        try:
            for proto in list(getattr(mgr.opcua.server.bserver, 'clients', [])):
                if getattr(proto.processor, 'session', None) is not None:
                    clients += 1
        except Exception:          # noqa: BLE001
            pass
        rate = mq.mes_rate() if mq is not None and hasattr(mq, 'mes_rate') else 0
        path_up = True
        for g in self.gateways:
            c = self.cons.get(g, {}).get(mid)
            if c is not None:
                path_up = not self.node_down(g) and not any(self.node_down(n) for n in c['nodes']) and \
                    not any((r or {}).get('mode') == 'disconnect' for lid in c['links'] for r in self.link_rules(lid))
                break
        st = self.plant.stations.get(mid)
        url = (st.cfg.get('url') if st is not None else '') or ''
        reach = self.probe(mid, url)
        return {'connected': bool(path_up and not self.node_down(mid) and (clients > 0 or rate > 0)), 'clients': clients, 'mes_per_min': rate,
                'reachable': reach, 'url': url, 'path_up': path_up}

    def mes_blocked(self):
        """所有接了网关的 MES 节点都断了 → _mes 报文先存着（网关断点续传）。没有 MES 节点或没接网关时不拦。"""
        linked = [(g, m, c) for g in self.gateways for m, c in self.cons.get(g, {}).items() if _btype(self.plant.stations.get(m)) == 'mes']
        if not linked:
            return False
        for g, m, c in linked:
            if not self.node_down(g) and not self.node_down(m) and not any(self.node_down(n) for n in c['nodes']) and \
                    not any((r or {}).get('mode') == 'disconnect' for lid in c['links'] for r in self.link_rules(lid)):
                return False
        return True

    def probe(self, mid, url):
        if not url or not url.startswith('http'):
            return False
        p = self._probe.setdefault(mid, {'t': 0, 'ok': False, 'busy': False})
        if time.time() - p['t'] > 30 and not p['busy']:
            p['busy'], p['t'] = True, time.time()

            def go():
                try:
                    with urllib.request.urlopen(url, timeout=3) as r:
                        p['ok'] = r.status < 500
                except urllib.error.HTTPError as e:      # 401/404 也说明服务在
                    p['ok'] = e.code < 500
                except Exception:          # noqa: BLE001
                    p['ok'] = False
                p['busy'] = False
            threading.Thread(target=go, daemon=True).start()
        return p['ok']


def worse(a, b):
    """两条故障里取更严重的（断开 > 坏质量 > 冻结 > 卡死 > 漂移 > 丢包 > 抖动 > 延迟）。"""
    if not a:
        return b
    if not b:
        return a
    ra = SEVERITY.index(a.get('mode')) if a.get('mode') in SEVERITY else 99
    rb = SEVERITY.index(b.get('mode')) if b.get('mode') in SEVERITY else 99
    if ra == rb and a.get('mode') in ('latency', 'jitter'):
        return a if float(a.get('latency', 0)) >= float(b.get('latency', 0)) else b
    return a if ra <= rb else b


def _pub(r):
    return {k: v for k, v in r.items() if not k.startswith('_')}


def attach(rt):
    """工厂启动时调用（沙箱也挂，架构图要用）。"""
    RT[rt.pid] = rt
    rt.plant.net = Network(rt)
    return rt.plant.net


def of(plant):
    return getattr(plant, 'net', None)


# ---------------------------------------------------------------- 网络线故障（运行时）
def set_link_fault(rt, lid, mode, minutes=0.0, **params):
    """在网络线 / 信号线上注入故障（mode 为空 = 恢复）。"""
    from . import comm
    p = rt.plant
    net = of(p)
    if net is None:
        raise ValueError(_tr('工厂没有网络模型'))
    net.ensure()
    if lid not in net.links:
        raise ValueError(_tr('没有网络线 / 信号线 {lid}', lid=lid))
    mode = {'loss': 'drop'}.get(mode, mode) if mode else mode
    old = [r for r in comm.rules(p) if r.get('protocol') == 'link' and r.get('link') == lid]
    for r in old:
        comm.clear(rt, rid=r['id'], quiet=bool(mode))
    if not mode:
        return None
    if mode not in LINK_MODES:
        raise ValueError(_tr('网络线故障只能是 {join}', join=_tr('、').join(_tr('{k}（{v}）', k=k, v=v) for k, v in LINK_MODES.items())))
    rs = comm.rules(p)
    n = max([r['id'] for r in rs if isinstance(r.get('id'), int)] + [getattr(p, '_comm_seq', 0)]) + 1
    p._comm_seq = n
    l = net.links[lid]
    r = {'id': n, 'protocol': 'link', 'link': lid, 'station': None, 'tag': None, 'mode': mode, 'latency': float(params.get('latency') or 5), 't0': p.t,
         'until': p.t + float(minutes) * 60 if minutes else None, 'started': p.clock_str(), 'include_mes': True,
         'from': l.get('from'), 'to': l.get('to')}
    if mode == 'drop':
        r['drop_pct'] = max(0.0, min(100.0, float(params.get('drop_pct') if params.get('drop_pct') not in (None, '') else 30)))
    if mode == 'freeze':
        r['_frozen'] = net.snapshot(lid)
    rs.append(r)
    p.log('SIGNAL', 'comm', _tr('网络故障：{describe}', describe=comm.describe(r)) + (_tr('，{float:g} 分钟后恢复', float=float(minutes)) if minutes else ''))
    p.label_open(f'LINK:{lid}', 'comm', comm.describe(r), protocol='link', mode=mode)
    comm._bump(p)
    return r


# ---------------------------------------------------------------- 架构图数据
def architecture(rt):
    """GET /api/p/<厂>/architecture：按层的节点、网络线和信号线（含实时状态和故障）、每个网关采集/上报情况、MES 连接状态。"""
    from .flow.catalog import BLOCK_TYPES, LAYERS
    p = rt.plant
    net = of(p) or attach(rt)
    net.ensure()
    mq = getattr(rt, 'mqtt', None)
    nodes = []
    for sid, st in p.stations.items():
        t = _btype(st)
        layer = BLOCK_TYPES.get(t, {}).get('layer', 'process')
        if st.kind in ('crew',) or t == 'buffer':
            continue
        down = net.node_down(sid)
        n = {'id': sid, 'name': st.name, 'type': t, 'kind': st.kind, 'layer': layer, 'state': st.state, 'alarm': st.alarm,
             'status': 'down' if down and layer in ('network', 'it', 'control') else 'fault' if st.state == 'Stopped' or st.alarm else 'ok',
             'pos': st.pos, 'gateways': net.gateways_of(sid) if layer in ('process', 'control') else []}
        if layer == 'process':
            n['field'] = {'points': len(st.tags), 'writable': sum(1 for x in st.tags.values() if x.writable),
                          'components': len(((getattr(st, 'cell_def', None) or {}).get('components')) or [])}
            n['plc'] = [plc for plc, _l in net.sig_of.get(sid, [])]
        if t == 'gateway':
            n['north'] = net.north(sid)
        if t == 'mes':
            n['mes'] = net.mes_status(sid)
        if t == 'plc':
            try:
                n['live'] = st.view()
            except Exception:          # noqa: BLE001
                n['live'] = None
            n['devices'] = [d for d, lst in net.sig_of.items() if any(x == sid for x, _ in lst)]
        nodes.append(n)
    links = []
    for lid, l in net.links.items():
        s = net.link_status(lid)
        d = {'id': lid, 'kind': l['kind'], 'from': l.get('from'), 'to': l.get('to'), 'protocol': l.get('protocol'), **s}
        if l['kind'] == 'signal':
            sg = l.get('signals') or []
            d['signals'] = len(sg)
            d['in'] = sum(1 for x in sg if x.get('dir') == 'in')
            d['out'] = sum(1 for x in sg if x.get('dir') == 'out')
        d['carries'] = sorted({dev for g in net.gateways for dev, path in net.serve.get(g, {}).items() if lid in path['links']})
        links.append(d)
    gws = []
    for g in net.gateways:
        sv = net.serve.get(g, {})
        north = net.north(g)
        pts = sum(len(p.stations[d].tags) for d in sv if d in p.stations)
        gws.append({'id': g, 'name': p.stations[g].name, 'online': not net.node_down(g), 'north': north, 'devices': sorted(sv),
                    'devices_down': sorted(d for d in sv if (net.path_rule(g, d) or {}).get('mode') == 'disconnect'),
                    'consumers': sorted(net.cons.get(g, {})), 'points': pts,
                    'published': {'opcua_nodes': pts if 'opcua' in north else 0,
                                  'mqtt_msgs': (mq.gw_stats.get(g, 0) if mq is not None and hasattr(mq, 'gw_stats') else 0) if 'mqtt' in north else 0,
                                  'modbus_units': len({rt.modbus.unit_of.get(d) for d in sv if getattr(rt.modbus, 'unit_of', {}).get(d)}) if 'modbus' in north else 0},
                    'addresses': {'opcua': _tr('ns=2;s={pid}/{g}/<设备>/<点位>', pid=rt.pid, g=g) if 'opcua' in north else None,
                                  'mqtt': _tr('vfactory/{pid}/{g}/<设备>/<点位>', pid=rt.pid, g=g) if 'mqtt' in north else None}})
    process = [n['id'] for n in nodes if n['layer'] == 'process']
    return {'plant': rt.pid, 'layers': LAYERS, 'order': ['it', 'network', 'control', 'process', 'field'], 'nodes': nodes, 'links': links, 'gateways': gws,
            'unassigned': sorted(d for d in process if not net.gateways_of(d)) if net.gateways else [],
            'has_gateways': bool(net.gateways), 'link_modes': LINK_MODES, 'time': p.clock_str()}
