"""示例数据：练习 PLC 的示范程序和 HMI 画面；控制单元没有自带画面时按 I/O 自动生成一个操作面板。

HMI 画面的来源（优先级从高到低，同一编号只取第一个）：
  1. data/plc/<工厂>/hmi/<编号>.json        用户在界面里保存的（覆盖下面两种）
  2. 控制单元定义里的 hmi 列表               cell.hmi = [{id, name, size, widgets}]，随工厂模型（yaml）一起分发
     vfactory/plc/seeds/<工厂>/*.hmi.json      随软件分发的种子画面（{cell: 单元编号, …}）
  3. 自动生成                                单元没有任何画面时，按 I/O 表生成"<单元名> 操作面板"
  另外练习 PLC 永远有一个示范画面 sandbox_demo。
控制单元的 PLC 程序：data/plc 里没有下载记录时用 cell.plc.program（随模型分发），并直接运行。
"""
from ..i18n import _tr
import copy
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.join(HERE, 'seeds')

SANDBOX_DEMO_PROGRAM = {
    'id': 'main', 'name': '示范：启停 + 定时 + 计数', 'lang': 'LD',
    'vars': [{'name': 'T1', 'type': 'TON', 'comment': '运行 3 秒后开阀'},
             {'name': 'C1', 'type': 'CTU', 'comment': '光电计件'},
             {'name': 'Cnt', 'type': 'INT', 'comment': '已计件数'}],
    'source': {'rungs': [
        {'comment': '启停自锁：按启动电机运行并保持，按停止（或液位超限）停机',
         'elements': [{'par': [[{'id': 'd_start', 't': 'NO', 'var': 'Start'}], [{'id': 'd_hold', 't': 'NO', 'var': 'Motor'}]]},
                      {'id': 'd_stop', 't': 'NC', 'var': 'Stop'}, {'id': 'd_lf', 't': 'NC', 'var': 'Lamp_Fault'},
                      {'par': [[{'id': 'd_motor', 't': 'COIL', 'var': 'Motor'}], [{'id': 'd_lrun', 't': 'COIL', 'var': 'Lamp_Run'}]]}]},
        {'comment': '电机运行 3 秒后打开电磁阀',
         'elements': [{'id': 'd_m2', 't': 'NO', 'var': 'Motor'},
                      {'id': 'd_t1', 't': 'FB', 'fb': 'TON', 'inst': 'T1', 'in': {'PT': 'T#3s'}, 'out': {}},
                      {'id': 'd_valve', 't': 'COIL', 'var': 'Valve'}]},
        {'comment': '光电 1 每检测到一件计数一次，停止按钮清零',
         'elements': [{'id': 'd_s1', 't': 'P', 'var': 'Sensor1'},
                      {'id': 'd_c1', 't': 'FB', 'fb': 'CTU', 'inst': 'C1', 'in': {'R': 'Stop', 'PV': '10'}, 'out': {'CV': 'Cnt'}}]},
        {'comment': '数码管显示件数',
         'elements': [{'id': 'd_mv', 't': 'MOVE', 'in': 'Cnt', 'out': 'Display'}]},
        {'comment': '液位超过 80 报警（停机），低于 60 自动解除',
         'elements': [{'id': 'd_cmp', 't': 'CMP', 'op': '>', 'a': 'Level', 'b': '80'}, {'id': 'd_set', 't': 'SET', 'var': 'Lamp_Fault'}]},
        {'comment': '',
         'elements': [{'id': 'd_cmp2', 't': 'CMP', 'op': '<', 'a': 'Level', 'b': '60'}, {'id': 'd_rst', 't': 'RESET', 'var': 'Lamp_Fault'}]},
    ]},
}

