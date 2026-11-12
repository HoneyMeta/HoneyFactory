"""提交工厂作业（4.4，kind = factory）：学生在客户端"我的工厂"里建一座工厂，选它交给老师。

老师发布时写要求（markdown）、截止时间，可选几条确定性的自动检查（spec.checks）：
  {kind: 'valid'}                          模型检查没有错误
  {kind: 'block', type: 'gateway', min: 1}  至少有 N 台某类设备（plc / gateway / conveyor …，见 flow.catalog.BLOCK_TYPES）
  {kind: 'plc_control', min: 1}            至少有一台 PLC 通过信号线控制 N 台设备
  {kind: 'good', min: 100}                 仿真 spec.hours 小时后合格品 ≥ K 件
  {kind: 'oee', block: 'M1', min: 0.6}     仿真后某台设备（编号或名称）的 OEE ≥ x
每条检查分值相同（满分 100）。没有任何检查时只等老师评分（提交记录状态 submitted，没有自动分）。
老师在教学控制台给的分数和评语就是成绩（覆盖自动分）。

提交物（存进 submissions.program）：{model: 工厂模型（2.0 块+连线）, programs: {PLC 块编号: 程序}}。
评分在进程池里跑（score_job）：同一份模型 + 程序、固定随机种子，结果可重复。
"""
from ..i18n import _tr
import copy
import math
import time

KIND_CN = '工厂设计'
MAX_HOURS = 24
CHECK_KINDS = ('valid', 'block', 'plc_control', 'good', 'oee')
NOT_DEVICES = {'plc', 'hmi', 'gateway', 'switch', 'scada', 'mes'}


class SpecError(ValueError):
    pass


def type_name(t):
    try:
        from ..flow.catalog import BLOCK_TYPES
        return (BLOCK_TYPES.get(t) or {}).get('label') or t
    except Exception:                                   # noqa: BLE001
        return t


def block_types():
    """发布向导用：可以要求的设备类型 [{type, label, cat}]。"""
    from ..flow.catalog import BLOCK_TYPES
    return [{'type': k, 'label': v.get('label') or k, 'cat': v.get('cat') or ''} for k, v in BLOCK_TYPES.items()
            if not v.get('legacy') and k != 'submodel']


