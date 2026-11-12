"""老师做课程（4.6）：课程编辑器的接口、校验、预览、发布（冻结 + 签名课程包）。设计见 docs/course-authoring-4.6.md。

  GET    /api/teach/authoring/meta                 编辑器要的选项：课的模板、PLC 场景（含评分项）、工厂模板（含设备和参数）、指标、题型、封面
  GET    /api/teach/authoring                      我的课程草稿（管理员看全部）
  POST   /api/teach/authoring  {name?, copy?}      新建（copy = 从内置/已发布课程复制一份来改）→ 草稿
  GET    /api/teach/authoring/{cid}                草稿（引擎格式的课程 JSON）+ 问题清单 + 发布状态
  PUT    /api/teach/authoring/{cid}  {course}      保存草稿（不阻止保存，返回问题清单）
  DELETE /api/teach/authoring/{cid}                删除草稿（已发布的版本和已发出去的作业不动）
  POST   /api/teach/authoring/{cid}/assets  {name, data}   上传封面（dataURL / base64，png/jpg/webp）
  POST   /api/teach/authoring/{cid}/preview        按学生的样子预览：冻结一份 _preview-<编号>，发布到老师自己的隐藏"课程预览"班 → 课程地图
  GET    /api/teach/authoring/{cid}/preview        预览的课程地图（每课的作业号，老师试做的分数）
  POST   /api/teach/authoring/{cid}/publish        发布新版本：校验通过才行（先把没跑过的试运行跑完）；冻结到 data/teach/courses/<编号>.json，打好签名的课程包
  GET    /api/teach/authoring/{cid}/checks         4.6.1 出题检查：问题清单 + 每课的试运行结果（起始模型 / 参考做法）+ 后台试运行进度
  POST   /api/teach/authoring/{cid}/checks  {force?}   后台试运行还没跑过的课（force = 全部重跑）；结果按课的内容指纹缓存
  POST   /api/teach/authoring/{cid}/reference  {aid} | {lesson, model?, program?, answers?}   存参考做法（老师在预览里做好的那一份；只存在服务器，不进课程包）
  DELETE /api/teach/authoring/{cid}/reference/{lid}   删掉这一课的参考做法
  之后用课程库的"发布到班级"（/api/teach/courses/{cid}/publish，course_api.py）发给班级，和内置课程完全一样。
课程包（客户端下载）：
  GET    /api/teach/courses/pubkey                 学校服务器的课程签名公钥
  GET    /api/teach/courses/{cid}/package          签名的课程包 .vfcourse（这门课发布到了我的班，或者我是老师）
  GET    /api/teach/courses/{cid}/assets/{name}    课程封面等图片
"""
from ..i18n import _tr
import asyncio
import base64
import copy
import hashlib
import json
import os
import re
import secrets

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from .. import courses, store
from ..courses import coursepkg, rules as R, verify
from . import db, scenes

ID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,32}$')
PREVIEW = '_preview-'
PREVIEW_MARK = '__preview__'
TEMPLATES = [
    {'id': 'plc', 'kind': 'cell', 'name': 'PLC 实训', 'icon': 'Cpu',
     'desc': '选一个 PLC 实训场景：学生写梯形图/ST，提交后用场景的自动测试序列评分。可以只选用部分评分项，再加自己的测试步骤。'},
    {'id': 'line', 'kind': 'plant', 'name': '产线任务', 'icon': 'DataLine',
     'desc': '选一个工厂模板，先改好参数，规定哪些参数学生能改；用固定随机种子跑 N 小时，按指标目标评分（如 8 小时合格品 ≥ K、OEE ≥ x）。'},
    {'id': 'quiz', 'kind': 'quiz', 'name': '测验', 'icon': 'EditPen',
     'desc': '单选、多选、判断、填数（带允许误差）。不用进沙箱，离线也能做、本机马上出分。'},
    {'id': 'point', 'kind': 'point', 'name': '在图上点设备', 'icon': 'Aim',
     'desc': '打开一个工厂，让学生在流程图/平面图/三维里点出某台设备（如"瓶颈是哪台"）。'},
    {'id': 'mes', 'kind': 'mes', 'name': 'MES 操作任务', 'icon': 'Tickets',
     'desc': '在 MES 里完成一项操作（下达工单、报工…），提交时按 MES 的状态检查。需要教学 MES 模块。'},
]
COVERS = ['course-custom-mixed.png', 'course-custom-quiz.png', 'course-custom-line.png', 'course-custom-mes.png', 'course-plc.png', 'course-machining.png',
          'course-foundry.png', 'course-plc-logic.png', 'course-plc-sorting.png', 'course-plc-handling.png', 'course-plc-line.png']


def _ready():
    db.x('create table if not exists authored_courses(id text primary key, owner text, data text, created text, updated text, version integer default 0, '
         'published_at text, pub_hash text, shared integer default 0)')
    db.x('create table if not exists authored_refs(cid text, lesson text, data text, created text, by text, primary key(cid, lesson))')
    db.x('create table if not exists authoring_baselines(hash text primary key, data text, created text)')


def _row(cid):
    _ready()
    return db.q('select * from authored_courses where id=?', (cid,), one=True)


def _assets_dir(cid):
    from .. import paths
    return paths.data('teach', 'course_assets', os.path.basename(cid))


def _pkg_path(cid, version):
    from .. import paths
    return paths.data('teach', 'course_pkgs', f'{os.path.basename(cid)}-v{int(version)}{coursepkg.EXT}')


def can_edit(u, row):
    if not row:
        return False
    if row['owner'] == u['username']:
        return True
    # 管理员 / 单位管理员：本单位老师做的课（5.0 按单位隔离）
    return u['role'] in ('admin', 'orgadmin') and store.org_of(row['owner']) == (u.get('org') or 'default')


# ---------------- 校验 ----------------
def validate_course(c):
    """返回 [{level: error|warn, where, msg}]。error 时不能发布（草稿照样能存）。"""
    out = []

    def E(where, msg, level='error'):
        out.append({'level': level, 'where': where, 'msg': msg, 'code': 'invalid'})
    if not isinstance(c, dict):
        return [{'level': 'error', 'where': '', 'msg': _tr('课程不是对象')}]
    if not str(c.get('name') or '').strip():
        E(_tr('课程'), _tr('课程名称不能为空'))
    chs = c.get('chapters') or []
    if not chs:
        E(_tr('课程'), _tr('至少要有一章'))
    seen_ch, seen_l, order = set(), set(), []
    for ch in chs:
        cw = _tr('章「{v}」', v=ch.get('title') or ch.get('id'))
        if not ID_RE.match(str(ch.get('id') or '')):
            E(cw, _tr('章编号只能用字母、数字、_ 和 -'))
        if ch.get('id') in seen_ch:
            E(cw, _tr('章编号 {get} 重复', get=ch.get('id')))
        seen_ch.add(ch.get('id'))
        if not str(ch.get('title') or '').strip():
            E(cw, _tr('章标题不能为空'))
        if not ch.get('lessons'):
            E(cw, _tr('这一章还没有课'), 'warn')
        for l in ch.get('lessons') or []:
            lw = _tr('课「{v}」', v=l.get('title') or l.get('id'))
            lid = l.get('id')
            if not ID_RE.match(str(lid or '')):
                E(lw, _tr('课编号只能用字母、数字、_ 和 -'))
            if lid in seen_l:
                E(lw, _tr('课编号 {lid} 重复', lid=lid))
            seen_l.add(lid)
            if not str(l.get('title') or '').strip():
                E(lw, _tr('课标题不能为空'))
            out += [{**x, 'where': lw, 'lesson': lid} for x in validate_lesson(l)]
            un = l.get('unlock') or {}
            for pre in (un.get('after') or []) if isinstance(un, dict) else []:
                if pre not in order:
                    E(lw, _tr('先修课 {pre} 不在这一课前面（先修课要排在前面）', pre=pre))
            order.append(lid)
    if not seen_l:
        E(_tr('课程'), _tr('至少要有一课'))
    return out


