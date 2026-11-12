"""教学接口（/api/teach/...）。

教师/管理员：
  GET  /api/teach/scenes                              场景库（摘要 + 可注入故障）
  GET  /api/teach/scenes/{sid}                        场景详情（含参考答案，仅老师）
  GET  /api/teach/classes                             我的班级（管理员看全部）
  POST /api/teach/classes                {name, descr?, teacher?}
  GET  /api/teach/classes/{cid}                       班级 + 名单
  PATCH/DELETE /api/teach/classes/{cid}
  POST /api/teach/classes/{cid}/roster   {csv, default_password?}   导入名单（列：账号,姓名,密码；表头可中文可英文，可省略）
  POST /api/teach/classes/{cid}/members  {username}   DELETE /api/teach/classes/{cid}/members/{username}
  GET  /api/teach/assignments?class_id=               任务列表（带提交统计）
  POST /api/teach/assignments            {class_id, scene, title?, descr?, due?, faults?:[{comp,kind}], start_faults?, hints?, tutor?}
  PATCH/DELETE /api/teach/assignments/{aid}
  GET  /api/teach/assignments/{aid}/progress          教师控制台：每个学生的状态、最高分、I/O 摘要
  POST /api/teach/assignments/{aid}/students/{user}/faults   {comp, kind}   给某个学生的沙箱注入故障
  DELETE /api/teach/assignments/{aid}/students/{user}/faults           清除
  GET  /api/teach/assignments/{aid}/students/{user}/watch    旁观（只读）：沙箱编号、I/O、PLC 状态、统计、最近事件、程序
  GET  /api/teach/assignments/{aid}/submissions        全部提交
  POST /api/teach/submissions/{sub}/review  {score?, comment?}    复核：改分（null = 恢复自动分）+ 评语
  GET  /api/teach/classes/{cid}/gradebook(.csv|.xlsx)  成绩册（每个任务取最高分）
  GET  /api/teach/sandboxes                            沙箱池状态
学生：
  GET  /api/teach/my                                   我的任务（状态、最高分、截止时间）
  GET  /api/teach/assignments/{aid}/task               任务书、I/O 表、评分规则、提示、我的提交
  POST /api/teach/assignments/{aid}/sandbox            进入我的沙箱（不存在就创建，休眠就唤醒）→ {pid, bid}
  POST /api/teach/assignments/{aid}/sandbox/reset      重置沙箱
  POST /api/teach/assignments/{aid}/submit             提交：用沙箱里的程序自动评分 → 得分与明细
作业包（.vfhw，见 package.py 和设计 4.2）：
  POST /api/teach/assignments/{aid}/submit_package     学生交客户端导出的作业包（原始字节或 {data: base64}）：服务器重新评分，记来源"客户端"
  GET  /api/teach/assignments/{aid}/package[?username=]  把沙箱里的作业打成作业包下载（学生自己的；老师可指定学生）
  POST /api/teach/assignments/{aid}/students/{u}/import_package   老师替学生导入作业包（记来源"导入"）
  GET  /api/teach/submissions/{sid}/package            下载某次提交的作业包（沙箱提交现打包）
  POST /api/teach/submissions/{sid}/open               老师：用这次提交建一个复核沙箱 sb-review-<sid>（只能运行，不能改）
  GET  /api/teach/assignments/{aid}/task?client=1      额外返回 client：在客户端本机建沙箱需要的完整定义
提交工厂（4.4，kind=factory，见 factory.py）：
  POST /api/teach/assignments            {kind:'factory', class_id, title, brief_md, due?, checks:[…], hours?}   没有场景，学生在客户端交自己的工厂
  GET  /api/teach/factory/types                        发布向导：可以要求的设备类型
  学生在客户端里选"我的工厂"提交：客户端打成版本 2 的作业包 → submit_package；服务器按 checks 自动检查，老师复核给分（就是成绩）
"""
from ..i18n import _tr, variants

# progress states of a student row: display text (message id) -> stable code (rows[].state_code, counts_code)
STATE_CODES = {'未开始': 'not_started', '未下载程序': 'no_program', '进行中': 'in_progress', '休眠': 'sleeping', '卡住': 'stuck', '已提交': 'submitted',
               '已满分': 'full_score', '离开': 'away', '故障中': 'faulted', '待评分': 'awaiting_grading', '已评分': 'graded'}


def state_code(text):
    for zh, code in STATE_CODES.items():
        if text in variants(zh):
            return code
    return 'other'
import asyncio
import copy
import csv
import io
import json
import os
import random
import re
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from .. import store
from .. import courses
from . import db, scenes
from . import package as pk
from .sandbox import Pool, pid_for, user_part
from .tasks import LessonTask, task_of

_pool = None


def score_pool():
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=3)
    return _pool


def me(request):
    return request.state.user


def need_teacher(request):
    u = me(request)
    if u['role'] not in ('teacher', 'admin', 'orgadmin'):      # 5.0 单位管理员：本单位的班级都能管（db.teaches 按单位查）
        raise HTTPException(403, _tr('只有老师和管理员可以操作'))
    return u


def org_of(u):
    return (u or {}).get('org') or 'default'


def need_class(u, cid):
    c = db.q('select * from classes where id=?', (cid,), one=True)
    if not c:
        raise HTTPException(404, _tr('没有这个班级'))
    if not db.teaches(u, cid):
        raise HTTPException(403, _tr('这不是你的班级'))
    return c


def need_assignment(u, aid, teacher=False):
    a = db.assignment(aid)
    if not a:
        raise HTTPException(404, _tr('没有这个任务'))
    local = _client_class(a['class_id']) and a['class_id'] in db.classes_of_student(u['username'])
    if not local and db.teaches(u, a['class_id']):         # 管理员 / 单位管理员：本单位的班（teaches 里按单位查）
        a['_teacher'] = True
        return a
    if teacher:
        raise HTTPException(403, _tr('这不是你班级的任务'))
    if a['class_id'] not in db.classes_of_student(u['username']):
        raise HTTPException(403, _tr('你不在这个班级'))
    if a['status'] != 'published':
        raise HTTPException(403, _tr('任务已关闭'))
    if a.get('start_at') and store.now()[:16] < a['start_at']:
        raise HTTPException(403, _tr('这个任务 {start_at} 才开始', start_at=a['start_at']))
    a['_teacher'] = False
    if a.get('course') and lesson_state(a, u['username'])['locked']:
        raise HTTPException(403, _tr('这一课还没解锁：先完成上一课（≥ 及格分）'))
    return a


CLIENT_TEACHERS = ('_local', '_school')      # 客户端（桌面模式）自己建的班：本机自学、学校作业的本机副本；本机账号在里面当学生


def _client_class(cid):
    r = db.q('select teacher from classes where id=?', (cid,), one=True)
    return bool(r and r['teacher'] in CLIENT_TEACHERS)


def need_task(a):
    return task_of(a)


REVIEW_PREFIX = 'sb-review-'


def _data_dir():
    """可写数据目录：桌面模式下是 VF_HOME（paths 模块），服务器上是 <程序目录>/data。"""
    try:
        from .. import paths
        for k in ('DATA', 'DATA_DIR', 'data_dir'):
            v = getattr(paths, k, None)
            if v:
                return v() if callable(v) else v
    except ImportError:
        pass
    import os
    return os.path.join(store.ROOT, 'data')


def course_open_all(class_id, course):
    r = db.q('select open_all from course_pubs where class_id=? and course=?', (class_id, course), one=True)
    return bool(r and r['open_all'])


def _unlock_min(lesson):
    u = (lesson or {}).get('unlock')
    try:
        return float(u.get('min', 60)) if isinstance(u, dict) else 60.0
    except (TypeError, ValueError):
        return 60.0


def lesson_state(a, username, best_cache=None):
    """课程作业对某个学生的状态：locked / open / done（≥ 解锁分）。按 seq 找同一班同一课程的上一课。"""
    bc = best_cache if best_cache is not None else {}

    def best(aid):
        if aid not in bc:
            bc[aid] = best_scores(aid)
        return (bc[aid].get(username) or {}).get('score')
    _, les = courses.get_lesson(a['course'], a['lesson'])
    mine = best(a['id'])
    st = {'best': mine, 'locked': False, 'state': 'done' if mine is not None and mine >= _unlock_min(les) else 'open'}
    if course_open_all(a['class_id'], a['course']):
        return st
    un = (les or {}).get('unlock')
    if isinstance(un, dict) and un.get('free'):                 # 4.6：这一课不锁
        return st
    if isinstance(un, dict) and un.get('after'):                # 4.6：指定先修课，全部达到各自的及格分才解锁
        for pre in un['after']:
            pa = db.q("select id, lesson from assignments where class_id=? and course=? and lesson=? and status='published'",
                      (a['class_id'], a['course'], pre), one=True)
            if not pa:
                continue
            _, pl = courses.get_lesson(a['course'], pre)
            pb = best(pa['id'])
            if pb is None or pb < _unlock_min(pl):
                st.update(locked=True, state='locked', waiting=pre)
                break
        return st
    prev = db.q("select id, lesson from assignments where class_id=? and course=? and seq<? and status='published' order by seq desc limit 1",
                (a['class_id'], a['course'], a.get('seq') or 0), one=True)
    if prev:
        _, pl = courses.get_lesson(a['course'], prev['lesson'])
        pb = best(prev['id'])
        if pb is None or pb < _unlock_min(pl):
            st.update(locked=True, state='locked')
    return st


def clean_answer(v):
    """作答只存数据：数字、字符串、布尔，或它们的列表（多选题）。"""
    if isinstance(v, (bool, int, float, str)):
        return v if not isinstance(v, str) else v[:400]
    if isinstance(v, (list, tuple)):
        return [x if isinstance(x, (bool, int, float)) else str(x)[:80] for x in list(v)[:40]]
    return str(v)[:400]


def mes_snapshot(lesson, answers, pid=None):
    """MES 课交作业时在本机 MES 上取快照（教学 MES 模块 vfactory/mes/teach_rules.py 提供；没有 MES 时 {}）。"""
    try:
        from ..mes import teach_rules
    except Exception:                                   # noqa: BLE001
        return {}
    try:
        return teach_rules.snapshot((lesson or {}).get('rules') or [], answers or {}, pid) or {}
    except Exception:                                   # noqa: BLE001
        return {}


def need_scene(sid):
    s = scenes.load_scene(sid)
    if not s:
        raise HTTPException(404, _tr('场景库里没有 {sid}', sid=sid))
    return s


def final(sub):
    return sub['override_score'] if sub.get('override_score') is not None else sub.get('auto_score')


def sub_view(r, full=False, show=True):
    d = {k: r[k] for k in ('id', 'assignment_id', 'username', 'created', 'status', 'auto_score', 'override_score', 'comment', 'reviewed_by',
                           'reviewed_at', 'late')}
    d['score'] = final(r)
    det = db.jl(r['details'], {}) or {}
    d['max'] = 100
    d['raw'] = {'score': det.get('raw_score'), 'max': det.get('max')}
    d['details'] = det.get('details', []) if show else []
    d['hidden'] = not show
    d['error'] = det.get('error')
    d['trial'] = bool(r.get('trial'))
    d['rule_comments'] = db.jl(r.get('rule_comments'), {}) or {}
    d['source'] = r.get('source') or 'sandbox'
    d['has_package'] = bool(r.get('package'))
    st = det.get('stats')
    if isinstance(st, dict) and 'plcs' in st and 'types' in st:          # 提交工厂：交的是哪座工厂（factory.summary）
        d['plant'] = {k: st.get(k) for k in ('name', 'blocks', 'plcs', 'programs', 'links')}
    if full:
        d['stats'] = det.get('stats')
        d['final_stats'] = det.get('final_stats')
        d['checks'] = det.get('checks')
        d['log'] = det.get('log')
        d['program'] = db.jl(r['program'])
    return d


