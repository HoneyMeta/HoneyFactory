"""AI 助教：读学生的程序、最近的 I/O 时序、评分结果，只给提示和引导问题，不给完整答案。

POST /api/tutor/ask  {assignment_id, question, history?: [{role, content}]}
  → {answer, filtered: bool, points: [{key, label, target, goto, plc?}], context: {program_lines, trace_rows, last_score}}
  points（4.6）：回答里的"看这里"——前端显示按钮，点了用跟随教程的聚光层圈出那个地方（target / goto 格式同 tour.ts）。
老师在任务里关掉"AI 助教"后，学生调用返回 403。老师/管理员调用时同样不出完整答案（便于预览学生会看到什么）。
大模型调用复用 copilot.chat（带重试），不改 copilot / assistant。
给外壳的全局 AI 面板用：answer(mgr, user, assignment_id, question, history) 是普通函数，可直接调用。
"""
from .i18n import _tr
import asyncio
import os
import json
import re

from fastapi import Body, HTTPException, Request

from . import copilot

SYSTEM = """你是职业院校 PLC 实训课的 AI 助教，学生正在虚拟工厂里给一台 PLC 块写程序（梯形图 LD 或结构化文本 ST）；PLC 是独立的设备，通过信号线读写一个控制单元的 I/O（变量名就是 I/O 表里的名字）。
你的规则（必须遵守）：
1. 只给提示和引导问题，帮助学生自己找到问题。绝不给出完整程序、完整梯级或可以直接复制粘贴的代码段。
2. 可以点出"哪个信号/哪个条件/哪一段逻辑"值得检查，可以解释指令（如 TON、R_TRIG、自锁、互锁）的一般用法，可以用一两句伪描述说明思路，但不写代码。
3. 结合学生程序、I/O 时序和评分明细，指出最可能的原因，按"先观察什么 → 再想什么"的顺序引导。
4. 每次回答不超过 200 字，用简体中文、口语化，结尾提出 1–2 个引导问题。
5. 如果学生直接要答案，礼貌拒绝并给出下一步该检查的地方。
""" + '{POINT_RULE}'

CODE_HINT = re.compile(r':=|\bIF\b.*\bTHEN\b|\bEND_IF\b|\bVAR\b|\bEND_VAR\b|\bTON\s*\(|\bCTU\s*\(|%[IQM][WXD]?\d', re.I)


def filter_answer(text):
    """去掉代码块和成段的程序；返回 (文本, 是否过滤过)。"""
    out, filtered = [], False
    t = re.sub(r'```.*?```', '［此处原有代码，助教不直接给代码］', text or '', flags=re.S)
    if t != (text or ''):
        filtered = True
    lines = t.split('\n')
    run = 0
    for ln in lines:
        if CODE_HINT.search(ln) and (ln.count(':=') or ln.strip().endswith(';') or re.search(r'\bEND_|\bTHEN\b', ln, re.I)):
            run += 1
            filtered = True
            if run == 1:
                out.append(_tr('［此处原有程序片段，助教不直接给代码］'))
            continue
        run = 0
        out.append(ln)
    return '\n'.join(out).strip(), filtered


def program_text(prog):
    if not prog:
        return _tr('（学生还没有下载程序）')
    src = prog.get('source')
    head = _tr('语言：{get}\n变量：', get=prog.get('lang', '?')) + ', '.join(f"{v.get('name')}:{v.get('type')}{'@' + v['addr'] if v.get('addr') else ''}" for v in prog.get('vars') or [])
    if isinstance(src, str):
        body = src
    else:
        body = json.dumps(src, ensure_ascii=False)
    return (head + '\n' + body)[:6000]


def build_messages(scene, prog, trace, last, question, history, hints_allowed, cat=None):
    from .teach import scenes
    rules = scenes.rules_of(scene)
    ctx = [_tr('实训任务：{name_of}', name_of=scenes.name_of(scene)), _tr('任务书：\n') + (scenes.task_md(scene) or '')[:3000],
           _tr('I/O 表：') + json.dumps(scenes.io_of(scene), ensure_ascii=False)[:2000],
           _tr('评分规则：') + json.dumps(rules, ensure_ascii=False)[:1500],
           _tr('学生当前程序：\n') + program_text(prog),
           _tr('最近的 I/O 时序（仿真秒，只列变化）：\n') + (trace or _tr('（暂无）'))]
    if last:
        ctx.append(_tr('最近一次提交的评分：') + json.dumps({'score': last.get('score'), 'details': last.get('details')}, ensure_ascii=False, default=str)[:2000])
    if hints_allowed and scenes.hints_of(scene):
        ctx.append(_tr('老师允许的提示（可以引用）：') + _tr('；').join(scenes.hints_of(scene)))
    if cat:
        ctx.append(catalog_text(cat))
    msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'system', 'content': '\n\n'.join(ctx)}]
    for h in (history or [])[-6:]:
        if h.get('role') in ('user', 'assistant') and isinstance(h.get('content'), str):
            msgs.append({'role': h['role'], 'content': h['content'][:2000]})
    msgs.append({'role': 'user', 'content': (question or _tr('我的程序哪里不对？')).strip()[:1000]})
    return msgs


