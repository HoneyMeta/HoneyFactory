"""单位（组织）：资料、状态、用户所属、用量统计、数据导出与删除。

单位状态：active 正常 / suspended 停用（全部账号不能登录，会话吊销）/ deleted 数据已删除（只留开户记录）。
到期（SaaS）：老师和学生不能登录，单位管理员还能登录（导出数据、联系续费）；不能再新建账号。
账号名全平台唯一（学生账号建议带单位前缀，例如 zzu.s2026001；导入名单时可以自动加）。
"""
from ..i18n import _tr
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta

from fastapi import HTTPException

from .. import store
from . import saas
from .schema import DEFAULT_ORG

ORG_ID_RE = re.compile(r'^[a-z][a-z0-9-]{1,30}$')
KINDS = {'school': '学校', 'enterprise': '企业'}
STATUS = {'active': '正常', 'suspended': '已停用', 'deleted': '数据已删除'}
FEATURES = {'courses': '课程包', 'plc': 'PLC 实训', 'ai': 'AI 助教/助手', 'client': '客户端'}
DEFAULT_FEATURES = {'courses': 'all', 'plc': True, 'ai': True, 'client': True}
TRIAL = {'teachers': 5, 'students': 50, 'days': 30, 'ai_quota': 200000}
SEAT_ROLES = {'teacher': 'teachers', 'student': 'students'}


def today():
    return datetime.now().strftime('%Y-%m-%d')


def get(oid):
    r = store.q('select * from orgs where id=?', (oid or DEFAULT_ORG,), one=True)
    if r:
        r['features'] = features_of(r)
    return r


def features_of(r):
    f = dict(DEFAULT_FEATURES)
    try:
        f.update(json.loads(r.get('features') or '{}') or {})
    except (ValueError, TypeError):
        pass
    return f


def clean_features(v):
    if not isinstance(v, dict):
        raise HTTPException(400, _tr('功能包格式不对'))
    out = {}
    for k in FEATURES:
        if k not in v:
            continue
        if k == 'courses':
            c = v[k]
            if c in ('all', None, ''):
                out[k] = 'all'
            elif isinstance(c, (list, tuple)):
                out[k] = [str(x) for x in c if str(x).strip()][:200]
            else:
                out[k] = [x.strip() for x in str(c).replace('，', ',').split(',') if x.strip()]
        else:
            out[k] = bool(v[k])
    return out


def expired(org):
    return bool(org and org.get('expires') and org['expires'] < today())


def org_view(r):
    if not r:
        return None
    d = {k: r.get(k) for k in ('id', 'name', 'kind', 'status', 'plan', 'contract_no', 'start_date', 'expires', 'seats_teachers', 'seats_students',
                               'ai_quota', 'trial', 'contact', 'notes', 'created', 'updated')}
    d['features'] = r['features'] if isinstance(r.get('features'), dict) else features_of(r)
    d['trial'] = bool(d['trial'])
    d['expired'] = expired(r)
    d['status_name'] = STATUS.get(r.get('status'), r.get('status'))
    return d


def login_block(u):
    """账号所属单位能不能登录：停用/删除都不能；SaaS 到期后只有单位管理员能登录。返回原因或空串。"""
    o = get(u.get('org'))
    if not o:
        return _tr('账号所属的单位不存在，请联系管理员')
    if o['status'] == 'suspended':
        return _tr('单位「{name}」已停用，请联系单位管理员或蜂元', name=o['name'])
    if o['status'] == 'deleted':
        return _tr('单位「{name}」的数据已删除', name=o['name'])
    if saas() and expired(o) and u.get('role') not in ('orgadmin', 'admin'):
        return _tr('单位「{name}」的服务已于 {expires} 到期，请联系单位管理员续期', name=o['name'], expires=o['expires'])
    return ''


def create(oid, name, kind='school', **kw):
    oid = (oid or '').strip().lower()
    if not ORG_ID_RE.match(oid):
        raise HTTPException(400, _tr('单位代码只能用小写字母、数字和短横线，字母开头，2～31 个字符（例：zzu、honey-tech）'))
    if get(oid):
        raise HTTPException(400, _tr('单位代码 {oid} 已经有了', oid=oid))
    name = (name or '').strip()[:60]
    if not name:
        raise HTTPException(400, _tr('请填写单位名称'))
    if kind not in KINDS:
        raise HTTPException(400, _tr('单位类型只能是 school（学校）或 enterprise（企业）'))
    now = store.now()
    feats = clean_features(kw.get('features') or {}) if kw.get('features') is not None else {}
    store.x('insert into orgs(id, name, kind, status, plan, contract_no, start_date, expires, seats_teachers, seats_students, features, ai_quota, trial, '
            'contact, notes, created, updated) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (oid, name, kind, 'active', kw.get('plan'), kw.get('contract_no'), kw.get('start_date') or today(), kw.get('expires'),
             _int_or_none(kw.get('seats_teachers')), _int_or_none(kw.get('seats_students')), json.dumps({**DEFAULT_FEATURES, **feats}, ensure_ascii=False),
             _int_or_none(kw.get('ai_quota')), 1 if kw.get('trial') else 0, kw.get('contact'), kw.get('notes'), now, now))
    return get(oid)


