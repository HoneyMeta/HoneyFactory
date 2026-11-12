"""接口文档：Swagger UI（/docs）和 ReDoc（/redoc），静态资源打包在 vfactory/static/apidocs（学校、工厂内网不能上外网也能打开）。

接口按模块分组（标签按路径自动归类，见 GROUPS），每组配中文说明；总说明里写了认证、令牌范围和三种协议的接入要点。
"""
from .i18n import _tr
import os
import re

from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'apidocs')

DESCRIPTION = """
蜂元虚拟工厂对外接口。除 `/api/login`、`/api/health` 外，所有 `/api` 接口都要令牌：请求头 `Authorization: Bearer <令牌>`。

**令牌**：登录得到的会话令牌（7 天），或在「API 令牌」页面创建的 `vf_` 开头的令牌。API 令牌可以设置
范围（read 只读 / write 读 + 写点位 / control 读写 + 仿真控制、故障注入、测试剧本 / admin 等同创建者）、限定工厂、有效期和 IP 白名单。

**常用流程**

1. `GET /api/plants` 列出工厂；`GET /api/p/{pid}/points/v2` 拿结构化点表（OPC UA NodeId、MQTT 主题、Modbus 地址）。
2. `POST /api/p/{pid}/station/{sid}/write` 写设定值 `{"tag": "Setpoint/TapTemp", "value": 1500}`。
3. `POST /api/p/{pid}/signals/comm` 注入通讯故障 `{"protocol": "mqtt", "mode": "drop", "station": "CNC1", "drop_pct": 30, "minutes": 5}`。
4. `POST /api/p/{pid}/tests/run` 运行测试剧本，`GET /api/p/{pid}/tests/runs/{rid}/junit.xml` 取 JUnit。

**协议接入要点**

- OPC UA：`opc.tcp://<主机>:4840/vfactory/`，命名空间 `http://honeymeta.cn/vfactory`，NodeId `ns=2;s=<工厂>/<设备>/<点位>`。
  数值点是 AnalogItemType（带 EngineeringUnits、EURange），有 SourceTimestamp、HistoryRead（24 小时）、报警按 AlarmConditionType 发事件。
  越界写入返回 BadOutOfRange。
- MQTT：主题 `vfactory/<工厂>/<区域>/<设备>/<点位>`，载荷 `{"value", "unit", "quality", "ts", "sim_ts", "wall_ts"}`；
  写入发到 `…/set`（`{"value": x, "id": "请求号"}` 或纯数值），回执在 `…/set/ack`，失败另发 `vfactory/<工厂>/_errors`。
- Modbus TCP：每个工厂一个端口，每台设备一个 Unit；完整地址见点表。异常码：02 地址越界/只读，03 值越界，04 从站故障，0B 从站不存在。

对外时间（仿真时钟或墙钟）在信号中心的「协议设置」里切换。
"""

TAGS = [
    {'name': '账号与令牌', 'description': '登录、当前用户、账号管理、API 令牌（范围、限定工厂、有效期、IP 白名单）、操作审计'},
    {'name': '工厂', 'description': '工厂列表、新建/删除、总览、元数据（含真实接入地址）、仿真控制（倍速、暂停、快进、重置）'},
    {'name': '设备与点位', 'description': '设备详情、写点位/设定值、注入设备故障、启停'},
    {'name': '信号与协议', 'description': '点表（v2 为英文结构化字段）、信号树、曲线、协议设置、通讯故障注入（协议 × 设备 × 点位）、录制回放、NodeSet2、MQTT 认证'},
    {'name': '联调测试', 'description': '测试剧本的增删改查、运行、JUnit；报文监视与导出'},
    {'name': '生产计划与场景', 'description': '班次、订单、计划停机；场景时间表（故障、写值、通讯故障按时间编排）'},
    {'name': '实验与报表', 'description': '方案对比实验、优化、运行报表、数据集导出、方案报告'},
    {'name': '模型编辑', 'description': '建模编辑器：草稿、校验、应用、版本、试运行'},
    {'name': '控制与 PLC', 'description': '控制单元、I/O、强制、软 PLC 程序、外接 PLC、HMI'},
    {'name': '教学', 'description': '班级、实训任务、学生沙箱、评分'},
    {'name': 'AI 助手', 'description': '智能助手、建模 Copilot'},
    {'name': '其他', 'description': '未归类的接口'},
]

