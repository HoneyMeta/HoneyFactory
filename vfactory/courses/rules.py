"""评分规则引擎（4.6）：所有评分规则都是声明式数据，没有任何可执行代码。

同一份代码在两边跑：学校服务器（权威评分）和客户端（桌面模式的本机后端，离线时的本机预估分）——客户端就是同一个 vfactory 包，
所以只要规则、学生的作答/模型/程序、随机种子一样，两边的分数一定一样。课程包里写着 engine = RULES_VERSION，客户端的引擎比课程要求的旧时
给出"本机预估分可能不准"的提示。

规则 rule = {key, kind, label?, weight, …}（kind 默认 kpi）：
  kpi     {metric, op, value}                     仿真指标：本课 time_h 小时、固定随机种子 seed（warmup_h 预热）跑完后取值，如 good、good_per_h、oee.<块>
  budget  {op, value}                             投资合计（万元，costs.py）
  limit   {metric, op, value}                     静态数量/布局：count.<类型>、count_all、buffer_total、operators、vehicles、overlap、outside
  answer  作答题（选择、判断、填数、在图上点选）：
            {choices:[…], answer: 1}                          单选（qtype 缺省 = single），answer 是选项下标
            {qtype:'multi', choices:[…], answer:[0, 2]}        多选：选的集合完全一致才得分
            {qtype:'tf', answer: true}                         判断
            {qtype:'number', answer: 12.5, tol: 0.5, unit?}    填数：|作答 − answer| ≤ tol
            {pick: true, kinds?:[类型], answer: ['M3'] | 'M3'}  在流程图/平面图/三维里点一台设备：点中其中之一
            每道题都可以带 explain（解析，4.6.2）：评分后按老师的设置（提交后 / 截止后 / 不显示）和正确答案一起给学生看
  mes     {query, field?, where?, op, value}      对 MES 状态的声明式检查（MES 课；由 MES 模块注册取数函数，见 register_mes）
  PLC 课（kind=cell）的规则仍是场景格式 {key, op, value, weight}：key 是统计量或测试序列里检查项的 key（control/scoring.py），
  老师在课里可以选用场景的哪些评分项（rubric）、追加自己的测试步骤（tests）和评分项（extra_rules），见 scenes.overlay_scene。
op：>= > <= < == !=（数值比较带 1e-9 容差）。

离线课程包里的答案是"封存"的（seal：按课程/课/题号派生的异或混淆，不是加密）：客户端能离线判分就一定能还原答案，
所以权威分永远是学校服务器重新评的分；混淆只是不让答案直接摆在 JSON 里。
"""
from __future__ import annotations

from ..i18n import _tr
import base64
import hashlib
import json
import math

RULES_VERSION = 1
OPS = {'>=': lambda a, b: a >= b - 1e-9, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b + 1e-9, '<': lambda a, b: a < b,
       '==': lambda a, b: (abs(a - b) < 1e-6) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else a == b,
       '!=': lambda a, b: a != b}
OP_CN = {'>=': '≥', '>': '>', '<=': '≤', '<': '<', '==': '=', '!=': '≠'}
KINDS = ('kpi', 'budget', 'limit', 'answer', 'mes')
QTYPES = ('single', 'multi', 'tf', 'number')
QTYPE_CN = {'single': '单选题', 'multi': '多选题', 'tf': '判断题', 'number': '填数题', 'pick': '点选题'}
_MES_PROVIDERS: list = []


# ---------------- MES 取数（M 的教学 MES 在这里挂函数） ----------------
def register_mes(fn):
    """fn(rule, ctx) → 值（数字 / 字符串 / None）。ctx = {'username', 'assignment_id', 'lesson', 'pid'}。
    多个取数函数按注册顺序试，第一个不返回 None 的为准；一个都没有时 MES 规则判"未连接 MES"，不得分。"""
    if fn not in _MES_PROVIDERS:
        _MES_PROVIDERS.append(fn)
    return fn


MES_MODULES = ('vfactory.teachmes.rules', 'vfactory.mes.teach_rules')


def load_mes_providers():
    """评分在进程池里跑（新进程）：按约定的模块名导入 MES 的取数函数（模块里调用 register_mes）。
    也可以用环境变量 VF_MES_RULE_MODULES=模块1,模块2 指定。没有这些模块时什么也不做。"""
    import importlib
    import os
    for m in list(MES_MODULES) + [x.strip() for x in os.environ.get('VF_MES_RULE_MODULES', '').split(',') if x.strip()]:
        try:
            importlib.import_module(m)
        except Exception:                               # noqa: BLE001
            pass


