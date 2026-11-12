"""PLC 接口测试（先启动 serve）：python tests/plc_api_check.py [工厂] [控制单元]

VF_URL 默认 http://127.0.0.1:8800。练习 PLC（_sandbox）在第一个工厂上测；给了工厂和控制单元时再测控制单元
（单元里要有 按钮×2 + 输送线 + 指示灯 这种启停结构，例如 tests 里 plctest 工厂的 CELL1）。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
TOK = ''
res = []


def call(method, url, body=None, raw=False, ctype='application/json'):
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    r = urllib.request.Request(B + url, method=method, data=data, headers={'Content-Type': ctype, **({'Authorization': 'Bearer ' + TOK} if TOK else {})})
    with urllib.request.urlopen(r, timeout=60) as f:
        d = f.read()
        return d if raw else json.loads(d)


def err_of(method, url, body=None):
    try:
        call(method, url, body)
        return None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}').get('detail')


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240])


TOK = call('POST', '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
pid = sys.argv[1] if len(sys.argv) > 1 else call('GET', '/api/plants')['plants'][0]['id']
bid = sys.argv[2] if len(sys.argv) > 2 else None
P = f'/api/p/{pid}'
pbid = bid           # 4.3：控制这个单元的 PLC 块（编程接口用它；按钮、点位还在单元上）
if bid:
    for c in call('GET', P + '/plc/cells')['cells']:
        if c['id'] == bid or bid in (c.get('devices') or []):
            pbid = c['id']
            break
    print('控制单元', bid, '→ PLC', pbid)

# ---------------------------------------------------------------- 4.1 示例数据（新装系统也有东西可看）
call('POST', P + '/hmi/_restore')
S = P + '/cells/_sandbox'
r = call('POST', S + '/plc', {'action': 'reset_program'})
g = call('GET', S + '/program')
ok('练习 PLC 恢复初始程序 = 示范程序并运行', r['state'] == 'RUN' and g['program']['name'].startswith('示范'), (r['state'], g['program'].get('name')))
hl = call('GET', P + '/hmi')['items']
ok('HMI 列表里总有练习 PLC 的示范画面', any(h['id'] == 'sandbox_demo' and h['source'] == 'demo' for h in hl), [(h['id'], h['source']) for h in hl])
d = call('GET', P + '/hmi/sandbox_demo')
ok('示范画面内容', d['cell'] == '_sandbox' and len(d['widgets']) >= 8, len(d.get('widgets') or []))
call('PUT', P + '/hmi/sandbox_demo', dict(d, name='我的示范'))
ok('改了示范画面保存成自己的版本', call('GET', P + '/hmi/sandbox_demo')['source'] == 'user+demo')
call('DELETE', P + '/hmi/sandbox_demo')
ok('删除自己的版本后恢复示范画面', call('GET', P + '/hmi/sandbox_demo')['name'].startswith('示范'))
call('DELETE', P + '/hmi/sandbox_demo')
ok('再删一次隐藏示范画面', not any(h['id'] == 'sandbox_demo' for h in call('GET', P + '/hmi')['items']))
call('PUT', P + '/hmi/sandbox_demo', d)
call('DELETE', P + '/hmi/sandbox_demo')
ok('隐藏后保存一次再删除 → 恢复', any(h['id'] == 'sandbox_demo' for h in call('GET', P + '/hmi')['items']))
if bid:
    r = call('POST', P + f'/cells/{pbid}/plc', {'action': 'reset_program'})
    g = call('GET', P + f'/cells/{pbid}/program')
    if r['state'] == 'RUN':
        ok('PLC 恢复初始程序 = PLC 块自带的程序并运行', g['program'].get('name') and g['same'], (r['state'], g['program'].get('name')))
    else:
        print('（这台 PLC 没有自带程序，跳过）')
    ok('每台 PLC 都有画面（自带或自动生成）', all(any(h.get('cell') == c['id'] for h in hl) for c in call('GET', P + '/plc/cells')['cells']),
       [(h['id'], h.get('cell'), h['source']) for h in hl])

# ---------------------------------------------------------------- 练习 PLC
g = call('GET', S + '/program')
ok('练习 PLC：读程序和 I/O 表', g['io'] and g['program']['lang'] in ('LD', 'ST'), [e['name'] for e in g['io']])
bad = call('POST', S + '/program/compile', {'program': {'lang': 'ST', 'source': 'Motor := Start\nLamp_Run := TRUE;'}})
ok('编译错误带行列、中文', not bad['ok'] and bad['errors'][0]['line'] == 1 and '分号' in bad['errors'][0]['msg'], bad['errors'])
prog = {'lang': 'ST', 'name': '启停', 'vars': [{'name': 'T1', 'type': 'TON'}, {'name': 'n', 'type': 'INT', 'comment': '运行秒数'}],
        'source': 'Motor := (Start OR Motor) AND NOT Stop;\nLamp_Run := Motor;\nT1(IN := Motor AND NOT T1.Q, PT := T#1s);\nIF T1.Q THEN n := n + 1; END_IF;\nDisplay := n;\n'}
d = call('POST', S + '/program/download', {'program': prog})
ok('下载并运行', d['ok'] and d['state'] == 'RUN', d.get('errors'))
time.sleep(0.3)
on = call('GET', S + '/online')
ok('在线：运行中、扫描计数在涨', on['state'] == 'RUN' and on['scan']['count'] > 0 and on['scan']['cycle_ms'] == 20, on['scan'])
call('POST', S + '/plc', {'action': 'force', 'name': 'Start', 'value': True})
time.sleep(0.3)
call('POST', S + '/plc', {'action': 'force', 'name': 'Start', 'value': None})
time.sleep(1.4)
on = call('GET', S + '/online')
ok('强制启动按钮 → 自锁运行、定时器计数', on['vars']['Motor'] is True and on['vars']['n'] >= 1 and not on['forced'], (on['vars'].get('Motor'), on['vars'].get('n')))
io = {r['name']: r for r in on['io']}
ok('I/O 监视表', io['Motor']['value'] is True and io['Motor']['addr'] == '%Q0.0' and io['Display']['value'] == on['vars']['n'], io['Motor'])
r = call('POST', S + '/plc', {'action': 'breakpoint', 'line': 3})
time.sleep(0.2)
on = call('GET', S + '/online')
ok('ST 断点命中', on['state'] == 'HALT' and on['halt']['line'] == 3 and on['bps'] == [3], on.get('halt'))
call('POST', S + '/plc', {'action': 'step', 'kind': 'stmt'})
on = call('GET', S + '/online')
ok('单步到下一条语句', on['halt']['line'] == 4, on.get('halt'))
call('POST', S + '/plc', {'action': 'breakpoint', 'clear': True})
call('POST', S + '/plc', {'action': 'run'})
on = call('GET', S + '/online')
ok('清除断点继续运行', on['state'] == 'RUN' and on['bps'] == [], on['state'])
n_before = on['vars']['n']
prog2 = dict(prog, source=prog['source'] + 'Lamp_Fault := n > 1000;\n')
d = call('POST', S + '/program/download', {'program': prog2})
on = call('GET', S + '/online')
ok('运行中下载保留变量值', d['ok'] and 'n' in d['kept'] and on['vars']['n'] >= n_before and on['vars']['Motor'] is True, d.get('kept'))
call('POST', S + '/plc', {'action': 'write', 'name': 'n', 'value': 2000})
time.sleep(0.1)
on = call('GET', S + '/online')
ok('在线写变量', on['vars']['Lamp_Fault'] is True, on['vars']['n'])
call('POST', S + '/plc', {'action': 'stop'})
on = call('GET', S + '/online')
ok('停止 → 输出为 0（变量值保留）', on['state'] == 'STOP' and on['vars']['Motor'] is True and not any(r['value'] for r in on['io'] if r['dir'] == 'out' and r['type'] == 'BOOL'), on['io'])
call('POST', S + '/plc', {'action': 'step', 'kind': 'scan'})
on = call('GET', S + '/online')
ok('单步一个扫描周期', on['state'] == 'HALT' and on['halt']['reason'] == 'scan_end', on.get('halt'))
call('POST', S + '/plc', {'action': 'run'})
e = err_of('POST', S + '/plc', {'action': 'force', 'name': 'Nope', 'value': 1})
ok('强制不存在的变量 → 400 中文', e and e[0] == 400 and 'Nope' in e[1], e)
ld = {'lang': 'LD', 'vars': [], 'source': {'rungs': [
    {'comment': '启停自锁', 'elements': [{'par': [[{'id': 'a', 't': 'NO', 'var': 'Start'}], [{'id': 'b', 't': 'NO', 'var': 'Motor'}]]},
                                         {'id': 'c', 't': 'NC', 'var': 'Stop'}, {'id': 'd', 't': 'COIL', 'var': 'Motor'}]},
    {'comment': '', 'elements': [{'t': 'NO', 'var': 'Motor'}, {'t': 'FB', 'fb': 'TON', 'inst': 'T2', 'in': {'PT': 'T#300ms'}}, {'t': 'COIL', 'var': 'Valve'}]}]}}
call('PUT', S + '/program', ld)
g = call('GET', S + '/program')
ok('保存工程（未下载 → 和 PLC 里不一致）', g['program']['lang'] == 'LD' and not g['same'], (g['project_hash'], g['online_hash']))
d = call('POST', S + '/program/download', {'cold': True})
time.sleep(0.5)
on = call('GET', S + '/online')
ok('下载工程里的 LD（冷启动）', d['ok'] and on['lang'] == 'LD' and 'ld' in on and on['ld']['c'][2] is True, on.get('ld'))
g = call('GET', S + '/program')
ok('下载后工程与 PLC 一致', g['same'], (g['project_hash'], g['online_hash']))
call('POST', S + '/plc', {'action': 'force', 'name': 'Start', 'value': True})
time.sleep(0.5)
on = call('GET', S + '/online')
ok('LD 在线通断', on['ld']['a'] == [True, True, True] and on['ld']['d'][0] and on['rungs'][0] and on['vars']['Valve'] is True, on['ld'])
call('POST', S + '/plc', {'action': 'unforce_all'})
call('POST', S + '/plc', {'action': 'breakpoint', 'rung': 1})
time.sleep(0.2)
on = call('GET', S + '/online')
ok('LD 梯级断点', on['state'] == 'HALT' and on['halt']['rung'] == 1, on.get('halt'))
call('POST', S + '/plc', {'action': 'breakpoint', 'clear': True})
call('POST', S + '/plc', {'action': 'run'})
x = call('GET', S + '/program/export.xml', raw=True).decode()
ok('导出 PLCopen XML', '<project' in x and 'tc6_0200' in x and 'leftPowerRail' in x)
im = call('POST', S + '/program/import', {'xml': x})
ok('导入 PLCopen XML', im['compile']['ok'] and im['program']['lang'] == 'LD' and len(im['program']['source']['rungs']) == 2, im['warnings'])
im = call('POST', S + '/program/import', x, ctype='application/xml')
ok('导入（直接传 XML 正文）', im['compile']['ok'])
e = err_of('POST', S + '/program/import', {'xml': '<a/>'})
ok('导入错误文件 → 400', e and e[0] == 400, e)

# ---------------------------------------------------------------- HMI
h = {'name': '测试画面', 'cell': '_sandbox', 'size': [800, 480], 'widgets': [
    {'id': 'w1', 'type': 'button', 'x': 20, 'y': 20, 'w': 100, 'h': 40, 'label': '启动', 'var': 'Start', 'mode': 'momentary'},
    {'id': 'w2', 'type': 'lamp', 'x': 140, 'y': 20, 'w': 40, 'h': 40, 'label': '运行', 'var': 'Motor', 'color': '#22c55e'},
    {'id': 'w3', 'type': 'trend', 'x': 20, 'y': 100, 'w': 400, 'h': 200, 'vars': ['Display']}]}
call('PUT', P + '/hmi/main_screen', h)
g = call('GET', P + '/hmi/main_screen')
ok('HMI 保存/读取', g['name'] == '测试画面' and len(g['widgets']) == 3)
ok('HMI 列表', any(x['id'] == 'main_screen' for x in call('GET', P + '/hmi')['items']))
e = err_of('PUT', P + '/hmi/bad.id', h)
ok('HMI 非法编号', e and e[0] in (400, 404), e)
e = err_of('PUT', P + '/hmi/x2', {'widgets': [{'type': 'rocket'}]})
ok('HMI 非法控件', e and e[0] == 400, e)
ok('HMI 删除', call('DELETE', P + '/hmi/main_screen')['ok'])

# ---------------------------------------------------------------- 控制单元
if bid:
    C = P + f'/cells/{pbid}'
    cells = call('GET', P + '/plc/cells')['cells']
    me = next((c for c in cells if c['id'] == pbid), {})
    ok('PLC 列表：PLC 块，带它控制的设备', me.get('kind') == 'plc' and bid in me.get('devices', []), me)
    g = call('GET', P + f'/cells/{bid}/program')
    ok('用控制单元编号打开编程 → 转到它的 PLC', g['cell']['id'] == pbid, g['cell'])
    g = call('GET', C + '/program')
    io = g['io']
    ok('控制单元 I/O 表', len(io) >= 4, [(e['name'], e['dir'], e['addr']) for e in io])

    def find(comp_type_hint, d):
        for e in io:
            if e['dir'] == d and (e.get('comp') or '').startswith(comp_type_hint):
                return e['name']
    start, stop, conv, lamp = find('B1', 'in'), find('B2', 'in'), find('C1', 'out'), find('LP', 'out')
    ok('找到按钮/输送线/灯的 I/O', all([start, stop, conv, lamp]), (start, stop, conv, lamp))
    ld = {'lang': 'LD', 'vars': [], 'source': {'rungs': [
        {'comment': '启停自锁（停止按钮常闭）', 'elements': [{'par': [[{'id': 's', 't': 'NO', 'var': start}], [{'id': 'h', 't': 'NO', 'var': conv}]]},
                                                          {'id': 't', 't': 'NO', 'var': stop}, {'id': 'm', 't': 'COIL', 'var': conv}]},
        {'comment': '运行灯', 'elements': [{'t': 'NO', 'var': conv}, {'t': 'COIL', 'var': lamp}]}]}}
    d = call('POST', C + '/program/download', {'program': ld, 'cold': True, 'run': True})
    ok('下载到控制单元', d['ok'] and d['state'] == 'RUN', d.get('errors'))
    call('POST', P + '/ctl', {'action': 'play'})
    call('POST', P + '/sim', {'speed': 1})
    time.sleep(1.5)
    call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B1', 'value': True})
    time.sleep(2.5)
    call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B1', 'value': False})
    time.sleep(2.5)
    on = call('GET', C + '/online')
    stt = call('GET', P + f'/station/{bid}')
    ok('按启动按钮 → 输送线自锁运行（PLC 输出）', on['vars'].get(conv) is True and on['vars'].get(lamp) is True, {k: on['vars'].get(k) for k in (start, stop, conv, lamp)})
    ok('单元点位跟随 PLC 输出', stt['tags'].get('IO/' + conv, {}).get('v') is True, stt['tags'].get('IO/' + conv))
    call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B2', 'value': True})
    time.sleep(2.5)
    call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B2', 'value': False})
    time.sleep(2.5)
    on = call('GET', C + '/online')
    ok('按停止按钮 → 停', on['vars'].get(conv) is False, on['vars'].get(conv))
    # 工厂重置后程序还在
    call('POST', P + '/ctl/reset', {})
    time.sleep(3)
    on = call('GET', C + '/online')
    ok('工厂重置后已下载的程序自动装回', on['state'] == 'RUN' and on['hash'] == d['hash'], (on['state'], on['hash'], d['hash']))
    x = call('GET', C + '/program/export.xml', raw=True).decode()
    ok('控制单元导出含 I/O 全局变量', f'name="{start}"' in x, x[:200])
    ext = call('GET', C + '/plc/external')
    ok('外接配置：默认 Modbus 服务器映射', ext['mode'] == 'internal' and ext['mapping'] and ext['mapping'][0]['addr'].startswith(('DI', 'IR', 'CO', 'HR')), ext['mapping'][:3])

# ---------------------------------------------------------------- 审计修复：状态/断点接口、时序、触点列、交叉引用、参考答案
if bid:
    C = P + f'/cells/{pbid}'
    call('POST', P + '/ctl', {'action': 'play'})
    call('POST', P + '/sim', {'speed': 1})
    call('POST', C + '/plc', {'action': 'run'})
    time.sleep(1.5)
    call('POST', C + '/plc', {'action': 'breakpoint', 'rung': 1, 'on': True})
    time.sleep(0.6)
    stt = call('GET', P + '/plc/status')
    me = next((c for c in stt['plcs'] if c['bid'] == pbid), {})
    ok('PLC 状态接口：断点列表带说明、暂停位置', me.get('bps') and me['bps'][0].get('rung') == 1 and me['bps'][0]['label'].startswith('梯级 2')
       and me.get('state') == 'HALT' and me['halt']['rung'] == 1 and me['label'].startswith('断点暂停'), me)
    ok('PLC 状态接口：halted 列表', any(c['bid'] == pbid for c in stt['halted']), stt['halted'])
    ok('PLC 状态接口：每台 PLC 带 devices', bid in me.get('devices', []), me.get('devices'))
    call('POST', C + '/plc', {'action': 'breakpoint', 'clear': True})
    call('POST', C + '/plc', {'action': 'run'})
    stt = call('GET', P + '/plc/status')
    ok('继续后不再是暂停', not stt['halted'], stt['halted'])
    rows = call('GET', P + f'/plc/{pbid}/io')
    r0 = next((r for r in rows if r['dir'] == 'out'), {})
    ok('PLC 通道表：每一路接到哪台设备的哪个点、当前值', rows and all(k in r0 for k in ('ch', 'dir', 'point', 'device', 'device_name', 'value', 'forced'))
       and r0['device'] == bid and not r0['ch'].startswith('%') and isinstance(r0['value'], bool), rows[:2])
    rows2 = call('GET', P + f'/plc/{bid}/io')
    ok('PLC 通道表：用设备编号也能查（转到它的 PLC）', [r['ch'] for r in rows2] == [r['ch'] for r in rows])
    e = err_of('GET', P + '/plc/NOPE/io')
    ok('PLC 通道表：没有这个 PLC → 404', e and e[0] == 404, e)
    g = call('GET', C + '/program')
    ins = [e for e in g['io'] if e['dir'] == 'in' and (e.get('type') or 'BOOL') == 'BOOL']
    ok('I/O 表带触点类型和静止值', ins and all(e.get('contact') in ('NO', 'NC') and e.get('idle') in (0, 1) for e in ins), [(e['name'], e.get('contact'), e.get('idle')) for e in ins])
    nc = [e for e in ins if e['contact'] == 'NC']
    ok('常闭按钮（停止）静止值为 1', any(e['idle'] == 1 for e in nc), nc)
    on = call('GET', C + '/online')
    ok('在线值的 I/O 行也带触点类型', any(r.get('contact') for r in on['io']), on['io'][:2])
    time.sleep(1.0)
    tr = call('GET', C + '/trace?seconds=10')
    ok('时序接口：信号列表和事件', tr['names'] and tr['events'] and len(tr['events'][0][1]) == len(tr['names']) and tr['signals'][0].get('dir'),
       {k: tr[k] for k in ('names', 'now_ms', 'start_ms')})
    r = call('POST', C + '/program/compile', {})
    ok('编译结果带交叉引用', isinstance(r.get('xref'), dict) and r['xref'], list(r.get('xref') or {})[:5])
    call('POST', C + '/plc', {'action': 'reset_stats'})
    ok('清零扫描统计', call('GET', C + '/online')['scan']['over'] == 0)
    e = err_of('GET', C + '/reference')
    ok('不是场景来的单元没有参考答案（404）', e and e[0] == 404, e)
if len(sys.argv) > 3:
    SP_ = f'/api/p/{sys.argv[3]}'
    sc = call('GET', SP_ + '/cells/CELL1/timing_spec')
    ok('期望时序：从场景测试生成（按钮、检查）', sc.get('scene') and sc['presses'] and sc['checks'] and 'eq' in sc['checks'][0], {k: sc.get(k) for k in ('scene', 'duration')})
    rf = call('GET', SP_ + '/cells/CELL1/reference')
    ok('老师/管理员能取参考答案（ST 和梯形图）', {p_['lang'] for p_ in rf['programs']} >= {'ST'}, [p_['lang'] for p_ in rf['programs']])
    stu = None
    try:
        stu = call('POST', '/api/login', {'username': 'guest', 'password': 'honey123'})['token']
    except Exception:          # noqa: BLE001
        pass
    if stu:
        old, TOK = TOK, stu
        e = err_of('GET', SP_ + '/cells/CELL1/reference')
        TOK = old
        ok('只读访客拿不到参考答案（403）', e and e[0] == 403, e)
bad = call('POST', S + '/program/compile', {'program': {'lang': 'ST', 'source': '(* 识别是绿(*teacher*)色 *)\nMotor := TRUE；'}})
ok('S28：嵌套注释 + 全角分号不再 500，返回中文错误', not bad['ok'] and '全角' in bad['errors'][0]['msg'] and bad['errors'][0]['line'] == 2, bad['errors'])
bad = call('POST', S + '/program/compile', {'program': {'lang': 'LD', 'source': {'rungs': [None, {'elements': 'x'}]}}})
ok('乱写的梯形图 JSON 也不会 500', not bad['ok'] and bad['errors'], bad['errors'][:1])

n_ok = sum(1 for _, c in res if c)
print(f'\n{n_ok}/{len(res)} 通过')
sys.exit(0 if n_ok == len(res) else 1)
