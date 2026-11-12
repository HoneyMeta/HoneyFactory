"""学校走查（audit-school.md）教学侧修复的接口测试（先启动 serve）：python tests/teach_audit_check.py
T2 名单导入（制表符/中文逗号/表头、预览、xlsx、模板）、T4 批量重置密码/移出、首次登录改密提示、T9 查看不建沙箱/状态不变、
T14 旁观只读 + 接管、T13 注入故障 → 故障中 → 学生排故 → 通知老师、S7 没进沙箱不能提交、T7 次数上限/开始时间/迟交/只显示总分、
T11 提交历史含程序快照和评分回放、分项评语、S17 PLC 课不能改模型、S4 发布前检查、缺失功能 12 学情分析、S38 助教超时降级。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
STAMP = time.strftime('%m%d%H%M%S')
res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240], flush=True)


def call(method, url, body=None, tok='', raw=False):
    r = urllib.request.Request(B + url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + tok} if tok else {})})
    with urllib.request.urlopen(r, timeout=300) as f:
        d = f.read()
        return d if raw else json.loads(d)


def err(method, url, body=None, tok=''):
    try:
        call(method, url, body, tok, raw=True)
        return 200, ''
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}').get('detail', '')


def login(u, p):
    return call('POST', '/api/login', {'username': u, 'password': p})['token']


admin = login('admin', 'honey123')
if 'ta_teacher' not in {u['username'] for u in call('GET', '/api/admin/users', tok=admin)['users']}:
    call('POST', '/api/admin/users', {'username': 'ta_teacher', 'name': '赵老师', 'role': 'teacher', 'password': 'teach123'}, tok=admin)
T = login('ta_teacher', 'teach123')
cid = call('POST', '/api/teach/classes', {'name': f'走查修复班 {STAMP}'}, tok=T)['id']
n0 = STAMP[-6:]
U = [f'au{n0}1', f'au{n0}2', f'au{n0}3', f'au{n0}4']

# ---------- T2 名单 ----------
paste = f"学号\t姓名\n{U[0]}\t赵一\n{U[1]}，钱二\n{U[2]},孙三\n{U[3]} 李四\n坏 账号\t周五\n{U[0]}\t赵一重复\n"
pv = call('POST', f'/api/teach/classes/{cid}/roster', {'csv': paste, 'preview': True}, tok=T)
st = {}
for r in pv['rows']:
    st.setdefault(r['username'], r['status'])
ok('预览：制表符、中文逗号、英文逗号、空格都能分开，表头跳过', all(st.get(u) == 'new' for u in U) and '学号' not in st, pv['counts'])
ok('预览：含空格的账号、重复行标红', pv['counts'].get('error') == 2, [r['msg'] for r in pv['rows'] if r['status'] == 'error'])
ok('预览不建账号', err('POST', '/api/login', {'username': U[0], 'password': '123456'})[0] == 401)
im = call('POST', f'/api/teach/classes/{cid}/roster', {'csv': paste}, tok=T)
ok('导入：只导好的行，问题行给原因', im['added'] == 4 and len(im['errors']) == 2 and len(im['accounts']) == 4, im['errors'])
S = {u: login(u, '123456') for u in U}
ok('导入的学生能用初始密码登录', len(S) == 4)
me = call('GET', '/api/teach/me', tok=S[U[0]])
ok('首次登录提示改密码', me['must_change_password'] is True)
call('POST', '/api/me/password', {'old': '123456', 'new': 'abc12345'}, tok=S[U[0]])
ok('改过密码后不再提示', call('GET', '/api/teach/me', tok=S[U[0]])['must_change_password'] is False)
tpl = call('GET', '/api/teach/roster_template.xlsx', tok=T, raw=True)
ok('名单模板 .xlsx', tpl[:2] == b'PK')
from openpyxl import Workbook  # noqa: E402
wb = Workbook()
ws = wb.active
ws.append(['学号', '姓名'])
ws.append([f'ax{n0}1', '吴六'])
ws.append([20260099, '数字学号'])
buf = io.BytesIO()
wb.save(buf)
xr = call('POST', f'/api/teach/classes/{cid}/roster', {'xlsx': base64.b64encode(buf.getvalue()).decode()}, tok=T)
ok('上传 .xlsx 导入（数字学号按文本）', xr['added'] == 2, xr)
rp = call('POST', f'/api/teach/classes/{cid}/members/reset_password', {'usernames': [U[3]], 'random': True}, tok=T)
pw4 = rp['accounts'][0]['password']
ok('批量重置密码（随机 6 位）', len(pw4) == 6 and login(U[3], pw4))
S[U[3]] = login(U[3], pw4)
rm = call('POST', f'/api/teach/classes/{cid}/members/remove', {'usernames': [f'ax{n0}1', '20260099']}, tok=T)
ok('批量移出', rm['removed'] == 2 and len(call('GET', f'/api/teach/classes/{cid}', tok=T)['members']) == 4)

# ---------- 发布：发布前检查、开始时间、次数上限、只显示总分 ----------
sd = call('GET', '/api/teach/scenes/s03_conveyor', tok=T)
ok('发布前检查：任务书与评分对齐的提醒（S4）', isinstance(sd.get('warnings'), list), sd.get('warnings'))
later = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's01_motor_latch', 'title': '还没开始的任务', 'start_at': '2099-01-01 08:00'}, tok=T)['id']
ok('开始时间之前学生看不到', all(a['id'] != later for a in call('GET', '/api/teach/my', tok=S[U[1]])) and err('GET', f'/api/teach/assignments/{later}/task', tok=S[U[1]])[0] == 403)
aid = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's01_motor_latch', 'title': '启停自锁（走查）', 'max_subs': 2, 'show_details': False,
                                             'faults': call('GET', '/api/teach/scenes', tok=T)[0]['faults']}, tok=T)['id']

# ---------- S7 没进沙箱不能提交，也不建沙箱 ----------
c, d = err('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[U[1]])
pg = call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)
ok('没进沙箱就提交：明确提示、不建沙箱（S7）', c == 400 and '进入' in d and all(r['sandbox'] == 'none' for r in pg['rows']), d)

# ---------- T9 老师查看不建沙箱、不改状态 ----------
w = call('GET', f'/api/teach/assignments/{aid}/students/{U[2]}/watch', tok=T)
pg = call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)
r2 = next(r for r in pg['rows'] if r['username'] == U[2])
ok('看"未开始"的学生不替他建沙箱（T9）', w['exists'] is False and r2['sandbox'] == 'none' and r2['state'] == '未开始', (w.get('msg'), r2['state']))
c, d = err('POST', f'/api/teach/assignments/{aid}/students/{U[2]}/faults', {'kind': 'sensor_stuck_on'}, tok=T)
ok('没开始的学生不能注入故障', c == 400, d)

# 学生 1 进沙箱、下载参考程序、提交
sb = call('POST', f'/api/teach/assignments/{aid}/sandbox', tok=S[U[1]])
pid = sb['pid']
ref = call('GET', '/api/teach/scenes/s01_motor_latch', tok=T)['reference']
ref = ref.get('st') if isinstance(ref, dict) and 'st' in ref else ref
lv = call('GET', f'/api/teach/assignments/{aid}/live', tok=S[U[1]])
ok('没下载程序时 live.has_program = false（前端据此禁用提交）', lv['has_program'] is False)
call('POST', f"/api/p/{pid}/cells/{sb['bid']}/program/download", {'program': ref}, tok=S[U[1]])
s1 = call('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[U[1]])
ok('只显示总分（T7）', s1['score'] == 100 and s1['details'] == [] and s1['hidden'] is True, (s1['score'], s1['hidden']))
bad = dict(ref, source=ref['source'].replace('(START OR M1_RUN)', 'START'))
call('POST', f"/api/p/{pid}/cells/{sb['bid']}/program/download", {'program': bad}, tok=S[U[1]])
s2 = call('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[U[1]])
ok('第二次交了没自锁的程序，分数变低', s2['score'] < 100, s2['score'])
c, d = err('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[U[1]])
ok('提交次数上限（T7）', c == 400 and '用完' in d, d)

# ---------- S17 PLC 课学生不能改模型 ----------
m = call('GET', f'/api/p/{pid}/model', tok=S[U[1]])['model']
ok('PLC 课：外壳点"运行"前的草稿保存照常（不然运行不了）', err('PUT', f'/api/p/{pid}/model', {'model': m}, tok=S[U[1]])[0] == 200)
c, d = err('POST', f'/api/p/{pid}/model/apply', {'note': 'x'}, tok=S[U[1]])
c2, _ = err('POST', f"/api/p/{pid}/station/{sb['bid']}/write", {'tag': 'Panel/START', 'value': True}, tok=S[U[1]])
ok('PLC 课：应用模型改动被拒（中文原因），按面板照常（S17）', c == 403 and 'PLC 控制课' in d and c2 == 200, d)
tk = call('GET', f'/api/teach/assignments/{aid}/task', tok=S[U[1]])
ok('任务接口带课的类型（前端据此只读）', tk['kind'] == 'cell')

# ---------- T14 旁观只读、接管 ----------
c, d = err('POST', f"/api/p/{pid}/cells/{sb['bid']}/program/download", {'program': ref}, tok=T)
ok('老师旁观时写学生沙箱被后端拒绝（T14）', c == 403 and '接管' in d, d)
ok('老师读学生沙箱照常', err('GET', f'/api/p/{pid}/meta', tok=T)[0] == 200)
call('POST', f'/api/teach/assignments/{aid}/students/{U[1]}/takeover', {'on': True}, tok=T)
c, _ = err('POST', f"/api/p/{pid}/cells/{sb['bid']}/program/download", {'program': ref}, tok=T)
lv = call('GET', f'/api/teach/assignments/{aid}/live', tok=S[U[1]])
ok('接管后老师可以写、学生看到"老师正在接管"', c == 200 and lv['takeover'] and lv['takeover']['name'] == '赵老师', lv['takeover'])
call('POST', f'/api/teach/assignments/{aid}/students/{U[1]}/takeover', {'on': False}, tok=T)
ok('结束接管后又是只读', err('POST', f"/api/p/{pid}/cells/{sb['bid']}/program/download", {'program': ref}, tok=T)[0] == 403)

# ---------- T13 故障中 → 学生排故 → 通知 ----------
f0 = call('GET', '/api/teach/scenes/s01_motor_latch', tok=T)['faults'][0]
call('POST', f'/api/teach/assignments/{aid}/students/{U[1]}/faults', {'comp': f0['comp'], 'kind': f0['kind']}, tok=T)
row = next(r for r in call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)['rows'] if r['username'] == U[1])
ok('学生卡片显示"故障中"（T13）', row['state'] == '故障中' and row['faults'][0]['label'], row['faults'])
lv = call('GET', f'/api/teach/assignments/{aid}/live', tok=S[U[1]])
ok('学生端知道有故障，并拿到可选部件和故障类型', lv['faults_active'] == 1 and lv['diagnose']['comps'] and lv['diagnose']['kinds'])
wrong = call('POST', f'/api/teach/assignments/{aid}/diagnose', {'comp': f0['comp'], 'kind': 'actuator_slow' if f0['kind'] != 'actuator_slow' else 'wire_break'}, tok=S[U[1]])
ok('排故答错：部件对了提示类型不对', wrong['ok'] is False and '类型' in wrong['msg'], wrong['msg'])
nb = call('GET', '/api/teach/notices?since=0', tok=T)
right = call('POST', f'/api/teach/assignments/{aid}/diagnose', {'comp': f0['comp'], 'kind': f0['kind']}, tok=S[U[1]])
na = call('GET', '/api/teach/notices?since=0', tok=T)
row = next(r for r in call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)['rows'] if r['username'] == U[1])
ok('排故答对：故障排除、老师收到通知、卡片不再"故障中"', right['ok'] and len(na) == len(nb) + 1 and '排除' in na[0]['msg'] and row['state'] != '故障中',
   (right['msg'], na[0]['msg']))

# ---------- T11 提交历史、程序快照、评分回放、分项评语 ----------
subs = call('GET', f'/api/teach/assignments/{aid}/submissions?username={U[1]}', tok=T)
ok('提交历史：每次都有程序快照和评分回放（T11）', len(subs) == 2 and all(s.get('program') for s in subs) and all(s.get('log') for s in subs),
   [(s.get('auto_score'), bool(s.get('program')), len(s.get('log') or [])) for s in subs])
ok('两次提交的程序快照不同（前端据此做对比）', subs[0]['program'].get('source') != subs[1]['program'].get('source'))
ok('老师看得到细则（学生端隐藏）', subs[0]['details'], len(subs[0]['details']))
k = subs[0]['details'][0]['key']
rv = call('POST', f"/api/teach/submissions/{subs[0]['id']}/review", {'comment': '自锁没做', 'rule_comments': {k: '这一项看看自锁'}}, tok=T)
ok('分项评语', rv['rule_comments'].get(k) == '这一项看看自锁' and rv['status'] == 'reviewed')

# ---------- 状态以学生自己的活动为准 ----------
row3 = next(r for r in call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)['rows'] if r['username'] == U[1])
ok('学生刚操作过 → 进行中/已满分等（不因老师查看变化）', row3['active'] is True, row3['state'])

# ---------- 缺失功能 12 学情 ----------
an = call('GET', f'/api/teach/assignments/{aid}/analytics', tok=T)
ok('学情分析：每个评分项的得分率、没交的学生', an['submitted'] == 1 and an['rules'] and set(an['notsubmitted']) == {U[0], U[2], U[3]}, [(r['label'], r['rate']) for r in an['rules']][:3])

# ---------- 成绩册导出明细 ----------
from openpyxl import load_workbook  # noqa: E402
gx = load_workbook(io.BytesIO(call('GET', f'/api/teach/classes/{cid}/gradebook.xlsx', tok=T, raw=True)))
hdr = [c.value for c in gx['提交明细'][1]]
ok('成绩册导出含评分明细和分项评语（T19）', '评分明细' in hdr and '分项评语' in hdr, hdr)

# ---------- S38 助教降级 ----------
th = call('GET', f'/api/tutor/hint?assignment_id={aid}', tok=S[U[1]])
ok('第 1 条提示接口（外壳等 15 秒时先显示）', th['total'] >= 1 and th['hint'])

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过（班级 {cid}）')
sys.exit(0 if n == len(res) else 1)
