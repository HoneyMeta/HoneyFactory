"""教学与控制层 / 软 PLC 之间的桥：场景库、沙箱工厂模型、评分、学生程序、故障注入、实时 I/O。

场景文件：vfactory/control/scenes/*.json（控制层负责编写）。这里只读，学生看到的版本去掉参考答案。
控制层（vfactory/control）和软 PLC（vfactory/plc）的函数名以它们的实现为准，这里集中做适配，教学其余代码只调这里。
"""
from ..i18n import _tr
import copy
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENE_DIR = os.path.join(ROOT, 'control', 'scenes')
_cache: dict = {}


# ---------------- 场景库 ----------------
def _files():
    return sorted(glob.glob(os.path.join(SCENE_DIR, '*.json')))


def load_scene(sid):
    path = os.path.join(SCENE_DIR, f'{os.path.basename(str(sid))}.json')
    if not os.path.exists(path):
        try:
            from ..control import scenes as cs          # 控制层也可以在代码里定义场景
            s = cs.get_scene(sid) if hasattr(cs, 'get_scene') else None
            if s:
                return s
        except Exception:
            pass
        return None
    mt = os.path.getmtime(path)
    c = _cache.get(path)
    from ..i18n import content                  # display texts in the current language (control/scenes/i18n/<scene>.en.json)
    if c and c[0] == mt:
        return content(c[1], path)
    with open(path, encoding='utf-8') as f:
        s = json.load(f)
    s.setdefault('id', os.path.basename(path)[:-5])
    _cache[path] = (mt, s)
    return content(s, path)


def scene_ids():
    return [os.path.basename(p)[:-5] for p in _files()]


def _get(s, *keys, default=None):
    for k in keys:
        if isinstance(s, dict) and s.get(k) not in (None, ''):
            return s[k]
    return default


def name_of(s):
    return _get(s, 'name', 'title', default=s.get('id'))


def cell_of(s):
    return _get(s, 'cell', 'cell_def', default={}) or {}


def io_of(s):
    return _get(s, 'io', 'io_table', default=None) or cell_of(s).get('io') or []


def task_md(s):
    return _get(s, 'task_md', 'task', 'taskbook', 'brief', 'markdown', default='')


def rules_of(s):
    r = _get(s, 'scoring', 'rules', 'score', default=[])
    if isinstance(r, dict):
        r = r.get('rules') or r.get('items') or []
    return r


def _fault_cn(comp, kind):
    """场景里没写名字的故障：用中文故障名，如"M1：电机过载跳闸"。"""
    try:
        from ..control.catalog import FAULTS
    except Exception:
        FAULTS = {}
    k = FAULTS.get(kind, kind or '')
    return _tr('{comp}：{k}', comp=comp, k=k) if comp else k


def faults_of(s):
    """可注入故障清单 → [{comp, kind, label}]"""
    out = []
    for f in _get(s, 'faults', 'fault_list', default=[]) or []:
        if isinstance(f, str):
            out.append({'comp': None, 'kind': f, 'label': _fault_cn(None, f)})
        elif isinstance(f, dict):
            out.append({'comp': f.get('comp') or f.get('component'), 'kind': f.get('kind') or f.get('fault'),
                        'label': f.get('label') or f.get('name') or f.get('desc') or _fault_cn(f.get('comp') or f.get('component'), f.get('kind') or f.get('fault'))})
    return out


def hints_of(s):
    h = _get(s, 'hints', default=[]) or []
    return [h] if isinstance(h, str) else list(h)


def reference_of(s):
    return _get(s, 'reference', 'solution', 'reference_program', 'answer', default=None)


def summary(s):
    return {'id': s['id'], 'name': name_of(s), 'level': _get(s, 'level', 'difficulty', 'order', default=None),
            'desc': _get(s, 'desc', 'summary', 'description', default=''), 'faults': faults_of(s), 'io_count': len(io_of(s)),
            'rules': [{'key': r.get('key'), 'label': r.get('label') or r.get('key'), 'weight': r.get('weight')} for r in rules_of(s) if isinstance(r, dict)],
            'has_reference': reference_of(s) is not None}


def list_scenes():
    out = []
    for sid in scene_ids():
        try:
            s = load_scene(sid)
            out.append(summary(s))
        except Exception as e:
            out.append({'id': sid, 'name': sid, 'error': str(e)})
    out.sort(key=lambda x: (x.get('level') if isinstance(x.get('level'), (int, float)) else 999, x['id']))
    return out


def public_scene(s, hints=True):
    """学生看到的场景：任务书、I/O 表、评分规则、提示（老师允许时）；不含参考答案。"""
    return {'id': s['id'], 'name': name_of(s), 'task_md': task_md(s), 'io': io_of(s),
            'rules': [{k: r.get(k) for k in ('key', 'label', 'op', 'value', 'weight', 'desc', 'how')} for r in rules_of(s) if isinstance(r, dict)],
            'hints': hints_of(s) if hints else [], 'level': _get(s, 'level', 'difficulty', default=None)}


