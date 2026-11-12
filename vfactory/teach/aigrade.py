"""AI 辅助评分（4.6）：老师在教学控制台"提交与复核"里让 AI 读学生的提交，按评分项给建议分和评语——只是建议，老师点"采用"或改过再保存复核才算成绩。

  GET  /api/teach/submissions/{sid}/ai_suggest            已有的建议（没有时 {suggestion: null}）
  POST /api/teach/submissions/{sid}/ai_suggest  {force?}  让 AI 看这次提交，生成建议 → {suggestion}
  POST /api/teach/submissions/{sid}/ai_decision {decision: accepted|edited|dismissed}   记下老师怎么处理（审计用，不改分）
  POST /api/teach/assignments/{aid}/ai_suggest_all {force?}   给全班每个学生最近一次提交生成建议（后台跑）→ {job}
  GET  /api/teach/ai_jobs/{job}                           批量进度 {total, done, failed, items:[{username, sid, status, error?}]}

AI 读的内容：评分项（自动检查的每一项：要求、结果、得分）、学生的程序 / 模型摘要 / 作答、自动试运行的记录、任务书摘要、老师的评分细则说明。
大模型走 copilot.chat（config/llm.local.json 或 VF_LLM_*，不在这里存任何密钥）。
测试 / 没有大模型时：环境变量 VF_LLM_FAKE=1（或 VF_AIGRADE_FAKE=1）用确定性的假模型（按自动检查结果写建议），界面照样标明"AI 建议"。
建议存在 ai_suggestions 表：{criteria:[{key, label, weight, auto, score, comment}], score（换算成 100 分）, comment, model, fake}。
"""
from ..i18n import _tr
import asyncio
import json
import os
import re
import time
import uuid

from fastapi import Body, HTTPException, Request

from .. import store
from . import db

SYSTEM = """你是职业院校"虚拟工厂"课程的阅卷助手，帮老师给学生的一次提交逐项打分、写评语。
规则（必须遵守）：
1. 只按给出的评分项打分，每项分数在 0 到该项满分之间；自动检查的结果是客观事实，不能和它矛盾（自动检查没通过的项，最多给一半分，除非你在程序/模型里看到明确理由，并在评语里写明）。
2. 自动检查以外的方面（程序结构、可读性、注释、方案是否合理）只在评语里说，必要时可以在"总体"里加减不超过 10 分。
3. 评语用简体中文，具体、可操作：指出做到了什么、哪里不对、下一步怎么改；每项不超过 60 字，总评不超过 120 字。不要给出完整答案程序。
4. 只输出一个 JSON 对象，不要输出其他文字：
{"criteria":[{"key":"评分项编号","score":数字,"comment":"评语"}],"score":总分(0-100),"comment":"总评"}"""


def _ready():
    db.x('create table if not exists ai_suggestions(sub_id integer primary key, assignment_id integer, username text, created text, status text, '
         'data text, error text, decision text, decided_by text, decided_at text)')


def fake_on():
    return os.environ.get('VF_LLM_FAKE') == '1' or os.environ.get('VF_AIGRADE_FAKE') == '1'


def criteria_of(sub, det):
    """评分项：自动检查的每一项；没有自动检查（工厂设计等）时用作业的检查项 / 一个"总体"项。"""
    out = []
    for d in det.get('details') or []:
        w = float(d.get('weight') or 0)
        out.append({'key': d.get('key') or d.get('rule') or d.get('label'), 'label': d.get('label') or d.get('key'), 'weight': w,
                    'auto': float(d.get('score', d.get('points', 0)) or 0), 'ok': d.get('ok', d.get('pass')), 'text': d.get('text') or ''})
    if not out:
        out.append({'key': 'overall', 'label': _tr('总体完成情况'), 'weight': 100.0, 'auto': None, 'ok': None, 'text': _tr('这个作业没有自动检查，按要求整体评价')})
    return out


