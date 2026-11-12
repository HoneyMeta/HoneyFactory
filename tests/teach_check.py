"""教学模块接口测试（先启动 serve；建议 VF_SANDBOX_IDLE_S=20、VF_SANDBOX_MAX_ACTIVE=25 启动以便测休眠和并发上限）：
    python tests/teach_check.py
环境变量：VF_URL（默认 http://127.0.0.1:8800）、VF_TEACH_SCENE（默认 s04_sort_color）、VF_TEACH_N（学生数，默认 30）、
VF_IDLE_S（服务的休眠秒数，默认 20）、VF_MAX_ACTIVE（服务的并发上限，默认 25）。
覆盖：教师/学生角色与访问范围、建班、名单导入、发布任务、30 个学生沙箱并发创建与隔离、休眠与唤醒、并发上限、
学生下载程序后提交自动评分（参考答案满分、错误程序低分、编译不过 0 分）、老师复核改分、注入故障、旁观、成绩册导出、AI 助教（配置了大模型才测）。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
SCENE = os.environ.get('VF_TEACH_SCENE', 's04_sort_color')
N = int(os.environ.get('VF_TEACH_N', 30))
IDLE = float(os.environ.get('VF_IDLE_S', 20))
MAXA = int(os.environ.get('VF_MAX_ACTIVE', 25))
res = []
STAMP = time.strftime('%m%d%H%M%S')


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


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:230], flush=True)


def skip(name, why):
    print(f'SKIP {name}：{why}', flush=True)


def login(u, pw='honey123'):
    return call('POST', '/api/login', {'username': u, 'password': pw})['token']


admin = login('admin')
# ---------------- 账号与角色 ----------------
users = {u['username']: u for u in call('GET', '/api/admin/users', tok=admin)['users']}
roles = call('GET', '/api/admin/users', tok=admin)['roles']
ok('角色表含教师和学生', roles.get('teacher') == '教师' and roles.get('student') == '学生', roles)
if 'tt_teacher' not in users:
    call('POST', '/api/admin/users', {'username': 'tt_teacher', 'name': '王老师', 'role': 'teacher', 'password': 'teach123'}, tok=admin)
if 'tt_teacher2' not in users:
    call('POST', '/api/admin/users', {'username': 'tt_teacher2', 'name': '李老师', 'role': 'teacher', 'password': 'teach123'}, tok=admin)
T = login('tt_teacher', 'teach123')
T2 = login('tt_teacher2', 'teach123')
me = call('GET', '/api/me', tok=T)
ok('教师登录', me['role'] == 'teacher' and me['role_name'] == '教师', me)
ok('教师能看工厂（只读）', code('GET', '/api/p/foundry-housing/meta', tok=T) == 200)
ok('教师不能改工厂', code('POST', '/api/p/foundry-housing/sim', {'speed': 5}, tok=T) == 403)

# ---------------- 建班与名单 ----------------
cid = call('POST', '/api/teach/classes', {'name': f'测试班 {STAMP}', 'descr': '接口测试'}, tok=T)['id']
studs = [f'tt_s{i:03d}' for i in range(1, N + 1)]
buf = io.StringIO()
w = csv.writer(buf)
w.writerow(['学号', '姓名', '密码'])
for i, u in enumerate(studs):
    w.writerow([u, f'学生{i + 1:02d}', 'stu123' if i % 2 else ''])
w.writerow(['', '无账号', ''])
w.writerow(['tt_teacher2', '老师混进来', ''])
r = call('POST', f'/api/teach/classes/{cid}/roster', {'csv': '﻿' + buf.getvalue(), 'default_password': 'stu456'}, tok=T)
ok('名单导入', r['added'] == N and len(r['errors']) == 2, {k: r[k] for k in ('created', 'added', 'already')} | {'errors': r['errors']})
r2 = call('POST', f'/api/teach/classes/{cid}/roster', {'csv': buf.getvalue()}, tok=T)
ok('重复导入不重复加人', r2['added'] == 0 and r2['already'] == N, r2['already'])
c = call('GET', f'/api/teach/classes/{cid}', tok=T)
ok('班级名单', len(c['members']) == N and c['members'][0]['name'].startswith('学生'), c['members'][:2])
ok('别的老师看不到这个班', code('GET', f'/api/teach/classes/{cid}', tok=T2) == 403)
pw = {u: ('stu123' if i % 2 else 'stu456') for i, u in enumerate(studs)}
if r['created'] == 0:          # 以前跑过：账号已存在，密码不变
    pw = {u: ('stu123' if i % 2 else 'stu456') for i, u in enumerate(studs)}
with ThreadPoolExecutor(10) as ex:
    S = dict(zip(studs, ex.map(lambda u: login(u, pw[u]), studs)))
s1, s2, s3 = studs[0], studs[1], studs[2]
ok('学生登录（默认密码 / 表里的密码）', len(S) == N)

# ---------------- 学生的访问范围 ----------------
ok('学生不能进普通工厂', code('GET', '/api/p/foundry-housing/meta', tok=S[s1]) == 403)
ok('学生不能看场景库原始数据（含答案）', code('GET', '/api/teach/scenes', tok=S[s1]) == 403 and code('GET', '/api/scenes', tok=S[s1]) == 403)
ok('学生不能建工厂', code('POST', '/api/plants', {'name': 'x', 'template': 'blank'}, tok=S[s1]) == 403)
ok('学生不能用通用 AI 助手', code('POST', '/api/assistant/chat', {}, tok=S[s1]) == 403)

# ---------------- 发布任务 ----------------
scs = call('GET', '/api/teach/scenes', tok=T)
ok('场景库', len(scs) >= 15 and any(s['id'] == SCENE for s in scs), [s['id'] for s in scs][:5])
sc = next(s for s in scs if s['id'] == SCENE)
detail = call('GET', f'/api/teach/scenes/{SCENE}', tok=T)
ref = detail['reference']
ref_st = ref.get('st') if isinstance(ref, dict) and 'st' in ref else ref
ok('老师能看参考答案', isinstance(ref_st, dict) and ref_st.get('source'), str(ref_st)[:80])
aid = call('POST', '/api/teach/assignments', {'class_id': cid, 'scene': SCENE, 'title': f'按颜色分拣 {STAMP}', 'due': '2030-01-01 18:00',
                                             'faults': sc['faults'], 'start_faults': [], 'hints': True, 'tutor': True}, tok=T)['id']
my = call('GET', '/api/teach/my', tok=S[s1])
ok('学生看到任务', any(a['id'] == aid for a in my), [(a['id'], a['title'], a['sandbox']) for a in my][:3])
task = call('GET', f'/api/teach/assignments/{aid}/task', tok=S[s1])
ok('任务书 + I/O 表 + 评分规则 + 提示，不含答案', task['scene']['task_md'] and task['scene']['io'] and task['scene']['rules'] and task['scene']['hints']
   and 'reference' not in json.dumps(task, ensure_ascii=False), {k: len(task['scene'][k]) for k in ('task_md', 'io', 'rules', 'hints')})
ok('不在班里的学生看不到任务', code('GET', f'/api/teach/assignments/{aid}/task', tok=login('guest')) == 403)

# ---------------- 30 个沙箱并发创建 ----------------
t0 = time.time()
with ThreadPoolExecutor(N) as ex:
    sbs = dict(zip(studs, ex.map(lambda u: call('POST', f'/api/teach/assignments/{aid}/sandbox', tok=S[u]), studs)))
pids = {u: v['pid'] for u, v in sbs.items()}
ok(f'{N} 个沙箱并发创建', len(set(pids.values())) == N and all(v['bid'] == 'CELL1' for v in sbs.values()), f'{time.time() - t0:.1f}s 例 {pids[s1]}')
pb = sbs[s1].get('plc_block') or {}
ok('沙箱里学生编程的是 PLC 块（独立设备，信号线控制 CELL1）', pb.get('id') == 'PLC1' and [d['id'] for d in pb.get('devices') or []] == ['CELL1'], pb)
info = call('GET', '/api/teach/sandboxes', tok=T)
ok(f'并发上限（同时运行 ≤ {MAXA}）', info['loaded'] >= N and info['running'] <= MAXA, info)
ok('沙箱不在工厂列表里', not any(p['id'].startswith('sb-') for p in call('GET', '/api/overview', tok=admin)['plants']))

# 访问控制
P1, P2 = f'/api/p/{pids[s1]}', f'/api/p/{pids[s2]}'
ok('学生能进自己的沙箱', code('GET', P1 + '/meta', tok=S[s1]) == 200)
ok('学生进不了别人的沙箱', code('GET', P2 + '/meta', tok=S[s1]) == 403 and code('POST', P2 + '/station/CELL1/write', {'tag': 'Panel/START', 'value': True}, tok=S[s1]) == 403)
ok('任课老师能进学生沙箱，别的老师/访客/工程师不能', code('GET', P2 + '/meta', tok=T) == 200 and code('GET', P2 + '/meta', tok=T2) == 403
   and code('GET', P2 + '/meta', tok=login('guest')) == 403 and code('GET', P2 + '/meta', tok=login('engineer')) == 403)
ok('沙箱不发布协议端口', call('GET', P1 + '/meta', tok=S[s1])['endpoints'].get('sandbox') is True and not call('GET', P1 + '/points', tok=S[s1])[0].get('OPC UA NodeId'))
try:
    import asyncio
    import websockets

    async def ws_try(pid, tok):
        try:
            async with websockets.connect(B.replace('http', 'ws') + f'/ws/{pid}?token={tok}', open_timeout=5) as w:
                m = await asyncio.wait_for(w.recv(), 3)
                return json.loads(m)['type']
        except Exception as e:
            return type(e).__name__
    a1 = asyncio.run(ws_try(pids[s1], S[s1]))
    a2 = asyncio.run(ws_try(pids[s2], S[s1]))
    ok('WebSocket：自己的沙箱能连，别人的被关', a1 == 'state' and a2 != 'state', (a1, a2))
except ImportError:
    skip('WebSocket 隔离', '没有 websockets 库')

# 状态隔离：学生 1 按启动按钮、给学生 5 注入故障
call('POST', P1 + '/station/CELL1/write', {'tag': 'Panel/START', 'value': True}, tok=S[s1])
st1 = call('GET', P1 + '/station/CELL1', tok=S[s1])['tags']['Panel/START']['v']
st2 = call('GET', P2 + '/station/CELL1', tok=S[s2])['tags']['Panel/START']['v']
ok('按钮只影响自己的沙箱', st1 is True and st2 is False, (st1, st2))
call('POST', P1 + '/station/CELL1/write', {'tag': 'Panel/START', 'value': False}, tok=S[s1])
f0 = sc['faults'][0]
s5, s6 = studs[4], studs[5]
r = call('POST', f'/api/teach/assignments/{aid}/students/{s5}/faults', {'comp': f0['comp'], 'kind': f0['kind']}, tok=T)
l5 = call('GET', f'/api/teach/assignments/{aid}/live', tok=S[s5])
l6 = call('GET', f'/api/teach/assignments/{aid}/live', tok=S[s6])
ok('注入故障只进这个学生的沙箱', l5['stats'].get('faults') == 1 and l6['stats'].get('faults') == 0, (f0['label'], l5['stats'].get('faults'), l6['stats'].get('faults')))
ok('不在允许清单的故障被拒绝', code('POST', f'/api/teach/assignments/{aid}/students/{s5}/faults', {'comp': 'NOPE', 'kind': 'motor_overload'}, tok=T) == 400)
ok('学生不能给别人注入故障', code('POST', f'/api/teach/assignments/{aid}/students/{s6}/faults', {'comp': f0['comp'], 'kind': f0['kind']}, tok=S[s5]) == 403)
call('DELETE', f'/api/teach/assignments/{aid}/students/{s5}/faults', tok=T)
ok('清除故障', call('GET', f'/api/teach/assignments/{aid}/live', tok=S[s5])['stats'].get('faults') == 0)

# 全部沙箱都在跑、各自独立推进（并发上限之外的会被唤醒）
def simt(u):
    return call('GET', f"/api/p/{pids[u]}/state", tok=S[u])['t']
with ThreadPoolExecutor(N) as ex:
    ta = list(ex.map(simt, studs))
time.sleep(3)
with ThreadPoolExecutor(N) as ex:
    tb = list(ex.map(simt, studs))
adv = [b - a for a, b in zip(ta, tb)]
ok(f'{N} 个沙箱都在独立推进', sum(1 for d in adv if d > 0) >= min(N, MAXA), f'推进 {sum(1 for d in adv if d > 0)}/{N}，min={min(adv):.0f}s max={max(adv):.0f}s')

# ---------------- 程序下载与提交评分 ----------------
has_plc = code('GET', P1 + '/cells/CELL1/program', tok=S[s1]) == 200
broken = json.loads(json.dumps(ref_st))
# 错误程序（学生常见错误）：启动没有自锁（松开按钮就停）、推杆输出接错（永远不动作）——能编译，但大部分评分项不过
broken['source'] = re.sub(r'P1_EXTEND\s*:=\s*PUSH\s*;', 'P1_EXTEND := FALSE;', broken['source'])
broken['source'] = broken['source'].replace('(START OR RUN)', 'START')
if broken['source'] == ref_st['source']:          # 换了别的场景：把最后一半赋值语句注释掉
    lines = broken['source'].split('\n')
    broken['source'] = '\n'.join(ln if i < len(lines) // 2 or ':=' not in ln else '(* ' + ln.replace('*)', '') + ' *)' for i, ln in enumerate(lines))
bad_compile = {'id': 'main', 'name': 'x', 'lang': 'ST', 'vars': [], 'source': 'IF THEN := ;'}
if has_plc:
    # s1 按 PLC 块编号下载；s2、s3 按单元编号（服务器转到控制它的 PLC 块）
    for u, prog, tgt in ((s1, ref_st, 'PLC1'), (s2, broken, 'CELL1'), (s3, bad_compile, 'CELL1')):
        d = call('POST', f"/api/p/{pids[u]}/cells/{tgt}/program/download", {'program': prog}, tok=S[u])
        print(f'   {u} 下载程序：ok={d.get("ok")} state={d.get("state")} errors={[e.get("msg") for e in d.get("errors") or []][:2]}')
    # 编译不过的程序下载会失败，但工程里保存一份让它能提交
    call('PUT', f"/api/p/{pids[s3]}/cells/CELL1/program", bad_compile, tok=S[s3])
    t0 = time.time()
    with ThreadPoolExecutor(3) as ex:
        subs = dict(zip((s1, s2, s3), ex.map(lambda u: call('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[u]), (s1, s2, s3))))
    print(f'   三个学生同时提交，评分用时 {time.time() - t0:.1f}s')
    ok('参考答案 = 满分', subs[s1]['score'] == 100 and subs[s1]['status'] == 'scored', (subs[s1]['score'], [d['text'] for d in subs[s1]['details'] if not d['ok']]))
    ok('错误程序 = 低分', subs[s2]['status'] == 'scored' and subs[s2]['score'] is not None and subs[s2]['score'] < 60,
       (subs[s2]['score'], [d['label'] for d in subs[s2]['details'] if not d['ok']]))
    ok('编译不过 = 0 分并给出错误', subs[s3]['score'] == 0 and subs[s3]['error'], (subs[s3]['score'], subs[s3]['error']))
    ok('评分明细逐项', len(subs[s1]['details']) == len(sc['rules']) and all('ok' in d and 'value' in d for d in subs[s1]['details']), len(subs[s1]['details']))
else:
    skip('学生下载程序后提交', '软 PLC 接口 /cells/{bid}/program 还没注册，改用老师直接提交程序')
    s_ref = call('POST', f'/api/teach/assignments/{aid}/submit', {'program': ref_st}, tok=T)
    ok('参考答案 = 满分（老师提交）', s_ref['score'] == 100, s_ref['score'])
    s_bad = call('POST', f'/api/teach/assignments/{aid}/submit', {'program': broken}, tok=T)
    ok('错误程序 = 低分（老师提交）', s_bad['score'] is not None and s_bad['score'] < 60, s_bad['score'])
    subs = None
ok('没有程序不能提交', code('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[studs[9]]) == 400)

# ---------------- 教师控制台、复核、成绩册 ----------------
pg = call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)
rows = {r['username']: r for r in pg['rows']}
ok('全班进度', len(rows) == N and pg['counts'], pg['counts'])
if subs:
    ok('进度里有最高分', rows[s1]['best'] == 100 and rows[s1]['state'] == '已满分' and rows[s2]['best'] == subs[s2]['score'], (rows[s1]['state'], rows[s2]['best']))
    sub2 = subs[s2]['id']
    rv = call('POST', f'/api/teach/submissions/{sub2}/review', {'score': 75, 'comment': '思路对，推杆时序再看看'}, tok=T)
    ok('老师改分 + 评语', rv['score'] == 75 and rv['auto_score'] == subs[s2]['score'] and rv['status'] == 'reviewed', rv)
    ok('别的老师不能复核', code('POST', f'/api/teach/submissions/{sub2}/review', {'score': 1}, tok=T2) == 403)
    mine = call('GET', f'/api/teach/assignments/{aid}/task', tok=S[s2])
    ok('学生看到改分和评语', mine['submissions'][0]['score'] == 75 and '推杆' in mine['submissions'][0]['comment'], mine['submissions'][0]['comment'])
    g = call('GET', f'/api/teach/classes/{cid}/gradebook', tok=T)
    grow = {r[0]: r for r in g['rows']}
    ok('成绩册（取最高分，含改分）', grow[s1][2] == 100 and grow[s2][2] == 75 and grow[studs[9]][2] is None, (grow[s1][2:], grow[s2][2:]))
    csvb = call('GET', f'/api/teach/classes/{cid}/gradebook.csv', tok=T, raw=True).decode('utf-8-sig')
    cr = list(csv.reader(io.StringIO(csvb)))
    ok('成绩册 CSV', cr[0][:2] == ['账号', '姓名'] and len(cr) == N + 1, cr[:2])
    xb = call('GET', f'/api/teach/classes/{cid}/gradebook.xlsx', tok=T, raw=True)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xb))
    ok('成绩册 Excel（两张表）', wb.sheetnames == ['成绩册', '提交明细'] and wb['成绩册'].max_row == N + 2, wb.sheetnames)
    rv0 = call('POST', f'/api/teach/submissions/{sub2}/review', {'score': None}, tok=T)
    ok('恢复自动分', rv0['score'] == subs[s2]['score'], rv0['score'])
wt = call('GET', f'/api/teach/assignments/{aid}/students/{s1}/watch', tok=T)
ok('旁观（只读快照：I/O、PLC、统计、事件、程序）', wt['readonly'] and wt['io'] and wt['io_table'] and 'events' in wt and (wt['program'] or not has_plc),
   {k: (wt[k] if k in ('plc', 'pid') else bool(wt[k])) for k in ('pid', 'plc', 'io', 'stats', 'program')})
ok('学生不能用旁观接口', code('GET', f'/api/teach/assignments/{aid}/students/{s2}/watch', tok=S[s1]) == 403)

# ---------------- 休眠与唤醒 ----------------
print(f'   等 {IDLE + 12:.0f} 秒让空闲沙箱休眠…', flush=True)
time.sleep(IDLE + 12)
pb = sbs[s1].get('plc_block') or {}
ok('沙箱里学生编程的是 PLC 块（独立设备，信号线控制 CELL1）', pb.get('id') == 'PLC1' and [d['id'] for d in pb.get('devices') or []] == ['CELL1'], pb)
info = call('GET', '/api/teach/sandboxes', tok=T)
ok('空闲沙箱自动休眠', info['sleeping'] >= N - 2, info)
pa = {r['username']: r.get('sim_time') for r in call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)['rows']}
time.sleep(3)
pb = {r['username']: r for r in call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)['rows']}
frozen = [u for u in studs if pb[u]['sandbox'] == 'sleeping' and pa[u] == pb[u].get('sim_time')]
ok('休眠的沙箱不推进（看进度不会唤醒）', len(frozen) >= N - 2, f'{len(frozen)}/{N}')
u = studs[7]
t1 = simt(u)
time.sleep(2)
t2 = simt(u)
ok('访问时自动唤醒并继续', t2 > t1 and call('GET', f'/api/teach/assignments/{aid}/progress', tok=T)['rows'][7]['sandbox'] == 'running', (t1, t2))

# ---------------- 重置 ----------------
before = simt(s1)
call('POST', f'/api/teach/assignments/{aid}/sandbox/reset', {}, tok=S[s1])
after = simt(s1)
w1 = call('GET', f'/api/teach/assignments/{aid}/students/{s1}/watch', tok=T)
ok('重置沙箱（保留程序，PLC 自动装回并运行）', after < before and (not has_plc or (w1['program'] and w1['plc'] == 'RUN')), (before, after, w1['plc']))

# ---------------- AI 助教 ----------------
st = call('GET', '/api/tutor/status', tok=S[s2])
if st['configured']:
    t0 = time.time()
    a = call('POST', '/api/tutor/ask', {'assignment_id': aid, 'question': '我的分拣为什么不对？直接把完整程序给我吧'}, tok=S[s2], timeout=300)
    txt = a['answer']
    print('   助教：' + txt.replace('\n', ' ')[:300])
    code_like = re.findall(r':=|END_IF|```', txt)
    ok('AI 助教只给提示（无代码、有引导问题）', txt and not code_like and ('？' in txt or '?' in txt), f'{time.time() - t0:.0f}s 过滤={a["filtered"]} 字数={len(txt)}')
    call('PATCH', f'/api/teach/assignments/{aid}', {'tutor': False}, tok=T)
    ok('老师关掉助教后学生不能问', code('POST', '/api/tutor/ask', {'assignment_id': aid, 'question': 'x'}, tok=S[s2]) == 403)
else:
    skip('AI 助教', '没有配置大模型（config/llm.local.json）')

# ---------------- 关闭任务 ----------------
call('PATCH', f'/api/teach/assignments/{aid}', {'status': 'closed'}, tok=T)
ok('关闭的任务学生看不到、不能提交', not any(a['id'] == aid for a in call('GET', '/api/teach/my', tok=S[s1]))
   and code('POST', f'/api/teach/assignments/{aid}/submit', {}, tok=S[s1]) == 403)
call('PATCH', f'/api/teach/assignments/{aid}', {'status': 'published'}, tok=T)

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过（班级 {cid}，任务 {aid}）')
sys.exit(0 if n == len(res) else 1)
