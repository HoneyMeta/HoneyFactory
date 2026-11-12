"""Frontend i18n check (no server needed): python tests/i18n_web_check.py

1. No CJK characters in web/src code (.vue .ts .js .css .html .json .md) outside web/src/locales/zh-CN.json, nor in
   web/*.html and web/public/brand/manifest.json. Data that must match Chinese text coming from the backend (plant models,
   course content, validation categories ...) is written with backslash-u escapes. ALLOW lists exact (file, substring) exceptions.
2. en.json and zh-CN.json have the same keys, and the same {n} placeholders per key; en.json has no CJK.
3. Every literal $t('ns.key') used in web/src exists in en.json.
Exit code 1 on any failure.
"""
import json, os, re, sys

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web')
ROOT = os.path.join(WEB, 'src')
CJK = re.compile('[' + chr(0x3000) + '-' + chr(0x303f) + chr(0x3400) + '-' + chr(0x4dbf) + chr(0x4e00) + '-' + chr(0x9fff)
                 + chr(0xf900) + '-' + chr(0xfaff) + chr(0xff00) + '-' + chr(0xffef) + ']')
EXTS = ('.vue', '.ts', '.js', '.css', '.html', '.json', '.md')
SKIP = {os.path.normpath('locales/zh-CN.json')}
ALLOW = [  # (path relative to web/src, substring of the line that may contain CJK)
]

fails = {'cjk': [], 'locale': [], 'missing': []}
used = set()


def scan(path, label):
    src = open(path, encoding='utf-8').read()
    for i, line in enumerate(src.split('\n'), 1):
        if CJK.search(line) and not any(label == a and s in line for a, s in ALLOW):
            fails['cjk'].append('CJK %s:%d: %s' % (label, i, line.strip()[:120]))
    return src


for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if not f.endswith(EXTS):
            continue
        p = os.path.join(dp, f)
        rel = os.path.normpath(os.path.relpath(p, ROOT))
        if rel in SKIP:
            used.update(re.findall(r"\$t\('(\w+\.\w+)'", open(p, encoding='utf-8').read()))
            continue
        src = scan(p, rel.replace(os.sep, '/'))
        used.update(re.findall(r"\$t\('(\w+\.\w+)'", src))
for extra in ('index.html', 'panels-dev.html', 'plc-dev.html', os.path.join('public', 'brand', 'manifest.json')):
    p = os.path.join(WEB, extra)
    if os.path.exists(p):
        scan(p, '../' + extra.replace(os.sep, '/'))

loc = os.path.join(ROOT, 'locales')
en = json.load(open(os.path.join(loc, 'en.json'), encoding='utf-8'))
zh = json.load(open(os.path.join(loc, 'zh-CN.json'), encoding='utf-8'))
flat = lambda d: {ns + '.' + k: v for ns, kv in d.items() for k, v in kv.items()}
fe, fz = flat(en), flat(zh)
for k in sorted(set(fe) ^ set(fz)):
    fails['locale'].append('KEY only in %s: %s' % ('en' if k in fe else 'zh-CN', k))
ph = lambda s: sorted(re.findall(r'\{\d+\}', s))
for k in sorted(set(fe) & set(fz)):
    if ph(fe[k]) != ph(fz[k]):
        fails['locale'].append('PLACEHOLDER mismatch %s: %r / %r' % (k, fe[k], fz[k]))
    if CJK.search(fe[k]):
        fails['locale'].append('CJK in en.json %s: %r' % (k, fe[k]))
for k in sorted(used - set(fe)):
    fails['missing'].append('MISSING key used in code: %s' % k)

allf = [x for v in fails.values() for x in v]
for f in allf[:200]:
    print('FAIL', f.encode('ascii', 'backslashreplace').decode())
print('%d/3 i18n web checks passed (%d keys, %d used in code)' % (sum(1 for v in fails.values() if not v), len(fe), len(used)))
sys.exit(1 if allf else 0)
