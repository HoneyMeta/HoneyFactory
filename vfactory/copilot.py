"""AI 助手：选中对象对话。读运行数据、解释原因；修改一律形成"变更集"（编辑命令列表）交给用户确认，确认后才进入草稿，可撤销。

大模型：config/llm.local.json（不入库）或环境变量 VF_LLM_BASE_URL / VF_LLM_API_KEY / VF_LLM_MODEL，OpenAI 兼容接口。
"""
from .i18n import _tr
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

from fastapi import Body, HTTPException, Request

from . import history, store
from .flow import catalog
from .flow.model import apply_ops, validate

from . import paths as _paths  # noqa: E402
CFG = os.path.join(_paths.CONFIG, 'llm.local.json')


def server_llm_cfg():
    """本机配置的大模型（服务器上的密钥）：config/llm.local.json 或 VF_LLM_*。
    No built-in endpoint, model or key: AI stays off until base_url, model and api_key are all configured."""
    c = {'base_url': '', 'model': '', 'api_key': ''}
    if os.path.exists(CFG):
        try:
            with open(CFG, encoding='utf-8') as f:
                c.update({k: v for k, v in json.load(f).items() if v})
        except Exception:
            pass
    for k in ('base_url', 'api_key', 'model'):
        if os.environ.get('VF_LLM_' + k.upper()):
            c[k] = os.environ['VF_LLM_' + k.upper()]
    if not (c['base_url'] and c['model'] and c['api_key']):
        c['api_key'] = ''                         # incomplete configuration = not configured (every caller checks api_key)
    return c


def llm_cfg():
    """5.0：客户端本机没配大模型、但登录着服务器时，经服务器的 AI 代理（/api/ai/proxy，密钥只在服务器上，按单位计量）。
    这时 proxy=True，api_key 是服务器给这个账号的登录令牌（不是大模型的密钥）。"""
    c = server_llm_cfg()
    if not c['api_key']:
        try:
            from .teach import client as tclient
            s = tclient.load_settings() if tclient.is_desktop_proc() else {}
        except Exception:                        # noqa: BLE001
            s = {}
        if s.get('url') and s.get('token'):
            c.update(base_url=s['url'].rstrip('/') + '/api/ai/proxy', api_key=s['token'], model='server', proxy=True)
    return c


BUDGET = 150    # 一次大模型调用（含重试）最多等多少秒


def chat(messages, tools=None, meter=None):
    """meter（服务器上替单位账号调用时，见 tenancy/aiproxy.Meter）：调用前查额度，调用后按 usage 记到单位上。"""
    c = llm_cfg()
    if not c['api_key']:
        raise HTTPException(400, _tr('还没有配置大模型（config/llm.local.json）'))
    if meter is not None:
        meter.check()
    from .i18n import llm_instruction            # every model call: answer in the UI language (after the leading system prompts)
    messages = list(messages)
    i = 0
    while i < len(messages) and isinstance(messages[i], dict) and messages[i].get('role') == 'system':
        i += 1
    messages.insert(i, {'role': 'system', 'content': llm_instruction()})
    body = {'model': c['model'], 'messages': messages, 'temperature': 0.2}
    if tools:
        body['tools'] = tools
    req = urllib.request.Request(c['base_url'].rstrip('/') + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + c['api_key']})
    # 网关偶尔断连（SSL EOF）或限流/5xx：退避重试；整次调用最多等 BUDGET 秒，网关卡住时尽快告诉用户，而不是让人干等几分钟
    t0 = time.time()
    for attempt in range(4):
        left = BUDGET - (time.time() - t0)
        try:
            with urllib.request.urlopen(req, timeout=max(10, min(90, left))) as r:
                full = json.loads(r.read())
                if meter is not None:
                    meter.charge(full.get('usage'), messages, full.get('choices'))
                return full['choices'][0]['message']
        except urllib.error.HTTPError as e:
            if c.get('proxy') and e.code in (401, 403, 413, 503):     # 经服务器代理：额度用完、没开通、登录过期——把服务器的说明原样给用户
                try:
                    why = json.loads(e.read().decode('utf-8')).get('detail')
                except Exception:                # noqa: BLE001
                    why = None
                raise HTTPException(403 if e.code != 503 else 503, why or _tr('服务器的 AI 代理拒绝了（{code}）', code=e.code))
            if e.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise HTTPException(502, _tr('大模型接口出错（{code}），请稍后再试', code=e.code))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            waited = round(time.time() - t0)
            if attempt == 3 or time.time() - t0 > BUDGET - 15:
                timeout = isinstance(e, TimeoutError) or 'timed out' in str(getattr(e, 'reason', e))
                raise HTTPException(504 if timeout else 502, _tr('大模型接口{v}，请稍后再试；其他功能不受影响', v=_tr('响应超时（等了 ') + str(waited) + _tr(' 秒）') if timeout else _tr('连不上：') + str(getattr(e, "reason", e))))
        time.sleep(2 * (attempt + 1))


