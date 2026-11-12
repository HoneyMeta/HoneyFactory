"""命令行（蜂元教学 MES，一般由蜂元虚拟工厂客户端启动，见 vfactory/mes/sidecar.py 和 vfmes/README.md）：
    python -m vfmes serve [--http 8900]     启动（首次自动建库、写入基础数据）；只监听 127.0.0.1
    python -m vfmes seed                    补全基础数据（可重复执行）
"""
from .i18n import _tr
import argparse
import logging
import sys

from . import db


def main(argv=None):
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(prog='vfmes')
    ap.add_argument('cmd', choices=['serve', 'seed'])
    ap.add_argument('--http', type=int, default=8900)
    ap.add_argument('--host', default='127.0.0.1', help=_tr('监听地址，默认 127.0.0.1（只给本机用）'))
    ap.add_argument('--db', default=None, help=_tr('数据库地址，默认 sqlite:///<HM_DATA>/mes.db'))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    for noisy in ('amqtt', 'asyncua', 'pymodbus', 'transitions'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    db.init(a.db)
    from . import seed
    seed.run()
    if a.cmd == 'seed':
        print(_tr('基础数据已就绪：'), db.DATA)
        return
    import uvicorn
    from . import edu
    from .app import build_app
    print(_tr('{BRAND}：http://127.0.0.1:{http}（本机学员，由蜂元虚拟工厂客户端打开）', BRAND=edu.BRAND, http=a.http), flush=True)
    uvicorn.run(build_app(), host=a.host, port=a.http, log_level='warning')


if __name__ == '__main__':
    main()
