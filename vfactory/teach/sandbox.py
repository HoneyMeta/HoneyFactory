"""学生沙箱：每个学生每个任务一个独立工厂实例（PlantRuntime 沙箱模式：不挂 OPC UA / Modbus / MQTT）。

编号 sb-<账号>-<任务号>（客户端本机的沙箱是 sb-L-<账号>-<本机任务号>），模型文件 data/sandboxes/<编号>.yaml；学生的 PLC 程序存在软 PLC 的存储里，按 PLC 块编号（data/plc/<编号>/cells/<PLC 块>.json）。
- 空闲（没有页面连着、超过 VF_SANDBOX_IDLE_S 秒没访问，默认 600）自动休眠：停掉仿真循环，内存里的状态保留；下次访问自动恢复。
- 同时运行的沙箱最多 VF_SANDBOX_MAX_ACTIVE 个（默认 40），超出时让最久没访问的休眠。
- 休眠超过 VF_SANDBOX_UNLOAD_S 秒（默认 7200）且内存里的沙箱多于 VF_SANDBOX_MAX_LOADED（默认 200）时，保存后卸载，下次进入重新加载。
"""
from ..i18n import _tr
import asyncio
import logging
import os
import re
import time
from collections import deque

from . import db, scenes

log = logging.getLogger('vfactory.teach')


def _env(k, d):
    try:
        return float(os.environ.get(k, d))
    except ValueError:
        return float(d)


def safe_user(u):
    """账号 → 沙箱编号里的一段（小写字母数字下划线原样保留，其他账号用哈希，保证编号只含安全字符且不超过 64 位）。"""
    u = str(u)
    if re.fullmatch(r'[a-z0-9_]{1,40}', u):
        return u
    import hashlib
    return 'x' + hashlib.sha1(u.encode('utf-8')).hexdigest()[:16]


def _local_mode():
    """客户端（桌面模式）：本机的作业沙箱。"""
    try:
        from .client import _MGR
        m = _MGR.get('m')
    except ImportError:
        m = None
    return bool(getattr(m, 'desktop', None)) or os.environ.get('VF_DESKTOP') == '1'


def user_part(username):
    """沙箱编号里的账号段。客户端本机的沙箱加 "L-"（大写，服务器上的账号段只有小写字母数字），
    和学校服务器上同一个学生的沙箱 sb-<账号>-<服务器作业号> 不会撞号（本机作业号和服务器作业号是两套）。"""
    return ('L-' if _local_mode() else '') + safe_user(username)


def pid_for(username, aid):
    return f'sb-{user_part(username)}-{int(aid)}'


def _adopt_legacy(username, aid, pid):
    """4.2 客户端的本机沙箱叫 sb-<账号>-<作业号>（没有 L-）：第一次进入时改成新编号（模型、PLC 程序、编辑器草稿一起搬）。"""
    if not pid.startswith('sb-L-'):
        return
    from ..server import SANDBOXES
    old = f'sb-{safe_user(username)}-{int(aid)}'
    src = os.path.join(SANDBOXES, f'{old}.yaml')
    if not os.path.exists(src) or os.path.exists(os.path.join(SANDBOXES, f'{pid}.yaml')):
        return
    r = db.q('select username, assignment_id from sandboxes where pid=?', (old,), one=True)
    if not r or r['username'] != username or r['assignment_id'] != int(aid):
        return
    try:
        from .. import paths
        from ..plc import store as ps
        moves = [(src, os.path.join(SANDBOXES, f'{pid}.yaml')), (src + '.bak', os.path.join(SANDBOXES, f'{pid}.yaml.bak')),
                 (os.path.join(ps.ROOT, old), os.path.join(ps.ROOT, pid)),
                 (os.path.join(paths.DATA, 'drafts', f'{old}.json'), os.path.join(paths.DATA, 'drafts', f'{pid}.json')),
                 (os.path.join(paths.DATA, 'versions', old), os.path.join(paths.DATA, 'versions', pid))]
        for a, b in moves:
            if os.path.exists(a) and not os.path.exists(b):
                os.replace(a, b)
        db.x('update sandboxes set pid=? where pid=?', (pid, old))
        log.info(_tr('本机沙箱 %s 改名为 %s'), old, pid)
    except Exception:
        log.exception(_tr('本机沙箱 %s 改名失败'), old)


