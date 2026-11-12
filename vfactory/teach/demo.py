"""演示教学数据：演示老师 + 演示班 + 6 个学生 + 已发布的课程。

不会自动出现在工厂/MES 客户那里，只有两种方式创建：
  1. 环境变量 VF_DEMO=1 启动服务：首次启动时建好（演示老师 demo_teacher / teach123，学生 demo_s01…demo_s06 / 123456）。
  2. 教学控制台里的"创建演示班级"按钮：POST /api/teach/demo（建在当前老师名下）。
命令行：python -m vfactory.teach.demo   （同 VF_DEMO=1 的效果）
"""
from ..i18n import _tr
import os

from fastapi import HTTPException, Request

from .. import courses, store
from . import db

STUDENTS = [('demo_s01', '张伟'), ('demo_s02', '李娜'), ('demo_s03', '王强'), ('demo_s04', '刘洋'), ('demo_s05', '陈静'), ('demo_s06', '杨帆')]
COURSES = ['machining', 'plc_basics']


def _publish(class_id, cid, teacher):
    import json
    from . import scenes
    c = courses.get_course(cid)
    if not c or db.q('select 1 from course_pubs where class_id=? and course=?', (class_id, cid), one=True):
        return 0
    n = 0
    for seq, (ch, l) in enumerate(courses.lessons(c), 1):
        kind = l.get('kind', 'plant')
        faults = scenes.faults_of(scenes.load_scene(l['scene']) or {}) if kind == 'cell' else []
        db.x('insert into assignments(class_id,scene,title,descr,due,faults,start_faults,hints,tutor,status,teacher,created,updated,course,lesson,kind,seq) '
             'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
             (class_id, l.get('scene'), l['title'][:80], '', None, json.dumps(faults, ensure_ascii=False), '[]', 1, 1, 'published', teacher,
              store.now(), store.now(), cid, l['id'], kind, seq))
        n += 1
    db.x('insert or ignore into course_pubs(class_id, course, open_all, teacher, created) values(?,?,?,?,?)', (class_id, cid, 0, teacher, store.now()))
    return n


def seed(teacher='demo_teacher', class_name='演示班（虚拟工厂实训）', students=STUDENTS, course_ids=COURSES):
    """建演示班（已存在则补齐）。返回 {class_id, students, lessons}。"""
    if teacher == 'demo_teacher' and not store.q('select 1 from users where username=?', (teacher,), one=True):
        store.x('insert into users(username,name,role,pw,created) values(?,?,?,?,?)', (teacher, _tr('演示老师'), 'teacher', store.hash_pw('teach123'), store.now()))
    c = db.q('select id from classes where name=? and teacher=?', (class_name, teacher), one=True)
    cid = c['id'] if c else db.x('insert into classes(name,teacher,descr,created) values(?,?,?,?)',
                                     (class_name, teacher, _tr('演示数据：学生账号 demo_s01…demo_s06，密码 123456'), store.now()))
    for u, name in students:
        ex = store.q('select role from users where username=?', (u,), one=True)
        if ex is None:
            store.x('insert into users(username,name,role,pw,created) values(?,?,?,?,?)', (u, name, 'student', store.hash_pw('123456'), store.now()))
        elif ex['role'] != 'student':
            continue
        if not db.q('select 1 from class_members where class_id=? and username=?', (cid, u), one=True):
            db.x('insert into class_members(class_id,username,created) values(?,?,?)', (cid, u, store.now()))
    n = sum(_publish(cid, x, teacher) for x in course_ids)
    return {'class_id': cid, 'class_name': class_name, 'students': [u for u, _ in students], 'lessons': n, 'password': '123456'}


def register(app, mgr):
    if os.environ.get('VF_DEMO') == '1':
        try:
            seed()
        except Exception:
            import logging
            logging.getLogger('vfactory.teach').exception(_tr('演示教学数据创建失败'))

    @app.post('/api/teach/demo')
    async def demo(request: Request):
        u = request.state.user
        if u['role'] not in ('teacher', 'admin'):
            raise HTTPException(403, _tr('只有老师和管理员可以创建演示班级'))
        return seed(teacher=u['username'], class_name=_tr('演示班（{v}）', v=u['name'] or u['username']))


if __name__ == '__main__':
    import json
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(seed(), ensure_ascii=False))
