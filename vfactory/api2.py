"""专业版接口：账号与权限、API 令牌、审计、仿真控制、生产计划、场景、实验、报表、信号中心、数据集、布局检查。"""
from .i18n import _tr
import asyncio
import io
import json
import math
import os
import shutil
from datetime import datetime

from fastapi import Body, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from . import comm, history, store

from .experiment import run_experiment
from .netmodel import INFRA_TYPES
from .scenario import ACTIONS, BUILTIN


def me_of(request: Request):
    return request.state.user


def need(request, role):
    u = request.state.user
    if not store.role_ok(u, role):
        raise HTTPException(403, _tr('当前账号没有这个权限'))
    return u


def need_user_admin(request):
    """账号管理：管理员（自部署）或单位管理员（5.0）——都只管自己单位的账号。"""
    u = request.state.user
    if u.get('role') not in ('admin', 'orgadmin'):
        raise HTTPException(403, _tr('当前账号没有这个权限'))
    return u, u.get('org') or 'default'


def tenancy_saas():
    from . import tenancy
    return tenancy.saas()


INITIAL_PASSWORDS = ('honey123', '123456', 'teach123')     # 安装和导入名单时的初始密码（前端 Login.vue 的 WEAK 同一份）


def register(app, mgr):
    # ---------------- 账号 ----------------
    @app.post('/api/login')
    async def login(request: Request, body: dict = Body(...)):
        """登录（5.0：连续输错锁定、同一 IP 失败太多限流、单位停用/到期拦截；会话可吊销）。"""
        from .tenancy import policy, security
        ip = request.client.host if request.client else ''
        u = security.login_user(body.get('username'), body.get('password'), ip)
        if body.get('client') == 'desktop' and not mgr.desktop:          # 客户端登录：单位要开通了"客户端"功能包
            from .tenancy import seats
            if not seats.feature(u.get('org'), 'client'):
                raise HTTPException(403, _tr('本单位没有开通客户端，请联系单位管理员'))
        store.audit(u['username'], 'LOGIN', '/api/login', 200, ip=ip)
        eu = policy.effective(u, mgr)
        return {'token': store.make_session(u['username'], ip=ip, agent=request.headers.get('user-agent', '')),
                'user': {'username': u['username'], 'name': u['name'], 'role': eu['role']}}

    @app.get('/api/me')
    async def me(request: Request):
        u = me_of(request)
        from . import tenancy
        from .tenancy import orgs
        o = orgs.get(u.get('org')) or {}
        return {'username': u['username'], 'name': u['name'], 'role': u['role'], 'role_name': store.ROLES.get(u['role']), 'company': _tr('蜂元科技（郑州）有限责任公司'),
                'org': {'id': o.get('id'), 'name': o.get('name'), 'features': o.get('features')}, 'deploy': tenancy.mode()}

    @app.post('/api/me/logout')
    async def logout(request: Request):
        """退出登录：吊销这次的会话（令牌立即失效）。"""
        u = me_of(request)
        if u.get('sid'):
            store.revoke_sessions(sid=u['sid'])
        return {'ok': True}

    @app.get('/api/me/sessions')
    async def my_sessions(request: Request):
        """我的登录（哪台电脑、什么时候）；current 是这次的。id 是会话号的前 8 位。"""
        u = me_of(request)
        rows = store.q('select sid, created, expires, last_seen, ip, agent from sessions where username=? and revoked=0 and expires>? '
                       'order by created desc limit 50', (u['username'], store.now()))
        for r in rows:
            r['current'] = r['sid'] == u.get('sid')
            r['id'] = r.pop('sid')[:8]
        return rows

    @app.delete('/api/me/sessions/{sid}')
    async def my_session_del(sid: str, request: Request):
        """注销我的某个登录（id 是列表里的前 8 位）；all = 除这次以外全部。"""
        u = me_of(request)
        if sid == 'all':
            store.revoke_sessions(username=u['username'], keep=u.get('sid'))
            return {'ok': True}
        r = store.q('select sid from sessions where username=? and substr(sid,1,8)=? and revoked=0', (u['username'], sid), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这个登录'))
        store.revoke_sessions(sid=r['sid'])
        return {'ok': True}

    @app.post('/api/me/password')
    async def change_pw(request: Request, body: dict = Body(...)):
        u = store.q('select * from users where username=?', (me_of(request)['username'],), one=True)
        if not store.check_pw(body.get('old') or '', u['pw']):
            raise HTTPException(400, _tr('原密码不对'))
        new = body.get('new') or ''
        if len(new) < 6:
            raise HTTPException(400, _tr('新密码至少 6 位'))
        if new == (body.get('old') or ''):
            raise HTTPException(400, _tr('新密码不能和原密码一样'))
        if new in INITIAL_PASSWORDS:
            raise HTTPException(400, _tr('不能用初始密码（honey123、123456、teach123 这类大家都知道的密码）'))
        from .tenancy import security
        security.check_password(new, u['username'])        # 5.0：SaaS 的密码规则更严（见 tenancy/security.py）
        store.x('update users set pw=?, pw_at=? where id=?', (store.hash_pw(new), store.now(), u['id']))
        store.revoke_sessions(username=u['username'], keep=me_of(request).get('sid'))     # 别处的登录都要重新登录
        return {'ok': True}

    def _roles_for(u):
        """能分配的角色：SaaS 只有单位管理员/老师/学生；单位管理员不能建管理员、工程师。"""
        if tenancy_saas():
            return {k: store.ROLES[k] for k in ('orgadmin', 'teacher', 'student')}
        if u['role'] == 'orgadmin':
            return {k: store.ROLES[k] for k in ('orgadmin', 'teacher', 'student', 'viewer')}
        return dict(store.ROLES)

    @app.get('/api/admin/users')
    async def users(request: Request):
        u, org = need_user_admin(request)                       # 5.0：只列本单位的账号
        return {'users': store.q('select id,username,name,role,active,archived,created,last_login from users where org=? order by id', (org,)),
                'roles': _roles_for(u)}

    @app.post('/api/admin/users')
    async def user_save(request: Request, body: dict = Body(...)):
        """新建/修改账号（只能是本单位的）。5.0：老师、学生占席位（超了不能建/启用，见 tenancy/seats.py）。"""
        from .tenancy import seats, security
        u, org = need_user_admin(request)
        if body.get('role') not in _roles_for(u):
            raise HTTPException(400, _tr('角色不对'))
        if body.get('id'):
            cur = store.q('select * from users where id=? and org=?', (body['id'], org), one=True)
            if not cur:
                raise HTTPException(404, _tr('没有这个账号'))
            if cur['role'] in ('admin', 'engineer') and u['role'] == 'orgadmin':
                raise HTTPException(403, _tr('单位管理员不能改管理员、工程师账号'))
            active = 1 if body.get('active', True) else 0
            if active and (not cur['active'] or cur['role'] != body['role']) and not cur.get('archived'):
                seats.check_add(org, body['role'], 1)
            store.x('update users set name=?, role=?, active=? where id=?', (body.get('name'), body['role'], active, body['id']))
            if body.get('password'):
                security.check_password(body['password'], cur['username'])
                store.x('update users set pw=?, failed=0, locked_until=null where id=?', (store.hash_pw(body['password']), body['id']))
                store.revoke_sessions(username=cur['username'])
            if not active:
                store.revoke_sessions(username=cur['username'])
        else:
            if not body.get('username') or store.q('select 1 from users where username=?', (body['username'],), one=True):
                raise HTTPException(400, _tr('账号为空或已存在'))
            seats.check_add(org, body['role'], 1)
            pw = body.get('password') or ('' if tenancy_saas() else 'honey123')
            if not pw:
                raise HTTPException(400, _tr('请设置初始密码'))
            security.check_password(pw, body['username'])
            store.x('insert into users(username,name,role,pw,created,org) values(?,?,?,?,?,?)',
                    (body['username'], body.get('name') or body['username'], body['role'], store.hash_pw(pw), store.now(), org))
        return {'ok': True}

    TOKEN_FIELDS = 'id,name,prefix,username,created,last_used,last_ip,uses,revoked,scope,plants,expires,ips'

    def token_rows(rows):
        now = store.now()
        for r in rows:
            r['plants'] = store._plants(r.get('plants')) or []
            r['expired'] = bool(r.get('expires') and r['expires'] < now)
            r['scope_name'] = store.SCOPES.get(r.get('scope')) or _tr('继承创建者权限（旧令牌）')
            r['uses'] = r.get('uses') or 0
            m = store._used.get(r['id'])
            if m and m.get('last'):
                r['uses'] += m['n']
                if m['last'] > (r.get('last_used') or ''):
                    r['last_used'], r['last_ip'] = m['last'], m['ip']
        return rows

    @app.get('/api/tokens')
    async def tokens(request: Request):
        """API 令牌列表（管理员看全部，其他人看自己的）。附带范围、限定工厂、有效期、IP 白名单、调用次数、最近使用时间和来源 IP。"""
        u = me_of(request)
        if u['role'] in ('admin', 'orgadmin'):                 # 管理员看本单位全部令牌（5.0 按单位隔离）
            return token_rows(store.q(f'select {TOKEN_FIELDS} from tokens where username in (select username from users where org=?) order by id desc',
                                      (u.get('org') or 'default',)))
        return token_rows(store.q(f'select {TOKEN_FIELDS} from tokens where username=? order by id desc', (u['username'],)))

    @app.get('/api/tokens/options')
    async def token_options(request: Request):
        u = me_of(request)
        top = 'admin' if u['role'] == 'admin' else 'control'
        return {'scopes': [{'value': k, 'label': v, 'allowed': store.SCOPE_LEVEL[k] <= store.SCOPE_LEVEL[top]} for k, v in store.SCOPES.items()],
                'plants': [{'id': pid, 'name': rt.plant.name} for pid, rt in mgr.rts.items()]}

    @app.post('/api/tokens')
    async def token_new(request: Request, body: dict = Body(...)):
        """新建 API 令牌。body: {name, scope: read|write|control|admin, plants?: [工厂编号], expires_days?: 天数 或 expires?: "YYYY-MM-DD", ips?: "10.0.0.0/8, 192.168.1.20"}"""
        u = need(request, 'engineer')
        # 不传 scope：和旧版一样继承创建者权限（已有的对接脚本照常工作）；界面上新建令牌总是明确选一个范围
        scope = body.get('scope') or None
        if scope is not None and scope not in store.SCOPES:
            raise HTTPException(400, _tr('令牌范围只能是 read / write / control / admin'))
        if scope == 'admin' and u['role'] != 'admin':
            raise HTTPException(403, _tr('只有管理员能创建 admin 范围的令牌'))
        plants = [str(x) for x in (body.get('plants') or []) if str(x)]
        bad = [x for x in plants if x not in mgr.rts]
        if bad:
            raise HTTPException(400, _tr('没有工厂 {join}', join=_tr('、').join(bad)))
        expires = None
        if body.get('expires_days') not in (None, '', 0):
            try:
                days = float(body['expires_days'])
            except (TypeError, ValueError):
                raise HTTPException(400, _tr('有效期天数需要数字'))
            if not 0 < days <= 3650:
                raise HTTPException(400, _tr('有效期 1 天到 10 年'))
            from datetime import timedelta
            expires = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        elif body.get('expires'):
            try:
                expires = datetime.fromisoformat(str(body['expires']).replace('T', ' ')[:19]).strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise HTTPException(400, _tr('有效期格式：YYYY-MM-DD'))
            if len(str(body['expires'])) <= 10:
                expires = expires[:10] + ' 23:59:59'
        ips = str(body.get('ips') or '').strip()
        if ips:
            import ipaddress
            for r in ips.replace('，', ',').replace(';', ',').replace(' ', ',').split(','):
                if r.strip():
                    try:
                        ipaddress.ip_network(r.strip(), strict=False)
                    except ValueError:
                        raise HTTPException(400, _tr('IP 白名单格式不对：{strip}（例：192.168.1.20 或 10.0.0.0/8）', strip=r.strip()))
        tok = store.new_api_token((body.get('name') or _tr('未命名'))[:40], u['username'], scope, plants or None, expires, ips or None)
        return {'token': tok, 'scope': scope or 'inherit', 'plants': plants, 'expires': expires, 'ips': ips, 'msg': _tr('令牌只显示这一次，请复制保存')}

    @app.delete('/api/tokens/{tid}')
    async def token_del(tid: int, request: Request):
        u = me_of(request)
        t = store.q('select * from tokens where id=?', (tid,), one=True)
        if not t or (t['username'] != u['username'] and (u['role'] not in ('admin', 'orgadmin') or store.org_of(t['username']) != (u.get('org') or 'default'))):
            raise HTTPException(404, _tr('没有这个令牌'))
        store.x('update tokens set revoked=1 where id=?', (tid,))
        return {'ok': True}

    @app.get('/api/admin/audit')
    async def audit(request: Request, q: str = '', limit: int = 300):
        _u, org = need_user_admin(request)                     # 5.0：只看本单位的审计
        limit = max(1, min(5000, limit))
        if q:
            return store.q('select * from audit where org=? and (username like ? or path like ? or detail like ?) order by id desc limit ?',
                           (org,) + (f'%{q}%',) * 3 + (limit,))
        return store.q('select * from audit where org=? order by id desc limit ?', (org, limit))

    # ---------------- 工厂总览与仿真控制 ----------------
    @app.get('/api/overview')
    async def overview(request: Request):
        out = []
        only = store.token_plants(getattr(request.state, 'user', None))      # 限定了工厂的令牌只看到那些工厂
        for pid, rt in mgr.rts.items():
            if only and pid not in only:
                continue
            p = rt.plant
            k = p.kpi
            st = [s.state for s in p.stations.values() if s.kind not in ('crew', 'agv') and s.cfg.get('type') not in INFRA_TYPES]
            out.append({'id': pid, 'name': p.name, 'product': p.plan.product['code'], 'time': p.clock_str(), 'speed': p.speed, 'paused': p.paused,
                        'stations': len(st), 'running': st.count('Executing'), 'stopped': st.count('Stopped'),
                        'alarms': sum(1 for s in p.stations.values() if s.alarm and s.kind != 'crew'), 'good': k['good'], 'castings': k['castings'],
                        'scrap_rate': round(k['scrap'] / k['castings'], 4) if k['castings'] else 0, 'rate': round(p.recent_rate(), 1),
                        'modbus_port': rt.cfg['plant']['modbus_port'], 'dirty': rt.dirty, 'scenario': rt.scenario.run['name'] if rt.scenario.run else None,
                        'recording': bool(rt.rec.file), 'clients': len(comm.clients(mgr, rt)), 'shift': p.plan.shift_name(), 'off': p.plan.off_reason})
        return {'plants': out, 'ports': {'http': mgr.args.http, 'opcua': mgr.args.opcua, 'mqtt': mgr.args.mqtt}}

    @app.post('/api/p/{pid}/advance')
    async def advance(pid: str, body: dict = Body(...)):
        """快进 N 小时（分段执行，期间界面照常刷新）。"""
        rt = mgr.get(pid)
        hours = max(0.0, min(72.0, float(body.get('hours', 1))))
        p = rt.plant
        was = p.paused
        p.paused = True
        n = int(hours * 3600 / p.dt)
        try:
            for i in range(0, n, 1800):
                for _ in range(min(1800, n - i)):
                    p.step()
                await asyncio.sleep(0)
        finally:
            p.paused = was
        p.log('PLANT', 'info', _tr('快进 {hours:g} 小时', hours=hours))
        return {'ok': True, 'time': p.clock_str()}

    @app.get('/api/p/{pid}/timeline')
    async def timeline(pid: str, hours: float = 8):
        p = mgr.get(pid).plant
        t0 = p.t - hours * 3600
        keep = {'fault', 'repair', 'alarm', 'tool', 'inject', 'scenario', 'plan', 'layout', 'heat', 'record', 'replay'}
        evs = []
        for e in p.events:
            if e['kind'] not in keep:
                continue
            t = (datetime.strptime(e['t'], '%Y-%m-%d %H:%M:%S') - p.t0).total_seconds()
            if t >= t0:
                evs.append({'seq': e['seq'], 't': e['t'], 'x': round((t - t0) / (hours * 3600), 5), 'kind': e['kind'], 'station': e['station'], 'msg': e['msg']})
        return {'from': (p.t0 + __import__('datetime').timedelta(seconds=max(0, t0))).strftime('%Y-%m-%d %H:%M'), 'to': p.clock_str(), 'events': evs[-400:]}

    # ---------------- 生产计划 ----------------
    def _plan_key(rt, cfg):
        """计划配置的"内容"（不含订单进度），用来比较运行中的计划和工厂配置文件里的是否一样。"""
        from .plan import Plan
        e = Plan(rt.plant, cfg or {}).export()
        e['orders'] = [{k: v for k, v in o.items() if k not in ('done', 'born')} for o in e['orders']]
        return json.dumps(e, sort_keys=True, ensure_ascii=False, default=str)

    def _plan_saved(rt):
        """4.7：运行中的计划是否已经保存进工厂配置（yaml）。"""
        from .server import read_plant
        try:
            sv = read_plant(rt.path).get('plan')
        except Exception:                          # noqa: BLE001  配置文件读不了：当作没保存
            return False
        return _plan_key(rt, sv) == _plan_key(rt, rt.plant.plan.export())

    def _plan_view(rt):
        return {**rt.plant.plan.view(), 'saved': _plan_saved(rt)}

    @app.get('/api/p/{pid}/plan')
    async def plan_get(pid: str):
        return _plan_view(mgr.get(pid))

    @app.post('/api/p/{pid}/plan/save')
    async def plan_save(pid: str, request: Request):
        """4.7：把运行中的计划写进工厂配置（只写 plan 段；别的运行中改动照旧在工作台里保存）。"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        from .server import read_yaml, write_yaml
        m = read_yaml(rt.path)
        m['plan'] = rt.plant.plan.export()
        if os.path.exists(rt.path):
            shutil.copy(rt.path, rt.path + '.bak')
        write_yaml(rt.path, m)
        rt.plant.log('PLAN', 'plan', _tr('生产计划已保存到工厂配置'))
        return _plan_view(rt)

    @app.put('/api/p/{pid}/plan')
    async def plan_put(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        from .plan import Plan
        old = {o['code']: o for o in rt.plant.plan.orders}
        cfg = {k: body.get(k) for k in ('shifts', 'workdays', 'breaks', 'downtime', 'products', 'orders') if body.get(k) is not None}
        for o in cfg.get('orders', []):
            if o.get('code') in old:
                o['done'] = old[o['code']]['done']
                o['born'] = old[o['code']]['born']
        np_ = Plan(rt.plant, cfg)
        np_.product = rt.plant.plan.product
        np_._first = False
        rt.plant.plan = np_
        np_.update()
        rt.cfg['plan'] = np_.export()
        rt.dirty = True
        rt.plant.log('PLAN', 'plan', _tr('生产计划已更新'))
        return _plan_view(rt)

    # ---------------- 场景 ----------------
    @app.get('/api/p/{pid}/scenarios')
    async def scenarios(pid: str):
        rt = mgr.get(pid)
        saved = store.q('select * from scenarios where plant=? order by id desc', (pid,))
        for s in saved:
            s['steps'] = json.loads(s['steps'] or '[]')
        builtin = [{**b, 'id': 'b:' + b['key'], 'builtin': True} for b in BUILTIN]
        valid = set(rt.plant.stations)
        for s in builtin + saved:
            s['missing'] = sorted({st['target'] for st in s['steps'] if st.get('target') and st['action'] not in ('comm',) and st['target'] not in valid})
        return {'items': builtin + saved, 'actions': ACTIONS, 'status': rt.scenario.view(),
                'stations': [{'id': s.id, 'name': s.name, 'faults': s.fault_kinds, 'writable': [k for k, t in s.tags.items() if t.writable]}
                             for s in rt.plant.stations.values()]}

    @app.post('/api/p/{pid}/scenarios')
    async def scenario_save(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        steps = json.dumps(body.get('steps') or [], ensure_ascii=False)
        if body.get('id') and not str(body['id']).startswith('b:'):
            store.x('update scenarios set name=?, descr=?, steps=?, updated=? where id=?', (body['name'], body.get('descr'), steps, store.now(), body['id']))
            return {'ok': True, 'id': body['id']}
        sid = store.x('insert into scenarios(plant,name,descr,steps,created,updated) values(?,?,?,?,?,?)',
                      (pid, body.get('name') or _tr('新场景'), body.get('descr'), steps, store.now(), store.now()))
        return {'ok': True, 'id': sid}

    @app.delete('/api/p/{pid}/scenarios/{sid}')
    async def scenario_del(pid: str, sid: int, request: Request):
        need(request, 'engineer')
        store.x('delete from scenarios where id=? and plant=?', (sid, pid))
        return {'ok': True}

    @app.post('/api/p/{pid}/scenarios/run')
    async def scenario_run(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        sid = str(body.get('id'))
        if sid.startswith('b:'):
            sc = next((b for b in BUILTIN if b['key'] == sid[2:]), None)
        else:
            sc = store.q('select * from scenarios where id=?', (int(sid),), one=True)
            if sc:
                sc['steps'] = json.loads(sc['steps'])
        if body.get('steps'):
            sc = {'name': body.get('name') or _tr('临时场景'), 'steps': body['steps']}
        if not sc:
            raise HTTPException(404, _tr('没有这个场景'))
        rt.scenario.start(sc)
        return rt.scenario.view()

    @app.post('/api/p/{pid}/scenarios/stop')
    async def scenario_stop(pid: str, request: Request):
        need(request, 'engineer')
        rt = mgr.get(pid)
        rt.scenario.stop()
        return rt.scenario.view()

    # ---------------- 实验 ----------------
    @app.get('/api/p/{pid}/experiments')
    async def experiments(pid: str):
        rows = store.q('select id,name,hours,reps,status,progress,created,finished,username,variants from experiments where plant=? order by id desc', (pid,))
        for r in rows:
            v = json.loads(r['variants'] or '[]')
            r['kind'] = 'optimize' if isinstance(v, dict) else 'compare'
            r['variants'] = v if isinstance(v, list) else []
            r['spec'] = v if isinstance(v, dict) else None
        return rows

    @app.get('/api/p/{pid}/experiments/{eid}')
    async def experiment(pid: str, eid: int):
        r = store.q('select * from experiments where id=?', (eid,), one=True)
        if not r:
            raise HTTPException(404, _tr('没有这个实验'))
        v = json.loads(r['variants'] or '[]')
        r['kind'] = 'optimize' if isinstance(v, dict) else 'compare'
        r['variants'] = v if isinstance(v, list) else []
        r['spec'] = v if isinstance(v, dict) else None
        r['result'] = json.loads(r['result']) if r['result'] else None
        if r['result']:
            from .experiment import annotate
            annotate(r['result'], r.get('hours'))
        return r

    @app.post('/api/p/{pid}/experiments')
    async def experiment_new(pid: str, request: Request, body: dict = Body(...)):
        """body: {name, hours, reps, seed?, warmup_h?, variants?: [{name, changes}], factors?: [{label, type, station/key/name/template/role, levels}]}
        有 factors 时按"参数 × 水平"全因子生成方案；基准（当前方案）自动放第一个。各方案用同一组种子（公共随机数）。"""
        from .experiment import expand_factors
        u = need(request, 'engineer')
        rt = mgr.get(pid)
        variants = body.get('variants') or []
        if body.get('factors'):
            try:
                variants = expand_factors(body['factors'], include_base=True) + [v for v in variants if v.get('changes')]
            except ValueError as e:
                raise HTTPException(400, str(e))
        elif not variants or variants[0].get('changes'):
            variants = [{'name': _tr('基准（当前方案）'), 'changes': []}] + variants
        resolve = _version_resolver(pid)
        for v in variants:
            _check_variant(v, resolve)
        hours = max(0.5, min(168.0, float(body.get('hours', 24))))
        reps = max(1, min(30, int(body.get('reps', 2))))
        if len(variants) * reps > 400:
            raise HTTPException(400, _tr('方案数 × 重复次数 = {v}，超过 400，请减少', v=len(variants) * reps))
        seed0 = int(body.get('seed', 42))
        warm = float(body['warmup_h']) if body.get('warmup_h') not in (None, '') else None
        eid = store.x('insert into experiments(plant,name,hours,reps,variants,status,progress,created,username) values(?,?,?,?,?,?,?,?,?)',
                      (pid, body.get('name') or _tr('实验'), hours, reps, json.dumps(variants, ensure_ascii=False), 'queued', 0, store.now(), u['username']))
        asyncio.create_task(run_experiment(eid, rt.build_cfg(), hours, reps, variants, seed0, warm, resolve))
        return {'ok': True, 'id': eid, 'variants': len(variants)}

    @app.delete('/api/p/{pid}/experiments/{eid}')
    async def experiment_del(pid: str, eid: int, request: Request):
        need(request, 'engineer')
        store.x('delete from experiments where id=?', (eid,))
        return {'ok': True}

    # ---------------- 报表 ----------------
    # 统计区间与分析浮窗、方案报告完全一样：analysis.window（最近 hours 小时，0 = 全部；warmup=1 截掉预热；起点对齐整点）
    def _range(p, hours, warmup='1'):
        from .analysis import window
        return window(p, hours, str(warmup).lower() not in ('0', 'false', 'no', ''))

    @app.get('/api/p/{pid}/report')
    async def report(pid: str, hours: float = 24, warmup: str = '1', full: str = '0'):
        p = mgr.get(pid).plant
        r = history.summary(p, *_range(p, hours, warmup))
        if full in ('0', 'false', ''):
            r.pop('objects', None)
        return r

    @app.get('/api/p/{pid}/report.xlsx')
    async def report_xlsx(pid: str, hours: float = 24, warmup: str = '1'):
        rt = mgr.get(pid)
        data = history.to_excel(history.summary(rt.plant, *_range(rt.plant, hours, warmup)), rt.plant.name)
        return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename=report-{pid}.xlsx'})

    @app.get('/api/p/{pid}/report/print', response_class=HTMLResponse)
    async def report_print(pid: str, hours: float = 24, warmup: str = '1'):
        rt = mgr.get(pid)
        return print_html(rt.plant.name, history.summary(rt.plant, *_range(rt.plant, hours, warmup)))

    # ---------------- 信号中心 ----------------
    @app.get('/api/p/{pid}/signals/tree')
    async def sig_tree(pid: str):
        from .server import _mb_text as _mbt
        rt = mgr.get(pid)
        opc = rt.opcua.points()
        mq = rt.mqtt.points() if rt.mqtt else {}
        mb = {(r['station'], r['tag']): r for r in rt.modbus.points()}
        out = []
        for st in rt.plant.stations.values():
            tags = []
            for k, t in st.tags.items():
                m = mb.get((st.id, k))
                v = t.value
                tags.append({'key': f'{st.id}/{k}', 'name': k, 'value': v if not isinstance(v, float) or math.isfinite(v) else None, 'unit': t.unit, 'desc': t.desc,
                             'dtype': t.dtype, 'writable': t.writable, 'lo': t.lo, 'hi': t.hi, 'opcua': opc.get(f'{st.id}/{k}'), 'mqtt': mq.get(f'{st.id}/{k}'),
                             'modbus': _mbt(rt.modbus.port, m).split(' ', 2)[2] if m else None})
            out.append({'id': st.id, 'name': st.name, 'kind': st.kind, 'area': st.area, 'tags': tags})
        return out

    @app.get('/api/p/{pid}/signals/trend')
    async def sig_trend(pid: str, key: str, hours: float = 4):
        p = mgr.get(pid).plant
        ts, vs = p.tagring.series(key, p.t - hours * 3600)
        return {'key': key, 't': [(p.t0 + __import__('datetime').timedelta(seconds=t)).strftime('%m-%d %H:%M') for t in ts], 'v': vs}

    @app.get('/api/p/{pid}/signals/status')
    async def sig_status(pid: str):
        """信号中心状态：在线客户端、通讯故障（comm = 协议级，rules = 全部规则）、支持的故障模式、录制回放、真实接入地址、协议设置。"""
        rt = mgr.get(pid)
        return {'clients': comm.clients(mgr, rt), 'comm': {k: comm.public(v) for k, v in rt.plant.comm.items() if v}, 'modes': comm.MODES, **rt.rec.status(),
                **comm.status(rt), 'recordings': comm.recordings(), 'endpoints': rt.meta()['endpoints'], 'settings': comm.settings(rt.plant),
                'mqtt_auth': (mgr.mqtt.auth if mgr.mqtt else None), 'mqtt_stats': {**rt.mqtt.stats, 'mes_queue': len(rt.mqtt.mesq), 'mes_held': len(rt.mqtt.mes_held), 'delayed': len(rt.mqtt.outq), 'gateways': rt.mqtt.gw_stats} if rt.mqtt else None,
                'opcua_sync_ms': getattr(rt.opcua, 'sync_ms', None), 'opcua_vars': len(getattr(rt.opcua, 'vars', []))}

    @app.post('/api/p/{pid}/signals/comm')
    async def sig_comm(pid: str, request: Request, body: dict = Body(...)):
        """注入 / 恢复通讯故障。body: {protocol: opcua|modbus|mqtt, mode（空 = 恢复）, station?, tag?（点位或以 / 结尾的前缀）, minutes?（0 = 一直保持）,
        latency?（延迟/抖动秒数）, drop_pct?（丢包百分比）, value?（卡死值，空 = 当前值）, rate?（漂移量/分钟）, include_mes?（MQTT 的 _mes 是否一起受影响，默认是）}。
        不支持的模式返回 400。"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        if body.get('link'):                      # 4.3：网络线 / 信号线故障（作用于经过这条线的数据，三种协议都受影响）
            from . import netmodel
            try:
                r = netmodel.set_link_fault(rt, body['link'], body.get('mode') or None, minutes=float(body.get('minutes') or 0),
                                            latency=body.get('latency'), drop_pct=body.get('drop_pct'))
            except ValueError as e:
                raise HTTPException(400, str(e))
            return {'ok': True, 'rule': comm.public(r) if r else None}
        proto = body.get('protocol')
        if proto not in comm.SUPPORTED:
            raise HTTPException(400, _tr('协议只能是 opcua / modbus / mqtt'))
        mode = body.get('mode') or None
        try:
            r = rt.comm_set(proto, mode, latency=float(body.get('latency') or 5), minutes=float(body.get('minutes') or 0), station=body.get('station'),
                            tag=body.get('tag'), drop_pct=body.get('drop_pct'), value=body.get('value'), rate=body.get('rate'),
                            include_mes=body.get('include_mes', True))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {'ok': True, 'rule': comm.public(r) if r else None}

    @app.delete('/api/p/{pid}/signals/comm/{rid}')
    async def sig_comm_del(pid: str, rid: int, request: Request):
        """按编号恢复一条通讯故障规则。"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        if not comm.clear(rt, rid=rid):
            raise HTTPException(404, _tr('没有这条故障规则（可能已到时自动恢复）'))
        return {'ok': True}

    @app.delete('/api/p/{pid}/signals/comm')
    async def sig_comm_clear(pid: str, request: Request):
        """恢复全部通讯故障。"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        n = 0
        for r in list(comm.rules(rt.plant)):
            n += comm.clear(rt, rid=r['id'])
        for proto in list(rt.plant.comm):
            rt.plant.comm[proto] = None
        return {'ok': True, 'cleared': n}

    # ---------------- 架构（4.3：信息系统 / 通讯 / 控制 / 生产设备 分层，第四张图的数据） ----------------
    @app.get('/api/p/{pid}/architecture')
    async def architecture(pid: str):
        """架构图数据：nodes（按层：it / network / control / process，带状态；生产设备带 field 汇总）、links（网络线和信号线，带实时状态、
        故障、经过它的设备）、gateways（采集的设备、北向协议、上报的点位 / 报文数、地址格式）、MES 连接状态、没接到任何网关的设备。"""
        from . import netmodel
        return netmodel.architecture(mgr.get(pid))

    @app.post('/api/p/{pid}/architecture/links/{lid}/fault')
    async def arch_link_fault(pid: str, lid: str, request: Request, body: dict = Body(...)):
        """在一条网络线 / 信号线上注入故障：{mode: disconnect|latency|jitter|drop|bad|freeze, minutes?, latency?, drop_pct?}；mode 为空 = 恢复。"""
        need(request, 'engineer')
        from . import netmodel
        try:
            r = netmodel.set_link_fault(mgr.get(pid), lid, body.get('mode') or None, minutes=float(body.get('minutes') or 0),
                                        latency=body.get('latency'), drop_pct=body.get('drop_pct'))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {'ok': True, 'rule': comm.public(r) if r else None}

    @app.delete('/api/p/{pid}/architecture/links/{lid}/fault')
    async def arch_link_clear(pid: str, lid: str, request: Request):
        need(request, 'engineer')
        from . import netmodel
        try:
            netmodel.set_link_fault(mgr.get(pid), lid, None)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {'ok': True}

    @app.get('/api/p/{pid}/protocol/settings')
    async def proto_settings(pid: str):
        """协议设置：time（sim 仿真时间 / wall 墙钟）、lenient_types、allow_out_of_range、modbus{auto, base, fmt, order, missing_unit}、mqtt{heartbeat_s}。"""
        return {'settings': comm.settings(mgr.get(pid).plant), 'defaults': comm.DEFAULTS, 'fmts': list(comm.FMTS), 'orders': list(comm.ORDERS)}

    @app.put('/api/p/{pid}/protocol/settings')
    async def proto_settings_put(pid: str, request: Request, body: dict = Body(...)):
        """修改协议设置（立即生效，Modbus 地址表按新设置重建；保存在服务器上，按工厂）。"""
        need(request, 'engineer')
        rt = mgr.get(pid)
        try:
            return {'ok': True, 'settings': comm.save_settings(rt, body)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get('/api/settings/mqtt')
    async def mqtt_auth_get():
        """MQTT 认证（全局）：anonymous = rw 匿名可读写 / ro 匿名只读 / none 必须用 API 令牌作密码登录。"""
        return {'auth': mgr.mqtt.auth if mgr.mqtt else None, 'enabled': bool(mgr.mqtt)}

    @app.put('/api/settings/mqtt')
    async def mqtt_auth_put(request: Request, body: dict = Body(...)):
        need(request, 'admin')
        if not mgr.mqtt:
            raise HTTPException(400, _tr('MQTT 没有启动'))
        try:
            return {'ok': True, 'auth': mgr.mqtt.save_auth(body)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post('/api/p/{pid}/signals/record')
    async def sig_record(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        if body.get('action') == 'start':
            return {'file': rt.rec.start()}
        return {'file': rt.rec.stop()}

    @app.post('/api/p/{pid}/signals/replay')
    async def sig_replay(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        if body.get('action') == 'stop':
            rt.rec.stop_replay()
            return {'ok': True}
        try:
            await rt.rec.play(body['file'], float(body.get('speed') or 10))
        except FileNotFoundError:
            raise HTTPException(404, _tr('没有这个录制文件'))
        return {'ok': True}

    @app.get('/api/p/{pid}/points.xlsx')
    async def points_xlsx(pid: str):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        rows = mgr.get(pid).points()
        wb = Workbook()
        ws = wb.active
        ws.title = _tr('点表')
        ws.append(list(rows[0].keys()))
        for c in ws[1]:
            c.font, c.fill = Font(bold=True), PatternFill('solid', fgColor='F2C94C')
        for r in rows:
            ws.append(list(r.values()))
        for i, w in enumerate((22, 30, 26, 8, 8, 6, 46, 46, 34)):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = 'A2'
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename=points-{pid}.xlsx'})

    @app.get('/api/p/{pid}/nodeset.xml')
    async def nodeset(pid: str):
        import os
        import tempfile
        rt = mgr.get(pid)
        nodes = [rt.opcua.top]
        stack = [rt.opcua.top]
        while stack:
            n = stack.pop()
            for ch in await n.get_children():
                nodes.append(ch)
                stack.append(ch)
        path = os.path.join(tempfile.gettempdir(), f'vf-nodeset-{pid}.xml')
        await mgr.opcua.server.export_xml(nodes, path)
        with open(path, 'rb') as f:
            data = f.read()
        return Response(data, media_type='application/xml', headers={'Content-Disposition': f'attachment; filename=nodeset-{pid}.xml'})

    # ---------------- 数据集 ----------------
    @app.get('/api/p/{pid}/dataset.zip')
    async def dataset(pid: str, hours: float = 24, keys: str = ''):
        p = mgr.get(pid).plant
        sel = [k for k in keys.split(',') if k] or None
        data = history.dataset_zip(p, max(0, p.t - hours * 3600), p.t, sel)
        return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename=dataset-{pid}-{p.now():%Y%m%d%H%M}.zip'})

    @app.get('/api/p/{pid}/dataset/info')
    async def dataset_info(pid: str):
        p = mgr.get(pid).plant
        r = p.tagring
        span = (p.t - r.ts[(r.pos - r.count) % r.n]) / 3600 if r.count else 0
        lb = {}
        for x in p.labels:
            lb[x['type']] = lb.get(x['type'], 0) + 1
        return {'hours': round(span, 1), 'rows': r.count, 'tags': len(r.keys), 'labels': lb, 'parts': len(p.parts), 'events': len(p.events),
                'keys': r.keys}

    # ---------------- 布局检查 ----------------
    @app.get('/api/p/{pid}/validate')
    async def validate(pid: str):
        return check_layout(mgr.get(pid))


def check_layout(rt):
    from .flow.model import issue_cat_code
    p = rt.plant
    issues = []

    def add(level, cat, msg, station=None):
        issues.append({'level': level, 'cat': cat, 'cat_code': issue_cat_code(cat), 'msg': msg, 'station': station})
    kinds = {}
    for s in p.stations.values():
        kinds.setdefault(s.kind, []).append(s)
    if 'molding' in kinds:
        for k, n in (('sand', _tr('砂处理系统')), ('treatment', _tr('球化孕育站')), ('cooling', _tr('冷却线')), ('furnace', _tr('中频炉'))):
            if k not in kinds:
                add('error', _tr('工艺'), _tr('有造型线但没有{n}', n=n), None)
        if 'shotblast' not in kinds:
            add('warn', _tr('工艺'), _tr('有造型线但没有抛丸机：落砂后的铸件无法清理'), None)
    if 'cnc' in kinds:
        for k, n in (('deburr', _tr('去毛刺单元')), ('inspection', _tr('检测站'))):
            if k not in kinds:
                add('warn', _tr('工艺'), _tr('有加工中心但没有{n}，零件会积压在缓存里', n=n), None)
        if 'agv' not in kinds:
            add('error', _tr('物流'), _tr('有加工中心但没有 AGV：毛坯无法送到线边'), None)
    if 'warehouse' not in kinds and ('inspection' in kinds):
        add('warn', _tr('物流'), _tr('没有立体仓库：成品会堆在成品待入库缓存'), None)
    # 重叠与越界
    boxes = []
    for s in p.stations.values():
        if s.kind in ('crew', 'agv'):
            continue
        L, W = s.size
        if (s.rot or 0) % 180:
            L, W = W, L
        boxes.append((s, s.pos[0] - L / 2, s.pos[0] + L / 2, s.pos[1] - W / 2, s.pos[1] + W / 2))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ox = min(a[2], b[2]) - max(a[1], b[1])
            oy = min(a[4], b[4]) - max(a[3], b[3])
            if ox > 0.2 and oy > 0.2:
                add('warn', _tr('布局'), _tr('{name} 与 {name2} 占地重叠 {ox:.1f}×{oy:.1f} m', name=a[0].name, name2=b[0].name, ox=ox, oy=oy), a[0].id)
    areas = rt.cfg.get('areas') or []
    if areas:
        x0, x1 = min(a['x'][0] for a in areas), max(a['x'][1] for a in areas)
        for s, a0, a1, b0, b1 in boxes:
            if a0 < x0 - 2 or a1 > x1 + 2:
                add('warn', _tr('布局'), _tr('{name} 超出厂房分区范围', name=s.name), s.id)
    # 人员覆盖
    from .models.people import ROLE_NEED
    crew = kinds.get('crew', [None])[0]
    covered = {sid for w in (crew.workers if crew else []) for sid in w['stations']}
    for s in p.stations.values():
        if s.kind in ROLE_NEED and s.kind in ('cnc', 'furnace', 'molding', 'shotblast') and s.id not in covered:
            add('warn', _tr('人员'), _tr('{name} 需要操作工但没有分配岗位（会被视为有人，产能偏乐观）', name=s.name), s.id)
    # AGV 站点
    agv = kinds.get('agv', [None])[0]
    if agv:
        for k, (nx, ny) in agv.nodes.items():
            for s, a0, a1, b0, b1 in boxes:
                if a0 < nx < a1 and b0 < ny < b1:
                    add('warn', _tr('物流'), _tr('AGV 站点 {k} 落在 {name} 占地内，小车会穿过设备', k=k, name=s.name), s.id)
    # Modbus 从站地址
    units = {}
    for s in p.stations.values():
        u = s.cfg.get('modbus_unit')
        if u:
            if u in units:
                add('error', _tr('协议'), _tr('Modbus 从站地址 {u} 被 {v} 和 {name} 重复使用', u=u, v=units[u], name=s.name), s.id)
            units[u] = s.name
    route = __import__('vfactory.tracking', fromlist=['route']).route(p)
    return {'ok': not any(i['level'] == 'error' for i in issues), 'issues': issues, 'route': route,
            'summary': {'error': sum(i['level'] == 'error' for i in issues), 'warn': sum(i['level'] == 'warn' for i in issues)}}


def _bj_now():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')


def _version_resolver(pid):
    """方案里"模型版本 #n / 当前草稿"→ 模型。"""
    def resolve(n):
        from .editor_api import get_version, load_draft
        if n in ('draft', None, ''):
            d = load_draft(pid)
            if not d or not d.get('model'):
                raise ValueError(_tr('没有未应用的草稿'))
            return d['model']
        return get_version(pid, int(n))['model']
    return resolve


def _check_variant(v, resolve):
    """新建实验时检查方案：版本号要存在、版本改动放在第一条、班次时间格式。"""
    import re
    chs = v.get('changes') or []
    for i, c in enumerate(chs):
        t = c.get('type')
        if t == 'version':
            if i != 0:
                raise HTTPException(400, _tr('方案「{get}」：模型版本必须是第一条改动', get=v.get('name')))
            try:
                resolve(c.get('n'))
            except HTTPException:
                raise HTTPException(400, _tr('方案「{get}」：没有模型版本 #{get2}', get=v.get('name'), get2=c.get('n')))
            except (ValueError, TypeError) as e:
                raise HTTPException(400, _tr('方案「{get}」：{e}', get=v.get('name'), e=e))
        elif t == 'plan':
            for x in (c.get('shifts') or []) + (c.get('breaks') or []):
                if not re.match(r'^\d{1,2}:\d{2}$', str(x.get('start', ''))) or not re.match(r'^\d{1,2}:\d{2}$', str(x.get('end', ''))):
                    raise HTTPException(400, _tr('方案「{get}」：班次/休息的起止时间应为 HH:MM', get=v.get('name')))
            wd = c.get('workdays')
            if wd is not None and (not isinstance(wd, list) or not all(str(d).isdigit() and 1 <= int(d) <= 7 for d in wd)):
                raise HTTPException(400, _tr('方案「{get}」：工作日用 1–7 表示周一到周日', get=v.get('name')))


def print_html(name, r):
    esc = lambda x: '' if x is None else str(x).replace('&', '&amp;').replace('<', '&lt;')
    util = ''.join(f"<tr><td>{esc(u['name'])}</td><td>{u['run'] * 100:.1f}%</td><td>{u.get('故障停机', 0) * 100:.1f}%</td><td>{u.get('待机/等待', 0) * 100:.1f}%</td>"
                   f"<td>{u.get('换型/换刀', 0) * 100:.1f}%</td><td>{u.get('计划停机', 0) * 100:.1f}%</td></tr>" for u in r['util'])
    hours = ''.join(f"<tr><td>{x['time']}</td><td>{x['castings']}</td><td>{x['good']}</td><td>{x['scrap']}</td><td>{x['energy']}</td></tr>" for x in r['series'][-48:])
    fs = ''.join(f'<li>{esc(f)}</li>' for f in r['findings'])
    k = [(_tr('浇注/来料'), r['castings']), (_tr('合格入库'), r['good']), (_tr('废品率'), f"{r['scrap_rate'] * 100:.2f}%"), (_tr('小时产出'), r['good_per_h']), (_tr('用电 kWh'), r['energy_total']),
         (_tr('电炉吨耗'), r['kwh_per_t'] or '—'), (_tr('平均在制品'), r['wip_avg']), (_tr('平均生产周期 h'), r['lead'].get('mean_h') if r['lead'] else '—')]
    kp = ''.join(f'<div class="k"><small>{a}</small><b>{b}</b></div>' for a, b in k)
    return _tr('<!doctype html><html><head><meta charset="utf-8"><title>运行报告 {esc}</title><style>\nbody{{font-family:\'Microsoft YaHei\',sans-serif;margin:28px;color:#222}}h1{{font-size:20px;margin:0}}.hd{{display:flex;justify-content:space-between;border-bottom:3px solid #f2c94c;padding-bottom:8px;margin-bottom:12px}}\n.ks{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.k{{border:1px solid #ddd;border-radius:6px;padding:6px 10px}}.k small{{color:#777;display:block}}.k b{{font-size:18px}}\ntable{{border-collapse:collapse;width:100%;margin:6px 0 16px}}td,th{{border:1px solid #ccc;padding:3px 6px;font-size:12px;text-align:left}}th{{background:#f6f2e6}}h3{{margin:16px 0 4px}}\n</style></head><body><div class="hd"><div><h1>{esc} · 运行报告</h1><div>统计区间（仿真时间）：{v} ~ {to}，{hours} 小时</div><div><small>导出时间（北京时间）：{v2}</small></div></div><div>蜂元虚拟工厂<br><small>蜂元科技（郑州）有限责任公司</small></div></div>\n<div class="ks">{kp}</div><h3>结论</h3><ul>{fs}</ul><h3>设备利用</h3><table><tr><th>设备</th><th>运行</th><th>故障停机</th><th>待机/等待</th><th>换型/换刀</th><th>计划停机</th></tr>{util}</table>\n<h3>每小时产出</h3><table><tr><th>时间</th><th>浇注</th><th>合格入库</th><th>报废</th><th>用电 kWh</th></tr>{hours2}</table>\n<script>setTimeout(()=>window.print(),500)</script></body></html>', esc=esc(name), v=r['from'], to=r['to'], hours=r['hours'], v2=_bj_now(), kp=kp, fs=fs, util=util, hours2=hours)
