"""Internationalisation: request language, message catalogue (English default, zh-CN) and translated content.

Message ids are the original Chinese source texts (the product was written in Chinese). `vfactory/locale/en.json` maps each id to
English, `vfactory/locale/zh-CN.json` holds optional zh-CN overrides. Code calls `_tr('...', name=value)`; `str.format` placeholders
are named. Module-level data (label tables, block catalogues, enum labels) stays as data and is translated where it is served
(`tr_obj`, the JSON response filter below). The teaching MES (vfmes/) uses the same module and catalogue.

Language of a request: header `X-Lang` > query `?lang=` > `Accept-Language` > server default.
Server default (simulation texts, background jobs, plant data): env `VF_LANG` (`en` | `zh-CN`), else `en`.
Demo mode: env `VF_DEMO=1` (demo accounts with the well-known initial passwords + the demo class). Without it a fresh server
has no accounts and asks for the first administrator (`/api/setup/admin`).

Content (courses, PLC training scenes, guided tours, plant templates, plants, samples) is authored in one language. English (or
other) text lives in a string map next to the file: `<dir>/i18n/<file stem>.en.json` = {"<source text>": "<English>"}; see
docs/translating-content.md. `content(obj, src)` returns `obj` with every mapped string replaced (in English; other languages unchanged).
"""
import contextlib
import contextvars
import glob
import json
import os
import re
import sys
from urllib.parse import parse_qs

LANGS = ('en', 'zh-CN')
_LANG = contextvars.ContextVar('vf_lang', default=None)
HERE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(HERE, 'locale')
_CAT: dict = {}
CJK = re.compile(r'[　-〿一-鿿＀-￯]')


def _load(name):
    if name not in _CAT:
        try:
            with open(os.path.join(_DIR, name + '.json'), encoding='utf-8') as f:
                _CAT[name] = json.load(f)
        except FileNotFoundError:
            _CAT[name] = {}
    return _CAT[name]


def norm(v) -> str | None:
    v = (v or '').strip().lower().replace('_', '-')
    if v.startswith('zh'):
        return 'zh-CN'
    if v.startswith('en'):
        return 'en'
    return None


def _flag(name) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def demo_mode() -> bool:
    """Demo mode: demo accounts (admin / engineer / guest with the well-known initial password) and the demo class."""
    return _flag('VF_DEMO')


def default_lang() -> str:
    return norm(os.environ.get('VF_LANG')) or 'en'


def lang() -> str:
    return _LANG.get() or default_lang()


def is_zh() -> bool:
    return lang() == 'zh-CN'


@contextlib.contextmanager
def use(language):
    tok = _LANG.set(norm(language) or 'en')
    try:
        yield
    finally:
        _LANG.reset(tok)


@contextlib.contextmanager
def server_language():
    """Run a block in the server language (VF_LANG): the simulation's texts do not depend on who triggered a step."""
    tok = _LANG.set(None)
    try:
        yield
    finally:
        _LANG.reset(tok)


def _lookup(s, language):
    if language == 'zh-CN':
        return _load('zh-CN').get(s, s)
    return _load('en').get(s)


def _importing() -> bool:
    """True while a module body is being executed by the import system: data built at import time keeps the source text and is
    translated where it is served."""
    f = sys._getframe(2)
    while f is not None:
        if f.f_code.co_filename.startswith('<frozen importlib'):
            return True
        f = f.f_back
    return False


def _tr(_s, /, **kw):
    """Translate message id `_s` into the current language and format named placeholders."""
    language = 'zh-CN' if _importing() else lang()
    out = _lookup(_s, language)
    if out is None:                       # no English yet: fall back to the source text
        out = _s
    elif language == 'en' and kw:         # labels passed as values (kind names, block names...) are translated too
        kw = {k: (en_text(v) if isinstance(v, str) else v) for k, v in kw.items()}
    if not kw:
        return out
    try:
        return out.format(**kw)
    except (KeyError, IndexError, ValueError):
        return _s.format(**kw)


tr = _tr


def server_tr(_s, /, **kw):
    """_tr in the server language (data written once for everybody: sample records, seeded names)."""
    with server_language():
        return _tr(_s, **kw)


def en_text(s):
    """English for one string if it is a catalogue id or mapped content text, else the string itself."""
    if not isinstance(s, str) or not CJK.search(s):
        return s
    return _load('en').get(s) or _load('data-en').get(s) or content_all().get(s) or s


def label(s):
    """A label from a module-level table in the current language (zh-CN: unchanged)."""
    return en_text(s) if lang() == 'en' else s


