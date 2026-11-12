"""客户端登录到服务器以后（"联网模式"）：本地服务当服务器的代理 + 本机工厂的运行环境（设计 4.3 第 4 节）。

为什么用代理（而不是让窗口直接打开服务器网址）：
- 窗口始终打开本地服务 http://127.0.0.1:<端口>/，网页（和客户端同版本）只跟一个来源打交道：没有跨域、没有混合内容（https 服务器页面
  不能随便访问本机 http），websocket、下载链接、AI 助手的流式回答都走同一条路；
- 服务器令牌只在本地服务里（DPAPI 加密存盘），网页拿的是本机会话；断网时网页照样打开，本机工厂、已下载的课继续能用；
- 服务器上的工厂和本机工厂在同一个列表里，按工厂编号分流，前端代码不用改调用方式。

分流规则（只在联网模式下；单机模式全部本机处理）：
  /api/p/<工厂>/…、/ws/<工厂>     本机有这个工厂/沙箱 → 本机，否则 → 服务器
  GET /api/plants、/api/overview   合并：服务器的工厂 + 本机工厂（local: true）
  POST /api/plants                 body.local 为真 → 本机新建，否则 → 服务器
  /api/teach…、/api/tutor…         学生 → 本机（本机自学 + 装到本机的学校作业，见 vfactory/teach/client.py），其他角色 → 服务器
  /api/desktop/…、/api/client/…、/api/mes/…、/api/health、/api/me、/api/login、网页文件   → 本机
  POST /api/me/password            改的是服务器账号的密码：转发给服务器，成功后更新本机记住的离线登录核对值（新密码离线也能登录，旧密码不行）
  其他 /api/…                      请求头 X-VF-Plant（或 ?vfp=）是本机工厂 → 本机，否则 → 服务器
服务器连不上：转发的请求回 503"离线"，合并列表只给本机部分；交作业（/api/client/school/submit）进本机待交队列，联网后自动交。
"""
from .i18n import _tr
import asyncio
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import paths, store

log = logging.getLogger('vfactory.desktop')
_PID = re.compile(r'^/api/p/([^/]+)')
_WS = re.compile(r'^/ws/([^/]+)$')
SAAS_SERVER_PATHS = ('/api/admin/', '/api/org', '/api/tokens', '/api/progress/', '/api/me/', '/api/teach')    # 连着 SaaS 时交给服务器的
_PROGRESS_EVENT = re.compile(r'^/api/teach/assignments/(\d+)/(submit|answers|sandbox)$')
LOCAL_PREFIXES = ('/api/desktop/', '/api/client/', '/api/mes/')     # /api/mes/：本机 MES（5.0.1，vfactory/mes/sidecar.py 转发），从不交给服务器
LOCAL_EXACT = {'/api/health', '/api/me', '/api/login'}
HOP = {'connection', 'keep-alive', 'transfer-encoding', 'te', 'trailer', 'upgrade', 'proxy-authorization', 'proxy-authenticate', 'host',
       'content-length', 'authorization', 'cookie'}


class Offline(Exception):
    pass


