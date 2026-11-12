"""课程接口（/api/teach/courses/...）。

  GET   /api/teach/courses                                  课程目录（章、课）+ 已发布到我的哪些班
  GET   /api/teach/courses/{cid}                            课程详情（老师看：含任务书、规则、参考答案）
  POST  /api/teach/courses/{cid}/publish  {class_id, open_all?, due?, hints?, tutor?, reveal?}   发布到班级：按课生成作业（已发布过则只补缺的课）
        reveal（4.6.2）：作答题的正确答案和解析 submit 提交后显示（默认）/ due 截止后显示 / never 不显示；再次发布时带上会改这门课在这个班的全部作业
  PATCH /api/teach/courses/{cid}/classes/{class_id}  {open_all?, reveal?}              全部开放 / 按顺序解锁；正确答案的显示方式
  DELETE /api/teach/courses/{cid}/classes/{class_id}                                    撤销发布（删除这门课在该班的全部作业、沙箱和提交）
  GET   /api/teach/courses/{cid}/progress?class_id=          每个学生每一课的最高分和状态
学生的课程地图：GET /api/teach/my/courses（在 api.py）。
"""
from ..i18n import _tr
import json

from fastapi import Body, HTTPException, Request

from .. import courses, store
from . import db, scenes
from .api import _reveal_arg, lesson_state, need_class, need_teacher


def _due_of(v):
    """截止时间 'YYYY-MM-DD HH:MM'（日期选择器给的 'YYYY-MM-DDTHH:MM' 也认）；空 = 不限时。"""
    if not v:
        return None
    from datetime import datetime
    v = str(v).replace('T', ' ')[:16]
    try:
        datetime.strptime(v, '%Y-%m-%d %H:%M')
    except ValueError:
        raise HTTPException(400, _tr('截止时间格式：YYYY-MM-DD HH:MM'))
    return v


def publish_course(class_id, cid, teacher, body):
    """把课程发布到班级：按课生成作业（已发布过的课只更新顺序，缺的补上）。客户端的"本机自学"班也用它。"""
    c = courses.get_course(cid)
    have = {r['lesson']: r['id'] for r in db.q('select id, lesson from assignments where class_id=? and course=?', (class_id, cid))}
    reveal = _reveal_arg(body.get('reveal'))
    if 'reveal' in body and have:
        db.x('update assignments set reveal=? where class_id=? and course=?', (reveal, class_id, cid))
    created = 0
    for seq, (ch, l) in enumerate(courses.lessons(c), 1):
        if l['id'] in have:
            db.x('update assignments set seq=? where id=?', (seq, have[l['id']]))
            continue
        kind = l.get('kind', 'plant')
        faults = []
        if kind == 'cell':
            s = scenes.load_scene(l.get('scene'))
            if not s:
                continue
            faults = scenes.faults_of(s)
        db.x('insert into assignments(class_id,scene,title,descr,due,faults,start_faults,hints,tutor,status,teacher,created,updated,course,lesson,kind,seq,reveal) '
             'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
             (class_id, l.get('scene'), l['title'][:80], '', _due_of(body.get('due')), json.dumps(faults, ensure_ascii=False), '[]',
              1 if body.get('hints', True) else 0, 1 if body.get('tutor', True) else 0, 'published', teacher, store.now(), store.now(),
              cid, l['id'], kind, seq, reveal))
        created += 1
    db.x('insert or ignore into course_pubs(class_id, course, open_all, teacher, created) values(?,?,?,?,?)',
         (class_id, cid, 1 if body.get('open_all') else 0, teacher, store.now()))
    if 'open_all' in body:
        db.x('update course_pubs set open_all=? where class_id=? and course=?', (1 if body['open_all'] else 0, class_id, cid))
    return {'ok': True, 'created': created, 'lessons': len(courses.lessons(c))}


def course_org(c):
    """老师做的课属于做课老师的单位；内置课程、课程包不属于任何单位（None）。"""
    if not c or c.get('origin') != 'authored':
        return None
    return store.org_of(c.get('owner')) if c.get('owner') else 'default'


def need_course(u, cid):
    """5.0：别的单位老师做的课看不到（当作没有）。"""
    c = courses.get_course(cid)
    if not c:
        raise HTTPException(404, _tr('没有这门课程'))
    o = course_org(c)
    if o is not None and o != (u.get('org') or 'default'):
        raise HTTPException(404, _tr('没有这门课程'))
    return c


