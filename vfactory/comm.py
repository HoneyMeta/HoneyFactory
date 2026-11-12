"""信号中心后端：协议设置、通讯故障注入、在线客户端、真实接入地址、录制与回放。

协议设置（每个工厂一份，存在服务器数据库 settings 表 proto:<工厂>，工厂文件 plant.protocols 可给默认值）：
  time               对外时间：sim = 仿真时钟（默认），wall = 服务器墙钟。决定 OPC UA SourceTimestamp、MQTT ts、HistoryRead 时间戳
  lenient_types      宽松类型转换（默认开）：OPC UA 用 Int32 写 Double 节点、MQTT 写 "12.5" 字符串都按点位类型转换
  allow_out_of_range 允许越界写入（故障演练用，默认关）：关时越界写入 OPC UA 返回 BadOutOfRange、Modbus 返回异常码 03、MQTT 回执失败
  modbus             {auto, base, fmt, order, missing_unit}：自动分配点位地址的起始地址、数据类型、字序；不存在的从站返回 0B 异常或不响应
  mqtt               {heartbeat_s}：_status 心跳间隔（秒）

通讯故障（规则）：协议 × 设备 × 点位，每条规则 {id, protocol, station?, tag?, mode, ...参数, until?}
  freeze      数据冻结：连接正常，值停在故障开始时（数采最难发现的故障）
  bad         坏质量：OPC UA 质量位 BadCommunicationError；MQTT 载荷 quality=bad（只在进入坏质量时发一次）；Modbus 返回异常码 04
  disconnect  断开：Modbus 关闭端口（设备级 = 该从站返回 0B）；MQTT 停发、_status 离线、踢掉订阅本厂主题的客户端并拒绝其订阅/写入；
              OPC UA 质量 BadNotConnected，并关闭访问本厂节点的会话（会话重连后一碰本厂节点就再次被断开）
  latency     延迟：MQTT 发布、Modbus 应答推迟 N 秒
  jitter      抖动：MQTT 发布、Modbus 应答随机推迟 0–N 秒（MQTT 会因此乱序）
  drop        丢包：按百分比丢掉 MQTT 报文 / OPC UA 数值更新 / Modbus 应答（客户端超时）
  stuck       卡死在某值：值固定为给定值（不填 = 故障开始时的值），质量仍为好
  drift       漂移：数值每分钟（仿真）偏移 rate，质量仍为好
协议级的规则同时登记在 plant.comm[协议]（旧接口、场景、剧本都还按这个读）。
"""
from .i18n import _tr
import asyncio
import contextvars
import re
import gzip
import json
import os
import random
import socket
import time
from datetime import datetime, timezone

from .store import ROOT

from . import paths as _paths  # noqa: E402
REC_DIR = _paths.data('recordings')
MODES = {'freeze': '数据冻结', 'bad': '坏质量', 'disconnect': '断开', 'latency': '延迟', 'jitter': '抖动', 'drop': '丢包',
         'stuck': '卡死在某值', 'drift': '漂移'}
SUPPORTED = {'opcua': ['freeze', 'bad', 'disconnect', 'stuck', 'drift', 'drop'],
             'modbus': ['freeze', 'bad', 'disconnect', 'latency', 'jitter', 'drop', 'stuck', 'drift'],
             'mqtt': ['freeze', 'bad', 'disconnect', 'latency', 'jitter', 'drop', 'stuck', 'drift']}
PROTO_CN = {'opcua': 'OPC UA', 'modbus': 'Modbus', 'mqtt': 'MQTT'}
MODE_HELP = {
    'freeze': '连接正常，值停在故障开始时',
    'bad': 'OPC UA 质量位 Bad、MQTT quality=bad（只发一次）、Modbus 返回异常码 04',
    'disconnect': 'Modbus 关端口（设备级：该从站返回 0B）；MQTT 停发并踢掉本厂订阅者；OPC UA 关闭访问本厂节点的会话',
    'latency': 'MQTT 发布 / Modbus 应答推迟固定秒数',
    'jitter': 'MQTT 发布 / Modbus 应答随机推迟 0–N 秒',
    'drop': '按百分比丢掉报文、数值更新或应答',
    'stuck': '值固定为给定值（空 = 故障开始时的值），质量仍为好',
    'drift': '数值每分钟（仿真时间）偏移给定量，质量仍为好',
}

