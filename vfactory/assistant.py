"""AI 助手（全站右下角）。

- 每条消息带上下文：当前页面、选中对象、视图、运行状态/回放时刻、草稿模型。
- 过程通过 SSE 推给前端：tool（人话进度）、proposal（修改方案卡片，先在副本上试算过）、action（场景/实验卡片）、
  wrote（服务端写的"已修改"回执）、navigate（带用户去某页/某对象/某时刻）、answer、error。
- 修改一律"先试算 → 给人看 → 凭令牌提交"：令牌绑定"这份改动 + 试算时的模型"，模型之后变过就拒绝，要求重新试算。
- 不替人做决定：不改真实设备，不发布排程；只改仿真模型草稿、断点、运行控制、场景和实验（场景/实验要用户点按钮）。
- 只读账号不提供写工具，服务端执行前再查一次权限；被拒绝作为工具结果返回给模型，而不是报错。
"""
from .i18n import _tr, variants
import asyncio
import copy
import hashlib
import json

from fastapi import Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import store
from .copilot import OPS_DOC, catalog_text, chat, model_text, run_tool
from .flow.model import apply_ops, diff, validate

MAX_ROUNDS = 10
PAGES = {'workbench': ('工作台（三维/流程图/平面图，运行与编辑）', 'workbench'), 'plan': ('生产计划', 'plan'), 'scenarios': ('场景', 'scenarios'),
         'experiments': ('实验对比', 'experiments'), 'reports': ('运行报表', 'reports'), 'signals': ('信号中心', 'signals'),
         'dataset': ('数据集', 'dataset'), 'help': ('帮助中心', '/help')}
WRITE_TOOLS = {'try_changes', 'apply_changes', 'propose_scenario', 'propose_experiment', 'set_breakpoint', 'sim_control', 'propose_plc_program'}

