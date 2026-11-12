"""AI 助手 15 条指令验收（先启动 serve，需配置大模型）：python tests/ai_cmds.py [序号,...]

前 4 条在示范工厂（高级模型），其余在临时建的通用机加线上；修改类只检查变更集（/model/ops 预览），不写入运行中的工厂。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
B = 'http://127.0.0.1:8800'
TOK = ''
res = []


def call(method, url, body=None):
    r = urllib.request.Request(B + url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOK})
    with urllib.request.urlopen(r, timeout=900) as f:
        return json.loads(f.read())


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:260].replace('\n', ' '), flush=True)


TOK = call('POST', '/api/login', {'username': 'admin', 'password': 'honey123'})['token']

# 临时通用机加线：来料 → 缓存 → 加工 → 检测 → 出口，人员池
LINE = {
    'blocks': [
        {'id': 'SRC1', 'type': 'source', 'name': '毛坯来料', 'pos': [6, 10], 'size': [4, 4], 'node': [0, 0], 'params': {'interval': 'expo(120)', 'batch': 1}},
        {'id': 'B1', 'type': 'buffer', 'name': '线边库', 'pos': [13, 10], 'size': [3, 3], 'node': [280, 0], 'params': {'capacity': 50}},
        {'id': 'M1', 'type': 'processor', 'name': '1#加工中心', 'pos': [20, 10], 'size': [4, 3.4], 'node': [560, 0], 'params': {'time': 'normal(150,8)', 'mtbf_h': 100, 'mttr_min': 30}},
        {'id': 'QC1', 'type': 'inspect', 'name': '终检', 'pos': [28, 10], 'size': [4, 4], 'node': [840, 0], 'params': {'time': '30', 'pod_pct': 95}},
        {'id': 'OUT1', 'type': 'sink', 'name': '成品出口', 'pos': [36, 10], 'size': [4, 4], 'node': [1120, 0], 'params': {}},
        {'id': 'OP1', 'type': 'operators', 'name': '操作工', 'pos': [20, 18], 'size': [2, 2], 'node': [560, 220], 'params': {'count': 2}},
    ],
    'links': [
        {'id': 'L1', 'kind': 'material', 'from': 'SRC1', 'from_port': 'out', 'to': 'B1', 'to_port': 'in'},
        {'id': 'L2', 'kind': 'material', 'from': 'B1', 'from_port': 'out', 'to': 'M1', 'to_port': 'in'},
        {'id': 'L3', 'kind': 'material', 'from': 'M1', 'from_port': 'out', 'to': 'QC1', 'to_port': 'in'},
        {'id': 'L4', 'kind': 'material', 'from': 'QC1', 'from_port': 'out', 'to': 'OUT1', 'to_port': 'in'},
    ], 'groups': [], 'notes': []}


def blocks(m):
    return {b['id']: b for b in m['blocks']}


def links(m, a=None, b=None, fp=None):
    return [l for l in m['links'] if (a is None or l['from'] == a) and (b is None or l['to'] == b) and (fp is None or (l.get('from_port') or 'out') == fp)]


def ask(pid, model, msg, sel):
    t0 = time.time()
    a = call('POST', f'/api/p/{pid}/ai', {'message': msg, 'selection': sel, 'model': model, 'view': 'graph'})
    a['secs'] = round(time.time() - t0)
    a['tools'] = [x['tool'] for x in a.get('trace') or []]
    if a.get('ops'):
        pv = call('POST', f'/api/p/{pid}/model/ops', {'model': model, 'ops': a['ops']})
        a['after'], a['valid'] = pv['model'], pv['validation']['ok']
    return a


def check_change(a, cond_fn):
    if not a.get('ops'):
        return False, '没有变更集：' + (a.get('answer') or '')[:120]
    if not a['valid']:
        return False, '变更集校验不通过'
    try:
        r = cond_fn(a['after'])
    except Exception as e:  # 预期字段缺失也算失败
        r = False, f'检查出错 {e}'
    return r if isinstance(r, tuple) else (r, '')


CASES = []


def case(n, pid, msg, sel, kind, cond=None):
    CASES.append((n, pid, msg, sel, kind, cond))


case(1, 'foundry-housing', 'CNC3 现在什么状态？最近有没有报警？', ['CNC3'], 'query', lambda a: 'get_runtime' in a['tools'])
case(2, 'foundry-housing', '现在整条线的瓶颈在哪？给出数据依据。', [], 'query', lambda a: bool({'get_report', 'get_runtime'} & set(a['tools'])))
case(3, 'foundry-housing', '把它的平均故障间隔改成 150 小时', ['CNC2'], 'change', lambda m: blocks(m)['CNC2']['params'].get('mtbf_h') == 150)
case(4, 'foundry-housing', '这几台的平均修复时间都改成 25 分钟', ['CNC1', 'CNC2', 'CNC3'], 'change',
     lambda m: all(blocks(m)[x]['params'].get('mttr_min') == 25 for x in ('CNC1', 'CNC2', 'CNC3')))
case(5, 'LINE', '把它改名为「精加工中心 A」，并往右挪 2 米', ['M1'], 'change',
     lambda m: (blocks(m)['M1']['name'] == '精加工中心 A' and abs(blocks(m)['M1']['pos'][0] - 22) < 0.01, blocks(m)['M1']))
case(6, 'LINE', '缓存容量改成 20 件', ['B1'], 'change', lambda m: blocks(m)['B1']['params'].get('capacity') == 20)
case(7, 'LINE', '来料改成平均 90 秒一件的指数分布', ['SRC1'], 'change', lambda m: (blocks(m)['SRC1']['params'].get('interval', '').replace(' ', '') in ('expo(90)', 'expo(90.0)'), blocks(m)['SRC1']['params']))
case(8, 'LINE', '再加一台和它一样的并联加工中心，从线边库取料，做完也送去终检', ['M1'], 'change',
     lambda m: (lambda new: (len(new) == 1 and links(m, 'B1', new[0]) and links(m, new[0], 'QC1'), new))(
         [b['id'] for b in m['blocks'] if b['type'] == 'processor' and b['id'] != 'M1']))
case(9, 'LINE', '给它加一个主轴温度点位 Spindle/Temp，单位 ℃，加工时 60 度左右、停下来慢慢降到 25 度', ['M1'], 'change',
     lambda m: (any('temp' in s['name'].lower() for s in blocks(m)['M1'].get('signals') or []), blocks(m)['M1'].get('signals')))
case(10, 'LINE', '检测不合格的送去返修，返修好了再回到终检复检', ['QC1'], 'change',
     lambda m: (lambda rw: (bool(rw) and links(m, 'QC1', rw[0], 'ng') and links(m, rw[0], 'QC1'), rw))(
         [b['id'] for b in m['blocks'] if b['type'] == 'rework']))
case(11, 'LINE', '它上下料需要人，从操作工这个人员池要人', ['M1'], 'change', lambda m: blocks(m)['M1']['params'].get('operator') == 'OP1')
case(12, 'LINE', '把加工时间缩短 20%，保持正态分布', ['M1'], 'change',
     lambda m: ('120' in str(blocks(m)['M1']['params'].get('time')), blocks(m)['M1']['params'].get('time')))
case(13, 'LINE', '删掉线边库，来料直接送到加工中心', ['B1'], 'change',
     lambda m: ('B1' not in blocks(m) and links(m, 'SRC1', 'M1'), [(l['from'], l['to']) for l in m['links']]))
case(14, 'LINE', '给它编一个场景：开始 1 小时后发生一次故障停机 30 分钟，然后恢复', ['M1'], 'scenario')
case(15, 'LINE', '设计一个实验：比较加工时间 normal(150,8) 和 normal(120,6) 两种方案 8 小时的产量', ['M1'], 'experiment')

only = {int(x) for x in sys.argv[1].split(',')} if len(sys.argv) > 1 else None
line = None
if any(c[1] == 'LINE' and (only is None or c[0] in only) for c in CASES):
    line = call('POST', '/api/plants', {'name': 'AI 指令测试线', 'template': 'blank'})['id']
    m = call('GET', f'/api/p/{line}/model')['model']
    m.update(LINE)
    call('PUT', f'/api/p/{line}/model', {'model': m})
    r = call('POST', f'/api/p/{line}/model/apply', {'note': 'AI 测试线'})
    print('测试线', line, r.get('mode'))
    time.sleep(3)
try:
    for n, pid, msg, sel, kind, cond in CASES:
        if only and n not in only:
            continue
        pid = line if pid == 'LINE' else pid
        model = call('GET', f'/api/p/{pid}/model')['model']
        try:
            a = ask(pid, model, msg, sel)
        except Exception as e:
            ok(f'{n:02d} {msg}', False, f'请求出错 {e}')
            continue
        tag = f"（{a['secs']}s，工具 {','.join(a['tools']) or '无'}）"
        if kind == 'query':
            ok(f'{n:02d} {msg}', len(a.get('answer') or '') > 20 and cond(a), tag + ' ' + (a.get('answer') or ''))
        elif kind == 'change':
            good, det = check_change(a, cond)
            ok(f'{n:02d} {msg}', good, f"{tag} {a.get('summary')} | {json.dumps(det, ensure_ascii=False, default=str)[:160]}")
        else:
            acts = [x for x in a.get('actions') or [] if x['type'] == kind]
            good = bool(acts) and (kind != 'scenario' or acts[0]['payload'].get('steps')) and (kind != 'experiment' or len(acts[0]['payload'].get('variants') or []) >= 1)
            ok(f'{n:02d} {msg}', good, tag + ' ' + json.dumps(acts[:1], ensure_ascii=False)[:200])
finally:
    if line:
        call('DELETE', f'/api/plants/{line}')
bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '；'.join(bad)) if bad else '')
