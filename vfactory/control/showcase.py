"""示范工厂（foundry-housing）里的控制单元：检测后的分拣段。

    python -m vfactory.control.showcase plants/foundry-housing.yaml    # 把旧版示范工厂转成 2.0 模型并插入分拣段（只需运行一次）
    python -m vfactory.control.showcase --templates templates/cells    # 重新生成 8 个控制单元演示模板

分拣段：内窥检测站 INS1 放行的件进入单元，视觉复检；带真实缺陷的漏检件（视觉显示为红色）被推杆推进 NG 料箱，经单元的 ng 口
送到"复检剔除品"出口报废；合格件到线尾经单元 out 口进成品待入库缓存 fg，再由 AGV 送立库。4.3 起 PLC 是独立设备：
程序（梯形图）在 PLC 块 PLC1 的 params.program，信号线 SIG1 把单元的全部 I/O 接到 PLC1；
全新安装（没有 data/ 目录）也能直接运行：上电即运行（RUN 初值 TRUE），按停止/急停后要按启动。
"""
from ..i18n import _tr
import copy
import os
import sys

from .catalog import auto_io

Z = 0.27


def _c(cid, typ, pos, rot=0, size=None, label='', **params):
    d = {'id': cid, 'type': typ, 'pos': list(pos), 'rot': rot}
    if size:
        d['size'] = list(size)
    if label:
        d['label'] = label
    if params:
        d['params'] = params
    return d


NO = lambda v: {'t': 'NO', 'var': v}           # noqa: E731
NC = lambda v: {'t': 'NC', 'var': v}           # noqa: E731
R = lambda c, *els: {'comment': c, 'elements': list(els)}  # noqa: E731


def ladder():
    """分拣段的参考程序（梯形图）。"""
    rungs = [
        R(_tr('启保停：上电即运行（RUN 初值为 1）；停止、急停是常闭触点'), {'par': [[NO('START')], [NO('RUN')]]}, NO('STOP'), NO('ESTOP'), {'t': 'COIL', 'var': 'RUN'}),
        R(_tr('输送带'), NO('RUN'), {'t': 'COIL', 'var': 'C1_FWD'}),
        R(_tr('运行指示灯'), NO('RUN'), {'t': 'COIL', 'var': 'LAMP_RUN'}),
        R(_tr('视觉复检：识别到缺陷（红色码 4）置位 NG 标志'), NO('V1_DETECT'), {'t': 'CMP', 'op': '=', 'a': 'V1_CODE', 'b': '4'}, {'t': 'SET', 'var': 'IS_NG'}),
        R(_tr('视觉看到合格件：复位 NG 标志'), NO('V1_DETECT'), {'t': 'CMP', 'op': '<>', 'a': 'V1_CODE', 'b': '4'}, {'t': 'RESET', 'var': 'IS_NG'}),
        R(_tr('NG 件到推杆前（S1 上升沿）：推杆动作'), {'t': 'P', 'var': 'S1'}, NO('IS_NG'), NO('RUN'), {'t': 'SET', 'var': 'PUSH'}),
        R(_tr('推杆动作后清掉 NG 标志'), NO('PUSH'), {'t': 'RESET', 'var': 'IS_NG'}),
        R(_tr('伸出到位或停机：推杆缩回'), {'par': [[NO('P1_FRONT')], [NC('RUN')]]}, {'t': 'RESET', 'var': 'PUSH'}),
        R(_tr('推杆电磁阀'), NO('PUSH'), {'t': 'COIL', 'var': 'P1_EXTEND'}),
        R(_tr('剔除指示灯：剔除后亮 3 秒'), NO('PUSH'), {'t': 'FB', 'fb': 'TOF', 'inst': 'T_NG', 'in': {'PT': 'T#3s'}}, {'t': 'COIL', 'var': 'LAMP_NG'}),
        R(_tr('合格件计数（线尾光电）'), NO('S_END'), {'t': 'FB', 'fb': 'CTU', 'inst': 'C_OK', 'in': {'R': 'FALSE', 'PV': '32767'}}, {'t': 'COIL', 'var': 'OK_FULL'}),
        R(_tr('数码管显示合格数'), {'t': 'MOVE', 'in': 'C_OK.CV', 'out': 'D1'}),
    ]
    return {'id': 'main', 'name': _tr('分拣段主程序'), 'lang': 'LD',
            'vars': [{'name': 'RUN', 'type': 'BOOL', 'init': True, 'comment': _tr('运行（上电即运行）')},
                     {'name': 'IS_NG', 'type': 'BOOL', 'comment': _tr('视觉判定的缺陷件在途')},
                     {'name': 'PUSH', 'type': 'BOOL', 'comment': _tr('推杆动作中')},
                     {'name': 'OK_FULL', 'type': 'BOOL', 'comment': _tr('计数器满（不用）')}],
            'source': {'rungs': rungs}}