def tr_obj(o, skip=frozenset()):
    """Translate every string value of a JSON-like object that is a catalogue id or mapped content text (exact match).
    String values under keys in `skip` (codes, ids) are left alone. Only in English."""
    if lang() != 'en':
        return o

    def walk(x):
        if isinstance(x, str):
            return en_text(x)
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, tuple):
            return tuple(walk(v) for v in x)
        if isinstance(x, dict):
            return {k: (v if k in skip and isinstance(v, str) else walk(v)) for k, v in x.items()}
        return x
    return walk(o)


def llm_instruction() -> str:
    """Appended to every model call: answer in the UI language."""
    if is_zh():
        return '请用简体中文回答（界面语言是中文）。'
    return ('The user interface language is English: always answer in English, including headings, table headers and labels, '
            'even when the data, tool results or instructions above are in Chinese. Keep identifiers, block ids, tag names, '
            'addresses, codes and numbers exactly as they are.')


def resolve(headers: dict, query: str) -> str:
    v = norm(headers.get(b'x-lang', b'').decode('latin-1'))
    if v:
        return v
    q = parse_qs(query or '')
    v = norm((q.get('lang') or [''])[0])
    if v:
        return v
    al = headers.get(b'accept-language', b'').decode('latin-1')
    if al:
        v = norm(al.split(',')[0].split(';')[0])
        if v:
            return v
    return default_lang()


# ---------------- JSON response filter ----------------
# English JSON responses under /api/: string values that are exactly a catalogue id or a mapped content text are translated.
# Not filtered: endpoints whose data is edited and saved back (model editor, PLC programs, course authoring drafts, datasets...)
# - otherwise a save would write the translation into the user's data - and the teaching MES generic record API.
NO_FILTER = ('/api/login', '/api/setup/', '/api/mes/e/', '/api/e/')
NO_FILTER_RX = re.compile(r'^/api/(p/[^/]+/(model|versions|plan$|tables/|submodels|hmi/|cells/[^/]+$|plc/[^/]+/program|protocol/settings|'
                          r'energy/settings)|teach/authoring/(?!meta$)[^/]+(/draft)?$|settings/|report/templates|templates)')
FILTER_SKIP = frozenset({'id', 'pid', 'sid', 'code', 'key', 'keys', 'kind', 'type', 'status', 'state', 'cls', 'role', 'roles', 'username', 'token',
                         'password', 'tag', 'tags_raw', 'addr', 'address', 'topic', 'node', 'nodeid', 'path', 'file', 'url', 'value', 'program',
                         'source', 'st', 'yaml', 'sql', 'module', 'writable', 'plant', 'scene', 'block', 'param', 'var', 'sym', 'symbol', 'cond', 'expr'})


def _filtered(path):
    return path.startswith('/api/') and not path.startswith(NO_FILTER) and not NO_FILTER_RX.match(path)