def catalog_text():
    lines = []
    for t, s in catalog.BLOCK_TYPES.items():
        ps = ', '.join(f"{k}({v['label']}{'·' + v['unit'] if v.get('unit') else ''}{'=' + json.dumps(v.get('default'), ensure_ascii=False) if v.get('default') not in (None, '', [], {}) else ''})"
                       for k, v in s['params'].items() if k not in ('defects', 'attrs'))
        lines.append(_tr('- {t}【{label}】入口 {v} 出口 {v2}；默认尺寸 {size}；参数：{ps}', t=t, label=s['label'], v=s['in'] or _tr('无'), v2=s['out'] or _tr('无'), size=s['size'], ps=ps))
    return '\n'.join(lines)


def model_text(m):
    bl = []
    for b in m.get('blocks', []):
        p = {k: v for k, v in (b.get('params') or {}).items() if k not in ('roles', 'nodes', 'defects', 'attrs')}
        bl.append(f"{b['id']}|{b['type']}|{b.get('name')}|pos={b.get('pos')} size={b.get('size')} node={b.get('node')}|{json.dumps(p, ensure_ascii=False)[:200]}")
    ln = [f"{l['id']}: {l['from']}.{l.get('from_port', 'out')} → {l['to']}.{l.get('to_port', 'in')}" + (f" via {l['via']}" if l.get('via') else '') for l in m.get('links', [])]
    return _tr('设备：\n') + '\n'.join(bl) + _tr('\n连线：\n') + '\n'.join(ln)


TOOLS = [
    {'type': 'function', 'function': {'name': 'get_runtime', 'description': '取设备的实时状态：状态、报警、功率、OEE、全部点位当前值、近 2 小时事件。',
                                      'parameters': {'type': 'object', 'properties': {'ids': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['ids']}}},
    {'type': 'function', 'function': {'name': 'get_report', 'description': '取近 N 小时的运行报表：产量、废品、能耗、设备时间构成、瓶颈、生产周期、结论。',
                                      'parameters': {'type': 'object', 'properties': {'hours': {'type': 'number'}}}}},
    {'type': 'function', 'function': {'name': 'get_trend', 'description': '取一个点位近 N 小时的曲线（30 秒一点，最多返回 120 点）。key 形如 CNC1/Monitoring/Spindle/Load',
                                      'parameters': {'type': 'object', 'properties': {'key': {'type': 'string'}, 'hours': {'type': 'number'}}, 'required': ['key']}}},
    {'type': 'function', 'function': {'name': 'propose_changes', 'description': '提出对模型的修改（编辑命令列表）。会先在草稿上试应用并校验，返回校验结果；有错误请修正后重新提出。用户确认后才生效。',
                                      'parameters': {'type': 'object', 'properties': {'summary': {'type': 'string', 'description': '一句话说明改了什么'},
                                                                                     'ops': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['summary', 'ops']}}},
    {'type': 'function', 'function': {'name': 'propose_scenario', 'description': '提出一个场景（按时间编排的故障/扰动），用户确认后保存并可运行。',
                                      'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'descr': {'type': 'string'},
                                                                                     'steps': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['name', 'steps']}}},
    {'type': 'function', 'function': {'name': 'propose_experiment', 'description': '提出一个实验对比（基准自动加入），用户确认后在后台计算。',
                                      'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'hours': {'type': 'number'},
                                                                                     'variants': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['name', 'variants']}}},
]

