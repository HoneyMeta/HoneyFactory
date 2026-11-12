"""客户端（桌面模式）里的教学：本机自学课程、学校作业、交作业、作业包（设计 4.2 第 3、4、6 节）。

只在桌面模式下可用（mgr.desktop，见 vfactory/desktop.py；测试时也可以设环境变量 VF_DESKTOP=1）——服务器上这些接口一律 404，免得被拿去访问任意网址。

本机自学：
  POST /api/client/local/ensure            建"本机自学"班（本机账号是学生），内置课程全部发布进来（按顺序解锁，本机评分 = 本机预估分）
学校服务器（本地后端代为访问，浏览器不用跨域）：
  GET  /api/client/status                  {desktop, school:{url, username, name, connected, at}}（不返回令牌）
  POST /api/client/school/test   {url?}    测连接：服务器版本；已登录时顺带验证令牌
  POST /api/client/school/login  {url, username, password}   登录学校服务器（只接受学生账号），令牌存本机设置
  POST /api/client/school/logout
  GET  /api/client/school/my               学校的"我的作业"（课程地图 + 单独任务），标出已在本机打开的
  POST /api/client/school/open   {remote_aid}     把学校作业装到本机（本机建同样的作业和沙箱）→ {local_aid}
  POST /api/client/school/submit {aid, plant?}    把本机沙箱里的作业打包交给学校服务器（服务器重新评分）→ 学校的评分结果
                                                  提交工厂作业（4.4）：plant = 选中的"我的工厂"编号，包里是这座工厂的模型 + PLC 程序（作业包版本 2）
作业包：
  GET  /api/teach/assignments/{aid}/package       导出（api.py；本机的学校作业会写上学校地址和学校的作业号）
  POST /api/client/open_package  {path} | {data}  打开 .vfhw（双击作业包：启动器打开 /teach?open=<路径>）→ 包的信息 + id
  POST /api/client/packages/{id}/run              老师：在本机复核沙箱里运行包里的程序/模型 → {pid, review: true}
                                                  学生：只能打开自己的包，装进自己这个作业的沙箱（接着做、再交）→ {pid, aid, own: true}
AI 助教：本机作业连着学校时转问学校的 /api/tutor/ask；没连上只给内置提示。
"""
from ..i18n import _tr
import asyncio
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import Body, HTTPException, Request

from .. import courses, store
from . import db, package as pk
from .tasks import task_of

LOCAL_CLASS = '本机自学'
SYS_TEACHER = '_local'
SCHOOL_TEACHER = '_school'


def is_desktop(app):
    mgr = getattr(app.state, 'mgr', None) or _MGR.get('m')
    return bool(getattr(mgr, 'desktop', None)) or bool(getattr(app.state, 'desktop', False)) or os.environ.get('VF_DESKTOP') == '1'


_MGR: dict = {}


def is_desktop_proc():
    """这个进程是不是客户端的本地服务（5.0：AI 助手经服务器代理时用；服务器进程里永远是 False）。"""
    m = _MGR.get('m')
    return bool(getattr(m, 'desktop', None)) or os.environ.get('VF_DESKTOP') == '1'


def _data_dir():
    from .api import _data_dir as d
    return d()


def _settings_path():
    return os.path.join(_data_dir(), 'client', 'school.json')


def load_settings():
    try:
        with open(_settings_path(), encoding='utf-8') as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def save_settings(d):
    p = _settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def norm_url(u):
    u = (u or '').strip().rstrip('/')
    if u and not u.startswith(('http://', 'https://')):
        u = 'http://' + u
    p = urllib.parse.urlparse(u)
    if p.scheme not in ('http', 'https') or not p.netloc:
        raise HTTPException(400, _tr('服务器地址不对，例如 http://192.168.1.10:8800'))
    return f'{p.scheme}://{p.netloc}{p.path.rstrip("/")}'


