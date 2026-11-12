"""MQTT：内置 Broker（amqtt），按统一命名空间（UNS）发布点位，并接受 .../set 写入。

主题：vfactory/<工厂>/<区域>/<工位>/<点位>，retain，载荷
  {"value": …, "unit": …, "quality": "good"|"bad", "ts": …, "sim_ts": …, "wall_ts": …}
  ts 是对外时间（协议设置：仿真时间或墙钟），sim_ts / wall_ts 两个都给；都是带时区的 ISO 8601。
  只在值或质量变化时发（report by exception）；进入坏质量时每个点只发一次 quality=bad。
写入：向 <点位主题>/set 发布 {"value": …, "id": "可选请求号"}、纯数值或 "true"/"false"。
  结果发到 <点位主题>/set/ack：{"ok": true/false, "value", "error", "code", "id", "ts"…}；失败同时发到 vfactory/<工厂>/_errors。
  带 retain 标志的 /set 消息不执行（防止 Broker 重启后把旧命令再执行一遍），回执里说明原因。
有网关的工厂（4.3）：每个北向含 mqtt 的网关另发 vfactory/<工厂>/<网关>/<设备>/<点位>（写入同样 …/set、回执 …/set/ack），
  网关状态 vfactory/<工厂>/<网关>/_status {online, devices, devices_down}；旧主题照发（是主网关的别名，协议设置 mqtt.legacy_topics 可关）。
  网络线 / 交换机 / 网关故障按路径作用；设备到网关的路断了，它的 _mes 报文存在网关，路通后补发；网关到 MES 的路断了，全部 _mes 先存着。
心跳：vfactory/<工厂>/_status（retain）{"online", "ts", "sim_ts", "wall_ts", "speed", "paused"}，按协议设置的间隔重发。
AGV 另按 VDA 5050 风格发布 vda5050/v2/<工厂>/<AGV>/state。
5.0 动作级信号（Actions/…，见 vfactory/actions.py）：每次变化单独发一条，ts / sim_ts 是动作发生的精确时刻（毫秒），不靠轮询比对。
5.0 原始现场模式（plant.raw_site，见 vfactory/rawsite.py）：点位主题换成集成商风格（vfactory/<工厂>/edge01/PLC2/DB10.DBD4、…/jj/M3_ZZFZ），
  不再发按网关组织的主题；有一台 PLC 的载荷是纯文本数值。_status、_mes、VDA 5050 不变。
MES 网关（相当于产线扫码枪 / PLC 报工经网关上送）：
  vfactory/<工厂>/_mes/part   每个零件事件 {sn, type, station, event, t, data, attrs?, sim_ts, wall_ts}（不含仿真真值）
  vfactory/<工厂>/_mes/event  生产日志 {seq, t, station, kind, msg, ...结构化字段, sim_ts, wall_ts}
  协议级的冻结/断开期间 _mes 消息先存着、恢复后补发（像网关的断点续传）；延迟/抖动/丢包同样作用于 _mes。注入故障时可以选择不影响 _mes。
认证与权限（全局设置 mqtt_auth.anonymous）：
  rw   匿名可读写（默认，和旧版一致）     ro   匿名只读（不能写 /set）     none  必须登录
  登录：用户名随意，密码填 API 令牌（vf_ 开头）。令牌范围 read 只能订阅；write/control/admin 可以写 /set；限定了工厂的令牌只能碰那些工厂的主题。
"""
from ..i18n import _tr
import asyncio
import heapq
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import timedelta

from amqtt.contexts import Action
from amqtt.plugins.base import BaseAuthPlugin, BaseTopicPlugin

from .. import comm, rawsite
from ..actions import events_since

log = logging.getLogger('vfactory.mqtt')
AREA_CODE = {'熔炼区': 'melting', '造型区': 'molding', '清理区': 'cleaning', '机加区': 'machining', '检测区': 'inspection',
             '仓储区': 'warehouse', '物流': 'logistics', '人员': 'people', '收货区': 'receiving'}
MAX_TAG_DEPTH = 8


def topic_of(pid, st, tname):
    return f"vfactory/{pid}/{AREA_CODE.get(st.area, 'other')}/{st.id}/{tname}"