SYSTEM_PLANT = """你是职业院校/工厂培训"生产线仿真与优化"课的 AI 助教，学生正在虚拟工厂的沙箱里改产线模型（设备、缓存、搬运车、人员、计划）来达成指标。
你的规则（必须遵守）：
1. 只给提示和引导问题，帮助学生自己找到办法。不要直接说出"把某参数改成某值""加哪台设备接到哪里"这样的完整答案，也不要替学生回答选择题或点选题。
2. 可以解释概念（节拍、产能、瓶颈、利特尔法则、缓存、换型、可用率、批量、能耗），可以指出该去看哪个数据（时间构成、缓存件数、零件履历、能耗分析）。
3. 结合任务书、评分规则、学生当前模型和实时指标，按"先观察什么 → 再想什么"的顺序引导。
4. 每次回答不超过 200 字，用简体中文、口语化，结尾提出 1–2 个引导问题。
""" + '{POINT_RULE}'

# ---------------- 4.6 "看这里"：助教指着界面上的地方说（和跟随教程同一个聚光层） ----------------
POINT_RULE = """6. 想让学生去看界面上的某个地方时，在句子里插入「【看这里：简短标签｜编号】」（编号只能从"可以指的地方"清单里原样抄，每次回答最多 2 个）。
   界面会把它变成一个"看这里"按钮，学生点了会打开对应的面板并把那个地方圈出来。
   只用它指"该去看、该去检查的地方"（检查表、日志、某个触点、某台设备、某个页签），不能用它暗示答案：
   不要指出选择题/点选题的答案设备，不要指着参数说改成多少，不要用工具条按钮暗示"在这里放一个什么元件就对了"。"""
SYSTEM = SYSTEM.replace('{POINT_RULE}', POINT_RULE)
SYSTEM_PLANT = SYSTEM_PLANT.replace('{POINT_RULE}', POINT_RULE.replace('6.', '5.', 1))

POINT_RE = re.compile(r'[【\[]\s*看这里\s*[:：]\s*([^|｜\]】\n]{1,30}?)\s*[|｜]\s*([^\]】\n]{1,80}?)\s*[\]】]')
MAX_POINTS = 3
PANEL_CN = {'teach-task': '任务面板', 'plc-editor': 'PLC 编程', 'cell-editor': '控制单元面板', 'events': '事件与报警', 'breakpoints': '断点',
            'outliner': '对象列表', 'library': '资源库', 'analysis': '分析', 'parts': '零件'}
TAB_CN = {'task': '任务书', 'goals': '评分标准 / 目标', 'io': 'I/O 表', 'score': '成绩', 'log': '日志'}
VIEW_CN = {'3d': '三维', 'plan': '平面图', 'graph': '流程图', 'arch': '架构图'}


def _ld_vars(prog):
    """学生程序里梯形图元件：{变量: {元件类型}}。"""
    out = {}
    src = (prog or {}).get('source') if (prog or {}).get('lang') == 'LD' else None

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            if x.get('par'):
                for br in x['par']:
                    walk(br)
            elif x.get('ser'):
                walk(x['ser'])
            elif x.get('var'):
                out.setdefault(str(x['var']).upper(), set()).add(x.get('t') or '')
    for r in (src or {}).get('rungs') or [] if isinstance(src, dict) else []:
        walk(r.get('elements') or [])
    return out