def sorting_cell():
    comps = [
        _c('IN1', 'cell_entry', (-3.6, 0, Z), label=_tr('来自内窥检测'), min_gap=4.0,
           assign={'default': {'kind': 'part', 'color': 'grey', 'material': 'metal', 'h': 0.18, 'w': 0.26}, 'defect': {'color': 'red'}}),
        _c('C1', 'belt_conveyor', (0, 0, 0), size=(7.6, 0.6), label=_tr('分拣输送带'), speed=0.3),
        _c('V1', 'vision_sensor', (-0.6, 0, 0.9), label=_tr('视觉复检'), radius=0.12, mode='color'),
        _c('S1', 'diffuse_sensor', (0.6, 0.35, 0.33), label=_tr('推杆前光电')),
        _c('P1', 'pusher', (0.6, 0.42, 0.33), label=_tr('剔除推杆'), stroke=0.8, speed=1.0),
        _c('OUT_NG', 'cell_exit', (0.6, -0.76, 0), size=(0.9, 0.9), label=_tr('NG 料箱'), port='ng', accept={'color': 'red'}),
        _c('S_END', 'diffuse_sensor', (3.3, 0.35, 0.33), label=_tr('线尾计数光电')),
        _c('OUT_OK', 'cell_exit', (3.85, 0, 0), size=(0.3, 0.9), label=_tr('合格出口'), accept={'color': 'grey'}),
        _c('START', 'button', (-3.5, 1.45, 0.95), label=_tr('启动'), color='green'),
        _c('STOP', 'button', (-3.3, 1.45, 0.95), label=_tr('停止'), color='red', nc=True),
        _c('ESTOP', 'estop', (-3.05, 1.45, 0.95), label=_tr('急停')),
        _c('LAMP_RUN', 'lamp', (-2.8, 1.45, 0.95), label=_tr('运行'), color='green'),
        _c('LAMP_NG', 'lamp', (-2.6, 1.45, 0.95), label=_tr('剔除'), color='red'),
        _c('D1', 'display', (-2.3, 1.45, 0.95), label=_tr('合格数')),
    ]
    cell = {'size': [8, 3.6], 'components': comps, 'plc': {'mode': 'internal', 'scan_ms': 20}}
    cell['io'] = auto_io(cell, keep=[])
    cell['plc']['program'] = ladder()
    try:                                     # 分拣段的 HMI 画面（PLC 层提供）随单元定义一起分发
        from ..plc.demo import sorting_panel_hmi
        cell['hmi'] = [sorting_panel_hmi('CELL1')]
    except Exception:
        pass
    return cell


HEADER = ('# 示范工厂：某转向器壳体铸造厂（铸造 + 机加 + 去毛刺 + 内窥检测 + 检测后分拣段 + 立库），2.0 项目模型。\n'
          '# 坐标单位 m：x 沿厂房长度方向，y 为进深方向；size = [长, 宽]。分拣段 CELL1 由独立的 PLC 块控制（信号线连接），梯形图程序在该 PLC 块的 params.program。\n')


