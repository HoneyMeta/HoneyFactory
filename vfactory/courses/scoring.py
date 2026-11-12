"""产线课（plant / diagnose）的评分：用学生的模型，按本课规定的随机种子和时长离线跑一遍，按规则打分。

返回结构与控制层 score_scene 一致：{ok, score, max, details:[...], stats, log, error?}；
details 每项：{key, label, kind, op, target, value, weight, score, ok, text}，另带别名 rule/got/want/pts。

规则（lesson.rules）：
  {"key","kind":"kpi","metric":"good_per_h","op":">=","value":55,"weight":40,"label":…}
  {"kind":"budget","op":"<=","value":120}                         成本合计（costs.py，可被 lesson.costs 覆盖）
  {"kind":"limit","metric":"count.processor","op":"<=","value":5}  数量/布局：count.<类型>、count_all、overlap、outside、buffer_total、operators、vehicles
  {"kind":"answer","choices":[...],"answer":1} / {"kind":"answer","pick":true,"kinds":["processor"],"answer":["M3"]}
指标（metric）：good、good_per_h、scrap、scrap_rate、wip_avg、wip_max、lead_mean_min、lead_p90_min、oee_avg、energy_kwh、kwh_per_good、
  escape、orders_done、orders_late、orders_open、util.<块>、blocked.<块>、starved.<块>、failed.<块>、oee.<块>、cost、count.<类型> …

防作弊（lesson.lock）：{"blocks":[锁定的块编号], "params":{类型:[参数…]}, "plan": true | ["orders"]}
  锁定块的参数、按类型固定的参数（新加的块必须和某台原有同类设备一样）、生产计划都按本课原始模型恢复，并在日志里说明。
  排故课（lesson.faults）里被"弄坏"的参数，只承认"坏值"和"正常值"两种。
"""
from __future__ import annotations

from ..i18n import _tr
import copy
import json
import math

from .costs import model_cost

OPS = {'>=': lambda a, b: a >= b - 1e-9, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b + 1e-9, '<': lambda a, b: a < b,
       '==': lambda a, b: (abs(a - b) < 1e-6) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else a == b,
       '!=': lambda a, b: a != b}
OP_CN = {'>=': '≥', '>': '>', '<=': '≤', '<': '<', '==': '=', '!=': '≠'}
METRIC_CN = {'good': '合格产出', 'good_per_h': '小时产出', 'scrap': '报废件数', 'scrap_rate': '废品率', 'wip_avg': '平均在制品', 'wip_max': '最大在制品',
             'lead_mean_min': '平均生产周期（分钟）', 'lead_p90_min': '生产周期 P90（分钟）', 'oee_avg': '平均 OEE', 'energy_kwh': '用电（kWh）',
             'kwh_per_good': '单件电耗（kWh）', 'escape': '漏检件数', 'orders_done': '完成订单数', 'orders_late': '延期订单数', 'orders_open': '未完成订单数',
             'cost': '投资（万元）', 'count_all': '设备总数', 'buffer_total': '缓存总容量', 'operators': '操作工人数', 'vehicles': '搬运车辆数',
             'overlap': '重叠的设备对数', 'outside': '超出厂房的设备数'}
