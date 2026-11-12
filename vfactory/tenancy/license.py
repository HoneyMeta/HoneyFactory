"""自部署的授权文件（.vflic）：Ed25519 签名，离线激活（不连蜂元的服务器）。

文件格式（JSON）：
  {"format": "vf-license", "version": 1, "key_id": "…", "alg": "ed25519",
   "payload": {"license_id", "org_name", "org_code", "seats": {"teachers": 20, "students": 600},
               "starts": "2026-09-01", "expires": "2027-08-31", "features": {"courses": "all"|[课程编号], "plc": true, "ai": true, "client": true},
               "ai_quota": 2000000, "issued": "2026-08-20", "note": "…"},
   "sig": "base64(Ed25519(规范化的 payload))"}
规范化 = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')。
放在 <数据目录>/config/license.vflic（单位管理页面上传，或手工放进去）。改动任何一个字节都验不过 → 按"未授权"处理。
签发：tools/license_sign.py（私钥从 --key 或环境变量 VF_LICENSE_KEY 指定的文件读，绝不进仓库）。
"""
from ..i18n import _tr
import base64
import hashlib
import json
import os
from datetime import datetime

from .. import paths

FORMAT = 'vf-license'
_cache: dict = {}


def canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def key_id(pub_raw: bytes):
    return hashlib.sha256(pub_raw).hexdigest()[:16]


def trusted():
    from .license_keys import TRUSTED
    return dict(TRUSTED)


def path():
    return os.path.join(paths.CONFIG, 'license.vflic')


def verify(doc, keys=None, today=None):
    """→ (payload, '') 或 (None, 原因)。不看到期（到期由 status() 判断，到期的授权仍然能看到内容）。"""
    if not isinstance(doc, dict) or doc.get('format') != FORMAT:
        return None, _tr('不是蜂元虚拟工厂的授权文件')
    if doc.get('alg') != 'ed25519':
        return None, _tr('授权文件的签名算法不对')
    keys = trusted() if keys is None else keys
    pub = keys.get(str(doc.get('key_id') or ''))
    if not pub:
        return None, _tr('授权文件不是用蜂元认可的密钥签的（key_id 不认识）')
    payload = doc.get('payload')
    if not isinstance(payload, dict):
        return None, _tr('授权文件内容不全')
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return None, _tr('服务器缺少 cryptography 组件，验不了授权文件（pip install cryptography）')
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(base64.b64decode(str(doc.get('sig') or '')), canonical(payload))
    except (InvalidSignature, ValueError, TypeError):
        return None, _tr('授权文件签名不对（文件被改过或损坏）')
    return payload, ''


def parse(raw):
    try:
        return json.loads(raw.decode('utf-8-sig') if isinstance(raw, (bytes, bytearray)) else raw)
    except (ValueError, UnicodeDecodeError):
        return None


def status():
    """当前授权：{installed, ok, error, payload, expired, days_left, path}。按文件修改时间缓存。"""
    p = path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {'installed': False, 'ok': False, 'error': '', 'payload': None, 'expired': False, 'path': p}
    c = _cache.get(p)
    if c and c[0] == mt:
        return c[1]
    try:
        with open(p, 'rb') as f:
            doc = parse(f.read())
    except OSError as e:
        doc, err = None, str(e)
    payload, err = verify(doc) if doc is not None else (None, _tr('授权文件读不出来（不是 JSON）'))
    st = {'installed': True, 'ok': bool(payload), 'error': err, 'payload': payload, 'path': p, 'expired': False, 'days_left': None}
    if payload and payload.get('expires'):
        try:
            left = (datetime.strptime(payload['expires'][:10], '%Y-%m-%d').date() - datetime.now().date()).days
            st.update(days_left=left, expired=left < 0)
        except ValueError:
            st.update(ok=False, error=_tr('授权文件的到期日格式不对'))
    _cache[p] = (mt, st)
    return st


def install(raw):
    """单位管理员上传授权文件：验签通过才写入（不改动原来的授权）。→ status()。"""
    doc = parse(raw)
    payload, err = verify(doc) if doc is not None else (None, _tr('授权文件读不出来（不是 JSON）'))
    if not payload:
        raise ValueError(err)
    os.makedirs(paths.CONFIG, exist_ok=True)
    p = path()
    with open(p + '.tmp', 'wb') as f:
        f.write(raw if isinstance(raw, (bytes, bytearray)) else raw.encode('utf-8'))
    os.replace(p + '.tmp', p)
    _cache.pop(p, None)
    return status()


def remove():
    try:
        os.remove(path())
    except OSError:
        pass
    _cache.pop(path(), None)
