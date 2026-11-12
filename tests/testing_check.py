"""联调：测试剧本接口 + 报文监视 + 命令行无界面运行（JUnit）。先启动 serve：python tests/testing_check.py
环境变量 VF_URL、VF_PLANT（默认 foundry-housing）；命令行部分用 VF_CLI_PORTS="OPCUA,MQTT,MODBUS"（默认 14840,11883,15020）避开正在运行的服务，
VF_LAUNCHER 可指定启动器脚本（B 机嵌入式 Python 用），否则用 python -m vfactory。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
PID = os.environ.get('VF_PLANT', 'foundry-housing')
P = f'{B}/api/p/{PID}'
TOK = ''
res = []


def call(method, url, body=None, raw=False, tok=None):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + (tok or TOK)} if (tok or TOK) else {})})
    with urllib.request.urlopen(r, timeout=120) as f:
        d = f.read()
        return d if raw else json.loads(d)


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:220], flush=True)


def load(name):
    with open(os.path.join(ROOT, 'tests', 'scripts', name), encoding='utf-8') as f:
        return json.load(f)


def wait_run(rid, limit=240):
    t0 = time.time()
    while time.time() - t0 < limit:
        r = call('GET', P + f'/tests/runs/{rid}')
        if r['status'] != 'running':
            return r
        time.sleep(1)
    return r


TOK = call('POST', B + '/api/login', {'username': 'admin', 'password': 'honey123'})['token']

# ---------- 接口 ----------
smoke = load('smoke_foundry.json')
try:
    call('POST', P + '/tests', {'script': {'name': 'bad', 'steps': [{'kind': 'nope'}]}})
    ok('剧本格式校验', False)
except urllib.error.HTTPError as e:
    ok('剧本格式校验', e.code == 400, e.read().decode()[:100])
v = call('POST', P + '/tests/validate', {'script': {'steps': [{'kind': 'assert', 'via': 'x', 'station': 'A', 'tag': 'B'}]}})
ok('validate 接口', v['errors'] and 'via' in v['errors'][0], v['errors'])
gtok = call('POST', B + '/api/login', {'username': 'guest', 'password': 'honey123'})['token']
try:
    call('POST', P + '/tests/run', {'script': smoke}, tok=gtok)
    ok('访客不能运行剧本', False)
except urllib.error.HTTPError as e:
    ok('访客不能运行剧本', e.code == 403)

tid = call('POST', P + '/tests', {'script': smoke})['id']
lst = call('GET', P + '/tests')
ok('保存剧本', any(t['id'] == tid and t['steps'] == len(smoke['steps']) for t in lst), [(t['id'], t['name']) for t in lst][:3])
msg0 = call('GET', P + '/debug/messages?since=0&limit=5')        # 先开始抓报文
ok('报文监视启动', msg0['ok'], msg0.get('msg'))
t0 = time.time()
rid = call('POST', P + f'/tests/{tid}/run')['run_id']
try:
    call('POST', P + '/tests/run', {'script': smoke})
    ok('同一工厂不能并行跑两个剧本', False)
except urllib.error.HTTPError as e:
    ok('同一工厂不能并行跑两个剧本', e.code == 409)
r = wait_run(rid)
for s in r['steps']:
    print(f"   {'✓' if s['ok'] else '✗'} {s['i']:02d} {s['desc']} — {s['msg'][:110]}")
ok('示例剧本（接口）全部通过', r['status'] == 'passed' and r['passed'] == len(smoke['steps']), f"{r['status']} {r.get('passed')}/{len(smoke['steps'])} {time.time() - t0:.0f}s")
ok('OPC UA / MQTT / MES 断言都真的走了协议', all(s['ok'] for s in r['steps'] if s['kind'] in ('assert', 'assert_mes')) and
   not any('进程内' in s['msg'] for s in r['steps']), '')
xml = call('GET', P + f'/tests/runs/{rid}/junit.xml', raw=True)
root = ET.fromstring(xml)
ok('JUnit（接口）', root.tag == 'testsuites' and root.get('tests') == str(len(smoke['steps'])) and root.get('failures') == '0', root.attrib)
hist = call('GET', P + f'/tests/{tid}/runs')
ok('运行历史', hist and hist[0]['id'] == rid and hist[0]['status'] == 'passed', hist[:1])

rid2 = call('POST', P + '/tests/run', {'script': load('expect_fail.json')})['run_id']
r2 = wait_run(rid2)
ok('故意失败的剧本：状态失败、只有 1 步失败', r2['status'] == 'failed' and r2['failed'] == 1 and r2['steps'][2]['ok'] is False, [s['msg'] for s in r2['steps']])
root2 = ET.fromstring(call('GET', P + f'/tests/runs/{rid2}/junit.xml', raw=True))
ok('JUnit 失败计数', root2.get('failures') == '1' and root2.find('.//failure') is not None, root2.attrib)

rid3 = call('POST', P + '/tests/run', {'script': load('opcua_bad_quality.json')})['run_id']
r3 = wait_run(rid3)
ok('OPC UA 坏质量剧本通过', r3['status'] == 'passed', [s['msg'] for s in r3['steps']])

time.sleep(1.5)
m = call('GET', P + f"/debug/messages?since=0&limit=2000")
mes = call('GET', P + f"/debug/messages?since=0&mes=1&limit=2000")
ok('报文监视收到点位报文', m['count'] > 50 and any(x['topic'].startswith(f'vfactory/{PID}/') and '/_' not in x['topic'] for x in m['items']),
   f"{m['count']} 条 {m['rate']}/s")
ok('报文监视收到 MES 报文', any('/_mes/event' in x['topic'] for x in mes['items']) and all('/_mes/' in x['topic'] or '_status' in x['topic'] or x['topic'].startswith('vda') for x in mes['items']),
   len(mes['items']))
f = call('GET', P + '/debug/messages?since=0&filter=CNC1&limit=50')
ok('报文过滤', f['items'] and all('CNC1' in x['topic'] or 'CNC1' in x['payload'] for x in f['items']), len(f['items']))
call('DELETE', P + f'/tests/{tid}')
ok('删除剧本', not any(t['id'] == tid for t in call('GET', P + '/tests')))

# ---------- 命令行 ----------
ports = (os.environ.get('VF_CLI_PORTS') or '14840,11883,15020').split(',')
base = [sys.executable, os.environ['VF_LAUNCHER']] if os.environ.get('VF_LAUNCHER') else [sys.executable, '-m', 'vfactory']
out = os.path.join(ROOT, 'data', 'testing_check')
os.makedirs(out, exist_ok=True)
junit = os.path.join(out, 'junit.xml')
cmd = base + ['test', 'tests/scripts/smoke_foundry.json', 'tests/scripts/expect_fail.json', '--config', 'plants/foundry-housing.yaml', '--junit', junit,
              '--json', os.path.join(out, 'result.json'), '--opcua', ports[0], '--mqtt', ports[1], '--modbus', ports[2]]
t0 = time.time()
p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=600, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
so = p.stdout.decode('utf-8', 'replace')
print('\n'.join('   ' + x for x in so.strip().split('\n')[-30:]))
if p.returncode not in (0, 1):
    print(p.stderr.decode('utf-8', 'replace')[-2000:])
ok('命令行退出码 = 1（有一个故意失败的剧本）', p.returncode == 1, f'{p.returncode} {time.time() - t0:.0f}s')
ok('命令行生成 JUnit', os.path.exists(junit))
if os.path.exists(junit):
    root = ET.parse(junit).getroot()
    suites = root.findall('testsuite')
    n_smoke = len(load('smoke_foundry.json')['steps'])
    ok('JUnit 有效：两个 testsuite、用例数和失败数正确', root.tag == 'testsuites' and len(suites) == 2 and suites[0].get('tests') == str(n_smoke)
       and suites[0].get('failures') == '0' and suites[1].get('failures') == '1' and root.get('failures') == '1',
       [(s.get('name'), s.get('tests'), s.get('failures')) for s in suites])
    ok('JUnit 每个用例有名称和耗时', all(tc.get('name') and tc.get('time') for tc in root.iter('testcase')), sum(1 for _ in root.iter('testcase')))
p2 = subprocess.run(base + ['test', 'tests/scripts/expect_fail.json', '--no-protocols', '--warmup', '0', '--junit', os.path.join(out, 'np.xml')],
                    cwd=ROOT, capture_output=True, timeout=300)
ok('命令行 --no-protocols 也能跑', p2.returncode == 1 and ET.parse(os.path.join(out, 'np.xml')).getroot().get('failures') == '1', p2.returncode)
p4 = subprocess.run(base + ['test', 'tests/scripts/smoke_foundry.json', '--no-protocols', '--junit', os.path.join(out, 'np2.xml')], cwd=ROOT, capture_output=True, timeout=300)
r4 = ET.parse(os.path.join(out, 'np2.xml')).getroot() if os.path.exists(os.path.join(out, 'np2.xml')) else None
ok('--no-protocols：协议断言记为跳过、整体通过（退出码 0）', p4.returncode == 0 and r4 is not None and r4.get('failures') == '0' and int(r4.get('skipped') or 0) > 0
   and r4.find('.//skipped') is not None, (p4.returncode, r4.attrib if r4 is not None else None))
p3 = subprocess.run(base + ['test', 'tests/scripts/nope.json'], cwd=ROOT, capture_output=True, timeout=60)
ok('剧本文件不存在 → 退出码 2', p3.returncode == 2, p3.returncode)

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过')
sys.exit(0 if n == len(res) else 1)
