"""方案报告导出（Word/PPT）与 SOP 接口检查（先启动 serve）：python tests/report_check2.py
环境变量 VF_URL（默认 http://127.0.0.1:8800）、VF_PLANT（默认 foundry-housing）。生成的文件留在 data/report_check2/ 便于人工打开看。"""
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

sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
PID = os.environ.get('VF_PLANT', 'foundry-housing')
P = f'{B}/api/p/{PID}'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'report_check2')
TOK = ''
res = []


def call(method, url, body=None, raw=False, tok=None, timeout=300):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + (tok or TOK)} if (tok or TOK) else {})})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        d = f.read()
        return (d, dict(f.headers)) if raw else json.loads(d)


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:200], flush=True)


def png_data_url():
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (800, 400), '#e8eef4')
    d = ImageDraw.Draw(im)
    for i in range(10):
        d.rectangle([30 + i * 75, 60, 90 + i * 75, 300], fill=('#d99a16', '#3b82c4', '#2e9d5b')[i % 3])
    b = io.BytesIO()
    im.save(b, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()


TOK = call('POST', B + '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
os.makedirs(OUT, exist_ok=True)

# 准备一个已完成的对比实验（没有就建一个小的）
opts = call('GET', P + '/report/export/options')
ok('导出选项', set(opts['sections']) >= {'layout', 'kpi', 'bottleneck', 'flow', 'energy', 'experiments', 'conclusions'} and 'templates' in opts, list(opts['sections']))
ck = call('GET', P + '/report/export/check?hours=24')
ok('导出前自检：同一份统计，各处数字一致', ck['check']['ok'] and ck['check']['total'] >= 8, [c['name'] for c in ck['check']['checks'] if not c['ok']])
ok('导出前预览：仿真时间、统计区间、瓶颈结论', ck['sim_time'] and ck['window'] and ck['bottleneck']['verdict'], (ck['window'], ck['bottleneck']['verdict'][:40]))
if not any(e['name'] == '报告测试：加一台 CNC' for e in opts['experiments']):
    r = call('POST', P + '/experiments', {'name': '报告测试：加一台 CNC', 'hours': 2, 'reps': 3,
                                          'variants': [{'name': '加一台 CNC', 'changes': [{'type': 'add', 'template': 'CNC1', 'count': 1}]}]})
    eid = r['id']
    for _ in range(200):
        e = call('GET', P + f'/experiments/{eid}')
        if e['status'] in ('done', 'failed'):
            break
        time.sleep(2)
    ok('建一个对比实验', e['status'] == 'done', e['status'])
    opts = call('GET', P + '/report/export/options')
exp = [e for e in opts['experiments'] if e['name'] == '报告测试：加一台 CNC'][:1] + [e for e in opts['experiments'] if e['kind'] == 'compare' and e['name'] != '报告测试：加一台 CNC'][:1]
ok('有已完成的实验', exp, [(e['id'], e['name']) for e in exp])

# Word：带前端截图
t0 = time.time()
data, hd = call('POST', P + '/report/export.docx', {'image': png_data_url(), 'experiments': [e['id'] for e in exp], 'hours': 24,
                                                     'title': '报告导出测试', 'author': '测试'}, raw=True)
open(os.path.join(OUT, 'report.docx'), 'wb').write(data)
ok('Word 导出', data[:2] == b'PK' and len(data) > 20000, f'{len(data)} 字节 {time.time() - t0:.1f}s 图={hd.get("x-report-image") or hd.get("X-Report-Image")}')
from docx import Document  # noqa: E402
doc = Document(io.BytesIO(data))
heads = [p.text for p in doc.paragraphs if p.style.name.startswith('Heading') or p.style.name == 'Title']
text = '\n'.join(p.text for p in doc.paragraphs) + '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
ok('Word 能解析、章节齐全', all(any(k in h for h in heads) for k in ('布局', '运行概况', '瓶颈', '物料流向', '能耗', '方案对比', '结论')), heads)
ok('Word 含截图和图表（布局 + 小时产出/在制品/瓶颈/时间构成/桑基/能耗/实验区间）', len(doc.inline_shapes) >= 9, len(doc.inline_shapes))
ok('Word 抬头写明仿真时间与导出时间（北京时间）', '仿真时间（模型里的时钟）' in text and '导出时间（北京时间）' in text, '')
ok('Word 瓶颈章节：活跃期法结论、把握、未参与判断的原因', '判断把握' in text and '未参与瓶颈判断' in text and '活跃' in text, '')
ok('Word 附统计口径与自检', '数据自检' in text and hd.get('x-report-check', hd.get('X-Report-Check', '')).split('/')[0] == hd.get('x-report-check', hd.get('X-Report-Check', '')).split('/')[-1], hd.get('X-Report-Check'))
import re as _re  # noqa: E402
nums = _re.findall(r'在制品平均 ([0-9.]+) 件', text)
wip_tbl = next((r.cells[1].text for t in doc.tables for r in t.rows if r.cells[0].text == '平均在制品'), '')
ok('Word 结论里的在制品 = 概况表里的在制品', nums and wip_tbl.startswith(nums[0]), (nums, wip_tbl))
ok('Word 含表格（概况/瓶颈/时间构成/能耗/实验）', len(doc.tables) >= 5, len(doc.tables))
ci_cells = [c.text for t in doc.tables for r in t.rows for c in r.cells if '（' in c.text and '–' in c.text]
ok('Word 方案对比表有 95% 置信区间（均值（下限–上限））', '95%' in text and len(ci_cells) >= 4, ci_cells[:4])
ok('Word 标题与署名', '报告导出测试' in text and '编制：测试' in text, '')

# PPT：不带截图（服务端画平面图），部分章节
data, hd = call('GET', P + '/report/export.pptx?sections=layout,kpi,bottleneck,energy,experiments,conclusions&hours=24', raw=True)
open(os.path.join(OUT, 'report.pptx'), 'wb').write(data)
ok('PPT 导出', data[:2] == b'PK' and len(data) > 20000, f'{len(data)} 字节 图={hd.get("x-report-image") or hd.get("X-Report-Image")}')
from pptx import Presentation  # noqa: E402
prs = Presentation(io.BytesIO(data))
slides = list(prs.slides)
kinds = [[sh.shape_type for sh in s.shapes] for s in slides]
alltext = '\n'.join(sh.text_frame.text for s in slides for sh in s.shapes if sh.has_text_frame)
ok('PPT 能解析、页数', len(slides) >= 7, len(slides))
ok('PPT 布局页有图片（服务端平面图）', any(13 in k for k in kinds), '')
ok('PPT 有原生图表', sum(1 for s in slides for sh in s.shapes if sh.has_chart) >= 2, sum(1 for s in slides for sh in s.shapes if sh.has_chart))
ok('PPT 有表格', any(sh.has_table for s in slides for sh in s.shapes), '')
ok('PPT 结论页', '结论与建议' in alltext and '瓶颈' in alltext, '')

# 只选部分章节
data, _ = call('POST', P + '/report/export.docx', {'sections': ['kpi', 'conclusions']}, raw=True)
d2 = Document(io.BytesIO(data))
h2 = [p.text for p in d2.paragraphs if p.style.name.startswith('Heading') and not p.text.startswith('附')]
ok('只导出选中的章节', len(h2) == 2 and '运行概况' in h2[0], h2)

# 公司模板（.dotx / .potx）
from docx import Document as _D  # noqa: E402
td = _D()
td.sections[0].header.paragraphs[0].text = '某公司 内部资料'
b_ = io.BytesIO()
td.save(b_)
raw = b_.getvalue()
zin = __import__('zipfile').ZipFile(io.BytesIO(raw))
zo_b = io.BytesIO()
with __import__('zipfile').ZipFile(zo_b, 'w') as zo:
    for it in zin.infolist():
        dat = zin.read(it.filename)
        if it.filename == '[Content_Types].xml':
            dat = dat.replace(b'wordprocessingml.document.main+xml', b'wordprocessingml.template.main+xml')
        zo.writestr(it, dat)
up = call('POST', B + '/api/report/templates', {'kind': 'docx', 'name': '公司模板.dotx', 'data_url': 'data:application/octet-stream;base64,' + base64.b64encode(zo_b.getvalue()).decode()})
ok('上传 Word 公司模板（.dotx）', up['ok'] and up['docx']['name'] == '公司模板.dotx', up)
from pptx import Presentation as _P  # noqa: E402
tp = _P()
b2 = io.BytesIO()
tp.save(b2)
up2 = call('POST', B + '/api/report/templates', {'kind': 'pptx', 'name': '公司模板.pptx', 'data_url': 'data:;base64,' + base64.b64encode(b2.getvalue()).decode()})
ok('上传 PPT 公司模板', up2['ok'], up2)
data, hd = call('POST', P + '/report/export.docx', {'sections': ['kpi', 'bottleneck'], 'hours': 24}, raw=True)
dt = Document(io.BytesIO(data))
ok('套用 Word 模板：页眉来自模板，正文是报告', (hd.get('x-report-template') or hd.get('X-Report-Template')) == 'company' and '某公司 内部资料' in dt.sections[0].header.paragraphs[0].text
   and any('运行概况' in p.text for p in dt.paragraphs), hd.get('X-Report-Template'))
data, hd = call('POST', P + '/report/export.pptx', {'sections': ['kpi', 'bottleneck'], 'hours': 24}, raw=True)
pt = Presentation(io.BytesIO(data))
ok('套用 PPT 模板（母版、版式来自模板，4:3）', (hd.get('x-report-template') or hd.get('X-Report-Template')) == 'company' and len(pt.slides) >= 3 and pt.slide_width == tp.slide_width, len(pt.slides))
open(os.path.join(OUT, 'report_tpl.pptx'), 'wb').write(data)
data, hd = call('POST', P + '/report/export.docx', {'sections': ['kpi'], 'template': False}, raw=True)
ok('可以不套模板', (hd.get('x-report-template') or hd.get('X-Report-Template')) == 'default', '')
try:
    call('POST', B + '/api/report/templates', {'kind': 'docx', 'name': 'a.txt', 'data_url': 'data:;base64,AAAA'})
    ok('模板文件类型校验', False)
except urllib.error.HTTPError as e:
    ok('模板文件类型校验', e.code == 400, e.read().decode()[:60])
for k in ('docx', 'pptx'):
    call('DELETE', B + f'/api/report/templates/{k}')
ok('删除模板', call('GET', B + '/api/report/templates') == {'docx': None, 'pptx': None})

# 坏截图
try:
    call('POST', P + '/report/export.docx', {'image': 'data:image/png;base64,AAAA'}, raw=True)
    ok('坏截图被拒绝', False)
except urllib.error.HTTPError as e:
    ok('坏截图被拒绝', e.code == 400, e.read().decode()[:80])

# SOP
meta = call('GET', P + '/meta')
sid = meta['stations'][0]['id']
try:
    call('PUT', P + '/sop', {'sops': [{'name': 'x', 'steps': [{'title': 'a', 'target': {'block': 'NOPE'}}]}]})
    ok('SOP 目标设备校验', False)
except urllib.error.HTTPError as e:
    ok('SOP 目标设备校验', e.code == 400)
r = call('PUT', P + '/sop', {'sops': [{'id': 'sop-t', 'name': '新员工熟悉产线', 'desc': '测试', 'steps': [
    {'title': '认识第一台设备', 'text': '**安全第一**', 'target': {'block': sid}, 'camera': {'mode': 'walk', 'pos': [1, 2, 3], 'look': [4, 5, 6]}, 'duration_s': 5},
    {'title': '第二步', 'text': '看看', 'target': {'block': meta['stations'][1]['id']}}]}]})
g = call('GET', P + '/sop')
ok('SOP 保存与读取', g['sops'][0]['steps'][0]['camera'] == {'mode': 'walk', 'pos': [1.0, 2.0, 3.0], 'look': [4.0, 5.0, 6.0]} and len(g['sops'][0]['steps']) == 2,
   g['sops'][0]['steps'][1])
gtok = call('POST', B + '/api/login', {'username': 'guest', 'password': 'honey123'})['token']
g2 = call('GET', P + '/sop', tok=gtok)
ok('访客能看 SOP', len(g2['sops']) == 1)
try:
    call('PUT', P + '/sop', {'sops': []}, tok=gtok)
    ok('访客不能改 SOP', False)
except urllib.error.HTTPError as e:
    ok('访客不能改 SOP', e.code == 403)

n = sum(1 for _, x in res if x)
print(f'\n{n}/{len(res)} 通过；文件在 {OUT}')
sys.exit(0 if n == len(res) else 1)
