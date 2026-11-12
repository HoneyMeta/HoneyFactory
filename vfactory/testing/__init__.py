"""联调工作区（MES 开发商）：测试剧本、无界面运行（CI）、报文监视。

接口
  GET    /api/p/{pid}/tests                         剧本列表（含最近一次结果）
  POST   /api/p/{pid}/tests          {name, script}  新建     → {id}
  GET    /api/p/{pid}/tests/{tid}                    剧本详情
  PUT    /api/p/{pid}/tests/{tid}    {name?, script}
  DELETE /api/p/{pid}/tests/{tid}
  POST   /api/p/{pid}/tests/{tid}/run                运行（后台）→ {run_id}
  POST   /api/p/{pid}/tests/run      {script}        运行未保存的剧本（编辑器里试跑）→ {run_id}
  GET    /api/p/{pid}/tests/runs/{rid}               运行结果（每一步通过/失败），运行中也可以轮询
  POST   /api/p/{pid}/tests/runs/{rid}/cancel
  GET    /api/p/{pid}/tests/runs/{rid}/junit.xml     JUnit XML
  GET    /api/p/{pid}/tests/{tid}/runs               历史运行
  POST   /api/p/{pid}/tests/validate {script}        只检查格式
  GET    /api/p/{pid}/debug/messages?since=&filter=&mes=1&station=&prefix=   报文监视（订阅 vfactory/<工厂>/# 与 vda5050/v2/<工厂>/#，首次调用时开始抓）
  GET    /api/p/{pid}/debug/messages.csv|.jsonl?filter=&mes=&station=&prefix=  导出抓到的报文（最近 20000 条）
命令行：python -m vfactory test <剧本.json> [...] --config plants/x.yaml --junit out.xml（见 cli.py）
"""
from ..i18n import _tr, server_tr
import asyncio
import json
import os
import time

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from .. import store
from .runner import Runner, junit_xml, validate

SCHEMA = """
create table if not exists test_scripts(id integer primary key, org text default 'default', plant text, name text, body text, created text, updated text, username text);
create table if not exists test_runs(id integer primary key, plant text, script_id integer, name text, status text, result text, created text, finished text,
  username text);
"""
_ready = False


def ready():
    global _ready
    if not _ready:
        c = store.conn()
        with store._lock:
            c.executescript(SCHEMA)
            c.commit()
        _ready = True


def need_eng(request):
    u = request.state.user
    if u['role'] not in ('admin', 'engineer'):
        raise HTTPException(403, _tr('只有工程师和管理员可以运行测试剧本'))
    return u


