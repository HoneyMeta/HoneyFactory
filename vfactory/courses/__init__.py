"""课程：一组按顺序推进的课，每课基于一个工厂（plant / diagnose）或一个控制单元场景（cell），包含任务书、提示、评分规则。

文件：vfactory/courses/<课程>.json（由 build.py 生成，也可以手写），课里的工厂 vfactory/courses/plants/<工厂>.yaml。
  {id, name, desc, level, chapters:[{id, title, lessons:[{id, title, kind, scene|plant, brief_md, hints, rules, time_h, seed, warmup_h,
   unlock, lock, costs, faults, reference}]}]}
课的类型：
  cell      控制单元场景（vfactory/control/scenes），评分用控制层的 score_scene
  plant     产线任务：学生改模型/参数后提交，服务器用固定随机种子跑 time_h 小时，按规则评分（scoring.py）
  diagnose  排故：开局把 faults 里的参数"弄坏"，学生在图上指出设备和故障类型并修好
解锁：默认上一课 ≥ 60 分解锁下一课（lesson.unlock 可改，老师可以对班级全部开放）。

4.6 起（格式向下兼容，旧课程文件原样可用）：
  课的类型多了 quiz（测验：单选/多选/判断/填数，没有沙箱）、point（在图上点设备：产线沙箱 + 点选题）、mes（MES 操作：对 MES 状态的声明式检查）。
  评分规则的判断在 rules.py（服务器、客户端同一份）。
  lesson.unlock：{min: 60}（上一课的及格分）、{after: [课编号…], min}（指定先修课，全部 ≥ min 才解锁）、{free: true}（不锁）。
  lesson.params：[{block, param, value}] 在模板工厂上先改好的参数；lesson.model：内嵌的完整工厂模型（老师做的课发布时会把模板冻结进来）；
  lesson.plant 可以写 "tpl:<templates 下的模板名>"。lesson.lock 多了 structure（不能增删设备/连线）、editable（只有这些 [块, 参数] 能改）。
  course.cover：封面（/brand/… 或课程包里的 assets/…）；course.tags；course.origin = builtin | authored | package。
老师做的课程（authoring）：草稿在数据库，发布后冻结成 data/teach/courses/<编号>.json（服务器用这一份评分）和签名的课程包 .vfcourse（coursepkg.py）；
客户端装到 data/client/courses/<编号>.vfcourse，每次读取都验签名，被改过的包不加载。
"""
from ..i18n import _tr
import copy
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PLANT_DIR = os.path.join(HERE, 'plants')
_cache: dict = {}
KIND_CN = {'cell': 'PLC 控制', 'plant': '产线任务', 'diagnose': '排故', 'quiz': '测验', 'point': '点选设备', 'mes': 'MES 操作任务'}
KINDS = tuple(KIND_CN)


def _load(path):
    """A course / course plant file with its display texts in the current language (content map <dir>/i18n/<name>.en.json)."""
    from ..i18n import content
    return content(_load_raw(path), path)


def _load_raw(path):
    mt = os.path.getmtime(path)
    c = _cache.get(path)
    if c and c[0] == mt:
        return c[1]
    if path.endswith('.json'):
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    else:
        from ..server import read_yaml
        d = read_yaml(path)
    _cache[path] = (mt, d)
    return d


def course_ids():
    """内置课程（随程序发布的 vfactory/courses/*.json）。"""
    return [os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(HERE, '*.json')))]


def authored_dir():
    from .. import paths
    return paths.data('teach', 'courses')


def installed_dir():
    from .. import paths
    return paths.data('client', 'courses')


def _safe(cid):
    return os.path.basename(str(cid or '')).replace('..', '')


def authored_ids():
    return [os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(authored_dir(), '*.json'))) if not os.path.basename(p).startswith('_preview-')]


def installed_ids():
    return [os.path.basename(p)[:-9] for p in sorted(glob.glob(os.path.join(installed_dir(), '*.vfcourse')))]


def all_course_ids():
    seen, out = set(), []
    for c in course_ids() + authored_ids() + installed_ids():
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


_pkg_cache: dict = {}
package_error: dict = {}


