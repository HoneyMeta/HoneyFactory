"""登录与权限：本地账号，PBKDF2 存密码，HMAC 签名令牌。"""
from .i18n import _tr
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request

from . import db
from .schema import BY_NAME

_secret = None

# 各角色可写的模块（读全部开放给已登录用户）
WRITE = {
    'admin': '*', 'manager': '*',
    'planner': {'生产管理', '主数据'},
    'engineer': {'主数据', '机加', '铸造', '质量管理'},
    'leader': {'生产管理', '设备管理'},
    'operator': {'生产管理', '设备管理'},
    'qc': {'质量管理'},
    'maint': {'设备管理'},
    'warehouse': {'仓储物流'},
}


def secret():
    global _secret
    if _secret is None:
        p = os.path.join(db.DATA, 'secret.key')
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as f:
                f.write(secrets.token_hex(32))
        _secret = open(p).read().strip().encode()
    return _secret


def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex()
    return f'pbkdf2${salt}${h}'


def check_pw(pw: str, stored: str | None) -> bool:
    try:
        _, salt, h = (stored or '').split('$')
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex(), h)


def make_token(user: dict, hours=24 * 7) -> str:
    body = base64.urlsafe_b64encode(json.dumps({'u': user['username'], 'exp': int(time.time() + hours * 3600)}).encode()).decode()
    sig = hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f'{body}.{sig}'


def read_token(tok: str) -> str | None:
    try:
        body, sig = tok.split('.')
        if not hmac.compare_digest(hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()[:32], sig):
            return None
        d = json.loads(base64.urlsafe_b64decode(body))
        return d['u'] if d['exp'] > time.time() else None
    except Exception:
        return None


def current_user(request: Request) -> dict:
    tok = request.headers.get('authorization', '').removeprefix('Bearer ').strip() or request.query_params.get('token') or request.cookies.get('mes_token')
    name = read_token(tok) if tok else None
    if not name:
        raise HTTPException(401, _tr('请先登录'))
    with db.engine.connect() as c:
        u = db.get(c, 'sys_user', username=name)
    if not u or not u['active']:
        raise HTTPException(401, _tr('账号已停用'))
    u['role_list'] = [r.strip() for r in (u['roles'] or '').split(',') if r.strip()]
    u.pop('password_hash', None)
    return u


def can_write(user: dict, entity: str) -> bool:
    mod = BY_NAME[entity].module
    for r in user['role_list']:
        w = WRITE.get(r)
        if w == '*' or (w and mod in w):
            return True
    return False


def require_write(user, entity):
    if not can_write(user, entity):
        raise HTTPException(403, _tr('当前角色没有"{module}"的修改权限', module=BY_NAME[entity].module))


def user_by_name(username: str) -> dict | None:
    with db.engine.connect() as c:
        u = db.get(c, 'sys_user', username=username)
    if not u:
        return None
    u['role_list'] = [r.strip() for r in (u['roles'] or '').split(',') if r.strip()]
    u.pop('password_hash', None)
    return u