def mes_value(rule, ctx):
    for fn in _MES_PROVIDERS:
        try:
            v = fn(rule, ctx or {})
        except Exception:                               # noqa: BLE001  取数出错 = 没取到
            v = None
        if v is not None:
            return v
    return None


# ---------------- 答案封存 ----------------
def _stream(salt, n):
    out = b''
    i = 0
    while len(out) < n:
        out += hashlib.sha256(f'{salt}#{i}'.encode('utf-8')).digest()
        i += 1
    return out[:n]


def seal_value(v, salt):
    b = json.dumps(v, ensure_ascii=False).encode('utf-8')
    return base64.b64encode(bytes(x ^ y for x, y in zip(b, _stream(salt, len(b))))).decode('ascii')


def unseal_value(s, salt):
    b = base64.b64decode(s)
    return json.loads(bytes(x ^ y for x, y in zip(b, _stream(salt, len(b)))).decode('utf-8'))


def _salt(course_id, lesson_id, key):
    return f'vfcourse|{course_id}|{lesson_id}|{key}'


def seal_lesson(lesson, course_id):
    """课程包用：把作答题的 answer 换成 seal（服务器自己评分用原始课程，不封存）。4.6.2：解析 explain 往往就是答案，一起封存成 explain_seal。"""
    for r in lesson.get('rules') or []:
        if r.get('kind') == 'answer' and 'answer' in r:
            r['seal'] = seal_value(r.pop('answer'), _salt(course_id, lesson.get('id'), r.get('key')))
        if r.get('kind') == 'answer' and r.get('explain'):
            r['explain_seal'] = seal_value(str(r.pop('explain')), _salt(course_id, lesson.get('id'), r.get('key')) + '|explain')
        r.pop('explain', None)
    return lesson


def explain_of(rule, lesson=None, course_id=None):
    """作答题的解析（4.6.2，可选）：明文 explain，或课程包里封存的 explain_seal。没有 = ''。"""
    if rule.get('explain'):
        return str(rule['explain']).strip()
    if rule.get('explain_seal'):
        try:
            return str(unseal_value(rule['explain_seal'], _salt(course_id or rule.get('_course'), (lesson or {}).get('id') or rule.get('_lesson'),
                                                                 rule.get('key')) + '|explain')).strip()
        except Exception:                               # noqa: BLE001
            return ''
    return ''


def answer_text(rule, v, names=None, correct=False):
    """作答 / 正确答案 → 给学生看的一句话（4.6.2 提交后显示答案）："B. 废品箱"、"对"、"60 秒"、"M1（1#数控车床）"。
    names：{设备编号: 名称}（点选题用）；correct=True 时填数题带允许误差、点选题多个答案用"或"连。没作答 = ''。"""
    if v is None or v == '' or (isinstance(v, list) and not v):
        return ''
    t = qtype(rule)
    letters = 'ABCDEFGHIJ'
    ch = rule.get('choices') or []

    def opt(i):
        try:
            k = int(float(i))
        except (TypeError, ValueError):
            return str(i)
        if 0 <= k < len(ch):
            return f'{letters[k] if k < len(letters) else k + 1}. {ch[k]}'
        return str(i)
    if t == 'single':
        return opt(v)
    if t == 'multi':
        xs = []
        for x in _as_list(v):
            try:
                xs.append(int(float(x)))
            except (TypeError, ValueError):
                continue
        return _tr('；').join(opt(x) for x in sorted(set(xs)))
    if t == 'tf':
        b = _bool(v)
        return _tr('对') if b else _tr('错') if b is False else str(v)
    if t == 'number':
        n = _num(v)
        unit = str(rule.get('unit') or '').strip()
        s = (fmt_num(n) if n is not None else str(v)) + (' ' + unit if unit and unit != '%' else unit if unit == '%' else '')
        tol = _num(rule.get('tol'))
        return s + (_tr('（允许误差 ±{fmt_num}）', fmt_num=fmt_num(tol)) if correct and tol else '')
    if t == 'pick':
        ids = [str(x) for x in _as_list(v) if x not in (None, '')]
        nm = names or {}
        return (_tr(' 或 ') if correct else _tr('、')).join(_tr('{i}（{v}）', i=i, v=nm[i]) if nm.get(i) and nm[i] != i else i for i in ids)
    return str(v)