TOOLS = [
    {'type': 'function', 'function': {'name': 'get_runtime', 'description': '取设备的实时状态：状态、报警、功率、OEE、全部点位当前值、近期事件。',
                                      'parameters': {'type': 'object', 'properties': {'ids': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['ids']}}},
    {'type': 'function', 'function': {'name': 'get_report', 'description': '取近 N 小时的运行报表：产量、废品、能耗、设备时间构成、瓶颈、生产周期、结论。',
                                      'parameters': {'type': 'object', 'properties': {'hours': {'type': 'number'}}}}},
    {'type': 'function', 'function': {'name': 'get_trend', 'description': '取一个点位近 N 小时的曲线。key 形如 CNC1/Monitoring/Spindle/Load',
                                      'parameters': {'type': 'object', 'properties': {'key': {'type': 'string'}, 'hours': {'type': 'number'}}, 'required': ['key']}}},
    {'type': 'function', 'function': {'name': 'get_time_breakdown', 'description': '每台设备最近 N 小时的时间构成（运行/换型/缺料/堵料/故障/待机/计划停机/非班次，已去掉预热）、OEE 和全厂产出/在制品/周期/瓶颈。分析瓶颈和损失时优先用它。',
                                      'parameters': {'type': 'object', 'properties': {'hours': {'type': 'number'}}}}},
    {'type': 'function', 'function': {'name': 'forecast_from_now', 'description': '从此刻推演：复制运行中工厂当前的状态，一份照现在继续、一份按 changes 改动，各快进 hours 小时对比（不影响运行中的工厂）。changes 元素：{"type":"param","station":"M1","key":"time","value":"normal(50,3)"} / {"type":"setpoint","station":"..","tag":"..","value":..} / {"type":"fault","station":"..","kind":"..或clear"} / {"type":"enable","station":"..","value":false} / {"type":"buffer","name":"..","value":40}。适合回答"如果现在…会怎样"。',
                                      'parameters': {'type': 'object', 'properties': {'changes': {'type': 'array', 'items': {'type': 'object'}}, 'hours': {'type': 'number'}},
                                                     'required': ['changes']}}},
    {'type': 'function', 'function': {'name': 'get_plc', 'description': '读一台 PLC 块（PLC 是独立的设备，通过信号线控制设备/控制单元）：程序（语言、源码）、I/O 通道表（变量名、地址、方向、接到哪台设备的哪个点）、它控制的设备、运行状态、实时变量值和 I/O 值、编译检查结果。cell 填 PLC 块编号，也可以填它控制的设备编号（自动找到控制它的 PLC）。',
                                      'parameters': {'type': 'object', 'properties': {'cell': {'type': 'string'}}, 'required': ['cell']}}},
    {'type': 'function', 'function': {'name': 'propose_plc_program', 'description': '给 PLC 块写/改程序（ST 结构化文本；变量名用 get_plc 返回的 I/O 通道表里的名字），先编译检查，通过后以卡片给使用者，使用者点"下载到 PLC"才生效。cell 填 PLC 块编号或它控制的设备编号。有编译错误会返回错误，请修正后再提。',
                                      'parameters': {'type': 'object', 'properties': {'cell': {'type': 'string'}, 'summary': {'type': 'string'}, 'source': {'type': 'string', 'description': '完整 ST 程序（含 VAR 声明）'}},
                                                     'required': ['cell', 'source']}}},
    {'type': 'function', 'function': {'name': 'try_changes', 'description': '在模型副本上应用一组编辑命令、校验，并让"当前草稿"和"改后"各快进 hours 小时（同一随机种子）对比 KPI。返回校验结果、KPI 对比和 apply_token。所有修改都必须先经过这一步。',
                                      'parameters': {'type': 'object', 'properties': {'summary': {'type': 'string', 'description': '一句话说明改了什么'},
                                                                                     'ops': {'type': 'array', 'items': {'type': 'object'}},
                                                                                     'hours': {'type': 'number', 'description': '试算时长，默认 4，最多 12'}}, 'required': ['summary', 'ops']}}},
    {'type': 'function', 'function': {'name': 'apply_changes', 'description': '把试算过的修改写进草稿。只能在用户这一轮明确同意（如"应用""可以""就这么改"）后调用，token 用最近一次 try_changes 返回的。',
                                      'parameters': {'type': 'object', 'properties': {'token': {'type': 'string'}, 'ops': {'type': 'array', 'items': {'type': 'object'}},
                                                                                     'summary': {'type': 'string'}}, 'required': ['token', 'ops']}}},
    {'type': 'function', 'function': {'name': 'propose_scenario', 'description': '提出一个场景（按时间编排的故障/扰动），以卡片给用户，用户点按钮才保存/运行。',
                                      'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'descr': {'type': 'string'},
                                                                                     'steps': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['name', 'steps']}}},
    {'type': 'function', 'function': {'name': 'propose_experiment', 'description': '提出一个实验对比（基准自动加入），以卡片给用户，用户点按钮才开始。',
                                      'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'hours': {'type': 'number'},
                                                                                     'variants': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['name', 'variants']}}},
    {'type': 'function', 'function': {'name': 'set_breakpoint', 'description': '加一个断点：条件成立时仿真自动暂停并定位。cond 见说明。',
                                      'parameters': {'type': 'object', 'properties': {'cond': {'type': 'object'}, 'name': {'type': 'string'}, 'once': {'type': 'boolean'}},
                                                     'required': ['cond']}}},
    {'type': 'function', 'function': {'name': 'sim_control', 'description': '运行控制：play / pause / step（seconds 秒或 event:true 到下一事件）/ run_to（cond 条件或 hours 小时，后台进行）。',
                                      'parameters': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['play', 'pause', 'step', 'run_to']},
                                                                                     'seconds': {'type': 'number'}, 'event': {'type': 'boolean'}, 'cond': {'type': 'object'},
                                                                                     'hours': {'type': 'number'}, 'speed': {'type': 'number'}}, 'required': ['action']}}},
    {'type': 'function', 'function': {'name': 'go_to', 'description': '带用户去看：打开页面，或在工作台里切视图/选中对象/跳到回放时刻。why 写一句为什么去。',
                                      'parameters': {'type': 'object', 'properties': {'page': {'type': 'string', 'enum': list(PAGES)},
                                                                                     'view': {'type': 'string', 'enum': ['3d', 'graph', 'plan']},
                                                                                     'select': {'type': 'array', 'items': {'type': 'string'}},
                                                                                     'time': {'type': 'string', 'description': '回放时刻 YYYY-MM-DD HH:MM'},
                                                                                     'why': {'type': 'string'}}, 'required': ['why']}}},
]
COND_DOC = """断点/运行到 的条件 cond：{"kind":"state","id":"CNC3","state":"Stopped"} 进入某状态（Executing/Idle/Starved/Blocked/Setup/Stopped）；
{"kind":"state_for","id":"M1","state":"Blocked","minutes":5}；{"kind":"alarm","id":"CNC3"}（id 可省）；{"kind":"buffer","id":"cnc_in","op":"<","value":5}；
{"kind":"kpi","key":"good","op":">=","value":500}；{"kind":"tag","id":"FUR1","tag":"Bath/Temperature","op":">","value":1500}；
{"kind":"event","id":"CNC3","ekind":"fault"}；{"kind":"time","at":"2026-11-03 08:00"}"""


