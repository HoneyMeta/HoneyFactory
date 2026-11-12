"""生成场景库 vfactory/control/scenes/*.json（15 个由易到难的 PLC 实训场景）。

    python -m vfactory.control.scenes.build      # 改了这里的定义后重新生成 JSON

每个场景：单元定义（含 I/O 表）、任务书（Markdown）、评分规则、自动测试序列、参考答案（ST；前 5 个另有梯形图）、可注入故障清单。
"""
import copy
import json
import os

from ..catalog import COMP_TYPES, FAULTS, auto_io, nc_inputs

HERE = os.path.dirname(os.path.abspath(__file__))
BELT = 0.25          # 输送机台面高度
BEAM = 0.35          # 侧装光电光束高度
EMIT = BELT + 0.02   # 发料口高度


# ---------------------------------------------------------------- 部件快捷写法
def C(cid, typ, pos, rot=0, size=None, label='', **params):
    d = {'id': cid, 'type': typ, 'pos': list(pos) + [0] * (3 - len(pos)), 'rot': rot}
    if size:
        d['size'] = list(size)
    if label:
        d['label'] = label
    if params:
        d['params'] = params
    return d


def belt(cid, x, y, L, rot=0, speed=0.3, W=0.6, label='', **kw):
    return C(cid, 'belt_conveyor', (x, y, 0), rot, (L, W), label, speed=speed, **kw)


def panel(x0=-3.6, y=1.6, extra=()):
    """标准操作台：启动（绿）、停止（红，常闭）、急停（常闭）、运行灯。"""
    z = 0.95
    out = [C('START', 'button', (x0, y, z), label='启动', color='green'),
           C('STOP', 'button', (x0 + 0.2, y, z), label='停止', color='red', nc=True),
           C('ESTOP', 'estop', (x0 + 0.45, y, z), label='急停'),
           C('LAMP_RUN', 'lamp', (x0 + 0.7, y, z), label='运行', color='green')]
    x = x0 + 0.9
    for e in extra:
        e = copy.deepcopy(e)
        e['pos'] = [x, y, z]
        out.append(e)
        x += 0.2 if e['type'] != 'display' else 0.3
    return out


RUN_ST = """    (* 启停：启动按钮自锁，停止按钮和急停按钮都是常闭触点（没按时为 TRUE） *)
    RUN := (START OR RUN) AND STOP AND ESTOP;
    LAMP_RUN := RUN;
"""


def prog(name, src, vars_=None, lang='ST'):
    return {'id': 'reference', 'name': name, 'lang': lang, 'vars': vars_ or [], 'source': src}


def ld(name, rungs, vars_):
    return {'id': 'reference_ld', 'name': name + '（梯形图）', 'lang': 'LD', 'vars': vars_, 'source': {'rungs': rungs}}


def V(name, typ='BOOL', init=None, comment=''):
    d = {'name': name, 'type': typ, 'comment': comment}
    if init is not None:
        d['init'] = init
    return d


NO = lambda v: {'t': 'NO', 'var': v}           # noqa: E731
NC = lambda v: {'t': 'NC', 'var': v}           # noqa: E731
PE = lambda v: {'t': 'P', 'var': v}            # noqa: E731
COIL = lambda v: {'t': 'COIL', 'var': v}       # noqa: E731
SET = lambda v: {'t': 'SET', 'var': v}         # noqa: E731
RST = lambda v: {'t': 'RESET', 'var': v}       # noqa: E731


def PAR(*branches):
    return {'par': [list(b) if isinstance(b, (list, tuple)) else [b] for b in branches]}


def R(comment, *els):
    return {'comment': comment, 'elements': list(els)}


RUN_LD = [R('启停自锁：启动并联自锁触点，串常闭停止和急停', PAR(NO('START'), NO('RUN')), NO('STOP'), NO('ESTOP'), COIL('RUN')),
          R('运行指示灯', NO('RUN'), COIL('LAMP_RUN'))]


def estop_steps(t, motion, main):
    """急停测试：按急停 → 运动输出 0.2 s 内全部断开；复位后不能自己启动；再按启动恢复。"""
    return [{'t': t, 'press': 'ESTOP'},
            {'t': t + 0.2, 'key': 'estop_ok', 'check': {'all_off': motion}, 'desc': '按下急停后运动输出没有立即断开'},
            {'t': t + 1.0, 'release': 'ESTOP'},
            {'t': t + 3.0, 'key': 'estop_ok', 'check': {'all_off': motion}, 'desc': '急停复位后设备自己重新启动了（必须再按启动）'},
            {'t': t + 4.0, 'press': 'START'},
            {'t': t + 5.0, 'key': 'restart_ok', 'check': {'out': main, 'eq': True}, 'desc': '急停复位后按启动不能恢复运行'}]


def start_steps(main):
    return [{'t': 1.0, 'press': 'START'}, {'t': 2.0, 'key': 'start_ok', 'check': {'out': main, 'eq': True}, 'desc': '按启动后没有运行'}]


STD_RULES = [{'key': 'start_ok', 'label': '启动正常', 'op': '==', 'value': 1, 'weight': 5},
             {'key': 'estop_ok', 'label': '急停：立即停止且复位后不自启', 'op': '==', 'value': 1, 'weight': 15},
             {'key': 'restart_ok', 'label': '急停复位后可以重新启动', 'op': '==', 'value': 1, 'weight': 5}]


def F(comp, kind, symptom):
    return {'comp': comp, 'kind': kind, 'label': f'{comp} {FAULTS[kind]}', 'symptom': symptom}


# ================================================================ 场景
SCENES = []


def scene(**kw):
    SCENES.append(kw)