# ---------------- 沙箱工厂模型 ----------------
def plant_cfg(s, title=''):
    """场景 → 独立的 2.0 工厂模型（只含这个控制单元）。优先用控制层提供的构造函数。"""
    cfg = None
    try:
        from ..control import scenes as cs
        for fn in ('scene_plant', 'build_plant', 'plant_for_scene', 'scene_model', 'standalone_plant'):
            if hasattr(cs, fn):
                cfg = getattr(cs, fn)(s)
                break
    except ImportError:
        pass
    if cfg is None:
        cfg = {'version': 2, 'plant': {'name': name_of(s), 'seed': 7, 'start': '2026-11-02T07:00:00', 'dt': 1.0, 'speed': 1, 'warmup_h': 0,
                                       'floor': [20, 12]},
               'areas': [{'name': _tr('实训区'), 'x': [0, 20], 'color': '#E3ECF2'}],
               'blocks': [{'id': 'CELL1', 'type': 'cell', 'name': name_of(s), 'pos': [4, 4], 'size': cell_of(s).get('size', [8, 4]),
                           'params': {'cell': copy.deepcopy(cell_of(s))}}],
               'links': [], 'groups': [], 'notes': []}
    cfg = copy.deepcopy(cfg)
    cfg.setdefault('plant', {})
    cfg['plant']['warmup_h'] = 0
    if title:
        cfg['plant']['name'] = title[:40]
    cfg['plant'].pop('modbus_port', None)
    return cfg


# ---------------- 运行中的控制单元 ----------------
def cells(rt):
    """工厂里的控制单元块（Station 对象）列表。"""
    return [st for st in list(rt.plant.stations.values()) if st.cfg.get('type') == 'cell' or st.kind == 'cell']


def cell(rt, bid=None):
    cs = cells(rt)
    if bid:
        cs = [c for c in cs if c.id == bid]
    return cs[0] if cs else None


def _sim(st):
    """控制单元块上的 CellSim（有 inputs/apply_outputs 的那个属性）。"""
    for k in ('sim', 'cellsim', 'cs'):
        v = getattr(st, k, None)
        if v is not None and hasattr(v, 'apply_outputs'):
            return v
    for v in vars(st).values():
        if hasattr(v, 'apply_outputs') and hasattr(v, 'inputs'):
            return v
    return None


def _plc(st):
    """站上的 PLC 运行时（PlcStation.plc，或者还没迁移的旧单元内置 PlcRuntime / 外接代理，都有 scan）。"""
    for k in ('plc', 'runtime', 'plc_rt'):
        v = getattr(st, k, None)
        if v is not None and hasattr(v, 'scan'):
            return v
    for v in vars(st).values():
        if hasattr(v, 'scan') and hasattr(v, 'state') and not hasattr(v, 'apply_outputs'):
            return v
    return None


# ---------------- 4.3：PLC 是独立的块（通过信号线控制单元） ----------------
def plcs(rt):
    """工厂里的 PLC 块（PlcStation）列表。"""
    return [st for st in rt.plant.all_stations() if getattr(st, 'kind', '') == 'plc']


def plc_station(rt, bid=None):
    """学生编程的对象：控制单元 bid（不给时第一个控制单元）的 PLC 块；bid 本身是 PLC 块时就是它。
    没迁移的旧单元（自己带 PLC）返回单元本身；都没有返回 None。"""
    if bid:
        st = rt.plant.find(bid)
        if st is not None and getattr(st, 'kind', '') == 'plc':
            return st
    c = cell(rt, bid)
    if c is not None:
        from ..plc.migrate import plc_of_cell
        p = plc_of_cell(rt.plant, c.id)
        if p is not None:
            return p
        if _plc(c) is not None:
            return c
    if not bid:
        ps = plcs(rt)
        return ps[0] if ps else None
    return None


def plc_info(rt, bid=None):
    """给前端和助教：{id, name, state, devices:[{id, name}]}（学生编程的 PLC 块，以及它通过信号线控制哪些设备）。"""
    p = plc_station(rt, bid)
    if p is None:
        return None
    devs = list(getattr(p, 'devices', None) or []) if getattr(p, 'kind', '') == 'plc' else [p.id]
    rp = _plc(p)
    v = getattr(rp, 'state', None) if rp is not None else None
    return {'id': p.id, 'name': getattr(p, 'name', p.id), 'state': v if isinstance(v, str) else None,
            'devices': [{'id': d, 'name': getattr(rt.plant.find(d), 'name', d)} for d in devs]}


