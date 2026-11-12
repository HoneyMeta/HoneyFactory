"""无界面运行测试剧本（给 CI 用）：进程内启动一个工厂（不起网页），按剧本执行，输出 JUnit XML。

    python -m vfactory test tests/scripts/demo.json --config plants/foundry-housing.yaml --junit out.xml
    python -m vfactory test a.json b.json --no-protocols          # 不起 OPC UA/MQTT/Modbus：协议断言记为"跳过"（JUnit <skipped>），MES 断言改用进程内钩子

剧本文件可以是一个剧本，也可以是 {"scripts": [...]}；剧本里的 "config" 字段可以指定工厂文件（相对剧本所在目录或项目根目录）。
默认端口：OPC UA 14840、MQTT 11883、Modbus 15020（避开正在运行的服务），用 --opcua/--mqtt/--modbus 改。
退出码：全部通过 0，有失败 1，参数/文件错误 2。跳过的步骤不算失败。
预热快照：同一工厂文件 + 同样的预热参数 + 同一版代码，预热结果存在 data/warm-cache/，下次直接载入（CI 秒级启动）；--no-cache 关掉。
"""
from ..i18n import _tr
import argparse
import asyncio
import glob
import hashlib
import io
import json
import logging
import os
import pickle
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_scripts(paths):
    out = []
    for p in paths:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        for s in (d.get('scripts') if isinstance(d, dict) and 'scripts' in d else [d]):
            s.setdefault('name', os.path.splitext(os.path.basename(p))[0])
            s['_dir'] = os.path.dirname(os.path.abspath(p))
            out.append(s)
    return out


def _resolve(cfg, base):
    for b in (base, os.getcwd(), ROOT):
        c = cfg if os.path.isabs(cfg) else os.path.join(b, cfg)
        if os.path.exists(c):
            return c
    raise FileNotFoundError(cfg)


from .. import paths as _paths  # noqa: E402
CACHE_DIR = _paths.data('warm-cache')


def _code_version():
    """仿真内核代码的指纹（文件名 + 大小 + 修改时间），代码一变缓存就作废。"""
    h = hashlib.sha1()
    for f in sorted(glob.glob(os.path.join(ROOT, 'vfactory', '**', '*.py'), recursive=True)):
        if os.sep + 'testing' + os.sep in f:
            continue
        st = os.stat(f)
        h.update(f'{os.path.relpath(f, ROOT)}:{st.st_size}:{int(st.st_mtime)}'.encode())
    return h.hexdigest()[:12]


def _model_key(path):
    """和 PlantRuntime.start 里一样的模型摘要（决定能不能用预热缓存）。"""
    from ..server import read_yaml
    cfg = read_yaml(path)
    if 'blocks' not in cfg:
        from ..flow.model import to_v2
        cfg = to_v2(cfg)
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class _Hole:
    """存盘时替代"运行时编译出来的局部函数"（软 PLC 梯形图闭包、单元回调）的占位，载入后重新生成。"""

    def __init__(self, name=''):
        self.name = name

    def __call__(self, *a, **k):
        raise RuntimeError(_tr('预热快照里的 {name} 没有重建', name=self.name))


def _hole(name):
    return _Hole(name)


class _Pickler(pickle.Pickler):
    found = False

    def reducer_override(self, obj):
        if isinstance(obj, types.FunctionType) and ('<locals>' in obj.__qualname__ or obj.__name__ == '<lambda>'):
            return _hole, (obj.__qualname__,)
        if isinstance(obj, _Hole):
            self.found = True
        return NotImplemented


def _has_hole(v):
    p = _Pickler(io.BytesIO(), protocol=pickle.HIGHEST_PROTOCOL)
    try:
        p.dump(v)
    except Exception:          # noqa: BLE001
        return True
    return p.found


def _dump_plant(plant, fh):
    _Pickler(fh, protocol=pickle.HIGHEST_PROTOCOL).dump(plant)


