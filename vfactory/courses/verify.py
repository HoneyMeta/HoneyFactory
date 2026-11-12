"""检查内置课程：每个产线/排故课，起始模型（学生拿到的）得分低、参考答案满分；控制课的场景存在。

    python -m vfactory.courses.verify [课程编号 …] [--lesson m04]
"""
from ..i18n import _tr
import sys
import time

from . import get_course, course_ids, lessons, plant_model, reference_model, start_model
from .scoring import score_lesson


def verify(cids=None, only=None, quiet=False):
    rows = []
    for cid in cids or course_ids():
        c = get_course(cid)
        for ch, l in lessons(c):
            if only and l['id'] not in only:
                continue
            kind = l.get('kind', 'plant')
            if kind == 'cell':
                from ..teach import scenes
                ok = scenes.load_scene(l['scene']) is not None
                rows.append({'course': cid, 'lesson': l['id'], 'title': l['title'], 'kind': kind, 'start': None, 'ref': None, 'ok': ok, 'secs': 0})
                continue
            if kind in ('quiz', 'mes'):                    # 4.6 测验 / MES 课：没作答 0 分、参考答案满分（MES 课要 MES 模块，只查规则）
                from .rules import validate_rule
                errs = [m for r in l.get('rules') or [] for m in validate_rule(r, kind)]
                a = score_lesson(l, None, None, {})
                b = score_lesson(l, None, None, (l.get('reference') or {}).get('answers') or {r['key']: r.get('answer') for r in l.get('rules') or [] if r.get('kind') == 'answer'}) if kind == 'quiz' else a
                ok = not errs and a['ok'] and (kind == 'mes' or (b['score'] >= b['max'] - 1e-6 and a['score'] < 60))
                rows.append({'course': cid, 'lesson': l['id'], 'title': l['title'], 'kind': kind, 'start': a['score'], 'ref': b['score'], 'max': b['max'],
                             'ok': ok, 'secs': 0, 'error': _tr('；').join(errs) or a.get('error'), 'log': []})
                if not quiet:
                    print(_tr('{v} {cid}/{id} {title}：起始 {score}，参考 {score2}/{max}', v='OK  ' if ok else 'BAD ', cid=cid, id=l['id'], title=l['title'], score=a['score'], score2=b['score'], max=b['max']), flush=True)
                continue
            t0 = time.time()
            orig = plant_model(l)
            a = score_lesson(l, start_model(l), orig, {})
            b = score_lesson(l, reference_model(l), orig, (l.get('reference') or {}).get('answers') or {})
            ok = a['ok'] and b['ok'] and b['score'] >= b['max'] - 1e-6 and a['score'] < 60
            r = {'course': cid, 'lesson': l['id'], 'title': l['title'], 'kind': kind, 'start': a['score'], 'ref': b['score'], 'max': b['max'], 'ok': ok,
                 'secs': round((time.time() - t0) / 2, 1), 'start_detail': [(d['key'], d['value'], d['ok']) for d in a['details']],
                 'ref_detail': [(d['key'], d['value'], d['ok']) for d in b['details']], 'log': (a.get('log') or []) + (b.get('log') or []),
                 'error': a.get('error') or b.get('error')}
            rows.append(r)
            if not quiet:
                print(_tr('{v} {cid}/{id} {title}：起始 {score}，参考 {score2}/{max}，单次评分 {secs}s', v='OK  ' if ok else 'BAD ', cid=cid, id=l['id'], title=l['title'], score=a['score'], score2=b['score'], max=b['max'], secs=r['secs']), flush=True)
                if not ok:
                    print(_tr('     起始'), r['start_detail'], _tr('\n     参考'), r['ref_detail'], '\n     ', r['error'] or '', r['log'][:3], flush=True)
    return rows


# ---------------- 4.6.1 出题检查：老师做的课，学生什么都不改能得几分、参考做法能不能及格 ----------------
EMPTY_PROGRAM = {'lang': 'st', 'vars': [], 'source': ''}
BASELINE_KINDS = ('plant', 'point', 'diagnose', 'cell')