# ---------------------------------------------------------------- 1 电机启停自锁
scene(id='s01_motor_latch', level=1, name='电机启停自锁',
      desc='按钮控制一台三相电机：启动、自锁、停止、热过载保护。PLC 入门第一课。',
      cell={'size': [8, 4], 'components': [
          C('M1', 'motor', (-2.6, -1.0, 0), 0, label='输送电机', ramp=0.6, kw=1.5),
          belt('C1', 0.2, 0, 6.6, speed=0.3, label='输送带（由 M1 拖动）', motor='M1'),
          C('E1', 'emitter', (-3.0, 0, EMIT), interval='6', parts=[{'kind': 'box', 'color': 'blue', 'h': 0.2, 'w': 0.25}]),
          C('R1', 'remover', (3.7, 0, 0), size=(0.5, 0.9)),
          C('START', 'button', (-3.6, 1.6, 0.95), label='启动', color='green'),
          C('STOP', 'button', (-3.4, 1.6, 0.95), label='停止', color='red', nc=True),
          C('LAMP_RUN', 'lamp', (-3.15, 1.6, 0.95), label='运行', color='green')]},
      task="""## 任务：电机启停自锁控制

输送带由电机 **M1** 拖动。用操作台上的两个按钮控制电机：

1. 按一下 **启动**（绿色，常开触点）电机启动，松开按钮后电机**保持运行**（自锁）；
2. 按一下 **停止**（红色，**常闭触点**：没按时输入为 1，按下为 0）电机停止；
3. 启动和停止同时按下时，**停止优先**；
4. 电机过载时热继电器动作（`M1_OL_OK` 变为 0），电机必须立即停止；热继电器复位后**不能自己重新启动**，要重新按启动；
5. 电机运行时 **运行指示灯** 亮。
""",
      hints=['自锁就是"启动按钮 OR 电机自己的输出"作为启动条件。', '停止按钮是常闭触点：没按时为 TRUE，所以要串在条件里（AND STOP），而不是 AND NOT STOP。',
             '热继电器的常闭触点 M1_OL_OK 和停止按钮一样串在条件里。'],
      ref_st="""PROGRAM MotorLatch
(* 启动按钮并联自锁触点，再串常闭的停止按钮和热继电器 *)
M1_RUN := (START OR M1_RUN) AND STOP AND M1_OL_OK;
LAMP_RUN := M1_RUN;
END_PROGRAM
""", ref_vars=[],
      ref_ld=[R('启保停：启动并联自锁，串常闭停止和热继电器', PAR(NO('START'), NO('M1_RUN')), NO('STOP'), NO('M1_OL_OK'), COIL('M1_RUN')),
              R('运行指示灯', NO('M1_RUN'), COIL('LAMP_RUN'))], ld_vars=[],
      test={'duration': 22, 'steps': [
          {'t': 1.0, 'press': 'START'}, {'t': 2.0, 'key': 'start_ok', 'check': {'out': 'M1_RUN', 'eq': True}, 'desc': '按启动后电机没有运行'},
          {'t': 2.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_RUN', 'eq': True}, 'desc': '运行时指示灯没亮'},
          {'t': 2.0, 'key': 'latch_ok', 'check': {'out': 'M1_RUN', 'eq': True}, 'hold': 3.0, 'desc': '松开启动按钮后电机停了（没有自锁）'},
          {'t': 6.0, 'press': 'STOP'}, {'t': 7.0, 'key': 'stop_ok', 'check': {'out': 'M1_RUN', 'eq': False}, 'desc': '按停止后电机没停'},
          {'t': 7.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_RUN', 'eq': False}, 'desc': '停止后指示灯没灭'},
          {'t': 7.0, 'key': 'stop_ok', 'check': {'out': 'M1_RUN', 'eq': False}, 'hold': 1.0, 'desc': '松开停止按钮后电机自己又启动了'},
          {'t': 9.0, 'press': 'START'}, {'t': 10.0, 'key': 'start_ok', 'check': {'out': 'M1_RUN', 'eq': True}},
          {'t': 11.0, 'press': 'START', 'hold': 0.5}, {'t': 11.0, 'press': 'STOP', 'hold': 0.5},
          {'t': 11.3, 'key': 'stop_priority', 'check': {'out': 'M1_RUN', 'eq': False}, 'desc': '启动和停止同时按下时电机还在运行（应停止优先）'},
          {'t': 13.0, 'press': 'START'}, {'t': 14.0, 'fault': {'comp': 'M1', 'kind': 'motor_overload'}},
          {'t': 14.3, 'key': 'overload_ok', 'check': {'out': 'M1_RUN', 'eq': False}, 'desc': '热继电器动作后输出没有断开'},
          {'t': 16.0, 'clear_faults': True},
          {'t': 17.5, 'key': 'overload_ok', 'check': {'out': 'M1_RUN', 'eq': False}, 'desc': '热继电器复位后电机自己重新启动了'},
          {'t': 18.0, 'press': 'START'}, {'t': 19.0, 'key': 'start_ok', 'check': {'out': 'M1_RUN', 'eq': True}}]},
      rules=[{'key': 'start_ok', 'label': '按启动电机运行', 'op': '==', 'value': 1, 'weight': 20},
             {'key': 'latch_ok', 'label': '松开按钮后保持运行（自锁）', 'op': '==', 'value': 1, 'weight': 25},
             {'key': 'stop_ok', 'label': '按停止电机停止', 'op': '==', 'value': 1, 'weight': 20},
             {'key': 'stop_priority', 'label': '停止优先', 'op': '==', 'value': 1, 'weight': 10},
             {'key': 'overload_ok', 'label': '过载保护且不自启', 'op': '==', 'value': 1, 'weight': 15},
             {'key': 'lamp_ok', 'label': '运行指示灯', 'op': '==', 'value': 1, 'weight': 10}],
      faults=[F('M1', 'motor_overload', '电机运行中突然停止，M1_OL_OK 变为 0，复位前按启动无效'),
              F('START', 'wire_break', '按启动没有任何反应，输入 START 一直为 0'),
              F('STOP', 'wire_break', '停止按钮断线：STOP 一直为 0，电机无法启动（常闭接法断线时停机，是安全的）'),
              F('STOP', 'sensor_stuck_on', '停止按钮触点粘连：按停止没反应（危险！）'),
              F('LAMP_RUN', 'wire_break', '电机在转但运行灯不亮')])

# ---------------------------------------------------------------- 2 正反转互锁
scene(id='s02_fwd_rev', level=2, name='电机正反转互锁',
      desc='正转、反转两个接触器绝不能同时吸合（会相间短路）：用 PLC 实现接触器互锁。',
      cell={'size': [8, 4], 'components': [
          C('M1', 'motor', (-2.6, -1.0, 0), 0, label='输送电机', reversible=True, ramp=0.8, kw=1.5),
          belt('C1', 0.2, 0, 6.6, speed=0.3, label='输送带（由 M1 拖动）', motor='M1'),
          C('FWD', 'button', (-3.6, 1.6, 0.95), label='正转', color='green'),
          C('REV', 'button', (-3.4, 1.6, 0.95), label='反转', color='blue'),
          C('STOP', 'button', (-3.2, 1.6, 0.95), label='停止', color='red', nc=True),
          C('LAMP_FWD', 'lamp', (-2.95, 1.6, 0.95), label='正转', color='green'),
          C('LAMP_REV', 'lamp', (-2.75, 1.6, 0.95), label='反转', color='yellow')]},
      task="""## 任务：电机正反转控制（接触器互锁）

电机 **M1** 有正转接触器 `M1_FWD` 和反转接触器 `M1_REV`。两个接触器**同时吸合会造成相间短路**，必须互锁。

1. 按 **正转** 电机正转并自锁，正转灯亮；按 **反转** 电机反转并自锁，反转灯亮；
2. 按 **停止**（常闭）电机停止；
3. **互锁**：正转运行时按反转按钮无效（反之亦然），必须先按停止再换向；任何时刻两个输出不能同时为 1，包括两个按钮同时按下；
4. 热继电器动作（`M1_OL_OK` = 0）时立即停止。
""",
      hints=['正转的条件里串上 NOT M1_REV，反转的条件里串上 NOT M1_FWD，这就是"接触器互锁"。',
             '两个按钮同时按下时，ST 里先执行的那一行会先得电，后一行因为互锁不会再得电。'],
      ref_st="""PROGRAM FwdRev
(* 正转：启动并联自锁，串停止、热继电器和反转互锁 *)
M1_FWD := (FWD OR M1_FWD) AND STOP AND M1_OL_OK AND NOT M1_REV;
(* 反转：同样，串正转互锁 *)
M1_REV := (REV OR M1_REV) AND STOP AND M1_OL_OK AND NOT M1_FWD;
LAMP_FWD := M1_FWD;
LAMP_REV := M1_REV;
END_PROGRAM
""", ref_vars=[],
      ref_ld=[R('正转：自锁 + 停止 + 热继电器 + 反转互锁', PAR(NO('FWD'), NO('M1_FWD')), NO('STOP'), NO('M1_OL_OK'), NC('M1_REV'), COIL('M1_FWD')),
              R('反转：自锁 + 停止 + 热继电器 + 正转互锁', PAR(NO('REV'), NO('M1_REV')), NO('STOP'), NO('M1_OL_OK'), NC('M1_FWD'), COIL('M1_REV')),
              R('正转指示', NO('M1_FWD'), COIL('LAMP_FWD')), R('反转指示', NO('M1_REV'), COIL('LAMP_REV'))], ld_vars=[],
      test={'duration': 24, 'steps': [
          {'t': 0.0, 'until': 24, 'key': 'interlock_ok', 'watch': {'never_both': ['M1_FWD', 'M1_REV']}, 'desc': '正反转接触器同时得电（短路！）'},
          {'t': 1.0, 'press': 'FWD'}, {'t': 2.0, 'key': 'fwd_ok', 'check': {'out': 'M1_FWD', 'eq': True}, 'desc': '按正转后没有正转'},
          {'t': 2.0, 'key': 'fwd_ok', 'check': {'out': 'M1_FWD', 'eq': True}, 'hold': 1.5, 'desc': '正转没有自锁'},
          {'t': 2.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_FWD', 'eq': True}},
          {'t': 4.0, 'press': 'REV'}, {'t': 4.2, 'key': 'interlock_ok', 'check': {'out': 'M1_REV', 'eq': False}, 'desc': '正转运行中按反转，反转接触器得电了'},
          {'t': 5.0, 'key': 'interlock_ok', 'check': {'out': 'M1_FWD', 'eq': True}, 'desc': '正转运行中按反转，正转被打断了（要求先停止再换向）'},
          {'t': 6.0, 'press': 'STOP'}, {'t': 7.0, 'key': 'stop_ok', 'check': {'all_off': ['M1_FWD', 'M1_REV']}, 'desc': '按停止没有停'},
          {'t': 8.0, 'press': 'REV'}, {'t': 9.0, 'key': 'rev_ok', 'check': {'out': 'M1_REV', 'eq': True}, 'desc': '按反转后没有反转'},
          {'t': 9.0, 'key': 'rev_ok', 'check': {'out': 'M1_REV', 'eq': True}, 'hold': 1.5, 'desc': '反转没有自锁'},
          {'t': 9.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_REV', 'eq': True}},
          {'t': 11.0, 'press': 'FWD'}, {'t': 11.5, 'key': 'interlock_ok', 'check': {'out': 'M1_FWD', 'eq': False}},
          {'t': 12.0, 'press': 'STOP'}, {'t': 13.0, 'key': 'stop_ok', 'check': {'all_off': ['M1_FWD', 'M1_REV']}},
          {'t': 14.0, 'press': 'FWD', 'hold': 0.5}, {'t': 14.0, 'press': 'REV', 'hold': 0.5},
          {'t': 15.0, 'press': 'STOP'}, {'t': 16.5, 'press': 'FWD'}, {'t': 17.5, 'fault': {'comp': 'M1', 'kind': 'motor_overload'}},
          {'t': 17.8, 'key': 'overload_ok', 'check': {'all_off': ['M1_FWD', 'M1_REV']}, 'desc': '过载后没有停止'},
          {'t': 19.0, 'clear_faults': True}, {'t': 20.5, 'key': 'overload_ok', 'check': {'all_off': ['M1_FWD', 'M1_REV']}, 'desc': '热继电器复位后自己启动了'}]},
      rules=[{'key': 'fwd_ok', 'label': '正转启动并自锁', 'op': '==', 'value': 1, 'weight': 15},
             {'key': 'rev_ok', 'label': '反转启动并自锁', 'op': '==', 'value': 1, 'weight': 15},
             {'key': 'stop_ok', 'label': '停止', 'op': '==', 'value': 1, 'weight': 15},
             {'key': 'interlock_ok', 'label': '正反转互锁', 'op': '==', 'value': 1, 'weight': 30},
             {'key': 'hard_reversals', 'label': '没有高速直接反转', 'op': '==', 'value': 0, 'weight': 5},
             {'key': 'overload_ok', 'label': '过载保护且不自启', 'op': '==', 'value': 1, 'weight': 10},
             {'key': 'lamp_ok', 'label': '方向指示灯', 'op': '==', 'value': 1, 'weight': 10}],
      faults=[F('M1', 'motor_overload', '电机运行中停止，M1_OL_OK = 0'), F('REV', 'wire_break', '按反转没有反应'),
              F('FWD', 'sensor_stuck_on', '正转按钮卡住：一按停止就又正转'), F('LAMP_REV', 'wire_break', '反转时指示灯不亮')])

# ---------------------------------------------------------------- 3 传送带启停
scene(id='s03_conveyor', level=3, name='传送带启停与急停',
      desc='一条输送线：启动、停止、急停（急停复位后必须重新启动）、运行/停止指示灯。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.5, 0, EMIT), interval='uniform(4,6)', parts=[{'kind': 'box', 'color': 'blue', 'h': 0.2, 'w': 0.25, 'weight': 2},
                                                                              {'kind': 'box', 'color': 'green', 'h': 0.2, 'w': 0.25, 'weight': 1}]),
          belt('C1', 0.0, 0, 7.6, speed=0.3, label='输送带'),
          C('S_END', 'diffuse_sensor', (3.4, 0.35, BEAM), label='末端光电'),
          C('R1', 'remover', (3.85, 0, 0), size=(0.4, 0.9)),
          *panel(extra=[C('LAMP_STOP', 'lamp', (0, 0, 0), label='停止', color='red')])]},
      task="""## 任务：输送线启停与急停

1. 按 **启动**，输送带 C1 运行，运行灯（绿）亮；按 **停止**，输送带停止，停止灯（红）亮；
2. **急停**按钮是常闭触点（正常为 1，按下为 0），按下后自锁：按下急停，输送带**立即**停止；
3. 急停旋转复位后，输送带**不能自己重新运行**，必须重新按启动；
4. 末端光电 `S_END` 检测零件到达线尾：运行期间零件要连续送到线尾，评分测试时段内至少送达 6 件（中途按过停止也算在内）。
""",
      hints=['把急停和停止一样串在自锁回路里，急停一按自锁就断了，复位后自然不会自己启动。'],
      ref_st="""PROGRAM Conveyor
VAR
    RUN : BOOL;     (* 运行标志 *)
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    LAMP_STOP := NOT RUN;
END_PROGRAM
""", ref_vars=[],
      ref_ld=RUN_LD + [R('输送带', NO('RUN'), COIL('C1_FWD')), R('停止灯', NC('RUN'), COIL('LAMP_STOP'))], ld_vars=[V('RUN')],
      test={'duration': 75, 'steps': start_steps('C1_FWD') + [
          {'t': 2.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_RUN', 'eq': True}}, {'t': 2.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_STOP', 'eq': False}},
          {'t': 30.0, 'press': 'STOP'}, {'t': 31.0, 'key': 'stop_ok', 'check': {'out': 'C1_FWD', 'eq': False}, 'desc': '按停止后输送带没停'},
          {'t': 31.0, 'key': 'lamp_ok', 'check': {'out': 'LAMP_STOP', 'eq': True}, 'desc': '停止后停止灯没亮'},
          {'t': 31.0, 'key': 'stop_ok', 'check': {'out': 'C1_FWD', 'eq': False}, 'hold': 2.0},
          {'t': 34.0, 'press': 'START'}, {'t': 35.0, 'key': 'start_ok', 'check': {'out': 'C1_FWD', 'eq': True}},
          {'t': 64.0, 'snapshot': True}] + estop_steps(65.0, ['C1_FWD'], 'C1_FWD')},
      rules=[{'key': 'start_ok', 'label': '按启动输送带运行', 'op': '==', 'value': 1, 'weight': 20},
             {'key': 'stop_ok', 'label': '按停止输送带停止', 'op': '==', 'value': 1, 'weight': 20},
             {'key': 'estop_ok', 'label': '急停：立即停止且复位后不自启', 'op': '==', 'value': 1, 'weight': 25},
             {'key': 'restart_ok', 'label': '急停复位后可以重新启动', 'op': '==', 'value': 1, 'weight': 10},
             {'key': 'lamp_ok', 'label': '运行/停止指示灯', 'op': '==', 'value': 1, 'weight': 10},
             {'key': 'removed', 'label': '输送到末端的零件', 'op': '>=', 'value': 6, 'weight': 15}],
      faults=[F('C1', 'motor_overload', '输送带不动，但输出 C1_FWD 为 1'), F('C1', 'actuator_slow', '输送带明显变慢'),
              F('ESTOP', 'wire_break', '急停回路断线：设备无法启动（常闭接法的好处）'), F('START', 'sensor_flicker', '启动按钮接触不良')])

# ---------------------------------------------------------------- 4 按颜色分拣
SORT_RULES = [{'key': 'sort_accuracy', 'label': '分拣正确率', 'op': '>=', 'value': 0.98, 'weight': 35},
              {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 15},
              {'key': 'jams', 'label': '卡件次数', 'op': '==', 'value': 0, 'weight': 10},
              {'key': 'throughput_per_min', 'label': '每分钟产出', 'op': '>=', 'value': 8, 'weight': 15}] + STD_RULES

scene(id='s04_sort_color', level=4, name='按颜色分拣',
      desc='视觉传感器识别颜色，推杆把绿色零件推进旁边的料箱，蓝色零件走到线尾。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='uniform(5,7)', parts=[{'kind': 'box', 'color': 'blue', 'h': 0.2, 'w': 0.25, 'weight': 1},
                                                                              {'kind': 'box', 'color': 'green', 'h': 0.2, 'w': 0.25, 'weight': 1}]),
          belt('C1', 0.0, 0, 7.6, speed=0.3, label='输送带'),
          C('V1', 'vision_sensor', (0.3, 0, 0.9), label='颜色识别', mode='color'),
          C('S1', 'diffuse_sensor', (1.5, 0.35, BEAM), label='推杆前光电'),
          C('P1', 'pusher', (1.5, 0.42, BEAM), label='推杆', stroke=0.8, speed=1.0),
          C('R_GREEN', 'remover', (1.5, -0.76, 0), size=(0.9, 0.9), label='绿色料箱', accept={'color': 'green'}),
          C('R_BLUE', 'remover', (3.85, 0, 0), size=(0.4, 0.9), label='蓝色出口', accept={'color': 'blue'}),
          *panel()]},
      task="""## 任务：按颜色分拣

蓝色、绿色两种零件随机来料。视觉传感器 `V1` 在零件经过时输出颜色码 `V1_CODE`（1 = 蓝，2 = 绿，没有零件时 0）。

1. 按启动输送带运行；按停止或急停时停止（急停复位后要重新按启动）；
2. **绿色**零件到达推杆前（光电 `S1` 检测到）时，推杆 `P1` 伸出把它推进绿色料箱，伸出到位（`P1_FRONT`）后立即缩回；
3. **蓝色**零件不推，随输送带走到线尾；
4. 分拣正确率 ≥ 98%，不能卡件、不能碰撞；每分钟至少分拣 8 件。
""",
      hints=['视觉传感器在推杆上游 1.2 m：零件经过视觉时先把颜色记下来（锁存），到推杆前再用。', '用 S1 的上升沿（R_TRIG）触发推杆，避免一个零件推两次。',
             '推杆是单电控气缸：P1_EXTEND 保持为 1 才伸出，到位后断开就缩回。'],
      ref_st="""PROGRAM SortColor
VAR
    RUN : BOOL;
    IS_GREEN : BOOL;      (* 最近一次视觉识别是绿色 *)
    PUSH : BOOL;          (* 推杆动作中 *)
    TRIG : R_TRIG;        (* S1 上升沿 *)
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    (* 零件经过视觉时锁存颜色 *)
    IF V1_DETECT THEN
        IS_GREEN := (V1_CODE = 2);
    END_IF;
    (* 零件到推杆前：绿色就推 *)
    TRIG(CLK := S1);
    IF TRIG.Q AND IS_GREEN AND RUN THEN
        PUSH := TRUE;
        IS_GREEN := FALSE;
    END_IF;
    IF P1_FRONT OR NOT RUN THEN
        PUSH := FALSE;
    END_IF;
    P1_EXTEND := PUSH;
END_PROGRAM
""", ref_vars=[],
      ref_ld=RUN_LD + [R('输送带', NO('RUN'), COIL('C1_FWD')),
                       R('视觉识别到绿色：置位"绿色"标志', NO('V1_DETECT'), {'t': 'CMP', 'op': '=', 'a': 'V1_CODE', 'b': '2'}, SET('IS_GREEN')),
                       R('视觉识别到其他颜色：复位标志', NO('V1_DETECT'), {'t': 'CMP', 'op': '<>', 'a': 'V1_CODE', 'b': '2'}, RST('IS_GREEN')),
                       R('S1 上升沿 + 绿色：推杆动作', PE('S1'), NO('IS_GREEN'), NO('RUN'), SET('PUSH')),
                       R('推杆动作后清掉颜色标志', NO('PUSH'), RST('IS_GREEN')),
                       R('伸出到位或停机：推杆缩回', PAR(NO('P1_FRONT'), NC('RUN')), RST('PUSH')),
                       R('推杆电磁阀', NO('PUSH'), COIL('P1_EXTEND'))],
      ld_vars=[V('RUN'), V('IS_GREEN'), V('PUSH')],
      test={'duration': 192, 'steps': start_steps('C1_FWD') + [{'t': 180.0, 'snapshot': True}] + estop_steps(181.0, ['C1_FWD', 'P1_EXTEND'], 'C1_FWD')},
      rules=SORT_RULES,
      faults=[F('S1', 'sensor_stuck_off', '绿色零件不被推出，直接走到线尾'), F('S1', 'sensor_stuck_on', '推杆不再动作（没有上升沿）'),
              F('V1', 'wire_break', '所有零件都不推（颜色码一直为 0）'), F('P1', 'actuator_jam', '推杆不动，P1_FRONT 一直不到位'),
              F('P1', 'actuator_slow', '推杆变慢，零件被推歪或没推进料箱'), F('S1', 'sensor_flicker', '偶尔多推/漏推'),
              F('C1', 'motor_overload', '输送带停转')])

