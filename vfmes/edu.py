"""蜂元教学 MES 的教学部分：蜂元虚拟工厂客户端在本机按需启动它（vfactory/mes/sidecar.py），只接一座本机工厂。

- 单用户：本机学员账号 learner（管理员权限，不用密码，客户端用一次性登录票自动登录），其他账号一律停用；只监听 127.0.0.1。
- 不接外部系统：只接本机的虚拟工厂（数据源和接口地址由客户端用环境变量给定），第一次启动自动"从虚拟工厂导入"。
- 数据放在客户端的数据目录（HM_DATA，每个工厂一份）。
- 给客户端和教学评分用的接口：/api/edu/*（客户端用 HM_EDU_KEY 调用），评分取数是声明式检查（见 QUERIES）。

环境变量（由虚拟工厂客户端 vfactory/mes/sidecar.py 设置）：
  HM_DATA              数据目录（mes.db、secret.key）；不给时用 <虚拟工厂目录>/data/mes-dev
  HM_EDU_KEY           客户端专用钥匙（x-hm-key 请求头）：换一次性登录票、查状态、评分取数
  HM_PLANT / HM_PLANT_NAME   虚拟工厂里的工厂编号 / 名称
  HM_VF_HTTP           虚拟工厂接口地址，如 http://127.0.0.1:52011/api/p/local-xxx
  HM_VF_TOKEN          虚拟工厂会话令牌（导入设备、取刀具数据用）
  HM_MQTT              虚拟工厂 MQTT 地址，如 mqtt://127.0.0.1:52012
  HM_USER_NAME         学员显示名（默认"学员"）
  HM_WATCH_PID         客户端本地服务的进程号：它没了 MES 跟着退出
"""
from .i18n import _tr
import asyncio
import hmac
import logging
import os
import secrets
import sys
import time

import sqlalchemy as sa
from fastapi import APIRouter, Body, HTTPException, Request

EDU = True                   # 只有教学这一种模式（/api/me、/api/edu/info 照旧返回 edu: true，前端和客户端测试会看）
BRAND = '蜂元教学 MES'
EDU_USER = 'learner'
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger('mes.edu')
STATE = {'started': time.time(), 'last': time.time(), 'requests': 0, 'import': '', 'imported_at': None}
_tickets: dict[str, float] = {}


def env(k, default=''):
    return os.environ.get(k, default) or default


def source_info() -> dict:
    """这个进程跑的是哪一份代码：vfmes 包所在目录；有没有混进别的 MES 包（旧的 honeymes）。客户端测试用来确认 MES 来自虚拟工厂目录。"""
    foreign = [p for p in sys.path if p and ('honeymes' in p.lower() or os.path.isfile(os.path.join(p, 'honeymes', '__init__.py')))]
    return {'source': PKG_DIR, 'honeymes_loaded': any(m == 'honeymes' or m.startswith('honeymes.') for m in sys.modules),
            'honeymes_paths': foreign}


# ---------------- 账号与初始数据 ----------------
def seed(c):
    """单用户：本机学员（管理员权限，所有模块可写），停用其他账号（旧数据库里可能还有）；数据源指向本机虚拟工厂。"""
    from . import auth, db
    name = env('HM_USER_NAME', _tr('学员'))
    u = db.get(c, 'sys_user', username=EDU_USER)
    if u:
        db.update(c, 'sys_user', u['id'], {'name': name, 'roles': 'admin', 'active': True}, raw=True)
    else:
        db.insert(c, 'sys_user', {'username': EDU_USER, 'name': name, 'roles': 'admin', 'active': True,
                                  'password_hash': auth.hash_pw(secrets.token_hex(16))}, raw=True)
    st = db.TABLES['sys_user']
    c.execute(st.update().where(st.c.username != EDU_USER).values(active=False))
    pid, pname = env('HM_PLANT'), env('HM_PLANT_NAME')
    ds = db.get(c, 'datasource', code='VF')
    # 只接客户端给的本机虚拟工厂；没给 MQTT 地址就不采集（不去连默认的 1883）
    row = {'enabled': bool(env('HM_MQTT')), 'remark': _tr('本机虚拟工厂（客户端自动配置）')}
    if env('HM_MQTT'):
        row['endpoint'] = env('HM_MQTT')
    if pid:
        row['prefix'] = f'vfactory/{pid}/'
        row['name'] = _tr('虚拟工厂（{v}）', v=pname or pid)
    if ds:
        db.update(c, 'datasource', ds['id'], row, raw=True)
    if env('HM_VF_HTTP'):
        db.set_setting(c, 'vf_http', env('HM_VF_HTTP').rstrip('/'), _tr('虚拟工厂接口地址'))
    if env('HM_VF_TOKEN'):
        db.set_setting(c, 'vf_token', env('HM_VF_TOKEN'), _tr('虚拟工厂会话令牌（客户端每次启动时更新）'))
    db.set_setting(c, 'company', pname or _tr('教学工厂'), _tr('公司名称'))
    db.set_setting(c, 'edu', '1', _tr('蜂元教学 MES'))


