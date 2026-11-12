"""编辑器接口：项目模型的草稿、应用、试运行、版本、模板、表达式试算、底图。"""
from .i18n import _tr
import asyncio
import base64
import copy
import json
import os
import time

from fastapi import Body, HTTPException, Request
from fastapi.responses import FileResponse

from . import store
from .flow import catalog
from .flow.expr import try_eval
from .flow.model import apply_ops, diff, expand, validate

from . import paths as _paths  # noqa: E402
DATA = _paths.DATA
HOT_LEGACY = {'mtbf_h', 'mttr_min'}


def _dir(*p):
    d = os.path.join(DATA, *p)
    os.makedirs(d, exist_ok=True)
    return d


def draft_path(pid):
    return os.path.join(_dir('drafts'), f'{pid}.json')


def load_draft(pid):
    p = draft_path(pid)
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        _migrate(d.get('model'))
        return d
    return None


def _migrate(m):
    """4.3：旧控制单元里的内置 PLC → 独立 PLC 块 + 信号线（和运行中的工厂 core.Plant 加载时一样，编号确定）。"""
    try:
        from .plc.migrate import migrate_model
        migrate_model(m)
    except Exception:       # noqa: BLE001  迁移失败不影响打开
        pass
    return m


def save_version(pid, model, user, note):
    d = _dir('versions', pid)
    n = len([f for f in os.listdir(d) if f.endswith('.json')]) + 1
    meta = {'n': n, 't': store.now(), 'user': user, 'note': note, 'blocks': len(model.get('blocks', [])), 'links': len(model.get('links', []))}
    with open(os.path.join(d, f'{n:04d}.json'), 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'model': model}, f, ensure_ascii=False)
    return meta


def versions(pid):
    d = _dir('versions', pid)
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        if f.endswith('.json'):
            with open(os.path.join(d, f), encoding='utf-8') as fh:
                out.append(json.load(fh)['meta'])
    return out


def get_version(pid, n):
    p = os.path.join(_dir('versions', pid), f'{int(n):04d}.json')
    if not os.path.exists(p):
        raise HTTPException(404, _tr('没有这个版本'))
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def saved_model(rt):
    """已保存（配置文件）里的模型；旧格式在内存里转成 2.0。"""
    from .server import read_plant
    m = read_plant(rt.path)
    if 'blocks' not in m:
        from .flow.model import to_v2
        m = to_v2(m)
    return _migrate(m)


def hot_apply(rt, m):
    """只改参数/位置时直接改运行中的工厂，仿真不中断；结构变了返回 False。"""
    cur = rt.build_cfg()
    if structure(cur) != structure(m):
        return False
    blocks = {b['id']: b for b in m['blocks']}
    for st in rt.plant.stations.values():
        b = blocks.get(st.id)
        if not b:
            continue
        legacy = catalog.BLOCK_TYPES.get(b['type'], {}).get('legacy')
        for k, val in (b.get('params') or {}).items():
            if legacy and k not in HOT_LEGACY and st.cfg.get(k) != val:
                return False
    for st in rt.plant.stations.values():
        b = blocks.get(st.id)
        if not b:
            continue
        st.cfg.update(copy.deepcopy(b.get('params') or {}))
        st.name = st.cfg['name'] = b.get('name', st.name)
        st.pos, st.size, st.rot = list(b['pos']), list(b['size']), b.get('rot', 0)
        st.failure.mtbf_h = float(st.cfg.get('mtbf_h') or 0)
        st.failure.mttr_min = float(st.cfg.get('mttr_min') or 30)
    rt.cfg = copy.deepcopy(m)
    rt.plant.cfg.update({k: m[k] for k in ('areas', 'plant') if k in m})
    rt.plant.name = m['plant'].get('name', rt.plant.name)
    return True


def _plan_cfg(p):
    """计划段的内容（不含订单进度），比较用。"""
    p = copy.deepcopy(p or {})
    p['orders'] = [{k: v for k, v in o.items() if k not in ('done', 'born', 'left', 'eta', 'late')} for o in p.get('orders') or []]
    return json.dumps(p, sort_keys=True, ensure_ascii=False, default=str)


def structure(model):
    """决定能否热更新：块（编号、类型、点位定义）和物料连线不变。"""
    ex = expand(model)
    return (sorted((b['id'], b['type'], json.dumps(b.get('signals') or [], sort_keys=True), json.dumps(b.get('bindings') or [], sort_keys=True))
                   for b in model.get('blocks', [])),
            sorted((l['from'], l.get('from_port'), l['to'], l.get('to_port'), l.get('via') or '', l.get('capacity') or 0,
                    json.dumps({k: l.get(k) for k in ('products', 'cond', 'weight')}, sort_keys=True))
                   for l in model.get('links', []) if l.get('kind', 'material') == 'material'),
            sorted(ex['buffers'].items()))