SIM_KINDS = ('kpi',)


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ---------------- 防作弊：把不允许改的东西恢复成本课原样 ----------------
def enforce(model, lesson, original):
    m = copy.deepcopy(model)
    notes = []
    lock = lesson.get('lock') or {}
    orig = {b['id']: b for b in original.get('blocks') or []}
    blocks = {b['id']: b for b in m.get('blocks') or []}
    faults = {(f['block'], f['param']): f for f in lesson.get('faults') or []}
    # 4.6 老师做的产线课：structure = 不能增删设备和连线；editable = 只有这些 [块, 参数] 可以改，其余参数按本课原值
    if lock.get('structure'):
        ids = sorted(b['id'] for b in m.get('blocks') or [])
        lk = lambda L: sorted((x.get('from'), x.get('to')) for x in L or [])                     # noqa: E731
        if ids != sorted(orig) or lk(m.get('links')) != lk(original.get('links')):
            notes.append(_tr('这一课不能增删设备和连线：评分时按本课原来的设备和连线计算（你改的参数照样算）'))
            nb = []
            for ob in original.get('blocks') or []:
                b = blocks.get(ob['id'])
                x = copy.deepcopy(ob)
                if b is not None:
                    x['params'] = copy.deepcopy(b.get('params') or {})
                nb.append(x)
            m['blocks'] = nb
            m['links'] = copy.deepcopy(original.get('links') or [])
            blocks = {b['id']: b for b in m['blocks']}
    if lock.get('editable') is not None:
        allowed = {(str(e[0]), str(e[1])) for e in lock.get('editable') or [] if isinstance(e, (list, tuple)) and len(e) >= 2}
        for bid, ob in orig.items():
            b = blocks.get(bid)
            if b is None:
                continue
            cur = b.get('params') or {}
            want = copy.deepcopy(ob.get('params') or {})
            for (bb, pp) in allowed:
                if bb == bid:
                    if pp in cur:
                        want[pp] = copy.deepcopy(cur[pp])
                    else:
                        want.pop(pp, None)
            if cur != want:
                bad = sorted(k for k in set(cur) | set(want) if not _same(cur.get(k), want.get(k)))
                notes.append(_tr('{v} 的「{join}」不是本课允许改的参数，评分时按原值计算', v=b.get("name") or bid, join=_tr('、').join(bad[:4])))
                b['params'] = want
    for bid in lock.get('blocks') or []:
        ob = orig.get(bid)
        if ob is None:
            continue
        b = blocks.get(bid)
        if b is None:
            m.setdefault('blocks', []).append(copy.deepcopy(ob))
            notes.append(_tr('{v} 是本课固定的设备，不能删除，已按原样放回（连线需要自己接）', v=ob.get("name") or bid))
            continue
        want = copy.deepcopy(ob.get('params') or {})
        for (fb, fp), f in faults.items():
            if fb == bid and fp in (b.get('params') or {}):
                want[fp] = (b['params'] or {})[fp] if _same((b['params'] or {}).get(fp), (ob.get('params') or {}).get(fp)) else f['value']
        if (b.get('params') or {}) != want:
            notes.append(_tr('{v} 的参数是本课规定的，评分时按原值计算', v=b.get("name") or bid))
            b['params'] = want
    for typ, keys in (lock.get('params') or {}).items():
        ref = [ob for ob in orig.values() if ob.get('type') == typ]
        if not ref:
            continue
        for b in m.get('blocks') or []:
            if b.get('type') != typ:
                continue
            p = b.setdefault('params', {})
            ob = orig.get(b['id']) if orig.get(b['id'], {}).get('type') == typ else None
            for k in keys:
                cur = p.get(k)
                if ob is not None:
                    allowed = [(ob.get('params') or {}).get(k)]
                    f = faults.get((b['id'], k))
                    if f:
                        allowed = [f['value'], (ob.get('params') or {}).get(k)]
                else:
                    allowed = [(x.get('params') or {}).get(k) for x in ref]
                if any(_same(cur, a) for a in allowed):
                    continue
                fix = allowed[0]
                if fix is None:
                    p.pop(k, None)
                else:
                    p[k] = copy.deepcopy(fix)
                notes.append(_tr('{v} 的「{k}」是设备本身的能力，不能改，评分时按 {fix} 计算', v=b.get("name") or b["id"], k=k, fix=fix))
    pl = lock.get('plan')
    if pl:
        op = copy.deepcopy(original.get('plan') or {})
        if pl is True:
            if _plan_key(m.get('plan')) != _plan_key(op):
                notes.append(_tr('生产计划（班次、产品、订单）是本课规定的，评分时按原计划计算'))
            m['plan'] = op
        else:
            sp = m.get('plan') or {}
            newp = copy.deepcopy(op)
            for key in pl:
                if key == 'orders':
                    a = sorted((o.get('code'), o.get('product'), o.get('qty'), str(o.get('due'))) for o in op.get('orders') or [])
                    b2 = sorted((o.get('code'), o.get('product'), o.get('qty'), str(o.get('due'))) for o in sp.get('orders') or [])
                    if a == b2:
                        newp['orders'] = [{k: o.get(k) for k in ('code', 'product', 'qty', 'due', 'customer') if o.get(k) is not None}
                                          for o in sp.get('orders') or []]
                    else:
                        notes.append(_tr('订单的数量、产品和交期不能改，只能调整顺序；评分时按原订单计算'))
                elif key in sp:
                    newp[key] = copy.deepcopy(sp[key])
            m['plan'] = newp
    m.setdefault('plant', {})
    for k in ('seed', 'start', 'dt'):
        if k in (original.get('plant') or {}):
            m['plant'][k] = original['plant'][k]
    return m, notes