def edu_user():
    from .auth import user_by_name
    return user_by_name(EDU_USER)


# ---------------- 自动导入、跟随客户端退出 ----------------
async def auto_import():
    """第一次启动（还没有设备）时自动从虚拟工厂导入设备、产线、点表、刀具；虚拟工厂还没就绪就每 3 秒再试，最多 2 分钟。"""
    from . import db
    from .collector import import_vf
    loop = asyncio.get_running_loop()
    for i in range(40):
        with db.engine.connect() as c:
            has = c.execute(sa.select(sa.func.count()).select_from(db.TABLES['equipment'])).scalar()
        if has:
            STATE['import'] = STATE['import'] or 'ok'
            return
        if not env('HM_VF_HTTP'):
            STATE['import'] = 'no_vf'
            return

        def go():
            with db.engine.begin() as c:
                ds = db.get(c, 'datasource', code='VF')
                return import_vf(c, ds, {}, edu_user())
        try:
            r = await loop.run_in_executor(None, go)
            STATE['import'], STATE['imported_at'] = 'ok', time.time()
            log.info(_tr('从虚拟工厂导入：%s'), r.get('msg'))
            return
        except Exception as e:                     # noqa: BLE001  虚拟工厂还没起来
            STATE['import'] = _tr('等待虚拟工厂：{getattr}', getattr=getattr(e, "detail", e))
            await asyncio.sleep(3 if i < 20 else 6)


def _pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000 | 0x1000, False, int(pid))
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


async def watch_parent():
    pid = int(env('HM_WATCH_PID', '0') or 0)
    if not pid:
        return
    while True:
        await asyncio.sleep(2)
        if not _pid_alive(pid):
            log.info(_tr('客户端进程 %s 已退出，蜂元教学 MES 退出'), pid)
            logging.shutdown()
            os._exit(0)


# ---------------- 接口 ----------------
router = APIRouter()


def _key_ok(request: Request) -> bool:
    k = env('HM_EDU_KEY')
    return bool(k) and hmac.compare_digest(request.headers.get('x-hm-key', ''), k)


def need_key(request: Request):
    if not _key_ok(request):
        raise HTTPException(403, _tr('只有虚拟工厂客户端能调用'))


def _user_or_key(request: Request):
    if _key_ok(request):
        return
    from .auth import current_user
    current_user(request)


@router.get('/api/edu/info')
def info():
    """公开：前端启动时取品牌和本机工厂。"""
    return {'edu': EDU, 'brand': BRAND, 'plant': {'id': env('HM_PLANT'), 'name': env('HM_PLANT_NAME')}}


@router.post('/api/edu/ticket')
def ticket(request: Request):
    """客户端：换一个一次性登录票（2 分钟内有效），放在内嵌页面地址的 #edu= 里。"""
    need_key(request)
    now = time.time()
    for k in [k for k, v in _tickets.items() if v < now]:
        _tickets.pop(k, None)
    t = secrets.token_urlsafe(20)
    _tickets[t] = now + 120
    return {'ticket': t}


@router.post('/api/edu/session')
def session(request: Request, body: dict = Body(...)):
    """网页：一次性登录票 → 本机学员的会话令牌。"""
    from .auth import make_token
    if (request.client.host if request.client else '') not in ('127.0.0.1', '::1', 'localhost', 'testclient'):
        raise HTTPException(403, _tr('只允许本机访问'))
    t = str(body.get('ticket') or '')
    if not t or _tickets.pop(t, 0) < time.time():
        raise HTTPException(401, _tr('登录票无效或已用过：请在虚拟工厂里重新打开 MES'))
    u = edu_user()
    return {'token': make_token(u, hours=24), 'user': {'username': u['username'], 'name': u['name'], 'roles': u['roles']}}


