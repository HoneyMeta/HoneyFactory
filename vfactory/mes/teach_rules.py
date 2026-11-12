"""MES 课（kind=mes）的评分取数：rules.register_mes 的取数函数（K 的规则引擎在评分进程里用 load_mes_providers 导入本模块）。

规则（声明式，课程 JSON 里写）：{key, kind: 'mes', query, where?, field?, answer_key?, rank?, op, value, weight, label?}
  query 见 vfmes/edu.py 的 QUERIES：work_order.count / work_order.done / report.count / report.good / oee.worst / oee.value / oee.count /
        ncr.count / ncr.traced / repair.for_worst_oee / part.count / trace.part / trace.ncr_match / spc.stable / spc.value
  answer_key：要和 MES 的结果核对的作答（课里另一条 kind=answer 的题号，例如 SPC 判断），取数函数返回 1（一致）/ 0。

取值顺序（provider(rule, ctx)）：
  1. ctx['mes_snapshot'][rule.key]：交作业时客户端在本机 MES 上取好的快照（学校服务器复评时用；服务器上没有 MES）。
  2. 本机正在运行的 MES（<数据目录>\\mes\\current.json；ctx['pid'] 给了的话要对得上）→ POST /api/edu/check。
  3. 都没有 → None（规则判"没有连上 MES"）。
作答：ctx['answers']；评分引擎目前不把作答放进 mes_ctx，这里把 rules.evaluate 包了一层，kind=mes 时把作答带进去。

给客户端交作业用：snapshot(rules, answers, pid=None) → {rule.key: 值}（放进 ctx['mes_snapshot']）。
"""
from ..i18n import _tr
import json
import logging
import urllib.request

from ..courses import rules as R

log = logging.getLogger('vfactory.mes.rules')


def _current(pid=None):
    from .. import paths
    try:
        with open(paths.home('mes', 'current.json'), encoding='utf-8') as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if pid and c.get('pid') != pid:
        return None
    return c


def _post(c, path, body, timeout=15):
    req = urllib.request.Request(f"http://127.0.0.1:{c['port']}{path}", method='POST', data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                                 headers={'Content-Type': 'application/json', 'x-hm-key': c['key']})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return json.loads(r.read())


RULE_KEYS = ('key', 'query', 'where', 'field', 'answer_key', 'rank', 'sn_key', 'machine_key', 'heat_key')


def provider(rule, ctx):
    ctx = ctx or {}
    snap = ctx.get('mes_snapshot')
    if isinstance(snap, dict) and rule.get('key') in snap:
        return snap[rule['key']]
    c = _current(ctx.get('pid'))
    if not c:
        return None
    body = {k: rule[k] for k in RULE_KEYS if k in rule}
    body['answers'] = ctx.get('answers') or {}
    try:
        return _post(c, '/api/edu/check', body).get('value')
    except Exception as e:                       # noqa: BLE001  MES 没在跑 / 端口变了
        log.info(_tr('MES 取数失败：%s'), e)
        return None


def snapshot(rules, answers=None, pid=None):
    """在本机 MES 上一次取全部 MES 规则的值。没有 MES 时返回 {}。"""
    c = _current(pid)
    if not c:
        return {}
    rs = [{k: r[k] for k in RULE_KEYS if k in r} for r in rules or [] if isinstance(r, dict) and r.get('kind') == 'mes']
    if not rs:
        return {}
    try:
        return _post(c, '/api/edu/snapshot', {'rules': rs, 'answers': answers or {}}).get('values') or {}
    except Exception as e:                       # noqa: BLE001
        log.info(_tr('MES 快照失败：%s'), e)
        return {}


R.register_mes(provider)

# 评分引擎调用 evaluate(rule, metrics, answers, lesson, course_id, mes_ctx)：MES 规则需要核对作答时，把作答放进 mes_ctx
if not getattr(R.evaluate, '_mes_answers', False):
    _orig_evaluate = R.evaluate

    def _evaluate(rule, metrics=None, answers=None, lesson=None, course_id=None, mes_ctx=None):
        if isinstance(rule, dict) and rule.get('kind') == 'mes' and answers and not (mes_ctx or {}).get('answers'):
            mes_ctx = {**(mes_ctx or {}), 'answers': answers}
        return _orig_evaluate(rule, metrics, answers, lesson, course_id, mes_ctx)
    _evaluate._mes_answers = True
    R.evaluate = _evaluate