def _load_plant(fh):
    """载入预热快照，并重建运行时编译的部分：控制单元的整厂回调、软 PLC（PLC 块或旧单元内置的，保留 PLC 的运行状态）。还有缺的就放弃快照。"""
    plant = pickle.load(fh)
    for st in plant.all_stations() if hasattr(plant, 'all_stations') else plant.stations.values():
        sim = getattr(st, 'sim', None)
        if sim is not None and hasattr(st, '_exit_put') and hasattr(st, 'take'):
            sim.entry_ready = (lambda s=st: s.available() > 0)
            sim.entry_take, sim.exit_put, sim.on_remove = st.take, st._exit_put, st._on_remove
        old = getattr(st, 'plc', None)
        if old is None or not _has_hole(old):
            continue
        # 4.3：PLC 是独立的 PLC 块（PlcStation._make 按块参数重建，再装回快照里正在运行的程序）；没迁移的旧单元还是 _make_plc
        rebuilt = False
        if getattr(st, 'kind', '') == 'plc' and hasattr(st, '_make'):
            try:
                prog = getattr(getattr(old, 'prog', None), 'program', None)
            except Exception:                              # noqa: BLE001  快照里程序对象是空洞：用块参数里的程序
                prog = None
            st._make()
            if isinstance(prog, dict) and st.plc is not None and hasattr(st.plc, 'load'):
                st.plc.load(prog, cold=True, io=st.io)
            rebuilt = True
        elif hasattr(st, '_make_plc'):
            st._make_plc()
            rebuilt = True
        if rebuilt:
            new = st.plc
            if new is not None:
                for k, v in vars(old).items():
                    if k in vars(new) and not _has_hole(v):
                        setattr(new, k, v)             # 运行状态（存储区、定时器、扫描计数）沿用快照
    return plant


def _cache_file(pid, key, ver):
    return os.path.join(CACHE_DIR, f'{pid}-{key[:16]}-{ver}.pkl')


class _Args:
    def __init__(self, a):
        self.http, self.opcua, self.mqtt, self.modbus = 0, a.opcua, a.mqtt, a.modbus
        self.no_mqtt = a.no_protocols


async def run_all(a, scripts):
    from ..protocols.mqtt import MqttHub
    from ..protocols.opcua import OpcUaHub
    from ..server import Manager, PlantRuntime, read_yaml, write_yaml
    from .runner import Runner, validate
    mgr = Manager(_Args(a))
    mgr.warm_sandbox = True                       # 无协议（沙箱）方式启动的工厂也用预热缓存
    ver = _code_version() if not a.no_cache else ''
    if not a.no_protocols:
        mgr.opcua = OpcUaHub(a.opcua)
        await mgr.opcua.start()
        mgr.mqtt = MqttHub(a.mqtt)
        await mgr.mqtt.start()
    tmp = tempfile.mkdtemp(prefix='vf-test-')
    results = []
    for i, sc in enumerate(scripts):
        errs = validate(sc)
        cfg_path = _resolve(sc.get('config') or a.config, sc.get('_dir', ROOT))
        pid = sc.get('plant') or os.path.splitext(os.path.basename(cfg_path))[0]
        if errs:
            results.append({'name': sc['name'], 'plant': pid, 'status': 'error', 'steps': [], 'notes': errs, 'duration_s': 0, 'failed': 0, 'started': ''})
            print(_tr('[剧本] {name}：格式错误 {errs}', name=sc["name"], errs=errs), flush=True)
            continue
        c = read_yaml(cfg_path)
        if a.warmup is not None:
            c['plant']['warmup_h'] = a.warmup
        c['plant']['modbus_port'] = a.modbus
        if sc.get('seed') is not None:
            c['plant']['seed'] = int(sc['seed'])
        path = os.path.join(tmp, f'{pid}-{i}.yaml')
        write_yaml(path, c)
        rt = PlantRuntime(mgr, pid, sandbox=a.no_protocols, path=path)
        t0 = time.time()
        cache_note = ''
        if not a.no_cache:
            key = _model_key(path)
            cf = _cache_file(pid, key, ver)
            if mgr.warm.get(pid, ('',))[0] != key and os.path.exists(cf):
                try:
                    with open(cf, 'rb') as fh:
                        mgr.warm[pid] = (key, _load_plant(fh))
                    cache_note = _tr('（预热快照）')
                except Exception as e:      # noqa: BLE001
                    print(_tr('  预热快照读不了，重新预热：{e}', e=e), flush=True)
        await rt.start()
        if not a.no_cache and not cache_note and mgr.warm.get(pid, ('',))[0] == key:
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                for old in glob.glob(os.path.join(CACHE_DIR, f'{pid}-*.pkl')):
                    if old != cf and time.time() - os.path.getmtime(old) > 7 * 86400:
                        os.remove(old)
                with open(cf + '.tmp', 'wb') as fh:
                    _dump_plant(mgr.warm[pid][1], fh)
                os.replace(cf + '.tmp', cf)
                cache_note = _tr('（已存预热快照，下次秒级启动）')
            except Exception as e:          # noqa: BLE001
                try:
                    os.remove(cf + '.tmp')
                except OSError:
                    pass
                cache_note = _tr('（预热快照没存上：{v}: {e}；同一次运行里的后续剧本仍复用内存里的预热结果）', v=type(e).__name__, e=e)
        mgr.rts[pid] = rt
        if a.speed:
            sc['speed'] = a.speed
        print(_tr('[剧本] {name}：工厂 {pid}（{name2}）已启动 {v:.1f}s{cache_note}，{len} 步', name=sc["name"], pid=pid, name2=rt.plant.name, v=time.time() - t0, cache_note=cache_note, len=len(sc["steps"]))
              + (_tr('，未启动协议：OPC UA / MQTT 断言记为跳过') if a.no_protocols else ''), flush=True)

        def show(res, _seen=set()):
            for s in res['steps']:
                if (s['ok'] is not None or s.get('skipped')) and (sc['name'], s['i']) not in _seen:
                    _seen.add((sc['name'], s['i']))
                    print(f"  {_tr('跳过') if s.get('skipped') else _tr('通过') if s['ok'] else _tr('失败')} {s['i']:02d} {s['desc']} — {s['msg']}", flush=True)
        res = await Runner(rt, sc, on_update=show).run()
        print(_tr('[结果] {name}：{status}（{passed} 通过 / {failed} 失败', name=sc['name'], status=res['status'], passed=res['passed'], failed=res['failed']) + (_tr(' / {get} 跳过', get=res.get('skipped')) if res.get('skipped') else '')
              + _tr('，{duration_s}s）', duration_s=res['duration_s']), flush=True)
        results.append(res)
        await rt.stop()
        del mgr.rts[pid]
    for stop in (lambda: mgr.opcua.server.stop(), lambda: mgr.mqtt.broker.shutdown()):
        try:
            if not a.no_protocols:
                await asyncio.wait_for(stop(), 5)
        except Exception:
            pass
    return results