def point_catalog(kind, blocks=(), comps=(), prog=None, plc='', forbid=()):
    """可以指的地方：{编号: {'label', 'target', 'goto', 'plc'?}}。kind：'cell'（PLC 课）或 'plant'（产线课）。
    target / goto 的格式和跟随教程一样（web/src/panels/teach/tour/tour.ts）：sel / tour / panel_btn / ld / block；goto 打开面板、切页签、选中设备。"""
    cat = {}

    def add(k, label, target, goto=None, **kw):
        cat[k] = {'label': label, 'target': target, 'goto': goto, **kw}
    for tab, cn in TAB_CN.items():
        if tab == 'log' and kind != 'cell' or tab == 'io' and kind != 'cell':
            continue
        add(f'tab:{tab}', _tr('任务面板「{cn}」页签', cn=cn), [{'sel': f'.task-panel #tab-{tab}'}, {'sel': '.task-panel .tp-tabs'}], {'teach_tab': tab})
    add('submit', _tr('「提交评分」按钮'), {'sel': '.task-panel [data-k="submit-score"]'}, {'teach_tab': 'goals'})
    if kind == 'cell':
        add('checklist', _tr('检查表'), [{'sel': '.task-panel [data-tour="checklist"]'}, {'tour': 'checklist'}], {'teach_tab': 'goals'})
        add('runlog', _tr('运行日志'), {'tour': 'run-log'}, {'console': True, 'console_tab': 'log'})
        for c in comps or []:
            t, cid = c.get('type'), c.get('id')
            if not cid:
                continue
            if t in ('button', 'estop'):
                add(f'btn:{cid}', _tr('操作台「{v}」', v=c.get("label") or cid), {'tour': f'btn-{cid}'}, {'console': True})
            elif t == 'lamp':
                add(f'lamp:{cid}', _tr('指示灯「{v}」', v=c.get("label") or cid), {'tour': f'lamp-{cid}'}, {'console': True})
        for v, ts in _ld_vars(prog).items():
            ed_goto = {'panel': 'plc-editor-float', 'plc_tab': 'prog'}
            add(f'ld:{v}', _tr('梯形图里的 {v}', v=v), [{'ld': {'var': v}}, {'sel': '.pw .lde'}], ed_goto, plc=plc)
            for t in ts:
                if t:
                    add(f'ld:{v}/{t}', _tr('梯形图里的 {v}（{t}）', v=v, t=t), [{'ld': {'var': v, 't': t}}, {'sel': '.pw .lde'}], ed_goto, plc=plc)
        add('panel:plc-editor', _tr('左边竖排的「PLC 编程」图标'), {'panel_btn': 'plc-editor'})
        add('panel:cell-editor', _tr('左边竖排的「控制单元」图标'), {'panel_btn': 'cell-editor'})
        add('editor', _tr('PLC 编程窗口'), {'sel': '.pw'}, {'panel': 'plc-editor-float'}, plc=plc)
    else:
        for p in ('outliner', 'library', 'analysis', 'events'):
            add(f'panel:{p}', _tr('左边竖排的「{v}」图标', v=PANEL_CN[p]), {'panel_btn': p})
    for b in blocks or []:
        bid = b.get('id')
        if not bid or bid in forbid:
            continue
        nm = b.get('name') or bid
        add(f'block:{bid}', _tr('设备 {nm}', nm=nm), {'block': bid}, {'select': bid})
        for v in ('3d', 'plan', 'graph'):
            add(f'block:{bid}@{v}', _tr('{v}里的 {nm}', v=VIEW_CN[v], nm=nm), {'block': bid}, {'select': bid, 'view': v})
        if kind != 'cell':
            add(f'props:{bid}', _tr('{nm} 的属性', nm=nm), {'sel': '.ed-right'}, {'select': bid, 'right': 'props'})
    return cat


def catalog_text(cat, limit=2500):
    """给大模型看的清单（同一台设备的视图变体只写一次）。"""
    lines = []
    for k, v in cat.items():
        if '@' in k:
            continue
        lines.append(f'{k}  {v["label"]}')
    txt = '\n'.join(lines)
    if len(txt) > limit:
        txt = txt[:limit] + '\n…'
    return _tr('可以指的地方（「【看这里：标签｜编号】」里的编号；设备还可以加 @3d / @plan / @graph 指定在哪张图里看，如 block:M1@plan）：\n') + txt


def extract_points(text, cat):
    """把回答里的「【看这里：标签｜编号】」换成标签文字，返回 (文本, [点])；清单里没有的编号只留文字。"""
    pts, seen = [], set()
    up = {k.upper(): k for k in cat}

    def rep(m):
        label, key = m.group(1).strip(), m.group(2).strip()
        k = cat.get(key) and key or up.get(key.upper())
        if k and k not in seen and len(pts) < MAX_POINTS:
            seen.add(k)
            c = cat[k]
            pts.append({'key': k, 'label': label or c['label'], 'target': c['target'], 'goto': c.get('goto'), **({'plc': c['plc']} if c.get('plc') else {})})
        return _tr('「{label}」', label=label) if label else ''
    return POINT_RE.sub(rep, text or ''), pts