@router.get('/api/edu/status')
def status(request: Request):
    """客户端：运行状态（空闲多久、导入情况、数据量），用来显示状态和空闲时自动停止。"""
    need_key(request)
    from . import db
    from .collector import COLLECTOR
    from .db import clock
    with db.engine.connect() as c:
        n = {k: c.execute(sa.select(sa.func.count()).select_from(db.TABLES[k])).scalar() for k in ('equipment', 'work_order', 'report', 'part', 'ncr')}
    return {'edu': EDU, 'plant': env('HM_PLANT'), 'started': STATE['started'], 'last_activity': STATE['last'],
            'idle_s': round(time.time() - STATE['last'], 1), 'requests': STATE['requests'], 'import': STATE['import'],
            'collector': {str(k): v for k, v in COLLECTOR.status.items()}, 'counts': n, 'data_clock': db.jsonable(clock.now()), 'pid': os.getpid(),
            **source_info()}


@router.post('/api/edu/import')
def reimport(request: Request):
    """客户端：重新从虚拟工厂导入（工厂改了设备之后）。"""
    need_key(request)
    from . import db
    from .collector import import_vf
    with db.engine.begin() as c:
        ds = db.get(c, 'datasource', code='VF')
        r = import_vf(c, ds, {}, edu_user())
    STATE['import'], STATE['imported_at'] = 'ok', time.time()
    return r


@router.post('/api/edu/check')
def check(request: Request, body: dict = Body(...)):
    """评分取数：一条声明式检查 {query, field?, where?, answer_key?, answers?} → {value}（见 QUERIES）。"""
    _user_or_key(request)
    try:
        return {'value': evaluate(body, body.get('answers') or {})}
    except KeyError as e:
        raise HTTPException(400, _tr('不认识的检查：{e}', e=e))


@router.post('/api/edu/snapshot')
def snapshot(request: Request, body: dict = Body(...)):
    """评分取数（一次取多条）：{rules: [...], answers: {...}} → {values: {rule.key: value}, at}。客户端交作业时把它带上，服务器按快照复评。"""
    _user_or_key(request)
    from .db import clock, jsonable
    ans = body.get('answers') or {}
    vals = {}
    for r in body.get('rules') or []:
        if isinstance(r, dict) and r.get('kind', 'mes') == 'mes' and r.get('key'):
            try:
                vals[r['key']] = evaluate(r, ans)
            except Exception:                      # noqa: BLE001
                vals[r['key']] = None
    return {'values': vals, 'at': jsonable(clock.now()), 'plant': env('HM_PLANT')}


# ---------------- 声明式检查 ----------------
def _norm(v):
    return str(v if v is not None else '').strip().upper().replace(' ', '')


def _as_list(v):
    return v if isinstance(v, (list, tuple)) else [v] if v not in (None, '') else []


def _wo_rows(c, where):
    from . import db
    wt, mt = db.TABLES['work_order'], db.TABLES['material']
    q = sa.select(wt).select_from(wt.outerjoin(mt, mt.c.id == wt.c.product))
    if where.get('product'):
        q = q.where(sa.or_(mt.c.code == where['product'], mt.c.name == where['product']))
    st = _as_list(where.get('status'))
    if st:
        q = q.where(wt.c.status.in_(st))
    for k, col in (('qty_gte', wt.c.qty), ('done_gte', wt.c.qty_done)):
        if where.get(k) is not None:
            q = q.where(col >= float(where[k]))
    if where.get('qty_lte') is not None:
        q = q.where(wt.c.qty <= float(where['qty_lte']))
    if where.get('customer'):
        q = q.where(wt.c.customer == where['customer'])
    return [dict(r) for r in c.execute(q).mappings()]


def _oee_rows(where):
    from .services.equipment import oee
    rows = oee(hours=int(where.get('hours') or 2), user=None)['rows']
    et = _as_list(where.get('etype'))
    if et:
        rows = [r for r in rows if r['etype'] in et]
    return [r for r in rows if r.get('OEE') is not None]


def q_work_order_count(c, rule, where, answers):
    return len(_wo_rows(c, where))


def q_work_order_done(c, rule, where, answers):
    return sum(int(r['qty_done'] or 0) for r in _wo_rows(c, where))


def q_report_count(c, rule, where, answers):
    from . import db
    rt = db.TABLES['report']
    q = sa.select(sa.func.count()).select_from(rt)
    if where.get('source'):
        q = q.where(rt.c.source.in_(_as_list(where['source'])))
    if where.get('work_order_product'):
        wids = [r['id'] for r in _wo_rows(c, {'product': where['work_order_product']})]
        q = q.where(rt.c.work_order.in_(wids or [-1]))
    return c.execute(q).scalar()