def _brief(r, lesson=None):
    """评分结果 → 出题检查要的摘要（百分制分数 + 每条规则过没过、实际值）。"""
    from .rules import fmt_value, metric_name
    if not isinstance(r, dict):
        return None
    mx = float(r.get('max') or 0) or 100.0
    rules = {x.get('key'): x for x in (lesson or {}).get('rules') or [] if isinstance(x, dict)}
    det = []
    for d in r.get('details') or []:
        rule = rules.get(d.get('key')) or {}
        v = d.get('value')
        det.append({'key': d.get('key'), 'label': d.get('label') or d.get('key'), 'kind': d.get('kind') or rule.get('kind') or ('kpi' if rules else 'plc'), 'ok': bool(d.get('ok')),
                    'value': v if isinstance(v, (int, float, str)) or v is None else str(v), 'score': d.get('score'), 'weight': d.get('weight'),
                    'value_text': d.get('value_text') or (fmt_value(metric_name(rule), v) if rule and isinstance(v, (int, float)) else ('—' if v is None else str(v)))})
    err = r.get('error')
    if not r.get('ok') and isinstance(r.get('compile'), dict) and r['compile'].get('ok') is False:
        err = None                                   # PLC 空程序编译不过 = 0 分，不是出错
    if not r.get('ok') and not err and not isinstance(r.get('compile'), dict):
        err = _tr('评分出错')
    return {'ok': err is None, 'score': round(float(r.get('score') or 0), 2), 'max': round(mx, 2),
            'pct': round(float(r.get('score') or 0) / mx * 100, 1), 'details': det, 'error': err, 'log': [str(x)[:200] for x in (r.get('log') or [])[:4]]}


def baseline(lesson, ref=None, course_id=None):
    """进程池里跑（和学生交作业同一条评分路径）：本课起始模型（学生什么都不改）评一次；有参考做法时再评一次参考做法。
    ref：老师在预览里存的参考做法 {model?, program?, answers?}；没有时用课里自带的 reference（复制内置课程带来的）或 PLC 场景自带的参考程序。"""
    import copy
    l = copy.deepcopy(lesson)
    l.setdefault('_course', course_id or 'draft')
    kind = l.get('kind', 'plant')
    ref = ref or {}
    t0 = time.time()
    out = {'kind': kind, 'start': None, 'ref': None, 'ref_source': None}
    try:
        if kind == 'cell':
            from ..teach import scenes
            from ..control.scoring import score_scene
            s = scenes.load_scene(l.get('scene'))
            if not s:
                return {**out, 'error': _tr('PLC 场景 {get} 不存在', get=l.get('scene'))}
            s = scenes.overlay_scene(s, l)
            out['start'] = _brief(scenes.normalize_result(score_scene(s, copy.deepcopy(EMPTY_PROGRAM))))
            if ref.get('program'):
                out['ref'], out['ref_source'] = _brief(scenes.normalize_result(score_scene(s, copy.deepcopy(ref['program'])))), 'teacher'
            elif (s.get('reference') or {}).get('st'):
                out['ref'], out['ref_source'] = _brief(scenes.normalize_result(score_scene(s, None))), 'scene'
        else:
            orig = plant_model(l)
            out['start'] = _brief(score_lesson(l, start_model(l), orig, {}), l)
            if ref.get('model') or ref.get('answers'):
                out['ref'] = _brief(score_lesson(l, copy.deepcopy(ref.get('model') or start_model(l)), orig, copy.deepcopy(ref.get('answers') or {})), l)
                out['ref_source'] = 'teacher'
            elif isinstance(l.get('reference'), dict) and (l['reference'].get('ops') or l['reference'].get('answers')):
                out['ref'] = _brief(score_lesson(l, reference_model(l), orig, l['reference'].get('answers') or {}), l)
                out['ref_source'] = 'lesson'
    except Exception as e:                           # noqa: BLE001
        out['error'] = f'{type(e).__name__}: {e}'
    out['secs'] = round(time.time() - t0, 1)
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    only = None
    if '--lesson' in sys.argv:
        only = sys.argv[sys.argv.index('--lesson') + 1].split(',')
        args = [a for a in args if a not in only]
    rs = verify(args or None, only)
    bad = [r for r in rs if not r['ok']]
    print(f'\n{len(rs) - len(bad)}/{len(rs)} 课通过')
    sys.exit(1 if bad else 0)