# ---------------------------------------------------------------- 5 按材质分拣
scene(id='s05_sort_material', level=5, name='按材质分拣（电感/电容）',
      desc='电感接近开关只认金属，电容接近开关什么都认：把金属件推出，塑料件放行。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='uniform(5,7)', parts=[
              {'kind': 'part', 'color': 'grey', 'material': 'metal', 'h': 0.15, 'w': 0.25, 'weight': 1},
              {'kind': 'part', 'color': 'blue', 'material': 'plastic', 'h': 0.15, 'w': 0.25, 'weight': 1},
              {'kind': 'part', 'color': 'white', 'material': 'plastic', 'h': 0.15, 'w': 0.25, 'weight': 1}]),
          belt('C1', 0.0, 0, 7.6, speed=0.3, label='输送带'),
          C('IND1', 'inductive', (0.6, 0.3, 0.32), label='电感接近开关', range=0.2),
          C('CAP1', 'capacitive', (0.6, -0.3, 0.32), 180, label='电容接近开关', range=0.2),
          C('S1', 'diffuse_sensor', (1.5, 0.35, 0.32), label='推杆前光电'),
          C('P1', 'pusher', (1.5, 0.42, 0.32), label='推杆', stroke=0.8, speed=1.0),
          C('R_METAL', 'remover', (1.5, -0.76, 0), size=(0.9, 0.9), label='金属料箱', accept={'material': 'metal'}),
          C('R_PLASTIC', 'remover', (3.85, 0, 0), size=(0.4, 0.9), label='塑料出口', accept={'material': 'plastic'}),
          *panel()]},
      task="""## 任务：按材质分拣

来料有金属件（灰）和塑料件（蓝、白）。电感接近开关 `IND1` 只在**金属件**经过时为 1；电容接近开关 `CAP1` 任何零件经过都为 1。

1. 启停、急停要求同前（急停复位后要重新按启动）；
2. 金属件到达推杆前（`S1`）时，推杆 `P1` 把它推进金属料箱；塑料件放行到线尾；
3. 正确率 ≥ 98%，不碰撞、不卡件，每分钟至少 8 件。
""",
      hints=['电感开关在推杆上游约 0.9 m，零件间距大于 1.5 m：经过电感时记下"是金属"，推完后清掉。',
             '也可以用电容开关的上升沿作为"一个零件经过"的时刻，在这一刻读电感开关的值。'],
      ref_st="""PROGRAM SortMaterial
VAR
    RUN : BOOL;
    IS_METAL : BOOL;
    PUSH : BOOL;
    TRIG : R_TRIG;
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    IF IND1 THEN
        IS_METAL := TRUE;          (* 金属件经过电感开关 *)
    END_IF;
    TRIG(CLK := S1);
    IF TRIG.Q THEN
        IF IS_METAL AND RUN THEN
            PUSH := TRUE;
        END_IF;
        IS_METAL := FALSE;          (* 每个零件到推杆前都清一次 *)
    END_IF;
    IF P1_FRONT OR NOT RUN THEN
        PUSH := FALSE;
    END_IF;
    P1_EXTEND := PUSH;
END_PROGRAM
""", ref_vars=[],
      ref_ld=RUN_LD + [R('输送带', NO('RUN'), COIL('C1_FWD')),
                       R('S1 上升沿 + 金属标志：推杆动作', PE('S1'), NO('IS_METAL'), NO('RUN'), SET('PUSH')),
                       R('推杆动作后清掉金属标志', NO('PUSH'), RST('IS_METAL')),
                       R('零件经过电感开关：置位金属标志', NO('IND1'), SET('IS_METAL')),
                       R('伸出到位或停机：缩回', PAR(NO('P1_FRONT'), NC('RUN')), RST('PUSH')),
                       R('推杆电磁阀', NO('PUSH'), COIL('P1_EXTEND'))],
      ld_vars=[V('RUN'), V('IS_METAL'), V('PUSH')],
      test={'duration': 192, 'steps': start_steps('C1_FWD') + [{'t': 180.0, 'snapshot': True}] + estop_steps(181.0, ['C1_FWD', 'P1_EXTEND'], 'C1_FWD')},
      rules=SORT_RULES,
      faults=[F('IND1', 'sensor_stuck_off', '金属件不被推出'), F('IND1', 'sensor_stuck_on', '所有零件都被推出'),
              F('CAP1', 'wire_break', '电容开关没有信号（如果程序用了它）'), F('P1', 'actuator_jam', '推杆不动'), F('S1', 'sensor_flicker', '偶尔多推')])

# ---------------------------------------------------------------- 6 按高度分拣
scene(id='s06_sort_height', level=6, name='按高度分拣（摆臂）',
      desc='测高传感器输出零件高度（mm），摆臂把高件导到旁边的输送线。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='uniform(7,9)', parts=[
              {'kind': 'box', 'color': 'orange', 'h': 0.3, 'w': 0.25, 'weight': 1},
              {'kind': 'box', 'color': 'blue', 'h': 0.15, 'w': 0.25, 'weight': 1}]),
          belt('C1', 0.0, 0, 7.6, speed=0.3, label='主输送带'),
          C('H1', 'height_sensor', (0.3, 0, 0.9), label='测高'),
          C('PA1', 'pivot_arm', (1.0, 0.33, 0.33), label='摆臂', length=1.1, angle=45, speed=180),
          belt('C2', 2.45, -0.65, 2.7, speed=0.3, label='高件输送带', height=0.2, W=0.7),
          C('S2', 'diffuse_sensor', (1.65, -0.28, 0.28), label='高件线光电', range=0.75),
          C('R_TALL', 'remover', (3.85, -0.65, 0), size=(0.4, 0.7), label='高件出口', accept={'min_h': 0.25}),
          C('R_LOW', 'remover', (3.85, 0, 0), size=(0.4, 0.6), label='矮件出口', accept={'max_h': 0.2}),
          *panel()]},
      task="""## 任务：按高度分拣

来料有高件（300 mm）和矮件（150 mm）。测高传感器 `H1` 输出零件高度（mm），没有零件时为 0。

1. 启停、急停同前；主输送带 C1 和高件输送带 C2 一起运行；
2. 高件到达前摆臂 `PA1` 摆出（`PA1_TURN` = 1），把高件导到 C2；高件到了 C2（光电 `S2` 检测到）后摆臂收回（如果后面还有高件在途就继续保持）；
3. 矮件经过时摆臂必须是收回状态；
4. 正确率 ≥ 98%，不碰撞、不卡件，每分钟至少 6 件。
""",
      hints=['用比较指令：H1 > 220 就是高件。', '高件在摆臂上要滑 2 s 左右，下一个零件可能已经到了测高点：用计数（在途高件数）比用一个标志可靠。'],
      ref_st="""PROGRAM SortHeight
VAR
    RUN : BOOL;
    N : INT := 0;           (* 已测到、还没到旁边输送线的高件数 *)
    TALL : R_TRIG;
    ARRIVE : R_TRIG;
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    C2_FWD := RUN;
    TALL(CLK := H1 > 220);          (* 测到一个高件 *)
    ARRIVE(CLK := S2);              (* 一个高件到了旁边的线 *)
    IF TALL.Q THEN N := N + 1; END_IF;
    IF ARRIVE.Q AND N > 0 THEN N := N - 1; END_IF;
    IF NOT RUN THEN N := 0; END_IF;
    PA1_TURN := RUN AND N > 0;      (* 有高件在途就摆出 *)
END_PROGRAM
""", ref_vars=[],
      test={'duration': 222, 'steps': start_steps('C1_FWD') + [{'t': 210.0, 'snapshot': True}] + estop_steps(211.0, ['C1_FWD', 'C2_FWD', 'PA1_TURN'], 'C1_FWD')},
      rules=[{**r, 'value': 6} if r['key'] == 'throughput_per_min' else r for r in SORT_RULES],
      faults=[F('H1', 'wire_break', '测高值一直为 0，所有零件走主线'), F('S2', 'sensor_stuck_off', '摆臂摆出后不收回，矮件也被导走'),
              F('PA1', 'actuator_slow', '摆臂动作慢，高件来不及导走'), F('PA1', 'actuator_jam', '摆臂不动')])

