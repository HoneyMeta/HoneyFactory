"""4.6 老师做课程 / 课程包 / AI 评分的接口测试（先启动 serve，最好带 VF_LLM_FAKE=1）：python tests/courses_check.py
离线部分（不需要服务）：规则引擎判题、答案封存、课程包签名与防篡改（python tests/courses_check.py --offline）。
环境变量 VF_URL（默认 http://127.0.0.1:8800）。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
res = []
STAMP = time.strftime('%m%d%H%M%S')


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300], flush=True)


def offline():
    from vfactory.courses import rules as R
    from vfactory.courses.scoring import grade
    L = {'id': 'q1', 'kind': 'quiz', 'rules': [
        {'key': 'a', 'kind': 'answer', 'choices': ['x', 'y', 'z'], 'answer': 1, 'weight': 10},
        {'key': 'b', 'kind': 'answer', 'qtype': 'multi', 'choices': ['x', 'y', 'z'], 'answer': [0, 2], 'weight': 10},
        {'key': 'c', 'kind': 'answer', 'qtype': 'tf', 'answer': False, 'weight': 10},
        {'key': 'd', 'kind': 'answer', 'qtype': 'number', 'answer': 12.5, 'tol': 0.5, 'weight': 10},
        {'key': 'e', 'kind': 'answer', 'pick': True, 'answer': ['M3', 'M3B'], 'weight': 10}]}
    full = {'a': 1, 'b': [2, 0], 'c': False, 'd': 12.9, 'e': 'M3B'}
    sc, mx, det = grade(L, {}, full)
    ok('规则引擎：单选/多选/判断/填数（误差内）/点选全对 = 满分', sc == mx == 50, det)
    sc2, _, det2 = grade(L, {}, {'a': 0, 'b': [0], 'c': True, 'd': 13.1, 'e': 'M1'})
    ok('规则引擎：全错 = 0', sc2 == 0, [d['ok'] for d in det2])
    ok('规则引擎：多选答案是字符串 "[0, 2]" 也认', R.check_answer(L['rules'][1], '[0, 2]', [0, 2]))
    import copy
    sealed = copy.deepcopy(L)
    R.seal_lesson(sealed, 'tc-x')
    ok('封存：课程包里不出现明文答案', all('answer' not in r and 'seal' in r for r in sealed['rules']), sealed['rules'][0])
    sealed['_course'] = 'tc-x'
    ok('封存后判分不变（客户端离线判分 = 服务器判分）', grade(sealed, {}, full)[0] == sc)
    ok('规则校验：拒绝带代码字段的规则', R.validate_rule({'key': 'x', 'kind': 'kpi', 'metric': 'good', 'op': '>=', 'value': 1, 'weight': 1, 'eval': '1'}))
    ok('规则校验：单选答案越界会报', R.validate_rule({'key': 'x', 'kind': 'answer', 'choices': ['a', 'b'], 'answer': 5, 'weight': 1}))
    # 4.6.2 提交后显示答案：作答 / 正确答案写成给学生看的话；解析和答案一起封存
    at = R.answer_text
    ok('答案文字：单选 / 多选 / 判断 / 填数 / 点选', at(L['rules'][0], 1) == 'B. y' and at(L['rules'][1], [2, 0]) == 'A. x；C. z' and at(L['rules'][2], False) == '错'
       and at(L['rules'][3], 12.5, correct=True) == '12.5（允许误差 ±0.5）' and at(L['rules'][4], ['M3', 'M3B'], {'M3': '3#铣削'}, correct=True) == 'M3（3#铣削） 或 M3B'
       and at(L['rules'][0], None) == '', [at(L['rules'][0], 1), at(L['rules'][1], [2, 0]), at(L['rules'][3], 12.5, correct=True), at(L['rules'][4], ['M3', 'M3B'], {'M3': '3#铣削'}, correct=True)])
    ex = copy.deepcopy(L)
    ex['rules'][0]['explain'] = '因为 y。'
    R.seal_lesson(ex, 'tc-x')
    ok('封存：解析也不出现明文，能还原', 'explain' not in ex['rules'][0] and ex['rules'][0].get('explain_seal') and R.explain_of(ex['rules'][0], ex, 'tc-x') == '因为 y。'
       and R.explain_of(ex['rules'][1], ex, 'tc-x') == '', ex['rules'][0])
    ok('规则校验：解析太长会报', R.validate_rule({'key': 'x', 'kind': 'answer', 'choices': ['a', 'b'], 'answer': 0, 'weight': 1, 'explain': '长' * 1001}))
    from vfactory import courses as C
    intro = C.get_course('intro_factory')
    i01 = next(l for ch in intro['chapters'] for l in ch['lessons'] if l['id'] == 'i01')
    ok('内置课程的题带解析（学生看到的课里没有）', all(r.get('explain') for r in i01['rules'] if r.get('kind') == 'answer')
       and not any('explain' in r for r in C.public_lesson(i01)['rules']), [r['key'] for r in i01['rules'] if not r.get('explain')])


def call(method, url, body=None, tok='', raw=False, timeout=300, data=None, ctype=None):
    h = {'Content-Type': ctype or 'application/json', **({'Authorization': 'Bearer ' + tok} if tok else {})}
    r = urllib.request.Request(B + url, method=method, data=data if data is not None else (json.dumps(body).encode() if body is not None else None), headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        d = f.read()
        return d if raw else json.loads(d)


def code(method, url, body=None, tok=''):
    try:
        call(method, url, body, tok, raw=True)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def err(method, url, body=None, tok=''):
    try:
        call(method, url, body, tok, raw=True)
        return 200, ''
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}').get('detail', '')


def login(u, pw):
    return call('POST', '/api/login', {'username': u, 'password': pw})['token']


def online():
    A = login('admin', 'honey123')
    users = [u['username'] for u in call('GET', '/api/admin/users', tok=A)['users']]
    if 'cc_teacher' not in users:
        call('POST', '/api/admin/users', {'username': 'cc_teacher', 'name': '课程老师', 'role': 'teacher', 'password': 'teach123'}, A)
    T = login('cc_teacher', 'teach123')
    cls = call('POST', '/api/teach/classes', {'name': f'课程编辑测试班 {STAMP}'}, T)
    stu = f'cc{STAMP[-6:]}'
    call('POST', f"/api/teach/classes/{cls['id']}/roster", {'csv': f'账号,姓名\n{stu},课程同学\n', 'default_password': '123456'}, T)
    S = login(stu, '123456')
    meta = call('GET', '/api/teach/authoring/meta', tok=T)
    ok('编辑器选项：5 种课的模板、PLC 场景（带评分项）、工厂模板', len(meta['templates']) == 5 and meta['scenes'] and meta['scenes'][0]['rules'] and meta['plants'],
       [t['id'] for t in meta['templates']])
    ok('签名算法 Ed25519', meta['signature'] == 'ed25519', meta['signature'])
    d = call('POST', '/api/teach/authoring', {'name': f'接口测试课 {STAMP}'}, T)
    cid = d['id']
    ok('新建课程草稿', cid.startswith('tc-') and d['errors'] > 0, d['issues'][:2])
    course = {'name': f'接口测试课 {STAMP}', 'desc': '测验 + PLC + 产线', 'level': 1, 'cover': '/brand/course-custom-quiz.png', 'chapters': [
        {'id': 'c1', 'title': '第一章', 'lessons': [
            {'id': 'q1', 'title': '小测', 'kind': 'quiz', 'brief_md': '答题', 'rules': [
                {'key': 'a', 'kind': 'answer', 'label': '急停按钮是常开还是常闭', 'choices': ['常开', '常闭'], 'answer': 1, 'weight': 50,
                 'explain': '急停要"失效偏向安全"：线断了也等于按下，所以用常闭。'},
                {'key': 'b', 'kind': 'answer', 'qtype': 'number', 'label': '节拍 60 秒，每小时最多几件', 'answer': 60, 'tol': 0.5, 'weight': 50}]},
            {'id': 'p1', 'title': '启停', 'kind': 'cell', 'scene': 's01_motor_latch', 'unlock': {'free': True}},
            {'id': 'l1', 'title': '产线', 'kind': 'plant', 'plant': 'mc02_serial', 'time_h': 2, 'seed': 7, 'unlock': {'after': ['q1']}, 'brief_md': '跑 2 小时，做出合格品。',
             'params': [], 'rules': [{'key': 'g', 'kind': 'kpi', 'metric': 'good', 'op': '>=', 'value': 1, 'weight': 100}]}]}]}
    v = call('PUT', f'/api/teach/authoring/{cid}', {'course': course}, T)
    ok('保存草稿：没有错误', v['errors'] == 0, v['issues'])
    bad = json.loads(json.dumps(course))
    bad['chapters'][0]['lessons'][0]['rules'][0]['answer'] = 7
    vb = call('PUT', f'/api/teach/authoring/{cid}', {'course': bad}, T)
    ok('校验：答案越界报错、不能发布', vb['errors'] > 0 and err('POST', f'/api/teach/authoring/{cid}/publish', {}, T)[0] == 400, vb['issues'][:1])
    call('PUT', f'/api/teach/authoring/{cid}', {'course': course}, T)
    pv = call('POST', f'/api/teach/authoring/{cid}/preview', {}, T)
    ok('预览：按学生的样子生成三课', pv['total'] == 3 and pv['preview'], [l['title'] for ch in pv['chapters'] for l in ch['lessons']])
    qa = pv['chapters'][0]['lessons'][0]['aid']
    call('PUT', f'/api/teach/assignments/{qa}/answers', {'answers': {'a': 1, 'b': 60}}, T)
    tr = call('POST', f'/api/teach/assignments/{qa}/submit', {}, T)
    ok('预览里老师试做测验 = 100（试做）', tr['score'] == 100 and tr['trial'], tr.get('score'))
    ok('预览班不出现在老师的班级列表', not any(c['name'] == '课程预览' for c in call('GET', '/api/teach/classes', tok=T)))
    p = call('POST', f'/api/teach/authoring/{cid}/publish', {}, T)
    ok('发布 v1：冻结 + 签名课程包', p['version'] == 1 and p['package']['signature'] == 'ed25519' and len(p['content_sha256']) == 64, p['package'])
    lib = call('GET', '/api/teach/courses', tok=T)
    ok('课程库里有这门课（老师自己的）', any(c['id'] == cid and c['origin'] == 'authored' for c in lib))
    r = call('POST', f'/api/teach/courses/{cid}/publish', {'class_id': cls['id']}, T)
    ok('发布到班级：生成 3 个作业', r['created'] == 3, r)
    m = call('GET', '/api/teach/my/courses', tok=S)
    mc = next(c for c in m['courses'] if c['course'] == cid)
    st = {l['id']: l['state'] for ch in mc['chapters'] for l in ch['lessons']}
    ok('学生课程：测验可做、PLC 课不锁（free）、产线课等先修课 q1', st == {'q1': 'open', 'p1': 'open', 'l1': 'locked'}, st)
    ok('学生课程卡片带封面和课的类型', mc['cover'] == '/brand/course-custom-quiz.png' and set(mc['kinds']) == {'quiz', 'cell', 'plant'}, mc.get('kinds'))
    aq = next(l['aid'] for ch in mc['chapters'] for l in ch['lessons'] if l['id'] == 'q1')
    al = next(l['aid'] for ch in mc['chapters'] for l in ch['lessons'] if l['id'] == 'l1')
    ok('测验课不能进沙箱', err('POST', f'/api/teach/assignments/{aq}/sandbox', {}, S)[0] == 400)
    t = call('GET', f'/api/teach/assignments/{aq}/task', tok=S)
    ok('学生看到的测验没有答案', all('answer' not in r and 'seal' not in r for r in t['scene']['rules']) and t['scene']['sandbox'] is False, t['scene']['rules'])
    call('PUT', f'/api/teach/assignments/{aq}/answers', {'answers': {'a': 1, 'b': 59}}, S)
    s1 = call('POST', f'/api/teach/assignments/{aq}/submit', {}, S)
    ok('测验提交：一题对一题错 = 50', s1['score'] == 50, s1.get('details'))
    s2 = call('POST', f'/api/teach/assignments/{aq}/submit', {'answers': {'b': 60.3}}, S)
    ok('测验再交：填数在允许误差内 = 100', s2['score'] == 100, s2.get('score'))
    st2 = {l['id']: l['state'] for ch in call('GET', '/api/teach/my/courses', tok=S)['courses'] if ch['course'] == cid for ch in ch['chapters'] for l in ch['lessons']}
    ok('先修课 q1 完成后产线课解锁', st2.get('l1') == 'open', st2)
    reveal_checks(T, S, stu, cid, s1)              # 会把这门课再发布到第二个班（学生也在里面）：放在按课程编号查学生地图的检查后面
    # 课程包
    pk = call('GET', '/api/teach/courses/pubkey', tok=S)
    data = call('GET', f'/api/teach/courses/{cid}/package', tok=S, raw=True)
    from vfactory.courses import coursepkg
    keys = {pk['key_id']: pk['public_key']}
    try:
        dd = coursepkg.verify(data, keys)
        good = True
    except coursepkg.CoursePackageError as e:
        good, dd = str(e), None
    ok('学生下载课程包：签名验过', good is True and dd['course']['id'] == cid, good)
    q1 = dd['course']['chapters'][0]['lessons'][0] if dd else {}
    ok('课程包里测验答案是封存的', all('answer' not in r and 'seal' in r for r in q1.get('rules') or []))
    z = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as w:
        for n in z.namelist():
            b = z.read(n)
            if n == 'course.json':
                b = b.replace('"weight": 50'.encode(), '"weight": 5'.encode(), 1)
            w.writestr(n, b)
    try:
        coursepkg.verify(buf.getvalue(), keys)
        rej = False
    except coursepkg.CoursePackageError as e:
        rej = str(e)
    ok('改过的课程包（改分值）被拒', bool(rej), rej)
    # AI 评分建议（假模型）
    subs = call('GET', f'/api/teach/assignments/{aq}/submissions?username={stu}', tok=T)
    sid = subs[0]['id']
    try:
        sg = call('POST', f'/api/teach/submissions/{sid}/ai_suggest', {}, T)
        sug = sg['suggestion']
        ok('AI 建议：每个评分项都有建议分和评语', len(sug['criteria']) == 2 and all(c['comment'] for c in sug['criteria']), sug)
        ok('AI 建议不改成绩（提交还是自动分、没有老师改分）', call('GET', f'/api/teach/assignments/{aq}/submissions?username={stu}', tok=T)[0]['override_score'] is None)
        j = call('POST', f'/api/teach/assignments/{aq}/ai_suggest_all', {'force': True}, T)
        for _ in range(60):
            jj = call('GET', f"/api/teach/ai_jobs/{j['job']}", tok=T)
            if not jj['running']:
                break
            time.sleep(0.5)
        ok('给全班生成建议：批量任务跑完', not jj['running'] and jj['done'] == jj['total'] >= 1, jj)
    except urllib.error.HTTPError as e:
        ok('AI 建议（需要 VF_LLM_FAKE=1 或配置大模型）', False, e.read()[:200])
    ok('学生不能调 AI 评分', code('POST', f'/api/teach/submissions/{sid}/ai_suggest', {}, S) == 403)
    del al
    authoring_checks(T, cls, stu, S)


# ---------------- 4.6.2 提交后显示正确答案和解析 ----------------
def reveal_checks(T, S, stu, cid, s1):
    d1 = {d['key']: d for d in s1.get('details') or []}
    ok('提交后（默认"提交后显示"）：每道题有你的答案、正确答案；有解析的带解析', (s1.get('reveal') or {}).get('state') == 'shown'
       and d1['a'].get('your') == 'B. 常闭' and d1['a'].get('correct') == 'B. 常闭' and '失效偏向安全' in d1['a'].get('explain', '')
       and d1['b'].get('your') == '59' and d1['b'].get('correct') == '60（允许误差 ±0.5）' and 'explain' not in d1['b'],
       {k: {x: d.get(x) for x in ('your', 'correct', 'explain')} for k, d in d1.items()})
    aq = next(l['aid'] for c in call('GET', '/api/teach/my/courses', tok=S)['courses'] if c['course'] == cid for ch in c['chapters'] for l in ch['lessons'] if l['id'] == 'q1')
    t = call('GET', f'/api/teach/assignments/{aq}/task', tok=S)
    ok('学生拿到的题目里没有解析（提交前看不到）', not any('explain' in r or 'explain_seal' in r for r in t['scene']['rules']))
    ok('任务详情里的历次提交也带正确答案', all(any(d.get('correct') for d in x['details']) for x in t['submissions']), len(t['submissions']))
    # 老师的作业：截止后显示（截止时间在以后）
    cls2 = call('POST', '/api/teach/classes', {'name': f'答案显示测试班 {STAMP}'}, T)
    call('POST', f"/api/teach/classes/{cls2['id']}/members", {'username': stu}, T)
    ok('发布课程时正确答案的显示方式写错 = 400', err('POST', f'/api/teach/courses/{cid}/publish', {'class_id': cls2['id'], 'reveal': 'sometimes'}, T)[0] == 400)
    r = call('POST', f'/api/teach/courses/{cid}/publish', {'class_id': cls2['id'], 'reveal': 'due', 'due': '2099-01-01 08:00'}, T)
    ok('发布课程：截止后显示 + 截止时间', r['created'] == 3, r)
    a2 = next(a for a in call('GET', f"/api/teach/assignments?class_id={cls2['id']}", tok=T) if a.get('lesson') == 'q1')
    ok('每一课的作业都是"截止后显示"', a2.get('reveal') == 'due' and a2.get('due') == '2099-01-01 08:00', {k: a2.get(k) for k in ('reveal', 'due')})
    call('PUT', f"/api/teach/assignments/{a2['id']}/answers", {'answers': {'a': 0, 'b': 60}}, S)
    h1 = call('POST', f"/api/teach/assignments/{a2['id']}/submit", {}, S)
    hd = {d['key']: d for d in h1.get('details') or []}
    ok('截止后显示：截止前提交只给你的答案，不给正确答案和解析', (h1.get('reveal') or {}).get('state') == 'due' and hd['a'].get('your') == 'A. 常开'
       and not any('correct' in d or 'explain' in d for d in hd.values()), {k: {x: d.get(x) for x in ('your', 'correct')} for k, d in hd.items()})
    th = call('GET', f"/api/teach/assignments/{a2['id']}/task", tok=S)
    ok('截止前再看任务详情也不给', not any('correct' in d for x in th['submissions'] for d in x['details']) and th['submissions'][0]['reveal']['due'] == '2099-01-01 08:00')
    tv = call('GET', f"/api/teach/assignments/{a2['id']}/submissions?username={stu}", tok=T)
    ok('老师看学生的提交：一直有正确答案', any(d.get('correct') for d in tv[0]['details']), [d.get('correct') for d in tv[0]['details']])
    call('PATCH', f"/api/teach/assignments/{a2['id']}", {'due': '2020-01-01 08:00'}, T)
    th2 = call('GET', f"/api/teach/assignments/{a2['id']}/task", tok=S)
    sd = {d['key']: d for d in th2['submissions'][0]['details']}
    ok('过了截止时间：同一次提交显示正确答案和解析', th2['submissions'][0]['reveal']['state'] == 'shown' and sd['a'].get('correct') == 'B. 常闭' and sd['a'].get('explain'),
       {k: d.get('correct') for k, d in sd.items()})
    call('PATCH', f"/api/teach/assignments/{a2['id']}", {'reveal': 'never'}, T)
    th3 = call('GET', f"/api/teach/assignments/{a2['id']}/task", tok=S)
    ok('不显示：只有你的答案', th3['submissions'][0]['reveal']['state'] == 'never' and not any('correct' in d for d in th3['submissions'][0]['details'])
       and th3['submissions'][0]['details'][0].get('your'))
    ok('作业的显示方式写错 = 400', err('PATCH', f"/api/teach/assignments/{a2['id']}", {'reveal': 'x'}, T)[0] == 400)
    call('PATCH', f"/api/teach/courses/{cid}/classes/{cls2['id']}", {'reveal': 'submit'}, T)
    ok('课程在班级里统一改回"提交后显示"', all(a.get('reveal') == 'submit' for a in call('GET', f"/api/teach/assignments?class_id={cls2['id']}", tok=T)))


# ---------------- 4.6.1 出题检查 ----------------
# 老师在服务器上做的测试课 tc-3be889（不动它）：一课产线任务、mc02_serial、任务书空、一条 {label:"1", weight:20, good ≥ 100}、8 小时、没有预算 / 限制 / 锁定。
def teacher_fixture(name):
    return {'name': name, 'desc': '', 'level': 1, 'tags': [], 'cover': '/brand/course-custom-line.png', 'chapters': [{'id': 'c1', 'title': '第一章', 'lessons': [
        {'id': 'l105', 'title': '产线任务 1', 'kind': 'plant', 'brief_md': '', 'hints': [], 'plant': 'mc02_serial', 'time_h': 8, 'seed': 7,
         'rules': [{'key': 'rspqg', 'weight': 20, 'label': '1', 'kind': 'kpi', 'metric': 'good', 'op': '>=', 'value': 100}]}]}]}


def codes(v, lid=None, levels=('error', 'warn', 'info')):
    return {i.get('code') for i in v['issues'] if i['level'] in levels and (lid is None or i.get('lesson') == lid)}


def offline_checks():
    from vfactory.courses import rules as R, verify
    from vfactory.teach import authoring as AU
    l = teacher_fixture('x')['chapters'][0]['lessons'][0]
    r = l['rules'][0]
    ok('说明：good ≥ 100（8 小时）= "8 小时合格品 ≥ 100 件"；标题"1"没意义 → 用说明', R.describe(r, l) == '8 小时合格品 ≥ 100 件' and R.title_of(r, l) == '8 小时合格品 ≥ 100 件',
       (R.describe(r, l), R.title_of(r, l)))
    ds = [R.describe(x, l) for x in ({'kind': 'kpi', 'metric': 'oee.M1', 'op': '>=', 'value': 0.75}, {'kind': 'budget', 'op': '<=', 'value': 220},
                                     {'kind': 'mes', 'query': 'work_order.count', 'op': '>=', 'value': 1}, {'kind': 'answer', 'choices': ['a', 'b'], 'answer': 1})]
    ok('说明：OEE / 投资 / MES / 作答（学生看的不带答案）', ds == ['M1 的 OEE ≥ 75%', '投资合计 ≤ 220 万元', 'MES：工单数 ≥ 1', '答案：单选题，选出正确的一项'], ds)
    ok('老师看的说明带答案', R.describe({'kind': 'answer', 'qtype': 'number', 'answer': 60, 'tol': 0.5, 'unit': '件'}, l, reveal=True) == '答案：60 ± 0.5 件')
    ok('名称有没有意义：空、"1"、"…"、两个字不算；"合格品产量"算', [R.meaningful_label(x) for x in ('', '1', '…', '产量', '12.5', '合格品产量')] == [False] * 5 + [True])
    ok('按比例凑成 100：差的分数补在最大的一项', R.normalize_weights([20]) == [100] and R.normalize_weights([10, 10, 13]) == [30, 30, 40] and sum(R.normalize_weights([1, 1, 1])) == 100,
       (R.normalize_weights([10, 10, 13]), R.normalize_weights([1, 1, 1])))
    cs = {i.get('code') for i in AU.validate_lesson(l)}
    ok('出题检查（不用跑）：任务书空 = 错误、分值合计 20、名称没意义、产线课没约束', {'brief', 'weights', 'label', 'unconstrained'} <= cs
       and [i['level'] for i in AU.validate_lesson(l) if i.get('code') == 'brief'] == ['error'], cs)
    res = verify.baseline(l)
    st = res.get('start') or {}
    ok('试运行起始模型（同一条评分路径，固定种子 8 小时）：什么都不改就满分', st.get('pct') == 100 and st['details'][0]['ok'] and st['details'][0]['value'] > 100, st)
    bi = AU.baseline_issues(l, res)
    b = next((i for i in bi if i.get('code') == 'baseline'), {})
    ok('试运行提醒："学生什么都不改就能得 100 分：合格品 8 小时约 N 件，目标 ≥ 100"', b.get('level') == 'warn' and '学生什么都不改就能得 100 分' in b.get('msg', '')
       and '合格品 8 小时约' in b['msg'] and '目标 ≥ 100' in b['msg'], b.get('msg'))
    ok('没有参考做法：备注"无法确认目标做得到"', any(i.get('code') == 'no_reference' and i['level'] == 'info' for i in bi))
    h1 = AU.baseline_hash(l)
    l2 = json.loads(json.dumps(l))
    l2['brief_md'] = '写了任务书'
    l2['rules'][0]['label'] = '合格品'
    l3 = json.loads(json.dumps(l))
    l3['rules'][0]['value'] = 450
    ok('试运行缓存键：改任务书、名称不变；改目标值就变', AU.baseline_hash(l2) == h1 and AU.baseline_hash(l3) != h1)


def authoring_checks(T, cls, stu, S):
    d = call('POST', '/api/teach/authoring', {'name': f'出题检查 {STAMP}'}, T)
    cid = d['id']
    v = call('PUT', f'/api/teach/authoring/{cid}', {'course': teacher_fixture(f'出题检查 {STAMP}')}, T)
    ok('保存后马上有不用跑的检查，试运行在后台跑', {'brief', 'weights', 'label', 'unconstrained'} <= codes(v) and (v['job'].get('running') or v['pending'] or v['baseline']),
       (sorted(codes(v)), v['job'], v['pending']))
    ok('目标说明（老师在编辑器里看到的"学生看到"）', v['goals']['l105']['rspqg']['title'] == '8 小时合格品 ≥ 100 件', v['goals'])
    t0 = time.time()
    v = call('POST', f'/api/teach/authoring/{cid}/checks', {'wait': True}, T)
    ok(f'试运行跑完（{time.time() - t0:.1f}s）：起始模型 100 分、合格品 > 100', not v['job'].get('running') and v['baseline']['l105']['start']['pct'] == 100, v['baseline'])
    want = {'brief', 'weights', 'label', 'unconstrained', 'baseline', 'no_reference'}
    ok('老师的测试课：所有检查都报出来了', want <= codes(v, 'l105'), sorted(codes(v, 'l105')))
    lv = {i.get('code'): i['level'] for i in v['issues'] if i.get('lesson') == 'l105'}
    ok('级别：任务书空是错误，分值 / 名称 / 没约束 / 什么都不改就满分是提醒', lv.get('brief') == 'error' and all(lv.get(k) == 'warn' for k in ('weights', 'label', 'unconstrained', 'baseline')), lv)
    bmsg = next(i['msg'] for i in v['issues'] if i.get('code') == 'baseline')
    ok('提醒里写清楚基线值和目标', '学生什么都不改就能得 100 分' in bmsg and '合格品 8 小时约' in bmsg and '目标 ≥ 100' in bmsg, bmsg)
    st, msg = err('POST', f'/api/teach/authoring/{cid}/publish', {}, T)
    ok('有错误不能发布（任务书空）', st == 400 and '任务书' in msg, (st, msg))
    v2 = call('POST', f'/api/teach/authoring/{cid}/checks', {}, T)
    ok('没改的课不重跑（按内容指纹缓存）', not v2['job'].get('running') and not v2['pending'] and v2['baseline']['l105']['start']['pct'] == 100, v2['job'])
    pv = call('POST', f'/api/teach/authoring/{cid}/preview', {}, T)
    ok('出题检查的错误不挡预览', pv['total'] == 1, pv.get('total'))
    pa = pv['chapters'][0]['lessons'][0]['aid']
    tk = call('GET', f'/api/teach/assignments/{pa}/task', tok=T)
    r0 = tk['scene']['rules'][0]
    ok('学生看到的目标：标题和说明都是"8 小时合格品 ≥ 100 件"（不是"1"）', r0['title'] == r0['label'] == '8 小时合格品 ≥ 100 件' and r0['goal'] == '8 小时合格品 ≥ 100 件', r0)
    # 修：按比例凑成 100、用生成的说明当名称、写任务书
    c = v['course']
    fixes = {i.get('code'): i.get('fix') for i in v['issues'] if i.get('lesson') == 'l105' and i.get('fix')}
    ok('提醒带修法：分值 → {rspqg: 100}，名称 → 生成的说明', fixes.get('weights', {}).get('weights') == {'rspqg': 100}
       and fixes.get('label', {}).get('value') == '8 小时合格品 ≥ 100 件', fixes)
    L = c['chapters'][0]['lessons'][0]
    for r in L['rules']:
        r['weight'] = fixes['weights']['weights'][r['key']]
        if r['key'] == fixes['label']['rule']:
            r['label'] = fixes['label']['value']
    L['brief_md'] = '### 任务\n8 小时内做出至少 100 件合格品。'
    v = call('PUT', f'/api/teach/authoring/{cid}', {'course': c}, T)
    v = call('POST', f'/api/teach/authoring/{cid}/checks', {'wait': True}, T)
    ok('修好以后：任务书、分值、名称的问题没了，没有错误', not ({'brief', 'weights', 'label'} & codes(v, 'l105')) and v['errors'] == 0, sorted(codes(v, 'l105')))
    ok('（目标太容易、没约束的提醒还在：只改了文字和分值）', {'baseline', 'unconstrained'} <= codes(v, 'l105'))
    # 再把目标定高、只让学生改两个缓存的容量：试运行重跑，"什么都不改就满分""没约束"消失；名称和目标对不上时提醒
    L = v['course']['chapters'][0]['lessons'][0]
    L['rules'][0]['value'] = 450
    L['lock'] = {'editable': [['B1', 'capacity'], ['B2', 'capacity']]}
    v = call('PUT', f'/api/teach/authoring/{cid}', {'course': v['course']}, T)
    ok('名称还是"≥ 100"、目标改成了 450：提醒对不上，修法是新的说明', any(i.get('code') == 'label' and (i.get('fix') or {}).get('value') == '8 小时合格品 ≥ 450 件' for i in v['issues']),
       [i['msg'] for i in v['issues'] if i.get('code') == 'label'])
    v['course']['chapters'][0]['lessons'][0]['rules'][0]['label'] = '8 小时合格品 ≥ 450 件'
    v = call('PUT', f'/api/teach/authoring/{cid}', {'course': v['course']}, T)
    v = call('POST', f'/api/teach/authoring/{cid}/checks', {'wait': True}, T)
    b = v['baseline']['l105']['start']
    ok('目标 450、只能改缓存：起始模型 0 分（合格品 < 450），提醒都没了，只剩"没有参考做法"', b['pct'] == 0 and codes(v, 'l105') == {'no_reference'}, (b, sorted(codes(v, 'l105'))))
    # 参考做法：从预览的沙箱里存（什么都没改 = 拿不到及格分 → 错误，不能发布）
    pv = call('POST', f'/api/teach/authoring/{cid}/preview', {}, T)
    pa = pv['chapters'][0]['lessons'][0]['aid']
    call('POST', f'/api/teach/assignments/{pa}/sandbox', {}, T)
    v = call('POST', f'/api/teach/authoring/{cid}/reference', {'aid': pa}, T)
    ok('存参考做法（从预览沙箱）：记下改了什么', v['refs'].get('l105') and v['refs']['l105']['summary'], v['refs'])
    v = call('POST', f'/api/teach/authoring/{cid}/checks', {'wait': True}, T)
    ref_iss = [i for i in v['issues'] if i.get('code') == 'reference']
    ok('参考做法拿不到及格分 = 错误："参考做法也拿不到及格分，目标可能做不到"', ref_iss and ref_iss[0]['level'] == 'error' and '参考做法也拿不到及格分' in ref_iss[0]['msg'],
       [i['msg'] for i in ref_iss])
    st, msg = err('POST', f'/api/teach/authoring/{cid}/publish', {}, T)
    ok('参考做法拿不到及格分时不能发布', st == 400 and '参考做法' in msg, (st, msg[:120]))
    # 好的参考做法：两个缓存放大到 20
    from vfactory.courses import start_model
    m = start_model(v['course']['chapters'][0]['lessons'][0])
    for blk in m['blocks']:
        if blk['id'] in ('B1', 'B2'):
            blk['params']['capacity'] = 20
    v = call('PUT', f'/api/teach/authoring/{cid}', {'course': v['course']}, T)
    v = call('POST', f'/api/teach/authoring/{cid}/reference', {'lesson': 'l105', 'model': m}, T)
    v = call('POST', f'/api/teach/authoring/{cid}/checks', {'wait': True}, T)
    ref = v['baseline']['l105'].get('ref') or {}
    ok('参考做法（缓存放大到 20）满分：错误没了', ref.get('pct') == 100 and v['baseline']['l105']['ref_source'] == 'teacher' and not codes(v, 'l105') and v['errors'] == 0,
       (ref.get('pct'), sorted(codes(v, 'l105'))))
    ok('参考做法摘要写出改了哪些参数', any('B1.capacity' in x for x in v['refs']['l105']['summary']), v['refs']['l105']['summary'])
    p = call('POST', f'/api/teach/authoring/{cid}/publish', {}, T)
    ok('改好以后可以发布', p['version'] == 1, p.get('version'))
    data = call('GET', f'/api/teach/courses/{cid}/package', tok=T, raw=True)
    cj = zipfile.ZipFile(io.BytesIO(data)).read('course.json').decode('utf-8')
    ok('参考做法不进课程包（包里缓存容量还是 1）', '"reference"' not in cj and '"capacity": 20' not in cj and '"capacity": 1' in cj)
    # 其他错误 / 提醒：测验没答案、填数没误差、点选答案不在工厂里、MES query 不认识、PLC 课试运行
    d2 = call('POST', '/api/teach/authoring', {'name': f'出题检查二 {STAMP}'}, T)
    c2 = {'name': f'出题检查二 {STAMP}', 'chapters': [{'id': 'c1', 'title': '一', 'lessons': [
        {'id': 'q1', 'title': '测验', 'kind': 'quiz', 'brief_md': '答题', 'rules': [
            {'key': 'm', 'kind': 'answer', 'qtype': 'multi', 'label': '哪些是输入', 'choices': ['按钮', '电机', '传感器'], 'answer': [], 'weight': 50},
            {'key': 'n', 'kind': 'answer', 'qtype': 'number', 'label': '节拍 60 秒，每小时几件', 'answer': 60, 'weight': 50}]},
        {'id': 'pt', 'title': '点瓶颈', 'kind': 'point', 'brief_md': '点出瓶颈', 'plant': 'mc03_bottleneck', 'lock': {'structure': True},
         'rules': [{'key': 'p', 'kind': 'answer', 'pick': True, 'label': '瓶颈是哪台', 'answer': ['NOPE9'], 'weight': 100}]},
        {'id': 'ms', 'title': 'MES', 'kind': 'mes', 'brief_md': '下达工单', 'rules': [{'key': 'w', 'kind': 'mes', 'label': '下达工单', 'query': 'work_orders.released', 'op': '>=', 'value': 1, 'weight': 100}]},
        {'id': 'pl', 'title': '启停', 'kind': 'cell', 'scene': 's01_motor_latch'}]}]}
    call('PUT', f"/api/teach/authoring/{d2['id']}", {'course': c2}, T)
    v = call('POST', f"/api/teach/authoring/{d2['id']}/checks", {'wait': True}, T)
    lv = {(i.get('lesson'), i.get('code')): i['level'] for i in v['issues']}
    ok('测验：多选没勾正确答案 = 错误；填数没设允许误差 = 提醒', lv.get(('q1', 'answer')) == 'error' and lv.get(('q1', 'tol')) == 'warn', lv)
    ok('点选题的答案不在工厂里 = 错误', any(i.get('lesson') == 'pt' and i['level'] == 'error' and 'NOPE9' in i['msg'] for i in v['issues']))
    ok('MES 检查的 query 不认识 = 错误', lv.get(('ms', 'mes_query')) == 'error', lv)
    pl = v['baseline'].get('pl') or {}
    ok('PLC 课也试运行：不写程序的分数 + 场景自带参考程序的分数', (pl.get('start') or {}).get('pct') is not None and pl.get('ref_source') == 'scene' and pl['ref']['pct'] >= 60,
       {k: pl.get(k) for k in ('ref_source',)} | {'start': (pl.get('start') or {}).get('pct'), 'ref': (pl.get('ref') or {}).get('pct')})
    ok('测验 / MES 课不试运行', 'q1' not in v['baseline'] and 'ms' not in v['baseline'] and not v['pending'], list(v['baseline']))
    ok('学生不能看出题检查', code('GET', f'/api/teach/authoring/{cid}/checks', None, S) == 403)
    del cls, stu


if __name__ == '__main__':
    offline()
    offline_checks()
    if '--offline' not in sys.argv:
        online()
    n = sum(1 for _, x in res if x)
    print(f'\n{n}/{len(res)} 通过')
    sys.exit(0 if n == len(res) else 1)
