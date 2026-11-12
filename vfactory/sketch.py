"""平面草图：把工厂配置压成几十个矩形，给开始页的模板预览 / 最近打开的缩略图用（前端 web/src/start/sketch.ts 画成 SVG）。

    plan_sketch(cfg) -> {'floor': [宽, 深], 'areas': [[x0, x1, 颜色], ...], 'r': [[x, y, w, h, 类], ...]}

类：p 生产设备、c 控制（PLC/HMI）、n 通讯（网关/交换机）、i 信息系统（SCADA/MES）、u 控制单元、e 单元里的部件、s 单元里的传感器/按钮。
"""

CONTROL = {'plc', 'hmi', 'soft_plc'}
NETWORK = {'gateway', 'switch', 'router', 'iot_gateway'}
IT = {'scada', 'mes', 'erp', 'historian'}
SKIP = {'transporter', 'operators', 'agv_fleet', 'crew'}
SENSOR_WORDS = ('sensor', 'button', 'switch', 'lamp', 'estop', 'knob', 'display', 'pot', 'encoder', 'proximity', 'photo')


def _kind(t):
    t = str(t or '')
    if t in CONTROL:
        return 'c'
    if t in NETWORK:
        return 'n'
    if t in IT:
        return 'i'
    if t == 'cell':
        return 'u'
    return 'p'


def _num(v, d=0.0):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return d


def plan_sketch(cfg, limit=300):
    """cfg：模板 / 工厂的 YAML 内容（dict）。出错或没有设备时返回 None。"""
    try:
        blocks = cfg.get('blocks') or cfg.get('stations') or []
        plant = cfg.get('plant') or {}
        rects = []
        for b in blocks:
            if not isinstance(b, dict) or b.get('type') in SKIP:
                continue
            pos, size = b.get('pos') or [0, 0], b.get('size') or [3, 3]
            x, y, w, h = _num(pos[0]), _num(pos[1] if len(pos) > 1 else 0), _num(size[0], 3), _num(size[1] if len(size) > 1 else size[0], 3)
            if round(_num(b.get('rot'))) % 180 == 90:
                w, h = h, w
            rects.append([x, y, w, h, _kind(b.get('type'))])
            cell = ((b.get('params') or {}).get('cell') or {}) if b.get('type') == 'cell' else {}
            for c in cell.get('components') or []:
                cp = c.get('pos') or [0, 0]
                cs = c.get('size') or [0.5, 0.5]
                cw, ch = _num(cs[0], 0.5), _num(cs[1] if len(cs) > 1 else cs[0], 0.5)
                if round(_num(c.get('rot'))) % 180 == 90:
                    cw, ch = ch, cw
                small = any(k in str(c.get('type') or '') for k in SENSOR_WORDS)
                rects.append([round(x + _num(cp[0]), 2), round(y + _num(cp[1] if len(cp) > 1 else 0), 2), max(cw, 0.25), max(ch, 0.25), 's' if small else 'e'])
            if len(rects) >= limit:
                break
        if not rects:
            return None
        fl = plant.get('floor') or (cfg.get('layout') or {}).get('floor')
        if not (isinstance(fl, (list, tuple)) and len(fl) >= 2):
            fl = [max(r[0] + r[2] / 2 for r in rects) + 2, max(r[1] + r[3] / 2 for r in rects) + 2]
        areas = []
        for a in cfg.get('areas') or []:
            ax = a.get('x') if isinstance(a, dict) else None
            if isinstance(ax, (list, tuple)) and len(ax) >= 2:
                areas.append([_num(ax[0]), _num(ax[1]), str(a.get('color') or '')])
        return {'floor': [_num(fl[0], 40), _num(fl[1], 30)], 'areas': areas[:20], 'r': rects}
    except Exception:
        return None
