"""TOTP（RFC 6238，HMAC-SHA1、30 秒、6 位，和手机上的验证器 App 通用）+ 一次性恢复码。只用标准库。"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _key(secret):
    s = secret.strip().replace(' ', '').upper()
    return base64.b32decode(s + '=' * (-len(s) % 8))


def code_at(secret, counter):
    mac = hmac.new(_key(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack('>I', mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(n).zfill(DIGITS)


def now_code(secret, t=None):
    return code_at(secret, int((time.time() if t is None else t) // STEP))


def verify(secret, code, last_counter=0, window=1, t=None):
    """验证一次口令：±window 个时间片；同一个（或更早的）时间片用过就不认（防重放）。→ 用掉的时间片号，或 None。"""
    code = str(code or '').strip().replace(' ', '')
    if not secret or len(code) != DIGITS or not code.isdigit():
        return None
    cur = int((time.time() if t is None else t) // STEP)
    for c in range(cur - window, cur + window + 1):
        if c <= int(last_counter or 0):
            continue
        if hmac.compare_digest(code_at(secret, c), code):
            return c
    return None


def otpauth_uri(secret, account, issuer='HoneyVF Ops'):
    label = urllib.parse.quote(f'{issuer}:{account}')
    return f'otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}'


# ---------------------------------------------------------------- 恢复码：10 个，每个只能用一次；库里只存加盐散列
ALPHA = 'abcdefghjkmnpqrstuvwxyz23456789'


def new_recovery_codes(n=10):
    return ['-'.join(''.join(secrets.choice(ALPHA) for _ in range(5)) for _ in range(2)) for _ in range(n)]


def hash_code(code, salt=None):
    salt = salt or secrets.token_hex(8)
    norm = str(code or '').strip().lower().replace(' ', '')
    return f"{salt}${hashlib.sha256((salt + norm).encode()).hexdigest()}"


def match_code(code, hashes):
    """→ 命中的散列在列表里的位置，没命中 -1。"""
    for i, h in enumerate(hashes or []):
        try:
            salt, _ = h.split('$')
        except ValueError:
            continue
        if hmac.compare_digest(hash_code(code, salt), h):
            return i
    return -1