# ---------------------------------------------------------------- 7 计数装箱
scene(id='s07_count_box', level=7, name='计数装箱',
      desc='每 5 个零件装一箱：计数器计数，装满后换箱。',
      cell={'size': [8, 4.4], 'components': [
          C('E1', 'emitter', (-3.6, 0, 0.72), interval='uniform(3,4)', parts=[{'kind': 'box', 'color': 'yellow', 'h': 0.12, 'w': 0.15}]),
          belt('C1', -1.0, 0, 5.6, speed=0.3, label='零件输送带', height=0.7),
          C('S1', 'diffuse_sensor', (1.75, 0.35, 0.78), label='落料计数光电'),
          C('E_BOX', 'emitter', (1.95, -1.65, EMIT), trigger='signal', parts=[{'kind': 'tote', 'color': 'blue', 'h': 0.3, 'w': 0.5}], label='空箱料仓'),
          belt('C2', 1.95, 0, 4.0, rot=90, speed=0.3, label='装箱输送带', W=0.7),
          C('S_BOX', 'diffuse_sensor', (2.45, 0.25, 0.4), -90, label='箱子到位光电', range=0.9),
          C('R_BOX', 'remover', (1.95, 2.0, 0), size=(0.8, 0.4), label='满箱出口', accept={'count': 5}),
          *panel(x0=-3.6, y=1.8, extra=[C('LAMP_FULL', 'lamp', (0, 0, 0), label='满箱', color='yellow')])]},
      task="""## 任务：计数装箱

零件从高处的输送带 C1 落进下面输送带 C2 上的周转箱。每箱装 **5 个**。

1. 启停、急停同前；
2. 开始时用 `E_BOX_RELEASE`（上升沿放一个空箱）放出空箱，C2 把箱子送到装箱位（光电 `S_BOX` 检测到）后停下；
3. C1 运行，光电 `S1` 每检测到一个零件掉落计数一次；第 5 个零件**完全掉进箱子**（S1 信号消失）后 C1 立即停止，满箱灯亮；
4. 然后放出下一个空箱、C2 运行：满箱被送走（`S_BOX` 先变 0），新空箱到位（`S_BOX` 再变 1）后 C2 停止，计数清零，C1 继续；
5. 每箱正好 5 个，不掉件、不碰撞。
""",
      hints=['用 CTU 计数器：CU 接 S1，PV = 5；用状态机（CASE）分"等箱子 / 装箱 / 换箱"几个步骤。',
             '第 5 个零件挡住 S1 的那一刻它还在 C1 上，等 S1 的下降沿再停 C1。'],
      ref_st="""PROGRAM CountBox
VAR
    RUN : BOOL;
    STEP : INT := 0;        (* 0 放空箱  1 空箱到位中  2 装箱  3 等满箱离开  4 等新箱到位 *)
    CNT : CTU;
    S1_FALL : F_TRIG;
    BOX_RISE : R_TRIG;
    BOX_FALL : F_TRIG;
    REL : BOOL;
END_VAR
""" + RUN_ST + """    S1_FALL(CLK := S1);
    BOX_RISE(CLK := S_BOX);
    BOX_FALL(CLK := S_BOX);
    CNT(CU := S1 AND STEP = 2, R := STEP <> 2, PV := 5);
    REL := FALSE;
    CASE STEP OF
        0:  IF RUN THEN REL := TRUE; STEP := 1; END_IF;          (* 放第一个空箱 *)
        1:  IF S_BOX THEN STEP := 2; END_IF;                       (* 空箱到装箱位 *)
        2:  IF CNT.Q AND S1_FALL.Q THEN STEP := 3; REL := TRUE; END_IF;   (* 第 5 个零件落下：放下一个空箱 *)
        3:  IF BOX_FALL.Q THEN STEP := 4; END_IF;                  (* 满箱离开光电 *)
        4:  IF BOX_RISE.Q THEN STEP := 2; END_IF;                  (* 新空箱到位 *)
    END_CASE;
    E_BOX_RELEASE := REL;
    C1_FWD := RUN AND STEP = 2 AND NOT (CNT.Q AND NOT S1);
    C2_FWD := RUN AND (STEP = 1 OR STEP = 3 OR STEP = 4);
    LAMP_FULL := STEP = 3 OR STEP = 4;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 186, 'steps': start_steps('LAMP_RUN') + [{'t': 175.0, 'snapshot': True}] + estop_steps(176.0, ['C1_FWD', 'C2_FWD'], 'LAMP_RUN')},
      rules=[{'key': 'bins.R_BOX.ok', 'label': '装满 5 个的箱数', 'op': '>=', 'value': 5, 'weight': 35},
             {'key': 'sorted_wrong', 'label': '数量不对的箱子', 'op': '==', 'value': 0, 'weight': 20},
             {'key': 'dropped', 'label': '掉件数', 'op': '==', 'value': 0, 'weight': 10},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 10}] + STD_RULES,
      faults=[F('S1', 'sensor_flicker', '计数偏多，箱子没满就换箱'), F('S1', 'sensor_stuck_off', '一直不换箱，零件越堆越高'),
              F('S_BOX', 'sensor_stuck_on', 'C2 不动或箱子不停'), F('C2', 'motor_overload', '满箱送不走')])

# ---------------------------------------------------------------- 8 定时放料
scene(id='s08_timed_feed', level=8, name='定时放料与工位停留',
      desc='料仓每 6 s 放一件；零件在加工工位被挡停挡住加工 3 s 后放行。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), trigger='signal', label='料仓', parts=[{'kind': 'part', 'color': 'grey', 'material': 'metal', 'h': 0.15, 'w': 0.25}]),
          belt('C1', 0.0, 0, 7.6, speed=0.3, label='输送带'),
          C('ST1', 'stopper', (0.5, 0, 0), label='工位挡停', width=0.6),
          C('S1', 'diffuse_sensor', (0.46, 0.35, 0.32), label='工位到位光电'),
          C('R1', 'remover', (3.85, 0, 0), size=(0.4, 0.9), label='出口'),
          *panel(extra=[C('LAMP_WORK', 'lamp', (0, 0, 0), label='加工中', color='yellow')])]},
      task="""## 任务：定时放料与工位停留

1. 启停、急停同前；运行时每 **6 s** 让料仓放一件（`E1_RELEASE` 的上升沿放一件）；
2. 挡停 `ST1` 平时升起（`ST1_RAISE` = 1），零件到工位（`S1` = 1）后**停留至少 3 s**（模拟加工），加工中灯亮；
3. 加工完挡停落下放行，零件离开后再升起，等下一件；挡停升起时上面不能有零件（否则顶到零件记碰撞）；
4. 每分钟至少 8 件，放料间隔不小于 5.5 s；零件之间不能追尾、不能碰撞。
""",
      hints=['用一个 TON 自己复位做 6 s 脉冲：T1(IN := RUN AND NOT T1.Q, PT := T#6S)，T1.Q 就是每 6 s 一个扫描周期的脉冲。',
             '挡停落下 1 s 后再升起，零件已经走过挡板。'],
      ref_st="""PROGRAM TimedFeed
VAR
    RUN : BOOL;
    FEED : TON;                 (* 6 s 放料脉冲 *)
    WORK : TON;                 (* 加工计时 *)
    PASS : TON;                 (* 放行计时 *)
    HOLD : BOOL := TRUE;        (* 挡停升起 *)
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    FEED(IN := RUN AND NOT FEED.Q, PT := T#6S);
    E1_RELEASE := FEED.Q;
    (* 零件到工位：加工 3.2 s *)
    WORK(IN := S1 AND HOLD, PT := T#3200MS);
    LAMP_WORK := S1 AND HOLD;
    IF WORK.Q THEN
        HOLD := FALSE;          (* 加工完：落下放行 *)
    END_IF;
    PASS(IN := NOT HOLD, PT := T#1S);
    IF PASS.Q THEN
        HOLD := TRUE;           (* 1 s 后零件已经走过挡板，重新升起 *)
    END_IF;
    ST1_RAISE := HOLD;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 192, 'steps': start_steps('C1_FWD') + [{'t': 180.0, 'snapshot': True}] + estop_steps(181.0, ['C1_FWD', 'E1_RELEASE'], 'C1_FWD')},
      rules=[{'key': 'emit_min_gap.E1', 'label': '最小放料间隔 s', 'op': '>=', 'value': 5.5, 'weight': 15},
             {'key': 'dwell_min.ST1', 'label': '工位最短停留 s', 'op': '>=', 'value': 3.0, 'weight': 25},
             {'key': 'throughput_per_min', 'label': '每分钟产出', 'op': '>=', 'value': 8, 'weight': 15},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 10},
             {'key': 'part_contacts', 'label': '零件追尾次数', 'op': '==', 'value': 0, 'weight': 10}] + STD_RULES,
      faults=[F('S1', 'sensor_stuck_off', '零件一直被挡在工位不放行'), F('S1', 'sensor_flicker', '加工时间被打断，停留不足 3 s'),
              F('ST1', 'actuator_jam', '挡停不动作'), F('E1', 'wire_break', '料仓不放料')])

# ---------------------------------------------------------------- 9 码垛
scene(id='s09_palletize', level=9, name='码垛（伺服取放）',
      desc='两轴伺服取放机械手把箱子码到托盘上：一层 3 个，码 2 层。',
      cell={'size': [8, 4.4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='8', max=6, parts=[{'kind': 'box', 'color': 'orange', 'h': 0.2, 'w': 0.25}]),
          belt('C1', -1.3, 0, 5.0, speed=0.3, label='来料输送带'),
          C('ST1', 'stopper', (1.13, 0, 0), label='端头挡块', normally_up=True),
          C('S1', 'diffuse_sensor', (1.0, 0.35, BEAM), label='取料位光电'),
          C('PP1', 'pick_place', (1.0, 0, 0), -90, label='取放机械手', mode='servo', x_stroke=1.6, z_stroke=0.9, z_top=1.1, x_speed=0.8, z_speed=0.5),
          C('PL1', 'pallet', (1.0, -1.15, 0), size=(0.5, 1.0), label='托盘', height=0.3),
          *panel(x0=-3.6, y=1.8)]},
      task="""## 任务：码垛

机械手 `PP1` 有水平轴 X（朝托盘方向，0–1600 mm）和垂直轴 Z（向下，0–900 mm），吸盘 `PP1_GRIP`。
输出 `PP1_X_SET` / `PP1_Z_SET` 是目标位置（mm），到位后 `PP1_X_AT` / `PP1_Z_AT` 为 1（Z 向下碰到东西时也会停下并给出到位）。

1. 启停、急停同前；来料一共 6 箱；
2. 箱子到取料位（`S1`）后：Z 下降吸住箱子 → 升到顶 → X 移到放料位 → Z 下降放到托盘上 → 松开 → 升到顶 → X 回取料位；
3. 托盘上一层放 3 个（X = 850、1150、1450 mm），放满一层后放第二层，共 2 层 6 个；
4. **先升到顶再平移**（否则撞上别的箱子记碰撞）；不能在高处松开（摔箱）；6 个箱子都要放在托盘范围内，不能掉件。
""",
      hints=['用 CASE 状态机，每个动作一个步骤，等到位信号再进下一步。', 'Z 目标直接给 900，碰到箱子/托盘就会停下并给出到位，不用算每层的高度。',
             '第 N 个箱子的 X 位置：850 + (N MOD 3) * 300。'],
      ref_st="""PROGRAM Palletize
VAR
    RUN : BOOL;
    STEP : INT := 0;
    N : INT := 0;           (* 已码箱数 *)
    XP : INT := 0;          (* 本次放料 X *)
    TM : TON;
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    TM(IN := STEP = 3 OR STEP = 8, PT := T#300MS);
    CASE STEP OF
        0:  PP1_X_SET := 0; PP1_Z_SET := 0;
            IF RUN AND S1 AND PP1_X_AT AND PP1_Z_AT AND N < 6 THEN STEP := 1; END_IF;
        1:  PP1_Z_SET := 900; STEP := 2;                               (* 下降到箱顶 *)
        2:  IF PP1_Z_AT THEN PP1_GRIP := TRUE; STEP := 3; END_IF;
        3:  IF PP1_GRIPPED AND TM.Q THEN PP1_Z_SET := 0; STEP := 4; END_IF;
        4:  IF PP1_Z_AT AND PP1_Z_POS < 5 THEN
                XP := 850 + (N MOD 3) * 300;
                PP1_X_SET := XP; STEP := 5;
            END_IF;
        5:  IF PP1_X_AT AND PP1_X_POS = XP THEN PP1_Z_SET := 900; STEP := 6; END_IF;
        6:  STEP := 7;
        7:  IF PP1_Z_AT THEN PP1_GRIP := FALSE; STEP := 8; END_IF;    (* 放下 *)
        8:  IF TM.Q THEN PP1_Z_SET := 0; STEP := 9; END_IF;
        9:  IF PP1_Z_AT AND PP1_Z_POS < 5 THEN PP1_X_SET := 0; STEP := 10; END_IF;
        10: IF PP1_X_AT AND PP1_X_POS = 0 THEN N := N + 1; STEP := 0; END_IF;
    END_CASE;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 112, 'steps': start_steps('C1_FWD') + [{'t': 100.0, 'snapshot': True}] + estop_steps(101.0, ['C1_FWD'], 'C1_FWD')},
      rules=[{'key': 'pallets.PL1.count', 'label': '托盘上的箱数', 'op': '==', 'value': 6, 'weight': 30},
             {'key': 'pallets.PL1.layers', 'label': '码垛层数', 'op': '==', 'value': 2, 'weight': 10},
             {'key': 'pallets.PL1.inside', 'label': '都码在托盘范围内', 'op': '==', 'value': True, 'weight': 5},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 15},
             {'key': 'hard_drops', 'label': '高处摔落次数', 'op': '==', 'value': 0, 'weight': 10},
             {'key': 'dropped', 'label': '掉件数', 'op': '==', 'value': 0, 'weight': 5}] + STD_RULES,
      faults=[F('S1', 'sensor_stuck_off', '机械手一直不去取料'), F('PP1', 'actuator_slow', '机械手动作明显变慢'),
              F('PP1', 'actuator_jam', '机械手不动，到位信号不来'), F('C1', 'motor_overload', '来料停止')])

# ---------------------------------------------------------------- 10 转台分流
scene(id='s10_turntable', level=10, name='转台分流',
      desc='零件进转台后：蓝色直行，绿色转 90° 送到侧线。练习单件分离和顺序控制。',
      cell={'size': [8, 4.4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='uniform(7,9)', parts=[{'kind': 'box', 'color': 'blue', 'h': 0.2, 'w': 0.25, 'weight': 1},
                                                                              {'kind': 'box', 'color': 'green', 'h': 0.2, 'w': 0.25, 'weight': 1}]),
          belt('C1', -1.575, 0, 4.45, speed=0.3, label='进料输送带'),
          C('ST1', 'stopper', (0.3, 0, 0), label='分离挡停'),
          C('V1', 'vision_sensor', (0.5, 0, 0.9), label='颜色识别', radius=0.12),
          C('S_ST', 'diffuse_sensor', (0.6, 0.35, BEAM), label='过挡停光电'),
          C('T1', 'turntable', (1.1, 0, 0), size=(0.9, 0.9), label='转台', angle=-90, speed=90, roll_speed=0.3),
          belt('C2', 2.6, 0, 2.1, speed=0.3, label='直行输送带'),
          belt('C3', 1.1, -1.25, 1.6, rot=-90, speed=0.3, label='侧线输送带'),
          C('R_BLUE', 'remover', (3.85, 0, 0), size=(0.4, 0.9), label='蓝色出口', accept={'color': 'blue'}),
          C('R_GREEN', 'remover', (1.1, -2.1, 0), size=(0.9, 0.3), label='绿色出口', accept={'color': 'green'}),
          *panel(x0=-3.6, y=1.8)]},
      task="""## 任务：转台分流

1. 启停、急停同前；
2. 分离挡停 `ST1` 平时升起挡住来料；转台空闲（在 0° 位且台上没有零件）时落下放行**一个**零件，零件刚过挡板（`S_ST` = 1）就升起挡住后面的零件；视觉 `V1` 装在挡停和转台之间，只看得到刚放行的那个零件；
3. 零件进转台（台面滚筒 `T1_ROLL_FWD` 正转），到台面中央（`T1_PART`）后停滚筒：
   - 蓝色：滚筒正转，送到直行输送带 C2；
   - 绿色：转台转到 -90°（`T1_TURN`，到位 `T1_TURNED`），滚筒正转送到侧线 C3，然后转回 0°；
4. 转台转动时台面上的零件必须完全在台面上；正确率 ≥ 98%，不碰撞、不卡件，每分钟至少 6 件。
""",
      hints=['零件放行后经过 V1 时记下是不是绿色，回到等料步骤时清掉。', '零件到台面中央后滚筒再转 0.4 s 让它对中；离开台面（T1_PART 变 0）后再等 1.5 s 才转回。'],
      ref_st="""PROGRAM Turntable
VAR
    RUN : BOOL;
    STEP : INT := 0;    (* 0 等料  1 放行  2 进台  3 对中  4 转向  5 出料  6 回位 *)
    GREEN : BOOL;       (* 台上零件是绿色 *)
    TC : TON;           (* 对中 *)
    TL : TON;           (* 离台 *)
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    C2_FWD := RUN;
    C3_FWD := RUN;
    TC(IN := STEP = 3, PT := T#400MS);
    TL(IN := STEP = 5 AND NOT T1_PART, PT := T#1500MS);
    CASE STEP OF
        0:  GREEN := FALSE;
            IF RUN AND T1_HOME AND NOT T1_PART THEN STEP := 1; END_IF;
        1:  IF V1_DETECT AND V1_CODE = 2 THEN GREEN := TRUE; END_IF;
            IF S_ST THEN STEP := 2; END_IF;                             (* 零件刚过挡板 *)
        2:  IF V1_DETECT AND V1_CODE = 2 THEN GREEN := TRUE; END_IF;
            IF T1_PART THEN STEP := 3; END_IF;
        3:  IF TC.Q THEN
                IF GREEN THEN STEP := 4; ELSE STEP := 5; END_IF;
            END_IF;
        4:  IF T1_TURNED THEN STEP := 5; END_IF;
        5:  IF TL.Q THEN STEP := 6; END_IF;
        6:  IF T1_HOME THEN STEP := 0; END_IF;
    END_CASE;
    ST1_RAISE := NOT (STEP = 1);
    T1_TURN := RUN AND (STEP = 4 OR STEP = 5) AND GREEN;
    T1_ROLL_FWD := RUN AND (STEP = 1 OR STEP = 2 OR (STEP = 3 AND NOT TC.Q) OR STEP = 5);
END_PROGRAM
""", ref_vars=[],
      test={'duration': 222, 'steps': start_steps('C1_FWD') + [{'t': 210.0, 'snapshot': True}] + estop_steps(211.0, ['C1_FWD', 'C2_FWD', 'C3_FWD', 'T1_ROLL_FWD'], 'C1_FWD')},
      rules=[{**r, 'value': 6} if r['key'] == 'throughput_per_min' else r for r in SORT_RULES],
      faults=[F('S_ST', 'sensor_stuck_off', '挡停落下后不升起，零件一个接一个冲进转台'), F('T1', 'actuator_slow', '转台转得很慢'),
              F('T1', 'actuator_jam', '转台不转，T1_TURNED 不来'), F('V1', 'wire_break', '所有零件都直行')])

# ---------------------------------------------------------------- 11 升降机两层
scene(id='s11_lift', level=11, name='升降机两层输送',
      desc='下层输送带把零件送上升降台，升到上层后送到上层输送带。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='uniform(9,11)', parts=[{'kind': 'box', 'color': 'blue', 'h': 0.2, 'w': 0.25, 'weight': 2},
                                                                               {'kind': 'box', 'color': 'red', 'h': 0.2, 'w': 0.25, 'weight': 1}]),
          belt('C1', -1.6, 0, 4.4, speed=0.3, label='下层输送带'),
          C('L1', 'lift', (1.0, 0, 0), size=(0.8, 0.7), label='升降台', height=0.25, z_high=1.0, speed=0.4, roll_speed=0.3),
          belt('C2', 2.6, 0, 2.4, speed=0.3, label='上层输送带', height=1.0),
          C('S_TOP', 'diffuse_sensor', (1.9, 0.35, 1.1), label='上层入口光电'),
          C('R1', 'remover', (3.85, 0, 0.95), size=(0.4, 0.8), label='上层出口'),
          *panel()]},
      task="""## 任务：升降机两层输送

1. 启停、急停同前；上层输送带 C2 一直运行；
2. 升降台 `L1` 在下位（`L1_BOTTOM`）时，下层输送带 C1 和台面滚筒运行，把零件送上台面；
3. 零件到台面中央（`L1_PART`）后：C1 停止、滚筒停止、升降台上升（`L1_UP`）；
4. 到上位（`L1_TOP`）后滚筒正转把零件送到 C2；上层入口光电 `S_TOP` 检测到零件后，升降台下降回下位；
5. 升降台升降时零件必须完全在台面上（否则记碰撞），不能有零件卡在台边（卡件），不能掉件；评分测试时段内至少送到上层出口 15 件（每分钟约 5 件）。
""",
      hints=['升降台不在下位时 C1 一定要停，否则零件会顶在台子侧面（卡件）。'],
      ref_st="""PROGRAM Lift
VAR
    RUN : BOOL;
    STEP : INT := 0;    (* 0 接料  1 对中  2 上升  3 出料  4 下降 *)
    TM : TON;
END_VAR
""" + RUN_ST + """    C2_FWD := RUN;
    TM(IN := STEP = 1, PT := T#600MS);
    CASE STEP OF
        0:  IF L1_PART THEN STEP := 1; END_IF;
        1:  IF TM.Q THEN STEP := 2; END_IF;
        2:  IF L1_TOP THEN STEP := 3; END_IF;
        3:  IF S_TOP THEN STEP := 4; END_IF;
        4:  IF L1_BOTTOM THEN STEP := 0; END_IF;
    END_CASE;
    C1_FWD := RUN AND STEP = 0 AND L1_BOTTOM;
    L1_ROLL_FWD := RUN AND ((STEP = 0 AND L1_BOTTOM) OR STEP = 1 OR STEP = 3);
    L1_UP := STEP = 2 OR STEP = 3;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 222, 'steps': start_steps('C2_FWD') + [{'t': 210.0, 'snapshot': True}] + estop_steps(211.0, ['C1_FWD', 'C2_FWD', 'L1_ROLL_FWD'], 'C2_FWD')},
      rules=[{'key': 'removed', 'label': '送到上层出口的件数', 'op': '>=', 'value': 15, 'weight': 30},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 20},
             {'key': 'jams', 'label': '卡件次数', 'op': '==', 'value': 0, 'weight': 15},
             {'key': 'dropped', 'label': '掉件数', 'op': '==', 'value': 0, 'weight': 10}] + STD_RULES,
      faults=[F('L1', 'actuator_slow', '升降台很慢，下层零件堆积'), F('S_TOP', 'sensor_stuck_off', '升降台停在上位不下来'),
              F('L1', 'wire_break', '升降台不动作')])

# ---------------------------------------------------------------- 12 取放机械手
scene(id='s12_pick_place', level=12, name='气动取放机械手',
      desc='两位气缸驱动的取放机械手把零件从一条线搬到另一条线：经典的顺序控制。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), interval='uniform(9,11)', parts=[{'kind': 'part', 'color': 'grey', 'material': 'metal', 'h': 0.2, 'w': 0.25}]),
          belt('C1', -1.4, 0, 4.8, speed=0.3, label='来料输送带'),
          C('ST1', 'stopper', (0.93, 0, 0), label='端头挡块', normally_up=True),
          C('S1', 'diffuse_sensor', (0.8, 0.35, BEAM), label='取料位光电'),
          C('PP1', 'pick_place', (0.8, 0, 0), -90, label='取放机械手', mode='pneumatic', x_stroke=1.2, z_stroke=0.65, z_top=1.1, x_speed=0.8, z_speed=0.5),
          belt('C2', 1.95, -1.2, 3.9, speed=0.3, label='出料输送带'),
          C('R1', 'remover', (3.85, -1.2, 0), size=(0.3, 0.8), label='出口'),
          *panel()]},
      task="""## 任务：气动取放机械手

机械手 `PP1` 有两个两位气缸：水平 `PP1_X_EXT`（伸出到出料线上方），垂直 `PP1_Z_DOWN`（下降），吸盘 `PP1_GRIP`；
到位信号 `PP1_X_BACK` / `PP1_X_FRONT` / `PP1_Z_TOP` / `PP1_Z_BOTTOM`（下降碰到零件也算到底），吸住 `PP1_GRIPPED`。

1. 启停、急停同前；
2. 零件到取料位（`S1`）后：下降 → 吸取 → 上升 → 伸出 → 下降 → 松开 → 上升 → 缩回，回到原位等下一件；
3. **必须上升到位后才能平移**（否则撞到零件/输送带记碰撞）；必须下降到位后才能松开（否则摔件）；
4. 不能掉件；评分测试时段内至少搬运 15 件（每分钟约 5 件）。
""",
      hints=['典型的步进顺序控制：每一步等上一步的到位信号。', '松开吸盘后等 0.3 s 再上升。'],
      ref_st="""PROGRAM PickPlace
VAR
    RUN : BOOL;
    STEP : INT := 0;
    TM : TON;
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    C2_FWD := RUN;
    TM(IN := STEP = 2 OR STEP = 6, PT := T#300MS);
    CASE STEP OF
        0: IF RUN AND S1 AND PP1_X_BACK AND PP1_Z_TOP THEN STEP := 1; END_IF;
        1: IF PP1_Z_BOTTOM THEN STEP := 2; END_IF;          (* 下降到零件 *)
        2: IF PP1_GRIPPED AND TM.Q THEN STEP := 3; END_IF;    (* 吸住 *)
        3: IF PP1_Z_TOP THEN STEP := 4; END_IF;             (* 上升 *)
        4: IF PP1_X_FRONT THEN STEP := 5; END_IF;           (* 伸出 *)
        5: IF PP1_Z_BOTTOM THEN STEP := 6; END_IF;          (* 下降到出料线 *)
        6: IF TM.Q THEN STEP := 7; END_IF;                   (* 松开 *)
        7: IF PP1_Z_TOP THEN STEP := 8; END_IF;             (* 上升 *)
        8: IF PP1_X_BACK THEN STEP := 0; END_IF;            (* 缩回 *)
    END_CASE;
    PP1_Z_DOWN := STEP = 1 OR STEP = 2 OR STEP = 5 OR STEP = 6;
    PP1_GRIP := STEP >= 2 AND STEP <= 5;
    PP1_X_EXT := STEP >= 4 AND STEP <= 7;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 192, 'steps': start_steps('C1_FWD') + [{'t': 180.0, 'snapshot': True}] + estop_steps(181.0, ['C1_FWD', 'C2_FWD'], 'C1_FWD')},
      rules=[{'key': 'removed', 'label': '搬运完成件数', 'op': '>=', 'value': 15, 'weight': 30},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 20},
             {'key': 'hard_drops', 'label': '高处摔落次数', 'op': '==', 'value': 0, 'weight': 15},
             {'key': 'dropped', 'label': '掉件数', 'op': '==', 'value': 0, 'weight': 10}] + STD_RULES,
      faults=[F('PP1', 'actuator_slow', '机械手动作慢'), F('S1', 'sensor_stuck_off', '机械手不去取料'),
              F('PP1', 'actuator_jam', '机械手停在半路，到位信号不来'), F('C2', 'motor_overload', '出料线不动，零件堆在放料位')])

# ---------------------------------------------------------------- 13 立库出入库
scene(id='s13_asrs', level=13, name='立体仓库出入库',
      desc='堆垛机把入库口的托盘存进货架，按出库按钮把最早入库的托盘送到出库口。',
      cell={'size': [8, 4.4], 'components': [
          C('RK1', 'rack', (0.0, -0.85, 0), size=(3.2, 0.6), label='货架', cols=4, rows=3, cell_h=0.5, base=0.3),
          C('SC1', 'stacker_crane', (-2.4, 0, 0), 0, size=(4.8, 0.5), label='堆垛机', travel=4.8, rack='RK1', fork_stroke=0.85, fork_speed=0.5,
            x_speed=1.0, z_speed=0.6, station_in=[0.3, 0.21], station_out=[4.5, 0.21]),
          C('E_IN', 'emitter', (-2.1, 1.75, EMIT), interval='uniform(24,28)', max=6, label='入库来料', start_delay=2,
            parts=[{'kind': 'pallet', 'color': 'blue', 'h': 0.25, 'w': 0.45, 'weight': 1}, {'kind': 'pallet', 'color': 'orange', 'h': 0.25, 'w': 0.45, 'weight': 1}]),
          belt('C_IN', -2.1, 1.25, 1.3, rot=-90, speed=0.3, label='入库输送带', W=0.6),
          C('ST_IN', 'stopper', (-2.1, 0.6, 0), -90, label='入库口挡块', normally_up=True),
          C('S_IN', 'diffuse_sensor', (-2.45, 0.85, BEAM), 90, label='入库口光电', range=0.8),
          belt('C_OUT', 2.1, 1.25, 1.3, rot=90, speed=0.3, label='出库输送带', W=0.6),
          C('R_OUT', 'remover', (2.1, 2.05, 0), size=(0.9, 0.3), label='出库口'),
          *panel(x0=-1.2, y=1.85, extra=[C('OUT_REQ', 'button', (0, 0, 0), label='出库', color='yellow'),
                                          C('D1', 'display', (0, 0, 0), label='库存')])]},
      task="""## 任务：立体仓库出入库

