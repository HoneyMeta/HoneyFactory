"""PLC 程序、HMI 画面、外接配置的持久化：data/plc/<工厂>/…（JSON 文件）。

  <工厂>/cells/<单元>.json   {"program": 工程里的程序, "downloaded": 最后下载到 PLC 的程序, "run": 下载后是否运行,
                               "mode": "internal"|"external", "external": {…外接配置…}, "sandbox_io": [...]}
  <工厂>/hmi/<画面>.json      HMI 画面
"""
from ..i18n import _tr
import json
import os
import re
import threading

from .. import store as _vfstore

from .. import paths as _paths  # noqa: E402
ROOT = _paths.data('plc')
SAFE = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')
_lock = threading.Lock()


def safe_id(x):
    x = str(x or '')
    return x if SAFE.match(x) else None


def _path(pid, kind, xid):
    p, x = safe_id(pid), safe_id(xid)
    if not p or not x:
        raise ValueError(_tr('编号只能包含字母、数字、下划线和短横线'))
    d = os.path.join(ROOT, p, kind)
    return d, os.path.join(d, f'{x}.json')


def load(pid, kind, xid, default=None):
    try:
        _, f = _path(pid, kind, xid)
    except ValueError:
        return default
    if not os.path.exists(f):
        return default
    try:
        with open(f, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(pid, kind, xid, data):
    d, f = _path(pid, kind, xid)
    os.makedirs(d, exist_ok=True)
    tmp = f + '.tmp'
    with _lock:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, f)


def update(pid, kind, xid, **kv):
    cur = load(pid, kind, xid, {}) or {}
    cur.update(kv)
    save(pid, kind, xid, cur)
    return cur


def listing(pid, kind):
    p = safe_id(pid)
    if not p:
        return []
    d = os.path.join(ROOT, p, kind)
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json'))


def remove(pid, kind, xid):
    try:
        _, f = _path(pid, kind, xid)
    except ValueError:
        return False
    if os.path.exists(f):
        os.remove(f)
        return True
    return False