def answer_of(rule, lesson=None, course_id=None):
    if 'answer' in rule:
        return rule['answer']
    if 'seal' in rule:
        try:
            return unseal_value(rule['seal'], _salt(course_id or rule.get('_course'), (lesson or {}).get('id') or rule.get('_lesson'), rule.get('key')))
        except Exception:                               # noqa: BLE001
            return None
    return None


# ---------------- 判一条规则 ----------------
def qtype(rule):
    if rule.get('pick'):
        return 'pick'
    return rule.get('qtype') or 'single'


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _as_list(v):
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, str) and v.strip().startswith('['):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else [x]
        except ValueError:
            return [v]
    return [v]


def _same(a, b):
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ('true', '1', '对', '是', 't', 'yes', 'y', '√', '正确'):
        return True
    if s in ('false', '0', '错', '否', 'f', 'no', 'n', '×', '错误'):
        return False
    return None


def check_answer(rule, got, want):
    """作答题：返回是否正确（没作答 = False）。"""
    if got is None or got == '' or want is None:
        return False
    t = qtype(rule)
    if t == 'pick':
        ws = _as_list(want)
        gs = _as_list(got)
        return any(str(g) == str(w) for g in gs for w in ws) if len(gs) == 1 else False
    if t == 'multi':
        try:
            return sorted(int(float(x)) for x in _as_list(got)) == sorted(int(float(x)) for x in _as_list(want))
        except (TypeError, ValueError):
            return False
    if t == 'tf':
        g = _bool(got)
        return g is not None and g == _bool(want)
    if t == 'number':
        g, w = _num(got), _num(want)
        if g is None or w is None:
            return False
        return abs(g - w) <= float(rule.get('tol') or 0) + 1e-9
    return _same(got, want)


def compare(op, got, target):
    g = _num(got)
    t = _num(target)
    if g is None or t is None:
        if got is None:
            return False
        return OPS.get(op, OPS['>='])(got, target) if op in ('==', '!=') else False
    return bool(OPS.get(op, OPS['>='])(g, t))


def metric_name(rule):
    return rule.get('metric') or ('cost' if rule.get('kind') == 'budget' else '')


def evaluate(rule, metrics=None, answers=None, lesson=None, course_id=None, mes_ctx=None):
    """一条规则 → (ok, got)。metrics：静态 + 仿真指标；answers：{题号: 作答}；mes_ctx：MES 取数的上下文。"""
    kind = rule.get('kind', 'kpi')
    if kind == 'answer':
        got = (answers or {}).get(rule.get('key'))
        return check_answer(rule, got, answer_of(rule, lesson, course_id)), got
    if kind == 'mes':
        got = mes_value(rule, mes_ctx)
        return (got is not None and compare(rule.get('op', '>='), got, rule.get('value'))), got
    got = (metrics or {}).get(metric_name(rule))
    return (got is not None and not isinstance(got, bool) and isinstance(got, (int, float)) and compare(rule.get('op', '>='), got, rule.get('value'))), got