堆垛机 `SC1`：输出目标号 `SC1_TARGET`（0 = 入库口，1–12 = 货架库位，从下往上逐层、每层从左往右，13 = 出库口），到达后 `SC1_AT_TARGET` = 1；
货叉 `SC1_FORK_LEFT` 伸向输送带一侧、`SC1_FORK_RIGHT` 伸向货架一侧，`SC1_LIFT` 顶升托起货物。

1. 启停、急停同前；
2. **入库**：托盘到入库口（`S_IN`）后，堆垛机到入库口 → 货叉左伸 → 顶升 → 货叉收回 → 到第一个空库位 → 货叉右伸 → 落下 → 收回；
3. **出库**：按 **出库** 按钮登记一次出库请求；堆垛机空闲时把**最早入库**的托盘取出送到出库口（目标 13，货叉左伸放到出库输送带上）；
4. 数码管 `D1` 显示当前库存数；
5. 货叉没收回时堆垛机不能移动（否则碰撞）；同一库位不能放两个托盘；不能掉件。
""",
      hints=['用两个计数：入库序号 NIN（下一个空库位 = NIN + 1）、出库序号 NOUT（最早的托盘在 NOUT + 1），先进先出。',
             '入库和出库都写成同一个状态机里的两段步骤。'],
      ref_st="""PROGRAM Asrs
