"""运行控制：状态（运行 / 暂停 / 编辑）、单步、运行到、断点、快照回放。

挂在 PlantRuntime 上（rt.ctl）。不改仿真内核：只用 Plant.step_hooks / event_hooks。
断点条件（cond）：
  {kind:'state', id, state}                 设备进入某状态（Stopped/Blocked/Starved/Setup/Idle/Executing）
  {kind:'state_for', id, state, minutes}    设备处于某状态超过 N 分钟
  {kind:'alarm', id?}                       出现报警（不填 id 表示任意设备）
  {kind:'buffer', id, op, value}            缓存/队列件数比较
  {kind:'kpi', key, op, value}              全厂指标比较（good、scrap、castings、machined、shipped…）
  {kind:'tag', id, tag, op, value}          点位比较
  {kind:'event', id?, ekind?, text?}        事件日志里出现（fault/alarm/repair/tool/plan/scenario…）
  {kind:'time', at:'YYYY-MM-DD HH:MM'}      到达某时刻
"""
from .i18n import _tr, label
import asyncio
import json
import operator
import time
import zlib
from collections import deque
from datetime import datetime

from fastapi import Body, HTTPException, Request

from . import store

OPS = {'>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le, '==': operator.eq, '!=': operator.ne}
STATE_CN = {'Executing': '运行', 'Idle': '待机', 'Starved': '缺料', 'Blocked': '堵料', 'Setup': '换型', 'Stopped': '停机', 'Planned': '计划停机'}
KPI_CN = {'good': '合格入库', 'scrap': '报废', 'castings': '铸件/来料', 'machined': '机加', 'shipped': '发运', 'escape': '漏检'}
SNAP_EVERY = 60          # 仿真秒：每分钟一份回放快照
SNAP_KEEP = 24 * 60      # 保留 24 小时


class Ctl:
    def __init__(self, rt, keep=None):
        self.rt = rt
        p = rt.plant
        self.bps = list(keep.bps) if keep else []
        self.hit = None
        self.snaps = deque(maxlen=SNAP_KEEP)
        self.since = {}
        self.prev = {}
        self.fresh = False            # 刚重置，还没开始运行 → 显示"编辑"状态
        self.busy = None              # 运行到… 的进度
        self._task = None
        self._last_snap = -1e9
        p.step_hooks.append(self.on_step)
        p.event_hooks.append(self.on_event)
        self.snap()

    # ---------- 状态 ----------
    def mode(self):
        p = self.rt.plant
        if self.busy:
            return 'running'
        if p.paused:
            return 'edit' if self.fresh else 'paused'
        return 'running'

    def status(self):
        s = self.snaps
        return {'mode': self.mode(), 'hit': self.hit, 'busy': self.busy, 'bps': sum(1 for b in self.bps if b.get('enabled', True)),
                'replay': [s[0][0], s[-1][0]] if s else None, 'replay_time': [s[0][1], s[-1][1]] if s else None}

    # ---------- 钩子 ----------
    def on_step(self):
        p = self.rt.plant
        it = int(p.t)
        if p.t - self._last_snap >= SNAP_EVERY:
            self.snap()
        if it % 5:
            return
        for st in p.stations.values():
            if self.since.get(st.id, (None,))[0] != st.state:
                self.since[st.id] = (st.state, p.t)
        for b in self.bps:
            if b.get('enabled', True) and b['cond'].get('kind') != 'event':
                self._check(b)

    def on_event(self, ev):
        for b in self.bps:
            c = b['cond']
            if not b.get('enabled', True) or c.get('kind') not in ('event', 'alarm'):
                continue
            if c.get('kind') == 'alarm':
                if ev.get('kind') == 'alarm' and (not c.get('id') or ev.get('station') == c['id']):
                    self._fire(b, _tr('{get} 报警：{get2}', get=ev.get('station'), get2=ev.get('msg')), ev.get('station'))
                continue
            if c.get('id') and ev.get('station') != c['id']:
                continue
            if c.get('ekind') and ev.get('kind') != c['ekind']:
                continue
            if c.get('text') and c['text'] not in (ev.get('msg') or ''):
                continue
            self._fire(b, f"{ev.get('station')} {ev.get('msg')}", ev.get('station'))

    # ---------- 条件 ----------
    def value(self, c):
        p = self.rt.plant
        k = c.get('kind')
        if k == 'state':
            st = p.stations.get(c.get('id'))
            return bool(st and st.state == c.get('state'))
        if k == 'state_for':
            st = p.stations.get(c.get('id'))
            if not st or st.state != c.get('state'):
                return False
            s = self.since.get(st.id)
            return bool(s and s[0] == st.state and p.t - s[1] >= float(c.get('minutes', 5)) * 60)
        if k == 'buffer':
            b = p.buffers.get(c.get('id'))
            return b is not None and OPS.get(c.get('op', '<'), operator.lt)(len(b), float(c.get('value', 0)))
        if k == 'kpi':
            v = p.kpi.get(c.get('key'))
            return isinstance(v, (int, float)) and OPS.get(c.get('op', '>='), operator.ge)(v, float(c.get('value', 0)))
        if k == 'tag':
            st = p.stations.get(c.get('id'))
            tg = st.tags.get(c.get('tag')) if st else None
            if tg is None or not isinstance(tg.value, (int, float)):
                return False
            return OPS.get(c.get('op', '>'), operator.gt)(tg.value, float(c.get('value', 0)))
        if k == 'time':
            try:
                return p.now() >= datetime.strptime(c['at'], '%Y-%m-%d %H:%M')
            except (KeyError, ValueError):
                return False
        return False

    def _check(self, b):
        v = self.value(b['cond'])
        was = self.prev.get(b['id'], None)
        self.prev[b['id']] = v
        if v and was is False:          # 只在由假变真时触发，避免一直命中
            self._fire(b, describe(b['cond'], self.rt.plant), b['cond'].get('id'))

    def _fire(self, b, msg, station=None):
        p = self.rt.plant
        b['hits'] = b.get('hits', 0) + 1
        if b.get('once'):
            b['enabled'] = False
        self.hit = {'bp': b['id'], 'name': b.get('name') or describe(b['cond'], p), 'msg': msg, 'station': station, 't': p.t, 'time': p.clock_str()}
        p.paused = True
        p.log(station or 'PLANT', 'breakpoint', _tr('断点命中：{name}', name=self.hit["name"]))

    # ---------- 快照 ----------
    def snap(self):
        p = self.rt.plant
        self._last_snap = p.t
        self.snaps.append((round(p.t, 1), p.clock_str(), zlib.compress(json.dumps(p.snapshot(), ensure_ascii=False, default=str).encode(), 3)))

    def at(self, t):
        if not self.snaps:
            return None
        best = None
        for s in self.snaps:
            if s[0] <= t:
                best = s
            else:
                break
        best = best or self.snaps[0]
        return json.loads(zlib.decompress(best[2]))

    # ---------- 单步 / 运行到 ----------
    def step(self, seconds=None, until_event=False):
        p = self.rt.plant
        p.paused = True
        self.fresh = False
        self.hit = None
        if until_event:
            seq = p.event_seq
            states = {s.id: s.state for s in p.stations.values()}
            for _ in range(3600):
                p.step()
                if p.event_seq != seq or any(states.get(s.id) != s.state for s in p.stations.values()):
                    break
        else:
            for _ in range(int(max(1, min(3600, seconds or 60)) / p.dt)):
                p.step()
        p.paused = True
        return p.clock_str()

    def run_to(self, cond=None, hours=None):
        """后台推进，直到条件成立 / 到时间 / 断点 / 取消；结束后暂停。"""
        if self._task and not self._task.done():
            raise HTTPException(409, _tr('正在运行到…，先取消'))
        p = self.rt.plant
        limit = float(hours or 24) * 3600
        target = None
        if cond and cond.get('kind') == 'time':
            try:
                target = (datetime.strptime(cond['at'], '%Y-%m-%d %H:%M') - p.t0).total_seconds()
            except (KeyError, ValueError):
                raise HTTPException(400, _tr('时间格式应为 YYYY-MM-DD HH:MM'))
            if target <= p.t:
                raise HTTPException(400, _tr('这个时刻已经过去了'))
            limit = target - p.t
        desc = describe(cond, p) if cond else _tr('{v:g} 小时后', v=limit / 3600)
        self.busy = {'goal': desc, 'progress': 0.0, 'started': p.clock_str()}
        self.fresh = False
        self.hit = None
        t_start = p.t

        async def go():
            p.paused = True
            done_msg = ''
            try:
                while True:
                    for _ in range(600):
                        p.step()
                        if self.hit:
                            break
                    self.busy['progress'] = round(min(1.0, (p.t - t_start) / limit), 3)
                    if self.hit:
                        done_msg = _tr('断点命中：{name}', name=self.hit["name"])
                        break
                    if cond and cond.get('kind') != 'time' and self.value(cond):
                        done_msg = _tr('条件成立：{desc}', desc=desc)
                        self.hit = {'bp': '', 'name': desc, 'msg': done_msg, 'station': cond.get('id'), 't': p.t, 'time': p.clock_str()}
                        break
                    if p.t - t_start >= limit:
                        done_msg = _tr('已到 {clock_str}', clock_str=p.clock_str()) if target else _tr('运行了 {v:g} 小时，条件仍未成立', v=limit / 3600)
                        break
                    await asyncio.sleep(0)
            finally:
                p.paused = True
                self.busy = None
                p.log('PLANT', 'info', _tr('运行到…结束：{v}', v=done_msg or _tr('已取消')))
        self._task = asyncio.create_task(go())
        return desc

    def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self.busy = None
        self.rt.plant.paused = True


def describe(c, p=None):
    if not c:
        return ''
    k = c.get('kind')
    name = (lambda i: f'{i} {p.stations[i].name}' if p is not None and i in p.stations else (i or _tr('任意设备')))
    op = {'>': _tr('大于'), '>=': '≥', '<': _tr('小于'), '<=': '≤', '==': _tr('等于'), '!=': _tr('不等于')}.get(c.get('op', ''), c.get('op', ''))
    if k == 'state':
        return _tr('{name} 进入{get}', name=name(c.get('id')), get=STATE_CN.get(c.get('state'), c.get('state')))
    if k == 'state_for':
        return _tr('{name} {get}超过 {get2} 分钟', name=name(c.get('id')), get=STATE_CN.get(c.get('state'), c.get('state')), get2=c.get('minutes', 5))
    if k == 'alarm':
        return _tr('{name} 出现报警', name=name(c.get('id')))
    if k == 'buffer':
        return _tr('{get} 件数{op} {get2}', get=c.get('id'), op=op, get2=c.get('value'))
    if k == 'kpi':
        return f"{label(KPI_CN.get(c.get('key'), c.get('key')))}{op} {c.get('value')}"
    if k == 'tag':
        return f"{c.get('id')}/{c.get('tag')} {op} {c.get('value')}"
    if k == 'event':
        return _tr('{name} 发生{v}事件{v2}', name=name(c.get('id')), v=c.get('ekind') or '', v2=(_tr('「') + c['text'] + _tr('」')) if c.get('text') else '')
    if k == 'time':
        return _tr('到 {get}', get=c.get('at'))
    return json.dumps(c, ensure_ascii=False)


def register(app, mgr):
    def need(request, role='engineer'):
        u = request.state.user
        if not store.role_ok(u, role):
            raise HTTPException(403, _tr('当前账号没有这个权限'))
        return u

    @app.post('/api/p/{pid}/ctl')
    async def ctl(pid: str, request: Request, body: dict = Body(...)):
        """运行控制：play / pause / step {seconds | event:true} / run_to {cond | hours} / cancel。"""
        need(request)
        rt = mgr.get(pid)
        c, p = rt.ctl, rt.plant
        a = body.get('action')
        if a == 'play':
            c.fresh = False
            c.hit = None
            if 'speed' in body:
                p.speed = max(0.1, min(3600.0, float(body['speed'])))
            p.paused = False
        elif a == 'pause':
            p.paused = True
        elif a == 'step':
            if c.busy:
                raise HTTPException(409, _tr('正在运行到…'))
            c.step(body.get('seconds'), bool(body.get('event')))
        elif a == 'run_to':
            return {'ok': True, 'goal': c.run_to(body.get('cond'), body.get('hours')), **c.status()}
        elif a == 'cancel':
            c.cancel()
        else:
            raise HTTPException(400, _tr('未知操作'))
        return {'ok': True, 'time': p.clock_str(), **c.status()}

    @app.post('/api/p/{pid}/ctl/reset')
    async def reset(pid: str, request: Request):
        """重置：按已保存的模型重建工厂并预热，停在"编辑"状态。草稿的去留由前端先处理。"""
        need(request)
        old = mgr.get(pid)
        old.ctl.cancel()
        await mgr.restart(pid)
        rt = mgr.get(pid)
        rt.ctl.bps = old.ctl.bps
        rt.plant.paused = True
        rt.ctl.fresh = True
        return {'ok': True, 'time': rt.plant.clock_str(), **rt.ctl.status()}

    @app.get('/api/p/{pid}/breakpoints')
    async def bp_list(pid: str):
        rt = mgr.get(pid)
        return [{**b, 'desc': describe(b['cond'], rt.plant)} for b in rt.ctl.bps]

    @app.post('/api/p/{pid}/breakpoints')
    async def bp_add(pid: str, request: Request, body: dict = Body(...)):
        need(request)
        rt = mgr.get(pid)
        cond = body.get('cond') or {}
        if cond.get('kind') not in ('state', 'state_for', 'alarm', 'buffer', 'kpi', 'tag', 'event', 'time'):
            raise HTTPException(400, _tr('断点条件不对'))
        b = {'id': f'BP{int(time.time() * 1000) % 10 ** 8}', 'name': body.get('name') or describe(cond, rt.plant), 'cond': cond,
             'enabled': True, 'once': bool(body.get('once')), 'hits': 0}
        rt.ctl.bps.append(b)
        return b

    @app.patch('/api/p/{pid}/breakpoints/{bid}')
    async def bp_patch(pid: str, bid: str, request: Request, body: dict = Body(...)):
        need(request)
        for b in mgr.get(pid).ctl.bps:
            if b['id'] == bid:
                b.update({k: v for k, v in body.items() if k in ('enabled', 'name', 'once', 'cond')})
                return b
        raise HTTPException(404, _tr('没有这个断点'))

    @app.delete('/api/p/{pid}/breakpoints/{bid}')
    async def bp_del(pid: str, bid: str, request: Request):
        need(request)
        c = mgr.get(pid).ctl
        c.bps = [b for b in c.bps if b['id'] != bid]
        return {'ok': True}

    @app.get('/api/p/{pid}/replay/index')
    async def replay_index(pid: str):
        c = mgr.get(pid).ctl
        return {'points': [[s[0], s[1]] for s in c.snaps], 'every': SNAP_EVERY}

    @app.get('/api/p/{pid}/replay/at')
    async def replay_at(pid: str, t: float):
        s = mgr.get(pid).ctl.at(t)
        if s is None:
            raise HTTPException(404, _tr('还没有回放数据'))
        return s