def io_values(rt, bid=None):
    """当前 I/O：{name: value}（输入 + 输出）。"""
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    if sim is None:
        return {}
    try:
        if hasattr(sim, 'io_values'):
            return dict(sim.io_values())
        d = dict(sim.inputs())
        d.update(getattr(sim, 'outputs', {}) or {})
        return d
    except Exception:
        return {}


def stats(rt, bid=None):
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    try:
        return sim.stats() if sim is not None else {}
    except Exception:
        return {}


def plc_state(rt, bid=None):
    """控制单元（不给时第一个）的 PLC 状态：RUN / STOP / HALT / ERROR…；没有 PLC 返回 None。4.3 起读控制它的 PLC 块。"""
    p = plc_station(rt, bid)
    rp = _plc(p) if p is not None else None
    v = getattr(rp, 'state', None) if rp is not None else None
    return v if isinstance(v, str) else None


def inject(rt, comp, kind, bid=None):
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    if sim is None:
        return _tr('这个沙箱里没有控制单元')
    try:
        r = sim.inject(comp, kind)
    except Exception as e:
        return _tr('注入失败：{e}', e=e)
    if isinstance(r, str) and r:
        return r
    rt.plant.log(st.id, 'inject', _tr('注入故障：{comp} {kind}', comp=comp, kind=kind))
    return None


def active_faults(rt, bid=None):
    """控制单元里当前生效的故障 [(部件, 故障类型)]。"""
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    if sim is None or not hasattr(sim, 'fault_list'):
        return []
    try:
        return [(f['comp'], f['kind']) for f in sim.fault_list()]
    except Exception:
        return []


def clear_one(rt, comp, bid=None):
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    if sim is not None and hasattr(sim, 'clear_faults'):
        sim.clear_faults(comp)


def components(rt, bid=None):
    """单元里的部件（排故时让学生选）：[{id, type, label}]"""
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    out = []
    for c in (getattr(sim, 'comps', {}) or {}).values():
        out.append({'id': c.id, 'type': getattr(c, 'type', ''), 'label': (getattr(c, 'd', {}) or {}).get('label') or c.id})
    return out


def clear_faults(rt, bid=None):
    st = cell(rt, bid)
    sim = _sim(st) if st else None
    if sim is not None and hasattr(sim, 'clear_faults'):
        sim.clear_faults()
        rt.plant.log(st.id, 'inject', _tr('清除全部故障'))


def get_program(rt, bid=None):
    """学生当前的 PLC 程序（bid：控制单元或 PLC 块编号，不给时第一个控制单元的 PLC）：
    优先取最后下载到 PLC 的那份（软 PLC 的存储 data/plc/<沙箱>/cells/<PLC 块>.json；迁移来的 PLC 还没有自己的记录时读原单元的），
    没下载过取工程里保存的程序，再没有取 PLC 块里的内联程序（场景自带的）。"""
    p = plc_station(rt, bid)
    if p is None:
        return None
    rec = {}
    try:
        from ..plc.api import saved_of
        rec = saved_of(rt.pid, p) or {}
    except ImportError:
        try:
            from ..plc import store as ps
            rec = ps.load(rt.pid, 'cells', p.id, {}) or {}
        except ImportError:
            pass
    for k in ('downloaded', 'program'):
        if isinstance(rec.get(k), dict) and rec[k].get('source') not in (None, '', {}):
            return copy.deepcopy(rec[k])
    if getattr(p, 'kind', '') == 'plc':
        v = p.cfg.get('program')
    else:                                                 # 没迁移的旧单元：单元定义里的内联程序
        v = ((p.cfg.get('cell') or {}).get('plc') or {}).get('program')
    return copy.deepcopy(v) if isinstance(v, dict) and v.get('source') not in (None, '', {}) else None


def plc_id_of_cfg(cfg):
    """工厂模型（还没建厂）里第一个控制单元的 PLC 块编号（信号线另一头的 plc 块）；没有返回 None。"""
    blocks = {b.get('id'): b for b in (cfg or {}).get('blocks') or []}
    for b in blocks.values():
        if b.get('type') != 'cell':
            continue
        for l in (cfg or {}).get('links') or []:
            if l.get('kind') == 'signal' and b['id'] in (l.get('from'), l.get('to')):
                o = l['to'] if l.get('from') == b['id'] else l.get('from')
                if (blocks.get(o) or {}).get('type') == 'plc':
                    return o
    return None


def program_targets(rt):
    """作业里要交的程序：[(控制单元编号, PLC 块)]，每个控制单元一项（作业包按单元编号存，兼容 4.2 的包）。"""
    out = []
    for c in cells(rt):
        p = plc_station(rt, c.id)
        if p is not None:
            out.append((c.id, p))
    return out


def forget_program(pid):
    """删除沙箱时一并删掉它在软 PLC 存储里的程序。"""
    import shutil
    try:
        from ..plc import store as ps
        d = os.path.join(ps.ROOT, pid)
        if ps.safe_id(pid) and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    except ImportError:
        pass