VAR
    RUN : BOOL;
    STEP : INT := 0;
    NIN : INT := 0;         (* 已入库个数 *)
    NOUT : INT := 0;        (* 已出库个数 *)
    REQ : INT := 0;         (* 待处理出库请求 *)
    OUTTRIG : R_TRIG;
    TM : TON;
END_VAR
""" + RUN_ST + """    C_IN_FWD := RUN;
    C_OUT_FWD := RUN;
    OUTTRIG(CLK := OUT_REQ);
    IF OUTTRIG.Q THEN REQ := REQ + 1; END_IF;
    TM(IN := STEP = 12 OR STEP = 16 OR STEP = 32 OR STEP = 36, PT := T#400MS);
    CASE STEP OF
        0:  SC1_FORK_LEFT := FALSE; SC1_FORK_RIGHT := FALSE; SC1_LIFT := FALSE;
            IF RUN AND SC1_FORK_HOME THEN
                IF S_IN AND NIN < 12 THEN STEP := 10;
                ELSIF REQ > 0 AND NIN > NOUT THEN STEP := 30;
                END_IF;
            END_IF;
        (* ---- 入库 ---- *)
        10: SC1_TARGET := 0; STEP := 11;
        11: IF SC1_AT_TARGET THEN SC1_FORK_LEFT := TRUE; STEP := 12; END_IF;
        12: IF SC1_FORK_LEFT_END AND TM.Q THEN SC1_LIFT := TRUE; STEP := 13; END_IF;
        13: IF SC1_LOADED THEN SC1_FORK_LEFT := FALSE; STEP := 14; END_IF;
        14: IF SC1_FORK_HOME THEN SC1_TARGET := NIN + 1; STEP := 15; END_IF;
        15: IF SC1_AT_TARGET THEN SC1_FORK_RIGHT := TRUE; STEP := 16; END_IF;
        16: IF SC1_FORK_RIGHT_END AND TM.Q THEN SC1_LIFT := FALSE; STEP := 17; END_IF;
        17: IF NOT SC1_LOADED THEN SC1_FORK_RIGHT := FALSE; STEP := 18; END_IF;
        18: IF SC1_FORK_HOME THEN NIN := NIN + 1; STEP := 0; END_IF;
        (* ---- 出库：先进先出 ---- *)
        30: SC1_TARGET := NOUT + 1; STEP := 31;
        31: IF SC1_AT_TARGET THEN SC1_FORK_RIGHT := TRUE; STEP := 32; END_IF;
        32: IF SC1_FORK_RIGHT_END AND TM.Q THEN SC1_LIFT := TRUE; STEP := 33; END_IF;
        33: IF SC1_LOADED THEN SC1_FORK_RIGHT := FALSE; STEP := 34; END_IF;
        34: IF SC1_FORK_HOME THEN SC1_TARGET := 13; STEP := 35; END_IF;
        35: IF SC1_AT_TARGET THEN SC1_FORK_LEFT := TRUE; STEP := 36; END_IF;
        36: IF SC1_FORK_LEFT_END AND TM.Q THEN SC1_LIFT := FALSE; STEP := 37; END_IF;
        37: IF NOT SC1_LOADED THEN SC1_FORK_LEFT := FALSE; STEP := 38; END_IF;
        38: IF SC1_FORK_HOME THEN NOUT := NOUT + 1; REQ := REQ - 1; STEP := 0; END_IF;
    END_CASE;
    D1 := NIN - NOUT;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 300, 'steps': start_steps('C_IN_FWD') + [
          {'t': 95.0, 'press': 'OUT_REQ'}, {'t': 100.0, 'press': 'OUT_REQ'},
          {'t': 287.0, 'snapshot': True}, {'t': 287.0, 'key': 'display_ok', 'check': {'out': 'D1', 'eq_stat': 'racks.RK1.stored'}, 'desc': '数码管显示的库存不对'}]
          + estop_steps(288.0, ['C_IN_FWD', 'C_OUT_FWD', 'SC1_FORK_LEFT', 'SC1_FORK_RIGHT'], 'C_IN_FWD')},
      rules=[{'key': 'racks.RK1.stored', 'label': '库存托盘数', 'op': '==', 'value': 4, 'weight': 20},
             {'key': 'bins.R_OUT.n', 'label': '出库托盘数', 'op': '==', 'value': 2, 'weight': 20},
             {'key': 'racks.RK1.double', 'label': '重复放入的库位', 'op': '==', 'value': 0, 'weight': 5},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 15},
             {'key': 'dropped', 'label': '掉件数', 'op': '==', 'value': 0, 'weight': 5},
             {'key': 'display_ok', 'label': '库存显示正确', 'op': '==', 'value': 1, 'weight': 10}] + STD_RULES,
      faults=[F('S_IN', 'sensor_stuck_off', '托盘到了入库口也不入库'), F('SC1', 'actuator_slow', '堆垛机很慢'),
              F('OUT_REQ', 'wire_break', '按出库没有反应'), F('SC1', 'actuator_jam', '堆垛机不动，到达信号不来')])

