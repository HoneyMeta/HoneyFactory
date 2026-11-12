"""无界面快进 plants/ 和 templates/ 下所有配置，打印关键 KPI，用来回归检查模型。

    python tests/sim_all.py [小时数]
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
import yaml  # noqa: E402

from vfactory.core import Plant  # noqa: E402

H = float(sys.argv[1]) if len(sys.argv) > 1 else 24
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for f in sorted(glob.glob(os.path.join(root, 'plants', '*.yaml')) + glob.glob(os.path.join(root, 'templates', '*.yaml'))):
    with open(f, encoding='utf-8') as fh:
        p = Plant(yaml.safe_load(fh))
    t0 = time.time()
    p.run_for(H * 3600)
    k = p.snapshot()['kpi']
    oee = {s.id: p.oee(s)['OEE'] for s in p.stations.values() if s.kind in ('cnc', 'inspection', 'molding')}
    crew = next((s for s in p.stations.values() if s.kind == 'crew'), None)
    busy = {}
    if crew:
        for w in crew.workers:
            busy[w['id']] = w['role']
    print(f"== {os.path.relpath(f, root)}  {p.name}  ({time.time() - t0:.0f}s)")
    print(f"   浇注 {k['castings']}  机加 {k['machined']}  合格 {k['good']}  报废 {k['scrap']} ({k['scrap_rate'] * 100:.1f}%)  发运 {k['shipped']}  "
          f"kWh/t {k['kwh_per_t_melt']}  缓存 {k['buffers']}")
    print(f"   OEE {oee}")
    if crew:
        print(f"   班组 {len(crew.workers)} 人，在岗 {crew.get('Crew/OnDuty')}")
    waits = [e for e in p.events if '操作工未到位' in e.get('msg', '')]
    print(f"   报警/事件数 {len(p.events)}")