def main(argv):
    ap = argparse.ArgumentParser(prog='vfactory test', description=_tr('无界面运行测试剧本，输出 JUnit XML'))
    ap.add_argument('scripts', nargs='+', help=_tr('剧本 JSON 文件'))
    ap.add_argument('--config', default='plants/foundry-housing.yaml', help=_tr('工厂文件（剧本里没写 config 时用）'))
    ap.add_argument('--junit', default='', help=_tr('JUnit XML 输出路径'))
    ap.add_argument('--json', default='', help=_tr('完整结果 JSON 输出路径'))
    ap.add_argument('--opcua', type=int, default=14840)
    ap.add_argument('--mqtt', type=int, default=11883)
    ap.add_argument('--modbus', type=int, default=15020)
    ap.add_argument('--no-protocols', action='store_true', help=_tr('不启动 OPC UA / MQTT / Modbus'))
    ap.add_argument('--speed', type=float, default=0, help=_tr('覆盖剧本里的仿真倍速'))
    ap.add_argument('--warmup', type=float, default=None, help=_tr('覆盖工厂的预热小时数（0 = 不预热，启动更快）'))
    ap.add_argument('--no-cache', action='store_true', help=_tr('不用、也不存预热快照（data/warm-cache）'))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    for noisy in ('asyncua', 'amqtt', 'pymodbus', 'transitions', 'vfactory'):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    try:
        scripts = _load_scripts(a.scripts)
    except (OSError, ValueError) as e:
        print(_tr('读不了剧本：{e}', e=e), file=sys.stderr)
        return 2
    try:
        results = asyncio.run(run_all(a, scripts))
    except FileNotFoundError as e:
        print(_tr('找不到工厂文件：{e}', e=e), file=sys.stderr)
        return 2
    from .runner import junit_xml
    if a.junit:
        os.makedirs(os.path.dirname(os.path.abspath(a.junit)), exist_ok=True)
        with open(a.junit, 'w', encoding='utf-8') as f:
            f.write(junit_xml(results))
        print(_tr('JUnit：{junit}', junit=a.junit))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    ok = all(r['status'] == 'passed' for r in results)
    print(_tr('全部通过') if ok else _tr('有失败'))
    return 0 if ok else 1