def gw_topic(pid, g, st, tname):
    """按网关组织的主题（4.3，有网关的工厂）：vfactory/<厂>/<网关>/<设备>/<点位>"""
    return f'vfactory/{pid}/{g}/{st.id}/{tname}'


def topic_match(flt, topic):
    """MQTT 通配符匹配（+ 单层、# 多层）。"""
    f, t = flt.split('/'), topic.split('/')
    for i, x in enumerate(f):
        if x == '#':
            return True
        if i >= len(t) or (x != '+' and x != t[i]):
            return False
    return len(f) == len(t)


def plant_of_topic(topic):
    """主题属于哪个工厂（vfactory/<工厂>/… 或 vda5050/v2/<工厂>/…）。"""
    p = topic.split('/')
    if len(p) > 1 and p[0] == 'vfactory':
        return p[1]
    if len(p) > 2 and p[0] == 'vda5050':
        return p[2]
    return None


def _internal(session):
    cid = getattr(session, 'client_id', '') or ''
    addr = str(getattr(session, 'remote_address', '') or '')
    return cid.startswith('vfactory-') and (addr in ('127.0.0.1', '::1', 'localhost') or addr.startswith('127.'))


class _SnapshotDict(dict):
    """遍历时用快照（keys/items/values/iter），避免 await 期间被并发修改。"""

    def __iter__(self):
        return iter(list(super().keys()))

    def keys(self):
        return list(super().keys())

    def items(self):
        return list(super().items())

    def values(self):
        return list(super().values())


class VfAuthPlugin(BaseAuthPlugin):
    """认证：匿名按全局设置；密码是 API 令牌时按令牌范围。"""

    @dataclass
    class Config:
        pass

    async def authenticate(self, *, session=None):
        hub = MqttHub.instance
        return hub.authenticate(session) if hub else True


class VfTopicPlugin(BaseTopicPlugin):
    """主题权限：只读令牌不能写；限定工厂的令牌只能碰自己的工厂；"断开"中的工厂拒绝外部订阅和写入。"""

    @dataclass
    class Config:
        pass

    async def topic_filtering(self, *, session=None, topic=None, action=None):
        hub = MqttHub.instance
        return hub.allow(session, topic, action) if hub else True


