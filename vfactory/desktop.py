"""桌面模式：Windows 客户端的本地服务（设计 4.2 第 2 节、4.3 第 4 节）。

    python -m vfactory desktop [--port 0] [--home DIR] [--protocols] [--server URL] [--watch-pid PID]

两种用法（desktop.json 的 mode）：
- 联网（mode=server）：用服务器账号登录（账号就是网页端"用户与角色"里的，权限按角色）。窗口里和网页端一样：服务器上的工厂经本地服务
  转发到服务器（见 vfactory/desktop_proxy.py），本机工厂（"下载到本机"或"本机新建"）在本地服务里跑。登录记住 7 天，期间断网也能打开
  本机工厂和装到本机的课，离线交的作业进待交队列，联网后自动交。
- 单机（mode=standalone）：登录页"不连服务器，单机使用"，本机管理员账号 local，全部功能都在本机。
第一次打开（mode 为空）：登录页。服务器地址可以由安装包预置：程序目录（或它的上一级）里的 server.json {"server": "http://…"}，或 --server。

- 只监听 127.0.0.1；--port 0 时先试上次用过的端口（网页的本地存储按"地址+端口"区分，端口不变登录和布局才留得住）。
- 数据都在 --home（= VF_HOME）下：data/、plants/、config/、logs/、desktop.json（设置）、account.json（登录，服务器令牌用 DPAPI 加密）、run.json。
- run.json：{port, pid, token, key, …}。token 是一次性的：网页用它换会话（POST /api/desktop/session）——单机模式直接给本机管理员会话，
  联网模式只在记住的登录还有效时给，否则网页去登录页；key 只给启动器用（再开窗口换新令牌、关窗后让服务退出）。
- 协议服务（OPC UA / Modbus / MQTT，本机工厂用）默认关闭；设置里打开（或 --protocols）。
- 本机 MES（蜂元教学 MES，本仓库 vfmes/，4.6）：/mes 页面给一个本机工厂按需启动，只这一个工厂打开协议，页面取数经 /api/mes/* 转发（vfactory/mes/sidecar.py）；服务器上没有。
"""
from .i18n import _tr, label
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import sys
import time
import urllib.parse

from fastapi import Body, HTTPException, Request

from . import __version__, paths, store

log = logging.getLogger('vfactory.desktop')
LOCAL_USER = 'local'
LOCAL_ROLE = 'admin'          # 单机模式的本机管理员
REMEMBER_S = 7 * 86400        # 登录记住 7 天（和服务器会话有效期一样）
DEFAULTS = {'mode': None, 'server': '', 'username': '', 'protocols': False, 'quality': 'low', 'port': None}
LOOPBACK = ('127.0.0.1', '::1', 'localhost')


def settings_path():
    return paths.home('desktop.json')


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(settings_path(), encoding='utf-8') as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def _write_json(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)


def save_settings(s):
    _write_json(settings_path(), {k: s.get(k) for k in DEFAULTS})


def preset_server():
    """安装包预置的服务器地址：server.json（在 app\\ 或它的上一级，即安装目录）。"""
    for p in (paths.app('server.json'), os.path.join(os.path.dirname(paths.APP), 'server.json')):
        try:
            with open(p, encoding='utf-8-sig') as f:
                v = (json.load(f) or {}).get('server')
                if v:
                    return norm_url(v)
        except (OSError, ValueError, HTTPException):
            continue
    return ''


CLOUD_PLACEHOLDER = 'https://vf-cloud.invalid'   # 蜂元云的地址还没定：占位（.invalid 永远解析不到）。用 VF_CLOUD_URL 配置


