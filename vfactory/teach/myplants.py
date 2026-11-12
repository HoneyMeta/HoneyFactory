"""客户端的"我的工厂"（4.4）：学生（和任何登录的账号）在本机建自己的工厂，数量不限，只在这台电脑上。

只在客户端（桌面模式）里有；服务器网页上这些接口 404（学生在网页端只有"教学"，页面上提示"在客户端里可以建自己的工厂"）。
工厂就是本机工厂（编号统一 local- 开头，和联网模式下"本机新建"的工厂同一套：本地服务里运行，代理按编号分流到本机）。
归属记在 data/client/myplants.json {编号: {owner, created, from}}：学生只能打开、改、删自己的；工程师/管理员不受限。

  GET    /api/client/myplants                     我的工厂 + 可选的起点（空白 / 课程里的产线 / 控制单元演示 / 完整示范）
  POST   /api/client/myplants          {name, template}     template：blank | showcase | cells/<名> | course:<课程>/<课>
  PATCH  /api/client/myplants/{pid}    {name}               改名
  POST   /api/client/myplants/{pid}/copy {name?}            复制一份
  DELETE /api/client/myplants/{pid}                         删除（挪进回收目录）
  GET    /api/client/myplants/{pid}/export                  导出工厂文件（.vfplant：和作业包同样的 zip，kind=factory，模型 + 每台 PLC 的程序）
  POST   /api/client/myplants/import   {data: base64, name?}  导入 .vfplant / 提交工厂的 .vfhw 为一座新工厂

提交工厂作业（kind=factory）就是选这里的一座工厂：collect() 取模型 + PLC 程序。
"""
from ..i18n import _tr, label
import json
import logging
import os
import re
import shutil
import time

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from .. import store
from . import factory

log = logging.getLogger('vfactory.teach')
PREFIX = 'local-'
EXT = '.vfplant'


def _data_dir():
    from .api import _data_dir as d
    return d()


def _own_path():
    return os.path.join(_data_dir(), 'client', 'myplants.json')


def owners():
    try:
        with open(_own_path(), encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_owners(d):
    p = _own_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)


def owner_of(pid):
    return (owners().get(pid) or {}).get('owner')


def privileged(u):
    return (u or {}).get('role') in ('admin', 'engineer')


def can_use(u, pid):
    """这个账号能不能打开/改这座本机工厂：自己的；工程师/管理员都可以。"""
    if not pid or not str(pid).startswith(PREFIX) or not u:
        return False
    return privileged(u) or owner_of(pid) == u.get('username')


def need_own(mgr, u, pid):
    """→ 运行中的本机工厂（不是自己的抛 403，没有抛 404）。"""
    pid = str(pid or '')
    rt = mgr.rts.get(pid)
    if rt is None or not pid.startswith(PREFIX):
        raise HTTPException(404, _tr('本机没有这座工厂：{pid}', pid=pid))
    if not can_use(u, pid):
        raise HTTPException(403, _tr('这不是你的工厂'))
    return rt


def collect(rt):
    return factory.collect(rt)


def is_desktop(mgr):
    return bool(getattr(mgr, 'desktop', None)) or os.environ.get('VF_DESKTOP') == '1'


_sketches = {}


def _lesson_sketch(cid, les):
    """课程产线的布局预览（开始页"新建"卡片用，web/src/start/sketch.ts 画成 SVG）；算一次缓存。"""
    key = f"{cid}/{les.get('id')}"
    if key not in _sketches:
        try:
            from .. import courses
            from ..sketch import plan_sketch
            _sketches[key] = plan_sketch(courses.plant_model(les))
        except Exception:
            _sketches[key] = None
    return _sketches[key]


def templates():
    """新建"我的工厂"的起点。"""
    from .. import courses
    from ..server import TEMPLATE_NAMES, template_info
    info = template_info()
    out = [{'key': 'blank', 'name': _tr('空白工厂'), 'group': _tr('空白'), 'desc': _tr('从零开始：在工作台里加设备、连线、加 PLC')}]
    for k, n in TEMPLATE_NAMES.items():
        if k.startswith('cells/'):
            out.append({'key': k, 'name': n, 'group': _tr('控制单元（PLC 实训）'), 'desc': (info.get(k) or {}).get('desc') or '', 'blocks': (info.get(k) or {}).get('blocks'),
                        'sketch': (info.get(k) or {}).get('sketch')})
    for c in courses.list_courses():
        for ch in c.get('chapters') or []:
            for l in ch.get('lessons') or []:
                if l.get('kind', 'plant') == 'plant':
                    out.append({'key': f"course:{c['id']}/{l['id']}", 'name': l['title'], 'group': _tr('课程：{name}', name=c['name']), 'desc': _tr('这一课的产线（不带作业）'),
                                'sketch': _lesson_sketch(c['id'], l)})
    out.append({'key': 'showcase', 'name': label(TEMPLATE_NAMES.get('showcase') or '完整示范'), 'group': _tr('完整示范'), 'desc': (info.get('showcase') or {}).get('desc') or '',
                'sketch': (info.get('showcase') or {}).get('sketch')})
    return out