# ---------------------------------------------------------------- 协议设置
DEFAULTS = {'time': 'sim', 'lenient_types': True, 'allow_out_of_range': False,
            'modbus': {'auto': True, 'base': 1000, 'fmt': 'float32', 'order': 'ABCD', 'missing_unit': 'exception'},
            'mqtt': {'heartbeat_s': 10, 'legacy_topics': True}}
FMTS = {'int16': 1, 'uint16': 1, 'int32': 2, 'uint32': 2, 'float32': 2, 'float64': 4}
ORDERS = ('ABCD', 'CDAB', 'BADC', 'DCBA')


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(base.get(k), dict) and isinstance(v, dict) else v
    return out


def settings(plant) -> dict:
    """工厂当前生效的协议设置（默认值 < 工厂文件 plant.protocols < 服务器上保存的设置）。"""
    s = getattr(plant, 'proto', None)
    if s is None:
        s = _merge(DEFAULTS, (plant.cfg.get('plant') or {}).get('protocols') or {})
        plant.proto = s
    return s


def load_settings(rt):
    """工厂启动时调用：合并默认值、工厂文件和数据库里的设置，挂到 plant.proto。"""
    from . import store
    s = _merge(DEFAULTS, (rt.cfg.get('plant') or {}).get('protocols') or {})
    try:
        r = store.q('select v from settings where k=?', (f'proto:{rt.pid}',), one=True)
        if r:
            s = _merge(s, json.loads(r['v']))
    except Exception:
        pass
    rt.plant.proto = s
    return s


def save_settings(rt, body: dict) -> dict:
    """校验并保存协议设置，立即生效（Modbus 地址表按新设置重建）。"""
    from . import store
    cur = settings(rt.plant)
    s = _merge(cur, {k: v for k, v in (body or {}).items() if k in DEFAULTS})
    if s['time'] not in ('sim', 'wall'):
        raise ValueError(_tr('对外时间只能是 sim（仿真时间）或 wall（墙钟）'))
    mb = s['modbus']
    if mb.get('fmt') not in FMTS:
        raise ValueError(_tr('Modbus 数据类型只能是 {join}', join='/'.join(FMTS)))
    if mb.get('order') not in ORDERS:
        raise ValueError(_tr('Modbus 字序只能是 {join}', join='/'.join(ORDERS)))
    try:
        mb['base'] = int(mb.get('base', 1000))
    except (TypeError, ValueError):
        raise ValueError(_tr('Modbus 起始地址需要整数'))
    if not 0 <= mb['base'] <= 60000:
        raise ValueError(_tr('Modbus 起始地址范围 0–60000'))
    if mb.get('missing_unit') not in ('exception', 'silent'):
        raise ValueError(_tr('不存在的从站只能 exception（返回 0B）或 silent（不响应）'))
    s['lenient_types'] = bool(s['lenient_types'])
    s['allow_out_of_range'] = bool(s['allow_out_of_range'])
    s['mqtt']['legacy_topics'] = bool(s['mqtt'].get('legacy_topics', True))
    try:
        s['mqtt']['heartbeat_s'] = max(0, min(3600, int(s['mqtt'].get('heartbeat_s') or 0)))
    except (TypeError, ValueError):
        raise ValueError(_tr('心跳间隔需要整数秒'))
    rt.plant.proto = s
    store.x('insert or replace into settings(k,v) values(?,?)', (f'proto:{rt.pid}', json.dumps(s, ensure_ascii=False)))
    try:
        rt.modbus.rebuild()
    except Exception:
        pass
    rt.plant.log('SIGNAL', 'comm', _tr('协议设置已修改：对外时间=') + (_tr('仿真时间') if s['time'] == 'sim' else _tr('墙钟')) +
                 (_tr('，允许越界写入') if s['allow_out_of_range'] else ''))
    return s