# ---------------- 校验（编辑器保存 / 发布前） ----------------
def validate_rule(r, kind_of_lesson='plant'):
    """返回问题列表（中文）；空 = 没问题。"""
    errs = []
    if not isinstance(r, dict):
        return [_tr('评分项不是对象')]
    key = r.get('key')
    if not key or not isinstance(key, str):
        errs.append(_tr('评分项缺少编号 key'))
    try:
        w = float(r.get('weight', 0) or 0)
        if w < 0:
            errs.append(_tr('{key}：分值不能是负数', key=key))
    except (TypeError, ValueError):
        errs.append(_tr('{key}：分值不是数字', key=key))
    kind = r.get('kind', 'kpi' if kind_of_lesson != 'cell' else 'plc')
    if kind_of_lesson == 'cell':
        if r.get('op', '>=') not in OPS:
            errs.append(_tr('{key}：比较符 {get} 不认识', key=key, get=r.get("op")))
        return errs
    if kind not in KINDS:
        errs.append(_tr('{key}：评分项类型 {kind} 不认识（可以是 {join}）', key=key, kind=kind, join=_tr('、').join(KINDS)))
        return errs
    if kind in ('kpi', 'limit') and not r.get('metric'):
        errs.append(_tr('{key}：缺少指标 metric', key=key))
    if kind in ('kpi', 'budget', 'limit', 'mes'):
        if r.get('op', '>=') not in OPS:
            errs.append(_tr('{key}：比较符 {get} 不认识', key=key, get=r.get("op")))
        if r.get('value') is None:
            errs.append(_tr('{key}：缺少目标值 value', key=key))
    if kind == 'mes' and not r.get('query'):
        errs.append(_tr('{key}：MES 检查缺少 query（查哪一项）', key=key))
    if kind == 'answer':
        t = qtype(r)
        a = r.get('answer', r.get('seal'))
        if a is None:
            errs.append(_tr('{key}：还没有设置正确答案', key=key))
        if t in ('single', 'multi'):
            ch = r.get('choices')
            if not isinstance(ch, list) or len(ch) < 2:
                errs.append(_tr('{key}：选择题至少要两个选项', key=key))
            elif 'answer' in r:
                idx = _as_list(r['answer']) if t == 'multi' else [r['answer']]
                for i in idx:
                    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(ch):
                        errs.append(_tr('{key}：正确答案 {i} 不是选项下标（0…{v}）', key=key, i=i, v=len(ch) - 1))
        elif t == 'number':
            if 'answer' in r and _num(r['answer']) is None:
                errs.append(_tr('{key}：填数题的答案不是数字', key=key))
            if _num(r.get('tol', 0)) is None or (_num(r.get('tol', 0)) or 0) < 0:
                errs.append(_tr('{key}：允许误差 tol 不对', key=key))
        elif t == 'tf':
            if 'answer' in r and _bool(r['answer']) is None:
                errs.append(_tr('{key}：判断题的答案应该是 对 / 错', key=key))
        elif t == 'pick':
            if 'answer' in r and not [x for x in _as_list(r['answer']) if x]:
                errs.append(_tr('{key}：点选题还没指定是哪台设备', key=key))
        if r.get('explain') is not None and not isinstance(r.get('explain'), str):
            errs.append(_tr('{key}：解析 explain 应该是一段文字', key=key))
        elif len(str(r.get('explain') or '')) > 1000:
            errs.append(_tr('{key}：解析太长（最多 1000 字）', key=key))
    for k, v in r.items():                                 # 规则是纯数据：不允许出现代码字段
        if k in ('code', 'expr', 'eval', 'script', 'py', 'js', 'lambda'):
            errs.append(_tr('{key}：评分规则只能是数据，不能含 {k}', key=key, k=k))
        if isinstance(v, str) and len(v) > 4000:
            errs.append(_tr('{key}：{k} 太长', key=key, k=k))
    return errs


def humanize(rule):
    """给老师和学生看的一句话："小时产出 ≥ 56"、"单选题：正确答案 B"（老师）。"""
    kind = rule.get('kind', 'kpi')
    if kind == 'answer':
        return QTYPE_CN.get(qtype(rule), '作答')
    op = OP_CN.get(rule.get('op', '>='), rule.get('op'))
    return f"{rule.get('label') or metric_name(rule) or rule.get('query') or rule.get('key')} {op} {rule.get('value')}"


# ---------------- 4.6.1 目标的说明文字（学生看到的"8 小时合格品 ≥ 100 件"） ----------------
# 指标目录：编号 → (名称, 单位, 方式)。方式 sum = 跑 time_h 小时累计的量（说明里带"N 小时"）；pct = 0~1 的比例（显示成百分数）。
METRICS = {
    'good': ('合格品', '件', 'sum'), 'good_per_h': ('小时产出', '件/小时', ''), 'scrap': ('报废', '件', 'sum'), 'scrap_rate': ('废品率', '%', 'pct'),
    'wip_avg': ('平均在制品', '件', ''), 'wip_max': ('最大在制品', '件', ''), 'lead_mean_min': ('平均生产周期', '分钟', ''),
    'lead_p90_min': ('生产周期 P90', '分钟', ''), 'oee_avg': ('平均 OEE', '%', 'pct'), 'energy_kwh': ('用电', 'kWh', 'sum'),
    'kwh_per_good': ('单件电耗', 'kWh/件', ''), 'escape': ('漏检', '件', 'sum'), 'orders_done': ('完成的订单', '个', 'sum'),
    'orders_late': ('延期的订单', '个', 'sum'), 'orders_open': ('没完成的订单', '个', 'sum'),
    'cost': ('投资合计', '万元', ''), 'count_all': ('设备总数', '台', ''), 'buffer_total': ('缓存总容量', '件', ''), 'operators': ('操作工', '人', ''),
    'vehicles': ('搬运车辆', '辆', ''), 'overlap': ('互相重叠的设备', '对', ''), 'outside': ('超出厂房的设备', '台', ''),
}
BLOCK_METRICS = {'util': ('利用率', '%', 'pct'), 'oee': ('OEE', '%', 'pct'), 'blocked': ('堵塞占比', '%', 'pct'), 'starved': ('缺料占比', '%', 'pct'),
                 'failed': ('故障占比', '%', 'pct'), 'cool_min': ('冷却时间', '分钟', ''), 'flow_per_h': ('输送能力', '件/小时', '')}