def install(app):
    """Pure ASGI middleware (install it last = outermost): sets the request language, echoes Content-Language and translates
    catalogue texts in English JSON responses."""
    class _LangMw:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get('type') not in ('http', 'websocket'):
                return await self.inner(scope, receive, send)
            hdrs = dict(scope.get('headers') or [])
            language = resolve(hdrs, scope.get('query_string', b'').decode('latin-1'))
            tok = _LANG.set(language)
            path = scope.get('path', '')
            filt = language == 'en' and scope.get('type') == 'http' and _filtered(path)
            state = {'start': None, 'body': [], 'json': False}

            async def send2(msg):
                if msg['type'] == 'http.response.start':
                    headers = [h for h in msg.get('headers', []) if h[0].lower() != b'content-language'] + [(b'content-language', language.encode())]
                    msg = {**msg, 'headers': headers}
                    ctype = dict((k.lower(), v) for k, v in headers).get(b'content-type', b'')
                    if filt and ctype.startswith(b'application/json'):
                        state['start'], state['json'] = msg, True
                        return
                    return await send(msg)
                if msg['type'] == 'http.response.body' and state['json']:
                    state['body'].append(msg.get('body', b''))
                    if msg.get('more_body'):
                        return
                    raw = b''.join(state['body'])
                    try:
                        if CJK.search(raw.decode('utf-8')) or b'\\u' in raw:
                            raw = json.dumps(tr_obj(json.loads(raw), FILTER_SKIP), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    except Exception:
                        pass
                    start = state['start']
                    headers = [h for h in start['headers'] if h[0].lower() != b'content-length'] + [(b'content-length', str(len(raw)).encode())]
                    await send({**start, 'headers': headers})
                    return await send({'type': 'http.response.body', 'body': raw})
                return await send(msg)
            try:
                return await self.inner(scope, receive, send2)
            finally:
                _LANG.reset(tok)
    app.add_middleware(_LangMw)
    _executor_context()


def _executor_context():
    """loop.run_in_executor(...) does not carry context variables into the worker thread (asyncio.to_thread does): make it carry
    them, so texts produced in worker threads (model calls, experiments, forks) use the request language."""
    import asyncio.base_events as be
    if getattr(be.BaseEventLoop.run_in_executor, '_vf_ctx', False):
        return
    orig = be.BaseEventLoop.run_in_executor

    def run_in_executor(self, executor, func, *args):
        import concurrent.futures as cf
        if executor is None or isinstance(executor, cf.ThreadPoolExecutor):     # process pools: the worker uses the server language
            return orig(self, executor, contextvars.copy_context().run, func, *args)
        return orig(self, executor, func, *args)
    run_in_executor._vf_ctx = True
    be.BaseEventLoop.run_in_executor = run_in_executor


# ---------------- content (courses, scenes, tours, templates, plants, samples) ----------------
# Display texts of a content file are translated through the string map next to it: <dir>/i18n/<stem>.en.json.
# Keys whose values are code or identifiers are never translated.
CONTENT_SKIP = frozenset({'id', 'key', 'kind', 'type', 'qtype', 'source', 'program', 'st', 'code', 'addr', 'address', 'tag_name', 'var',
                          'scene', 'plant', 'ref', 'seal', 'explain_seal', 'expr', 'formula', 'when', 'cond'})
_MAPS: dict = {}
_ALL: dict = {}


def content_map_path(src):
    d, f = os.path.split(os.path.abspath(src))
    return os.path.join(d, 'i18n', os.path.splitext(f)[0] + '.en.json')


def content_map(src) -> dict:
    """The English string map of one content file ({} if there is none)."""
    if not src:
        return {}
    p = content_map_path(src)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    c = _MAPS.get(p)
    if c and c[0] == mt:
        return c[1]
    try:
        with open(p, encoding='utf-8') as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    _MAPS[p] = (mt, m if isinstance(m, dict) else {})
    _ALL.clear()
    return _MAPS[p][1]


def content_dirs():
    """Folders whose files have content maps (program folder; plants/ under the data folder as well)."""
    root = os.path.dirname(HERE)
    out = [os.path.join(root, 'templates'), os.path.join(root, 'templates', 'cells'), os.path.join(root, 'plants'),
           os.path.join(HERE, 'courses'), os.path.join(HERE, 'courses', 'plants'), os.path.join(HERE, 'control', 'scenes'),
           os.path.join(HERE, 'teach', 'tours'), os.path.join(HERE, 'samples')]
    return out


def content_all() -> dict:
    """All content maps merged (texts that leave their file: template names in lists, plant names in events...)."""
    if not _ALL:
        merged = {}
        for d in content_dirs():
            for p in sorted(glob.glob(os.path.join(d, 'i18n', '*.en.json'))):
                try:
                    with open(p, encoding='utf-8') as f:
                        m = json.load(f)
                    if isinstance(m, dict):
                        for k, v in m.items():
                            merged.setdefault(k, v)
                except (OSError, ValueError):
                    continue
        merged.setdefault('', '')
        _ALL.update(merged)
    return _ALL


def content(obj, src=None, language=None):
    """`obj` (JSON/YAML data of a content file) in `language` (default: the current language). English: mapped strings replaced,
    in a new object; the cached original is never modified. Other languages: `obj` itself."""
    language = language or lang()
    if language != 'en' or obj is None:
        return obj
    m = content_map(src) if src else {}
    en = _load('en')
    allm = content_all()

    def walk(x, key=None):
        if isinstance(x, str):
            if key in CONTENT_SKIP or not CJK.search(x):
                return x
            return m.get(x) or allm.get(x) or en.get(x) or x
        if isinstance(x, list):
            return [walk(v, key) for v in x]
        if isinstance(x, dict):
            return {k: walk(v, k) for k, v in x.items()}
        return x
    return walk(obj)


# ---------------- logic on texts that may be translated ----------------
def variants(msgid) -> set:
    """The source text and its English translation (texts written earlier may be in either language)."""
    return {msgid, _load('en').get(msgid, msgid)}


def _rx(template):
    parts = re.split(r'\{[^{}]*\}', template)
    return re.compile('.*?'.join(re.escape(p) for p in parts), re.S)


def matches(text, msgid) -> bool:
    """True if `text` was produced from message `msgid` (any language; placeholders match anything)."""
    if not text:
        return False
    return any(_rx(v).search(text) for v in variants(msgid))
