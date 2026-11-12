"""安灯与物料申请：实体动作、安灯看板。"""
from ..i18n import _tr
import sqlalchemy as sa
from fastapi import APIRouter, Depends

from .. import db
from ..auth import current_user
from ..crud import HOOKS, action, attach_labels, out
from ..db import clock
from ..schema import TABLES

router = APIRouter()


# ---------------- 实体动作 ----------------
@action('andon', 'respond')
def _andon_respond(c, r, body, user):
    if r['status'] == 'closed':
        return {'msg': _tr('已经关闭')}
    db.update(c, 'andon', r['id'], {'status': 'responding', 'responder': user['name'] or user['username'], 'response_at': clock.now()}, raw=True)
    return {'msg': _tr('已响应')}


@action('andon', 'close')
def _andon_close(c, r, body, user):
    db.update(c, 'andon', r['id'], {'status': 'closed', 'closed_at': clock.now(), 'close_note': body.get('note') or _tr('已处理'),
                                     'responder': r['responder'] or user['name'] or user['username']}, raw=True)
    return {'msg': _tr('已关闭')}


@action('material_request', 'issue')
def _mr_issue(c, r, body, user):
    from .warehouse import move
    if r['status'] != 'submitted':
        return {'msg': _tr('这张申请已处理')}
    wh = r['warehouse']
    if not wh:
        st = TABLES['stock']
        wh = c.execute(sa.select(st.c.warehouse).where((st.c.material == r['material']) & (st.c.qty > 0)).order_by(st.c.qty.desc()).limit(1)).scalar()
    if wh:
        move(c, 'out', r['material'], r['qty'], wh, ref=r['code'], who=user['name'] or user['username'], reason=_tr('物料申请发料'))
    db.update(c, 'material_request', r['id'], {'status': 'issued', 'warehouse': wh}, raw=True)
    return {'msg': _tr('已发料') if wh else _tr('已标记发料（没有找到有库存的仓库，未过账）')}


@action('material_request', 'reject')
def _mr_reject(c, r, body, user):
    db.update(c, 'material_request', r['id'], {'status': 'rejected', 'reason': (r['reason'] or '') + _tr(' | 退回：{v}', v=body.get('note') or '')}, raw=True)
    return {'msg': _tr('已退回')}


# ---------------- 安灯看板 ----------------
@router.get('/api/andon/board')
def andon_board(user=Depends(current_user)):
    t = TABLES['andon']
    with db.engine.connect() as c:
        open_ = db.rows(c, 'andon', t.c.status != 'closed', order=t.c.id.desc(), limit=50)
        attach_labels(c, 'andon', open_)
        closed = db.rows(c, 'andon', t.c.status == 'closed', order=t.c.id.desc(), limit=10)
        attach_labels(c, 'andon', closed)
    return {'open': out(open_), 'closed': out(closed), 'now': db.jsonable(clock.now())}


def _andon_fill(c, rid, user):
    """手工发起的安灯：补上发起人和时间。"""
    a = db.get(c, 'andon', rid)
    vals = {}
    if not a['raised_by']:
        vals['raised_by'] = user.get('name') or user['username']
    if not a['raised_at']:
        vals['raised_at'] = clock.now()
    if not a['status']:
        vals['status'] = 'open'
    if vals:
        db.update(c, 'andon', rid, vals, raw=True)


HOOKS[('andon', 'after_save')] = _andon_fill