def _load_installed(cid):
    """客户端装的课程包：文件变了就重新验签名（被改过的包返回 None，原因记在 package_error）。"""
    p = os.path.join(installed_dir(), f'{_safe(cid)}.vfcourse')
    if not os.path.exists(p):
        return None
    mt = os.path.getmtime(p)
    c = _pkg_cache.get(p)
    if c and c[0] == mt:
        return c[1]
    from . import coursepkg
    try:
        with open(p, 'rb') as f:
            d = coursepkg.verify_installed(f.read())
        course = d['course']
        course['origin'] = 'package'
        course['package'] = {k: d['manifest'].get(k) for k in ('version', 'content_sha256', 'created', 'server', 'engine')}
        for ch in course.get('chapters') or []:
            for l in ch.get('lessons') or []:
                l['_course'] = course['id']
        package_error.pop(cid, None)
    except Exception as e:                           # noqa: BLE001  签名不对 / 文件坏了：不加载
        package_error[cid] = str(e)
        course = None
    _pkg_cache[p] = (mt, course)
    return course


def get_course(cid):
    cid = _safe(cid)
    p = os.path.join(HERE, f'{cid}.json')
    if os.path.exists(p):
        return copy.deepcopy(_load(p))
    p = os.path.join(authored_dir(), f'{cid}.json')
    if os.path.exists(p):
        c = copy.deepcopy(_load(p))
        c['origin'] = 'authored'
        return c
    c = _load_installed(cid)
    return copy.deepcopy(c) if c else None


def lessons(course):
    """按顺序展开：[(章, 课)]"""
    return [(ch, l) for ch in course.get('chapters') or [] for l in ch.get('lessons') or []]


def get_lesson(cid, lid):
    c = get_course(cid)
    if not c:
        return None, None
    for ch, l in lessons(c):
        if l['id'] == lid:
            return c, l
    return c, None


def course_card(c):
    ls = lessons(c)
    return {'id': c['id'], 'name': c['name'], 'desc': c.get('desc', ''), 'level': c.get('level'), 'lessons': len(ls), 'cover': c.get('cover'),
            'tags': c.get('tags') or [], 'origin': c.get('origin') or 'builtin', 'owner': c.get('owner'), 'order': c.get('order'),
            'version': (c.get('package') or {}).get('version') or c.get('version'),
            'kinds': sorted({l.get('kind', 'plant') for _ch, l in ls}),
            'chapters': [{'id': ch['id'], 'title': ch['title'], 'lessons': [{'id': l['id'], 'title': l['title'], 'kind': l.get('kind', 'plant')}
                                                                       for l in ch.get('lessons') or []]} for ch in c.get('chapters') or []]}


def list_courses(include=('builtin',)):
    """课程目录。include：builtin（内置）、authored（服务器上老师发布的）、package（客户端装的课程包）。默认只列内置（客户端"本机自学"用）。"""
    ids = []
    if 'builtin' in include:
        ids += course_ids()
    if 'authored' in include:
        ids += [i for i in authored_ids() if i not in ids]
    if 'package' in include:
        ids += [i for i in installed_ids() if i not in ids]
    out = []
    for cid in ids:
        c = get_course(cid)
        if c:
            out.append(course_card(c))
    out.sort(key=lambda x: (0 if x['origin'] == 'builtin' else 1, x.get('level') or 99, x.get('order') or 99, x['id']))
    return out


def plant_model(lesson):
    """本课原始（正常）工厂模型（2.0；旧格式在内存里转换）。
    lesson.model（内嵌模型）> lesson.plant = "tpl:<模板>"（templates/）> vfactory/courses/plants/<plant>.yaml；再套上 lesson.params。"""
    if isinstance(lesson.get('model'), dict):
        m = copy.deepcopy(lesson['model'])
    else:
        name = str(lesson.get('plant') or '')
        if name.startswith('tpl:'):
            from ..server import TEMPLATES
            p = os.path.join(TEMPLATES, f"{os.path.basename(name[4:])}.yaml")
        else:
            p = os.path.join(PLANT_DIR, f"{os.path.basename(name)}.yaml")
        m = copy.deepcopy(_load(p))
    if 'blocks' not in m:
        from ..flow.model import to_v2
        m = to_v2(m)
    for e in lesson.get('params') or []:
        for b in m.get('blocks') or []:
            if b['id'] == e.get('block') and e.get('param'):
                b.setdefault('params', {})[e['param']] = copy.deepcopy(e.get('value'))
    return m