def _call(url, method='GET', body=None, token=None, raw=None, ctype=None, timeout=30):
    """同步访问学校服务器（在线程里跑）。返回 (状态码, 解析后的 JSON 或字节)。"""
    data = raw if raw is not None else (json.dumps(body).encode('utf-8') if body is not None else None)
    h = {'Accept': 'application/json'}
    if data is not None:
        h['Content-Type'] = ctype or ('application/octet-stream' if raw is not None else 'application/json')
    if token:
        h['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        b, code = e.read(), e.code
    try:
        return code, json.loads(b.decode('utf-8')) if b else {}
    except ValueError:
        return code, b


async def remote(path, method='GET', body=None, raw=None, need_login=True, url=None, token=None, timeout=60):
    s = load_settings()
    base = url or s.get('url')
    if not base:
        raise HTTPException(400, _tr('还没设置学校服务器：在"设置 → 学校服务器"里填地址并登录'))
    tok = token if token is not None else (s.get('token') if need_login else None)
    if need_login and not tok:
        raise HTTPException(401, _tr('还没登录学校服务器'))
    try:
        code, d = await asyncio.get_running_loop().run_in_executor(None, lambda: _call(base + path, method, body, tok, raw, timeout=timeout))
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise HTTPException(502, _tr('连不上学校服务器（{base}）：{getattr}', base=base, getattr=getattr(e, "reason", e)))
    if code == 401 and need_login:
        raise HTTPException(401, _tr('学校服务器的登录已过期，请在设置里重新登录'))
    if code >= 400:
        msg = d.get('detail') if isinstance(d, dict) else None
        raise HTTPException(code if code < 500 else 502, _tr('学校服务器：{v}', v=msg or code))
    return d


def register(app, mgr):
    _MGR['m'] = mgr

    def need_desktop(request):
        if not is_desktop(app):
            raise HTTPException(404, _tr('只有客户端（桌面模式）有这个功能'))
        return request.state.user

    # ---------------- 本机自学 ----------------
    def ensure_local(username):
        """"本机自学"班：本机账号是学生，内置课程都发布进来（新版本多出的课程、课也补上）。"""
        from .course_api import publish_course
        c = db.q('select id from classes where name=? and teacher=?', (LOCAL_CLASS, SYS_TEACHER), one=True)
        cid = c['id'] if c else db.x('insert into classes(name, teacher, descr, created) values(?,?,?,?)',
                                     (LOCAL_CLASS, SYS_TEACHER, _tr('客户端自带的课程，离线练习；分数是本机预估分'), store.now()))
        db.x('insert or ignore into class_members(class_id, username, created) values(?,?,?)', (cid, username, store.now()))
        n = 0
        for co in courses.list_courses():
            n += publish_course(cid, co['id'], SYS_TEACHER, {})['created']
        return cid, n

    @app.post('/api/client/local/ensure')
    async def local_ensure(request: Request):
        u = need_desktop(request)
        cid, n = ensure_local(u['username'])
        return {'class_id': cid, 'created': n}

    # ---------------- 学校服务器 ----------------
    def school_view():
        s = load_settings()
        return {'url': s.get('url') or '', 'username': s.get('username') or '', 'name': s.get('name') or '', 'connected': bool(s.get('token')),
                'at': s.get('at')}

    @app.get('/api/client/status')
    async def status(request: Request):
        u = need_desktop(request)
        return {'desktop': True, 'school': school_view(), 'user': u['username']}

    @app.post('/api/client/school/test')
    async def school_test(request: Request, body: dict = Body(default={})):
        need_desktop(request)
        s = load_settings()
        url = norm_url(body.get('url') or s.get('url'))
        h = await remote('/api/health', url=url, need_login=False, timeout=10)
        out = {'ok': True, 'url': url, 'server': {k: h.get(k) for k in ('version', 'edition', 'desktop')} if isinstance(h, dict) else {}}
        if s.get('token') and url == s.get('url'):
            try:
                m = await remote('/api/teach/me', timeout=10)
                out['login'] = {'ok': True, 'username': m.get('username'), 'name': m.get('name')}
            except HTTPException as e:
                out['login'] = {'ok': False, 'msg': e.detail}
        return out

    @app.post('/api/client/school/login')
    async def school_login(request: Request, body: dict = Body(...)):
        need_desktop(request)
        url = norm_url(body.get('url'))
        user, pw = (body.get('username') or '').strip(), body.get('password') or ''
        if not user or not pw:
            raise HTTPException(400, _tr('填写学校发给你的账号和密码'))
        try:
            r = await remote('/api/login', 'POST', {'username': user, 'password': pw}, url=url, need_login=False, timeout=15)
        except HTTPException as e:
            if e.status_code in (400, 401, 403):
                raise HTTPException(400, _tr('学校服务器：账号或密码不对'))
            raise
        tok = r.get('token') if isinstance(r, dict) else None
        if not tok:
            raise HTTPException(502, _tr('学校服务器没有返回登录令牌'))
        m = await remote('/api/teach/me', url=url, token=tok, timeout=15)
        if (m.get('role') or '') not in ('student',):
            raise HTTPException(400, _tr('客户端只能用学生账号连学校服务器（{user} 是 {get}）；老师请直接用浏览器打开学校服务器', user=user, get=m.get('role')))
        old = load_settings()
        try:
            h = await remote('/api/health', url=url, need_login=False, timeout=10)
            deploy = (h.get('deploy') if isinstance(h, dict) else None) or 'selfhost'
        except HTTPException:
            deploy = 'selfhost'
        save_settings({'url': url, 'username': user, 'name': m.get('name') or user, 'token': tok, 'at': store.now(), 'deploy': deploy,
                       'course_keys': old.get('course_keys') or {}, 'course_key_by_url': old.get('course_key_by_url') or {}})
        await pin_key(url, tok)
        return school_view()

    @app.post('/api/client/school/logout')
    async def school_logout(request: Request):
        need_desktop(request)
        s = load_settings()
        s.pop('token', None)
        save_settings(s)
        return school_view()

    # ---------------- 4.6 课程包：老师做的课，客户端下载签名的课程包离线做 ----------------
    async def pin_key(url=None, tok=None):
        """记下学校服务器的课程签名公钥（先到先信；之后换了密钥的包验不过，要重新登录确认）。"""
        s = load_settings()
        try:
            k = await remote('/api/teach/courses/pubkey', url=url or s.get('url'), token=tok or s.get('token'), timeout=15)
        except HTTPException:
            return s.get('course_keys') or {}
        keys = dict(s.get('course_keys') or {})
        by = dict(s.get('course_key_by_url') or {})
        u = url or s.get('url')
        if isinstance(k, dict) and k.get('alg') == 'ed25519' and k.get('key_id') and k.get('public_key') and u not in by:
            keys[k['key_id']] = k['public_key']          # 每个学校服务器第一次见到时记下它的公钥（先到先信）
            by[u] = k['key_id']
            s.update(course_keys=keys, course_key_by_url=by)
            save_settings(s)
        return keys

    async def ensure_course(cid, version=None):
        """学校作业用到的课本机没有（或学校有了新版本）：从学校下载课程包，验签名后装到本机。"""
        from ..courses import coursepkg
        have = courses.get_course(cid)
        if have and (have.get('origin') != 'package' or not version or (have.get('version') or 0) >= version):
            return have
        st = load_settings()
        keys = st.get('course_keys') if st.get('url') in (st.get('course_key_by_url') or {}) else await pin_key()
        data = await remote(f'/api/teach/courses/{cid}/package', timeout=60)
        if isinstance(data, dict):
            raise HTTPException(502, _tr('学校服务器没有返回课程包'))
        try:
            coursepkg.install(data, keys)
        except coursepkg.CoursePackageError as e:
            raise HTTPException(400, _tr('课程包校验没通过，没有安装：{e}', e=e))
        return courses.get_course(cid)

    @app.post('/api/client/courses/install')
    async def course_install(request: Request, body: dict = Body(...)):
        """手动装课程包（老师发的 .vfcourse 文件）：只认已登录过的学校服务器的签名。"""
        need_desktop(request)
        from ..courses import coursepkg
        d = str(body.get('data') or '')
        if d.startswith('data:'):
            d = d.split(',', 1)[-1]
        import base64
        try:
            raw = base64.b64decode(d)
        except ValueError:
            raise HTTPException(400, _tr('课程包数据不对'))
        try:
            r = coursepkg.install(raw, load_settings().get('course_keys') or {})
        except coursepkg.CoursePackageError as e:
            raise HTTPException(400, _tr('课程包校验没通过，没有安装：{e}', e=e))
        return {'ok': True, 'course': r['course']['id'], 'name': r['course'].get('name'), 'version': r['course'].get('version'),
                'content_sha256': r['manifest']['content_sha256']}

    @app.get('/api/client/courses')
    async def course_installed(request: Request):
        need_desktop(request)
        out = []
        for cid in courses.installed_ids():
            c = courses.get_course(cid)
            out.append({'id': cid, 'ok': bool(c), 'name': (c or {}).get('name'), 'version': (c or {}).get('version'),
                        'package': (c or {}).get('package'), 'error': courses.package_error.get(cid)})
        return {'courses': out, 'keys': list((load_settings().get('course_keys') or {}).keys())}

    def link_of(local_aid):
        return db.q('select * from client_links where local_aid=?', (local_aid,), one=True)

    @app.get('/api/client/school/my')
    async def school_my(request: Request):
        need_desktop(request)
        d = await remote('/api/teach/my/courses')
        url = load_settings().get('url')
        links = {r['remote_aid']: r['local_aid'] for r in db.q('select * from client_links where server=?', (url,))}
        for c in d.get('courses') or []:
            for ch in c.get('chapters') or []:
                for l in ch.get('lessons') or []:
                    l['local_aid'] = links.get(l.get('aid'))
        for t in d.get('tasks') or []:
            t['local_aid'] = links.get(t.get('id'))
        d['server'] = url
        return d

    def mirror_class(username, url, class_name):
        name = _tr('学校：{v}', v=class_name or url)
        c = db.q('select id from classes where name=? and teacher=?', (name, SCHOOL_TEACHER), one=True)
        cid = c['id'] if c else db.x('insert into classes(name, teacher, descr, created) values(?,?,?,?)',
                                     (name, SCHOOL_TEACHER, _tr('学校服务器 {url} 的作业（本机练习，交作业时交给学校）', url=url), store.now()))
        db.x('insert or ignore into class_members(class_id, username, created) values(?,?,?)', (cid, username, store.now()))
        return cid

    @app.post('/api/client/school/open')
    async def school_open(request: Request, body: dict = Body(...)):
        """学校作业 → 本机作业（同样的课/场景、设置），之后在本机沙箱里做。已打开过的只更新设置。"""
        u = need_desktop(request)
        try:
            raid = int(body.get('remote_aid'))
        except (TypeError, ValueError):
            raise HTTPException(400, _tr('缺少学校的作业号'))
        return await open_school(u, raid)

    async def open_school(u, raid):
        t = await remote(f'/api/teach/assignments/{raid}/task?client=1')
        c = t.get('client') or {}
        st = c.get('settings') or {}
        a = t.get('assignment') or {}
        url = load_settings().get('url')
        if (c.get('kind') or a.get('kind')) == 'factory' and not isinstance(st.get('spec'), dict):
            raise HTTPException(400, _tr('这是提交工厂作业，但学校服务器没有给出要求（服务器版本太旧？）'))
        if c.get('course') and c.get('course_origin') == 'authored':        # 4.6 老师做的课：先装（或更新）签名的课程包
            await ensure_course(c['course'], c.get('course_version'))
        try:
            task_of({'course': c.get('course'), 'lesson': c.get('lesson'), 'scene': c.get('scene'), 'kind': c.get('kind'), 'spec': st.get('spec')})
        except HTTPException:
            raise HTTPException(400, _tr('这个作业用到的课程/场景本机没有：请升级客户端'))
        cid = mirror_class(u['username'], url, c.get('class_name'))
        if c.get('course'):
            db.x('insert or ignore into course_pubs(class_id, course, open_all, teacher, created) values(?,?,?,?,?)',
                 (cid, c['course'], 1, SCHOOL_TEACHER, store.now()))
        ln = db.q('select * from client_links where server=? and remote_aid=?', (url, raid), one=True)
        vals = (cid, c.get('scene'), (st.get('title') or a.get('title') or '')[:80], st.get('descr') or '', st.get('due'),
                json.dumps(st.get('faults') or [], ensure_ascii=False), json.dumps(st.get('start_faults') or [], ensure_ascii=False),
                1 if st.get('hints', True) else 0, 1 if st.get('tutor', True) else 0, c.get('course'), c.get('lesson'), c.get('kind') or 'cell',
                a.get('seq'), json.dumps(st['spec'], ensure_ascii=False) if isinstance(st.get('spec'), dict) else None)
        if ln and db.assignment(ln['local_aid']):
            laid = ln['local_aid']
            db.x('update assignments set class_id=?, scene=?, title=?, descr=?, due=?, faults=?, start_faults=?, hints=?, tutor=?, course=?, lesson=?, '
                 'kind=?, seq=?, spec=?, updated=? where id=?', vals + (store.now(), laid))
        else:
            laid = db.x('insert into assignments(class_id, scene, title, descr, due, faults, start_faults, hints, tutor, course, lesson, kind, seq, '
                        'spec, status, teacher, created, updated) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        vals + ('published', SCHOOL_TEACHER, store.now(), store.now()))
        db.x('insert or replace into client_links(local_aid, server, remote_aid, remote_class, remote_title, remote_due, fetched) values(?,?,?,?,?,?,?)',
             (laid, url, raid, c.get('class_name'), a.get('title'), st.get('due'), store.now()))
        return {'local_aid': laid, 'remote_aid': raid, 'title': st.get('title') or a.get('title')}

    @app.post('/api/client/school/submit')
    async def school_submit(request: Request, body: dict = Body(...)):
        """本机作业打包 → 学校服务器 submit_package（服务器重新评分）。返回学校的评分结果（和沙箱提交同样的结构）。"""
        u = need_desktop(request)
        laid = int(body.get('aid') or 0)
        ln = link_of(laid)
        if not ln:
            raise HTTPException(400, _tr('这不是学校的作业（本机自学的课只有本机预估分，可以"导出作业包"交给老师）'))
        s = load_settings()
        if s.get('url') != ln['server']:
            raise HTTPException(400, _tr('这个作业是 {server} 的，现在连的是 {v}', server=ln['server'], v=s.get('url') or _tr('（没连）')))
        build = app.state.teach_build_package
        data = await build(laid, u['username'], body.get('plant'))
        r = await remote(f"/api/teach/assignments/{ln['remote_aid']}/submit_package", 'POST', raw=data, timeout=360)
        db.x('update client_links set fetched=? where local_aid=?', (store.now(), laid))
        return {'remote': r, 'server': ln['server'], 'remote_aid': ln['remote_aid'], 'plant': body.get('plant')}

    @app.get('/api/client/school/results')
    async def school_results(request: Request, aid: int = 0):
        """本机作业对应的学校作业：学校服务器上我的提交（老师给的分数、评语）。连不上返回 offline=True。"""
        need_desktop(request)
        ln = link_of(aid)
        if not ln:
            return {'school': False, 'submissions': []}
        s = load_settings()
        if not s.get('token') or s.get('url') != ln['server']:
            return {'school': True, 'offline': True, 'submissions': [], 'server': ln['server']}
        try:
            t = await remote(f"/api/teach/assignments/{ln['remote_aid']}/task", timeout=20)
        except HTTPException as e:
            return {'school': True, 'offline': True, 'msg': e.detail, 'submissions': [], 'server': ln['server']}
        keep = ('id', 'created', 'status', 'score', 'auto_score', 'override_score', 'comment', 'reviewed_by', 'reviewed_at', 'source', 'late', 'details',
                'hidden', 'error', 'rule_comments', 'reveal')          # reveal：学校服务器按老师的设置给的正确答案和解析（4.6.2）
        return {'school': True, 'server': ln['server'], 'remote_aid': ln['remote_aid'], 'best': t.get('best'),
                'submissions': [{k: x.get(k) for k in keep} for x in t.get('submissions') or []]}

    # ---------------- 作业包：导出时写学校信息、打开 ----------------
    def package_meta(a, meta):
        ln = link_of(a['id'])
        s = load_settings()
        if ln:
            meta.update(server=ln['server'], assignment_id=ln['remote_aid'], local_assignment_id=a['id'])
            if s.get('username'):
                meta['student'] = {'username': s.get('username'), 'name': s.get('name') or s.get('username')}
        elif is_desktop(app):
            meta.update(assignment_id=None, local_assignment_id=a['id'], server=None)
            meta['student'] = {'username': s.get('username') or None, 'name': s.get('name') or None}
        return meta
    app.state.package_meta = package_meta

    def task_client_info(a):
        if not is_desktop(app):
            return None
        ln = link_of(a['id'])
        s = load_settings()
        return {'desktop': True, 'local': not ln, 'school': ({'server': ln['server'], 'remote_aid': ln['remote_aid'], 'title': ln['remote_title'],
                                                              'connected': bool(s.get('token')) and s.get('url') == ln['server']} if ln else None)}
    app.state.task_client_info = task_client_info

    def _opened_dir():
        return os.path.join(_data_dir(), 'client', 'opened')

    @app.post('/api/client/open_package')
    async def open_package(request: Request, body: dict = Body(...)):
        need_desktop(request)
        if body.get('path'):
            p = str(body['path'])
            if not p.lower().endswith((pk.EXT, '.vfplant')):        # .vfplant：导出的工厂文件（和作业包同样的 zip，kind=factory）
                raise HTTPException(400, _tr('只能打开作业包（.vfhw）或工厂文件（.vfplant）：{p}', p=p))
            if not os.path.isfile(p):
                raise HTTPException(400, _tr('找不到作业包文件：{p}', p=p))
            if os.path.getsize(p) > pk.MAX_BYTES:
                raise HTTPException(400, _tr('作业包超过 5 MB'))
            with open(p, 'rb') as f:
                data = f.read()
        else:
            try:
                data = pk.decode(body)
            except pk.PackageError as e:
                raise HTTPException(400, str(e))
        try:
            pkg = pk.read(data)
        except pk.PackageError as e:
            raise HTTPException(400, str(e))
        h = hashlib.sha256(data).hexdigest()[:16]
        os.makedirs(_opened_dir(), exist_ok=True)
        with open(os.path.join(_opened_dir(), h + pk.EXT), 'wb') as f:
            f.write(data)
        info = pkg.summary()
        if info.get('kind') == 'factory':                 # 提交工厂的作业包 / 导出的工厂文件：老师在本机运行看；学生导入为"我的工厂"
            info['task_name'] = info.get('title') or (info.get('plant') or {}).get('name') or _tr('工厂')
            info['runnable'] = True
            return {'id': h, 'path': body.get('path'), **info}
        try:
            t = task_of({'course': info.get('course'), 'lesson': info.get('lesson'), 'scene': info.get('scene')})
            info['task_name'] = t.name
            info['runnable'] = True
        except HTTPException as e:
            info['runnable'] = False
            info['why'] = _tr('本机没有这个作业用到的课程/场景（{detail}），请升级客户端', detail=e.detail)
        return {'id': h, 'path': body.get('path'), **info}

    @app.post('/api/client/packages/{pid_hash}/run')
    async def run_package(pid_hash: str, request: Request):
        u = need_desktop(request)
        if not pid_hash.isalnum() or len(pid_hash) > 32:
            raise HTTPException(400, _tr('作业包编号不对'))
        f = os.path.join(_opened_dir(), pid_hash + pk.EXT)
        if not os.path.exists(f):
            raise HTTPException(404, _tr('先打开作业包'))
        with open(f, 'rb') as fh:
            pkg = pk.read(fh.read())
        m = pkg.manifest
        if m.get('kind') == 'factory':
            return await run_factory_package(u, pkg, pid_hash)
        t = task_of({'course': m.get('course'), 'lesson': m.get('lesson'), 'scene': m.get('scene')})
        who = (m.get('student') or {}).get('name') or (m.get('student') or {}).get('username') or _tr('学生')
        title = _tr('作业包 · {who} · {v}', who=who, v=m.get('title') or t.name)
        try:
            art = pk.artifact(pkg, t)
        except pk.PackageError as e:
            raise HTTPException(400, str(e))
        if u.get('role') == 'student':
            return await open_own(u, pkg, t, art)
        if t.kind == 'cell':
            cfg, programs = t.plant_cfg(title), {'CELL1': art}
        else:
            import copy
            cfg, programs = copy.deepcopy(art), None
            cfg.setdefault('plant', {})['name'] = title
        pid = f'sb-review-p{pid_hash[:12]}'
        rt = await mgr.teach_pool.ensure_review(pid, u['username'], None, cfg, programs, fresh=True)
        from . import scenes
        c = scenes.cell(rt) if scenes.cells(rt) else None
        return {'pid': pid, 'bid': c.id if c else None, 'review': True, 'readonly': False, 'title': title}

    async def run_factory_package(u, pkg, pid_hash):
        """提交工厂的包：学生 → 导入为一座新的"我的工厂"；老师/工程师 → 本机复核沙箱里运行（模型 + 每台 PLC 的程序）。"""
        import copy
        m = pkg.manifest
        if not pkg.model or not isinstance(pkg.model.get('blocks'), list):
            raise HTTPException(400, _tr('作业包里没有工厂模型'))
        who = (m.get('student') or {}).get('name') or (m.get('student') or {}).get('username') or _tr('学生')
        if u.get('role') == 'student':
            from . import myplants
            owner = (m.get('student') or {}).get('username')
            if owner and owner != u['username']:
                raise HTTPException(403, _tr('这是 {who} 的工厂文件：学生只能导入自己的', who=who))
            pid = await myplants._install(mgr, pkg.model, m.get('title') or (pkg.model.get('plant') or {}).get('name'), u['username'], 'import',
                                          pkg.programs)
            return {'pid': pid, 'myplant': True, 'own': True, 'review': False, 'readonly': False, 'title': m.get('title'),
                    'msg': _tr('已导入为一座"我的工厂"，可以在工作台里接着改')}
        title = _tr('作业包 · {who} · {v}', who=who, v=m.get('title') or _tr('工厂'))
        cfg = copy.deepcopy(pkg.model)
        cfg.setdefault('plant', {})['name'] = title[:40]
        cfg['plant'].pop('modbus_port', None)
        pid = f'sb-review-p{pid_hash[:12]}'
        await mgr.teach_pool.ensure_review(pid, u['username'], None, cfg, dict(pkg.programs), fresh=True)
        return {'pid': pid, 'bid': None, 'review': True, 'readonly': False, 'title': title, 'kind': 'factory'}

    async def open_own(u, pkg, t, art):
        """学生打开自己的作业包：装进自己这个作业的沙箱（接着做、再交），不进老师用的复核沙箱。
        找本机作业的顺序：学校作业（服务器 + 学校作业号，本机没打开过且连着学校时先装到本机）→ 导出时的本机作业号 → 本机自学里同一课。"""
        m = pkg.manifest
        me = u['username']
        owner = (m.get('student') or {}).get('username')
        if owner and owner != me:
            raise HTTPException(403, _tr('这是 {v} 的作业包：学生只能打开自己的作业包（老师用客户端打开可以复核）', v=(m.get('student') or {}).get('name') or owner))
        from .api import need_assignment
        laid = None
        if m.get('server') and m.get('assignment_id'):
            ln = db.q('select local_aid from client_links where server=? and remote_aid=?', (m['server'], m['assignment_id']), one=True)
            laid = ln['local_aid'] if ln else None
            s = load_settings()
            if laid is None and s.get('token') and s.get('url') == m['server']:
                try:
                    laid = (await open_school(u, int(m['assignment_id'])))['local_aid']
                except HTTPException:
                    laid = None
        if laid is None and m.get('local_assignment_id') and not m.get('server'):
            laid = m['local_assignment_id']
        cands = [laid] if laid else []
        if not cands:                                     # 本机自学里同一课 / 同一场景
            cid, _ = ensure_local(me)
            if m.get('course') and m.get('lesson'):
                rows = db.q('select id from assignments where class_id=? and course=? and lesson=?', (cid, m['course'], m['lesson']))
            else:
                rows = db.q("select id from assignments where class_id=? and scene=? and (course is null or course='')", (cid, m.get('scene')))
            cands = [r['id'] for r in rows]
        a = None
        import copy
        local_pkg = copy.copy(pkg)                        # 包里的作业号是学校的（或导出时的本机号），本机作业按课/场景/类型对
        local_pkg.manifest = dict(m, assignment_id=None)
        for x in cands:
            try:
                a = need_assignment(u, int(x))
                pk.check_target(local_pkg, a, t)
                break
            except (HTTPException, pk.PackageError, ValueError, TypeError):
                a = None
        if a is None:
            where = _tr('学校 {server} 的作业 {get}', server=m['server'], get=m.get('assignment_id')) if m.get('server') else _tr('本机的课程')
            raise HTTPException(400, _tr('在这台电脑上找不到这个作业包对应的作业（{where}）：先在"我的课程"里打开这个作业，再打开作业包', where=where))
        if t.kind == 'cell':
            rt = await mgr.teach_pool.load_work(me, a, t, program=art)
        else:
            rt = await mgr.teach_pool.load_work(me, a, t, model=art)
        from . import scenes
        c = scenes.cell(rt) if scenes.cells(rt) else None
        return {'pid': rt.pid, 'bid': c.id if c else None, 'aid': a['id'], 'own': True, 'review': False, 'readonly': False,
                'title': a.get('title') or t.name, 'msg': _tr('已把作业包里的') + (_tr('程序下载到你的沙箱 PLC') if t.kind == 'cell' else _tr('模型装进你的沙箱')) + _tr('，可以接着做、再提交')}

    # ---------------- AI 助教：转问学校 ----------------
    async def tutor_proxy(user, aid, body):
        if not is_desktop(app):
            return None
        ln = link_of(aid)
        s = load_settings()
        if ln and s.get('deploy') == 'saas' and s.get('token') and s.get('url') == ln['server']:
            return None                          # 5.0 SaaS：助教在本机答（看本机沙箱），大模型经服务器的 AI 代理（按单位计量、密钥不出服务器）
        if ln and s.get('token') and s.get('url') == ln['server']:
            try:
                return await remote('/api/tutor/ask', 'POST', {'assignment_id': ln['remote_aid'], 'question': body.get('question') or '',
                                                              'history': body.get('history')}, timeout=150)
            except HTTPException as e:
                if e.status_code not in (502, 401):
                    raise
                why = _tr('学校服务器连不上') if e.status_code == 502 else _tr('学校服务器的登录过期了')
        else:
            why = _tr('没连学校服务器') if not ln else _tr('还没登录学校服务器')
        from .. import copilot
        if copilot.server_llm_cfg().get('api_key'):
            return None                          # 本机自己配了大模型（完整版）：照常回答（经服务器 AI 代理的不算：助教要按学校的作业设置问学校）
        from .api import need_assignment, need_task
        a = need_assignment(user, aid)
        hs = need_task(a).public(a['hints']).get('hints') or []
        tip = _tr('先看看提示 1：{v}', v=hs[0]) if hs else _tr('先对照任务书和评分标准，一条一条检查。')
        return {'answer': _tr('{why}，AI 助教用不了（客户端本身没有大模型，要通过学校服务器问）。{tip}', why=why, tip=tip), 'filtered': False, 'fallback': True, 'offline': True}
    app.state.tutor_proxy = tutor_proxy
