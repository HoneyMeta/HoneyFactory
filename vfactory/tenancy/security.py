"""安全：登录限流与锁定、密码规则、会话时长、安全响应头、请求大小、Cookie。

登录锁定（单位账号和运维账号都用）：
  同一账号连续输错 VF_LOCKOUT_N 次（默认 5）→ 锁 VF_LOCKOUT_MIN 分钟（默认 15）；登录成功清零。
  同一 IP 10 分钟内失败 VF_IP_FAIL_N 次（默认 30）→ 这个 IP 暂停登录 10 分钟（只数失败，正常登录不受影响）。
密码规则：
  自部署默认和 4.x 一样（至少 6 位、不能用初始密码）；SaaS（或 VF_PW_POLICY=strict）：至少 8 位、字母和数字都要有、不能含账号名、不能是常见密码。
会话：VF_SESSION_HOURS（默认 168 小时 = 7 天，客户端"记住登录 7 天"靠它）；退出登录、改密码、归档、停用单位都会吊销。
Cookie：主界面用 Authorization 头（令牌在浏览器本地存储里，不用 Cookie，天然不受 CSRF 影响）；运维后台用 Cookie，
  HttpOnly + SameSite=Strict + Secure（HTTPS 时）+ 双提交 CSRF 令牌（见 ops.py）。
"""
from ..i18n import _tr
import re
import secrets
import string
import time
from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from . import flag, saas, setting

COMMON = {'12345678', '123456789', '1234567890', 'password', 'password1', 'qwerty123', 'abc12345', 'abcd1234', 'a1234567', 'admin123', 'honey123',
          'teach123', '11111111', '88888888', '00000000', 'iloveyou', 'qwertyuiop', '1q2w3e4r', 'passw0rd', 'p@ssw0rd', 'woaini1314', 'aa123456'}
INITIAL = ('honey123', '123456', 'teach123')


def _int(name, default):
    try:
        return int(setting(name, default))
    except (TypeError, ValueError):
        return default


def session_hours():
    return _int('session_hours', 24 * 7)


def strict_passwords():
    return saas() or str(setting('pw_policy', '')).lower() == 'strict'


def password_problem(pw, username='', strict=None):
    """密码不合规的原因（中文），合规返回空串。"""
    strict = strict_passwords() if strict is None else strict
    pw = pw or ''
    if not strict:
        if len(pw) < 6:
            return _tr('密码至少 6 位')
        return ''
    if len(pw) < 8:
        return _tr('密码至少 8 位')
    if len(pw) > 128:
        return _tr('密码太长（最多 128 位）')
    if not re.search(r'[A-Za-z]', pw) or not re.search(r'\d', pw):
        return _tr('密码要同时有字母和数字')
    if username and len(username) >= 3 and username.lower() in pw.lower():
        return _tr('密码不能包含账号名')
    if pw.lower() in COMMON or pw in INITIAL:
        return _tr('这个密码太常见了，换一个')
    return ''


def check_password(pw, username='', strict=None):
    why = password_problem(pw, username, strict)
    if why:
        raise HTTPException(400, why)


def random_password(n=10):
    """临时密码：字母 + 数字，去掉容易看错的字符；保证两类都有。"""
    letters = [c for c in string.ascii_letters if c not in 'lIO']
    digits = [c for c in string.digits if c not in '01']
    while True:
        s = ''.join(secrets.choice(letters + digits) for _ in range(n))
        if any(c in digits for c in s) and any(c in letters for c in s):
            return s


# ---------------------------------------------------------------- 登录限流与锁定
_ip_fail: dict = {}


def lockout_n():
    return _int('lockout_n', 5)


def lockout_min():
    return _int('lockout_min', 15)


def ip_blocked(ip):
    rec = _ip_fail.get(ip or '')
    if not rec:
        return False
    now = time.time()
    rec[:] = [t for t in rec if now - t < 600]
    return len(rec) >= _int('ip_fail_n', 30)


