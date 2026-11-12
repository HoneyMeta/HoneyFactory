"""教学模块：班级与名单、实训任务、学生沙箱、自动评分与复核、教师控制台、成绩册。

接口都在 /api/teach/ 下（见 api.py）；AI 助教在 vfactory/tutor.py（/api/tutor/ask）。

角色（store.ROLES）：
  teacher  教师：看所有工厂（只读）；管理自己的班级、发布任务、复核评分；进入本班学生的沙箱（旁观、注入故障、远程协助）
  student  学生：只能进自己的沙箱（/api/p/sb-<账号>-<任务号>/...），以及 /api/teach、/api/tutor
  admin    管理员：教学功能全部可用
  engineer / viewer：不能进学生沙箱，其余不变
"""
from ..i18n import _tr
import re
import time
from urllib.parse import unquote

from . import db

WRITE = ('POST', 'PUT', 'PATCH', 'DELETE')
_PID = re.compile(r'^/api/p/([^/]+)')
# 学生不能看的只读接口：场景库原始数据含参考答案；大模型助手会直接给答案（学生用 AI 助教）
STUDENT_DENY = ('/api/scenes', '/api/admin', '/api/assistant', '/api/copilot', '/api/tokens', '/api/plants')
TEACH_PATHS = ('/api/teach/', '/api/tutor')
# 4.6：任何人都能用的纯计算接口（属性面板里填表达式时的试算；不读写工厂）。学生在课里改来料间隔等表达式参数要先过它
OPEN_POST = ('/api/expr/check', '/api/me/password')
# 5.0：任何角色都能写的"自己的"接口：退出登录/会话（/api/me/…）、客户端上报进度、AI 代理（按单位计量）
SELF_WRITE = ('/api/me/', '/api/progress/', '/api/ai/proxy/')
# 5.0：单位管理员（orgadmin）还能写的：单位管理、账号
ORG_WRITE = ('/api/org', '/api/admin/users')
_owner_cache: dict = {}
_kind_cache: dict = {}
# 学生本人最近一次访问自己沙箱的时间（老师查看、旁观不算），教师控制台的"进行中"按这个判断
student_seen: dict = {}
# 老师"接管"：沙箱 → {teacher, name, since}；接管期间老师对该沙箱的写操作才放行，学生端会看到提示
takeovers: dict = {}
# 控制单元课（PLC 课）里学生不能改的东西：保存/应用模型、增删设备、单元结构（只能改 PLC 程序、按面板、强制 I/O）。
# 草稿保存（PUT model）和暂停中的参数热更新（model/hot）放行：外壳点"运行"前总会先存一次草稿，拦了就运行不了；
# 草稿不进运行中的工厂，结构改动要 model/apply 才生效（这里拦），评分也只用场景定义 + 学生的 PLC 程序，改模型拿不到分。
_MODEL_WRITE = re.compile(r'^/api/p/[^/]+/(model/(apply|ops)|station(/[^/]+)?|plant|cells/[^/]+)$')
_MODEL_WRITE_OK = re.compile(r'^/api/p/[^/]+/station/[^/]+/(write|fault|enable)$')
# 复核沙箱 sb-review-…（老师打开学生的一次提交来运行）：只能运行、按操作台、强制 I/O，不能改学生交的程序和模型
_REVIEW_DENY = re.compile(r'^/api/p/[^/]+/(cells/[^/]+/(program(/download|/import)?|plc/external)|hmi/.*)$')
REVIEW_PREFIX = 'sb-review-'


def sandbox_kind(pid):
    """沙箱所属作业的类型：cell（PLC 课）/ plant / diagnose。"""
    if pid in _kind_cache:
        return _kind_cache[pid]
    own = sandbox_owner(pid)
    k = None
    if own:
        r = db.q('select kind from assignments where id=?', (own[1],), one=True)
        k = (r and r['kind']) or 'cell'
        _kind_cache[pid] = k
    return k


def sandbox_owner(pid):
    """沙箱编号 → (学生账号, 任务号, 班级号)；不是登记过的沙箱返回 None。"""
    if pid in _owner_cache:
        return _owner_cache[pid]
    r = db.q('select s.username, s.assignment_id, a.class_id from sandboxes s left join assignments a on a.id=s.assignment_id where s.pid=?', (pid,), one=True)
    v = (r['username'], r['assignment_id'], r['class_id']) if r else None
    if v:
        _owner_cache[pid] = v
    return v


def forget(pid):
    _owner_cache.pop(pid, None)
    _kind_cache.pop(pid, None)
    _open_model.pop(pid, None)
    takeovers.pop(pid, None)