def write_tag(plant, st, name, value, source=''):
    """协议写入点位（OPC UA / Modbus / MQTT 共用）：宽松类型转换、越界检查（可关）。返回 (错误码, 说明)，成功为 ('', '')。
    错误码：notfound / readonly / type / range / other。"""
    t = st.tags.get(name)
    if t is None:
        return 'notfound', _tr('没有点位 {name}', name=name)
    if not t.writable:
        return 'readonly', _tr('{name} 只读', name=name)
    s = settings(plant)
    if isinstance(value, dict):
        value = value.get('value')
    if not s['lenient_types']:
        ok = (t.dtype == 'bool' and isinstance(value, bool)) or (t.dtype == 'int' and isinstance(value, int) and not isinstance(value, bool)) or \
             (t.dtype == 'float' and isinstance(value, float)) or (t.dtype == 'str' and isinstance(value, str))
        if not ok:
            return 'type', _tr('{name} 需要 {dtype} 类型（严格类型模式）', name=name, dtype=t.dtype)
    try:
        if t.dtype == 'bool':
            if isinstance(value, str):
                lv = value.strip().lower()
                if lv not in ('1', '0', 'true', 'false', 'on', 'off', 'yes', 'no'):
                    raise ValueError(value)
                value = lv in ('1', 'true', 'on', 'yes')
            else:
                value = bool(value)
        elif t.dtype == 'int':
            f = float(value)
            if f != f or f in (float('inf'), float('-inf')):
                raise ValueError(value)
            value = int(round(f))
        elif t.dtype == 'float':
            value = float(value)
            if value != value or value in (float('inf'), float('-inf')):
                raise ValueError(value)
        elif value is None:
            raise ValueError(value)
        else:
            value = str(value)
    except (TypeError, ValueError):
        return 'type', _tr('{name} 数值格式不对（{value!r}）', name=name, value=value)
    if t.dtype in ('int', 'float') and (t.lo is not None and value < t.lo or t.hi is not None and value > t.hi):
        if not s['allow_out_of_range']:
            return 'range', _tr('{name} 超出范围 {lo}–{hi}', name=name, lo=t.lo, hi=t.hi)
        t.value = value                               # 故障演练：越界值照样进模型
        st.on_write(name, value)
        plant.log(st.id, 'param', _tr('{name} = {value}（越界写入{v}）', name=name, value=value, v=_tr('，') + source if source else ""))
        return '', ''
    err = st.write(name, value)
    if err:
        low = err.lower()                        # messages are in the request language: classify Chinese and English texts
        return ('range' if ('范围' in err or 'range' in low) else 'type' if ('格式' in err or 'format' in low or 'type' in low) else 'other'), err
    return '', ''


# ---------------------------------------------------------------- 时间
def local_tz():
    return datetime.now().astimezone().tzinfo


def sim_dt(plant, t=None) -> datetime:
    """仿真时刻（带本地时区）。"""
    from datetime import timedelta
    d = plant.t0 + timedelta(seconds=plant.t if t is None else t)
    return d.replace(tzinfo=local_tz())


def wall_dt() -> datetime:
    return datetime.now().astimezone()


def ext_dt(plant) -> datetime:
    """对外时间（按协议设置：仿真时间或墙钟）。"""
    return wall_dt() if settings(plant)['time'] == 'wall' else sim_dt(plant)


def iso(d: datetime, ms=False) -> str:
    return d.isoformat(timespec='milliseconds' if ms else 'seconds')


def stamps(plant) -> dict:
    """MQTT 载荷里的时间字段：ts（对外时间）、sim_ts、wall_ts，都是带时区的 ISO 8601。"""
    s, w = sim_dt(plant), wall_dt()
    return {'ts': iso(w, True) if settings(plant)['time'] == 'wall' else iso(s), 'sim_ts': iso(s), 'wall_ts': iso(w, True)}


# ---------------------------------------------------------------- 真实接入地址
_hosts = {'t': 0, 'v': []}


def host_addresses():
    """本机 IPv4 地址（主网卡在前，去掉回环和 169.254）。60 秒缓存。"""
    if time.time() - _hosts['t'] < 60 and _hosts['v']:
        return _hosts['v']
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(('10.255.255.255', 1))           # UDP connect 不发包，只用来选出主网卡
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in ips:
        if ip not in out and not ip.startswith('127.') and not ip.startswith('169.254.') and ip != '0.0.0.0':
            out.append(ip)
    _hosts.update(t=time.time(), v=out or ['127.0.0.1'])
    return _hosts['v']


# 当前请求的账号（server.py 的认证中间件设置）：role, host。没有请求（后台、导出脚本）时为 None，看到完整信息
_viewer = contextvars.ContextVar('vf_endpoint_viewer', default=None)


