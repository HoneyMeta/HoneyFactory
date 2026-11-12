"""本地存储（SQLite，标准库）：用户与角色、API 令牌、操作审计、场景库、实验记录。

5.0：表里的 org 字段就是"单位"（vfactory/tenancy）。自部署一套一个单位（default）；SaaS 一个库里多个单位，
每个请求按用户所属单位隔离（tenancy/policy.py + 各接口的单位检查）。会话带 sid，记在 sessions 表里，可以吊销。
"""
from .i18n import _tr
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from . import paths as _paths  # noqa: E402
DB = _paths.data('vf.db')                       # 可写数据走 paths（VF_HOME 可整体挪走）
ROLES = {'admin': '管理员', 'engineer': '工程师', 'viewer': '只读访客', 'teacher': '教师', 'student': '学生',
         'orgadmin': '单位管理员'}   # 教师/学生/单位管理员的访问范围见 vfactory/teach/guard；单位管理员管本单位的老师、学生、席位（5.0）
# 权限等级：教师/学生在自己能进的范围里（沙箱、教学接口）等同工程师——范围由认证中间件里的 teach guard 先挡住
ROLE_LEVEL = {'viewer': 0, 'student': 1, 'teacher': 1, 'engineer': 1, 'orgadmin': 1, 'admin': 2}


def role_ok(u, role):
    return ROLE_LEVEL.get((u or {}).get('role'), 0) >= ROLE_LEVEL[role]
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_secret = None

SCHEMA = """
create table if not exists users(id integer primary key, org text default 'default', username text unique, name text, role text, pw text,
  active integer default 1, created text, last_login text);
create table if not exists tokens(id integer primary key, org text default 'default', name text, prefix text, hash text, username text,
  created text, last_used text, revoked integer default 0);
create table if not exists audit(id integer primary key, org text default 'default', t text, username text, method text, path text,
  status integer, detail text, ip text);
create table if not exists scenarios(id integer primary key, org text default 'default', plant text, name text, descr text, steps text,
  builtin integer default 0, created text, updated text);
create table if not exists experiments(id integer primary key, org text default 'default', plant text, name text, hours real, reps integer,
  variants text, status text, progress real, result text, created text, finished text, username text);
create table if not exists settings(k text primary key, v text);
create table if not exists assistant_threads(id integer primary key, org text default 'default', username text, plant text, title text,
  messages text, created text, updated text);
"""


def conn():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        _conn = sqlite3.connect(DB, check_same_thread=False, timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        cols = {r[1] for r in _conn.execute('pragma table_info(tokens)').fetchall()}
        for c, typ in TOKEN_COLS:                 # 令牌范围、工厂、有效期、IP 白名单、调用次数（老库自动加列）
            if c not in cols:
                _conn.execute(f'alter table tokens add column {c} {typ}')
        from .tenancy import schema as _tschema     # 5.0：单位、会话、运维后台等新表；旧数据归"默认单位"（可重复执行）
        _tschema.ensure(_conn)
        if not _conn.execute('select 1 from users limit 1').fetchone() and _demo_users():
            for u, n, r in (('admin', _tr('管理员'), 'admin'), ('engineer', _tr('联调工程师'), 'engineer'), ('guest', _tr('访客'), 'viewer')):
                _conn.execute('insert into users(username,name,role,pw,created) values(?,?,?,?,?)', (u, n, r, hash_pw('honey123'), now()))
        _conn.commit()
    return _conn


def q(sql, args=(), one=False):
    with _lock:
        cur = conn().execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def secret():
    global _secret
    if _secret is None:
        r = q("select v from settings where k='secret'", one=True)
        if not r:
            x("insert into settings(k,v) values('secret',?)", (secrets.token_hex(32),))
            r = q("select v from settings where k='secret'", one=True)
        _secret = r['v'].encode()
    return _secret


def hash_pw(pw):
    salt = secrets.token_hex(8)
    return f"pbkdf2${salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex()}"


def check_pw(pw, stored):
    try:
        _, salt, h = (stored or '').split('$')
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex(), h)


def _demo_users():
    """Demo accounts admin / engineer / guest (password honey123, known to everyone) only in demo mode (VF_DEMO=1), never in SaaS.
    A production server starts without accounts: the first administrator is created on the login page (/api/setup/admin)
    or with `python -m vfactory create-admin`."""
    from . import i18n, tenancy
    return i18n.demo_mode() and not tenancy.saas()


def admin_needed():
    """No active administrator yet (fresh production install): the login page offers "create administrator"."""
    from . import tenancy
    if tenancy.saas():
        return False
    return not q("select 1 from users where role='admin' and active=1 limit 1", one=True)


