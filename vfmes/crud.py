"""通用增删改查：/api/e/<实体>，以及实体动作 /api/e/<实体>/<id>/do/<动作>。"""
from .i18n import _tr
import csv
import io

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import db
from .auth import current_user, require_write
from .schema import BY_NAME, TABLES

router = APIRouter()
ACTIONS: dict = {}          # (实体, 动作) -> fn(conn, row, body, user) -> dict|None
HOOKS: dict = {}            # (实体, 'after_save') -> fn(conn, id, user)


def action(entity, name):
    def deco(fn):
        ACTIONS[(entity, name)] = fn
        return fn
    return deco


def label_of(r: dict) -> str:
    for a, b in (('code', 'name'), ('sn', None), ('username', 'name'), ('title', None), ('name', None), ('code', None), ('ladle', None)):
        if r.get(a):
            return f"{r[a]} {r[b]}" if b and r.get(b) and r.get(b) != r.get(a) else str(r[a])
    return f"#{r['id']}"


def attach_labels(conn, entity: str, items: list[dict]):
    e = BY_NAME[entity]
    for f in e.fields:
        if f.t != 'ref':
            continue
        ids = {r[f.name] for r in items if r.get(f.name)}
        if not ids:
            continue
        t = TABLES[f.ref]
        lab = {r['id']: label_of(dict(r)) for r in conn.execute(sa.select(t).where(t.c.id.in_(ids))).mappings()}
        for r in items:
            if r.get(f.name):
                r[f.name + '__label'] = lab.get(r[f.name], f'#{r[f.name]}')
    return items


def out(items):
    return [{k: db.jsonable(v) for k, v in r.items()} for r in items]


def _ent(entity):
    if entity not in BY_NAME:
        raise HTTPException(404, _tr('没有实体 {entity}', entity=entity))
    return BY_NAME[entity], TABLES[entity]


def build_query(entity, params: dict):
    e, t = _ent(entity)
    q = sa.select(t)
    conds = []
    kw = (params.get('q') or '').strip()
    if kw:
        cols = [t.c[f.name] for f in e.fields if f.search] or [t.c[f.name] for f in e.fields if f.t == 'str'][:3]
        conds.append(sa.or_(*[c.ilike(f'%{kw}%') for c in cols]))
    for k, v in params.items():
        if k.startswith('f_') and v not in ('', None):
            name = k[2:]
            op = 'eq'
            if name.endswith('__from'):
                name, op = name[:-6], 'ge'
            elif name.endswith('__to'):
                name, op = name[:-4], 'lt'
            if name not in t.c:
                continue
            f = next((x for x in e.fields if x.name == name), None)
            val = db.coerce(entity, {name: v})[name] if f else v
            conds.append(t.c[name] == val if op == 'eq' else t.c[name] >= val if op == 'ge' else t.c[name] < val)
    for c in conds:
        q = q.where(c)
    sort = params.get('sort') or e.order
    desc = sort.startswith('-')
    col = t.c.get(sort.lstrip('-'), t.c.id)
    q = q.order_by(col.desc() if desc else col.asc(), t.c.id.desc() if desc else t.c.id.asc())
    return q, conds, t


