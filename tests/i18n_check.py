"""i18n check (backend): Chinese string literals in vfactory/ and vfmes/ that are not covered by the message catalogue, and content
texts without an English entry in their content map.

    python tests/i18n_check.py                     report; exit 1 when something is not in the allowlist
    python tests/i18n_check.py --write-allowlist   (maintainers) rewrite tests/i18n_allowlist.json with the current findings

Rules (comments and docstrings are ignored):
  hard-coded    a Chinese literal inside a function that is not passed through _tr(...) (parsing keywords, regexes, comparisons with
                stored values, data contracts such as the delivery package belong in the allowlist with a reason)
  untranslated  a _tr() message id or a module-level Chinese label without an English entry in vfactory/locale/en.json
  data          teaching-MES seed data (vfmes/seed.py) without an entry in vfactory/locale/data-en.json
  content       a display text of a content file (courses, PLC scenes, tours, templates, plants, samples) missing from its
                content map <dir>/i18n/<file>.en.json (see docs/translating-content.md)
Not checked: vfactory/locale, vfactory/static, the content builders (courses/build*.py, control/scenes/build.py: they generate
content files, which are checked as content).
"""
import ast
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTS = ('vfactory', 'vfmes')
ALLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n_allowlist.json')
CJK = re.compile(r'[　-〿一-鿿＀-￯]')
DATA = re.compile(r'^vfmes/seed\.py$')
SKIP = re.compile(r'(^|/)i18n\.py$|(^|/)locale/|(^|/)static/|^vfactory/courses/build[a-z_]*\.py$|^vfactory/control/scenes/build\.py$'
                  r'|(^|/)license_keys\.py$')
CONTENT_GLOBS = ['templates/*.yaml', 'templates/cells/*.yaml', 'plants/*.yaml', 'vfactory/courses/*.json', 'vfactory/courses/plants/*.yaml',
                 'vfactory/control/scenes/*.json', 'vfactory/teach/tours/*.json', 'vfactory/samples/*.json', 'vfactory/samples/*.yaml']


def load(name):
    with open(os.path.join(REPO, 'vfactory', 'locale', name), encoding='utf-8') as f:
        return json.load(f)


EN, DEN = load('en.json'), load('data-en.json')


def literal_text(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return ''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in n.values)
    return None


class V(ast.NodeVisitor):
    def __init__(self):
        self.fn = 0
        self.out = []      # (kind, line, text)

    def _body(self, body):
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        for s in body:
            self.visit(s)

    def visit_Module(self, n):
        self._body(n.body)

    def visit_ClassDef(self, n):
        for d in n.decorator_list:
            self.visit(d)
        self._body(n.body)

    def _fn(self, n):
        for d in n.decorator_list:
            self.visit(d)
        self.visit(n.args)
        self.fn += 1
        self._body(n.body)
        self.fn -= 1
    visit_FunctionDef = visit_AsyncFunctionDef = _fn

    def visit_Lambda(self, n):
        self.fn += 1
        self.visit(n.body)
        self.fn -= 1

    # calls whose argument is a message id (translated now, at read time, or matched in every language)
    MSGID_ARG = {'_tr': 0, 'tr': 0, 'server_tr': 0, 'matches': 1, 'variants': 0, 'label': 0, 'en_text': 0}

    def visit_Call(self, n):
        fname = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ''
        idx = self.MSGID_ARG.get(fname)
        if idx is not None and len(n.args) > idx and literal_text(n.args[idx]) is not None:
            for i, a in enumerate(n.args):
                if i != idx:
                    self.visit(a)
            t = literal_text(n.args[idx])
            if CJK.search(t):
                self.out.append(('msgid', n.lineno, t))
            for k in n.keywords:
                self.visit(k.value)
            return
        self.generic_visit(n)

    def _lit(self, n):
        t = literal_text(n)
        if t is None or not CJK.search(t):
            return
        self.out.append(('fn' if self.fn else 'mod', n.lineno, t))

    def visit_Constant(self, n):
        self._lit(n)

    def visit_JoinedStr(self, n):
        self._lit(n)
        for v in n.values:
            if isinstance(v, ast.FormattedValue):
                self.visit(v.value)