def _template_cfg(key):
    from .. import courses
    from ..server import TEMPLATE_NAMES, TEMPLATES, read_yaml
    key = str(key or 'blank')
    if key.startswith('course:'):
        cid, _, lid = key[7:].partition('/')
        _c, les = courses.get_lesson(cid, lid)
        if not les or les.get('kind', 'plant') != 'plant':
            raise HTTPException(400, _tr('没有这一课的产线'))
        return courses.plant_model(les)
    if key not in TEMPLATE_NAMES and key != 'blank':
        raise HTTPException(400, _tr('没有这个模板'))
    c = read_yaml(os.path.join(TEMPLATES, f'{key}.yaml'))
    if 'blocks' not in c:
        raise HTTPException(400, _tr('这个模板是旧格式，不能作为"我的工厂"的起点'))
    return c


def _slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', str(name or '').lower()).strip('-')[:20]
    return s or 'my'


async def _install(mgr, cfg, name, owner, src, programs=None):
    """写一座新的本机工厂并启动 → 编号。programs：{PLC 块编号: 程序}（装进软 PLC 并运行）。"""
    from ..server import PLANTS, clear_editor_state, write_yaml
    import copy
    cfg = copy.deepcopy(cfg)
    cfg.setdefault('plant', {})['name'] = (str(name or '').strip() or cfg['plant'].get('name') or _tr('我的工厂'))[:40]
    cfg['plant'].pop('modbus_port', None)
    base = PREFIX + _slug(src if not str(src).startswith('local-') else 'copy')
    pid, n = base, 1
    while pid in mgr.rts or os.path.exists(os.path.join(PLANTS, f'{pid}.yaml')):
        n += 1
        pid = f'{base}-{n}'
    clear_editor_state(pid)
    try:
        from ..plc import store as ps
        d = os.path.join(ps.ROOT, pid)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        for bid, prog in (programs or {}).items():
            if isinstance(prog, dict) and prog.get('source') and ps.safe_id(bid):
                ps.update(pid, 'cells', bid, program=prog, downloaded=prog, run=True, mode='internal', downloaded_at=store.now())
    except ImportError:
        pass
    os.makedirs(PLANTS, exist_ok=True)
    write_yaml(os.path.join(PLANTS, f'{pid}.yaml'), cfg)
    rt = await mgr.launch(pid)
    if not rt:
        raise HTTPException(500, _tr('工厂启动失败，请看日志'))
    o = owners()
    o[pid] = {'owner': owner, 'created': store.now(), 'from': str(src)[:80]}
    _save_owners(o)
    log.info(_tr('我的工厂 %s（%s）已建好，来自 %s'), pid, owner, src)
    return pid


def view(mgr, pid, meta=None):
    rt = mgr.rts.get(pid)
    meta = meta or owners().get(pid) or {}
    if rt is None:
        return None
    from ..editor_api import load_draft
    path = rt.path
    try:
        mt = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))
    except OSError:
        mt = None
    blocks = rt.cfg.get('blocks') or []
    return {'id': pid, 'name': rt.plant.name, 'owner': meta.get('owner'), 'created': meta.get('created'), 'from': meta.get('from'), 'updated': mt,
            'blocks': len(blocks), 'plcs': sum(1 for b in blocks if b.get('type') == 'plc'), 'draft': bool(load_draft(pid)), 'dirty': bool(rt.dirty),
            'paused': rt.plant.paused, 'time': rt.plant.clock_str()}


