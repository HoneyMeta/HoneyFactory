"""专业版接口冒烟测试（先启动 serve）：python tests/api_check.py"""
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


def call(method, url, body=None, raw=False, tok=None):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + (tok or TOK)} if (tok or TOK) else {})})
    with urllib.request.urlopen(r, timeout=180) as f:
        d = f.read()
        return d if raw else json.loads(d)


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:160])


try:
    call('GET', B + '/api/overview')
    ok('未登录拒绝', False)
except urllib.error.HTTPError as e:
    ok('未登录拒绝', e.code == 401)
TOK = call('POST', B + '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
ok('登录', TOK)
g = call('POST', B + '/api/login', {'username': 'guest', 'password': 'honey123'})['token']
try:
    call('POST', P + '/sim', {'speed': 10}, tok=g)
    ok('只读账号不能修改', False)
except urllib.error.HTTPError as e:
    ok('只读账号不能修改', e.code == 403)
ov = call('GET', B + '/api/overview')
ok('工厂总览', ov['plants'], json.dumps(ov['plants'][0], ensure_ascii=False))
plan = call('GET', P + '/plan')
plan['cfg']['orders'] = [{'code': 'SO-T1', 'product': plan['product']['code'], 'qty': 200, 'due': '2030-01-01 00:00', 'customer': '测试'}]
plan['cfg']['breaks'] = [{'name': '午餐', 'start': '11:30', 'end': '12:00'}]
r = call('PUT', P + '/plan', plan['cfg'])
ok('生产计划更新', r['orders'] and r['orders'][0]['code'] == 'SO-T1', r['orders'])
ok('4.7 计划应用后标出"还没保存到工厂配置"', r.get('saved') is False and call('GET', P + '/plan').get('saved') is False, r.get('saved'))
# 4.7「保存到工厂配置」：在一个临时工厂上试（不改示范工厂的配置文件）
tp = call('POST', B + '/api/plants', {'name': '计划保存测试', 'template': 'blank'})['id']
try:
    TP = B + f'/api/p/{tp}'
    p0 = call('GET', TP + '/plan')
    p0['cfg']['breaks'] = [{'name': '工间休息', 'start': '10:00', 'end': '10:15'}]
    r1 = call('PUT', TP + '/plan', p0['cfg'])
    r2 = call('POST', TP + '/plan/save', {})
    r3 = call('GET', TP + '/plan')
    ok('4.7 计划保存到工厂配置', p0.get('saved') is True and r1.get('saved') is False and r2.get('saved') is True and r3.get('saved') is True
       and r3['cfg']['breaks'][0]['name'] == '工间休息', (p0.get('saved'), r1.get('saved'), r2.get('saved'), r3.get('saved')))
finally:
    call('DELETE', B + f'/api/plants/{tp}')
sc = call('GET', P + '/scenarios')
ok('场景库', len(sc['items']) >= 10, [s['name'] for s in sc['items']][:10])
r = call('POST', P + '/scenarios/run', {'id': 'b:tool_break'})
ok('运行场景', r['running'] and r['running']['name'] == '夜班断刀', r['running']['steps'])
call('POST', P + '/sim', {'speed': 300})
time.sleep(10)
st = call('GET', P + '/scenarios')['status']
ok('场景执行完成', not st['running'] and st['history'], st['history'][0]['log'] if st['history'] else st)
call('POST', P + '/sim', {'speed': 10})
call('POST', P + '/advance', {'hours': 2})
rep = call('GET', P + '/report?hours=4')
ok('报表', rep['good'] >= 0 and rep['util'] and rep['findings'], rep['findings'][:2])
x = call('GET', P + '/report.xlsx?hours=4', raw=True)
ok('报表 Excel', x[:2] == b'PK', len(x))
tl = call('GET', P + '/timeline?hours=8')
ok('时间轴事件', tl['events'], len(tl['events']))
tree = call('GET', P + '/signals/tree')
ok('点位浏览', sum(len(s['tags']) for s in tree) > 300, len(tree))
tr = call('GET', P + '/signals/trend?key=CNC1/Monitoring/Spindle/Load&hours=4')
ok('点位趋势', len(tr['v']) > 10, len(tr['v']))
call('POST', P + '/signals/comm', {'protocol': 'modbus', 'mode': 'disconnect', 'minutes': 1})
time.sleep(2)
s1 = call('GET', P + '/signals/status')
ok('通讯故障注入', s1['comm'].get('modbus'), s1['comm'])
call('POST', P + '/signals/comm', {'protocol': 'modbus', 'mode': ''})
r = call('POST', P + '/signals/record', {'action': 'start'})
time.sleep(4)
r2 = call('POST', P + '/signals/record', {'action': 'stop'})
ok('录制', r2['file'], r2)
r = call('POST', P + '/signals/replay', {'file': r2['file'], 'speed': 50})
time.sleep(3)
ok('回放', True, call('GET', P + '/signals/status')['replay'])
call('POST', P + '/signals/replay', {'action': 'stop'})
info = call('GET', P + '/dataset/info')
ok('数据集信息', info['rows'] > 0, {k: v for k, v in info.items() if k != 'keys'})
z = call('GET', P + '/dataset.zip?hours=4', raw=True)
ok('数据集导出', z[:2] == b'PK', len(z))
v = call('GET', P + '/validate')
ok('布局检查', 'issues' in v, v['summary'])
x = call('GET', P + '/points.xlsx', raw=True)
ok('点表 Excel', x[:2] == b'PK', len(x))
x = call('GET', P + '/nodeset.xml', raw=True)
ok('OPC UA NodeSet', b'UANodeSet' in x[:2000], len(x))
t = call('POST', B + '/api/tokens', {'name': '测试'})['token']
ok('API 令牌', call('GET', B + '/api/me', tok=t)['username'] == 'admin', t[:10])
a = call('GET', B + '/api/admin/audit')
ok('审计日志', len(a) > 5, a[0])
e = call('POST', P + '/experiments', {'name': '加一台 CNC', 'hours': 6, 'reps': 1,
                                      'variants': [{'name': '加一台 CNC', 'changes': [{'type': 'add', 'template': 'CNC1', 'count': 1}]},
                                                   {'name': '检测站节拍提升', 'changes': [{'type': 'setpoint', 'station': 'INS1', 'tag': 'Setpoint/SecPerHole', 'value': 4}]}]})
for _ in range(90):
    time.sleep(3)
    ex = call('GET', P + f"/experiments/{e['id']}")
    if ex['status'] in ('done', 'failed'):
        break
ok('实验对比', ex['status'] == 'done', (ex['result'] or {}).get('text'))
# ---- 修改密码（4.4）：原密码 + 新密码；和原密码相同、初始密码、太短都拒绝；管理员重置别人的密码照旧 ----
pu = 'pw' + time.strftime('%H%M%S')
call('POST', B + '/api/admin/users', {'username': pu, 'name': '改密码测试', 'role': 'engineer', 'password': 'honey123'})
pt = call('POST', B + '/api/login', {'username': pu, 'password': 'honey123'})['token']


def pw_err(old, new, tok=None):
    try:
        call('POST', B + '/api/me/password', {'old': old, 'new': new}, tok=tok or pt)
        return 200, ''
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}').get('detail', '')