TYPE_CN = {'processor': '加工设备', 'buffer': '缓存', 'conveyor': '输送线', 'inspect': '检验站', 'assembly': '装配站', 'batch': '批处理设备',
           'transporter': '搬运车队', 'operators': '工人组', 'source': '来料口', 'sink': '成品库', 'storage': '仓库', 'plc': 'PLC', 'cell': '控制单元'}
# MES 检查能用的 query（教学 MES 的取数函数认这些，见 vfactory/mes/teach_rules.py）；MES 模块可以用 register_mes_queries 再加
MES_QUERIES = {
    'work_order.count': '工单数', 'work_order.done': '完工的工单数', 'report.count': '报工记录数', 'report.good': '报工的合格数',
    'oee.worst': 'OEE 最低的设备', 'oee.value': '设备 OEE', 'oee.count': '有 OEE 记录的设备数', 'ncr.count': '不合格品记录数',
    'ncr.traced': '追溯到来源的不合格品数', 'repair.for_worst_oee': '给 OEE 最低设备开的维修单', 'part.count': '零件数',
    'trace.part': '零件追溯', 'trace.ncr_match': '追溯结果和不合格品对得上', 'spc.stable': 'SPC 判断过程稳定', 'spc.value': 'SPC 统计值',
}


def register_mes_queries(d):
    """MES 模块登记它认识的 query：{query: 中文名}。"""
    MES_QUERIES.update({str(k): str(v) for k, v in (d or {}).items()})


def metric_info(metric):
    """指标 → (名称, 单位, 方式, 设备编号)。设备指标 oee.M1 → ('OEE', '%', 'pct', 'M1')；count.<类型> → ('加工设备数量', '台', '', '')。"""
    m = str(metric or '')
    if m in METRICS:
        return (*METRICS[m], '')
    base, _, blk = m.partition('.')
    if base in BLOCK_METRICS and blk:
        return (*BLOCK_METRICS[base], blk)
    if base == 'count' and blk:
        return (_tr('{get}数量', get=TYPE_CN.get(blk, blk)), _tr('个') if blk in ('buffer', 'source', 'sink') else _tr('台'), '', '')
    return (m or '?', '', '', '')


def fmt_num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f'{round(v, 3):g}'


def fmt_value(metric, v, unit_too=True):
    """指标值 + 单位："150 件"、"75%"（比例指标 0~1 显示成百分数）。"""
    if v is None:
        return '—'
    name, unit, mode, _blk = metric_info(metric)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if mode == 'pct' and abs(v) <= 1.5:
            return f'{fmt_num(v * 100)}%'
        return fmt_num(v) + (('' if unit == '%' else ' ') + unit if unit and unit_too else '')
    return str(v)


def _op(rule):
    return OP_CN.get(rule.get('op', '>='), rule.get('op') or '≥')


def subject(rule, lesson=None):
    """目标说的"是什么"：'8 小时合格品'、'M1 的 OEE'、'投资合计'、'MES：工单数'。"""
    kind = rule.get('kind', 'kpi')
    if kind == 'budget':
        return _tr('投资合计')
    if kind == 'mes':
        q = str(rule.get('query') or '')
        w = rule.get('where')
        cond = _tr('（') + _tr('，').join(f'{k} = {v}' for k, v in w.items()) + _tr('）') if isinstance(w, dict) and w else ''
        return _tr('MES：{get}{cond}', get=MES_QUERIES.get(q, q or _tr('（没选查哪一项）')), cond=cond)
    name, _unit, mode, blk = metric_info(metric_name(rule))
    if blk:
        return _tr('{blk} 的 {name}', blk=blk, name=name)
    if kind == 'kpi' and mode == 'sum':
        try:
            h = float((lesson or {}).get('time_h') or 8)
        except (TypeError, ValueError):
            h = 8.0
        return _tr('{fmt_num} 小时{name}', fmt_num=fmt_num(h), name=name)
    return name


