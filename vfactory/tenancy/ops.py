"""平台运维后台（蜂元自己的人用）：网页 /ops，接口 /api/ops/…。和单位账号完全分开（ops_admins 表），没有"以单位身份登录"。

登录：账号 + 密码 → 第一次登录先绑定 TOTP（扫二维码，给 10 个一次性恢复码）→ 以后每次登录都要 TOTP（或一个恢复码）。
会话：Cookie vf_ops（HttpOnly、SameSite=Strict、HTTPS 时 Secure，只发给 /api/ops），空闲 VF_OPS_IDLE_MIN 分钟（默认 15）或
      满 VF_OPS_MAX_HOURS 小时（默认 8）失效；写操作要带 X-CSRF-Token（= Cookie vf_ops_csrf，双提交）。
敏感操作再验 TOTP（请求体 totp 或请求头 X-OPS-TOTP）：改席位/到期/功能包/AI 额度、停用/恢复单位、导出单位数据、建运维账号、停用运维账号、
      重置别人的 TOTP、改 IP 白名单。同一个口令只能用一次。
IP 白名单（可选）：环境变量 VF_OPS_IPS 或后台设置（如 10.0.0.0/8, 203.0.113.7），设了以后只有这些地址能访问 /api/ops。
审计：ops_audit 表只增不改（数据库触发器拦截 update/delete），每条带前一条的哈希（哈希链），/api/ops/audit/verify 能查出被改过/删过。
第一个运维账号用命令行建：python tools/ops_admin.py create --username <账号>（见 docs/部署-自部署与SaaS.md）。
"""
from ..i18n import _tr
import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .. import store
from . import orgs, saas, security, seats, setting, totp

COOKIE = 'vf_ops'
CSRF_COOKIE = 'vf_ops_csrf'
PENDING_TTL = 300
_pending: dict = {}


# ---------------------------------------------------------------- 设置、IP 白名单
def ops_setting(k, default=None):
    r = store.q('select v from ops_settings where k=?', (k,), one=True)
    return r['v'] if r and r['v'] not in (None, '') else default


def ip_rules():
    return str(setting('ops_ips', '') or ops_setting('ip_allow', '') or '').strip()


def client_ip(request):
    return request.client.host if request.client else ''


def ip_ok(request):
    rules = ip_rules()
    return not rules or store.ip_allowed(client_ip(request), rules)


def idle_s():
    return int(setting('ops_idle_min', 15)) * 60


def max_s():
    return int(setting('ops_max_hours', 8)) * 3600


# ---------------------------------------------------------------- 审计（哈希链）
def _chain(prev, row):
    s = '\x1f'.join(str(row.get(k) or '') for k in ('t', 'admin', 'action', 'target', 'detail', 'ip'))
    return hashlib.sha256((prev + '\x1e' + s).encode('utf-8')).hexdigest()


def audit(admin, action, target='', detail='', ip=''):
    with store._lock:                                  # 取上一条哈希和写入要在同一把锁里，链才不会分叉
        c = store.conn()
        last = c.execute('select hash from ops_audit order by id desc limit 1').fetchone()
        prev = last[0] if last else '0' * 64
        row = {'t': store.now(), 'admin': admin or '', 'action': action, 'target': str(target or '')[:200],
               'detail': (detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str))[:2000], 'ip': ip or ''}
        h = _chain(prev, row)
        c.execute('insert into ops_audit(t, admin, action, target, detail, ip, prev, hash) values(?,?,?,?,?,?,?,?)',
                  (row['t'], row['admin'], row['action'], row['target'], row['detail'], row['ip'], prev, h))
        c.commit()


