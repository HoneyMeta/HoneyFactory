"""客户端（桌面模式）接口测试：登录制客户端（设计 4.3 第 4 节）+ 客户端里的教学（4.2 第 3、4、6 节）。

自己起两个服务（临时数据目录，不碰别的实例）：学校/公司服务器（serve）和客户端（desktop），中途会停掉、再起服务器来测离线。
    python tests/client_check.py
环境变量：VF_TEST_SERVER_PORT（默认 8892，OPC UA/Modbus/MQTT 用 4894/5094/18894）、VF_TEST_CLIENT_PORT（默认 8893，0 = 自动）、VF_TEST_OPCUA / VF_TEST_MODBUS / VF_TEST_MQTT（服务器的协议端口）、VF_TEST_KEEP=1 保留临时目录。
覆盖：没登录（一次性令牌换不到会话、接口 401）、登录（密码错、地址连不上、角色跟服务器走）、服务器工厂经本地服务转发（HTTP、下载链接、websocket）、
工厂列表合并、本机新建 / 下载到本机、按页面工厂分流、管理员在客户端里管账号（就是服务器的）、退出登录；
学生：本机自学、学校作业装到本机、交给学校（服务器重新评分）、作业包导出/打开/复核、AI 助教转问；
离线：服务器停掉后本机工厂照常、服务器工厂 503、交作业进待交队列、重开客户端记住的登录、离线登录；服务器回来后自动交；单机模式。
4.4：学生的"我的工厂"（新建 / 改名 / 复制 / 导出 / 导入 / 删除、归属）、提交工厂作业（本机检查、交给学校、服务器自动检查、老师给分和评语、
学生在客户端里看到；离线排队）、客户端里改密码（改服务器账号、本机离线登录跟着换）。
4.5（Electron 外壳）：/api/desktop/native（启动器 key；通知事件 submitted/queued/resent、待交数、最近的工厂、更新地址）、/api/desktop/recent、
服务器的自动更新源 /api/client/update/…（不用登录）+ 管理员上传/列表/删除 /api/admin/client-update。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vfactory.teach import package as pk  # noqa: E402

SP = int(os.environ.get('VF_TEST_SERVER_PORT', 8892))
CP = int(os.environ.get('VF_TEST_CLIENT_PORT', 8893))
if not CP:                                        # 0 = 让系统给一个空闲端口
    import socket
    with socket.socket() as _s:
        _s.bind(('127.0.0.1', 0))
        CP = _s.getsockname()[1]
SV, CL = f'http://127.0.0.1:{SP}', f'http://127.0.0.1:{CP}'
WORK = tempfile.mkdtemp(prefix='vf-client-check-')
SHOME, CHOME, AHOME = os.path.join(WORK, 'server'), os.path.join(WORK, 'client'), os.path.join(WORK, 'alone')
STAMP = time.strftime('%m%d%H%M%S')
BOOT = f"import sys, runpy; sys.path.insert(0, {ROOT!r}); sys.argv = ['vfactory'] + sys.argv[1:]; runpy.run_module('vfactory', run_name='__main__', alter_sys=True)"
res = []
procs = {}


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240], flush=True)


def call(base, method, url, body=None, tok='', raw=False, data=None, timeout=400, headers=None):
    h = {'Authorization': 'Bearer ' + tok} if tok else {}
    h['Content-Type'] = 'application/octet-stream' if data is not None else 'application/json'
    h.update(headers or {})
    r = urllib.request.Request(base + url, method=method, data=data if data is not None else (json.dumps(body).encode() if body is not None else None), headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            d = f.read()
            return d if raw else json.loads(d)
    except urllib.error.HTTPError as e:
        if not getattr(call, 'quiet', False):
            print(f'  （{method} {base}{url} → {e.code}：{e.read()[:300]!r}）', flush=True)
        raise


def err(base, method, url, body=None, tok=''):
    h = {'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + tok} if tok else {})}
    r = urllib.request.Request(base + url, method=method, data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        urllib.request.urlopen(r, timeout=400).read()
        return 200, ''
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}').get('detail', '')


S = lambda *a, **k: call(SV, *a, **k)      # noqa: E731
C = lambda *a, **k: call(CL, *a, **k)      # noqa: E731


def up(url, secs=240):
    for _ in range(secs * 2):
        try:
            urllib.request.urlopen(url + '/api/health', timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start_server():
    env = dict(os.environ, VF_HOME=SHOME, PYTHONIOENCODING='utf-8')
    log = open(os.path.join(WORK, 'server.log'), 'a', encoding='utf-8')
    procs['server'] = subprocess.Popen([sys.executable, '-c', BOOT, 'serve', '--http', str(SP), '--opcua', os.environ.get('VF_TEST_OPCUA', '4894'),
                                        '--modbus', os.environ.get('VF_TEST_MODBUS', '5094'), '--mqtt', os.environ.get('VF_TEST_MQTT', '18894')],
                                       env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    return up(SV)


def stop(name):
    p = procs.pop(name, None)
    if p:
        p.terminate()
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()


def start_client(home, port=CP):
    env = {k: v for k, v in os.environ.items() if k not in ('VF_HOME', 'VF_DESKTOP')}
    env['PYTHONIOENCODING'] = 'utf-8'
    rj = os.path.join(home, 'run.json')
    if os.path.exists(rj):
        os.remove(rj)
    procs['client'] = subprocess.Popen([sys.executable, '-c', BOOT, 'desktop', '--port', str(port), '--home', home, '--watch-pid', str(os.getpid())],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    for _ in range(240):
        if os.path.exists(rj):
            break
        time.sleep(0.5)
    with open(rj, encoding='utf-8') as f:
        return json.load(f)


def ticket(run):
    return C('POST', '/api/desktop/ticket', {}, headers={'X-VF-Key': run['key']})['token']


def _zf_read(cid):
    """客户端装好的课程包里的 course.json（文本）。"""
    import io as _io
    import zipfile as _zf
    return _zf.ZipFile(_io.BytesIO(open(os.path.join(CHOME, 'data', 'client', 'courses', f'{cid}.vfcourse'), 'rb').read())).read('course.json').decode('utf-8')


def login(u, p):
    return C('POST', '/api/desktop/login', {'server': SV, 'username': u, 'password': p})


try:
    # ================================================================ 起服务
    ok('学校/公司服务器（serve，临时数据目录）起来了', start_server(), SV)
    run = start_client(CHOME)
    ok('客户端（desktop）起来了', run.get('port') == CP, run.get('url'))
    h = C('GET', '/api/health')
    ok('健康检查：桌面模式、还没登录', h['desktop'] and h['mode'] is None and h['version'], h)

    # ================================================================ 没登录
    s0 = C('POST', '/api/desktop/session', {'token': run['token']})
    ok('没登录：一次性令牌换不到会话，要去登录页', s0.get('need_login') and 'token' not in s0, s0)
    ok('一次性令牌只能用一次', err(CL, 'POST', '/api/desktop/session', {'token': run['token']})[0] == 401)
    ok('没登录：接口一律 401', err(CL, 'GET', '/api/overview')[0] == 401 and err(CL, 'GET', '/api/plants', tok='x.y')[0] == 401)
    c, d = err(CL, 'POST', '/api/desktop/login', {'server': SV, 'username': 'admin', 'password': 'wrong'})
    ok('密码不对：中文提示', c == 400 and ('密码' in d or '账号' in d), d)
    c, d = err(CL, 'POST', '/api/desktop/login', {'server': 'http://127.0.0.1:9', 'username': 'admin', 'password': 'honey123'})
    ok('服务器连不上（也没登录过）：中文提示，可以选单机', c == 502 and '连不上' in d and '单机' in d, d)

    # ================================================================ 服务器上准备账号、班级、作业
    admin = S('POST', '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
    for u, n, r, p in (('cl_eng', '赵工', 'engineer', 'eng12345'), ('cl_teacher', '林老师', 'teacher', 'teach123')):
        S('POST', '/api/admin/users', {'username': u, 'name': n, 'role': r, 'password': p}, tok=admin)
    T = S('POST', '/api/login', {'username': 'cl_teacher', 'password': 'teach123'})['token']
    stu = f'cl{STAMP[-6:]}'
    cid = S('POST', '/api/teach/classes', {'name': f'客户端班 {STAMP}'}, tok=T)['id']
    S('POST', f'/api/teach/classes/{cid}/roster', {'csv': f'{stu},客户端同学'}, tok=T)
    aid = S('POST', '/api/teach/assignments', {'class_id': cid, 'scene': 's01_motor_latch', 'title': '启停自锁（客户端做）', 'due': '2030-01-01 18:00'}, tok=T)['id']
    S('POST', '/api/teach/courses/plc_basics/publish', {'class_id': cid, 'open_all': True}, tok=T)
    S('POST', '/api/teach/courses/machining/publish', {'class_id': cid, 'open_all': True}, tok=T)
    ref = S('GET', '/api/teach/scenes/s01_motor_latch', tok=T)['reference']['st']
    ok('学校服务器上没有客户端接口', err(SV, 'GET', '/api/client/status', tok=T)[0] == 404)
    splants = [p['id'] for p in S('GET', '/api/plants', tok=admin)['plants']]

    # ================================================================ 工程师：服务器工厂 + 本机工厂
    lg = login('cl_eng', 'eng12345')
    L = lg['token']
    ok('工程师用服务器账号登录：联网模式、在线', lg['mode'] == 'server' and lg['online'] and lg['account']['role'] == 'engineer', {k: lg[k] for k in ('mode', 'online', 'account')})
    me = C('GET', '/api/me', tok=L)
    ok('客户端里的账号和角色就是服务器的', me['username'] == 'cl_eng' and me['role'] == 'engineer' and me['name'] == '赵工', me)
    pl = C('GET', '/api/plants', tok=L)
    ok('工厂列表：服务器的工厂（标 local=false）', [p['id'] for p in pl['plants'] if not p['local']] == splants and pl.get('template_info'), [p['id'] for p in pl['plants']])
    sp = splants[0]
    m1, m2 = C('GET', f'/api/p/{sp}/meta', tok=L), S('GET', f'/api/p/{sp}/meta', tok=admin)
    ok('服务器工厂的接口经本地服务转发', m1['name'] == m2['name'] and len(m1['stations']) == len(m2['stations']), m1['name'])
    csv = C('GET', f'/api/p/{sp}/points.csv?token={L}', raw=True).decode('utf-8-sig')
    ok('下载链接（?token=本机会话）也能转发', csv.startswith('工位,'), csv[:30])
    from websockets.sync.client import connect as wsc
    with wsc(f'ws://127.0.0.1:{CP}/ws/{sp}?token={L}', open_timeout=10) as ws:
        msg = json.loads(ws.recv(timeout=10))
    ok('服务器工厂的实时状态（websocket）经本地服务转发', msg.get('type') == 'state' and 'kpi' in msg['data'], list(msg.get('data', {}))[:5])
    ok('请求头 X-VF-Plant 是服务器工厂：其他接口也交给服务器', C('GET', '/api/catalog', tok=L, headers={'X-VF-Plant': sp}) == S('GET', '/api/catalog', tok=admin))
    c, _ = err(CL, 'GET', '/api/admin/users', tok=L)
    ok('工程师不能管账号（服务器说了算）', c == 403, c)
    nl = C('POST', '/api/plants', {'name': '本机试验线', 'template': 'machining', 'local': True}, tok=L)
    lp1 = nl['id']
    ok('本机新建：编号带 local- 前缀', lp1.startswith('local-'), lp1)
    pl2 = C('GET', '/api/plants', tok=L)['plants']
    ok('本机工厂出现在列表里（local=true），服务器上没有', any(p['id'] == lp1 and p['local'] for p in pl2) and err(SV, 'GET', f'/api/p/{lp1}/meta', tok=admin)[0] == 404)
    ok('本机工厂的接口在本机', C('GET', f'/api/p/{lp1}/meta', tok=L)['name'] == '本机试验线')
    ok('工作台的"本机/服务器"标记', C('GET', f'/api/desktop/where/{lp1}', tok=L)['local'] and not C('GET', f'/api/desktop/where/{sp}', tok=L)['local'])
    dl = C('POST', '/api/desktop/plants/download', {'pid': sp, 'name': '示范厂（本机）'}, tok=L)
    lp2 = dl['id']
    cells = C('GET', f'/api/p/{lp2}/plc/cells', tok=L)['cells']
    ok('下载到本机：模型 + PLC 程序，在本机运行', lp2.startswith('local-') and dl['plc_programs'] >= 1 and len(cells) >= 1, dl)
    st1 = C('GET', f'/api/p/{lp2}/state', tok=L)
    ok('下载下来的工厂在本机跑', st1['kpi'] is not None, st1.get('time'))
    C('POST', '/api/desktop/logout', {}, tok=L)
    ok('退出登录：接口 401，令牌换不到会话', err(CL, 'GET', '/api/overview', tok=L)[0] == 401 and C('POST', '/api/desktop/session', {'token': ticket(run)}).get('need_login'))

    # ================================================================ 管理员：账号就是服务器的
    La = login('admin', 'honey123')['token']
    users = C('GET', '/api/admin/users', tok=La)['users']
    ok('管理员在客户端里管账号 = 服务器的"用户与角色"', any(u['username'] == stu for u in users) and any(u['username'] == 'cl_eng' for u in users), len(users))
    C('POST', '/api/desktop/logout', {}, tok=La)

    # ================================================================ 学生：本机自学 + 学校作业
    lg = login(stu, '123456')
    L = lg['token']
    ok('学生登录（初始密码：前端会要求改）', lg['account']['role'] == 'student' and lg.get('must_change_pw'), lg['account'])
    st = C('GET', '/api/client/status', tok=L)
    ok('学校服务器 = 登录的服务器，不用再单独登录', st['school']['connected'] and st['school']['url'] == SV and st['school']['username'] == stu, st['school'])
    ok('状态接口不返回令牌', 'token' not in json.dumps(st))
    pls = C('GET', '/api/plants', tok=L)
    ok('学生的工厂列表：没有工厂（和网页端一样）', pls['plants'] == [], len(pls['plants']))
    C('POST', '/api/client/local/ensure', {}, tok=L)
    mc = C('GET', '/api/teach/my/courses', tok=L)
    mine = [c for c in mc['courses'] if c['class_name'] == '本机自学']
    ok('本机自学：客户端自带的课程出现在课程地图（学生的教学接口在本机）', len(mine) >= 3, [c['course'] for c in mine])
    pb = next(c for c in mine if c['course'] == 'plc_basics')
    fl = [l for ch in pb['chapters'] for l in ch['lessons']]
    ok('本机解锁：第 1 课可做、第 2 课锁定', fl[0]['state'] == 'open' and fl[1]['state'] == 'locked', [l['state'] for l in fl[:3]])
    la = fl[0]['aid']
    tk = C('GET', f'/api/teach/assignments/{la}/task', tok=L)
    ok('本机自学的课：标明是本机', tk['desktop'] and tk['desktop']['local'] and tk['desktop']['school'] is None, tk['desktop'])
    sb = C('POST', f'/api/teach/assignments/{la}/sandbox', tok=L)
    ok('本机课的沙箱在本机', C('GET', f"/api/desktop/where/{sb['pid']}", tok=L)['local'], sb['pid'])
    d1 = C('POST', f"/api/p/{sb['pid']}/cells/{sb['bid']}/program/download", {'program': ref}, tok=L)
    ok('本机沙箱下载参考程序（PLC 在本机跑）', d1.get('ok') and d1.get('state') == 'RUN', {k: d1.get(k) for k in ('ok', 'state', 'errors')})
    ok('本机沙箱编号带 L-（不会和学校服务器上的沙箱撞号）', sb['pid'].startswith('sb-L-'), sb['pid'])
    ok('沙箱信息里有学生编程的 PLC 块（独立设备，信号线控制单元）', (sb.get('plc_block') or {}).get('id') == 'PLC1'
       and [d['id'] for d in sb['plc_block']['devices']] == [sb['bid']], sb.get('plc_block'))
    lsp = C('POST', f'/api/teach/assignments/{la}/submit', {}, tok=L)
    ok('本机评分（PLC 课：下载到 PLC 块的参考程序满分）', lsp.get('score') == 100 and not lsp['trial'], (lsp.get('score'), lsp.get('error')))
    # 产线课（模型就是作业）也评一次
    mp = next(c for c in mine if c['course'] == 'machining')
    ml = next(l for ch in mp['chapters'] for l in ch['lessons'] if l['state'] == 'open')
    C('POST', f"/api/teach/assignments/{ml['aid']}/sandbox", tok=L)
    ls = C('POST', f"/api/teach/assignments/{ml['aid']}/submit", {'answers': {'q_cap': 0}}, tok=L)
    ok('本机评分（本机预估分，产线课）', isinstance(ls.get('score'), (int, float)) and not ls['trial'], (ml['title'], ls.get('score')))
    qd = next((d for d in ls.get('details') or [] if d.get('key') == 'q_cap'), {})
    ok('4.6.2 本机自学：本机评分后就显示正确答案和解析', (ls.get('reveal') or {}).get('state') == 'shown' and qd.get('your', '').startswith('A.')
       and qd.get('correct', '').startswith('B.') and '3600' in qd.get('explain', ''), {k: qd.get(k) for k in ('your', 'correct', 'explain')})
    my = C('GET', '/api/client/school/my', tok=L)
    task = next(t for t in my['tasks'] if t['id'] == aid)
    smc = next(c for c in my['courses'] if c['course'] == 'machining')
    sl = next(l for ch in smc['chapters'] for l in ch['lessons'] if not l['locked'])
    ok('学校的"我的作业"：单独任务 + 发布的课程', task['local_aid'] is None and sl['local_aid'] is None, [t['title'] for t in my['tasks']] + [smc['name']])
    sa = sl['aid']
    lid = C('POST', '/api/client/school/open', {'remote_aid': sa}, tok=L)['local_aid']
    tk2 = C('GET', f'/api/teach/assignments/{lid}/task', tok=L)
    ok('学校作业装到本机：标明学校作业号、已连接', tk2['desktop']['school']['remote_aid'] == sa and tk2['desktop']['school']['connected'], tk2['desktop'])
    ok('再打开一次是同一个本机作业', C('POST', '/api/client/school/open', {'remote_aid': sa}, tok=L)['local_aid'] == lid)
    sb2 = C('POST', f'/api/teach/assignments/{lid}/sandbox', tok=L)
    ok('学校作业的沙箱在本机', C('GET', f"/api/desktop/where/{sb2['pid']}", tok=L)['local'], sb2['pid'])
    loc = C('POST', f'/api/teach/assignments/{lid}/submit', {}, tok=L)
    rs = C('POST', '/api/client/school/submit', {'aid': lid}, tok=L)
    ok('提交给老师：打包交到学校，学校重新评分（和本机预估分一致）', rs['remote']['score'] == loc['score'] and rs['remote']['source'] == 'client',
       (loc['score'], rs['remote']['score']))
    subs = S('GET', f'/api/teach/assignments/{sa}/submissions?username={stu}', tok=T)
    ok('老师在服务器上看到这次提交（来源：客户端，带作业包）', subs and subs[0]['source'] == 'client' and subs[0]['has_package'], [(x['source'], x['score']) for x in subs])
    xp = C('GET', f'/api/teach/assignments/{lid}/package', tok=L, raw=True)
    xm = pk.read(xp).manifest
    ok('导出的作业包：学校地址、学校作业号、学生账号', xm['server'] == SV and xm['assignment_id'] == sa and xm['student']['username'] == stu, xm.get('student'))
    pth = os.path.join(CHOME, f'pkgtest-{STAMP}.vfhw')
    with open(pth, 'wb') as f:
        f.write(xp)
    # 学校的 PLC 单个任务（s01）：装到本机 → 下载程序到 PLC 块 → 本机评分 → 交给学校（学校用同一份程序重新评分）
    pid2 = C('POST', '/api/client/school/open', {'remote_aid': aid}, tok=L)['local_aid']
    sb3 = C('POST', f'/api/teach/assignments/{pid2}/sandbox', tok=L)
    d3 = C('POST', f"/api/p/{sb3['pid']}/cells/{sb3['plc_block']['id']}/program/download", {'program': ref}, tok=L)
    loc3 = C('POST', f'/api/teach/assignments/{pid2}/submit', {}, tok=L)
    rs3 = C('POST', '/api/client/school/submit', {'aid': pid2}, tok=L)
    ok('学校的 PLC 作业：程序下载到 PLC 块 → 本机满分 → 交给学校重新评分一致', d3.get('ok') and loc3.get('score') == 100 and rs3['remote']['score'] == 100,
       (d3.get('state'), loc3.get('score'), rs3['remote'].get('score')))
    # 学生打开自己的作业包：装进自己这个作业的沙箱（不是老师的复核沙箱）
    xp3 = C('GET', f'/api/teach/assignments/{pid2}/package', tok=L, raw=True)
    pth3 = os.path.join(CHOME, f'pkgplc-{STAMP}.vfhw')
    with open(pth3, 'wb') as f:
        f.write(xp3)
    C('POST', f'/api/teach/assignments/{pid2}/sandbox/reset', {'clear_program': True}, tok=L)
    lv0 = C('GET', f'/api/teach/assignments/{pid2}/live', tok=L)
    oi = C('POST', '/api/client/open_package', {'path': pth3}, tok=L)
    orr = C('POST', f"/api/client/packages/{oi['id']}/run", {}, tok=L)
    lv1 = C('GET', f'/api/teach/assignments/{pid2}/live', tok=L)
    ok('学生双击自己的作业包：程序装回自己的作业沙箱（PLC 运行），能接着做、再交', orr.get('own') and orr['aid'] == pid2 and orr['pid'] == sb3['pid']
       and not lv0['has_program'] and lv1['has_program'] and lv1['plc'] == 'RUN', (orr.get('pid'), lv0['has_program'], lv1['has_program'], lv1.get('plc')))
    oi2 = C('POST', '/api/client/open_package', {'path': pth}, tok=L)
    orr2 = C('POST', f"/api/client/packages/{oi2['id']}/run", {}, tok=L)
    ok('学生打开自己的产线课作业包：模型装回自己的沙箱', orr2.get('own') and orr2['aid'] == lid and orr2['pid'] == sb2['pid'], orr2.get('pid'))
    ta = C('POST', '/api/tutor/ask', {'assignment_id': lid, 'question': '我的程序为什么松开启动按钮就停了？'}, tok=L)
    ok('AI 助教：转问学校（学校没配大模型时给内置提示）', bool(ta.get('answer')), ta.get('answer', '')[:60])

    # 4.6 老师做的课：客户端下载签名的课程包，离线本机判分，交给学校重评一致；被改过的包装不上
    dq = S('POST', '/api/teach/authoring', {'name': f'客户端测验 {STAMP}'}, tok=T)
    S('PUT', f"/api/teach/authoring/{dq['id']}", {'course': {'name': f'客户端测验 {STAMP}', 'chapters': [{'id': 'c1', 'title': '一', 'lessons': [
        {'id': 'q1', 'title': '测验', 'kind': 'quiz', 'brief_md': '答两道题。', 'rules': [{'key': 'a', 'kind': 'answer', 'label': '选 B', 'choices': ['A', 'B'], 'answer': 1, 'weight': 3,
                                                                   'explain': '题目说了选 B。'},
                                                                  {'key': 'n', 'kind': 'answer', 'qtype': 'number', 'label': '60', 'answer': 60, 'tol': 1, 'weight': 1}]}]}]}}, tok=T)
    S('POST', f"/api/teach/authoring/{dq['id']}/publish", {}, tok=T)
    S('POST', f"/api/teach/courses/{dq['id']}/publish", {'class_id': cid}, tok=T)
    qra = next(a for a in S('GET', f'/api/teach/assignments?class_id={cid}', tok=T) if a.get('course') == dq['id'])['id']
    qla = C('POST', '/api/client/school/open', {'remote_aid': qra}, tok=L)['local_aid']
    inst = C('GET', '/api/client/courses', tok=L)
    me_c = next((x for x in inst['courses'] if x['id'] == dq['id']), {})
    ok('老师做的课：客户端装好签名的课程包（记下学校公钥）', me_c.get('ok') and me_c.get('version') == 1 and inst['keys'], inst)
    C('POST', '/api/client/school/logout', {}, tok=L)                     # 离线
    C('PUT', f'/api/teach/assignments/{qla}/answers', {'answers': {'a': 1, 'n': 63}}, tok=L)
    lq = C('POST', f'/api/teach/assignments/{qla}/submit', {}, tok=L)
    ok('离线：本机按课程包判分（一题对一题错 = 75）', lq.get('score') == 75, lq.get('score'))
    lqd = {d['key']: d for d in lq.get('details') or []}
    ok('4.6.2 学校作业的本机预估分：只有"你的答案"，不给正确答案和解析', (lq.get('reveal') or {}).get('state') == 'local' and lqd.get('n', {}).get('your') == '63'
       and not any('correct' in d or 'explain' in d for d in lqd.values()), {k: {x: d.get(x) for x in ('your', 'correct')} for k, d in lqd.items()})
    ok('4.6.2 课程包里的解析也是封存的', all('explain' not in r for ch in json.loads(_zf_read(dq['id']))['chapters'] for l in ch['lessons'] for r in l['rules'])
       and any(r.get('explain_seal') for ch in json.loads(_zf_read(dq['id']))['chapters'] for l in ch['lessons'] for r in l['rules']))
    C('POST', '/api/client/school/login', {'url': SV, 'username': stu, 'password': '123456'}, tok=L)      # 重新连上学校
    rq = C('POST', '/api/client/school/submit', {'aid': qla}, tok=L)
    ok('交给学校：服务器用自己的课程重评 = 本机分', rq['remote']['score'] == lq['score'] and rq['remote']['source'] == 'client', (lq['score'], rq['remote'].get('score')))
    rqd = {d['key']: d for d in rq['remote'].get('details') or []}
    ok('4.6.2 学校重评的结果按老师的设置（默认提交后显示）带正确答案和解析', (rq['remote'].get('reveal') or {}).get('state') == 'shown'
       and rqd.get('n', {}).get('correct', '').startswith('60') and rqd.get('a', {}).get('explain') == '题目说了选 B。', {k: {x: d.get(x) for x in ('your', 'correct', 'explain')} for k, d in rqd.items()})
    srq = C('GET', f'/api/client/school/results?aid={qla}', tok=L)
    ok('4.6.2 客户端"老师那边的成绩"里也有正确答案', (srq['submissions'][0].get('reveal') or {}).get('state') == 'shown'
       and any(d.get('correct') for d in srq['submissions'][0].get('details') or []), srq['submissions'][0].get('reveal'))
    import io as _io
    import zipfile as _zf
    raw = open(os.path.join(CHOME, 'data', 'client', 'courses', f"{dq['id']}.vfcourse"), 'rb').read()
    z = _zf.ZipFile(_io.BytesIO(raw))
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, 'w') as w:
        for nme in z.namelist():
            w.writestr(nme, z.read(nme).replace(b'"weight": 3', b'"weight": 30') if nme == 'course.json' else z.read(nme))
    import base64 as _b64
    c5, d5 = err(CL, 'POST', '/api/client/courses/install', {'data': _b64.b64encode(buf.getvalue()).decode()}, tok=L)
    ok('改过的课程包（改分值）装不上', c5 == 400 and '没有安装' in str(d5), (c5, d5))

    # 4.6 MES 课（M 的 mes_intro）：交作业时客户端在本机 MES 上取快照，本机评分和学校复评都按快照 → 分数一致（这里用一个假的本机 MES）
    import http.server
    import threading

    class FakeMes(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            vals = {'wo': 1, 'rep': 3}
            out = {'values': {r['key']: vals.get(r['key'], 0) for r in body.get('rules') or []}} if self.path.endswith('/snapshot') else {'value': vals.get(body.get('key'), 0)}
            b = json.dumps(out).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass
    fm = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeMes)
    threading.Thread(target=fm.serve_forever, daemon=True).start()
    os.makedirs(os.path.join(CHOME, 'mes'), exist_ok=True)
    cur_json = os.path.join(CHOME, 'mes', 'current.json')
    with open(cur_json, 'w', encoding='utf-8') as f:
        json.dump({'port': fm.server_address[1], 'key': 'test'}, f)
    try:
        S('POST', '/api/teach/courses/mes_intro/publish', {'class_id': cid, 'open_all': True}, tok=T)
        mra = next(a for a in S('GET', f'/api/teach/assignments?class_id={cid}', tok=T) if a.get('course') == 'mes_intro' and a.get('lesson') == 'm01')['id']
        mla = C('POST', '/api/client/school/open', {'remote_aid': mra}, tok=L)['local_aid']
        C('PUT', f'/api/teach/assignments/{mla}/answers', {'answers': {'q_status': 1}}, tok=L)
        lm = C('POST', f'/api/teach/assignments/{mla}/submit', {}, tok=L)
        ok('MES 课本机评分：按本机 MES 的快照判（工单、自动报工、作答都对 = 100）', lm.get('score') == 100, [(d['key'], d['ok']) for d in lm.get('details') or []])
        mp = pk.read(C('GET', f'/api/teach/assignments/{mla}/package', tok=L, raw=True))
        ok('MES 课作业包带 MES 快照', mp.manifest['kind'] == 'mes' and mp.mes_snapshot == {'wo': 1, 'rep': 3}, mp.mes_snapshot)
        rm = C('POST', '/api/client/school/submit', {'aid': mla}, tok=L)
        ok('MES 课交给学校：服务器没有 MES，按快照复评 = 本机分', rm['remote']['score'] == lm['score'] == 100, (lm.get('score'), rm['remote'].get('score')))
        Ss = S('POST', '/api/login', {'username': stu, 'password': '123456'})['token']
        S('PUT', f'/api/teach/assignments/{mra}/answers', {'answers': {'q_status': 1}}, tok=Ss)
        wm = S('POST', f'/api/teach/assignments/{mra}/submit', {}, tok=Ss)
        ok('网页上直接交 MES 课（服务器没有 MES、没有快照）：MES 检查判"没有连上 MES"', wm['score'] == 30 and any('没有连上 MES' in (d.get('text') or '') for d in wm['details']), wm['score'])
    finally:
        os.remove(cur_json)
        fm.shutdown()

    fake = pk.read(xp3)
    fake.manifest['student'] = {'username': 'someone_else', 'name': '别人'}
    pth4 = os.path.join(CHOME, f'pkgother-{STAMP}.vfhw')
    with open(pth4, 'wb') as f:
        f.write(pk.build(fake.manifest, fake.programs, fake.model, fake.answers, {}))
    oi4 = C('POST', '/api/client/open_package', {'path': pth4}, tok=L)
    c4, d4 = err(CL, 'POST', f"/api/client/packages/{oi4['id']}/run", {}, tok=L)
    ok('学生打开别人的作业包：不让打开（也不进复核沙箱）', c4 == 403 and '自己的作业包' in str(d4), (c4, d4))

    # ================================================================ 4.4 我的工厂（学生自己的本机工厂）+ 提交工厂作业
    fa = S('POST', '/api/teach/assignments', {'class_id': cid, 'kind': 'factory', 'title': '设计一座小工厂（客户端）', 'brief_md': '## 要求\n有出口、有合格品',
                                              'checks': [{'kind': 'valid'}, {'kind': 'block', 'type': 'plc', 'min': 1}, {'kind': 'good', 'min': 1}], 'hours': 1},
           tok=T)['id']
    mp0 = C('GET', '/api/client/myplants', tok=L)
    keys = {t['key'] for t in mp0['templates']}
    ok('我的工厂：一开始是空的；起点有空白 / 课程里的产线 / 控制单元演示 / 完整示范', mp0['plants'] == []
       and {'blank', 'showcase', 'course:machining/m01', 'cells/motor'} <= keys, len(keys))
    g1 = C('POST', '/api/client/myplants', {'name': '我的机加线', 'template': 'course:machining/m01'}, tok=L)
    g2 = C('POST', '/api/client/myplants', {'name': '我的电机控制', 'template': 'cells/motor'}, tok=L)
    g3 = C('POST', '/api/client/myplants', {'name': '空白', 'template': 'blank'}, tok=L)
    ok('新建三座（数量不限）：编号 local-、在本机运行', all(x['id'].startswith('local-') for x in (g1, g2, g3))
       and all(C('GET', f"/api/desktop/where/{x['id']}", tok=L)['local'] for x in (g1, g2, g3)), [x['id'] for x in (g1, g2, g3)])
    ok('学生能打开、改、保存自己的工厂（工作台接口不受学生范围限制）', C('GET', f"/api/p/{g1['id']}/model", tok=L)['model']['blocks']
       and err(CL, 'POST', f"/api/p/{g1['id']}/save", {}, tok=L)[0] == 200 and err(CL, 'POST', f"/api/p/{g1['id']}/sim", {'paused': True}, tok=L)[0] == 200)
    with wsc(f"ws://127.0.0.1:{CP}/ws/{g1['id']}?token={L}", open_timeout=10) as ws:
        msgf = json.loads(ws.recv(timeout=10))
    ok('自己工厂的实时状态（websocket）', msgf.get('type') == 'state', msgf.get('type'))
    ok('别人在这台电脑上的本机工厂（工程师建的）：学生进不去，也不在"我的工厂"里', err(CL, 'GET', f'/api/p/{lp1}/meta', tok=L)[0] == 403
       and lp1 not in [x['id'] for x in C('GET', '/api/client/myplants', tok=L)['plants']])
    C('PATCH', f"/api/client/myplants/{g3['id']}", {'name': '空白改名'}, tok=L)
    cpy = C('POST', f"/api/client/myplants/{g2['id']}/copy", {}, tok=L)
    ex = C('GET', f"/api/client/myplants/{g2['id']}/export", tok=L, raw=True)
    exm = pk.read(ex)
    imp = C('POST', '/api/client/myplants/import', {'data': base64.b64encode(ex).decode(), 'name': '导入的电机'}, tok=L)
    C('DELETE', f"/api/client/myplants/{cpy['id']}", tok=L)
    names = sorted(x['name'] for x in C('GET', '/api/client/myplants', tok=L)['plants'])
    ok('改名 / 复制 / 导出（.vfplant：版本 2、模型 + PLC 程序）/ 导入 / 删除', names == sorted(['我的机加线', '我的电机控制', '空白改名', '导入的电机'])
       and exm.manifest['kind'] == 'factory' and exm.manifest['version'] == 2 and exm.programs, names)
    pl0 = list(exm.programs)[0]
    ok('导入的工厂带着 PLC 程序', C('GET', f"/api/p/{imp['id']}/cells/{pl0}/program", tok=L)['program']['source'] == exm.programs[pl0]['source'], pl0)
    my2 = C('GET', '/api/client/school/my', tok=L)
    ft = next(t for t in my2['tasks'] if t['id'] == fa)
    ok('学校的提交工厂作业出现在"学校作业"里', ft['kind'] == 'factory', ft['title'])
    fl = C('POST', '/api/client/school/open', {'remote_aid': fa}, tok=L)['local_aid']
    ftk = C('GET', f'/api/teach/assignments/{fl}/task', tok=L)
    ok('装到本机：也是提交工厂作业（要求、检查项和学校一样）', ftk['kind'] == 'factory' and len(ftk['scene']['rules']) == 3
       and ftk['desktop']['school']['remote_aid'] == fa, [r['label'] for r in ftk['scene']['rules']])
    lc = C('POST', f'/api/teach/assignments/{fl}/submit', {'plant': g1['id']}, tok=L)
    ok('本机检查（本机预估分）：机加线没有 PLC → 3 条过 2 条', abs(lc['score'] - 66.7) < 0.1, lc['score'])
    c, d = err(CL, 'POST', f'/api/teach/assignments/{fl}/submit', {'plant': lp1}, tok=L)
    ok('不能拿别人的本机工厂交', c == 403, d)
    rs4 = C('POST', '/api/client/school/submit', {'aid': fl, 'plant': g1['id']}, tok=L)
    ok('提交给老师：学校重新检查（和本机一致），来源客户端', rs4['remote']['score'] == lc['score'] and rs4['remote']['source'] == 'client', rs4['remote'].get('score'))
    NAT = lambda since=0: C('GET', f'/api/desktop/native?since={since}', headers={'X-VF-Key': run['key']})   # noqa: E731  外壳（Electron）轮询的接口
    ev = NAT()['events']
    ok('4.5 外壳通知：联网交上 → submitted 事件（带学校的作业名）', any(e['kind'] == 'submitted' and e['title'] for e in ev), [(e['kind'], e['title']) for e in ev][-3:])
    fsubs = S('GET', f'/api/teach/assignments/{fa}/submissions?username={stu}', tok=T)
    fpk = pk.read(S('GET', f"/api/teach/submissions/{fsubs[0]['id']}/package", tok=T, raw=True))
    ok('老师看到交的是哪座工厂（我的机加线），作业包版本 2', fsubs[0]['plant']['name'] == '我的机加线' and fpk.manifest['version'] == 2
       and fpk.manifest['plant']['id'] == g1['id'], fsubs[0].get('plant'))
    S('POST', f"/api/teach/submissions/{fsubs[0]['id']}/review", {'score': 85, 'comment': '再加一台 PLC 控制机床'}, tok=T)
    sr = C('GET', f'/api/client/school/results?aid={fl}', tok=L)
    ok('老师给的分和评语：学生在客户端里看得到（就是成绩）', sr['best'] == 85 and sr['submissions'][0]['comment'] == '再加一台 PLC 控制机床'
       and sr['submissions'][0]['score'] == 85, sr.get('best'))

    # ================================================================ 老师用客户端打开学生的作业包（双击 .vfhw）
    C('POST', '/api/desktop/logout', {}, tok=L)
    Lt = login('cl_teacher', 'teach123')['token']
    ok('老师登录客户端：教学接口在服务器（教学控制台）', any(c['id'] == cid for c in C('GET', '/api/teach/classes', tok=Lt)))
    info = C('POST', '/api/client/open_package', {'path': pth}, tok=Lt)
    rr = C('POST', f"/api/client/packages/{info['id']}/run", {}, tok=Lt)
    ok('打开作业包：在本机复核沙箱里运行', info['runnable'] and info['student']['username'] == stu and rr['pid'].startswith('sb-review-p')
       and C('GET', f"/api/desktop/where/{rr['pid']}", tok=Lt)['local'], rr['pid'])
    codes = [err(CL, 'GET', f"/api/p/{rr['pid']}/{x}", tok=Lt)[0] for x in ('meta', 'model', 'state')]
    ok('老师在工作台里打开复核沙箱（meta/model/state 可读）', codes == [200, 200, 200], codes)
    C('POST', '/api/desktop/logout', {}, tok=Lt)
    L = login(stu, '123456')['token']

    # ================================================================ 离线
    stop('server')
    ov = C('GET', '/api/overview', tok=L)
    ok('服务器停了：列表照常（只有本机部分），标明离线', ov.get('offline') is True, {k: ov.get(k) for k in ('offline', 'server')})
    ok('健康检查：离线', C('GET', '/api/health')['online'] is False)
    q = C('POST', '/api/client/school/submit', {'aid': lid}, tok=L)
    ok('离线交作业：存进待交队列', q.get('queued') and q['outbox']['state'] == 'waiting', q.get('msg'))
    qf = C('POST', '/api/client/school/submit', {'aid': fl, 'plant': g2['id']}, tok=L)
    ok('离线交提交工厂作业：选的工厂打成包排队', qf.get('queued') and qf['outbox']['plant'] == g2['id'], qf.get('outbox'))
    nq = NAT()
    ok('4.5 外壳通知：离线交 → queued 事件，托盘的待交数 2', [e['kind'] for e in nq['events']].count('queued') == 2 and nq['outbox']['waiting'] == 2, nq['outbox'])
    ok('本机课的沙箱离线照常', C('GET', f"/api/p/{sb2['pid']}/state", tok=L)['kpi'] is not None)
    stop('client')
    run = start_client(CHOME)
    s1 = C('POST', '/api/desktop/session', {'token': run['token']})
    L = s1.get('token', '')
    ok('断网时重开客户端：记住的登录直接进', L and s1['mode'] == 'server' and s1['account']['username'] == stu, {k: s1.get(k) for k in ('mode', 'online')})
    C('POST', f'/api/teach/assignments/{lid}/sandbox', tok=L)                 # 重开后从"我的课程"进课（沙箱按需启动）
    ok('离线时本机工厂、本机课照常（服务器工厂 503）', C('GET', f"/api/p/{sb2['pid']}/state", tok=L)['kpi'] is not None
       and err(CL, 'GET', f'/api/p/{sp}/meta', tok=L)[0] == 503)
    c, d = err(CL, 'POST', '/api/desktop/login', {'server': SV, 'username': stu, 'password': 'wrong'})
    ok('离线登录：密码不对不放行', c == 400 and '密码' in d, d)
    lo = login(stu, '123456')
    ok('离线登录：7 天内在这台电脑登录过、密码对 → 进得去', lo.get('offline') and lo['token'], lo.get('mode'))
    L = lo['token']
    ok('设置里看得到待交作业', [x['state'] for x in C('GET', '/api/desktop/settings', tok=L)['outbox']] == ['waiting', 'waiting'])
    start_server()
    fr = C('POST', '/api/desktop/outbox/flush', {}, tok=L)
    subs2 = S('GET', f'/api/teach/assignments/{sa}/submissions?username={stu}', tok=T)
    ok('服务器回来：待交作业自动交上，服务器重新评分', fr['sent'] == 2 and len(subs2) == len(subs) + 1 and subs2[0]['source'] == 'client', (fr['sent'], len(subs2)))
    fsubs2 = S('GET', f'/api/teach/assignments/{fa}/submissions?username={stu}', tok=T)
    ok('排队的提交工厂作业也交上了（我的电机控制：有 PLC）', len(fsubs2) == len(fsubs) + 1 and fsubs2[0]['plant']['name'] == '我的电机控制'
       and fsubs2[0]['auto_score'] is not None, [(x['plant']['name'], x['auto_score']) for x in fsubs2])
    ok('健康检查：又在线了', C('GET', '/api/health')['online'] is True)

    # ================================================================ 4.5 Electron 外壳用的接口：通知事件、最近的工厂、自动更新的下载源
    nr = NAT()
    ok('外壳通知：联网后自动补交 → resent 事件 ×2，待交数归零', [e['kind'] for e in nr['events']].count('resent') == 2 and nr['outbox']['waiting'] == 0, nr['outbox'])
    ok('外壳接口：只增量给新事件（since）', NAT(nr['seq'])['events'] == [] and nr['seq'] >= 2)
    ok('外壳接口：没有启动器 key → 403', err(CL, 'GET', '/api/desktop/native')[0] == 403)
    ok('外壳接口：联网模式给出更新地址 = 服务器/api/client/update/', nr['update_url'] == SV + '/api/client/update/' and nr['mode'] == 'server' and nr['user'] == stu, nr['update_url'])
    C('POST', '/api/desktop/recent', {'pid': g1['id'], 'name': '我的机加线'}, tok=L)
    C('POST', '/api/desktop/recent', {'pid': 'sb-x', 'name': '沙箱'}, tok=L)
    C('POST', '/api/desktop/recent', {'pid': g2['id'], 'name': '我的电机控制'}, tok=L)
    C('POST', '/api/desktop/recent', {'pid': g1['id'], 'name': '我的机加线'}, tok=L)
    rc = NAT()['recent']
    ok('最近的工厂：最新的在前、去重、沙箱不记、标本机', [r['pid'] for r in rc][:2] == [g1['id'], g2['id']] and rc[0]['local'] and len(rc) == 2, [(r['pid'], r['local']) for r in rc])
    ok('最近的工厂：网页也能读（按当前账号）', [r['pid'] for r in C('GET', '/api/desktop/recent', tok=L)['recent']] == [r['pid'] for r in rc])
    c, d = err(SV, 'GET', '/api/client/update/latest.yml')
    ok('更新源：服务器还没放更新 → 404 中文提示（不用登录）', c == 404 and '更新' in d, (c, d))
    yml = '\n'.join(['version: 99.0.0', 'files:', '  - url: HoneyVF-Setup-99.0.0.exe', '    sha512: abc', '    size: 3',
                     'path: HoneyVF-Setup-99.0.0.exe', 'sha512: abc', ''])
    ok('更新源：非管理员不能上传', err(SV, 'PUT', '/api/admin/client-update/latest.yml', tok=T)[0] == 403)
    call.quiet = True
    try:
        call(SV, 'PUT', '/api/admin/client-update/a%20b.yml', data=b'x', tok=admin)
        bad = 200
    except urllib.error.HTTPError as e:
        bad = e.code
    call.quiet = False
    ok('更新源：文件名只能是字母数字点横线', bad == 400, bad)
    S('PUT', '/api/admin/client-update/HoneyVF-Setup-99.0.0.exe', data=b'exe', tok=admin)
    up1 = S('PUT', '/api/admin/client-update/latest.yml', data=yml.encode(), tok=admin)
    ok('更新源：管理员上传安装包和 latest.yml', up1['ok'] and up1['version'] == '99.0.0', up1)
    ok('更新源：不登录就能下 latest.yml 和安装包（electron-updater 不带令牌）', S('GET', '/api/client/update/latest.yml', raw=True).decode().startswith('version: 99.0.0')
       and S('GET', '/api/client/update/HoneyVF-Setup-99.0.0.exe', raw=True) == b'exe')
    lst = S('GET', '/api/admin/client-update', tok=admin)
    ok('更新源：管理员看得到版本和文件', lst['version'] == '99.0.0' and {f['name'] for f in lst['files']} == {'latest.yml', 'HoneyVF-Setup-99.0.0.exe'}, lst['files'])
    S('DELETE', '/api/admin/client-update/latest.yml', tok=admin)
    ok('更新源：删掉 latest.yml 后又是"没有更新"', err(SV, 'GET', '/api/client/update/latest.yml')[0] == 404)

    # ================================================================ 客户端里改密码：改的是服务器账号，本机离线登录跟着换
    c, d = err(CL, 'POST', '/api/me/password', {'old': '123456', 'new': '123456'}, tok=L)
    ok('改密码：新密码和原密码一样 → 拒绝', c == 400 and '一样' in d, d)
    c, d = err(CL, 'POST', '/api/me/password', {'old': '123456', 'new': 'honey123'}, tok=L)
    ok('改密码：不能用初始密码', c == 400 and '初始密码' in d, d)
    c, d = err(CL, 'POST', '/api/me/password', {'old': 'wrong11', 'new': 'Newpass88'}, tok=L)
    ok('改密码：原密码不对（服务器核对）', c == 400 and '原密码' in d, d)
    pr = C('POST', '/api/me/password', {'old': '123456', 'new': 'Newpass88'}, tok=L)
    ok('客户端里改密码：转给服务器改，本机离线登录核对值跟着换', pr.get('ok') and pr.get('offline_login_updated'), pr)
    ok('服务器上：新密码能登录，旧密码不行', S('POST', '/api/login', {'username': stu, 'password': 'Newpass88'}).get('token')
       and err(SV, 'POST', '/api/login', {'username': stu, 'password': '123456'})[0] == 401)
    stop('server')
    c, d = err(CL, 'POST', '/api/me/password', {'old': 'Newpass88', 'new': 'Other99x'}, tok=L)
    ok('离线时不能改密码（要联网），说清楚', c == 503 and '联网' in d, (c, d))
    c, d = err(CL, 'POST', '/api/desktop/login', {'server': SV, 'username': stu, 'password': '123456'})
    ok('离线登录：旧密码不行了', c == 400 and '密码' in d, d)
    lo2 = login(stu, 'Newpass88')
    ok('离线登录：新密码可以', lo2.get('offline') and lo2.get('token'), lo2.get('mode'))
    L = lo2['token']
    start_server()
    C('POST', '/api/desktop/logout', {}, tok=L)
    ok('退出登录后没有学校令牌', not C('GET', '/api/client/status', tok=C('POST', '/api/desktop/standalone', {})['token'])['school']['connected'])
    stop('client')

    # ================================================================ 单机模式
    run = start_client(AHOME, CP)
    ok('单机：第一次也要选（登录页）', C('POST', '/api/desktop/session', {'token': run['token']}).get('need_login'))
    sal = C('POST', '/api/desktop/standalone', {})
    A = sal['token']
    ok('单机使用：本机管理员', sal['mode'] == 'standalone' and C('GET', '/api/me', tok=A)['role'] == 'admin')
    ok('单机：首页有完整示范工厂', [p['id'] for p in C('GET', '/api/plants', tok=A)['plants']] == ['foundry-housing'])
    ok('单机：之后打开直接进（不用再选）', C('POST', '/api/desktop/session', {'token': ticket(run)}).get('token'))
    ok('单机：本机账号的接口在本机（不转发）', C('GET', '/api/admin/users', tok=A)['users'][0]['username'] and C('GET', '/api/health')['mode'] == 'standalone')
    na = C('GET', '/api/desktop/native', headers={'X-VF-Key': run['key']})
    ok('单机：外壳接口 user=local，没有更新地址（只能手动检查）', na['mode'] == 'standalone' and na['user'] == 'local' and na['update_url'] == '', na.get('update_url'))
finally:
    for n in list(procs):
        stop(n)
    if os.environ.get('VF_TEST_KEEP') != '1':
        shutil.rmtree(WORK, ignore_errors=True)
    else:
        print('临时目录', WORK)

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过')
sys.exit(0 if n == len(res) else 1)