def set_viewer(role, host):
    """host 来自请求头，只回显给请求者本人，这里只防乱字符。"""
    _viewer.set({'role': role, 'host': host if host and re.fullmatch(r'[\w.\-:]+', host) else '127.0.0.1'})


def endpoints(rt):
    """接入地址。管理员：真实 IP（多网卡全部列出）+ 主机名；其他账号：只用他访问服务器的那个地址，不暴露网卡和主机名。"""
    if rt.sandbox:
        return {'opcua': None, 'modbus': None, 'mqtt': None, 'sandbox': True}
    if getattr(rt, 'noproto', False):            # 桌面模式关了协议服务
        return {'opcua': None, 'modbus': None, 'mqtt': None, 'protocols_off': True}
    v = _viewer.get()
    full = v is None or v['role'] == 'admin'
    hosts = host_addresses() if full else [v['host']]
    a = rt.mgr.args
    mport = rt.cfg['plant']['modbus_port']
    ip = hosts[0]
    return {'opcua': f'opc.tcp://{ip}:{a.opcua}/vfactory/', 'opcua_prefix': f'{rt.pid}/',
            'modbus': f'{ip}:{mport}', 'mqtt': f'{ip}:{a.mqtt}' if rt.mqtt else None, 'mqtt_prefix': f'vfactory/{rt.pid}/',
            'hostname': socket.gethostname() if full else None, 'hosts': hosts,
            'all': {'opcua': [f'opc.tcp://{h}:{a.opcua}/vfactory/' for h in hosts], 'modbus': [f'{h}:{mport}' for h in hosts],
                    'mqtt': [f'{h}:{a.mqtt}' for h in hosts] if rt.mqtt else []},
            'ports': {'opcua': a.opcua, 'modbus': mport, 'mqtt': a.mqtt if rt.mqtt else None}}


# ---------------------------------------------------------------- 通讯故障规则
def rules(plant) -> list:
    r = getattr(plant, 'comm_rules', None)
    if r is None:
        r = plant.comm_rules = []
    return r


def _label_key(r):
    if r.get('link'):
        return f"LINK:{r['link']}"
    k = r['protocol'].upper()
    if r.get('station'):
        k += ':' + r['station'] + ('/' + r['tag'] if r.get('tag') else '')
    return k


def public(r):
    return {k: v for k, v in r.items() if not k.startswith('_')}


def describe(r):
    if r.get('link'):
        m = {'drop': _tr('丢包'), 'disconnect': _tr('断开'), 'latency': _tr('延迟'), 'jitter': _tr('抖动'), 'bad': _tr('坏质量'), 'freeze': _tr('冻结')}.get(r['mode'], r['mode'])
        extra = _tr(' {get:g} 秒', get=r.get('latency', 5)) if r['mode'] in ('latency', 'jitter') else f" {r.get('drop_pct', 30):g}%" if r['mode'] == 'drop' else ''
        return _tr('网络线 {link}（{v} → {v2}）{m}{extra}', link=r['link'], v=r.get('from') or '?', v2=r.get('to') or '?', m=m, extra=extra)
    where = PROTO_CN.get(r['protocol'], r['protocol'])
    if r.get('station'):
        where += f" {r['station']}" + (f"/{r['tag']}" if r.get('tag') else '')
    m = MODES.get(r['mode'], r['mode'])
    extra = ''
    if r['mode'] in ('latency', 'jitter'):
        extra = _tr(' {get:g} 秒', get=r.get('latency', 5))
    elif r['mode'] == 'drop':
        extra = f" {r.get('drop_pct', 30):g}%"
    elif r['mode'] == 'stuck' and r.get('value') not in (None, ''):
        extra = f" = {r['value']}"
    elif r['mode'] == 'drift':
        extra = _tr(' {get:+g}/分钟', get=r.get('rate', 1))
    return f'{where} {m}{extra}'


