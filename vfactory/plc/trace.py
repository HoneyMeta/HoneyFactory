"""I/O 时序记录（逻辑分析仪的数据）：每个扫描周期把 I/O 映像和 PLC 时钟记下来，只在有变化时存一条，最近 N 秒。

    tr = Tracer(['START', 'STOP', 'M1_RUN'])
    tr.record(t_ms, (True, True, False))
    tr.window(seconds=30) -> {'names', 'now_ms', 'events': [[t_ms, [值…]], …]}   # 第一条是窗口起点处的值
"""
from collections import deque


class Tracer:
    def __init__(self, names, max_events=40000, keep_s=120):
        self.names = list(names)
        self.ev = deque(maxlen=max_events)
        self.last = None
        self.now = 0
        self.keep_ms = keep_s * 1000

    def record(self, t_ms, values):
        self.now = t_ms
        if values != self.last:
            self.ev.append((t_ms, values))
            self.last = values
            # 只留最近 keep_s 秒（保留窗口起点之前的最后一条，作为起始值）
            while len(self.ev) > 2 and self.ev[1][0] < t_ms - self.keep_ms:
                self.ev.popleft()

    def window(self, seconds=30, since_ms=None):
        start = self.now - int(seconds * 1000) if since_ms is None else since_ms
        out, base = [], None
        for t, v in self.ev:
            if t <= start:
                base = (t, v)
            else:
                out.append([t, list(v)])
        if base is not None:
            out.insert(0, [max(base[0], start), list(base[1])])
        return {'names': self.names, 'now_ms': self.now, 'start_ms': start, 'events': out}
