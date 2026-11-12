"""数据库访问：SQLAlchemy Core。默认 SQLite（<HM_DATA>/mes.db）。

所有写操作都在事件循环线程里同步执行（单进程），采集和接口不会并发写同一行。
"""
from .i18n import _tr
import json
import os
import re
from datetime import date, datetime, timedelta

import sqlalchemy as sa

from .schema import BY_NAME, TABLES, metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # 虚拟工厂目录（vfmes 包的上一级）
# 可写数据目录：客户端用 HM_DATA 给每个工厂一份（<客户端数据目录>/mes/<工厂>）；单独跑时默认 <ROOT>/data/mes-dev
DATA = os.path.abspath(os.environ['HM_DATA']) if os.environ.get('HM_DATA') else os.path.join(ROOT, 'data', 'mes-dev')
engine: sa.Engine = None  # type: ignore


def init(url: str | None = None):
    global engine
    url = url or os.environ.get('MES_DB') or 'sqlite:///' + os.path.join(DATA, 'mes.db').replace('\\', '/')
    if url.startswith('sqlite:///'):
        os.makedirs(os.path.dirname(url[10:]), exist_ok=True)
    engine = sa.create_engine(url, future=True, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {})
    if url.startswith('sqlite'):
        @sa.event.listens_for(engine, 'connect')
        def _pragma(conn, _):
            c = conn.cursor()
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('PRAGMA synchronous=NORMAL')
            c.close()
    metadata.create_all(engine)
    return engine


class Clock:
    """数据时钟：以采集到的数据时间为准（虚拟工厂会加速运行）；没有数据时用系统时间。"""
    data_now: datetime | None = None
    _behind = 0          # 连续收到明显更早的时间的次数

    def now(self) -> datetime:
        return self.data_now or datetime.now().replace(microsecond=0)

    def feed(self, ts: datetime):
        if not ts:
            return
        if self.data_now is None or ts > self.data_now:
            self.data_now, self._behind = ts, 0
        elif (self.data_now - ts).total_seconds() > 2 * 3600:
            # 数据源重置（如虚拟工厂点了"重置"，仿真时间回到起点）：持续收到早 2 小时以上的时间，就跟着回退
            self._behind += 1
            if self._behind >= 30:
                self.data_now, self._behind = ts, 0
        else:
            self._behind = 0


clock = Clock()


def parse_dt(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).replace('T', ' ').replace('Z', '')[:19]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def coerce(entity: str, row: dict) -> dict:
    """把前端传来的值按字段类型转换。"""
    e = BY_NAME[entity]
    out = {}
    for f in e.fields:
        if f.name not in row:
            continue
        v = row[f.name]
        if v == '' and f.t not in ('str', 'text'):
            v = None
        try:
            if v is None:
                pass
            elif f.t in ('int', 'ref'):
                v = int(float(v))
            elif f.t == 'float':
                v = float(v)
            elif f.t == 'bool':
                v = v if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'yes', 'on', '是')
            elif f.t == 'datetime':
                v = parse_dt(v)
            elif f.t == 'date':
                d = parse_dt(v)
                v = d.date() if d else None
            elif f.t == 'json' and isinstance(v, str):
                v = json.loads(v) if v.strip() else None
        except (TypeError, ValueError):
            raise ValueError(_tr('{label} 格式不对：{v}', label=f.label, v=v))
        out[f.name] = v
    return out


def next_code(conn, entity: str, pattern: str, when: datetime | None = None) -> str:
    """按格式生成单号：{d}=yymmdd，{n:03}=当天流水。"""
    when = when or clock.now()
    prefix = pattern.split('{n')[0].format(d=when.strftime('%y%m%d'))
    t = TABLES[entity]
    last = conn.execute(sa.select(t.c.code).where(t.c.code.like(prefix + '%')).order_by(t.c.code.desc()).limit(1)).scalar()
    n = 1
    if last:
        m = re.search(r'(\d+)$', last[len(prefix):] or '')
        n = int(m.group(1)) + 1 if m else 1
    return pattern.format(d=when.strftime('%y%m%d'), n=n)


def insert(conn, entity: str, row: dict, raw=False) -> int:
    e, t = BY_NAME[entity], TABLES[entity]
    data = row if raw else coerce(entity, row)
    for f in e.fields:
        if f.auto and not data.get(f.name):
            data[f.name] = next_code(conn, entity, f.auto)
        if f.name not in data and f.default is not None:
            data[f.name] = f.default
    now = clock.now()
    data.setdefault('created_at', now)
    data['updated_at'] = now
    return conn.execute(t.insert().values(**data)).inserted_primary_key[0]


def update(conn, entity: str, rid: int, row: dict, raw=False):
    t = TABLES[entity]
    data = row if raw else coerce(entity, row)
    data['updated_at'] = clock.now()
    conn.execute(t.update().where(t.c.id == rid).values(**data))


def get(conn, entity: str, rid=None, **where) -> dict | None:
    t = TABLES[entity]
    q = sa.select(t)
    if rid is not None:
        q = q.where(t.c.id == rid)
    for k, v in where.items():
        q = q.where(t.c[k] == v)
    r = conn.execute(q.limit(1)).mappings().first()
    return dict(r) if r else None


def rows(conn, entity: str, *conds, order=None, limit=None, **where) -> list[dict]:
    t = TABLES[entity]
    q = sa.select(t)
    for c in conds:
        q = q.where(c)
    for k, v in where.items():
        q = q.where(t.c[k] == v)
    if order is not None:
        q = q.order_by(*order) if isinstance(order, (tuple, list)) else q.order_by(order)
    if limit:
        q = q.limit(limit)
    return [dict(r) for r in conn.execute(q).mappings()]


def setting(conn, key, default=None):
    r = get(conn, 'setting', key=key)
    return r['value'] if r else default


def set_setting(conn, key, value, remark=''):
    r = get(conn, 'setting', key=key)
    if r:
        update(conn, 'setting', r['id'], {'value': str(value)}, raw=True)
    else:
        insert(conn, 'setting', {'key': key, 'value': str(value), 'remark': remark}, raw=True)


def jsonable(v):
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, date):
        return v.isoformat()
    return v


def day_range(d: date | str | None = None):
    if d is None:
        d = clock.now().date()
    if isinstance(d, str):
        d = parse_dt(d).date()
    s = datetime(d.year, d.month, d.day)
    return s, s + timedelta(days=1)
