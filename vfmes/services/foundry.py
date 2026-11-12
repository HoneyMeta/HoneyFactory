"""铸造包：炉次记录、炉料倒冲、炉次分析。"""
from ..i18n import _tr
import sqlalchemy as sa
from fastapi import APIRouter, Depends

from .. import db
from ..auth import current_user
from ..crud import attach_labels, out
from ..schema import TABLES

router = APIRouter()
ELEMS = ('C', 'Si', 'Mn', 'S', 'P')
BASE_RATIO = {'CM-PIG': 45, 'CM-STEEL': 25, 'CM-RET': 28, 'CM-CARB': 1, 'CM-FESI': 1}     # 常规配比 %


def on_heat(c, eid, ev, ts):
    code = ev['heat']
    h = db.get(c, 'heat', code=code)
    if ev.get('phase') == 'start':
        if not h:
            db.insert(c, 'heat', {'code': code, 'furnace': eid, 'start': ts, 'status': 'melting', 'castings': 0, 'scrap': 0}, raw=True)
    elif ev.get('phase') == 'end':
        kg = ev.get('kg') or 0
        vals = {'end': ts, 'kwh': ev.get('kwh'), 'kg': kg, 'kwh_per_t': round(ev['kwh'] / (kg / 1000), 1) if kg and ev.get('kwh') else None,
                'lining': ev.get('lining'), 'status': 'done'}
        if h:
            db.update(c, 'heat', h['id'], vals, raw=True)
        else:
            db.insert(c, 'heat', {'code': code, 'furnace': eid, **vals}, raw=True)
        backflush(c, code, kg)


def on_chem(c, ev, ts):
    h = db.get(c, 'heat', code=ev['heat'])
    vals = {k: ev.get(k) for k in ELEMS} | {'CE': ev.get('CE'), 'tap_temp': ev.get('temp'), 'status': 'holding'}
    if h:
        db.update(c, 'heat', h['id'], vals, raw=True)


def backflush(c, heat_code, kg):
    """炉次结束按常规配比倒冲炉料消耗（出库到原材料库，炉料台账的库存跟着减）。"""
    if not kg:
        return
    from .warehouse import move
    wh = db.get(c, 'warehouse', wtype='raw')
    if not wh:
        return
    for m in db.rows(c, 'charge_material'):
        pct = BASE_RATIO.get(m['code'], 0)
        if not pct:
            continue
        mat = db.get(c, 'material', code=m['code'])
        if mat:
            move(c, 'out', mat['id'], round(kg * pct / 100 / 1000, 3), wh['id'], ref=heat_code, who=_tr('系统倒冲'), reason=_tr('炉次炉料消耗'))
        t = TABLES['charge_material']
        c.execute(t.update().where(t.c.id == m['id']).values(stock_t=sa.func.coalesce(t.c.stock_t, 0) - kg * pct / 100 / 1000))


@router.get('/api/foundry/heats')
def heats(n: int = 60, user=Depends(current_user)):
    ht = TABLES['heat']
    with db.engine.connect() as c:
        rows = db.rows(c, 'heat', order=ht.c.id.desc(), limit=n)
        attach_labels(c, 'heat', rows)
        tr = TABLES['treatment_rec']
        mg = {r[0]: r[1] for r in c.execute(sa.select(tr.c.heat_code, sa.func.avg(tr.c.mg)).group_by(tr.c.heat_code)).all()}
    for r in rows:
        r['mg_avg'] = round(mg.get(r['code']) or 0, 4) or None
        r['scrap_rate'] = round((r['scrap'] or 0) / r['castings'], 4) if r['castings'] else None
    done = [r for r in rows if r['status'] == 'done' and r['kwh_per_t']]
    avg = {'kwh_per_t': round(sum(r['kwh_per_t'] for r in done) / len(done), 1) if done else None,
           'CE': round(sum(r['CE'] for r in rows if r['CE']) / max(1, sum(1 for r in rows if r['CE'])), 3)}
    return {'rows': out(list(reversed(rows))), 'avg': avg}
