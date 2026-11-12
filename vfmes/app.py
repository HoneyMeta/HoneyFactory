"""应用入口：登录、元数据、各业务接口、采集启动。只有接口：页面在蜂元虚拟工厂自己的网页里（web/src/mes/，经客户端本地服务的 /api/mes/* 转发，5.0.1）。"""
from .i18n import _tr
import logging

from fastapi import Body, Depends, FastAPI, HTTPException

from . import auth, crud, db, edu
from .auth import current_user
from .collector import COLLECTOR
from .db import clock
from .schema import ROLES, spec_json
from .services import equipment, foundry, machining, ops, production, quality, views, warehouse

log = logging.getLogger('mes')


def build_app():
    app = FastAPI(title=edu.BRAND, version='1.0.0')
    for r in (crud.router, production.router, quality.router, equipment.router, warehouse.router, foundry.router, machining.router, views.router, ops.router):
        app.include_router(r)
    edu.install(app)

    @app.on_event('startup')
    async def _start():
        await COLLECTOR.start()

    @app.post('/api/login')
    def login(body: dict = Body(...)):
        """账号密码登录（本机学员用一次性登录票，见 edu.py；其他账号都停用了，这里总是 401）。"""
        with db.engine.connect() as c:
            u = db.get(c, 'sys_user', username=(body.get('username') or '').strip())
        if not u or not u['active'] or not auth.check_pw(body.get('password') or '', u['password_hash']):
            raise HTTPException(401, _tr('账号或密码不对'))
        return {'token': auth.make_token(u), 'user': {'username': u['username'], 'name': u['name'], 'roles': u['roles']}}

    @app.get('/api/me')
    def me(user=Depends(current_user)):
        with db.engine.connect() as c:
            company = db.setting(c, 'company', '')
        return {**{k: db.jsonable(v) for k, v in user.items()}, 'company': company, 'now': db.jsonable(clock.now()), 'edu': edu.EDU,
                'writable': sorted({e['module'] for e in spec_json() if auth.can_write(user, e['name'])})}

    @app.get('/api/meta')
    def meta(user=Depends(current_user)):
        from .i18n import label, lang
        ents = [{**e, 'module_label': label(e.get('module') or '')} for e in spec_json()]     # module stays the key; module_label for display
        return {'entities': ents, 'roles': ROLES, 'edu': edu.EDU, 'lang': lang(), 'langs': ['en', 'zh-CN']}

    @app.get('/api/clock')
    def clk():
        return {'now': db.jsonable(clock.now()), 'data': clock.data_now is not None}

    @app.get('/api/collector')
    def coll(user=Depends(current_user)):
        from .ingest import ING
        return {'status': {str(k): v for k, v in COLLECTOR.status.items()}, 'stats': dict(ING.stats), 'now': db.jsonable(clock.now())}

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'], include_in_schema=False)
    def no_api(path: str):
        raise HTTPException(404, _tr('没有这个接口'))     # 未知接口一律 404

    from .i18n import install
    install(app)                                 # request language (X-Lang from the client proxy), English JSON texts
    return app
