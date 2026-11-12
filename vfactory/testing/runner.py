"""测试剧本运行器（联调工作区 / 命令行 CI 共用）。

剧本 JSON：
{
  "name": "CNC1 断刀后 MES 收到报警",
  "speed": 60,                      运行期间的仿真倍速（结束后恢复原值）；不填保持当前
  "steps": [
    {"kind": "set_tag",    "station": "INS1", "tag": "Monitoring/Light", "value": 0.4}     直接改点位值（模拟传感器）
    {"kind": "setpoint",   "station": "INS1", "tag": "Setpoint/Sensitivity", "value": 0.8} 按客户端写入设定值（校验可写和范围）
    {"kind": "fault",      "station": "CNC1", "fault": "tool_break"}                       注入设备故障（clear = 清除）
    {"kind": "cell_fault", "station": "CELL1", "comp": "S1", "fault": "sensor_stuck_on"}  控制单元部件故障
    {"kind": "comm_fault", "link": "N3", "mode": "disconnect"}                          网络线 / 信号线故障（4.3，经过这条线的数据受影响）
    {"kind": "comm_fault", "protocol": "mqtt", "mode": "freeze", "minutes": 0}            通讯故障（mode 为空 = 恢复）；可加 station / tag（按设备、点位）、
                           latency（延迟/抖动秒）、drop_pct（丢包 %）、value（卡死值）、rate（漂移/分钟）、include_mes
    {"kind": "wait",       "seconds": 120}                                                  等待仿真时间（秒）
    {"kind": "wait_until", "cond": {...}, "timeout": 600}                                   等到条件成立（仿真秒超时）
    {"kind": "assert",     "via": "rest|opcua|mqtt", "station": "CNC1", "tag": "Common/State", "op": "==", "value": "Stopped",
                           "tol": 0, "within": 5}                                           断言点位值（协议有刷新延迟，within 墙钟秒内重试）
    {"kind": "assert_mes", "topic": "event|part", "match": {"station": "CNC1", "kind": "~fault"}, "within": 300, "since": "start|step"}
                                                                                            断言 vfactory/<工厂>/_mes/<topic> 上出现匹配的消息（~ 表示包含）
    {"kind": "assert_kpi", "key": "good", "op": ">", "value": 0}
  ]
}
条件 cond：{kind:'tag', id, tag, op, value} / {kind:'state', id, state} / {kind:'kpi', key, op, value} / {kind:'buffer', id, op, value} /
           {kind:'event', id?, ekind?, text?}（从剧本开始算）
没有启动对应协议时（命令行 --no-protocols、沙箱工厂），via=opcua / mqtt 的断言记为"跳过"（JUnit <skipped>），不算失败。
"""
from ..i18n import _tr, label
import asyncio
import json
import logging
import operator
import time