@router.get('/api/e/{entity}.csv', response_class=PlainTextResponse)
def export(entity: str, request: Request, user=Depends(current_user)):
    """导出 CSV（要放在 /api/e/{entity} 前面，不然 'xxx.csv' 会被当成实体名）。"""
    e, _ = _ent(entity)
    q, _, _ = build_query(entity, dict(request.query_params))
    with db.engine.connect() as c:
        items = attach_labels(c, entity, [dict(r) for r in c.execute(q.limit(50000)).mappings()])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f.label for f in e.fields])
    for r in items:
        w.writerow([r.get(f.name + '__label', db.jsonable(r.get(f.name))) if f.t == 'ref' else (f.enum or {}).get(r.get(f.name), db.jsonable(r.get(f.name)))
                    for f in e.fields])
    return PlainTextResponse('﻿' + buf.getvalue(), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': f'attachment; filename={entity}.csv'})


@router.get('/api/e/{entity}')
def list_(entity: str, request: Request, page: int = 1, size: int = 20, user=Depends(current_user)):
    params = dict(request.query_params)
    q, conds, t = build_query(entity, params)
    with db.engine.connect() as c:
        cnt = sa.select(sa.func.count()).select_from(t)
        for x in conds:
            cnt = cnt.where(x)
        total = c.execute(cnt).scalar()
        size = max(1, min(size, 2000))
        items = [dict(r) for r in c.execute(q.limit(size).offset((page - 1) * size)).mappings()]
        attach_labels(c, entity, items)
    return {'total': total, 'items': out(items)}


@router.get('/api/e/{entity}/{rid}')
def get_(entity: str, rid: int, user=Depends(current_user)):
    _ent(entity)
    with db.engine.connect() as c:
        r = db.get(c, entity, rid)
        if not r:
            raise HTTPException(404, _tr('记录不存在'))
        attach_labels(c, entity, [r])
        kids = {}
        for ch in BY_NAME[entity].children:
            child, fk = ch[0], ch[1]
            val = r.get(ch[2]) if len(ch) > 2 else rid
            ct = TABLES[child]
            items = [dict(x) for x in c.execute(sa.select(ct).where(ct.c[fk] == val).order_by(*(
                [ct.c.seq] if 'seq' in ct.c else [ct.c.id.desc()])).limit(500)).mappings()]
            kids[child] = out(attach_labels(c, child, items))
    return {'item': out([r])[0], 'children': kids}


@router.post('/api/e/{entity}')
def create(entity: str, body: dict = Body(...), user=Depends(current_user)):
    e, _ = _ent(entity)
    if e.internal:
        raise HTTPException(400, _tr('{label}由系统自动记录，不能手工新增', label=e.label))
    require_write(user, entity)
    with db.engine.begin() as c:
        for f in e.fields:
            if f.req and body.get(f.name) in (None, '') and not f.auto:
                raise HTTPException(400, _tr('请填写{label}', label=f.label))
        try:
            rid = db.insert(c, entity, {k: v for k, v in body.items() if k not in ('id', 'created_at', 'updated_at')})
        except sa.exc.IntegrityError:
            raise HTTPException(400, _tr('编码重复'))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        h = HOOKS.get((entity, 'after_save'))
        if h:
            h(c, rid, user)
    return {'ok': True, 'id': rid}


@router.put('/api/e/{entity}/{rid}')
def update_(entity: str, rid: int, body: dict = Body(...), user=Depends(current_user)):
    e, _ = _ent(entity)
    require_write(user, entity)
    ro = {f.name for f in e.fields if f.ro}
    data = {k: v for k, v in body.items() if k not in ro and k not in ('id', 'created_at', 'updated_at') and not k.endswith('__label')}
    with db.engine.begin() as c:
        if not db.get(c, entity, rid):
            raise HTTPException(404, _tr('记录不存在'))
        try:
            db.update(c, entity, rid, data)
        except sa.exc.IntegrityError:
            raise HTTPException(400, _tr('编码重复'))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        h = HOOKS.get((entity, 'after_save'))
        if h:
            h(c, rid, user)
    return {'ok': True}


@router.delete('/api/e/{entity}/{rid}')
def delete_(entity: str, rid: int, user=Depends(current_user)):
    e, t = _ent(entity)
    require_write(user, entity)
    with db.engine.begin() as c:
        # 被引用的不让删
        for other in BY_NAME.values():
            for f in other.fields:
                if f.t == 'ref' and f.ref == entity:
                    ot = TABLES[other.name]
                    n = c.execute(sa.select(sa.func.count()).select_from(ot).where(ot.c[f.name] == rid)).scalar()
                    if n:
                        raise HTTPException(400, _tr('还有 {n} 条{label}引用它，不能删除', n=n, label=other.label))
        c.execute(t.delete().where(t.c.id == rid))
    return {'ok': True}


@router.post('/api/e/{entity}/{rid}/do/{act}')
def do_action(entity: str, rid: int, act: str, body: dict = Body(default={}), user=Depends(current_user)):
    fn = ACTIONS.get((entity, act))
    if not fn:
        raise HTTPException(404, _tr('没有这个操作'))
    require_write(user, entity)
    with db.engine.begin() as c:
        r = db.get(c, entity, rid)
        if not r:
            raise HTTPException(404, _tr('记录不存在'))
        res = fn(c, r, body or {}, user)
    return {'ok': True, **(res or {})}
