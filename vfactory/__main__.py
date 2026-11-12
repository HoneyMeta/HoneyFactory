"""命令行入口。

    python -m vfactory serve                                    # 实时运行 plants/*.yaml 里的所有工厂：仿真 + OPC UA + Modbus + MQTT + Web
    python -m vfactory sim    --config plants/foundry-housing.yaml --hours 8   # 无界面快进一个工厂，输出 KPI（用来校验模型是否合理）
    python -m vfactory test   剧本.json --config plants/foundry-housing.yaml --junit out.xml   # 无界面跑测试剧本，输出 JUnit（见 vfactory/testing/cli.py）
    python -m vfactory desktop [--port 0] [--home DIR] [--server URL] [--protocols]   # 桌面模式（Windows 客户端，见 vfactory/desktop.py）
    python -m vfactory create-admin [--username U --password P --name N]   # production: first administrator (VF_DEMO=1 = demo accounts)

所有可写数据的位置见 vfactory/paths.py：默认在程序目录；VF_HOME 环境变量或 --home 挪到别处。
"""
from .i18n import _tr
import argparse
import json
import os
import sys
import time


def _early_home(argv):
    """--home 要在导入其他模块之前变成 VF_HOME（各模块导入时就定了数据路径）。"""
    for i, x in enumerate(argv):
        if x == '--home' and i + 1 < len(argv):
            os.environ['VF_HOME'] = os.path.abspath(os.path.expanduser(argv[i + 1]))
        elif x.startswith('--home='):
            os.environ['VF_HOME'] = os.path.abspath(os.path.expanduser(x.split('=', 1)[1]))


_early_home(sys.argv[1:])

import yaml  # noqa: E402

from .core import Plant  # noqa: E402


def load(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def summary(plant: Plant) -> dict:
    s = plant.snapshot()
    out = {'仿真时长h': s['kpi']['hours'], 'KPI': s['kpi'], 'OEE': {}}
    for st in plant.stations.values():
        if st.kind in ('cnc', 'molding', 'deburr', 'inspection', 'shotblast'):
            out['OEE'][st.id] = plant.oee(st)
    out['furnace_kwh_per_t'] = s['kpi']['kwh_per_t_melt']
    return out


def main(argv=None):
    if sys.stdout is not None:                     # pythonw.exe（客户端）没有控制台
        sys.stdout.reconfigure(encoding='utf-8')
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == 'test':                 # 无界面跑测试剧本（CI）：python -m vfactory test <剧本.json> --junit out.xml
        from .testing.cli import main as test_main
        sys.exit(test_main(argv[1:]))
    ap = argparse.ArgumentParser(prog='vfactory')
    ap.add_argument('cmd', choices=['serve', 'sim', 'desktop', 'create-admin'])
    ap.add_argument('--config', default='plants/foundry-housing.yaml')
    ap.add_argument('--hours', type=float, default=8)
    ap.add_argument('--http', type=int, default=8800)
    ap.add_argument('--opcua', type=int, default=4840)
    ap.add_argument('--modbus', type=int, default=5020)
    ap.add_argument('--mqtt', type=int, default=1883)
    ap.add_argument('--no-mqtt', action='store_true')
    # desktop（桌面模式）
    ap.add_argument('--port', type=int, default=0, help=_tr('desktop：本地端口，0 = 自动（优先用上次的）'))
    ap.add_argument('--home', default=None, help=_tr('可写数据目录（= 环境变量 VF_HOME）'))
    ap.add_argument('--server', default=None, help=_tr('desktop：服务器地址（登录页预填；安装包也可以用 server.json 预置）'))
    ap.add_argument('--protocols', action='store_true', help=_tr('desktop：启动时打开 OPC UA / Modbus / MQTT（默认关，设置里也能开）'))
    ap.add_argument('--watch-pid', type=int, default=0, help=_tr('desktop：启动器进程号，它退出后本地服务跟着退出'))
    ap.add_argument('--username', default=None, help=_tr('create-admin：管理员账号'))
    ap.add_argument('--password', default=None, help=_tr('create-admin：密码（至少 8 位；不给时在命令行里输入）'))
    ap.add_argument('--name', default='', help=_tr('create-admin：显示名'))
    a = ap.parse_args(argv)
    if a.cmd == 'create-admin':                   # first administrator of a production install (same rules as /api/setup/admin)
        import getpass
        from . import store
        user = a.username or input(_tr('管理员账号：')).strip()
        pw = a.password or getpass.getpass(_tr('密码：'))
        try:
            u = store.create_admin(user, pw, a.name)
        except ValueError as e:
            print(e)
            sys.exit(1)
        print(_tr('已创建管理员 {username}', username=u['username']))
        return
    if a.cmd == 'desktop':
        from .desktop import run
        run(a)
        return
    if a.cmd == 'sim':
        plant = Plant(load(a.config))
        t0 = time.time()
        plant.run_for(a.hours * 3600)
        res = summary(plant)
        res['墙钟秒'] = round(time.time() - t0, 1)
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return
    from .server import serve
    serve(None, a)


if __name__ == '__main__':
    main()