def describe(rule, lesson=None, reveal=False):
    """一条评分规则的说明（学生和老师都看）："8 小时合格品 ≥ 100 件"、"M1 的 OEE ≥ 75%"、"投资合计 ≤ 220 万元"、"答案：…"、"MES：…"。
    reveal=True 时作答题写出正确答案（只给老师看）。"""
    if not isinstance(rule, dict):
        return ''
    kind = rule.get('kind', 'kpi')
    if kind == 'answer':
        t = qtype(rule)
        unit = str(rule.get('unit') or '')
        tol = _num(rule.get('tol'))
        if reveal:
            a = answer_of(rule, lesson)
            if t == 'single':
                ch = rule.get('choices') or []
                txt = _tr('（{v}）', v=ch[a]) if isinstance(a, int) and not isinstance(a, bool) and 0 <= a < len(ch) and str(ch[a]).strip() else ''
                return _tr('答案：{v}{txt}', v='ABCDEFGH'[a] if isinstance(a, int) and 0 <= a < 8 else a, txt=txt)
            if t == 'multi':
                xs = [x for x in _as_list(a) if isinstance(x, int)]
                return _tr('答案：') + (_tr('、').join('ABCDEFGH'[x] for x in sorted(xs) if 0 <= x < 8) or _tr('（没选）'))
            if t == 'tf':
                b = _bool(a)
                return _tr('答案：') + (_tr('对') if b else _tr('错') if b is False else _tr('（没设）'))
            if t == 'number':
                return _tr('答案：{v}{v2}{v3}', v=fmt_num(_num(a)) if _num(a) is not None else _tr('（没设）'), v2=f' ± {fmt_num(tol)}' if tol else '', v3=(' ' + unit) if unit else '')
            if t == 'pick':
                return _tr('答案：点中 ') + (_tr(' 或 ').join(str(x) for x in _as_list(a) if x) or _tr('（没选设备）'))
        if t == 'multi':
            return _tr('答案：多选题，选出全部正确的项')
        if t == 'tf':
            return _tr('答案：判断对错')
        if t == 'number':
            return _tr('答案：填一个数') + (_tr('（允许误差 ±{fmt_num}{v}）', fmt_num=fmt_num(tol), v=(' ' + unit) if unit else '') if tol else (_tr('（单位：{unit}）', unit=unit) if unit else ''))
        if t == 'pick':
            return _tr('答案：在图上点出那台设备')
        return _tr('答案：单选题，选出正确的一项')
    v = rule.get('value')
    if kind == 'mes':
        return f'{subject(rule, lesson)} {_op(rule)} {fmt_num(v) if isinstance(v, (int, float)) else v}'
    return f'{subject(rule, lesson)} {_op(rule)} {fmt_value(metric_name(rule), v)}'


def meaningful_label(s):
    """老师写的名称能不能当标题：空的、只有数字/标点、只有一两个字的都不算。"""
    import re
    s = str(s or '').strip()
    core = re.sub(r'[\W_]+', '', s)
    return bool(core) and not core.isdigit() and len(s) > 2


def title_of(rule, lesson=None):
    """学生看到的目标标题：老师的名称有意义就用它，不然用生成的说明。"""
    return str(rule.get('label')).strip() if meaningful_label(rule.get('label')) else describe(rule, lesson)


def normalize_weights(ws):
    """按比例凑成 100：四舍五入成整数，差的分数补在分值最大的那一项上。"""
    ws = [max(0.0, float(w or 0)) for w in ws]
    tot = sum(ws)
    if tot <= 0 or not ws:
        return [int(w) for w in ws]
    out = [int(math.floor(w * 100 / tot + 0.5)) for w in ws]          # 四舍五入（和编辑器里的 Math.round 一样，不用银行家舍入）
    i = max(range(len(ws)), key=lambda j: ws[j])
    out[i] += 100 - sum(out)
    return out


def pass_score(lesson):
    """本课及格分（lesson.unlock.min，默认 60，百分制）。"""
    u = (lesson or {}).get('unlock')
    try:
        return float(u.get('min', 60)) if isinstance(u, dict) else 60.0
    except (TypeError, ValueError):
        return 60.0
