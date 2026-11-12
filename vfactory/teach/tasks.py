"""作业的"任务"抽象：同一套沙箱、提交、评分、旁观流程，背后可以是控制单元场景（cell）、课程里的产线/排故课（plant / diagnose），
或者 4.4 的"提交工厂"作业（factory：学生在客户端交自己建的工厂，没有沙箱，见 factory.py）。

    t = task_of(assignment)          # 没有 course/lesson 字段的旧作业都是场景作业
    t.plant_cfg(title)               沙箱的起始工厂模型
    t.public(hints)                  学生看到的任务（任务书、I/O 表、评分规则、提示），不含答案
    t.faults()                       老师可以注入的故障 [{comp, kind, label}]
    t.inject(rt, comp, kind)         注入；返回错误文字或 None
    t.artifact(rt)                   提交物：cell = 学生的 PLC 程序；plant = 学生当前的工厂模型（编辑器草稿优先）
    t.score_call(artifact, answers)  (进程池函数, 参数)
    t.live(rt, answers)              每条评分规则的实时进度（运行中估计）
"""
from ..i18n import _tr, variants
import copy

from fastapi import HTTPException

from .. import courses
from . import scenes


class CellTask:
    kind = 'cell'

    def __init__(self, scene, lesson=None):
        self.scene = scene
        self.lesson = lesson
        self.id = scene['id']
        self.name = (lesson or {}).get('title') or scenes.name_of(scene)

    def plant_cfg(self, title=''):
        return scenes.plant_cfg(self.scene, title)

    def public(self, hints=True):
        d = scenes.public_scene(self.scene, hints)
        d.update(kind='cell', kind_cn=_tr('PLC 控制'), brief_md=self.plc_note() + d.get('task_md', ''), plc=self.plc_id())
        return d

    def plc_id(self):
        """沙箱里学生编程的 PLC 块编号（4.3：PLC 是独立设备，信号线接控制单元的全部 I/O；场景工厂里固定是 PLC1）。"""
        if not hasattr(self, '_plc_id'):
            try:
                self._plc_id = scenes.plc_id_of_cfg(self.plant_cfg())
            except Exception:                                 # noqa: BLE001
                self._plc_id = None
        return self._plc_id

    def plc_note(self):
        p = self.plc_id()
        if not p:
            return ''
        return (_tr('> 本课的 PLC 是一台单独的设备 **{p}**（PLC 块），通过信号线读写实训单元的全部 I/O，程序里的变量名就是 I/O 表里的名称。点工作台最左边竖排图标里的"PLC"（芯片图标）打开 PLC 面板，点"编程"打开编程窗口（也可以在画布上点 {p}，再点浮出的工具条或右边"属性"页里的"编程"）；写好后点编程窗口工具栏上的"下载"，第一次下载后 PLC 自动运行，再按操作台上的"启动"试一试。', p=p) + '\n\n')

    def faults(self):
        return scenes.faults_of(self.scene)

    def inject(self, rt, comp, kind, bid=None):
        return scenes.inject(rt, comp, kind, bid)

    def clear(self, rt):
        scenes.clear_faults(rt)

    def artifact(self, rt):
        return scenes.get_program(rt)

    def active_faults(self, rt):
        return scenes.active_faults(rt)

    def clear_one(self, rt, comp, kind):
        scenes.clear_one(rt, comp)

    def parts(self, rt):
        """排故时可以选的部件和故障类型。"""
        from ..control import catalog as K
        return {'comps': scenes.components(rt), 'kinds': [{'kind': k, 'label': v} for k, v in K.FAULTS.items()]}

    def overlay(self):
        """4.6 老师做的 PLC 课：只用场景的部分评分项、追加测试步骤和评分项（scenes.overlay_scene）。"""
        l = self.lesson or {}
        o = {k: l.get(k) for k in ('rubric', 'tests', 'extra_rules') if l.get(k) is not None}
        return o or None

    def score_call(self, artifact, answers=None):
        o = self.overlay()
        return (scenes.score_job, (self.scene['id'], artifact, o)) if o else (scenes.score_job, (self.scene['id'], artifact))

    def live(self, rt, answers=None):
        return None

    def reference(self):
        return scenes.reference_of(self.scene)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class LessonTask:
    """课程里的产线课 / 排故课。"""

    def __init__(self, course, lesson):
        self.course, self.lesson = course, lesson
        self.kind = lesson.get('kind', 'plant')
        self.id = f"{course['id']}/{lesson['id']}"
        self.name = lesson['title']

    def plant_cfg(self, title=''):
        return courses.start_model(self.lesson, title)

    def public(self, hints=True):
        d = courses.public_lesson(self.lesson, hints)
        d.update(name=self.lesson['title'], task_md=d['brief_md'], io=[], course=self.course['id'], course_name=self.course['name'])
        return d

    def faults(self):
        out = []
        for b in courses.plant_model(self.lesson).get('blocks') or []:
            if b.get('type') in ('processor', 'batch', 'inspect', 'assembly'):
                out.append({'comp': b['id'], 'kind': 'failure', 'label': _tr('{v} 故障停机', v=b.get('name') or b['id'])})
            if b.get('type') == 'processor':
                out.append({'comp': b['id'], 'kind': 'slow', 'label': _tr('{v} 节拍变慢 30%', v=b.get('name') or b['id'])})
        return out

    def inject(self, rt, comp, kind, bid=None):
        st = rt.plant.stations.get(comp)
        if st is None:
            return _tr('沙箱里没有设备 {comp}', comp=comp)
        err = st.inject(kind)
        if err:
            return err
        rt.plant.log(comp, 'inject', _tr('老师注入故障：{get}', get=st.fault_kinds.get(kind, kind)))
        return None

    def clear(self, rt):
        for st in rt.plant.stations.values():
            if getattr(st, 'fault_kinds', None):
                try:
                    st.inject('clear')
                except Exception:
                    pass

    def active_faults(self, rt):
        out = []
        for st in rt.plant.stations.values():
            if getattr(st, 'failure', None) is not None and st.failure.repair_left > 0 and any(str(st.alarm or '').endswith(v) for v in variants('（人工注入）') | {_tr('设备故障（人工注入）')[len(_tr('设备故障')):]}):
                out.append((st.id, 'failure'))
            if getattr(st, 'slow', 1.0) > 1.0:
                out.append((st.id, 'slow'))
        return out

    def clear_one(self, rt, comp, kind):
        st = rt.plant.stations.get(comp)
        if st is not None:
            if kind == 'slow':
                st.slow = 1.0
            else:
                st.inject('clear')

    def parts(self, rt):
        bl = [b for b in courses.plant_model(self.lesson).get('blocks') or [] if b.get('type') in ('processor', 'batch', 'inspect', 'assembly')]
        return {'comps': [{'id': b['id'], 'type': b['type'], 'label': b.get('name') or b['id']} for b in bl],
                'kinds': [{'kind': 'failure', 'label': _tr('故障停机')}, {'kind': 'slow', 'label': _tr('节拍变慢')}]}

    def artifact(self, rt):
        from ..editor_api import load_draft
        d = load_draft(rt.pid)
        return copy.deepcopy(d['model']) if d and d.get('model') else rt.build_cfg()

    def score_call(self, artifact, answers=None):
        return courses.score_job, (self.course['id'], self.lesson['id'], artifact, answers or {})

    def reference(self):
        return self.lesson.get('reference')

    def live(self, rt, answers=None):
        """评分规则的实时进度：成本/数量/布局用当前模型精确算；指标用沙箱里已经跑过的时间估计。"""
        from ..courses.rules import describe, fmt_value, metric_name
        from ..courses.scoring import OP_CN, OPS, _label, static_metrics
        model = self.artifact(rt)
        sm = static_metrics(model, self.lesson)
        p = rt.plant
        hrs = max(1e-6, p.t / 3600)
        k = p.kpi
        lts = [lt for _t, lt in list(p.lead_times)[-200:]]
        wl = [w for _t, w in list(p.wip_log)[-120:]]
        energy = sum(s.energy_kwh for s in p.stations.values())
        est = {'good': k['good'], 'good_per_h': round(k['good'] / hrs, 2), 'scrap': k['scrap'],
               'scrap_rate': round(k['scrap'] / k['castings'], 4) if k['castings'] else 0.0,
               'wip_avg': round(sum(wl) / len(wl), 2) if wl else p.wip_now(), 'lead_mean_min': round(sum(lts) / len(lts) / 60, 2) if lts else None,
               'energy_kwh': round(energy, 1), 'kwh_per_good': round(energy / k['good'], 3) if k['good'] else None, 'escape': k.get('escape', 0)}
        if p.plan.orders:
            est['orders_done'] = sum(1 for o in p.plan.orders if o['done'] >= o['qty'])
            est['orders_open'] = sum(1 for o in p.plan.orders if o['done'] < o['qty'])
        out = []
        for r in self.lesson.get('rules') or []:
            kind = r.get('kind', 'kpi')
            row = {'key': r.get('key'), 'kind': kind, 'label': _label(r, self.lesson), 'op': r.get('op'), 'target': r.get('value'), 'weight': r.get('weight'),
                   'goal': describe(r, self.lesson)}
            row['title'] = row['label']
            if kind == 'answer':
                row['value'] = (answers or {}).get(r['key'])
                row['answered'] = row['value'] is not None
                row['op'] = None
                row['target'] = None
            else:
                m = r.get('metric') or ('cost' if kind == 'budget' else '')
                v = sm.get(m) if kind in ('budget', 'limit') else est.get(m)
                row['value'] = round(v, 3) if isinstance(v, float) else v
                row['exact'] = kind in ('budget', 'limit')
                row['ok'] = None if _num(v) is None else bool(OPS.get(r.get('op', '>='), OPS['>='])(float(v), float(r.get('value'))))
                row['text'] = f"{OP_CN.get(r.get('op'), r.get('op'))} {fmt_value(metric_name(r), r.get('value'))}"
                row['value_text'] = fmt_value(metric_name(r), row['value'])
                if kind == 'kpi' and m not in est:
                    row['note'] = _tr('提交后按完整运行计算')
            out.append(row)
        notes = []
        try:                                        # 4.5：改了本课锁定的参数——实时数字用的是改过的模型，提交时会改回原值，先说清楚
            from ..courses.scoring import enforce
            _m, notes = enforce(model, self.lesson, courses.plant_model(self.lesson))
        except Exception:                           # noqa: BLE001
            notes = []
        return {'rules': out, 'sim_hours': round(hrs, 2), 'cost': sm.get('cost'), 'cost_rows': sm.get('cost_rows'), 'locked': notes}