def _forbidden_blocks(rules):
    """点选题的答案设备：助教不能指着它（会直接泄露答案）。"""
    out = set()
    for r in rules or []:
        if r.get('kind') == 'answer' and r.get('pick') and r.get('answer'):
            a = r['answer']
            out.update(a if isinstance(a, (list, tuple, set)) else [a])
    return {str(x) for x in out}


def model_text(model):
    lines = []
    for b in (model or {}).get('blocks') or []:
        p = {k: v for k, v in (b.get('params') or {}).items() if k in ('time', 'interval', 'capacity', 'count', 'batch', 'max_wait_min', 'length_m', 'speed_mps',
                                                                       'setup_min', 'mtbf_h', 'mttr_min', 'operator', 'load_s', 'pod_pct', 'attrs')}
        lines.append(f"{b['id']} {b.get('type')} {b.get('name', '')} {json.dumps(p, ensure_ascii=False)}")
    links = [f"{l['from']}→{l['to']}" + (_tr('（{via} 搬运）', via=l['via']) if l.get('via') else '') for l in (model or {}).get('links') or []]
    return ('\n'.join(lines) + _tr('\n连线：') + _tr('，').join(links))[:5000]


def build_messages_plant(t, model, live, last, question, history, hints_allowed, cat=None):
    pub = t.public(hints_allowed)
    rules = [{k: r.get(k) for k in ('label', 'kind', 'metric', 'op', 'value', 'choices')} for r in pub['rules']]
    ctx = [_tr('课程：{name}；本课：{name2}', name=t.course['name'], name2=t.name), _tr('任务书：\n') + (pub['brief_md'] or '')[:3000],
           _tr('评分规则：') + json.dumps(rules, ensure_ascii=False)[:2000], _tr('学生当前模型：\n') + model_text(model),
           _tr('沙箱里的实时进度（运行中估计）：') + json.dumps((live or {}).get('rules'), ensure_ascii=False, default=str)[:1500]]
    if last:
        ctx.append(_tr('最近一次提交的评分：') + json.dumps({'score': last.get('score'), 'details': [d.get('text') for d in last.get('details') or []]},
                                                ensure_ascii=False, default=str)[:1500])
    if pub['hints']:
        ctx.append(_tr('老师允许的提示（可以引用）：') + _tr('；').join(pub['hints']))
    if cat:
        ctx.append(catalog_text(cat))
    msgs = [{'role': 'system', 'content': SYSTEM_PLANT}, {'role': 'system', 'content': '\n\n'.join(ctx)}]
    for h in (history or [])[-6:]:
        if h.get('role') in ('user', 'assistant') and isinstance(h.get('content'), str):
            msgs.append({'role': h['role'], 'content': h['content'][:2000]})
    msgs.append({'role': 'user', 'content': (question or _tr('我下一步该做什么？')).strip()[:1000]})
    return msgs


TIMEOUT = float(os.environ.get('VF_TUTOR_TIMEOUT', 90))


async def _ask_llm(msgs, meter=None):
    """调大模型；超时或网关出错返回 None（学生端给友好提示，不显示错误码）。meter：按单位计量（5.0，tenancy/aiproxy）。
    单位的 AI 额度用完 / 没开通：抛出 403 的说明（学生要知道为什么用不了）。"""
    try:
        call = (lambda: copilot.chat(msgs, meter=meter)) if meter is not None else (lambda: copilot.chat(msgs))
        return await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, call), TIMEOUT)
    except HTTPException as e:
        if e.status_code == 403:
            raise
        return None
    except (asyncio.TimeoutError, Exception):
        return None


def point_of(cat, key, label=None):
    c = (cat or {}).get(key)
    if not c:
        return None
    return {'key': key, 'label': label or c['label'], 'target': c['target'], 'goto': c.get('goto'), **({'plc': c['plc']} if c.get('plc') else {})}


def finish(content, cat):
    """大模型的回答 → (文本, 过滤过没有, 看这里的点)。先取出"看这里"标记，再过滤代码。"""
    text, pts = extract_points(content, cat or {})
    text, filtered = filter_answer(text)
    return text, filtered, pts


def _busy(hints, cat=None):
    h = (hints or [])
    tip = _tr('先看看提示 1：{v}', v=h[0]) if h else _tr('先对照任务书再检查一遍，看看哪个信号或动作和要求不一样。')
    pts = [p for p in (point_of(cat, 'tab:task', _tr('任务书')), point_of(cat, 'checklist')) if p]     # 没有大模型也能"看这里"：任务书、检查表
    if not copilot.llm_cfg().get('api_key'):
        return {'answer': _tr('AI 助教还没有接上大模型（请老师在系统设置里配置）。{tip}', tip=tip), 'filtered': False, 'fallback': True, 'points': pts}
    return {'answer': _tr('助教这会儿有点忙，没来得及看完你的情况。{tip}', tip=tip) + _tr('\n\n过一会儿再问我一次。'), 'filtered': False, 'fallback': True, 'points': pts}


