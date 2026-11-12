"""课程包 .vfcourse（4.6）：老师做的课程发到客户端（离线做、本机预估分）时用的签名包。设计见 docs/course-authoring-4.6.md。

zip 内容：
  manifest.json   {format:'vfcourse', version:1, engine:<rules.RULES_VERSION>, course:{id, name, version}, created, server,
                   files:{文件名: sha256}, content_sha256}
                   content_sha256 = sha256(按文件名排序的 "文件名:哈希\\n" 串)，就是"这门课这一版"的内容指纹
  signature.json  {alg:'ed25519', key_id, sig}       sig = Ed25519(规范化的 manifest.json 字节)，用学校服务器的课程签名密钥
                  （装不了 cryptography 时退回 {alg:'hmac-sha256'}：客户端不能离线验，装包时在线让服务器验一次，再用本机密钥封一个本机印章）
  course.json     课程（引擎格式，courses/__init__.py）：去掉参考答案（reference），作答题的答案封存（rules.seal_lesson）
  assets/…        封面等图片（png/jpg/webp/svg）

客户端信任的公钥：第一次连学校服务器时从 /api/teach/courses/pubkey 取下来存在本机（school.json 的 course_keys，先到先信）；
之后每次读课程包都用它验签名——包里任何一个字节被改过（换答案、改分值、改评分规则），签名或哈希就对不上，这门课不加载。
服务器评分只用服务器自己冻结的那份课程（data/teach/courses/<编号>.json），客户端的包只用于离线练习和本机预估分。
"""
from __future__ import annotations

from ..i18n import _tr
import base64
import copy
import hashlib
import hmac
import io
import json
import os
import time
import zipfile

FORMAT = 'vfcourse'
VERSION = 1
EXT = '.vfcourse'
MAX_BYTES = 20 * 1024 * 1024
ASSET_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.svg')


class CoursePackageError(ValueError):
    pass


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def content_hash(files: dict) -> str:
    return _sha(''.join(f'{k}:{files[k]}\n' for k in sorted(files)).encode('utf-8'))


# ---------------- 签名密钥（服务器） ----------------
def have_ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
        return True
    except Exception:                                   # noqa: BLE001
        return False


def _setting(k, make=None):
    from .. import store
    r = store.q('select v from settings where k=?', (k,), one=True)
    if not r and make:
        store.x('insert or ignore into settings(k, v) values(?, ?)', (k, make()))
        r = store.q('select v from settings where k=?', (k,), one=True)
    return r['v'] if r else None


def _private_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization as S

    def make():
        k = Ed25519PrivateKey.generate()
        return k.private_bytes(S.Encoding.Raw, S.PrivateFormat.Raw, S.NoEncryption()).hex()
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_setting('course_sign_key', make)))


def key_id(pub_raw: bytes) -> str:
    return _sha(pub_raw)[:16]


def public_info():
    """学校服务器的课程签名公钥（客户端先到先信，存下来以后离线验包）。"""
    if not have_ed25519():
        return {'alg': 'hmac-sha256', 'key_id': 'server-hmac', 'public_key': None}
    from cryptography.hazmat.primitives import serialization as S
    pub = _private_key().public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    return {'alg': 'ed25519', 'key_id': key_id(pub), 'public_key': base64.b64encode(pub).decode('ascii')}


def sign(msg: bytes) -> dict:
    if have_ed25519():
        info = public_info()
        return {'alg': 'ed25519', 'key_id': info['key_id'], 'sig': base64.b64encode(_private_key().sign(msg)).decode('ascii')}
    from .. import store
    return {'alg': 'hmac-sha256', 'key_id': 'server-hmac', 'sig': hmac.new(store.secret(), msg, hashlib.sha256).hexdigest()}


def check_sig(msg: bytes, sig: dict, keys: dict) -> None:
    """keys：{key_id: 公钥 base64}。验不过抛 CoursePackageError。"""
    alg = (sig or {}).get('alg')
    if alg == 'ed25519':
        pub = (keys or {}).get(sig.get('key_id'))
        if not pub:
            raise CoursePackageError(_tr('课程包的签名密钥不是这所学校服务器的（没有对应的公钥）'))
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(base64.b64decode(sig.get('sig') or ''), msg)
        except ImportError:
            raise CoursePackageError(_tr('本机缺少验签名用的 cryptography 组件'))
        except Exception:                               # noqa: BLE001
            raise CoursePackageError(_tr('课程包签名不对：内容被改过，或者不是学校服务器发的'))
        return
    if alg == 'hmac-sha256':
        from .. import store
        if not hmac.compare_digest(hmac.new(store.secret(), msg, hashlib.sha256).hexdigest(), str(sig.get('sig') or '')):
            raise CoursePackageError(_tr('课程包签名不对：内容被改过，或者不是这台服务器发的'))
        return
    raise CoursePackageError(_tr('不认识的签名算法：{alg}', alg=alg))


# ---------------- 打包（服务器） ----------------
def public_course(course: dict) -> dict:
    """进课程包的课程：去掉参考答案和老师的私有字段，作答题答案封存。"""
    from .rules import seal_lesson
    c = copy.deepcopy(course)
    for k in ('owner_name', 'drafts', 'notes_private'):
        c.pop(k, None)
    for ch in c.get('chapters') or []:
        for l in ch.get('lessons') or []:
            l.pop('reference', None)
            l.pop('_course', None)
            seal_lesson(l, c['id'])
    return c