SANDBOX_DEMO_HMI = {
    'id': 'sandbox_demo', 'name': '示范画面（练习 PLC）', 'cell': '_sandbox', 'size': [900, 480], 'source': 'demo',
    'widgets': [
        {'id': 'g1', 'type': 'rect', 'x': 20, 'y': 20, 'w': 420, 'h': 210, 'label': '操作', 'color': '#7d8893'},
        {'id': 'b1', 'type': 'button', 'x': 40, 'y': 50, 'w': 110, 'h': 48, 'label': '启动', 'var': 'Start', 'mode': 'momentary', 'color': '#1f9d55'},
        {'id': 'b2', 'type': 'button', 'x': 170, 'y': 50, 'w': 110, 'h': 48, 'label': '停止', 'var': 'Stop', 'mode': 'momentary', 'color': '#c83a3a'},
        {'id': 'b3', 'type': 'button', 'x': 300, 'y': 50, 'w': 120, 'h': 48, 'label': '来一件（光电1）', 'var': 'Sensor1', 'mode': 'momentary', 'color': '#2f6fa8'},
        {'id': 'l1', 'type': 'lamp', 'x': 40, 'y': 120, 'w': 120, 'h': 44, 'label': '运行', 'var': 'Lamp_Run', 'color': '#22c55e'},
        {'id': 'l2', 'type': 'lamp', 'x': 170, 'y': 120, 'w': 120, 'h': 44, 'label': '电磁阀', 'var': 'Valve', 'color': '#3b82f6'},
        {'id': 'l3', 'type': 'lamp', 'x': 300, 'y': 120, 'w': 130, 'h': 44, 'label': '液位报警', 'var': 'Lamp_Fault', 'color': '#ef4444'},
        {'id': 'i1', 'type': 'input', 'x': 40, 'y': 172, 'w': 180, 'h': 50, 'label': '液位（输入 0–100 回车）', 'var': 'Level'},
        {'id': 'n1', 'type': 'number', 'x': 470, 'y': 30, 'w': 150, 'h': 60, 'label': '件数', 'var': 'Display', 'unit': '件'},
        {'id': 'n2', 'type': 'number', 'x': 640, 'y': 30, 'w': 150, 'h': 60, 'label': 'T1 已计时', 'var': 'T1.ET'},
        {'id': 'r1', 'type': 'bar', 'x': 820, 'y': 30, 'w': 60, 'h': 200, 'label': '液位', 'var': 'Level', 'min': 0, 'max': 100, 'color': '#3b82f6'},
        {'id': 't1', 'type': 'trend', 'x': 470, 'y': 110, 'w': 330, 'h': 180, 'label': '液位趋势', 'vars': ['Level'], 'min': 0, 'max': 100},
        {'id': 'x1', 'type': 'text', 'x': 20, 'y': 250, 'w': 430, 'h': 60, 'size': 13,
         'label': '练习 PLC 没有接设备：按钮相当于现场按钮（按下=强制为 1），液位在左边输入。程序在“PLC 编程”里，可以随便改。'},
    ],
}

_SAFE = re.compile(r'[^A-Za-z0-9_\-]')

# 自动面板里按部件类型放控件
_IN_BUTTON = ('button', 'estop', 'switch')


def _norm_screen(s, cell_id, i):
    s = copy.deepcopy(s)
    s['id'] = _SAFE.sub('_', str(s.get('id') or f'{cell_id}_hmi{i + 1}'))[:64]
    s.setdefault('name', s['id'])
    s.setdefault('cell', cell_id)
    s.setdefault('size', [960, 560])
    s.setdefault('widgets', [])
    return s


def seed_screens(pid):
    out = []
    for f in sorted(glob.glob(os.path.join(SEEDS, _SAFE.sub('_', pid), '*.hmi.json'))):
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        s = _norm_screen(d, d.get('cell') or '', 0)
        s['source'] = 'seed'
        out.append(s)
    return out


def cell_screens(cell_id, cell_def):
    out = []
    for i, s in enumerate(cell_def.get('hmi') or []):
        if isinstance(s, dict):
            s = _norm_screen(s, cell_id, i)
            s['source'] = 'model'
            out.append(s)
    return out


_PANEL_TYPES = {'button', 'estop', 'switch'}


def auto_screen(cell_id, name, io, components=None):
    """按 I/O 表生成操作面板：面板按钮/急停是"按面板按钮"（常闭接法由单元处理），其他输入（光电、限位）是"模拟信号"按钮，
    输出是指示灯，数值是数值显示。"""
    ctype = {c.get('id'): c.get('type') for c in components or []}
    ws = []
    x, y = 30, 54
    ins = [e for e in io if e.get('dir') == 'in']
    outs = [e for e in io if e.get('dir') == 'out']
    ws.append({'id': 'gi', 'type': 'text', 'x': 30, 'y': 18, 'w': 400, 'h': 28, 'size': 14, 'label': _tr('输入（按下 = 现场信号为 1）')})
    for k, e in enumerate(ins[:16]):
        t = (e.get('type') or 'BOOL').upper()
        lab = (e.get('comment') or e['name'])[:12]
        if t == 'BOOL':
            w = {'id': f'i{k}', 'type': 'button', 'x': x, 'y': y, 'w': 130, 'h': 40, 'label': lab, 'var': e['name'], 'mode': 'momentary',
                 'color': '#2f6fa8'}
            kind = ctype.get(e.get('comp'))
            if kind in _PANEL_TYPES:
                w.update(panel=True, color='#c83a3a' if kind == 'estop' or 'STOP' in e['name'].upper() else '#1f9d55')
                if kind in ('estop', 'switch'):
                    w['mode'] = 'toggle'
            ws.append(w)
        else:
            ws.append({'id': f'i{k}', 'type': 'number', 'x': x, 'y': y, 'w': 130, 'h': 52, 'label': lab, 'var': e['name']})
        x += 145
        if x > 600:
            x, y = 30, y + 64
    y2 = y + 90
    ws.append({'id': 'go', 'type': 'text', 'x': 30, 'y': y2 - 36, 'w': 400, 'h': 28, 'size': 14, 'label': _tr('输出（PLC 给执行器、指示灯）')})
    x, y = 30, y2
    for k, e in enumerate(outs[:16]):
        t = (e.get('type') or 'BOOL').upper()
        lab = (e.get('comment') or e['name'])[:12]
        if t == 'BOOL':
            ws.append({'id': f'o{k}', 'type': 'lamp', 'x': x, 'y': y, 'w': 140, 'h': 40, 'label': lab, 'var': e['name'], 'color': '#22c55e'})
        else:
            ws.append({'id': f'o{k}', 'type': 'number', 'x': x, 'y': y, 'w': 140, 'h': 52, 'label': lab, 'var': e['name']})
        x += 150
        if x > 620:
            x, y = 30, y + 60
    h = max(360, y + 90)
    return {'id': _SAFE.sub('_', f'auto_{cell_id}')[:64], 'name': _tr('{name} 操作面板（自动生成）', name=name), 'cell': cell_id, 'size': [800, h], 'widgets': ws,
            'source': 'auto'}


