"""单位管理员（role = orgadmin；自部署的 admin 也能用）：本单位的老师、学生、席位、用量、数据导出与删除、授权文件（自部署）。

  GET  /api/org                              单位资料、席位（上限/已用/剩余）、用量、授权状态
  GET  /api/org/users?role=&archived=        本单位账号
  POST /api/org/teachers   {username, name, password?}           建老师（占老师席位；不给密码就生成临时密码，第一次登录要改）
  POST /api/org/students/import {csv|xlsx, class_id?, default_password?, prefix?, preview?}   批量导入学生（占学生席位，超了整批不导）
  POST /api/org/users/archive  {usernames? | class_id?}           归档（学期结束）：不能登录、不占席位，成绩和提交都留着
  POST /api/org/users/restore  {usernames}                        恢复归档的账号（要有空余席位）
  POST /api/org/users/{username}/active   {active}               停用 / 启用
  POST /api/org/users/{username}/reset_password                   重置为临时密码（吊销他的全部登录）
  GET  /api/org/usage
  POST /api/org/export   {password}                               本单位全部数据（zip）——个人信息保护：单位有权导出
  POST /api/org/delete   {confirm, password}                       删除本单位全部数据和账号（confirm = 单位名称）
  GET/POST/DELETE /api/org/license                                自部署：授权文件（上传即验签，离线激活）
"""
from ..i18n import _tr
import base64

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from .. import store
from . import license as lic
from . import orgs, saas, security, seats

ROLES_MANAGED = ('teacher', 'student')


def need_orgadmin(request):
    u = request.state.user
    if u.get('role') not in ('orgadmin', 'admin'):
        raise HTTPException(403, _tr('只有单位管理员可以操作'))
    return u, u.get('org') or 'default'


def _user_in_org(oid, username):
    r = store.q('select * from users where username=? and org=?', (username, oid), one=True)
    if not r:
        raise HTTPException(404, _tr('本单位没有账号 {username}', username=username))
    return r


def _check_pw(u, pw, username):
    security.check_password(pw, username)


def _mark_reset(username, by):
    from ..teach import db as tdb
    tdb.ready()
    r = store.q('select pw from users where username=?', (username,), one=True)
    if r:
        tdb.x('insert or replace into pw_reset(username, hash, at, by) values(?,?,?,?)', (username, r['pw'], store.now(), by))


def user_row(r):
    return {k: r.get(k) for k in ('username', 'name', 'role', 'active', 'archived', 'created', 'last_login')} | {
        'role_name': store.ROLES.get(r.get('role')), 'locked': security.is_locked(r)}