def _int_or_none(v):
    if v in (None, ''):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, _tr('需要整数：{v}', v=v))
    if n < 0:
        raise HTTPException(400, _tr('数量不能是负数'))
    return n


def _date_or_none(v):
    if v in (None, ''):
        return None
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise HTTPException(400, _tr('日期格式：YYYY-MM-DD（{v}）', v=v))


EDITABLE = ('name', 'kind', 'plan', 'contract_no', 'start_date', 'contact', 'notes')
SENSITIVE = ('seats_teachers', 'seats_students', 'expires', 'features', 'ai_quota', 'status')


def update(oid, body):
    o = get(oid)
    if not o:
        raise HTTPException(404, _tr('没有这个单位'))
    sets = []
    for k in EDITABLE + SENSITIVE:
        if k not in body:
            continue
        v = body[k]
        if k in ('seats_teachers', 'seats_students', 'ai_quota'):
            v = _int_or_none(v)
        elif k in ('expires', 'start_date'):
            v = _date_or_none(v)
        elif k == 'features':
            v = json.dumps({**o['features'], **clean_features(v)}, ensure_ascii=False)
        elif k == 'kind' and v not in KINDS:
            raise HTTPException(400, _tr('单位类型不对'))
        elif k == 'status' and v not in ('active', 'suspended'):
            raise HTTPException(400, _tr('状态只能是 active / suspended'))
        elif k == 'name':
            v = str(v or '').strip()[:60]
            if not v:
                raise HTTPException(400, _tr('单位名称不能为空'))
        else:
            v = None if v is None else str(v)[:500]
        sets.append((k, v))
    for k, v in sets:
        store.x(f'update orgs set {k}=?, updated=? where id=?', (v, store.now(), oid))
    if dict(sets).get('status') == 'suspended':
        revoke_org_sessions(oid)
    return get(oid)


def revoke_org_sessions(oid):
    for r in store.q('select username from users where org=?', (oid,)):
        store.revoke_sessions(username=r['username'])


def all_orgs():
    return [org_view(get(r['id'])) for r in store.q('select id from orgs order by created, id')]


# ---------------------------------------------------------------- 用量
def counts(oid):
    r = {k: 0 for k in ('teachers', 'students', 'orgadmins', 'archived', 'others')}
    for x in store.q('select role, archived, active, count(*) n from users where org=? group by role, archived, active', (oid,)):
        if x['archived']:
            r['archived'] += x['n']
            continue
        if not x['active']:
            continue
        k = SEAT_ROLES.get(x['role']) or ('orgadmins' if x['role'] in ('orgadmin', 'admin') else 'others')
        r[k] += x['n']
    return r


def usage(oid):
    from . import aiproxy
    from ..teach import db as tdb
    tdb.ready()
    c = counts(oid)
    since = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    month = datetime.now().strftime('%Y-%m')
    active = store.q('select count(*) n from users where org=? and archived=0 and last_login>=?', (oid, since), one=True)['n']
    subs = store.q('select count(*) n from submissions s join assignments a on a.id=s.assignment_id join classes c on c.id=a.class_id where c.org=?',
                   (oid,), one=True)['n']
    subs_m = store.q('select count(*) n from submissions s join assignments a on a.id=s.assignment_id join classes c on c.id=a.class_id '
                     'where c.org=? and s.created>=?', (oid, month + '-01'), one=True)['n']
    classes = store.q("select count(*) n from classes where org=? and coalesce(descr,'')!='__preview__'", (oid,), one=True)['n']
    ai = aiproxy.month_usage(oid)
    return {**c, 'active_30d': active, 'submissions': subs, 'submissions_month': subs_m, 'classes': classes,
            'ai_tokens_month': ai['tokens'], 'ai_calls_month': ai['calls'], 'ai_tokens_total': aiproxy.total_usage(oid), 'month': month}


# ---------------------------------------------------------------- 单位数据：导出、删除（个人信息保护：单位可以导出和删除全部数据）
def _org_classes(oid):
    from ..teach import db as tdb
    tdb.ready()
    return [r['id'] for r in store.q('select id from classes where org=?', (oid,))]


def _org_assignments(cids):
    if not cids:
        return []
    qs = ','.join('?' * len(cids))
    return [r['id'] for r in store.q(f'select id from assignments where class_id in ({qs})', tuple(cids))]


def _rows(sql, args=()):
    return store.q(sql, args)


