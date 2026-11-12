"""AI 代理与计量：大模型的密钥只在服务器上（config/llm.local.json 或 VF_LLM_*），客户端的 AI 助手/助教经服务器转发。

  POST /api/ai/proxy/chat/completions   OpenAI 兼容（只收 messages、tools、tool_choice、temperature、max_tokens；模型由服务器定）
  GET  /api/ai/quota                    本单位本月的 AI 用量和额度
计量：按单位、按月记 tokens（上游返回的 usage.total_tokens；没有就按字数估）。额度 = 单位的 ai_quota（每月 tokens，SaaS 在运维后台设，
自部署在授权文件里；空 = 不限）。用完了：本单位的 AI 功能停用到下个月（或增加额度），给明确提示。功能包里关掉 ai 时也停用。
服务器自己调大模型的地方（AI 助教 /api/tutor/ask、AI 辅助评分）用 meter_for(user) 一样计量。
测试：VF_LLM_FAKE=1 时不连上游，回一个假回答（usage 按字数估），计量照常。
"""
from ..i18n import _tr
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

from fastapi import Body, HTTPException, Request

from .. import store
from .schema import DEFAULT_ORG

MAX_PROXY_BYTES = 8 * 1024 * 1024
KEEP = ('messages', 'tools', 'tool_choice', 'temperature', 'max_tokens')


def month():
    return datetime.now().strftime('%Y-%m')


def month_usage(oid, m=None):
    r = store.q('select tokens, calls from ai_usage where org=? and month=?', (oid or DEFAULT_ORG, m or month()), one=True)
    return {'tokens': (r or {}).get('tokens') or 0, 'calls': (r or {}).get('calls') or 0}


def total_usage(oid):
    return store.q('select coalesce(sum(tokens),0) n from ai_usage where org=?', (oid or DEFAULT_ORG,), one=True)['n']


def status(oid):
    from . import seats
    lim = seats.limits(oid)
    used = month_usage(oid)
    q = lim.get('ai_quota')
    enabled = bool(lim['features'].get('ai', True))
    left = None if q is None else max(0, int(q) - used['tokens'])
    return {'enabled': enabled, 'quota': q, 'used': used['tokens'], 'calls': used['calls'], 'left': left, 'month': month(),
            'blocked': (not enabled) or (left is not None and left <= 0)}


def check(oid):
    s = status(oid)
    if not s['enabled']:
        raise HTTPException(403, _tr('本单位没有开通 AI 功能包，AI 助手和 AI 助教用不了；请联系单位管理员'))
    if s['left'] is not None and s['left'] <= 0:
        raise HTTPException(403, _tr('本单位本月的 AI 额度（{quota:,} tokens）已经用完，AI 功能暂停到下个月；需要更多额度请联系单位管理员或蜂元', quota=s['quota']))


def charge(oid, tokens, calls=1):
    tokens = max(0, int(tokens or 0))
    oid = oid or DEFAULT_ORG
    store.x('insert into ai_usage(org, month, tokens, calls) values(?,?,?,?) on conflict(org, month) do update set tokens=tokens+excluded.tokens, '
            'calls=calls+excluded.calls', (oid, month(), tokens, calls))