def _plan_key(p):
    """计划里真正影响结果的部分（运行时导出的计划会带上默认值和完成进度，不能直接比）。"""
    p = p or {}
    return (json.dumps([(x.get('start'), x.get('end')) for x in p.get('shifts') or []]), json.dumps([(x.get('start'), x.get('end')) for x in p.get('breaks') or []]),
            json.dumps(p.get('downtime') or [], sort_keys=True, default=str),
            json.dumps([(o.get('code'), o.get('product'), o.get('qty'), str(o.get('due'))) for o in p.get('orders') or []]),
            json.dumps(sorted(set(p.get('workdays') or [1, 2, 3, 4, 5, 6, 7]))))


def _same(a, b):
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


# ---------------- 静态指标（不用跑仿真） ----------------
def static_metrics(model, lesson):
    out = {}
    cost, rows = model_cost(model, lesson.get('costs'))
    out['cost'] = cost
    out['cost_rows'] = rows
    bl = model.get('blocks') or []
    real = [b for b in bl if b.get('type') not in ('source', 'sink', 'storage', 'transporter', 'operators')]
    out['count_all'] = len(real)
    for b in bl:
        k = 'count.' + b.get('type', '?')
        out[k] = out.get(k, 0) + 1
    out['buffer_total'] = sum(int(_num((b.get('params') or {}).get('capacity', 50))) for b in bl if b.get('type') == 'buffer')
    out['operators'] = sum(int(_num((b.get('params') or {}).get('count', 2))) for b in bl if b.get('type') == 'operators')
    out['vehicles'] = sum(int(_num((b.get('params') or {}).get('count', 2))) for b in bl if b.get('type') == 'transporter')
    fw, fh = ((model.get('plant') or {}).get('floor') or [999, 999])[:2]
    rects = []
    outside = 0
    for b in real:
        x, y = (b.get('pos') or [0, 0])[:2]
        w, h = (b.get('size') or [4, 4])[:2]
        if int(round(b.get('rot') or 0)) % 180 == 90:
            w, h = h, w
        if x < -0.01 or y < -0.01 or x + w > fw + 0.01 or y + h > fh + 0.01:
            outside += 1
        rects.append((x, y, x + w, y + h))
    ov = 0
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b2 = rects[i], rects[j]
            if a[0] < b2[2] - 0.05 and b2[0] < a[2] - 0.05 and a[1] < b2[3] - 0.05 and b2[1] < a[3] - 0.05:
                ov += 1
    for b in bl:
        if b.get('type') == 'conveyor':
            pp = b.get('params') or {}
            v = _num(pp.get('speed_mps', 0.2), 0.2)
            out['cool_min.' + b['id']] = round(_num(pp.get('length_m', 10), 10) / v / 60, 2) if v > 0 else None
            out['flow_per_h.' + b['id']] = round(v / max(0.01, _num(pp.get('pitch_m', 1), 1)) * 3600, 1)
    out['overlap'] = ov
    out['outside'] = outside
    return out


