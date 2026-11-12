"""本机 MES 边车：客户端（桌面模式）里按需启动"蜂元教学 MES"（本仓库的 vfmes 包），只给本机工厂用（本机工厂、"我的工厂"、本机课的沙箱）。

为什么在本机：MES 一个工厂一个进程、一个数据库，放在学校服务器上给每个学生起一套太耗资源；教学用也不接真实工厂。

流程（POST /api/desktop/mes/start {pid}）：
  1. 只认本机工厂；同一时间只跑一个 MES（换工厂时先停掉上一个）。
  2. 给这个工厂打开协议（Manager.enable_proto：总开关不动，只这一个工厂挂 OPC UA / Modbus / MQTT，端口被占就换空闲端口）。
  3. 起 MES 子进程：同一个 Python（安装包里的精简运行时）跑 vfmes，监听 127.0.0.1 的空闲端口，数据在 <数据目录>\\mes\\<工厂>\\，
     数据源指向这个工厂的 MQTT，第一次启动自动"从虚拟工厂导入"设备和点表（用当前账号的本机会话令牌读工厂接口）。
  4. 5.0.1 起 MES 的页面就在虚拟工厂自己的网页里（web/src/mes/，路径 /mes/...），不再内嵌 MES 的网页。
     网页只和本地服务说话：/api/mes/<路径> 由这里转发到 MES 的 /api/<路径>（register 里的 mes_proxy）。
     MES 的钥匙（x-hm-key）和本机学员的会话令牌只在本地服务里：钥匙 → 一次性登录票 → /api/edu/session 换会话令牌，
     转发时带 Authorization: Bearer <令牌>（401 就重新换一次）。网页拿不到钥匙和令牌。
停止：点"停止"、工厂被删掉/关掉、空闲太久（默认 30 分钟：MES 里没有操作、MES 页面也没开着）、本地服务退出（MES 还会盯着本地服务的进程号自己退出）。
<数据目录>\\mes\\current.json 记着正在运行的 MES（端口、钥匙），评分进程（teach_rules.py）从这里找 MES 取数。
"""
from ..i18n import _tr
import asyncio
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from .. import paths, store

log = logging.getLogger('vfactory.mes')
IDLE_MIN = 30                       # 默认空闲多少分钟自动停止（设置里 mes_idle_min 可改，0 = 不自动停）
START_TIMEOUT = 90
MES_KINDS = {'furnace', 'treatment', 'sand', 'molding', 'cooling', 'shotblast', 'cnc', 'deburr', 'inspection', 'warehouse', 'receiving'}
# 子进程入口：把虚拟工厂目录（vfmes 包所在）放在 sys.path 最前面（精简运行时的 ._pth 不认 PYTHONPATH），
# 并去掉别处带 vfmes / honeymes 包的目录（开发机的 ._pth 里可能有旧的 HoneyMES 仓库），保证用的是这一份
BOOT = ("import os, sys; r = os.path.abspath(sys.argv[1]); "
        "sys.path = [r] + [p for p in sys.path if p and os.path.normcase(os.path.abspath(p)) != os.path.normcase(r) "
        "and not any(os.path.isfile(os.path.join(p, k, '__init__.py')) for k in ('vfmes', 'honeymes'))]; "
        "from vfmes.__main__ import main; main(sys.argv[2:])")


def mes_source():
    """蜂元教学 MES 的位置：虚拟工厂目录本身（开发时是仓库根目录，安装包里是 resources\\vf）。要有 vfmes 包（安装包里默认带上，-NoMes 时不带）。
    5.0.1 起 MES 的页面在虚拟工厂自己的网页里（web/src/mes/），不再需要 web-mes\\dist。缺了返回 ''。"""
    ok = os.path.isfile(os.path.join(paths.APP, 'vfmes', '__main__.py'))
    return os.path.abspath(paths.APP) if ok else ''


# 转发 /api/mes/<路径> 时：网页的这些查询参数是给本地服务的（下载链接的令牌、联网模式的工厂上下文），不转给 MES
_DROP_QS = {'token', 'vfp'}
_PASS_HEADERS = ('content-type', 'content-disposition', 'cache-control')


def _raw(method, url, headers, body, timeout):
    """→ (状态码, 头字典(小写键), 字节)。HTTP 错误也照样返回；连不上抛 URLError/OSError。"""
    req = urllib.request.Request(url, method=method, data=body if body else (b'' if method in ('POST', 'PUT', 'PATCH') else None), headers=headers)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}, e.read()


def _safe(pid):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', pid)[:80] or 'plant'