def context_text(a, t, sub, det, crit):
    from ..tutor import model_text, program_text
    prog = db.jl(sub.get('program'), None)
    parts = [_tr('作业：{get}（类型 {getattr}）', get=a.get('title'), getattr=getattr(t, 'kind', '?'))]
    try:
        pub = t.public(True)
        md = pub.get('brief_md') or pub.get('task_md') or ''
        parts.append(_tr('任务书（节选）：\n') + md[:2500])
    except Exception:                                   # noqa: BLE001
        pass
    parts.append(_tr('评分项（自动检查结果）：\n') + '\n'.join(
        _tr('- {key}｜{label}｜满分 {weight:g}｜自动得分 {v}｜{text}', key=c['key'], label=c['label'], weight=c['weight'], v='—' if c['auto'] is None else format(c['auto'], 'g'), text=c['text']) for c in crit))
    if isinstance(prog, dict):
        if prog.get('model', {}).get('blocks') if isinstance(prog.get('model'), dict) else False:
            parts.append(_tr('学生的工厂模型：\n') + model_text(prog['model']))
            for k, v in (prog.get('programs') or {}).items():
                parts.append(_tr('PLC {k} 的程序：\n', k=k) + program_text(v)[:2500])
        elif prog.get('blocks'):
            parts.append(_tr('学生的产线模型：\n') + model_text(prog))
        elif prog.get('source') is not None:
            parts.append(_tr('学生的 PLC 程序：\n') + program_text(prog))
    ans = det.get('answers')
    if ans:
        parts.append(_tr('学生的作答：') + json.dumps(ans, ensure_ascii=False)[:1500])
    if det.get('stats'):
        st = {k: v for k, v in (det.get('stats') or {}).items() if isinstance(v, (int, float, str))}
        parts.append(_tr('运行统计：') + json.dumps(st, ensure_ascii=False)[:1500])
    if det.get('log'):
        parts.append(_tr('自动试运行记录（最后几条）：\n') + '\n'.join(str(x if isinstance(x, str) else x.get('msg', x)) for x in det['log'][-15:])[:2000])
    if det.get('error'):
        parts.append(_tr('评分出错信息：') + str(det['error'])[:400])
    return '\n\n'.join(parts)


def _fake(crit, det):
    """假模型：按自动检查写建议（测试用，结果确定）。"""
    out = []
    for c in crit:
        if c['auto'] is None:
            sc = round(c['weight'] * 0.8, 1)
            cm = _tr('（AI 测试模式）作业已提交，请老师结合工厂/程序看一遍再定分。')
        elif c['ok'] is False:
            sc = 0.0
            cm = _tr('（AI 测试模式）这一项没做到：{v}。先对照要求再试一次。', v=c['text'][:40])
        else:
            sc = c['weight']
            cm = _tr('（AI 测试模式）这一项做到了。')
        out.append({'key': c['key'], 'score': sc, 'comment': cm})
    tot = sum(x['score'] for x in out)
    mx = sum(c['weight'] for c in crit) or 100
    return {'criteria': out, 'score': round(tot / mx * 100, 1), 'comment': _tr('（AI 测试模式）总体按自动检查结果给出，请老师确认。'), 'model': 'fake'}


def _parse(text):
    if not text:
        raise ValueError(_tr('大模型没有返回内容'))
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        raise ValueError(_tr('大模型没有按 JSON 格式回答'))
    return json.loads(m.group(0))


def suggest_sync(a, t, sub):
    """生成一条建议（同步，放在线程里跑）。返回 data。"""
    det = db.jl(sub.get('details'), {}) or {}
    crit = criteria_of(sub, det)
    from ..tenancy import aiproxy
    meter = aiproxy.class_meter(a.get('class_id'))       # 5.0 按单位计量（客户端本机不计）
    if fake_on():
        if meter is not None:
            meter.check()
        raw = _fake(crit, det)
        if meter is not None:
            meter.charge(None, crit, raw)
    else:
        from .. import copilot
        msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': context_text(a, t, sub, det, crit)}]
        msg = copilot.chat(msgs, meter=meter)
        raw = _parse((msg or {}).get('content') or '')
        raw['model'] = copilot.llm_cfg().get('model')
    by = {str(x.get('key')): x for x in raw.get('criteria') or [] if isinstance(x, dict)}
    items = []
    for c in crit:
        x = by.get(str(c['key'])) or {}
        try:
            sc = float(x.get('score'))
        except (TypeError, ValueError):
            sc = c['auto'] if c['auto'] is not None else 0.0
        sc = max(0.0, min(c['weight'], sc))
        items.append({**{k: c[k] for k in ('key', 'label', 'weight', 'auto', 'ok')}, 'score': round(sc, 1), 'comment': str(x.get('comment') or '')[:300]})
    mx = sum(c['weight'] for c in crit) or 100
    base = sum(i['score'] for i in items) / mx * 100
    try:
        total = float(raw.get('score'))
        if abs(total - base) > 10:                           # 总分只能在逐项合计上下 10 分以内（见 SYSTEM 第 2 条）
            total = base + (10 if total > base else -10)
    except (TypeError, ValueError):
        total = base
    return {'criteria': items, 'score': round(max(0.0, min(100.0, total)), 1), 'base': round(base, 1), 'comment': str(raw.get('comment') or '')[:500],
            'model': raw.get('model'), 'fake': fake_on(), 'auto_score': sub.get('auto_score'), 'at': store.now()}


def _view(r):
    if not r:
        return None
    return {'sub_id': r['sub_id'], 'status': r['status'], 'created': r['created'], 'error': r['error'], 'decision': r['decision'],
            'decided_by': r['decided_by'], **(db.jl(r['data'], {}) or {})}


JOBS: dict = {}


