"""编辑器与 AI 助手接口测试（先启动 serve）：python tests/editor_check.py [--ai]"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
B = __import__('os').environ.get('VF_URL', 'http://127.0.0.1:8800')
P = B + '/api/p/foundry-housing'
TOK = ''
res = []


def call(method, url, body=None):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOK})
    with urllib.request.urlopen(r, timeout=600) as f:
        return json.loads(f.read())


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300])


TOK = call('POST', B + '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
cat = call('GET', B + '/api/catalog')
ok('块类型目录', len(cat['types']) >= 25, f"{len(cat['types'])} 种")
call('DELETE', P + '/model/draft')
g = call('GET', P + '/model')
m = g['model']
ok('读取 2.0 模型', m.get('version') == 2 and m['blocks'] and m['links'], f"{len(m['blocks'])} 块 {len(m['links'])} 线，校验 {g['validation']['summary']}")
# 参数修改 → 热更新
cnc = next(b for b in m['blocks'] if b['id'] == 'CNC1')
orig = {'name': cnc['name'], 'mtbf_h': cnc['params'].get('mtbf_h')}
cnc['params']['mtbf_h'] = 90
cnc['name'] = '1#加工中心（改）'
r = call('PUT', P + '/model', {'model': m})
ok('保存草稿', r['ok'] and r['running_changes'], r['running_changes'])
r = call('POST', P + '/model/apply', {})
ok('参数修改热更新', r['mode'] == 'hot', r)
# 结构修改：加一个通用加工块，从线边库取料送到待去毛刺
m = call('GET', P + '/model')['model']
m['blocks'].append({'id': 'MX1', 'type': 'processor', 'name': '通用加工中心', 'pos': [111, 18], 'size': [4, 3.4], 'node': [1840, 520],
                    'params': {'time': 'normal(420,20)', 'mtbf_h': 100, 'mttr_min': 30},
                    'signals': [{'name': 'Spindle/Load', 'unit': '%', 'desc': '主轴负载', 'expr': 'if_(busy, 50 + noise(2), 2)'}]})
m['links'] += [{'id': 'LX1', 'kind': 'material', 'from': 'cnc_in', 'from_port': 'out', 'to': 'MX1', 'to_port': 'in'},
               {'id': 'LX2', 'kind': 'material', 'from': 'MX1', 'from_port': 'out', 'to': 'deb_in', 'to_port': 'in'}]
v = call('PUT', P + '/model', {'model': m})['validation']
ok('草稿校验', v['ok'], v['summary'])
t0 = time.time()
tr = call('POST', P + '/model/tryrun', {'model': m, 'hours': 4})
ok('试运行对比', tr.get('rows'), f"{tr.get('text')}（{time.time() - t0:.0f}s）")
r = call('POST', P + '/model/apply', {'note': '加一台通用加工中心'})
ok('结构修改重建', r['mode'] == 'rebuild', r)
time.sleep(3)
st = call('GET', P + '/station/MX1')
ok('新块已运行并有自定义点位', 'Spindle/Load' in st['tags'], st['state'])
vs = call('GET', P + '/versions')
ok('版本历史', len(vs) >= 2, [(v['n'], v['note']) for v in vs[:3]])
d = call('GET', P + f"/versions/{vs[-1]['n']}/diff?against=current")
ok('版本差异', any(x['id'] == 'MX1' for x in d), [(x['kind'], x['id']) for x in d][:6])
t = call('POST', B + '/api/templates', {'name': '通用加工中心', 'blocks': [b for b in m['blocks'] if b['id'] == 'MX1'], 'links': []})
ok('存为模板', t['id'] in [x['id'] for x in call('GET', B + '/api/templates')])
e = call('POST', B + '/api/expr/check', {'expr': 'normal(60,3) + noise(1)'})
ok('表达式试算', e['ok'], e)
e = call('POST', B + '/api/expr/check', {'expr': '__import__("os")'})
ok('危险表达式被拒绝', not e['ok'], e.get('error'))
# 还原：去掉 MX1
m = call('GET', P + '/model')['model']
m['blocks'] = [b for b in m['blocks'] if b['id'] != 'MX1']
m['links'] = [l for l in m['links'] if 'MX1' not in (l['from'], l['to'])]
cnc = next(b for b in m['blocks'] if b['id'] == 'CNC1')
cnc['name'], cnc['params']['mtbf_h'] = orig['name'], orig['mtbf_h']
call('PUT', P + '/model', {'model': m})
call('POST', P + '/model/apply', {'note': '还原'})
if '--ai' in sys.argv:
    st = call('GET', B + '/api/ai/status')
    ok('大模型可用', st['available'], st)
    t0 = time.time()
    a = call('POST', P + '/ai', {'message': 'CNC3 现在什么状态？最近有什么报警？', 'selection': ['CNC3'], 'view': 'graph'})
    ok('AI 查询选中设备', a['answer'] and any(x['tool'] == 'get_runtime' for x in a['trace']), f"{a['answer'][:150]}（{time.time() - t0:.0f}s）")
    t0 = time.time()
    m = call('GET', P + '/model')['model']
    a = call('POST', P + '/ai', {'message': '在它旁边加一台通用加工中心，从机加线边库取料，加工时间正态分布均值 420 秒标准差 20 秒，做完送到待去毛刺。', 'selection': ['CNC6'],
                                 'model': m, 'view': 'graph'})
    ok('AI 提出变更集', a['ops'] and a['validation'] and a['validation']['ok'], f"{a['summary']} | {len(a['ops'])} 条 | {a['answer'][:120]}（{time.time() - t0:.0f}s）")
    pv = call('POST', P + '/model/ops', {'model': m, 'ops': a['ops']})
    ok('变更集可应用', pv['validation']['ok'] and len(pv['model']['blocks']) > len(m['blocks']), pv['validation']['summary'])
    t0 = time.time()
    a = call('POST', P + '/ai', {'message': '给 SAND1 编一个场景：开始后 30 分钟型砂水分设定在 1 小时内升到 3.9%，3 小时后恢复 3.4%。', 'selection': ['SAND1']})
    ok('AI 生成场景', a['actions'] and a['actions'][0]['type'] == 'scenario', json.dumps(a['actions'], ensure_ascii=False)[:200] + f'（{time.time() - t0:.0f}s）')
bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