def add_to(model):
    """在 2.0 模型里插入分拣段：INS1 → CELL1 → fg；CELL1 的 ng → NG1（报废出口）。"""
    m = copy.deepcopy(model)
    if any(b['id'] == 'CELL1' for b in m['blocks']):
        return m
    ins = next(b for b in m['blocks'] if b['id'] == 'INS1')
    node = ins.get('node') or [2760, 40]
    m['blocks'].append({'id': 'CELL1', 'type': 'cell', 'name': _tr('检测后分拣段'), 'pos': [120.5, 20.5], 'size': [8, 3.6], 'rot': 0, 'area': _tr('检测区'),
                        'node': [node[0] + 115, node[1] + 150], 'params': {'cell': sorting_cell(), 'substep_ms': 40, 'bypass_s': 30}})
    m['blocks'].append({'id': 'NG1', 'type': 'sink', 'name': _tr('复检剔除品'), 'pos': [126.5, 26.5], 'size': [3, 3], 'rot': 0, 'area': _tr('检测区'),
                        'node': [node[0] + 230, node[1] + 290], 'params': {'scrap': True, 'scrap_cause': _tr('分拣段复检剔除'), 'ship_every_h': 0}})
    for l in m['links']:
        if l['from'] == 'INS1' and (l.get('from_port') or 'out') == 'out' and l['to'] == 'fg':
            l['to'], l['to_port'] = 'CELL1', 'in'
    n = len(m['links'])
    m['links'].append({'id': f'L{n + 1}', 'kind': 'material', 'from': 'CELL1', 'from_port': 'out', 'to': 'fg', 'to_port': 'in'})
    m['links'].append({'id': f'L{n + 2}', 'kind': 'material', 'from': 'CELL1', 'from_port': 'ng', 'to': 'NG1', 'to_port': 'in'})
    from ..plc.migrate import migrate_model              # 4.3：单元里的 PLC → 独立 PLC 块 + 信号线
    migrate_model(m)
    return m


# 控制单元演示模板（templates/cells/<文件名>.yaml）：一个场景 + 参考答案，上电即运行
DEMOS = [('line', 's15_full_line', '控制单元演示：整线联动（接入整厂）'),
         ('sort', 's04_sort_color', '控制单元演示：视觉按颜色分拣（推杆）'),
         ('pivot', 's06_sort_height', '控制单元演示：测高按高度分拣（摆臂）'),
         ('box', 's07_count_box', '控制单元演示：计数装箱'),
         ('palletize', 's09_palletize', '控制单元演示：伺服取放机械手码垛'),
         ('lift', 's11_lift', '控制单元演示：升降机两层输送'),
         ('asrs', 's13_asrs', '控制单元演示：堆垛机立体仓库出入库'),
         ('motor', 's02_fwd_rev', '控制单元演示：电机正反转互锁（按面板按钮操作）')]


def demo_plant(sid, name):
    from . import scenes
    m = scenes.scene_plant(sid, title=name, with_reference=True, speed=1)
    prog = next(b for b in m['blocks'] if b['type'] == 'plc')['params']['program']
    if isinstance(prog.get('source'), str):         # 演示：上电即运行（运行标志初值 TRUE）
        prog['source'] = prog['source'].replace('    RUN : BOOL;', '    RUN : BOOL := TRUE;     (* 演示：上电即运行 *)', 1)
    m['plant'].pop('modbus_port', None)
    m['plant']['start'] = 'now'
    return m


def write_templates(folder):
    from ..server import write_yaml
    os.makedirs(folder, exist_ok=True)
    for fn, sid, name in DEMOS:
        path = os.path.join(folder, fn + '.yaml')
        write_yaml(path, demo_plant(sid, name))
        with open(path, encoding='utf-8') as f:
            body = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f'# {name}' + chr(10) + _tr('# 由 python -m vfactory.control.showcase --templates 生成：场景 {sid} + 参考答案（程序在 PLC 块的 params.program，信号线接单元 I/O）', sid=sid) + chr(10) + body)
    print(_tr('已生成'), len(DEMOS), _tr('个控制单元演示模板 →'), os.path.abspath(folder))


def main(path):
    import yaml

    from ..flow.model import to_v2
    from ..server import write_yaml
    with open(path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    m = add_to(to_v2(cfg))
    from ..plc.migrate import migrate_model
    migrate_model(m)
    write_yaml(path, m)
    with open(path, encoding='utf-8') as f:
        body = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(HEADER + body)
    print(_tr('已写入'), os.path.abspath(path), len(m['blocks']), _tr('块'), len(m['links']), _tr('条连线'))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--templates':
        write_templates(sys.argv[2] if len(sys.argv) > 2 else 'templates/cells')
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else 'plants/foundry-housing.yaml')
