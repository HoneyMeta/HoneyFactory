# 4.6 老师改过评分的 PLC 课：实时检查表 / 演示 / 自动测试预检和最终评分用同一份改动（B 机，先启动 serve）：
#   python tests/coach_overlay_check.py   （VF_URL 默认 http://127.0.0.1:8800）
# 老师在课程编辑器里做一门课：PLC 课「电机启停自锁」只选 3 个评分项，再加一条自加检查（"按 START → 1 秒内 M1_RUN 得电"）；
# 发布给班级。学生进沙箱：检查表只有这 4 项（不是场景原来的 6 项）；下载参考程序后自动测试预检的明细、提交评分的明细都是这 4 项，
# 检查表、预检、评分逐项一致；"演示"能演示自加的那一项。
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import os
import sys
import time
import urllib.request

B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:400])


def call(m, u, body=None, tok='', timeout=120):
    req = urllib.request.Request(B + u, method=m, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + tok} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or 'null')
    except urllib.error.HTTPError as e:
        return {'_status': e.code, '_body': e.read().decode()[:300]}


def login(u, p):
    return call('POST', '/api/login', {'username': u, 'password': p})['token']


stamp = str(int(time.time()))[-6:]
A = login('admin', 'honey123')
users = [u['username'] for u in call('GET', '/api/admin/users', tok=A)['users']]
if 'co_teacher' not in users:
    call('POST', '/api/admin/users', {'username': 'co_teacher', 'name': '评分老师', 'role': 'teacher', 'password': 'teach123'}, tok=A)
T = login('co_teacher', 'teach123')
cls = call('POST', '/api/teach/classes', {'name': f'评分改动测试班 {stamp}'}, tok=T)
stu = f'co{stamp}'
call('POST', f"/api/teach/classes/{cls['id']}/roster", {'csv': f'账号,姓名\n{stu},评分同学\n', 'default_password': '123456'}, tok=T)
S = login(stu, '123456')

sc = call('GET', '/api/teach/scenes/s01_motor_latch', tok=T)
keys = [r['key'] for r in (sc.get('rules') or sc.get('scoring', {}).get('rules') or [])]
if not keys:
    keys = ['start_ok', 'latch_ok', 'stop_ok', 'stop_priority', 'overload_ok', 'lamp_ok']
RUBRIC = [k for k in keys if k in ('start_ok', 'latch_ok', 'stop_ok')] or keys[:3]
lesson = {'id': 'l1', 'title': '电机启停（老师改过评分）', 'kind': 'cell', 'scene': 's01_motor_latch', 'rubric': RUBRIC,
          'tests': [{'t': 30.0, 'press': 'START'}, {'t': 30.6, 'release': 'START'}, {'t': 31.5, 'key': 'x_again', 'check': {'out': 'M1_RUN', 'eq': True}, 'desc': '停了以后再按启动没有转'}],
          'extra_rules': [{'key': 'x_again', 'label': '停了以后再按启动又能转', 'op': '==', 'value': 1, 'weight': 10}]}
c = call('POST', '/api/teach/authoring', {'name': f'改评分小课 {stamp}'}, tok=T)
cid = c['id']
course = c['course']
course['chapters'][0]['lessons'] = [lesson]
sv = call('PUT', f'/api/teach/authoring/{cid}', {'course': course}, tok=T)
ok('课程编辑器保存：PLC 课的评分改动没有错误', sv.get('errors') == 0, sv.get('issues'))
pb = call('POST', f'/api/teach/authoring/{cid}/publish', tok=T)
ok('课程发布（冻结一个版本）', pb.get('version', 0) >= 1, pb)
r = call('POST', f'/api/teach/courses/{cid}/publish', {'class_id': cls['id'], 'open_all': True}, tok=T)
ok('发布给班级', not r.get('_status'), r)
asg = [a for a in call('GET', f"/api/teach/assignments?class_id={cls['id']}", tok=T) if a.get('course') == cid]
ok('班级里有这一课', len(asg) == 1, [a.get('lesson') for a in asg])
aid = asg[0]['id']
sb = call('POST', f'/api/teach/assignments/{aid}/sandbox', {}, tok=S)
pid = sb['pid']
want = RUBRIC + ['x_again']
cl = None
for _ in range(60):
    v = call('GET', f'/api/p/{pid}/coach?since=0', tok=S)
    cl = v.get('checklist')
    if cl and not cl.get('preparing') and cl.get('items'):
        break
    time.sleep(1)
got = [i['key'] for i in (cl or {}).get('items') or []]
ok('实时检查表：只有老师选的评分项 + 自加的检查（不是场景原来的全部）', sorted(got) == sorted(want), f'{got} / 想要 {want} / 场景原有 {keys}')
lab = {i['key']: i.get('label') for i in (cl or {}).get('items') or []}
ok('自加检查在检查表里有名字', lab.get('x_again') == '停了以后再按启动又能转', lab)

ref = sc.get('reference', {}).get('ld')
call('POST', f'/api/p/{pid}/cells/PLC1/program/download', {'program': ref, 'cold': True}, tok=S)
time.sleep(2)
au = call('POST', f'/api/p/{pid}/coach/autotest', tok=S, timeout=320)
ak = sorted(d['key'] for d in au.get('details') or [])
ok('自动测试预检：明细就是这 4 项，参考程序满分', ak == sorted(want) and au.get('score') == 100, f"{ak} {au.get('score')} {au.get('error')}")
tr = call('POST', f'/api/p/{pid}/coach/trial', {'key': 'x_again'}, tok=S)
ok('"演示"能演示自加的检查', tr.get('ok') and tr.get('seconds', 0) > 0, tr)
call('POST', f'/api/p/{pid}/coach/stop_trial', tok=S)
sub = call('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S, timeout=320)
for _ in range(120):
    task = call('GET', f'/api/teach/assignments/{aid}/task', tok=S)
    s0 = (task.get('submissions') or [{}])[0]
    if s0.get('status') not in ('queued', 'running', None):
        break
    time.sleep(2)
sk = sorted(d['key'] for d in s0.get('details') or [])
ok('提交评分：明细和检查表、预检是同样的 4 项，满分', sk == sorted(want) and s0.get('score') == 100, f"{sk} {s0.get('score')} {s0.get('status')}")
bad = [n for n, cnd in res if not cnd]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过' + ('；失败：' + '、'.join(bad) if bad else ''))
sys.exit(1 if bad else 0)
