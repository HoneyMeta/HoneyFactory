"""First-run check on a PRODUCTION server (no VF_DEMO, fresh data directory): no demo accounts, the first administrator is created
through /api/setup/admin, then the set-up step is closed. Also checks the request language (X-Lang / ?lang= / default).

    VF_URL=http://127.0.0.1:8800 python tests/setup_check.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

B = os.environ.get('VF_URL', 'http://127.0.0.1:8800').rstrip('/')
results = []


def ok(name, cond, detail=''):
    results.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300])


def call(method, path, body=None, tok='', lang=None):
    h = {'Content-Type': 'application/json'}
    if lang:
        h['X-Lang'] = lang
    if tok:
        h['Authorization'] = 'Bearer ' + tok
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, json.loads(x.read() or b'null'), dict(x.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'null'), dict(e.headers)


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    c, h, _ = call('GET', '/api/health')
    ok('health: production, set-up needed', c == 200 and h.get('demo') is False and h.get('setup_needed') is True, h)
    ok('health: languages', h.get('langs') == ['en', 'zh-CN'] and h.get('lang') in ('en', 'zh-CN'), h.get('lang'))
    c, s, _ = call('GET', '/api/setup/admin')
    ok('GET /api/setup/admin needed', c == 200 and s.get('needed') is True and s.get('demo') is False, s)
    c, _, _ = call('POST', '/api/login', {'username': 'admin', 'password': 'honey123'})
    ok('no demo account admin/honey123', c == 401, c)
    c, d, _ = call('POST', '/api/setup/admin', {'username': 'boss', 'password': 'honey123'}, lang='en')
    ok('initial password refused (en message)', c == 400 and 'honey123' in str(d.get('detail', '')) and not any('一' <= ch <= '鿿' for ch in str(d.get('detail', ''))), d)
    c, d, _ = call('POST', '/api/setup/admin', {'username': 'boss', 'password': 'short'}, lang='zh-CN')
    ok('short password refused (zh message)', c == 400 and '8' in str(d.get('detail', '')), d)
    c, d, _ = call('POST', '/api/setup/admin', {'username': 'boss', 'password': 'Factory#2026', 'name': 'Boss'})
    tok = (d or {}).get('token', '')
    ok('first administrator created', c == 200 and tok and d['user']['role'] == 'admin', d.get('user') if isinstance(d, dict) else d)
    c, me, hd = call('GET', '/api/me', tok=tok, lang='zh-CN')
    ok('token works; Content-Language follows X-Lang', c == 200 and me.get('role') == 'admin' and hd.get('content-language', hd.get('Content-Language')) == 'zh-CN', hd.get('content-language'))
    c, d, _ = call('POST', '/api/setup/admin', {'username': 'boss2', 'password': 'Factory#2027'})
    ok('second set-up refused', c == 400, d)
    c, s, _ = call('GET', '/api/setup/admin')
    ok('set-up closed', s.get('needed') is False, s)
    c, d, _ = call('GET', '/api/p/no-such-plant/meta?lang=en', tok=tok)
    c2, d2, _ = call('GET', '/api/p/no-such-plant/meta', tok=tok, lang='zh-CN')
    ok('error texts per request language (?lang=en / X-Lang zh-CN)', c == 404 and 'no-such-plant' in d['detail'] and not any('一' <= ch <= '鿿' for ch in d['detail'])
       and any('一' <= ch <= '鿿' for ch in d2['detail']), (d, d2))
    n = sum(results)
    print(f'{n}/{len(results)} passed')
    return 0 if n == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
