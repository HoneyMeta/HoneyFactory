"""5.0 单位（组织）、两种部署方式、席位与授权、平台运维后台（设计见 docs/部署-自部署与SaaS.md）。

部署方式（同一套代码）：
  selfhost  自部署（默认，和 4.x 完全一样）：学校/企业自己的服务器；一个单位（default）；席位来自签名的授权文件（license.py）。
            服务器照样能跑工厂，但默认的工作方式也是客户端本机跑。
  saas      蜂元云：服务器只管账号、单位、课程、班级、作业与提交、成绩、AI 代理、运维后台；不跑工厂、仿真、OPC UA / Modbus / MQTT。
            建模和仿真都在客户端（学生的电脑）上；浏览器里只有平台运维（/ops）、单位管理、老师的班级与成绩、账号页面。
设置：环境变量 VF_MODE=saas|selfhost，或 config/deploy.json {"mode": "saas"}（环境变量优先）。

模块：
  schema    新表、旧库迁移（所有已有数据归入"默认单位" default，可重复执行）
  orgs      单位、用户所属单位、用量统计、单位数据导出/删除
  seats     席位检查（自部署读授权文件，SaaS 读运维后台的设置，同一个入口）
  license   授权文件（Ed25519 签名，离线激活）；公钥在 license_keys.py
  security  登录限流与锁定、密码规则、会话（可吊销）、安全响应头、请求大小
  totp      RFC 6238 一次性口令 + 恢复码
  policy    每个请求的单位/部署方式检查（server.py 认证中间件调用）
  ops       平台运维后台接口 /api/ops/…（TOTP 必须、敏感操作再验、IP 白名单、哈希链审计）
  orgadmin  单位管理员接口 /api/org/…
  progress  客户端上报进度 /api/progress/report，老师看班级进度
  aiproxy   AI 代理 /api/ai/proxy/…（密钥只在服务器上），按单位计量和限额
  hooks     服务器复评/防作弊的挂钩（现在不做，留接口）
"""
import json
import os

from .. import paths

MODES = ('selfhost', 'saas')
_cfg_cache: dict = {}


def deploy_cfg():
    """config/deploy.json（可选）：{"mode": "saas", "license_required": false, "ops_ips": "…", "session_hours": 168}。"""
    p = os.path.join(paths.CONFIG, 'deploy.json')
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    c = _cfg_cache.get(p)
    if c and c[0] == mt:
        return c[1]
    try:
        with open(p, encoding='utf-8-sig') as f:
            d = json.load(f) or {}
    except (OSError, ValueError):
        d = {}
    _cfg_cache[p] = (mt, d if isinstance(d, dict) else {})
    return _cfg_cache[p][1]


def mode():
    m = (os.environ.get('VF_MODE') or str(deploy_cfg().get('mode') or '') or 'selfhost').strip().lower()
    return m if m in MODES else 'selfhost'


def saas():
    return mode() == 'saas'


def setting(name, default=None):
    """部署设置：环境变量 VF_<NAME> 优先，其次 config/deploy.json 的 name。"""
    v = os.environ.get('VF_' + name.upper())
    if v not in (None, ''):
        return v
    v = deploy_cfg().get(name)
    return default if v in (None, '') else v


def flag(name, default=False):
    v = setting(name, None)
    if v is None:
        return default
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


def register(app, mgr):
    """server.build_app 调用：运维后台、单位管理、进度上报、AI 代理的接口，以及安全中间件。"""
    from . import aiproxy, ops, orgadmin, progress, security
    security.install(app)
    ops.register(app, mgr)
    orgadmin.register(app, mgr)
    progress.register(app, mgr)
    aiproxy.register(app, mgr)