def cloud_url():
    """5.0 客户端登录页默认的服务器 = 蜂元云。配置（先到先用）：环境变量 VF_CLOUD_URL → 安装目录 server.json 的 "cloud"
    → <数据目录>/config/client.json 的 "VF_CLOUD_URL" → 占位地址。"""
    v = os.environ.get('VF_CLOUD_URL')
    if not v:
        for p in (paths.app('server.json'), os.path.join(os.path.dirname(paths.APP), 'server.json')):
            try:
                with open(p, encoding='utf-8-sig') as f:
                    v = (json.load(f) or {}).get('cloud')
                if v:
                    break
            except (OSError, ValueError):
                continue
    if not v:
        try:
            with open(os.path.join(paths.CONFIG, 'client.json'), encoding='utf-8-sig') as f:
                v = (json.load(f) or {}).get('VF_CLOUD_URL')
        except (OSError, ValueError):
            v = None
    try:
        return norm_url(v) if v else CLOUD_PLACEHOLDER
    except HTTPException:
        return CLOUD_PLACEHOLDER


def norm_url(u):
    u = (u or '').strip().rstrip('/')
    if u and not u.startswith(('http://', 'https://')):
        u = 'http://' + u
    p = urllib.parse.urlparse(u)
    if p.scheme not in ('http', 'https') or not p.netloc:
        raise HTTPException(400, _tr('服务器地址不对，例如 http://192.168.1.10:8800'))
    return f'{p.scheme}://{p.netloc}{p.path.rstrip("/")}'


# ---------------------------------------------------------------- 服务器令牌加密（Windows DPAPI，只有本机这个 Windows 账号能解）
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):     # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError(_tr('DPAPI 失败'))
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def seal(s):
    if not s:
        return ''
    if os.name == 'nt':
        return 'dpapi:' + base64.b64encode(_dpapi(s.encode(), True)).decode()
    return 'b64:' + base64.b64encode(s.encode()).decode()


def unseal(s):
    try:
        if s.startswith('dpapi:'):
            return _dpapi(base64.b64decode(s[6:]), False).decode()
        if s.startswith('b64:'):
            return base64.b64decode(s[4:]).decode()
    except Exception:
        log.warning(_tr('服务器令牌解不开（换了 Windows 账号？），需要重新登录'))
    return ''


def _verifier(server, username, pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac('sha256', f'{server}\n{username}\n{pw}'.encode(), salt.encode(), 120000).hex()
    return f'{salt}${h}'


def free_port(prefer=None):
    """先试 prefer（上次的端口），不行就让系统给一个空闲端口。"""
    for p in ([prefer] if prefer else []) + [0]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', int(p)))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError(_tr('没有空闲端口'))


def ensure_local_user():
    """单机模式的本机管理员；同时停用默认演示账号（初始密码人人知道）。"""
    if store.q('select 1 from users where username=?', (LOCAL_USER,), one=True):
        store.x('update users set active=1, role=? where username=?', (LOCAL_ROLE, LOCAL_USER))
        return
    store.x('insert into users(username,name,role,pw,created) values(?,?,?,?,?)',
            (LOCAL_USER, _tr('本机用户'), LOCAL_ROLE, store.hash_pw(secrets.token_hex(16)), store.now()))
    store.x("update users set active=0 where username in ('admin','engineer','guest')")


def mirror_user(username, name, role):
    """服务器账号在本机的影子：本机的权限检查（角色、教学范围）照服务器的角色来。本机密码随机，不能用来登录。"""
    if role not in store.ROLES:
        role = 'viewer'
    if store.q('select 1 from users where username=?', (username,), one=True):
        store.x('update users set name=?, role=?, active=1 where username=?', (name, role, username))
    else:
        store.x('insert into users(username,name,role,pw,created) values(?,?,?,?,?)',
                (username, name, role, store.hash_pw(secrets.token_hex(16)), store.now()))


def _pid_alive(pid):
    if not pid:
        return True
    if os.name == 'nt':
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000 | 0x1000, False, int(pid))     # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102                # WAIT_TIMEOUT = 还在运行
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


RECENT_MAX = 10