def create_admin(username, password, name=''):
    """First administrator (only while there is none). Raises ValueError with a message."""
    import re
    from .tenancy import security
    username = (username or '').strip()
    if not admin_needed():
        raise ValueError(_tr('管理员账号已存在'))
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{2,40}', username):
        raise ValueError(_tr('账号只能用字母、数字和 _ . @ -，2～40 个字符'))
    if len(password or '') < 8:
        raise ValueError(_tr('密码至少 8 位'))
    if password in ('honey123', '123456', 'teach123'):
        raise ValueError(_tr('不能用初始密码（honey123、123456、teach123 这类大家都知道的密码）'))
    try:
        security.check_password(password, username)
    except Exception as e:                       # HTTPException from the password rules
        raise ValueError(getattr(e, 'detail', None) or str(e))
    with _lock:
        c = conn()
        if c.execute("select 1 from users where role='admin' and active=1 limit 1").fetchone():
            raise ValueError(_tr('管理员账号已存在'))
        if c.execute('select 1 from users where username=?', (username,)).fetchone():
            c.execute('update users set role=?, pw=?, active=1, name=? where username=?', ('admin', hash_pw(password), name or username, username))
        else:
            c.execute('insert into users(username,name,role,pw,created,pw_at) values(?,?,?,?,?,?)',
                      (username, name or username, 'admin', hash_pw(password), now(), now()))
        c.commit()
    return q('select * from users where username=?', (username,), one=True)