class Trace:
    """沙箱的 I/O 时序（每仿真秒采样一次，只记变化），给 AI 助教和教师旁观用。"""

    def __init__(self, rt):
        self.rt, self.plant = rt, rt.plant
        self.rows: deque = deque(maxlen=400)
        self.last: dict = {}
        self.plant.step_hooks.append(self.tick)

    def tick(self):
        try:
            v = scenes.io_values(self.rt)
        except Exception:
            return
        ch = {k: x for k, x in v.items() if self.last.get(k, None) != x}
        if ch:
            self.last.update(ch)
            self.rows.append((round(self.plant.t, 1), ch))

    def text(self, n=60):
        return '\n'.join(f't={t:g}s ' + ', '.join(f'{k}={v}' for k, v in ch.items()) for t, ch in list(self.rows)[-n:])


class Pool:
    def __init__(self, mgr):
        self.mgr = mgr
        self.idle_s = _env('VF_SANDBOX_IDLE_S', 600)
        self.max_active = int(_env('VF_SANDBOX_MAX_ACTIVE', 40))
        self.max_loaded = int(_env('VF_SANDBOX_MAX_LOADED', 200))
        self.unload_s = _env('VF_SANDBOX_UNLOAD_S', 7200)
        self.locks: dict[str, asyncio.Lock] = {}
        self.traces: dict[str, Trace] = {}
        self.slept_at: dict[str, float] = {}
        self._reaper = None
        self.after_start = []          # 沙箱（重新）启动后的回调 fn(rt)：比如让软 PLC 把学生下载过的程序装回去

    # ---------- 生命周期 ----------
    def start_reaper(self):
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self.reaper())

    async def reaper(self):
        while True:
            await asyncio.sleep(5)
            try:
                await self.sweep()
            except Exception:
                log.exception(_tr('沙箱回收'))

    async def sweep(self):
        now = time.time()
        for pid, rt in list(self.mgr.sandboxes.items()):
            if not rt.hibernating and not rt.clients and now - rt.last_access > self.idle_s:
                self.sleep(rt)
        if len(self.mgr.sandboxes) > self.max_loaded:
            for pid, rt in sorted(self.mgr.sandboxes.items(), key=lambda x: x[1].last_access):
                if len(self.mgr.sandboxes) <= self.max_loaded:
                    break
                if rt.hibernating and not rt.clients and now - self.slept_at.get(pid, now) > self.unload_s:
                    await self.unload(pid)

    def sleep(self, rt):
        try:
            if rt.dirty:
                rt.save()
        except Exception:
            log.exception(_tr('沙箱 %s 保存失败'), rt.pid)
        rt.hibernate()
        self.slept_at[rt.pid] = time.time()
        log.info(_tr('沙箱 %s 休眠'), rt.pid)

    async def unload(self, pid):
        rt = self.mgr.sandboxes.pop(pid, None)
        if rt:
            try:
                if rt.dirty:
                    rt.save()
            except Exception:
                log.exception(_tr('沙箱 %s 保存失败'), pid)
            await rt.stop()
            self.traces.pop(pid, None)
            log.info(_tr('沙箱 %s 已卸载'), pid)

    def enforce_limit(self, keep=None):
        act = [rt for rt in self.mgr.sandboxes.values() if not rt.hibernating and rt.pid != keep]
        over = len(act) + (1 if keep else 0) - self.max_active
        if over <= 0:
            return
        act.sort(key=lambda r: (bool(r.clients), r.last_access))     # 先让没人看着、最久没访问的休眠
        for rt in act[:over]:
            self.sleep(rt)

    # ---------- 创建 / 进入 ----------
    def lock(self, pid):
        return self.locks.setdefault(pid, asyncio.Lock())

    async def ensure(self, username, a, task):
        """进入沙箱（不存在就按任务的起始模型新建，已休眠就唤醒）。task：teach.tasks 里的任务对象。返回 PlantRuntime。"""
        from ..server import SANDBOXES, PlantRuntime, write_yaml
        self.start_reaper()
        pid = pid_for(username, a['id'])
        async with self.lock(pid):
            rt = self.mgr.sandboxes.get(pid)
            if rt is None:
                _adopt_legacy(username, a['id'], pid)
                path = os.path.join(SANDBOXES, f'{pid}.yaml')
                fresh = not os.path.exists(path)
                if fresh:
                    os.makedirs(SANDBOXES, exist_ok=True)
                    cfg = task.plant_cfg(f"{a.get('title') or task.name} · {username}")
                    write_yaml(path, cfg)
                if not db.q('select 1 from sandboxes where pid=?', (pid,), one=True):
                    db.x('insert into sandboxes(pid,username,assignment_id,created,last_access) values(?,?,?,?,?)',
                         (pid, username, a['id'], db.store.now(), db.store.now()))
                rt = PlantRuntime(self.mgr, pid, sandbox=True)
                await rt.start()
                self.mgr.sandboxes[pid] = rt
                for fn in self.after_start:
                    try:
                        fn(rt)
                    except Exception:
                        log.exception(_tr('沙箱 %s 启动回调出错'), pid)
                if fresh:
                    for f in a.get('start_faults') or []:
                        err = task.inject(rt, f.get('comp'), f.get('kind'))
                        if err:
                            log.warning(_tr('沙箱 %s 开局故障失败：%s'), pid, err)
            rt.touch()
            self.slept_at.pop(pid, None)
            db.x('update sandboxes set last_access=? where pid=?', (db.store.now(), pid))
            self.trace(rt)
            self.enforce_limit(keep=pid)
            return rt

    async def ensure_review(self, pid, owner, aid, cfg, programs=None, fresh=False):
        """复核沙箱（sb-review-…）：按给定模型新建（fresh 时丢掉旧的），把提交里的 PLC 程序装进软 PLC 并运行。
        owner：登记的账号（服务器上是交作业的学生，客户端里是本机账号）；programs：{单元编号或 PLC 块编号: 程序}，找不到时按顺序装进各控制单元的 PLC 块。"""
        from ..server import SANDBOXES, PlantRuntime, write_yaml
        self.start_reaper()
        async with self.lock(pid):
            rt = self.mgr.sandboxes.get(pid)
            if rt is not None and fresh:
                self.mgr.sandboxes.pop(pid, None)
                await rt.stop()
                rt = None
            if rt is None:
                os.makedirs(SANDBOXES, exist_ok=True)
                path = os.path.join(SANDBOXES, f'{pid}.yaml')
                if fresh or not os.path.exists(path):
                    for p in (path, path + '.bak'):
                        if os.path.exists(p):
                            os.remove(p)
                    write_yaml(path, cfg)
                    scenes.forget_program(pid)
                    from ..server import clear_editor_state
                    clear_editor_state(pid)
                db.x('insert or replace into sandboxes(pid,username,assignment_id,created,last_access) values(?,?,?,?,?)',
                     (pid, owner, aid, db.store.now(), db.store.now()))
                from . import forget
                forget(pid)
                rt = PlantRuntime(self.mgr, pid, sandbox=True)
                await rt.start()
                self.mgr.sandboxes[pid] = rt
                if programs:
                    try:
                        from ..plc import store as ps
                        cs = scenes.cells(rt)
                        for i, (bid, prog) in enumerate(programs.items()):
                            # 包里按单元编号（4.2 起）或 PLC 块编号存；4.3 起程序存在控制这个单元的 PLC 块名下
                            tgt = scenes.plc_station(rt, bid) if rt.plant.find(bid) is not None else None
                            if tgt is None and i < len(cs):
                                tgt = scenes.plc_station(rt, cs[i].id)
                            if tgt is not None and prog:
                                ps.update(pid, 'cells', tgt.id, program=prog, downloaded=prog, run=True, mode='internal',
                                          downloaded_at=db.store.now())
                    except Exception:
                        log.exception(_tr('复核沙箱 %s 装程序失败'), pid)
                for fn in self.after_start:
                    try:
                        fn(rt)
                    except Exception:
                        log.exception(_tr('沙箱 %s 启动回调出错'), pid)
            rt.touch()
            self.trace(rt)
            self.enforce_limit(keep=pid)
            return rt

    def trace(self, rt):
        t = self.traces.get(rt.pid)
        if t is None or t.plant is not rt.plant:       # 重置/重启后是新的 Plant 对象
            t = self.traces[rt.pid] = Trace(rt)
        return t

    async def reset(self, username, a, task, clear_program=False):
        """丢掉当前沙箱，按场景重新建一个；clear_program 时连学生程序一起清掉。"""
        from ..server import SANDBOXES
        pid = pid_for(username, a['id'])
        async with self.lock(pid):
            rt = self.mgr.sandboxes.pop(pid, None)
            if rt:
                await rt.stop()
            self.traces.pop(pid, None)
            path = os.path.join(SANDBOXES, f'{pid}.yaml')
            for p in (path, path + '.bak'):
                if os.path.exists(p):
                    os.remove(p)
            if clear_program:
                scenes.forget_program(pid)
            from ..server import clear_editor_state
            clear_editor_state(pid)                    # 编辑器草稿和版本也回到起点（产线课的"作业"就是模型）
        return await self.ensure(username, a, task)

    async def load_work(self, username, a, task, program=None, model=None):
        """把一份作业（作业包里的 PLC 程序或产线模型）装进这个学生自己的沙箱：沙箱回到起点后装入，程序下载到 PLC 并运行。
        客户端里学生打开自己导出的作业包时用（接着做、再交）。"""
        from ..server import SANDBOXES, write_yaml
        pid = pid_for(username, a['id'])
        async with self.lock(pid):
            rt = self.mgr.sandboxes.pop(pid, None)
            if rt:
                await rt.stop()
            self.traces.pop(pid, None)
            path = os.path.join(SANDBOXES, f'{pid}.yaml')
            for p in (path, path + '.bak'):
                if os.path.exists(p):
                    os.remove(p)
            scenes.forget_program(pid)
            from ..server import clear_editor_state
            clear_editor_state(pid)
            if model is not None:
                import copy
                cfg = copy.deepcopy(model)
                cfg.setdefault('plant', {})['name'] = f"{a.get('title') or task.name} · {username}"[:40]
                os.makedirs(SANDBOXES, exist_ok=True)
                write_yaml(path, cfg)
            elif program is not None:
                tgt = scenes.plc_id_of_cfg(task.plant_cfg())          # 场景工厂里控制单元的 PLC 块编号（迁移结果固定，例如 PLC1）
                if tgt:
                    from ..plc import store as ps
                    ps.update(pid, 'cells', tgt, program=program, downloaded=program, run=True, mode='internal', downloaded_at=db.store.now())
        return await self.ensure(username, a, task)

    async def drop(self, pid):
        """删除沙箱（任务删除时）。"""
        from ..server import SANDBOXES
        from . import forget
        rt = self.mgr.sandboxes.pop(pid, None)
        if rt:
            await rt.stop()
        self.traces.pop(pid, None)
        for p in (os.path.join(SANDBOXES, f'{pid}.yaml'), os.path.join(SANDBOXES, f'{pid}.yaml.bak')):
            if os.path.exists(p):
                os.remove(p)
        db.x('delete from sandboxes where pid=?', (pid,))
        scenes.forget_program(pid)
        forget(pid)

    def status(self, pid):
        rt = self.mgr.sandboxes.get(pid)
        if rt is None:
            return 'none'
        return 'sleeping' if rt.hibernating else 'running'

    def info(self):
        rts = list(self.mgr.sandboxes.values())
        return {'loaded': len(rts), 'running': sum(1 for r in rts if not r.hibernating), 'sleeping': sum(1 for r in rts if r.hibernating),
                'max_active': self.max_active, 'idle_s': self.idle_s, 'max_loaded': self.max_loaded}