def content_findings():
    sys.path.insert(0, REPO)
    import yaml
    from vfactory.i18n import CONTENT_SKIP, content_map_path
    found = []
    for g in CONTENT_GLOBS:
        for p in sorted(glob.glob(os.path.join(REPO, g))):
            rel = os.path.relpath(p, REPO).replace('\\', '/')
            with open(p, encoding='utf-8') as f:
                d = json.load(f) if p.endswith('.json') else yaml.safe_load(f)
            mp = content_map_path(p)
            m = {}
            if os.path.exists(mp):
                with open(mp, encoding='utf-8') as f:
                    m = json.load(f)
            seen = set()

            def walk(x, key=None):
                if isinstance(x, str):
                    if x[:1] in '[{':            # JSON stored as a string (sample experiments): its texts
                        try:
                            return walk(json.loads(x), key)
                        except ValueError:
                            pass
                    if key not in CONTENT_SKIP and CJK.search(x) and not m.get(x) and x not in EN and x not in seen:
                        seen.add(x)
                        found.append(('content', rel, 0, x))
                elif isinstance(x, list):
                    for v in x:
                        walk(v, key)
                elif isinstance(x, dict):
                    for k, v in x.items():
                        walk(v, k)
            walk(d)
    return found


def scan():
    found = []
    for root in ROOTS:
        for dp, dn, fn in os.walk(os.path.join(REPO, root)):
            if '__pycache__' in dp:
                continue
            for name in fn:
                if not name.endswith('.py'):
                    continue
                p = os.path.join(dp, name)
                rel = os.path.relpath(p, REPO).replace('\\', '/')
                if SKIP.search(rel):
                    continue
                with open(p, encoding='utf-8') as f:
                    v = V()
                    v.visit(ast.parse(f.read()))
                data = bool(DATA.search(rel))
                for kind, line, t in v.out:
                    if data:
                        if '{}' not in t and t not in DEN and t not in EN:
                            found.append(('data', rel, line, t))
                    elif kind == 'msgid':
                        if t not in EN:
                            found.append(('untranslated', rel, line, t))
                    elif kind == 'mod':
                        if t not in EN and '{}' not in t:
                            found.append(('untranslated', rel, line, t))
                    else:
                        found.append(('hard-coded', rel, line, t))
    return found + content_findings()


REASONS = {'hard-coded': 'matches Chinese input/stored values (keywords, regex, comparisons, dict keys) or a data contract',
           'untranslated': 'model prompt / template kept in the source language; every model call adds the UI-language instruction',
           'data': 'demo data value without English entry (stays Chinese in English mode)',
           'content': 'content text without English entry (shown in Chinese in English mode)'}


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    found = scan()
    allow = {}
    if os.path.exists(ALLOW):
        with open(ALLOW, encoding='utf-8') as f:
            allow = {(a['file'], a['text']): a for a in json.load(f)['items']}
    if '--write-allowlist' in sys.argv:
        items = []
        for kind, rel, line, t in found:
            old = allow.get((rel, t))
            items.append({'file': rel, 'text': t, 'kind': kind, 'reason': (old or {}).get('reason') or REASONS.get(kind, '')})
        uniq = {(i['file'], i['text']): i for i in items}
        with open(ALLOW, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'note': 'Chinese literals that intentionally stay as they are (see tests/i18n_check.py)', 'items': list(uniq.values())},
                      f, ensure_ascii=False, indent=1)
        print('allowlist written:', len(uniq))
        return 0
    bad = [x for x in found if (x[1], x[3]) not in allow]
    by = {}
    for kind, rel, line, t in found:
        by[kind] = by.get(kind, 0) + 1
    print('Chinese literals not covered by the catalogue:', by, '| allowlisted', len(found) - len(bad), '| NEW', len(bad))
    for kind, rel, line, t in bad[:200]:
        print(f'  {kind:13} {rel}:{line}  {t[:90]!r}')
    print(f'{len(found) - len(bad)}/{len(found)} allowlisted')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