def validate_lesson(l):
    out = []

    def E(msg, level='error'):
        out.append({'level': level, 'msg': msg, 'code': 'invalid'})
    kind = l.get('kind', 'plant')
    if kind not in courses.KINDS:
        E(_tr('课的类型 {kind} 不认识', kind=kind))
        return out
    rs = l.get('rules') or []
    if kind == 'cell':
        s = scenes.load_scene(l.get('scene'))
        if not s:
            E(_tr('PLC 场景 {v} 不存在', v=l.get('scene') or _tr('（没选）')))
            return out
        keys = {r.get('key') for r in scenes.rules_of(s) if isinstance(r, dict)}
        for k in l.get('rubric') or []:
            if k not in keys:
                E(_tr('评分项 {k} 不是这个场景的', k=k))
        steps = l.get('tests') or []
        if not isinstance(steps, list):
            E(_tr('追加的测试步骤应该是列表'))
            steps = []
        test_keys = {st.get('key') for st in steps if isinstance(st, dict) and st.get('key')}
        for st in steps:
            if not isinstance(st, dict) or not isinstance(st.get('t', 0), (int, float)):
                E(_tr('测试步骤要写清时间 t（秒）'))
                continue
            if not any(k in st for k in ('press', 'release', 'set', 'check', 'watch', 'fault', 'clear_faults', 'snapshot')):
                E(_tr('测试步骤 t={get} 没有动作（press / set / check …）', get=st.get('t')))
        for r in l.get('extra_rules') or []:
            out += [{'level': 'error', 'msg': m, 'code': 'invalid'} for m in R.validate_rule(r, 'cell')]
            if r.get('key') not in test_keys and r.get('key') not in keys:
                E(_tr('评分项 {get} 在测试步骤里没有对应的检查（key 要和某个 check 的 key 一样）', get=r.get('key')), 'warn')
        if l.get('rubric') is not None and not l.get('rubric') and not l.get('extra_rules'):
            E(_tr('至少要选一个评分项'))
        return out + lesson_checks(l)
    for r in rs:
        out += [{'level': 'error', 'msg': m, 'code': 'invalid'} for m in R.validate_rule(r, kind)]
    if not rs:
        E(_tr('还没有评分项'))
    if sum(float(r.get('weight', 0) or 0) for r in rs if isinstance(r, dict)) <= 0 and rs:
        E(_tr('评分项的分值加起来是 0'))
    keys = [r.get('key') for r in rs if isinstance(r, dict)]
    if len(keys) != len(set(keys)):
        E(_tr('评分项编号有重复'))
    if kind == 'quiz' and any(r.get('kind') != 'answer' for r in rs):
        E(_tr('测验课只能有作答题'))
    if kind == 'mes' and any(r.get('kind') not in ('mes', 'answer') for r in rs):
        E(_tr('MES 操作课的评分项只能是 MES 检查或作答题'))
    if kind == 'point' and not any(r.get('kind') == 'answer' and r.get('pick') for r in rs):
        E(_tr('点选课至少要有一道"在图上点设备"的题'))
    if kind in ('plant', 'point', 'diagnose'):
        try:
            m = courses.plant_model(l)
            ids = {b['id'] for b in m.get('blocks') or []}
            for e in l.get('params') or []:
                if e.get('block') not in ids:
                    E(_tr('改参数：设备 {get} 不在这个工厂里', get=e.get('block')))
            for e in (l.get('lock') or {}).get('editable') or []:
                if not isinstance(e, (list, tuple)) or len(e) < 2 or e[0] not in ids:
                    E(_tr('学生可改的参数 {e} 不对', e=e))
            for r in rs:
                if r.get('pick') and 'answer' in r:
                    for x in R._as_list(r['answer']):
                        if x not in ids:
                            E(_tr('点选题 {get} 的答案 {x} 不在这个工厂里', get=r.get('key'), x=x))
        except Exception as e:                           # noqa: BLE001
            E(_tr('工厂 {v} 打不开：{e}', v=l.get('plant') or _tr('（没选）'), e=e))
        if any(r.get('kind', 'kpi') == 'kpi' for r in rs):
            try:
                h = float(l.get('time_h') or 8)
                if not 0 < h <= 24 * 7:
                    E(_tr('仿真时长要在 0~168 小时之间'))
            except (TypeError, ValueError):
                E(_tr('仿真时长不是数字'))
    return out + lesson_checks(l)