def register(app, mgr):
    if getattr(mgr, 'desktop', None):
        return
    from ..teach import api as tapi
    from ..teach import db as tdb

    @app.get('/api/org')
    async def org_info(request: Request):
        u, oid = need_orgadmin(request)
        o = orgs.get(oid)
        out = {'org': orgs.org_view(o), 'limits': seats.summary(oid), 'usage': orgs.usage(oid), 'mode': 'saas' if saas() else 'selfhost'}
        if not saas():
            st = lic.status()
            out['license'] = {k: st.get(k) for k in ('installed', 'ok', 'error', 'expired', 'days_left')} | {'payload': st.get('payload')}
        return out

    @app.get('/api/org/users')
    async def org_users(request: Request, role: str = '', archived: int = -1):
        _u, oid = need_orgadmin(request)
        sql, args = 'select * from users where org=?', [oid]
        if role:
            sql += ' and role=?'
            args.append(role)
        if archived in (0, 1):
            sql += ' and coalesce(archived,0)=?'
            args.append(archived)
        return {'users': [user_row(r) for r in store.q(sql + ' order by role, username', tuple(args))], 'roles': store.ROLES}

    @app.post('/api/org/teachers')
    async def teacher_new(request: Request, body: dict = Body(...)):
        u, oid = need_orgadmin(request)
        username = str(body.get('username') or '').strip()
        if not tapi.ACCOUNT_RE.match(username):
            raise HTTPException(400, _tr('账号只能用字母、数字、下划线、点和短横线（不能有空格和中文）'))
        if store.q('select 1 from users where username=?', (username,), one=True):
            raise HTTPException(400, _tr('账号 {username} 已经被用了', username=username) + (_tr('（账号全平台唯一，建议带单位前缀，例如 ') + oid + '.' + username + _tr('）') if saas() else ''))
        seats.check_add(oid, 'teacher', 1)
        pw = str(body.get('password') or '') or security.random_password(10)
        _check_pw(u, pw, username)
        store.x('insert into users(username, name, role, pw, created, org) values(?,?,?,?,?,?)',
                (username, (body.get('name') or username)[:40], 'teacher', store.hash_pw(pw), store.now(), oid))
        _mark_reset(username, u['username'])
        store.audit(u['username'], 'POST', '/api/org/teachers', 200, _tr('新建老师 {username}', username=username), org=oid)
        return {'ok': True, 'username': username, 'password': pw, 'limits': seats.summary(oid)}

    @app.post('/api/org/students/import')
    async def students_import(request: Request, body: dict = Body(...)):
        """批量导入学生：preview=true 只检查。新账号占学生席位，超了整批不导（提示还剩几个）。prefix=true 给账号加"单位代码."前缀。"""
        u, oid = need_orgadmin(request)
        cid = int(body.get('class_id') or 0)
        if cid:
            tapi.need_class(u, cid)
        rows = tapi.roster_rows(tapi.xlsx_rows(body['xlsx']) if body.get('xlsx') else tapi._text_rows(body.get('csv') or ''))
        if body.get('prefix'):
            for r in rows:
                name = str(r['username'] or '').strip()
                if name and not name.startswith(oid + '.'):
                    r['username'] = f'{oid}.{name}'
        gen = not body.get('default_password')
        dpw = str(body.get('default_password') or '') or security.random_password(8)
        rows = tapi.check_roster(cid, rows, dpw, org=oid)
        if not rows:
            raise HTTPException(400, _tr('名单是空的'))
        if len(rows) > 2000:
            raise HTTPException(400, _tr('一次最多导入 2000 人'))
        for r in rows:                                   # 密码规则（SaaS 更严）：表里给的密码不合规的那一行报错
            if r['status'] == 'new' and r['password']:
                why = security.password_problem(r['password'], r['username'])
                if why:
                    r['status'], r['msg'] = 'error', why
        new = [r for r in rows if r['status'] == 'new']
        lim = seats.summary(oid)
        cnt = {}
        for r in rows:
            cnt[r['status']] = cnt.get(r['status'], 0) + 1
        if body.get('preview'):
            return {'rows': rows, 'counts': cnt, 'new': len(new), 'limits': lim,
                    'seat_ok': lim['left']['students'] is None or len(new) <= lim['left']['students']}
        if not gen:
            security.check_password(dpw)
        seats.check_add(oid, 'student', len(new))
        accounts, errors, added = [], [], 0
        for r in rows:
            if r['status'] == 'error':
                errors.append(_tr('第 {line} 行（{v}）：{msg}', line=r['line'], v=r['username'] or _tr('空'), msg=r['msg']))
                continue
            if r['status'] == 'new':
                pw = r['password'] or (security.random_password(8) if gen else dpw)
                store.x('insert into users(username, name, role, pw, created, org) values(?,?,?,?,?,?)',
                        (r['username'], r['name'] or r['username'], 'student', store.hash_pw(pw), store.now(), oid))
                _mark_reset(r['username'], u['username'])
                accounts.append({'username': r['username'], 'name': r['name'] or r['username'], 'password': pw})
            if cid and r['status'] in ('new', 'exists'):
                tdb.x('insert or ignore into class_members(class_id, username, created) values(?,?,?)', (cid, r['username'], store.now()))
                added += 1
        store.audit(u['username'], 'POST', '/api/org/students/import', 200, _tr('导入学生 新建 {len}，加入班级 {added}', len=len(accounts), added=added), org=oid)
        return {'ok': True, 'created': len(accounts), 'added': added, 'errors': errors, 'accounts': accounts, 'limits': seats.summary(oid)}

    def _targets(oid, body, me):
        names = [str(x) for x in (body.get('usernames') or [])]
        if body.get('class_id'):
            c = tdb.q('select * from classes where id=? and org=?', (int(body['class_id']), oid), one=True)
            if not c:
                raise HTTPException(404, _tr('本单位没有这个班级'))
            names += tdb.members(c['id'])
        out = []
        for n in dict.fromkeys(names):
            r = store.q('select * from users where username=? and org=?', (n, oid), one=True)
            if not r:
                raise HTTPException(404, _tr('本单位没有账号 {n}', n=n))
            if r['username'] == me or r['role'] not in ROLES_MANAGED:
                raise HTTPException(400, _tr('{n} 不是老师或学生账号，不能在这里归档/恢复', n=n))
            out.append(r)
        return out

    @app.post('/api/org/users/archive')
    async def archive(request: Request, body: dict = Body(...)):
        """学期结束：归档学生（或老师）——不能登录、不占席位；成绩、提交都保留，随时能恢复。"""
        u, oid = need_orgadmin(request)
        rows = _targets(oid, body, u['username'])
        for r in rows:
            store.x('update users set archived=1 where id=?', (r['id'],))
            store.revoke_sessions(username=r['username'])
        store.audit(u['username'], 'POST', '/api/org/users/archive', 200, _tr('归档 {len} 个账号', len=len(rows)), org=oid)
        return {'ok': True, 'archived': len(rows), 'limits': seats.summary(oid)}

    @app.post('/api/org/users/restore')
    async def restore(request: Request, body: dict = Body(...)):
        u, oid = need_orgadmin(request)
        rows = [r for r in _targets(oid, body, u['username']) if r.get('archived')]
        for role in ROLES_MANAGED:
            seats.check_add(oid, role, sum(1 for r in rows if r['role'] == role and r['active']))
        for r in rows:
            store.x('update users set archived=0 where id=?', (r['id'],))
        store.audit(u['username'], 'POST', '/api/org/users/restore', 200, _tr('恢复 {len} 个账号', len=len(rows)), org=oid)
        return {'ok': True, 'restored': len(rows), 'limits': seats.summary(oid)}

    @app.post('/api/org/users/{username}/active')
    async def set_active(username: str, request: Request, body: dict = Body(...)):
        u, oid = need_orgadmin(request)
        r = _user_in_org(oid, username)
        if r['username'] == u['username']:
            raise HTTPException(400, _tr('不能停用自己'))
        on = bool(body.get('active'))
        if on and not r['active'] and not r.get('archived'):
            seats.check_add(oid, r['role'], 1)
        store.x('update users set active=? where id=?', (1 if on else 0, r['id']))
        if not on:
            store.revoke_sessions(username=username)
        return {'ok': True, 'limits': seats.summary(oid)}

    @app.post('/api/org/users/{username}/reset_password')
    async def reset_password(username: str, request: Request):
        u, oid = need_orgadmin(request)
        r = _user_in_org(oid, username)
        if r['role'] in ('orgadmin', 'admin') and r['username'] != u['username']:
            raise HTTPException(403, _tr('单位管理员的密码请本人修改（忘了请联系蜂元）'))
        pw = security.random_password(10)
        store.x('update users set pw=?, failed=0, locked_until=null where id=?', (store.hash_pw(pw), r['id']))
        _mark_reset(username, u['username'])
        store.revoke_sessions(username=username)
        store.audit(u['username'], 'POST', f'/api/org/users/{username}/reset_password', 200, _tr('重置密码'), org=oid)
        return {'ok': True, 'username': username, 'password': pw}

    @app.get('/api/org/usage')
    async def org_usage(request: Request):
        _u, oid = need_orgadmin(request)
        return orgs.usage(oid)

    def _need_password(u, body):
        row = store.q('select pw from users where username=?', (u['username'],), one=True)
        if not row or not store.check_pw(str((body or {}).get('password') or ''), row['pw']):
            raise HTTPException(403, _tr('请输入你自己的登录密码确认'))

    @app.post('/api/org/export')
    async def org_export(request: Request, body: dict = Body(...)):
        u, oid = need_orgadmin(request)
        _need_password(u, body)
        data = orgs.export_zip(oid)
        store.audit(u['username'], 'POST', '/api/org/export', 200, _tr('导出本单位数据 {len} 字节', len=len(data)), org=oid)
        return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename=org-{oid}.zip'})

    @app.post('/api/org/delete')
    async def org_delete(request: Request, body: dict = Body(...)):
        """删除本单位全部数据：班级、作业、提交、作业包、进度、账号（自部署保留你自己的管理员账号）。不能撤销——先导出备份。"""
        u, oid = need_orgadmin(request)
        _need_password(u, body)
        o = orgs.get(oid)
        if str(body.get('confirm') or '').strip() not in (o['name'], oid):
            raise HTTPException(400, _tr('请在确认框里输入单位名称「{name}」', name=o['name']))
        n = orgs.delete_data(oid, keep_user=None if saas() else u['username'])
        store.audit(u['username'], 'POST', '/api/org/delete', 200, _tr('删除本单位数据 {n}', n=n), org=oid)
        return {'ok': True, 'deleted': n}

    @app.get('/api/org/license')
    async def license_get(request: Request):
        need_orgadmin(request)
        if saas():
            raise HTTPException(404, _tr('SaaS 版没有授权文件（席位由蜂元在运维后台设置）'))
        st = lic.status()
        return {k: st.get(k) for k in ('installed', 'ok', 'error', 'expired', 'days_left', 'payload')} | {'limits': seats.summary()}

    @app.post('/api/org/license')
    async def license_put(request: Request, body: dict = Body(...)):
        """上传授权文件（.vflic 的文本，或 base64 / data: 地址）：验签通过才生效，离线即可激活。"""
        u, oid = need_orgadmin(request)
        if saas():
            raise HTTPException(404, _tr('SaaS 版没有授权文件'))
        raw = str(body.get('data') or '')
        if raw.startswith('data:'):
            raw = raw.split(',', 1)[-1]
        if not raw.lstrip().startswith('{'):
            try:
                raw = base64.b64decode(raw).decode('utf-8')
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, _tr('授权文件读不出来'))
        if len(raw) > 64 * 1024:
            raise HTTPException(413, _tr('授权文件太大了'))
        try:
            st = lic.install(raw.encode('utf-8'))
        except ValueError as e:
            raise HTTPException(400, _tr('授权文件没有通过验证：{e}', e=e))
        store.audit(u['username'], 'POST', '/api/org/license', 200, _tr('导入授权 {get}', get=(st.get('payload') or {}).get('license_id')), org=oid)
        return {k: st.get(k) for k in ('installed', 'ok', 'error', 'expired', 'days_left', 'payload')} | {'limits': seats.summary()}

    @app.delete('/api/org/license')
    async def license_del(request: Request):
        u, oid = need_orgadmin(request)
        if saas():
            raise HTTPException(404, _tr('SaaS 版没有授权文件'))
        lic.remove()
        store.audit(u['username'], 'DELETE', '/api/org/license', 200, _tr('删除授权文件'), org=oid)
        return {'ok': True, 'limits': seats.summary()}