def q_report_good(c, rule, where, answers):
    from . import db
    rt = db.TABLES['report']
    q = sa.select(sa.func.coalesce(sa.func.sum(rt.c.qty_good), 0))
    if where.get('work_order_product'):
        wids = [r['id'] for r in _wo_rows(c, {'product': where['work_order_product']})]
        q = q.where(rt.c.work_order.in_(wids or [-1]))
    return int(c.execute(q).scalar() or 0)


def q_oee_worst(c, rule, where, answers):
    """OEE 最低的设备（默认看最近 2 小时、加工中心）。有 answer_key 时：学员的回答在最差的 rank 台之内 → 1，否则 0。"""
    rows = sorted(_oee_rows(where), key=lambda r: r['OEE'])
    if not rows:
        return None
    ak = rule.get('answer_key')
    if ak:
        a = _norm(answers.get(ak))
        if not a:
            return 0
        rank = int(rule.get('rank') or 1)
        return 1 if any(a in (_norm(r['code']), _norm(r['name'])) for r in rows[:rank]) else 0
    return rows[0].get(rule.get('field') or 'code')


def q_oee_value(c, rule, where, answers):
    rows = _oee_rows(where)
    eq = _norm(where.get('equipment'))
    for r in rows:
        if _norm(r['code']) == eq or _norm(r['name']) == eq:
            return r.get(rule.get('field') or 'OEE')
    return None


def q_oee_count(c, rule, where, answers):
    return len(_oee_rows(where))


def q_ncr_count(c, rule, where, answers):
    from . import db
    nt = db.TABLES['ncr']
    q = sa.select(sa.func.count()).select_from(nt)
    if where.get('status'):
        q = q.where(nt.c.status.in_(_as_list(where['status'])))
    if where.get('disposition'):
        q = q.where(nt.c.disposition.in_(_as_list(where['disposition'])))
    if where.get('source'):
        q = q.where(nt.c.source.in_(_as_list(where['source'])))
    return c.execute(q).scalar()


def q_ncr_traced(c, rule, where, answers):
    """追溯作业（不用作答）：学员在不合格品的"原因分析"里写上了这个零件的加工机床和炉次（和 MES 追溯一致）的 NCR 条数。"""
    from . import db
    n = 0
    for r in db.rows(c, 'ncr'):
        txt = _norm(r.get('root_cause'))
        if not txt or not r.get('sn'):
            continue
        p = db.get(c, 'part', sn=r['sn'])
        if not p or not (p['machine'] or p['heat']):
            continue
        if (not p['machine'] or _norm(p['machine']) in txt) and (not p['heat'] or _norm(p['heat']) in txt):
            n += 1
    return n


def q_repair_for_worst_oee(c, rule, where, answers):
    """OEE 作业（不用作答）：给 OEE 最差的 rank 台设备之一开了维修工单 → 1，否则 0。where: hours、etype、rank。"""
    from . import db
    rows = sorted(_oee_rows(where), key=lambda r: r['OEE'])
    if not rows:
        return None
    worst = {r['id'] for r in rows[:int(where.get('rank') or rule.get('rank') or 1)]}
    rt = db.TABLES['repair_order']
    n = c.execute(sa.select(sa.func.count()).select_from(rt).where(rt.c.equipment.in_(list(worst)))).scalar()
    return 1 if n else 0


def q_part_count(c, rule, where, answers):
    from . import db
    pt = db.TABLES['part']
    q = sa.select(sa.func.count()).select_from(pt)
    if where.get('status'):
        q = q.where(pt.c.status.in_(_as_list(where['status'])))
    return c.execute(q).scalar()


def q_trace_part(c, rule, where, answers):
    """一个零件的追溯字段（heat 炉次 / machine 机床 / status / station / work_order）。sn 来自 where.sn 或 answers[sn_key]。"""
    from . import db
    sn = str(where.get('sn') or answers.get(rule.get('sn_key') or 'sn') or '').strip()
    p = db.get(c, 'part', sn=sn) if sn else None
    if not p:
        return None
    return p.get(rule.get('field') or 'heat')


