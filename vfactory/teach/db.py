"""教学数据表（和 store 同一个 SQLite 库，首次使用时建表）。

classes          班级：名称、任课老师、说明
class_members    班级学生名单
assignments      实训任务：来自场景库的一个场景，截止时间、允许注入的故障、开局故障、提示/AI 助教开关
sandboxes        学生沙箱登记：沙箱编号 sb-<账号>-<任务号> → 学生、任务
submissions      提交记录：自动评分（得分 + 每项明细）、程序快照、老师复核（改分 + 评语）
"""
import json
import threading

from .. import store

SCHEMA = """
create table if not exists classes(id integer primary key, org text default 'default', name text, teacher text, descr text, created text);
create table if not exists class_members(id integer primary key, class_id integer, username text, created text, unique(class_id, username));
create table if not exists assignments(id integer primary key, org text default 'default', class_id integer, scene text, title text, descr text,
  due text, faults text, start_faults text, hints integer default 1, tutor integer default 1, status text default 'published',
  teacher text, created text, updated text);
create table if not exists sandboxes(pid text primary key, username text, assignment_id integer, created text, last_access text);
create table if not exists submissions(id integer primary key, assignment_id integer, username text, created text, status text,
  auto_score real, score real, details text, program text, late integer default 0, override_score real, comment text,
  reviewed_by text, reviewed_at text);
create index if not exists ix_sub_a on submissions(assignment_id, username);
create table if not exists course_pubs(id integer primary key, class_id integer, course text, open_all integer default 0, teacher text, created text,
  unique(class_id, course));
create table if not exists answers(assignment_id integer, username text, data text, updated text, primary key(assignment_id, username));
create table if not exists pw_reset(username text primary key, hash text, at text, by text);
create table if not exists fault_log(id integer primary key, assignment_id integer, username text, pid text, comp text, kind text, label text, at text,
  at_ts real, by text, cleared_at text, cleared_by text, attempts integer default 0);
create table if not exists client_links(local_aid integer primary key, server text, remote_aid integer, remote_class text, remote_title text,
  remote_due text, fetched text);
create table if not exists notices(id integer primary key, class_id integer, assignment_id integer, username text, at text, kind text, msg text);
"""
# 课程化以后 assignments 多出的列（旧库自动补上）
COLUMNS = {'assignments': [('course', 'text'), ('lesson', 'text'), ('kind', 'text'), ('seq', 'integer'), ('start_at', 'text'), ('max_subs', 'integer'),
                           ('allow_late', 'integer default 1'), ('show_details', 'integer default 1'),
                           ('spec', 'text'),           # 4.4 提交工厂作业：要求（markdown）+ 自动检查项，JSON
                           ('reveal', "text default 'submit'")],   # 4.6.2 作答题的正确答案和解析：submit 提交后显示 / due 截止后显示 / never 不显示
           'submissions': [('rule_comments', 'text'), ('trial', 'integer default 0'), ('source', "text default 'sandbox'"), ('package', 'text')]}
REVEAL = ('submit', 'due', 'never')       # 作答题的正确答案什么时候给学生看
_ready = False
_lock = threading.Lock()


def ready():
    global _ready
    if not _ready:
        with _lock:
            if not _ready:
                c = store.conn()
                with store._lock:
                    c.executescript(SCHEMA)
                    for t, cols in COLUMNS.items():
                        have = {r[1] for r in c.execute(f'pragma table_info({t})').fetchall()}
                        for name, typ in cols:
                            if name not in have:
                                c.execute(f'alter table {t} add column {name} {typ}')
                    from ..tenancy import schema as tschema       # 5.0：没有单位的班级、作业归"默认单位"
                    tschema.migrate_orgs(c)
                    c.commit()
                _ready = True


def q(sql, args=(), one=False):
    ready()
    return store.q(sql, args, one)


def x(sql, args=()):
    ready()
    return store.x(sql, args)


def jl(s, default=None):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def assignment(aid):
    a = q('select * from assignments where id=?', (aid,), one=True)
    if a:
        a['faults'] = jl(a['faults'], [])
        a['start_faults'] = jl(a['start_faults'], [])
        a['hints'], a['tutor'] = bool(a['hints']), bool(a['tutor'])
        a['allow_late'] = a.get('allow_late') is None or bool(a['allow_late'])
        a['show_details'] = a.get('show_details') is None or bool(a['show_details'])
        a['spec'] = jl(a.get('spec'), None)
        a['reveal'] = a.get('reveal') if a.get('reveal') in REVEAL else 'submit'
    return a


def members(cid):
    return [r['username'] for r in q('select username from class_members where class_id=? order by username', (cid,))]


def classes_of_student(username):
    return [r['class_id'] for r in q('select class_id from class_members where username=?', (username,))]


def teaches(user, cid):
    """老师是否管这个班（管理员、单位管理员管本单位所有班；5.0 起按单位隔离）。"""
    c = q('select teacher, org from classes where id=?', (cid,), one=True)
    if not c:
        return False
    if user['role'] in ('admin', 'orgadmin'):
        return (c.get('org') or 'default') == (user.get('org') or 'default')
    return c['teacher'] == user['username']