def make_session(username, hours=None, ip='', agent=''):
    """会话令牌 = 签名的 {u, exp, sid}；sid 记在 sessions 表里（退出登录、改密码、停用单位时吊销）。"""
    if hours is None:
        from .tenancy import security
        hours = security.session_hours()
    sid = secrets.token_urlsafe(12)
    exp = int(time.time() + hours * 3600)
    org = (q('select org from users where username=?', (username,), one=True) or {}).get('org') or 'default'
    x('insert into sessions(sid, username, org, created, expires, last_seen, ip, agent) values(?,?,?,?,?,?,?,?)',
      (sid, username, org, now(), datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S'), now(), ip or '', (agent or '')[:120]))
    body = base64.urlsafe_b64encode(json.dumps({'u': username, 'exp': exp, 'sid': sid}).encode()).decode()
    return body + '.' + hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()[:32]


_sid_ok: dict = {}          # sid → 上次查库确认有效的时间（同一进程里吊销时清掉，所以吊销立即生效）


def session_sid(tok):
    try:
        body, _sig = (tok or '').split('.')
        return json.loads(base64.urlsafe_b64decode(body)).get('sid')
    except Exception:
        return None


def revoke_sessions(username=None, sid=None, keep=None):
    """吊销会话：某个 sid，或某个账号的全部会话（keep = 保留的那个 sid，改密码时保留当前这个）。"""
    if sid:
        x('update sessions set revoked=1 where sid=?', (sid,))
        _sid_ok.pop(sid, None)
        return
    if username:
        x('update sessions set revoked=1 where username=? and sid!=?', (username, keep or ''))
        for k in [k for k in _sid_ok if k != keep]:
            _sid_ok.pop(k, None)


def _sid_valid(sid):
    t = _sid_ok.get(sid)
    if t and time.time() - t < 30:
        return True
    r = q('select revoked from sessions where sid=?', (sid,), one=True)
    if not r or r['revoked']:
        return False
    if len(_sid_ok) > 20000:
        _sid_ok.clear()
    _sid_ok[sid] = time.time()
    x('update sessions set last_seen=? where sid=?', (now(), sid))
    return True


def user_from_token(tok: str, ip: str = '', mark: bool = True):
    """会话令牌或 API 令牌（vf_ 开头）→ 用户；无效、过期、IP 不在白名单都返回 None（原因用 check_token 拿）。"""
    u, _err = check_token(tok, ip, mark)
    return u


def check_token(tok: str, ip: str = '', mark: bool = True):
    """→ (用户, 错误说明)。API 令牌的用户字典里带 token={id, name, scope, plants, expires}。"""
    if not tok:
        return None, _tr('请先登录')
    if tok.startswith('vf_'):
        h = hashlib.sha256(tok.encode()).hexdigest()
        t = q('select * from tokens where hash=? and revoked=0', (h,), one=True)
        if not t:
            return None, _tr('令牌无效或已吊销')
        if t.get('expires') and t['expires'] < now():
            return None, _tr('令牌已于 {expires} 过期', expires=t['expires'])
        if t.get('ips') and not ip_allowed(ip, t['ips']):
            return None, _tr('令牌不允许从 {v} 使用（IP 白名单：{ips}）', v=ip or _tr('未知地址'), ips=t["ips"])
        if mark:
            _mark_used(t['id'], ip)
        u = q('select * from users where username=? and active=1', (t['username'],), one=True)
        if not u or u.get('archived'):
            return None, _tr('令牌所属账号已停用')
        u['via_token'] = t['name']
        u['token'] = {'id': t['id'], 'name': t['name'], 'scope': t.get('scope') or None, 'plants': _plants(t.get('plants')), 'expires': t.get('expires')}
        return u, ''
    try:
        body, sig = tok.split('.')
        if not hmac.compare_digest(hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()[:32], sig):
            return None, _tr('登录已失效，请重新登录')
        d = json.loads(base64.urlsafe_b64decode(body))
        if d['exp'] < time.time():
            return None, _tr('登录已过期，请重新登录')
        if d.get('sid') and not _sid_valid(d['sid']):          # 5.0 会话可吊销（4.x 发的旧令牌没有 sid：到期前照常有效）
            return None, _tr('登录已退出或被注销，请重新登录')
        u = q('select * from users where username=? and active=1', (d['u'],), one=True)
        if u and u.get('archived'):
            return None, _tr('账号已归档（学期结束），请联系单位管理员')
        if u:
            u['sid'] = d.get('sid')
        return (u, '') if u else (None, _tr('账号已停用'))
    except Exception:
        return None, _tr('登录已失效，请重新登录')


# ---------------------------------------------------------------- API 令牌：范围、工厂、有效期、IP 白名单
TOKEN_COLS = (('scope', 'text'), ('plants', 'text'), ('expires', 'text'), ('ips', 'text'), ('uses', 'integer default 0'), ('last_ip', 'text'))
SCOPES = {'read': '只读', 'write': '读 + 写点位', 'control': '读写 + 仿真控制/故障/剧本', 'admin': '等同创建者'}
SCOPE_LEVEL = {'read': 0, 'write': 1, 'control': 2, 'admin': 3}
_used: dict = {}


def _plants(v):
    if not v:
        return None
    try:
        r = json.loads(v)
        return [str(i) for i in r] or None
    except ValueError:
        return [i.strip() for i in str(v).split(',') if i.strip()] or None


def ip_allowed(ip, rules):
    import ipaddress
    try:
        a = ipaddress.ip_address((ip or '').strip())
    except ValueError:
        return False
    for r in str(rules).replace('，', ',').replace(';', ',').replace(' ', ',').split(','):
        r = r.strip()
        if not r:
            continue
        try:
            if a in ipaddress.ip_network(r, strict=False):
                return True
        except ValueError:
            continue
    return False


def _mark_used(tid, ip):
    """真实"最近使用"：每次调用都记，但同一令牌 5 秒内只写一次库（次数在内存里累计）。"""
    now_s = time.time()
    rec = _used.setdefault(tid, {'t': 0, 'n': 0})
    rec['n'] += 1
    rec['last'], rec['ip'] = now(), ip or ''            # 列表里叠加还没落库的部分，显示的是真实值
    if now_s - rec['t'] >= 5:
        n, rec['n'], rec['t'] = rec['n'], 0, now_s
        x('update tokens set last_used=?, last_ip=?, uses=coalesce(uses,0)+? where id=?', (now(), ip or '', n, tid))


def token_plants(u):
    t = (u or {}).get('token')
    return (t or {}).get('plants') if t else None


def token_deny(u, method, path):
    """令牌范围检查（会话令牌和旧令牌不受限）。返回拒绝原因或空串。"""
    import re
    t = (u or {}).get('token')
    if not t:
        return ''
    pl = t.get('plants')
    if pl:
        m = re.match(r'^/(?:api/p|ws)/([^/]+)', path)
        if m and m.group(1) not in pl:
            return _tr('这个令牌只能访问工厂 {join}', join=_tr('、').join(pl))
    sc = t.get('scope')
    if not sc or sc == 'admin':
        return ''
    if path.startswith('/api/admin/') or path.startswith('/api/tokens') or path.startswith('/api/settings/') or path == '/api/me/password':
        return _tr('令牌范围「{v}」不能管理账号、令牌和全局设置', v=SCOPES[sc])
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return ''
    if sc == 'read':
        return _tr('只读令牌不能修改（令牌范围 read）')
    if sc == 'write':
        if re.match(r'^/api/p/[^/]+/station/[^/]+/write$', path) or re.match(r'^/api/p/[^/]+/tests/validate$', path):
            return ''
        return _tr('这个令牌只能读和写点位（令牌范围 write）；仿真控制、故障注入、剧本需要 control 范围')
    if sc == 'control' and (path == '/api/plants' or path.startswith('/api/plants/')):
        return _tr('令牌范围 control 不能新建或删除工厂')
    return ''


def new_api_token(name, username, scope=None, plants=None, expires=None, ips=None):
    tok = 'vf_' + secrets.token_urlsafe(24)
    x('insert into tokens(name,prefix,hash,username,created,scope,plants,expires,ips,uses) values(?,?,?,?,?,?,?,?,?,0)',
      (name, tok[:10], hashlib.sha256(tok.encode()).hexdigest(), username, now(), scope, json.dumps(plants, ensure_ascii=False) if plants else None,
       expires or None, ips or None))
    return tok


def audit(username, method, path, status, detail='', ip='', org=None):
    """操作审计（单位内的；平台运维的审计在 ops_audit，带哈希链）。org 不给时按账号查（账号名后面可能带"（令牌 …）"）。"""
    if org is None:
        base = str(username or '').split('（')[0].split(' (')[0]
        org = (q('select org from users where username=?', (base,), one=True) or {}).get('org') or 'default'
    x('insert into audit(t,username,method,path,status,detail,ip,org) values(?,?,?,?,?,?,?,?)', (now(), username, method, path, status, detail[:500], ip, org))


def org_of(username):
    return (q('select org from users where username=?', (username,), one=True) or {}).get('org') or 'default'