# ---------------- 4.6.1 出题检查 ----------------
# 不用跑仿真的检查（lesson_checks，保存时马上出）+ 试运行（baseline_issues：后台按和学生交作业同一条评分路径跑起始模型和参考做法）。
# 每条问题 {level: error|warn|info, code, msg, rule?, fix?, check: True}：error（错误）不能发布，warn（提醒）、info（备注）不挡发布。
# check=True 的问题不挡"按学生预览"（老师要进预览才能存参考做法、试做）。
def _fmt(v):
    return R.fmt_num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def lesson_checks(l):
    out = []

    def A(level, code, msg, **kw):
        out.append({'level': level, 'code': code, 'msg': msg, 'check': True, **kw})
    kind = l.get('kind', 'plant')
    rs = [r for r in l.get('rules') or [] if isinstance(r, dict)]
    if not str(l.get('brief_md') or '').strip():
        if kind == 'cell':
            s = scenes.load_scene(l.get('scene'))
            if s and not str(scenes.task_md(s) or '').strip():
                A('error', 'brief', _tr('任务书是空的（场景也没有自带任务书）：学生不知道要做什么'))
        else:
            A('error', 'brief', _tr('任务书是空的：学生不知道要做什么。写清楚要达到什么、能改什么、怎么算完成（提示可以不写）'))
    if kind == 'cell':                                  # PLC 课的评分项来自场景（满分按勾选项换算），名称也是场景写好的
        return out
    ws = [float(r.get('weight', 0) or 0) if isinstance(r.get('weight', 0), (int, float)) else 0.0 for r in rs]
    tot = sum(ws)
    if rs and tot > 0 and abs(tot - 100) > 1e-6:
        new = R.normalize_weights(ws)
        A('warn', 'weights', _tr('评分项合计 {v} 分，不是 100：学生在每一项上看到的是原来的分值（比如"{v2} 分"），总分再按比例换算成百分制。可以按比例凑成 100（{join}）', v=_fmt(tot), v2=_fmt(ws[0]), join=_tr('、').join(_fmt(x) for x in new)), fix={'kind': 'weights', 'weights': {r.get('key'): n for r, n in zip(rs, new)}})
    for r in rs:
        lab = str(r.get('label') or '').strip()
        g = R.describe(r, l)
        if R.meaningful_label(lab):
            if r.get('kind') != 'answer' and lab != g and re.search(r'[≥≤<>=≠]', lab) and R.subject(r, l) in lab:
                A('warn', 'label', _tr('目标的名称「{lab}」和现在的目标"{g}"对不上（改过目标值？）', lab=lab, g=g), rule=r.get('key'), fix={'kind': 'label', 'rule': r.get('key'), 'value': g})
            continue
        if r.get('kind') == 'answer':
            A('warn', 'label', _tr('题目「{v}」看不出问的是什么：写清题目（学生看到的标题现在是"{g}"）', v=lab or _tr('（空）'), g=g), rule=r.get('key'))
        else:
            A('warn', 'label', (_tr('目标的名称「{lab}」没有意义', lab=lab) if lab else _tr('目标没有名称')) + _tr('，学生看到的标题是生成的说明"{g}"。可以直接用它当名称', g=g),
              rule=r.get('key'), fix={'kind': 'label', 'rule': r.get('key'), 'value': g})
    for r in rs:
        if r.get('kind', 'kpi') in ('kpi', 'limit') and isinstance(r.get('value'), (int, float)) and not isinstance(r.get('value'), bool):
            name, _u, mode, _b = R.metric_info(r.get('metric'))
            if mode == 'pct' and abs(float(r['value'])) > 1.5:
                A('warn', 'pct', _tr('「{title_of}」：{name}是 0~1 之间的比例，目标 {v} 永远达不到（75% 要写 0.75）', title_of=R.title_of(r, l), name=name, v=_fmt(r["value"])), rule=r.get('key'))
    lock = l.get('lock') or {}
    if kind in ('plant', 'diagnose') and any(r.get('kind', 'kpi') == 'kpi' for r in rs) \
            and not any(r.get('kind') in ('budget', 'limit') for r in rs) and not any(lock.get(k) for k in ('editable', 'structure', 'blocks', 'params')):
        A('warn', 'unconstrained', _tr('学生可以随意加设备或改参数，目标可能被轻松达成：加一条"投资预算"或"数量 / 布局"限制，或者在"工厂"页规定学生能改哪些参数、不能增删设备'))
    for r in rs:
        if r.get('kind') != 'answer':
            continue
        t = R.qtype(r)
        tt = R.title_of(r, l)
        a = r.get('answer')
        ch = r.get('choices') if isinstance(r.get('choices'), list) else []
        if t == 'single' and isinstance(a, int) and not isinstance(a, bool) and 0 <= a < len(ch) and not str(ch[a]).strip():
            A('error', 'answer', _tr('「{tt}」：标成正确答案的选项 {v} 是空的', tt=tt, v="ABCDEFGH"[a] if a < 8 else a), rule=r.get('key'))
        elif t in ('single', 'multi') and ch and any(not str(x).strip() for x in ch):
            A('warn', 'choices', _tr('「{tt}」：有空的选项', tt=tt), rule=r.get('key'))
        if t == 'multi' and 'answer' in r and not R._as_list(a):
            A('error', 'answer', _tr('「{tt}」：多选题还没勾正确答案', tt=tt), rule=r.get('key'))
        if t == 'number' and R._num(a) is not None and not (R._num(r.get('tol')) or 0) > 0:
            A('warn', 'tol', _tr('「{tt}」：填数题没设允许误差，学生必须填得一模一样才算对（比如答案 {v}，填 {v2} 也算错）', tt=tt, v=_fmt(R._num(a)), v2=_fmt(R._num(a) + 0.1)), rule=r.get('key'))
    for r in rs:
        if r.get('kind') == 'mes' and r.get('query') and str(r['query']) not in R.MES_QUERIES:
            A('error', 'mes_query', _tr('MES 检查「{title_of}」的 query「{query}」不认识：教学 MES 取不到这个数，这一项永远判"没有连上 MES"。能用的有 {join} …', title_of=R.title_of(r, l), query=r["query"], join=_tr('、').join(list(R.MES_QUERIES)[:8])), rule=r.get('key'))
    return out


def needs_baseline(l):
    return l.get('kind', 'plant') in verify.BASELINE_KINDS and (l.get('kind') == 'cell' or bool(l.get('rules')))


def runnable(l):
    """能试运行吗（工厂打得开、场景在）。不能的时候已经有对应的错误了。"""
    try:
        if l.get('kind') == 'cell':
            return bool(scenes.load_scene(l.get('scene')))
        courses.plant_model(l)
        return True
    except Exception:                                    # noqa: BLE001
        return False