def ip_failed(ip):
    _ip_fail.setdefault(ip or '', []).append(time.time())
    if len(_ip_fail) > 5000:
        _ip_fail.clear()


def locked_msg(until):
    try:
        left = max(1, int((datetime.strptime(until, '%Y-%m-%d %H:%M:%S') - datetime.now()).total_seconds() // 60) + 1)
    except (TypeError, ValueError):
        left = lockout_min()
    return _tr('连续输错密码次数太多，账号已锁定，请 {left} 分钟后再试（或请管理员重置密码）', left=left)


def is_locked(row):
    lu = (row or {}).get('locked_until')
    return bool(lu and lu > datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


def login_user(username, password, ip=''):
    """单位账号登录：限流、锁定、单位状态检查。成功返回用户行，失败抛 HTTPException（401 账号或密码不对 / 423 锁定 / 429 限流 / 403 单位停用）。"""
    from .. import store
    from . import orgs
    if ip_blocked(ip):
        raise HTTPException(429, _tr('这台电脑登录失败次数太多，请 10 分钟后再试'))
    u = store.q('select * from users where username=?', ((username or '').strip(),), one=True)
    if u and is_locked(u):
        raise HTTPException(423, locked_msg(u['locked_until']))
    if not u or not u['active'] or not store.check_pw(password or '', u['pw']):
        ip_failed(ip)
        if u and u['active']:
            n = int(u.get('failed') or 0) + 1
            if n >= lockout_n():
                until = (datetime.now() + timedelta(minutes=lockout_min())).strftime('%Y-%m-%d %H:%M:%S')
                store.x('update users set failed=0, locked_until=? where id=?', (until, u['id']))
                store.audit(u['username'], 'LOCK', '/api/login', 423, _tr('连续输错 {n} 次，锁定 {lockout_min} 分钟', n=n, lockout_min=lockout_min()), ip)
                raise HTTPException(423, locked_msg(until))
            store.x('update users set failed=? where id=?', (n, u['id']))
        raise HTTPException(401, _tr('账号或密码不对'))
    if u.get('archived'):
        raise HTTPException(403, _tr('账号已归档（学期结束），请联系单位管理员'))
    why = orgs.login_block(u)
    if why:
        raise HTTPException(403, why)
    store.x('update users set failed=0, locked_until=null, last_login=? where id=?', (store.now(), u['id']))
    return u


# ---------------------------------------------------------------- 请求大小、安全响应头
def max_body():
    return _int('max_body_mb', 64) * 1024 * 1024


def https_on(request):
    """请求是不是 HTTPS（直连或反向代理传来的 X-Forwarded-Proto）。VF_HTTPS=1 时一律当作 HTTPS（反向代理没传头时用）。"""
    if flag('https'):
        return True
    if request.url.scheme == 'https':
        return True
    return (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip().lower() == 'https'


def install(app):
    @app.middleware('http')
    async def security_mw(request, call_next):
        cl = request.headers.get('content-length')
        if cl and cl.isdigit() and int(cl) > max_body():
            return JSONResponse({'detail': _tr('请求太大（超过 {v} MB）', v=max_body() // 1024 // 1024)}, 413)
        resp = await call_next(request)
        h = resp.headers
        h.setdefault('X-Content-Type-Options', 'nosniff')
        h.setdefault('Referrer-Policy', 'same-origin')
        if not request.url.path.startswith(('/docs', '/redoc')):
            h.setdefault('X-Frame-Options', 'SAMEORIGIN')
        if https_on(request):
            h.setdefault('Strict-Transport-Security', 'max-age=31536000')
        return resp


def set_cookie(resp, request, name, value, max_age, http_only=True, path='/'):
    resp.set_cookie(name, value, max_age=max_age, httponly=http_only, samesite='strict', secure=https_on(request), path=path)