# ---------------- 仿真指标 ----------------
def sim_metrics(model, lesson):
    from .. import analysis, history
    from ..core import Plant
    cfg = copy.deepcopy(model)
    pl = cfg.setdefault('plant', {})
    warm = float(lesson.get('warmup_h', 0) or 0)
    hours = float(lesson.get('time_h', 8) or 8)
    pl['warmup_h'] = warm
    pl['seed'] = int(lesson.get('seed', pl.get('seed', 7)))
    pl.pop('modbus_port', None)
    p = Plant(cfg)
    done_at = {}

    def watch():
        for o in p.plan.orders:
            if o['code'] not in done_at and o['done'] >= o['qty']:
                done_at[o['code']] = p.now().strftime('%Y-%m-%d %H:%M')
    p.step_hooks.append(watch)
    if warm <= 0:
        p.hourly.append(history.snapshot(p))         # 统计从 0 时刻开始时，补一个起点快照（否则第一小时不计入）
    p.run_for((warm + hours) * 3600)
    t0, t1 = warm * 3600, p.t
    s = history.summary(p, t0, t1)
    st = analysis.stats(p, t0, t1)
    out = {'good': s['good'], 'good_per_h': s['good_per_h'], 'scrap': s['scrap'], 'scrap_rate': s['scrap_rate'], 'escape': s.get('escape', 0),
           'wip_avg': st['plant'].get('wip_avg'), 'wip_max': st['plant'].get('wip_max'),
           'lead_mean_min': round(st['plant']['lead_mean_h'] * 60, 2) if st['plant'].get('lead_mean_h') is not None else None,
           'lead_p90_min': round(st['plant']['lead_p90_h'] * 60, 2) if st['plant'].get('lead_p90_h') is not None else None,
           'oee_avg': st['plant'].get('oee_avg'), 'energy_kwh': s.get('energy_total'), 'kwh_per_good': s.get('kwh_per_good')}
    for o in st['objects']:
        sh = o.get('share') or {}
        out['util.' + o['id']] = sh.get('run', 0.0)
        out['blocked.' + o['id']] = sh.get('blocked', 0.0)
        out['starved.' + o['id']] = sh.get('starved', 0.0)
        out['failed.' + o['id']] = sh.get('failed', 0.0)
        if o.get('oee') is not None:
            out['oee.' + o['id']] = o['oee']
    orders = p.plan.orders
    if orders:
        late = 0
        for o in orders:
            due = str(o.get('due') or '')[:16]
            fin = done_at.get(o['code'])
            if due and (fin is None or fin > due):
                late += 1
        out['orders_done'] = sum(1 for o in orders if o['done'] >= o['qty'])
        out['orders_open'] = sum(1 for o in orders if o['done'] < o['qty'])
        out['orders_late'] = late
        out['orders'] = [{'code': o['code'], 'product': o.get('product'), 'qty': o['qty'], 'done': o['done'], 'due': o.get('due'),
                          'finished': done_at.get(o['code'])} for o in orders]
    bn = s.get('bottleneck') or []
    out['bottleneck'] = [b['name'] for b in bn[:3]]
    out['hours'] = hours
    return out


# ---------------- 打分 ----------------
def _label(r, lesson=None):
    """目标的标题（4.6.1）：老师的名称有意义（不是空的、"1"、一两个字）就用它，不然用生成的说明"8 小时合格品 ≥ 100 件"。"""
    from .rules import title_of
    return title_of(r, lesson) or r.get('key', '?')


