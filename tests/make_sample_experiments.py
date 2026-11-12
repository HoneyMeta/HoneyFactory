"""重新生成示范工厂的示例实验（新装时自动写进实验列表，实验面板里"用示例填充"也用它们）：
    python tests/make_sample_experiments.py [compare|optimize|all]
输出 vfactory/samples/experiment_foundry-housing.json（方案对比）和 experiment_foundry-housing__opt.json（参数优化）。
用真实的实验代码在后台进程里跑（和界面上新建实验完全一样），对比实验 4 个方案 × 5 次 × 24 小时，优化 12 个候选 × 2 次 × 8 小时，大约 20–30 分钟。
"""
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding='utf-8')

from vfactory import experiment, store  # noqa: E402
from vfactory.server import read_yaml  # noqa: E402

PID = 'foundry-housing'
OUT = os.path.join(ROOT, 'vfactory', 'samples')
TWO_SHIFTS = [{'name': '早班', 'start': '07:00', 'end': '15:00'}, {'name': '中班', 'start': '15:00', 'end': '23:00'}]
COMPARE = {
    'name': '示例：检测站扩能、提速与两班制对比', 'hours': 24.0, 'reps': 5, 'seed': 42,
    'variants': [
        {'name': '基准（当前方案）', 'changes': []},
        {'name': '加一台内窥检测站', 'changes': [{'type': 'add', 'template': 'INS1', 'count': 1}]},
        {'name': '检测站每孔检测时间 5→4 秒', 'changes': [{'type': 'setpoint', 'station': 'INS1', 'tag': 'Setpoint/SecPerHole', 'value': 4}]},
        {'name': '改两班制（周一至周六）', 'changes': [{'type': 'plan', 'shifts': TWO_SHIFTS, 'workdays': [1, 2, 3, 4, 5, 6],
                                                    'label': '两班（早 7–15、中 15–23），周一至周六'}]},
    ]}
OPTIMIZE = {
    'name': '示例：检测与机加产能优化', 'hours': 8.0, 'reps': 2, 'budget': 12, 'pop': 6, 'method': 'ga', 'seed': 42, 'search_seed': 7,
    'params': [{'kind': 'add', 'template': 'INS1', 'lo': 0, 'hi': 1, 'step': 1, 'label': '加内窥检测站（台）'},
               {'kind': 'add', 'template': 'CNC1', 'lo': 0, 'hi': 2, 'step': 1, 'label': '加加工中心（台）'},
               {'kind': 'buffer', 'name': 'ins_in', 'lo': 10, 'hi': 40, 'step': 10, 'label': '待检测缓存（件）'}],
    'objectives': [{'key': 'good_per_h', 'sense': 'max'}, {'key': 'wip_avg', 'sense': 'min'}],
    'constraints': [{'key': 'scrap_rate', 'op': '<=', 'value': 0.05}]}


def capture():
    got = {}

    def x(sql, args=()):
        if "status='done'" in sql:
            got['result'], got['finished'] = args[0], args[1]
        elif "status='failed'" in sql:
            got['error'] = args[0]
        return 1
    store.x = x
    return got


def base_cfg():
    cfg = read_yaml(os.path.join(ROOT, 'plants', f'{PID}.yaml'))
    cfg.setdefault('plan', {})
    return cfg


def save(fn, e, variants, got):
    if 'result' not in got:
        raise SystemExit(f"失败：{got.get('error')}")
    d = {'name': e['name'], 'hours': e['hours'], 'reps': e['reps'], 'variants': json.dumps(variants, ensure_ascii=False), 'status': 'done', 'progress': 1.0,
         'result': got['result'], 'created': got['finished'], 'finished': got['finished']}
    with open(os.path.join(OUT, fn), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    print('已写入', fn, len(got['result']) // 1024, 'KB')


def main(what):
    if what in ('compare', 'all'):
        t = time.time()
        got = capture()
        asyncio.run(experiment.run_experiment(0, base_cfg(), COMPARE['hours'], COMPARE['reps'], COMPARE['variants'], COMPARE['seed'], None))
        print('对比实验', round(time.time() - t), 's')
        save(f'experiment_{PID}.json', COMPARE, COMPARE['variants'], got)
        print('\n'.join(json.loads(got['result'])['text']))
    if what in ('optimize', 'all'):
        t = time.time()
        got = capture()
        spec = {k: v for k, v in OPTIMIZE.items() if k != 'name'}
        asyncio.run(experiment.run_optimization(0, base_cfg(), spec))
        print('优化', round(time.time() - t), 's')
        save(f'experiment_{PID}__opt.json', OPTIMIZE, {'kind': 'optimize', **spec}, got)
        print('\n'.join(json.loads(got['result'])['text']))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'all')
