"""专业仿真接口冒烟测试（先启动 serve）：VF_URL=http://127.0.0.1:8800 VF_PLANT=foundry-housing python tests/sim_api_check.py

覆盖 /analysis/*、/energy/settings、/tables*、/submodels*、/underlay/dxf、/fork、/optimize、/experiments（因子 + 置信区间 + 导出）。
会在指定工厂上新建并删除一张临时数据表和一个临时子模型定义；能耗设置测完恢复原值。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
PID = os.environ.get('VF_PLANT', 'foundry-housing')
P = f'{B}/api/p/{PID}'
TOK = ''
res = []


def call(method, url, body=None, raw=False):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + TOK} if TOK else {})})
    with urllib.request.urlopen(r, timeout=600) as f:
        d = f.read()
        return d if raw else json.loads(d)


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:200], flush=True)


TOK = call('POST', B + '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
s = call('GET', P + '/analysis/stats?hours=24')
ok('统计接口', s['objects'] and s['classes'] and 'wip_avg' in s['plant'], {k: s['plant'][k] for k in ('good', 'wip_avg', 'oee_avg')})
bn = call('GET', P + '/analysis/bottleneck?hours=24')
ok('瓶颈接口（活跃期法、并列判断、着色数据）', bn['method'] == 'active_period' and bn['items'] and bn['verdict'] and bn['by_station']
   and all({'rank', 'share', 'util', 'tie', 'bottleneck'} <= set(v) for v in bn['by_station'].values()), bn['verdict'])
ok('瓶颈：与统计接口同一份结果', s['bottleneck']['top'] == bn['top'] and s['plant']['bottleneck'][0]['group'] == bn['items'][0]['group'], (s['bottleneck']['top'], bn['top']))
rp = call('GET', P + '/report?hours=24')
ok('报表与统计同区间同口径（在制品、产出）', rp['from'] == s['from'] and abs(rp['wip_avg'] - s['plant']['wip_avg']) < 3, (rp['wip_avg'], s['plant']['wip_avg']))
sk = call('GET', P + '/analysis/sankey?hours=24')
ok('桑基图接口', sk['nodes'] and sk['links'], f"{len(sk['nodes'])} 节点 {len(sk['links'])} 条流")
g = call('GET', P + '/analysis/gantt?by=resource&hours=4')
ok('甘特图（设备）接口', g['rows'] and g['items'], f"{len(g['rows'])} 行 {len(g['items'])} 段")
g2 = call('GET', P + '/analysis/gantt?by=part&hours=8&limit=10')
ok('甘特图（零件）接口', g2['rows'], f"{len(g2['rows'])} 件")
try:
    call('GET', P + '/analysis/gantt?by=xx')
    ok('甘特图参数校验', False)
except urllib.error.HTTPError as e:
    ok('甘特图参数校验', e.code == 400)
e = call('GET', P + '/analysis/energy?hours=24')
ok('能耗接口', e['kwh'] > 0 and e['cost'] > 0 and (e['peak_kw'] > 0 or len(e['curve']) <= 1) and e['curve'],  # 峰值需量只算满 15 分钟的时段
   {k: e[k] for k in ('kwh', 'cost', 'peak_kw', 'co2_kg')})
old = call('GET', P + '/energy/settings')
new = call('PUT', P + '/energy/settings', {**old, 'tou': [], 'default_price': 1.0})
e2 = call('GET', P + '/analysis/energy?hours=24')
ok('电价设置生效', abs(e2['cost'] - e2['kwh'] * 1.0) < 1, (e2['cost'], e2['kwh']))
call('PUT', P + '/energy/settings', old)
# 数据表
csv = '时间,产品,数量,订单\n0,A,3,T-1\n1,B,2,T-2\n'
t = call('POST', P + '/tables/import', {'filename': 'apitest.csv', 'data_url': 'data:text/csv;base64,' + base64.b64encode(csv.encode('utf-8')).decode(), 'name': 'API测试表'})
ok('数据表导入', t['n_rows'] == 2 and t['columns'][0] == '时间', t['columns'])
ls = call('GET', P + '/tables')
ok('数据表列表', any(x['name'] == 'API测试表' for x in ls), [x['name'] for x in ls])
t2 = call('PUT', P + '/tables/' + urllib.request.quote('API测试表'), {'name': 'API测试表', 'columns': ['时间', '产品', '数量', '订单'], 'rows': [[0, 'A', 5, 'T-9']]})
ok('数据表修改', t2['rows'] == [{'时间': 0, '产品': 'A', '数量': 5, '订单': 'T-9'}], t2['rows'])
c = call('GET', P + '/tables/' + urllib.request.quote('API测试表') + '/export.csv', raw=True).decode('utf-8-sig')
ok('数据表导出 CSV', c.startswith('时间,产品'), c[:30])
ops = call('POST', P + '/tables/' + urllib.request.quote('API测试表') + '/ops', {'kind': 'routing'})
ok('路线转命令（缺列时给出说明）', ops['issues'] and not ops['ops'], ops['issues'][:1])
call('DELETE', P + '/tables/' + urllib.request.quote('API测试表'))
ok('数据表删除', not any(x['name'] == 'API测试表' for x in call('GET', P + '/tables')))
# 子模型
d = call('PUT', P + '/submodels/APITEST', {'name': '测试单元', 'blocks': [{'id': 'X1', 'type': 'processor', 'name': '工序', 'pos': [0, 0], 'params': {'time': '60'}}], 'links': [],
                                           'expose': [{'name': 'ct', 'targets': ['X1.time']}]})
sm = call('GET', P + '/submodels')
ok('子模型定义保存', any(x['id'] == 'APITEST' and x['entry_resolved'] for x in sm['defs']), [x['id'] for x in sm['defs']])
m = {'version': 2, 'plant': {'name': 'x'}, 'submodels': [d], 'blocks': [{'id': 'S', 'type': 'submodel', 'name': 'S', 'pos': [0, 0], 'params': {'def': 'APITEST', 'ct': '30'}}], 'links': []}
ex = call('POST', P + '/submodels/expand', {'model': m})
ok('子模型展开预览', any(b['id'] == 'S_X1' and b['params']['time'] == '30' for b in ex['blocks']), [b['id'] for b in ex['blocks']])
call('DELETE', P + '/submodels/APITEST')
# DXF
dxf = '0\nSECTION\n2\nENTITIES\n0\nLINE\n8\nA\n10\n0\n20\n0\n11\n40\n21\n0\n0\nCIRCLE\n8\nB\n10\n20\n20\n10\n40\n5\n0\nENDSEC\n0\nEOF\n'
u = call('POST', P + '/underlay/dxf', {'text': dxf, 'unit': 'm'})
ok('DXF 导入', u['w'] == 40 and u['underlay']['url'].startswith(f'/api/p/{PID}/underlay.svg'), (u['w'], u['h'], u['layers']))
svg = call('GET', B + u['underlay']['url'].split('?')[0] + '?token=' + TOK, raw=True)
ok('DXF 底图 SVG 可取', svg.startswith(b'<svg'), len(svg))
# 推演
t0 = time.time()
f = call('POST', P + '/fork', {'hours': 2, 'reps': 2, 'changes': [{'type': 'enable', 'station': s['objects'][0]['id'], 'value': False}]})
ok('从此刻推演', f['rows'] and f['text'] and f['reps'] == 2, f"{f['text']}（{time.time() - t0:.0f}s，副本 {f['blob_kb']} KB）")
# 实验（因子）+ 优化
sts = call('GET', P + '/meta')['stations']
buf = list(call('GET', P + '/meta')['buffers'])[0]
x = call('POST', P + '/experiments', {'name': 'API 因子实验', 'hours': 1, 'reps': 2, 'warmup_h': 0.5, 'factors': [{'type': 'buffer', 'name': buf, 'levels': [5, 50]}]})
ok('因子实验创建', x['variants'] == 3, x)
opt = call('POST', P + '/optimize', {'name': 'API 优化', 'hours': 1, 'reps': 1, 'budget': 4, 'pop': 4, 'warmup_h': 0.5,
                                     'params': [{'kind': 'buffer', 'name': buf, 'lo': 5, 'hi': 45, 'step': 10}], 'objectives': [{'key': 'good_per_h', 'sense': 'max'}]})
for _ in range(240):
    a = call('GET', f"{P}/experiments/{x['id']}")
    b = call('GET', f"{P}/experiments/{opt['id']}")
    if a['status'] in ('done', 'failed') and b['status'] in ('done', 'failed'):
        break
    time.sleep(3)
ok('因子实验完成（含 95% 区间）', a['status'] == 'done' and a['result']['rows'][1]['ci']['good']['n'] == 2, a['status'] if a['status'] != 'done' else a['result']['text'][0])
ok('优化完成', b['status'] == 'done' and b['kind'] == 'optimize' and b['result']['best'], b['status'] if b['status'] != 'done' else b['result']['text'])
lst = call('GET', P + '/experiments')
ok('实验列表区分对比/优化', {r['kind'] for r in lst if r['id'] in (x['id'], opt['id'])} == {'compare', 'optimize'})
xl = call('GET', f"{P}/experiments/{x['id']}/export.xlsx", raw=True)
cs = call('GET', f"{P}/experiments/{x['id']}/export.csv", raw=True).decode('utf-8-sig')
ok('实验导出 Excel/CSV', xl[:2] == b'PK' and '95%下限' in cs, (len(xl), len(cs)))
ok('实验结果带可信度提示（2 次重复、1 小时 → 警告）', a['result'].get('quality') and not a['result']['quality']['ok'] and a['result']['quality']['recommended_reps'] >= 5,
   (a['result'].get('quality') or {}).get('warnings'))
ok('实验置信区间不越界', all(c['lo'] is None or c['lo'] >= 0 for r in a['result']['rows'] for c in r['ci'].values()), '')
vers = call('GET', P + '/versions')
try:
    call('POST', P + '/experiments', {'name': 'x', 'hours': 1, 'reps': 1, 'variants': [{'name': 'v', 'changes': [{'type': 'version', 'n': 99999}]}]})
    ok('不存在的模型版本被拒绝', False)
except urllib.error.HTTPError as e_:
    ok('不存在的模型版本被拒绝', e_.code == 400, e_.read().decode()[:80])
try:
    call('POST', P + '/experiments', {'name': 'x', 'hours': 1, 'reps': 1, 'variants': [{'name': 'v', 'changes': [{'type': 'plan', 'shifts': [{'start': '7点', 'end': '15:00'}]}]}]})
    ok('班次时间格式校验', False)
except urllib.error.HTTPError as e_:
    ok('班次时间格式校验', e_.code == 400, e_.read().decode()[:80])
vx = call('POST', P + '/experiments', {'name': 'API 版本与班次', 'hours': 1, 'reps': 1, 'warmup_h': 0.5, 'variants': [
    {'name': '只开 8–12 点', 'changes': [{'type': 'plan', 'shifts': [{'name': '短班', 'start': '08:00', 'end': '12:00'}], 'label': '短班 8–12'}]}]
    + ([{'name': f"版本 #{vers[-1]['n']}", 'changes': [{'type': 'version', 'n': vers[-1]['n']}]}] if vers else [])})
for _ in range(120):
    v_ = call('GET', f"{P}/experiments/{vx['id']}")
    if v_['status'] in ('done', 'failed'):
        break
    time.sleep(3)
ok('方案可以是另一套班次 / 模型版本', v_['status'] == 'done' and len(v_['result']['rows']) == vx['variants'], v_['status'] if v_['status'] != 'done' else v_['result']['text'][:2])
call('DELETE', f"{P}/experiments/{vx['id']}")
for i in (x['id'], opt['id']):
    call('DELETE', f'{P}/experiments/{i}')
bad = [n for n, g_ in res if not g_]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
sys.exit(1 if bad else 0)
