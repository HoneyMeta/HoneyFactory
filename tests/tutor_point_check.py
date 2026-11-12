# 4.6 AI 助教"看这里"（不用服务、不用大模型）：python tests/tutor_point_check.py
# 用假的大模型回答测：可以指的地方清单（检查表、日志、操作台按钮、梯形图元件、设备、页签、面板）、
# 回答里「【看这里：标签｜编号】」变成按钮数据、乱写的编号丢掉、点选题的答案设备不能指、提示词里写了规则、没有大模型时也给"看这里"。
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from vfactory import copilot, tutor  # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300])


PROG = {'lang': 'LD', 'vars': [], 'source': {'rungs': [
    {'elements': [{'par': [[{'t': 'NO', 'var': 'START'}], [{'t': 'NO', 'var': 'M1_RUN'}]]}, {'t': 'NC', 'var': 'STOP'}, {'t': 'COIL', 'var': 'M1_RUN'}]}]}}
COMPS = [{'id': 'START', 'type': 'button', 'label': '启动'}, {'id': 'STOP', 'type': 'button', 'label': '停止'}, {'id': 'LAMP_RUN', 'type': 'lamp', 'label': '运行灯'},
         {'id': 'M1', 'type': 'motor', 'label': '电机'}]
cat = tutor.point_catalog('cell', [{'id': 'CELL1', 'name': '实训单元'}, {'id': 'PLC1', 'name': 'PLC'}], COMPS, PROG, 'PLC1')
ok('PLC 课可以指：检查表、运行日志、页签、提交按钮', all(k in cat for k in ('checklist', 'runlog', 'tab:task', 'tab:goals', 'tab:io', 'submit')), sorted(cat)[:12])
ok('可以指操作台按钮和指示灯（data-tour=btn-/lamp-，带我去 = 打开操作台）',
   cat.get('btn:START', {}).get('target') == {'tour': 'btn-START'} and cat['btn:START']['goto'] == {'console': True} and 'lamp:LAMP_RUN' in cat and 'btn:M1' not in cat)
ok('可以指梯形图元件（变量 + 类型，带我去 = 打开编程窗口的程序页）',
   cat.get('ld:STOP/NC', {}).get('target', [None])[0] == {'ld': {'var': 'STOP', 't': 'NC'}} and cat['ld:STOP/NC']['goto'] == {'panel': 'plc-editor-float', 'plc_tab': 'prog'}
   and cat['ld:STOP/NC'].get('plc') == 'PLC1' and 'ld:START' in cat and 'ld:M1_RUN/COIL' in cat)
ok('可以指设备（三维 / 平面 / 流程里的那一台）和左边的面板图标',
   cat.get('block:CELL1', {}).get('target') == {'block': 'CELL1'} and cat['block:CELL1@plan']['goto'] == {'select': 'CELL1', 'view': 'plan'}
   and cat.get('panel:plc-editor', {}).get('target') == {'panel_btn': 'plc-editor'})
txt = tutor.catalog_text(cat)
ok('清单文字给大模型：有编号和说明，视图变体不重复列', 'checklist  检查表' in txt and 'ld:STOP/NC' in txt and '@plan  ' not in txt, txt[:200])

# ---- 假的大模型回答 ----
FAKE = ('按了启动没反应，先别急着改程序。【看这里：检查表｜checklist】里看看哪一项是红的，'
        '再看【看这里：STOP 触点|ld:stop/nc】：没按停止的时候 STOP 是 1 还是 0？【看这里：乱指|nothing:1】'
        '【看这里：日志｜runlog】【看这里：操作台|btn:START】\n```\nM1_RUN := START AND NOT STOP;\n```')
calls = []


def fake_chat(messages, tools=None):
    calls.append(messages)
    return {'role': 'assistant', 'content': FAKE}


copilot.chat = fake_chat
msgs = tutor.build_messages({'id': 's01', 'name': '电机启停自锁', 'task_md': '按启动电机转', 'io': [], 'scoring': []}, PROG, '', None, '为什么没反应', [], False, cat)
ok('提示词：只给提示 + "看这里"规则（不能用它暗示答案）', '看这里' in msgs[0]['content'] and '不能用它暗示答案' in msgs[0]['content'] and '只给提示' in msgs[0]['content'])
ok('上下文里带上可以指的地方清单', '可以指的地方' in msgs[1]['content'] and 'btn:START' in msgs[1]['content'])
ok('产线课提示词也有"看这里"规则', '看这里' in tutor.SYSTEM_PLANT and '{POINT_RULE}' not in tutor.SYSTEM_PLANT and '{POINT_RULE}' not in tutor.SYSTEM)
m = asyncio.run(tutor._ask_llm(msgs))
text, filtered, pts = tutor.finish(m['content'], cat)
ok('假大模型被调用', len(calls) == 1)
keys = [p['key'] for p in pts]
ok('回答里的"看这里"变成点：最多 3 个、编号大小写不敏感、清单外的丢掉', keys == ['checklist', 'ld:STOP/NC', 'runlog'], keys)
ok('点带着标签、聚光目标和带我去', pts[0]['label'] == '检查表' and pts[0]['target'][0] == {'sel': '.task-panel [data-tour="checklist"]'} and pts[0]['goto'] == {'teach_tab': 'goals'}
   and pts[1]['plc'] == 'PLC1', pts[:2])
ok('正文里标记换成标签文字，不留编号', '「检查表」' in text and 'checklist' not in text and '【' not in text and 'ld:' not in text, text)
ok('代码照样被过滤（助教只给提示）', filtered and ':=' not in text, text[-80:])

# ---- 产线课：点选题的答案设备不能指 ----
rules = [{'key': 'q_bn', 'kind': 'answer', 'pick': True, 'answer': ['M2'], 'label': '哪台是瓶颈'}, {'key': 'thr', 'kind': 'metric'}]
pcat = tutor.point_catalog('plant', [{'id': 'M1', 'name': '粗车'}, {'id': 'M2', 'name': '精车'}, {'id': 'B1', 'name': '缓存'}], forbid=tutor._forbidden_blocks(rules))
ok('产线课：可以指设备、设备属性、分析面板；点选题答案 M2 不在清单里', 'block:M1' in pcat and 'props:B1' in pcat and 'panel:analysis' in pcat and not any('M2' in k for k in pcat)
   and 'checklist' not in pcat, sorted(pcat)[:10])
_, _, pp = tutor.finish('看【看这里：精车|block:M2】和【看这里：粗车|block:M1@3d】', pcat)
ok('大模型硬要指答案设备也会被丢掉', [p['key'] for p in pp] == ['block:M1@3d'] and pp[0]['goto'] == {'select': 'M1', 'view': '3d'}, pp)

# ---- 没有大模型：也给"看这里" ----
copilot.llm_cfg = lambda: {}
b = tutor._busy(['先看任务书'], cat)
ok('没接大模型：回答里说清楚，并给"看这里"（任务书、检查表）', b['fallback'] and [p['key'] for p in b['points']] == ['tab:task', 'checklist'] and b['points'][0]['label'] == '任务书', b)

bad = [n for n, c in res if not c]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过' + ('；失败：' + '、'.join(bad) if bad else ''))
sys.exit(1 if bad else 0)
