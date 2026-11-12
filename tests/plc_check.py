"""软 PLC 离线测试（不需要启动服务）：python tests/plc_check.py [-v]

覆盖：词法/语法、每条指令、定时器/计数器/沿、CASE/循环、数组、类型检查与中文报错、LD 每种元件、LD 与 ST 等价、
强制、断点/单步、在线下载保留变量、冷启动、看门狗、运行错误、PLCopen 往返、外接驱动（Modbus 服务器/客户端、S7、OPC UA）、
vfactory/control/scenes/*.json 里的参考答案（有就跑）。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import copy
import glob
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from vfactory import plc  # noqa: E402
from vfactory.plc import PlcRuntime, compile_program, plcopen, st  # noqa: E402
from vfactory.plc.compiler import WATCHDOG  # noqa: E402

VERBOSE = '-v' in sys.argv
res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    if VERBOSE or not cond:
        print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300])


IO = [{'name': 'Start', 'dir': 'in', 'addr': '%I0.0'}, {'name': 'Stop', 'dir': 'in', 'addr': '%I0.1'},
      {'name': 'S1', 'dir': 'in', 'addr': '%I0.2'}, {'name': 'Level', 'dir': 'in', 'type': 'INT', 'addr': '%IW2'},
      {'name': 'Motor', 'dir': 'out', 'addr': '%Q0.0'}, {'name': 'Lamp', 'dir': 'out', 'addr': '%Q0.1'},
      {'name': 'Disp', 'dir': 'out', 'type': 'INT', 'addr': '%QW2'}]


def run_st(src, steps=1, inputs=None, io=None, vars_=None, dt=0.02):
    p = PlcRuntime({'lang': 'ST', 'vars': vars_ or [], 'source': src}, io=io if io is not None else IO)
    if not p.last_compile['ok']:
        raise AssertionError(f'编译失败：{p.last_compile["errors"]}')
    for i in range(steps):
        p.scan(inputs(i) if callable(inputs) else (inputs or {}), dt)
    return p


def V(p, name):
    return p.value(name)


def errs(src, io=None, vars_=None, lang='ST'):
    r = plc.compile({'lang': lang, 'vars': vars_ or [], 'source': src}, io if io is not None else IO)
    return r['errors']


# ============================================================ 词法 / 语法
ok('时间常量 T#2s', st.parse_time('T#2s') == 2000)
ok('时间常量 T#1m30s500ms', st.parse_time('T#1m30s500ms') == 90500)
ok('时间常量 TIME#1.5s', st.parse_time('TIME#1.5s') == 1500)
ok('时间常量 t#1h', st.parse_time('t#1h') == 3600000)
ok('时间显示', st.fmt_time(90500) == 'T#1m30s500ms', st.fmt_time(90500))
ok('地址 %I0.0 规范化', st.norm_addr('%I0.0')[0] == '%IX0.0')
ok('地址 %Q1.7', st.norm_addr('%q1.7')[0] == '%QX1.7')
ok('地址 %MW10', st.norm_addr('%MW10')[0] == '%MW10')
ok('地址 %I0.8 非法', st.norm_addr('%I0.8') is None)
toks = st.lex("x := 16#FF + 2#1010 + 8#17 + 1_000 + 1.5E2; (* c *) // d\n /* e */")
vals = [t.v for t in toks if t.k in ('INT', 'REAL')]
ok('进制与实数常量', vals == [255, 10, 15, 1000, 150.0], vals)
p = run_st('Disp := 16#10 + 2#11;')
ok('进制常量计算', V(p, 'Disp') == 19, V(p, 'Disp'))

# ============================================================ 表达式 / 运算
p = run_st('''VAR a,b,c : INT; d : DINT; r : REAL; x,y,z,w : BOOL; END_VAR
a := 32767; a := a + 1;                 (* 溢出回绕 *)
b := -7 / 2; c := -7 MOD 2;
d := 100000 * 3;
r := 7 / 2.0;
x := TRUE AND NOT FALSE; y := TRUE XOR TRUE; z := (3 > 2) OR (1 = 2); w := 5 <> 5;''')
ok('INT 溢出回绕', V(p, 'a') == -32768, V(p, 'a'))
ok('整数除法向零取整', V(p, 'b') == -3, V(p, 'b'))
ok('MOD 符号随被除数', V(p, 'c') == -1, V(p, 'c'))
ok('DINT 乘法', V(p, 'd') == 300000)
ok('REAL 除法', abs(V(p, 'r') - 3.5) < 1e-9)
ok('布尔运算 AND/NOT', V(p, 'x') is True)
ok('XOR', V(p, 'y') is False)
ok('比较 + OR', V(p, 'z') is True)
ok('不等于', V(p, 'w') is False)
p = run_st('''VAR i,j,k,m,n,o,q : INT; r1,r2,r3,r4 : REAL; t1 : TIME; d1 : DINT; w1 : WORD; b1: BOOL; END_VAR
i := ABS(-5); j := MIN(4, 2, 9); k := MAX(4, 2, 9); m := LIMIT(0, 120, 100); n := SEL(TRUE, 1, 2); o := MUX(2, 10, 20, 30);
r1 := SQRT(16.0); r2 := INT_TO_REAL(3) / 2.0; q := REAL_TO_INT(2.5); r3 := EXPT(2.0, 10.0); r4 := 2.0 ** 3.0;
t1 := T#1s + T#500ms; d1 := TIME_TO_DINT(t1); w1 := SHL(WORD#1, 4) OR SHR(16#80, 3); b1 := INT_TO_BOOL(5);''')
ok('ABS', V(p, 'i') == 5)
ok('MIN 多参数', V(p, 'j') == 2)
ok('MAX 多参数', V(p, 'k') == 9)
ok('LIMIT', V(p, 'm') == 100)
ok('SEL', V(p, 'n') == 2)
ok('MUX', V(p, 'o') == 30)
ok('SQRT', V(p, 'r1') == 4.0)
ok('INT_TO_REAL', V(p, 'r2') == 1.5)
ok('REAL_TO_INT 四舍五入', V(p, 'q') == 3, V(p, 'q'))
ok('EXPT', V(p, 'r3') == 1024.0)
ok('** 乘方', V(p, 'r4') == 8.0)
ok('TIME 加法', V(p, 't1') == 1500)
ok('TIME_TO_DINT', V(p, 'd1') == 1500)
ok('SHL/SHR', V(p, 'w1') == 16 | 16, V(p, 'w1'))
ok('INT_TO_BOOL', V(p, 'b1') is True)
p = run_st('''VAR w: WORD := 16#00F0; b3, b4: BOOL; r: WORD; END_VAR
b3 := w.4; b4 := w.0; w.0 := TRUE; r := ROL(WORD#16#8001, 1);''')
ok('取位 w.4', V(p, 'b3') is True)
ok('取位 w.0', V(p, 'b4') is False)
ok('位赋值 w.0 := TRUE', V(p, 'w') == 0xF1)
ok('ROL', V(p, 'r') == 0x0003, V(p, 'r'))

# ============================================================ 控制结构
p = run_st('''VAR i, s, n, k, sel, out1 : INT; arr : ARRAY[1..5] OF INT := [5, 4, 3]; END_VAR
s := 0;
FOR i := 1 TO 10 DO
  IF i = 3 THEN CONTINUE; END_IF;
  IF i > 6 THEN EXIT; END_IF;
  s := s + i;
END_FOR;
n := 0;
FOR i := 10 TO 1 BY -3 DO n := n + 1; END_FOR;
k := 0;
WHILE k < 5 DO k := k + 2; END_WHILE;
REPEAT k := k + 10; UNTIL k > 30 END_REPEAT;
sel := 7;
CASE sel OF
  1, 2: out1 := 1;
  3..8: out1 := 2;
ELSE out1 := 3;
END_CASE;
arr[5] := arr[1] + arr[2];''')
ok('FOR + CONTINUE + EXIT', V(p, 's') == 1 + 2 + 4 + 5 + 6, V(p, 's'))
ok('FOR BY -3', V(p, 'n') == 4, V(p, 'n'))
ok('WHILE + REPEAT', V(p, 'k') == 36, V(p, 'k'))
ok('CASE 范围分支', V(p, 'out1') == 2)
ok('数组初值与下标', V(p, 'arr') == [5, 4, 3, 0, 9], V(p, 'arr'))
p = run_st('VAR x: INT; END_VAR\nCASE x OF 1: Disp := 1; ELSE Disp := 99; END_CASE;')
ok('CASE ELSE', V(p, 'Disp') == 99)
p = run_st('VAR x: INT; END_VAR\nx := 1; IF x = 1 THEN RETURN; END_IF; x := 2;')
ok('RETURN 结束扫描', V(p, 'x') == 1)
p = run_st('IF Level > 100 THEN Lamp := TRUE; ELSIF Level > 50 THEN Disp := 50; ELSE Disp := 0; END_IF;', inputs={'Level': 70})
ok('ELSIF + 模拟量输入', V(p, 'Disp') == 50 and not V(p, 'Lamp'))
p = run_st('VAR CONSTANT N : INT := 3; END_VAR\nVAR a : ARRAY[0..N] OF INT; END_VAR\nCASE 2 OF N: Disp := 1; 2: Disp := 2; END_CASE;') if False else None
p = run_st('VAR CONSTANT N : INT := 3; END_VAR\nVAR q : INT := N * 2; END_VAR\nCASE 3 OF N: Disp := q; END_CASE;')
ok('常量初值与 CASE 常量标签', V(p, 'Disp') == 6, V(p, 'Disp'))

# ============================================================ 功能块：定时器
def timer_trace(fb, pattern, pt='T#100ms', n=None):
    p = PlcRuntime({'lang': 'ST', 'source': f'VAR T : {fb}; END_VAR\nT(IN := Start, PT := {pt});\nMotor := T.Q;\nDisp := TIME_TO_INT(T.ET);'}, io=IO)
    out, ets = [], []
    for v in pattern:
        o = p.scan({'Start': bool(v)}, 0.02)
        out.append(int(o['Motor']))
        ets.append(o['Disp'])
    return out, ets


q, et = timer_trace('TON', [1] * 8 + [0] * 2)
ok('TON：100ms = 5 个 20ms 扫描后接通', q == [0, 0, 0, 0, 0, 1, 1, 1, 0, 0], q)
ok('TON：ET 计时并封顶', et[:7] == [0, 20, 40, 60, 80, 100, 100] and et[8] == 0, et)
q, et = timer_trace('TON', [1, 1, 0, 1, 1, 1, 1, 1, 1])
ok('TON：中途断开重新计时', q == [0, 0, 0, 0, 0, 0, 0, 0, 1], q)
q, et = timer_trace('TOF', [1, 1, 0, 0, 0, 0, 0, 0, 0])
ok('TOF：断开后延时 100ms 才断', q == [1, 1, 1, 1, 1, 1, 1, 0, 0], q)
q, et = timer_trace('TOF', [1, 0, 0, 1, 0, 0, 0, 0, 0, 0])
ok('TOF：延时中重新接通', q == [1, 1, 1, 1, 1, 1, 1, 1, 1, 0], q)
q, et = timer_trace('TP', [1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
ok('TP：固定宽度脉冲（输入变短也不影响）', q == [1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 0], q)
q, et = timer_trace('TP', [1, 1, 1, 1, 1, 1, 1, 0, 1])
ok('TP：脉冲结束后要重新上升沿才触发', q == [1, 1, 1, 1, 1, 0, 0, 0, 1], q)
q, et = timer_trace('TON', [1, 1, 1], pt='T#0ms')
ok('TON：PT=0 立刻接通', q == [1, 1, 1], q)
# 大 dt
p = PlcRuntime({'lang': 'ST', 'source': 'VAR T: TON; END_VAR\nT(IN:=Start, PT:=T#2s);\nMotor := T.Q;'}, io=IO)
o = [p.scan({'Start': True}, 0.5)['Motor'] for _ in range(6)]
ok('TON：按 dt 计时（0.5s 步长，2s 后接通）', o == [False, False, False, False, True, True], o)

# ============================================================ 计数器 / 沿 / 触发器
p = PlcRuntime({'lang': 'ST', 'source': '''VAR C: CTU; D: CTD; UD: CTUD; R: R_TRIG; F: F_TRIG; s: SR; rs: RS; nR, nF : INT; END_VAR
C(CU := S1, R := Stop, PV := 3);
D(CD := S1, LD := Stop, PV := 2);
UD(CU := S1, CD := Start, R := FALSE, LD := FALSE, PV := 2);
R(CLK := S1); IF R.Q THEN nR := nR + 1; END_IF;
F(CLK := S1); IF F.Q THEN nF := nF + 1; END_IF;
s(S1 := Start, R := Stop); rs(S := Start, R1 := Stop);
Motor := C.Q; Lamp := D.Q;'''}, io=IO)
seq = [dict(S1=b) for b in [1, 0, 1, 1, 0, 1, 0]]
for x in seq:
    p.scan(x)
ok('CTU 上升沿计数', p.value('C.CV') == 3 and p.value('C.Q') is True, p.value('C.CV'))
ok('CTD 减计数到 0 以下', p.value('D.CV') == -3 and p.value('D.Q') is True, p.value('D.CV'))
ok('R_TRIG 次数', p.value('nR') == 3, p.value('nR'))
ok('F_TRIG 次数（无首次误触发）', p.value('nF') == 3, p.value('nF'))
p.scan({'Stop': True})
ok('CTU 复位', p.value('C.CV') == 0 and p.value('C.Q') is False)
ok('CTD 装载 PV', p.value('D.CV') == 2)
p.scan({'Stop': False, 'Start': True})
ok('CTUD 加计数后减计数', p.value('UD.CV') == 3 - 1, p.value('UD.CV'))
ok('SR 置位', p.value('s.Q1') is True)
ok('RS 置位', p.value('rs.Q1') is True)
p.scan({'Start': True, 'Stop': True})
ok('SR 置位优先', p.value('s.Q1') is True)
ok('RS 复位优先', p.value('rs.Q1') is False)
p.scan({'Start': False, 'Stop': False})
ok('SR 保持', p.value('s.Q1') is True)
p = PlcRuntime({'lang': 'ST', 'source': 'VAR C: CTU; END_VAR\nC.PV := 5;\nC(CU := S1);\nMotor := C.Q;'}, io=IO)
for b in [1, 0, 1, 0, 1, 0]:
    p.scan({'S1': bool(b)})
ok('功能块输入可直接赋值（C.PV := 5）', p.value('C.CV') == 3 and p.value('Motor') is False)
p = run_st('VAR T1: TON; e AT %MD4 : TIME; END_VAR\nT1(IN := TRUE, PT := T#40ms, Q => Lamp, ET => e);', steps=3, io=IO)
ok('功能块输出 => 写到变量/地址', p.value('Lamp') is True and p.value('%MD4') == 40, (p.value('Lamp'), p.value('%MD4')))

# ============================================================ 直接地址
p = run_st('%QX0.0 := %IX0.0 AND NOT %I0.1; %MW10 := %MW10 + 1; %MX1.0 := %MW10 > 1;', steps=2, inputs={'Start': True})
ok('直接地址读写（%I/%Q/%M）', p.value('Motor') is True and p.value('%MW10') == 2 and p.value('%MX1.0') is True)
p = PlcRuntime({'lang': 'ST', 'vars': [{'name': 'Btn', 'type': 'BOOL', 'addr': '%I0.0'}], 'source': 'Motor := Btn;'}, io=IO)
p.scan({'Start': True})
ok('变量表 AT 地址与 I/O 同地址别名', p.value('Motor') is True)

# ============================================================ 编译错误（中文 + 行列）
e = errs('Motor := Start\nLamp := TRUE;')
ok('缺分号报在上一行行尾', e and e[0]['line'] == 1 and '分号' in e[0]['msg'], e)
e = errs('IF Start THEN\n  Motor := TRUE;\n')
ok('IF 缺 END_IF', e and 'END_IF' in e[0]['msg'], e)
e = errs('Motr := TRUE;')
ok('未声明变量给出相近建议', e and '没有声明变量 Motr' in e[0]['msg'] and 'Motor' in e[0]['msg'], e)
e = errs('VAR i: INT; END_VAR\ni := 1.5;')
ok('REAL → INT 报错并提示转换函数', e and 'REAL_TO_INT' in e[0]['msg'] and e[0]['line'] == 2, e)
e = errs('VAR i: INT; END_VAR\nMotor := i;')
ok('INT → BOOL 报错', e and '不能把 INT 赋给 BOOL' in e[0]['msg'], e)
e = errs('VAR T1: TON; END_VAR\nT1(IN := Start, PT := 5);')
ok('PT 给整数报错（时间格式）', e and 'T#' in e[0]['msg'], e)
e = errs('VAR T1: TON; END_VAR\nT1(IN := Start, PX := T#1s);')
ok('功能块参数名错误', e and '没有输入参数 PX' in e[0]['msg'], e)
e = errs('VAR T1: TON; END_VAR\nT1.Q := TRUE;')
ok('写功能块输出报错', e and '只能读' in e[0]['msg'], e)
e = errs('VAR x : BOOLL; END_VAR')
ok('类型拼错给建议', e and 'BOOL' in e[0]['msg'], e)
e = errs('Motor = TRUE;')
ok('= 当赋值给提示', e and ':=' in e[0]['msg'], e)
e = errs('VAR x: INT; END_VAR\nx := 1;\nEXIT;')
ok('循环外 EXIT', e and 'EXIT' in e[0]['msg'] and e[0]['line'] == 3, e)
e = errs('VAR x: INT; x: BOOL; END_VAR')
ok('重复声明', e and '重复声明' in e[0]['msg'], e)
e = errs('(* 没结束的注释\nMotor := TRUE;')
ok('注释没结束', e and '注释' in e[0]['msg'], e)
e = errs('VAR x: INT; END_VAR\nx := x + ;')
ok('表达式不完整', e and e[0]['line'] == 2, e)
e = errs('Motor := Start;\nLamp := Stop + 1;\nDisp := TRUE;')
ok('多个错误一次报出', len(e) == 2 and e[0]['line'] == 2 and e[1]['line'] == 3, e)
e = errs('Disp := T#1s;')
ok('TIME → INT 报错', e and 'TIME_TO_DINT' in e[0]['msg'], e)
e = errs('IF Disp THEN Motor := TRUE; END_IF;')
ok('IF 条件类型', e and '布尔' in e[0]['msg'], e)
e = errs('', vars_=[{'name': '1abc', 'type': 'BOOL'}])
ok('变量表非法名称', e and e[0].get('var') == '1abc', e)
e = errs('', vars_=[{'name': 'x', 'type': 'INT', 'addr': '%MX0.0'}])
ok('位地址放 INT 报错', e and '位地址' in e[0]['msg'], e)
r = plc.compile({'lang': 'ST', 'source': 'VAR i: INT; d: DINT; END_VAR\ni := d;'}, IO)
ok('DINT → INT 只警告', r['ok'] and r['warnings'] and '溢出' in r['warnings'][0]['msg'], r)
r = plc.compile({'lang': 'ST', 'source': 'Start := TRUE;'}, IO)
ok('给输入赋值警告', r['ok'] and r['warnings'], r['warnings'])

# ============================================================ 运行错误 / 看门狗
p = run_st('VAR z: INT; END_VAR\nDisp := 10 / z;\nMotor := TRUE;')
ok('除数为零 → 错误状态', p.state == 'ERROR' and '除数为零' in p.error['msg'] and p.error['line'] == 2, p.error)
ok('错误状态输出为 0', p.outputs['Motor'] is False)
ok('错误状态不能单步', p.step() != '')
p.stop()
ok('停止后清除错误可再运行（仍会报错）', p.run() == '' and p.state == 'RUN')
p = run_st('VAR a: ARRAY[0..3] OF INT; i: INT := 7; END_VAR\na[i] := 1;')
ok('数组越界', p.state == 'ERROR' and '越界' in p.error['msg'], p.error)
t0 = time.perf_counter()
p = run_st('VAR i: INT; END_VAR\nWHILE TRUE DO i := i + 1; END_WHILE;')
ok('死循环被看门狗截住', p.state == 'ERROR' and '看门狗' in p.error['msg'], p.error)
ok('看门狗耗时可控', time.perf_counter() - t0 < 5, time.perf_counter() - t0)

# ============================================================ LD 梯形图
def LD(rungs, vars_=None):
    return {'lang': 'LD', 'vars': vars_ or [], 'source': {'rungs': rungs}}


SELF_HOLD = [{'comment': '启停自锁', 'elements': [
    {'par': [[{'id': 'k1', 't': 'NO', 'var': 'Start'}], [{'id': 'k2', 't': 'NO', 'var': 'Motor'}]]},
    {'id': 'k3', 't': 'NC', 'var': 'Stop'}, {'id': 'y1', 't': 'COIL', 'var': 'Motor'}]}]
p = PlcRuntime(LD(SELF_HOLD), io=IO)
ok('LD 编译', p.last_compile['ok'], p.last_compile['errors'])
o = [p.scan({'Start': a, 'Stop': b})['Motor'] for a, b in [(0, 0), (1, 0), (0, 0), (0, 1), (0, 0)]]
ok('LD 启停自锁', o == [False, True, True, False, False], o)
p.scan({'Start': True})
p.scan({'Start': True})
on = p.online()
ok('LD 在线：触点通断 [左, 右, 闭合]', on['ld']['k1'] == [True, True, True] and on['ld']['k2'] == [True, True, True], on['ld'])
ok('LD 在线：常闭触点闭合', on['ld']['k3'] == [True, True, True])
ok('LD 在线：线圈得电 + 梯级能流', on['ld']['y1'][0] is True and on['rungs'] == [True])
p.scan({'Start': False, 'Stop': True})
on = p.online()
ok('LD 在线：常闭触点断开时右侧无电', on['ld']['k3'] == [True, False, False] and on['rungs'] == [False], on['ld'])
p = PlcRuntime(LD([
    {'elements': [{'t': 'P', 'var': 'S1'}, {'t': 'SET', 'var': 'Lamp'}]},
    {'elements': [{'t': 'N', 'var': 'S1'}, {'t': 'MATH', 'op': 'ADD', 'a': 'Disp', 'b': '1', 'out': 'Disp'}]},
    {'elements': [{'t': 'NO', 'var': 'Stop'}, {'t': 'RESET', 'var': 'Lamp'}]},
    {'elements': [{'t': 'NO', 'var': 'Start'}, {'t': 'NCOIL', 'var': 'Motor'}]},
]), io=IO)
ok('LD 沿/置位/复位/取反线圈/运算编译', p.last_compile['ok'], p.last_compile['errors'])
o = [p.scan({'S1': s, 'Stop': r}) for s, r in [(0, 0), (1, 0), (1, 0), (0, 0), (1, 0), (0, 1), (0, 0)]]
ok('LD 上升沿触点 + 置位', o[1]['Lamp'] and o[2]['Lamp'] and o[3]['Lamp'])
ok('LD 下降沿只触发一次', p.value('Disp') == 2, p.value('Disp'))
ok('LD 复位线圈', not o[5]['Lamp'] and not o[6]['Lamp'])
ok('LD 取反线圈', o[0]['Motor'] is True)
p = PlcRuntime(LD([
    {'comment': '定时', 'elements': [{'t': 'NO', 'var': 'Start'}, {'id': 'tm', 't': 'FB', 'fb': 'TON', 'inst': 'T1', 'in': {'PT': 'T#60ms'}, 'out': {'ET': 'Et'}},
                                       {'t': 'COIL', 'var': 'Motor'}]},
    {'elements': [{'t': 'NO', 'var': 'S1'}, {'t': 'FB', 'fb': 'CTU', 'inst': 'C1', 'in': {'R': 'Stop', 'PV': '3'}}, {'t': 'COIL', 'var': 'Lamp'}]},
    {'elements': [{'t': 'CMP', 'op': 'GE', 'a': 'C1.CV', 'b': '2'}, {'t': 'MOVE', 'in': '77', 'out': '%MW0'}]},
], vars_=[{'name': 'Et', 'type': 'TIME'}]), io=IO)
ok('LD 功能块盒子自动声明实例', p.last_compile['ok'] and any(s['name'] == 'T1' and s['type'] == 'TON' for s in p.last_compile['symbols']), p.last_compile['errors'])
o = [p.scan({'Start': True})['Motor'] for _ in range(4)]
ok('LD TON 盒子', o == [False, False, False, True] and p.value('Et') == 60, (o, p.value('Et')))
ok('LD 功能块在线值（ET）', p.online()['vars']['T1']['ET'] == 60)
for b in [1, 0, 1, 0, 1]:
    p.scan({'Start': True, 'S1': bool(b)})
ok('LD CTU 盒子 + 比较 + 传送', p.value('Lamp') is True and p.value('%MW0') == 77, (p.value('C1.CV'), p.value('%MW0')))
e = plc.compile(LD([{'elements': [{'id': 'bad', 't': 'NO', 'var': 'Lvl'}, {'t': 'COIL', 'var': 'Motor'}]}]), IO)['errors']
ok('LD 错误带梯级和元件', e and e[0]['rung'] == 0 and e[0]['elem'] == 'bad' and 'Lvl' in e[0]['msg'], e)
e = plc.compile(LD([{'elements': [{'t': 'NO', 'var': 'Level'}, {'t': 'COIL', 'var': 'Motor'}]}]), IO)['errors']
ok('LD 触点用数值变量报错', e and '布尔' in e[0]['msg'], e)
e = plc.compile(LD([{'elements': [{'t': 'NO', 'var': 'Start'}, {'t': 'FB', 'fb': 'TON', 'inst': 'T1', 'in': {'PT': '5'}}]}]), IO)['errors']
ok('LD 定时器 PT 写成整数报错', e and e[0]['rung'] == 0, e)
r = plc.compile(LD([{'elements': [{'t': 'NO', 'var': 'Start'}]}]), IO)
ok('LD 没有线圈的梯级给警告', r['ok'] and r['warnings'], r['warnings'])

# ============================================================ LD 与 ST 等价
ST_EQ = '''VAR T1: TON; C1: CTU; R1: R_TRIG; END_VAR
Motor := (Start OR Motor) AND NOT Stop;
T1(IN := Motor, PT := T#100ms);
R1(CLK := S1);
C1(CU := R1.Q AND Motor, R := Stop, PV := 4);
Lamp := T1.Q AND NOT C1.Q;
IF C1.CV >= 2 THEN Disp := C1.CV * 10; END_IF;'''
LD_EQ = LD([
    {'elements': [{'par': [[{'t': 'NO', 'var': 'Start'}], [{'t': 'NO', 'var': 'Motor'}]]}, {'t': 'NC', 'var': 'Stop'}, {'t': 'COIL', 'var': 'Motor'}]},
    {'elements': [{'t': 'NO', 'var': 'Motor'}, {'t': 'FB', 'fb': 'TON', 'inst': 'T1', 'in': {'PT': 'T#100ms'}}]},
    {'elements': [{'t': 'P', 'var': 'S1'}, {'t': 'NO', 'var': 'Motor'}, {'t': 'FB', 'fb': 'CTU', 'inst': 'C1', 'in': {'R': 'Stop', 'PV': '4'}}]},
    {'elements': [{'t': 'NO', 'var': 'T1.Q'}, {'t': 'NC', 'var': 'C1.Q'}, {'t': 'COIL', 'var': 'Lamp'}]},
    {'elements': [{'t': 'CMP', 'op': '>=', 'a': 'C1.CV', 'b': '2'}, {'t': 'MATH', 'op': 'MUL', 'a': 'C1.CV', 'b': '10', 'out': 'Disp'}]},
])
a = PlcRuntime({'lang': 'ST', 'source': ST_EQ}, io=IO)
b = PlcRuntime(LD_EQ, io=IO)
rng = random.Random(7)
same, n = True, 0
for i in range(3000):
    x = {'Start': rng.random() < 0.08, 'Stop': rng.random() < 0.02, 'S1': rng.random() < 0.3}
    oa, ob = a.scan(x), b.scan(x)
    if oa != ob:
        same = False
        break
    n += oa['Lamp'] + (oa['Disp'] > 0)
ok('LD 与 ST 同一逻辑 3000 个随机扫描输出完全一致', same and n > 50, (i, n))

# ============================================================ 强制
p = PlcRuntime(LD(SELF_HOLD), io=IO)
p.force('Start', True)
o = p.scan({'Start': False})
ok('强制输入 TRUE 覆盖现场信号', o['Motor'] is True)
p.force('Start', None)
p.force('Stop', True)
o = p.scan({'Start': False})
ok('强制停止', o['Motor'] is False)
p.force('Stop', None)
p.force('%QX0.0', True)
o = p.scan({})
ok('按地址强制输出', o['Motor'] is True and p.online()['forced'].get('Motor') is True, p.online()['forced'])
io_row = next(r for r in p.online()['io'] if r['name'] == 'Motor')
ok('I/O 监视表标出强制', io_row['forced'] is True)
p.unforce_all()
o = p.scan({})
ok('取消全部强制', o['Motor'] is False and not p.online()['forced'])
p = run_st('VAR cnt: INT; END_VAR\ncnt := cnt + 1;\nDisp := cnt;', steps=1)
p.force('cnt', 100)
p.scan({})
ok('强制中间变量（扫描开始和结束都按强制值）', p.value('cnt') == 100 and p.value('Disp') == 101, (p.value('cnt'), p.value('Disp')))
p.force('cnt', None)
p.write('cnt', 5)
p.scan({})
ok('写一次（不强制）', p.value('cnt') == 6)
p = PlcRuntime({'lang': 'ST', 'source': 'VAR T1: TON; END_VAR\nT1(IN:=TRUE, PT:=T#10s);\nMotor := T1.Q;'}, io=IO)
ok('功能块成员不能强制（会被功能块覆盖），给出提示', '功能块' in p.force('T1.Q', True))
ok('功能块输入可以在线写入', p.write('T1.PT', 'T#1s') == '' and p.value('T1.PT') == 1000)
ok('强制错误名称报错', p.force('NoSuch', 1) != '')
ok('强制类型错误', p.force('Start', 'abc') != '')

# ============================================================ 断点 / 单步
p = PlcRuntime({'lang': 'ST', 'source': 'VAR a, b, c: INT; END_VAR\na := a + 1;\nb := b + 1;\n\nc := c + 1;\nMotor := TRUE;'}, io=IO)
ok('可停的行', p.prog.lines == [2, 3, 5, 6], p.prog.lines)
ok('断点设在空行挪到下一条语句', p.set_breakpoint(4) == 5)
o = p.scan({})
on = p.online()
ok('断点命中：暂停在第 5 行', p.state == 'HALT' and on['halt']['line'] == 5 and on['halt']['mid_scan'], on.get('halt'))
ok('断点前的语句已执行、后面的没执行', p.value('a') == 1 and p.value('b') == 1 and p.value('c') == 0)
ok('暂停时输出保持（还没写出）', o['Motor'] is False)
o = p.scan({})
ok('暂停时扫描不推进', p.value('c') == 0)
p.step('stmt')
ok('单步语句：执行第 5 行停在第 6 行', p.value('c') == 1 and p.online()['halt']['line'] == 6, p.online().get('halt'))
p.step('stmt')
ok('单步执行到扫描结束', p.online()['halt']['mid_scan'] is False and p.outputs['Motor'] is True)
p.run()
p.scan({})
ok('继续运行再次命中断点', p.state == 'HALT' and p.value('a') == 2)
p.set_breakpoint(5, False)
p.run()
ok('删除断点后继续运行', p.state == 'RUN' and p.value('c') == 2)
p.stop()
p.step('scan')
ok('单步一个扫描周期', p.state == 'HALT' and p.value('a') == 3 and p.value('c') == 3)
p.step('scan')
ok('再单步一个周期', p.value('a') == 4)
p.stop()
ok('停止时输出为 0', p.outputs['Motor'] is False)
p = PlcRuntime(LD(SELF_HOLD + [{'elements': [{'t': 'NO', 'var': 'Motor'}, {'t': 'COIL', 'var': 'Lamp'}]}]), io=IO)
p.set_breakpoint(2)                        # 梯级 1（第 2 个梯级）
p.scan({'Start': True})
on = p.online()
ok('LD 梯级断点', p.state == 'HALT' and on['halt']['rung'] == 1 and p.value('Motor') is True and p.value('Lamp') is False, on.get('halt'))
p.run()
ok('LD 继续', p.value('Lamp') is True and p.state == 'RUN')

# ============================================================ 在线下载（保留变量）/ 冷启动
v1 = {'lang': 'ST', 'source': 'VAR C1: CTU; total: INT; RETAIN_x: INT; END_VAR\nC1(CU := S1, PV := 100);\ntotal := total + 1;'}
p = PlcRuntime(v1, io=IO)
for b in [1, 0, 1, 0, 1, 0]:
    p.scan({'S1': bool(b)})
ok('下载前计数 3', p.value('C1.CV') == 3 and p.value('total') == 6)
v2 = {'lang': 'ST', 'source': 'VAR C1: CTU; total: DINT; extra: INT := 9; END_VAR\nC1(CU := S1, PV := 100);\ntotal := total + 1;\nDisp := C1.CV;'}
r = p.load(v2)
ok('在线下载保留同名同类型变量', r['ok'] and p.value('C1.CV') == 3 and 'C1' in r['kept'], r.get('kept'))
ok('类型改变的变量重新初始化', p.value('total') == 0)
ok('新变量用初值', p.value('extra') == 9)
ok('下载后保持运行', p.state == 'RUN')
p.scan({'S1': True})
ok('下载后继续计数', p.value('C1.CV') == 4 and p.outputs['Disp'] == 4)
r = p.load(v2, cold=True)
ok('冷启动全部回到初值', p.value('C1.CV') == 0 and r['cold'])
bad = p.load({'lang': 'ST', 'source': 'Motor := ;'})
ok('编译失败不影响运行中的程序', not bad['ok'] and p.prog.hash == r['hash'] and p.state == 'RUN')
p = PlcRuntime({'lang': 'ST', 'source': 'VAR RETAIN keep: INT; END_VAR\nVAR temp: INT; END_VAR\nkeep := keep + 1; temp := temp + 1;'}, io=IO)
p.scan({})
p.scan({})
p.reset(cold=False)
ok('暖复位保留 RETAIN 变量', p.value('keep') == 2 and p.value('temp') == 0)
p.reset(cold=True)
ok('冷复位清零 RETAIN', p.value('keep') == 0)
p = PlcRuntime(LD(SELF_HOLD), io=IO)
p.scan({'Start': True})
p.scan({'Start': False})
r = p.load(LD(SELF_HOLD + [{'elements': [{'t': 'NO', 'var': 'Motor'}, {'t': 'COIL', 'var': 'Lamp'}]}]))
o = p.scan({})
ok('LD 运行中下载：自锁状态保持', o['Motor'] is True and o['Lamp'] is True, o)
pc = copy.deepcopy(p)
pc.scan({'Stop': True})
ok('PLC 可 deepcopy（工厂预热缓存），副本独立', pc.value('Motor') is False and p.value('Motor') is True)

# ============================================================ 4.1：示例数据、手写 YAML 的元素类型
import yaml  # noqa: E402
from vfactory.plc.api import SANDBOX_IO  # noqa: E402
from vfactory.plc.demo import SANDBOX_DEMO_HMI, SANDBOX_DEMO_PROGRAM, auto_screen, cell_screens  # noqa: E402
y = yaml.safe_load('rungs:\n  - elements: [{t: NO, var: Start}, {t: NC, var: Stop}, {t: COIL, var: Motor}]\n')
ok('手写 YAML 里的 NO 被读成 False', y['rungs'][0]['elements'][0]['t'] is False)
p = PlcRuntime({'lang': 'LD', 'source': y}, io=IO)
ok('t=False 按常开触点编译', p.last_compile['ok'] and p.scan({'Start': True})['Motor'] is True, p.last_compile['errors'])
p = PlcRuntime({'lang': 'LD', 'source': {'rungs': [{'elements': [{'t': 'contact', 'var': 'Start'}, {'t': 'falling', 'var': 'S1'}, {'t': 'coil', 'var': 'Lamp'}]}]}}, io=IO)
ok('元素类型别名（contact/falling/coil，大小写不限）', p.last_compile['ok'], p.last_compile['errors'])
p = PlcRuntime(SANDBOX_DEMO_PROGRAM, io=SANDBOX_IO)
ok('练习 PLC 示范程序能编译', p.last_compile['ok'] and not p.last_compile['warnings'], p.last_compile)
o = [p.scan({'Start': s_, 'Stop': False, 'Level': 10}, 0.02)['Motor'] for s_ in (True, False, False)]
for _ in range(160):
    o2 = p.scan({'Start': False, 'Stop': False, 'Level': 10}, 0.02)
ok('示范程序：启停自锁、3 秒开阀', o == [True, True, True] and o2['Valve'] is True and o2['Lamp_Run'] is True, (o, o2))
for b in (True, False, True, False):
    o2 = p.scan({'Sensor1': b, 'Level': 10}, 0.02)
ok('示范程序：光电计件显示', o2['Display'] == 2, o2)
o2 = p.scan({'Level': 90}, 0.02)
o3 = p.scan({'Level': 90}, 0.02)
ok('示范程序：液位超限报警并停机', o3['Lamp_Fault'] is True and o3['Motor'] is False, o3)
names = {e['name'] for e in SANDBOX_IO}
bad = [w for w in SANDBOX_DEMO_HMI['widgets'] if w.get('var') and w['var'].split('.')[0] not in names | {'T1'}]
ok('示范画面绑定的变量都存在', not bad, bad)
a = auto_screen('CELL9', '测试单元', [{'name': 'B1', 'dir': 'in'}, {'name': 'H1', 'dir': 'in', 'type': 'INT'}, {'name': 'LP', 'dir': 'out'}])
ok('自动生成操作面板：输入按钮、数值、输出灯', [w['type'] for w in a['widgets'] if w.get('var')] == ['button', 'number', 'lamp'] and a['cell'] == 'CELL9', a)
c = cell_screens('C1', {'hmi': [{'name': 'x', 'widgets': []}, {'id': 'bad id!', 'widgets': []}]})
ok('单元定义里的画面：补编号、编号规整', [x['id'] for x in c] == ['C1_hmi1', 'bad_id_'] and all(x['source'] == 'model' and x['cell'] == 'C1' for x in c), c)

# ============================================================ S28：词法/语法对任何输入都不崩溃（模糊测试）
e = errs('(* 识别是绿(*teacher*)色 *)\nMotor := TRUE;')
ok('S28 嵌套注释 (* … (* … *) … *) 正常编译', e == [], e)
e = errs('(* 外 (* 内 *)\nMotor := TRUE;')
ok('S28 嵌套注释没关完：中文错误带行号', e and '注释没有结束' in e[0]['msg'] and e[0]['line'] == 1, e)
e = errs('Motor := TRUE；')
ok('全角分号给出中文提示', e and '全角' in e[0]['msg'], e)
e = errs('Motor := 2#102 > 1;')
ok('进制常量里的非法数字', e and '进制' in e[0]['msg'], e)
e = errs('Motor := ' + '(' * 3000 + 'TRUE' + ')' * 3000 + ';')
ok('括号嵌套 3000 层不崩溃', isinstance(e, list) and e, e[:1])


def fuzz_ok(src, lang='ST'):
    try:
        r = plc.compile({'lang': lang, 'source': src}, IO)
    except Exception as ex:          # noqa: BLE001
        return f'{type(ex).__name__}: {ex}'
    if not isinstance(r, dict) or 'errors' not in r:
        return '返回格式不对'
    for er in r['errors']:
        if not isinstance(er.get('msg'), str) or not any(ord(ch) > 127 for ch in er['msg']):
            return '错误信息不是中文：' + str(er)
        if '编译器没能处理' in er['msg'] or '无法识别的内容（' in er['msg']:
            return '走到了兜底（应该给出具体的错误）：' + str(er)
    return ''


rng = random.Random(28)
ALPHA = list('abcxyzABCXYZ_0123456789 \t\n;:=()[]{}*/+-<>.,#%\'"&^!?@$~`|') + [
    '(*', '*)', '/*', '*/', '//', ':=', '=>', 'T#', '16#', '2#', '%IX', '%QW', 'IF ', 'THEN ', 'END_IF', 'FOR ', 'CASE ', 'OF ', 'VAR ', 'END_VAR',
    'TON', '颜', '色', '；', '（', '）', '：', 'é', ' ', '\x00', '﻿', '\U0001F600']
bad = []
for i in range(3000):
    src = ''.join(rng.choice(ALPHA) for _ in range(rng.randint(0, 60)))
    m = fuzz_ok(src)
    if m:
        bad.append((src, m))
        if len(bad) > 3:
            break
ok('模糊测试：3000 段随机字符都只返回中文编译错误', not bad, bad[:2])
base = [ST_EQ, 'PROGRAM Main\nVAR\n  T1 : TON; (* 定时 *)\n  a : ARRAY[0..3] OF INT;\nEND_VAR\nT1(IN := Start, PT := T#2s);\n'
               'CASE a[1] OF 1..3: Motor := T1.Q; ELSE Lamp := TRUE; END_CASE;\nEND_PROGRAM\n']
for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vfactory', 'control', 'scenes', '*.json')))[:15]:
    try:
        base.append(json.load(open(f, encoding='utf-8'))['reference']['st']['source'])
    except (ValueError, KeyError, TypeError):
        pass
bad = []
for i in range(2500):
    src = rng.choice(base)
    for _ in range(rng.randint(1, 4)):
        k = rng.randint(0, max(0, len(src) - 1))
        op = rng.random()
        if op < .4:
            src = src[:k] + src[k + rng.randint(1, 12):]
        elif op < .8:
            src = src[:k] + rng.choice(ALPHA) + src[k:]
        else:
            j = rng.randint(0, len(src))
            src = src[:k] + src[j:j + 40] + src[k:]
    m = fuzz_ok(src)
    if m:
        bad.append((src[:200], m))
        if len(bad) > 3:
            break
ok(f'模糊测试：2500 个改坏的真实程序（{len(base)} 个底本）都只返回中文编译错误', not bad, bad[:2])
bad = []
LD_ATOMS = [None, 1, 'x', [], {}, {'t': 'NO'}, {'t': 'NO', 'var': 'Start'}, {'t': 'COIL', 'var': 'Motor'}, {'par': 'x'}, {'par': [[], [None]]}, {'ser': 5},
            {'t': 'FB', 'fb': 'TON'}, {'t': 'FB', 'fb': 'XX', 'inst': '1a'}, {'t': 'CMP', 'op': '??'}, {'t': 'MATH', 'op': 'ADD', 'a': '(', 'b': '1', 'out': '2'},
            {'t': False, 'var': '颜色'}, {'t': 'MOVE', 'in': {'a': 1}, 'out': []}]


def tree(d=0):
    x = rng.choice(LD_ATOMS)
    if d < 3 and rng.random() < .3:
        return {'par': [[tree(d + 1) for _ in range(rng.randint(0, 3))] for _ in range(rng.randint(0, 3))]}
    return json.loads(json.dumps(x))


for i in range(1500):
    src = rng.choice([{'rungs': [{'elements': [tree() for _ in range(rng.randint(0, 5))]} for _ in range(rng.randint(0, 3))]}, {'rungs': 'x'},
                      {'rungs': [None, 1]}, [], 'not json', {'rungs': [{'elements': 'x'}]}])
    m = fuzz_ok(src, 'LD')
    if m:
        bad.append((json.dumps(src, ensure_ascii=False)[:200], m))
        if len(bad) > 3:
            break
ok('模糊测试：1500 个乱写的梯形图 JSON 都只返回中文编译错误', not bad, bad[:2])

# ============================================================ 审计修复：交叉引用、双线圈、时序记录、状态文字、超周期
r = plc.compile(LD([{'elements': [{'id': 'a', 't': 'NO', 'var': 'Start'}, {'id': 'b', 't': 'COIL', 'var': 'Motor'}]},
                    {'elements': [{'id': 'c', 't': 'NO', 'var': 'S1'}, {'id': 'd', 't': 'COIL', 'var': 'Motor'}]},
                    {'elements': [{'id': 'e', 't': 'NO', 'var': 'Motor'}, {'id': 'f', 't': 'SET', 'var': 'Lamp'}]},
                    {'elements': [{'id': 'g', 't': 'NO', 'var': 'Stop'}, {'id': 'h', 't': 'RESET', 'var': 'Lamp'}]}]), IO)
xr = r['xref']
ok('交叉引用：Motor 两处写、一处读', [x['rung'] for x in xr['Motor'] if x['k'] == 'W'] == [0, 1] and any(x['k'] == 'R' and x['rung'] == 2 for x in xr['Motor']), xr.get('Motor'))
ok('交叉引用：置位/复位分开记', {x['k'] for x in xr['Lamp']} == {'S', 'RS'}, xr.get('Lamp'))
ok('双线圈警告（梯级 1、2）', any('双线圈' in w['msg'] and 'Motor' in w['msg'] and '1、2' in w['msg'] for w in r['warnings']), r['warnings'])
ok('置位+复位不算双线圈', not any('Lamp' in w['msg'] for w in r['warnings'] if '双线圈' in w['msg']))
r = plc.compile({'lang': 'ST', 'source': 'VAR T1: TON; END_VAR\nT1(IN := Start, PT := T#1s);\nMotor := T1.Q AND NOT Stop;'}, IO)
ok('交叉引用（ST）：行号、功能块调用和成员读取', {'k': 'C', 'line': 2} in r['xref']['T1'] and {'k': 'R', 'line': 3, 'f': 'Q'} in r['xref']['T1']
   and r['xref']['Motor'] == [{'k': 'W', 'line': 3}], r['xref'])
p = PlcRuntime({'lang': 'ST', 'source': 'Motor := Start;'}, io=IO)
for i in range(20):
    p.scan({'Start': i % 10 < 5}, 0.02)
w = p.tracer.window(1)
idx_s, idx_m = w['names'].index('Start'), w['names'].index('Motor')
ok('时序记录：只记变化（20 个周期 4 次变化）', len(w['events']) == 4 and w['events'][1][0] == 120, w['events'])
ok('时序记录：输入、输出都在', w['events'][0][1][idx_s] is True and w['events'][0][1][idx_m] is True)
p.set_breakpoint(1)
p.scan({'Start': True})
ok('状态文字：断点暂停（第 1 行）', p.label() == '断点暂停（第 1 行）' and p.halt_info()['line'] == 1, p.label())
p.run()
ok('状态文字：运行', p.label() == '运行')
q = PlcRuntime(LD([{'elements': [{'t': 'NO', 'var': 'Start'}, {'t': 'COIL', 'var': 'Motor'}]}, {'elements': [{'t': 'NO', 'var': 'S1'}, {'t': 'COIL', 'var': 'Lamp'}]}]), io=IO)
q.set_breakpoint(2)
q.scan({})
ok('状态文字：LD 断点暂停（梯级 2）', q.label() == '断点暂停（梯级 2）' and q.halt_info()['rung'] == 1, q.label())
p = PlcRuntime({'lang': 'ST', 'source': 'VAR i, n: DINT; END_VAR\nFOR i := 1 TO 20000 DO n := n + 1; END_FOR;'}, scan_ms=0.5, io=IO)
for _ in range(5):
    p.scan({})
st_ = p.stats()
ok('超周期：计数并给出比例', st_['over'] == 5 and st_['over_recent'] == 5 and st_['over_pct'] == 100.0, st_)
p.reset_stats()
ok('超周期统计可以清零', p.stats()['over'] == 0 and p.stats()['max_ms'] == 0)

# ============================================================ pickle 往返（推演/快照把整个工厂 pickle）
import pickle  # noqa: E402
for lang, prog in (('ST', {'lang': 'ST', 'source': ST_EQ}), ('LD', LD_EQ)):
    a = PlcRuntime(prog, io=IO)
    rng = random.Random(5)
    seq = [{'Start': rng.random() < 0.1, 'Stop': rng.random() < 0.02, 'S1': rng.random() < 0.3} for _ in range(600)]
    for x in seq[:300]:
        a.scan(x)
    a.force('S1', True)
    a.write('Disp', 7)
    b = pickle.loads(pickle.dumps(a))
    ok(f'pickle 往返（{lang}）：变量、功能块、强制、运行状态都在', b.state == a.state and b.online(ld=False)['vars'] == a.online(ld=False)['vars']
       and b.forces == a.forces and b.prog.hash == a.prog.hash and b.tracer.window(5)['events'] == a.tracer.window(5)['events'])
    same = all(a.scan(x) == b.scan(x) for x in seq[300:])
    ok(f'pickle 往返（{lang}）：之后 300 个扫描输出完全一致（定时器、计数器、沿记忆接着走）', same)
a = PlcRuntime({'lang': 'ST', 'source': 'VAR n: INT; END_VAR\nn := n + 1;\nMotor := TRUE;\nn := n + 10;'}, io=IO)
a.set_breakpoint(3)
a.scan({})
b = pickle.loads(pickle.dumps(a))
ok('pickle 往返：停在断点（扫描中间）的位置也保留', b.state == 'HALT' and b.halt_info() == a.halt_info() and b.value('n') == 1)
b.run()
ok('pickle 往返：从断点继续执行剩下的语句', b.value('n') == 11 and b.outputs['Motor'] is True, b.value('n'))
from vfactory.plc.external import ExternalPlc  # noqa: E402
e = ExternalPlc({'protocol': 'modbus_server', 'port': 1502}, IO)
e.scan({'Start': True})
e.force('Motor', True)
e2 = pickle.loads(pickle.dumps(e))
ok('外接 PLC 代理可以 pickle（不带驱动）', e2.forces == {'Motor': True} and e2.inputs['Start'] is True and e2._drv is None)
c = copy.deepcopy(a)
ok('deepcopy 仍然共享编译结果（预热缓存不重新编译）', c.prog is a.prog and c.mem is not a.mem)

# ============================================================ cycle：按扫描周期累计
p = PlcRuntime({'lang': 'ST', 'source': 'VAR n: INT; END_VAR\nn := n + 1;'}, scan_ms=10, io=IO)
p.cycle({}, 0.05)
p.cycle({}, 0.004)
p.cycle({}, 0.007)
ok('cycle：50ms + 11ms → 6 次扫描', p.value('n') == 6, p.value('n'))

# ============================================================ for_cell / 无 I/O 表
p = plc.for_cell({'io': IO[:2] + IO[4:5], 'plc': {'scan_ms': 10, 'program': LD(SELF_HOLD)}})
ok('for_cell 建内置 PLC 并运行', p.state == 'RUN' and p.scan({'Start': True}, 0.01)['Motor'] is True)
p = plc.for_cell({'io': [], 'plc': {}})
ok('for_cell 没程序 → STOP、输出空', p.state == 'STOP' and p.scan({}) == {})
p = PlcRuntime({'lang': 'ST', 'vars': [{'name': 'Y', 'type': 'BOOL', 'addr': '%QX0.5'}, {'name': 'X', 'type': 'BOOL'}], 'source': 'Y := X;'})
o = p.scan({'X': True})
ok('没有 I/O 表时按变量名输入、按 %Q 输出', o == {'Y': True}, o)

# ============================================================ PLCopen XML
xml = plcopen.export_xml(LD_EQ, IO)
ok('导出 PLCopen XML', xml.startswith('<?xml') and 'tc6_0200' in xml and '<leftPowerRail' in xml and 'typeName="TON"' in xml)
prog, glob_, warn = plcopen.import_xml(xml)
ok('导入（附加数据原样还原）', prog['lang'] == 'LD' and prog['source']['rungs'][0]['elements'][0].keys() == LD_EQ['source']['rungs'][0]['elements'][0].keys())
ok('I/O 导出为全局变量（带地址）', any(g['name'] == 'Start' and g['addr'] == '%I0.0' for g in glob_), glob_)
xml2 = plcopen.export_xml(LD_EQ, IO, vendor_data=False)
prog2, _, warn2 = plcopen.import_xml(xml2)
c2 = compile_program(prog2, IO)
ok('只按 TC6 图形导入能编译', c2.ok, c2.errors)
a, b = PlcRuntime(LD_EQ, io=IO), PlcRuntime(prog2, io=IO)
rng = random.Random(3)
same = True
for i in range(1500):
    x = {'Start': rng.random() < 0.08, 'Stop': rng.random() < 0.02, 'S1': rng.random() < 0.3}
    if a.scan(x) != b.scan(x):
        same = False
        break
ok('图形导入后行为与原程序一致', same, i)
src = 'PROGRAM Main\nVAR\n  T1 : TON; (* 定时 *)\nEND_VAR\nT1(IN := Start, PT := T#2s);\nMotor := T1.Q;\nEND_PROGRAM\n'
xml3 = plcopen.export_xml({'lang': 'ST', 'vars': [{'name': 'k', 'type': 'ARRAY[0..3] OF INT', 'init': '[1, 2]', 'comment': '数组'},
                                                   {'name': 'R', 'type': 'REAL', 'retain': True, 'init': '1.5'}], 'source': src})
p3, _, _ = plcopen.import_xml(xml3)
ok('ST 文本原样往返', p3['source'] == src, repr(p3['source'][:80]))
ok('变量表往返（数组/RETAIN/初值/注释）', p3['vars'][0]['type'] == 'ARRAY[0..3] OF INT' and p3['vars'][0]['comment'] == '数组' and
   any(v.get('retain') and v['init'] == '1.5' for v in p3['vars']), p3['vars'])
CODESYS_LIKE = '''<?xml version="1.0" encoding="utf-8"?>
<project xmlns="http://www.plcopen.org/xml/tc6_0200">
  <fileHeader companyName="x" productName="CODESYS" productVersion="3.5" creationDateTime="2026-01-01T00:00:00"/>
  <contentHeader name="t"><coordinateInfo><fbd><scaling x="1" y="1"/></fbd><ld><scaling x="1" y="1"/></ld><sfc><scaling x="1" y="1"/></sfc></coordinateInfo></contentHeader>
  <types><dataTypes/><pous>
    <pou name="PLC_PRG" pouType="program">
      <interface><localVars><variable name="bRun"><type><BOOL/></type></variable></localVars></interface>
      <body><LD>
        <leftPowerRail localId="1"><position x="0" y="0"/><connectionPointOut formalParameter="none"/></leftPowerRail>
        <comment localId="9" height="10" width="10"><position x="0" y="-20"/><content><xhtml xmlns="http://www.w3.org/1999/xhtml">自锁</xhtml></content></comment>
        <contact localId="2" negated="false"><position x="10" y="0"/><connectionPointIn><connection refLocalId="1"/></connectionPointIn><connectionPointOut/><variable>Start</variable></contact>
        <contact localId="3" negated="false"><position x="10" y="30"/><connectionPointIn><connection refLocalId="1"/></connectionPointIn><connectionPointOut/><variable>bRun</variable></contact>
        <contact localId="4" negated="true"><position x="50" y="0"/><connectionPointIn><connection refLocalId="2"/><connection refLocalId="3"/></connectionPointIn><connectionPointOut/><variable>Stop</variable></contact>
        <coil localId="5" negated="false"><position x="90" y="0"/><connectionPointIn><connection refLocalId="4"/></connectionPointIn><connectionPointOut/><variable>bRun</variable></coil>
        <coil localId="6" negated="false"><position x="90" y="30"/><connectionPointIn><connection refLocalId="4"/></connectionPointIn><connectionPointOut/><variable>Motor</variable></coil>
        <rightPowerRail localId="7"><position x="200" y="0"/><connectionPointIn><connection refLocalId="5"/><connection refLocalId="6"/></connectionPointIn></rightPowerRail>
      </LD></body>
    </pou>
    <pou name="FB_X" pouType="functionBlock"><interface/><body><ST><xhtml xmlns="http://www.w3.org/1999/xhtml"/></ST></body></pou>
  </pous></types>
  <instances><configurations/></instances>
</project>'''
p4, _, w4 = plcopen.import_xml(CODESYS_LIKE)
ok('导入第三方（CODESYS 风格）梯形图：并联输出线圈', len(p4['source']['rungs']) == 1 and p4['source']['rungs'][0]['comment'] == '自锁', json.dumps(p4['source'], ensure_ascii=False)[:300])
ok('忽略不支持的功能块 POU 并提示', any('FB_X' in w for w in w4), w4)
r4 = PlcRuntime(p4, io=IO)
o = [r4.scan({'Start': a, 'Stop': b})['Motor'] for a, b in [(1, 0), (0, 0), (0, 1), (0, 0)]]
ok('第三方梯形图导入后能运行', o == [True, True, False, False], o)
for bad, what in (('<x/>', '根元素'), ('not xml', 'XML'), ('<project xmlns="http://www.plcopen.org/xml/tc6_0200"><types><pous/></types></project>', '没有程序')):
    try:
        plcopen.import_xml(bad)
        ok(f'导入错误：{what}', False)
    except plcopen.ImportError_ as e:
        ok(f'导入错误：{what}', what in str(e), str(e))

# ============================================================ 性能
big = '\n'.join(f'IF %IX{i // 8}.{i % 8} AND NOT %MX{i // 8}.{i % 8} THEN %MW{i * 2} := %MW{i * 2} + 1; END_IF;' for i in range(200))
p = PlcRuntime({'lang': 'ST', 'source': big}, io=[])
t0 = time.perf_counter()
for _ in range(200):
    p.scan({})
per = (time.perf_counter() - t0) / 200 * 1000
ok('性能：200 条 IF 的程序一次扫描 < 3 ms', per < 3, f'{per:.3f} ms')
ok('扫描时间统计', p.stats()['count'] == 200 and p.stats()['avg_ms'] > 0, p.stats())


# ============================================================ 外接驱动
async def ext_tests():
    from vfactory.plc.external import ExternalPlc, default_mapping
    io = [{'name': 'Start', 'dir': 'in', 'addr': '%I0.0'}, {'name': 'Stop', 'dir': 'in', 'addr': '%I0.1'},
          {'name': 'Level', 'dir': 'in', 'type': 'INT', 'addr': '%IW2'}, {'name': 'Motor', 'dir': 'out', 'addr': '%Q0.0'},
          {'name': 'Speed', 'dir': 'out', 'type': 'REAL', 'addr': '%QD4'}]
    mp = default_mapping(io, 'modbus_server')
    ok('默认映射：Modbus 服务器（DI/IR/CO/HR）', [m['addr'] for m in mp] == ['DI0', 'DI1', 'IR0', 'CO0', 'HR0'], mp)
    mp = default_mapping(io, 's7')
    ok('默认映射：S7 按 I/O 地址', [m['addr'] for m in mp] == ['I0.0', 'I0.1', 'IW2', 'Q0.0', 'QD4'], mp)
    # --- Modbus 服务器：外部 PLC 用客户端实现启停自锁
    try:
        from pymodbus.client import AsyncModbusTcpClient
    except ImportError:
        ok('pymodbus 可用（跳过 Modbus 测试）', True)
        return
    port = int(os.environ.get('PLC_TEST_PORT', '6151'))
    ext = ExternalPlc({'protocol': 'modbus_server', 'port': port}, io)
    await ext.start({})
    c = AsyncModbusTcpClient('127.0.0.1', port=port)
    await c.connect()
    ok('Modbus 服务器：外部客户端连上', c.connected)
    hist = []
    for i in range(40):
        start, stop = 5 <= i < 8, 25 <= i < 27
        o = ext.scan({'Start': start, 'Stop': stop, 'Level': 1234 if i > 2 else 0}, 0.02)
        hist.append(o['Motor'])
        di = (await c.read_discrete_inputs(0, count=2)).bits[:2]
        motor = (await c.read_coils(0, count=1)).bits[0]
        run = (di[0] or motor) and not di[1]
        await c.write_coil(0, run)
        rr = await c.write_registers(0, list(__import__('struct').unpack('>HH', __import__('struct').pack('>f', 12.5))))
        await asyncio.sleep(0.005)
    ir = (await c.read_input_registers(0, count=1)).registers[0]
    ext.scan({}, 0.02)
    ok('Modbus 服务器：传感器 → DI，执行器 ← 线圈（外部 PLC 自锁，一个扫描后响应）', not any(hist[:6]) and all(hist[6:26]) and not any(hist[26:]), hist)
    ok('Modbus 服务器：模拟量 IR / 实数 HR', ir == 1234 and abs(ext.outputs['Speed'] - 12.5) < 1e-6, (ir, ext.outputs['Speed']))
    ok('Modbus 服务器：统计客户端', ext.status['peer'] == '1 个客户端', ext.status)
    c.close()
    ext.force('Motor', True)
    ok('外接 PLC 也能强制', ext.scan({}, 0.02)['Motor'] is True and ext.online()['io'][3]['forced'])
    # --- Modbus 客户端：连另一个 Modbus 服务器（外部"软 PLC"）
    port2 = port + 1
    ext2srv = ExternalPlc({'protocol': 'modbus_server', 'port': port2}, [{'name': 'X', 'dir': 'in'}, {'name': 'Y', 'dir': 'out'}])
    await ext2srv.start({})
    cli = ExternalPlc({'protocol': 'modbus', 'endpoint': f'127.0.0.1:{port2}', 'poll_ms': 10,
                       'mapping': [{'name': 'Start', 'addr': 'CO0'}, {'name': 'Level', 'addr': 'HR10'}, {'name': 'Motor', 'addr': 'CO5'}, {'name': 'Speed', 'addr': 'HR20'}]}, io)
    await cli.start({})
    cli.scan({'Start': True, 'Level': -5})
    sl = ext2srv._drv.slave
    sl.setValues(1, 5, [True])
    import struct
    sl.setValues(3, 20, list(struct.unpack('>HH', struct.pack('>f', 3.25))))
    for _ in range(50):
        await asyncio.sleep(0.02)
        if cli.status['polls'] > 3:
            break
    o = cli.scan({'Start': True, 'Level': -5})
    ok('Modbus 客户端：写线圈/寄存器到外部', sl.getValues(1, 0, 1)[0] is True and sl.getValues(3, 10, 1)[0] == 65531, (sl.getValues(1, 0, 1), sl.getValues(3, 10, 1)))
    ok('Modbus 客户端：从外部读执行器', o['Motor'] is True and abs(o['Speed'] - 3.25) < 1e-6 and cli.status['connected'], (o, cli.status))
    await cli.stop()
    await ext.stop()
    await ext2srv.stop()
    bad = ExternalPlc({'protocol': 'modbus', 'endpoint': '127.0.0.1:1', 'poll_ms': 10}, io)
    await bad.start({})
    for _ in range(40):                      # Windows 上连本机关闭的端口要等约 2 秒才报拒绝
        await asyncio.sleep(0.1)
        if bad.status['error']:
            break
    ok('Modbus 客户端：连不上时报告错误、不抛异常', not bad.status['connected'] and bad.status['error'], bad.status)
    await bad.stop()
    # --- S7：对着一个最小的假 S7 服务器
    srv = FakeS7()
    server = await asyncio.start_server(srv.handle, '127.0.0.1', 0)
    sport = server.sockets[0].getsockname()[1]
    s7 = ExternalPlc({'protocol': 's7', 'endpoint': f'127.0.0.1:{sport}', 'rack': 0, 'slot': 1, 'poll_ms': 10,
                      'mapping': [{'name': 'Level', 'addr': 'DB1.DBW2'}]}, io)
    await s7.start({})
    for _ in range(50):
        await asyncio.sleep(0.02)
        if s7.status['polls'] > 2:
            break
    s7.scan({'Start': True, 'Stop': False, 'Level': -300})
    srv.areas[(0x82, 0)][0] = 0b1
    srv.areas[(0x82, 0)][4:8] = bytearray(struct.pack('>f', 7.5))
    await asyncio.sleep(0.15)
    o = s7.scan({'Start': True, 'Stop': False, 'Level': -300})
    ok('S7：连接（COTP + 通讯设置）', s7.status['connected'] and srv.tsap == 0x0101, (s7.status, hex(srv.tsap or 0)))
    ok('S7：写 I 区位、DB 字', srv.areas[(0x81, 0)][0] & 1 == 1 and struct.unpack('>h', bytes(srv.areas[(0x84, 1)][2:4]))[0] == -300,
       (srv.areas[(0x81, 0)][:1], srv.areas[(0x84, 1)][:4]))
    ok('S7：读 Q 区位和实数', o['Motor'] is True and abs(o['Speed'] - 7.5) < 1e-6, o)
    await s7.stop()
    server.close()
    # --- OPC UA：发布到虚拟工厂的服务器 + 客户端模式读写它
    try:
        from asyncua import Client
        from vfactory.protocols.opcua import OpcUaHub
    except ImportError:
        ok('asyncua 可用（跳过 OPC UA 测试）', True)
        return
    hub = OpcUaHub(int(os.environ.get('PLC_TEST_OPCUA', '4869')))
    await hub.start()

    class M:
        opcua = hub
    ua_ext = ExternalPlc({'protocol': 'opcua_server', 'poll_ms': 20}, io)
    await ua_ext.start({'mgr': M, 'pid': 'tp', 'bid': 'CELL1'})
    ua_ext.scan({'Start': True, 'Level': 42})
    await asyncio.sleep(0.15)
    cl = Client(f'opc.tcp://127.0.0.1:{hub.port}/vfactory/')
    await cl.connect()
    nin = cl.get_node(f'ns={hub.idx};s=tp/CELL1/PLC/Inputs/Start')
    nlv = cl.get_node(f'ns={hub.idx};s=tp/CELL1/PLC/Inputs/Level')
    nout = cl.get_node(f'ns={hub.idx};s=tp/CELL1/PLC/Outputs/Motor')
    v1, v2 = await nin.read_value(), await nlv.read_value()
    from asyncua import ua
    await nout.write_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
    await asyncio.sleep(0.15)
    o = ua_ext.scan({'Start': True, 'Level': 42})
    ok('OPC UA 服务器：发布传感器节点', v1 is True and v2 == 42, (v1, v2))
    ok('OPC UA 服务器：外部写执行器节点', o['Motor'] is True, o)
    await cl.disconnect()
    # 客户端模式：把 tp/CELL1 的节点当外部 PLC
    io2 = [{'name': 'Motor', 'dir': 'in'}, {'name': 'Level', 'dir': 'out', 'type': 'INT'}]
    ua_cli = ExternalPlc({'protocol': 'opcua', 'endpoint': f'opc.tcp://127.0.0.1:{hub.port}/vfactory/', 'poll_ms': 20,
                          'mapping': [{'name': 'Motor', 'addr': f'ns={hub.idx};s=tp/CELL1/PLC/Outputs/Motor'},
                                      {'name': 'Level', 'addr': f'ns={hub.idx};s=tp/CELL1/PLC/Inputs/Level'}]}, io2)
    await ua_cli.start({})
    ua_cli.scan({'Motor': False})
    for _ in range(100):
        await asyncio.sleep(0.05)
        if ua_cli.status['polls'] > 3:
            break
    o2 = ua_cli.scan({'Motor': False})
    await asyncio.sleep(0.2)
    o = ua_ext.scan({'Start': True, 'Level': 42})
    ok('OPC UA 客户端：读外部节点', o2['Level'] == 42 and ua_cli.status['connected'], (o2, ua_cli.status))
    ok('OPC UA 客户端：写外部节点', o['Motor'] is False, o)
    await ua_cli.stop()
    await ua_ext.stop()
    await hub.server.stop()


class FakeS7:
    """测试用的最小 S7 服务器：COTP CR/CC、通讯设置、读/写变量（I/Q/M/DB）。"""
    def __init__(self):
        self.areas = {(0x81, 0): bytearray(64), (0x82, 0): bytearray(64), (0x83, 0): bytearray(64), (0x84, 1): bytearray(64)}
        self.tsap = None

    async def handle(self, r, w):
        import struct
        try:
            while True:
                hdr = await r.readexactly(4)
                n = struct.unpack('>H', hdr[2:4])[0]
                body = await r.readexactly(n - 4)
                if body[1] == 0xE0:                       # CR
                    i = 7
                    while i < len(body):
                        code, ln = body[i], body[i + 1]
                        if code == 0xC2:
                            self.tsap = int.from_bytes(body[i + 2:i + 2 + ln], 'big')
                        i += 2 + ln
                    cc = bytes([0x11, 0xD0, 0, 1, 0, 1, 0]) + body[7:]
                    w.write(struct.pack('>BBH', 3, 0, len(cc) + 4) + cc)
                    await w.drain()
                    continue
                s = body[3:]
                ref = s[4:6]
                plen, dlen = struct.unpack('>HH', s[6:10])
                par, data = s[10:10 + plen], s[10 + plen:10 + plen + dlen]
                func = par[0]
                if func == 0xF0:
                    rp, rd = par, b''
                elif func == 4:
                    cnt = par[1]
                    rd = b''
                    for k in range(cnt):
                        it = par[2 + 12 * k:14 + 12 * k]
                        ln, db = struct.unpack('>HH', it[4:8])
                        area, addr = it[8], int.from_bytes(it[9:12], 'big')
                        buf = self.areas[(area, db if area == 0x84 else 0)]
                        b0 = addr // 8
                        part = bytes([0xFF, 4]) + struct.pack('>H', ln * 8) + bytes(buf[b0:b0 + ln])
                        if k < cnt - 1 and ln % 2:
                            part += b'\x00'
                        rd += part
                    rp = bytes([4, cnt])
                elif func == 5:
                    cnt = par[1]
                    pos = 0
                    codes = b''
                    for k in range(cnt):
                        it = par[2 + 12 * k:14 + 12 * k]
                        ts = it[3]
                        ln, db = struct.unpack('>HH', it[4:8])
                        area, addr = it[8], int.from_bytes(it[9:12], 'big')
                        buf = self.areas[(area, db if area == 0x84 else 0)]
                        dts = data[pos + 1]
                        dl = struct.unpack('>H', data[pos + 2:pos + 4])[0]
                        nb = 1 if dts == 3 else dl // 8
                        val = data[pos + 4:pos + 4 + nb]
                        if ts == 1:
                            b0, bit = addr // 8, addr % 8
                            buf[b0] = (buf[b0] | (1 << bit)) if val[0] else (buf[b0] & ~(1 << bit))
                        else:
                            buf[addr // 8:addr // 8 + nb] = val
                        pos += 4 + nb + (nb % 2 if k < cnt - 1 else 0)
                        codes += b'\xff'
                    rp, rd = bytes([5, cnt]), codes
                else:
                    break
                s7 = bytes([0x32, 3, 0, 0]) + ref + struct.pack('>HH', len(rp), len(rd)) + b'\x00\x00' + rp + rd
                pkt = bytes([2, 0xF0, 0x80]) + s7
                w.write(struct.pack('>BBH', 3, 0, len(pkt) + 4) + pkt)
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()


asyncio.run(ext_tests())

# ============================================================ 场景参考答案（控制层写在 vfactory/control/scenes/*.json）
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scene_files = sorted(glob.glob(os.path.join(root, 'vfactory', 'control', 'scenes', '*.json')))
for f in scene_files:
    try:
        sc = json.load(open(f, encoding='utf-8'))
    except ValueError as e:
        ok(f'场景 {os.path.basename(f)} 能读', False, e)
        continue
    cell = sc.get('cell') or {}
    io = cell.get('io') or sc.get('io') or []
    sols = []
    for k in ('solution', 'reference', 'answer', 'solutions'):
        v = sc.get(k)
        if isinstance(v, dict) and not ('source' in v or 'lang' in v):      # {'st': 程序, 'ld': 程序}
            sols += [x for x in v.values() if isinstance(x, dict)]
        elif isinstance(v, dict):
            sols.append(v)
        elif isinstance(v, list):
            sols += [x for x in v if isinstance(x, dict)]
    if not sols:
        ok(f'场景 {os.path.basename(f)} 有参考答案', False, list(sc))
        continue
    for i, sol in enumerate(sols):
        if 'lang' not in sol and isinstance(sol.get('source'), str):
            sol = dict(sol, lang='ST')
        p = PlcRuntime(sol, io=io)
        c = p.last_compile
        nm = f"场景 {sc.get('id') or os.path.basename(f)} 参考答案{i + 1}（{sol.get('lang')}）"
        ok(nm + ' 编译通过', c['ok'], c['errors'][:3])
        if c['ok']:
            rng = random.Random(1)
            err = None
            for _ in range(500):
                x = {e['name']: (rng.random() < 0.2) if (e.get('type') or 'BOOL') == 'BOOL' else rng.randint(0, 100) for e in io if e.get('dir') == 'in'}
                p.scan(x, 0.02)
                if p.state == 'ERROR':
                    err = p.error
                    break
            ok(nm + ' 随机输入 500 个扫描不出错', err is None, err)
if not scene_files:
    print('（vfactory/control/scenes 下还没有场景，跳过参考答案测试）')

n_ok = sum(1 for _, c in res if c)
print(f'\n{n_ok}/{len(res)} 通过')
sys.exit(0 if n_ok == len(res) else 1)