class QuizTask(LessonTask):
    """4.6 测验课（kind=quiz）：没有沙箱，只交作答（单选/多选/判断/填数），服务器和客户端用同一份规则判分。"""
    sandbox = False

    def plant_cfg(self, title=''):
        from ..server import TEMPLATES, read_yaml
        import os
        c = read_yaml(os.path.join(TEMPLATES, 'blank.yaml'))
        c.setdefault('plant', {})['name'] = (title or self.name)[:40]
        c.get('plant', {}).pop('modbus_port', None)
        return c

    def faults(self):
        return []

    def inject(self, rt, comp, kind, bid=None):
        return _tr('测验课没有沙箱，不能注入故障')

    def clear(self, rt):
        pass

    def active_faults(self, rt):
        return []

    def clear_one(self, rt, comp, kind):
        pass

    def parts(self, rt):
        return {'comps': [], 'kinds': []}

    def artifact(self, rt):
        return None

    def live(self, rt, answers=None):
        return None


class MesTask(QuizTask):
    """4.6 MES 操作课（kind=mes）：学生在 MES 里操作，提交时按声明式规则检查 MES 状态（取数函数由 MES 模块注册，rules.register_mes）。"""



class FactoryTask:
    """提交工厂（4.4）：没有沙箱和起始模型，学生在客户端"我的工厂"里建，交的是 {model, programs}。"""
    kind = 'factory'

    def __init__(self, a):
        from . import factory
        self.f = factory
        self.a = a
        self.spec = a.get('spec') if isinstance(a.get('spec'), dict) else {}
        self.id = f"factory/{a.get('id')}"
        self.name = a.get('title') or _tr('工厂设计')
        self.scene = None
        self.lesson = None

    def plant_cfg(self, title=''):
        from ..server import TEMPLATES, read_yaml
        import os
        c = read_yaml(os.path.join(TEMPLATES, 'blank.yaml'))
        if title:
            c.setdefault('plant', {})['name'] = title[:40]
        c.get('plant', {}).pop('modbus_port', None)
        return c

    def public(self, hints=True):
        return self.f.public(self.spec, self.name, self.a.get('descr') or '')

    def faults(self):
        return []

    def inject(self, rt, comp, kind, bid=None):
        return _tr('提交工厂作业没有沙箱，不能注入故障')

    def clear(self, rt):
        pass

    def active_faults(self, rt):
        return []

    def clear_one(self, rt, comp, kind):
        pass

    def parts(self, rt):
        return {'comps': [], 'kinds': []}

    def artifact(self, rt):
        model, programs, _info = self.f.collect(rt)
        return {'model': model, 'programs': programs}

    def score_call(self, artifact, answers=None):
        return self.f.score_job, (copy.deepcopy(self.spec), artifact)

    def live(self, rt, answers=None):
        return None

    def reference(self):
        return None


def task_of(a):
    """作业 → 任务对象；找不到场景/课时 404。"""
    if a.get('kind') == 'factory':
        return FactoryTask(a)
    if a.get('course') and a.get('lesson'):
        c, l = courses.get_lesson(a['course'], a['lesson'])
        if not l:
            raise HTTPException(404, _tr('课程里没有这课：{course}/{lesson}', course=a['course'], lesson=a['lesson']))
        if l.get('kind') == 'cell':
            s = scenes.load_scene(l['scene'])
            if not s:
                raise HTTPException(404, _tr('场景库里没有 {scene}', scene=l['scene']))
            return CellTask(scenes.overlay_scene(s, l), l)
        if l.get('kind') == 'quiz':
            return QuizTask(c, l)
        if l.get('kind') == 'mes':
            return MesTask(c, l)
        return LessonTask(c, l)
    s = scenes.load_scene(a.get('scene'))
    if not s:
        raise HTTPException(404, _tr('场景库里没有 {get}', get=a.get('scene')))
    return CellTask(s)
