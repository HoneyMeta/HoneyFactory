"""5.0 原始现场模式（raw site）：协议层不用我们整洁的点位名，而是像集成商刚调完的现场那样，用 PLC 地址和拼音缩写。

用途：让 MES 走"拿到半成品点表 → 自己摸清点位含义"的标准接入路径（AI 补全点表），并能打分（答案另存，见 delivery.py）。
开关：工厂配置 plant.raw_site: true（默认关）；接口 PUT /api/p/{pid}/delivery/raw_site。切换时协议层重建，仿真不重置。

命名（同一座工厂、同样的设备顺序 → 名字每次都一样）
- 设备按区域分到 S7 PLC：PLC1、PLC2…（每台设备一个数据块 DB10、DB11…）
    实数 / 整数 → DB10.DBD4（4 字节），开关量 → DB10.DBX0.3，字符串 → DB10.DBB40（STRING[40]）
    动作信号：电磁阀 / 指令 → Q0.3，到位传感器 → I1.2，循环 / 主轴 → M2.0，段号 / 计数 → MW4，用时 → MD8
- 加工中心各有自己的数控系统：M1…M6，点位名是"机床号_中文说明拼音首字母"，例如 M3_ZZFZ（主轴负载）；
    动作信号用 PMC 地址：输入 X8.4、输出 Y0.3、内部 R0.1
- 其它（网关、交换机、MES、AGV 调度）：SYS 下，SYS_<拼音首字母>
- 有少量"不规整"的：默认名 Tag123、主题里双斜杠、大写、空格、_new 后缀；最后一台 PLC 的 MQTT 载荷是纯文本数值（不是 JSON）

OPC UA：ns=2;s=<工厂>/<通道>.<设备>.<地址>，目录 <工厂>/<通道>/<设备>/<地址>（通道 S7 / CNC / SYS）
MQTT：vfactory/<工厂>/<边缘网关>/<PLC>/<地址>、vfactory/<工厂>/jj/M3_ZZFZ、vfactory/<工厂>/sys/…（写入同样是 <主题>/set）
Modbus：地址不变（寄存器本来就没有名字），点表里只有 从站:表:地址。
"""
from __future__ import annotations

from .i18n import _tr
NET_KINDS = ('gateway', 'switch', 'scada', 'mes')
# GB2312 一级汉字按拼音排序：区位码落在哪一段就是哪个声母
_GB = [(0xB0A1, 'A'), (0xB0C5, 'B'), (0xB2C1, 'C'), (0xB4EE, 'D'), (0xB6EA, 'E'), (0xB7A2, 'F'), (0xB8C1, 'G'), (0xB9FE, 'H'), (0xBBF7, 'J'),
       (0xBFA6, 'K'), (0xC0AC, 'L'), (0xC2E8, 'M'), (0xC4C3, 'N'), (0xC5B6, 'O'), (0xC5BE, 'P'), (0xC6DA, 'Q'), (0xC8BB, 'R'), (0xC8F6, 'S'),
       (0xCBFA, 'T'), (0xCDDA, 'W'), (0xCEF4, 'X'), (0xD1B9, 'Y'), (0xD4D1, 'Z'), (0xD7FA, '')]


def initials(text: str, n=4) -> str:
    """中文说明 → 拼音首字母（大写），字母数字原样；其它字符跳过。"""
    out = []
    for ch in str(text or ''):
        if ch.isascii():
            if ch.isalnum():
                out.append(ch.upper())
        else:
            try:
                b = ch.encode('gb2312')
            except UnicodeEncodeError:
                continue
            if len(b) != 2:
                continue
            code = (b[0] << 8) | b[1]
            letter = ''
            for i in range(len(_GB) - 1):
                if _GB[i][0] <= code < _GB[i + 1][0]:
                    letter = _GB[i][1]
                    break
            if letter:
                out.append(letter)
        if len(out) >= n:
            break
    return ''.join(out)


def enabled(plant) -> bool:
    return bool((plant.cfg.get('plant') or {}).get('raw_site'))


def _sig(plant):
    return (plant.layout_version, len(plant.stations), sum(len(st.tags) for st in plant.stations.values()))


def names(plant) -> dict:
    """{(设备, 点位): {opc, path, topic, plain, code, ctrl, addr}}，缓存在 plant 上，设备或点位变了重算。"""
    c = getattr(plant, '_raw_names', None)
    s = _sig(plant)
    if c is not None and c[0] == s:
        return c[1]
    m = build(plant)
    plant._raw_names = (s, m)
    plant._raw_rev = {v['topic']: k for k, v in m.items()}
    return m


def by_topic(plant, suffix):
    names(plant)
    return getattr(plant, '_raw_rev', {}).get(suffix)


def _is_out(tname):
    leaf = tname.rsplit('/', 1)[-1]
    return leaf.endswith('Valve') or leaf.endswith('Cmd')


def _is_mbit(tname):
    return tname.rsplit('/', 1)[-1] in ('CycleOn', 'SpindleRun')


