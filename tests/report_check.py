"""快进一段时间后检查报表、数据集、计划功能。python tests/report_check.py [小时]"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
import yaml  # noqa: E402

from vfactory.core import Plant  # noqa: E402
from vfactory.history import dataset_zip, summary, to_excel  # noqa: E402

H = float(sys.argv[1]) if len(sys.argv) > 1 else 24
cfg = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), '..', 'plants', 'foundry-housing.yaml'), encoding='utf-8'))
cfg['plant']['start'] = '2026-11-02T07:00:00'
cfg['plan'] = {'shifts': [{'name': '早班', 'start': '07:00', 'end': '15:00'}, {'name': '中班', 'start': '15:00', 'end': '23:00'}],
               'breaks': [{'name': '午餐', 'start': '11:30', 'end': '12:00'}],
               'downtime': [{'station': 'CNC3', 'start': '2026-11-02 09:00', 'hours': 2, 'reason': '计划保养'}],
               'products': [{'code': 'SGH-450', 'name': 'SGH-450', 'cycle_factor': 1.0, 'changeover_min': 30},
                            {'code': 'SGH-520', 'name': 'SGH-520', 'cycle_factor': 1.15, 'changeover_min': 40}],
               'orders': [{'code': 'SO-1', 'product': 'SGH-450', 'qty': 150}, {'code': 'SO-2', 'product': 'SGH-520', 'qty': 300}]}
p = Plant(cfg)
t0 = time.time()
p.run_for(H * 3600)
print(f'{H} h in {time.time() - t0:.0f}s')
r = summary(p)
print({k: r[k] for k in ('from', 'to', 'castings', 'good', 'scrap', 'scrap_rate', 'good_per_h', 'energy_total', 'kwh_per_t', 'wip_avg')})
print('bottleneck', r['bottleneck'][:3])
print('lead', {k: v for k, v in r['lead'].items() if k != 'hist'})
print('\n'.join(r['findings']))
print('plan', json.dumps({k: v for k, v in p.plan.view().items() if k != 'cfg'}, ensure_ascii=False)[:600])
print('labels', len(p.labels), sorted({l['type'] for l in p.labels}))
print('planned util CNC3', [u for u in r['util'] if u['id'] == 'CNC3'])
print('excel bytes', len(to_excel(r, p.name)), 'zip bytes', len(dataset_zip(p, 0, p.t)))
print('ring', p.tagring.count, len(p.tagring.keys))