def set_fault(rt, proto, mode, latency=5.0, minutes=0.0, station=None, tag=None, **params):
    """新增（或替换同一对象上的）故障规则；mode 为空 = 恢复该对象。返回规则或 None。"""
    p = rt.plant
    if proto not in SUPPORTED:
        raise ValueError(_tr('协议只能是 opcua / modbus / mqtt'))
    station = (station or '').strip() or None
    tag = (tag or '').strip() or None
    if tag and not station:
        raise ValueError(_tr('按点位注入时需要同时指定设备'))
    if station and not (p.stations.get(station) or getattr(p, 'sub_index', {}).get(station)):
        raise ValueError(_tr('没有设备 {station}', station=station))
    if not mode:
        clear(rt, proto=proto, station=station, tag=tag)
        return None
    if mode not in SUPPORTED[proto]:
        raise ValueError(_tr('{v} 不支持「{get}」，支持：{join}', v=PROTO_CN[proto], get=MODES.get(mode, mode), join=_tr('、').join(MODES[m] for m in SUPPORTED[proto])))
    clear(rt, proto=proto, station=station, tag=tag, quiet=True)
    rs = rules(p)
    n = max([r['id'] for r in rs] + [getattr(p, '_comm_seq', 0)]) + 1
    p._comm_seq = n
    r = {'id': n, 'protocol': proto, 'station': station, 'tag': tag, 'mode': mode, 'latency': float(latency or 5), 't0': p.t,
         'until': p.t + float(minutes) * 60 if minutes else None, 'started': p.clock_str(),
         'include_mes': bool(params.get('include_mes', True))}
    if mode == 'drop':
        r['drop_pct'] = max(0.0, min(100.0, float(params.get('drop_pct') if params.get('drop_pct') not in (None, '') else 30)))
    if mode == 'stuck':
        r['value'] = params.get('value') if params.get('value') not in ('',) else None
    if mode == 'drift':
        r['rate'] = float(params.get('rate') if params.get('rate') not in (None, '') else 1.0)
    if mode == 'freeze' or (mode == 'stuck' and r.get('value') in (None, '')):
        # 冻结值取故障开始这一刻（不能等协议下一个周期再取：剧本里"注入冻结→马上写新值"时会把新值冻住）
        fz = r['_frozen'] = {}
        for st in ([p.stations.get(station) or p.sub_index.get(station)] if station else list(p.stations.values())):
            for k, t in st.tags.items():
                if not tag or k == tag or k.startswith(tag.rstrip('/') + '/'):
                    fz[f'{st.id}/{k}'] = t.value
    rs.append(r)
    if not station:
        p.comm[proto] = r
    p.log('SIGNAL', 'comm', _tr('通讯故障：{describe}', describe=describe(r)) + (_tr('，{float:g} 分钟后恢复', float=float(minutes)) if minutes else ''))
    p.label_close(_label_key(r), 'comm')
    p.label_open(_label_key(r), 'comm', describe(r), protocol=proto, mode=mode)
    _bump(p)
    return r


def clear(rt, rid=None, proto=None, station=None, tag=None, quiet=False):
    """删除规则：按编号，或按 协议+设备+点位 精确匹配（都不给 = 该协议协议级规则）。"""
    p = rt.plant
    rs = rules(p)
    keep, gone = [], []
    for r in rs:
        hit = r['id'] == rid if rid is not None else (r['protocol'] == proto and r.get('station') == station and r.get('tag') == tag)
        (gone if hit else keep).append(r)
    rs[:] = keep
    for r in gone:
        if not r.get('station') and p.comm.get(r['protocol']) is r:
            p.comm[r['protocol']] = None
        p.label_close(_label_key(r), 'comm')
        if not quiet:
            p.log('SIGNAL', 'comm', _tr('通讯恢复：{describe}', describe=describe(r)))
    if gone:
        _bump(p)
    if rid is None and not station and not gone and p.comm.get(proto):      # 旧数据：只有 plant.comm 没有规则
        p.comm[proto] = None
    return len(gone)


def tick(rt):
    """到时自动恢复（仿真时间）。"""
    p = rt.plant
    for r in list(rules(p)):
        if r.get('until') and p.t >= r['until']:
            clear(rt, rid=r['id'])


def _bump(p):
    p._comm_ver = getattr(p, '_comm_ver', 0) + 1


def version(p):
    return getattr(p, '_comm_ver', 0)


def protocol_rule(p, proto):
    """协议级规则（没有设备/点位限定）。"""
    for r in reversed(rules(p)):
        if r['protocol'] == proto and not r.get('station'):
            return r
    c = p.comm.get(proto)
    return c if c and c.get('mode') else None


def station_rules(p, proto, sid):
    return [r for r in rules(p) if r['protocol'] == proto and r.get('station') == sid]


