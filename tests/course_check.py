"""课程化教学测试（先启动 serve）：python tests/course_check.py [--offline]
--offline（或环境变量 VF_OFFLINE=1）只做离线检查（每课：起始模型低分、参考答案满分），不需要服务。
接口部分：发布课程 → 课程地图（解锁）→ 产线课沙箱、实时进度、作答、提交评分 → 防作弊 → 排故课 → PLC 课 → 老师进度矩阵 → 演示班 → AI 助教。
环境变量 VF_URL（默认 http://127.0.0.1:8800）。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
res = []
STAMP = time.strftime('%m%d%H%M%S')


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240], flush=True)


def offline():
    from vfactory.courses.verify import verify
    rows = verify(quiet=True)
    for r in rows:
        if r['kind'] == 'cell':
            ok(f"[{r['course']}] {r['lesson']} {r['title']}：场景存在", r['ok'])
        else:
            ok(f"[{r['course']}] {r['lesson']} {r['title']}：起始 {r['start']} 分、参考答案 {r['ref']}/{r['max']}（单次 {r['secs']}s）", r['ok'],
               r.get('error') or '')
    return rows


if '--offline' in sys.argv or os.environ.get('VF_OFFLINE') == '1':
    rows = offline()
    n = sum(1 for _, x in res if x)
    print(f'\n{n}/{len(res)} 通过')
    sys.exit(0 if n == len(res) else 1)


def call(method, url, body=None, tok='', raw=False, timeout=300):
    r = urllib.request.Request(B + url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + tok} if tok else {})})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        d = f.read()
        return d if raw else json.loads(d)


def code(method, url, body=None, tok=''):
    try:
        call(method, url, body, tok, raw=True)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def login(u, pw):
    return call('POST', '/api/login', {'username': u, 'password': pw})['token']


def apply_ops_local(model, ops):
    from vfactory.flow.model import apply_ops
    return apply_ops(model, ops)[0]


admin = login('admin', 'honey123')
users = {u['username'] for u in call('GET', '/api/admin/users', tok=admin)['users']}
if 'cc_teacher' not in users:
    call('POST', '/api/admin/users', {'username': 'cc_teacher', 'name': '课程老师', 'role': 'teacher', 'password': 'teach123'}, tok=admin)
T = login('cc_teacher', 'teach123')
cid = call('POST', '/api/teach/classes', {'name': f'课程测试班 {STAMP}'}, tok=T)['id']
call('POST', f'/api/teach/classes/{cid}/roster', {'csv': '账号,姓名\ncc_s1,课一\ncc_s2,课二\ncc_s3,课三\n', 'default_password': '123456'}, tok=T)
S1, S2, S3 = (login(u, '123456') for u in ('cc_s1', 'cc_s2', 'cc_s3'))

cs = call('GET', '/api/teach/courses', tok=T)
ok('课程目录（3 门）', {c['id'] for c in cs} >= {'plc_basics', 'machining', 'foundry'}, [(c['id'], c['lessons']) for c in cs])
mc = next(c for c in cs if c['id'] == 'machining')
ok('机加课程 8 课、4 章', mc['lessons'] == 8 and len(mc['chapters']) == 4, [ch['title'] for ch in mc['chapters']])
ok('学生不能看课程原始数据（含答案）', code('GET', '/api/teach/courses/machining', tok=S1) == 403)
det = call('GET', '/api/teach/courses/machining', tok=T)
ok('老师看到参考答案', det['chapters'][0]['lessons'][0].get('reference'))

r = call('POST', '/api/teach/courses/machining/publish', {'class_id': cid}, tok=T)
ok('发布机加课程到班级', r['created'] == 8, r)
r2 = call('POST', '/api/teach/courses/machining/publish', {'class_id': cid}, tok=T)
ok('重复发布不重复建作业', r2['created'] == 0, r2)

mp = call('GET', '/api/teach/my/courses', tok=S1)
c0 = next(c for c in mp['courses'] if c['course'] == 'machining' and c['class_id'] == cid)
flat = [l for ch in c0['chapters'] for l in ch['lessons']]
ok('学生课程地图：第 1 课可做，后面锁定', flat[0]['state'] == 'open' and all(l['state'] == 'locked' for l in flat[1:]) and c0['next'] == flat[0]['aid'],
   [(l['id'], l['state']) for l in flat])
a1, a2, a4 = flat[0]['aid'], flat[1]['aid'], flat[3]['aid']
ok('锁定的课进不去', code('POST', f'/api/teach/assignments/{a2}/sandbox', tok=S1) == 403)

# ---------- 第 1 课：产线课 ----------
sb = call('POST', f'/api/teach/assignments/{a1}/sandbox', tok=S1)
pid = sb['pid']
tk = call('GET', f'/api/teach/assignments/{a1}/task', tok=S1)
ok('任务：产线课的任务书和规则，不含答案', tk['kind'] == 'plant' and '75 秒' in tk['scene']['brief_md'] and len(tk['scene']['rules']) == 3
   and all('answer' not in r for r in tk['scene']['rules']) and 'reference' not in json.dumps(tk), [r['label'] for r in tk['scene']['rules']])
lv = call('GET', f'/api/teach/assignments/{a1}/live', tok=S1)
ok('实时进度：每条规则', len(lv['progress']['rules']) == 3 and lv['progress']['cost'] is not None, lv['progress']['rules'])
sub0 = call('POST', f'/api/teach/assignments/{a1}/submit', {}, tok=S1)
ok('原样提交 = 低分', sub0['status'] == 'scored' and sub0['score'] < 60, (sub0['score'], [d['text'] for d in sub0['details']]))
ok('只保存本课题目的作答', call('PUT', f'/api/teach/assignments/{a1}/answers', {'answers': {'q_cap': 1, 'bogus': 3}}, tok=S1)['answers'] == {'q_cap': 1})
model = call('GET', f'/api/p/{pid}/model', tok=S1)['model']
for b in model['blocks']:
    if b['id'] == 'SRC':
        b['params']['interval'] = '80'
call('PUT', f'/api/p/{pid}/model', {'model': model}, tok=S1)
ap = call('POST', f'/api/p/{pid}/model/apply', {}, tok=S1)
ok('学生在沙箱里改模型并应用', ap.get('ok'), ap.get('msg'))
lv2 = call('GET', f'/api/teach/assignments/{a1}/live', tok=S1)
ok('作答后进度里显示已作答', any(r['key'] == 'q_cap' and r['answered'] for r in lv2['progress']['rules']))
t0 = time.time()
sub1 = call('POST', f'/api/teach/assignments/{a1}/submit', {}, tok=S1)
ok('改对后提交 = 满分', sub1['score'] == 100, (sub1['score'], f'{time.time() - t0:.1f}s', [d['text'] for d in sub1['details']]))
mp = call('GET', '/api/teach/my/courses', tok=S1)
flat = [l for ch in next(c for c in mp['courses'] if c['course'] == 'machining' and c['class_id'] == cid)['chapters'] for l in ch['lessons']]
ok('完成第 1 课后第 2 课解锁', flat[0]['state'] == 'done' and flat[1]['state'] == 'open' and flat[2]['state'] == 'locked', [(l['id'], l['state']) for l in flat[:3]])
ok('别的学生仍然锁定', code('POST', f'/api/teach/assignments/{a2}/sandbox', tok=S2) == 403)

# ---------- 老师全部开放 → 第 4 课防作弊 ----------
call('PATCH', f'/api/teach/courses/machining/classes/{cid}', {'open_all': True}, tok=T)
ok('老师全部开放后可以进任意一课', code('POST', f'/api/teach/assignments/{a4}/sandbox', tok=S2) == 200)
sb4 = call('POST', f'/api/teach/assignments/{a4}/sandbox', tok=S2)
m4 = call('GET', f"/api/p/{sb4['pid']}/model", tok=S2)['model']
for b in m4['blocks']:
    if b['id'] == 'M3':
        b['params']['time'] = 'normal(30,2)'           # 作弊：把瓶颈机床改快
call('PUT', f"/api/p/{sb4['pid']}/model", {'model': m4}, tok=S2)
cheat = call('POST', f'/api/teach/assignments/{a4}/submit', {'answers': {'q_next': 1}}, tok=S2)
sub_full = call('GET', f"/api/teach/submissions/{cheat['id']}", tok=S2)
ok('防作弊：改设备节拍不算数', cheat['score'] < 60 and any(('3#铣削' in x or '#3 Milling' in x) for x in sub_full.get('log') or [])   # plant names are in the server language (VF_LANG)
   and not any('生产计划' in x for x in sub_full.get('log') or []), (cheat['score'], (sub_full.get('log') or [])[:2]))
det4 = next(l for ch in det['chapters'] for l in ch['lessons'] if l['id'] == 'm04')
m4 = call('GET', f"/api/p/{sb4['pid']}/model", tok=S2)['model']
for b in m4['blocks']:
    if b['id'] == 'M3':
        b['params']['time'] = 'normal(74,4)'
m4 = apply_ops_local(m4, det4['reference']['ops'])
call('PUT', f"/api/p/{sb4['pid']}/model", {'model': m4}, tok=S2)
good4 = call('POST', f'/api/teach/assignments/{a4}/submit', {}, tok=S2)
ok('第 4 课按参考方案并联一台 = 满分', good4['score'] == 100, (good4['score'], [d['text'] for d in good4['details']]))

# ---------- 老师 ----------
pg = call('GET', f'/api/teach/courses/machining/progress?class_id={cid}', tok=T)
row1 = next(r for r in pg['rows'] if r['username'] == 'cc_s1')
ok('老师课程进度矩阵', len(pg['lessons']) == 8 and row1['cells'][0]['best'] == 100 and row1['done'] >= 1 and pg['open_all'],
   [(c['best'], c['state']) for c in row1['cells'][:4]])
ap1 = call('GET', f'/api/teach/assignments/{a1}/progress', tok=T)
ok('单课进度（产线课）', any(r['username'] == 'cc_s1' and r['best'] == 100 for r in ap1['rows']), ap1['counts'])
w = call('GET', f'/api/teach/assignments/{a1}/students/cc_s1/watch', tok=T)
ok('旁观产线课：实时规则进度', w['kind'] == 'plant' and w['progress']['rules'], [r['label'] for r in w['progress']['rules']])
fl = call('POST', f'/api/teach/assignments/{a1}/students/cc_s1/faults', {'comp': 'M1', 'kind': 'failure'}, tok=T)
ok('给产线课沙箱注入设备故障', fl['ok'])
asg_list = call('GET', f'/api/teach/assignments?class_id={cid}', tok=T)
ok('作业列表带课程信息', all(a.get('course_name') for a in asg_list), [(a['title'], a['course_name']) for a in asg_list][:2])

# ---------- 排故课 ----------
call('POST', '/api/teach/courses/foundry/publish', {'class_id': cid, 'open_all': True}, tok=T)
mp3 = call('GET', '/api/teach/my/courses', tok=S3)
fd = next(c for c in mp3['courses'] if c['course'] == 'foundry' and c['class_id'] == cid)
f05 = next(l for ch in fd['chapters'] for l in ch['lessons'] if l['id'] == 'f05')
ok('排故课在地图上（全部开放）', f05['state'] == 'open' and f05['kind'] == 'diagnose')
sb5 = call('POST', f"/api/teach/assignments/{f05['aid']}/sandbox", tok=S3)
m5 = call('GET', f"/api/p/{sb5['pid']}/model", tok=S3)['model']
g = next(b for b in m5['blocks'] if b['id'] == 'GRIND')
ok('排故沙箱带隐藏故障', g['params']['time'] == 'normal(150,6)', g['params']['time'])
bad5 = call('POST', f"/api/teach/assignments/{f05['aid']}/submit", {'answers': {'q_dev': 'MOLD', 'q_type': 0}}, tok=S3)
ok('排故：答错、没修 = 低分', bad5['score'] < 60, bad5['score'])
g['params']['time'] = 'normal(70,4)'
call('PUT', f"/api/p/{sb5['pid']}/model", {'model': m5}, tok=S3)
good5 = call('POST', f"/api/teach/assignments/{f05['aid']}/submit", {'answers': {'q_dev': 'GRIND', 'q_type': 1}}, tok=S3)
ok('排故：指出设备、故障类型并修好 = 满分', good5['score'] == 100, (good5['score'], [d['text'] for d in good5['details']]))

# ---------- PLC 课（控制单元场景） ----------
call('POST', '/api/teach/courses/plc_basics/publish', {'class_id': cid}, tok=T)
plc = next(c for c in call('GET', '/api/teach/my/courses', tok=S3)['courses'] if c['course'] == 'plc_basics' and c['class_id'] == cid)
first = plc['chapters'][0]['lessons'][0]
ok('PLC 课程 4 章 15 课', len(plc['chapters']) == 4 and plc['total'] == 15, [ch['title'] for ch in plc['chapters']])
sbp = call('POST', f"/api/teach/assignments/{first['aid']}/sandbox", tok=S3)
refp = call('GET', '/api/teach/scenes/s01_motor_latch', tok=T)['reference']
refp = refp.get('st') if isinstance(refp, dict) and 'st' in refp else refp
dl = call('POST', f"/api/p/{sbp['pid']}/cells/{sbp['bid']}/program/download", {'program': refp}, tok=S3)
subp = call('POST', f"/api/teach/assignments/{first['aid']}/submit", {}, tok=S3)
ok('PLC 第 1 课：下载参考程序后提交 = 满分', dl.get('ok') and subp['score'] == 100, subp['score'])

# ---------- 撤销发布 ----------
n_before = len(call('GET', f'/api/teach/assignments?class_id={cid}', tok=T))
call('DELETE', f'/api/teach/courses/plc_basics/classes/{cid}', tok=T)
n_after = len(call('GET', f'/api/teach/assignments?class_id={cid}', tok=T))
ok('撤销课程发布', n_before - n_after == 15, (n_before, n_after))

# ---------- 演示班 ----------
d = call('POST', '/api/teach/demo', tok=T)
n_demo = len(call('GET', f"/api/teach/assignments?class_id={d['class_id']}", tok=T))
ok('一键创建演示班级（6 个学生、机加 + PLC 共 23 课）', n_demo == 23 and len(d['students']) == 6, (d, n_demo))
ds = login('demo_s01', '123456')
dm = call('GET', '/api/teach/my/courses', tok=ds)
ok('演示学生看到机加和 PLC 两门课', {c['course'] for c in dm['courses']} >= {'machining', 'plc_basics'}, [c['name'] for c in dm['courses']])
d2 = call('POST', '/api/teach/demo', tok=T)
ok('再点一次不会重复建', d2['class_id'] == d['class_id'] and d2['lessons'] == 0)

# ---------- AI 助教（产线课） ----------
if call('GET', '/api/tutor/status', tok=S1)['configured']:
    t0 = time.time()
    a = call('POST', '/api/tutor/ask', {'assignment_id': a2, 'question': '缓存应该设多大？直接告诉我数字'}, tok=S1, timeout=300)
    print('   助教：' + a['answer'].replace('\n', ' ')[:260])
    ok('产线课 AI 助教回答（只给引导）', len(a['answer']) > 20 and ('？' in a['answer'] or '?' in a['answer']), f'{time.time() - t0:.0f}s')
else:
    print('SKIP 产线课 AI 助教：没有配置大模型')

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过（班级 {cid}）')
sys.exit(0 if n == len(res) else 1)