def _num(v, lo, hi, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SpecError(_tr('{what}要是数字', what=what))
    if math.isnan(x) or not lo <= x <= hi:
        raise SpecError(_tr('{what}应在 {lo}–{hi} 之间', what=what, lo=lo, hi=hi))
    return x


def clean_spec(body):
    """老师提交的要求 → 存库的 spec（不合格抛 SpecError，信息是中文）。"""
    body = body or {}
    brief = str(body.get('brief_md') or '').strip()
    if len(brief) > 20000:
        raise SpecError(_tr('要求太长（最多 2 万字）'))
    hours = _num(body.get('hours') or 8, 0.5, MAX_HOURS, _tr('仿真时长（小时）'))
    out = []
    try:
        from ..flow.catalog import BLOCK_TYPES
    except Exception:                                   # noqa: BLE001
        BLOCK_TYPES = {}
    for c in body.get('checks') or []:
        if not isinstance(c, dict):
            continue
        k = c.get('kind')
        if k not in CHECK_KINDS:
            raise SpecError(_tr('不认识的检查项 {k}', k=k))
        if k == 'valid':
            out.append({'kind': 'valid'})
        elif k == 'block':
            t = str(c.get('type') or '')
            if t not in BLOCK_TYPES:
                raise SpecError(_tr('没有设备类型 {t}', t=t))
            out.append({'kind': 'block', 'type': t, 'min': int(_num(c.get('min') or 1, 1, 99, _tr('设备台数')))})
        elif k == 'plc_control':
            out.append({'kind': 'plc_control', 'min': int(_num(c.get('min') or 1, 1, 99, _tr('PLC 控制的设备台数')))})
        elif k == 'good':
            out.append({'kind': 'good', 'min': int(_num(c.get('min'), 1, 10 ** 7, _tr('合格品件数')))})
        elif k == 'oee':
            b = str(c.get('block') or '').strip()[:40]
            if not b:
                raise SpecError(_tr('OEE 检查要写设备编号或名称'))
            m = _num(c.get('min'), 0, 100, _tr('OEE 下限'))
            out.append({'kind': 'oee', 'block': b, 'min': round(m / 100 if m > 1 else m, 4)})
    if len(out) > 20:
        raise SpecError(_tr('自动检查最多 20 条'))
    return {'brief_md': brief, 'checks': out, 'hours': hours}


def check_label(c, hours=8):
    k = c.get('kind')
    if k == 'valid':
        return _tr('模型检查没有错误')
    if k == 'block':
        return _tr('有{type_name}（至少 {get} 台）', type_name=type_name(c['type']), get=c.get('min', 1))
    if k == 'plc_control':
        return _tr('有一台 PLC 通过信号线控制至少 {get} 台设备', get=c.get('min', 1))
    if k == 'good':
        return _tr('仿真 {hours:g} 小时，合格品至少 {get} 件', hours=hours, get=c.get('min'))
    if k == 'oee':
        return _tr('仿真 {hours:g} 小时，{get} 的 OEE 至少 {round:g}%', hours=hours, get=c.get('block'), round=round(float(c.get('min') or 0) * 100, 1))
    return str(k)


def rules(spec):
    """任务书"评分标准"里列出的检查项（和评分明细同样的字段）。"""
    spec = spec or {}
    cs = spec.get('checks') or []
    if not cs:
        return []
    w = round(100.0 / len(cs), 2)
    hours = float(spec.get('hours') or 8)
    out = []
    for i, c in enumerate(cs):
        bool_like = c['kind'] == 'valid'
        target = 1 if bool_like else (round(float(c.get('min') or 0) * 100, 1) if c['kind'] == 'oee' else c.get('min'))
        out.append({'key': f'c{i + 1}', 'kind': 'check', 'check': c['kind'], 'label': check_label(c, hours), 'op': '==' if bool_like else '>=',
                    'value': target, 'weight': w, 'unit': '%' if c['kind'] == 'oee' else ''})
    return out


def public(spec, title='', descr=''):
    spec = spec or {}
    brief = spec.get('brief_md') or ''
    rs = rules(spec)
    tail = (_tr('\n\n### 自动检查\n') + '\n'.join(f'- {r["label"]}' for r in rs) + _tr('\n\n老师会看你的工厂再给最终分数和评语。')) if rs else \
        _tr('\n\n老师会打开你的工厂看，然后给分数和评语（这个作业没有自动检查）。')
    md = (brief or _tr('## {v}\n\n按老师的要求搭一座工厂。', v=title or _tr('工厂设计'))) + tail
    return {'id': 'factory', 'name': title or _tr('工厂设计'), 'kind': 'factory', 'kind_cn': KIND_CN, 'brief_md': md, 'task_md': md, 'rules': rs, 'hints': [],
            'io': [], 'time_h': spec.get('hours') or 8, 'checks': spec.get('checks') or [], 'hours': spec.get('hours') or 8}


# ---------------------------------------------------------------- 从本机工厂取提交物
def collect(rt, pid=None):
    """运行中的本机工厂 → (模型, {PLC 块编号: 程序}, 摘要)。模型取编辑器草稿（还没保存的改动也算），没有草稿取运行中的工厂。
    程序取每台 PLC 最后下载的那份（没下载过取工程里保存的，再没有取块里自带的）。"""
    from ..editor_api import load_draft
    pid = pid or rt.pid
    d = load_draft(pid)
    model = copy.deepcopy(d['model']) if d and isinstance(d.get('model'), dict) and d['model'].get('blocks') is not None else rt.build_cfg()
    model.get('plant', {}).pop('modbus_port', None)
    programs = {}
    try:
        from ..plc import store as ps
    except ImportError:                                 # pragma: no cover
        ps = None
    for b in model.get('blocks') or []:
        if b.get('type') != 'plc':
            continue
        rec = {}
        if ps is not None:
            rec = ps.load(pid, 'cells', b['id'], {}) or {}
            if not rec and (b.get('params') or {}).get('migrated_from'):
                rec = ps.load(pid, 'cells', b['params']['migrated_from'], {}) or {}
        got = None
        for k in ('downloaded', 'program'):
            if isinstance(rec.get(k), dict) and rec[k].get('source') not in (None, '', {}):
                got = rec[k]
                break
        if got is None:
            v = (b.get('params') or {}).get('program')
            got = v if isinstance(v, dict) and v.get('source') not in (None, '', {}) else None
        if got is not None:
            programs[b['id']] = copy.deepcopy(got)
    info = summary(model, programs)
    info['id'] = pid
    return model, programs, info


def summary(model, programs=None):
    bl = model.get('blocks') or []
    by = {}
    for b in bl:
        by[b.get('type')] = by.get(b.get('type'), 0) + 1
    return {'name': (model.get('plant') or {}).get('name') or '', 'blocks': len(bl), 'types': by,
            'plcs': sorted(b['id'] for b in bl if b.get('type') == 'plc'), 'programs': sorted((programs or {}).keys()),
            'links': len(model.get('links') or [])}


def controlled(model):
    """每台 PLC 通过信号线控制的设备：{PLC 编号: {设备编号…}}。"""
    blocks = {b.get('id'): b for b in model.get('blocks') or []}
    out = {k: set() for k, b in blocks.items() if b.get('type') == 'plc'}
    for l in model.get('links') or []:
        if l.get('kind') != 'signal':
            continue
        a, b = l.get('from'), l.get('to')
        for p, o in ((a, b), (b, a)):
            if p in out and o in blocks and blocks[o].get('type') not in NOT_DEVICES:
                out[p].add(o)
    return out


# ---------------------------------------------------------------- 评分（进程池）
def _sim(model, programs, hours, wall_limit=240):
    from .. import analysis, history
    from ..core import Plant
    cfg = copy.deepcopy(model)
    pl = cfg.setdefault('plant', {})
    pl['warmup_h'] = 0
    pl.pop('modbus_port', None)
    for b in cfg.get('blocks') or []:
        if b.get('type') == 'plc' and b['id'] in (programs or {}):
            b.setdefault('params', {})['program'] = copy.deepcopy(programs[b['id']])
    p = Plant(cfg)
    for st in p.all_stations():                         # 软 PLC：装了程序就运行（和学生在本机点"运行"一样）
        rp = getattr(st, 'plc', None) if getattr(st, 'kind', '') == 'plc' else None
        if rp is not None and getattr(rp, 'prog', None) is not None and getattr(rp, 'state', '') == 'STOP' and hasattr(rp, 'run'):
            rp.run()
    p.hourly.append(history.snapshot(p))
    end = hours * 3600
    t_wall = time.time()
    while p.t < end - 1e-6:
        p.run_for(min(600.0, end - p.t))
        if time.time() - t_wall > wall_limit:
            raise TimeoutError(_tr('仿真太慢：{wall_limit} 秒只跑了 {v:.1f} 小时（工厂太大或 PLC 扫描太密），请老师把仿真时长调短', wall_limit=wall_limit, v=p.t / 3600))
    s = history.summary(p, 0, p.t)
    st = analysis.stats(p, 0, p.t)
    oee = {}
    for o in st['objects']:
        if o.get('oee') is not None:
            oee[o['id']] = o['oee']
            if o.get('name'):
                oee.setdefault('name:' + str(o['name']), o['oee'])
    names = {sid: getattr(x, 'name', sid) for sid, x in p.stations.items()}
    for sid, v in list(oee.items()):
        if not sid.startswith('name:') and names.get(sid):
            oee.setdefault('name:' + str(names[sid]), v)
    return {'good': s['good'], 'good_per_h': s.get('good_per_h'), 'scrap': s.get('scrap'), 'oee': oee, 'hours': round(p.t / 3600, 2),
            'oee_avg': st['plant'].get('oee_avg')}


def score_job(spec, art):
    """进程池里调用：按 spec.checks 检查提交的工厂。返回和其他评分一样的结构；没有检查项时 manual=True（只等老师评分）。"""
    log = []
    try:
        spec = spec or {}
        checks = spec.get('checks') or []
        model = (art or {}).get('model') or {}
        programs = (art or {}).get('programs') or {}
        info = summary(model, programs)
        if not checks:
            return {'ok': True, 'manual': True, 'score': 0.0, 'max': 0.0, 'details': [], 'stats': info, 'log': [_tr('没有自动检查，等老师评分')]}
        hours = float(spec.get('hours') or 8)
        from ..flow.model import validate
        v = validate(model) if isinstance(model.get('blocks'), list) else {'ok': False, 'issues': [{'level': 'error', 'msg': _tr('不是 2.0 工厂模型（没有 blocks）')}]}
        errs = [i.get('msg') for i in v.get('issues') or [] if i.get('level') == 'error']
        sim = None
        sim_err = None
        if any(c['kind'] in ('good', 'oee') for c in checks):
            if errs:
                sim_err = _tr('模型有错误，不能仿真：') + _tr('；').join(errs[:3])
            else:
                try:
                    sim = _sim(model, programs, hours)
                    log.append(_tr('仿真 {hours} 小时：合格品 {good} 件', hours=sim['hours'], good=sim['good']))
                except Exception as e:                  # noqa: BLE001
                    sim_err = _tr('仿真出错：{e}', e=e)
            if sim_err:
                log.append(sim_err)
        ctl = controlled(model)
        types = info['types']
        det = []
        rs = rules(spec)
        total = 0.0
        for r, c in zip(rs, checks):
            k = c['kind']
            ok, val, why = False, None, ''
            if k == 'valid':
                ok, val = not errs, (1 if not errs else 0)
                why = _tr('；').join(errs[:3])
            elif k == 'block':
                val = types.get(c['type'], 0)
                ok = val >= c.get('min', 1)
            elif k == 'plc_control':
                val = max((len(x) for x in ctl.values()), default=0)
                ok = val >= c.get('min', 1)
                if not ctl:
                    why = _tr('工厂里没有 PLC')
            elif k == 'good':
                if sim is not None:
                    val = sim['good']
                    ok = val >= c.get('min', 0)
                else:
                    why = sim_err or ''
            elif k == 'oee':
                if sim is not None:
                    o = sim['oee'].get(c['block'])
                    if o is None:
                        o = sim['oee'].get('name:' + c['block'])
                    if o is None:
                        why = _tr('工厂里没有叫 {block} 的设备（或它没有 OEE）', block=c['block'])
                    else:
                        val = round(float(o) * 100, 1)
                        ok = float(o) >= float(c.get('min') or 0)
                else:
                    why = sim_err or ''
            sc = r['weight'] if ok else 0.0
            total += sc
            shown = val if val is not None else '—'
            det.append({'key': r['key'], 'label': r['label'], 'kind': 'check', 'op': r['op'], 'target': r['value'], 'value': val, 'weight': r['weight'],
                        'score': sc, 'points': sc, 'ok': bool(ok), 'desc': why,
                        'text': _tr('{label}：{v}（实际 {shown}{v2}）', label=r['label'], v=_tr('做到了') if ok else _tr('没做到'), shown=shown, v2=r.get('unit') or '') + (_tr('；{why}', why=why) if why and not ok else '')})
        stats = dict(info)
        if sim is not None:
            stats.update(good=sim['good'], good_per_h=sim['good_per_h'], scrap=sim['scrap'], oee_avg=sim['oee_avg'], sim_hours=sim['hours'])
        npass = sum(1 for d in det if d['ok'])
        return {'ok': True, 'score': round(100.0 * npass / len(det), 2) if det else 0.0, 'max': 100.0, 'details': det, 'stats': stats, 'log': log}
    except Exception as e:                              # noqa: BLE001
        import traceback
        return {'ok': False, 'error': _tr('检查出错：{v}: {e}', v=type(e).__name__, e=e), 'score': 0, 'max': 100, 'details': [], 'log': log + [traceback.format_exc()[-800:]]}