class Desktop:
    OPEN = {'/api/desktop/session', '/api/desktop/ticket', '/api/desktop/shutdown', '/api/desktop/login', '/api/desktop/standalone',
            '/api/desktop/login_info', '/api/desktop/native'}

    def __init__(self, args):
        from .desktop_proxy import Outbox
        self.args = args
        self.settings = load_settings()
        if args.protocols:
            self.settings['protocols'] = True
        if getattr(args, 'server', None):
            self.settings['server'] = norm_url(args.server)
        self.account = self._load_account()
        self.tickets: dict[str, float] = {}       # 一次性令牌 → 过期时间
        self.key = secrets.token_urlsafe(24)       # 启动器专用
        self.token = self.ticket()
        self.server = None
        self.mgr = None
        self.app = None
        self.online = None                         # None = 还没试过
        self.offline_why = ''
        self.outbox = Outbox(self)
        self.started = time.strftime('%Y-%m-%d %H:%M:%S')
        self.events: list[dict] = []               # 给外壳（Electron）发系统通知用：作业已提交 / 已排队 / 已自动补交
        self.seq = 0
        from .mes.sidecar import MesSidecar
        self.mes = MesSidecar(self)                # 本机 MES（蜂元教学 MES）
        from .tenancy.progress_client import Reporter
        self.progress = Reporter(self)             # 5.0 学校作业的进度上报（定时 + 事件，离线排队补报）

    # ---------- 外壳（Electron）用：系统通知事件、最近打开的工厂 ----------
    def event(self, kind, title='', **kw):
        """kind：submitted（联网直接交上）/ queued（连不上，进待交队列）/ resent（联网后自动补交）。外壳轮询 /api/desktop/native 取走。"""
        self.seq += 1
        self.events = (self.events + [{'seq': self.seq, 'kind': kind, 'title': title or _tr('作业'), 'at': store.now(), **kw}])[-50:]

    def assignment_title(self, laid):
        try:
            from .teach import db as tdb
            ln = tdb.q('select remote_title from client_links where local_aid=?', (int(laid or 0),), one=True)
            return (ln or {}).get('remote_title') or ''
        except Exception:
            return ''

    def recent(self):
        try:
            with open(paths.home('recent.json'), encoding='utf-8') as f:
                r = json.load(f)
            return [x for x in r if isinstance(x, dict) and x.get('pid')][:RECENT_MAX] if isinstance(r, list) else []
        except (OSError, ValueError):
            return []

    def add_recent(self, pid, name='', user=''):
        """网页进入某个工厂时记一笔（托盘"最近的工厂"、任务栏跳转列表用）。学生的作业沙箱（sb-…）不记。"""
        pid = str(pid or '').strip()
        if not pid or pid.startswith('sb-') or len(pid) > 120:
            return self.recent()
        r = [x for x in self.recent() if x.get('pid') != pid]
        r.insert(0, {'pid': pid, 'name': str(name or pid)[:60], 'local': self.settings.get('mode') == 'standalone' or self.is_local(pid),
                     'user': user, 'at': store.now()})
        _write_json(paths.home('recent.json'), r[:RECENT_MAX])
        return r[:RECENT_MAX]

    # ---------- 登录状态 ----------
    def _load_account(self):
        try:
            with open(paths.home('account.json'), encoding='utf-8') as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def _save_account(self):
        _write_json(paths.home('account.json'), self.account)

    def connected(self):
        """联网模式且记住的登录还有效（服务器令牌在、7 天内登录过）。"""
        a = self.account
        return (self.settings.get('mode') == 'server' and bool(a.get('token')) and a.get('server') == self.settings.get('server')
                and time.time() - float(a.get('login_at') or 0) < REMEMBER_S)

    def server_url(self):
        return self.account.get('server') or self.settings.get('server') or ''

    def server_token(self):
        return unseal(self.account.get('token') or '')

    def set_online(self, on, why=''):
        was = self.online
        self.online, self.offline_why = bool(on), ('' if on else why)
        if on and was is False:
            log.info(_tr('服务器又连上了'))
            if self.mgr and self.outbox.items():
                asyncio.get_event_loop().create_task(self.outbox.flush())
        elif not on and was is not False:
            log.info(_tr('服务器连不上：%s'), why)

    def server_expired(self):
        """服务器说令牌无效：清掉令牌（保留地址和账号名给登录页预填）。"""
        log.info(_tr('服务器令牌失效，需要重新登录'))
        self.account.pop('token', None)
        self._save_account()
        self._sync_school(None)

    def is_local(self, pid):
        """这个工厂/沙箱在本机（本机工厂、本机课的沙箱、作业包复核沙箱）。"""
        from .server import SANDBOXES
        m = self.mgr
        if not pid or (m and (pid in m.rts or pid in m.sandboxes)):
            return bool(pid)
        safe = os.path.basename(pid)
        return os.path.exists(os.path.join(paths.PLANTS, f'{safe}.yaml')) or os.path.exists(os.path.join(SANDBOXES, f'{safe}.yaml'))

    def _sync_school(self, token):
        """教学模块（vfactory/teach/client.py）用的学校服务器设置：就是登录的这个服务器和账号，不用再单独登录。"""
        try:
            from .teach import client as tclient
            s = tclient.load_settings()
            if token:
                a = self.account
                s.update(url=a['server'], username=a['username'], name=a.get('name') or a['username'], token=token, at=store.now(),
                         deploy=a.get('deploy') or 'selfhost')      # 5.0：saas 时 AI 助教在本机答（大模型经服务器代理）
            else:
                s.pop('token', None)
            tclient.save_settings(s)
        except Exception:
            log.exception(_tr('学校服务器设置没同步上'))

    def session_for(self, username, hours=24 * 7):
        return store.make_session(username, hours=hours)

    def resume(self):
        """一次性令牌换会话时：单机 → 本机管理员；联网且登录还有效 → 那个账号；否则 None（去登录页）。"""
        mode = self.settings.get('mode')
        if mode == 'standalone':
            ensure_local_user()
            return LOCAL_USER
        if mode == 'server' and self.connected():
            a = self.account
            mirror_user(a['username'], a.get('name') or a['username'], a.get('role') or 'viewer')
            return a['username']
        return None

    # ---------- 一次性令牌 ----------
    def ticket(self, ttl=600):
        t = secrets.token_urlsafe(24)
        now = time.time()
        self.tickets = {k: v for k, v in self.tickets.items() if v > now}
        self.tickets[t] = now + ttl
        return t

    def take(self, t):
        exp = self.tickets.pop(str(t or ''), 0)
        return exp > time.time()

    def health(self):
        a = self.account
        mode = self.settings.get('mode')
        if mode == 'server' and not self.connected():
            mode = None                            # 登录过期：前端当作没登录
        return {'mode': mode, 'server': self.server_url() if self.settings.get('mode') == 'server' else '',
                'online': self.online if self.settings.get('mode') == 'server' else None,
                'account': {'username': a.get('username'), 'name': a.get('name'), 'role': a.get('role')} if self.connected() else None,
                'server_deploy': (a.get('deploy') or 'selfhost') if self.connected() else None,      # 5.0：saas = 工厂只在本机跑
                'org_name': a.get('org') if self.connected() else None,
                'protocols': bool(self.mgr and self.mgr.protocols), 'quality': self.settings.get('quality'),
                'mes': {'state': self.mes.state, 'pid': self.mes.pid, 'plant_name': self.mes.plant_name}}

    def info(self):
        a = self.args
        ob = self.outbox.items()
        return {**self.health(), 'version': __version__, 'home': paths.HOME, 'data': paths.DATA, 'app': paths.APP, 'port': a.http,
                'ports': {'opcua': a.opcua, 'modbus': a.modbus, 'mqtt': None if a.no_mqtt else a.mqtt}, 'started': self.started,
                'plants': len(self.mgr.rts) if self.mgr else 0, 'offline_why': self.offline_why,
                'login_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(self.account['login_at'])) if self.account.get('login_at') else None,
                'outbox': [{k: x.get(k) for k in ('id', 'title', 'remote_aid', 'queued', 'state', 'msg', 'sent')} for x in ob]}

    # ---------- 接口 ----------
    def register(self, app):
        d = self
        d.app = app
        d.mes.register(app)

        def local_only(request: Request):
            if (request.client.host if request.client else '') not in LOOPBACK:
                raise HTTPException(403, _tr('只允许本机访问'))

        def launcher_only(request: Request):
            local_only(request)
            if not secrets.compare_digest(request.headers.get('x-vf-key', ''), d.key):
                raise HTTPException(403, _tr('只有启动器能调用'))

        def done_login(username, extra=None):
            store.x('update users set last_login=? where username=?', (store.now(), username))
            return {'token': d.session_for(username), 'user': username, **d.health(), **(extra or {})}

        @app.post('/api/desktop/session')
        async def session(request: Request, body: dict = Body(...)):
            """网页打开时用启动器给的一次性令牌换会话：单机模式、或联网模式记住的登录还有效时给会话；否则 need_login。"""
            local_only(request)
            if not d.take(body.get('token')):
                raise HTTPException(401, _tr('本机令牌无效或已用过：请关闭窗口，重新打开蜂元虚拟工厂'))
            who = d.resume()
            if not who:
                return {'need_login': True, **(await login_info())}
            return done_login(who)

        @app.get('/api/desktop/login_info')
        async def login_info():
            """登录页：预置/上次的服务器地址、上次的账号。"""
            pre = preset_server()
            cloud = cloud_url()
            # 5.0：默认连蜂元云；装机时预置了学校服务器（server.json）或上次用过别的服务器，就预填那个
            return {'server': d.settings.get('server') or pre or cloud, 'preset': pre, 'cloud': cloud,
                    'cloud_ready': cloud != CLOUD_PLACEHOLDER, 'username': d.settings.get('username') or d.account.get('username') or '',
                    'mode': d.settings.get('mode'), 'version': __version__}

        @app.post('/api/desktop/login')
        async def login(request: Request, body: dict = Body(...)):
            """用服务器账号登录。连不上服务器时：同一服务器、同一账号、7 天内在这台电脑上登录过，并且密码对 → 离线登录。"""
            local_only(request)
            from .desktop_proxy import Offline, acall, jbody
            url = norm_url(body.get('server') or d.settings.get('server') or preset_server())
            user, pw = (body.get('username') or '').strip(), body.get('password') or ''
            if not user or not pw:
                raise HTTPException(400, _tr('请填写账号和密码'))
            try:
                code, _, b = await acall('POST', url + '/api/login', body={'username': user, 'password': pw, 'client': 'desktop'}, timeout=15)
            except Offline as e:
                a = d.account
                known = (a.get('server') == url and a.get('username') == user and a.get('token') and a.get('verifier')
                         and time.time() - float(a.get('login_at') or 0) < REMEMBER_S)
                if not known:
                    raise HTTPException(502, _tr('连不上服务器 {url}（{e}）。在这台电脑上 7 天内用这个账号登录过才能离线登录；也可以选"不连服务器，单机使用"。', url=url, e=e))
                if not hmac.compare_digest(_verifier(url, user, pw, a['verifier'].split('$')[0]), a['verifier']):
                    raise HTTPException(400, _tr('密码不对（现在连不上服务器，用的是这台电脑记住的登录来核对）'))
                d.settings.update(mode='server', server=url, username=user)
                save_settings(d.settings)
                d.set_online(False, str(e))
                mirror_user(user, a.get('name') or user, a.get('role') or 'viewer')
                return done_login(user, {'offline': True})
            if code in (400, 401, 403, 423, 429):                  # 423 连续输错被锁、429 限流（5.0）：服务器的中文说明原样给
                raise HTTPException(400, jbody(b).get('detail') or _tr('账号或密码不对'))
            if code != 200 or not jbody(b).get('token'):
                raise HTTPException(502, _tr('服务器登录失败（{v}）：确认地址是蜂元虚拟工厂服务器', v=jbody(b).get('detail') or code))
            tok = jbody(b)['token']
            code, _, mb = await acall('GET', url + '/api/me', token=tok, timeout=15)
            me = jbody(mb) if code == 200 else {}
            name, role = me.get('name') or user, me.get('role') or 'viewer'
            d.account = {'server': url, 'username': user, 'name': name, 'role': role, 'token': seal(tok), 'verifier': _verifier(url, user, pw),
                         'login_at': time.time(), 'deploy': me.get('deploy') or 'selfhost', 'org': (me.get('org') or {}).get('name')}
            d._save_account()
            d.settings.update(mode='server', server=url, username=user)
            save_settings(d.settings)
            d.set_online(True)
            mirror_user(user, name, role)
            d._sync_school(tok)
            log.info(_tr('已登录服务器 %s：%s（%s）'), url, user, role)
            if d.outbox.items():
                asyncio.get_running_loop().create_task(d.outbox.flush())
            try:                                                    # 5.0：管理员发的临时密码（随机的）也要先改
                tc, _, tb = await acall('GET', url + '/api/teach/me', token=tok, timeout=15)
                must = bool(jbody(tb).get('must_change_password')) if tc == 200 else False
            except Offline:
                must = False
            return done_login(user, {'must_change_pw': pw in ('honey123', '123456', 'teach123') or must})

        @app.post('/api/desktop/standalone')
        async def standalone(request: Request):
            """登录页"不连服务器，单机使用"：本机管理员，全部功能在本机；第一次用时放一个完整示范工厂。"""
            local_only(request)
            d.settings['mode'] = 'standalone'
            save_settings(d.settings)
            ensure_local_user()
            has = bool(d.mgr.rts) or (os.path.isdir(paths.PLANTS) and any(f.endswith('.yaml') for f in os.listdir(paths.PLANTS)))
            if not has:
                try:
                    from .server import TEMPLATE_NAMES
                    await d.mgr.create(label(TEMPLATE_NAMES['showcase']), 'showcase', want_id='foundry-housing')
                except HTTPException:
                    log.exception(_tr('示范工厂没建成'))
            return done_login(LOCAL_USER)

        @app.post('/api/desktop/logout')
        async def logout(request: Request):
            """退出登录（联网模式忘掉服务器令牌；单机模式回到登录页）。本机工厂和数据不动。"""
            if d.settings.get('mode') == 'server':
                tok = d.server_token()
                if tok:                                             # 5.0：服务器上的会话也吊销（连不上就算了，会话到期自己失效）
                    from .desktop_proxy import Offline, acall
                    try:
                        await acall('POST', d.server_url() + '/api/me/logout', body={}, token=tok, timeout=5)
                    except Offline:
                        pass
                d.account.pop('token', None)
                d._save_account()
                d._sync_school(None)
            d.settings['mode'] = None
            save_settings(d.settings)
            return {'ok': True}

        @app.post('/api/desktop/ticket')
        async def ticket(request: Request):
            """启动器再开一个窗口（第二次双击、双击作业包）时换一个新的一次性令牌。"""
            launcher_only(request)
            return {'token': d.ticket()}

        @app.post('/api/desktop/shutdown')
        async def shutdown(request: Request):
            """启动器：窗口都关了，退出本地服务。"""
            launcher_only(request)
            log.info(_tr('启动器要求退出'))
            if d.server:
                d.server.should_exit = True
            return {'ok': True}

        @app.get('/api/desktop/settings')
        async def get_settings():
            return d.info()

        @app.put('/api/desktop/settings')
        async def put_settings(body: dict = Body(...)):
            """设置：protocols（本机工厂的协议服务开/关，立即生效，本机工厂会重建）、quality（三维质量 low/high）。"""
            s = d.settings
            if 'quality' in body:
                if body['quality'] not in ('low', 'high'):
                    raise HTTPException(400, _tr('三维质量只能是 low 或 high'))
                s['quality'] = body['quality']
            err = None
            if 'protocols' in body:
                try:
                    await d.mgr.set_protocols(bool(body['protocols']))
                except RuntimeError as e:
                    err = str(e)
                s['protocols'] = d.mgr.protocols
            save_settings(s)
            if err:
                raise HTTPException(400, err + _tr('（可能端口被别的程序占用了）'))
            return d.info()

        @app.post('/api/desktop/plants/download')
        async def download(request: Request, body: dict = Body(...)):
            """把服务器上的工厂（模型 + PLC 程序）复制到本机，作为本机工厂运行。"""
            u = request.state.user
            if not store.role_ok(u, 'engineer') or u.get('role') in ('student', 'teacher'):
                raise HTTPException(403, _tr('当前账号不能下载工厂（需要工程师或管理员）'))
            if not d.connected():
                raise HTTPException(400, _tr('先登录服务器'))
            from .desktop_proxy import download_plant
            try:
                return await download_plant(d, str(body.get('pid') or ''), body.get('name'))
            except RuntimeError as e:
                raise HTTPException(400, str(e))

        @app.get('/api/desktop/where/{pid}')
        async def where(pid: str):
            """这个工厂/沙箱在本机还是服务器（工作台顶上的"本机/服务器"标记）。"""
            return {'pid': pid, 'local': d.settings.get('mode') == 'standalone' or d.is_local(pid)}

        @app.post('/api/desktop/outbox/flush')
        async def outbox_flush():
            """待交作业：现在就试着交。"""
            n = await d.outbox.flush()
            return {'sent': n, **d.info()}

        @app.post('/api/desktop/open_folder')
        async def open_folder(body: dict = Body({})):
            """在资源管理器里打开数据目录（或日志目录）。"""
            target = paths.LOGS if body.get('which') == 'logs' else paths.HOME
            os.makedirs(target, exist_ok=True)
            if os.name == 'nt':
                os.startfile(target)            # noqa: S606 —— 本机、固定目录
            return {'ok': True, 'path': target}

        @app.get('/api/desktop/recent')
        async def get_recent(request: Request):
            u = request.state.user
            return {'recent': [x for x in d.recent() if x.get('user') in ('', None, u['username'])]}

        @app.post('/api/desktop/recent')
        async def post_recent(request: Request, body: dict = Body(...)):
            """网页打开了某个工厂（工作台等 /p/<编号>/… 页面）：记进"最近的工厂"。"""
            u = request.state.user
            d.add_recent(body.get('pid'), body.get('name'), u['username'])
            return {'ok': True}

        @app.get('/api/desktop/native')
        async def native(request: Request, since: int = 0):
            """外壳（Electron 主进程）轮询：托盘菜单（最近的工厂、待交作业数）、系统通知事件、更新地址。只认启动器的 key。"""
            launcher_only(request)
            ob = d.outbox.items()
            who = d.account.get('username') if d.connected() else (LOCAL_USER if d.settings.get('mode') == 'standalone' else None)
            h = d.health()
            srv = h['server'] if h['mode'] == 'server' else ''
            return {**h, 'version': __version__, 'home': paths.HOME, 'logs': paths.LOGS, 'user': who,
                    'recent': [x for x in d.recent() if who and x.get('user') in ('', None, who)],
                    'outbox': {'waiting': sum(1 for x in ob if x.get('state') == 'waiting'), 'failed': sum(1 for x in ob if x.get('state') == 'failed'),
                               'sent': sum(1 for x in ob if x.get('state') == 'sent'), 'total': len(ob)},
                    'update_url': (srv + '/api/client/update/') if srv else '',
                    'events': [e for e in d.events if e['seq'] > since], 'seq': d.seq}

    async def monitor(self):
        """联网模式：每 20 秒看一下服务器在不在；连上时把待交作业交了。"""
        from .desktop_proxy import Offline, acall
        while True:
            if self.connected():
                try:
                    code, _, _ = await acall('GET', self.server_url() + '/api/health', timeout=5)
                    self.set_online(code == 200, f'HTTP {code}')
                    if code == 200 and any(x['state'] == 'waiting' for x in self.outbox.items()):
                        await self.outbox.flush()
                except Offline as e:
                    self.set_online(False, str(e))
                except Exception:
                    log.exception(_tr('服务器状态检查出错'))
            await asyncio.sleep(20)

    # ---------- 运行信息 ----------
    def run_file(self):
        return paths.home('run.json')

    def write_run(self):
        a = self.args
        info = {'port': a.http, 'pid': os.getpid(), 'token': self.token, 'key': self.key, 'version': __version__, 'started': self.started,
                'home': paths.HOME, 'url': f'http://127.0.0.1:{a.http}/', 'mode': self.settings.get('mode')}
        _write_json(self.run_file(), info)

    def clear_run(self):
        try:
            with open(self.run_file(), encoding='utf-8') as f:
                if json.load(f).get('pid') != os.getpid():
                    return
            os.remove(self.run_file())
        except (OSError, ValueError):
            pass