def build(plant) -> dict:
    sts = list(plant.stations.values())
    area_plc, plc_of, db_of, cnc_of = {}, {}, {}, {}
    n_cnc = 0
    for st in sts:
        if st.kind == 'cnc':
            n_cnc += 1
            cnc_of[st.id] = f'M{n_cnc}'
        elif st.kind in NET_KINDS or st.kind in ('agv', 'crew'):
            continue
        else:
            a = st.area or _tr('其它')
            if a not in area_plc:
                area_plc[a] = len(area_plc) + 1
            plc_of[st.id] = area_plc[a]
    per_plc = {}
    for st in sts:
        if st.id in plc_of:
            k = plc_of[st.id]
            db_of[st.id] = 10 + per_plc.get(k, 0)
            per_plc[k] = per_plc.get(k, 0) + 1
    last_plc = max(area_plc.values()) if area_plc else 0
    io = {}                     # 控制器 → 计数器（I/Q/M 字节位、MW/MD 偏移）
    out, used_topics, sys_names = {}, set(), set()
    i = 0

    def bit(ctrl, kind):
        c = io.setdefault(ctrl, {})
        n = c.get(kind, 0)
        c[kind] = n + 1
        return n // 8, n % 8

    def word(ctrl, kind, size):
        c = io.setdefault(ctrl, {})
        n = c.get(kind, 0)
        c[kind] = n + size
        return n

    for st in sts:
        db = db_of.get(st.id)
        off, bitpos = 0, 0                       # 数据块里的字节偏移 / 当前字节里的位
        used_names = set()
        for tname, tag in st.tags.items():
            i += 1
            dt = tag.dtype
            ev = getattr(tag, 'event', False)
            if st.id in cnc_of:                   # 数控系统：拼音缩写 + PMC 地址
                M = cnc_of[st.id]
                ctrl, chan = M, 'CNC'
                if ev and dt == 'bool':
                    if _is_out(tname):
                        b, k = bit(M, 'Y')
                        addr = f'Y{b}.{k}'
                    elif _is_mbit(tname):
                        b, k = bit(M, 'R')
                        addr = f'R{b}.{k}'
                    else:
                        b, k = bit(M, 'X')
                        addr = f'X{8 + b}.{k}'
                    name, topic = f'{M}.{addr}', f'jj/{M}/{addr}'
                else:
                    base = f"{M}_{initials(tag.desc) or 'D'}"
                    nm, j = base, 1
                    while nm in used_names:
                        j += 1
                        nm = f'{base}{j}'
                    used_names.add(nm)
                    addr = nm
                    name, topic = nm, f'jj/{nm}'
                path = [chan, M, addr]
            elif db is not None:                  # S7 PLC 数据块
                P = f'PLC{plc_of[st.id]}'
                ctrl, chan = P, 'S7'
                if ev and dt == 'bool':
                    if _is_out(tname):
                        b, k = bit(P, 'Q')
                        addr = f'Q{b}.{k}'
                    elif _is_mbit(tname):
                        b, k = bit(P, 'M')
                        addr = f'M{b}.{k}'
                    else:
                        b, k = bit(P, 'I')
                        addr = f'I{b}.{k}'
                elif ev and dt == 'int':
                    addr = f"MW{100 + word(P, 'MW', 2)}"
                elif ev and dt == 'float':
                    addr = f"MD{200 + word(P, 'MD', 4)}"
                elif dt == 'bool':
                    addr = f'DB{db}.DBX{off}.{bitpos}'
                    bitpos += 1
                    if bitpos == 8:
                        off, bitpos = off + 1, 0
                else:
                    if bitpos:
                        off, bitpos = off + 1, 0
                    if off % 2:
                        off += 1
                    if dt == 'str':
                        addr = f'DB{db}.DBB{off}'
                        off += 42
                    else:
                        addr = f'DB{db}.DBD{off}'
                        off += 4
                if i % 29 == 13:                   # 集成商忘了改名的默认变量
                    addr = f'Tag{i}'
                name = f'{P}.{addr}'
                edge = 'edge01' if plc_of[st.id] <= 2 else 'edge02'
                pseg = 'PLC 3' if plc_of[st.id] == 3 else P
                topic = f'{edge}/{pseg}/{addr}'
                path = [chan, P, addr]
            else:                                 # 网络设备、AGV 调度、班组
                ctrl, chan = 'SYS', 'SYS'
                base = f"SYS_{st.kind[:3].upper()}_{initials(tag.desc) or 'D'}"
                nm, j = base, 1
                while nm in sys_names:
                    j += 1
                    nm = f'{base}{j}'
                sys_names.add(nm)
                addr = name = nm
                topic = f'sys/{nm}'
                path = [chan, 'SYS', addr]
            if i % 31 == 7:                       # 不规整的主题
                topic = topic.replace('/', '//', 1)
            elif i % 37 == 11:
                topic = topic.upper()
            elif i % 43 == 5:
                topic += '_new'
            t0, j = topic, 1
            while topic in used_topics:
                j += 1
                topic = f'{t0}_{j}'
            used_topics.add(topic)
            out[(st.id, tname)] = {'opc': '.'.join(path), 'path': path, 'topic': topic, 'code': name, 'ctrl': ctrl, 'addr': addr,
                                   'plain': db is not None and plc_of[st.id] == last_plc and last_plc > 1}
    return out