def verify_chain():
    rows = store.q('select * from ops_audit order by id')
    prev, bad = '0' * 64, []
    last_id = 0
    for r in rows:
        if r['id'] != last_id + 1:
            bad.append({'id': r['id'], 'why': _tr('编号不连续：{last_id} 之后是 {id}（中间的记录被删了）', last_id=last_id, id=r['id'])})
        if r['prev'] != prev:
            bad.append({'id': r['id'], 'why': _tr('前一条的哈希对不上（前面有记录被改过或删过）')})
        if _chain(r['prev'], r) != r['hash']:
            bad.append({'id': r['id'], 'why': _tr('这一条的内容被改过')})
        prev, last_id = r['hash'], r['id']
    return {'ok': not bad, 'count': len(rows), 'problems': bad[:50], 'head': prev}


# ---------------------------------------------------------------- 运维账号
def create_admin(username, name='', password=None, must_change=True):
    username = (username or '').strip()
    import re
    if not re.fullmatch(r'[A-Za-z0-9_.\-]{2,40}', username):
        raise HTTPException(400, _tr('运维账号只能用字母、数字、下划线、点和短横线（2～40 位）'))
    if store.q('select 1 from ops_admins where username=?', (username,), one=True):
        raise HTTPException(400, _tr('运维账号 {username} 已经有了', username=username))
    pw = password or security.random_password(14)
    security.check_password(pw, username, strict=True)
    store.x('insert into ops_admins(username, name, pw, active, created, must_change) values(?,?,?,?,?,?)',
            (username, name or username, store.hash_pw(pw), 1, store.now(), 1 if must_change else 0))
    return pw


def admin_view(a):
    return {k: a.get(k) for k in ('id', 'username', 'name', 'active', 'created', 'last_login')} | {
        'totp_on': bool(a.get('totp_on')), 'recovery_left': len(json.loads(a.get('recovery') or '[]')), 'must_change': bool(a.get('must_change')),
        'locked': security.is_locked(a)}


def _pend(admin, kind, secret=None):
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v['at'] > PENDING_TTL]:
        _pending.pop(k, None)
    t = secrets.token_urlsafe(24)
    _pending[t] = {'admin': admin['username'], 'kind': kind, 'secret': secret, 'at': now, 'tries': 0}
    return t


def _take_pending(token, kind):
    p = _pending.get(str(token or ''))
    if not p or p['kind'] != kind or time.time() - p['at'] > PENDING_TTL:
        raise HTTPException(401, _tr('登录步骤已过期，请重新输入账号和密码'))
    p['tries'] += 1
    if p['tries'] > 5:
        _pending.pop(token, None)
        raise HTTPException(401, _tr('验证码输错太多次，请重新登录'))
    return p


def _fail_admin(a, request):
    security.ip_failed(client_ip(request))
    n = int(a.get('failed') or 0) + 1
    if n >= security.lockout_n():
        until = (datetime.now() + timedelta(minutes=max(30, security.lockout_min()))).strftime('%Y-%m-%d %H:%M:%S')
        store.x('update ops_admins set failed=0, locked_until=? where id=?', (until, a['id']))
        audit(a['username'], 'lockout', a['username'], _tr('连续失败 {n} 次', n=n), client_ip(request))
        raise HTTPException(423, security.locked_msg(until))
    store.x('update ops_admins set failed=? where id=?', (n, a['id']))