def register(app, mgr):
    from .api import need_assignment, need_task, need_teacher
    _ready()

    def need_sub(request, sid):
        u = need_teacher(request)
        s = db.q('select * from submissions where id=?', (sid,), one=True)
        if not s:
            raise HTTPException(404, _tr('没有这次提交'))
        a = need_assignment(u, s['assignment_id'], teacher=True)
        return u, a, s

    async def run_one(a, s, force=False):
        if not force:
            old = db.q('select * from ai_suggestions where sub_id=?', (s['id'],), one=True)
            if old and old['status'] == 'ok':
                return _view(old)
        t = need_task(a)
        db.x('insert or replace into ai_suggestions(sub_id, assignment_id, username, created, status, data) values(?,?,?,?,?,?)',
             (s['id'], a['id'], s['username'], store.now(), 'running', None))
        try:
            data = await asyncio.get_running_loop().run_in_executor(None, suggest_sync, a, t, s)
            db.x('update ai_suggestions set status=?, data=?, error=null where sub_id=?', ('ok', json.dumps(data, ensure_ascii=False), s['id']))
        except Exception as e:                                # noqa: BLE001  大模型没接 / 超时 / 格式不对：记下原因
            msg = getattr(e, 'detail', None) or str(e)
            db.x('update ai_suggestions set status=?, error=? where sub_id=?', ('error', str(msg)[:400], s['id']))
        return _view(db.q('select * from ai_suggestions where sub_id=?', (s['id'],), one=True))

    @app.get('/api/teach/submissions/{sid}/ai_suggest')
    async def get_one(sid: int, request: Request):
        need_sub(request, sid)
        return {'suggestion': _view(db.q('select * from ai_suggestions where sub_id=?', (sid,), one=True)), 'fake': fake_on()}

    @app.post('/api/teach/submissions/{sid}/ai_suggest')
    async def make_one(sid: int, request: Request, body: dict = Body(default={})):
        _u, a, s = need_sub(request, sid)
        v = await run_one(a, s, bool((body or {}).get('force')))
        if v and v['status'] == 'error':
            raise HTTPException(502, _tr('AI 没能给出建议：') + (v.get('error') or ''))
        return {'suggestion': v, 'fake': fake_on()}

    @app.post('/api/teach/submissions/{sid}/ai_decision')
    async def decide(sid: int, request: Request, body: dict = Body(...)):
        u, _a, _s = need_sub(request, sid)
        d = str(body.get('decision') or '')
        if d not in ('accepted', 'edited', 'dismissed'):
            raise HTTPException(400, _tr('decision 只能是 accepted / edited / dismissed'))
        db.x('update ai_suggestions set decision=?, decided_by=?, decided_at=? where sub_id=?', (d, u['username'], store.now(), sid))
        return {'ok': True}

    @app.post('/api/teach/assignments/{aid}/ai_suggest_all')
    async def make_all(aid: int, request: Request, body: dict = Body(default={})):
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        force = bool((body or {}).get('force'))
        subs = []
        for un in db.members(a['class_id']):
            s = db.q("select * from submissions where assignment_id=? and username=? and status in ('scored','submitted','reviewed') and coalesce(trial,0)=0 "
                     'order by id desc limit 1', (aid, un), one=True)
            if s:
                subs.append(s)
        jid = uuid.uuid4().hex[:10]
        job = {'id': jid, 'assignment_id': aid, 'total': len(subs), 'done': 0, 'failed': 0, 'running': True, 'started': time.time(),
               'items': [{'username': s['username'], 'sid': s['id'], 'status': 'waiting'} for s in subs], 'by': u['username']}
        JOBS[jid] = job

        async def work():
            sem = asyncio.Semaphore(3)

            async def one(i, s):
                async with sem:
                    job['items'][i]['status'] = 'running'
                    v = await run_one(a, s, force)
                    ok = bool(v) and v['status'] == 'ok'
                    job['items'][i].update(status='ok' if ok else 'error', error=(v or {}).get('error'), score=(v or {}).get('score'))
                    job['done'] += 1
                    if not ok:
                        job['failed'] += 1
            await asyncio.gather(*(one(i, s) for i, s in enumerate(subs)))
            job['running'] = False
        asyncio.get_running_loop().create_task(work())
        return {'job': jid, 'total': len(subs), 'fake': fake_on()}

    @app.get('/api/teach/assignments/{aid}/ai_suggestions')
    async def list_for(aid: int, request: Request):
        u = need_teacher(request)
        need_assignment(u, aid, teacher=True)
        return {'items': [_view(r) for r in db.q('select * from ai_suggestions where assignment_id=? order by sub_id desc', (aid,))], 'fake': fake_on()}

    @app.get('/api/teach/ai_jobs/{jid}')
    async def job_get(jid: str, request: Request):
        u = need_teacher(request)
        j = JOBS.get(jid)
        if not j or (u['role'] != 'admin' and j['by'] != u['username']):
            raise HTTPException(404, _tr('没有这个批量任务'))
        return {k: v for k, v in j.items() if k != 'by'}