def plant_choices():
    """老师做产线课 / 点选课时可选的工厂：课程自带的工厂 + templates/ 下的模板（带设备和可改的参数）。"""
    out = []
    for p in sorted(glob.glob(os.path.join(PLANT_DIR, '*.yaml'))):
        out.append({'id': os.path.basename(p)[:-5], 'source': 'course'})
    from ..server import TEMPLATES
    for p in sorted(glob.glob(os.path.join(TEMPLATES, '*.yaml'))):
        out.append({'id': 'tpl:' + os.path.basename(p)[:-5], 'source': 'template'})
    for o in out:
        try:
            m = plant_model({'plant': o['id']})
            o['name'] = (m.get('plant') or {}).get('name') or o['id']
            o['blocks'] = [{'id': b['id'], 'type': b.get('type'), 'name': b.get('name') or b['id'],
                            'params': {k: v for k, v in (b.get('params') or {}).items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}}
                           for b in m.get('blocks') or []]
        except Exception as e:                       # noqa: BLE001
            o['error'] = str(e)
    return out


def start_model(lesson, title=''):
    """学生沙箱的起始模型：原始模型 + 排故课的隐藏故障。"""
    m = plant_model(lesson)
    for f in lesson.get('faults') or []:
        for b in m.get('blocks') or []:
            if b['id'] == f['block']:
                b.setdefault('params', {})[f['param']] = copy.deepcopy(f['value'])
    m['plant'].pop('modbus_port', None)
    if title:
        m['plant']['name'] = title[:40]
    return m


def reference_model(lesson):
    from ..flow.model import apply_ops
    m, _ = apply_ops(start_model(lesson), (lesson.get('reference') or {}).get('ops') or [])
    return m


def public_lesson(lesson, hints=True):
    """学生看到的课：去掉参考答案、隐藏故障和选择题答案。"""
    from .rules import describe
    from .scoring import _label
    rules = []
    for r in lesson.get('rules') or []:
        x = {k: r.get(k) for k in ('key', 'kind', 'label', 'metric', 'op', 'value', 'weight', 'choices', 'pick', 'kinds', 'qtype', 'unit', 'query')
             if r.get(k) is not None}
        x['label'] = _label(r, lesson)               # 4.6.1：老师的名称没意义（"1"）时是生成的说明
        x['title'] = x['label']
        x['goal'] = describe(r, lesson)              # "8 小时合格品 ≥ 100 件"（作答题不含答案）
        if x.get('kind') == 'answer':
            x.pop('value', None)
            x.setdefault('qtype', 'pick' if r.get('pick') else 'single')
        rules.append(x)
    return {'id': lesson['id'], 'title': lesson['title'], 'kind': lesson.get('kind', 'plant'), 'kind_cn': KIND_CN.get(lesson.get('kind', 'plant')),
            'brief_md': lesson.get('brief_md', ''), 'hints': (lesson.get('hints') or []) if hints else [], 'rules': rules,
            'time_h': lesson.get('time_h'), 'scene': lesson.get('scene'), 'sandbox': lesson.get('kind', 'plant') not in ('quiz', 'mes')}


def score_job(cid, lid, model, answers):
    """进程池里调用：产线/排故课评分。"""
    from .scoring import score_lesson
    c, l = get_lesson(cid, lid)
    if not l:
        err = package_error.get(_safe(cid))
        return {'ok': False, 'error': _tr('没有课 {cid}/{lid}', cid=cid, lid=lid) + (_tr('（课程包校验没通过：{err}）', err=err) if err else ''), 'score': 0, 'max': 100, 'details': []}
    l.setdefault('_course', c['id'])
    if l.get('kind') in ('quiz', 'mes'):
        from .rules import load_mes_providers
        load_mes_providers()
        return score_lesson(l, model, None, answers or {})
    return score_lesson(l, model, plant_model(l), answers or {})