def register(app, mgr):
    def need(request, role='engineer'):
        u = request.state.user
        if not store.role_ok(u, role):
            raise HTTPException(403, _tr('当前账号没有这个权限'))
        return u

    @app.get('/api/catalog')
    async def cat():
        return catalog.public()

    @app.get('/api/p/{pid}/model')
    async def model_get(pid: str):
        rt = mgr.get(pid)
        cur = rt.build_cfg()
        d = load_draft(pid)
        m = d['model'] if d else cur
        return {'model': m, 'draft': bool(d), 'draft_saved': d['saved'] if d else None, 'validation': validate(m), **_state(rt, m)}

    @app.put('/api/p/{pid}/model')
    async def model_put(pid: str, request: Request, body: dict = Body(...)):
        u = need(request)
        m = _migrate(body['model'])
        with open(draft_path(pid), 'w', encoding='utf-8') as f:
            json.dump({'model': m, 'saved': store.now(), 'user': u['username']}, f, ensure_ascii=False)
        return {'ok': True, 'validation': validate(m), **_state(mgr.get(pid), m)}

    def _state(rt, m):
        """running_changes：草稿相对已保存的改动；live：运行中已生效但未保存的；structural：结构改动还没生效。"""
        sv = saved_model(rt)
        cur = rt.build_cfg()
        nop = lambda x: {k: v for k, v in x.items() if k != 'plan'}     # 计划的完成进度每分钟都在变，不算模型改动
        return {'running_changes': diff(nop(sv), nop(m)), 'live_changes': diff(nop(sv), nop(cur)), 'structural': structure(cur) != structure(m)}

    @app.post('/api/p/{pid}/model/hot')
    async def model_hot(pid: str, request: Request, body: dict = Body(...)):
        """暂停中改参数/位置：立即作用到运行中的工厂（不写配置文件，不存版本）。"""
        need(request)
        rt = mgr.get(pid)
        m = body['model']
        if not validate(m)['ok']:
            return {'ok': False, 'reason': 'invalid', **_state(rt, m)}
        ok = hot_apply(rt, m)
        if ok:
            rt.dirty = True
        return {'ok': ok, 'reason': '' if ok else 'structure', **_state(rt, m)}

    @app.delete('/api/p/{pid}/model/draft')
    async def model_discard(pid: str, request: Request):
        need(request)
        p = draft_path(pid)
        if os.path.exists(p):
            os.remove(p)
        return {'ok': True}

    @app.post('/api/p/{pid}/model/apply')
    async def model_apply(pid: str, request: Request, body: dict = Body(default={})):
        """把草稿应用到运行中的工厂：只有参数/位置变化时热更新，结构变化时重建并预热。"""
        u = need(request)
        rt = mgr.get(pid)
        d = load_draft(pid)
        m = body.get('model') or (d['model'] if d else None)
        if not m:
            raise HTTPException(400, _tr('没有草稿'))
        v = validate(m)
        if not v['ok']:
            raise HTTPException(400, _tr('模型有 {error} 个错误，先在「检查」面板里处理', error=v['summary']['error']))
        cur = rt.build_cfg()
        sv = saved_model(rt)
        changes = diff(sv, m)
        if not changes and not diff(cur, m):
            return {'ok': True, 'mode': 'none', 'msg': _tr('没有改动')}
        save_version(pid, sv, u['username'], _tr('应用前自动备份')) if not versions(pid) else None
        hot = not body.get('rebuild') and hot_apply(rt, m)
        if hot:
            rt.save()
            mode = 'hot'
        else:
            from .server import write_yaml
            m2 = copy.deepcopy(m)
            # 4.7：计划在"生产计划"页改、应用到运行中的工厂；草稿里带的计划和已保存的一样（只是打开草稿时的旧副本）就以运行中的为准，
            #      草稿里的计划和已保存的不一样（载入了一个旧版本）才用草稿的
            if m2.get('plan') is None or _plan_cfg(m2.get('plan')) == _plan_cfg(sv.get('plan')):
                m2['plan'] = rt.plant.plan.export()
            write_yaml(rt.path, m2)
            await mgr.restart(pid)
            mode = 'rebuild'
        meta = save_version(pid, m, u['username'], body.get('note') or (_tr('参数更新') if mode == 'hot' else _tr('结构修改')))
        if os.path.exists(draft_path(pid)):
            os.remove(draft_path(pid))
        mgr.get(pid).plant.log('PLANT', 'layout', _tr('模型已应用（{v}，版本 {n}）', v=_tr('热更新') if mode == 'hot' else _tr('重建并预热'), n=meta['n']))
        return {'ok': True, 'mode': mode, 'version': meta['n'], 'changes': len(changes),
                'msg': _tr('已热更新，仿真不中断') if mode == 'hot' else _tr('结构有变化，已按新模型重建工厂并预热')}

    @app.post('/api/p/{pid}/model/tryrun')
    async def tryrun(pid: str, request: Request, body: dict = Body(...)):
        """试运行：当前模型和草稿各自在后台快进 N 小时，对比 KPI。"""
        need(request)
        from .experiment import compare, pool, run_one
        rt = mgr.get(pid)
        hours = max(1.0, min(48.0, float(body.get('hours', 8))))
        cur = rt.build_cfg()
        m = body['model']
        v = validate(m)
        if not v['ok']:
            raise HTTPException(400, _tr('草稿有错误，先处理"检查"面板里的问题'))
        loop = asyncio.get_running_loop()
        t0 = time.time()
        a, b = await asyncio.gather(loop.run_in_executor(pool(), run_one, cur, hours, 42, []), loop.run_in_executor(pool(), run_one, m, hours, 42, []))
        r = compare([{'name': _tr('当前运行'), 'changes': []}, {'name': _tr('草稿'), 'changes': []}], [[a], [b]])
        r['wall_s'] = round(time.time() - t0, 1)
        r['hours'] = hours
        return r

    @app.get('/api/p/{pid}/versions')
    async def vers(pid: str):
        return versions(pid)

    @app.get('/api/p/{pid}/versions/{n}')
    async def ver(pid: str, n: int):
        return get_version(pid, n)

    @app.get('/api/p/{pid}/versions/{n}/diff')
    async def ver_diff(pid: str, n: int, against: str = 'current'):
        a = get_version(pid, n)['model']
        if against == 'current':
            b = mgr.get(pid).build_cfg()
        elif against == 'draft':
            d = load_draft(pid)
            b = d['model'] if d else mgr.get(pid).build_cfg()
        else:
            b = get_version(pid, int(against))['model']
        return diff(a, b)

    @app.post('/api/p/{pid}/versions')
    async def ver_save(pid: str, request: Request, body: dict = Body(default={})):
        u = need(request)
        d = load_draft(pid)
        m = d['model'] if d else mgr.get(pid).build_cfg()
        return save_version(pid, m, u['username'], body.get('note') or _tr('手动保存'))

    # ---- 模板 ----
    @app.get('/api/templates')
    async def tpl_list():
        d = _dir('templates')
        out = []
        for f in sorted(os.listdir(d)):
            if f.endswith('.json'):
                with open(os.path.join(d, f), encoding='utf-8') as fh:
                    t = json.load(fh)
                out.append(t)
        return out

    @app.post('/api/templates')
    async def tpl_save(request: Request, body: dict = Body(...)):
        u = need(request)
        tid = f"T{int(time.time() * 1000)}"
        t = {'id': tid, 'name': body.get('name') or _tr('模板'), 'desc': body.get('desc') or '', 'blocks': body.get('blocks') or [], 'links': body.get('links') or [],
             'user': u['username'], 'created': store.now()}
        with open(os.path.join(_dir('templates'), f'{tid}.json'), 'w', encoding='utf-8') as f:
            json.dump(t, f, ensure_ascii=False)
        return t

    @app.delete('/api/templates/{tid}')
    async def tpl_del(tid: str, request: Request):
        need(request)
        p = os.path.join(_dir('templates'), f'{os.path.basename(tid)}.json')
        if os.path.exists(p):
            os.remove(p)
        return {'ok': True}

    # ---- 表达式试算 ----
    @app.post('/api/expr/check')
    async def expr_check(body: dict = Body(...)):
        import numpy as np
        rng = np.random.default_rng(1)
        item = {'type': 'A', 'pour_temp': 1420, 'mg': 0.04, 'defects': {}}
        vals = []
        for _ in range(int(body.get('samples', 5))):
            ok, v = try_eval(body.get('expr', ''), rng, item=item)
            if not ok:
                return {'ok': False, 'error': v}
            vals.append(v)
        return {'ok': True, 'samples': [round(x, 4) if isinstance(x, float) else x for x in vals]}

    # ---- 底图 ----
    @app.post('/api/p/{pid}/underlay')
    async def underlay_up(pid: str, request: Request, body: dict = Body(...)):
        need(request)
        data = body.get('data_url', '')
        if ',' not in data:
            raise HTTPException(400, _tr('图片格式不对'))
        raw = base64.b64decode(data.split(',', 1)[1])
        if len(raw) > 15 * 1024 * 1024:
            raise HTTPException(400, _tr('图片超过 15 MB'))
        with open(os.path.join(_dir('underlays'), f'{pid}.img'), 'wb') as f:
            f.write(raw)
        return {'ok': True, 'url': f'/api/p/{pid}/underlay.img?v={int(time.time())}'}

    @app.get('/api/p/{pid}/underlay.img')
    async def underlay_get(pid: str):
        p = os.path.join(_dir('underlays'), f'{pid}.img')
        if not os.path.exists(p):
            raise HTTPException(404)
        return FileResponse(p, media_type='image/png')

    @app.post('/api/p/{pid}/model/ops')
    async def model_ops(pid: str, request: Request, body: dict = Body(...)):
        """在给定模型上应用一组命令并校验（AI 变更集预览用）。"""
        need(request, 'viewer')
        m, inv = apply_ops(body['model'], body.get('ops') or [])
        return {'model': m, 'inverse': inv, 'validation': validate(m)}
