"""报文监视：订阅内置 Broker 上某个工厂的全部主题，留最近 20000 条给联调台看（有网关时点位报文翻倍）。两分钟没人看自动断开。

每条报文记两个时间：recv = 本机收到的时刻（墙钟，带毫秒和时区），sim = 载荷里的仿真时间（sim_ts / ts / t，没有就空）。
可按设备（主题里的设备编号段）或主题前缀过滤，导出 CSV / JSONL。"""
from ..i18n import _tr
import asyncio
import json
import time
from collections import deque


class Sniffer:
    def __init__(self, pid, port, keep=20000, idle_s=120):
        self.pid, self.port, self.idle_s = pid, port, idle_s
        self.buf: deque = deque(maxlen=keep)
        self.seq = 0
        self.total = 0
        self.dead = False
        self.last_poll = time.time()
        self.started = time.strftime('%H:%M:%S')
        self.recent: deque = deque(maxlen=400)

    async def start(self):
        from amqtt.client import MQTTClient
        self.client = MQTTClient(client_id=f'vfactory-sniff-{self.pid}-{int(time.time()) % 100000}')
        await self.client.connect(f'mqtt://127.0.0.1:{self.port}/')
        await self.client.subscribe([(f'vfactory/{self.pid}/#', 0), (f'vda5050/v2/{self.pid}/#', 0)])
        self.task = asyncio.create_task(self.loop())

    def touch(self):
        self.last_poll = time.time()

    async def loop(self):
        try:
            while time.time() - self.last_poll < self.idle_s:
                try:
                    m = await self.client.deliver_message(timeout_duration=2)      # 不能用 wait_for：amqtt 超时后后台任务还会吃掉下一条报文
                except asyncio.TimeoutError:
                    continue
                self.seq += 1
                self.total += 1
                raw = m.data.decode('utf-8', 'replace')
                now = time.time()
                self.recent.append(now)
                self.buf.append({'seq': self.seq, 'ts': time.strftime('%H:%M:%S', time.localtime(now)), 'recv': _iso_ms(now), 'sim': _sim_of(raw),
                                 'topic': m.topic, 'payload': raw[:2000], 'bytes': len(m.data), 'retain': bool(getattr(m, 'retain', False))})
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self.dead = True
            try:
                await self.client.disconnect()
            except Exception:
                pass

    def rate(self):
        now = time.time()
        return round(sum(1 for t in self.recent if now - t < 10) / 10, 1)

    def since(self, seq, flt='', mes_only=False, limit=300, station='', prefix=''):
        out = []
        for m in reversed(self.buf):
            if m['seq'] <= seq:
                break
            t = m['topic']
            if mes_only and '/_mes/' not in t and '/_status' not in t and '/_errors' not in t and not t.startswith('vda5050'):
                continue
            if station and not _of_station(m, station):
                continue
            if prefix and not t.startswith(prefix):
                continue
            if flt and flt not in t and flt not in m['payload']:
                continue
            out.append(m)
            if len(out) >= limit:
                break
        out.reverse()
        return out


def _iso_ms(t):
    from datetime import datetime
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec='milliseconds')


def _sim_of(raw):
    """载荷里的仿真时间：sim_ts（新版）/ ts / t（_mes 消息）。"""
    if not raw.startswith('{'):
        return ''
    try:
        d = json.loads(raw)
    except ValueError:
        return ''
    if not isinstance(d, dict):
        return ''
    v = d.get('sim_ts') or d.get('t') or d.get('timestamp') or d.get('ts') or ''
    return str(v)


def _of_station(m, sid):
    """报文属于某台设备：主题里有这一段（vfactory/厂/区/设备/…、vda5050/v2/厂/AGV），或 _mes 载荷里 station = 设备。"""
    parts = m['topic'].split('/')
    if sid in parts[2:]:
        return True
    if '/_mes/' in m['topic'] or m['topic'].endswith('/_errors'):
        return f'"station": "{sid}"' in m['payload'] or f'/{sid}/' in m['payload']
    return False


def export(items, fmt='csv'):
    """导出：csv（Excel 可直接打开，带 BOM）或 jsonl（一行一条）。"""
    if fmt == 'jsonl':
        return '\n'.join(json.dumps({k: m.get(k) for k in ('seq', 'recv', 'sim', 'topic', 'retain', 'bytes', 'payload')}, ensure_ascii=False) for m in items) + '\n'
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([_tr('序号'), _tr('接收时间（本机）'), _tr('仿真时间（载荷）'), _tr('主题'), _tr('保留'), _tr('字节'), _tr('载荷')])
    for m in items:
        w.writerow([m['seq'], m.get('recv', m.get('ts')), m.get('sim', ''), m['topic'], 'Y' if m.get('retain') else '', m.get('bytes'), m['payload']])
    return '\ufeff' + buf.getvalue()


def pretty(payload):
    try:
        return json.dumps(json.loads(payload), ensure_ascii=False, indent=1)
    except ValueError:
        return payload