def _setup_logging():
    os.makedirs(paths.LOGS, exist_ok=True)
    logf = os.path.join(paths.LOGS, 'vfactory.log')
    try:                                          # 只留最近一次和上一次
        if os.path.exists(logf) and os.path.getsize(logf) > 0:
            os.replace(logf, logf + '.1')
    except OSError:
        pass
    handlers = [logging.FileHandler(logf, encoding='utf-8')]
    if sys.stdout is None or sys.stderr is None:  # pythonw.exe：没有控制台，print 和未捕获的异常也进日志文件
        fh = open(logf, 'a', encoding='utf-8', buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or fh
        sys.stderr = sys.stderr or fh
    else:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s', handlers=handlers)
    for noisy in ('asyncua', 'amqtt', 'pymodbus', 'transitions'):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run(args):
    """python -m vfactory desktop 的主体（参数见 __main__.py）。"""
    import uvicorn

    from .desktop_proxy import Proxy
    from .server import Manager, build_app
    os.makedirs(paths.HOME, exist_ok=True)
    _setup_logging()
    d = Desktop(args)
    args.http = free_port(args.port or d.settings.get('port'))
    d.settings['port'] = args.http
    if not d.settings.get('server'):
        d.settings['server'] = preset_server()
    save_settings(d.settings)
    mgr = Manager(args)
    mgr.desktop, d.mgr = d, mgr
    mgr.protocols = bool(d.settings.get('protocols'))
    mgr.seed_showcase = False                     # 单机模式第一次选择时才放示范工厂；联网模式首页是服务器的工厂
    app = build_app(mgr)
    log.info(_tr('桌面模式 %s：数据目录 %s，%s，协议服务 %s'), __version__, paths.HOME,
             {'server': _tr('联网 {server_url}', server_url=d.server_url()), 'standalone': _tr('单机')}.get(d.settings.get('mode'), _tr('未登录')), _tr('开') if mgr.protocols else _tr('关'))

    async def main():
        await mgr.start()
        server = d.server = uvicorn.Server(uvicorn.Config(Proxy(app, d), host='127.0.0.1', port=args.http, log_level='warning', log_config=None,
                                                          ws_max_size=64 * 1024 * 1024))
        task = asyncio.create_task(server.serve())
        while not server.started and not task.done():
            await asyncio.sleep(0.05)
        if task.done():
            await task
            return
        d.write_run()
        log.info(_tr('本地服务 http://127.0.0.1:%s/ 已就绪'), args.http)

        async def watch():                        # 启动器没了（被结束、崩溃）：服务跟着退出，不留孤儿进程
            while not server.should_exit:
                await asyncio.sleep(2)
                if args.watch_pid and not _pid_alive(args.watch_pid):
                    log.info(_tr('启动器进程 %s 已退出，本地服务退出'), args.watch_pid)
                    server.should_exit = True
        w = asyncio.create_task(watch())
        mon = asyncio.create_task(d.monitor())
        rep = asyncio.create_task(d.progress.loop())  # 5.0 进度上报
        try:
            await task
        finally:
            w.cancel()
            mon.cancel()
            rep.cancel()
            d.mes.kill_now()                      # 本机 MES 跟着退出
        # 直接结束进程：不等仿真循环、线程池、评分进程池慢慢收尾（数据库每次写入都已提交，工厂文件在保存时就写好了）。
        d.clear_run()
        log.info(_tr('本地服务已退出'))
        logging.shutdown()
        os._exit(0)

    try:
        asyncio.run(main())
    finally:
        d.mes.kill_now()
        d.clear_run()
        log.info(_tr('本地服务已退出'))