class MqttHub:
    """内置 Broker，只启动一次；每个工厂一个 MqttAdapter。"""
    instance = None

    def __init__(self, port=1883):
        self.port = port
        self.plants: dict[str, 'MqttAdapter'] = {}
        self.auth = {'anonymous': 'rw'}
        self.broker = None

    def load_auth(self):
        try:
            from .. import store
            r = store.q("select v from settings where k='mqtt_auth'", one=True)
            if r:
                self.auth.update(json.loads(r['v']))
        except Exception:
            pass
        return self.auth

    def save_auth(self, body):
        from .. import store
        mode = (body or {}).get('anonymous')
        if mode not in ('rw', 'ro', 'none'):
            raise ValueError(_tr('匿名访问只能是 rw（读写）/ ro（只读）/ none（禁止）'))
        self.auth['anonymous'] = mode
        store.x("insert or replace into settings(k,v) values('mqtt_auth',?)", (json.dumps(self.auth),))
        return self.auth

    async def start(self):
        from amqtt.broker import Broker
        MqttHub.instance = self
        self.load_auth()
        listeners = {'default': {'type': 'tcp', 'bind': f'0.0.0.0:{self.port}'}}
        cfgs = [{'listeners': listeners, 'plugins': {'vfactory.protocols.mqtt.VfAuthPlugin': {}, 'vfactory.protocols.mqtt.VfTopicPlugin': {}}},
                {'listeners': listeners, 'plugins': {'amqtt.plugins.authentication.AnonymousAuthPlugin': {'allow_anonymous': True}}}]
        for i, cfg in enumerate(cfgs):
            try:
                self.broker = Broker(cfg)
                # amqtt 在新连接时一边遍历全部订阅一边 await，期间别的客户端订阅/退订会 "dictionary changed size during iteration"，
                # 新客户端被断开、订阅卡死（联调台跑剧本时偶发）。换成遍历快照的字典。
                if isinstance(getattr(self.broker, '_subscriptions', None), dict):
                    self.broker._subscriptions = _SnapshotDict(self.broker._subscriptions)
                await self.broker.start()
                if i:
                    log.warning(_tr('MQTT 认证插件没加载上，Broker 以匿名模式运行'))
                break
            except Exception:
                log.exception(_tr('内置 MQTT Broker 启动失败（端口被占用？）') + (_tr('，改用匿名模式重试') if not i else _tr('，改为连接本机已有 Broker')))
                self.broker = None
        log.info('MQTT broker on :%s', self.port)

    # ---------- 认证与主题权限 ----------
    def authenticate(self, session):
        if session is None:
            return False
        if _internal(session):
            session._vf = {'scope': 'admin', 'plants': None, 'internal': True}
            return True
        pw = getattr(session, 'password', None)
        if isinstance(pw, (bytes, bytearray)):
            pw = pw.decode('utf-8', 'replace')
        if pw:
            from .. import store
            u = store.user_from_token(str(pw), ip=str(getattr(session, 'remote_address', '') or ''), mark=True)
            if not u or not str(pw).startswith('vf_'):
                log.info(_tr('MQTT 登录失败：%s（密码需要是有效的 API 令牌）'), getattr(session, 'client_id', ''))
                return False
            t = u.get('token') or {}
            scope = t.get('scope') or {'admin': 'admin', 'engineer': 'control', 'teacher': 'control', 'student': 'read'}.get(u['role'], 'read')
            session._vf = {'scope': scope, 'plants': t.get('plants') or None, 'user': u['username']}
            return True
        mode = self.auth.get('anonymous', 'rw')
        if mode == 'none':
            log.info(_tr('MQTT 拒绝匿名连接：%s'), getattr(session, 'client_id', ''))
            return False
        session._vf = {'scope': 'write' if mode == 'rw' else 'read', 'plants': None, 'anonymous': True}
        return True

    def allow(self, session, topic, action):
        if not topic:
            return False
        vf = getattr(session, '_vf', None) if session is not None else None
        if vf and vf.get('internal'):
            return True
        if action == Action.RECEIVE:
            if vf and vf.get('plants'):
                pid = plant_of_topic(topic)
                return pid is None or pid in vf['plants']
            return True
        pid = plant_of_topic(topic)
        if action == Action.SUBSCRIBE:
            if vf and vf.get('plants'):
                if pid is None or ('+' in pid or '#' in pid):
                    return topic.startswith('$SYS')
                if pid not in vf['plants']:
                    return False
            if pid and pid in self.plants and self.plants[pid].offline:
                return False
            return True
        if action == Action.PUBLISH:
            if pid and pid in self.plants and self.plants[pid].offline:
                return False
            if vf and vf.get('plants') and pid not in vf['plants']:
                return False
            if topic.endswith('/set'):
                return not vf or vf.get('scope') in ('write', 'control', 'admin')
            return not vf or vf.get('scope') in ('write', 'control', 'admin')
        return True

    async def kick_plant(self, pid):
        """踢掉订阅了本厂主题的外部客户端（"断开"故障）。"""
        b = self.broker
        if not b:
            return 0
        samples = [f'vfactory/{pid}/x/ST/Tag', f'vfactory/{pid}/_status', f'vfactory/{pid}/_mes/event', f'vda5050/v2/{pid}/AGV1/state']
        victims = set()
        for flt, subs in list(getattr(b, '_subscriptions', {}).items()):
            if any(topic_match(flt, s) for s in samples):
                for sess, _q in subs:
                    if not _internal(sess):
                        victims.add(sess.client_id)
        n = 0
        for cid in victims:
            pair = b._sessions.get(cid)
            if not pair:
                continue
            _sess, handler = pair
            try:
                w = getattr(handler, 'writer', None)
                if w is not None:
                    r = w.close()
                    if asyncio.iscoroutine(r):
                        await r
                    n += 1
                    log.info(_tr('MQTT 断开客户端 %s（%s 通讯断开）'), cid, pid)
            except Exception:
                log.debug('kick %s', cid, exc_info=True)
        return n