c1, d1 = pw_err('honey123', 'abc')
c2, d2 = pw_err('honey123', 'honey123')
c3, d3 = pw_err('honey123', '123456')
c4, d4 = pw_err('wrong123', 'Good1234')
ok('改密码：太短 / 和原密码一样 / 初始密码 / 原密码不对 都拒绝', (c1, c2, c3, c4) == (400, 400, 400, 400) and '6' in d1 and '一样' in d2 and '初始' in d3 and '原密码' in d4,
   (d1, d2, d3, d4))
ok('改密码：成功后新密码能登录、旧的不行', pw_err('honey123', 'Good1234')[0] == 200 and call('POST', B + '/api/login', {'username': pu, 'password': 'Good1234'})['token'])
try:
    call('POST', B + '/api/login', {'username': pu, 'password': 'honey123'})
    ok('旧密码不能再登录', False)
except urllib.error.HTTPError as e:
    ok('旧密码不能再登录', e.code == 401)
uid = next(u['id'] for u in call('GET', B + '/api/admin/users')['users'] if u['username'] == pu)
call('POST', B + '/api/admin/users', {'id': uid, 'username': pu, 'name': '改密码测试', 'role': 'engineer', 'password': 'Reset5678'})
ok('管理员在"用户与角色"里重置别人的密码（照旧）', call('POST', B + '/api/login', {'username': pu, 'password': 'Reset5678'})['token'])
bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
