"""所有可写路径的唯一出处。

程序目录（APP）：代码、templates/、vfactory/courses、vfactory/control/scenes、vfactory/static、web/dist —— 只读。
数据目录（HOME）：data/（数据库、草稿、版本、录制、PLC 程序、沙箱、预热缓存、报告模板…）、plants/、config/、logs/ —— 可写。

默认 HOME = APP（服务器部署和测试的行为和以前完全一样）；设了环境变量 VF_HOME（或 `python -m vfactory desktop --home DIR`，
入口会在导入其他模块之前把它写进 VF_HOME）就整体挪到那个目录。各模块在导入时取路径，所以 VF_HOME 必须在导入 vfactory 的其他模块之前设好。
"""
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.abspath(os.path.expanduser(os.environ['VF_HOME'])) if os.environ.get('VF_HOME') else APP
RELOCATED = os.path.normcase(HOME) != os.path.normcase(APP)

DATA = os.path.join(HOME, 'data')
PLANTS = os.path.join(HOME, 'plants')
CONFIG = os.path.join(HOME, 'config')
LOGS = os.path.join(HOME, 'logs')


def data(*p):
    """data/ 下的路径（不建目录）。"""
    return os.path.join(DATA, *p)


def home(*p):
    return os.path.join(HOME, *p)


def app(*p):
    """程序目录下的只读资源。"""
    return os.path.join(APP, *p)