GROUPS = [
    (r'^/api/(login|me|admin|tokens)', '账号与令牌'),
    (r'^/api/p/[^/]+/(signals|points|nodeset|protocol)|^/api/settings/mqtt', '信号与协议'),
    (r'^/api/p/[^/]+/(tests|debug)', '联调测试'),
    (r'^/api/p/[^/]+/(station|track|part|parts)', '设备与点位'),
    (r'^/api/p/[^/]+/(plan|scenarios)', '生产计划与场景'),
    (r'^/api/p/[^/]+/(experiments|report|dataset|analysis|design|sop)', '实验与报表'),
    (r'^/api/p/[^/]+/(model|editor|draft|versions|tryrun|validate|layout|catalog|blocks)', '模型编辑'),
    (r'^/api/p/[^/]+/(cells|plc|hmi|control|io)|^/api/(scenes|plc|control)', '控制与 PLC'),
    (r'^/api/(teach|classes|courses|sandbox)', '教学'),
    (r'^/api/(assistant|copilot|ai)|^/api/p/[^/]+/(assistant|copilot|ai)', 'AI 助手'),
    (r'^/api/(plants|overview|health)|^/api/p/[^/]+', '工厂'),
]


def tag_routes(app):
    for r in app.routes:
        path = getattr(r, 'path', '')
        if not path.startswith('/api'):
            if hasattr(r, 'include_in_schema'):
                r.include_in_schema = False       # 前端页面兜底路由等不进接口文档
            continue
        if getattr(r, 'include_in_schema', True) is False:
            continue
        if getattr(r, 'tags', None):
            continue
        for pat, name in GROUPS:
            if re.search(pat, path):
                r.tags = [name]
                break
        else:
            r.tags = [_tr('其他')]


def register(app):
    if os.path.isdir(STATIC):
        app.mount('/_apidocs', StaticFiles(directory=STATIC), name='apidocs')
    orig = app.openapi

    def openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema
        tag_routes(app)                           # 生成文档前给所有接口归组（含后注册的模块）
        sch = orig()
        sch.setdefault('components', {}).setdefault('securitySchemes', {})['令牌'] = {
            'type': 'http', 'scheme': 'bearer', 'description': _tr('会话令牌或 vf_ 开头的 API 令牌（右上角 Authorize 填入后即可在页面里试调用）')}
        sch['security'] = [{'令牌': []}]
        return sch
    app.openapi = openapi

    @app.get('/docs', include_in_schema=False)
    async def docs():
        return get_swagger_ui_html(openapi_url=app.openapi_url, title=_tr('蜂元虚拟工厂 API 文档'),
                                   swagger_js_url='/_apidocs/swagger-ui-bundle.js', swagger_css_url='/_apidocs/swagger-ui.css',
                                   swagger_favicon_url='/_apidocs/favicon-32x32.png',
                                   swagger_ui_parameters={'docExpansion': 'none', 'defaultModelsExpandDepth': -1, 'persistAuthorization': True,
                                                          'filter': True, 'tryItOutEnabled': False})

    @app.get('/redoc', include_in_schema=False)
    async def redoc():
        return get_redoc_html(openapi_url=app.openapi_url, title=_tr('蜂元虚拟工厂 API 文档（ReDoc）'), redoc_js_url='/_apidocs/redoc.standalone.js',
                              redoc_favicon_url='/_apidocs/favicon-32x32.png', with_google_fonts=False)

    @app.get('/docs/help', include_in_schema=False, response_class=HTMLResponse)
    async def docs_help():
        return HTMLResponse(_tr('<meta charset="utf-8"><p>接口文档：<a href="/docs">Swagger UI</a> · <a href="/redoc">ReDoc</a> · <a href="/openapi.json">openapi.json</a></p>'))