log = logging.getLogger('vfactory.testing')
OPS = {'==': operator.eq, '!=': operator.ne, '>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le}
KIND_CN = {'set_tag': '设定点位', 'setpoint': '写设定值', 'fault': '注入故障', 'cell_fault': '部件故障', 'comm_fault': '通讯故障', 'wait': '等待',
           'wait_until': '等待条件', 'assert': '断言', 'assert_mes': '断言 MES 消息', 'assert_kpi': '断言指标'}
VIA_CN = {'rest': '接口', 'opcua': 'OPC UA', 'mqtt': 'MQTT'}


class StepFail(Exception):
    pass


class StepSkip(Exception):
    """这一步在当前环境下没法做（例如没启动协议），记为跳过。"""


def _coerce(a, b):
    """比较前把期望值转成实际值的类型。"""
    if isinstance(a, bool):
        return a, b if isinstance(b, bool) else str(b).lower() in ('1', 'true', 'on', 'yes')
    if isinstance(a, (int, float)) and not isinstance(b, bool):
        try:
            return float(a), float(b)
        except (TypeError, ValueError):
            return a, b
    return (str(a) if a is not None else None), (str(b) if b is not None else None)


def compare(actual, op, expect, tol=0.0):
    if op not in OPS:
        raise StepFail(_tr('不认识的比较符 {op}', op=op))
    a, b = _coerce(actual, expect)
    if op in ('==', '!=') and isinstance(a, float) and isinstance(b, float) and tol:
        eq = abs(a - b) <= float(tol)
        return eq if op == '==' else not eq
    try:
        return OPS[op](a, b)
    except TypeError:
        return False


def match(msg, pattern):
    for k, v in (pattern or {}).items():
        cur = msg
        for part in str(k).split('.'):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if isinstance(v, str) and v.startswith('~'):
            if v[1:] not in json.dumps(cur, ensure_ascii=False, default=str):
                return False
        elif cur != v and str(cur) != str(v):
            return False
    return True


def describe(s):
    k = s.get('kind')
    if k in ('set_tag', 'setpoint'):
        return f"{label(KIND_CN[k])} {s.get('station')}/{s.get('tag')} = {s.get('value')}"
    if k == 'fault':
        return _tr('注入故障 {get} {get2}', get=s.get('station'), get2=s.get('fault'))
    if k == 'cell_fault':
        return _tr('部件故障 {get}/{get2} {get3}', get=s.get('station'), get2=s.get('comp'), get3=s.get('fault'))
    if k == 'comm_fault':
        return _tr('通讯故障 {get} {v}', get=s.get('protocol'), v=s.get('mode') or _tr('恢复'))
    if k == 'wait':
        return _tr('等待 {get} 秒（仿真）', get=s.get('seconds'))
    if k == 'wait_until':
        return _tr('等待直到 {dumps}', dumps=json.dumps(s.get('cond'), ensure_ascii=False))
    if k == 'assert':
        return _tr('断言（{get}）{get2}/{get3} {get4} {get5}', get=VIA_CN.get(s.get('via', 'rest'), s.get('via')), get2=s.get('station'), get3=s.get('tag'), get4=s.get('op', '=='), get5=s.get('value'))
    if k == 'assert_mes':
        return _tr('断言 MES {get} 消息 {dumps}', get=s.get('topic', 'event'), dumps=json.dumps(s.get('match'), ensure_ascii=False))
    if k == 'assert_kpi':
        return _tr('断言指标 {get} {get2} {get3}', get=s.get('key'), get2=s.get('op', '>='), get3=s.get('value'))
    return k or '?'


class Bus:
    """订阅 vfactory/<工厂>/#：MQTT 点位最新值 + MES 消息。没有 MQTT 时直接挂到仿真内核的钩子上（标注为进程内）。"""

    def __init__(self, rt):
        self.rt = rt
        self.latest: dict = {}
        self.mes: list = []           # (墙钟, 仿真秒, topic, payload)
        self.client = None
        self.inproc = False

    async def start(self):
        mgr = self.rt.mgr
        if getattr(self.rt, 'mqtt', None) is not None and getattr(mgr, 'mqtt', None) is not None:
            from amqtt.client import MQTTClient
            self.client = MQTTClient(client_id=f'vfactory-test-{self.rt.pid}-{int(time.time() * 1000) % 100000}')
            try:                                  # 连不上 / 订阅卡住时不要让剧本永远停在"运行中"
                await asyncio.wait_for(self.client.connect(f'mqtt://127.0.0.1:{mgr.args.mqtt}/'), 15)
                await asyncio.wait_for(self.client.subscribe([(f'vfactory/{self.rt.pid}/#', 0)]), 15)
            except asyncio.TimeoutError:
                raise RuntimeError(_tr('连接内置 MQTT Broker 超时（15 秒）'))
            self.task = asyncio.create_task(self.listen())
        else:
            self.inproc = True
            p = self.rt.plant
            self._ph = lambda part, station, what, data: self.mes.append((time.time(), p.t, 'part', {
                'sn': part['id'], 'type': part.get('type'), 'station': station, 'event': what, 'data': {k: v for k, v in data.items() if k != 'truth'},
                'status': part.get('status')}))
            self._eh = lambda ev: self.mes.append((time.time(), p.t, 'event', dict(ev)))
            p.part_hooks.append(self._ph)
            p.event_hooks.append(self._eh)

    async def listen(self):
        while True:
            try:
                m = await self.client.deliver_message()
                topic = m.topic
                try:
                    body = json.loads(m.data.decode('utf-8', 'replace'))
                except ValueError:
                    body = m.data.decode('utf-8', 'replace')
                if '/_mes/' in topic:
                    self.mes.append((time.time(), self.rt.plant.t, topic.rsplit('/', 1)[-1], body))
                else:
                    self.latest[topic] = body
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(0.2)

    async def stop(self):
        if self.client:
            self.task.cancel()
            try:
                await self.client.disconnect()
            except Exception:
                pass
        elif self.inproc:
            p = self.rt.plant
            for lst, f in ((p.part_hooks, self._ph), (p.event_hooks, self._eh)):
                if f in lst:
                    lst.remove(f)


class Runner:
    def __init__(self, rt, script, on_update=None):
        self.rt, self.script = rt, script
        self.steps = list(script.get('steps') or [])
        self.result = {'name': script.get('name') or _tr('未命名剧本'), 'status': 'running', 'steps': [], 'started': time.strftime('%Y-%m-%d %H:%M:%S'),
                       'finished': None, 'duration_s': None, 'plant': rt.pid, 'notes': []}
        self.on_update = on_update
        self.opc = None
        self.cancelled = False

    @property
    def plant(self):
        return self.rt.plant

    # ---------- 等待 ----------
    async def until_sim(self, t_target, wall_limit):
        t0 = time.time()
        while self.plant.t < t_target:
            if self.cancelled:
                raise StepFail(_tr('已取消'))
            if time.time() - t0 > wall_limit:
                raise StepFail(_tr('仿真推进太慢：{wall_limit:.0f} 秒内没到 {t_target:g}（当前 {t:g}，是否被断点暂停？）', wall_limit=wall_limit, t_target=t_target, t=self.plant.t))
            if self.plant.paused and not self.rt.ctl.busy:
                self.plant.paused = False
            await asyncio.sleep(0.03)

    def wall_for(self, sim_s):
        return sim_s / max(0.1, self.plant.speed) * 3 + 15

    # ---------- 读值 ----------
    def station(self, sid):
        p = self.plant
        st = p.stations.get(sid) or getattr(p, 'sub_index', {}).get(sid)
        if st is None:
            raise StepFail(_tr('没有设备 {sid}', sid=sid))
        return st

    def tag_value(self, sid, tag):
        st = self.station(sid)
        if tag not in st.tags:
            raise StepFail(_tr('{sid} 没有点位 {tag}', sid=sid, tag=tag))
        return st.tags[tag].value

    async def read_opcua(self, sid, tag):
        if getattr(self.rt.mgr, 'opcua', None) is None or self.rt.sandbox:
            raise StepSkip(_tr('跳过：没有启动 OPC UA（命令行 --no-protocols 或沙箱工厂）'))
        from asyncua import Client
        if self.opc is None:
            self.opc = Client(f'opc.tcp://127.0.0.1:{self.rt.mgr.args.opcua}/vfactory/')
            await self.opc.connect()
            self.opc_ns = await self.opc.get_namespace_index('http://honeymeta.cn/vfactory')
        node = self.opc.get_node(f'ns={self.opc_ns};s={self.rt.pid}/{sid}/{tag}')
        dv = await node.read_data_value(raise_on_bad_status=False)
        if dv.StatusCode is not None and not dv.StatusCode.is_good():
            return {'value': dv.Value.Value if dv.Value else None, 'bad': dv.StatusCode.name}
        return {'value': dv.Value.Value}

    def read_mqtt(self, sid, tag):
        from ..protocols.mqtt import topic_of
        if self.bus.inproc:
            raise StepSkip(_tr('跳过：没有启动 MQTT（命令行 --no-protocols、沙箱工厂或 MQTT 未启动）'))
        b = self.bus.latest.get(topic_of(self.rt.pid, self.station(sid), tag))
        if b is None:
            return None
        return b if isinstance(b, dict) else {'value': b}

    # ---------- 步骤 ----------
    async def do(self, s, t_run0):
        k = s.get('kind')
        p = self.plant
        if k == 'set_tag':
            st = self.station(s['station'])
            if s['tag'] not in st.tags:
                raise StepFail(_tr('{station} 没有点位 {tag}', station=s['station'], tag=s['tag']))
            st.tags[s['tag']].value = s['value']
            return f"{s['station']}/{s['tag']} ← {s['value']}"
        if k == 'setpoint':
            err = self.station(s['station']).write(s['tag'], s['value'])
            if err:
                raise StepFail(err)
            return _tr('写入成功')
        if k == 'fault':
            st = self.station(s['station'])
            err = st.inject(s.get('fault') or 'failure')
            if err:
                raise StepFail(err)
            p.log(st.id, 'inject', _tr('测试剧本注入：{get}', get=st.fault_kinds.get(s.get('fault'), s.get('fault'))))
            return _tr('已注入')
        if k == 'cell_fault':
            from ..teach import scenes
            err = scenes.inject(self.rt, s.get('comp'), s.get('fault'), s.get('station'))
            if err:
                raise StepFail(err)
            return _tr('已注入')
        if k == 'comm_fault' and s.get('link'):        # 网络线 / 信号线故障（4.3）
            from ..netmodel import set_link_fault
            try:
                set_link_fault(self.rt, s['link'], s.get('mode') or None, minutes=float(s.get('minutes') or 0), latency=s.get('latency'), drop_pct=s.get('drop_pct'))
            except ValueError as e:
                raise StepFail(str(e))
            return _tr('已设置') if s.get('mode') else _tr('已恢复')
        if k == 'comm_fault':
            if s.get('protocol') not in ('opcua', 'modbus', 'mqtt'):
                raise StepFail(_tr('协议只能是 opcua / modbus / mqtt'))
            try:
                self.rt.comm_set(s['protocol'], s.get('mode') or None, latency=float(s.get('latency') or 5), minutes=float(s.get('minutes') or 0),
                                 station=s.get('station'), tag=s.get('tag'), drop_pct=s.get('drop_pct'), value=s.get('value'), rate=s.get('rate'),
                                 include_mes=s.get('include_mes', True))
            except ValueError as e:
                raise StepFail(str(e))
            return _tr('已设置') if s.get('mode') else _tr('已恢复')
        if k == 'wait':
            sec = float(s.get('seconds', 1))
            await self.until_sim(p.t + sec, self.wall_for(sec))
            return _tr('到仿真 {clock_str}', clock_str=p.clock_str())
        if k == 'wait_until':
            limit = float(s.get('timeout', 600))
            t_end = p.t + limit
            t0w = time.time()
            while True:
                ok, cur = self.cond(s.get('cond') or {}, t_run0)
                if ok:
                    return _tr('条件成立（当前值 {cur}）', cur=cur)
                if p.t >= t_end:
                    raise StepFail(_tr('{limit:g} 秒（仿真）内条件没有成立，当前值 {cur}', limit=limit, cur=cur))
                if time.time() - t0w > self.wall_for(limit):
                    raise StepFail(_tr('仿真推进太慢，等待超时'))
                if p.paused and not self.rt.ctl.busy:
                    p.paused = False
                await asyncio.sleep(0.05)
        if k == 'assert':
            via = s.get('via', 'rest')
            within = float(s.get('within', 5 if via != 'rest' else 0))
            t0w = time.time()
            last = None
            while True:
                if via == 'rest':
                    v = {'value': self.tag_value(s['station'], s['tag'])}
                elif via == 'opcua':
                    v = await self.read_opcua(s['station'], s['tag'])
                elif via == 'mqtt':
                    v = self.read_mqtt(s['station'], s['tag'])
                else:
                    raise StepFail(_tr('不认识的读取方式 {via}', via=via))
                last = v
                good = v is not None and not v.get('bad') and v.get('quality') != 'bad'
                if s.get('expect_bad'):
                    if v is not None and (v.get('bad') or v.get('quality') == 'bad'):
                        return _tr('坏质量 {v}', v=v.get('bad') or 'quality=bad')
                elif good and compare(v.get('value'), s.get('op', '=='), s.get('value'), s.get('tol') or 0):
                    return _tr('实际值 {get}', get=v.get('value'))
                if time.time() - t0w >= within:
                    break
                await asyncio.sleep(0.25)
            if last is None:
                raise StepFail(_tr('没有读到值'))
            raise StepFail(_tr('实际值 {get}', get=last.get('value')) + (_tr('（质量 {v}）', v=last.get('bad') or last.get('quality')) if last.get('bad') or last.get('quality') == 'bad' else ''))
        if k == 'assert_mes':
            topic = s.get('topic', 'event')
            within = float(s.get('within', 60))
            since_t = t_run0 if s.get('since', 'start') == 'start' else self._step_t0
            t_end = p.t + within
            t0w = time.time()
            while True:
                hits = [m for (_w, ts, tp, m) in list(self.bus.mes) if tp == topic and ts >= since_t - 1 and isinstance(m, dict) and match(m, s.get('match'))]
                if hits:
                    return _tr('收到 {len} 条，例：{v}', len=len(hits), v=json.dumps(hits[0], ensure_ascii=False, default=str)[:200]) + (_tr('（进程内钩子，未经 MQTT）') if self.bus.inproc else '')
                if p.t >= t_end and time.time() - t0w > 2:
                    raise StepFail(_tr('{within:g} 秒（仿真）内没有收到匹配的 {topic} 消息（共收到 {sum} 条 {topic}）', within=within, topic=topic, sum=sum(1 for m in self.bus.mes if m[2] == topic)))
                if time.time() - t0w > self.wall_for(within):
                    raise StepFail(_tr('等待超时'))
                if p.paused and not self.rt.ctl.busy:
                    p.paused = False
                await asyncio.sleep(0.1)
        if k == 'assert_kpi':
            v = p.kpi.get(s.get('key'))
            if v is None:
                raise StepFail(_tr('没有指标 {get}', get=s.get('key')))
            if not compare(v, s.get('op', '>='), s.get('value')):
                raise StepFail(_tr('实际值 {v}', v=v))
            return _tr('实际值 {v}', v=v)
        raise StepFail(_tr('不认识的步骤类型 {k}', k=k))

    def cond(self, c, t_run0):
        p = self.plant
        k = c.get('kind')
        if k == 'tag':
            v = self.tag_value(c.get('id') or c.get('station'), c.get('tag'))
            return compare(v, c.get('op', '=='), c.get('value'), c.get('tol') or 0), v
        if k == 'event':
            for e in reversed(list(p.events)):
                if e.get('seq', 0) <= self._seq0:
                    break
                if (not c.get('id') or e.get('station') == c['id']) and (not c.get('ekind') or e.get('kind') == c['ekind']) and \
                        (not c.get('text') or c['text'] in (e.get('msg') or '')):
                    return True, e.get('msg')
            return False, _tr('未出现')
        if k == 'kpi':
            v = p.kpi.get(c.get('key'))
            return (v is not None and compare(v, c.get('op', '>='), c.get('value'))), v
        if k in ('state', 'state_for', 'buffer', 'time'):
            return bool(self.rt.ctl.value(c)), '—'
        raise StepFail(_tr('不认识的条件 {k}', k=k))

    # ---------- 主流程 ----------
    async def run(self):
        p = self.plant
        speed0, paused0 = p.speed, p.paused
        t_wall0 = time.time()
        self.bus = Bus(self.rt)
        try:
            await self.bus.start()
            if self.script.get('speed'):
                p.speed = max(0.1, min(3600.0, float(self.script['speed'])))
            p.paused = False
            t_run0 = p.t
            self._seq0 = p.event_seq
            for i, s in enumerate(self.steps):
                if self.cancelled:
                    break
                self._step_t0 = p.t
                w0 = time.time()
                rec = {'i': i + 1, 'kind': s.get('kind'), 'desc': s.get('name') or describe(s), 'ok': None, 'msg': '', 'sim_time': p.clock_str()}
                self.result['steps'].append(rec)
                self._push()
                try:
                    rec['msg'] = await self.do(s, t_run0)
                    rec['ok'] = True
                except StepSkip as e:
                    rec['ok'], rec['skipped'], rec['msg'] = None, True, str(e)
                except StepFail as e:
                    rec['ok'], rec['msg'] = False, str(e)
                except Exception as e:
                    log.exception(_tr('剧本步骤出错'))
                    rec['ok'], rec['msg'], rec['error'] = False, f'{type(e).__name__}: {e}', True
                rec['ms'] = int((time.time() - w0) * 1000)
                rec['sim_end'] = p.clock_str()
                self._push()
                if rec['ok'] is False and (s.get('stop_on_fail') or self.script.get('stop_on_fail')):
                    self.result['notes'].append(_tr('第 {v} 步失败，剧本设置了失败即停止', v=i + 1))
                    break
            fails = [r for r in self.result['steps'] if r['ok'] is False]
            self.result['status'] = 'cancelled' if self.cancelled else ('passed' if not fails and len(self.result['steps']) == len(self.steps) else 'failed')
        except Exception as e:
            log.exception(_tr('剧本运行出错'))
            self.result['status'] = 'error'
            self.result['notes'].append(f'{type(e).__name__}: {e}')
        finally:
            await self.bus.stop()
            if self.opc is not None:
                try:
                    await self.opc.disconnect()
                except Exception:
                    pass
            if self.script.get('speed'):
                p.speed = speed0
            if self.script.get('restore_pause', True):
                p.paused = paused0
            self.result['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
            self.result['duration_s'] = round(time.time() - t_wall0, 2)
            self.result['passed'] = sum(1 for r in self.result['steps'] if r['ok'])
            self.result['failed'] = sum(1 for r in self.result['steps'] if r['ok'] is False)
            self.result['skipped'] = sum(1 for r in self.result['steps'] if r.get('skipped'))
            self._push()
        return self.result

    def _push(self):
        if self.on_update:
            try:
                self.on_update(self.result)
            except Exception:
                pass


def junit_xml(results):
    """[result] → JUnit XML 字符串（每个剧本一个 testsuite，每一步一个 testcase）。"""
    from xml.sax.saxutils import quoteattr, escape
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    tt = sum(len(r['steps']) for r in results)
    tf = sum(r.get('failed', 0) for r in results)
    te = sum(1 for r in results for s in r['steps'] if s.get('error'))
    tsk = sum(1 for r in results for s in r['steps'] if s['ok'] is None)
    out.append(f'<testsuites name="vfactory" tests="{tt}" failures="{tf - te}" errors="{te}" skipped="{tsk}" '
               f'time="{sum(r.get("duration_s") or 0 for r in results):.2f}">')
    for r in results:
        f = sum(1 for s in r['steps'] if s['ok'] is False and not s.get('error'))
        e = sum(1 for s in r['steps'] if s.get('error')) + (1 if r['status'] == 'error' else 0)
        sk = sum(1 for s in r['steps'] if s['ok'] is None)
        out.append(f'  <testsuite name={quoteattr(r["name"])} tests="{len(r["steps"])}" failures="{f}" errors="{e}" skipped="{sk}" '
                   f'time="{r.get("duration_s") or 0:.2f}" timestamp={quoteattr(str(r.get("started") or "").replace(" ", "T"))}>')
        out.append(f'    <properties><property name="plant" value={quoteattr(str(r.get("plant")))}/></properties>')
        for s in r['steps']:
            name = f'{s["i"]:02d} {s["desc"]}'
            out.append(f'    <testcase classname={quoteattr("vfactory." + r["name"])} name={quoteattr(name)} time="{(s.get("ms") or 0) / 1000:.3f}">')
            if s['ok'] is False:
                tag = 'error' if s.get('error') else 'failure'
                out.append(f'      <{tag} message={quoteattr(s["msg"][:500])}>{escape(s["msg"])}</{tag}>')
            elif s['ok'] is None:
                out.append(f'      <skipped message={quoteattr(str(s.get("msg") or _tr('未执行')))}/>')
            out.append(_tr('      <system-out>{escape}（仿真 {get} → {get2}）</system-out>', escape=escape(str(s.get("msg") or "")), get=s.get("sim_time"), get2=s.get("sim_end", "")))
            out.append('    </testcase>')
        for n in r.get('notes') or []:
            out.append(f'    <system-err>{escape(n)}</system-err>')
        out.append('  </testsuite>')
    out.append('</testsuites>')
    return '\n'.join(out) + '\n'


def validate(script):
    if not isinstance(script, dict):
        return [_tr('剧本需要是 JSON 对象')]
    errs = []
    if not isinstance(script.get('steps'), list) or not script['steps']:
        errs.append(_tr('剧本没有步骤'))
    for i, s in enumerate(script.get('steps') or []):
        k = s.get('kind') if isinstance(s, dict) else None
        if k not in KIND_CN:
            errs.append(_tr('第 {v} 步：不认识的步骤类型 {k}', v=i + 1, k=k))
            continue
        need = {'set_tag': ('station', 'tag', 'value'), 'setpoint': ('station', 'tag', 'value'), 'fault': ('station',), 'cell_fault': ('fault',),
                'comm_fault': ('protocol',), 'wait': ('seconds',), 'wait_until': ('cond',), 'assert': ('station', 'tag'), 'assert_mes': ('match',),
                'assert_kpi': ('key', 'value')}[k]
        if k == 'comm_fault' and s.get('link'):
            need = ()
        for f in need:
            if s.get(f) in (None, ''):
                errs.append(_tr('第 {v} 步（{v2}）缺少 {f}', v=i + 1, v2=KIND_CN[k], f=f))
        if k == 'assert' and s.get('via', 'rest') not in VIA_CN:
            errs.append(_tr('第 {v} 步：via 只能是 rest / opcua / mqtt', v=i + 1))
        if k == 'comm_fault' and s.get('mode') and not s.get('link'):
            from ..comm import MODES, SUPPORTED
            if s.get('protocol') in SUPPORTED and s['mode'] not in SUPPORTED[s['protocol']]:
                errs.append(_tr('第 {v} 步：{protocol} 不支持故障模式 {mode}（支持 {join}）', v=i + 1, protocol=s['protocol'], mode=s['mode'], join='/'.join(SUPPORTED[s['protocol']])))
            elif s['mode'] not in MODES:
                errs.append(_tr('第 {v} 步：不认识的故障模式 {mode}', v=i + 1, mode=s['mode']))
        if s.get('op') and s['op'] not in OPS:
            errs.append(_tr('第 {v} 步：比较符 {op} 不对', v=i + 1, op=s['op']))
    return errs