def cell_catalog(t, rt, prog):
    from .teach import scenes
    try:
        comps = scenes.components(rt)
    except Exception:                                  # noqa: BLE001
        comps = []
    try:
        blocks = (rt.build_cfg() or {}).get('blocks') or []
    except Exception:                                  # noqa: BLE001
        blocks = []
    plc = ''
    try:
        plc = t.plc_id() or ''
    except Exception:                                  # noqa: BLE001
        pass
    return point_catalog('cell', blocks, comps, prog, plc)


def _meter(mgr, user):
    from .tenancy import aiproxy
    return aiproxy.meter_for(user, mgr)


async def answer(mgr, user, aid, question, history=None):
    from .teach import db
    from .teach.api import need_assignment, need_task, sub_view
    from .teach.tasks import LessonTask
    a = need_assignment(user, aid)
    if not a['tutor'] and not a['_teacher']:
        raise HTTPException(403, _tr('老师关闭了本任务的 AI 助教'))
    t = need_task(a)
    if t.kind == 'factory':                      # 提交工厂作业（4.4）没有沙箱，也不开 AI 助教
        raise HTTPException(400, _tr('工厂设计作业没有 AI 助教：有问题直接问老师'))
    pool = mgr.teach_pool
    rt = await pool.ensure(user['username'], a, t)
    r = db.q('select * from submissions where assignment_id=? and username=? order by id desc limit 1', (aid, user['username']), one=True)
    last = sub_view(r) if r else None
    if isinstance(t, LessonTask):
        ans = db.q('select data from answers where assignment_id=? and username=?', (aid, user['username']), one=True)
        model = t.artifact(rt)
        live = t.live(rt, db.jl(ans['data'], {}) if ans else {})
        cat = point_catalog('plant', model.get('blocks') or [], forbid=_forbidden_blocks(t.lesson.get('rules')))
        msgs = build_messages_plant(t, model, live, last, question, history, a['hints'], cat)
        msg = await _ask_llm(msgs, _meter(mgr, user))
        if msg is None:
            return _busy(t.public(a['hints']).get('hints'), cat)
        text, filtered, pts = finish((msg or {}).get('content') or '', cat)
        return {'answer': text or _tr('（助教没有回答，请换个问法）'), 'filtered': filtered, 'points': pts,
                'context': {'blocks': len(model.get('blocks') or []), 'last_score': last and last.get('score')}}
    s = t.scene
    prog = t.artifact(rt)
    trace = pool.trace(rt).text(60)
    cat = cell_catalog(t, rt, prog)
    msgs = build_messages(s, prog, trace, last, question, history, a['hints'], cat)
    msg = await _ask_llm(msgs, _meter(mgr, user))
    if msg is None:
        return _busy(t.public(a['hints']).get('hints'), cat)
    text, filtered, pts = finish((msg or {}).get('content') or '', cat)
    return {'answer': text or _tr('（助教没有回答，请换个问法）'), 'filtered': filtered, 'points': pts,
            'context': {'program_lines': len((program_text(prog)).split('\n')), 'trace_rows': len(pool.trace(rt).rows),
                        'last_score': last and last.get('score')}}


def register(app, mgr):
    @app.post('/api/tutor/ask')
    async def ask(request: Request, body: dict = Body(...)):
        try:
            aid = int(body.get('assignment_id'))
        except (TypeError, ValueError):
            raise HTTPException(400, _tr('缺少 assignment_id'))
        proxy = getattr(request.app.state, 'tutor_proxy', None)      # 客户端：转问学校服务器，或离线只给内置提示（teach/client.py）
        if proxy:
            r = await proxy(request.state.user, aid, body)
            if r is not None:
                return r
        return await answer(mgr, request.state.user, aid, body.get('question') or '', body.get('history'))

    @app.get('/api/tutor/hint')
    async def hint(request: Request, assignment_id: int, n: int = 1):
        """第 n 条提示（老师关了提示时返回空）：外壳的 AI 助教等待超过 15 秒时可以先显示这一条。"""
        from .teach.api import need_assignment, need_task
        a = need_assignment(request.state.user, assignment_id)
        hs = need_task(a).public(a['hints']).get('hints') or []
        return {'hint': hs[n - 1] if 0 < n <= len(hs) else None, 'total': len(hs)}

    @app.get('/api/tutor/status')
    async def status():
        return {'configured': bool(copilot.llm_cfg().get('api_key'))}