def sorting_panel_hmi(cell_id='CELL1'):
    """示范工厂"检测后分拣段"的操作画面（I/O 名见 vfactory/control/showcase.py 的 sorting_cell）。
    控制层可以直接写进单元定义：cell['hmi'] = [sorting_panel_hmi()]，就随工厂模型分发。"""
    lamp = lambda i, x, y, lab, var, color: {'id': i, 'type': 'lamp', 'x': x, 'y': y, 'w': 135, 'h': 40, 'label': lab, 'var': var, 'color': color}  # noqa: E731
    return {
        'id': 'sort_panel', 'name': _tr('分拣段操作画面'), 'cell': cell_id, 'size': [940, 520],
        'widgets': [
            {'id': 'g1', 'type': 'rect', 'x': 20, 'y': 20, 'w': 430, 'h': 220, 'label': _tr('操作台'), 'color': '#7d8893'},
            {'id': 'b1', 'type': 'button', 'x': 40, 'y': 50, 'w': 120, 'h': 50, 'label': _tr('启动'), 'var': 'START', 'panel': True, 'mode': 'momentary',
             'color': '#1f9d55'},
            {'id': 'b2', 'type': 'button', 'x': 175, 'y': 50, 'w': 120, 'h': 50, 'label': _tr('停止'), 'var': 'STOP', 'panel': True, 'mode': 'momentary',
             'color': '#c83a3a'},
            {'id': 'b3', 'type': 'button', 'x': 310, 'y': 50, 'w': 120, 'h': 50, 'label': _tr('急停（按下/复位）'), 'var': 'ESTOP', 'panel': True,
             'mode': 'toggle', 'color': '#b91c1c'},
            {'id': 'l1', 'type': 'lamp', 'x': 40, 'y': 120, 'w': 120, 'h': 44, 'label': _tr('运行'), 'var': 'LAMP_RUN', 'color': '#22c55e'},
            {'id': 'l2', 'type': 'lamp', 'x': 175, 'y': 120, 'w': 120, 'h': 44, 'label': _tr('剔除'), 'var': 'LAMP_NG', 'color': '#ef4444'},
            {'id': 'l3', 'type': 'lamp', 'x': 310, 'y': 120, 'w': 130, 'h': 44, 'label': _tr('输送带'), 'var': 'C1_FWD', 'color': '#3b82f6'},
            {'id': 'n1', 'type': 'number', 'x': 40, 'y': 176, 'w': 190, 'h': 56, 'label': _tr('合格数（数码管 D1）'), 'var': 'D1', 'unit': '件'},
            {'id': 'n2', 'type': 'number', 'x': 245, 'y': 176, 'w': 190, 'h': 56, 'label': _tr('视觉识别码（4=缺陷）'), 'var': 'V1_CODE'},
            {'id': 'g2', 'type': 'rect', 'x': 470, 'y': 20, 'w': 450, 'h': 220, 'label': _tr('现场信号'), 'color': '#7d8893'},
            lamp('s1', 490, 50, _tr('视觉有件'), 'V1_DETECT', '#f2b632'), lamp('s2', 635, 50, _tr('推杆前光电'), 'S1', '#f2b632'),
            lamp('s3', 780, 50, _tr('线尾光电'), 'S_END', '#f2b632'), lamp('s4', 490, 100, _tr('推杆伸出'), 'P1_EXTEND', '#3b82f6'),
            lamp('s5', 635, 100, _tr('伸出到位'), 'P1_FRONT', '#3b82f6'), lamp('s6', 780, 100, _tr('缺陷件在途'), 'IS_NG', '#ef4444'),
            lamp('s7', 490, 150, _tr('NG 箱满'), 'OUT_NG_BUSY', '#ef4444'), lamp('s8', 635, 150, _tr('合格口满'), 'OUT_OK_BUSY', '#ef4444'),
            {'id': 't1', 'type': 'trend', 'x': 20, 'y': 260, 'w': 900, 'h': 180, 'label': _tr('输送带 / 推杆前光电 / 推杆'), 'vars': ['C1_FWD', 'S1', 'P1_EXTEND'],
             'min': 0, 'max': 1.2},
            {'id': 'x1', 'type': 'text', 'x': 20, 'y': 452, 'w': 900, 'h': 50, 'size': 13,
             'label': _tr('按钮等于按单元操作台上的实体按钮（停止、急停是常闭接法，单元自动处理）。视觉看到红色（缺陷）件时，推杆在光电 S1 处把它推进 NG 料箱。')},
        ],
    }
