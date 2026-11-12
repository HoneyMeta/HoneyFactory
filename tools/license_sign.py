"""自部署授权文件（.vflic）的密钥和签发工具——蜂元内部用，私钥绝不进仓库、不进安装包。

  生成密钥对（只做一次；私钥放在保险的地方，例如加密 U 盘 / 密码管理器）：
    python tools/license_sign.py keygen --out D:\\secure\\vf-license
      → D:\\secure\\vf-license\\vf-license-signing.key（私钥，32 字节十六进制）
        屏幕上打印公钥那一行：粘进 vfactory/tenancy/license_keys.py 的 TRUSTED，随下一版发布

  签发（私钥用 --key 或环境变量 VF_LICENSE_KEY 指定的文件）：
    python tools/license_sign.py sign --key D:\\secure\\vf-license\\vf-license-signing.key ^
        --org-name "郑州某职业技术学院" --org-code zzvtc --teachers 20 --students 600 ^
        --starts 2026-09-01 --expires 2027-08-31 --features plc,ai,client --courses all --ai-quota 2000000 ^
        --out zzvtc-2026.vflic

  检查一个授权文件（用仓库里的公钥，或 --pub 指定）：
    python tools/license_sign.py verify zzvtc-2026.vflic
"""
import argparse
import base64
import json
import os
import secrets
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from vfactory.tenancy import license as lic  # noqa: E402


def _need_crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
    except ImportError:
        sys.exit('需要 cryptography：pip install cryptography')


def _inside_repo(p):
    try:
        return os.path.commonpath([os.path.realpath(p), os.path.realpath(REPO)]) == os.path.realpath(REPO)
    except ValueError:
        return False


def keygen(a):
    _need_crypto()
    from cryptography.hazmat.primitives import serialization as S
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    out = os.path.abspath(a.out)
    if _inside_repo(out) and not a.allow_repo:
        sys.exit(f'私钥不能放在仓库里（{out}）：换一个仓库以外的目录')
    os.makedirs(out, exist_ok=True)
    kp = os.path.join(out, 'vf-license-signing.key')
    if os.path.exists(kp):
        sys.exit(f'{kp} 已经存在：不覆盖（换密钥请换目录，旧公钥在 license_keys.py 里保留一段时间）')
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(S.Encoding.Raw, S.PrivateFormat.Raw, S.NoEncryption())
    with open(kp, 'w', encoding='ascii') as f:
        f.write(raw.hex() + '\n')
    try:
        os.chmod(kp, 0o600)
    except OSError:
        pass
    pub = k.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    kid = lic.key_id(pub)
    print(f'私钥：{kp}（保管好；丢了只能换密钥，泄露了别人就能签授权）')
    print('把下面这一行粘进 vfactory/tenancy/license_keys.py 的 TRUSTED：')
    print(f"    '{kid}': '{base64.b64encode(pub).decode()}',")


def _load_key(path):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    path = path or os.environ.get('VF_LICENSE_KEY')
    if not path:
        sys.exit('请用 --key 或环境变量 VF_LICENSE_KEY 指定私钥文件')
    with open(path, encoding='ascii') as f:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(f.read().strip()))


def _date(v, name):
    try:
        return datetime.strptime(v, '%Y-%m-%d').strftime('%Y-%m-%d')
    except (TypeError, ValueError):
        sys.exit(f'{name} 的格式是 YYYY-MM-DD')


def build(key, a):
    from cryptography.hazmat.primitives import serialization as S
    feats = {'plc': False, 'ai': False, 'client': False}
    for x in (a.features or '').replace('，', ',').split(','):
        if x.strip():
            if x.strip() not in feats:
                sys.exit(f'不认识的功能包：{x}（可选 plc, ai, client）')
            feats[x.strip()] = True
    feats['courses'] = 'all' if a.courses in (None, '', 'all') else [c.strip() for c in a.courses.split(',') if c.strip()]
    payload = {'license_id': a.license_id or f"VF-{datetime.now():%Y%m%d}-{secrets.token_hex(3).upper()}", 'org_name': a.org_name,
               'org_code': a.org_code, 'seats': {'teachers': a.teachers, 'students': a.students},
               'starts': _date(a.starts, '--starts') if a.starts else datetime.now().strftime('%Y-%m-%d'), 'expires': _date(a.expires, '--expires'),
               'features': feats, 'ai_quota': a.ai_quota, 'issued': datetime.now().strftime('%Y-%m-%d'), 'note': a.note or ''}
    pub = key.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    return {'format': lic.FORMAT, 'version': 1, 'alg': 'ed25519', 'key_id': lic.key_id(pub), 'payload': payload,
            'sig': base64.b64encode(key.sign(lic.canonical(payload))).decode()}


def sign(a):
    key = _load_key(a.key)
    doc = build(key, a)
    data = json.dumps(doc, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(data)
        print(f"已签发 {doc['payload']['license_id']} → {a.out}")
    else:
        print(data)


def verify(a):
    with open(a.file, 'rb') as f:
        doc = lic.parse(f.read())
    keys = None
    if a.pub:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: F401
        raw = base64.b64decode(a.pub)
        keys = {lic.key_id(raw): a.pub}
    p, err = lic.verify(doc, keys)
    if not p:
        sys.exit(f'验证没通过：{err}')
    print(json.dumps(p, ensure_ascii=False, indent=1))
    print('签名正确' + ('（已过期）' if p.get('expires', '9999') < datetime.now().strftime('%Y-%m-%d') else ''))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='license_sign', description='蜂元虚拟工厂自部署授权文件：生成密钥、签发、验证')
    sub = ap.add_subparsers(dest='cmd', required=True)
    k = sub.add_parser('keygen')
    k.add_argument('--out', required=True, help='放私钥的目录（不能在仓库里）')
    k.add_argument('--allow-repo', action='store_true', help=argparse.SUPPRESS)
    s = sub.add_parser('sign')
    s.add_argument('--key', help='私钥文件（或环境变量 VF_LICENSE_KEY）')
    s.add_argument('--org-name', required=True)
    s.add_argument('--org-code', default='')
    s.add_argument('--teachers', type=int, required=True)
    s.add_argument('--students', type=int, required=True)
    s.add_argument('--starts', default='')
    s.add_argument('--expires', required=True)
    s.add_argument('--features', default='plc,ai,client', help='逗号分隔：plc, ai, client')
    s.add_argument('--courses', default='all', help='all 或课程编号（逗号分隔）')
    s.add_argument('--ai-quota', type=int, default=None, help='每月 AI tokens；不填 = 不限')
    s.add_argument('--license-id', default='')
    s.add_argument('--note', default='')
    s.add_argument('--out', default='')
    v = sub.add_parser('verify')
    v.add_argument('file')
    v.add_argument('--pub', default='', help='公钥（base64）；不填用 license_keys.py 里的')
    a = ap.parse_args(argv)
    {'keygen': keygen, 'sign': sign, 'verify': verify}[a.cmd](a)


if __name__ == '__main__':
    main()