OPS_DOC = """编辑命令（ops 数组的元素）：
  {"op":"add_block","block":{"id":"M4","type":"processor","name":"4#加工中心","pos":[x,y],"size":[L,W],"rot":0,"node":[gx,gy],"params":{...},"signals":[...]}}
  {"op":"remove_block","id":"M4"}               （相关连线一起删除）
  {"op":"update_block","id":"M1","set":{"params.time":"normal(380,15)","name":"…","pos":[x,y],"signals":[…]}}   路径用点分隔
  {"op":"add_link","link":{"id":"L99","kind":"material","from":"A","from_port":"out","to":"B","to_port":"in","via":"搬运车队编号(可选)","capacity":2,"cond":"item.get('result')=='OK'(可选)","weight":1}}
  {"op":"remove_link","id":"L9"}  {"op":"update_link","id":"L9","set":{"capacity":5}}
  {"op":"update_plant","set":{"plant.name":"…"}}
规则：
- 编号用字母开头，不能和已有编号重复；新连线编号用 L 加数字。
- pos 是厂房平面坐标（米），size 是占地长宽（米）；node 是流程图卡片坐标（像素，卡片约 200×100，同一工序上下间隔 120、前后工序左右间隔 230）。
- 新设备放在相关设备旁边，不要和已有设备占地重叠。
- 两个缓存（buffer）之间的连线必须指定 via（搬运车队）。
- 加工/检测等块之间可以直接连线（自带小队列），也可以中间放缓存块。
- 表达式可用：normal(m,sd) tri(a,mode,b) uniform(a,b) expo(mean) lognormal(m,sd) noise(sd) walk(sd,lo,hi) lag(x,tau秒) ramp(t0_h,t1_h,v0,v1) if_(c,a,b) tag('设备/点位') param('参数') clip，变量 t(小时) busy state power item。
- 自定义点位 signals：[{"name":"Mold/Temp","unit":"°C","desc":"模具温度","expr":"lag(25+power*3,300)+noise(0.5)"}]
场景步骤 steps：[{"at":分钟,"action":"fault|clear|write|ramp|disable|absent|comm|speed|note","target":"设备或协议","tag":"点位","value":值,"minutes":时长}]
实验 variants：[{"name":"方案名","changes":[{"type":"add","template":"CNC1","count":1}|{"type":"param","station":"M1","key":"time","value":"normal(300,10)"}|{"type":"setpoint","station":"INS1","tag":"Setpoint/Sensitivity","value":0.5}|{"type":"remove","station":"X"}|{"type":"crew","role":"岗位","value":3}|{"type":"buffer","name":"B1","value":40}]}]"""


