"""席位检查：自部署读授权文件，SaaS 读运维后台给单位设的席位——都从 limits() 出来，建账号的地方统一调 check_add()。

席位：teacher 占老师席位，student 占学生席位；单位管理员、管理员、工程师、访客不占。归档（archived）和停用的账号不占。
超了：不能再建（明确告诉还剩几个、怎么办）；已有账号照常能用。
自部署没装授权文件：默认不限席位（和 4.x 一样），页面上提示"未激活"；deploy.json 的 license_required=true（或 VF_LICENSE_REQUIRED=1）时
按试用额度（5 名老师、50 名学生）。授权到期：不能再新建账号（已有账号照常能用），提示续期。
"""
from ..i18n import _tr
from fastapi import HTTPException

from . import flag, license, orgs, saas
from .schema import DEFAULT_ORG

UNLIMITED = None


def limits(oid=None):
    """→ {org, name, source, teachers, students, expires, expired, features, ai_quota, status, licence?}。teachers/students 为 None 表示不限。"""
    oid = oid or DEFAULT_ORG
    o = orgs.get(oid) or {'id': oid, 'name': oid, 'status': 'active', 'features': dict(orgs.DEFAULT_FEATURES)}
    if saas():
        return {'org': oid, 'name': o['name'], 'source': 'console', 'teachers': o.get('seats_teachers'), 'students': o.get('seats_students'),
                'expires': o.get('expires'), 'expired': orgs.expired(o), 'features': o['features'], 'ai_quota': o.get('ai_quota'),
                'status': o.get('status'), 'trial': bool(o.get('trial'))}
    st = license.status()
    lic = {k: st.get(k) for k in ('installed', 'ok', 'error', 'expired', 'days_left')}
    p = st.get('payload') if st.get('ok') else None
    if p and not st.get('expired'):
        seats = p.get('seats') or {}
        return {'org': oid, 'name': p.get('org_name') or o['name'], 'source': 'licence', 'teachers': seats.get('teachers'), 'students': seats.get('students'),
                'expires': p.get('expires'), 'expired': False, 'features': {**orgs.DEFAULT_FEATURES, **(p.get('features') or {})},
                'ai_quota': p.get('ai_quota'), 'status': o.get('status'), 'licence': {**lic, 'id': p.get('license_id'), 'org_code': p.get('org_code')}}
    if p and st.get('expired'):
        # 到期：已有账号照常用，不能再新建（teachers/students = 现有人数）
        c = orgs.counts(oid)
        return {'org': oid, 'name': p.get('org_name') or o['name'], 'source': 'licence', 'teachers': c['teachers'], 'students': c['students'],
                'expires': p.get('expires'), 'expired': True, 'features': {**orgs.DEFAULT_FEATURES, **(p.get('features') or {})},
                'ai_quota': p.get('ai_quota'), 'status': o.get('status'), 'licence': {**lic, 'id': p.get('license_id')}}
    if flag('license_required'):
        return {'org': oid, 'name': o['name'], 'source': 'unlicensed', 'teachers': orgs.TRIAL['teachers'], 'students': orgs.TRIAL['students'],
                'expires': None, 'expired': False, 'features': dict(orgs.DEFAULT_FEATURES), 'ai_quota': None, 'status': o.get('status'), 'licence': lic}
    return {'org': oid, 'name': o['name'], 'source': 'unlicensed', 'teachers': UNLIMITED, 'students': UNLIMITED, 'expires': None, 'expired': False,
            'features': dict(orgs.DEFAULT_FEATURES), 'ai_quota': None, 'status': o.get('status'), 'licence': lic}


def summary(oid=None):
    lim = limits(oid)
    c = orgs.counts(lim['org'])
    lim['used'] = {'teachers': c['teachers'], 'students': c['students'], 'archived': c['archived'], 'orgadmins': c['orgadmins']}
    lim['left'] = {k: (None if lim[k] is None else max(0, lim[k] - c[k])) for k in ('teachers', 'students')}
    return lim


def check_add(oid, role, n=1):
    """要在单位 oid 里新建（或恢复）n 个 role 账号：超席位、单位到期/停用时抛 403（中文说明）。不占席位的角色直接放行。"""
    oid = oid or DEFAULT_ORG
    o = orgs.get(oid)
    if o and o['status'] != 'active':
        raise HTTPException(403, _tr('单位「{name}」{get}，不能新建账号', name=o['name'], get=orgs.STATUS.get(o['status'], o['status'])))
    lim = limits(oid)
    key = orgs.SEAT_ROLES.get(role)
    if not key or n <= 0:
        return
    who = _tr('老师') if key == 'teachers' else _tr('学生')
    if lim['expired']:
        raise HTTPException(403, _tr('单位的{v}已于 {expires} 到期：不能再新建{who}账号（已有账号照常能用）。', v=_tr('授权') if lim['source'] == 'licence' else _tr('服务'), expires=lim['expires'], who=who)
                                 + (_tr('请联系蜂元续期，导入新的授权文件。') if lim['source'] == 'licence' else _tr('请联系蜂元续期。')))
    cap = lim[key]
    if cap is None:
        return
    used = orgs.counts(oid)[key]
    if used + n > cap:
        left = max(0, cap - used)
        tip = _tr('可以先把结课/毕业的学生归档（单位管理 → 学生 → 归档）腾出席位，') if key == 'students' else _tr('可以先停用不再上课的老师账号，')
        more = _tr('或导入席位更多的授权文件。') if lim['source'] == 'licence' else (_tr('或导入授权文件。') if lim['source'] == 'unlicensed' else _tr('或联系蜂元增加席位。'))
        raise HTTPException(403, _tr('{who}席位不够：本单位最多 {cap} 名{who}，已有 {used} 名，还剩 {left} 个，这次要新建 {n} 个。{tip}{more}', who=who, cap=cap, used=used, left=left, n=n, tip=tip, more=more))


def feature(oid, name):
    f = limits(oid)['features']
    return f.get(name, True) if name != 'courses' else f.get('courses', 'all')


def course_allowed(oid, course_id):
    c = feature(oid, 'courses')
    return c in ('all', None, True) or (isinstance(c, list) and course_id in c)