def reveal_state(a):
    """4.6.2 作答题的正确答案和解析给不给学生看：
    shown 显示 | due 截止以后才显示（还没到截止 / 没设截止时间）| never 老师设了不显示 |
    local 客户端里学校作业的本机预估分（还没交给老师：不显示，交给老师以后学校服务器按老师的设置给）。
    老师（看学生的提交、预览里试做）一直显示；客户端"本机自学"的课提交（本机评分）后就显示。"""
    if a.get('_teacher'):
        return 'shown'
    c = db.q('select teacher from classes where id=?', (a['class_id'],), one=True)
    who = (c or {}).get('teacher')
    if who == '_school':
        return 'local'
    if who == '_local':
        return 'shown'
    p = a.get('reveal') or 'submit'
    if p == 'never':
        return 'never'
    if p == 'due':
        return 'shown' if a.get('due') and store.now()[:16] >= a['due'] else 'due'
    return 'shown'


def _block_names(t):
    try:
        return {b['id']: b.get('name') or b['id'] for b in courses.plant_model(t.lesson).get('blocks') or []}
    except Exception:                                   # noqa: BLE001  测验课没有工厂
        return {}


def with_reveal(view, a, t, row):
    """学生看到的一次提交（4.6.2）：每道作答题加上"你的答案"（your）；按 reveal_state 再加正确答案（correct）和解析（explain）。
    view['reveal'] = {state, policy, due}。评分细则不显示（show_details 关了）时什么也不加。AI 助教用的 sub_view 不经过这里（不给答案）。"""
    from ..courses import rules as R
    if not isinstance(t, LessonTask) or view.get('hidden'):
        return view
    rules = {r.get('key'): r for r in t.lesson.get('rules') or [] if r.get('kind') == 'answer'}
    if not rules:
        return view
    state = reveal_state(a)
    ans = (db.jl(row.get('details'), {}) or {}).get('answers') or {}
    names = _block_names(t) if any(r.get('pick') for r in rules.values()) else {}
    cid = t.course['id']
    for d in view.get('details') or []:
        r = rules.get(d.get('key'))
        if not r:
            continue
        d['your'] = R.answer_text(r, ans.get(d['key']), names)
        if state == 'shown':
            d['correct'] = R.answer_text(r, R.answer_of(r, t.lesson, cid), names, correct=True)
            ex = R.explain_of(r, t.lesson, cid)
            if ex:
                d['explain'] = ex
    view['reveal'] = {'state': state, 'policy': a.get('reveal') or 'submit', 'due': a.get('due')}
    return view


def _reveal_arg(v):
    if v in (None, ''):
        return 'submit'
    if v not in db.REVEAL:
        raise HTTPException(400, _tr('正确答案的显示方式只能是 submit（提交后）/ due（截止后）/ never（不显示）'))
    return v


def best_scores(aid):
    out = {}
    for r in db.q('select * from submissions where assignment_id=? and status in (?,?)', (aid, 'scored', 'reviewed')):
        s = final(r)
        if s is None:
            continue
        b = out.get(r['username'])
        if b is None or s > b['score']:
            out[r['username']] = {'score': s, 'id': r['id'], 'at': r['created'], 'reviewed': r['status'] == 'reviewed'}
    return out


HEAD_KEYS = {'user': ('账号', '学号', '用户名', '登录名', 'username', 'user', 'id', 'account', 'no', '编号'), 'name': ('姓名', '名字', '学生姓名', 'name'),
             'pw': ('密码', '初始密码', 'password', 'pw')}
ACCOUNT_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,40}$')


def _split_line(line):
    """一行 → 字段：制表符（从 Excel 复制）、逗号、中文逗号、分号、顿号都算分隔；都没有时按空白分。"""
    for sep in ('\t', ',', _tr('，'), ';', _tr('；'), _tr('、')):
        if sep in line:
            return [c.strip().strip('"').strip() for c in line.split(sep)]
    return [c for c in re.split(r'\s+', line.strip()) if c]


def roster_rows(rows):
    """二维表（文本或 Excel 读出来的）→ [{line, username, name, password}]；第一行是表头时按表头找列。"""
    rows = [[str(c if c is not None else '').strip() for c in r] for r in rows]
    rows = [(i + 1, r) for i, r in enumerate(rows) if any(c for c in r)]
    if not rows:
        return []
    head = [c.lower() for c in rows[0][1]]
    idx = {}
    for k, names in HEAD_KEYS.items():
        for i, h in enumerate(head):
            if h in names:
                idx[k] = i
                break
    if 'user' in idx or 'name' in idx:
        rows = rows[1:]
        idx.setdefault('user', 0)
    else:
        idx = {'user': 0, 'name': 1, 'pw': 2}
    out = []
    for line, r in rows:
        def col(k):
            i = idx.get(k)
            return r[i] if i is not None and i < len(r) else ''
        out.append({'line': line, 'username': col('user'), 'name': col('name'), 'password': col('pw')})
    return out


def parse_roster(text):
    """粘贴的名单文本 → 行（兼容旧调用：返回 [(账号, 姓名, 密码)]）。"""
    return [(r['username'], r['name'], r['password']) for r in roster_rows(_text_rows(text))]


def _text_rows(text):
    return [_split_line(ln) for ln in (text or '').lstrip('\ufeff').replace('\r', '').split('\n')]


def xlsx_rows(b64):
    import base64
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(base64.b64decode(b64.split(',', 1)[-1])), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(400, _tr('读不了这个 Excel 文件（请用 .xlsx 格式）'))
    ws = wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def check_roster(cid, rows, dpw, org=None):
    """导入前检查每一行：new 新账号 / exists 已有学生账号 / in_class 已在班里 / error（原因）。
    org（5.0）：已有账号必须是同一个单位的（账号全平台唯一，别的单位的学生不能拉进来）。"""
    if org is None and cid:
        org = (db.q('select org from classes where id=?', (cid,), one=True) or {}).get('org') or 'default'
    seen = {}
    out = []
    for r in rows:
        u, msg, st = r['username'], '', ''
        if isinstance(u, float) and u.is_integer():
            u = str(int(u))
        u = str(u).strip()
        r['username'] = u
        pw = str(r['password'] or '').strip()
        if not u:
            st, msg = 'error', _tr('账号为空')
        elif not ACCOUNT_RE.match(u):
            st, msg = 'error', _tr('账号只能用字母、数字、下划线、点和短横线（不能有空格、中文或逗号）')
        elif u in seen:
            st, msg = 'error', _tr('和第 {v} 行重复', v=seen[u])
        else:
            seen[u] = r['line']
            ex = store.q('select role, org from users where username=?', (u,), one=True)
            if ex is None:
                st = 'new'
                if len(pw or dpw) < 6:
                    st, msg = 'error', _tr('密码少于 6 位')
            elif org is not None and (ex.get('org') or 'default') != org:
                st, msg = 'error', _tr('账号已被别的单位使用（账号全平台唯一，换一个，或加单位前缀）')
            elif ex['role'] != 'student':
                st, msg = 'error', _tr('已是{get}账号，不能加入班级', get=store.ROLES.get(ex['role'], ex['role']))
            elif cid and db.q('select 1 from class_members where class_id=? and username=?', (cid, u), one=True):
                st, msg = 'in_class', _tr('已在班里')
            else:
                st, msg = 'exists', _tr('账号已存在，直接加入本班（密码不变）')
        out.append({**r, 'password': pw, 'status': st, 'msg': msg})
    return out