def grade(lesson, metrics, answers, mes_ctx=None):
    """按规则打分（规则的判断在 rules.py，服务器和客户端共用）。"""
    from . import rules as R
    total = mx = 0.0
    details = []
    cid = lesson.get('_course')
    for r in lesson.get('rules') or []:
        kind = r.get('kind', 'kpi')
        w = float(r.get('weight', 0) or 0)
        mx += w
        op = r.get('op', '>=')
        target = r.get('value')
        ok, got = R.evaluate(r, metrics, answers, lesson, cid, mes_ctx)
        sc = w if ok else 0.0
        total += sc
        val = round(got, 4) if isinstance(got, float) else got
        lab = _label(r, lesson)
        d = {'goal': R.describe(r, lesson), 'title': lab}
        if kind == 'answer':
            text = _tr('{lab}：', lab=lab) + (_tr('回答正确') if ok else (_tr('还没有作答') if got is None or got == '' else _tr('回答不对')))
            val = None if got is None or got == '' else (_tr('已作答') if not ok else _tr('正确'))
            op, target = '==', (_tr('（点选）') if r.get('pick') else _tr('（') + R.QTYPE_CN.get(R.qtype(r), '作答') + _tr('）'))
            d['qtype'] = R.qtype(r)
        elif kind == 'mes':
            text = _tr('{lab} {get} {target}：MES 里实际 {v}', lab=lab, get=OP_CN.get(op, op), target=target, v=_tr('—（没有连上 MES）') if got is None else val)
        else:
            text = _tr('{lab} {get} {target}：实际 {v}', lab=lab, get=OP_CN.get(op, op), target=target, v="—" if val is None else val)
            d['value_text'] = R.fmt_value(R.metric_name(r), val)
        details.append({'key': r.get('key'), 'label': lab, 'kind': kind, 'op': op, 'target': target, 'value': val, 'weight': w, 'score': sc, 'ok': bool(ok),
                        'text': text, 'rule': r.get('key'), 'got': val, 'want': target, 'pts': sc, **d})
    return round(total, 2), round(mx, 2), details


NO_MODEL_KINDS = ('quiz', 'mes')


def score_lesson(lesson, model, original, answers=None):
    """评分入口（进程池里调用）。model：学生当前的模型；original：本课原始（正常）模型。"""
    log = []
    if lesson.get('kind') in NO_MODEL_KINDS:          # 4.6 测验课 / MES 操作课：没有工厂模型，只按作答 / MES 状态判
        try:
            ctx = dict(model) if isinstance(model, dict) else {}       # MES 取数上下文：学生、作业、pid、作答、交作业时的 MES 快照
            ctx.setdefault('answers', answers or {})
            sc, mx, det = grade(lesson, {}, answers, ctx)
            return {'ok': True, 'score': sc, 'max': mx, 'details': det, 'stats': {}, 'log': log}
        except Exception as e:                       # noqa: BLE001
            return {'ok': False, 'error': _tr('评分出错：{v}: {e}', v=type(e).__name__, e=e), 'score': 0.0, 'max': 100.0, 'details': [], 'log': log}
    try:
        from ..flow.model import validate
        v = validate(model)
        if not v['ok']:
            errs = [i['msg'] for i in v.get('issues') or [] if i.get('level') == 'error'][:3]
            return {'ok': True, 'score': 0.0, 'max': float(sum(float(r.get('weight', 0) or 0) for r in lesson.get('rules') or [])) or 100.0,
                    'details': [], 'stats': {}, 'log': errs, 'error': _tr('模型有错误，不能运行：') + _tr('；').join(errs)}
        m, notes = enforce(model, lesson, original)
        log += notes
        metrics = static_metrics(m, lesson)
        if any(r.get('kind', 'kpi') in SIM_KINDS for r in lesson.get('rules') or []):
            metrics.update(sim_metrics(m, lesson))
        sc, mx, det = grade(lesson, metrics, answers)
        stats = {k: v for k, v in metrics.items() if k != 'cost_rows' and not (isinstance(v, float) and math.isnan(v))}
        return {'ok': True, 'score': sc, 'max': mx, 'details': det, 'stats': stats, 'cost_rows': metrics.get('cost_rows'), 'log': log}
    except Exception as e:
        import traceback
        return {'ok': False, 'error': _tr('评分出错：{v}: {e}', v=type(e).__name__, e=e), 'score': 0.0, 'max': 100.0, 'details': [], 'log': log + [traceback.format_exc()[-800:]]}
