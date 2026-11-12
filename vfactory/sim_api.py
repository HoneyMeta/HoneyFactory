"""专业仿真接口：统计/桑基/甘特/能耗、数据表、子模型、DXF 底图、从此刻推演、优化、实验导出。

在 server.build_app 里 `sim_api.register(app, mgr)` 注册。所有接口在 /api 下，需要登录令牌。
"""
from .i18n import _tr
import base64
import copy
import json
import os
import re
import time

from fastapi import Body, HTTPException, Request
from fastapi.responses import FileResponse, Response

from . import analysis, datatables, store
from .api2 import need


def _data_dir(*p):
    from . import paths as _paths
    d = _paths.data(*p)
    os.makedirs(d, exist_ok=True)
    return d


def _b(v):
    return str(v).lower() not in ('0', 'false', 'no', '')


def persist_key(rt, key, value):
    """把模型的一个顶层段（tables / submodels / energy）写进：运行中的工厂、配置文件、编辑器草稿。不连带保存其他未保存的运行改动。"""
    from .server import read_yaml, write_yaml
    rt.cfg[key] = copy.deepcopy(value)
    rt.plant.cfg[key] = copy.deepcopy(value)
    rt.plant.__dict__.pop('_tbl_cache', None)
    if os.path.exists(rt.path):
        y = read_yaml(rt.path)
        y[key] = copy.deepcopy(value)
        write_yaml(rt.path, y)
    try:
        from .editor_api import draft_path, load_draft
        d = load_draft(rt.pid)
        if d:
            d['model'][key] = copy.deepcopy(value)
            with open(draft_path(rt.pid), 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def _decode(body):
    if body.get('data_url'):
        data = body['data_url']
        return base64.b64decode(data.split(',', 1)[1] if ',' in data else data)
    if body.get('text') is not None:
        return str(body['text']).encode('utf-8')
    raise HTTPException(400, _tr('没有文件内容（data_url 或 text）'))


def register(app, mgr):
    # ---------------- 统计分析 ----------------
    def win(p, hours, warmup):
        return analysis.window(p, hours, _b(warmup))

    @app.get('/api/p/{pid}/analysis/stats')
    async def a_stats(pid: str, hours: float = 24, warmup: str = '1'):
        p = mgr.get(pid).plant
        return analysis.stats(p, *win(p, hours, warmup))

    @app.get('/api/p/{pid}/analysis/bottleneck')
    async def a_bottleneck(pid: str, hours: float = 24, warmup: str = '1', timeline: str = '0'):
        """瓶颈分析（活跃期法 + 堵料/等料旁证），与报表、方案报告同一个函数、同一个区间规则。
        by_station = {设备: {rank, share, tie, util, bottleneck, group}} 给工作台按利用率/瓶颈着色用。"""
        p = mgr.get(pid).plant
        return analysis.bottleneck(p, *win(p, hours, warmup), timeline=_b(timeline))

    @app.get('/api/p/{pid}/analysis/sankey')
    async def a_sankey(pid: str, hours: float = 24, level: str = 'block', warmup: str = '1'):
        p = mgr.get(pid).plant
        return analysis.sankey(p, *win(p, hours, warmup), level=level)

    @app.get('/api/p/{pid}/analysis/gantt')
    async def a_gantt(pid: str, by: str = 'resource', hours: float = 8, ids: str = '', order: str = '', limit: int = 60, warmup: str = '0'):
        p = mgr.get(pid).plant
        t0, t1 = win(p, hours, warmup)
        if by == 'resource':
            return analysis.gantt_resource(p, t0, t1, [x for x in ids.split(',') if x] or None)
        if by not in ('order', 'part'):
            raise HTTPException(400, _tr('by 只能是 resource / order / part'))
        return analysis.gantt_orders(p, t0, t1, by=by, order=order or None, limit=max(1, min(300, limit)))

    @app.get('/api/p/{pid}/analysis/energy')
    async def a_energy(pid: str, hours: float = 24, warmup: str = '1'):
        p = mgr.get(pid).plant
        return analysis.energy(p, *win(p, hours, warmup))

    @app.get('/api/p/{pid}/energy/settings')
    async def e_get(pid: str):
        return analysis.energy_settings(mgr.get(pid).cfg)

    @app.put('/api/p/{pid}/energy/settings')
    async def e_put(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        e = {}
        tou = []
        for x in body.get('tou') or []:
            if not re.match(r'^\d{1,2}:\d{2}$', str(x.get('start', ''))) or not re.match(r'^\d{1,2}:\d{2}$', str(x.get('end', ''))):
                raise HTTPException(400, _tr('时段 {get} 的起止时间格式应为 HH:MM', get=x.get("name")))
            tou.append({'name': str(x.get('name') or _tr('时段')), 'start': x['start'], 'end': x['end'], 'price': float(x.get('price') or 0)})
        e['tou'] = tou
        for k in ('default_price', 'demand_price', 'co2_kg_per_kwh'):
            if body.get(k) is not None:
                e[k] = float(body[k])
        persist_key(rt, 'energy', e)
        return analysis.energy_settings(rt.cfg)

    # ---------------- 数据表 ----------------
    def tables(rt):
        return copy.deepcopy(datatables.tables_of(rt.cfg))

    def used_by(rt, name):
        out = []
        for b in rt.cfg.get('blocks', []):
            p = b.get('params') or {}
            if p.get('table') == name or any(isinstance(v, str) and f"tbl('{name}'" in v.replace('"', "'") for v in p.values()):
                out.append({'id': b['id'], 'name': b.get('name', b['id'])})
        return out

    @app.get('/api/p/{pid}/tables')
    async def t_list(pid: str, full: str = '0'):
        rt = mgr.get(pid)
        out = []
        for t in tables(rt):
            d = {'name': t['name'], 'desc': t.get('desc', ''), 'columns': t.get('columns') or [], 'n_rows': len(t.get('rows') or []), 'used_by': used_by(rt, t['name'])}
            if _b(full):
                d['rows'] = t.get('rows') or []
            out.append(d)
        return out

    @app.get('/api/p/{pid}/tables/{name}')
    async def t_get(pid: str, name: str):
        rt = mgr.get(pid)
        t = datatables.find(rt.cfg, name)
        if not t:
            raise HTTPException(404, _tr('没有这个数据表'))
        return {**t, 'used_by': used_by(rt, name)}

    def _check_name(nm):
        nm = str(nm or '').strip()
        if not nm or len(nm) > 40 or re.search(r'[\\/\'"]', nm):
            raise HTTPException(400, _tr('表名为空、太长或含有引号/斜杠'))
        return nm

    @app.put('/api/p/{pid}/tables/{name}')
    async def t_put(pid: str, name: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        new_name = _check_name(body.get('name') or name)
        cols = [str(c) for c in body.get('columns') or []]
        if not cols:
            raise HTTPException(400, _tr('至少要有一列'))
        t = datatables.normalize(cols, body.get('rows') or [])
        t.update(name=new_name, desc=str(body.get('desc') or ''))
        ts = [x for x in tables(rt) if x['name'] not in (name, new_name)]
        ts.append(t)
        persist_key(rt, 'tables', ts)
        _reload_sources(rt, {name, new_name})
        return {**t, 'used_by': used_by(rt, new_name)}

    @app.delete('/api/p/{pid}/tables/{name}')
    async def t_del(pid: str, name: str, request: Request):
        need(request, 'engineer')
        rt = mgr.get(pid)
        persist_key(rt, 'tables', [x for x in tables(rt) if x['name'] != name])
        return {'ok': True}

    @app.post('/api/p/{pid}/tables/import')
    async def t_import(pid: str, request: Request, body: dict = Body(...)):
        """导入 CSV / Excel 为数据表（同名覆盖）。body: {name, filename, data_url | text}"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        raw = _decode(body)
        fn = body.get('filename') or 'data.csv'
        try:
            t = datatables.parse_file(fn, raw)
        except Exception as e:
            raise HTTPException(400, _tr('读取失败：{e}', e=e))
        nm = _check_name(body.get('name') or os.path.splitext(os.path.basename(fn))[0])
        t.update(name=nm, desc=str(body.get('desc') or _tr('从 {fn} 导入', fn=fn)))
        ts = [x for x in tables(rt) if x['name'] != nm] + [t]
        persist_key(rt, 'tables', ts)
        _reload_sources(rt, {nm})
        return {**t, 'n_rows': len(t['rows']), 'used_by': used_by(rt, nm)}

    @app.get('/api/p/{pid}/tables/{name}/export.csv')
    async def t_csv(pid: str, name: str):
        t = datatables.find(mgr.get(pid).cfg, name)
        if not t:
            raise HTTPException(404, _tr('没有这个数据表'))
        return Response(datatables.to_csv(t).encode('utf-8'), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + _q(name) + '.csv'})

    @app.post('/api/p/{pid}/tables/{name}/ops')
    async def t_ops(pid: str, name: str, body: dict = Body(default={})):
        """把工艺路线表 / BOM 表转成编辑命令（不直接改模型）。body: {kind: routing|bom, model?}。
        返回的 ops 可交给 /model/ops 预览、再 PUT /model 写入草稿，在工作台里应用。"""
        rt = mgr.get(pid)
        t = datatables.find(rt.cfg, name)
        if not t:
            raise HTTPException(404, _tr('没有这个数据表'))
        model = body.get('model') or _model(rt)
        kind = body.get('kind') or 'routing'
        if kind == 'routing':
            return datatables.routing_ops(model, t)
        if kind == 'bom':
            return datatables.bom_ops(model, t)
        raise HTTPException(400, _tr('kind 只能是 routing / bom'))

    def _reload_sources(rt, names):
        p = rt.plant
        for st in p.all_stations():
            if st.kind == 'source' and (st.cfg.get('table') in names):
                st.sched = st._load_schedule()
                st.si = sum(1 for r in st.sched or [] if r[0] <= p.t)
                st.rep = 0

    def _model(rt):
        try:
            from .editor_api import load_draft
            d = load_draft(rt.pid)
            if d:
                return d['model']
        except Exception:
            pass
        return rt.build_cfg()

    # ---------------- 子模型 ----------------
    @app.get('/api/p/{pid}/submodels')
    async def sm_list(pid: str):
        from .flow.model import submodel_ports
        rt = mgr.get(pid)
        defs = []
        for d in rt.cfg.get('submodels') or []:
            en, ex = submodel_ports(d)
            used = [b['id'] for b in rt.cfg.get('blocks', []) if b['type'] == 'submodel' and (b.get('params') or {}).get('def') in (d.get('id'), d.get('name'))]
            defs.append({**d, 'entry_resolved': en, 'exit_resolved': ex, 'used_by': used})
        tpls = []
        tdir = _data_dir('templates')
        for f in sorted(os.listdir(tdir)):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(tdir, f), encoding='utf-8') as fh:
                        t = json.load(fh)
                    tpls.append({'id': t.get('id'), 'name': t.get('name'), 'blocks': len(t.get('blocks') or [])})
                except (OSError, ValueError):
                    pass
        return {'defs': defs, 'templates': tpls}

    def _check_def(d):
        if not d.get('blocks'):
            raise HTTPException(400, _tr('子模型至少要有一个块'))
        ids = [b.get('id') for b in d['blocks']]
        if len(set(ids)) != len(ids):
            raise HTTPException(400, _tr('子模型里块编号重复'))
        for e in d.get('expose') or []:
            for tg in e.get('targets') or []:
                if str(tg).split('.', 1)[0] not in ids:
                    raise HTTPException(400, _tr('暴露参数 {get} 的目标 {tg} 不在子模型里', get=e.get("name"), tg=tg))
        return d

    @app.put('/api/p/{pid}/submodels/{sid}')
    async def sm_put(pid: str, sid: str, request: Request, body: dict = Body(...)):
        """新建/更新子模型定义：{name, blocks, links, entry?, exit?, expose?:[{name,label,default,targets:['M1.time']}]}"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        if not re.match(r'^[A-Za-z][A-Za-z0-9_\-]{0,31}$', sid):
            raise HTTPException(400, _tr('子模型编号只能用字母开头的字母、数字、下划线'))
        d = _check_def({'id': sid, 'name': body.get('name') or sid, 'desc': body.get('desc') or '', 'blocks': body.get('blocks') or [],
                        'links': body.get('links') or [], 'entry': body.get('entry'), 'exit': body.get('exit'), 'expose': body.get('expose') or []})
        defs = [x for x in rt.cfg.get('submodels') or [] if x.get('id') != sid] + [d]
        persist_key(rt, 'submodels', defs)
        return d

    @app.post('/api/p/{pid}/submodels/from-template')
    async def sm_from_tpl(pid: str, request: Request, body: dict = Body(...)):
        """把编辑器保存的模板（T…）变成本工厂的子模型定义。body: {template, id?, name?, expose?}"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        tid = os.path.basename(str(body.get('template') or ''))
        path = os.path.join(_data_dir('templates'), f'{tid}.json')
        if not os.path.exists(path):
            raise HTTPException(404, _tr('没有这个模板'))
        with open(path, encoding='utf-8') as f:
            t = json.load(f)
        sid = body.get('id') or re.sub(r'[^A-Za-z0-9_]', '', 'SM' + tid[-6:])
        d = _check_def({'id': sid, 'name': body.get('name') or t.get('name') or sid, 'desc': t.get('desc', ''), 'blocks': t.get('blocks') or [],
                        'links': t.get('links') or [], 'expose': body.get('expose') or []})
        defs = [x for x in rt.cfg.get('submodels') or [] if x.get('id') != sid] + [d]
        persist_key(rt, 'submodels', defs)
        return d

    @app.delete('/api/p/{pid}/submodels/{sid}')
    async def sm_del(pid: str, sid: str, request: Request):
        need(request, 'engineer')
        rt = mgr.get(pid)
        persist_key(rt, 'submodels', [x for x in rt.cfg.get('submodels') or [] if x.get('id') != sid])
        return {'ok': True}

    @app.post('/api/p/{pid}/submodels/expand')
    async def sm_expand(pid: str, body: dict = Body(...)):
        """预览：给定模型（默认当前模型）展开子模型后的块和连线（内部块带 _parent）。"""
        from .flow.model import flatten
        rt = mgr.get(pid)
        m = body.get('model') or _model(rt)
        fb, fl, rin, rout = flatten(m)
        return {'blocks': fb, 'links': fl, 'entry': rin, 'exit': rout}

    # ---------------- DXF 底图 ----------------
    @app.post('/api/p/{pid}/underlay/dxf')
    async def dxf_up(pid: str, request: Request, body: dict = Body(...)):
        """DXF → 折线（米）+ SVG 底图。body: {data_url | text, unit?: mm|cm|m|in|ft, layers?: [...], origin?: [x,y], flip_y?: true}
        返回 underlay 可直接写进 plant.underlay（编辑器 update_plant），polylines 用于吸附。"""
        need(request, 'engineer')
        from .dxf import DxfError, convert, to_svg
        mgr.get(pid)
        raw = _decode(body)
        if len(raw) > 60 * 1024 * 1024:
            raise HTTPException(400, _tr('DXF 超过 60 MB'))
        text = None
        for enc in ('utf-8', 'gbk', 'latin-1'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            org = body.get('origin') or [0, 0]
            res = convert(text, unit=body.get('unit'), layers=body.get('layers') or None, origin=(float(org[0]), float(org[1])),
                          flip_y=body.get('flip_y', True) is not False)
        except DxfError as e:
            raise HTTPException(400, str(e))
        svg = to_svg(res)
        with open(os.path.join(_data_dir('underlays'), f'{pid}.svg'), 'w', encoding='utf-8') as f:
            f.write(svg)
        x0, y0, x1, y1 = res['bbox']
        ul = {'url': f'/api/p/{pid}/underlay.svg?v={int(time.time())}', 'x': x0, 'y': y0, 'w': round(x1 - x0, 3), 'h': round(y1 - y0, 3),
              'opacity': 0.6, 'show': True, 'kind': 'dxf'}
        snap = res['polylines'] if _b(body.get('polylines', '1')) else []
        return {'underlay': ul, 'unit': res['unit'], 'scale': res['scale'], 'bbox': res['bbox'], 'w': res['w'], 'h': res['h'], 'layers': res['layers'],
                'n_polylines': len(res['polylines']), 'n_texts': len(res['texts']), 'truncated': res['truncated'], 'polylines': snap,
                'texts': res['texts'][:500]}

    @app.get('/api/p/{pid}/underlay.svg')
    async def dxf_svg(pid: str):
        p = os.path.join(_data_dir('underlays'), f'{os.path.basename(pid)}.svg')
        if not os.path.exists(p):
            raise HTTPException(404)
        return FileResponse(p, media_type='image/svg+xml')

    # ---------------- 从此刻推演 ----------------
    @app.post('/api/p/{pid}/fork')
    async def fork_run(pid: str, request: Request, body: dict = Body(default={})):
        """body: {hours: 4, reps: 1, name?, changes: [{type: param|setpoint|fault|enable|buffer, ...}]} → 基准 vs 改动的 KPI 预测。"""
        need(request, 'engineer')
        from .fork import fork
        rt = mgr.get(pid)
        return await fork(rt.plant, float(body.get('hours', 4)), body.get('changes') or [], int(body.get('reps', 1)), body.get('name') or _tr('改动后'))

    # ---------------- 优化 ----------------
    @app.post('/api/p/{pid}/optimize')
    async def opt_new(pid: str, request: Request, body: dict = Body(...)):
        """body: {name, hours, reps, budget, pop, method: ga|random, params:[{kind: param|buffer|add|crew, station,key|name|template|role, lo, hi, step | levels}],
        objectives:[{key, sense: max|min, weight?}], constraints:[{key, op: '<='|'>=', value}]}。进度和结果在 /experiments/{id}。"""
        import asyncio
        from .experiment import run_optimization
        u = need(request, 'engineer')
        rt = mgr.get(pid)
        spec = {k: body.get(k) for k in ('params', 'objectives', 'constraints', 'method', 'budget', 'pop', 'seed', 'warmup_h', 'search_seed') if body.get(k) is not None}
        spec['hours'] = max(0.5, min(168.0, float(body.get('hours', 8))))
        spec['reps'] = max(1, min(10, int(body.get('reps', 1))))
        spec['budget'] = max(2, min(200, int(body.get('budget', 24))))
        if not spec.get('params'):
            raise HTTPException(400, _tr('至少选一个可调参数'))
        eid = store.x('insert into experiments(plant,name,hours,reps,variants,status,progress,created,username) values(?,?,?,?,?,?,?,?,?)',
                      (pid, body.get('name') or _tr('参数优化'), spec['hours'], spec['reps'], json.dumps({'kind': 'optimize', **spec}, ensure_ascii=False),
                       'queued', 0, store.now(), u['username']))
        asyncio.create_task(run_optimization(eid, rt.build_cfg(), spec))
        return {'ok': True, 'id': eid}

    # ---------------- 实验导出 ----------------
    def _exp(eid):
        r = store.q('select * from experiments where id=?', (eid,), one=True)
        if not r or not r['result']:
            raise HTTPException(404, _tr('实验不存在或还没算完'))
        return r, json.loads(r['result'])

    @app.get('/api/p/{pid}/experiments/{eid}/export.csv')
    async def exp_csv(pid: str, eid: int):
        from .experiment import export_csv
        r, res = _exp(eid)
        return Response(export_csv(res).encode('utf-8'), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename=experiment-{eid}.csv'})

    @app.get('/api/p/{pid}/experiments/{eid}/export.xlsx')
    async def exp_xlsx(pid: str, eid: int):
        from .experiment import export_xlsx
        r, res = _exp(eid)
        return Response(export_xlsx(res, r['name']), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename=experiment-{eid}.xlsx'})


def _q(s):
    from urllib.parse import quote
    return quote(s)