# ---------------------------------------------------------------- 同步访问服务器（在线程里跑）
def http(method, url, body=None, raw=None, token=None, timeout=30, headers=None):
    """→ (状态码, 头字典, 字节)。连不上抛 Offline。"""
    data = raw if raw is not None else (json.dumps(body).encode('utf-8') if body is not None else None)
    h = {'Accept': 'application/json', **(headers or {})}
    if data is not None and 'Content-Type' not in h:
        h['Content-Type'] = 'application/octet-stream' if raw is not None else 'application/json'
    if token:
        h['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()) if e.headers else {}, e.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise Offline(str(getattr(e, 'reason', e)))


def jbody(b):
    try:
        return json.loads(b.decode('utf-8')) if b else {}
    except ValueError:
        return {}


async def acall(method, url, **kw):
    return await asyncio.get_running_loop().run_in_executor(None, lambda: http(method, url, **kw))


def _json_response(status, obj):
    b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    return status, [(b'content-type', b'application/json; charset=utf-8'), (b'content-length', str(len(b)).encode())], b


async def _send(send, status, headers, body):
    await send({'type': 'http.response.start', 'status': status, 'headers': headers})
    await send({'type': 'http.response.body', 'body': body})


class Proxy:
    """包在 FastAPI 应用外面的 ASGI 中间件。d = vfactory.desktop.Desktop。"""

    def __init__(self, app, d):
        self.app, self.d = app, d

    async def __call__(self, scope, receive, send):
        d = self.d
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        path = scope['path']
        if d.settings.get('mode') != 'standalone' and not d.connected():
            # 没登录（第一次打开、退出登录、服务器令牌过期或超过 7 天）：除了登录相关的接口，一律 401 → 前端去登录页
            if scope['type'] == 'http' and path.startswith('/api/') and path not in d.OPEN and path != '/api/health':
                return await _send(send, *_json_response(401, {'detail': _tr('请先登录')}))
            if scope['type'] == 'websocket':
                await receive()
                return await send({'type': 'websocket.close', 'code': 1008})
            return await self.app(scope, receive, send)
        if d.settings.get('mode') == 'standalone':
            return await self.app(scope, receive, send)
        if scope['type'] == 'websocket':
            m = _WS.match(path)
            if m and not d.is_local(urllib.parse.unquote(m.group(1))) and (d.account or {}).get('deploy') != 'saas':
                return await self.ws_proxy(scope, receive, send, m.group(1))
            return await self.app(scope, receive, send)
        if not (path.startswith('/api/') or path in ('/docs', '/redoc', '/openapi.json')):
            return await self.app(scope, receive, send)       # 网页文件：本机（和客户端同版本）
        user = self.user(scope)
        if path == '/api/me/password' and scope['method'] == 'POST':
            return await self.change_password(scope, receive, send, user)
        target = self.route(scope, user)
        if target == 'local':
            if scope['method'] == 'POST' and path == '/api/client/school/submit':
                return await self.submit_or_queue(scope, receive, send, user)
            m = _PROGRESS_EVENT.match(path) if scope['method'] in ('POST', 'PUT') else None
            if m and getattr(d, 'progress', None):               # 5.0：本机交作业/作答 → 10 秒内上报一次进度
                d.progress.mark()
            return await self.app(scope, receive, send)
        if not user:                                            # 没有本机会话：交给本机返回 401（前端转登录页）
            return await self.app(scope, receive, send)
        body = await _read_body(receive)
        if target == 'merge':
            return await _send(send, *await self.merged(scope, body))
        if target == 'create':
            try:
                b = json.loads(body or b'{}')
            except ValueError:
                b = {}
            if b.get('local') or (self.d.account or {}).get('deploy') == 'saas':   # 本机新建（连着 SaaS 时只能本机）：编号统一加 local- 前缀，不会和服务器上的工厂撞号
                base = str(b.get('id') or b.get('copy_from') or b.get('template') or 'plant').lower()
                base = 'local-' + re.sub(r'[^a-z0-9]+', '-', base.removeprefix('local-')).strip('-')[:30]
                pid, n = base, 1
                while self.d.is_local(pid):
                    n += 1
                    pid = f'{base}-{n}'
                b['id'] = pid
                body = json.dumps(b).encode()
                scope = {**scope, 'headers': [(k, v) for k, v in scope['headers'] if k.lower() != b'content-length']
                         + [(b'content-length', str(len(body)).encode())]}
                return await self.app(scope, _replay(body), send)
        return await self.forward(scope, body, send)

    # ---------- 分流 ----------
    def user(self, scope):
        qs = urllib.parse.parse_qs(scope.get('query_string', b'').decode())
        hd = _headers(scope)
        tok = hd.get('authorization', '').removeprefix('Bearer ').strip() or (qs.get('token') or [''])[0]
        if not tok:
            return None
        try:
            u, _ = store.check_token(tok, (scope.get('client') or ('',))[0], mark=False)
        except Exception:
            return None
        return u

    def route(self, scope, user):
        d, path, method = self.d, scope['path'], scope['method']
        if path in LOCAL_EXACT or path.startswith(LOCAL_PREFIXES):
            return 'local'
        if (d.account or {}).get('deploy') == 'saas':
            # 5.0 连着 SaaS：服务器上没有工厂，工厂、模型、模板、目录、建模助手这些都在本机；服务器只管账号、单位、教学、进度
            if path.startswith(('/api/teach', '/api/tutor')):
                if self.saas_local(path, method, user):
                    return 'local'
                return 'local' if (user or {}).get('role') == 'student' else 'server'
            if path.startswith(SAAS_SERVER_PATHS):
                return 'server'
            if path == '/api/plants' and method == 'POST':
                return 'create'
            if path in ('/api/plants', '/api/overview') and method == 'GET':
                return 'merge'                                 # 服务器那边是空的；合并时本机的标上 local
            return 'local'
        m = _PID.match(path)
        if m:
            return 'local' if d.is_local(urllib.parse.unquote(m.group(1))) else 'server'
        if path in ('/api/plants', '/api/overview') and method == 'GET':
            return 'merge'
        if path == '/api/plants' and method == 'POST':
            return 'create'
        dm = re.match(r'^/api/plants/([^/]+)$', path)
        if dm:
            return 'local' if d.is_local(urllib.parse.unquote(dm.group(1))) else 'server'
        if path.startswith(('/api/teach', '/api/tutor')) and self.saas_local(path, method, user):
            return 'local'
        if path.startswith(('/api/teach', '/api/tutor')):
            return 'local' if (user or {}).get('role') == 'student' else 'server'
        hd = _headers(scope)
        qs = urllib.parse.parse_qs(scope.get('query_string', b'').decode())
        ctx = hd.get('x-vf-plant') or (qs.get('vfp') or [''])[0]
        if ctx and d.is_local(urllib.parse.unquote(ctx)):
            return 'local'
        return 'server'

    def saas_local(self, path, method, user):
        """5.0：连着 SaaS 服务器（服务器不跑工厂）时，老师的课程编辑器、出题检查、预览、AI 助教在本机跑：
        /api/teach/authoring/…、预览作业（编号 ≥ 10 亿）、预览课程和本机草稿的课程详情/封面、/api/tutor/…。"""
        if (self.d.account or {}).get('deploy') != 'saas':
            return False
        if path.startswith('/api/tutor'):
            return True
        if path.startswith('/api/teach/authoring'):
            return True
        from .tenancy.coursesync import PREVIEW_AID_BASE
        m = re.match(r'^/api/teach/assignments/(\d+)(/|$)', path)
        if m:
            return int(m.group(1)) >= PREVIEW_AID_BASE
        m = re.match(r'^/api/teach/courses/([^/]+)(/assets/[^/]+)?$', path)
        if m and method == 'GET':
            cid = urllib.parse.unquote(m.group(1))
            if cid.startswith('_preview-'):
                return True
            try:
                from .teach import authoring
                return bool(authoring._row(cid))
            except Exception:                                   # noqa: BLE001
                return False
        return False

    # ---------- 转发（流式：AI 助手的 SSE 回答、大文件下载） ----------
    async def forward(self, scope, body, send):
        d = self.d
        qs = [(k, v) for k, v in urllib.parse.parse_qsl(scope.get('query_string', b'').decode(), keep_blank_values=True) if k not in ('token', 'vfp')]
        url = d.server_url() + urllib.parse.quote(scope['path']) + ('?' + urllib.parse.urlencode(qs) if qs else '')
        hd = {k: v for k, v in _headers(scope).items() if k not in HOP and not k.startswith('x-vf-') and k not in ('origin', 'referer')}
        hd['Authorization'] = 'Bearer ' + (d.server_token() or '')
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def work():
            req = urllib.request.Request(url, data=body if body else None, method=scope['method'], headers=hd)
            try:
                try:
                    r = urllib.request.urlopen(req, timeout=300)
                except urllib.error.HTTPError as e:
                    r = e
                loop.call_soon_threadsafe(q.put_nowait, ('start', r.status if hasattr(r, 'status') else r.code, list(r.headers.items())))
                while True:
                    chunk = r.read1(65536) if hasattr(r, 'read1') else r.read(65536)
                    if not chunk:
                        break
                    loop.call_soon_threadsafe(q.put_nowait, ('data', chunk))
                loop.call_soon_threadsafe(q.put_nowait, ('end',))
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                loop.call_soon_threadsafe(q.put_nowait, ('fail', str(getattr(e, 'reason', e))))

        threading.Thread(target=work, daemon=True).start()
        first = await q.get()
        if first[0] == 'fail':
            d.set_online(False, first[1])
            return await _send(send, *_json_response(503, {'detail': _tr('离线：连不上服务器 {server_url}（{v}）。本机工厂和已下载的课可以继续用。', server_url=d.server_url(), v=first[1]),
                                                           'offline': True}))
        d.set_online(True)
        status, hdrs = first[1], first[2]
        if status == 401:                                      # 服务器令牌过期/被吊销：本机会话一起作废，前端转登录页
            while (await q.get())[0] == 'data':
                pass
            d.server_expired()
            return await _send(send, *_json_response(401, {'detail': _tr('服务器的登录已过期，请重新登录')}))
        out = [(k.lower().encode('latin-1'), str(v).encode('latin-1')) for k, v in hdrs if k.lower() not in HOP]
        await send({'type': 'http.response.start', 'status': status, 'headers': out})
        while True:
            m = await q.get()
            if m[0] == 'data':
                await send({'type': 'http.response.body', 'body': m[1], 'more_body': True})
            else:
                break
        await send({'type': 'http.response.body', 'body': b''})

    # ---------- 工厂列表：服务器 + 本机 ----------
    async def merged(self, scope, body):
        d = self.d
        code, hdrs, lb = await _inner(self.app, scope, body)
        local = jbody(lb) if code == 200 else {}
        lp = [{**p, 'local': True} for p in local.get('plants') or []]
        q = scope.get('query_string', b'').decode()
        try:
            sc, _, sb = await acall('GET', d.server_url() + scope['path'] + ('?' + q if q else ''), token=d.server_token(), timeout=15)
            d.set_online(True)
        except Offline as e:
            d.set_online(False, str(e))
            return _json_response(200, {**local, 'plants': lp, 'offline': True, 'server': d.server_url()})
        if sc == 401:
            d.server_expired()
            return _json_response(401, {'detail': _tr('服务器的登录已过期，请重新登录')})
        srv = jbody(sb) if sc == 200 else {}
        sp = [{**p, 'local': False} for p in srv.get('plants') or []]
        out = {**local, **srv, 'plants': sp + lp, 'server': d.server_url()}
        if scope['path'] == '/api/overview' and 'ports' in local and 'ports' not in srv:
            out['ports'] = None
        return _json_response(200, out)

    # ---------- websocket：服务器工厂的实时状态 ----------
    async def ws_proxy(self, scope, receive, send, pid):
        from websockets.asyncio.client import connect
        d = self.d
        msg = await receive()                                   # websocket.connect
        if msg['type'] != 'websocket.connect' or not self.user(scope):
            return await send({'type': 'websocket.close', 'code': 1008})
        base = d.server_url()
        url = ('wss' if base.startswith('https') else 'ws') + base[base.index(':'):] + f'/ws/{pid}?token=' + urllib.parse.quote(d.server_token() or '')
        try:
            up = await asyncio.wait_for(connect(url, max_size=None, open_timeout=10), 12)
        except Exception as e:                                  # 离线：关掉，前端 1.5 秒后重连
            d.set_online(False, str(e))
            return await send({'type': 'websocket.close', 'code': 1011})
        await send({'type': 'websocket.accept'})

        async def down():                                       # 服务器 → 网页
            try:
                async for m in up:
                    await send({'type': 'websocket.send', 'text': m} if isinstance(m, str) else {'type': 'websocket.send', 'bytes': m})
            except Exception:
                pass

        async def upward():                                     # 网页 → 服务器；网页断开就结束
            while True:
                m = await receive()
                if m['type'] == 'websocket.disconnect':
                    return 'gone'
                if m['type'] == 'websocket.receive':
                    try:
                        await up.send(m.get('text') if m.get('text') is not None else m.get('bytes'))
                    except Exception:
                        return 'up-closed'

        t1, t2 = asyncio.create_task(down()), asyncio.create_task(upward())
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        try:
            await up.close()
        except Exception:
            pass
        if t1 in done:                                          # 服务器那头断了（工厂重建等）：让网页重连
            try:
                await send({'type': 'websocket.close', 'code': 1012})
            except Exception:
                pass

    # ---------- 改密码：改服务器账号的，并更新本机记住的离线登录 ----------
    async def change_password(self, scope, receive, send, user):
        from .desktop import _verifier
        d = self.d
        body = await _read_body(receive)
        if not user:
            return await _send(send, *_json_response(401, {'detail': _tr('请先登录')}))
        try:
            b = json.loads(body or b'{}')
        except ValueError:
            b = {}
        try:
            code, _, rb = await acall('POST', d.server_url() + '/api/me/password', body={'old': b.get('old') or '', 'new': b.get('new') or ''},
                                      token=d.server_token(), timeout=20)
        except Offline as e:
            d.set_online(False, str(e))
            return await _send(send, *_json_response(503, {'detail': _tr('现在连不上服务器 {server_url}：改密码要联网（改的是服务器上的账号）', server_url=d.server_url()), 'offline': True}))
        d.set_online(True)
        if code == 401:
            d.server_expired()
            return await _send(send, *_json_response(401, {'detail': _tr('服务器的登录已过期，请重新登录')}))
        if code != 200:
            return await _send(send, *_json_response(code if code < 500 else 502, {'detail': jbody(rb).get('detail') or _tr('服务器没有改成（{code}）', code=code)}))
        a = d.account
        if a.get('username') == user.get('username') and a.get('server') == d.server_url():
            a['verifier'] = _verifier(a['server'], a['username'], b.get('new') or '')      # 离线登录从此用新密码核对
            d._save_account()
        log.info(_tr('服务器账号 %s 改了密码（本机离线登录核对值已更新）'), user.get('username'))
        return await _send(send, *_json_response(200, {'ok': True, 'server': d.server_url(), 'offline_login_updated': True}))

    # ---------- 交作业：连不上就进待交队列 ----------
    async def submit_or_queue(self, scope, receive, send, user):
        body = await _read_body(receive)
        code, hdrs, rb = await _inner(self.app, scope, body)
        if code == 200:
            try:
                laid = json.loads(body or b'{}').get('aid')
                self.d.event('submitted', self.d.assignment_title(laid))
                if getattr(self.d, 'progress', None):
                    self.d.progress.mark(submitted_laid=laid)       # 5.0：交给学校了 → 进度状态"已提交"
            except Exception:
                pass
        if code == 502 and user:
            try:
                jb = json.loads(body or b'{}')
                q = await self.d.outbox.add(int(jb.get('aid') or 0), user['username'], plant=jb.get('plant'))
                return await _send(send, *_json_response(202, {'queued': True, 'outbox': q,
                                                               'msg': _tr('现在连不上服务器：作业已打包存在本机，联网后自动交（设置 → 待交作业 里能看到）')}))
            except Exception as e:
                log.exception(_tr('作业进待交队列失败'))
                return await _send(send, *_json_response(502, {'detail': _tr('连不上服务器，作业也没能存进待交队列：{e}', e=e)}))
        return await _send(send, code, hdrs, rb)


# ---------------------------------------------------------------- 待交作业（离线时交的）
class Outbox:
    def __init__(self, d):
        self.d = d
        self.dir = paths.data('client', 'outbox')
        self._lock = asyncio.Lock()

    def items(self):
        out = []
        for f in sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []:
            if f.endswith('.json'):
                try:
                    with open(os.path.join(self.dir, f), encoding='utf-8') as fh:
                        out.append(json.load(fh))
                except (OSError, ValueError):
                    pass
        return out

    async def add(self, laid, username, plant=None):
        """把本机作业打成包存起来（存的是交的那一刻的程序/模型；提交工厂作业是那一刻的"我的工厂"）。"""
        from .teach import db as tdb
        app = self.d.app
        ln = tdb.q('select * from client_links where local_aid=?', (laid,), one=True)
        if not ln:
            raise ValueError(_tr('不是学校的作业'))
        data = await app.state.teach_build_package(laid, username, plant)
        os.makedirs(self.dir, exist_ok=True)
        qid = time.strftime('%Y%m%d%H%M%S') + f'-{laid}'
        with open(os.path.join(self.dir, qid + '.vfhw'), 'wb') as f:
            f.write(data)
        item = {'id': qid, 'local_aid': laid, 'remote_aid': ln['remote_aid'], 'server': ln['server'], 'title': ln.get('remote_title'),
                'username': username, 'queued': store.now(), 'state': 'waiting', 'tries': 0, 'msg': '', 'plant': plant or None}
        self._save(item)
        self.d.event('queued', item['title'])
        log.info(_tr('作业进待交队列 %s（学校作业 %s）'), qid, ln['remote_aid'])
        return item

    def _save(self, item):
        p = os.path.join(self.dir, item['id'] + '.json')
        with open(p + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(item, f, ensure_ascii=False, indent=1)
        os.replace(p + '.tmp', p)

    async def flush(self):
        """联网时把待交的作业交上去（服务器重新评分）。截止、次数等被服务器拒绝的标成 failed，不再重试。"""
        d = self.d
        if not d.connected():
            return 0
        n = 0
        async with self._lock:
            for it in self.items():
                if it['state'] != 'waiting' or it['server'] != d.server_url() or it['username'] != d.account.get('username'):
                    continue
                with open(os.path.join(self.dir, it['id'] + '.vfhw'), 'rb') as f:
                    data = f.read()
                try:
                    code, _, b = await acall('POST', f"{d.server_url()}/api/teach/assignments/{it['remote_aid']}/submit_package", raw=data,
                                             token=d.server_token(), timeout=360)
                except Offline as e:
                    d.set_online(False, str(e))
                    return n
                d.set_online(True)
                it['tries'] += 1
                r = jbody(b)
                if code == 200:
                    it.update(state='sent', sent=store.now(), result={'score': (r.get('score') if isinstance(r, dict) else None)}, msg=_tr('已交'))
                    n += 1
                    d.event('resent', it.get('title'))
                elif code == 401:
                    d.server_expired()
                    return n
                else:
                    it.update(state='failed', msg=_tr('服务器拒收：{v}', v=r.get('detail') if isinstance(r, dict) else code))
                self._save(it)
                log.info(_tr('待交作业 %s → %s %s'), it['id'], it['state'], it.get('msg'))
        return n


# ---------------------------------------------------------------- 把服务器上的工厂下载到本机
async def download_plant(d, pid, name=None):
    from .server import write_yaml
    base, tok = d.server_url(), d.server_token()
    try:
        code, _, b = await acall('GET', f'{base}/api/p/{urllib.parse.quote(pid)}/model', token=tok, timeout=60)
    except Offline as e:
        raise RuntimeError(_tr('连不上服务器：{e}', e=e))
    if code != 200:
        raise RuntimeError(_tr('服务器：{v}', v=jbody(b).get('detail') or code))
    model = jbody(b).get('model')
    if not isinstance(model, dict) or 'plant' not in model:
        raise RuntimeError(_tr('服务器没有返回工厂模型'))
    mgr = d.mgr
    base_id = 'local-' + re.sub(r'[^a-z0-9-]+', '-', pid.lower()).strip('-')[:30]
    lid, n = base_id, 1
    while lid in mgr.rts or os.path.exists(os.path.join(paths.PLANTS, f'{lid}.yaml')):
        n += 1
        lid = f'{base_id}-{n}'
    model['plant']['name'] = (name or model['plant'].get('name') or pid)[:40]
    model['plant'].pop('modbus_port', None)
    os.makedirs(paths.PLANTS, exist_ok=True)
    write_yaml(os.path.join(paths.PLANTS, f'{lid}.yaml'), model)
    # PLC 程序（工程里的，不在模型文件里）
    copied = 0
    try:
        code, _, b = await acall('GET', f'{base}/api/p/{urllib.parse.quote(pid)}/plc/cells', token=tok, timeout=30)
        cells = jbody(b).get('cells') or [] if code == 200 else []
        from .plc import store as ps
        for c in cells:
            code, _, pb = await acall('GET', f"{base}/api/p/{urllib.parse.quote(pid)}/cells/{urllib.parse.quote(c['id'])}/program", token=tok, timeout=30)
            prog = jbody(pb).get('program') if code == 200 else None
            if isinstance(prog, dict):
                ps.update(lid, 'cells', c['id'], program=prog, saved_at=store.now())
                copied += 1
    except Offline:
        pass
    rt = await mgr.launch(lid)
    if not rt:
        raise RuntimeError(_tr('下载下来的工厂启动失败，请看日志'))
    log.info(_tr('服务器工厂 %s 已下载到本机 %s（PLC 程序 %s 个）'), pid, lid, copied)
    return {'id': lid, 'name': rt.plant.name, 'plc_programs': copied, 'from': pid}


# ---------------------------------------------------------------- ASGI 小工具
def _headers(scope):
    return {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers') or []}


async def _read_body(receive):
    out = b''
    while True:
        m = await receive()
        if m['type'] == 'http.disconnect':
            break
        out += m.get('body', b'')
        if not m.get('more_body'):
            break
    return out


def _replay(body):
    done = False

    async def receive():
        nonlocal done
        if done:
            await asyncio.sleep(3600)
            return {'type': 'http.disconnect'}
        done = True
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return receive


async def _inner(app, scope, body):
    """在本机应用里跑一个请求，拿回 (状态码, 头, 正文)。"""
    out = {'status': 500, 'headers': [], 'body': b''}

    async def send(m):
        if m['type'] == 'http.response.start':
            out['status'], out['headers'] = m['status'], m.get('headers') or []
        elif m['type'] == 'http.response.body':
            out['body'] += m.get('body', b'')
    await app(scope, _replay(body), send)
    return out['status'], out['headers'], out['body']