class MqttAdapter:
    def __init__(self, pid, plant, port=1883, period=1.0):
        self.pid, self.plant, self.port, self.period = pid, plant, port, period
        self.last = {}
        self.mesq: deque = deque(maxlen=50000)
        self.outq: list = []
        self.oseq = 0
        self.offline = False
        self.stats = {'published': 0, 'dropped': 0, 'writes': 0, 'write_errors': 0}
        self.gw_stats: dict = {}          # 网关 → 已发的点位报文数
        self.gw_last: dict = {}           # 网关 → 上次发的 _status
        self.mes_held: list = []          # 网络断开期间存着的 _mes 报文（恢复后按顺序补发）
        self.mes_times: deque = deque(maxlen=20000)
        self.raw = rawsite.enabled(plant)  # 原始现场模式（切换时整个适配器重建）
        self.act_seq = getattr(plant, 'act_seq', 0)   # 动作事件游标：从现在起发，不补历史
        self.retained: set = set()        # 发过的 retain 主题（切换命名时清掉，免得新订阅者收到旧名字）
        self.gws: dict = {}
        self.stopped = False

    def _rn(self):
        """原始现场命名表（每秒最多重算一次签名，免得每个点位都去数一遍全厂点位）。"""
        now = time.monotonic()
        if getattr(self, '_rn_t', 0) + 1.0 < now or getattr(self, '_rn_m', None) is None:
            self._rn_t, self._rn_m = now, rawsite.names(self.plant)
        return self._rn_m

    def topic(self, st, tname):
        if self.raw:
            r = self._rn().get((st.id, tname))
            if r:
                return f"vfactory/{self.pid}/{r['topic']}"
        return topic_of(self.pid, st, tname)

    def _plain(self, st, tname):
        if not self.raw:
            return False
        r = self._rn().get((st.id, tname))
        return bool(r and r['plain'])

    def ev_stamp(self, t):
        """动作事件的时间戳：事件自己的仿真时刻（毫秒）；墙钟模式按当前倍速折算。"""
        p = self.plant
        s = comm.sim_dt(p, t)
        w = comm.wall_dt() - timedelta(seconds=max(0.0, p.t - t) / max(0.1, p.speed))
        return {'ts': comm.iso(w if comm.settings(p)['time'] == 'wall' else s, True), 'sim_ts': comm.iso(s, True), 'wall_ts': comm.iso(w, True)}

    BIRTH_ATTRS = ('heat', 'ladle', 'mold', 'cavity', 'pour_temp', 'mg', 'sand_moisture', 'compactability', 'ce')

    def _on_part(self, part, station, what, data):
        msg = {'sn': part['id'], 'type': part.get('type'), 'station': station, 'event': what, 't': self.plant.clock_str(),
               'data': {k: v for k, v in data.items() if k not in ('truth',)}, 'status': part.get('status')}
        if what in ('poured', 'received'):
            msg['attrs'] = {k: part.get(k) for k in self.BIRTH_ATTRS if part.get(k) is not None}
            if what == 'received':
                msg['attrs']['supplier'] = part.get('heat')
        st = comm.stamps(self.plant)
        msg['sim_ts'], msg['wall_ts'] = st['sim_ts'], st['wall_ts']
        self.mesq.append(('part', msg))

    def _on_event(self, ev):
        st = comm.stamps(self.plant)
        self.mesq.append(('event', {**ev, 'sim_ts': st['sim_ts'], 'wall_ts': st['wall_ts']}))

    async def start(self):
        from amqtt.client import MQTTClient
        self.pub = MQTTClient(client_id=f'vfactory-pub-{self.pid}')
        await self.pub.connect(f'mqtt://127.0.0.1:{self.port}/')
        self.sub = MQTTClient(client_id=f'vfactory-sub-{self.pid}')
        await self.sub.connect(f'mqtt://127.0.0.1:{self.port}/')
        # 只订阅写入主题：vfactory/<厂>/<区>/<设备>/<点位 1..N 层>/set（不再收自己发出的上千个点位主题）
        await self.sub.subscribe([(f'vfactory/{self.pid}/+/+/' + '+/' * n + 'set', 0) for n in range(1, MAX_TAG_DEPTH + 1)])
        if self.raw:                      # 原始现场：主题层数不固定，可写点位逐个订阅 …/set
            sets = [(self.topic(st, t) + '/set', 0) for st in list(self.plant.stations.values()) for t, tag in st.tags.items() if tag.writable]
            for i in range(0, len(sets), 200):
                await self.sub.subscribe(sets[i:i + 200])
        self.plant.part_hooks.append(self._on_part)
        self.plant.event_hooks.append(self._on_event)
        if MqttHub.instance:
            MqttHub.instance.plants[self.pid] = self
        self.tasks = [asyncio.create_task(self.loop()), asyncio.create_task(self.listen()), asyncio.create_task(self.mes_loop()),
                      asyncio.create_task(self.sender())]

    async def stop(self, clear_retained=False):
        # 先让发布循环自己退出（cancel 打断 amqtt 的 publish 时会变成 ProtocolHandlerError 被循环吞掉，旧循环会接着用旧名字发）
        self.stopped = True
        own = [t for t in self.tasks if t is not self.tasks[1]]        # listen 一直等收消息，只能 cancel
        try:
            await asyncio.wait(own, timeout=max(3.0, self.period * 3))
        except Exception:
            pass
        for t in self.tasks:
            t.cancel()
        if MqttHub.instance and MqttHub.instance.plants.get(self.pid) is self:
            del MqttHub.instance.plants[self.pid]
        for lst, f in ((self.plant.part_hooks, self._on_part), (self.plant.event_hooks, self._on_event)):
            if f in lst:
                lst.remove(f)
        if clear_retained:                        # 换命名（原始现场开 / 关）：清掉旧主题的 retain，新订阅者不会再收到旧名字
            # 本适配器发过的 + Broker 里本厂的其它点位 retain（以前的运行、已删掉的设备留下的），_status / _mes 不动
            pre = f'vfactory/{self.pid}/'
            try:
                b = MqttHub.instance.broker if MqttHub.instance else None
                for k in list(getattr(b, '_retained_messages', {}) or {}):
                    if k.startswith(pre) and not k.endswith('/_status') and not k[len(pre):].startswith('_'):
                        self.retained.add(k)
            except Exception:
                log.debug('retained scan', exc_info=True)
            n = 0
            try:
                tops = list(self.retained)
                # QoS 1、逐条等 Broker 确认（QoS 0 + 断开会丢掉 Broker 还没处理的清除；amqtt 并发 QoS 1 也会丢）
                for tp in tops:
                    await self.pub.publish(tp, b'', qos=1, retain=True)
                    n += 1
            except Exception:
                log.exception('mqtt clear retained')
            log.info(_tr('MQTT %s 换命名：清掉 %d / %d 个旧主题的 retain'), self.pid, n, len(self.retained))
            self.retained.clear()
        for c in (self.pub, self.sub):
            try:
                await c.disconnect()
            except Exception:
                pass

    # ---------- 发送（延迟/抖动经队列） ----------
    async def _send(self, topic, body, retain=False, delay=0.0):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        if retain:
            self.retained.add(topic)
        if delay > 0:
            self.oseq += 1
            heapq.heappush(self.outq, (time.time() + delay, self.oseq, topic, data, retain))
            return
        await self.pub.publish(topic, data, qos=0, retain=retain)
        self.stats['published'] += 1

    async def sender(self):
        while not self.stopped:
            try:
                now = time.time()
                while self.outq and self.outq[0][0] <= now and not self.stopped:
                    _d, _s, topic, data, retain = heapq.heappop(self.outq)
                    if self.offline:
                        continue
                    await self.pub.publish(topic, data, qos=0, retain=retain)
                    self.stats['published'] += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                if self.stopped:
                    return
                log.exception('mqtt delayed publish')
            await asyncio.sleep(0.05)

    async def loop(self):
        online, last_hb, last_kick = None, 0.0, 0.0
        while not self.stopped:
            try:
                p = self.plant
                pr = comm.protocol_rule(p, 'mqtt')
                pmode = pr.get('mode') if pr else None
                self.offline = pmode == 'disconnect'
                now_online = not self.offline
                hb = comm.settings(p)['mqtt'].get('heartbeat_s') or 0
                if now_online != online or (hb and time.time() - last_hb >= hb):
                    online, last_hb = now_online, time.time()
                    await self._send(f'vfactory/{self.pid}/_status', {'online': online, **comm.stamps(p), 'speed': p.speed, 'paused': p.paused,
                                                                      'time_mode': comm.settings(p)['time']}, retain=True)
                    net = getattr(p, 'net', None)
                    if net is not None and net.gateways:
                        await self.gw_status(net, comm.stamps(p))
                if self.offline:
                    if time.time() - last_kick > 2 and MqttHub.instance:
                        last_kick = time.time()
                        await MqttHub.instance.kick_plant(self.pid)
                else:
                    await self.publish_events()
                    await self.publish(pmode)
                    net = getattr(p, 'net', None)
                    if net is not None and net.gateways:
                        await self.gw_status(net)
            except asyncio.CancelledError:
                raise
            except Exception:
                if self.stopped:
                    return
                log.exception('mqtt publish')
            await asyncio.sleep(self.period)

    async def mes_loop(self):
        while not self.stopped:
            try:
                pr = comm.protocol_rule(self.plant, 'mqtt')
                hold = pr and pr.get('include_mes', True) and pr.get('mode') in ('freeze', 'disconnect')
                net = getattr(self.plant, 'net', None)
                if net is not None and net.gateways and not hold:
                    if net.mes_blocked():               # 网关到 MES 的路断了：全部存着
                        hold = True
                    elif self.mes_held:                 # 路通了：先补发存着的（设备那段路还断着的继续存）
                        keep, rel = [], []
                        for kind, msg in self.mes_held:
                            (keep if self._st_down(net, msg) else rel).append((kind, msg))
                        self.mesq.extendleft(reversed(rel))
                        self.mes_held = keep
                n = 0
                while self.mesq and n < 3000 and not hold:
                    kind, msg = self.mesq.popleft()
                    n += 1
                    if net is not None and net.gateways and self._st_down(net, msg):
                        self.mes_held.append((kind, msg))      # 这台设备到网关的路断了：报工 / 事件先存在网关
                        continue
                    if pr and pr.get('include_mes', True):
                        if comm.dropped(pr):
                            self.stats['dropped'] += 1
                            continue
                        d = comm.delay_of(pr)
                    else:
                        d = 0
                    await self._send(f'vfactory/{self.pid}/_mes/{kind}', msg, delay=d)
                    self.mes_times.append(time.time())
            except asyncio.CancelledError:
                raise
            except Exception:
                if self.stopped:
                    return
                log.exception('mqtt mes publish')
            await asyncio.sleep(0.2)

    def _st_down(self, net, msg):
        sid = msg.get('station') if isinstance(msg, dict) else None
        return bool(sid) and sid in self.plant.stations and (net.path_rule(None, sid) or {}).get('mode') == 'disconnect'

    def mes_rate(self):
        now = time.time()
        return sum(1 for t in self.mes_times if now - t < 60)

    async def gw_status(self, net, stamp=None):
        """每个网关一个 _status（在线、采集设备数、链路中断的设备）。变化时发，心跳时重发。"""
        p = self.plant
        for g in net.gateways:
            if 'mqtt' not in net.north(g):
                continue
            sv = net.served(g)
            body = {'online': net.gateway_up(g), 'devices': len(sv), 'devices_down': sorted(d for d in sv if (net.path_rule(g, d) or {}).get('mode') == 'disconnect')}
            if self.gw_last.get(g) != body or stamp is not None:
                self.gw_last[g] = body
                await self._send(f'vfactory/{self.pid}/{g}/_status', {**body, **(stamp or comm.stamps(p))}, retain=True)

    async def _point(self, topic, key, st, tname, tag, gw, stamp_box, value=None, stamp=None):
        """一个点位主题：值或质量变了才发。value / stamp 给了 = 动作事件（值和精确时间戳由事件带来）。"""
        p = self.plant
        r = comm.effective(p, 'mqtt', st.id, tname, gw)
        mode = r.get('mode') if r else None
        if mode == 'disconnect':
            return
        if stamp is None and tag.event and key in self.last:
            go = self._gw_only(st.id)
            if (gw is None and not go) or (gw is not None and go and gw == self.gws[st.id][0]):
                return                                      # 动作点位在主主题上只按事件发（publish_events）；网关别名主题按周期发最新值
        val = comm.view(p, r, f'{st.id}/{tname}', tag.value if stamp is None else value, tag.dtype)
        q = 'bad' if mode == 'bad' else 'good'
        if self.last.get(key) == (val, q):
            return
        self.last[key] = (val, q)
        if mode == 'drop' and comm.dropped(r):
            self.stats['dropped'] += 1
            return
        if stamp is None:
            if stamp_box[0] is None:
                stamp_box[0] = comm.stamps(p)
            stamp = stamp_box[0]
        v = val if not isinstance(val, float) or val == val else None
        if self.raw and self._plain(st, tname):              # 原始现场：这台 PLC 的网关只发纯文本数值
            body = ('' if v is None else str(int(v)) if isinstance(v, bool) else str(v)).encode()
        else:
            body = {'value': v, 'unit': tag.unit, 'quality': q, **stamp}
        await self._send(topic, body, retain=True, delay=comm.delay_of(r))
        if gw:
            self.gw_stats[gw] = self.gw_stats.get(gw, 0) + 1

    async def publish(self, pmode=None):
        p = self.plant
        box = [None]
        net = getattr(p, 'net', None)
        gws = {}
        if net is not None:
            net.ensure()
            if not self.raw:                              # 原始现场模式没有按网关组织的主题
                for g in net.gateways:
                    if 'mqtt' in net.north(g) and net.gateway_up(g):
                        for d in net.served(g):
                            gws.setdefault(d, []).append(g)
        self.gws = gws
        legacy = not gws or comm.settings(p)['mqtt'].get('legacy_topics', True)
        for st in list(p.stations.values()):
            for tname, tag in st.tags.items():
                if not tag.mqtt:
                    continue
                if legacy or st.id not in gws:            # 旧主题（有网关时是主网关的别名）
                    await self._point(self.topic(st, tname), (st.id, tname), st, tname, tag, None, box)
                for g in gws.get(st.id, ()):              # 按网关组织的主题
                    await self._point(gw_topic(self.pid, g, st, tname), (g, st.id, tname), st, tname, tag, g, box)
            stamp = box[0]
            ra = comm.effective(p, 'mqtt', st.id, '') if st.kind == 'agv' else None
            if st.kind == 'agv' and (ra or {}).get('mode') not in ('freeze', 'disconnect', 'stuck'):
                ts = (stamp or comm.stamps(p))['ts']
                for a in st.agvs:
                    if comm.dropped(ra):
                        continue
                    payload = {'headerId': int(p.t), 'timestamp': ts, 'version': '2.0.0', 'manufacturer': 'VirtualFactory',
                               'serialNumber': a['id'], 'orderId': a['task'], 'driving': a['state'] == 'Moving',
                               'agvPosition': {'x': round(a['x'], 2), 'y': round(a['y'], 2), 'mapId': 'plant', 'positionInitialized': True},
                               'batteryState': {'batteryCharge': round(a['soc'], 1), 'charging': a['state'] == 'Charging'},
                               'loads': [{'loadId': x['id']} for x in a['load']], 'operatingMode': 'AUTOMATIC',
                               'errors': [{'errorType': 'blocked', 'errorLevel': 'WARNING'}] if a['state'] == 'Blocked' else []}
                    await self._send(f"vda5050/v2/{self.pid}/{a['id']}/state", payload, delay=comm.delay_of(ra))

    async def publish_events(self):
        """动作级信号：每个变化一条，时间戳是动作的精确时刻。"""
        p = self.plant
        self.act_seq, evs = events_since(p, self.act_seq)
        if not evs:
            return
        # 精确事件只发在"主"主题上（点表里的那个：旧主题；关了旧主题时是主网关的主题），网关别名主题由周期发布带最新值，省一半报文
        stamps = {}
        for i, (_seq, t, sid, tname, v) in enumerate(evs):
            st = p.stations.get(sid)
            tag = st.tags.get(tname) if st is not None else None
            if tag is None or not tag.mqtt:
                continue
            stamp = stamps.get(t)
            if stamp is None:
                stamp = stamps[t] = self.ev_stamp(t)
            if not self._gw_only(sid):
                await self._point(self.topic(st, tname), (sid, tname), st, tname, tag, None, None, value=v, stamp=stamp)
            else:
                g = self.gws[sid][0]
                await self._point(gw_topic(self.pid, g, st, tname), (g, sid, tname), st, tname, tag, g, None, value=v, stamp=stamp)
            if i % 200 == 199:
                await asyncio.sleep(0)

    def _gw_only(self, sid):
        """这台设备只有网关主题（协议设置关了旧主题）。"""
        return bool(self.gws.get(sid)) and not comm.settings(self.plant)['mqtt'].get('legacy_topics', True)

    # ---------- 写入 ----------
    @staticmethod
    def parse(raw: bytes):
        """载荷 → (值, 请求号, 错误)。支持 {"value": x, "id": …}、纯数值、true/false、带引号的字符串。"""
        s = raw.decode('utf-8', 'replace').strip()
        if not s:
            return None, None, _tr('载荷为空')
        try:
            v = json.loads(s)
        except ValueError:
            return s, None, ''                        # 不是 JSON：按原文（例如 on / off）
        if isinstance(v, dict):
            if 'value' not in v:
                return None, v.get('id'), _tr('对象载荷需要 value 字段，例如 {"value": 12.5}')
            return v['value'], v.get('id'), ''
        if isinstance(v, list):
            return None, None, _tr('不支持数组载荷')
        return v, None, ''

    async def listen(self):
        while True:
            try:
                msg = await self.sub.deliver_message()
                topic = msg.topic
                if not topic.endswith('/set'):
                    continue
                await self.handle_set(topic, msg.data or b'', bool(getattr(msg, 'retain', False)))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('mqtt listen')
                await asyncio.sleep(1)

    async def handle_set(self, topic, data, retain=False):
        p = self.plant
        parts = topic.split('/')
        sid, tname = (parts[3], '/'.join(parts[4:-1])) if len(parts) > 5 else (None, None)
        net = getattr(p, 'net', None)
        gw = parts[2] if net is not None and len(parts) > 5 and parts[2] in net.gateways else None
        if self.raw:                                   # 原始现场：按主题反查设备和点位
            pre = f'vfactory/{self.pid}/'
            hit = rawsite.by_topic(p, topic[len(pre):-len('/set')]) if topic.startswith(pre) and topic.endswith('/set') else None
            sid, tname = hit if hit else (None, None)
            gw = None
        val, rid, err = self.parse(data)
        code = 'format' if err else ''
        st = p.stations.get(sid) if sid else None
        if not err and retain:
            code, err = 'retained', _tr('带 retain 标志的写入不执行（发布 /set 时请不要设 retain）')
        if not err and self.offline:
            code, err = 'offline', _tr('通讯断开中')
        if not err and st is None:
            code, err = 'notfound', _tr('没有设备 {sid}', sid=sid)
        if not err and gw and sid not in net.served(gw):
            code, err = 'notfound', _tr('网关 {gw} 没有采集设备 {sid}', gw=gw, sid=sid)
        if not err and not gw and topic != self.topic(st, tname) + '/set':
            code, err = 'notfound', _tr('主题不对，应为 {topic}/set', topic=self.topic(st, tname))
        if not err and (comm.effective(p, 'mqtt', st.id, tname, gw) or {}).get('mode') == 'disconnect':
            code, err = 'offline', _tr('{sid} 到网关的网络断开，写不到设备', sid=sid)
        if not err:
            code, err = comm.write_tag(p, st, tname, val, 'MQTT')
        ack = {'ok': not err, 'value': st.tags[tname].value if not err and st and tname in st.tags else val, 'id': rid, **comm.stamps(p)}
        if err:
            ack.update(error=err, code=code)
            self.stats['write_errors'] += 1
            log.info(_tr('MQTT 写入被拒绝：%s %s'), topic, err)
            await self._send(f'vfactory/{self.pid}/_errors', {'topic': topic, 'payload': data.decode('utf-8', 'replace')[:500], 'error': err, 'code': code, 'id': rid,
                                                               **comm.stamps(p)})
        else:
            self.stats['writes'] += 1
            self.last.pop((st.id, tname), None)      # 下个周期把新值发出去
        await self._send(topic + '/ack', ack)

    def points(self):
        return {f'{st.id}/{t}': self.topic(st, t) for st in list(self.plant.stations.values()) for t in st.tags}