def sig(model, ops):
    return hashlib.sha256((json.dumps(model, sort_keys=True, ensure_ascii=False) + '|' + json.dumps(ops, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:20]


def describe_ops(ops, model):
    """服务端写的修改说明（不用模型的话）。"""
    by = {b['id']: b for b in model.get('blocks', [])}
    nm = lambda i: _tr('{get}（{i}）', get=by[i].get('name', i), i=i) if i in by else i
    out = []
    for o in ops:
        t = o.get('op')
        if t == 'add_block':
            b = o.get('block', {})
            out.append(_tr('新增 {get}「{get2}」（{get3}）', get=b.get('type'), get2=b.get('name', b.get('id')), get3=b.get('id')))
            by[b.get('id')] = b
        elif t == 'remove_block':
            out.append(_tr('删除 {nm}', nm=nm(o.get('id'))))
        elif t == 'update_block':
            out.append(_tr('修改 {nm}：', nm=nm(o.get('id'))) + _tr('；').join(f"{k} = {json.dumps(v, ensure_ascii=False)[:60]}" for k, v in (o.get('set') or {}).items()))
        elif t == 'add_link':
            l = o.get('link', {})
            out.append(_tr('连线 {nm} → {nm2}', nm=nm(l.get('from')), nm2=nm(l.get('to'))) + (_tr('（由 {via} 搬运）', via=l['via']) if l.get('via') else ''))
        elif t == 'remove_link':
            out.append(_tr('删除连线 {get}', get=o.get('id')))
        elif t == 'update_link':
            out.append(_tr('修改连线 {get}：', get=o.get('id')) + _tr('；').join(f"{k} = {v}" for k, v in (o.get('set') or {}).items()))
        else:
            out.append(t)
    return out


def phrase(fn, args, model):
    by = {b['id']: b.get('name', b['id']) for b in model.get('blocks', [])}
    ids = _tr('、').join(by.get(i, i) for i in (args.get('ids') or [])[:4])
    return {'get_runtime': _tr('正在读{v}的实时状态…', v=ids or _tr('设备')), 'get_report': _tr('正在看最近 {v:g} 小时的运行报表…', v=args.get('hours') or 8),
            'get_trend': _tr('正在看 {get} 的曲线…', get=args.get('key', '')), 'try_changes': _tr('正在副本上试算这个改动（快进 {min:g} 小时对比）…', min=min(12, args.get('hours') or 4)),
            'apply_changes': _tr('正在写入草稿…'), 'propose_scenario': _tr('正在编排场景…'), 'propose_experiment': _tr('正在设计实验…'),
            'set_breakpoint': _tr('正在设置断点…'), 'sim_control': _tr('正在操作仿真…'), 'go_to': _tr('正在打开…'),
            'get_time_breakdown': _tr('正在统计各设备的时间都花在哪…'), 'get_plc': _tr('正在读 {get} 的 PLC 程序和 I/O…', get=args.get('cell', '')), 'propose_plc_program': _tr('正在写 PLC 程序并编译检查…'), 'forecast_from_now': _tr('正在从此刻往后推演 {min:g} 小时…', min=min(12, args.get('hours') or 4))}.get(fn, '正在处理…')


def measure(model, ops, hours):
    """当前草稿 vs 改后，各快进 hours 小时（同一随机种子）。"""
    from .experiment import pool, run_one
    m2, _ = apply_ops(model, ops)
    f1 = pool().submit(run_one, copy.deepcopy(model), hours, 42, [])
    f2 = pool().submit(run_one, m2, hours, 42, [])
    a, b = f1.result(timeout=600), f2.result(timeout=600)
    rows = []
    for k, label, unit, better in (('good_per_h', _tr('小时产出'), _tr('件/h'), 1), ('good', _tr('合格入库'), _tr('件'), 1), ('scrap_rate', _tr('废品率'), '', -1), ('wip_avg', _tr('平均在制品'), _tr('件'), -1),
                                   ('lead_mean', _tr('平均生产周期'), 'h', -1), ('kwh_per_good', _tr('单件电耗'), 'kWh', -1)):
        x, y = a.get(k), b.get(k)
        d = (y - x) / x if isinstance(x, (int, float)) and isinstance(y, (int, float)) and x else None
        rows.append({'key': k, 'label': label, 'unit': unit, 'before': x, 'after': y, 'delta': round(d, 4) if d is not None else None,
                     'good': None if d is None or abs(d) < 0.005 else (d > 0) == (better > 0)})
    bn = lambda r: r['bottleneck'][0]['name'] if r.get('bottleneck') else '—'
    return {'hours': hours, 'rows': rows, 'bottleneck_before': bn(a), 'bottleneck_after': bn(b)}


def register(app, mgr):
    def user_of(request):
        return request.state.user

    def can_write(u):
        return u.get('role') in ('admin', 'engineer')

    def thread(tid, u):
        r = store.q('select * from assistant_threads where id=? and username=?', (tid, u['username']), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这个对话'))
        r['messages'] = json.loads(r['messages'] or '[]')
        return r

    @app.get('/api/assistant/threads')
    async def threads(request: Request, plant: str = ''):
        u = user_of(request)
        rows = store.q('select id,plant,title,messages,updated from assistant_threads where username=? order by updated desc limit 100', (u['username'],))
        return [{'id': r['id'], 'plant': r['plant'], 'title': r['title'], 'updated': r['updated'], 'count': len(json.loads(r['messages'] or '[]'))} for r in rows]

    @app.post('/api/assistant/threads')
    async def thread_new(request: Request, body: dict = Body(default={})):
        u = user_of(request)
        tid = store.x('insert into assistant_threads(username,plant,title,messages,created,updated) values(?,?,?,?,?,?)',
                      (u['username'], body.get('plant') or '', _tr('新对话'), '[]', store.now(), store.now()))
        return {'id': tid}

    @app.get('/api/assistant/threads/{tid}')
    async def thread_get(tid: int, request: Request):
        return thread(tid, user_of(request))

    @app.patch('/api/assistant/threads/{tid}')
    async def thread_rename(tid: int, request: Request, body: dict = Body(...)):
        thread(tid, user_of(request))
        store.x('update assistant_threads set title=? where id=?', ((body.get('title') or _tr('对话'))[:60], tid))
        return {'ok': True}

    @app.delete('/api/assistant/threads/{tid}')
    async def thread_del(tid: int, request: Request):
        thread(tid, user_of(request))
        store.x('delete from assistant_threads where id=?', (tid,))
        return {'ok': True}

    @app.post('/api/assistant/commit')
    async def commit(request: Request, body: dict = Body(...)):
        """卡片上的"应用到草稿"按钮：验令牌，返回服务端回执；前端随后把 ops 作为一步写进草稿（可撤销）。"""
        u = user_of(request)
        if not can_write(u):
            raise HTTPException(403, _tr('只读账号不能修改模型'))
        model, ops = body.get('model') or {}, body.get('ops') or []
        if sig(model, ops) != body.get('token'):
            raise HTTPException(409, _tr('试算之后模型又改过了，这个方案需要重新试算'))
        m2, _ = apply_ops(model, ops)
        v = validate(m2)
        if not v['ok']:
            raise HTTPException(400, _tr('这份修改现在校验不通过，需要重新试算'))
        store.audit(u['username'], 'AI', '/api/assistant/commit', 200, _tr('写入草稿 {len} 条修改', len=len(ops)))
        mark_applied(body.get('thread'), u, body.get('token'), True)
        return {'ok': True, 'lines': describe_ops(ops, model), 'changes': len(diff(model, m2))}

    @app.post('/api/assistant/threads/{tid}/card')
    async def card_state(tid: int, request: Request, body: dict = Body(...)):
        """记住方案卡片的状态（已应用 / 已撤销），重新打开对话时照样显示。"""
        mark_applied(tid, user_of(request), body.get('token'), bool(body.get('applied')))
        return {'ok': True}

    def mark_applied(tid, u, token, applied):
        if not tid or not token:
            return
        try:
            th = thread(int(tid), u)
        except HTTPException:
            return
        for m in th['messages']:
            for c in m.get('cards') or []:
                if c.get('kind') == 'proposal' and c.get('token') == token:
                    c['applied'] = applied
        store.x('update assistant_threads set messages=? where id=?', (json.dumps(th['messages'], ensure_ascii=False, default=str), th['id']))

    @app.post('/api/assistant/threads/{tid}/message')
    async def message(tid: int, request: Request, body: dict = Body(...)):
        u = user_of(request)
        th = thread(tid, u)
        pid = body.get('plant') or th['plant']
        rt = mgr.get(pid)
        q_raw = (body.get('message') or '').strip()
        if not q_raw and not body.get('image'):
            raise HTTPException(400, _tr('请输入内容'))
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(kind, data):
            loop.call_soon_threadsafe(queue.put_nowait, (kind, data))

        async def work():
            cards = []
            answer = ''
            try:
                answer = await run(th, rt, u, body, q_raw, emit, cards)
            except HTTPException as e:
                emit('error', {'msg': e.detail})
                answer = _tr('没能完成：') + str(e.detail)
            except Exception as e:  # 大模型或网络问题，给人能看懂的话
                emit('error', {'msg': _tr('没能完成：{e}', e=e)})
                answer = _tr('没能完成：{e}', e=e)
            msgs = th['messages']
            msgs.append({'role': 'user', 'content': q_raw, 'ctx': body.get('ctx') or [], 'page': body.get('page'), 't': store.now(),
                         'image': bool(body.get('image'))})
            msgs.append({'role': 'assistant', 'content': answer, 'cards': cards, 't': store.now()})
            title = th['title'] if th['title'] not in variants('新对话') else (q_raw[:40] or _tr('看图'))
            store.x('update assistant_threads set messages=?, title=?, plant=?, updated=? where id=?',
                    (json.dumps(msgs[-80:], ensure_ascii=False, default=str), title, pid, store.now(), tid))
            store.audit(u['username'], 'AI', f'/api/assistant/threads/{tid}', 200, q_raw[:200])
            emit('answer', {'text': answer, 'title': title})
            emit('_end', None)

        task = asyncio.create_task(work())

        async def stream():
            while True:
                kind, data = await queue.get()
                if kind == '_end':
                    break
                yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            await task
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    async def run(th, rt, u, body, q_raw, emit, cards):
        p = rt.plant
        model = body.get('model') or rt.build_cfg()
        sel = [s for s in body.get('selection') or [] if s]
        blocks = {b['id']: b for b in model.get('blocks', [])}
        sel_txt = '\n'.join(json.dumps(blocks[s], ensure_ascii=False)[:1500] for s in sel if s in blocks) or _tr('（没有选中对象）')
        writer = can_write(u)
        ctl = rt.ctl.status()
        mode = {'running': _tr('运行中'), 'paused': _tr('已暂停'), 'edit': _tr('已重置（编辑状态）')}.get(ctl['mode'], ctl['mode'])
        pages = '\n'.join(_tr('- {k}：{v}', k=k, v=v[0]) for k, v in PAGES.items())
        system = _tr('你是"蜂元虚拟工厂"里的 AI 助手，帮工程师分析仿真运行、修改仿真模型。用中文，简短、具体。\n使用者：{v}（{v2}）。\n当前工厂：{name}；仿真时间 {clock_str}；状态：{mode}{v3}；当前产品 {code}。\n使用者现在在页面 {v4}，视图 {v5}。\n当前选中的对象（消息里的"它""这台""这几台"指这些，不是历史里提到的对象）：\n{sel_txt}\n\n规则：\n- 数字只能来自工具返回的结果（运行数据、报表、时间构成、曲线、试算、推演），不能编。需要数据先调工具。\n- "如果现在…会怎样"这类问题用 forecast_from_now；要改模型结构或长期参数用 try_changes。\n- 修改模型：先用 try_changes 在副本上试算，拿到 KPI 对比后用一两句话说清"改什么、预计影响（引用数字）"，然后停下等使用者决定。不要说"已经改好"。\n- 只有使用者在这一轮明确同意（"应用""可以""就这么改"等）时，才用最近一次 try_changes 返回的 token 调 apply_changes，而且要在同一轮里做完。\n- 场景、实验用 propose_scenario / propose_experiment 给出卡片，由使用者点按钮决定。\n- 需要让使用者看某处时用 go_to（页面、视图、选中对象、回放时刻）。可去的页面：\n{pages}\n- 不做的事：不改真实设备，不替人发布计划或做签字类决定；只读账号不提供修改，遇到修改需求说明需要工程师账号。\n\n完整模型摘要：\n{model_text}\n\n可用的块类型：\n{catalog_text}\n\n{OPS_DOC}\n{COND_DOC}', v=u.get('name') or u['username'], v2=_tr('可以修改模型') if writer else _tr('只读账号，只能查看，不能修改'), name=p.name, clock_str=p.clock_str(), mode=mode, v3=(_tr('；正在回放 ') + body['replay_time']) if body.get('replay_time') else '', code=p.plan.product['code'], v4=body.get('page') or _tr('工作台'), v5=body.get('view') or _tr('三维'), sel_txt=sel_txt, pages=pages, model_text=model_text(model), catalog_text=catalog_text(), OPS_DOC=OPS_DOC, COND_DOC=COND_DOC)
        msgs = [{'role': 'system', 'content': system}]
        for h in th['messages'][-12:]:
            c = h.get('content') or ''
            if h['role'] == 'user' and h.get('ctx'):
                c = _tr('【当时选中：{join}】\n{c}', join=_tr('、').join(h['ctx']), c=c)
            if h['role'] == 'assistant':
                for cd in h.get('cards') or []:
                    if cd.get('kind') == 'proposal':
                        c += _tr('\n（提出过修改：{get}，token={get2}）', get=cd.get('summary'), get2=cd.get('token'))
                    elif cd.get('kind') == 'wrote':
                        c += _tr('\n（已写入草稿：{v}）', v=_tr('；').join(cd.get('lines') or [])[:300])
            if c:
                msgs.append({'role': h['role'], 'content': c[:4000]})
        q = q_raw
        if sel:
            names = _tr('、').join(_tr('{x}（{get}）', x=x, get=blocks[x].get('name', x)) if x in blocks else x for x in sel)
            q = _tr('【本条针对选中的：{names}】\n{q}', names=names, q=q)
        if body.get('image'):
            msgs.append({'role': 'user', 'content': [{'type': 'text', 'text': q or _tr('看这张图')}, {'type': 'image_url', 'image_url': {'url': body['image']}}]})
        else:
            msgs.append({'role': 'user', 'content': q})
        tools = [t for t in TOOLS if writer or t['function']['name'] not in WRITE_TOOLS]
        loop = asyncio.get_running_loop()
        last_token = {}
        for rnd in range(MAX_ROUNDS + 1):
            final = rnd == MAX_ROUNDS
            if final:
                msgs.append({'role': 'user', 'content': _tr('不要再查了，根据已经拿到的结果直接回答。')})
            m = await loop.run_in_executor(None, chat, msgs, None if final else tools)
            calls = m.get('tool_calls') or []
            if not calls:
                return m.get('content') or ''
            msgs.append({'role': 'assistant', 'content': m.get('content') or '', 'tool_calls': calls})
            for tc in calls:
                fn = tc['function']['name']
                try:
                    args = json.loads(tc['function'].get('arguments') or '{}')
                except ValueError:
                    args = {}
                emit('tool', {'tool': fn, 'phrase': phrase(fn, args, model)})
                try:
                    if fn in WRITE_TOOLS and not writer:
                        res = {'refused': _tr('只读账号不能修改，请让工程师账号来做')}
                    else:
                        res = await call_tool(rt, fn, args, model, emit, cards, last_token, u)
                except Exception as ex:
                    res = {'error': str(ex)}
                msgs.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': json.dumps(res, ensure_ascii=False, default=str)[:14000]})
        return ''

    async def call_tool(rt, fn, args, model, emit, cards, last_token, u):
        """在主事件循环里执行（和仿真循环同一线程，不会抢着改工厂）；只有试算放到进程池。"""
        if fn in ('get_runtime', 'get_report', 'get_trend'):
            return run_tool(rt, fn, args, model)
        if fn == 'get_time_breakdown':
            from . import analysis
            t0, t1 = analysis.window(rt.plant, float(args.get('hours') or 8), True)
            r = analysis.stats(rt.plant, t0, t1)
            r['objects'] = [{k: o.get(k) for k in ('id', 'name', 'share', 'oee')} for o in r.get('objects', []) if not o.get('passive')][:40]
            return r
        if fn in ('get_plc', 'propose_plc_program'):
            svc = getattr(app.state, 'plc', None)
            if svc is None:
                return {'error': _tr('这个版本没有 PLC 模块')}
            try:
                st, cd = svc.cell(rt.pid, args.get('cell') or '')
            except HTTPException as e:
                return {'refused': _tr('{get} 没有可编程的 PLC：{detail}', get=args.get("cell"), detail=e.detail)}
            from .plc.program import compile_program
            io = cd.get('io') or []
            is_blk = getattr(st, 'kind', '') == 'plc'
            devs = list(getattr(st, 'devices', None) or []) if is_blk else [st.id]
            controls = [{'id': d, 'name': getattr(rt.plant.find(d), 'name', d)} for d in devs]
            ctl_txt = _tr('、').join(_tr('{name}（{id}）', name=c['name'], id=c['id']) for c in controls) or _tr('还没有接设备')
            if fn == 'get_plc':
                p = svc.plc_of(rt.pid, st, cd)
                prog = getattr(p, 'prog', None)
                program = prog.program if prog is not None else None
                on = {}
                try:
                    on = p.online(ld=False)
                except Exception:
                    pass
                chk = compile_program(program, io).result() if program else {'ok': False, 'errors': [{'msg': _tr('还没有程序')}]}
                return {'plc': st.id, 'cell': st.id, 'name': st.name, 'kind': _tr('PLC 块') if is_blk else _tr('控制单元内置 PLC（旧模型）'), 'controls': controls,
                        'note': _tr('{name}（{id}）是 PLC 块，通过信号线控制 {ctl_txt}；编程、下载都对这台 PLC', name=st.name, id=st.id, ctl_txt=ctl_txt) if is_blk else '',
                        'io': [{k: e.get(k) for k in ('name', 'dir', 'type', 'addr', 'comment', 'device', 'point') if e.get(k) is not None} for e in io], 'program': {'lang': (program or {}).get('lang'), 'source': str((program or {}).get('source'))[:6000]} if program else None,
                        'state': getattr(p, 'state', None), 'online': {k: on.get(k) for k in ('state', 'vars', 'io', 'forced', 'scan') if k in on}, 'compile': {k: chk.get(k) for k in ('ok', 'errors', 'warnings')}}
            prog = {'lang': 'ST', 'name': _tr('主程序'), 'source': args.get('source') or ''}
            chk = compile_program(prog, io).result()
            if not chk.get('ok'):
                return {'ok': False, 'errors': chk.get('errors', [])[:10], 'hint': _tr('修正后重新 propose_plc_program')}
            card = {'kind': 'plc', 'summary': args.get('summary') or _tr('PLC 程序'), 'cell': st.id, 'cell_name': st.name, 'program': prog, 'controls': controls,
                    'lines': [_tr('{name}（{id}）· ST · {len} 行，编译通过', name=st.name, id=st.id, len=len(prog['source'].splitlines())) + (_tr('；控制 {ctl_txt}', ctl_txt=ctl_txt) if is_blk else '')]}
            cards.append(card)
            emit('plc', card)
            return {'ok': True, 'note': _tr('程序已作为卡片给使用者，由他点"下载到 PLC"')}
        if fn == 'forecast_from_now':
            from .fork import fork
            r = await fork(rt.plant, max(1.0, min(12.0, float(args.get('hours') or 4))), args.get('changes') or [], 1, _tr('改动后'))
            return {k: r.get(k) for k in ('rows', 'text', 'errors', 'wall_s')}
        if fn == 'try_changes':
            ops = args.get('ops') or []
            try:
                m2, _ = apply_ops(model, ops)
            except Exception as e:
                return {'ok': False, 'error': _tr('命令有误：{e}', e=e)}
            v = validate(m2)
            errs = [i for i in v['issues'] if i['level'] == 'error']
            if errs:
                return {'ok': False, 'errors': errs[:10], 'hint': _tr('修正后重新 try_changes')}
            hours = max(1.0, min(12.0, float(args.get('hours') or 4)))
            meas = await asyncio.get_running_loop().run_in_executor(None, measure, model, ops, hours)
            token = sig(model, ops)
            last_token['t'] = token
            card = {'kind': 'proposal', 'summary': args.get('summary') or _tr('修改方案'), 'ops': ops, 'lines': describe_ops(ops, model),
                    'measure': meas, 'token': token, 'warn': [i['msg'] for i in v['issues'] if i['level'] == 'warn'][:5]}
            cards.append(card)
            emit('proposal', card)
            return {'ok': True, 'measure': meas, 'apply_token': token, 'note': _tr('方案已作为卡片给使用者；等他同意再 apply_changes')}
        if fn == 'apply_changes':
            ops = args.get('ops') or []
            if sig(model, ops) != args.get('token'):
                return {'refused': _tr('令牌和这份改动/当前模型对不上（模型可能在试算后改过），请重新 try_changes')}
            m2, _ = apply_ops(model, ops)
            if not validate(m2)['ok']:
                return {'refused': _tr('校验不通过，请重新 try_changes')}
            card = {'kind': 'wrote', 'summary': args.get('summary') or _tr('已写入草稿'), 'ops': ops, 'lines': describe_ops(ops, model), 'token': args.get('token')}
            cards.append(card)
            emit('wrote', card)
            store.audit(u['username'], 'AI', '/api/assistant/apply', 200, _tr('写入草稿 {len} 条修改', len=len(ops)))
            return {'ok': True, 'note': _tr('已写入草稿（使用者可撤销）；应用到工厂要使用者自己点')}
        if fn in ('propose_scenario', 'propose_experiment'):
            card = {'kind': 'action', 'type': fn.split('_')[1], 'payload': args}
            cards.append(card)
            emit('action', card)
            return {'ok': True, 'note': _tr('已作为卡片给使用者，由他决定保存/运行')}
        if fn == 'set_breakpoint':
            from .runctl import describe
            cond = args.get('cond') or {}
            if cond.get('kind') not in ('state', 'state_for', 'alarm', 'buffer', 'kpi', 'tag', 'event', 'time'):
                return {'refused': _tr('条件格式不对')}
            import time as _t
            b = {'id': f'BP{int(_t.time() * 1000) % 10 ** 8}', 'name': args.get('name') or describe(cond, rt.plant), 'cond': cond,
                 'enabled': True, 'once': bool(args.get('once')), 'hits': 0}
            rt.ctl.bps.append(b)
            card = {'kind': 'wrote', 'summary': _tr('已加断点'), 'lines': [_tr('断点：{name}', name=b['name'])], 'breakpoint': b['id']}
            cards.append(card)
            emit('wrote', card)
            return {'ok': True, 'breakpoint': b}
        if fn == 'sim_control':
            c, p = rt.ctl, rt.plant
            a = args.get('action')
            if a == 'play':
                c.fresh, c.hit = False, None
                if args.get('speed'):
                    p.speed = max(0.1, min(3600.0, float(args['speed'])))
                p.paused = False
                line = _tr('继续运行（{speed:g}×）', speed=p.speed)
            elif a == 'pause':
                p.paused = True
                line = _tr('已暂停')
            elif a == 'step':
                c.step(args.get('seconds'), bool(args.get('event')))
                line = _tr('单步到 {clock_str}', clock_str=p.clock_str())
            elif a == 'run_to':
                line = _tr('后台运行到：') + c.run_to(args.get('cond'), args.get('hours'))
            else:
                return {'refused': _tr('未知操作')}
            card = {'kind': 'wrote', 'summary': _tr('运行控制'), 'lines': [line]}
            cards.append(card)
            emit('wrote', card)
            return {'ok': True, 'result': line, 'time': p.clock_str()}
        if fn == 'go_to':
            pg = args.get('page') or 'workbench'
            if pg not in PAGES:
                return {'refused': _tr('没有页面 {pg}', pg=pg)}
            path = PAGES[pg][1]
            nav = {'path': path if path.startswith('/') else f'/p/{rt.pid}' + (f'/{path}' if path else ''), 'view': args.get('view'),
                   'select': args.get('select') or [], 'time': args.get('time'), 'why': args.get('why') or ''}
            card = {'kind': 'went', **nav}
            cards.append(card)
            emit('navigate', nav)
            return {'ok': True}
        raise ValueError(_tr('未知工具 {fn}', fn=fn))