def q_trace_ncr_match(c, rule, where, answers):
    """追溯作答核对：学员写的零件码是不合格件（有 NCR、报废或返修过），并且写的机床和炉次都和 MES 里的追溯一致 → 1，否则 0。
    answers 的键由 sn_key / machine_key / heat_key 指定（默认 sn / machine / heat）。"""
    from . import db
    sn = str(answers.get(rule.get('sn_key') or 'sn') or '').strip()
    if not sn:
        return 0
    p = db.get(c, 'part', sn=sn)
    if not p:
        return 0
    bad = p['status'] in ('scrap', 'rework') or (p['rework_count'] or 0) > 0 or bool(db.get(c, 'ncr', sn=sn))
    if not bad:
        return 0
    m_ok = _norm(answers.get(rule.get('machine_key') or 'machine')) == _norm(p['machine']) if p['machine'] else True
    h_ok = _norm(answers.get(rule.get('heat_key') or 'heat')) == _norm(p['heat']) if p['heat'] else True
    return 1 if (m_ok and h_ok) else 0


def _spc(where):
    from .services.quality import spc
    return spc(char=where.get('char') or 'BORE_DIA', station=where.get('station') or '', n=int(where.get('n') or 125), sub=int(where.get('sub') or 5), user=None)


def q_spc_stable(c, rule, where, answers):
    """SPC 是否受控：数据够、没有判异点 → 1，否则 0。有 answer_key 时核对学员的判断（true/"稳定" = 受控）是否和 MES 一致 → 1 / 0。"""
    s = _spc(where)
    if not s.get('enough'):
        return None
    stable = 0 if s.get('rules') else 1
    ak = rule.get('answer_key')
    if ak:
        a = answers.get(ak)
        if a is None or a == '':
            return 0
        said = a if isinstance(a, bool) else str(a).strip().lower() in ('1', 'true', 'yes', '稳定', '受控', '是')
        return 1 if int(bool(said)) == stable else 0
    return stable


def q_spc_value(c, rule, where, answers):
    s = _spc(where)
    if not s.get('enough'):
        return None
    f = rule.get('field') or 'Cpk'
    if f == 'violations':
        return len(s.get('rules') or [])
    return s.get(f)


QUERIES = {
    'work_order.count': q_work_order_count,     # where: product, status(可多个), qty_gte, qty_lte, done_gte, customer
    'work_order.done': q_work_order_done,       # 完工数合计
    'report.count': q_report_count,             # 报工条数；where: source, work_order_product
    'report.good': q_report_good,               # 报工合格数合计
    'oee.worst': q_oee_worst,                   # field（默认 code）或 answer_key + rank；where: hours, etype
    'oee.value': q_oee_value,                   # where.equipment 的 OEE（field 可选 A/P/Q/OEE）
    'oee.count': q_oee_count,                   # 有 OEE 数据的设备台数
    'ncr.count': q_ncr_count,                   # where: status, disposition, source
    'ncr.traced': q_ncr_traced,                 # 原因分析里写对了机床和炉次的 NCR 条数
    'repair.for_worst_oee': q_repair_for_worst_oee,   # 给 OEE 最差的设备开了维修工单（1/0）
    'part.count': q_part_count,
    'trace.part': q_trace_part,                 # field: heat / machine / status / station
    'trace.ncr_match': q_trace_ncr_match,       # 作答核对
    'spc.stable': q_spc_stable,                 # where.char；可 answer_key
    'spc.value': q_spc_value,                   # field: Cpk / Ppk / mean / count / violations
}


def evaluate(rule: dict, answers: dict | None = None):
    from . import db
    q = rule.get('query')
    if q not in QUERIES:
        raise KeyError(q)
    with db.engine.connect() as c:
        v = QUERIES[q](c, rule, rule.get('where') or {}, answers or {})
    if isinstance(v, float):
        v = round(v, 4)
    return v


# ---------------- 挂到应用上 ----------------
def install(app):
    """build_app 里调用：客户端接口、活动时间（空闲自动停止用）、自动导入、跟随客户端退出。"""
    app.include_router(router)

    @app.middleware('http')
    async def edu_mw(request: Request, call_next):
        p = request.url.path
        if p.startswith('/api/') and not p.startswith('/api/edu/') and p != '/api/clock':
            STATE['last'] = time.time()            # 用户在用（页面轮询的数据时钟不算）
            STATE['requests'] += 1
        elif not p.startswith('/api/'):
            STATE['last'] = time.time()
        return await call_next(request)

    @app.on_event('startup')
    async def _edu_start():
        asyncio.create_task(auto_import())
        asyncio.create_task(watch_parent())