def register(app, mgr):
    live: dict[int, dict] = {}            # 运行中的结果（rid → {result, runner}）
    sniffers: dict[str, object] = {}

    def row(r, full=False):
        ready()
        d = {'id': r['id'], 'plant': r['plant'], 'name': r['name'], 'created': r['created'], 'updated': r['updated'], 'username': r['username']}
        body = json.loads(r['body'] or '{}')
        d['steps'] = len(body.get('steps') or [])
        if full:
            d['script'] = body
        last = store.q('select id,status,created,finished from test_runs where script_id=? order by id desc limit 1', (r['id'],), one=True)
        d['last'] = last
        return d

    def get_script(pid, tid):
        ready()
        r = store.q('select * from test_scripts where id=? and plant=?', (tid, pid), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这个剧本'))
        return r

    def seed_samples(pid):
        """示例剧本（tests/scripts/*.json 里 plant 是本工厂的）：这个工厂第一次打开剧本列表时放进去，删掉后不再补。"""
        key = f'sample_tests:{pid}'
        if store.q('select 1 from settings where k=?', (key,), one=True) or store.q('select 1 from test_scripts where plant=?', (pid,), one=True):
            return
        d = os.path.join(store.ROOT, 'tests', 'scripts')
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not fn.endswith('.json') or fn.startswith('expect_fail'):      # 故意失败的剧本只给 CI 自检用，不放进示例
                continue
            try:
                with open(os.path.join(d, fn), encoding='utf-8') as f:
                    sc = json.load(f)
            except (OSError, ValueError):
                continue
            if sc.get('plant') != pid or validate(sc):
                continue
            store.x('insert into test_scripts(plant,name,body,created,updated,username) values(?,?,?,?,?,?)',
                    (pid, sc.get('name') or fn[:-5], json.dumps(sc, ensure_ascii=False), store.now(), store.now(), server_tr('示例数据')))
        store.x('insert or replace into settings(k,v) values(?,?)', (key, store.now()))

    @app.get('/api/p/{pid}/tests')
    async def tests(pid: str):
        rt = mgr.get(pid)
        ready()
        if not rt.sandbox:
            seed_samples(pid)
        return [row(r) for r in store.q('select * from test_scripts where plant=? order by id desc', (pid,))]

    @app.post('/api/p/{pid}/tests/validate')
    async def tests_validate(pid: str, body: dict = Body(...)):
        return {'errors': validate(body.get('script'))}

    @app.post('/api/p/{pid}/tests')
    async def test_new(pid: str, request: Request, body: dict = Body(...)):
        u = need_eng(request)
        mgr.get(pid)
        sc = body.get('script') or {}
        errs = validate(sc)
        if errs:
            raise HTTPException(400, _tr('；').join(errs[:5]))
        name = (body.get('name') or sc.get('name') or _tr('测试剧本'))[:80]
        sc['name'] = name
        ready()
        tid = store.x('insert into test_scripts(plant,name,body,created,updated,username) values(?,?,?,?,?,?)',
                      (pid, name, json.dumps(sc, ensure_ascii=False), store.now(), store.now(), u['username']))
        return {'ok': True, 'id': tid}

    @app.get('/api/p/{pid}/tests/{tid}')
    async def test_get(pid: str, tid: int):
        return row(get_script(pid, tid), full=True)

    @app.put('/api/p/{pid}/tests/{tid}')
    async def test_put(pid: str, tid: int, request: Request, body: dict = Body(...)):
        need_eng(request)
        r = get_script(pid, tid)
        sc = body.get('script') or json.loads(r['body'])
        errs = validate(sc)
        if errs:
            raise HTTPException(400, _tr('；').join(errs[:5]))
        name = (body.get('name') or sc.get('name') or r['name'])[:80]
        sc['name'] = name
        store.x('update test_scripts set name=?, body=?, updated=? where id=?', (name, json.dumps(sc, ensure_ascii=False), store.now(), tid))
        return {'ok': True}

    @app.delete('/api/p/{pid}/tests/{tid}')
    async def test_del(pid: str, tid: int, request: Request):
        need_eng(request)
        get_script(pid, tid)
        store.x('delete from test_scripts where id=?', (tid,))
        return {'ok': True}

    async def start_run(pid, script, sid, u):
        rt = mgr.get(pid)
        errs = validate(script)
        if errs:
            raise HTTPException(400, _tr('；').join(errs[:5]))
        if any(v['plant'] == pid and v['result']['status'] == 'running' for v in live.values()):
            raise HTTPException(409, _tr('这个工厂已有剧本在运行，请等它结束或取消'))
        ready()
        rid = store.x('insert into test_runs(plant,script_id,name,status,created,username) values(?,?,?,?,?,?)',
                      (pid, sid, script.get('name') or _tr('临时剧本'), 'running', store.now(), u['username']))
        rn = Runner(rt, script)
        live[rid] = {'plant': pid, 'result': rn.result, 'runner': rn}

        async def go():
            res = await rn.run()
            store.x('update test_runs set status=?, result=?, finished=? where id=?', (res['status'], json.dumps(res, ensure_ascii=False, default=str), store.now(), rid))
            await asyncio.sleep(30)
            live.pop(rid, None)
        live[rid]['task'] = asyncio.create_task(go())
        return {'ok': True, 'run_id': rid}

    @app.post('/api/p/{pid}/tests/run')
    async def run_inline(pid: str, request: Request, body: dict = Body(...)):
        u = need_eng(request)
        return await start_run(pid, body.get('script') or {}, None, u)

    @app.post('/api/p/{pid}/tests/{tid}/run')
    async def run_saved(pid: str, tid: int, request: Request):
        u = need_eng(request)
        r = get_script(pid, tid)
        return await start_run(pid, json.loads(r['body']), tid, u)

    def run_result(pid, rid):
        if rid in live and live[rid]['plant'] == pid:
            return {'id': rid, **live[rid]['result']}
        ready()
        r = store.q('select * from test_runs where id=? and plant=?', (rid, pid), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这次运行'))
        res = json.loads(r['result']) if r['result'] else {'name': r['name'], 'status': r['status'], 'steps': []}
        return {'id': rid, **res}

    @app.get('/api/p/{pid}/tests/runs/{rid}')
    async def run_get(pid: str, rid: int):
        return run_result(pid, rid)

    @app.post('/api/p/{pid}/tests/runs/{rid}/cancel')
    async def run_cancel(pid: str, rid: int, request: Request):
        need_eng(request)
        v = live.get(rid)
        if v and v['plant'] == pid:
            v['runner'].cancelled = True
        return {'ok': True}

    @app.get('/api/p/{pid}/tests/runs/{rid}/junit.xml')
    async def run_junit(pid: str, rid: int):
        res = run_result(pid, rid)
        return Response(junit_xml([res]), media_type='application/xml', headers={'Content-Disposition': f'attachment; filename=junit-{rid}.xml'})

    @app.get('/api/p/{pid}/tests/{tid}/runs')
    async def runs_of(pid: str, tid: int):
        ready()
        return store.q('select id,status,created,finished,username from test_runs where plant=? and script_id=? order by id desc limit 50', (pid, tid))

    # ---------------- 报文监视 ----------------
    async def sniffer_of(pid):
        from .sniffer import Sniffer
        sn = sniffers.get(pid)
        if sn is None or sn.dead:
            sn = sniffers[pid] = Sniffer(pid, mgr.args.mqtt)
            await sn.start()
        sn.touch()
        return sn

    @app.get('/api/p/{pid}/debug/messages')
    async def messages(pid: str, since: int = 0, filter: str = '', mes: int = 0, limit: int = 300, station: str = '', prefix: str = ''):
        """报文监视：每条有 recv（本机接收时间）和 sim（载荷里的仿真时间）；可按设备 station、主题前缀 prefix、关键字 filter 过滤。"""
        rt = mgr.get(pid)
        if rt.sandbox or not mgr.mqtt:
            return {'ok': False, 'msg': _tr('这个工厂没有 MQTT（沙箱或 MQTT 未启动）'), 'items': [], 'seq': 0}
        sn = await sniffer_of(pid)
        items = sn.since(since, filter, bool(mes), max(1, min(2000, limit)), station, prefix)
        return {'ok': True, 'items': items, 'seq': sn.seq, 'started': sn.started, 'count': sn.total, 'rate': sn.rate()}

    @app.get('/api/p/{pid}/debug/messages.{fmt}')
    async def messages_export(pid: str, fmt: str, filter: str = '', mes: int = 0, station: str = '', prefix: str = ''):
        """导出报文（csv / jsonl），范围是联调台开始抓以来的最近 20000 条。"""
        if fmt not in ('csv', 'jsonl'):
            raise HTTPException(404, _tr('只能导出 csv 或 jsonl'))
        rt = mgr.get(pid)
        if rt.sandbox or not mgr.mqtt:
            raise HTTPException(400, _tr('这个工厂没有 MQTT（沙箱或 MQTT 未启动）'))
        from .sniffer import export
        sn = await sniffer_of(pid)
        items = sn.since(0, filter, bool(mes), 20000, station, prefix)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        return Response(export(items, fmt), media_type='text/csv; charset=utf-8' if fmt == 'csv' else 'application/x-ndjson; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename=messages-{pid}-{stamp}.{fmt}'})