def rule_for(p, proto, sid, tname):
    """某个点位上生效的规则：点位级 > 设备级 > 协议级（同级取最新）。tag 以 / 结尾时按前缀匹配。"""
    best, rank = None, -1
    for r in rules(p):
        if r['protocol'] != proto:
            continue
        if r.get('station'):
            if r['station'] != sid:
                continue
            tg = r.get('tag')
            if tg:
                if not (tname == tg or (tg.endswith('/') and tname.startswith(tg)) or tname.startswith(tg + '/')):
                    continue
                k = 2
            else:
                k = 1
        else:
            k = 0
        if k >= rank:
            best, rank = r, k
    if best is None:
        c = p.comm.get(proto)
        if c and c.get('mode') and 'id' not in c:                 # 只在 plant.comm 里的旧格式故障
            best = c
    return best


def effective(p, proto, sid, tname, gw=None):
    """点位上真正生效的故障：协议 × 设备 × 点位规则，叠加它经网关 gw（None = 主网关）的网络路径故障（网络线、交换机、网关、PLC），取更严重的。
    没有网关的工厂只看前者（和 4.1 一样）。"""
    r = rule_for(p, proto, sid, tname)
    net = getattr(p, 'net', None)
    if net is None or not net.gateways:
        return r
    n = net.path_rule(gw, sid)
    if not n:
        return r
    from .netmodel import worse
    return worse(r, n)


def view(p, r, key, value, dtype='float'):
    """按规则变换对外值：冻结/卡死/漂移。其它模式原样返回。"""
    if r is None:
        return value
    m = r.get('mode')
    if m == 'freeze' or (m == 'stuck' and r.get('value') in (None, '')):
        fz = r.setdefault('_frozen', {})
        if key not in fz:
            fz[key] = value
        return fz[key]
    if m == 'stuck':
        v = r['value']
        try:
            if dtype == 'float':
                return float(v)
            if dtype == 'int':
                return int(float(v))
            if dtype == 'bool':
                return v if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'on', 'yes')
        except (TypeError, ValueError):
            return value
        return v
    if m == 'drift' and dtype in ('float', 'int') and isinstance(value, (int, float)) and not isinstance(value, bool):
        d = float(r.get('rate', 1.0)) * (p.t - r.get('t0', p.t)) / 60
        return round(value + d, 4) if dtype == 'float' else int(round(value + d))
    return value


def dropped(r):
    return bool(r) and r.get('mode') == 'drop' and random.random() * 100 < float(r.get('drop_pct', 30))


def delay_of(r):
    if not r:
        return 0.0
    if r.get('mode') == 'latency':
        return float(r.get('latency', 5))
    if r.get('mode') == 'jitter':
        return random.uniform(0, float(r.get('latency', 5)))
    return 0.0


def status(rt):
    p = rt.plant
    return {'rules': [{**public(r), 'desc': describe(r), 'left_min': round((r['until'] - p.t) / 60, 1) if r.get('until') else None} for r in rules(p)],
            'supported': SUPPORTED, 'help': MODE_HELP}


def clients(mgr, rt):
    out = []
    try:
        for c in list(mgr.opcua.server.bserver.clients):
            out.append({'protocol': 'OPC UA', 'peer': ':'.join(map(str, c.peer_name or ())), 'detail': _tr('所有工厂共用服务端')})
    except Exception:
        pass
    try:
        srv = rt.modbus.server
        for k, proto in list(getattr(srv, 'active_connections', {}).items()):
            peer = proto.transport.get_extra_info('peername') if getattr(proto, 'transport', None) else None
            out.append({'protocol': 'Modbus TCP', 'peer': ':'.join(map(str, peer)) if peer else str(k), 'detail': _tr('端口 {port}', port=rt.modbus.port)})
    except Exception:
        pass
    try:
        for cid, (sess, _h) in list(mgr.mqtt.broker._sessions.items()):
            if cid.startswith('vfactory-'):
                continue
            out.append({'protocol': 'MQTT', 'peer': f"{getattr(sess, 'remote_address', '')}:{getattr(sess, 'remote_port', '')}", 'detail': f'client_id={cid}'})
    except Exception:
        pass
    return out