def register(app, mgr, drop_assignment):
    @app.get('/api/teach/courses')
    async def course_list(request: Request):
        u = need_teacher(request)
        org = u.get('org') or 'default'
        out = courses.list_courses(include=('builtin', 'authored'))
        from .authoring import _ready
        _ready()
        shared = {r['id'] for r in db.q('select id from authored_courses where shared=1')}
        out = [c for c in out if c['origin'] != 'authored' or (course_org(courses.get_course(c['id'])) == org and (
            u['role'] in ('admin', 'orgadmin') or c.get('owner') == u['username'] or c['id'] in shared))]
        mine = {c['id'] for c in (db.q('select id from classes where org=?', (org,)) if u['role'] in ('admin', 'orgadmin')
                                  else db.q('select id from classes where teacher=?', (u['username'],)))}
        pubs = db.q('select p.*, c.name class_name from course_pubs p join classes c on c.id=p.class_id')
        for c in out:
            c['classes'] = [{'class_id': p['class_id'], 'class_name': p['class_name'], 'open_all': bool(p['open_all']), 'created': p['created']}
                            for p in pubs if p['course'] == c['id'] and p['class_id'] in mine]
        return out

    @app.get('/api/teach/courses/{cid}')
    async def course_get(cid: str, request: Request):
        c = need_course(need_teacher(request), cid)
        for ch, l in courses.lessons(c):
            if l.get('kind') == 'cell':
                s = scenes.load_scene(l.get('scene'))
                if s:
                    s = scenes.overlay_scene(s, l)
                    l['brief_md'] = scenes.task_md(s)
                    l['rules'] = scenes.rules_of(s)
                    l['hints'] = scenes.hints_of(s)
        return c

    @app.post('/api/teach/courses/{cid}/publish')
    async def publish(cid: str, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        need_course(u, cid)
        class_id = int(body.get('class_id') or 0)
        need_class(u, class_id)
        return publish_course(class_id, cid, u['username'], body)

    @app.patch('/api/teach/courses/{cid}/classes/{class_id}')
    async def pub_patch(cid: str, class_id: int, request: Request, body: dict = Body(...)):
        u = need_teacher(request)
        need_class(u, class_id)
        if not db.q('select 1 from course_pubs where class_id=? and course=?', (class_id, cid), one=True):
            raise HTTPException(404, _tr('这门课程还没发布到这个班'))
        if 'open_all' in body:
            db.x('update course_pubs set open_all=? where class_id=? and course=?', (1 if body['open_all'] else 0, class_id, cid))
        if 'reveal' in body:
            db.x('update assignments set reveal=? where class_id=? and course=?', (_reveal_arg(body['reveal']), class_id, cid))
        return {'ok': True}

    @app.delete('/api/teach/courses/{cid}/classes/{class_id}')
    async def unpublish(cid: str, class_id: int, request: Request):
        u = need_teacher(request)
        need_class(u, class_id)
        for r in db.q('select id from assignments where class_id=? and course=?', (class_id, cid)):
            await drop_assignment(r['id'])
        db.x('delete from course_pubs where class_id=? and course=?', (class_id, cid))
        return {'ok': True}

    @app.get('/api/teach/courses/{cid}/progress')
    async def course_progress(cid: str, request: Request, class_id: int = 0):
        u = need_teacher(request)
        need_class(u, class_id)
        c = need_course(u, cid)
        asg = {r['lesson']: dict(r) for r in db.q('select * from assignments where class_id=? and course=? order by seq', (class_id, cid))}
        cols = []
        for ch, l in courses.lessons(c):
            a = asg.get(l['id'])
            if a:
                cols.append({'aid': a['id'], 'id': l['id'], 'title': l['title'], 'kind': l.get('kind', 'plant'), 'chapter': ch['title'],
                             'status': a['status']})
        names = {r['username']: r['name'] for r in store.q('select username,name from users where org=?', (u.get('org') or 'default',))}
        bc = {}
        rows = []
        for m in db.members(class_id):
            cells = []
            for col in cols:
                a = asg[col['id']]
                st = lesson_state(a, m, bc)
                cells.append({'aid': col['aid'], 'best': st['best'], 'state': st['state']})
            done = sum(1 for x in cells if x['state'] == 'done')
            rows.append({'username': m, 'name': names.get(m) or m, 'cells': cells, 'done': done,
                         'current': next((col['title'] for col, x in zip(cols, cells) if x['state'] == 'open'), None)})
        per = []
        for i, col in enumerate(cols):
            sc = [r['cells'][i]['best'] for r in rows if r['cells'][i]['best'] is not None]
            per.append({'aid': col['aid'], 'submitted': len(sc), 'avg': round(sum(sc) / len(sc), 1) if sc else None,
                        'done': sum(1 for r in rows if r['cells'][i]['state'] == 'done')})
        pub = db.q('select open_all from course_pubs where class_id=? and course=?', (class_id, cid), one=True)
        return {'course': {'id': cid, 'name': c['name']}, 'lessons': cols, 'rows': rows, 'per_lesson': per, 'open_all': bool(pub and pub['open_all'])}