# ---------------------------------------------------------------- 14 双工位联锁
scene(id='s14_dual_station', level=14, name='双工位联锁',
      desc='两个串联工位：一号工位加工 3 s，二号工位加工 6 s；二号工位有件时一号工位不能放行。',
      cell={'size': [8, 4], 'components': [
          C('E1', 'emitter', (-3.6, 0, EMIT), trigger='signal', label='料仓', parts=[{'kind': 'part', 'color': 'grey', 'material': 'metal', 'h': 0.15, 'w': 0.25}]),
          belt('C1', 0.0, 0, 7.6, speed=0.3, label='输送带'),
          C('ST1', 'stopper', (-2.6, 0, 0), label='一号工位挡停'),
          C('S1', 'diffuse_sensor', (-2.64, 0.35, 0.32), label='一号工位光电'),
          C('ST2', 'stopper', (-1.9, 0, 0), label='二号工位挡停'),
          C('S2', 'diffuse_sensor', (-1.94, 0.35, 0.32), label='二号工位光电'),
          C('R1', 'remover', (3.85, 0, 0), size=(0.4, 0.9), label='出口'),
          *panel(extra=[C('LAMP_W1', 'lamp', (0, 0, 0), label='一号加工', color='yellow'), C('LAMP_W2', 'lamp', (0, 0, 0), label='二号加工', color='yellow')])]},
      task="""## 任务：双工位联锁

一条输送带上有两个工位，各有一个挡停（输出 1 = 升起挡住）和到位光电。

1. 启停、急停同前；挡停平时升起；料仓 `E1` 按需放料（`E1_RELEASE` 上升沿放一件）：一号工位空了（上一件已经放行）才放下一件；
2. 零件到一号工位停留 **3 s**，到二号工位停留 **6 s**（加工中对应的灯亮），然后挡停落下 1 s 放行；
3. **联锁**：二号工位上有零件（或者有零件正从一号工位往二号工位走）时，一号工位加工完也不能放行，必须等二号工位的零件离开；
4. 两个工位可以同时加工；不能有零件追尾、不能碰撞，每分钟至少 5 件。
""",
      hints=['用一个"二号工位占用"标志：一号放行时置位，二号工位的零件离开（S2 下降沿）时复位。'],
      ref_st="""PROGRAM DualStation
VAR
    RUN : BOOL;
    W1T : TON;  W2T : TON;              (* 加工计时 *)
    P1T : TON;  P2T : TON;              (* 放行计时 *)
    H1 : BOOL := TRUE;  H2 : BOOL := TRUE;
    W2_BUSY : BOOL;                      (* 二号工位占用（含途中） *)
    S2F : F_TRIG;
    DONE1 : BOOL;
    W1_BUSY : BOOL;                      (* 一号工位占用（含料仓到工位途中） *)
    FEED : BOOL;
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;
    (* 按需放料：一号工位空了才放下一件 *)
    FEED := RUN AND NOT W1_BUSY;
    IF FEED THEN W1_BUSY := TRUE; END_IF;
    E1_RELEASE := FEED;
    (* 一号工位 *)
    W1T(IN := S1 AND H1, PT := T#3200MS);
    IF W1T.Q THEN DONE1 := TRUE; END_IF;
    IF DONE1 AND NOT W2_BUSY THEN
        H1 := FALSE; DONE1 := FALSE; W2_BUSY := TRUE;
    END_IF;
    P1T(IN := NOT H1, PT := T#1S);
    IF P1T.Q THEN H1 := TRUE; W1_BUSY := FALSE; END_IF;
    (* 二号工位 *)
    W2T(IN := S2 AND H2, PT := T#6200MS);
    IF W2T.Q THEN H2 := FALSE; END_IF;
    P2T(IN := NOT H2, PT := T#1S);
    IF P2T.Q THEN H2 := TRUE; END_IF;
    S2F(CLK := S2);
    IF S2F.Q AND NOT H2 THEN W2_BUSY := FALSE; END_IF;
    ST1_RAISE := H1;
    ST2_RAISE := H2;
    LAMP_W1 := S1 AND H1;
    LAMP_W2 := S2 AND H2;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 252, 'steps': start_steps('C1_FWD') + [{'t': 240.0, 'snapshot': True}] + estop_steps(241.0, ['C1_FWD'], 'C1_FWD')},
      rules=[{'key': 'dwell_min.ST1', 'label': '一号工位最短停留 s', 'op': '>=', 'value': 3.0, 'weight': 15},
             {'key': 'dwell_min.ST2', 'label': '二号工位最短停留 s', 'op': '>=', 'value': 6.0, 'weight': 15},
             {'key': 'part_contacts', 'label': '零件追尾次数（联锁）', 'op': '==', 'value': 0, 'weight': 25},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 10},
             {'key': 'throughput_per_min', 'label': '每分钟产出', 'op': '>=', 'value': 5, 'weight': 10}] + STD_RULES,
      faults=[F('S2', 'sensor_stuck_on', '一号工位一直不放行'), F('ST2', 'actuator_jam', '二号工位挡停不落，零件堆积'),
              F('S1', 'sensor_flicker', '一号工位加工时间不够')])

# ---------------------------------------------------------------- 15 整线联动
scene(id='s15_full_line', level=15, name='整线联动（接入整厂）',
      desc='整厂上游来料进入单元：工位加工、颜色检测剔除次品、转台按材质分流，合格件和次品分别交回整厂。',
      cell={'size': [9, 4.6], 'components': [
          C('IN1', 'cell_entry', (-4.1, 0, EMIT), label='单元入口', min_gap=6.0,
            assign={'random': [{'color': 'blue', 'material': 'plastic', 'weight': 4}, {'color': 'green', 'material': 'plastic', 'weight': 2},
                               {'color': 'grey', 'material': 'metal', 'weight': 3}], 'default': {'kind': 'box', 'h': 0.2, 'w': 0.25}}),
          belt('C1', -1.65, 0, 5.7, speed=0.3, label='主输送带'),
          C('ST1', 'stopper', (-2.8, 0, 0), label='加工工位挡停'),
          C('S1', 'diffuse_sensor', (-2.84, 0.35, BEAM), label='加工工位光电'),
          C('V1', 'vision_sensor', (-1.9, 0, 0.9), label='颜色检测'),
          C('S2', 'diffuse_sensor', (-1.0, 0.35, BEAM), label='剔除推杆光电'),
          C('P1', 'pusher', (-1.0, 0.42, BEAM), label='剔除推杆', stroke=0.8),
          C('OUT_NG', 'cell_exit', (-1.0, -0.76, 0), size=(0.9, 0.9), label='次品出口', port='ng', accept={'color': 'green'}),
          C('ST2', 'stopper', (0.85, 0, 0), label='分离挡停'),
          C('IND1', 'inductive', (1.0, -0.3, 0.32), 180, label='电感（金属）', range=0.2),
          C('S_ST', 'diffuse_sensor', (1.12, 0.35, BEAM), label='过挡停光电'),
          C('T1', 'turntable', (1.65, 0, 0), size=(0.9, 0.9), label='转台', angle=-90),
          belt('C2', 3.2, 0, 2.2, speed=0.3, label='塑料件输送带'),
          belt('C3', 1.65, -1.3, 1.7, rot=-90, speed=0.3, label='金属件输送带'),
          C('OUT_PL', 'cell_exit', (4.35, 0, 0), size=(0.3, 0.9), label='塑料件出口', accept={'material': 'plastic', 'color': 'blue'}),
          C('OUT_ME', 'cell_exit', (1.65, -2.2, 0), size=(0.9, 0.2), label='金属件出口', accept={'material': 'metal'}),
          *panel(x0=-4.1, y=1.9, extra=[C('LAMP_WORK', 'lamp', (0, 0, 0), label='加工中', color='yellow'), C('D1', 'display', (0, 0, 0), label='合格数')])]},
      task="""## 任务：整线联动（接入整厂）

本单元放在整厂流程里：上游零件从单元入口进入，合格件从"塑料件出口""金属件出口"交回整厂下游（out），次品从"次品出口"交给整厂的不合格品通道（ng）。

1. 启停、急停同前；
2. **加工**：零件到加工工位（`S1`）后挡停 `ST1` 挡住停留 **2 s**（加工中灯亮），然后放行；
3. **检测剔除**：视觉 `V1` 识别到**绿色**（次品）时，零件到推杆前（`S2`）由推杆 `P1` 推进次品出口；
4. **分流**：分离挡停 `ST2` 每次只放一个零件进转台，电感开关 `IND1`（装在挡停和转台之间）识别金属件：金属件转到 -90° 送到金属件输送带 C3，塑料件直行到 C2；
5. 数码管 `D1` 显示合格件（两个合格出口）累计数；
6. 正确率 ≥ 98%，不碰撞、不卡件，每分钟至少 5 件。
""",
      hints=['可以把前面几个场景的程序拼起来：工位停留（场景 8）、颜色剔除（场景 4）、转台分流（场景 10）。',
             '放行的零件经过 IND1 时记下"是金属"，回到等料步骤时清掉。'],
      ref_st="""PROGRAM FullLine
VAR
    RUN : BOOL;
    (* 加工工位 *)
    WT : TON;  PT1 : TON;  H1 : BOOL := TRUE;
    (* 剔除 *)
    IS_GREEN : BOOL;  PUSH : BOOL;  TRIG2 : R_TRIG;
    (* 转台 *)
    STEP : INT := 0;  METAL : BOOL;  TC : TON;  TL : TON;
    GOOD : INT := 0;
END_VAR
""" + RUN_ST + """    C1_FWD := RUN;  C2_FWD := RUN;  C3_FWD := RUN;
    (* ---- 加工工位：停留 2 s ---- *)
    WT(IN := S1 AND H1, PT := T#2200MS);
    LAMP_WORK := S1 AND H1;
    IF WT.Q THEN H1 := FALSE; END_IF;
    PT1(IN := NOT H1, PT := T#1S);
    IF PT1.Q THEN H1 := TRUE; END_IF;
    ST1_RAISE := H1;
    (* ---- 颜色剔除 ---- *)
    IF V1_DETECT THEN IS_GREEN := (V1_CODE = 2); END_IF;
    TRIG2(CLK := S2);
    IF TRIG2.Q AND IS_GREEN AND RUN THEN PUSH := TRUE; IS_GREEN := FALSE; END_IF;
    IF P1_FRONT OR NOT RUN THEN PUSH := FALSE; END_IF;
    P1_EXTEND := PUSH;
    (* ---- 转台分流 ---- *)
    TC(IN := STEP = 3, PT := T#400MS);
    TL(IN := STEP = 5 AND NOT T1_PART, PT := T#1500MS);
    CASE STEP OF
        0:  METAL := FALSE;
            IF RUN AND T1_HOME AND NOT T1_PART THEN STEP := 1; END_IF;
        1:  IF IND1 THEN METAL := TRUE; END_IF;
            IF S_ST THEN STEP := 2; END_IF;
        2:  IF IND1 THEN METAL := TRUE; END_IF;
            IF T1_PART THEN STEP := 3; END_IF;
        3:  IF TC.Q THEN
                IF METAL THEN STEP := 4; ELSE STEP := 5; END_IF;
            END_IF;
        4:  IF T1_TURNED THEN STEP := 5; END_IF;
        5:  IF TL.Q THEN STEP := 6; GOOD := GOOD + 1; END_IF;
        6:  IF T1_HOME THEN STEP := 0; END_IF;
    END_CASE;
    ST2_RAISE := NOT (STEP = 1);
    T1_TURN := RUN AND (STEP = 4 OR STEP = 5) AND METAL;
    T1_ROLL_FWD := RUN AND (STEP = 1 OR STEP = 2 OR (STEP = 3 AND NOT TC.Q) OR STEP = 5);
    D1 := GOOD;
END_PROGRAM
""", ref_vars=[],
      test={'duration': 252, 'feed': {'interval': 'uniform(8,9)', 'start': 1.0},
            'steps': start_steps('C1_FWD') + [{'t': 240.0, 'snapshot': True},
                                              {'t': 240.0, 'key': 'display_ok', 'check': {'out': 'D1', 'op': '>=', 'value': 1}}]
            + estop_steps(241.0, ['C1_FWD', 'C2_FWD', 'C3_FWD', 'P1_EXTEND', 'T1_ROLL_FWD'], 'C1_FWD')},
      rules=[{'key': 'sort_accuracy', 'label': '分拣/剔除正确率', 'op': '>=', 'value': 0.98, 'weight': 25},
             {'key': 'dwell_min.ST1', 'label': '加工工位最短停留 s', 'op': '>=', 'value': 2.0, 'weight': 10},
             {'key': 'collisions', 'label': '碰撞次数', 'op': '==', 'value': 0, 'weight': 15},
             {'key': 'jams', 'label': '卡件次数', 'op': '==', 'value': 0, 'weight': 10},
             {'key': 'throughput_per_min', 'label': '每分钟产出', 'op': '>=', 'value': 5, 'weight': 10},
             {'key': 'display_ok', 'label': '合格数显示', 'op': '==', 'value': 1, 'weight': 5}] + STD_RULES,
      faults=[F('V1', 'wire_break', '次品不被剔除'), F('IND1', 'sensor_stuck_on', '所有零件都转向金属线'), F('T1', 'actuator_slow', '转台慢，来料堆积'),
              F('S_ST', 'sensor_stuck_off', '分离挡停一直落下'), F('P1', 'actuator_jam', '推杆不动，次品混进合格品')])


# ================================================================ 4.5 新手走查修正（docs/audit/4.5-novice-walkthrough.md）
# 只改给学生看的文字（任务书、提示、检查项说明、评分项的"怎么试"），测试序列的动作和判断不变（评分结果不变）。
FIX_TASK = {
    's01_motor_latch': [
        ('2. 按一下 **停止**（红色，**常闭触点**：没按时输入为 1，按下为 0）电机停止；',
         '2. 按一下 **停止**（红色）电机停止。注意停止按钮是**常闭按钮**：没按时 `STOP` = 1，按下时 = 0。所以梯形图里 STOP 要画成'
         '**常开触点 -| |-**（ST 里写 `AND STOP`）；画成常闭触点 -|/|- 的话，没按也是断开，按启动电机不会转；'),
        ('5. 电机运行时 **运行指示灯** 亮。\n',
         '5. 电机运行时 **运行指示灯** 亮。\n\n**做对了是这样**：按一下启动马上松手，输送带一直转、运行灯亮；按一下停止，输送带停、灯灭。'
         '热继电器过载你在操作台上做不出来：在「评分标准（检查表）」里点这一项的「演示」，系统会模拟一次过载。\n'),
    ],
    's02_fwd_rev': [],
    's03_conveyor': [
        ('3. 急停旋转复位后，', '3. 急停拍下后会一直保持（操作台上的按钮变成"复位"），**再点一下**才复位；复位后，'),
        ('4. 末端光电 `S_END` 检测零件到达线尾：运行期间零件要连续送到线尾，评分测试时段内至少送达 6 件（中途按过停止也算在内）。',
         '4. 运行期间零件要连续送到线尾：评分时输送带大约运行 1 分钟（中间停一次），线尾出口要收到至少 6 件。末端光电 `S_END` 只用来观察（程序里可以不用）。'),
    ],
    's05_sort_material': [
        ('启停、急停要求同前（急停复位后要重新按启动）', '启停、急停同前'),
        ('电容接近开关 `CAP1` 任何零件经过都为 1。', '电容接近开关 `CAP1` 任何零件经过都为 1（可以用来判断"有零件经过"，选用）。'),
    ],
    's07_count_box': [
        ('1. 启停、急停同前；\n2. 开始时用 `E_BOX_RELEASE`（上升沿放一个空箱）',
         '1. 启停、急停同前；运行时运行灯 `LAMP_RUN` 亮（开始时要等空箱到位 C1 才转，所以评分用运行灯判断"已启动"）；\n'
         '2. 开始时用 `E_BOX_RELEASE` 放出空箱（它从 0 变 1 一次放一个空箱；一直保持 1 也只放一个，要再放就先回 0）'),
        ('5. 每箱正好 5 个，不掉件、不碰撞。', '5. 每箱正好 5 个，不掉件、不碰撞（箱子不在装箱位、`S_BOX` = 0 时 C1 必须停，否则零件掉到地上）。'),
    ],
    's10_turntable': [
        ('零件进转台（台面滚筒 `T1_ROLL_FWD` 正转），', '视觉颜色码 `V1_CODE`：1 = 蓝，2 = 绿，没有零件时为 0。零件进转台（台面滚筒 `T1_ROLL_FWD` 正转），'),
    ],
    's11_lift': [
        ('3. 零件到台面中央（`L1_PART`）后：C1 停止、滚筒停止、升降台上升（`L1_UP`）；',
         '3. 零件到台面中央（`L1_PART` = 1）后，台面滚筒 `L1_ROLL_FWD` 再转约 0.6 s 让零件完全上台，然后 C1、滚筒停止，升降台上升（`L1_UP`）；'),
    ],
    's13_asrs': [
        ('4. 数码管 `D1` 显示当前库存数；', '4. 数码管 `D1` 显示当前库存数（评分时会来 6 个托盘，测试在第 95 s、100 s 各按一次出库，所以最后货架上 4 个、出库口 2 个）；'),
    ],
    's15_full_line': [
        ('3. **检测剔除**：视觉 `V1` 识别到**绿色**（次品）时，', '3. **检测剔除**：视觉 `V1` 识别到**绿色**（`V1_CODE` = 2，次品）时，'),
    ],
}
FIX_HINT = {
    's06_sort_height': [('用比较指令：H1 > 220 就是高件。', '梯形图里用比较触点（CMP，`H1 > 220`），ST 写 `IF H1 > 220`：高件约 300、矮件约 150，阈值取中间。')],
    's08_timed_feed': [(None, '停留计时比 3 s 多留一点（例如 T#3200MS）：仿真里检测有一个扫描周期的延迟，正好 3 s 可能测出 2.98 s。')],
    's09_palletize': [('第 N 个箱子的 X 位置：850 + (N MOD 3) * 300。', '已经码了 N 个（N 从 0 开始数）时，下一个放在 X = 850 + (N MOD 3) * 300；吸住后等 PP1_GRIPPED = 1 再上升。')],
    's11_lift': [(None, '零件到台面中央（L1_PART）后滚筒再转约 0.6 s，零件完全上台以后再停滚筒、上升。')],
    's12_pick_place': [('松开吸盘后等 0.3 s 再上升。', '吸住（PP1_GRIPPED = 1）后等 0.3 s 再上升；松开吸盘后也等 0.3 s 再上升。')],
    's14_dual_station': [(None, '停留计时比要求多留一点（例如 3.2 s、6.2 s）：检测有一个扫描周期的延迟。')],
    's15_full_line': [('可以把前面几个场景的程序拼起来：工位停留（场景 8）、颜色剔除（场景 4）、转台分流（场景 10）。',
                       '可以把前面几课的程序拼起来：「定时放料与工位停留」（工位停留）、「按颜色分拣」（剔除）、「转台分流」（分流）。')],
}
# 测试步骤里没写 desc 的检查：(场景, key, 时刻) → 没通过时给学生看的原因
FIX_DESC = {
    ('s01_motor_latch', 'start_ok', 10.0): '停止以后再按启动，电机没有重新运行',
    ('s01_motor_latch', 'start_ok', 19.0): '热继电器复位后再按启动，电机没有重新运行',
    ('s02_fwd_rev', 'lamp_ok', 2.0): '正转时正转灯没亮',
    ('s02_fwd_rev', 'lamp_ok', 9.0): '反转时反转灯没亮',
    ('s02_fwd_rev', 'interlock_ok', 11.5): '反转运行中按正转，正转接触器得电了（没有互锁）',
    ('s02_fwd_rev', 'interlock_ok', 4.2): '正转运行中按反转，反转接触器得电了（没有互锁）',
    ('s02_fwd_rev', 'interlock_ok', 5.0): '正转运行中按了反转以后正转停了（按反转应该无效）',
    ('s02_fwd_rev', 'stop_ok', 13.0): '反转时按停止没有停',
    ('s03_conveyor', 'lamp_ok', 2.0): '运行时运行灯没亮 / 停止灯还亮着',
    ('s03_conveyor', 'stop_ok', 31.0): '按停止后输送带没停，或者松开停止后自己又转了',
    ('s03_conveyor', 'start_ok', 35.0): '停止以后再按启动，输送带没有重新运行',
    ('s15_full_line', 'display_ok', 240.0): '数码管 D1 没有显示合格件数',
}
FIX_LABEL = {('s02_fwd_rev', 'hard_reversals'): '高速直接反转次数'}
# 实时检查表里每一项"怎么试"（学生在操作台上怎么触发它）
HOW = {
    's01_motor_latch': {
        'start_ok': '按一下启动（按下就松手），电机 M1_RUN 应该马上变 1',
        'latch_ok': '按一下启动后松开，电机要继续运行至少 3 秒（自锁）',
        'stop_ok': '电机转着的时候按一下停止：1 秒内停，松开停止后也不能自己再转',
        'stop_priority': '电机转着时 Shift+点击把启动锁住按下，再按停止：电机应该停（或点"演示全部"）',
        'overload_ok': '点这一项的"演示"：系统模拟热继电器过载（M1_OL_OK 变 0），电机要立刻停；复位后不能自己转',
        'lamp_ok': '电机转的时候运行灯亮，按停止以后运行灯灭'},
    's02_fwd_rev': {
        'fwd_ok': '停着时按一下正转：M1_FWD 变 1，松手后保持',
        'rev_ok': '停着时按一下反转：M1_REV 变 1，松手后保持',
        'stop_ok': '正转或反转运行时按停止：1 秒内两个接触器都断开',
        'interlock_ok': '正转时按反转应该没反应（正转继续），反转时按正转也一样；任何时候 M1_FWD 和 M1_REV 都不能同时为 1',
        'hard_reversals': '电机转着时按另一个方向的按钮，程序不能直接换向（先按停止）',
        'overload_ok': '点这一项的"演示"：系统模拟过载，两个方向都要立刻停，复位后不能自己转',
        'lamp_ok': '正转时正转灯亮，反转时反转灯亮'},
    's03_conveyor': {
        'start_ok': '按一下启动：C1 运行（松手保持）；停止以后再按启动也要能运行',
        'stop_ok': '运行时按一下停止：1 秒内 C1 停，并且一直停着',
        'estop_ok': '运行时点一下急停：马上停；再点一下复位，C1 不能自己转',
        'restart_ok': '急停复位后按启动，C1 重新运行',
        'lamp_ok': '运行时运行灯亮、停止灯灭；按停止后停止灯亮',
        'removed': '让输送带运行约 1 分钟，线尾出口收到至少 6 件（这里显示当前件数）'},
    's07_count_box': {'bins.R_BOX.ok': '连续运行约 3 分钟，至少送走 5 个正好装了 5 件的满箱（这里显示当前数）'},
    's08_timed_feed': {'emit_min_gap.E1': '运行时两次放料（E1_RELEASE 每次 0→1）之间至少隔 5.5 秒（这里显示目前最小间隔）',
                       'dwell_min.ST1': '每个零件都在工位挡停前停够 3 秒再放行（这里显示目前最短的一次）'},
    's09_palletize': {'pallets.PL1.count': '运行约 100 秒，6 个箱子全部码到托盘上', 'pallets.PL1.layers': '一层 3 个、码成 2 层',
                      'pallets.PL1.inside': '每个箱子都放在托盘范围内（X = 850 / 1150 / 1450）'},
    's13_asrs': {'racks.RK1.stored': '来 6 个托盘，按两次"出库"以后货架上剩 4 个', 'bins.R_OUT.n': '两次出库都执行，出库口收到 2 个（先进先出）',
                 'racks.RK1.double': '同一个库位不能放两个托盘', 'display_ok': '数码管 D1 一直等于货架上实际的托盘数'},
    's14_dual_station': {'dwell_min.ST1': '每个零件在一号工位停够 3 秒（这里显示目前最短的一次）', 'dwell_min.ST2': '每个零件在二号工位停够 6 秒（这里显示目前最短的一次）'},
    's15_full_line': {'dwell_min.ST1': '每个零件在加工工位停够 2 秒（这里显示目前最短的一次）', 'display_ok': '运行一段时间后数码管 D1 显示合格件累计数'},
}
STD_HOW = {'start_ok': '按一下启动，主输送带（评分看 {main}）开始运行',
           'estop_ok': '运行时点一下急停：0.2 秒内运动输出全部断开；再点一下复位，设备不能自己动',
           'restart_ok': '急停复位后按启动，{main} 重新运行'}
STAT_HOW = {'sort_accuracy': '按启动让它连续跑几分钟，看分拣对不对（这里显示当前正确率）',
            'collisions': '连续运行时不能出现碰撞（这里显示当前次数）', 'jams': '连续运行时零件不能被挡住走不动（这里显示当前次数）',
            'throughput_per_min': '连续运行不停线，这里显示当前每分钟产出（刚启动时偏低）', 'removed': '连续运行，这里显示已经送到出口的件数',
            'dropped': '零件不能掉到地上（这里显示当前掉件数）', 'hard_drops': '下降到位后才松开（这里显示高处摔落次数）',
            'part_contacts': '零件之间不能追尾（这里显示当前次数）', 'sorted_wrong': '每箱正好 5 个（这里显示装错的件数）'}


def _fix_45(sc):
    sid = sc['id']
    for old, new in FIX_TASK.get(sid, []):
        assert old in sc['task'], (sid, old[:30])
        sc['task'] = sc['task'].replace(old, new)
    hs = list(sc.get('hints') or [])
    for old, new in FIX_HINT.get(sid, []):
        if old is None:
            hs.append(new)
        else:
            assert old in hs, (sid, old[:30])
            hs[hs.index(old)] = new
    sc['hints'] = hs
    for st in sc['test']['steps']:
        k = (sid, st.get('key'), float(st.get('t', 0)))
        if st.get('check') is not None and not st.get('desc') and k in FIX_DESC:
            st['desc'] = FIX_DESC[k]
    main = next((st['check'].get('out') for st in sc['test']['steps'] if st.get('key') == 'start_ok' and isinstance(st.get('check'), dict)), 'C1_FWD')
    for st in sc['test']['steps']:                 # 标准启动检查：说清楚测的是哪个输出（有的课测运行灯、有的测上层输送带）
        if st.get('key') == 'start_ok' and st.get('desc') == '按启动后没有运行':
            st['desc'] = f'按启动 1 秒后 {main} 还是 0（没有运行）'
    for r in sc['rules']:
        lab = FIX_LABEL.get((sid, r['key']))
        if lab:
            r['label'] = lab
        how = HOW.get(sid, {}).get(r['key']) or STD_HOW.get(r['key'], '').format(main=main) or STAT_HOW.get(r['key'])
        if how:
            r['how'] = how


for _s in SCENES:
    _fix_45(_s)


STD_TEXT = ('启停与急停：按 **启动** 运行，按 **停止** 停止；按下 **急停** 所有运动立即停止，急停复位后设备不能自己恢复，'
            '必须重新按启动；急停拍下后会一直保持（操作台上的按钮变成"复位"），再点一下才复位')
for _s in SCENES:                      # "启停、急停同前"展开成完整要求（任务书单独发给学生，不能指望"同前"）
    _s['task'] = _s['task'].replace('启停、急停同前', STD_TEXT)
    assert '同前' not in _s['task'], _s['id']


# ================================================================ 生成
def io_table_md(io):
    rows = ['| 名称 | 方向 | 类型 | 地址 | 触点 | 未操作时 | 说明 |', '|---|---|---|---|---|---|---|']
    for e in io:
        ct = {'NO': '常开', 'NC': '**常闭**'}.get(e.get('contact'), '—')
        idle = e.get('idle', 0)
        idle = ('1' if idle else '0') if (e.get('type') or 'BOOL') == 'BOOL' else str(idle)
        rows.append(f"| `{e['name']}` | {'输入' if e['dir'] == 'in' else '输出'} | {e['type']} | {e['addr']} | {ct} | {idle} | {e.get('comment', '')} |")
    return '\n'.join(rows)


def contact_note(io):
    """任务书里的触点说明（自动生成，和 I/O 表一致）。"""
    nc = nc_inputs(io)
    if not nc:
        return '> 触点说明：本单元的按钮和传感器都是**常开触点**，未按下 / 没检测到时为 0，按下 / 检测到时为 1。'
    names = '、'.join(f'`{n}`' for n in nc)
    home = [e['name'] for e in io if e.get('dir') == 'in' and e.get('contact') == 'NO' and e.get('idle')]
    tail = f'例外：{"、".join(f"`{n}`" for n in home)} 是"在原位/到位"信号，设备停在初始位置时就是 1。' if home else ''
    return (f'> 触点说明：{names} 是**常闭触点**，未按下（未动作）时为 **1**，按下（动作）时为 0——梯形图里用**常开触点**串联它们'
            f'（ST 里直接 AND），不要取反；其余按钮和传感器是常开触点，未动作时为 0。{tail}')


# 评分项 → 任务书正文里必须出现的说法（任选其一）；removed / throughput_per_min 还要写出具体数值
MENTION = {'start_ok': ['启动'], 'stop_ok': ['停止'], 'estop_ok': ['急停'], 'restart_ok': ['重新按启动'], 'latch_ok': ['自锁'],
           'stop_priority': ['停止优先'], 'overload_ok': ['热继电器'], 'lamp_ok': ['灯'], 'fwd_ok': ['正转'], 'rev_ok': ['反转'],
           'interlock_ok': ['互锁'], 'hard_reversals': ['先按停止'], 'sort_accuracy': ['正确率'], 'collisions': ['碰撞'], 'jams': ['卡件'],
           'throughput_per_min': ['每分钟'], 'removed': ['件'], 'dropped': ['掉件'], 'hard_drops': ['摔'], 'part_contacts': ['追尾'],
           'sorted_wrong': ['正好'], 'display_ok': ['数码管'], 'bins.R_BOX.ok': ['每箱'], 'dwell_min.ST1': ['停留'], 'dwell_min.ST2': ['停留'],
           'emit_min_gap.E1': ['间隔'], 'pallets.PL1.count': ['共 2 层 6 个'], 'pallets.PL1.layers': ['2 层'], 'pallets.PL1.inside': ['托盘范围'],
           'racks.RK1.stored': ['库存'], 'bins.R_OUT.n': ['出库'], 'racks.RK1.double': ['同一库位']}
CONTRADICT = ['不要求', '可以不做', '不评分']


def check_task(s):
    """任务书和评分规则对齐：每个评分项在任务书正文里都有对应要求；正文里不能出现"不要求"之类和评分矛盾的话。返回问题列表。"""
    text = s['task']
    out = []
    for r in s['rules']:
        kws = r.get('mention') or MENTION.get(r['key'])
        if not kws:
            out.append(f"{s['id']}: 评分项 {r['key']} 没有配置任务书关键词（MENTION 或 rule.mention）")
            continue
        if not any(k in text for k in kws):
            out.append(f"{s['id']}: 评分项「{r.get('label')}」在任务书正文里找不到对应要求（应出现：{' / '.join(kws)}）")
        if r['key'] in ('removed', 'throughput_per_min') and f"{r['value']:g}" not in text:
            out.append(f"{s['id']}: 评分项「{r.get('label')}」的指标 {r['value']:g} 没写进任务书正文")
    for w in CONTRADICT:
        if w in text:
            out.append(f"{s['id']}: 任务书正文里有「{w}」，和评分规则矛盾")
    return out


def rules_md(rules):
    """评分标准写成人话：做到 = 1 的写"（做到）"，= 0 的写"（不能出现）"，比例写成百分数。"""
    from ..scoring import OP_CN

    def cond(r):
        op, v = r['op'], r['value']
        if op == '==' and (v is True or v == 1) and not isinstance(v, float):
            return '（做到）'
        if op == '==' and v == 0 and not isinstance(v, bool):
            return '：必须为 0（不能出现）'
        if isinstance(v, float) and 0 < v < 1:
            return f' {OP_CN.get(op, op)} {v * 100:g}%'
        return f' {OP_CN.get(op, op)} {v}'
    lines = [f"- {r['label']}{cond(r)}：**{r['weight']:g} 分**" + (f"\n  - 怎么试：{r['how']}" if r.get('how') else '') for r in rules]
    return '\n'.join(lines) + '\n\n> 进沙箱以后，「评分标准（检查表）」页签会边操作边打勾，判断方法和提交评分完全一样。'


def build(s):
    cell = copy.deepcopy(s['cell'])
    for c in cell['components']:
        c.setdefault('rot', 0)
        assert c['type'] in COMP_TYPES, c['type']
    cell['io'] = auto_io(cell, keep=[])
    io = cell['io']
    names = {e['name'] for e in io}
    ref = {'st': prog('参考答案', s['ref_st'], s.get('ref_vars'))}
    if s.get('ref_ld'):
        ref['ld'] = ld('参考答案', s['ref_ld'], s.get('ld_vars') or [])
    md = (s['task'].rstrip() + '\n\n' + contact_note(io) + '\n\n### I/O 分配表\n\n' + io_table_md(io) + '\n\n### 评分标准（满分 '
          + f"{sum(r['weight'] for r in s['rules']):g}" + ' 分）\n\n' + rules_md(s['rules']) + '\n')
    checks = {st['key'] for st in s['test']['steps'] if st.get('key')}
    cell['metrics'] = [r['key'] for r in s['rules'] if r['key'] not in checks]     # 统计页按评分指标显示（测试序列的检查项不算统计量）
    if not cell['metrics']:
        types = {c['type'] for c in cell['components']}
        cell['metrics'] = ['interlock_violations', 'hard_reversals'] if 'motor' in types else ['removed', 'throughput_per_min']
    out = {'id': s['id'], 'name': s['name'], 'level': s['level'], 'order': s['level'], 'desc': s['desc'],
           'cell': cell, 'plc': {'mode': 'internal', 'scan_ms': 20}, 'io': io, 'task_md': md, 'hints': s.get('hints', []),
           'scoring': {'rules': s['rules']}, 'test': s['test'], 'reference': ref, 'faults': s.get('faults', []),
           'version': 1}
    for f in out['faults']:
        assert f['comp'] in {c['id'] for c in cell['components']} | names, (s['id'], f)
    return out


def main():
    problems = [m for s in SCENES for m in check_task(s)]
    if problems:
        print('任务书与评分不一致：\n  ' + '\n  '.join(problems))
        raise SystemExit(1)
    for s in SCENES:
        d = build(s)
        with open(os.path.join(HERE, d['id'] + '.json'), 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    print(f'已生成 {len(SCENES)} 个场景')


if __name__ == '__main__':
    main()