def _start_session(request, a, extra=None):
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = time.time()
    store.x('insert into ops_sessions(sid, admin, csrf, created, last_seen, expires, ip) values(?,?,?,?,?,?,?)',
            (sid, a['username'], csrf, now, now, now + max_s(), client_ip(request)))
    store.x('update ops_admins set failed=0, locked_until=null, last_login=? where id=?', (store.now(), a['id']))
    audit(a['username'], 'login', a['username'], '', client_ip(request))
    resp = JSONResponse({'ok': True, 'admin': admin_view(store.q('select * from ops_admins where id=?', (a['id'],), one=True)),
                         'csrf': csrf, 'idle_min': idle_s() // 60, **(extra or {})})
    security.set_cookie(resp, request, COOKIE, sid, max_s(), http_only=True, path='/api/ops')
    security.set_cookie(resp, request, CSRF_COOKIE, csrf, max_s(), http_only=False, path='/')
    return resp


def need_ops(request, allow_must_change=False):
    """→ 运维账号行。查 IP 白名单、会话（空闲/绝对时长）、写操作的 CSRF。"""
    if not ip_ok(request):
        raise HTTPException(403, _tr('这个地址（{client_ip}）不在运维后台的 IP 白名单里', client_ip=client_ip(request)))
    sid = request.cookies.get(COOKIE) or ''
    s = store.q('select * from ops_sessions where sid=?', (sid,), one=True) if sid else None
    now = time.time()
    if not s or s['revoked'] or now > s['expires'] or now - s['last_seen'] > idle_s():
        raise HTTPException(401, _tr('运维后台的登录已过期，请重新登录'))
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        hdr = request.headers.get('x-csrf-token') or ''
        if not hdr or not secrets.compare_digest(hdr, s['csrf']) or not secrets.compare_digest(request.cookies.get(CSRF_COOKIE) or '', s['csrf']):
            raise HTTPException(403, _tr('请求缺少或带错了 CSRF 令牌（请刷新页面）'))
        origin = request.headers.get('origin')
        if origin and origin.split('://', 1)[-1] != (request.headers.get('host') or ''):
            raise HTTPException(403, _tr('跨站请求被拒绝'))
    a = store.q('select * from ops_admins where username=? and active=1', (s['admin'],), one=True)
    if not a:
        raise HTTPException(401, _tr('运维账号已停用'))
    if a.get('must_change') and not allow_must_change:
        raise HTTPException(403, _tr('请先修改初始密码'))
    store.x('update ops_sessions set last_seen=? where sid=?', (now, sid))
    a['_sid'] = sid
    return a


def need_totp(request, a, body=None):
    """敏感操作：再验一次 TOTP（防会话被盗用）。"""
    code = (body or {}).get('totp') if isinstance(body, dict) else None
    code = code or request.headers.get('x-ops-totp') or ''
    c = totp.verify(a.get('totp_secret'), code, a.get('totp_last') or 0)
    if c is None:
        audit(a['username'], 'reauth_failed', '', request.url.path, client_ip(request))
        raise HTTPException(403, _tr('这个操作需要再输一次动态验证码（TOTP），验证码不对或已经用过'))
    store.x('update ops_admins set totp_last=? where id=?', (c, a['id']))


# ---------------------------------------------------------------- 接口
def register(app, mgr):
    if getattr(mgr, 'desktop', None) or not saas():
        return                                   # 运维后台只在 SaaS 里有（自部署是一个单位，单位管理员在 /org 管）

    def ip(request):
        return client_ip(request)

    @app.post('/api/ops/login')
    async def login(request: Request, body: dict = Body(...)):
        """第一步：账号 + 密码。→ {step: 'enroll', pending, secret, uri}（还没绑定 TOTP）或 {step: 'totp', pending}。"""
        if not ip_ok(request):
            raise HTTPException(403, _tr('这个地址（{ip}）不在运维后台的 IP 白名单里', ip=ip(request)))
        if security.ip_blocked(ip(request)):
            raise HTTPException(429, _tr('这台电脑登录失败次数太多，请 10 分钟后再试'))
        a = store.q('select * from ops_admins where username=?', ((body.get('username') or '').strip(),), one=True)
        if a and security.is_locked(a):
            raise HTTPException(423, security.locked_msg(a['locked_until']))
        if not a or not a['active'] or not store.check_pw(body.get('password') or '', a['pw']):
            if a and a['active']:
                _fail_admin(a, request)
            else:
                security.ip_failed(ip(request))
            audit(body.get('username') or '', 'login_failed', '', _tr('密码不对或账号不存在'), ip(request))
            raise HTTPException(401, _tr('账号或密码不对'))
        if not a['totp_on']:
            secret = totp.new_secret()
            return {'step': 'enroll', 'pending': _pend(a, 'enroll', secret), 'secret': secret, 'uri': totp.otpauth_uri(secret, a['username']),
                    'must_change': bool(a.get('must_change'))}
        return {'step': 'totp', 'pending': _pend(a, 'totp'), 'must_change': bool(a.get('must_change'))}

    @app.post('/api/ops/enroll')
    async def enroll(request: Request, body: dict = Body(...)):
        """第一次登录：输入验证器 App 上的 6 位码，绑定成功后给 10 个恢复码（只显示这一次）并登录。"""
        p = _take_pending(body.get('pending'), 'enroll')
        a = store.q('select * from ops_admins where username=? and active=1', (p['admin'],), one=True)
        if not a:
            raise HTTPException(401, _tr('账号已停用'))
        c = totp.verify(p['secret'], body.get('code'), 0)
        if c is None:
            raise HTTPException(400, _tr('验证码不对：确认手机时间准确，输入验证器 App 上现在显示的 6 位数'))
        codes = totp.new_recovery_codes(10)
        store.x('update ops_admins set totp_secret=?, totp_on=1, totp_last=?, recovery=? where id=?',
                (p['secret'], c, json.dumps([totp.hash_code(x) for x in codes]), a['id']))
        _pending.pop(body.get('pending'), None)
        audit(a['username'], 'totp_enrolled', a['username'], '', ip(request))
        return _start_session(request, a, {'recovery_codes': codes})

    @app.post('/api/ops/verify')
    async def verify(request: Request, body: dict = Body(...)):
        """第二步：TOTP 验证码（code）或一个恢复码（recovery，用过作废）。"""
        p = _take_pending(body.get('pending'), 'totp')
        a = store.q('select * from ops_admins where username=? and active=1', (p['admin'],), one=True)
        if not a:
            raise HTTPException(401, _tr('账号已停用'))
        extra = {}
        if body.get('recovery'):
            hs = json.loads(a.get('recovery') or '[]')
            i = totp.match_code(body['recovery'], hs)
            if i < 0:
                _fail_admin(a, request)
                raise HTTPException(400, _tr('恢复码不对或已经用过'))
            hs.pop(i)
            store.x('update ops_admins set recovery=? where id=?', (json.dumps(hs), a['id']))
            audit(a['username'], 'recovery_code_used', a['username'], _tr('还剩 {len} 个', len=len(hs)), ip(request))
            extra['recovery_left'] = len(hs)
        else:
            c = totp.verify(a['totp_secret'], body.get('code'), a.get('totp_last') or 0)
            if c is None:
                _fail_admin(a, request)
                raise HTTPException(400, _tr('验证码不对或已经用过（每个验证码只能用一次，等下一个）'))
            store.x('update ops_admins set totp_last=? where id=?', (c, a['id']))
        _pending.pop(body.get('pending'), None)
        return _start_session(request, a, extra)

    @app.post('/api/ops/logout')
    async def logout(request: Request):
        sid = request.cookies.get(COOKIE) or ''
        if sid:
            store.x('update ops_sessions set revoked=1 where sid=?', (sid,))
        resp = JSONResponse({'ok': True})
        resp.delete_cookie(COOKIE, path='/api/ops')
        resp.delete_cookie(CSRF_COOKIE, path='/')
        return resp

    @app.get('/api/ops/me')
    async def me(request: Request):
        a = need_ops(request, allow_must_change=True)
        s = store.q('select csrf, expires from ops_sessions where sid=?', (a['_sid'],), one=True)
        return {'admin': admin_view(a), 'csrf': s['csrf'], 'idle_min': idle_s() // 60, 'expires_in': int(s['expires'] - time.time()),
                'mode': 'saas' if saas() else 'selfhost', 'ip_allow': ip_rules(), 'ip': ip(request)}

    @app.post('/api/ops/password')
    async def password(request: Request, body: dict = Body(...)):
        a = need_ops(request, allow_must_change=True)
        if not store.check_pw(body.get('old') or '', a['pw']):
            raise HTTPException(400, _tr('原密码不对'))
        security.check_password(body.get('new') or '', a['username'], strict=True)
        if body.get('new') == body.get('old'):
            raise HTTPException(400, _tr('新密码不能和原密码一样'))
        store.x('update ops_admins set pw=?, must_change=0 where id=?', (store.hash_pw(body['new']), a['id']))
        store.x('update ops_sessions set revoked=1 where admin=? and sid!=?', (a['username'], a['_sid']))
        audit(a['username'], 'password_changed', a['username'], '', ip(request))
        return {'ok': True}

    # ---------------- 单位 ----------------
    def org_full(o):
        v = orgs.org_view(o)
        v['usage'] = orgs.usage(o['id'])
        lim = seats.summary(o['id'])
        v['left'] = lim['left']
        v['admins'] = [r['username'] for r in store.q("select username from users where org=? and role in ('orgadmin','admin') and archived=0", (o['id'],))]
        return v

    @app.get('/api/ops/orgs')
    async def org_list(request: Request):
        need_ops(request)
        return {'orgs': [org_full(orgs.get(o['id'])) for o in orgs.all_orgs()], 'features': orgs.FEATURES, 'kinds': orgs.KINDS, 'trial': orgs.TRIAL}

    @app.get('/api/ops/orgs/{oid}')
    async def org_get(oid: str, request: Request):
        need_ops(request)
        o = orgs.get(oid)
        if not o:
            raise HTTPException(404, _tr('没有这个单位'))
        return org_full(o)

    def _new_org_admin(oid, username, name):
        from ..teach import db as tdb
        username = (username or '').strip()
        if not username:
            raise HTTPException(400, _tr('请填写单位管理员的账号'))
        from ..teach.api import ACCOUNT_RE
        if not ACCOUNT_RE.match(username):
            raise HTTPException(400, _tr('账号只能用字母、数字、下划线、点和短横线'))
        if store.q('select 1 from users where username=?', (username,), one=True):
            raise HTTPException(400, _tr('账号 {username} 已经被用了（账号全平台唯一，建议带单位前缀，例如 {oid}.admin）', username=username, oid=oid))
        pw = security.random_password(12)
        store.x('insert into users(username, name, role, pw, created, org) values(?,?,?,?,?,?)',
                (username, name or username, 'orgadmin', store.hash_pw(pw), store.now(), oid))
        tdb.ready()
        r = store.q('select pw from users where username=?', (username,), one=True)
        tdb.x('insert or replace into pw_reset(username, hash, at, by) values(?,?,?,?)', (username, r['pw'], store.now(), 'ops'))
        return pw

    @app.post('/api/ops/orgs')
    async def org_create(request: Request, body: dict = Body(...)):
        """开户：单位资料、席位、到期、功能包、AI 额度 + 第一个单位管理员（初始密码只显示这一次，第一次登录要改）。"""
        a = need_ops(request)
        need_totp(request, a, body)
        o = orgs.create(body.get('id'), body.get('name'), body.get('kind') or 'school', **{k: body.get(k) for k in (
            'plan', 'contract_no', 'start_date', 'expires', 'seats_teachers', 'seats_students', 'features', 'ai_quota', 'contact', 'notes')})
        out = {'org': org_full(orgs.get(o['id']))}
        if body.get('admin_username'):
            out['admin'] = {'username': body['admin_username'], 'password': _new_org_admin(o['id'], body['admin_username'], body.get('admin_name'))}
        audit(a['username'], 'org_create', o['id'], {k: body.get(k) for k in ('name', 'plan', 'contract_no', 'expires', 'seats_teachers', 'seats_students',
                                                                             'features', 'ai_quota', 'admin_username')}, ip(request))
        return out

    @app.post('/api/ops/trials')
    async def trial_create(request: Request, body: dict = Body(...)):
        """试用账号：30 天、5 名老师、50 名学生（不需要再验 TOTP）。"""
        a = need_ops(request)
        t = orgs.TRIAL
        exp = (datetime.now() + timedelta(days=t['days'])).strftime('%Y-%m-%d')
        o = orgs.create(body.get('id'), body.get('name'), body.get('kind') or 'school', plan='trial', expires=exp, seats_teachers=t['teachers'],
                        seats_students=t['students'], ai_quota=t['ai_quota'], trial=True, contact=body.get('contact'), notes=body.get('notes'))
        out = {'org': org_full(orgs.get(o['id']))}
        if body.get('admin_username'):
            out['admin'] = {'username': body['admin_username'], 'password': _new_org_admin(o['id'], body['admin_username'], body.get('admin_name'))}
        audit(a['username'], 'trial_create', o['id'], {'name': body.get('name'), 'expires': exp, 'admin': body.get('admin_username')}, ip(request))
        return out

    @app.patch('/api/ops/orgs/{oid}')
    async def org_patch(oid: str, request: Request, body: dict = Body(...)):
        """改单位资料。席位、到期、功能包、AI 额度、状态是敏感项：要带 totp。"""
        a = need_ops(request)
        if any(k in body for k in orgs.SENSITIVE):
            need_totp(request, a, body)
        before = orgs.org_view(orgs.get(oid))
        if not before:
            raise HTTPException(404, _tr('没有这个单位'))
        o = orgs.update(oid, body)
        changed = {k: [before.get(k), orgs.org_view(o).get(k)] for k in orgs.EDITABLE + orgs.SENSITIVE if k in body}
        audit(a['username'], 'org_update', oid, changed, ip(request))
        return org_full(o)

    @app.post('/api/ops/orgs/{oid}/admins')
    async def org_add_admin(oid: str, request: Request, body: dict = Body(...)):
        """给单位再建一个单位管理员（原来的管理员离职等）：初始密码只显示这一次。不能代替单位登录。"""
        a = need_ops(request)
        need_totp(request, a, body)
        if not orgs.get(oid):
            raise HTTPException(404, _tr('没有这个单位'))
        pw = _new_org_admin(oid, body.get('username'), body.get('name'))
        audit(a['username'], 'org_admin_create', oid, body.get('username'), ip(request))
        return {'username': body.get('username'), 'password': pw}

    @app.post('/api/ops/orgs/{oid}/suspend')
    async def org_suspend(oid: str, request: Request, body: dict = Body(default={})):
        a = need_ops(request)
        need_totp(request, a, body)
        o = orgs.update(oid, {'status': 'suspended'})
        audit(a['username'], 'org_suspend', oid, body.get('reason') or '', ip(request))
        return org_full(o)

    @app.post('/api/ops/orgs/{oid}/resume')
    async def org_resume(oid: str, request: Request, body: dict = Body(default={})):
        a = need_ops(request)
        need_totp(request, a, body)
        o = orgs.update(oid, {'status': 'active'})
        audit(a['username'], 'org_resume', oid, body.get('reason') or '', ip(request))
        return org_full(o)

    @app.get('/api/ops/orgs/{oid}/export')
    async def org_export(oid: str, request: Request):
        """单位数据导出（备份）：要在请求头 X-OPS-TOTP 带验证码。"""
        a = need_ops(request)
        need_totp(request, a)
        data = orgs.export_zip(oid)
        audit(a['username'], 'org_export', oid, _tr('{len} 字节', len=len(data)), ip(request))
        return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename=org-{oid}-{datetime.now():%Y%m%d}.zip'})

    @app.get('/api/ops/usage')
    async def usage_all(request: Request):
        need_ops(request)
        return {'orgs': [{'id': o['id'], 'name': o['name'], 'status': o['status'], 'expires': o['expires'], 'trial': o['trial'], **orgs.usage(o['id'])}
                         for o in orgs.all_orgs()]}

    # ---------------- 运维账号 ----------------
    @app.get('/api/ops/admins')
    async def admins(request: Request):
        need_ops(request)
        return {'admins': [admin_view(r) for r in store.q('select * from ops_admins order by id')]}

    @app.post('/api/ops/admins')
    async def admin_new(request: Request, body: dict = Body(...)):
        a = need_ops(request)
        need_totp(request, a, body)
        pw = create_admin(body.get('username'), body.get('name'))
        audit(a['username'], 'admin_create', body.get('username'), '', ip(request))
        return {'username': body.get('username'), 'password': pw, 'msg': _tr('初始密码只显示这一次；对方第一次登录要绑定 TOTP 并修改密码')}

    @app.post('/api/ops/admins/{aid}/disable')
    async def admin_disable(aid: int, request: Request, body: dict = Body(default={})):
        a = need_ops(request)
        need_totp(request, a, body)
        t = store.q('select * from ops_admins where id=?', (aid,), one=True)
        if not t:
            raise HTTPException(404, _tr('没有这个运维账号'))
        if t['username'] == a['username']:
            raise HTTPException(400, _tr('不能停用自己'))
        store.x('update ops_admins set active=0 where id=?', (aid,))
        store.x('update ops_sessions set revoked=1 where admin=?', (t['username'],))
        audit(a['username'], 'admin_disable', t['username'], '', ip(request))
        return {'ok': True}

    @app.post('/api/ops/admins/{aid}/reset_totp')
    async def admin_reset_totp(aid: int, request: Request, body: dict = Body(default={})):
        """别人的手机丢了：清掉 TOTP，下次登录重新绑定（同时作废恢复码、退出全部会话）。"""
        a = need_ops(request)
        need_totp(request, a, body)
        t = store.q('select * from ops_admins where id=?', (aid,), one=True)
        if not t:
            raise HTTPException(404, _tr('没有这个运维账号'))
        store.x("update ops_admins set totp_on=0, totp_secret=null, totp_last=0, recovery='[]' where id=?", (aid,))
        store.x('update ops_sessions set revoked=1 where admin=?', (t['username'],))
        audit(a['username'], 'admin_reset_totp', t['username'], '', ip(request))
        return {'ok': True}

    # ---------------- 审计、设置 ----------------
    @app.get('/api/ops/audit')
    async def audit_list(request: Request, limit: int = 300, q: str = ''):
        need_ops(request)
        limit = max(1, min(2000, limit))
        if q:
            rows = store.q('select * from ops_audit where admin like ? or action like ? or target like ? or detail like ? order by id desc limit ?',
                           (f'%{q}%',) * 4 + (limit,))
        else:
            rows = store.q('select * from ops_audit order by id desc limit ?', (limit,))
        return {'rows': rows}

    @app.get('/api/ops/audit/verify')
    async def audit_verify(request: Request):
        need_ops(request)
        return verify_chain()

    @app.put('/api/ops/settings')
    async def settings_put(request: Request, body: dict = Body(...)):
        """IP 白名单（例：10.0.0.0/8, 203.0.113.7；空 = 不限）。要带 totp。改完马上生效——别把自己挡在外面。"""
        a = need_ops(request)
        need_totp(request, a, body)
        rules = str(body.get('ip_allow') or '').strip()
        if rules:
            import ipaddress
            for r in rules.replace('，', ',').replace(';', ',').replace(' ', ',').split(','):
                if r.strip():
                    try:
                        ipaddress.ip_network(r.strip(), strict=False)
                    except ValueError:
                        raise HTTPException(400, _tr('IP 白名单格式不对：{strip}', strip=r.strip()))
            if not store.ip_allowed(client_ip(request), rules):
                raise HTTPException(400, _tr('你现在的地址 {client_ip} 不在这个白名单里，保存了会把自己挡在外面', client_ip=client_ip(request)))
        store.x('insert or replace into ops_settings(k, v) values(?,?)', ('ip_allow', rules))
        audit(a['username'], 'settings', 'ip_allow', rules, ip(request))
        return {'ok': True, 'ip_allow': ip_rules()}