class Recorder:
    """录制：每 2 秒（仿真时间）把变化的点位值写进 gz 文件；回放：暂停仿真，把录下的值按时间顺序写回点位，三种协议照常发布。"""

    def __init__(self, rt):
        self.rt = rt
        self.file = None
        self.path = None
        self.last = {}
        self.n = 0
        self.t_start = 0
        self.replay = None

    # ---- 录制 ----
    def start(self):
        if self.file:
            return self.path
        os.makedirs(REC_DIR, exist_ok=True)
        p = self.rt.plant
        name = f"{self.rt.pid}-{p.now():%Y%m%d-%H%M%S}.jsonl.gz"
        self.path = os.path.join(REC_DIR, name)
        self.file = gzip.open(self.path, 'wt', encoding='utf-8')
        self.file.write(json.dumps({'meta': {'plant': self.rt.pid, 'name': p.name, 'start': p.clock_str(), 't0': p.t}}, ensure_ascii=False) + '\n')
        self.last, self.n, self.t_start = {}, 0, p.t
        p.step_hooks.append(self.tick)
        p.log('SIGNAL', 'record', _tr('开始录制 {name}', name=name))
        return name

    def tick(self):
        p = self.rt.plant
        if int(p.t) % 2:
            return
        ch = []
        for st in p.stations.values():
            for k, tg in st.tags.items():
                key = f'{st.id}/{k}'
                v = tg.value
                if self.last.get(key, ()) != v:
                    self.last[key] = v
                    ch.append([key, v])
        if ch:
            self.file.write(json.dumps({'t': p.t, 'c': ch}, ensure_ascii=False, default=str) + '\n')
            self.n += len(ch)

    def stop(self):
        if not self.file:
            return None
        p = self.rt.plant
        if self.tick in p.step_hooks:
            p.step_hooks.remove(self.tick)
        self.file.close()
        self.file = None
        p.log('SIGNAL', 'record', _tr('录制结束：{basename}，{n} 个数据变化', basename=os.path.basename(self.path), n=self.n))
        return os.path.basename(self.path)

    def status(self):
        p = self.rt.plant
        rec = {'file': os.path.basename(self.path), 'minutes': round((p.t - self.t_start) / 60, 1), 'changes': self.n} if self.file else None
        return {'recording': rec, 'replay': self.replay and {k: v for k, v in self.replay.items() if k != 'task'}}

    # ---- 回放 ----
    async def play(self, fname, speed=10.0):
        path = os.path.join(REC_DIR, os.path.basename(fname))
        if not os.path.exists(path):
            raise FileNotFoundError(fname)
        self.stop_replay()
        p = self.rt.plant
        was_paused = p.paused
        p.paused = True
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            lines = [json.loads(x) for x in f]
        frames = [x for x in lines if 't' in x]
        self.replay = {'file': fname, 'speed': speed, 'frames': len(frames), 'pos': 0, 'sim_time': '', 'meta': lines[0].get('meta') if lines else {}}
        p.log('SIGNAL', 'replay', _tr('开始回放 {fname}（{speed:g}×），仿真暂停', fname=fname, speed=speed))

        async def go():
            try:
                t_prev = frames[0]['t'] if frames else 0
                t0 = self.replay['meta'].get('t0', t_prev)
                start_wall = time.time()
                for i, fr in enumerate(frames):
                    wait = (fr['t'] - frames[0]['t']) / speed - (time.time() - start_wall)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    for key, v in fr['c']:
                        sid, tag = key.split('/', 1)
                        st = p.stations.get(sid)
                        if st and tag in st.tags:
                            st.tags[tag].value = v
                    self.replay['pos'] = i + 1
                    self.replay['sim_time'] = _tr('+{v:.1f} 分钟', v=(fr['t'] - t0) / 60)
            finally:
                p.paused = was_paused
                p.log('SIGNAL', 'replay', _tr('回放结束，仿真恢复'))
                self.replay = None
        self.replay['task'] = asyncio.create_task(go())

    def stop_replay(self):
        if self.replay and self.replay.get('task'):
            self.replay['task'].cancel()


def recordings():
    if not os.path.isdir(REC_DIR):
        return []
    out = []
    for f in sorted(os.listdir(REC_DIR), reverse=True):
        if f.endswith('.jsonl.gz'):
            st = os.stat(os.path.join(REC_DIR, f))
            out.append({'file': f, 'kb': round(st.st_size / 1024, 1), 'created': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))})
    return out