def mes_dir(*p):
    return paths.home('mes', *p)


def current_file():
    return mes_dir('current.json')


def read_current():
    try:
        with open(current_file(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _http(method, url, key='', body=None, timeout=5):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, method=method, data=data, headers={'Content-Type': 'application/json', **({'x-hm-key': key} if key else {})})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return json.loads(r.read() or b'null')


class MesSidecar:
    def __init__(self, desktop):
        self.d = desktop
        self.proc: subprocess.Popen | None = None
        self.state = 'stopped'          # stopped / starting / running / error
        self.pid = ''                   # 工厂编号
        self.plant_name = ''
        self.port = 0
        self.key = ''
        self.token = ''                 # 本机学员在 MES 里的会话令牌（只在本地服务里，转发 /api/mes/* 时用）
        self.error = ''
        self.stopped_why = ''
        self.started = 0.0
        self.last_ping = 0.0
        self.remote = {}                # MES 的 /api/edu/status
        self.ports = {}
        self.lock = asyncio.Lock()
        self.task = None

    # ---------- 信息 ----------
    def idle_min(self):
        try:
            return float(self.d.settings.get('mes_idle_min', IDLE_MIN))
        except (TypeError, ValueError):
            return IDLE_MIN

    def local_plants(self, user):
        """可以开 MES 的本机工厂：本机运行的工厂（单机模式全部、联网模式"本机"的）+ 本机课的沙箱。fit = 设备类型 MES 都认识。"""
        m = self.d.mgr
        stu = (user or {}).get('role') in ('student', 'teacher')
        out = []
        for pid, rt in list(m.rts.items()) + list(m.sandboxes.items()):
            if stu and not (pid.startswith('local-') or pid.startswith('sb-')):
                continue
            try:
                kinds = [st.kind for st in rt.plant.stations.values()]
                name = rt.plant.name
            except Exception:                    # noqa: BLE001  还在启动
                kinds, name = [], pid
            n = sum(1 for k in kinds if k in MES_KINDS)
            out.append({'id': pid, 'name': name, 'sandbox': rt.sandbox, 'stations': len(kinds), 'mes_devices': n, 'fit': n >= 3,
                        'protocols': not rt.noproto, 'running': self.pid == pid and self.state in ('starting', 'running')})
        out.sort(key=lambda x: (not x['fit'], x['sandbox'], x['name']))
        return out

    def status(self):
        r = self.remote or {}
        idle = None
        if self.state == 'running':
            idle = min(float(r.get('idle_s') or 0), time.time() - (self.last_ping or self.started))
        return {'available': bool(mes_source()), 'state': self.state, 'pid': self.pid, 'plant_name': self.plant_name, 'port': self.port or None,
                'url': f'http://127.0.0.1:{self.port}/' if self.state == 'running' else '', 'error': self.error, 'stopped_why': self.stopped_why,
                'started': time.strftime('%H:%M:%S', time.localtime(self.started)) if self.started else '', 'uptime_s': round(time.time() - self.started) if self.state == 'running' else 0,
                'idle_s': round(idle) if idle is not None else None, 'idle_min': self.idle_min(), 'ports': self.ports,
                'counts': r.get('counts') or {}, 'import': r.get('import') or '', 'collector': r.get('collector') or {}, 'data_clock': r.get('data_clock') or '',
                'process': self.proc.pid if self.proc and self.proc.poll() is None else None, 'log': mes_dir('logs', 'mes.log'),
                'last_pid': self.d.settings.get('mes_last_pid') or ''}

    # ---------- 启动 / 停止 ----------
    async def start(self, pid, user):
        async with self.lock:
            m = self.d.mgr
            if pid not in m.rts and pid not in m.sandboxes:
                raise HTTPException(404, _tr('本机没有工厂 {pid}', pid=pid))
            if not self.d.is_local(pid):
                raise HTTPException(400, _tr('MES 只能给本机工厂用（服务器上的工厂先"下载到本机"）'))
            if self.state in ('running', 'starting') and self.pid == pid and self.proc and self.proc.poll() is None:
                return self.status()
            if self.state in ('running', 'starting'):
                await self._stop(_tr('换到另一个工厂'))
            src = mes_source()
            if not src:
                raise HTTPException(400, _tr('这个客户端没有带蜂元教学 MES（虚拟工厂目录里没有 vfmes 包：打包时用了 -NoMes）'))
            self.state, self.pid, self.error, self.stopped_why = 'starting', pid, '', ''
            rt = m.get(pid)
            self.plant_name = rt.plant.name
            try:
                self.ports = await m.enable_proto(pid)
                if not self.ports.get('mqtt'):
                    raise RuntimeError(_tr('这个工厂的 MQTT 没有开起来（看本地服务日志）'))
                await self._spawn(src, pid, user)
            except HTTPException:
                self.state = 'error'
                raise
            except Exception as e:                # noqa: BLE001
                log.exception(_tr('MES 没有启动起来'))
                self.state, self.error = 'error', str(e)
                self._kill()
                raise HTTPException(500, _tr('MES 没有启动起来：{e}', e=e))
            self.state, self.last_ping = 'running', time.time()
            if self.d.settings.get('mes_last_pid') != pid:          # 下次打开 MES 页面时默认给这个工厂启动
                self.d.settings['mes_last_pid'] = pid
                from ..desktop import save_settings
                save_settings(self.d.settings)
            log.info(_tr('本机 MES 已启动：工厂 %s，端口 %s，MQTT %s'), pid, self.port, self.ports.get('mqtt'))
            if not self.task or self.task.done():
                self.task = asyncio.create_task(self.monitor())
            return self.status()

    async def _spawn(self, src, pid, user):
        from ..desktop import free_port
        self.port, self.key, self.token = free_port(int(os.environ.get('VF_MES_PORT') or 0) or None), secrets.token_urlsafe(24), ''   # VF_MES_PORT：测试时固定端口
        data = mes_dir(_safe(pid))
        os.makedirs(os.path.join(mes_dir('logs')), exist_ok=True)
        os.makedirs(data, exist_ok=True)
        a = self.d.args
        env = {k: v for k, v in os.environ.items() if not k.startswith('HM_') and k not in ('PYTHONPATH', 'PYTHONHOME', 'MES_DB')}
        env.update({'HM_DATA': data, 'HM_EDU_KEY': self.key, 'HM_PLANT': pid, 'HM_PLANT_NAME': self.plant_name,
                    'HM_VF_HTTP': f'http://127.0.0.1:{a.http}/api/p/{urllib.parse.quote(pid)}',
                    'HM_VF_TOKEN': store.make_session(user['username'], hours=24 * 7), 'HM_MQTT': f"mqtt://127.0.0.1:{self.ports['mqtt']}",
                    'HM_USER_NAME': user.get('name') or user['username'], 'HM_WATCH_PID': str(os.getpid()),
                    'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONNOUSERSITE': '1'})
        logf = mes_dir('logs', 'mes.log')
        try:
            if os.path.exists(logf) and os.path.getsize(logf) > 2_000_000:
                os.replace(logf, logf + '.1')
        except OSError:
            pass
        py = sys.executable
        if os.path.basename(py).lower() == 'pythonw.exe' and os.path.exists(os.path.join(os.path.dirname(py), 'python.exe')):
            py = os.path.join(os.path.dirname(py), 'python.exe')     # 有输出重定向，用 python.exe 也不会弹窗（CREATE_NO_WINDOW）
        out = open(logf, 'a', encoding='utf-8')  # noqa: SIM115
        out.write(_tr('\n==== {strftime} 启动蜂元教学 MES：工厂 {pid}，端口 {port}，代码 {src}\n', strftime=time.strftime("%Y-%m-%d %H:%M:%S"), pid=pid, port=self.port, src=src))
        out.flush()
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.proc = subprocess.Popen([py, '-c', BOOT, src, 'serve', '--http', str(self.port)], cwd=src, env=env, stdout=out, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=flags)
        out.close()
        self.started = time.time()
        loop = asyncio.get_running_loop()
        t0 = time.time()
        while time.time() - t0 < START_TIMEOUT:
            if self.proc.poll() is not None:
                raise RuntimeError(_tr('MES 进程退出了（退出码 {returncode}），日志：{logf}\n', returncode=self.proc.returncode, logf=logf) + self._log_tail())
            try:
                self.remote = await loop.run_in_executor(None, lambda: _http('GET', f'http://127.0.0.1:{self.port}/api/edu/status', self.key, timeout=3))
                if self.remote.get('edu'):
                    break
                raise RuntimeError(_tr('端口上的不是蜂元教学 MES'))
            except (urllib.error.URLError, ConnectionError, OSError, ValueError):
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError(_tr('MES {START_TIMEOUT} 秒内没有就绪，日志：{logf}', START_TIMEOUT=START_TIMEOUT, logf=logf))
        os.makedirs(mes_dir(), exist_ok=True)
        tmp = current_file() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'pid': pid, 'name': self.plant_name, 'port': self.port, 'key': self.key, 'process': self.proc.pid, 'vf_pid': os.getpid(),
                       'started': store.now()}, f, ensure_ascii=False)
        os.replace(tmp, current_file())

    def _log_tail(self, n=12):
        try:
            with open(mes_dir('logs', 'mes.log'), encoding='utf-8', errors='replace') as f:
                return ''.join(f.readlines()[-n:])
        except OSError:
            return ''

    def _kill(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(5)
            except Exception:                    # noqa: BLE001
                try:
                    p.kill()
                except Exception:                # noqa: BLE001
                    pass
        try:
            c = read_current()
            if c and c.get('vf_pid') == os.getpid():
                os.remove(current_file())
        except OSError:
            pass

    async def _stop(self, why=''):
        if self.state == 'stopped' and not self.proc:
            return
        log.info(_tr('本机 MES 停止：%s'), why or _tr('手动'))
        await asyncio.get_running_loop().run_in_executor(None, self._kill)
        self.state, self.stopped_why, self.remote, self.port, self.key, self.token = 'stopped', why, {}, 0, '', ''

    async def stop(self, why=''):
        async with self.lock:
            await self._stop(why)
            return self.status()

    def kill_now(self):
        """本地服务退出时（同步）：直接结束 MES。"""
        self._kill()
        self.state = 'stopped'

    async def session_token(self, renew=False):
        """本机学员在 MES 里的会话令牌：钥匙 → 一次性登录票 → /api/edu/session（MES 只认本机来的请求）。只留在本地服务里。"""
        if self.state != 'running':
            raise HTTPException(503, _tr('MES 没在运行'))
        if self.token and not renew:
            return self.token
        port, key = self.port, self.key
        loop = asyncio.get_running_loop()
        for i in range(6):                         # 刚起来时偶尔断一次连接（Windows 10053），重试几次
            try:
                t = await loop.run_in_executor(None, lambda: _http('POST', f'http://127.0.0.1:{port}/api/edu/ticket', key, {}))
                s = await loop.run_in_executor(None, lambda: _http('POST', f'http://127.0.0.1:{port}/api/edu/session', '', {'ticket': t['ticket']}))
                if port == self.port:              # 换令牌期间 MES 没有被重启
                    self.token = s['token']
                return s['token']
            except (urllib.error.URLError, ConnectionError, OSError, KeyError, TypeError) as e:
                if i == 5:
                    raise HTTPException(502, _tr('MES 没有响应：{e}', e=e))
                await asyncio.sleep(0.5)

    async def proxy(self, method, path, query, ctype, body):
        """网页的 /api/mes/<path> → MES 的 /api/<path>，带上本机学员的会话（MES 说 401 就换一个令牌再试一次）。
        → (状态码, 头, 字节)。MES 没在运行 → 503；连不上 → 502。MES 的 401 不原样给网页（网页会以为虚拟工厂的登录过期了）。"""
        if self.state != 'running' or not self.port:
            return 503, {'content-type': 'application/json'}, json.dumps(
                {'detail': _tr('MES 没在运行：') + (self.stopped_why or self.error or _tr('先打开 MES')), 'mes_state': self.state}, ensure_ascii=False).encode()
        url = f'http://127.0.0.1:{self.port}/api/{path}' + (f'?{query}' if query else '')
        loop = asyncio.get_running_loop()
        code, hd, raw = 502, {}, b''
        for attempt in range(2):
            tok = await self.session_token(renew=attempt > 0)
            from ..i18n import lang                  # the page's language (X-Lang / ?lang=) goes to the MES too
            h = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/json, text/csv, text/html, */*', 'X-Lang': lang()}
            if ctype:
                h['Content-Type'] = ctype
            try:
                code, hd, raw = await loop.run_in_executor(None, lambda: _raw(method, url, h, body, 120))
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                if self.state != 'running' or not self.proc or self.proc.poll() is not None:     # 正在停（点了停止、空闲自动停止）：当作已停止
                    return 503, {'content-type': 'application/json'}, json.dumps({'detail': _tr('MES 已停止'), 'mes_state': 'stopped'}, ensure_ascii=False).encode()
                return 502, {'content-type': 'application/json'}, json.dumps({'detail': _tr('MES 没有响应：{e}', e=e)}, ensure_ascii=False).encode()
            if code != 401:
                break
        if code == 401:
            code = 502
            raw = json.dumps({'detail': _tr('MES 不认本机学员的会话（重新打开 MES 试试）')}, ensure_ascii=False).encode()
            hd = {'content-type': 'application/json'}
        return code, hd, raw

    async def call(self, method, path, body=None, timeout=10):
        if self.state != 'running':
            raise HTTPException(400, _tr('MES 没在运行'))
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: _http(method, f'http://127.0.0.1:{self.port}{path}', self.key, body, timeout))
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get('detail')
            except Exception:                    # noqa: BLE001
                detail = str(e)
            raise HTTPException(e.code, detail)

    # ---------- 看护：进程退出、工厂没了、空闲太久 ----------
    async def monitor(self):
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(10)
            if self.state != 'running':
                continue
            try:
                if not self.proc or self.proc.poll() is not None:
                    code = self.proc.returncode if self.proc else None
                    self.proc = None
                    self.state, self.error = 'error', _tr('MES 进程意外退出（退出码 {code}）', code=code)
                    log.warning(self.error + '\n' + self._log_tail())
                    continue
                m = self.d.mgr
                if self.pid not in m.rts and self.pid not in m.sandboxes:
                    await self.stop(_tr('工厂已关闭'))
                    continue
                try:
                    self.remote = await loop.run_in_executor(None, lambda: _http('GET', f'http://127.0.0.1:{self.port}/api/edu/status', self.key, timeout=4))
                except Exception:                # noqa: BLE001
                    continue
                lim = self.idle_min()
                idle = min(float(self.remote.get('idle_s') or 0), time.time() - (self.last_ping or self.started))
                if lim > 0 and idle > lim * 60:
                    await self.stop(_tr('空闲超过 {lim:g} 分钟，已自动停止（再点"打开 MES"就能接着用，数据都在）', lim=lim))
            except Exception:                    # noqa: BLE001
                log.exception(_tr('MES 看护出错'))

    # ---------- 接口 ----------
    def register(self, app):
        sc = self

        @app.get('/api/desktop/mes')
        async def mes_status(request: Request):
            """本机 MES 的状态 + 可以开 MES 的本机工厂。"""
            return {**sc.status(), 'plants': sc.local_plants(request.state.user), 'mode': sc.d.settings.get('mode'), 'connected': sc.d.connected()}

        @app.post('/api/desktop/mes/start')
        async def mes_start(request: Request, body: dict = Body(...)):
            """给一个本机工厂启动 MES（打开这个工厂的协议），返回状态。页面随后经 /api/mes/* 取数。"""
            pid = str(body.get('pid') or '').strip()
            if not pid:
                raise HTTPException(400, _tr('先选一个本机工厂'))
            await sc.start(pid, request.state.user)
            await sc.session_token()                 # 先换好会话，页面第一次取数就不用等
            return sc.status()

        @app.api_route('/api/mes/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'], include_in_schema=False)
        async def mes_proxy(path: str, request: Request):
            """5.0.1：MES 页面（web/src/mes/）取数都走这里 → 本机 MES 的 /api/<path>。虚拟工厂的登录照常检查（下载链接用 ?token=）；
            MES 的钥匙和会话令牌不出本地服务。只在桌面模式注册（服务器上没有 MES）。"""
            q = urllib.parse.urlencode([(k, v) for k, v in request.query_params.multi_items() if k not in _DROP_QS])
            body = await request.body() if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') else None
            code, hd, raw = await sc.proxy(request.method, path, q, request.headers.get('content-type', ''), body)
            out = {k: v for k, v in hd.items() if k in _PASS_HEADERS}
            out.setdefault('cache-control', 'no-store')
            return Response(content=raw, status_code=code, headers=out, media_type=None)

        @app.post('/api/desktop/mes/stop')
        async def mes_stop():
            return await sc.stop(_tr('手动停止'))

        @app.post('/api/desktop/mes/ping')
        async def mes_ping():
            """/mes 页面开着时每分钟一次（不算空闲）。"""
            sc.last_ping = time.time()
            return sc.status()

        @app.post('/api/desktop/mes/reimport')
        async def mes_reimport():
            """工厂改了设备：让 MES 重新导入设备和点表。"""
            return await sc.call('POST', '/api/edu/import', {}, timeout=60)

        @app.put('/api/desktop/mes/settings')
        async def mes_settings(body: dict = Body(...)):
            """空闲多少分钟自动停止（0 = 不自动停止）。"""
            try:
                v = max(0.0, min(24 * 60.0, float(body.get('idle_min'))))
            except (TypeError, ValueError):
                raise HTTPException(400, _tr('idle_min 要是分钟数'))
            sc.d.settings['mes_idle_min'] = v
            from ..desktop import save_settings
            save_settings(sc.d.settings)
            return sc.status()