def build(course: dict, assets: dict | None = None, server: str = '') -> bytes:
    from .rules import RULES_VERSION
    files = {'course.json': json.dumps(public_course(course), ensure_ascii=False, indent=1).encode('utf-8')}
    for name, b in (assets or {}).items():
        n = os.path.basename(str(name))
        if not n.lower().endswith(ASSET_EXT):
            continue
        files['assets/' + n] = b
    hashes = {k: _sha(v) for k, v in files.items()}
    man = {'format': FORMAT, 'version': VERSION, 'engine': RULES_VERSION,
           'course': {'id': course['id'], 'name': course.get('name'), 'version': course.get('version')},
           'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'server': server or '', 'files': hashes, 'content_sha256': content_hash(hashes)}
    mb = canon(man)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', mb)
        z.writestr('signature.json', json.dumps(sign(mb)))
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


# ---------------- 读包、验包 ----------------
def read(data: bytes) -> dict:
    """结构 + 哈希检查（不验签名）。返回 {manifest, manifest_bytes, signature, course, assets}。"""
    if not data:
        raise CoursePackageError(_tr('课程包是空的'))
    if len(data) > MAX_BYTES:
        raise CoursePackageError(_tr('课程包太大'))
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise CoursePackageError(_tr('不是课程包（.vfcourse），或者文件已损坏'))
    with z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        if sum(i.file_size for i in z.infolist()) > MAX_BYTES * 3:
            raise CoursePackageError(_tr('课程包解压后太大'))
        if 'manifest.json' not in names or 'signature.json' not in names:
            raise CoursePackageError(_tr('课程包缺少 manifest.json 或 signature.json'))
        mb = z.read('manifest.json')
        try:
            man = json.loads(mb.decode('utf-8'))
            sig = json.loads(z.read('signature.json').decode('utf-8'))
        except ValueError:
            raise CoursePackageError(_tr('课程包的清单不是有效的 JSON'))
        if not isinstance(man, dict) or man.get('format') != FORMAT:
            raise CoursePackageError(_tr('不是课程包（format 不是 vfcourse）'))
        if int(man.get('version') or 0) > VERSION:
            raise CoursePackageError(_tr('课程包版本比这个程序新，请升级客户端'))
        files = man.get('files') or {}
        if content_hash(files) != man.get('content_sha256'):
            raise CoursePackageError(_tr('课程包的内容指纹不对'))
        got = {}
        for n in names:
            if n in ('manifest.json', 'signature.json'):
                continue
            if n not in files:
                raise CoursePackageError(_tr('课程包里有清单外的文件：{n}', n=n))
            b = z.read(n)
            if _sha(b) != files[n]:
                raise CoursePackageError(_tr('课程包里的 {n} 被改过（校验值不对）', n=n))
            got[n] = b
        for n in files:
            if n not in got:
                raise CoursePackageError(_tr('课程包缺文件：{n}', n=n))
    try:
        course = json.loads(got['course.json'].decode('utf-8'))
    except (KeyError, ValueError):
        raise CoursePackageError(_tr('课程包里没有有效的 course.json'))
    if not isinstance(course, dict) or course.get('id') != (man.get('course') or {}).get('id'):
        raise CoursePackageError(_tr('课程包里的课程编号和清单对不上'))
    return {'manifest': man, 'manifest_bytes': mb, 'signature': sig, 'course': course,
            'assets': {k[len('assets/'):]: v for k, v in got.items() if k.startswith('assets/')}}


def verify(data: bytes, keys: dict) -> dict:
    d = read(data)
    check_sig(d['manifest_bytes'], d['signature'], keys)
    return d


# ---------------- 客户端：装包、读已装的包 ----------------
def _local_seal(data: bytes) -> str:
    from .. import store
    return hmac.new(store.secret(), b'vfcourse-local|' + hashlib.sha256(data).digest(), hashlib.sha256).hexdigest()


def pinned_keys() -> dict:
    try:
        from ..teach.client import load_settings
        return dict(load_settings().get('course_keys') or {})
    except Exception:                                   # noqa: BLE001
        return {}


def verify_installed(data: bytes) -> dict:
    """客户端读已装的课程包：Ed25519 用记下的学校公钥验；HMAC 包（服务器没装 cryptography）验装包时封的本机印章。"""
    d = read(data)
    alg = (d['signature'] or {}).get('alg')
    if alg == 'hmac-sha256':
        cid = d['course']['id']
        from . import installed_dir
        p = os.path.join(installed_dir(), f'{cid}{EXT}.seal')
        try:
            with open(p, encoding='ascii') as f:
                seal = f.read().strip()
        except OSError:
            raise CoursePackageError(_tr('这门课的本机印章不见了：重新从学校服务器下载'))
        if not hmac.compare_digest(seal, _local_seal(data)):
            raise CoursePackageError(_tr('课程包被改过（和下载时的本机印章对不上）'))
        return d
    check_sig(d['manifest_bytes'], d['signature'], pinned_keys())
    return d


def install(data: bytes, keys: dict, online_ok=False) -> dict:
    """验过再装到 data/client/courses/<编号>.vfcourse。online_ok：HMAC 包已经在线让学校服务器验过。"""
    d = read(data)
    alg = (d['signature'] or {}).get('alg')
    if alg == 'hmac-sha256':
        if not online_ok:
            raise CoursePackageError(_tr('这个课程包只能在线验证（学校服务器没有 Ed25519 签名组件）'))
    else:
        check_sig(d['manifest_bytes'], d['signature'], keys)
    from . import installed_dir
    cid = d['course']['id']
    if not cid or '/' in cid or '\\' in cid or '..' in cid:
        raise CoursePackageError(_tr('课程编号不对'))
    os.makedirs(installed_dir(), exist_ok=True)
    p = os.path.join(installed_dir(), f'{cid}{EXT}')
    tmp = p + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, p)
    if alg == 'hmac-sha256':
        with open(p + '.seal', 'w', encoding='ascii') as f:
            f.write(_local_seal(data))
    return d