_open_model: dict = {}


def _model_unlocked(pid):
    """4.6：老师做的 PLC 课可以设 lock_model: false（学生也能改设备和控制单元）。"""
    if pid not in _open_model:
        own = sandbox_owner(pid)
        v = False
        if own:
            r = db.q('select course, lesson from assignments where id=?', (own[1],), one=True)
            if r and r['course']:
                from .. import courses
                _c, l = courses.get_lesson(r['course'], r['lesson'])
                v = bool(l) and l.get('lock_model') is False
        _open_model[pid] = v
    return _open_model[pid]


def _cell_lesson_block(pid, method, path):
    if method not in WRITE or sandbox_kind(pid) != 'cell':
        return None
    if _model_unlocked(pid):
        return None
    if _MODEL_WRITE_OK.match(path) or not _MODEL_WRITE.match(path):
        return None
    return _tr('这一课是 PLC 控制课：设备和控制单元的结构不能改，只能写 PLC 程序、按操作台、强制 I/O')


def guard(u, method, path):
    """HTTP 中间件和 WebSocket 调用：返回拒绝原因（字符串）或 None（放行）。不改变 admin/engineer/viewer 原有权限。"""
    role = u.get('role')
    m = _PID.match(path)
    pid = unquote(m.group(1)) if m else None
    if pid and pid.startswith(REVIEW_PREFIX):
        own = sandbox_owner(pid)
        if role == 'student' or not own:
            return _tr('复核沙箱只对任课老师开放')
        if not (role == 'admin' or own[0] == u['username'] or (own[2] is not None and db.teaches(u, own[2]))):
            return _tr('这不是你班上学生的作业')
        if method in WRITE and (_REVIEW_DENY.match(path) or (_MODEL_WRITE.match(path) and not _MODEL_WRITE_OK.match(path))):
            return _tr('复核沙箱只用来运行学生交的作业：可以运行、按操作台、强制 I/O，不能改程序和模型')
        return None
    if pid and pid.startswith('sb-'):
        if role == 'admin':
            return None
        own = sandbox_owner(pid)
        if own and own[0] == u['username'] and role not in ('student', 'teacher'):
            student_seen[pid] = time.time()            # 客户端（桌面模式）的本机账号：自己的练习沙箱
            return _cell_lesson_block(pid, method, path)
        if role == 'student':
            if not own or own[0] != u['username']:
                return _tr('只能进入自己的沙箱')
            student_seen[pid] = time.time()
            return _cell_lesson_block(pid, method, path)
        if role == 'teacher':
            if own and own[0] == u['username']:                    # 老师自己的试做沙箱
                return _cell_lesson_block(pid, method, path)
            if own and own[2] is not None and db.teaches(u, own[2]):
                if method in WRITE:
                    t = takeovers.get(pid)
                    if not t or t['teacher'] != u['username']:
                        return _tr('旁观是只读的：要修改学生的沙箱，请先在教学控制台点"接管"（学生会收到通知）')
                return None
            return _tr('这不是你班上学生的沙箱')
        return _tr('学生沙箱只对任课老师和学生本人开放')
    if role == 'student':
        if path.startswith(TEACH_PATHS) or path in OPEN_POST or path.startswith(SELF_WRITE):
            return None
        if pid:
            return _tr('学生账号只能进入自己的实训沙箱')
        if method in WRITE or path.startswith(STUDENT_DENY):
            return _tr('学生账号没有这个权限')
        return None
    if role in ('teacher', 'orgadmin') and method in WRITE:
        if path.startswith(TEACH_PATHS) or path in OPEN_POST or path.startswith(SELF_WRITE):
            return None
        if role == 'orgadmin' and path.startswith(ORG_WRITE):
            return None
        return (_tr('单位管理员') if role == 'orgadmin' else _tr('教师')) + _tr('账号不能修改工厂（可以管理班级、任务和学生沙箱）')
    return None


def register(app, mgr):
    from . import api, client, course_api, demo, myplants
    api.register(app, mgr)
    client.register(app, mgr)
    myplants.register(app, mgr)                  # 客户端"我的工厂"（4.4）
    from . import authoring, aigrade
    authoring.register(app, mgr)                 # 4.6 老师做课程、课程包（要在 course_api 之前：/api/teach/courses/pubkey）
    course_api.register(app, mgr, app.state.teach_drop)
    aigrade.register(app, mgr)                   # 4.6 AI 辅助评分
    demo.register(app, mgr)
    from . import coach
    coach.register(app, mgr)                     # 4.5 运行日志、实时检查表、诊断、演示
    from .. import tutor
    tutor.register(app, mgr)