def register(app, mgr):
    def need(request):
        if not is_desktop(mgr):
            raise HTTPException(404, _tr('"我的工厂"只在客户端里有：装上蜂元虚拟工厂客户端，登录后在左边菜单里找"我的工厂"'))
        return request.state.user

    @app.get('/api/client/myplants')
    async def my_list(request: Request):
        u = need(request)
        own = owners()
        rows = []
        for pid in list(mgr.rts):
            if not pid.startswith(PREFIX):
                continue
            meta = own.get(pid) or {}
            if meta.get('owner') != u['username'] and not (privileged(u) and not meta):
                continue
            v = view(mgr, pid, meta)
            if v:
                rows.append(v)
        rows.sort(key=lambda r: r.get('updated') or '', reverse=True)
        return {'plants': rows, 'templates': templates(), 'ext': EXT}

    @app.post('/api/client/myplants')
    async def my_new(request: Request, body: dict = Body(...)):
        u = need(request)
        key = body.get('template') or 'blank'
        cfg = _template_cfg(key)
        pid = await _install(mgr, cfg, body.get('name'), u['username'], key)
        return view(mgr, pid)

    @app.patch('/api/client/myplants/{pid}')
    async def my_rename(pid: str, request: Request, body: dict = Body(...)):
        u = need(request)
        rt = need_own(mgr, u, pid)
        name = str(body.get('name') or '').strip()[:40]
        if not name:
            raise HTTPException(400, _tr('名称不能是空的'))
        rt.patch_plant({'name': name})
        rt.save()
        from ..editor_api import draft_path, load_draft
        d = load_draft(pid)
        if d and isinstance(d.get('model'), dict):
            d['model'].setdefault('plant', {})['name'] = name
            with open(draft_path(pid), 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False)
        return view(mgr, pid)

    @app.post('/api/client/myplants/{pid}/copy')
    async def my_copy(pid: str, request: Request, body: dict = Body(default={})):
        u = need(request)
        rt = need_own(mgr, u, pid)
        model, programs, _ = collect(rt)
        nid = await _install(mgr, model, (body or {}).get('name') or _tr('{name} 副本', name=rt.plant.name), u['username'], pid, programs)
        return view(mgr, nid)

    @app.delete('/api/client/myplants/{pid}')
    async def my_delete(pid: str, request: Request):
        from ..server import PLANTS, clear_editor_state
        u = need(request)
        rt = need_own(mgr, u, pid)
        await rt.stop()
        mgr.rts.pop(pid, None)
        trash = os.path.join(PLANTS, '.trash')
        os.makedirs(trash, exist_ok=True)
        stamp = int(time.time())
        if os.path.exists(rt.path):
            shutil.move(rt.path, os.path.join(trash, f'{pid}-{stamp}.yaml'))
        clear_editor_state(pid, os.path.join(trash, f'{pid}-{stamp}'))
        try:
            from ..plc import store as ps
            d = os.path.join(ps.ROOT, pid)
            if os.path.isdir(d):
                shutil.move(d, os.path.join(trash, f'{pid}-{stamp}-plc'))
        except (ImportError, OSError):
            pass
        o = owners()
        o.pop(pid, None)
        _save_owners(o)
        return {'ok': True}

    def _package(u, rt):
        from . import package as pk
        model, programs, info = collect(rt)
        meta = {'kind': 'factory', 'title': rt.plant.name, 'plant': info, 'assignment_id': None, 'server': None,
                'student': {'username': u['username'], 'name': u.get('name') or u['username']}}
        return pk.build(meta, programs, model, None, {'sim_time': rt.plant.clock_str()})

    @app.get('/api/client/myplants/{pid}/export')
    async def my_export(pid: str, request: Request):
        from urllib.parse import quote
        u = need(request)
        rt = need_own(mgr, u, pid)
        try:
            data = _package(u, rt)
        except ValueError as e:
            raise HTTPException(400, str(e))
        name = re.sub(r'[\\/:*?"<>|]+', '_', rt.plant.name or pid)[:40] + EXT
        return Response(data, media_type='application/octet-stream', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.post('/api/client/myplants/import')
    async def my_import(request: Request, body: dict = Body(...)):
        from . import package as pk
        u = need(request)
        try:
            pkg = pk.read(pk.decode(body))
        except pk.PackageError as e:
            raise HTTPException(400, str(e))
        if not pkg.model or not isinstance(pkg.model.get('blocks'), list):
            raise HTTPException(400, _tr('这个文件里没有可以导入的工厂模型（PLC 课的作业包只有程序）'))
        progs = pkg.programs if pkg.manifest.get('kind') == 'factory' else {}
        pid = await _install(mgr, pkg.model, body.get('name') or pkg.manifest.get('title') or (pkg.model.get('plant') or {}).get('name'),
                             u['username'], 'import', progs)
        return view(mgr, pid)

    app.state.myplants_package = _package


_PID = re.compile(r'^/(?:api/p|ws)/([^/]+)')
HARD_DENY = ('/api/admin', '/api/tokens', '/api/assistant', '/api/copilot', '/api/settings/')


def own_context(mgr, u, path, header_pid='', query_pid=''):
    """客户端里学生/老师在自己的"我的工厂"里操作：放行（教学角色的访问范围只管学校的沙箱，管不到本机自己的工厂）。
    判断依据：路径 /api/p/<编号>/… 或 /ws/<编号>，其他接口看请求头 X-VF-Plant（或 ?vfp=）指向的工厂。"""
    if not is_desktop(mgr) or not u or u.get('role') not in ('student', 'teacher') or path.startswith(HARD_DENY):
        return False
    from urllib.parse import unquote
    m = _PID.match(path)
    pid = unquote(m.group(1)) if m else (header_pid or query_pid or '')
    return bool(pid) and pid.startswith(PREFIX) and pid in mgr.rts and owner_of(pid) == u.get('username')
