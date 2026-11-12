"""作业包 .vfhw 与服务器接口（设计 4.2 第 4、5 节）的接口测试（先启动 serve）：python tests/package_check.py
- 沙箱导出作业包 → submit_package：服务器重新评分 = 同一程序的沙箱提交分；包里谎报的 local_score 不算
- 坏包：哈希不对、超过 5 MB、不是 zip、交错作业、类型不对 → 400 中文原因
- 截止时间 / 提交次数上限照常；老师替学生导入（来源"导入"）；下载提交的作业包；打开复核沙箱 sb-review-<提交号>（学生进不去，老师能运行不能改）
- /task?client=1 给客户端的完整定义；产线课（模型）作业包同样重新评分
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from vfactory.teach import package as pk  # noqa: E402

B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
STAMP = time.strftime('%m%d%H%M%S')
res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240], flush=True)


def call(method, url, body=None, tok='', raw=False, data=None):
    h = {'Authorization': 'Bearer ' + tok} if tok else {}
    if data is not None:
        h['Content-Type'] = 'application/octet-stream'
        payload = data
    else:
        h['Content-Type'] = 'application/json'
        payload = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + url, method=method, data=payload, headers=h)
    with urllib.request.urlopen(r, timeout=400) as f:
        d = f.read()
        return d if raw else json.loads(d)


def err(method, url, body=None, tok='', data=None):
    try:
        call(method, url, body, tok, raw=True, data=data)
        return 200, ''
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}').get('detail', '')


def login(u, p):
    return call('POST', '/api/login', {'username': u, 'password': p})['token']


admin = login('admin', 'honey123')
if 'pk_teacher' not in {u['username'] for u in call('GET', '/api/admin/users', tok=admin)['users']}:
    call('POST', '/api/admin/users', {'username': 'pk_teacher', 'name': '包老师', 'role': 'teacher', 'password': 'teach123'}, tok=admin)
T = login('pk_teacher', 'teach123')
n0 = STAMP[-6:]
U1, U2, U3 = f'pk{n0}a', f'pk{n0}b', f'pk{n0}c'
cid = call('POST', '/api/teach/classes', {'name': f'作业包班 {STAMP}'}, tok=T)['id']
call('POST', f'/api/teach/classes/{cid}/roster', {'csv': f'{U1},甲\n{U2},乙'}, tok=T)
cid2 = call('POST', '/api/teach/classes', {'name': f'别的班 {STAMP}'}, tok=T)['id']
call('POST', f'/api/teach/classes/{cid2}/roster', {'csv': f'{U3},丙'}, tok=T)
S1, S2, S3 = (login(u, '123456') for u in (U1, U2, U3))

aid = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's01_motor_latch', 'title': '启停自锁（作业包）', 'max_subs': 4}, tok=T)['id']
aid_other = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's02_fwd_rev', 'title': '正反转（别的作业）'}, tok=T)['id']
ref = call('GET', '/api/teach/scenes/s01_motor_latch', tok=T)['reference']['st']

# ---------- 客户端拉作业：/task?client=1 ----------
tk = call('GET', f'/api/teach/assignments/{aid}/task?client=1', tok=S1)
c = tk.get('client') or {}
ok('/task?client=1 给本机建沙箱的完整定义', c.get('kind') == 'cell' and c.get('scene') == 's01_motor_latch' and isinstance(c.get('start_model'), dict)
   and c['start_model'].get('blocks') and c['settings']['max_subs'] == 4 and c['package_format']['format'] == 'vfhw', list(c))
ok('不带 client 时没有这一段', 'client' not in call('GET', f'/api/teach/assignments/{aid}/task', tok=S1))

# ---------- 沙箱提交 vs 作业包提交：同一个程序同一个分 ----------
c0, d0 = err('GET', f'/api/teach/assignments/{aid}/package', tok=S1)
ok('还没进沙箱不能导出', c0 == 400 and '沙箱' in d0, d0)
sb = call('POST', f'/api/teach/assignments/{aid}/sandbox', tok=S1)
call('POST', f"/api/p/{sb['pid']}/cells/{sb['bid']}/program/download", {'program': ref}, tok=S1)
s_sb = call('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S1)
data = call('GET', f'/api/teach/assignments/{aid}/package', tok=S1, raw=True)
p = pk.read(data)
ok('导出作业包：manifest、程序、校验值', p.manifest['format'] == 'vfhw' and p.manifest['assignment_id'] == aid and p.programs
   and set(p.manifest['sha256']) == set(p.manifest['files']) and p.manifest['local_score']['score'] == s_sb['score'], p.summary())
s_pk = call('POST', f'/api/teach/assignments/{aid}/submit_package', tok=S1, data=data)
ok('作业包提交：服务器重新评分，和沙箱提交同分', s_pk['score'] == s_sb['score'] == 100 and s_pk['source'] == 'client' and s_pk['has_package'],
   (s_sb['score'], s_pk['score'], s_pk['source']))
ok('作业包提交返回和沙箱提交同样的结构', set(s_sb) <= set(s_pk) | {'local_score'}, sorted(set(s_sb) - set(s_pk)))
s_b64 = call('POST', f'/api/teach/assignments/{aid}/submit_package', {'data': __import__('base64').b64encode(data).decode()}, tok=S1)
ok('也接受 {data: base64}', s_b64['score'] == 100)

# ---------- 谎报本机分：服务器不信 ----------
bad = dict(ref, source=ref['source'].replace('(START OR M1_RUN)', 'START'))
man = dict(p.manifest)
for k in ('files', 'sha256', 'format', 'version', 'created', 'client_version'):
    man.pop(k, None)
man['local_score'] = {'score': 100, 'max': 100, 'details': []}
fake = pk.build(man, {'CELL1': bad})
s_fake = call('POST', f'/api/teach/assignments/{aid}/submit_package', tok=S1, data=fake)
ok('包里写 100 分没用：服务器按程序重新评分', s_fake['score'] < 100 and s_fake['local_score'] == 100, (s_fake['score'], s_fake['local_score']))

# ---------- 次数上限 ----------
c, d = err('POST', f'/api/teach/assignments/{aid}/submit_package', tok=S1, data=data)
ok('提交次数上限对作业包同样有效', c == 400 and '用完' in d, d)

# ---------- 坏包 ----------
zb = io.BytesIO()
with zipfile.ZipFile(io.BytesIO(data)) as zi, zipfile.ZipFile(zb, 'w') as zo:
    for n in zi.namelist():
        b = zi.read(n)
        if n.startswith('program/'):
            b = b.replace(b'M1_RUN', b'M1_RUX', 1)
        zo.writestr(n, b)
c, d = err('POST', f'/api/teach/assignments/{aid_other}/submit_package', tok=S2, data=zb.getvalue())
ok('文件改过、校验不对 → 拒收', c == 400 and '校验' in d, d)
c, d = err('POST', f'/api/teach/assignments/{aid_other}/submit_package', tok=S2, data=b'PK' + os.urandom(6 * 1024 * 1024))
ok('超过 5 MB → 拒收', c in (400, 413) and 'MB' in d, (c, d))
c, d = err('POST', f'/api/teach/assignments/{aid_other}/submit_package', tok=S2, data=b'hello')
ok('不是 zip → 拒收', c == 400 and '作业包' in d, d)
c, d = err('POST', f'/api/teach/assignments/{aid_other}/submit_package', tok=S2, data=data)
ok('交到别的作业 → 拒收', c == 400 and str(aid) in d, d)
man2 = dict(man, assignment_id=None, scene='s02_fwd_rev', kind='plant')
c, d = err('POST', f'/api/teach/assignments/{aid_other}/submit_package', tok=S2, data=pk.build(man2, None, {'plant': {'name': 'x'}, 'blocks': []}))
ok('类型对不上（产线包交到 PLC 课）→ 拒收', c == 400 and '类型' in d, d)
c, d = err('POST', f'/api/teach/assignments/{aid}/submit_package', tok=S3, data=data)
ok('别的班的学生不能交', c == 403, d)

# ---------- 截止时间 ----------
aid_due = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's01_motor_latch', 'title': '已截止', 'due': '2020-01-01 08:00', 'allow_late': False}, tok=T)['id']
m3 = dict(man, assignment_id=aid_due)
c, d = err('POST', f'/api/teach/assignments/{aid_due}/submit_package', tok=S2, data=pk.build(m3, {'CELL1': ref}))
ok('过了截止时间（不收迟交）→ 拒收', c == 400 and '截止' in d, d)

# ---------- 老师导入 ----------
c, d = err('POST', f'/api/teach/assignments/{aid}/students/{U2}/import_package', tok=S1, data=data)
ok('学生不能用导入接口', c == 403, d)
c, d = err('POST', f'/api/teach/assignments/{aid}/students/{U3}/import_package', tok=T, data=data)
ok('导入给不在班里的学生 → 拒绝', c == 400 and '不在' in d, d)
im = call('POST', f'/api/teach/assignments/{aid}/students/{U2}/import_package', tok=T, data=data)
ok('老师替学生导入：记为该生的提交，来源"导入"，服务器评分', im['username'] == U2 and im['source'] == 'import' and im['score'] == 100 and U1 in (im['comment'] or ''),
   (im['source'], im['score'], im['comment']))
subs = call('GET', f'/api/teach/assignments/{aid}/submissions?username={U1}', tok=T)
ok('提交列表带来源', [x['source'] for x in subs][::-1] == ['sandbox', 'client', 'client', 'client'], [x['source'] for x in subs])

# ---------- 下载提交的作业包 ----------
sid_client = s_pk['id']
got = call('GET', f'/api/teach/submissions/{sid_client}/package', tok=T, raw=True)
ok('下载客户端提交的作业包：和交上来的一模一样', got == data)
got2 = pk.read(call('GET', f"/api/teach/submissions/{s_sb['id']}/package", tok=T, raw=True))
ok('沙箱提交也能下载作业包（用当时的程序快照现打包）', got2.programs.get('CELL1', {}).get('source') == ref['source'] and got2.manifest['source'] == 'sandbox')
ok('学生不能下载提交的作业包', err('GET', f'/api/teach/submissions/{sid_client}/package', tok=S1)[0] == 403)

# ---------- 复核沙箱 ----------
sid_fake = s_fake['id']
op = call('POST', f'/api/teach/submissions/{sid_fake}/open', {}, tok=T)
rp = op['pid']
ok('打开运行：复核沙箱 sb-review-<提交号>', rp == f'sb-review-{sid_fake}' and op['review'] and op['bid'], op)
prg = call('GET', f"/api/p/{rp}/cells/{op['bid']}/program", tok=T)
ok('复核沙箱里装的是那次提交的程序', 'START AND' in prg['program']['source'].replace('\n', ' ') or 'M1_RUN := START' in prg['program']['source'], prg['program']['source'][:120])
ok('学生进不了复核沙箱（包括交作业的本人）', err('GET', f'/api/p/{rp}/meta', tok=S1)[0] == 403 and err('GET', f'/api/p/{rp}/meta', tok=S2)[0] == 403)
c, d = err('POST', f"/api/p/{rp}/cells/{op['bid']}/program/download", {'program': ref}, tok=T)
ok('复核沙箱里老师不能改程序', c == 403 and '复核' in d, d)
c1, _ = err('POST', f'/api/p/{rp}/ctl', {'action': 'play'}, tok=T)
c2, _ = err('POST', f"/api/p/{rp}/station/{op['bid']}/write", {'tag': 'Panel/START', 'value': True}, tok=T)
ok('复核沙箱里老师可以运行、按操作台', c1 == 200 and c2 == 200, (c1, c2))
T2 = None
if 'pk_teacher2' not in {u['username'] for u in call('GET', '/api/admin/users', tok=admin)['users']}:
    call('POST', '/api/admin/users', {'username': 'pk_teacher2', 'name': '别的老师', 'role': 'teacher', 'password': 'teach123'}, tok=admin)
T2 = login('pk_teacher2', 'teach123')
ok('别班老师打不开、进不去', err('POST', f'/api/teach/submissions/{sid_fake}/open', {}, tok=T2)[0] == 403 and err('GET', f'/api/p/{rp}/meta', tok=T2)[0] == 403)
pg = call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)
ok('复核沙箱不影响学生的沙箱状态', next(r for r in pg['rows'] if r['username'] == U1)['sandbox'] != 'none')

# ---------- 产线课（模型）作业包 ----------
call('POST', '/api/teach/courses/machining/publish', {'class_id': cid, 'open_all': True}, tok=T)
lessons = [a for a in call('GET', f'/api/teach/assignments?class_id={cid}', tok=T) if a.get('course') == 'machining']
lp = next(a for a in sorted(lessons, key=lambda a: a['seq']) if a['kind'] == 'plant')
call('POST', f"/api/teach/assignments/{lp['id']}/sandbox", tok=S2)
t0 = time.time()
sp_sb = call('POST', f"/api/teach/assignments/{lp['id']}/submit", {}, tok=S2)
pdata = call('GET', f"/api/teach/assignments/{lp['id']}/package", tok=S2, raw=True)
pp = pk.read(pdata)
ok('产线课导出：模型 model.yaml', pp.model and pp.model.get('blocks') and not pp.programs and pp.manifest['kind'] == 'plant', pp.summary())
sp_pk = call('POST', f"/api/teach/assignments/{lp['id']}/submit_package", tok=S2, data=pdata)
ok('产线课作业包重新评分 = 沙箱提交分', sp_pk['score'] == sp_sb['score'] and sp_pk['source'] == 'client', (sp_sb['score'], sp_pk['score'], f'{time.time() - t0:.0f}s'))
op2 = call('POST', f"/api/teach/submissions/{sp_pk['id']}/open", {}, tok=T)
ok('产线课提交也能打开运行（复核沙箱用学生的模型）', op2['pid'] == f"sb-review-{sp_pk['id']}" and call('GET', f"/api/p/{op2['pid']}/meta", tok=T))

# 4.4：作业包版本 2（提交工厂）+ 向下兼容  —— 插到 package_check.py 结尾的统计之前
import base64 as _b64  # noqa: E402,F401
from vfactory import courses as _courses  # noqa: E402
from vfactory.plc.migrate import migrate_model as _migrate  # noqa: E402
from vfactory.server import read_yaml as _read_yaml  # noqa: E402
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ok('只用到版本 1 功能的包（PLC 课、产线课）仍写版本 1：老服务器照样能收', p.manifest['version'] == 1 and pp.manifest['version'] == 1,
   (p.manifest['version'], pp.manifest['version']))


def _rezip(raw, edit):
    """改 manifest（模拟别的版本的客户端）。"""
    zb = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zi, zipfile.ZipFile(zb, 'w') as zo:
        for nm in zi.namelist():
            b = zi.read(nm)
            if nm == 'manifest.json':
                m = json.loads(b)
                edit(m)
                b = json.dumps(m, ensure_ascii=False).encode()
            zo.writestr(nm, b)
    return zb.getvalue()


v1 = _rezip(data, lambda m: m.update(version=1, client_version='4.2.0'))
aid_v1 = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's01_motor_latch', 'title': '老客户端交的'}, tok=T)['id']
ok('4.2/4.3 客户端交的版本 1 包：新服务器照收、照评分', call('POST', f'/api/teach/assignments/{aid_v1}/submit_package', tok=S2,
                                                     data=_rezip(v1, lambda m: m.update(assignment_id=aid_v1)))['score'] == 100)
c, d = err('POST', f'/api/teach/assignments/{aid_v1}/submit_package', tok=S2, data=_rezip(v1, lambda m: m.update(assignment_id=aid_v1, version=3)))
ok('比服务器新的版本（3）→ 拒收并提示升级', c == 400 and '升级' in d, d)

model_mc = _courses.plant_model(_courses.get_lesson('machining', 'm01')[1])
motor = _read_yaml(os.path.join(ROOT, 'templates', 'cells', 'motor.yaml'))
_migrate(motor)
mprog = {b['id']: b['params']['program'] for b in motor['blocks'] if b['type'] == 'plc' and (b.get('params') or {}).get('program')}
checks = [{'kind': 'valid'}, {'kind': 'block', 'type': 'plc', 'min': 1}, {'kind': 'plc_control', 'min': 1}, {'kind': 'good', 'min': 1}]
c, d = err('POST', '/api/teach/assignments', {'class_id': cid, 'kind': 'factory', 'title': '坏检查', 'checks': [{'kind': 'block', 'type': 'nosuch'}]}, tok=T)
ok('发布提交工厂作业：检查项不对 → 中文提示', c == 400 and 'nosuch' in d, d)
fa = call('POST', '/api/teach/assignments', {'class_id': cid, 'kind': 'factory', 'title': '设计一座小工厂', 'brief_md': '## 要求\n至少一台 PLC',
                                              'checks': checks, 'hours': 1, 'due': '2030-01-01 18:00'}, tok=T)['id']
fm = call('POST', '/api/teach/assignments', {'class_id': cid, 'kind': 'factory', 'title': '只由老师打分', 'brief_md': '随便搭'}, tok=T)['id']
tf = call('GET', f'/api/teach/assignments/{fa}/task?client=1', tok=S1)
ok('学生看到提交工厂作业：要求 + 自动检查（评分标准）+ 客户端用的 spec', tf['kind'] == 'factory' and len(tf['scene']['rules']) == 4
   and '至少一台 PLC' in tf['scene']['brief_md'] and tf['client']['settings']['spec']['checks'] == checks, [r['label'] for r in tf['scene']['rules']])
ok('我的作业里有它（类型 factory）', any(x['id'] == fa and x['kind'] == 'factory' for x in call('GET', '/api/teach/my', tok=S1)))
c, d = err('POST', f'/api/teach/assignments/{fa}/submit', {'plant': 'local-x'}, tok=S1)
ok('网页端学生不能直接交（要在客户端里选"我的工厂"）', c == 400 and '客户端' in d, d)
c, d = err('GET', '/api/client/myplants', tok=S1)
ok('服务器上没有"我的工厂"接口', c == 404, d)


def _fpkg(model, programs, aid_, who=U1):
    meta = {'kind': 'factory', 'assignment_id': aid_, 'title': (model.get('plant') or {}).get('name'), 'student': {'username': who, 'name': who},
            'plant': {'id': 'local-test', 'name': (model.get('plant') or {}).get('name'), 'blocks': len(model.get('blocks') or [])}}
    return pk.build(meta, programs, model)


f1 = _fpkg(model_mc, {}, fa)
ok('提交工厂的包写版本 2，PLC 程序按 PLC 块编号存', pk.read(f1).manifest['version'] == 2
   and set(pk.read(_fpkg(motor, mprog, fa)).programs) == set(mprog), (pk.read(f1).manifest['version'], list(mprog)))
c, d = err('POST', f'/api/teach/assignments/{fa}/submit_package', tok=S1, data=_rezip(f1, lambda m: m.update(version=1)))
ok('提交工厂的包写成版本 1 → 拒收', c == 400 and '版本 2' in d, d)
c, d = err('POST', f'/api/teach/assignments/{fa}/submit_package', tok=S1, data=data)
ok('PLC 课的包交到提交工厂作业 → 拒收', c == 400 and ('类型' in d or '作业' in d), d)
r1 = call('POST', f'/api/teach/assignments/{fa}/submit_package', tok=S1, data=f1)
det1 = {d_['label']: d_['ok'] for d_ in r1['details']}
ok('服务器自动检查（没有 PLC 的产线）：模型对、有合格品，没有 PLC → 50 分', r1['score'] == 50 and r1['status'] == 'scored' and r1['source'] == 'client'
   and sum(det1.values()) == 2, det1)
r2 = call('POST', f'/api/teach/assignments/{fa}/submit_package', tok=S2, data=_fpkg(motor, mprog, fa, U2))
ok('有 PLC 控制单元的工厂：PLC 两项都过（没有出口所以合格品 0）→ 75 分', r2['score'] == 75, [(d_['label'], d_['ok'], d_['value']) for d_ in r2['details']])
again = call('POST', f'/api/teach/assignments/{fa}/submit_package', tok=S1, data=f1)
ok('同一座工厂再交一次：结果一样（确定性）', again['score'] == r1['score'] and [d_['value'] for d_ in again['details']] == [d_['value'] for d_ in r1['details']])
lst = call('GET', f'/api/teach/assignments/{fa}/submissions', tok=T)
ok('老师的提交列表：带交的是哪座工厂', lst and all(x.get('plant') and x['plant']['blocks'] for x in lst), [(x['username'], x.get('plant', {}).get('name')) for x in lst])
opf = call('POST', f"/api/teach/submissions/{r2['id']}/open", {}, tok=T)
pl_id = list(mprog)[0]
prg = call('GET', f"/api/p/{opf['pid']}/cells/{pl_id}/program", tok=T)
ok('老师打开运行：复核沙箱里是学生的工厂 + 他的 PLC 程序', opf['kind'] == 'factory' and opf['pid'] == f"sb-review-{r2['id']}"
   and prg['program']['source'] == mprog[pl_id]['source'], opf['pid'])
ok('学生进不了提交工厂的复核沙箱', err('GET', f"/api/p/{opf['pid']}/meta", tok=S2)[0] == 403)
dl = pk.read(call('GET', f"/api/teach/submissions/{r2['id']}/package", tok=T, raw=True))
ok('下载提交的工厂包：版本 2，模型 + 程序', dl.manifest['kind'] == 'factory' and dl.manifest['version'] == 2 and dl.programs.get(pl_id), dl.summary())
rv = call('POST', f"/api/teach/submissions/{r1['id']}/review", {'score': 88, 'comment': '布局清楚，下次加一台 PLC'}, tok=T)
ok('老师给分 + 评语：就是成绩（覆盖自动检查分）', rv['score'] == 88 and rv['status'] == 'reviewed', (rv['score'], rv['status']))
tk1 = call('GET', f'/api/teach/assignments/{fa}/task', tok=S1)
ok('学生看到老师给的分和评语', tk1['best'] == 88 and any(x['comment'] == '布局清楚，下次加一台 PLC' and x['score'] == 88 for x in tk1['submissions']), tk1['best'])
g = call('GET', f'/api/teach/classes/{cid}/gradebook', tok=T)
col = g['head'].index('设计一座小工厂')
ok('成绩册里是老师给的分', next(r for r in g['rows'] if r[0] == U1)[col] == 88, next(r for r in g['rows'] if r[0] == U1)[col])
rm = call('POST', f'/api/teach/assignments/{fm}/submit_package', tok=S1, data=_fpkg(model_mc, {}, fm))
ok('没有自动检查的工厂作业：已收到、等老师评分（没有自动分）', rm['status'] == 'submitted' and rm['score'] is None and rm['auto_score'] is None, (rm['status'], rm['score']))
pgm = call('GET', f'/api/teach/assignments/{fm}/progress', tok=T)
ok('教学控制台：这个学生"待评分"', next(r for r in pgm['rows'] if r['username'] == U1)['state'] == '待评分', pgm['counts'])
wt = call('GET', f'/api/teach/assignments/{fm}/students/{U1}/watch', tok=T)
ok('提交工厂作业没有沙箱：旁观给说明', wt['exists'] is False and wt['kind'] == 'factory' and '提交与复核' in wt['msg'], wt['msg'])
call('POST', f"/api/teach/submissions/{rm['id']}/review", {'score': 92, 'comment': '很好'}, tok=T)
pgm2 = call('GET', f'/api/teach/assignments/{fm}/progress', tok=T)
row2 = next(r for r in pgm2['rows'] if r['username'] == U1)
ok('老师评分后：最高分 92，不再待评分', row2['best'] == 92 and row2['state'] != '待评分', (row2['best'], row2['state']))
call('PATCH', f'/api/teach/assignments/{fa}', {'checks': [{'kind': 'valid'}], 'brief_md': '改过的要求'}, tok=T)
ok('老师改要求和检查项', len(call('GET', f'/api/teach/assignments/{fa}/task', tok=S1)['scene']['rules']) == 1)

# ---------- 4.6 老师做的测验课：作业包只有作答（版本 2），服务器重评 = 直接提交的分 ----------
dq = call('POST', '/api/teach/authoring', {'name': f'作业包测验 {STAMP}'}, tok=T)
qc = {'name': f'作业包测验 {STAMP}', 'chapters': [{'id': 'c1', 'title': '一', 'lessons': [{'id': 'q1', 'title': '测验', 'kind': 'quiz', 'brief_md': '答三道题。', 'rules': [
    {'key': 'a', 'kind': 'answer', 'label': '选 B', 'choices': ['A', 'B'], 'answer': 1, 'weight': 1},
    {'key': 'b', 'kind': 'answer', 'qtype': 'multi', 'label': '选 A 和 C', 'choices': ['A', 'B', 'C'], 'answer': [0, 2], 'weight': 1},
    {'key': 'c', 'kind': 'answer', 'qtype': 'tf', 'label': '对', 'answer': True, 'weight': 2}]}]}]}
call('PUT', f"/api/teach/authoring/{dq['id']}", {'course': qc}, tok=T)
call('POST', f"/api/teach/authoring/{dq['id']}/publish", {}, tok=T)
call('POST', f"/api/teach/courses/{dq['id']}/publish", {'class_id': cid}, tok=T)
qa = next(a for a in call('GET', f'/api/teach/assignments?class_id={cid}', tok=T) if a.get('course') == dq['id'])['id']
tq = call('GET', f'/api/teach/assignments/{qa}/task?client=1', tok=S1)
ok('/task?client=1：老师做的课写明来源和版本（客户端据此下载课程包）', tq['client']['course_origin'] == 'authored' and tq['client']['course_version'] == 1, tq['client'].get('course_origin'))
call('PUT', f'/api/teach/assignments/{qa}/answers', {'answers': {'a': 1, 'b': [2, 0], 'c': False}}, tok=S1)
direct = call('POST', f'/api/teach/assignments/{qa}/submit', {}, tok=S1)
qp = call('GET', f'/api/teach/assignments/{qa}/package', tok=S1, raw=True)
qk = pk.read(qp)
ok('测验课作业包：版本 2、类型 quiz、只有作答（多选是列表）', qk.manifest['version'] == 2 and qk.manifest['kind'] == 'quiz' and qk.model is None and not qk.programs
   and qk.answers.get('b') == [2, 0], qk.summary())
viap = call('POST', f'/api/teach/assignments/{qa}/submit_package', tok=S1, data=qp)
ok('测验课作业包重评 = 直接提交的分（单选、多选对，判断错 = 50）', viap['score'] == direct['score'] == 50, (direct['score'], viap['score']))
ok('测验课作业包交到别的作业：拒收', err('POST', f'/api/teach/assignments/{aid}/submit_package', tok=S1, data=qp)[0] == 400)

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过（班级 {cid}）')
sys.exit(0 if n == len(res) else 1)