def register(app, mgr):
    pool = Pool(mgr)
    app.state.teach_pool = pool
    mgr.teach_pool = pool

    def plc_restore(rt):
        svc = getattr(app.state, 'plc', None)          # 软 PLC 服务（vfactory/plc/api.py）：把学生最后下载的程序装回新建的 PLC
        if svc is not None and hasattr(svc, 'reconcile'):
            svc.reconcile(rt.pid, rt)
    pool.after_start.append(plc_restore)

    def sandbox_rt(username, aid):
        return mgr.sandboxes.get(pid_for(username, aid))

    # ---------------- 场景库 ----------------
    @app.get('/api/teach/scenes')
    async def scene_list(request: Request):
        need_teacher(request)
        return scenes.list_scenes()

    @app.get('/api/teach/scenes/{sid}')
    async def scene_get(sid: str, request: Request):
        need_teacher(request)
        s = need_scene(sid)
        return {**scenes.public_scene(s, True), 'faults': scenes.faults_of(s), 'reference': scenes.reference_of(s), 'cell': scenes.cell_of(s),
                'warnings': scenes.check_scene(s)}

    # ---------------- 班级 ----------------
    @app.get('/api/teach/classes')
    async def class_list(request: Request):
        u = need_teacher(request)
        rows = db.q('select * from classes where org=? order by id', (org_of(u),)) if u['role'] in ('admin', 'orgadmin') \
            else db.q('select * from classes where teacher=? order by id', (u['username'],))
        rows = [r for r in rows if (r.get('descr') or '') != '__preview__']      # 4.6 课程预览用的隐藏班
        for r in rows:
            r['students'] = db.q('select count(*) n from class_members where class_id=?', (r['id'],), one=True)['n']
            r['assignments'] = db.q('select count(*) n from assignments where class_id=?', (r['id'],), one=True)['n']
        return rows

    @app.post('/api/teach/classes')
    async def class_new(request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        name = (body.get('name') or '').strip()[:60]
        if not name:
            raise HTTPException(400, _tr('班级名称不能为空'))
        teacher = u['username']
        if u['role'] in ('admin', 'orgadmin') and body.get('teacher'):
            t = store.q('select role, org from users where username=?', (body['teacher'],), one=True)
            if not t or t['role'] not in ('teacher', 'admin', 'orgadmin') or (t.get('org') or 'default') != org_of(u):
                raise HTTPException(400, _tr('任课老师账号不存在或不是本单位的教师'))
            teacher = body['teacher']
        cid = db.x('insert into classes(name,teacher,descr,created,org) values(?,?,?,?,?)',
                   (name, teacher, (body.get('descr') or '')[:500], store.now(), org_of(u)))
        return {'ok': True, 'id': cid}

    @app.get('/api/teach/classes/{cid}')
    async def class_get(cid: int, request: Request):
        u = need_teacher(request)
        c = need_class(u, cid)
        names = {r['username']: r for r in store.q('select username,name,last_login,active from users where role=?', ('student',))}
        c['members'] = [{'username': m, 'name': (names.get(m) or {}).get('name') or m, 'last_login': (names.get(m) or {}).get('last_login')}
                        for m in db.members(cid)]
        return c

    @app.patch('/api/teach/classes/{cid}')
    async def class_patch(cid: int, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        need_class(u, cid)
        if 'name' in body:
            db.x('update classes set name=? where id=?', (str(body['name'])[:60], cid))
        if 'descr' in body:
            db.x('update classes set descr=? where id=?', (str(body['descr'])[:500], cid))
        return {'ok': True}

    @app.delete('/api/teach/classes/{cid}')
    async def class_del(cid: int, request: Request):
        u = need_teacher(request)
        need_class(u, cid)
        for a in db.q('select id from assignments where class_id=?', (cid,)):
            await _drop_assignment(a['id'])
        db.x('delete from class_members where class_id=?', (cid,))
        db.x('delete from course_pubs where class_id=?', (cid,))
        db.x('delete from classes where id=?', (cid,))
        return {'ok': True}

    @app.post('/api/teach/classes/{cid}/roster')
    async def roster(cid: int, request: Request, body: dict = Body(...)):
        """导入名单：账号已存在的学生直接加入班级（不改密码）；新账号建成学生，密码为表里的密码或 default_password（默认 123456）。"""
        u = need_teacher(request)
        c = need_class(u, cid)
        from ..tenancy import saas as _saas, seats, security
        org = c.get('org') or 'default'
        gen = _saas() and not body.get('default_password')        # SaaS：没给默认密码时每人一个随机临时密码（密码规则更严）
        dpw = str(body.get('default_password') or (_tr('（每人随机）') if gen else '123456'))
        if not gen and _saas():
            security.check_password(dpw)
        rows = check_roster(cid, roster_rows(xlsx_rows(body['xlsx']) if body.get('xlsx') else _text_rows(body.get('csv') or '')),
                            'x' * 8 if gen else dpw, org=org)
        for r in rows:
            if r['status'] == 'new' and r['password'] and _saas():
                why = security.password_problem(r['password'], r['username'])
                if why:
                    r['status'], r['msg'] = 'error', why
        if not rows:
            raise HTTPException(400, _tr('名单是空的'))
        if len(rows) > 2000:
            raise HTTPException(400, _tr('一次最多导入 2000 人'))
        if body.get('preview'):
            cnt = {}
            for r in rows:
                cnt[r['status']] = cnt.get(r['status'], 0) + 1
            return {'rows': rows, 'counts': cnt, 'default_password': dpw, 'limits': seats.summary(org)}
        seats.check_add(org, 'student', sum(1 for r in rows if r['status'] == 'new'))   # 5.0 席位：超了整批不导
        created, added, existed, errors, accounts = [], [], [], [], []
        for r in rows:
            user, st = r['username'], r['status']
            if st == 'error':
                errors.append(_tr('第 {line} 行（{v}）：{msg}', line=r['line'], v=user or _tr('空'), msg=r['msg']))
                continue
            if st == 'new':
                pw = r['password'] or (security.random_password(8) if gen else dpw)
                store.x('insert into users(username,name,role,pw,created,org) values(?,?,?,?,?,?)',
                        (user, r['name'] or user, 'student', store.hash_pw(pw), store.now(), org))
                _mark_reset(user, u['username'])
                created.append(user)
                accounts.append({'username': user, 'name': r['name'] or user, 'password': pw})
            if st == 'in_class':
                existed.append(user)
                continue
            db.x('insert or ignore into class_members(class_id,username,created) values(?,?,?)', (cid, user, store.now()))
            added.append(user)
        skipped = [_tr('第 {line} 行（{username}）：已在班里', line=r['line'], username=r['username']) for r in rows if r['status'] == 'in_class']
        return {'ok': True, 'created': len(created), 'added': len(added), 'already': len(existed), 'errors': errors, 'skipped': skipped,
                'default_password': dpw, 'accounts': accounts}

    def _mark_reset(username, by):
        """记下"老师给的初始密码"：学生改过密码之前，登录后会被提示先改密码。"""
        r = store.q('select pw from users where username=?', (username,), one=True)
        if r:
            db.x('insert or replace into pw_reset(username, hash, at, by) values(?,?,?,?)', (username, r['pw'], store.now(), by))

    @app.get('/api/teach/roster_template.xlsx')
    async def roster_template(request: Request):
        """名单模板：学号、姓名、初始密码（可空）。"""
        need_teacher(request)
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = _tr('学生名单')
        ws.append([_tr('学号'), _tr('姓名'), _tr('初始密码')])
        for c in ws[1]:
            c.font, c.fill = Font(bold=True), PatternFill('solid', fgColor='DDEBF7')
        ws.append(['s2026001', _tr('张三'), ''])
        ws.append(['s2026002', _tr('李四'), ''])
        ws.column_dimensions['A'].width, ws.column_dimensions['B'].width, ws.column_dimensions['C'].width = 16, 12, 14
        ws['E1'] = _tr('说明：学号只能用字母、数字、下划线；初始密码可以不填（用导入时的默认密码，至少 6 位）。')
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename=roster-template.xlsx'})

    @app.post('/api/teach/classes/{cid}/members/reset_password')
    async def reset_pw(cid: int, request: Request, body: dict = Body(...)):
        """批量重置密码：random=true 时每人一个 6 位随机数字，否则统一用 password（默认 123456）。返回账号条数据。"""
        u = need_teacher(request)
        need_class(u, cid)
        members = set(db.members(cid))
        names = {r['username']: r['name'] for r in store.q('select username,name from users')}
        out = []
        for user in body.get('usernames') or []:
            if user not in members:
                continue
            from ..tenancy import saas as _saas, security
            if body.get('random'):
                pw = security.random_password(8) if _saas() else ''.join(random.choice('0123456789') for _ in range(6))
            else:
                pw = str(body.get('password') or '123456')
            if len(pw) < 6:
                raise HTTPException(400, _tr('密码至少 6 位'))
            if _saas():
                security.check_password(pw, user)
            store.x('update users set pw=?, failed=0, locked_until=null where username=? and role=?', (store.hash_pw(pw), user, 'student'))
            store.revoke_sessions(username=user)                # 5.0：重置密码后旧的登录全部失效
            _mark_reset(user, u['username'])
            out.append({'username': user, 'name': names.get(user) or user, 'password': pw})
        return {'ok': True, 'accounts': out}

    @app.post('/api/teach/classes/{cid}/members/remove')
    async def members_remove(cid: int, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        need_class(u, cid)
        n = 0
        for user in body.get('usernames') or []:
            db.x('delete from class_members where class_id=? and username=?', (cid, user))
            n += 1
        return {'ok': True, 'removed': n}

    @app.post('/api/teach/classes/{cid}/members')
    async def member_add(cid: int, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        need_class(u, cid)
        r = await roster(cid, request, {'csv': f"username,name,password\n{body.get('username', '')},{body.get('name', '')},{body.get('password', '')}",
                                         'default_password': body.get('password') or '123456'})
        if r['errors']:
            raise HTTPException(400, r['errors'][0])
        return r

    @app.delete('/api/teach/classes/{cid}/members/{username}')
    async def member_del(cid: int, username: str, request: Request):
        u = need_teacher(request)
        need_class(u, cid)
        db.x('delete from class_members where class_id=? and username=?', (cid, username))
        return {'ok': True}

    # ---------------- 任务 ----------------
    def _clean_faults(t, fl):
        allowed = t.faults()
        out = []
        for f in fl or []:
            f = {'comp': f.get('comp'), 'kind': f.get('kind')} if isinstance(f, dict) else {'comp': None, 'kind': str(f)}
            if allowed and not any(x['kind'] == f['kind'] and (x['comp'] in (None, f['comp']) or f['comp'] is None) for x in allowed):
                raise HTTPException(400, _tr('场景不支持故障 {v} {kind}', v=f['comp'] or '', kind=f['kind']))
            if f['comp'] is None:
                m = next((x for x in allowed if x['kind'] == f['kind']), None)
                f['comp'] = m and m['comp']
            out.append(f)
        return out

    def _due(v):
        if not v:
            return None
        v = str(v).replace('T', ' ')[:16]
        try:
            datetime.strptime(v, '%Y-%m-%d %H:%M')
        except ValueError:
            raise HTTPException(400, _tr('截止时间格式：YYYY-MM-DD HH:MM'))
        return v

    @app.get('/api/teach/assignments')
    async def assignment_list(request: Request, class_id: int = 0):
        u = need_teacher(request)
        if class_id:
            need_class(u, class_id)
            rows = db.q('select id from assignments where class_id=? order by id desc', (class_id,))
        elif u['role'] in ('admin', 'orgadmin'):
            rows = db.q("select a.id from assignments a join classes c on c.id=a.class_id where coalesce(c.descr,'')!='__preview__' and c.org=? "
                        'order by a.id desc', (org_of(u),))
        else:
            rows = db.q("select a.id from assignments a join classes c on c.id=a.class_id where c.teacher=? and coalesce(c.descr,'')!='__preview__' "
                        "order by a.id desc", (u['username'],))
        out = []
        for r in rows:
            a = db.assignment(r['id'])
            try:
                a['scene_name'] = task_of(a).name
            except HTTPException:
                a['scene_name'] = a['scene'] or a.get('lesson')
            if a.get('course'):
                c = courses.get_course(a['course'])
                a['course_name'] = c['name'] if c else a['course']
            n = len(db.members(a['class_id']))
            best = best_scores(a['id'])
            a['class_name'] = (db.q('select name from classes where id=?', (a['class_id'],), one=True) or {}).get('name')
            a['students'], a['submitted'] = n, len(best)
            a['avg'] = round(sum(b['score'] for b in best.values()) / len(best), 1) if best else None
            out.append(a)
        return out

    @app.get('/api/teach/factory/types')
    async def factory_types(request: Request):
        need_teacher(request)
        from . import factory
        return {'types': factory.block_types(), 'max_hours': factory.MAX_HOURS}

    def _factory_spec(body):
        from . import factory
        try:
            return factory.clean_spec(body)
        except factory.SpecError as e:
            raise HTTPException(400, str(e))

    @app.post('/api/teach/assignments')
    async def assignment_new(request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        cid = int(body.get('class_id') or 0)
        need_class(u, cid)
        rv = _reveal_arg(body.get('reveal'))
        if body.get('kind') == 'factory':                  # 提交工厂：没有场景；要求和自动检查在 spec 里
            spec = _factory_spec(body)
            title = str(body.get('title') or '').strip()[:80]
            if not title:
                raise HTTPException(400, _tr('请填写作业名称'))
            aid = db.x('insert into assignments(class_id,scene,title,descr,due,faults,start_faults,hints,tutor,status,teacher,created,updated,'
                       'start_at,max_subs,allow_late,show_details,kind,spec) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (cid, None, title, (body.get('descr') or '')[:2000], _due(body.get('due')), '[]', '[]', 0, 0, 'published',
                        u['username'], store.now(), store.now(), _due(body.get('start_at')), int(body['max_subs']) if body.get('max_subs') else None,
                        0 if body.get('allow_late') is False else 1, 0 if body.get('show_details') is False else 1, 'factory',
                        json.dumps(spec, ensure_ascii=False)))
            db.x('update assignments set reveal=? where id=?', (rv, aid))
            return {'ok': True, 'id': aid}
        s = need_scene(body.get('scene'))
        t = task_of({'scene': s['id']})
        faults = _clean_faults(t, body.get('faults'))
        start = _clean_faults(t, body.get('start_faults'))
        title = (body.get('title') or scenes.name_of(s))[:80]
        aid = db.x('insert into assignments(class_id,scene,title,descr,due,faults,start_faults,hints,tutor,status,teacher,created,updated,'
                   'start_at,max_subs,allow_late,show_details,kind) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (cid, s['id'], title, (body.get('descr') or '')[:2000], _due(body.get('due')), json.dumps(faults, ensure_ascii=False),
                    json.dumps(start, ensure_ascii=False), 1 if body.get('hints', True) else 0, 1 if body.get('tutor', True) else 0, 'published',
                    u['username'], store.now(), store.now(), _due(body.get('start_at')), int(body['max_subs']) if body.get('max_subs') else None,
                    0 if body.get('allow_late') is False else 1, 0 if body.get('show_details') is False else 1, 'cell'))
        db.x('update assignments set reveal=? where id=?', (rv, aid))
        return {'ok': True, 'id': aid}

    @app.patch('/api/teach/assignments/{aid}')
    async def assignment_patch(aid: int, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        s = need_task(a)
        sets = []
        if 'title' in body:
            sets.append(('title', str(body['title'])[:80]))
        if 'descr' in body:
            sets.append(('descr', str(body['descr'])[:2000]))
        if 'due' in body:
            sets.append(('due', _due(body['due'])))
        if 'faults' in body:
            sets.append(('faults', json.dumps(_clean_faults(s, body['faults']), ensure_ascii=False)))
        if 'start_faults' in body:
            sets.append(('start_faults', json.dumps(_clean_faults(s, body['start_faults']), ensure_ascii=False)))
        for k in ('hints', 'tutor', 'allow_late', 'show_details'):
            if k in body:
                sets.append((k, 1 if body[k] else 0))
        if 'start_at' in body:
            sets.append(('start_at', _due(body['start_at'])))
        if 'reveal' in body:
            sets.append(('reveal', _reveal_arg(body['reveal'])))
        if 'max_subs' in body:
            sets.append(('max_subs', int(body['max_subs']) if body['max_subs'] else None))
        if a.get('kind') == 'factory' and any(k in body for k in ('brief_md', 'checks', 'hours')):
            cur = a.get('spec') or {}
            sets.append(('spec', json.dumps(_factory_spec({'brief_md': body.get('brief_md', cur.get('brief_md')), 'checks': body.get('checks', cur.get('checks')),
                                                         'hours': body.get('hours', cur.get('hours'))}), ensure_ascii=False)))
        if 'status' in body:
            if body['status'] not in ('published', 'closed'):
                raise HTTPException(400, _tr('状态只能是 published / closed'))
            sets.append(('status', body['status']))
        for k, v in sets:
            db.x(f'update assignments set {k}=?, updated=? where id=?', (v, store.now(), aid))
        return {'ok': True, 'assignment': db.assignment(aid)}

    async def _drop_assignment(aid):
        """删除作业：沙箱、提交、作答一并删除（课程撤销发布也用它）。"""
        for r in db.q('select pid from sandboxes where assignment_id=?', (aid,)):
            await pool.drop(r['pid'])
        db.x('delete from submissions where assignment_id=?', (aid,))
        db.x('delete from answers where assignment_id=?', (aid,))
        db.x('delete from assignments where id=?', (aid,))

    @app.delete('/api/teach/assignments/{aid}')
    async def assignment_del(aid: int, request: Request):
        u = need_teacher(request)
        need_assignment(u, aid, teacher=True)
        await _drop_assignment(aid)
        return {'ok': True}

    # ---------------- 学生 ----------------
    @app.get('/api/teach/my')
    async def my(request: Request):
        u = me(request)
        cids = db.classes_of_student(u['username'])
        out = []
        for cid in cids:
            cname = (db.q('select name from classes where id=?', (cid,), one=True) or {}).get('name')
            bc = {}
            for r in db.q("select id from assignments where class_id=? and status='published' and (start_at is null or start_at<=?) "
                          "order by coalesce(course,''), coalesce(seq,0), id desc", (cid, store.now()[:16])):
                a = db.assignment(r['id'])
                try:
                    tname = task_of(a).name
                except HTTPException:
                    continue
                b = best_scores(a['id']).get(u['username'])
                n = db.q('select count(*) n from submissions where assignment_id=? and username=?', (a['id'], u['username']), one=True)['n']
                ls = lesson_state(a, u['username'], bc) if a.get('course') else {'locked': False, 'state': 'done' if b and b['score'] >= 60 else 'open'}
                out.append({'id': a['id'], 'title': a['title'], 'class_name': cname, 'class_id': cid, 'scene': a['scene'], 'scene_name': tname,
                            'course': a.get('course'), 'lesson': a.get('lesson'), 'kind': a.get('kind') or 'cell', 'seq': a.get('seq'),
                            'locked': ls['locked'], 'state': ls['state'],
                            'due': a['due'], 'overdue': bool(a['due'] and a['due'] < store.now()[:16]), 'best': b and b['score'],
                            'submissions': n, 'sandbox': pool.status(pid_for(u['username'], a['id'])), 'tutor': a['tutor'], 'hints': a['hints']})
        return out

    @app.get('/api/teach/my/courses')
    async def my_courses(request: Request):
        """课程地图：我的班级里发布了的课程 → 章 → 课（锁定/可做/完成 + 最高分），课程外的单独任务另列。"""
        items = await my(request)
        by = {}
        loose = []
        for it in items:
            if not it['course']:
                loose.append(it)
                continue
            by.setdefault((it['class_id'], it['course']), {})[it['lesson']] = it
        out = []
        for (cid, course), got in by.items():
            c = courses.get_course(course)
            if not c:
                continue
            chs = []
            for ch in c.get('chapters') or []:
                ls = []
                for l in ch.get('lessons') or []:
                    it = got.get(l['id'])
                    if it:
                        ls.append({'aid': it['id'], 'id': l['id'], 'title': l['title'], 'kind': l.get('kind', 'plant'), 'state': it['state'],
                                   'locked': it['locked'], 'best': it['best'], 'submissions': it['submissions'], 'sandbox': it['sandbox'], 'due': it['due'],
                                   'time_h': l.get('time_h'), 'prereq': ((l.get('unlock') or {}).get('after') if isinstance(l.get('unlock'), dict) else None)})
                if ls:
                    chs.append({'id': ch['id'], 'title': ch['title'], 'lessons': ls})
            flat = [l for ch in chs for l in ch['lessons']]
            out.append({'course': course, 'name': c['name'], 'desc': c.get('desc', ''), 'level': c.get('level'), 'class_id': cid,
                        'cover': c.get('cover'), 'origin': c.get('origin') or 'builtin', 'tags': c.get('tags') or [], 'order': c.get('order'),
                        'kinds': sorted({l['kind'] for ch in chs for l in ch['lessons']}),
                        'best_sum': round(sum(l['best'] or 0 for ch in chs for l in ch['lessons']), 1),
                        'class_name': next(iter(got.values()))['class_name'], 'chapters': chs, 'done': sum(1 for l in flat if l['state'] == 'done'),
                        'total': len(flat), 'next': next((l['aid'] for l in flat if l['state'] == 'open'), None)})
        out.sort(key=lambda x: (x.get('level') or 99, x.get('order') or 99, x['course']))      # 入门课在前（level、order 小的先）
        return {'courses': out, 'tasks': loose}

    @app.get('/api/teach/assignments/{aid}/task')
    async def task(aid: int, request: Request, username: str = '', client: int = 0):
        """任务详情。老师可以带 ?username= 看某个学生的提交和作答（旁观时左栏用）。
        client=1（客户端拉学校作业）：另给 client 段，客户端据此在本机建同样的沙箱（起始模型、作业设置）。"""
        u = me(request)
        a = need_assignment(u, aid)
        t = need_task(a)
        who = username if (username and a['_teacher']) else u['username']
        subs = db.q('select * from submissions where assignment_id=? and username=? order by id desc limit 20', (aid, who))
        ans = db.q('select data from answers where assignment_id=? and username=?', (aid, who), one=True)
        out = {'assignment': {k: a.get(k) for k in ('id', 'title', 'descr', 'due', 'hints', 'tutor', 'status', 'class_id', 'course', 'lesson', 'seq', 'kind', 'reveal')},
               'kind': t.kind, 'scene': t.public(a['hints'] or a['_teacher']), 'pid': pid_for(who, aid), 'username': who,
               'viewer': 'teacher' if who != u['username'] else ('trial' if a['_teacher'] else 'student'),
               'sandbox': pool.status(pid_for(who, aid)), 'submissions': [with_reveal(sub_view(r, show=a['show_details'] or a['_teacher']), a, t, r) for r in subs],
               'best': (best_scores(aid).get(who) or {}).get('score'), 'answers': db.jl(ans['data'], {}) if ans else {},
               'limits': {'max_subs': a.get('max_subs'), 'used': len(subs), 'allow_late': a['allow_late'], 'due': a['due'], 'start_at': a.get('start_at')}}
        if a.get('course'):
            c = courses.get_course(a['course'])
            out['course'] = {'id': a['course'], 'name': c['name'] if c else a['course'], 'cover': (c or {}).get('cover'), 'origin': (c or {}).get('origin') or 'builtin'}
            out['next'] = db.q("select id, title from assignments where class_id=? and course=? and seq>? and status='published' order by seq limit 1",
                               (a['class_id'], a['course'], a.get('seq') or 0), one=True)
        from .coach import tour_exists                           # 4.5 跟随教程：这一课有没有写好的步骤
        out['tour'] = t.id if tour_exists(t.id) else None
        hook = getattr(app.state, 'task_client_info', None)       # 客户端：本机自学 / 学校作业、是否连着学校
        if hook:
            out['desktop'] = hook(a)
        if client:
            cc = courses.get_course(a['course']) if a.get('course') else None
            out['client'] = {'kind': t.kind, 'scene': a.get('scene'), 'course': a.get('course'), 'lesson': a.get('lesson'),
                             'course_origin': (cc or {}).get('origin') or ('builtin' if cc else None), 'course_version': (cc or {}).get('version'),
                             'start_model': t.plant_cfg(a.get('title') or t.name),
                             'settings': {k: a.get(k) for k in ('title', 'descr', 'due', 'start_at', 'hints', 'tutor', 'max_subs', 'allow_late',
                                                                'show_details', 'faults', 'start_faults', 'spec', 'reveal')},
                             'class_name': (db.q('select name from classes where id=?', (a['class_id'],), one=True) or {}).get('name'),
                             'server_version': pk.client_version(), 'package_format': {'format': pk.FORMAT, 'version': pk.VERSION, 'max_bytes': pk.MAX_BYTES}}
        return out

    @app.get('/api/teach/assignments/{aid}/answers')
    async def answers_get(aid: int, request: Request):
        u = me(request)
        need_assignment(u, aid)
        r = db.q('select data from answers where assignment_id=? and username=?', (aid, u['username']), one=True)
        return {'answers': db.jl(r['data'], {}) if r else {}}

    @app.put('/api/teach/assignments/{aid}/answers')
    async def answers_put(aid: int, request: Request, body: dict = Body(...)):
        """保存作答（选择题、在图上点选的设备）。只保存本课规则里有的题目。"""
        u = me(request)
        a = need_assignment(u, aid)
        t = need_task(a)
        keys = {r['key'] for r in (t.lesson.get('rules') or []) if r.get('kind') == 'answer'} if isinstance(t, LessonTask) else set()
        cur = db.q('select data from answers where assignment_id=? and username=?', (aid, u['username']), one=True)
        data = db.jl(cur['data'], {}) if cur else {}
        for k, v in (body.get('answers') or {}).items():
            if k in keys:
                if v is None or v == '' or v == []:
                    data.pop(k, None)
                else:
                    data[k] = clean_answer(v)
        db.x('insert or replace into answers(assignment_id, username, data, updated) values(?,?,?,?)',
             (aid, u['username'], json.dumps(data, ensure_ascii=False), store.now()))
        return {'ok': True, 'answers': data}

    def _sandbox_view(rt):
        c = scenes.cell(rt) if scenes.cells(rt) else None
        # bid：控制单元（设备）；plc_block：学生编程的 PLC 块（4.3 起 PLC 是独立的块，通过信号线控制单元）
        return {'pid': rt.pid, 'bid': c.id if c else None, 'cells': [x.id for x in scenes.cells(rt)], 'name': rt.plant.name,
                'plc_block': scenes.plc_info(rt), 'state': 'sleeping' if rt.hibernating else 'running'}

    @app.post('/api/teach/assignments/{aid}/sandbox')
    async def sandbox_enter(aid: int, request: Request):
        u = me(request)
        a = need_assignment(u, aid)
        t = need_task(a)
        if getattr(t, 'sandbox', True) is False:
            raise HTTPException(400, _tr('这一课不用进沙箱：直接在"目标与作答"里作答，再点"提交评分"'))
        rt = await pool.ensure(u['username'], a, t)
        return _sandbox_view(rt)

    @app.post('/api/teach/assignments/{aid}/sandbox/reset')
    async def sandbox_reset(aid: int, request: Request, body: dict = Body(default={})):
        u = me(request)
        a = need_assignment(u, aid)
        rt = await pool.reset(u['username'], a, need_task(a), clear_program=bool((body or {}).get('clear_program')))
        return _sandbox_view(rt)

    @app.get('/api/teach/assignments/{aid}/live')
    async def live(aid: int, request: Request):
        """学生自己的沙箱实时状态（I/O、PLC、统计）；沙箱没创建时 running=False。"""
        u = me(request)
        a = need_assignment(u, aid)
        rt = mgr.sandboxes.get(pid_for(u['username'], aid))
        if rt is None:
            return {'running': False, 'sandbox': 'none'}
        rt.touch()
        t = need_task(a)
        extra = {'takeover': _takeover_info(rt.pid), 'faults_active': len(open_faults(aid, u['username'], rt, t)),
                 'diagnose': t.parts(rt) if open_faults(aid, u['username'], rt, t) else None}
        if isinstance(t, LessonTask):
            ans = db.q('select data from answers where assignment_id=? and username=?', (aid, u['username']), one=True)
            return {'running': not rt.hibernating, 'sandbox': pool.status(rt.pid), 'pid': rt.pid, 'bid': None, 'time': rt.plant.clock_str(), 'sim_s': round(rt.plant.t, 1),
                    'paused': rt.plant.paused, 'progress': t.live(rt, db.jl(ans['data'], {}) if ans else {}), 'has_program': True, **extra}
        c = scenes.cell(rt)
        return {'running': not rt.hibernating, 'sandbox': pool.status(rt.pid), 'pid': rt.pid, 'bid': c.id if c else None, 'io': scenes.io_values(rt),
                'plc': scenes.plc_state(rt), 'plc_block': scenes.plc_info(rt), 'stats': scenes.stats(rt), 'alarm': (c.alarm if c else '') or '',
                'hint': getattr(c, 'hint', '') if c else '', 'time': rt.plant.clock_str(),
                'has_program': bool(t.artifact(rt)), **extra}

    def _submit_checks(a, username, as_student=True):
        """截止时间、提交次数（学生交、老师替学生导入都查）；返回是否逾期。"""
        if a['status'] != 'published':
            raise HTTPException(400, _tr('任务已关闭，不能提交'))
        late = 1 if a['due'] and store.now()[:16] > a['due'] else 0
        if as_student:
            if late and not a['allow_late']:
                raise HTTPException(400, _tr('已过截止时间（{due}），老师设置了不接受迟交', due=a['due']))
            if a.get('max_subs'):
                n = db.q("select count(*) n from submissions where assignment_id=? and username=? and status!='error'", (a['id'], username), one=True)['n']
                if n >= a['max_subs']:
                    raise HTTPException(400, _tr('提交次数已用完（最多 {max_subs} 次）', max_subs=a['max_subs']))
        return late

    async def _score_and_record(a, t, username, program, answers, late, trial=False, source='sandbox', pkg_bytes=None):
        """记一次提交并评分（沙箱提交、作业包提交、老师导入都走这里，评分代码完全相同）。返回提交记录。"""
        aid = a['id']
        if getattr(t, 'kind', '') == 'mes':                   # MES 课：评分时取的是这个学生在 MES 里的状态
            src = program if isinstance(program, dict) else {}
            program = {'kind': 'mes', 'username': username, 'assignment_id': aid, 'lesson': a.get('lesson'), 'course': a.get('course'),
                       'class_id': a.get('class_id'), 'pid': src.get('pid'), 'mes_snapshot': src.get('mes_snapshot')}
            if not isinstance(program['mes_snapshot'], dict) and (getattr(mgr, 'desktop', None) or os.environ.get('VF_DESKTOP') == '1'):
                # 客户端：交作业这一刻在本机 MES 上取快照，本机评分和交给学校的作业包用同一份（学校服务器上没有 MES，复评只看快照）
                program['mes_snapshot'] = await asyncio.get_running_loop().run_in_executor(None, mes_snapshot, t.lesson, answers, program['pid'])
        pending = db.q("select id, created from submissions where assignment_id=? and username=? and status='scoring'", (aid, username), one=True)
        if pending and time.time() - datetime.strptime(pending['created'], '%Y-%m-%d %H:%M:%S').timestamp() < 300:
            raise HTTPException(409, _tr('上一次提交还在评分，请稍等'))
        sid = db.x('insert into submissions(assignment_id,username,created,status,program,late,trial,source) values(?,?,?,?,?,?,?,?)',
                   (aid, username, store.now(), 'scoring', json.dumps(program, ensure_ascii=False), late, 1 if trial else 0, source))
        if pkg_bytes:
            d = _pkg_dir()
            os.makedirs(d, exist_ok=True)
            fn = f'{sid}{pk.EXT}'
            with open(os.path.join(d, fn), 'wb') as f:
                f.write(pkg_bytes)
            db.x('update submissions set package=? where id=?', (fn, sid))
        loop = asyncio.get_running_loop()
        try:
            fn, args = t.score_call(program, answers)
            r = await asyncio.wait_for(loop.run_in_executor(score_pool(), fn, *args), timeout=300)
        except Exception as e:
            r = {'ok': False, 'error': _tr('评分出错：{e}', e=e), 'score': 0, 'max': 100, 'details': []}
        if not r.get('ok') and isinstance(r.get('compile'), dict) and r['compile'].get('ok') is False:
            r.update(ok=True, score=0.0)          # 学生程序编译不过：记 0 分（不是评分系统出错），错误信息留在明细里
        st = 'scored' if r.get('ok') else 'error'
        sc = round(float(r['score']) / float(r.get('max') or 100) * 100, 1) if r.get('ok') else None
        if r.get('ok') and r.get('manual'):       # 提交工厂、没有自动检查：已收到，等老师评分（老师给的分就是成绩）
            st, sc = 'submitted', None
        keep = {k: r.get(k) for k in ('max', 'details', 'stats', 'error', 'final_stats', 'checks', 'cost_rows')}
        if answers is not None:
            keep['answers'] = answers
        keep['raw_score'] = r.get('score')
        keep['log'] = (r.get('log') or [])[-30:]
        db.x('update submissions set status=?, auto_score=?, details=? where id=?',
             (st, sc, json.dumps(keep, ensure_ascii=False, default=str), sid))
        return db.q('select * from submissions where id=?', (sid,), one=True)

    @app.post('/api/teach/assignments/{aid}/submit')
    async def submit(aid: int, request: Request, body: dict = Body(default={})):
        u = me(request)
        a = need_assignment(u, aid)
        t = need_task(a)
        if t.kind == 'factory':                         # 提交工厂：客户端里选一座"我的工厂"（本机检查 = 本机预估分）
            late = _submit_checks(a, u['username'], as_student=not a['_teacher'])
            art = await _factory_art(u, body.get('plant'))
            row = await _score_and_record(a, t, u['username'], art, None, late, trial=a['_teacher'])
            return sub_view(row, show=a['show_details'] or a['_teacher'])
        teacher_art = u['role'] in ('teacher', 'admin') and (body.get('program') or body.get('model'))
        program = (body.get('program') or body.get('model')) if teacher_art else None
        late = _submit_checks(a, u['username'], as_student=not a['_teacher'])
        if program is None and getattr(t, 'sandbox', True) is False:     # 4.6 测验 / MES 课：没有沙箱，只交作答（MES 课可以带 pid：在哪座工厂的 MES 上做的）
            program = {'kind': t.kind, 'pid': body.get('pid')}
        if program is None:
            from ..server import SANDBOXES
            pid = pid_for(u['username'], aid)
            import os
            if pid not in mgr.sandboxes and not os.path.exists(os.path.join(SANDBOXES, f'{pid}.yaml')):
                raise HTTPException(400, _tr('还没进入沙箱做这个任务：先点"进入"，写好程序并下载到 PLC，再提交'))
            rt = await pool.ensure(u['username'], a, t)
            program = t.artifact(rt)
        if not program:
            raise HTTPException(400, _tr('沙箱里还没有程序：先写好程序并下载到 PLC，再提交'))
        answers = None
        if isinstance(t, LessonTask):
            if body.get('answers'):
                await answers_put(aid, request, {'answers': body['answers']})
            ar = db.q('select data from answers where assignment_id=? and username=?', (aid, u['username']), one=True)
            answers = db.jl(ar['data'], {}) if ar else {}
        row = await _score_and_record(a, t, u['username'], program, answers, late, trial=a['_teacher'])
        return with_reveal(sub_view(row, show=a['show_details'] or a['_teacher']), a, t, row)

    async def _factory_art(u, plant):
        """提交工厂：这个账号在本机的一座工厂 → {model, programs}（只有客户端有"我的工厂"）。"""
        from . import myplants
        if not plant:
            raise HTTPException(400, _tr('先选一座"我的工厂"再提交（工厂设计作业在客户端里做）'))
        if not getattr(mgr, 'desktop', None) and os.environ.get('VF_DESKTOP') != '1':
            raise HTTPException(400, _tr('工厂设计作业要在客户端里做：在客户端的"我的工厂"里建好工厂，再在这里选它提交'))
        rt = myplants.need_own(mgr, u, str(plant))
        model, programs, _ = myplants.collect(rt)
        return {'model': model, 'programs': programs}

    # ---------------- 作业包 ----------------
    def _pkg_answers(t, pkg):
        """包里的作答只留本课规则里有的题。"""
        if not isinstance(t, LessonTask):
            return None
        keys = {r['key'] for r in (t.lesson.get('rules') or []) if r.get('kind') == 'answer'}
        return {k: clean_answer(v) for k, v in (pkg.answers or {}).items() if k in keys and v is not None}

    async def _read_pkg(request):
        ct = (request.headers.get('content-type') or '').lower()
        raw = await request.body()
        if len(raw) > pk.MAX_BYTES * 2:
            raise HTTPException(413, _tr('作业包超过 {v} MB', v=pk.MAX_BYTES // 1024 // 1024))
        try:
            if 'json' in ct:
                data = pk.decode(json.loads(raw.decode('utf-8') or '{}'))
            else:
                data = raw
            return pk.read(data)
        except pk.PackageError as e:
            raise HTTPException(400, str(e))
        except ValueError:
            raise HTTPException(400, _tr('请求内容不是有效的 JSON'))

    async def _take_package(a, t, username, pkg, source, as_student):
        late = _submit_checks(a, username, as_student=as_student)
        try:
            pk.check_target(pkg, a, t)
            program = pk.artifact(pkg, t)
        except pk.PackageError as e:
            raise HTTPException(400, str(e))
        answers = _pkg_answers(t, pkg)
        if answers is not None and answers:
            cur = db.q('select data from answers where assignment_id=? and username=?', (a['id'], username), one=True)
            data = {**(db.jl(cur['data'], {}) if cur else {}), **answers}
            db.x('insert or replace into answers(assignment_id, username, data, updated) values(?,?,?,?)',
                 (a['id'], username, json.dumps(data, ensure_ascii=False), store.now()))
        from ..tenancy import saas as _saas
        if _saas():                                         # 5.0 SaaS：服务器不跑仿真，按客户端本机评的分记（复评挂钩见 tenancy/hooks.py）
            row = _record_client_score(a, t, username, program, answers, late, source, pkg)
        else:
            row = await _score_and_record(a, t, username, program, answers, late, trial=False, source=source, pkg_bytes=pkg.raw)
        try:
            from ..tenancy import progress
            progress.note_submission(username, a['id'], final(row))
        except Exception:                                   # noqa: BLE001  进度只是附带的，不影响交作业
            pass
        return row

    def _record_client_score(a, t, username, program, answers, late, source, pkg):
        """SaaS：作业包里的本机评分（local_score）就是成绩（老师可以复核改分）；details 里标 verified=false。没有本机分的：已收到，等老师评。"""
        from ..tenancy import hooks
        ls = pkg.manifest.get('local_score') if isinstance(pkg.manifest.get('local_score'), dict) else None
        sc = None
        if ls and ls.get('score') is not None:
            try:
                sc = round(max(0.0, min(100.0, float(ls['score']) / float(ls.get('max') or 100) * 100)), 1)
            except (TypeError, ValueError):
                sc = None
        st = 'scored' if sc is not None else 'submitted'
        keep = {'max': 100, 'details': (ls or {}).get('details') or [], 'raw_score': sc, 'verified': False, 'client_reported': True,
                'client_at': (ls or {}).get('at'), 'log': []}
        if answers is not None:
            keep['answers'] = answers
        sid = db.x('insert into submissions(assignment_id,username,created,status,program,late,trial,source,auto_score,details) values(?,?,?,?,?,?,?,?,?,?)',
                   (a['id'], username, store.now(), st, json.dumps(program, ensure_ascii=False, default=str), late, 0, source, sc,
                    json.dumps(keep, ensure_ascii=False, default=str)))
        d = _pkg_dir()
        os.makedirs(d, exist_ok=True)
        fn = f'{sid}{pk.EXT}'
        with open(os.path.join(d, fn), 'wb') as f:
            f.write(pkg.raw)
        db.x('update submissions set package=? where id=?', (fn, sid))
        row = db.q('select * from submissions where id=?', (sid,), one=True)
        r = hooks.rescore(row, pkg)                          # 5.0 没有注册复评函数：None
        if r:
            keep.update(details=r.get('details') or keep['details'], verified=bool(r.get('verified')), raw_score=r.get('score'))
            db.x('update submissions set auto_score=?, status=?, details=? where id=?',
                 (r.get('score'), 'scored', json.dumps(keep, ensure_ascii=False, default=str), sid))
            row = db.q('select * from submissions where id=?', (sid,), one=True)
        return row

    @app.post('/api/teach/assignments/{aid}/submit_package')
    async def submit_package(aid: int, request: Request):
        """学生交作业包：服务器拿包里的程序/模型/作答重新评分（不看包里的 local_score），截止和次数照常查。"""
        u = me(request)
        a = need_assignment(u, aid)
        if a['_teacher']:
            raise HTTPException(400, _tr('老师请用"导入作业包"替学生导入'))
        t = need_task(a)
        pkg = await _read_pkg(request)
        row = await _take_package(a, t, u['username'], pkg, 'client', as_student=True)
        out = with_reveal(sub_view(row, show=a['show_details']), a, t, row)       # 学校服务器重新评分：按老师的设置带上正确答案和解析
        out['local_score'] = (pkg.manifest.get('local_score') or {}).get('score')
        return out

    @app.post('/api/teach/assignments/{aid}/students/{username}/import_package')
    async def import_package(aid: int, username: str, request: Request):
        """老师替学生导入作业包（学生交不了网时），记为该生的一次提交（来源"导入"）。不受次数限制，逾期照样标记。"""
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        if username not in db.members(a['class_id']):
            raise HTTPException(400, _tr('{username} 不在这个班', username=username))
        t = need_task(a)
        pkg = await _read_pkg(request)
        who = (pkg.manifest.get('student') or {}).get('username')
        row = await _take_package(a, t, username, pkg, 'import', as_student=False)
        db.x('update submissions set comment=? where id=?', (_tr('老师 {username} 导入的作业包', username=u['username']) + (_tr('（包里写的学生是 {who}）', who=who) if who and who != username else ''),
                                                              row['id']))
        return sub_view(db.q('select * from submissions where id=?', (row['id'],), one=True), full=True)

    def _pkg_dir():
        import os
        return os.path.join(_data_dir(), 'teach', 'packages')

    def _pkg_meta(a, t, username, extra=None):
        names = {r['username']: r['name'] for r in store.q('select username,name from users where username=?', (username,))}
        return {'student': {'username': username, 'name': names.get(username) or username}, 'server': None, 'assignment_id': a['id'],
                'title': a.get('title'), 'course': a.get('course'), 'lesson': a.get('lesson'), 'scene': a.get('scene'), 'kind': t.kind, **(extra or {})}

    def _sandbox_package(a, t, username, rt):
        """把沙箱里的作业打包：PLC 程序（控制每个单元的 PLC 块最后下载的那份）/ 模型、作答、运行摘要、本机最高分。"""
        programs, model = {}, None
        if t.kind == 'cell':
            for cid, plc in scenes.program_targets(rt):      # 按单元编号存（和 4.2 的包兼容），程序取自控制它的 PLC 块
                p = scenes.get_program(rt, plc.id)
                if p:
                    programs[cid] = p
        else:
            model = t.artifact(rt)
        ans = db.q('select data from answers where assignment_id=? and username=?', (a['id'], username), one=True)
        best = db.q("select * from submissions where assignment_id=? and username=? and status in ('scored','reviewed') order by auto_score desc limit 1",
                    (a['id'], username), one=True)
        local = None
        if best:
            det = db.jl(best['details'], {}) or {}
            local = {'score': best['auto_score'], 'max': 100, 'details': det.get('details') or [], 'at': best['created']}
        runlog = {'sim_time': rt.plant.clock_str(), 'sim_seconds': round(rt.plant.t, 1), 'submissions_here': db.q(
            'select count(*) n from submissions where assignment_id=? and username=?', (a['id'], username), one=True)['n'],
            'events': [e.get('msg') for e in list(getattr(rt.plant, 'events', []) or [])[-20:] if isinstance(e, dict)]}
        return programs, model, (db.jl(ans['data'], {}) if ans else {}), runlog, local

    @app.get('/api/teach/assignments/{aid}/package')
    async def export_package(aid: int, request: Request, username: str = '', plant: str = ''):
        """导出作业包（.vfhw）：学生导出自己的；老师可 ?username= 导出某个学生的。客户端（桌面模式）里可以加 server/remote_aid 信息（见 client.py）。
        提交工厂作业：?plant=<我的工厂编号>（客户端里）。"""
        u = me(request)
        a = need_assignment(u, aid)
        who = username if (username and a['_teacher']) else u['username']
        data, meta = await _export_bytes(a, who, plant=plant, user=u)
        from urllib.parse import quote
        return Response(data, media_type='application/octet-stream',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(pk.filename(meta))}"})

    async def _export_bytes(a, who, plant='', user=None):
        aid = a['id']
        t = need_task(a)
        if t.kind == 'factory':
            return _factory_package(a, t, who, plant, user)
        if getattr(t, 'sandbox', True) is False:                 # 测验 / MES 课：包里只有作答
            ans = db.q('select data from answers where assignment_id=? and username=?', (aid, who), one=True)
            best = db.q("select * from submissions where assignment_id=? and username=? and status in ('scored','reviewed') order by auto_score desc limit 1",
                        (aid, who), one=True)
            local = None
            if best:
                det = db.jl(best['details'], {}) or {}
                local = {'score': best['auto_score'], 'max': 100, 'details': det.get('details') or [], 'at': best['created']}
            meta = _pkg_meta(a, t, who, {'local_score': local})
            hook = getattr(app.state, 'package_meta', None)
            if hook:
                meta = hook(a, meta)
            snap = None
            if t.kind == 'mes':                                    # MES 课：带上本机评分时取的 MES 快照（学校服务器按它复评）
                last = db.q("select program from submissions where assignment_id=? and username=? and status in ('scored','reviewed') order by id desc limit 1",
                            (aid, who), one=True)
                snap = (db.jl(last['program'], {}) or {}).get('mes_snapshot') if last else None
                if not isinstance(snap, dict):
                    snap = await asyncio.get_running_loop().run_in_executor(None, mes_snapshot, t.lesson, db.jl(ans['data'], {}) if ans else {}, None)
            try:
                return pk.build(meta, {}, None, db.jl(ans['data'], {}) if ans else {}, {'kind': t.kind}, mes_snapshot=snap), meta
            except pk.PackageError as e:
                raise HTTPException(400, str(e))
        rt = mgr.sandboxes.get(pid_for(who, aid))
        if rt is None:
            from ..server import SANDBOXES
            import os
            if not os.path.exists(os.path.join(SANDBOXES, f'{pid_for(who, aid)}.yaml')):
                raise HTTPException(400, _tr('还没进入沙箱做这个任务，没有可导出的作业'))
            rt = await pool.ensure(who, a, t)
        programs, model, answers, runlog, local = _sandbox_package(a, t, who, rt)
        if t.kind == 'cell' and not programs:
            raise HTTPException(400, _tr('沙箱里还没有程序：先写好程序并下载到 PLC，再导出'))
        meta = _pkg_meta(a, t, who, {'local_score': local})
        hook = getattr(app.state, 'package_meta', None)       # 客户端：换成学校服务器的作业号、地址
        if hook:
            meta = hook(a, meta)
        try:
            return pk.build(meta, programs, model, answers, runlog), meta
        except pk.PackageError as e:
            raise HTTPException(400, str(e))

    def _factory_package(a, t, who, plant, user=None):
        """提交工厂的作业包（版本 2）：选中的本机工厂的模型 + 每台 PLC 的程序。"""
        from . import myplants
        if not plant:
            raise HTTPException(400, _tr('先选一座"我的工厂"'))
        u = user or (store.q('select * from users where username=?', (who,), one=True) or {'username': who, 'role': 'student'})
        rt = myplants.need_own(mgr, u, str(plant))
        model, programs, info = myplants.collect(rt)
        best = db.q("select * from submissions where assignment_id=? and username=? and status in ('scored','reviewed') order by id desc limit 1",
                    (a['id'], who), one=True)
        local = None
        if best and best['auto_score'] is not None:
            det = db.jl(best['details'], {}) or {}
            local = {'score': best['auto_score'], 'max': 100, 'details': det.get('details') or [], 'at': best['created']}
        meta = _pkg_meta(a, t, who, {'local_score': local, 'plant': info})
        hook = getattr(app.state, 'package_meta', None)
        if hook:
            meta = hook(a, meta)
        runlog = {'plant': info.get('id'), 'sim_time': rt.plant.clock_str(),
                  'events': [e.get('msg') for e in list(rt.plant.events)[-20:] if isinstance(e, dict)]}
        try:
            return pk.build(meta, programs, model, None, runlog), meta
        except pk.PackageError as e:
            raise HTTPException(400, str(e))

    async def _build_for(aid, username, plant=None):
        """客户端交学校作业用：本机作业 aid 的作业包字节（提交工厂作业要给 plant = 我的工厂编号）。"""
        a = db.assignment(aid)
        if not a:
            raise HTTPException(404, _tr('没有这个作业'))
        return (await _export_bytes(a, username, plant=plant or ''))[0]
    app.state.teach_build_package = _build_for

    def _need_sub(u, sid):
        r = db.q('select * from submissions where id=?', (sid,), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这次提交'))
        a = need_assignment(u, r['assignment_id'], teacher=True)
        return r, a

    def _sub_package(r, a):
        """提交的作业包：客户端/导入的提交原样返回；沙箱提交用当时的程序快照现打包。"""
        import os
        if r.get('package'):
            f = os.path.join(_pkg_dir(), os.path.basename(r['package']))
            if os.path.exists(f):
                with open(f, 'rb') as fh:
                    return fh.read()
        t = need_task(a)
        prog = db.jl(r['program'])
        det = db.jl(r['details'], {}) or {}
        meta = _pkg_meta(a, t, r['username'], {'submission_id': r['id'], 'source': r.get('source') or 'sandbox',
                                               'local_score': {'score': r['auto_score'], 'max': 100, 'details': det.get('details') or []}})
        if t.kind == 'cell':
            return pk.build(meta, {'CELL1': prog}, None, det.get('answers') or {}, {'log': det.get('log')})
        if t.kind == 'factory':
            from . import factory
            prog = prog or {}
            meta['plant'] = factory.summary(prog.get('model') or {}, prog.get('programs'))
            return pk.build(meta, prog.get('programs') or {}, prog.get('model') or {}, None, {'log': det.get('log')})
        return pk.build(meta, None, prog, det.get('answers') or {}, {'log': det.get('log')})

    @app.get('/api/teach/submissions/{sid}/package')
    async def sub_package(sid: int, request: Request):
        u = need_teacher(request)
        r, a = _need_sub(u, sid)
        data = _sub_package(r, a)
        from urllib.parse import quote
        name = f"{r['username']}-{a.get('lesson') or a.get('scene') or 'task'}-{sid}{pk.EXT}"
        return Response(data, media_type='application/octet-stream', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.post('/api/teach/submissions/{sid}/open')
    async def sub_open(sid: int, request: Request, body: dict = Body(default={})):
        """老师打开一次提交来运行：复核沙箱 sb-review-<提交号>，装上当时的程序/模型；可以运行、按操作台，不能改。fresh=true 重建。"""
        u = need_teacher(request)
        r, a = _need_sub(u, sid)
        t = need_task(a)
        prog = db.jl(r['program'])
        if not prog:
            raise HTTPException(400, _tr('这次提交没有程序/模型快照'))
        title = _tr('复核 · {username} 第 {sid} 号提交 · {v}', username=r['username'], sid=sid, v=a.get('title') or t.name)
        if t.kind == 'cell':
            cfg, programs = t.plant_cfg(title), {'CELL1': prog}
        elif t.kind == 'factory':                  # 提交的工厂：模型 + 每台 PLC 的程序（按 PLC 块编号装）
            cfg, programs = copy.deepcopy(prog.get('model') or {}), copy.deepcopy(prog.get('programs') or {})
            cfg.setdefault('plant', {})['name'] = title[:40]
            cfg['plant'].pop('modbus_port', None)
        else:
            cfg, programs = copy.deepcopy(prog), None
            cfg.setdefault('plant', {})['name'] = title
        pid = f'{REVIEW_PREFIX}{int(sid)}'
        rt = await pool.ensure_review(pid, r['username'], a['id'], cfg, programs, fresh=bool((body or {}).get('fresh')))
        v = _sandbox_view(rt)
        v.update(readonly=False, review=True, submission=sid, username=r['username'], kind=t.kind)
        return v

    # ---------------- 教师控制台 ----------------
    jam_seen: dict = {}            # 沙箱 → 上次看到的卡件+碰撞+掉件数（新增了就算"卡住"）
    ACTIVE_S = 300                 # 学生 5 分钟内访问过自己的沙箱才算"进行中"

    def open_faults(aid, username, rt, t):
        """老师注入、还没排除的故障。沙箱里故障已经没了（学生或老师清掉、设备自己修好）就记为已排除并通知老师。"""
        rows = db.q('select * from fault_log where assignment_id=? and username=? and cleared_at is null', (aid, username))
        if not rows or rt is None:
            return rows
        try:
            t = t or need_task(db.assignment(aid))
            act = set(t.active_faults(rt))
        except Exception:
            return rows
        out = []
        for f in rows:
            if (f['comp'], f['kind']) in act:
                out.append(f)
                continue
            db.x('update fault_log set cleared_at=?, cleared_by=? where id=?', (store.now(), 'sandbox', f['id']))
            a = db.assignment(aid)
            notify(a, username, 'fault_cleared', _tr('{username} 的沙箱里「{label}」已经没有了（用时 {round} 分钟）', username=username, label=f['label'], round=round((time.time() - (f['at_ts'] or time.time())) / 60)))
        return out

    def notify(a, username, kind, msg):
        db.x('insert into notices(class_id, assignment_id, username, at, kind, msg) values(?,?,?,?,?,?)',
             (a['class_id'] if a else None, a['id'] if a else None, username, store.now(), kind, msg))

    def _takeover_info(pid):
        from . import takeovers
        t = takeovers.get(pid)
        return {'teacher': t['teacher'], 'name': t['name'], 'since': t['since']} if t else None

    def _student_row(a, username, names, best, subs_n):
        from . import student_seen
        pid = pid_for(username, a['id'])
        rt = mgr.sandboxes.get(pid)            # 只读，不唤醒
        row = {'username': username, 'name': names.get(username) or username, 'pid': pid, 'sandbox': pool.status(pid),
               'best': (best.get(username) or {}).get('score'), 'reviewed': (best.get(username) or {}).get('reviewed', False),
               'submissions': subs_n.get(username, 0), 'plc': None, 'stats': {}, 'alarm': '', 'last_access': None}
        cellish = not a.get('kind') or a.get('kind') == 'cell'
        if rt is not None:
            if cellish:
                row['plc'] = scenes.plc_state(rt)
                row['stats'] = scenes.stats(rt)
                c = scenes.cell(rt)
                row['alarm'] = (c.alarm if c else '') or ''
            else:
                k = rt.plant.kpi
                hrs = max(1e-6, rt.plant.t / 3600)
                row['stats'] = {'good': k['good'], 'good_per_h': round(k['good'] / hrs, 1), 'scrap': k['scrap']}
                row['alarm'] = next((st.alarm for st in rt.plant.stations.values() if st.alarm and st.state == 'Stopped'), '')
                from ..editor_api import load_draft
                row['edited'] = bool(load_draft(pid))
            row['last_access'] = datetime.fromtimestamp(rt.last_access).strftime('%H:%M:%S')
            row['sim_time'] = round(rt.plant.t)
        stt = row['stats'] or {}
        prev = jam_seen.get(pid)
        bad = (stt.get('jams') or 0) + (stt.get('collisions') or 0) + (stt.get('dropped') or 0)
        jam_seen[pid] = bad
        benign = (_tr('PLC 未运行'), _tr('没有 PLC 程序'), _tr('没有接 PLC（用信号线接一台 PLC）'), '')
        stuck = cellish and bool(row['alarm'] not in benign or row['plc'] == 'ERROR' or (prev is not None and bad > prev))
        seen = student_seen.get(pid)
        row['active'] = bool(seen and time.time() - seen < ACTIVE_S)
        row['seen'] = datetime.fromtimestamp(seen).strftime('%H:%M') if seen else None
        of = open_faults(a['id'], username, rt, None) if rt is not None else db.q(
            'select * from fault_log where assignment_id=? and username=? and cleared_at is null', (a['id'], username))
        row['faults'] = [{'label': f['label'], 'since_min': round((time.time() - (f.get('at_ts') or time.time())) / 60), 'attempts': f.get('attempts') or 0}
                         for f in of]
        if a.get('kind') == 'factory':           # 提交工厂：没有沙箱，按提交和老师评分算
            waiting = db.q("select count(*) n from submissions where assignment_id=? and username=? and status='submitted'",
                           (a['id'], username), one=True)['n']
            row['state'] = (_tr('已满分') if row['best'] is not None and row['best'] >= 99.5 else _tr('待评分') if waiting and not row['reviewed']
                            else _tr('已评分') if row['reviewed'] else _tr('已提交') if row['submissions'] else _tr('未开始'))
        elif row['faults']:
            row['state'] = _tr('故障中')
        elif row['best'] is not None and row['best'] >= 99.5:
            row['state'] = _tr('已满分')
        elif not row['active']:
            started = rt is not None or seen or db.q('select 1 from sandboxes where pid=?', (pid,), one=True)
            row['state'] = _tr('已提交') if row['submissions'] else (_tr('离开') if started else _tr('未开始'))
        elif rt is None:
            row['state'] = _tr('进行中')
        elif stuck:
            row['state'] = _tr('卡住')
        elif cellish and (row['plc'] in (None, 'NONE') or row['alarm'] in variants('没有 PLC 程序') or scenes.get_program(rt) is None):
            row['state'] = _tr('未下载程序')
        else:
            row['state'] = _tr('进行中')
        return row

    @app.get('/api/teach/assignments/{aid}/progress')
    async def progress(aid: int, request: Request, since: int = 0):
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        users = db.members(a['class_id'])
        names = {r['username']: r['name'] for r in store.q('select username,name from users')}
        best = best_scores(aid)
        subs_n = {r['username']: r['n'] for r in db.q('select username, count(*) n from submissions where assignment_id=? group by username', (aid,))}
        rows = [_student_row(a, x, names, best, subs_n) for x in users]
        from ..tenancy import saas as _saas
        if _saas():                                      # 5.0 SaaS：没有沙箱，按客户端上报的进度和在线情况
            from ..tenancy import progress as tprogress
            tprogress.overlay(aid, rows)
        cnt, cnt_code = {}, {}
        for r in rows:
            r['state_code'] = state_code(r['state'])      # i18n: the text is in the reader's language, the code is stable
            cnt[r['state']] = cnt.get(r['state'], 0) + 1
            cnt_code[r['state_code']] = cnt_code.get(r['state_code'], 0) + 1
        sc = [r['best'] for r in rows if r['best'] is not None]
        try:
            t = need_task(a)
            rk = [r.get('key') for r in (t.public(True).get('rules') or [])]
        except HTTPException:
            rk = []
        return {'assignment': a, 'rows': rows, 'counts': cnt, 'counts_code': cnt_code, 'avg': round(sum(sc) / len(sc), 1) if sc else None, 'pool': pool.info(),
                'rule_keys': rk, 'notices': db.q('select * from notices where assignment_id=? and id>? order by id', (aid, since))}

    async def _student_rt(request, aid, username, create=False):
        """老师操作学生沙箱：只用已经存在的沙箱（在内存里的不唤醒；存在文件但没加载的才加载），不替学生新建。"""
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        if username not in db.members(a['class_id']) and username != u['username']:
            raise HTTPException(404, _tr('这个学生不在班级里'))
        t = need_task(a)
        pid = pid_for(username, aid)
        rt = mgr.sandboxes.get(pid)
        if t.kind == 'factory':
            return u, a, t, None
        if rt is None:
            from ..server import SANDBOXES
            import os
            if not os.path.exists(os.path.join(SANDBOXES, f'{pid}.yaml')) and not create:
                return u, a, t, None
            rt = await pool.ensure(username, a, t)
        return u, a, t, rt

    @app.post('/api/teach/assignments/{aid}/students/{username}/faults')
    async def inject(aid: int, username: str, request: Request, body: dict = Body(...)):
        u, a, s, rt = await _student_rt(request, aid, username)
        if rt is None:
            raise HTTPException(400, _tr('学生还没开始这个任务（没有沙箱），不能注入故障'))
        rt.touch()
        comp, kind = body.get('comp'), body.get('kind')
        allowed = a['faults']
        if allowed and u['role'] != 'admin' and not any(f['kind'] == kind and (comp is None or f.get('comp') in (None, comp)) for f in allowed):
            raise HTTPException(400, _tr('这个故障不在本任务允许的故障清单里'))
        if not comp:
            m = next((f for f in (allowed or s.faults()) if f['kind'] == kind), None)
            comp = m and m.get('comp')
        err = s.inject(rt, comp, kind, body.get('bid'))
        if err:
            raise HTTPException(400, err)
        label = next((f.get('label') for f in (allowed or s.faults()) if f['kind'] == kind and f.get('comp') in (None, comp)), None) or scenes._fault_cn(comp, kind)
        db.x('insert into fault_log(assignment_id, username, pid, comp, kind, label, at, at_ts, by) values(?,?,?,?,?,?,?,?,?)',
             (aid, username, rt.pid, comp, kind, label, store.now(), time.time(), u['username']))
        return {'ok': True, 'pid': rt.pid, 'label': label}

    @app.delete('/api/teach/assignments/{aid}/students/{username}/faults')
    async def clear(aid: int, username: str, request: Request):
        u, a, s, rt = await _student_rt(request, aid, username)
        if rt is not None:
            s.clear(rt)
        db.x("update fault_log set cleared_at=?, cleared_by=? where assignment_id=? and username=? and cleared_at is null",
             (store.now(), u['username'], aid, username))
        return {'ok': True}

    @app.get('/api/teach/assignments/{aid}/students/{username}/watch')
    async def watch(aid: int, username: str, request: Request):
        u, a, s, rt = await _student_rt(request, aid, username)
        if s.kind == 'factory':
            return {'exists': False, 'readonly': True, 'kind': 'factory', 'pid': None,
                    'msg': _tr('工厂设计作业没有沙箱：学生在客户端的"我的工厂"里建，交上来以后在"提交与复核"里打开运行')}
        if rt is None:
            return {'exists': False, 'readonly': True, 'kind': s.kind, 'msg': _tr('学生还没开始这个任务（还没有沙箱）'), 'pid': pid_for(username, aid)}
        t = pool.trace(rt)
        ev = [e for e in list(rt.plant.events)[-30:]]
        if isinstance(s, LessonTask):
            ans = db.q('select data from answers where assignment_id=? and username=?', (aid, username), one=True)
            k = rt.plant.kpi
            return {**_sandbox_view(rt), 'readonly': True, 'kind': s.kind, 'io': {}, 'io_table': [], 'plc': None, 'events': ev, 'time': rt.plant.clock_str(),
                    'sim_t': round(rt.plant.t, 1), 'progress': s.live(rt, db.jl(ans['data'], {}) if ans else {}),
                    'stats': {'good': k['good'], 'scrap': k['scrap'], 'castings': k['castings']}, 'answers': db.jl(ans['data'], {}) if ans else {},
                    'program': None, 'model_blocks': len(s.artifact(rt).get('blocks') or [])}
        c = scenes.cell(rt)
        return {**_sandbox_view(rt), 'readonly': True, 'kind': 'cell', 'io': scenes.io_values(rt), 'io_table': scenes.io_of(s.scene), 'plc': scenes.plc_state(rt),
                'stats': scenes.stats(rt), 'alarm': (c.alarm if c else '') or '', 'events': ev, 'trace': list(t.rows)[-40:],
                'program': scenes.get_program(rt), 'time': rt.plant.clock_str(), 'sim_t': round(rt.plant.t, 1)}

    @app.post('/api/teach/assignments/{aid}/students/{username}/takeover')
    async def takeover(aid: int, username: str, request: Request, body: dict = Body(default={})):
        """接管：老师对学生沙箱的写操作放行（编辑程序、下载、运行），学生端显示"某老师正在接管"。on=false 结束接管。"""
        from . import takeovers
        u, a, s, rt = await _student_rt(request, aid, username)
        pid = pid_for(username, aid)
        if (body or {}).get('on', True):
            if rt is None:
                raise HTTPException(400, _tr('学生还没开始这个任务（没有沙箱）'))
            takeovers[pid] = {'teacher': u['username'], 'name': u['name'] or u['username'], 'since': store.now()[11:16]}
            notify(a, username, 'takeover', _tr('{v} 接管了 {username} 的沙箱', v=u['name'] or u['username'], username=username))
        else:
            takeovers.pop(pid, None)
        return {'ok': True, 'takeover': _takeover_info(pid)}

    @app.post('/api/teach/assignments/{aid}/diagnose')
    async def diagnose(aid: int, request: Request, body: dict = Body(...)):
        """学生排故：报告"哪个部件、什么故障"。对了就排除这个故障并通知老师；错了记一次尝试。"""
        u = me(request)
        a = need_assignment(u, aid)
        t = need_task(a)
        rt = mgr.sandboxes.get(pid_for(u['username'], aid))
        if rt is None:
            raise HTTPException(400, _tr('先进入沙箱'))
        comp, kind = body.get('comp'), body.get('kind')
        rows = open_faults(aid, u['username'], rt, t)
        if not rows:
            return {'ok': False, 'msg': _tr('现在没有老师注入的故障。')}
        hit = next((f for f in rows if f['comp'] == comp and f['kind'] == kind), None)
        if not hit:
            for f in rows:
                db.x('update fault_log set attempts=coalesce(attempts,0)+1 where id=?', (f['id'],))
            near = any(f['comp'] == comp for f in rows)
            return {'ok': False, 'msg': _tr('部件找对了，但故障类型不对，再想想现象。') if near else _tr('不是这里。再观察一下：哪个信号或动作和正常时不一样？')}
        t.clear_one(rt, comp, kind)
        mins = round((time.time() - (hit['at_ts'] or time.time())) / 60, 1)
        db.x('update fault_log set cleared_at=?, cleared_by=? where id=?', (store.now(), u['username'], hit['id']))
        notify(a, u['username'], 'fault_fixed', _tr('{username} 找到并排除了「{label}」，用时 {mins} 分钟，尝试 {v} 次', username=u['username'], label=hit['label'], mins=mins, v=(hit['attempts'] or 0) + 1))
        return {'ok': True, 'msg': _tr('找对了：{label}。故障已排除，老师会收到通知。', label=hit['label']), 'left': len(rows) - 1}

    @app.get('/api/teach/assignments/{aid}/analytics')
    async def analytics(aid: int, request: Request):
        """班级学情：每个评分项的全班得分率（按每人最好的一次提交），最常见的失分项。"""
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        best = best_scores(aid)
        members = set(db.members(a['class_id']))
        per = {}
        texts = {}
        n = 0
        for user, b in best.items():
            if user not in members:
                continue
            r = db.q('select details from submissions where id=?', (b['id'],), one=True)
            det = (db.jl(r['details'], {}) or {}).get('details') or []
            n += 1
            for d in det:
                k = d.get('key') or d.get('label')
                x = per.setdefault(k, {'key': k, 'label': d.get('label') or k, 'weight': d.get('weight'), 'pass': 0, 'n': 0})
                x['n'] += 1
                if d.get('ok') or d.get('pass'):
                    x['pass'] += 1
                else:
                    texts.setdefault(k, []).append(d.get('text') or '')
        rows = sorted(per.values(), key=lambda x: x['pass'] / max(1, x['n']))
        for x in rows:
            x['rate'] = round(x['pass'] / max(1, x['n']), 3)
            x['examples'] = texts.get(x['key'], [])[:3]
        sc = [b['score'] for user, b in best.items() if user in members]
        dist = {'0-59': sum(1 for x in sc if x < 60), '60-79': sum(1 for x in sc if 60 <= x < 80), '80-99': sum(1 for x in sc if 80 <= x < 99.5),
                '100': sum(1 for x in sc if x >= 99.5)}
        return {'students': len(members), 'submitted': n, 'rules': rows, 'dist': dist,
                'notsubmitted': sorted(members - set(best))}

    @app.get('/api/teach/notices')
    async def notices(request: Request, since: int = 0):
        """老师的通知（学生排除故障、接管等），只返回自己班级的。"""
        u = need_teacher(request)
        if u['role'] in ('admin', 'orgadmin'):
            return db.q('select n.* from notices n join classes c on c.id=n.class_id where c.org=? and n.id>? order by n.id desc limit 50',
                        (org_of(u), since))
        return db.q('select n.* from notices n join classes c on c.id=n.class_id where c.teacher=? and n.id>? order by n.id desc limit 50',
                    (u['username'], since))

    @app.get('/api/teach/assignments/{aid}/submissions')
    async def submissions(aid: int, request: Request, username: str = ''):
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        if username:
            rows = db.q('select * from submissions where assignment_id=? and username=? order by id desc', (aid, username))
            t = need_task(a)                             # 老师看一个学生的提交：每道题学生答了什么、正确答案、解析
            return [with_reveal(sub_view(r, full=True), a, t, r) for r in rows]
        rows = db.q('select * from submissions where assignment_id=? order by id desc limit 500', (aid,))
        return [sub_view(r, full=bool(username)) for r in rows]

    @app.get('/api/teach/submissions/{sub}')
    async def submission(sub: int, request: Request):
        u = me(request)
        r = db.q('select * from submissions where id=?', (sub,), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这次提交'))
        a = need_assignment(u, r['assignment_id'])
        if not a['_teacher'] and r['username'] != u['username']:
            raise HTTPException(403, _tr('不能看别人的提交'))
        return sub_view(r, full=True)

    @app.post('/api/teach/submissions/{sub}/review')
    async def review(sub: int, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        r = db.q('select * from submissions where id=?', (sub,), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这次提交'))
        need_assignment(u, r['assignment_id'], teacher=True)
        ov = body.get('score', r['override_score']) if 'score' in body else r['override_score']
        if ov is not None:
            try:
                ov = float(ov)
            except (TypeError, ValueError):
                raise HTTPException(400, _tr('分数要是数字'))
            if not 0 <= ov <= 100:
                raise HTTPException(400, _tr('分数在 0–100 之间'))
        status = 'reviewed' if (ov is not None or body.get('comment')) else ('scored' if r['auto_score'] is not None else r['status'])
        if r['status'] == 'error' and ov is None:
            status = 'error'
        rc = db.jl(r.get('rule_comments'), {}) or {}
        for k, v in (body.get('rule_comments') or {}).items():
            if v:
                rc[k] = str(v)[:500]
            else:
                rc.pop(k, None)
        if rc and status not in ('reviewed', 'error'):
            status = 'reviewed'
        db.x('update submissions set override_score=?, comment=?, reviewed_by=?, reviewed_at=?, status=?, rule_comments=? where id=?',
             (ov, (body.get('comment') if 'comment' in body else r['comment']) or '', u['username'], store.now(), status,
              json.dumps(rc, ensure_ascii=False), sub))
        return sub_view(db.q('select * from submissions where id=?', (sub,), one=True))

    # ---------------- 成绩册 ----------------
    def gradebook(cid):
        asg = [db.assignment(r['id']) for r in db.q('select id from assignments where class_id=? order by id', (cid,))]
        names = {r['username']: r['name'] for r in store.q('select username,name from users')}
        bests = {a['id']: best_scores(a['id']) for a in asg}
        head = [_tr('账号'), _tr('姓名')] + [a['title'] for a in asg] + [_tr('平均分')]
        rows = []
        for m in db.members(cid):
            sc = [_n((bests[a['id']].get(m) or {}).get('score')) for a in asg]
            got = [x for x in sc if x is not None]
            rows.append([m, names.get(m) or m] + sc + [_n(round(sum(got) / len(asg), 1)) if asg else None])
        return head, rows, asg

    def _n(v):
        """分数：整数就不带 .0"""
        return int(v) if isinstance(v, float) and v.is_integer() else v

    @app.get('/api/teach/classes/{cid}/gradebook')
    async def grade_json(cid: int, request: Request):
        u = need_teacher(request)
        need_class(u, cid)
        head, rows, asg = gradebook(cid)
        return {'head': head, 'rows': rows, 'assignments': [{'id': a['id'], 'title': a['title'], 'due': a['due'], 'course': a.get('course'), 'seq': a.get('seq')}
                                                           for a in asg]}

    @app.get('/api/teach/classes/{cid}/gradebook.csv')
    async def grade_csv(cid: int, request: Request):
        u = need_teacher(request)
        c = need_class(u, cid)
        head, rows, _ = gradebook(cid)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows([['' if v is None else v for v in r] for r in rows])
        return Response('﻿' + buf.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename=gradebook-{cid}.csv'})

    @app.get('/api/teach/classes/{cid}/gradebook.xlsx')
    async def grade_xlsx(cid: int, request: Request):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        u = need_teacher(request)
        c = need_class(u, cid)
        head, rows, asg = gradebook(cid)
        wb = Workbook()
        ws = wb.active
        ws.title = _tr('成绩册')
        ws.append([_tr('{name} 成绩册（导出于 {now}，每个任务取最高分，含老师改分）', name=c['name'], now=store.now())])
        ws.append(head)
        for cell in ws[2]:
            cell.font, cell.fill = Font(bold=True), PatternFill('solid', fgColor='DDEBF7')
        for r in rows:
            ws.append(r)
        ws.column_dimensions['A'].width, ws.column_dimensions['B'].width = 16, 12
        ws.freeze_panes = 'C3'
        ws2 = wb.create_sheet(_tr('提交明细'))
        ws2.append([_tr('任务'), _tr('账号'), _tr('姓名'), _tr('提交时间'), _tr('自动分'), _tr('老师改分'), _tr('最终分'), _tr('状态'), _tr('逾期'), _tr('评分明细'), _tr('评语'), _tr('分项评语')])
        mem = set(db.members(cid))
        names = {r['username']: r['name'] for r in store.q('select username,name from users')}
        for a in asg:
            for r in db.q('select * from submissions where assignment_id=? order by username, id', (a['id'],)):
                if r['username'] not in mem:
                    continue
                det = (db.jl(r['details'], {}) or {}).get('details') or []
                detail = _tr('；').join(f"{d.get('label') or d.get('key')} {_n(d.get('score') or 0)}/{_n(d.get('weight') or 0)}" for d in det)
                rc = _tr('；').join(_tr('{k}：{v}', k=k, v=v) for k, v in (db.jl(r.get('rule_comments'), {}) or {}).items())
                ws2.append([a['title'], r['username'], names.get(r['username']) or r['username'], r['created'], _n(r['auto_score']), _n(r['override_score']),
                            _n(final(r)), {'scored': _tr('已评分'), 'reviewed': _tr('已复核'), 'error': _tr('评分失败'), 'scoring': _tr('评分中')}.get(r['status'], r['status']),
                            _tr('是') if r['late'] else '', detail, r['comment'] or '', rc])
        for col, w in zip('ABCDEFGHIJKL', (18, 12, 10, 18, 8, 8, 8, 8, 6, 60, 30, 40)):
            ws2.column_dimensions[col].width = w
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename=gradebook-{cid}.xlsx'})

    @app.get('/api/teach/sandboxes')
    async def sandboxes(request: Request):
        need_teacher(request)
        return pool.info()

    @app.get('/api/teach/me')
    async def teach_me(request: Request):
        u = me(request)
        r = db.q('select hash from pw_reset where username=?', (u['username'],), one=True)
        cur = store.q('select pw from users where username=?', (u['username'],), one=True)
        must = bool(r and cur and r['hash'] == cur['pw'])
        return {'username': u['username'], 'name': u['name'], 'role': u['role'], 'is_teacher': u['role'] in ('teacher', 'admin', 'orgadmin'),
                'safe': user_part(u['username']), 'must_change_password': must}

    app.state.teach_drop = _drop_assignment