def register(app, mgr):
    @app.get('/api/ai/status')
    async def ai_status():
        c = llm_cfg()
        return {'available': bool(c['api_key']), 'model': c['model']}

    @app.post('/api/p/{pid}/ai')
    async def ask(pid: str, request: Request, body: dict = Body(...)):
        user = request.state.user
        rt = mgr.get(pid)
        p = rt.plant
        model = body.get('model') or rt.build_cfg()
        sel = [s for s in body.get('selection') or [] if s]
        blocks = {b['id']: b for b in model.get('blocks', [])}
        sel_txt = '\n'.join(json.dumps(blocks[s], ensure_ascii=False)[:1500] for s in sel if s in blocks) or _tr('（没有选中对象，针对整个工厂）')
        system = _tr('你是"蜂元虚拟工厂"的建模与分析助手，帮助工程师修改仿真模型、分析运行数据。用中文，简洁、具体、引用数据。\n当前工厂：{name}，仿真时间 {clock_str}，当前产品 {code}。当前视图：{get}。\n用户当前选中的对象（消息里的“它”“这台”“这几台”指这些，不是历史里提到的对象）：\n{sel_txt}\n\n完整模型摘要：\n{model_text}\n\n可用的块类型：\n{catalog_text}\n\n{OPS_DOC}\n\n工作方式：\n- 需要数据时先调用 get_runtime / get_report / get_trend，不要编造数字。\n- 要修改模型时调用 propose_changes（一次提出完整的修改），根据返回的校验结果修正，直到没有错误。不要说"已经改好"，改动要用户确认后才生效。\n- 场景用 propose_scenario，实验用 propose_experiment。\n- 最后用几句话说明：做了什么判断、提出了哪些修改、需要用户确认什么。', name=p.name, clock_str=p.clock_str(), code=p.plan.product['code'], get=body.get('view', 'graph'), sel_txt=sel_txt, model_text=model_text(model), catalog_text=catalog_text(), OPS_DOC=OPS_DOC)
        msgs = [{'role': 'system', 'content': system}]
        for h in (body.get('history') or [])[-8:]:
            if h.get('role') in ('user', 'assistant') and h.get('content'):
                msgs.append({'role': h['role'], 'content': str(h['content'])[:4000]})
        q = body.get('message') or ''
        if sel:   # 每条消息都标明当时选中的对象，避免"它"指到上一轮的对象
            names = _tr('、').join(_tr('{s}（{get}）', s=s, get=blocks[s].get('name', s)) if s in blocks else s for s in sel)
            q = _tr('【本条针对选中的：{names}】\n{q}', names=names, q=q)
        if body.get('image'):
            msgs.append({'role': 'user', 'content': [{'type': 'text', 'text': q or _tr('按这张图摆出布局')}, {'type': 'image_url', 'image_url': {'url': body['image']}}]})
        else:
            msgs.append({'role': 'user', 'content': q})
        ops, summary, actions, val, trace = [], '', [], None, []
        work = model
        import asyncio
        loop = asyncio.get_running_loop()
        for _ in range(10):
            m = await loop.run_in_executor(None, chat, msgs, TOOLS)
            calls = m.get('tool_calls') or []
            if not calls:
                answer = m.get('content') or ''
                break
            msgs.append({'role': 'assistant', 'content': m.get('content') or '', 'tool_calls': calls})
            for tc in calls:
                fn = tc['function']['name']
                try:
                    args = json.loads(tc['function'].get('arguments') or '{}')
                except ValueError:
                    args = {}
                try:
                    res = run_tool(rt, fn, args, work)
                    if fn == 'propose_changes':
                        if res.get('ok'):
                            ops, summary, val = args.get('ops') or [], args.get('summary') or '', res['validation']
                        res = {k: v for k, v in res.items() if k != 'model'}
                    elif fn in ('propose_scenario', 'propose_experiment'):
                        actions.append({'type': fn.split('_')[1], 'payload': args})
                    trace.append({'tool': fn, 'args': {k: v for k, v in args.items() if k != 'ops'} if fn != 'propose_changes' else {'summary': args.get('summary'), 'ops': len(args.get('ops') or [])}})
                    content = json.dumps(res, ensure_ascii=False, default=str)[:14000]
                except Exception as ex:
                    content = json.dumps({'error': str(ex)}, ensure_ascii=False)
                msgs.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': content})
        else:
            answer = _tr('步骤太多，没能完成。请把需求说得更具体一些。')
        store.audit(user['username'], 'AI', f'/api/p/{pid}/ai', 200, (q[:200] + (_tr('（提出 {len} 条修改）', len=len(ops)) if ops else '')))
        return {'answer': answer, 'ops': ops, 'summary': summary, 'actions': actions, 'validation': val, 'trace': trace}


def run_tool(rt, fn, args, model):
    p = rt.plant
    if fn == 'get_runtime':
        out = {}
        for sid in args.get('ids') or []:
            st = p.stations.get(sid)
            if not st:
                out[sid] = _tr('不存在（可能是草稿里新加、还没应用）')
                continue
            d = st.snapshot(full=True)
            d['tags'] = {k: v['v'] for k, v in d['tags'].items()}
            d.pop('truth', None)
            d['oee'] = p.oee(st)
            d['events'] = [e for e in list(p.events)[-400:] if e['station'] == sid][-15:]
            out[sid] = d
        return out
    if fn == 'get_report':
        h = float(args.get('hours') or 8)
        r = history.summary(p, max(0, p.t - h * 3600), p.t)
        r.pop('series', None)
        if r.get('lead'):
            r['lead'].pop('hist', None)
        return r
    if fn == 'get_trend':
        h = float(args.get('hours') or 4)
        ts, vs = p.tagring.series(args['key'], p.t - h * 3600)
        step = max(1, len(vs) // 120)
        from datetime import timedelta
        return {'key': args['key'], 'points': [[(p.t0 + timedelta(seconds=t)).strftime('%m-%d %H:%M'), v] for t, v in list(zip(ts, vs))[::step]][:120],
                'min': min(vs) if vs else None, 'max': max(vs) if vs else None, 'last': vs[-1] if vs else None}
    if fn == 'propose_changes':
        m2, _inv = apply_ops(model, args.get('ops') or [])
        v = validate(m2)
        new_err = [i for i in v['issues'] if i['level'] == 'error']
        return {'ok': not new_err, 'validation': v, 'errors': new_err[:10], 'model': m2}
    if fn == 'propose_scenario':
        return {'ok': True, 'note': _tr('已作为待确认动作返回给用户')}
    if fn == 'propose_experiment':
        return {'ok': True, 'note': _tr('已作为待确认动作返回给用户')}
    raise ValueError(_tr('未知工具 {fn}', fn=fn))
