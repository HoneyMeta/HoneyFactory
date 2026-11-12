"""工作台后端：运行控制、断点、回放、热更新、AI 助手（SSE、试算、令牌提交）。先启动 serve：python tests/workbench_check.py [--ai]"""
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
P = B + '/api/p/foundry-housing'
TOK = ''
res = []


def call(method, url, body=None):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOK})
    with urllib.request.urlopen(r, timeout=900) as f:
        return json.loads(f.read())


def status(method, url, body=None):
    try:
        call(method, url, body)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def sse(url, body):
    r = urllib.request.Request(url, method='POST', data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOK})
    evs, kind = [], None
    with urllib.request.urlopen(r, timeout=900) as f:
        for raw in f:
            line = raw.decode('utf-8').rstrip('\n')
            if line.startswith('event: '):
                kind = line[7:]
            elif line.startswith('data: '):
                evs.append((kind, json.loads(line[6:])))
    return evs


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300], flush=True)


TOK = call('POST', B + '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
call('DELETE', P + '/model/draft')
r = call('POST', P + '/ctl', {'action': 'pause'})
ok('暂停', r['mode'] == 'paused', r['mode'])
t0 = call('GET', P + '/state')['t']
r = call('POST', P + '/ctl', {'action': 'step', 'seconds': 120})
t1 = call('GET', P + '/state')['t']
ok('单步 2 分钟', abs(t1 - t0 - 120) < 1.5, f'{t0} → {t1}')
seq0 = call('GET', P + '/events?since=0&limit=1')
r = call('POST', P + '/ctl', {'action': 'step', 'event': True})
t2 = call('GET', P + '/state')['t']
ok('单步到下一事件', 0 < t2 - t1 <= 3600, f'推进 {t2 - t1:.0f} 秒')
# 断点：CNC3 故障时暂停
b = call('POST', P + '/breakpoints', {'cond': {'kind': 'state', 'id': 'CNC3', 'state': 'Stopped'}, 'once': True})
ok('加断点', b['id'] and 'CNC3' in b['name'], b['name'])
call('POST', P + '/ctl', {'action': 'play', 'speed': 60})
time.sleep(1.5)
faults = call('GET', P + '/station/CNC3')['faults']
call('POST', P + '/station/CNC3/fault', {'kind': next(iter(faults))})
time.sleep(2.5)
st = call('GET', P + '/state')
hit = st.get('ctl', {}).get('hit') if 'ctl' in st else None
ctl = call('POST', P + '/ctl', {'action': 'pause'})
ok('断点命中后自动暂停', ctl['hit'] and ctl['hit']['station'] == 'CNC3', ctl['hit'])
call('POST', P + '/station/CNC3/fault', {'kind': 'clear'})
call('DELETE', P + f"/breakpoints/{b['id']}")
# 运行到：合格品再多 3 件
g0 = call('GET', P + '/state')['kpi']['good']
r = call('POST', P + '/ctl', {'action': 'run_to', 'cond': {'kind': 'kpi', 'key': 'good', 'op': '>=', 'value': g0 + 3}, 'hours': 6})
for _ in range(120):
    time.sleep(0.5)
    s = call('GET', P + '/state')
    if s['kpi']['good'] >= g0 + 3 and s['paused']:
        break
s = call('GET', P + '/state')
ok('运行到条件成立后暂停', s['kpi']['good'] >= g0 + 3 and s['paused'], f"合格 {g0} → {s['kpi']['good']}，{r['goal']}")
ix = call('GET', P + '/replay/index')
snap = call('GET', P + f"/replay/at?t={ix['points'][len(ix['points']) // 2][0]}")
ok('回放快照', len(ix['points']) > 10 and snap.get('stations'), f"{len(ix['points'])} 份，{snap.get('time')}")
# 暂停中改参数 → 热更新（不写文件）
m = call('GET', P + '/model')['model']
cnc = next(x for x in m['blocks'] if x['id'] == 'CNC2')
old = cnc['params'].get('mttr_min')
cnc['params']['mttr_min'] = 33
h = call('POST', P + '/model/hot', {'model': m})
ok('暂停中改参数立即生效', h['ok'] and any(c['id'] == 'CNC2' for c in h['live_changes']), [c['id'] for c in h['live_changes']])
m['blocks'].append({'id': 'MZ1', 'type': 'processor', 'name': '测试加工', 'pos': [120, 40], 'size': [4, 3.4], 'node': [0, 900], 'params': {}})
h2 = call('POST', P + '/model/hot', {'model': m})
ok('结构改动不能热更新', not h2['ok'] and h2['structural'], h2['reason'])
# 重置：放弃改动
call('DELETE', P + '/model/draft')
r = call('POST', P + '/ctl/reset')
ok('重置后进入编辑状态', r['mode'] == 'edit', r['time'])
m = call('GET', P + '/model')
ok('重置后回到已保存的模型', not m['live_changes'] and next(x for x in m['model']['blocks'] if x['id'] == 'CNC2')['params'].get('mttr_min') == old,
   len(m['live_changes']))
call('POST', P + '/ctl', {'action': 'play', 'speed': 10})
# 只读账号不能控制
gt = call('POST', B + '/api/login', {'username': 'guest', 'password': 'honey123'})['token']
TOK, keep = gt, TOK
ok('只读账号不能控制仿真', status('POST', P + '/ctl', {'action': 'pause'}) == 403)
TOK = keep

if '--ai' in sys.argv:
    th = call('POST', B + '/api/assistant/threads', {'plant': 'foundry-housing'})
    model = call('GET', P + '/model')['model']
    t = time.time()
    evs = sse(B + f"/api/assistant/threads/{th['id']}/message", {'plant': 'foundry-housing', 'message': '它现在什么状态？', 'selection': ['CNC3'], 'ctx': ['3#加工中心'],
                                                                 'page': '/p/foundry-housing', 'view': '3d', 'model': model})
    kinds = [k for k, _ in evs]
    ans = next((d['text'] for k, d in evs if k == 'answer'), '')
    ok('助手：查询走 SSE，有人话进度', 'tool' in kinds and ans and all('正在' in d['phrase'] for k, d in evs if k == 'tool'),
       f"{[d['phrase'] for k, d in evs if k == 'tool']} {ans[:80]}（{time.time() - t:.0f}s）")
    t = time.time()
    evs = sse(B + f"/api/assistant/threads/{th['id']}/message", {'plant': 'foundry-housing', 'message': '把它的平均故障间隔改成 150 小时，看看对产量的影响',
                                                                 'selection': ['CNC3'], 'ctx': ['3#加工中心'], 'page': '/p/foundry-housing', 'model': model})
    prop = next((d for k, d in evs if k == 'proposal'), None)
    ok('助手：先试算再提议（带 KPI 对比和令牌）', prop and prop['token'] and prop['measure']['rows'],
       f"{prop and prop['summary']} | {prop and [(r['label'], r['delta']) for r in prop['measure']['rows'][:3]]}（{time.time() - t:.0f}s）")
    if prop:
        c = call('POST', B + '/api/assistant/commit', {'model': model, 'ops': prop['ops'], 'token': prop['token']})
        ok('助手：凭令牌提交，服务端回执', c['ok'] and c['lines'], c['lines'])
        m2 = json.loads(json.dumps(model))
        m2['blocks'][0]['name'] += '（改）'
        ok('助手：模型变了令牌失效', status('POST', B + '/api/assistant/commit', {'model': m2, 'ops': prop['ops'], 'token': prop['token']}) == 409)
    evs = sse(B + f"/api/assistant/threads/{th['id']}/message", {'plant': 'foundry-housing', 'message': '在 CNC5 故障的时候自动暂停，然后带我去三维里看它',
                                                                 'page': '/p/foundry-housing', 'model': model})
    kinds = [k for k, _ in evs]
    ok('助手：设断点并带去看', 'wrote' in kinds and 'navigate' in kinds, [d for k, d in evs if k in ('wrote', 'navigate')])
    for b in call('GET', P + '/breakpoints'):
        call('DELETE', P + f"/breakpoints/{b['id']}")
    thr = call('GET', B + f"/api/assistant/threads/{th['id']}")
    ok('助手：对话已保存', len(thr['messages']) == 6 and thr['title'] != '新对话', thr['title'])
    call('DELETE', B + f"/api/assistant/threads/{th['id']}")
bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