def export_zip(oid):
    """单位的全部数据（不含密码散列）：单位资料、账号、班级与名单、作业、提交（含作业包文件）、作答、上报的进度、AI 用量、单位审计。"""
    from ..teach.api import _data_dir
    o = get(oid)
    if not o:
        raise HTTPException(404, _tr('没有这个单位'))
    cids = _org_classes(oid)
    aids = _org_assignments(cids)
    users = _rows('select id, username, name, role, active, archived, created, last_login from users where org=? order by id', (oid,))
    names = [u['username'] for u in users]
    qc = ','.join('?' * len(cids)) or "''"
    qa = ','.join('?' * len(aids)) or "''"
    qu = ','.join('?' * len(names)) or "''"
    data = {
        'org.json': org_view(o),
        'users.json': users,
        'classes.json': _rows(f'select * from classes where id in ({qc})', tuple(cids)),
        'class_members.json': _rows(f'select * from class_members where class_id in ({qc})', tuple(cids)),
        'assignments.json': _rows(f'select * from assignments where id in ({qa})', tuple(aids)),
        'submissions.json': _rows(f'select * from submissions where assignment_id in ({qa})', tuple(aids)),
        'answers.json': _rows(f'select * from answers where assignment_id in ({qa})', tuple(aids)),
        'course_pubs.json': _rows(f'select * from course_pubs where class_id in ({qc})', tuple(cids)),
        'progress_reports.json': _rows('select * from progress_reports where org=?', (oid,)),
        'ai_usage.json': _rows('select * from ai_usage where org=?', (oid,)),
        'tokens.json': _rows(f'select id, name, prefix, username, created, last_used, revoked, scope, expires from tokens where username in ({qu})', tuple(names)),
        'audit.json': _rows('select * from audit where org=? order by id', (oid,)),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', _tr('蜂元虚拟工厂 单位数据导出\n单位：{name}（{oid}）\n导出时间：{now}\n每个 .json 是一张表（UTF-8）；packages/ 是学生交的作业包（.vfhw）。账号不含密码。\n', name=o['name'], oid=oid, now=store.now()))
        for k, v in data.items():
            z.writestr(k, json.dumps(v, ensure_ascii=False, indent=1, default=str))
        pdir = os.path.join(_data_dir(), 'teach', 'packages')
        for s in data['submissions.json']:
            fn = s.get('package')
            if fn and os.path.basename(fn) == fn:
                p = os.path.join(pdir, fn)
                if os.path.isfile(p):
                    z.write(p, f'packages/{fn}')
    return buf.getvalue()


def delete_data(oid, keep_user=None):
    """删除单位的全部业务数据和账号（keep_user：自部署时保留正在操作的管理员）。SaaS 单位状态改成 deleted。返回删除的条数。"""
    from ..teach.api import _data_dir
    cids = _org_classes(oid)
    aids = _org_assignments(cids)
    qc = ','.join('?' * len(cids)) or "''"
    qa = ','.join('?' * len(aids)) or "''"
    n = {}
    pdir = os.path.join(_data_dir(), 'teach', 'packages')
    for s in store.q(f'select package from submissions where assignment_id in ({qa})', tuple(aids)):
        fn = s.get('package')
        if fn and os.path.basename(fn) == fn:
            try:
                os.remove(os.path.join(pdir, fn))
            except OSError:
                pass
    for t, sql, args in (('submissions', f'delete from submissions where assignment_id in ({qa})', tuple(aids)),
                         ('answers', f'delete from answers where assignment_id in ({qa})', tuple(aids)),
                         ('fault_log', f'delete from fault_log where assignment_id in ({qa})', tuple(aids)),
                         ('sandboxes', f'delete from sandboxes where assignment_id in ({qa})', tuple(aids)),
                         ('assignments', f'delete from assignments where id in ({qa})', tuple(aids)),
                         ('class_members', f'delete from class_members where class_id in ({qc})', tuple(cids)),
                         ('course_pubs', f'delete from course_pubs where class_id in ({qc})', tuple(cids)),
                         ('notices', f'delete from notices where class_id in ({qc})', tuple(cids)),
                         ('classes', f'delete from classes where id in ({qc})', tuple(cids)),
                         ('progress_reports', 'delete from progress_reports where org=?', (oid,)),
                         ('progress_log', 'delete from progress_log where org=?', (oid,)),
                         ('presence', 'delete from presence where org=?', (oid,))):
        before = store.q(sql.replace('delete from', 'select count(*) n from', 1), args, one=True)['n']
        store.x(sql, args)
        n[t] = before
    users = [r['username'] for r in store.q('select username from users where org=?', (oid,)) if r['username'] != keep_user]
    for u in users:
        store.revoke_sessions(username=u)
        store.x('update tokens set revoked=1 where username=?', (u,))
        store.x('delete from pw_reset where username=?', (u,))
        store.x('delete from users where username=?', (u,))
    n['users'] = len(users)
    if saas():
        store.x("update orgs set status='deleted', updated=? where id=?", (store.now(), oid))
    return n
