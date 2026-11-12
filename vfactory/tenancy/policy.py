"""每个请求的单位检查（server.py 的认证中间件在认出用户以后调用）。

1. 单位状态：停用/删除的单位一律拒绝；SaaS 到期后只有单位管理员能用（导出数据、续期）。
2. SaaS：服务器不跑工厂和仿真——工厂、沙箱、场景试运行、建模助手、全局设置这些接口一律拒绝（说明去客户端）。
   GET /api/plants、/api/overview 照常回应（空列表），网页和客户端的列表合并不用改。
3. SaaS：没有平台级的"管理员"——单位里的 admin 账号按单位管理员（orgadmin）对待，只能管本单位。
4. 课程包、PLC 功能包：发布课程到班级时检查本单位买了没有。
（每条数据属于哪个单位，由各接口自己检查：教学接口经 teach/db.teaches、need_class、need_assignment；账号、令牌、审计在 api2；
 tests/tenant_check.py 枚举全部接口证明不会串单位。）
"""
from ..i18n import _tr
import re

from . import orgs, saas

SAAS_MSG = 'SaaS 云服务不在服务器上运行工厂和仿真：请在蜂元虚拟工厂客户端里打开（工厂在你自己的电脑上运行）'
SAAS_BLOCK_PREFIX = ('/api/p/', '/api/templates', '/api/assistant', '/api/settings/', '/api/report/templates', '/api/admin/client-update',
                     '/api/teach/sandboxes', '/api/teach/demo', '/api/teach/authoring', '/api/scenes', '/api/copilot', '/api/cells/',
                     '/api/plants/', '/api/desktop/', '/api/client/', '/api/tutor')
SAAS_BLOCK_RE = (re.compile(r'^/api/teach/assignments/\d+/(sandbox(/reset)?|submit|live|diagnose|package)$'),
                 re.compile(r'^/api/teach/assignments/\d+/students/[^/]+/(faults|watch|takeover)$'),
                 re.compile(r'^/api/teach/submissions/\d+/open$'))
SAAS_WHY = {'/api/teach/authoring': '课程在客户端里做（出题检查、预览要在你的电脑上跑工厂）：打开蜂元虚拟工厂客户端 → 课程 → 新建课程 / 编辑，'
                                    '发布时自动传到云端',
            '/api/settings/': '全局设置只在自部署版里有（SaaS 由蜂元统一维护）',
            '/api/admin/client-update': '客户端更新由蜂元统一发布',
            '/api/report/templates': '报告模板只在自部署版里能改',
            '/api/tutor': 'SaaS 云服务的 AI 助教在客户端里用（看的是你电脑上的沙箱；大模型经服务器的 AI 代理，按单位计量）'}
PUBLISH_RE = re.compile(r'^/api/teach/courses/([^/]+)/publish$')
ROLE_ONLY_SAAS = ('orgadmin', 'teacher', 'student')


def effective(u, mgr=None):
    """SaaS 里单位账号的 admin 角色按 orgadmin 处理（没有跨单位的管理员；平台运维在 /ops，是另一套账号）。"""
    if u and saas() and not getattr(mgr, 'desktop', None) and u.get('role') == 'admin':
        u = dict(u, role='orgadmin', role_was='admin')
    return u


SAAS_AUTHORING_OK = (('GET', re.compile(r'^/api/teach/authoring$')), ('POST', re.compile(r'^/api/teach/authoring/upload$')),
                     ('GET', re.compile(r'^/api/teach/authoring/[^/]+/draft$')))


def saas_block(method, path):
    if path in ('/api/plants', '/api/overview') and method == 'GET':
        return None
    if any(m == method and r.match(path) for m, r in SAAS_AUTHORING_OK):      # 课程：列表、客户端传上来的课程包、取回草稿（不跑工厂）
        return None
    if path == '/api/plants':
        return SAAS_MSG
    for p in SAAS_BLOCK_PREFIX:
        if path.startswith(p) or path == p.rstrip('/'):
            return SAAS_WHY.get(p, SAAS_MSG)
    for r in SAAS_BLOCK_RE:
        if r.match(path):
            return SAAS_MSG
    return None


def check(u, method, path, mgr=None):
    """→ 拒绝原因（中文）或 None。客户端（桌面模式）本机的请求不管（本机只有一个人）。"""
    if getattr(mgr, 'desktop', None):
        return None
    why = orgs.login_block(u)
    if why:
        return why
    if not saas():
        return publish_check(u, method, path)
    if u.get('role') not in ROLE_ONLY_SAAS and not path.startswith(('/api/me', '/api/teach/me')):
        return _tr('SaaS 云服务里没有「{get}」这种账号（只有单位管理员、老师、学生），请联系单位管理员', get=u.get('role'))
    why = saas_block(method, path)
    if why:
        return why
    return publish_check(u, method, path)


def publish_check(u, method, path):
    """发布课程到班级：课程包、PLC 功能包。"""
    m = PUBLISH_RE.match(path) if method == 'POST' else None
    if not m:
        return None
    from . import seats
    from .. import courses
    oid = u.get('org')
    cid = m.group(1)
    if not seats.course_allowed(oid, cid):
        return _tr('本单位没有开通课程「{cid}」（课程包）：请联系蜂元开通', cid=cid)
    c = courses.get_course(cid)
    if c and not seats.feature(oid, 'plc') and any(l.get('kind', 'plant') == 'cell' for _ch, l in courses.lessons(c)):
        return _tr('本单位没有开通 PLC 实训功能包：这门课里有 PLC 编程课，不能发布')
    return None