def baseline_hash(l, ref=None):
    """试运行结果的缓存键：和评分有关的内容（规则不含名称；工厂模板 / PLC 场景展开后的内容；参考做法；引擎版本）。改任务书、名称不用重跑。"""
    keep = {k: v for k, v in l.items() if k not in ('title', 'brief_md', 'hints', 'unlock', '_k', 'id', '_course')}
    keep['rules'] = [{k: v for k, v in r.items() if k not in ('label', 'explain')} if isinstance(r, dict) else r for r in l.get('rules') or []]
    try:
        if l.get('kind') == 'cell':
            keep['_scene'] = scenes.load_scene(l.get('scene'))
        else:
            keep['_model'] = courses.plant_model(l)
    except Exception:                                    # noqa: BLE001
        pass
    keep['_ref'] = ref or None
    keep['_engine'] = [R.RULES_VERSION, 1]
    return hashlib.sha256(json.dumps(keep, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def _target(rule):
    v = rule.get('value')
    return R.fmt_num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def _phrase(rule, l, d):
    """"合格品 8 小时约 150 件，目标 ≥ 100"。"""
    name, _u, mode, blk = R.metric_info(R.metric_name(rule))
    val = d.get('value_text') or _fmt(d.get('value'))
    if rule.get('kind', 'kpi') == 'kpi' and mode == 'sum' and not blk:
        try:
            h = R.fmt_num(float(l.get('time_h') or 8))
        except (TypeError, ValueError):
            h = '8'
        head = _tr('{name} {h} 小时约 {val}', name=name, h=h, val=val)
    else:
        head = _tr('{subject}约 {val}', subject=R.subject(rule, l), val=val)
    return _tr('{head}，目标 {get} {v}', head=head, get=R.OP_CN.get(rule.get("op", ">="), rule.get("op")), v=_target(rule))


def baseline_issues(l, res, running=False):
    """试运行结果 → 出题检查的问题。res = verify.baseline 的结果（None = 还没跑）。"""
    out = []

    def A(level, code, msg, **kw):
        out.append({'level': level, 'code': code, 'msg': msg, 'check': True, 'stage': 'run', **kw})
    kind = l.get('kind', 'plant')
    if res is None:
        A('info', 'baseline_pending', _tr('正在试运行起始模型…') if running else _tr('还没试运行起始模型（保存后自动在后台跑，发布前一定会跑完）'))
        return out
    if res.get('error'):
        A('warn', 'baseline_error', _tr('试运行出错：{error}', error=res["error"]))
        return out
    pas = R.pass_score(l)
    rules = {r.get('key'): r for r in l.get('rules') or [] if isinstance(r, dict)}
    st = res.get('start') or {}
    if st.get('error'):
        A('warn', 'baseline_error', _tr('起始模型试运行出错：{error}', error=st["error"]))
    elif st:
        if kind == 'cell':
            passing = [d for d in st.get('details') or [] if d.get('ok')]
            if st.get('pct', 0) >= pas:
                A('warn', 'baseline', _tr('学生不写程序就能得 {v} 分（及格 {v2}）：', v=_fmt(st["pct"]), v2=_fmt(pas))
                  + _tr('、').join(_tr('「{get}」', get=d.get("label")) for d in passing) + _tr(' 不写程序就过了'), baseline=st['pct'])
        else:
            passing = [d for d in st.get('details') or [] if d.get('ok') and (rules.get(d.get('key')) or {}).get('kind', 'kpi') == 'kpi']
            if st.get('pct', 0) >= pas or passing:
                parts = [_phrase(rules[d['key']], l, d) for d in passing if d.get('key') in rules]
                A('warn', 'baseline', _tr('学生什么都不改就能得 {v} 分（及格 {v2}）', v=_fmt(st["pct"]), v2=_fmt(pas)) + (_tr('：') + _tr('；').join(parts) if parts else '')
                  + _tr('。把目标定高一点、加限制，或者先把工厂的参数改差一点'), baseline=st['pct'], rules=[d['key'] for d in passing])
    ref, src = res.get('ref'), res.get('ref_source')
    if ref:
        bad = [d for d in ref.get('details') or [] if not d.get('ok')]
        miss = _tr('；').join(_phrase(rules[d['key']], l, d) if d.get('key') in rules and rules[d['key']].get('kind', 'kpi') in ('kpi', 'limit', 'budget')
                        else _tr('「{get}」', get=d.get("label")) for d in bad[:4])
        who = {'teacher': _tr('参考做法'), 'scene': _tr('场景自带的参考程序'), 'lesson': _tr('课里自带的参考做法')}.get(src, _tr('参考做法'))
        if ref.get('error'):
            A('error' if src == 'teacher' else 'warn', 'reference', _tr('{who}试运行出错：{error}', who=who, error=ref["error"]))
        elif ref.get('pct', 0) < pas:
            A('error' if src == 'teacher' else 'warn', 'reference', _tr('{who}也拿不到及格分，目标可能做不到：{who}得 {v} 分（及格 {v2}）', who=who, v=_fmt(ref["pct"]), v2=_fmt(pas))
              + (_tr('，没达到的：{miss}', miss=miss) if miss else ''), ref_score=ref['pct'])
    else:
        A('info', 'no_reference', _tr('没有参考做法：无法确认目标做得到。在"按学生预览"里把这一课做一遍，点"存为参考做法"'))
    return out


def model_diff(a, b):
    """参考做法相对起始模型改了什么（给老师看的几行字）。"""
    A = {x['id']: x for x in (a or {}).get('blocks') or [] if isinstance(x, dict) and 'id' in x}
    B = {x['id']: x for x in (b or {}).get('blocks') or [] if isinstance(x, dict) and 'id' in x}
    out = [_tr('加了 {k}（{get}）', k=k, get=R.TYPE_CN.get(B[k].get("type"), B[k].get("type"))) for k in B if k not in A]
    out += [_tr('删了 {k}', k=k) for k in A if k not in B]
    for k in A:
        if k in B:
            pa, pb = A[k].get('params') or {}, B[k].get('params') or {}
            for p in sorted(set(pa) | set(pb)):
                if json.dumps(pa.get(p), sort_keys=True, default=str) != json.dumps(pb.get(p), sort_keys=True, default=str):
                    out.append(_tr('{k}.{p}：{get} → {get2}', k=k, p=p, get=pa.get(p, "—"), get2=pb.get(p, "—")))
    lk = lambda m: sorted((x.get('from'), x.get('to')) for x in (m or {}).get('links') or [])     # noqa: E731
    if lk(a) != lk(b):
        out.append(_tr('改了连线'))
    return out[:12]


def freeze(c, cid, owner, version):
    """草稿 → 服务器评分用的冻结课程：产线课把工厂模型（模板 + 改好的参数）内嵌进去，以后模板改了也不影响这门课。"""
    f = copy.deepcopy(c)
    f['id'] = cid
    f['owner'] = owner
    f['version'] = version
    f['origin'] = 'authored'
    for ch in f.get('chapters') or []:
        for l in ch.get('lessons') or []:
            if l.get('kind', 'plant') in ('plant', 'point', 'diagnose') and not isinstance(l.get('model'), dict):
                m = courses.plant_model(l)
                m.setdefault('plant', {}).pop('modbus_port', None)
                l['model'] = m
                l.pop('params', None)
            l.pop('_course', None)
    return f


def _write_frozen(cid, data):
    d = courses.authored_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{cid}.json')
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def assets_of(cid):
    d = _assets_dir(cid)
    out = {}
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.lower().endswith(coursepkg.ASSET_EXT):
                with open(os.path.join(d, n), 'rb') as fh:
                    out[n] = fh.read()
    return out


def build_package(cid, server=''):
    """当前发布版本的课程包（有缓存）。"""
    c = courses.get_course(cid)
    if not c or c.get('origin') != 'authored':
        raise HTTPException(404, _tr('只有老师发布的课程有课程包（内置课程客户端自带）'))
    p = _pkg_path(cid, c.get('version') or 1)
    if os.path.exists(p):
        with open(p, 'rb') as fh:
            return fh.read()
    data = coursepkg.build(c, assets_of(c['id'].replace(PREVIEW, '')), server)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as fh:
        fh.write(data)
    return data


def new_course(name, owner):
    return {'name': name or _tr('新课程'), 'desc': '', 'level': 1, 'cover': '/brand/course-custom-mixed.png', 'tags': [],
            'chapters': [{'id': 'c1', 'title': _tr('第一章'), 'lessons': []}]}


# ---------------- 试运行的缓存、参考做法、后台任务 ----------------
_jobs: dict = {}                                     # 课程编号 → {running, done, total, lessons, started, finished}
_tasks: dict = {}                                    # 课程编号 → asyncio.Task


def refs_of(cid):
    _ready()
    return {r['lesson']: {**(db.jl(r['data'], {}) or {}), 'created': r['created'], 'by': r['by']}
            for r in db.q('select * from authored_refs where cid=?', (cid,))}


def _ref_input(ref):
    """参考做法里参与评分的部分（进试运行、进缓存键）。"""
    return {k: ref[k] for k in ('model', 'program', 'answers') if ref and ref.get(k) is not None} or None


def _cached(h):
    r = db.q('select data from authoring_baselines where hash=?', (h,), one=True)
    return db.jl(r['data'], None) if r else None


def _plan(cid, c, refs=None):
    """每课：要不要试运行、缓存键、缓存的结果。"""
    refs = refs_of(cid) if refs is None else refs
    out = []
    for _ch, l in courses.lessons(c):
        if not needs_baseline(l) or not runnable(l):
            continue
        ri = _ref_input(refs.get(l.get('id')))
        h = baseline_hash(l, ri)
        out.append({'lesson': l, 'ref': ri, 'hash': h, 'result': _cached(h)})
    return out


def checks_of(cid, c):
    """出题检查的全部结果：问题清单（不用跑的 + 试运行得出的）、每课的试运行结果、还没跑的课、后台进度、参考做法、每个目标的说明。"""
    _ready()
    iss = validate_course(c)
    refs = refs_of(cid)
    job = {k: v for k, v in (_jobs.get(cid) or {}).items()}
    running = bool(job.get('running'))
    plan = {p['lesson'].get('id'): p for p in _plan(cid, c, refs)}
    base, pending, goals = {}, [], {}
    for _ch, l in courses.lessons(c):
        lid = l.get('id')
        goals[lid] = {r.get('key'): {'goal': R.describe(r, l), 'title': R.title_of(r, l), 'answer': R.describe(r, l, reveal=True) if r.get('kind') == 'answer' else None}
                      for r in l.get('rules') or [] if isinstance(r, dict) and l.get('kind') != 'cell'}
        p = plan.get(lid)
        if not p:
            continue
        res = p['result']
        if res is None:
            pending.append(lid)
        else:
            base[lid] = {**res, 'pass': R.pass_score(l)}
            rl = {r.get('key'): r for r in l.get('rules') or [] if isinstance(r, dict)}
            for part in ('start', 'ref'):                   # 缓存里的名称可能是旧的（改名称不重跑）：按现在的课重写标题
                for d in (base[lid].get(part) or {}).get('details') or []:
                    if d.get('key') in rl:
                        d['label'] = R.title_of(rl[d['key']], l)
        lw = _tr('课「{v}」', v=l.get('title') or lid)
        iss += [{**x, 'where': lw, 'lesson': lid} for x in baseline_issues(l, res, running and lid in (job.get('lessons') or []))]
    rv = {lid: {k: v for k, v in x.items() if k in ('created', 'by', 'summary', 'kind', 'aid')} for lid, x in refs.items()}
    return {'issues': iss, 'baseline': base, 'pending': pending, 'job': job, 'refs': rv, 'goals': goals}


async def run_baselines(cid, c, force=False):
    """后台试运行（和学生交作业同一个评分进程池、同一条评分路径）；同一门课同时只跑一个。返回 asyncio.Task（没有要跑的返回 None）。"""
    from .api import score_pool
    t = _tasks.get(cid)
    if t and not t.done():
        return t
    items = _plan(cid, c)
    if force:
        for p in items:
            db.x('delete from authoring_baselines where hash=?', (p['hash'],))
    else:
        items = [p for p in items if p['result'] is None]
    if not items:
        return None
    job = {'running': True, 'done': 0, 'total': len(items), 'lessons': [p['lesson'].get('id') for p in items],
           'titles': [p['lesson'].get('title') for p in items], 'started': store.now(), 'finished': None}
    _jobs[cid] = job

    async def one(p):
        loop = asyncio.get_running_loop()
        try:
            res = await asyncio.wait_for(loop.run_in_executor(score_pool(), verify.baseline, copy.deepcopy(p['lesson']), p['ref'], cid), timeout=300)
        except Exception as e:                       # noqa: BLE001
            res = {'kind': p['lesson'].get('kind'), 'error': _tr('试运行没跑完：{v} {e}', v=type(e).__name__, e=e)}
        db.x('insert or replace into authoring_baselines(hash, data, created) values(?,?,?)', (p['hash'], json.dumps(res, ensure_ascii=False, default=str), store.now()))
        job['done'] += 1

    async def all_():
        try:
            await asyncio.gather(*[one(p) for p in items])
        finally:
            job['running'] = False
            job['finished'] = store.now()
    t = asyncio.create_task(all_())
    _tasks[cid] = t
    return t


async def ensure_baselines(cid, c):
    """发布前：正在跑的等它跑完，没跑过的现在跑完。"""
    for _ in range(3):
        t = _tasks.get(cid)
        if t and not t.done():
            await t
        t = await run_baselines(cid, c)
        if t is None:
            return
        await t


def register(app, mgr):
    from .api import need_teacher, me
    from .course_api import publish_course
    _ready()

    def need_own(request, cid):
        u = need_teacher(request)
        r = _row(cid)
        if not r:
            raise HTTPException(404, _tr('没有这门课程草稿'))
        if not can_edit(u, r):
            raise HTTPException(403, _tr('这不是你做的课程'))
        return u, r

    def view(r):
        c = db.jl(r['data'], {}) or {}
        ck = checks_of(r['id'], c)
        iss = ck['issues']
        return {'id': r['id'], 'owner': r['owner'], 'course': c, 'issues': iss, 'errors': sum(1 for i in iss if i['level'] == 'error'),
                'blocking_preview': sum(1 for i in iss if i['level'] == 'error' and not i.get('check')),
                **{k: ck[k] for k in ('baseline', 'pending', 'job', 'refs', 'goals')},
                'version': r['version'] or 0, 'published_at': r['published_at'], 'content_sha256': r['pub_hash'], 'updated': r['updated'],
                'shared': bool(r['shared']), 'dirty': bool(r['published_at']) and (r['updated'] or '') > (r['published_at'] or ''),
                'classes': [{'class_id': p['class_id'], 'class_name': p['class_name']} for p in
                            db.q('select p.class_id, c.name class_name from course_pubs p join classes c on c.id=p.class_id where p.course=? and '
                                 "coalesce(c.descr,'')!=?", (r['id'], PREVIEW_MARK))]}

    @app.get('/api/teach/authoring/meta')
    async def meta(request: Request):
        need_teacher(request)
        from ..courses.scoring import METRIC_CN
        sc = []
        for s in scenes.list_scenes():
            full = scenes.load_scene(s['id'])
            sc.append({'id': s['id'], 'name': s.get('name'), 'level': s.get('level'), 'desc': s.get('desc'),
                       'rules': [{k: r.get(k) for k in ('key', 'label', 'op', 'value', 'weight')} for r in scenes.rules_of(full) if isinstance(r, dict)],
                       'io': [{k: e.get(k) for k in ('name', 'dir', 'type', 'addr', 'desc')} for e in scenes.io_of(full)],
                       'duration': ((full or {}).get('test') or {}).get('duration')})
        return {'templates': TEMPLATES, 'scenes': sc, 'plants': courses.plant_choices(), 'metrics': METRIC_CN,
                'block_metrics': {'util': _tr('利用率'), 'oee': 'OEE', 'blocked': _tr('堵塞占比'), 'starved': _tr('缺料占比'), 'failed': _tr('故障占比')},
                'ops': R.OP_CN, 'qtypes': R.QTYPE_CN, 'covers': ['/brand/' + x for x in COVERS], 'engine': R.RULES_VERSION,
                'signature': coursepkg.public_info()['alg']}

    @app.get('/api/teach/authoring')
    async def mine(request: Request):
        u = need_teacher(request)
        rows = [r for r in db.q('select * from authored_courses order by updated desc') if store.org_of(r['owner']) == (u.get('org') or 'default')]             if u['role'] in ('admin', 'orgadmin') else \
            db.q('select * from authored_courses where owner=? order by updated desc', (u['username'],))
        out = []
        for r in rows:
            c = db.jl(r['data'], {}) or {}
            ls = courses.lessons(c)
            out.append({'id': r['id'], 'name': c.get('name'), 'desc': c.get('desc', ''), 'cover': c.get('cover'), 'lessons': len(ls),
                        'kinds': sorted({l.get('kind', 'plant') for _ch, l in ls}), 'version': r['version'] or 0, 'published_at': r['published_at'],
                        'updated': r['updated'], 'owner': r['owner'], 'dirty': bool(r['published_at']) and (r['updated'] or '') > (r['published_at'] or '')})
        from ..tenancy import coursesync
        if coursesync.client_saas():                    # 5.0：老师在别的电脑上做、已经传到服务器的课，也列出来（可以下载到本机继续改）
            have = {x['id'] for x in out}
            for x in await coursesync.remote_list():
                if isinstance(x, dict) and x.get('id') not in have and x.get('owner') == u['username']:
                    out.append({**x, 'remote': True})
        return out

    @app.post('/api/teach/authoring')
    async def create(request: Request, body: dict = Body(default={})):
        u = need_teacher(request)
        _ready()
        from ..tenancy import coursesync
        csaas = coursesync.client_saas()
        n = 6 if csaas else 3                          # 5.0 客户端里做的课要传到服务器：编号长一点，不和别的单位撞
        cid = 'tc-' + secrets.token_hex(n)
        while _row(cid) or courses.get_course(cid):
            cid = 'tc-' + secrets.token_hex(n)
        if body.get('copy'):
            src = courses.get_course(body['copy'])
            if not src and csaas:                      # 服务器上的课（别的老师共享的）：下课程包来复制
                src = await coursesync.remote_package_course(body['copy'])
            if not src:
                raise HTTPException(404, _tr('没有这门课程'))
            c = copy.deepcopy(src)
            for k in ('id', 'owner', 'version', 'origin', 'package', 'order'):
                c.pop(k, None)
            c['name'] = (body.get('name') or _tr('{name}（副本）', name=src['name']))[:60]
            c.setdefault('cover', '/brand/course-custom-mixed.png')
        else:
            c = new_course((body.get('name') or '').strip()[:60], u['username'])
        now = store.now()
        db.x('insert into authored_courses(id, owner, data, created, updated, version) values(?,?,?,?,?,0)',
             (cid, u['username'], json.dumps(c, ensure_ascii=False), now, now))
        return view(_row(cid))

    @app.get('/api/teach/authoring/{cid}')
    async def get_one(cid: str, request: Request):
        _u, r = need_own(request, cid)
        return view(r)

    @app.put('/api/teach/authoring/{cid}')
    async def save(cid: str, request: Request, body: dict = Body(...)):
        _u, r = need_own(request, cid)
        c = body.get('course')
        if not isinstance(c, dict):
            raise HTTPException(400, _tr('缺少课程内容'))
        c = {k: v for k, v in c.items() if k not in ('id', 'owner', 'version', 'origin', 'package')}
        raw = json.dumps(c, ensure_ascii=False)
        if len(raw) > 2_000_000:
            raise HTTPException(413, _tr('课程太大了（超过 2 MB）'))
        db.x('update authored_courses set data=?, updated=?, shared=coalesce(?, shared) where id=?',
             (raw, store.now(), (1 if body['shared'] else 0) if 'shared' in body else None, cid))
        await run_baselines(cid, c)                    # 4.6.1 出题检查：改过的课在后台试运行（结果按内容缓存，没改的不重跑）
        return view(_row(cid))

    @app.delete('/api/teach/authoring/{cid}')
    async def remove(cid: str, request: Request):
        need_own(request, cid)
        db.x('delete from authored_courses where id=?', (cid,))
        return {'ok': True}

    @app.post('/api/teach/authoring/{cid}/assets')
    async def upload(cid: str, request: Request, body: dict = Body(...)):
        need_own(request, cid)
        name = os.path.basename(str(body.get('name') or 'cover.png')).lower()
        ext = os.path.splitext(name)[1]
        if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise HTTPException(400, _tr('封面只能是 png / jpg / webp 图片'))
        d = str(body.get('data') or '')
        if d.startswith('data:'):
            d = d.split(',', 1)[-1]
        try:
            b = base64.b64decode(d)
        except ValueError:
            raise HTTPException(400, _tr('图片数据不对'))
        if len(b) > 3 * 1024 * 1024:
            raise HTTPException(413, _tr('图片不能超过 3 MB'))
        os.makedirs(_assets_dir(cid), exist_ok=True)
        fn = f'cover-{secrets.token_hex(3)}{ext}'
        with open(os.path.join(_assets_dir(cid), fn), 'wb') as fh:
            fh.write(b)
        return {'ok': True, 'name': fn, 'cover': f'assets/{fn}', 'url': f'/api/teach/courses/{cid}/assets/{fn}'}

    def _preview_class(u):
        c = db.q('select id from classes where teacher=? and descr=?', (u['username'], PREVIEW_MARK), one=True)
        return c['id'] if c else db.x('insert into classes(name, teacher, descr, created) values(?,?,?,?)',
                                      (_tr('课程预览'), u['username'], PREVIEW_MARK, store.now()))

    def _preview_map(u, cid):
        from .api import lesson_state
        pc = _preview_class(u)
        pid = PREVIEW + cid
        c = courses.get_course(pid)
        if not c:
            raise HTTPException(404, _tr('还没有生成预览'))
        asg = {r['lesson']: dict(r) for r in db.q('select * from assignments where class_id=? and course=? order by seq', (pc, pid))}
        bc = {}
        chs = []
        for ch in c.get('chapters') or []:
            ls = []
            for l in ch.get('lessons') or []:
                a = asg.get(l['id'])
                if not a:
                    continue
                st = lesson_state(a, u['username'], bc)
                ls.append({'aid': a['id'], 'id': l['id'], 'title': l['title'], 'kind': l.get('kind', 'plant'), 'state': st['state'], 'locked': False,
                           'best': st['best'], 'submissions': 0, 'due': None})
            if ls:
                chs.append({'id': ch['id'], 'title': ch['title'], 'lessons': ls})
        flat = [l for ch in chs for l in ch['lessons']]
        return {'course': pid, 'source': cid, 'name': c['name'], 'desc': c.get('desc', ''), 'cover': c.get('cover'), 'class_id': pc, 'class_name': _tr('课程预览'),
                'preview': True, 'chapters': chs, 'done': sum(1 for l in flat if l['state'] == 'done'), 'total': len(flat),
                'next': flat[0]['aid'] if flat else None, 'kinds': sorted({l['kind'] for l in flat})}

    @app.post('/api/teach/authoring/{cid}/preview')
    async def preview(cid: str, request: Request):
        u, r = need_own(request, cid)
        c = db.jl(r['data'], {}) or {}
        iss = [i for i in validate_course(c) if i['level'] == 'error' and not i.get('check')]      # 出题检查的问题不挡预览（要在预览里存参考做法）
        if iss:
            raise HTTPException(400, _tr('先改好这些问题再预览：') + _tr('；').join(f"{i['where']} {i['msg']}" for i in iss[:4]))
        pid = PREVIEW + cid
        _write_frozen(pid, freeze(c, pid, r['owner'], 0))
        pc = _preview_class(u)
        # 预览班：每次重新生成（课改了，作业跟着变）
        drop = app.state.teach_drop
        want = {l['id'] for _ch, l in courses.lessons(c)}
        for x in db.q('select id, lesson from assignments where class_id=? and course=?', (pc, pid)):
            if x['lesson'] not in want:
                await drop(x['id'])
        publish_course(pc, pid, u['username'], {'open_all': True})
        from ..tenancy import coursesync
        if coursesync.client_saas():                 # 5.0 连着 SaaS 的客户端里预览：作业编号挪到 10 亿以上，代理按编号分流到本机，不和服务器的作业撞号
            B = coursesync.PREVIEW_AID_BASE
            for x in db.q('select id from assignments where class_id=? and id<?', (pc, B)):
                for t in ('submissions', 'answers', 'sandboxes', 'fault_log'):
                    db.x(f'update {t} set assignment_id=? where assignment_id=?', (x['id'] + B, x['id']))
                db.x('update assignments set id=? where id=?', (x['id'] + B, x['id']))
        return _preview_map(u, cid)

    @app.get('/api/teach/authoring/{cid}/preview')
    async def preview_get(cid: str, request: Request):
        u, _r = need_own(request, cid)
        return _preview_map(u, cid)

    @app.post('/api/teach/authoring/{cid}/publish')
    async def publish(cid: str, request: Request):
        _u, r = need_own(request, cid)
        c = db.jl(r['data'], {}) or {}
        await ensure_baselines(cid, c)                # 4.6.1 试运行（起始模型、参考做法）没跑完的先跑完：参考做法拿不到及格分是错误
        iss = [i for i in checks_of(cid, c)['issues'] if i['level'] == 'error']
        if iss:
            raise HTTPException(400, _tr('课程还有问题，不能发布：') + _tr('；').join(f"{i['where']} {i['msg']}" for i in iss[:5]))
        ver = int(r['version'] or 0) + 1
        frozen = freeze(c, cid, r['owner'], ver)
        _write_frozen(cid, frozen)
        hist = os.path.join(courses.authored_dir(), 'versions')
        os.makedirs(hist, exist_ok=True)
        with open(os.path.join(hist, f'{cid}.v{ver}.json'), 'w', encoding='utf-8') as fh:
            json.dump(frozen, fh, ensure_ascii=False, indent=1)
        data = build_package(cid, str(request.base_url).rstrip('/'))
        man = coursepkg.read(data)['manifest']
        now = store.now()
        db.x('update authored_courses set version=?, published_at=?, pub_hash=?, updated=? where id=?', (ver, now, man['content_sha256'], now, cid))
        up = None
        from ..tenancy import coursesync
        if coursesync.client_saas():                  # 5.0 SaaS：本机试运行、冻结、签名好了 → 传到服务器（服务器不跑工厂，只验包）
            up = await coursesync.upload(data, c)
            if up.get('version') and int(up['version']) != ver:       # 版本号以服务器为准
                db.x('update authored_courses set version=? where id=?', (int(up['version']), cid))
        return {**view(_row(cid)), 'package': {'bytes': len(data), 'content_sha256': man['content_sha256'], 'signature': coursepkg.public_info()['alg']},
                'uploaded': up}

    # ---------------- 5.0 SaaS：老师客户端传上来的课程（服务器）/ 从服务器取回草稿（客户端） ----------------
    @app.post('/api/teach/authoring/upload')
    async def upload_course(request: Request, body: dict = Body(...)):
        """老师客户端发布的课程包（本机试运行过、本机密钥签名）：服务器只验包（结构、哈希、签名、静态校验），不跑工厂；存成本单位的课程。"""
        u = need_teacher(request)
        from ..tenancy import coursesync
        return coursesync.ingest(u, body)

    @app.get('/api/teach/authoring/{cid}/draft')
    async def draft_get(cid: str, request: Request):
        """可编辑的草稿（课程的主人、本单位管理员）：老师换了电脑，在客户端里"下载到本机继续改"。"""
        u = need_teacher(request)
        r = _row(cid)
        if not r or not can_edit(u, r):
            raise HTTPException(404, _tr('没有这门课程草稿'))
        return {'id': cid, 'owner': r['owner'], 'version': r['version'] or 0, 'course': db.jl(r['data'], {}) or {}, 'published_at': r['published_at']}

    @app.post('/api/teach/authoring/{cid}/fetch')
    async def fetch_remote(cid: str, request: Request):
        """客户端：把服务器上自己的课（别的电脑上做的）下载到本机继续改。"""
        u = need_teacher(request)
        from ..tenancy import coursesync
        if not coursesync.client_saas():
            raise HTTPException(404, _tr('只有连着 SaaS 的客户端需要从服务器取草稿'))
        d = await coursesync.remote_draft(cid)
        c = d.get('course') if isinstance(d, dict) else None
        if not isinstance(c, dict):
            raise HTTPException(502, _tr('服务器没有返回草稿'))
        now = store.now()
        if _row(cid):
            db.x('update authored_courses set data=?, version=?, updated=? where id=?', (json.dumps(c, ensure_ascii=False), int(d.get('version') or 0), now, cid))
        else:
            db.x('insert into authored_courses(id, owner, data, created, updated, version, published_at) values(?,?,?,?,?,?,?)',
                 (cid, u['username'], json.dumps(c, ensure_ascii=False), now, now, int(d.get('version') or 0), d.get('published_at')))
        return view(_row(cid))

    # ---------------- 4.6.1 出题检查、参考做法 ----------------
    @app.get('/api/teach/authoring/{cid}/checks')
    async def checks_get(cid: str, request: Request):
        _u, r = need_own(request, cid)
        return view(r)

    @app.post('/api/teach/authoring/{cid}/checks')
    async def checks_run(cid: str, request: Request, body: dict = Body(default={})):
        _u, r = need_own(request, cid)
        await run_baselines(cid, db.jl(r['data'], {}) or {}, bool(body.get('force')))
        if body.get('wait'):                          # 测试和脚本用：等试运行跑完再返回
            await ensure_baselines(cid, db.jl(r['data'], {}) or {})
        return view(_row(cid))

    @app.post('/api/teach/authoring/{cid}/reference')
    async def reference_put(cid: str, request: Request, body: dict = Body(default={})):
        """存参考做法：{aid}（预览里的作业：取老师沙箱里现在的模型 / PLC 程序和作答），或者直接给 {lesson, model? | program?, answers?}。"""
        u, r = need_own(request, cid)
        c = db.jl(r['data'], {}) or {}
        lid, model, program, answers, aid = body.get('lesson'), body.get('model'), body.get('program'), body.get('answers'), body.get('aid')
        if aid:
            from .api import need_assignment
            from .sandbox import pid_for
            from .tasks import task_of
            from ..server import SANDBOXES
            a = need_assignment(u, int(aid))
            if a.get('course') != PREVIEW + cid:
                raise HTTPException(400, _tr('只能从这门课的预览里存参考做法'))
            lid = a.get('lesson')
            t = task_of(a)
            if getattr(t, 'sandbox', True) is False:
                raise HTTPException(400, _tr('测验和 MES 课不需要参考做法（测验按标准答案判）'))
            pid = pid_for(u['username'], a['id'])
            art = None
            if pid in mgr.sandboxes or os.path.exists(os.path.join(SANDBOXES, f'{pid}.yaml')):
                rt = await app.state.teach_pool.ensure(u['username'], a, t)
                art = t.artifact(rt)
            if not art:
                sub = db.q("select program from submissions where assignment_id=? and username=? and status!='error' order by id desc limit 1", (a['id'], u['username']), one=True)
                art = db.jl(sub['program'], None) if sub else None
            if not art:
                raise HTTPException(400, _tr('预览里还没有做这一课：先进去改好模型（或写好程序并下载到 PLC），再存为参考做法'))
            ar = db.q('select data from answers where assignment_id=? and username=?', (a['id'], u['username']), one=True)
            answers = db.jl(ar['data'], {}) if ar else {}
            if t.kind == 'cell':
                program = art
            else:
                model = art
        lesson = next((l for _ch, l in courses.lessons(c) if l.get('id') == lid), None)
        if not lesson:
            raise HTTPException(404, _tr('课程里没有课 {lid}', lid=lid))
        kind = lesson.get('kind', 'plant')
        if kind not in verify.BASELINE_KINDS:
            raise HTTPException(400, _tr('测验和 MES 课不需要参考做法（测验按标准答案判）'))
        if kind == 'cell' and not isinstance(program, dict):
            raise HTTPException(400, _tr('PLC 课的参考做法是 PLC 程序'))
        if kind != 'cell' and not isinstance(model, dict):
            raise HTTPException(400, _tr('产线 / 点选课的参考做法是工厂模型'))
        data = {'kind': kind, 'aid': aid, 'answers': {k: v for k, v in (answers or {}).items() if v is not None}}
        if kind == 'cell':
            data['program'] = program
            n = len(str(program.get('source') or '').splitlines()) if isinstance(program.get('source'), str) else len((program.get('source') or {}).get('rungs') or [])
            data['summary'] = [_tr('{v}程序 {n} {v2}', v='ST' if program.get('lang') == 'st' else _tr('梯形图'), n=n, v2=_tr('行') if program.get('lang') == 'st' else _tr('个梯级'))]
        else:
            data['model'] = model
            data['summary'] = model_diff(courses.start_model(lesson), model) or [_tr('和起始模型一样（什么都没改）')]
            if data['answers']:
                data['summary'].append(_tr('作答 {len} 题', len=len(data['answers'])))
        raw = json.dumps(data, ensure_ascii=False, default=str)
        if len(raw) > 3_000_000:
            raise HTTPException(413, _tr('参考做法太大了'))
        db.x('insert or replace into authored_refs(cid, lesson, data, created, by) values(?,?,?,?,?)', (cid, lid, raw, store.now(), u['username']))
        await run_baselines(cid, c)
        return view(_row(cid))

    @app.delete('/api/teach/authoring/{cid}/reference/{lid}')
    async def reference_del(cid: str, lid: str, request: Request):
        need_own(request, cid)
        db.x('delete from authored_refs where cid=? and lesson=?', (cid, lid))
        return view(_row(cid))

    # ---------------- 课程包（客户端） ----------------
    @app.get('/api/teach/courses/pubkey')
    async def pubkey(request: Request):
        me(request)
        return coursepkg.public_info()

    def _may_read(u, cid):
        if u['role'] in ('teacher', 'admin', 'orgadmin'):
            from .course_api import course_org          # 5.0：别的单位老师做的课不给
            o = course_org(courses.get_course(cid))
            return o is None or o == (u.get('org') or 'default')
        cls = db.classes_of_student(u['username'])
        return bool(cls) and bool(db.q(f"select 1 from course_pubs where course=? and class_id in ({','.join('?' * len(cls))})", (cid, *cls), one=True))

    @app.get('/api/teach/courses/{cid}/package')
    async def package(cid: str, request: Request):
        u = me(request)
        if not _may_read(u, cid):
            raise HTTPException(403, _tr('这门课没有发布到你的班级'))
        data = build_package(cid, str(request.base_url).rstrip('/'))
        return Response(data, media_type='application/octet-stream', headers={'Content-Disposition': f'attachment; filename="{cid}{coursepkg.EXT}"'})

    @app.get('/api/teach/courses/{cid}/assets/{name}')
    async def asset(cid: str, name: str, request: Request):
        n = os.path.basename(name)
        ext = os.path.splitext(n)[1].lower()
        if ext not in coursepkg.ASSET_EXT:
            raise HTTPException(404, _tr('没有这个文件'))
        ctype = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml'}[ext]
        base = os.path.basename(cid[len(PREVIEW):] if cid.startswith(PREVIEW) else cid)
        if base in ('', '.', '..'):
            raise HTTPException(404, _tr('没有这个文件'))
        from .course_api import course_org                 # 5.0：别的单位老师做的课，封面也不给
        o = course_org(courses.get_course(base))
        if o is not None and o != (me(request).get('org') or 'default'):
            raise HTTPException(404, _tr('没有这个文件'))
        p = os.path.join(_assets_dir(base), n)
        if os.path.exists(p):
            with open(p, 'rb') as fh:
                return Response(fh.read(), media_type=ctype, headers={'Cache-Control': 'max-age=3600'})
        ip = os.path.join(courses.installed_dir(), f'{os.path.basename(base)}{coursepkg.EXT}')
        if os.path.exists(ip):
            try:
                with open(ip, 'rb') as fh:
                    d = coursepkg.verify_installed(fh.read())
                if n in d['assets']:
                    return Response(d['assets'][n], media_type=ctype, headers={'Cache-Control': 'max-age=3600'})
            except coursepkg.CoursePackageError:
                pass
        raise HTTPException(404, _tr('没有这个文件'))
