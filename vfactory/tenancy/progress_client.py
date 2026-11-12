"""客户端（桌面模式）这边的进度上报：学校作业（client_links 里连着服务器的本机作业）的进度、当前步骤、本机分数，
定时（60 秒看一次，有变化才报）和事件发生时（交作业、作答、本机评分以后 10 秒内）报给服务器 /api/progress/report。
连不上服务器：存进本机队列 data/client/progress_queue.json（最多 500 条，带当时的时间），联网后按顺序补报。
服务器太旧（没有这个接口，404）：这次运行不再报，队列清掉（免得一直攒）。
"""
from ..i18n import _tr
import asyncio
import json
import logging
import os
import time

from .. import paths, store

log = logging.getLogger('vfactory.desktop')
QMAX = 500
PERIOD = 60
EVENT_DELAY = 10


def queue_path():
    return paths.data('client', 'progress_queue.json')


def load_queue():
    try:
        with open(queue_path(), encoding='utf-8') as f:
            q = json.load(f)
            return q if isinstance(q, list) else []
    except (OSError, ValueError):
        return []


def save_queue(q):
    p = queue_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(q[-QMAX:], f, ensure_ascii=False)
    os.replace(p + '.tmp', p)


def _progress(mgr, username, laid, a):
    """→ (progress 0~1 或 None, 当前步骤, 状态)。沙箱在跑时用评分规则的实时进度（产线课）；否则看本机提交。"""
    from ..teach import db
    from ..teach.sandbox import pid_for
    from ..teach.tasks import LessonTask, task_of
    best = db.q("select max(auto_score) s, count(*) n from submissions where assignment_id=? and username=? and status in ('scored','reviewed','submitted')",
                (laid, username), one=True) or {}
    rt = getattr(mgr, 'sandboxes', {}).get(pid_for(username, laid)) if mgr else None
    prog, step = None, ''
    try:
        t = task_of(a)
    except Exception:                                   # noqa: BLE001
        t = None
    if rt is not None and isinstance(t, LessonTask) and getattr(t, 'sandbox', True) is not False:
        try:
            ans = db.q('select data from answers where assignment_id=? and username=?', (laid, username), one=True)
            live = t.live(rt, db.jl(ans['data'], {}) if ans else {}) or {}
            rules = live.get('rules') or []
            if rules:
                done = [r for r in rules if r.get('ok') is True or r.get('answered')]
                prog = round(len(done) / len(rules), 3)
                nxt = next((r for r in rules if not (r.get('ok') is True or r.get('answered'))), None)
                step = _tr('在做：{v}', v=nxt.get('label') or nxt.get('key')) if nxt else _tr('目标都达到了，可以提交')
        except Exception:                               # noqa: BLE001  实时进度算不出来就只报分数
            pass
    if best.get('s') is not None:
        state = 'done' if float(best['s']) >= 60 else 'working'
        if prog is None:
            prog = round(min(1.0, float(best['s']) / 100), 3)
        step = step or _tr('本机已评分 {n} 次', n=best['n'])
    elif rt is not None:
        state = 'working'
        step = step or _tr('在沙箱里做')
    else:
        state = 'not_started'
    return prog, step, state, best.get('s')


class Reporter:
    def __init__(self, d):
        self.d = d
        self.last: dict = {}                            # 服务器作业号 → 上次报的内容（没变就不报）
        self.unsupported_for = None                     # 服务器没有这个接口（旧版本）
        self.event_at = 0.0
        self.submitted: set = set()

    def mark(self, submitted_laid=None):
        """有事件（交作业、作答）：10 秒内报一次。"""
        if submitted_laid:
            self.submitted.add(int(submitted_laid))
        self.event_at = time.time()

    def school(self):
        from ..teach import client as tclient
        return tclient.load_settings()

    def collect(self):
        from ..teach import db
        s = self.school()
        url, user = s.get('url'), s.get('username')
        if not url or not user:
            return []
        out = []
        for ln in db.q('select * from client_links where server=?', (url,)):
            a = db.assignment(ln['local_aid'])
            if not a:
                continue
            prog, step, state, score = _progress(self.d.mgr, user, ln['local_aid'], a)
            if ln['local_aid'] in self.submitted:
                state = 'submitted'
            item = {'assignment_id': ln['remote_aid'], 'progress': prog, 'step': step[:120], 'state': state, 'score': score}
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if self.last.get(ln['remote_aid']) == key:
                continue
            self.last[ln['remote_aid']] = key
            out.append({**item, 'at': store.now()})
        return out

    async def tick(self):
        items = self.collect()
        if items:
            s = self.school()
            q = load_queue() + [{**it, '_server': s.get('url'), '_user': s.get('username')} for it in items]
            save_queue(q)
        sent = await self.flush()
        if not sent:
            await self.heartbeat()

    async def heartbeat(self):
        """没有新进度也报一声：老师的班级进度页据此显示"在线"（3 分钟内报过）。连不上就算了（不排队）。"""
        from ..desktop_proxy import Offline, acall
        from .. import __version__
        s = self.school()
        if not s.get('url') or not s.get('token') or self.unsupported_for == s.get('url'):
            return
        if (getattr(self.d, 'account', None) or {}).get('role') not in (None, 'student'):
            return                                     # 老师、管理员的客户端不算"学生在线"
        try:
            await acall('POST', s['url'] + '/api/progress/report', body={'items': [], 'heartbeat': {'client': f'desktop {__version__}'}},
                        token=s['token'], timeout=10)
        except Offline:
            pass

    async def flush(self):
        from ..desktop_proxy import Offline, acall, jbody
        s = self.school()
        url, tok = s.get('url'), s.get('token')
        if not url or not tok or self.unsupported_for == url:
            return 0
        q = load_queue()
        mine = [x for x in q if x.get('_server') == url and x.get('_user') == s.get('username')]
        if not mine:
            return 0
        sent = 0
        for i in range(0, len(mine), 100):
            batch = mine[i:i + 100]
            try:
                code, _, b = await acall('POST', url + '/api/progress/report', body={'items': [{k: v for k, v in x.items() if not k.startswith('_')}
                                                                                              for x in batch]}, token=tok, timeout=20)
            except Offline:
                return sent                              # 离线：留在队列里，联网后补报
            if code == 404:
                log.info(_tr('服务器 %s 没有进度上报接口（旧版本），不再上报'), url)
                self.unsupported_for = url
                save_queue([x for x in q if x.get('_server') != url])
                return sent
            if code == 401:
                return sent
            sent_ids = {id(x) for x in batch}
            q = [x for x in q if id(x) not in sent_ids]
            save_queue(q)
            sent += len(batch)
            if code != 200:
                log.info(_tr('进度上报被服务器拒绝（%s）：%s'), code, jbody(b).get('detail'))
        return sent

    async def loop(self):
        period = float(os.environ.get('VF_PROGRESS_PERIOD') or PERIOD)
        delay = float(os.environ.get('VF_PROGRESS_DELAY') or EVENT_DELAY)
        last = 0.0
        while True:
            await asyncio.sleep(1)
            try:
                now = time.time()
                event_due = self.event_at > last and now - self.event_at >= delay
                if (now - last >= period or event_due) and self.school().get('url'):
                    last = now
                    await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:                            # noqa: BLE001
                log.exception(_tr('进度上报出错'))