# ---------------- 评分 ----------------
def overlay_scene(s, lesson):
    """4.6 老师做的 PLC 课在场景上的改动（声明式）：rubric = 只用这些评分项；tests = 追加的测试步骤（和场景 test.steps 同格式）；
    extra_rules = 追加的评分项（key 对应 tests 里某个 check 的 key，或某个统计量）。没有改动时原样返回。"""
    if not s or not lesson or not any(lesson.get(k) is not None for k in ('rubric', 'tests', 'extra_rules')):
        return s
    s = copy.deepcopy(s)
    rs = [r for r in rules_of(s) if isinstance(r, dict)]
    if lesson.get('rubric') is not None:
        keep = set(lesson.get('rubric') or [])
        rs = [r for r in rs if r.get('key') in keep]
    rs += [copy.deepcopy(r) for r in lesson.get('extra_rules') or [] if isinstance(r, dict)]
    s['scoring'] = {'rules': rs}
    s.pop('rules', None)
    if lesson.get('tests'):
        t = s.setdefault('test', {})
        t['steps'] = list(t.get('steps') or []) + [copy.deepcopy(x) for x in lesson['tests'] if isinstance(x, dict)]
        last = max([float(x.get('t', 0)) + float(x.get('within', 0) or 0) + float(x.get('hold', 0) or 0) for x in lesson['tests'] if isinstance(x, dict)] + [0])
        t['duration'] = max(float(t.get('duration', 120)), last + 2)
    return s


def score_job(scene_id, program, overlay=None):
    """在进程池里跑：用学生程序把场景从头跑一遍，按评分规则打分。返回 {score, max, details:[...], stats, ok, error?}
    overlay：老师做的课对场景的改动（rubric / tests / extra_rules，见 overlay_scene）。"""
    s = load_scene(scene_id)
    if s and overlay:
        s = overlay_scene(s, overlay)
    if not s:
        return {'ok': False, 'error': _tr('没有场景 {scene_id}', scene_id=scene_id), 'score': 0, 'max': 100, 'details': []}
    try:
        from ..control import scoring
    except ImportError as e:
        return {'ok': False, 'error': _tr('评分引擎不可用：{e}', e=e), 'score': 0, 'max': 100, 'details': []}
    for fn in ('score_scene', 'score_program', 'evaluate', 'score', 'run_scoring'):
        if hasattr(scoring, fn):
            r = getattr(scoring, fn)(s, program)
            return normalize_result(r)
    return {'ok': False, 'error': _tr('评分引擎没有可调用的函数'), 'score': 0, 'max': 100, 'details': []}


def normalize_result(r):
    if not isinstance(r, dict):
        return {'ok': False, 'error': _tr('评分结果格式不对'), 'score': 0, 'max': 100, 'details': []}
    out = dict(r)
    out.setdefault('ok', True)
    out['score'] = float(out.get('score', out.get('total', 0)) or 0)
    out['max'] = float(out.get('max', out.get('max_score', 100)) or 100)
    out['details'] = out.get('details') or out.get('items') or out.get('rules') or []
    return out


# ---------------- 发布前检查：任务书和评分是否对得上 ----------------
def _bigrams(t):
    import re as _re
    cn = ''.join(_re.findall(_tr('[一-龥A-Za-z0-9_]'), t or ''))
    return {cn[i:i + 2] for i in range(len(cn) - 1)}


def check_scene(s):
    """返回提醒列表：评分项在任务书正文里找不到对应的要求；任务书说"不要求"的内容却被评分。（启发式，给老师发布前看）"""
    import re as _re
    md = task_md(s) or ''
    body = _re.split(r'#+\s*(?:评分|Scoring|Grading)', md)[0]
    body_bg = _bigrams(body)
    out = []
    sentences = [x for x in _re.split(r'[。；\n]|(?<=[.;])\s', body) if x.strip()]
    for r in rules_of(s):
        if not isinstance(r, dict):
            continue
        lab = _re.sub(r'[≥≤=<>]+\s*[\d.]+.*$', '', str(r.get('label') or r.get('key') or '')).strip()
        bg = _bigrams(lab)
        if len(bg) >= 2 and len(bg & body_bg) / len(bg) < 0.3:
            out.append(_tr('评分项「{lab}」在任务书正文里没有对应的要求句', lab=lab))
        for sen in sentences:
            if any(w in sen for w in (_tr('不要求'), _tr('不需要'), _tr('不用做'), _tr('不考核'))) and len(bg) >= 2 and len(bg & _bigrams(sen)) / len(bg) >= 0.4:
                out.append(_tr('任务书写着「{v}」，但评分里有「{lab}」', v=sen.strip()[:40], lab=lab))
    return out
