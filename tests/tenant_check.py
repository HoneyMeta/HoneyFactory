"""5.0 单位隔离与安全检查（SaaS 模式的服务器）。

自动枚举全部 FastAPI 接口（在本进程里 build_app 一份，不启动），用两个单位（A、B）各角色（单位管理员、老师、学生）的账号证明：
B 的任何账号拿 A 的数据编号去调任何接口，都拿不到 A 的数据（响应里没有 A 的标记字符串）、改不了 A 的数据（前后快照一致）；
确实不能这么测的接口在 ALLOW 里写明原因。另外检查：席位上限、授权文件（有效/过期/被改/不认识的密钥）、TOTP 绑定和恢复码、
敏感操作再验、防重放、登录锁定、会话吊销、运维审计哈希链、AI 额度、单位停用、SaaS 不跑工厂。

用法（服务器：VF_MODE=saas、全新的 VF_HOME、VF_LLM_FAKE=1）：
  VF_URL=http://127.0.0.1:8820 VF_HOME=<服务器的数据目录> VF_TEST_LICENSE_KEY=<测试私钥文件> python tests/tenant_check.py
VF_HOME 必须和服务器同一个：本进程直接在库里建第一个运维账号（等于 tools/ops_admin.py create），并检查审计表的防篡改。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import argparse
import base64
import http.cookiejar
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
URL = os.environ.get('VF_URL', 'http://127.0.0.1:8820').rstrip('/')
if not os.environ.get('VF_HOME'):
    sys.exit('请设 VF_HOME = 服务器的数据目录')
os.environ['VF_MODE'] = 'saas'
sys.stdout.reconfigure(encoding='utf-8')

from vfactory.tenancy import totp as T  # noqa: E402

RES = []


def ok(name, cond, info=''):
    RES.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'  → {str(info)[:400]}'), flush=True)
    return bool(cond)


# ---------------------------------------------------------------- HTTP
def call(method, path, body=None, tok=None, raw=None, headers=None, opener=None, timeout=60):
    h = {'Accept': 'application/json', **(headers or {})}
    data = None
    if raw is not None:
        data, h['Content-Type'] = raw, 'application/octet-stream'
    elif body is not None:
        data, h['Content-Type'] = json.dumps(body).encode('utf-8'), 'application/json'
    if tok:
        h['Authorization'] = 'Bearer ' + tok
    req = urllib.request.Request(URL + path, data=data, method=method, headers=h)
    try:
        r = (opener.open if opener else urllib.request.urlopen)(req, timeout=timeout)
        code, b, rh = r.status, r.read(), dict(r.headers.items())
    except urllib.error.HTTPError as e:
        code, b, rh = e.code, e.read(), dict(e.headers.items()) if e.headers else {}
    try:
        j = json.loads(b.decode('utf-8')) if b else {}
    except (ValueError, UnicodeDecodeError):
        j = b
    return code, j, rh


def J(method, path, body=None, tok=None, want=200, **kw):
    c, j, _ = call(method, path, body, tok, **kw)
    if c != want:
        raise AssertionError(f'{method} {path} → {c} {str(j)[:300]}')
    return j


def detail(j):
    return j.get('detail') if isinstance(j, dict) else str(j)[:200]


def login(u, p):
    c, j, _ = call('POST', '/api/login', {'username': u, 'password': p})
    return j.get('token') if c == 200 else None


class Totp:
    """测试里算 TOTP：服务器不认同一个（或更早的）时间片，所以每次取一个比上次大的时间片（±1 窗口内），不够就等下一片。"""

    def __init__(self, secret, last=0):
        self.secret, self.last = secret, last

    def code(self):
        while True:
            cur = int(time.time() // 30)
            for c in (cur - 1, cur, cur + 1):
                if c > self.last:
                    self.last = c
                    return T.code_at(self.secret, c)
            time.sleep(1)


class Ops:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ''
        self.t = None

    def c(self, method, path, body=None, csrf=True, headers=None):
        h = dict(headers or {})
        if csrf and self.csrf:
            h['X-CSRF-Token'] = self.csrf
        return call(method, path, body, opener=self.op, headers=h)

    def j(self, method, path, body=None, want=200, **kw):
        code, j, _ = self.c(method, path, body, **kw)
        if code != want:
            raise AssertionError(f'ops {method} {path} → {code} {str(j)[:300]}')
        return j

    def sens(self, method, path, body=None, want=200):
        return self.j(method, path, {**(body or {}), 'totp': self.t.code()}, want)


# ---------------------------------------------------------------- 接口枚举（本进程里 build_app，不启动）
def enumerate_routes():
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from vfactory.server import Manager, build_app
    args = argparse.Namespace(http=0, opcua=0, mqtt=0, modbus=0, no_mqtt=True, port=0, home=None, server=None, protocols=False, watch_pid=0,
                              config='', hours=0, cmd='serve')
    app = build_app(Manager(args))
    out = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {'HEAD', 'OPTIONS'}):
                out.append((m, r.path))
        elif isinstance(r, APIWebSocketRoute):
            out.append(('WS', r.path))
    return out


# 不能拿 B 的账号直接打的接口（原因）——其余全部要测
ALLOW = {
    ('POST', '/api/me/logout'): '只吊销调用者自己的会话（会把测试账号登出），在"会话吊销"里单独测',
    ('POST', '/api/login'): '登录接口（不带令牌），锁定和限流单独测',
    ('GET', '/api/health'): '公开：版本和部署方式，不含单位数据',
}
OPEN = {('POST', '/api/login'), ('GET', '/api/health')}


def main():
    from vfactory import store
    from vfactory.tenancy import ops as tops
    t0 = time.time()
    print(f'服务器 {URL}，数据目录 {os.environ["VF_HOME"]}')
    c, h, _ = call('GET', '/api/health')
    ok('服务器是 SaaS 模式', c == 200 and h.get('deploy') == 'saas', h)
    ok('SaaS 服务器不跑工厂', h.get('plants') == [], h.get('plants'))

    # ================================================================ 1. 运维后台：第一个账号（命令行）、TOTP 绑定、恢复码
    opw = 'OpsTest#' + str(int(time.time()))[-6:] + 'a1'
    store.conn()
    if not store.q('select 1 from ops_admins where username=?', ('ops.test',), one=True):
        tops.create_admin('ops.test', '测试运维', opw, must_change=False)
    else:
        store.x("update ops_admins set pw=?, totp_on=0, totp_secret=null, totp_last=0, recovery='[]', failed=0, locked_until=null where username=?",
                (store.hash_pw(opw), 'ops.test'))
    tops.audit('cli', 'admin_create', 'ops.test', 'tenant_check', 'localhost')
    O = Ops()
    c, j, _ = O.c('GET', '/api/ops/orgs')
    ok('运维接口不登录 → 401', c == 401, c)
    c, j, _ = O.c('POST', '/api/ops/login', {'username': 'ops.test', 'password': 'wrong-pass-1'})
    ok('运维登录：密码错 → 401', c == 401, j)
    j = O.j('POST', '/api/ops/login', {'username': 'ops.test', 'password': opw})
    ok('第一次登录要绑定 TOTP（给密钥和 otpauth 地址）', j.get('step') == 'enroll' and j.get('secret') and j.get('uri', '').startswith('otpauth://totp/'), j)
    pend, secret = j['pending'], j['secret']
    c, jj, _ = O.c('POST', '/api/ops/enroll', {'pending': pend, 'code': '000000'})
    ok('绑定：验证码错 → 400', c == 400, jj)
    O.t = Totp(secret)
    j = O.j('POST', '/api/ops/enroll', {'pending': pend, 'code': O.t.code()})
    codes = j.get('recovery_codes') or []
    ok('绑定成功：给 10 个恢复码、CSRF 令牌，Cookie 是 HttpOnly', len(codes) == 10 and j.get('csrf') and any(ck.name == 'vf_ops' for ck in O.jar), j)
    O.csrf = j['csrf']
    ck = next((ck for ck in O.jar if ck.name == 'vf_ops'), None)
    ok('运维会话 Cookie：HttpOnly、SameSite=Strict、只发给 /api/ops', ck is not None and ck.has_nonstandard_attr('HttpOnly') and ck.path == '/api/ops'
       and (ck.get_nonstandard_attr('SameSite') or '').lower() == 'strict', ck and ck.__dict__)
    c, j, _ = O.c('POST', '/api/ops/trials', {'id': 'nocsrf', 'name': 'x'}, csrf=False)
    ok('写操作没带 CSRF 令牌 → 403', c == 403 and 'CSRF' in str(j), j)
    # 恢复码：能用一次，第二次不行
    O2 = Ops()
    j = O2.j('POST', '/api/ops/login', {'username': 'ops.test', 'password': opw})
    ok('第二次登录：要 TOTP', j.get('step') == 'totp', j)
    j2 = O2.j('POST', '/api/ops/verify', {'pending': j['pending'], 'recovery': codes[0]})
    ok('用恢复码登录成功，剩 9 个', j2.get('ok') and j2.get('recovery_left') == 9, j2)
    O3 = Ops()
    j = O3.j('POST', '/api/ops/login', {'username': 'ops.test', 'password': opw})
    c, j3, _ = O3.c('POST', '/api/ops/verify', {'pending': j['pending'], 'recovery': codes[0]})
    ok('同一个恢复码第二次 → 拒绝', c == 400, j3)
    c, j3, _ = O3.c('POST', '/api/ops/verify', {'pending': j['pending'], 'code': T.code_at(secret, O.t.last)})
    ok('TOTP 防重放：用过的验证码 → 拒绝', c == 400, j3)
    # 敏感操作再验
    c, j, _ = O.c('POST', '/api/ops/orgs', {'id': 'ta', 'name': 'x'})
    ok('敏感操作（开户）不带 TOTP → 403', c == 403 and 'TOTP' in str(j), j)
    c, j, _ = O.c('POST', '/api/ops/orgs', {'id': 'ta', 'name': 'x', 'totp': '123456'})
    ok('敏感操作 TOTP 错 → 403', c == 403, j)

    # ================================================================ 2. 开户：A、B 两个单位 + 试用单位 C
    stamp = datetime.now().strftime('%H%M%S')
    A = {'org': 'ta' + stamp[-4:], 'name': f'TA-甲单位-orgmark{stamp}'}
    B = {'org': 'tb' + stamp[-4:], 'name': f'TB-乙单位-{stamp}'}
    feats = {'courses': 'all', 'plc': True, 'ai': True, 'client': True}
    ja = O.sens('POST', '/api/ops/orgs', {'id': A['org'], 'name': A['name'], 'plan': '标准版', 'contract_no': 'HT-A-001', 'expires': '2030-12-31',
                                          'seats_teachers': 3, 'seats_students': 5, 'features': feats, 'ai_quota': 1000000,
                                          'admin_username': A['org'] + '.admin', 'admin_name': 'TA-管理员-admmark'})
    jb = O.sens('POST', '/api/ops/orgs', {'id': B['org'], 'name': B['name'], 'plan': '标准版', 'expires': '2030-12-31', 'seats_teachers': 10,
                                          'seats_students': 50, 'features': feats, 'ai_quota': 1000000, 'admin_username': B['org'] + '.admin'})
    ok('开户：单位 + 单位管理员（初始密码只显示一次）', ja['admin']['password'] and jb['admin']['password'] and ja['org']['seats_students'] == 5, ja)
    jc = O.j('POST', '/api/ops/trials', {'id': 'tc' + stamp[-4:], 'name': f'TC-试用-{stamp}', 'admin_username': 'tc' + stamp[-4:] + '.admin'})
    exp = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    ok('试用账号：30 天、5 名老师、50 名学生', jc['org']['trial'] and jc['org']['expires'] == exp and jc['org']['seats_teachers'] == 5
       and jc['org']['seats_students'] == 50, jc['org'])

    def org_admin_login(x, pw):
        tok = login(x['org'] + '.admin', pw)
        new = f'Adm{stamp}x9z'
        J('POST', '/api/me/password', {'old': pw, 'new': new}, tok)
        return login(x['org'] + '.admin', new)
    A['oa'] = org_admin_login(A, ja['admin']['password'])
    B['oa'] = org_admin_login(B, jb['admin']['password'])
    me = J('GET', '/api/me', tok=A['oa'])
    ok('单位管理员登录：角色 orgadmin，单位是 A', me['role'] == 'orgadmin' and me['org']['id'] == A['org'], me)
    c, j, _ = call('POST', '/api/me/password', {'old': f'Adm{stamp}x9z', 'new': '12345678'}, A['oa'])
    ok('SaaS 密码规则：纯数字常见密码 → 400', c == 400, j)

    # ================================================================ 3. 单位管理员：老师（席位）、学生导入（席位）、归档
    for x in (A, B):
        r = J('POST', '/api/org/teachers', {'username': f"{x['org']}.t1", 'name': 'TA-老师-tchmark' if x is A else 'TB-老师'}, x['oa'])
        x['t_pw'] = r['password']
    J('POST', '/api/org/teachers', {'username': f"{A['org']}.t2", 'name': 'TA-老师2'}, A['oa'])
    J('POST', '/api/org/teachers', {'username': f"{A['org']}.t3", 'name': 'TA-老师3'}, A['oa'])
    c, j, _ = call('POST', '/api/org/teachers', {'username': f"{A['org']}.t4", 'name': 'TA-老师4'}, A['oa'])
    ok('老师席位满了（上限 3）→ 403，说明还剩几个', c == 403 and '席位' in detail(j) and '还剩 0' in detail(j), j)
    c, j, _ = call('POST', '/api/admin/users', {'username': f"{A['org']}.t5", 'name': 'x', 'role': 'teacher', 'password': 'Abcdef123'}, A['oa'])
    ok('账号页建老师也查席位 → 403', c == 403 and '席位' in detail(j), j)
    for x in (A, B):
        x['t'] = login(f"{x['org']}.t1", x['t_pw'])
        x['class'] = J('POST', '/api/teach/classes', {'name': 'TA-班级-clsmark' if x is A else 'TB-班级'}, x['t'])['id']
    csv = 's1,TA-学生-stumark\ns2,TA-学生2\ns3,TA-学生3'
    pre = J('POST', '/api/org/students/import', {'csv': csv, 'class_id': A['class'], 'prefix': True, 'preview': True}, A['oa'])
    ok('导入预览：3 个新账号（加了单位前缀），席位够', pre['new'] == 3 and pre['seat_ok'] and pre['rows'][0]['username'] == f"{A['org']}.s1", pre)
    r = J('POST', '/api/org/students/import', {'csv': csv, 'class_id': A['class'], 'prefix': True}, A['oa'])
    ok('导入学生：建 3 个、加进班级、每人随机临时密码', r['created'] == 3 and r['added'] == 3 and all(len(a['password']) >= 8 for a in r['accounts']), r)
    A['stu_pw'] = {a['username']: a['password'] for a in r['accounts']}
    A['student'] = f"{A['org']}.s1"
    r = J('POST', '/api/org/students/import', {'csv': 's1,TB-学生\ns2,TB-学生2', 'class_id': B['class'], 'prefix': True}, B['oa'])
    B['stu_pw'] = {a['username']: a['password'] for a in r['accounts']}
    B['student'] = f"{B['org']}.s1"
    c, j, _ = call('POST', '/api/org/students/import', {'csv': 's4,x\ns5,y\ns6,z', 'prefix': True}, A['oa'])
    ok('学生席位不够（上限 5，已有 3，要 3）→ 403 整批不导', c == 403 and '还剩 2' in detail(j), j)
    ok('超了一个也没建', not any(u['username'] == f"{A['org']}.s4" for u in J('GET', '/api/org/users', tok=A['oa'])['users']))
    c, j, _ = call('POST', f"/api/teach/classes/{A['class']}/roster", {'csv': 'ta_extra1,a,Abcd12345\nta_extra2,b,Abcd12345\nta_extra3,c,Abcd12345'}, A['t'])
    ok('老师在班级里导名单也查席位 → 403', c == 403 and '席位' in detail(j), j)
    c, j, _ = call('POST', f"/api/teach/classes/{B['class']}/roster", {'csv': f"{A['student']},偷拉"}, B['t'])
    ok('别的单位的学生拉不进本班（账号全平台唯一）', c == 200 and not j.get('added') and any('别的单位' in e for e in j.get('errors') or []), j)
    r45 = J('POST', '/api/org/students/import', {'csv': 's4,TA-学生4\ns5,TA-学生5', 'class_id': A['class'], 'prefix': True}, A['oa'])
    s5pw = next(a['password'] for a in r45['accounts'] if a['username'].endswith('.s5'))
    c, j, _ = call('POST', '/api/org/students/import', {'csv': 's6,TA-学生6', 'prefix': True}, A['oa'])
    ok('学生满 5 个以后再导 1 个 → 403', c == 403, j)
    J('POST', '/api/org/users/archive', {'usernames': [f"{A['org']}.s5"]}, A['oa'])
    lim = J('GET', '/api/org', tok=A['oa'])['limits']
    ok('归档 1 个学生：腾出 1 个席位', lim['used']['students'] == 4 and lim['left']['students'] == 1 and lim['used']['archived'] == 1, lim)
    c, j, _ = call('POST', '/api/login', {'username': f"{A['org']}.s5", 'password': s5pw})
    ok('归档的账号（密码对）登录不了，说明已归档', c == 403 and '归档' in detail(j), j)
    r = J('POST', '/api/org/students/import', {'csv': 's6,TA-学生6', 'prefix': True}, A['oa'])
    ok('腾出席位后能再导 1 个', r['created'] == 1, r)
    c, j, _ = call('POST', '/api/org/users/restore', {'usernames': [f"{A['org']}.s5"]}, A['oa'])
    ok('席位满时恢复归档的账号 → 403', c == 403 and '席位' in detail(j), j)

    # ================================================================ 4. 发课、学生（客户端）交作业包、上报进度
    from vfactory import courses
    from vfactory.teach import package as pk
    for x in (A, B):
        J('POST', '/api/teach/courses/intro_factory/publish', {'class_id': x['class'], 'open_all': True}, x['t'])
        asg = J('GET', f"/api/teach/assignments?class_id={x['class']}", tok=x['t'])
        x['aid'] = next(a['id'] for a in asg if a.get('lesson') == 'i01')
        J('PATCH', f"/api/teach/assignments/{x['aid']}", {'title': 'TA-作业-asgmark' if x is A else 'TB-作业'}, x['t'])
        x['s'] = login(x['student'], x['stu_pw'][x['student']])
    c, j, _ = call('POST', f"/api/teach/assignments/{A['aid']}/sandbox", {}, A['s'])
    ok('SaaS：学生不能在服务器上开沙箱 → 403（去客户端）', c == 403 and '客户端' in detail(j), j)
    c, j, _ = call('GET', '/api/p/foundry-housing/state', tok=A['s'])
    ok('SaaS：工厂接口 → 403', c == 403, j)
    c, j, _ = call('POST', '/api/plants', {'name': 'x', 'template': 'blank'}, A['oa'])
    ok('SaaS：建工厂 → 403', c == 403, j)
    c, j, _ = call('GET', '/api/overview', tok=A['t'])
    ok('SaaS：工厂总览是空的', c == 200 and j.get('plants') == [], j)
    c, j, _ = call('POST', f"/api/teach/assignments/{A['aid']}/submit", {}, A['s'])
    ok('SaaS：沙箱提交（服务器评分）→ 403', c == 403, j)
    _c, les = courses.get_lesson('intro_factory', 'i01')
    for x, score in ((A, 72.5), (B, 61.0)):
        meta = {'student': {'username': x['student'], 'name': '学生'}, 'server': URL, 'assignment_id': x['aid'], 'title': 'i01', 'course': 'intro_factory',
                'lesson': 'i01', 'scene': None, 'kind': 'plant', 'local_score': {'score': score, 'max': 100, 'details': [{'key': 'k', 'label': '产量', 'score': score}],
                                                                                    'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}
        data = pk.build(meta, {}, courses.start_model(les, 'i01'), {}, {'sim_time': '1h'})
        r = J('POST', f"/api/teach/assignments/{x['aid']}/submit_package", tok=x['s'], raw=data)
        x['sub'] = r['id']
        ok(f"{x['org']}：交作业包，服务器按本机分记（不在服务器上仿真）", r['score'] == score and r['source'] == 'client', r)
        J('POST', '/api/progress/report', {'items': [{'assignment_id': x['aid'], 'progress': 0.4, 'step': 'TA-步骤-stepmark' if x is A else 'TB-步骤', 'state': 'working',
                                                      'score': score, 'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]}, x['s'])
    rep = J('GET', f"/api/teach/classes/{A['class']}/reported", tok=A['t'])
    me_row = next((s for s in rep['students'] if s['username'] == A['student']), {})
    ok('老师的班级进度：看到学生上报的进度和当前步骤', (me_row.get('items') or {}).get(str(A['aid'])) or (me_row.get('items') or {}).get(A['aid']), rep)
    r = J('POST', '/api/progress/report', {'items': [{'assignment_id': A['aid'], 'progress': 0.9, 'step': 'B 冒充'}]}, B['s'])
    ok('B 的学生给 A 的作业报进度 → 拒收', r['accepted'] == 0 and r['rejected'], r)
    # 补报：旧时间的记录不覆盖新状态
    old_at = (datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
    J('POST', '/api/progress/report', {'items': [{'assignment_id': A['aid'], 'progress': 0.1, 'step': '离线时的旧记录', 'at': old_at}]}, A['s'])
    one = J('GET', f"/api/teach/assignments/{A['aid']}/reported", tok=A['t'])
    st = next(s for s in one['students'] if s['username'] == A['student'])
    ok('离线补报的旧记录只进日志，不覆盖最新状态', st['latest']['progress'] == 1.0 or st['latest']['step'] != '离线时的旧记录', st)
    ok('上报日志里有补报的记录（带当时的时间）', any(l['at'] == old_at for l in st['log']), st['log'][:3])
    # ---------------- 4b. SaaS 里老师做课程：客户端签名的课程包传到服务器（服务器只验包，不跑工厂）
    import copy as _copy
    import io as _io
    import secrets as _secrets
    import zipfile as _zip
    from cryptography.hazmat.primitives import serialization as _S
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from vfactory.courses import coursepkg

    def mk_pkg(course, key, tamper=False):
        raw = coursepkg.build(course, {}, 'client')                  # 本进程的密钥签的：下面换成"老师客户端"的密钥重签
        zin = _zip.ZipFile(_io.BytesIO(raw))
        files = {n: zin.read(n) for n in zin.namelist()}
        if tamper:
            files['course.json'] = files['course.json'].replace('TA-课程'.encode(), 'TA-改过'.encode())
        sig = {'alg': 'ed25519', 'key_id': coursepkg.key_id(key.public_key().public_bytes(_S.Encoding.Raw, _S.PublicFormat.Raw)),
               'sig': base64.b64encode(key.sign(files['manifest.json'])).decode()}
        files['signature.json'] = json.dumps(sig).encode()
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, 'w') as z:
            for n, b in files.items():
                z.writestr(n, b)
        return base64.b64encode(buf.getvalue()).decode()
    tkey, okey = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    tpub = base64.b64encode(tkey.public_key().public_bytes(_S.Encoding.Raw, _S.PublicFormat.Raw)).decode()
    crs = _copy.deepcopy(courses.get_course('intro_factory'))
    for k in ('origin', 'package', 'order'):
        crs.pop(k, None)
    crs.update(id='tc-' + _secrets.token_hex(6), name='TA-课程-crsmark')
    A['course'] = crs['id']
    c, j, _ = call('POST', '/api/teach/authoring', {'name': 'x'}, A['t'])
    ok('SaaS：服务器上不能直接做课（403，说明去客户端）', c == 403 and '客户端' in detail(j), j)
    c, j, _ = call('POST', '/api/teach/authoring/upload', {'package': mk_pkg(crs, tkey), 'public_key': tpub, 'draft': crs}, A['t'])
    ok('老师客户端传课程包：服务器验签通过，存成 v1', c == 200 and j.get('version') == 1 and j.get('id') == crs['id'], j)
    c, j, _ = call('POST', '/api/teach/authoring/upload', {'package': mk_pkg(crs, tkey, tamper=True), 'public_key': tpub, 'draft': crs}, A['t'])
    ok('被改过的课程包（内容和清单哈希对不上）→ 400', c == 400 and '改过' in detail(j), j)
    c, j, _ = call('POST', '/api/teach/authoring/upload', {'package': mk_pkg(crs, okey), 'public_key': tpub, 'draft': crs}, A['t'])
    ok('签名不是随包公钥签的 → 400', c == 400 and '签名' in detail(j), j)
    c, j, _ = call('POST', '/api/teach/authoring/upload', {'package': mk_pkg(crs, tkey), 'public_key': tpub, 'draft': crs}, B['t'])
    ok('别的单位的老师用同一个课程编号上传 → 409', c == 409, j)
    bad = _copy.deepcopy(crs)
    bad['chapters'][0]['lessons'][0]['kind'] = 'nonsense'
    c, j, _ = call('POST', '/api/teach/authoring/upload', {'package': mk_pkg(bad, tkey), 'public_key': tpub, 'draft': bad}, A['t'])
    ok('课程静态校验不过（课的类型不认识）→ 400', c == 400 and '问题' in detail(j), j)
    c, j, _ = call('POST', '/api/teach/authoring/upload', {'package': mk_pkg(crs, tkey), 'public_key': tpub, 'draft': crs}, A['t'])
    ok('同一个老师再传一次：v2（版本号由服务器递增）', c == 200 and j.get('version') == 2, j)
    mine_a = J('GET', '/api/teach/authoring', tok=A['t'])
    ok('老师的"我做的课程"里有传上来的课', any(x['id'] == crs['id'] for x in mine_a), [x['id'] for x in mine_a])
    ok('取回草稿（换了电脑接着改）：本人可以', J('GET', f"/api/teach/authoring/{crs['id']}/draft", tok=A['t'])['course']['name'] == 'TA-课程-crsmark')
    ok('取回草稿：别的单位的老师 → 404', call('GET', f"/api/teach/authoring/{crs['id']}/draft", tok=B['t'])[0] == 404)
    ok('课程库：B 的老师看不到 A 传上来的课', not any(x['id'] == crs['id'] for x in J('GET', '/api/teach/courses', tok=B['t'])))
    J('POST', f"/api/teach/courses/{crs['id']}/publish", {'class_id': A['class'], 'open_all': True}, A['t'])
    pk_raw = call('GET', f"/api/teach/courses/{crs['id']}/package", tok=A['s'])[1]
    spub = J('GET', '/api/teach/courses/pubkey', tok=A['s'])
    try:
        d = coursepkg.verify(pk_raw, {spub['key_id']: spub['public_key']})
        good = d['course']['version'] == 2 and d['course']['name'] == 'TA-课程-crsmark'
    except Exception as e:                           # noqa: BLE001
        good = str(e)
    ok('学生下的课程包由服务器重新签名（学生客户端只认服务器的公钥），版本 2', good is True, good)
    ok('B 的学生下不了 A 的课程包', call('GET', f"/api/teach/courses/{crs['id']}/package", tok=B['s'])[0] in (403, 404))

    # 令牌（A 的老师）
    c, j, _ = call('GET', '/api/tokens', tok=A['oa'])
    A['token_id'] = 1
    # 会话号（A 学生的一个登录）
    sess = J('GET', '/api/me/sessions', tok=A['s'])
    A['sess8'] = sess[0]['id'] if sess else 'xxxxxxxx'

    # ================================================================ 5. 枚举全部接口：B 的各角色拿 A 的编号
    routes = enumerate_routes()
    api_routes = [r for r in routes if r[1].startswith(('/api/', '/ws/'))]
    ok(f'枚举到 {len(api_routes)} 个接口（含 WebSocket）', len(api_routes) > 250, len(api_routes))
    # 只用 A 存进去的内容做标记（名字、标题、步骤）；账号名会出现在 B 自己的审计里（B 拿 A 的账号名打接口），不算泄露
    marks = ['orgmark', 'clsmark', 'stumark', 'tchmark', 'asgmark', 'admmark', 'stepmark', 'crsmark']

    def snapshot():
        users = J('GET', '/api/org/users', tok=A['oa'])['users']
        cl = J('GET', f"/api/teach/classes/{A['class']}", tok=A['t'])
        asg = J('GET', f"/api/teach/assignments?class_id={A['class']}", tok=A['t'])
        subs = J('GET', f"/api/teach/assignments/{A['aid']}/submissions", tok=A['t'])
        prog = J('GET', f"/api/teach/assignments/{A['aid']}/reported", tok=A['t'])
        return json.dumps({'users': sorted((u['username'], u['name'], u['role'], u['active'], u['archived']) for u in users),
                           'class': [cl['name'], cl['teacher'], sorted(m['username'] for m in cl['members'])],
                           'asg': sorted((a['id'], a['title'], a['status'], a.get('due')) for a in asg),
                           'subs': sorted((s['id'], s['username'], s['score'], s.get('comment')) for s in subs),
                           'prog': [(s['username'], (s['latest'] or {}).get('step'), (s['latest'] or {}).get('progress')) for s in prog['students']]},
                          ensure_ascii=False, sort_keys=True)
    before = snapshot()
    ok('正例：A 自己的老师能看到 A 的标记（证明标记检测有效）', 'clsmark' in json.dumps(J('GET', f"/api/teach/classes/{A['class']}", tok=A['t']), ensure_ascii=False))

    def fill(path):
        def sub(m):
            name = m.group(1).split(':')[0]
            if name == 'cid':
                return A['course'] if path.startswith(('/api/teach/courses/', '/api/teach/authoring/')) else str(A['class'])
            if name == 'class_id':
                return str(A['class'])
            if name == 'aid':
                return str(A['aid'])
            if name in ('sid', 'sub'):
                if '/submissions/' in path:
                    return str(A['sub'])
                if '/sessions/' in path:
                    return A['sess8']
                return 'S1'
            if name == 'username':
                return A['student']
            if name == 'tid':
                return str(A['token_id'])
            if name == 'pid':
                return 'foundry-housing'
            if name == 'oid':
                return A['org']
            if name == 'name':
                return 'cover.png'
            if name == 'jid':
                return 'nojob'
            return '1'
        return re.sub(r'\{([^}]+)\}', sub, path)
    body = {'class_id': A['class'], 'assignment_id': A['aid'], 'aid': A['aid'], 'usernames': [A['student']], 'items': [{'assignment_id': A['aid'], 'progress': 0.99}],
            'score': 0, 'comment': 'B 改分', 'title': 'B 改标题', 'status': 'closed', 'active': False, 'question': 'x', 'messages': [{'role': 'user', 'content': 'x'}],
            'confirm': 'wrong', 'password': 'wrong-password-1', 'old': 'wrong-password-1', 'new': 'Whatever123', 'name': 'B-新建'}
    actors = [('B单位管理员', B['oa']), ('B老师', B['t']), ('B学生', B['s'])]
    tested = leaks = 0
    per_status, okay = {}, {}
    for (method, path) in api_routes:
        if (method, path) in ALLOW or path.startswith('/api/ops/'):
            continue
        p = fill(path)
        if method == 'WS':
            continue                                                  # WebSocket 只有 /ws/{pid}：SaaS 没有工厂，下面单独测
        for who, tok in actors:
            code, j, _ = call(method, p, None if method in ('GET', 'DELETE') else body, tok, timeout=60)
            tested += 1
            per_status[code] = per_status.get(code, 0) + 1
            if code < 400:
                okay.setdefault(f'{method} {path}', []).append(who[1:])
            txt = json.dumps(j, ensure_ascii=False, default=str) if not isinstance(j, (bytes, bytearray)) else j.decode('utf-8', 'replace')
            hit = [m for m in marks if m in txt]
            if code < 400 and hit:
                leaks += 1
                ok(f'不串单位：{who} {method} {path}', False, f'{code} 响应里有 A 的 {hit}：{txt[:200]}')
            if code == 401:
                ok(f'B 的令牌一直有效：{who} {method} {path}', False, f'401 {detail(j)}')
    ok(f'B 的 3 个角色 × 全部接口（{tested} 次请求）：响应里都没有 A 的数据', leaks == 0, leaks)
    print('  没有这样测的接口（原因）：')
    for (m, p), why in ALLOW.items():
        print(f'    {m} {p}：{why}')
    print(f"    /api/ops/…（{sum(1 for _m, p in api_routes if p.startswith('/api/ops/'))} 个）：运维后台另一套账号和 Cookie 会话，下面单独测（单位令牌一律 401）")
    print('    WS /ws/{pid}：WebSocket，下面单独测（SaaS 没有工厂，连上也收不到数据）')
    print('  状态码分布：', dict(sorted(per_status.items())))
    print('  B 的账号拿 A 的编号也回 2xx 的接口（都是 B 自己的数据或公共内容，已核对没有 A 的标记）：')
    for k, v in sorted(okay.items()):
        print(f"    {k}  [{'/'.join(v)}]")
    after = snapshot()
    ok('B 打完全部接口以后，A 的数据（账号、班级、名单、作业、提交、进度）一个字节没变', before == after, (before, after))
    # WebSocket：SaaS 没有工厂
    try:
        import websockets.sync.client as wsc
        try:
            w = wsc.connect(URL.replace('http', 'ws') + f"/ws/foundry-housing?token={B['t']}", open_timeout=5)
            try:
                w.recv(timeout=3)
                got = True
            except Exception:
                got = False
            w.close()
        except Exception:
            got = False
        ok('WebSocket /ws/{pid}：SaaS 没有工厂，收不到任何数据', not got)
    except ImportError:
        ok('WebSocket 检查（websockets 没装，跳过）', True)
    # 不带令牌：除了公开接口一律 401
    from vfactory.client_update import OPEN_PREFIXES as UPD
    bad = [f'{m} {p}' for (m, p) in api_routes if m != 'WS' and (m, p) not in OPEN and not p.startswith('/api/ops/') and not p.startswith(UPD)
           and call(m, fill(p), None if m in ('GET', 'DELETE') else {})[0] != 401]
    ok('不带令牌：除了登录和健康检查，全部接口 401', not bad, bad[:10])
    ops_routes = sorted({(m, p) for (m, p) in api_routes if p.startswith('/api/ops/')})
    bad = [f'{m} {p}' for (m, p) in ops_routes if p not in ('/api/ops/login', '/api/ops/enroll', '/api/ops/verify', '/api/ops/logout')
           and call(m, fill(p), None if m in ('GET', 'DELETE') else {}, B['oa'])[0] != 401]
    ok(f'运维接口（{len(ops_routes)} 个）：单位账号的令牌一律 401', not bad, bad)

    # ================================================================ 6. 登录锁定、会话吊销
    for i in range(5):
        c, j, _ = call('POST', '/api/login', {'username': B['student'], 'password': f'wrong{i}xx'})
    ok('连续输错 5 次 → 423 锁定（说清楚几分钟后再试）', c == 423 and '分钟' in detail(j), (c, j))
    c, j, _ = call('POST', '/api/login', {'username': B['student'], 'password': B['stu_pw'][B['student']]})
    ok('锁定期间密码对了也登录不了', c == 423, (c, j))
    r = J('POST', f"/api/org/users/{B['student']}/reset_password", tok=B['oa'])
    B['stu_pw'][B['student']] = r['password']
    ok('单位管理员重置密码 → 解锁，新密码能登录', login(B['student'], r['password']))
    ok('重置密码以后旧的登录作废', call('GET', '/api/me', tok=B['s'])[0] == 401)
    B['s'] = login(B['student'], r['password'])
    t2 = login(B['student'], r['password'])
    J('POST', '/api/me/logout', {}, t2)
    ok('退出登录：这个令牌立即失效，另一个登录不受影响', call('GET', '/api/me', tok=t2)[0] == 401 and call('GET', '/api/me', tok=B['s'])[0] == 200)

    # ================================================================ 7. AI 额度（假模型，计量照常）
    q = J('GET', '/api/ai/quota', tok=B['s'])
    ok('AI 额度：能查本单位本月用量', q['enabled'] and q['quota'] == 1000000, q)
    r = J('POST', '/api/ai/proxy/chat/completions', {'messages': [{'role': 'user', 'content': '你好'}]}, B['s'])
    ok('AI 代理：经服务器调大模型（客户端不碰密钥），返回 usage', r.get('choices') and (r.get('usage') or {}).get('total_tokens'), r)
    used = J('GET', '/api/ai/quota', tok=B['s'])['used']
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'ai_quota': used})
    c, j, _ = call('POST', '/api/ai/proxy/chat/completions', {'messages': [{'role': 'user', 'content': '再来'}]}, B['s'])
    ok('B 的额度用完 → 403，说明用完了、怎么办', c == 403 and '额度' in detail(j), j)
    ok('/api/ai/quota 显示 blocked', J('GET', '/api/ai/quota', tok=B['s'])['blocked'])
    c, j, _ = call('POST', '/api/ai/proxy/chat/completions', {'messages': [{'role': 'user', 'content': 'A 照常'}]}, A['s'])
    ok('A 的 AI 不受 B 影响', c == 200, j)
    c, j, _ = call('POST', f"/api/teach/submissions/{B['sub']}/ai_suggest", {}, B['t'])
    ok('AI 辅助评分也按单位额度停用', c == 502 and '额度' in detail(j), j)
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'features': {'ai': False}, 'ai_quota': 10 ** 9})
    c, j, _ = call('POST', '/api/ai/proxy/chat/completions', {'messages': [{'role': 'user', 'content': 'x'}]}, B['s'])
    ok('功能包里关掉 AI → 403', c == 403 and '开通' in detail(j), j)
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'features': {'ai': True}})
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'features': {'client': False}})
    c, j, _ = call('POST', '/api/login', {'username': B['student'], 'password': B['stu_pw'][B['student']], 'client': 'desktop'})
    ok('功能包里关掉客户端 → 客户端登录 403', c == 403 and '客户端' in detail(j), j)
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'features': {'client': True}})

    # ================================================================ 8. 停用单位、到期
    O.sens('POST', f"/api/ops/orgs/{B['org']}/suspend", {'reason': 'tenant_check'})
    c1 = call('GET', '/api/me', tok=B['t'])[0]
    c2, j2, _ = call('POST', '/api/login', {'username': B['student'], 'password': B['stu_pw'][B['student']]})
    ok('停用单位：已登录的令牌失效、不能再登录（说明原因）', c1 in (401, 403) and c2 == 403 and '停用' in detail(j2), (c1, j2))
    ok('停用 B 不影响 A', call('GET', '/api/me', tok=A['t'])[0] == 200)
    O.sens('POST', f"/api/ops/orgs/{B['org']}/resume", {})
    B['t'] = login(f"{B['org']}.t1", B['t_pw'])
    B['oa'] = login(f"{B['org']}.admin", f'Adm{stamp}x9z')        # 停用时吊销了全部会话
    ok('恢复单位：能登录', bool(B['t']) and bool(B['oa']))
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'expires': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')})
    c, j, _ = call('POST', '/api/login', {'username': f"{B['org']}.t1", 'password': B['t_pw']})
    ok('到期：老师登录不了（说明到期日）', c == 403 and '到期' in detail(j), j)
    c, j, _ = call('GET', '/api/org', tok=B['oa'])
    ok('到期：单位管理员还能进（导出数据、续期）', c == 200 and j['org']['expired'], j)
    c, j, _ = call('POST', '/api/org/teachers', {'username': f"{B['org']}.t9", 'name': 'x'}, B['oa'])
    ok('到期：不能新建账号', c == 403 and '到期' in detail(j), j)
    O.sens('PATCH', f"/api/ops/orgs/{B['org']}", {'expires': '2030-12-31'})

    # ================================================================ 9. 导出 / 运维审计哈希链
    c, j, _ = call('POST', '/api/org/export', {'password': 'wrong'}, A['oa'])
    ok('单位导出要再输一次密码', c == 403, j)
    c, raw, h = call('POST', '/api/org/export', {'password': f'Adm{stamp}x9z'}, A['oa'])
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(raw)) if c == 200 else None
    names = z.namelist() if z else []
    users_json = json.loads(z.read('users.json')) if z else []
    ok('单位导出：zip（账号、班级、作业、提交、作业包、进度、审计），不含密码、不含别的单位',
       c == 200 and 'users.json' in names and 'submissions.json' in names and any(n.startswith('packages/') for n in names)
       and all('pw' not in u for u in users_json) and all(u['username'].startswith(A['org'] + '.') for u in users_json), (c, names))
    c, raw, _ = O.c('GET', f"/api/ops/orgs/{A['org']}/export")
    ok('运维导出单位数据：不带 TOTP → 403', c == 403)
    c, raw, _ = O.c('GET', f"/api/ops/orgs/{A['org']}/export", headers={'X-OPS-TOTP': O.t.code()})
    ok('运维导出单位数据（再验 TOTP）', c == 200 and isinstance(raw, (bytes, bytearray)) and raw[:2] == b'PK', c)
    v = O.j('GET', '/api/ops/audit/verify')
    ok(f"运维审计哈希链完整（{v['count']} 条）", v['ok'] and v['count'] >= 10, v)
    rows = O.j('GET', '/api/ops/audit?limit=500')['rows']
    acts = {r['action'] for r in rows}
    ok('审计记下了开户、试用、改额度、停用、恢复、导出、登录、再验失败', {'org_create', 'trial_create', 'org_update', 'org_suspend', 'org_resume', 'org_export',
                                                          'login', 'reauth_failed'} <= acts, acts)
    db = sqlite3.connect(os.path.join(os.environ['VF_HOME'], 'data', 'vf.db'))
    try:
        db.execute("update ops_audit set detail='改过' where id=2")
        db.commit()
        blocked = False
    except sqlite3.DatabaseError:
        blocked = True
    ok('审计表只增不改：update 被数据库触发器拦下', blocked)
    try:
        db.execute('delete from ops_audit where id=3')
        db.commit()
        blocked = False
    except sqlite3.DatabaseError:
        blocked = True
    ok('审计表只增不改：delete 被拦下', blocked)
    # 绕过触发器直接改库（模拟拿到数据库文件的人）：哈希链能查出来
    orig = db.execute('select detail from ops_audit where id=2').fetchone()[0]
    db.execute('drop trigger ops_audit_no_update')
    db.execute("update ops_audit set detail='被人改过' where id=2")
    db.commit()
    v2 = O.j('GET', '/api/ops/audit/verify')
    ok('绕过触发器改了一条：哈希链查出是第 2 条', not v2['ok'] and any(p['id'] == 2 for p in v2['problems']), v2)
    db.execute('update ops_audit set detail=? where id=2', (orig,))
    db.execute("create trigger if not exists ops_audit_no_update before update on ops_audit begin select raise(abort, 'ops_audit is append-only'); end;")
    db.commit()
    db.close()
    ok('改回去以后哈希链又完整了', O.j('GET', '/api/ops/audit/verify')['ok'])

    # ================================================================ 10. 运维账号：建账号要再验、不能"以单位身份登录"、IP 白名单、登出
    c, j, _ = O.c('POST', '/api/ops/admins', {'username': 'ops.two'})
    ok('建运维账号不带 TOTP → 403', c == 403)
    j = O.sens('POST', '/api/ops/admins', {'username': 'ops.two' + stamp, 'name': '二号'})
    ok('建运维账号（再验 TOTP）：初始密码只显示一次', len(j.get('password') or '') >= 12, j)
    paths = {p for (_m, p) in api_routes if p.startswith('/api/ops/')}
    ok('运维后台没有"以单位身份登录"的接口', not any(re.search(r'impersonat|login_as|as_org|sudo', p) for p in paths), paths)
    c, j, _ = O.c('PUT', '/api/ops/settings', {'ip_allow': '10.255.255.0/24', 'totp': O.t.code()})
    ok('IP 白名单：不包含自己的地址时拒绝保存（防止把自己挡在外面）', c == 400 and '挡在外面' in detail(j), j)
    j = O.sens('PUT', '/api/ops/settings', {'ip_allow': '127.0.0.1/32, ::1'})
    ok('IP 白名单：保存本机地址', j['ip_allow'].startswith('127.0.0.1'), j)
    O.sens('PUT', '/api/ops/settings', {'ip_allow': ''})
    O.j('POST', '/api/ops/logout', {})
    ok('运维登出：会话失效', O.c('GET', '/api/ops/me')[0] == 401)
    # 运维账号锁定
    for i in range(5):
        c, j, _ = call('POST', '/api/ops/login', {'username': 'ops.two' + stamp, 'password': f'bad{i}pass'})
    ok('运维账号连续输错 5 次 → 锁定', c == 423, (c, j))

    # ================================================================ 11. 授权文件（自部署）：有效 / 过期 / 被改 / 不认识的密钥
    key = os.environ.get('VF_TEST_LICENSE_KEY')
    if key and os.path.exists(key):
        os.environ['VF_MODE'] = 'selfhost'
        from vfactory.tenancy import license as lic
        from vfactory.tenancy import seats
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
        import license_sign as ls
        k = ls._load_key(key)

        def mk(**kw):
            a = argparse.Namespace(org_name='测试学院', org_code='tst', teachers=2, students=3, starts='', expires='2030-12-31', features='plc,ai,client',
                                   courses='all', ai_quota=5000, license_id='', note='', **{})
            for kk, vv in kw.items():
                setattr(a, kk, vv)
            return ls.build(k, a)
        good = mk()
        p, err = lic.verify(good)
        ok('授权文件：签名正确 → 有效', p and p['seats']['students'] == 3, err)
        bad = json.loads(json.dumps(good))
        bad['payload']['seats']['students'] = 9999
        p, err = lic.verify(bad)
        ok('授权文件：改了席位（被篡改）→ 无效', p is None and '签名不对' in err, err)
        bad2 = json.loads(json.dumps(good))
        bad2['key_id'] = '0' * 16
        ok('授权文件：不认识的密钥 → 无效', lic.verify(bad2)[0] is None)
        st = lic.install(json.dumps(good).encode('utf-8'))
        lim = seats.limits()
        ok('导入有效授权：席位来自授权文件', st['ok'] and lim['source'] == 'licence' and lim['students'] == 3 and lim['teachers'] == 2, lim)
        exp_doc = mk(expires=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'))
        time.sleep(1.1)
        st = lic.install(json.dumps(exp_doc).encode('utf-8'))
        lim = seats.limits()
        ok('过期的授权：能导入（看得到内容）但标成过期，不能再新建账号', st['ok'] and st['expired'] and lim['expired'], (st, lim))
        try:
            seats.check_add('default', 'student', 1)
            blocked = False
        except Exception as e:                       # noqa: BLE001
            blocked = '到期' in str(getattr(e, 'detail', e))
        ok('过期授权：建学生 → 拒绝并说明到期', blocked)
        try:
            lic.install(json.dumps(bad).encode('utf-8'))
            refused = False
        except ValueError as e:
            refused = '签名' in str(e)
        ok('被改过的授权文件不能导入', refused)
        lic.remove()
        ok('删掉授权：回到未授权（默认不限席位）', seats.limits()['source'] == 'unlicensed')
        os.environ['VF_MODE'] = 'saas'
    else:
        ok('授权文件检查：没有测试私钥（VF_TEST_LICENSE_KEY），跳过', True)

    n = sum(1 for _, x in RES if x)
    print(f'\ntenant_check：{n}/{len(RES)} 通过（{time.time() - t0:.0f} 秒）')
    return 0 if n == len(RES) else 1


if __name__ == '__main__':
    sys.exit(main())