def estimate(obj):
    """没有 usage 时粗估：中文大约 1 字 1 token，英文 4 字符 1 token；按 JSON 长度的一半算（偏保守）。"""
    try:
        return max(1, len(json.dumps(obj, ensure_ascii=False)) // 2)
    except (TypeError, ValueError):
        return 1


class Meter:
    """copilot.chat(..., meter=Meter(org))：调用前查额度，调用后记用量。"""

    def __init__(self, oid):
        self.oid = oid or DEFAULT_ORG

    def check(self):
        check(self.oid)

    def charge(self, usage, request_obj=None, reply_obj=None):
        n = (usage or {}).get('total_tokens') if isinstance(usage, dict) else None
        if not n:
            n = estimate(request_obj) + estimate(reply_obj)
        charge(self.oid, n)


def meter_for(user, mgr=None):
    """服务器上替某个账号调大模型时的计量器；客户端（桌面模式）本机不计（经服务器代理时由服务器计）。"""
    if not user or getattr(mgr, 'desktop', None) or os.environ.get('VF_DESKTOP') == '1':
        return None
    return Meter(user.get('org') or store.org_of(user.get('username')))


def class_meter(class_id):
    """按班级所属单位计量（AI 辅助评分用）；客户端进程里返回 None。"""
    try:
        from ..teach import client as tclient
        if tclient.is_desktop_proc():
            return None
    except Exception:                            # noqa: BLE001
        pass
    r = store.q('select org from classes where id=?', (class_id,), one=True)
    return Meter((r or {}).get('org') or DEFAULT_ORG)


def _fake(body):
    msgs = body.get('messages') or []
    last = next((m.get('content') for m in reversed(msgs) if m.get('role') == 'user'), '') or ''
    if isinstance(last, list):
        last = ' '.join(str(x.get('text') or '') for x in last if isinstance(x, dict))
    reply = {'role': 'assistant', 'content': _tr('（测试用假模型）收到 {len} 条消息，最后一条是：{v}', len=len(msgs), v=str(last)[:60])}
    n = estimate(msgs) + estimate(reply)
    return {'id': 'fake-' + str(int(time.time() * 1000)), 'object': 'chat.completion', 'model': 'fake',
            'choices': [{'index': 0, 'message': reply, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': n - estimate(reply),
                                                                                         'completion_tokens': estimate(reply), 'total_tokens': n}}


def upstream(body):
    """把请求交给服务器配置的大模型（OpenAI 兼容）。→ 上游的完整 JSON。"""
    from .. import copilot
    if os.environ.get('VF_LLM_FAKE') == '1':
        return _fake(body)
    c = copilot.server_llm_cfg()
    if not c.get('api_key'):
        raise HTTPException(503, _tr('服务器还没有配置大模型（运维：config/llm.local.json 或 VF_LLM_API_KEY）'))
    out = {k: body[k] for k in KEEP if k in body}
    out['model'] = c['model']
    if 'max_tokens' in out:
        try:
            out['max_tokens'] = max(1, min(8192, int(out['max_tokens'])))
        except (TypeError, ValueError):
            out.pop('max_tokens')
    req = urllib.request.Request(c['base_url'].rstrip('/') + '/chat/completions', data=json.dumps(out).encode('utf-8'),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + c['api_key']})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(getattr(e, 'reason', e))
        time.sleep(2 * (attempt + 1))
    raise HTTPException(502, _tr('大模型接口出错（{last}），请稍后再试', last=last))


def register(app, mgr):
    if getattr(mgr, 'desktop', None):
        return                                   # 客户端本机没有代理（它自己经服务器代理）

    @app.post('/api/ai/proxy/chat/completions')
    async def proxy(request: Request, body: dict = Body(...)):
        """AI 代理（OpenAI 兼容）：客户端的 AI 助手、AI 助教经这里调大模型；密钥只在服务器上。按单位计量，额度用完返回 403。"""
        u = request.state.user
        oid = u.get('org') or DEFAULT_ORG
        msgs = body.get('messages')
        if not isinstance(msgs, list) or not msgs:
            raise HTTPException(400, _tr('缺少 messages'))
        if len(json.dumps(body, ensure_ascii=False)) > MAX_PROXY_BYTES:
            raise HTTPException(413, _tr('这次 AI 请求太大了（超过 8 MB）'))
        check(oid)
        import asyncio
        r = await asyncio.get_running_loop().run_in_executor(None, upstream, body)
        n = (r.get('usage') or {}).get('total_tokens') if isinstance(r, dict) else None
        charge(oid, n or (estimate(msgs) + estimate((r or {}).get('choices'))))
        return r

    @app.get('/api/ai/quota')
    async def quota(request: Request):
        """本单位本月的 AI 用量、额度、是否可用。"""
        u = request.state.user
        return status(u.get('org') or DEFAULT_ORG)
