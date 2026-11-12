# HoneyFactory（蜂元虚拟工厂）

[English](README.md) | **简体中文**

[![CI](https://github.com/HoneyMeta/HoneyFactory/actions/workflows/ci.yml/badge.svg)](https://github.com/HoneyMeta/HoneyFactory/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

HoneyFactory 是开源的虚拟工厂。它用工艺模型仿真一座工厂（熔炼、造型、机加工、检测、输送线、机器人、AGV、人员），
每个点位都通过真实的 OPC UA、Modbus TCP、MQTT 服务对外发布，MES、SCADA、数据平台和 AI 算法可以像接真实工厂一样
拿它来开发和测试。浏览器里的工作台可以在三维、平面图、流程图和控制/网络架构图里编辑工厂；内置的软 PLC（梯形图和
结构化文本）和 HMI 编辑器运行控制层。课程、班级、每个学生一份的沙箱和自动评分，让它也是一套 PLC 编程和生产运营的
实训系统。后端是 Python（FastAPI、asyncua、pymodbus、amqtt），前端是 Vue 3 + three.js。仓库自带一座示范工厂
（虚构的球墨铸铁铸造 + 机加工厂），开箱即运行。

这些数据为什么适合做测试：

- **信号有因果**：每个点位由工艺公式算出，工序之间相互影响（浇注温度低了，下游冷隔就多；刀具磨损了，缸孔尺寸就变大）。
- **协议是真的**：标准客户端直接连，写入会改变仿真。
- **可控制**：运行中改参数、注入设备 / 元件 / 网络 / 通讯故障、增减设备。
- **有标准答案**：每个零件的完整谱系和真实缺陷都记录下来，可以拿来给 AI 算法或 MES 打分。

它和同一团队开源的 MOM/MES 系统 [HoneyMOM](https://github.com/HoneyMeta/HoneyMOM) 配套：HoneyMOM 用标准交付包接入
HoneyFactory 的工厂，并订阅它的 `_mes` MQTT 主题。

- [功能](#功能)
- [快速开始](#快速开始)
- [配置](#配置)
- [AI 配置](#ai-配置)
- [协议](#协议)
- [架构](#架构)
- [路线图](#路线图)
- [许可证](#许可证)
- [参与贡献](#参与贡献)

## 功能

### 仿真与模型

- 通用块（来料、加工、批处理、缓存、输送线、检测、返修、装配、拆分、出口、仓库、人员池、搬运车队），以及铸造厂和
  机加工厂的高精度工艺模型：中频炉能量平衡、球化孕育、砂处理控制、铸件缺陷模型、Kienzle 切削力、Taylor 刀具寿命、
  刀具磨损与缸孔尺寸、带检出概率的内窥检测。详见 [docs/modeling.md](docs/modeling.md)（英文）。
- 参数可以写分布和公式；自定义公式点位、数据表（工艺路线、BOM、投料计划）、子模型、班次与休息、产品与订单、
  换型矩阵、Weibull 故障；有技能的工人会走到需要人的设备旁作业。
- 加工中心、造型线、机器人的动作级信号（防护门、夹具、主轴、NC 程序段、气缸行程），按毫秒时刻发布；动作故障
  （比如气缸泄漏）会拖慢节拍。
- 多座工厂同时运行；模板有空白工厂、铸造厂、机加工厂、铸造 + 机加一体和完整示范。

### 工作台

- 一个模型、四个视图：三维、平面图（CAD 式：墙、区域、尺寸、AGV 路网、DXF 底图）、流程图、架构图（信息系统、
  通讯、控制、设备）。
- 像游戏引擎编辑器一样边运行边改：运行、暂停、单步、运行到某时刻或某状态，1×～3600× 倍速；按状态、数值、报警、
  指标设断点；回放最近 24 小时；草稿 → 检查 → 试运行 → 应用，可撤销重做、有版本。
- 对象面板列出设备的全部关联：物料上下游、控制它的 PLC、每一路信号的通道和实时值、网络和上报路径。
- 通用、教学、设计、联调四个工作区；界面有英文和简体中文。

### 控制层与软 PLC

- 32 种设备级部件（输送线、传感器、气缸、挡停、转台、升降台、取放机械手、堆垛机、操作面板），带 I/O 表和元件级
  故障；15 个实训场景，从电机启停自锁到整条线。
- PLC、HMI、交换机、网关、SCADA、MES 都是独立设备，用信号线和网络线连接。
- 软 PLC 的编译器和虚拟机都是自己写的，支持梯形图和结构化文本：在线监视、强制、断点、单步、运行中下载、
  PLCopen XML 导入导出、I/O 时序图、交叉引用。也可以让真实 PLC 通过 Modbus、OPC UA 或 S7 接管一个控制单元。

### 教学

- 内置课程：工厂与设备入门、传感器与执行器（PLC 先修）、生产运营入门、PLC 控制基础（15 课）、生产线仿真与优化
  （机加工）、铸造厂运营、MES 入门。
- 课的类型：PLC 实训、按产量 / 预算 / 限值规则评分的产线任务、排故、测验、在图上点设备、MES 操作；老师可以在
  课程编辑器里做自己的课。
- 班级、名单导入、发布作业、每个学生一份沙箱（空闲自动休眠）、带防作弊检查的自动评分、老师复核、注入故障练排故、
  班级实时进度、成绩册导出。
- AI 助教只给提示、不给答案（可选）；给老师的 AI 辅助评分建议。
- 教学 MES（`vfmes/`：工单、派工报工、OEE、质量、SPC、追溯、库存），MES 课时由桌面客户端在本机启动。
  详见 [docs/teaching.md](docs/teaching.md)（英文）。

### 联调与对接

- 信号中心：浏览所有点位及其 OPC UA、Modbus、MQTT 地址、实时值、趋势和写入；按协议 × 设备 × 点位注入通讯故障
  （断开、坏质量、延迟、抖动、丢包、冻结、卡死、漂移）；录制与回放；报文抓取。
- 网络模型：网络线、交换机、网关故障按"设备 → 网关"的路径作用于三种协议；链路断开时网关缓存 MES 报文。
- **标准交付包**（点表 `points.xlsx`、平面图 `layout.dxf`、三维模型 `*.glb`、说明），和 HoneyMOM 接入读取的格式
  一致；**原始现场模式**把点位改成集成商现场那样的名字（`S7.PLC2.DB10.DBD4`），配有标准答案，用来测 AI 辅助的点位映射。
- 测试剧本（步骤表，经 REST、OPC UA、MQTT 断言），在界面里运行，或无界面运行并输出 JUnit，接进 CI。
- API 令牌可设范围、限定工厂、有效期、IP 白名单；OpenAPI 文档在 `/docs` 和 `/redoc`。

### 分析与设计

- 设备时间构成、在制品、生产周期、分时段 OEE、活跃期法瓶颈分析、桑基图、甘特图、能耗（峰值需量、分时电价）。
- 带重复和 95% 置信区间的实验、全因子设计、多目标优化（遗传算法）、"从此刻推演"。
- 场景（按时间编排的故障和操作）、带真值标签的数据集、Excel / PDF / Word / PowerPoint 报告（可用公司模板）、三维 SOP 漫游。

### 平台

- 角色：管理员、工程师、只读访客、教师、学生、单位管理员；审计日志。
- 自部署（服务器上跑工厂）或 SaaS 模式（服务器只管账号、单位、席位、课程和成绩，工厂在桌面客户端里跑）；离线激活的
  签名授权文件、带 TOTP 的运维后台。见 [docs/deployment.md](docs/deployment.md)（英文）和
  [docs/部署-自部署与SaaS.md](docs/部署-自部署与SaaS.md)。
- Windows 桌面客户端（Electron）：本机跑工厂、可离线、向学校服务器交作业。见 [docs/desktop-client.md](docs/desktop-client.md)（英文）。

## 快速开始

### Docker（演示）

需要 Docker 和 Compose v2。

```bash
git clone https://github.com/HoneyMeta/HoneyFactory.git
cd HoneyFactory
docker compose up
```

第一次运行要构建镜像（几分钟）。然后打开 http://localhost:8800 ，用 `admin` / `honey123` 登录（`engineer` 和只读的
`guest` 密码相同）。演示班级的老师是 `demo_teacher`（`teach123`），学生 `demo_s01` … `demo_s06`（`123456`）。
示范工厂 `foundry-housing` 已经在运行：OPC UA 客户端连 `opc.tcp://localhost:4840/vfactory/`，MQTT 客户端连
`localhost:1883`（主题 `vfactory/#`），Modbus 客户端连 `localhost:5020`。

界面默认英文，右上角可切换中文。要让工厂本身（设备名、事件、点位说明）也用中文，启动前设 `VF_LANG=zh-CN`：

```bash
VF_LANG=zh-CN docker compose up
```

生产部署（没有演示账号，第一次打开时创建管理员）：

```bash
cp docker/env.example .env        # VF_LANG、TZ、端口、大模型地址……
docker compose -f docker-compose.yml -f docker/compose.production.yml up -d
```

生产部署、HTTPS、备份和 SaaS 模式见 [docs/deployment.md](docs/deployment.md)。

### 手动安装（开发）

需要 Python 3.12 和 Node.js 20 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate            # Windows：.venv\Scripts\activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..

VF_DEMO=1 python -m vfactory serve   # Windows：set VF_DEMO=1 && python -m vfactory serve
```

打开 http://localhost:8800 。不设 `VF_DEMO=1` 就是生产安装：没有任何账号，在浏览器里或用
`python -m vfactory create-admin --username admin` 创建管理员。Windows 上 `run.cmd` 做同样的事（`VF_PYTHON` 指定解释器）。

改前端时在 `web/` 里运行 `npm run dev`（Vite 开发服务器，`/api` 和 `/ws` 转发到 8800 端口）。

不启动服务、直接快进一座工厂并输出指标：

```bash
python -m vfactory sim --config plants/foundry-housing.yaml --hours 24
```

## 配置

启动时读取环境变量。最常用的：

| 变量 | 默认值 | 含义 |
|---|---|---|
| `VF_DEMO` | 关 | `1`：演示账号（密码 `honey123`）和演示班级。不设：生产安装，没有账号。 |
| `VF_LANG` | `en` | 服务器语言，`en` 或 `zh-CN`：请求没带语言时的默认值，也是运行中的工厂用的语言。 |
| `VF_HOME` | 程序目录 | 数据目录：`data/`（数据库、草稿、版本、录制、沙箱）、`plants/`、`config/`、`logs/`。 |
| `VF_MODE` | `selfhost` | `selfhost` 或 `saas`（见 [docs/deployment.md](docs/deployment.md)），也可以写在 `config/deploy.json`。 |
| `VF_LLM_BASE_URL`、`VF_LLM_API_KEY`、`VF_LLM_MODEL` | – | AI 功能用的 OpenAI 兼容大模型接口。 |
| `VF_SANDBOX_MAX_ACTIVE`、`VF_SANDBOX_IDLE_S` | `40`、`600` | 同时运行的学生沙箱上限；沙箱空闲多少秒后休眠。 |
| `VF_HTTPS` | 关 | `1`：反向代理没传 `X-Forwarded-Proto` 时，把请求当作 HTTPS。 |

`python -m vfactory serve` 的参数：`--http`（默认 8800）、`--opcua`（4840）、`--mqtt`（1883）、`--modbus`（5020，第一个
Modbus 端口）、`--no-mqtt`。完整列表（含安全、SaaS、桌面客户端相关的变量）见 [docs/configuration.md](docs/configuration.md)。

## AI 配置

AI 功能（每个页面右下角的建模助手、学生的 AI 助教、给老师的 AI 辅助评分）用 OpenAI chat-completions 接口格式
（`POST <base_url>/chat/completions`，带工具调用），托管服务和自建的 vLLM、Ollama、LM Studio 等 OpenAI 兼容服务都能用。

用环境变量配置：

```bash
VF_LLM_BASE_URL=https://api.example.com/v1
VF_LLM_API_KEY=...
VF_LLM_MODEL=your-model-name
```

或者把 `config/llm.example.json` 复制成数据目录下的 `config/llm.local.json`（不进仓库）再填写。环境变量优先于文件。

HoneyFactory 不带任何默认的大模型地址、模型名和密钥，仓库里也没有密钥。三项都配好之前 AI 一直关闭，AI 助教这时只给
内置提示。助手提出的模型修改先在副本上试算，你确认后才写入。配置了大模型以后，包含模型数据、工厂数据和学生作答的
提示词会发给那个接口。桌面客户端本机没有配置时，经服务器的 AI 代理（`/api/ai/proxy`）调用，密钥只留在服务器上。

## 协议

| 服务 | 默认地址 | 说明 |
|---|---|---|
| 网页和 REST API | `http://<主机>:8800` | `/api/...`，WebSocket `/ws/<工厂>`，OpenAPI 文档 `/docs`、`/redoc` |
| OPC UA | `opc.tcp://<主机>:4840/vfactory/` | NodeId `ns=2;s=<工厂>/<设备>/<点位>`，AnalogItemType（工程单位、量程），HistoryRead（24 小时），A&C 报警事件 |
| Modbus TCP | `<主机>:5020` 起 | 每个工厂一个端口，每台设备一个单元，保持寄存器 1000 起，默认 `float32` ABCD |
| MQTT | `<主机>:1883` | 内置 Broker；`vfactory/<工厂>/<区域>/<设备>/<点位>`，写入 `.../set`，回执 `.../set/ack` |
| 给 MES 的 MQTT | 同一个 Broker | `vfactory/<工厂>/_mes/part`（零件事件）、`vfactory/<工厂>/_mes/event`（生产日志） |
| 交付包 | `GET /api/p/<工厂>/delivery.zip` | `points.xlsx`、`layout.dxf`、`models/*.glb`、`README.md` |

载荷格式、网关、故障、协议设置和测试剧本见 [docs/protocols.md](docs/protocols.md)（英文）；点表格式见
[docs/interface/点表格式.md](docs/interface/点表格式.md)。

## 架构

```
  浏览器（Vue 3 + three.js）              Windows 桌面客户端（Electron）         MES / SCADA / AI 客户端
  工作台、信号中心、课程                  同一套界面、本机服务、可离线            （HoneyMOM、UaExpert、Node-RED……）
              │ HTTP /api、WebSocket /ws          │ /api 转发、交作业                  │ OPC UA / Modbus / MQTT
 ┌────────────┴───────────────────────────────────┴───────────────────────────────────┴──────────┐
 │ HoneyFactory：一个 Python 进程（FastAPI）                                                        │
 │   工厂：仿真内核 + 工艺模型 + 控制单元 + 软 PLC + 网络模型                                        │
 │   协议服务：OPC UA（asyncua）、Modbus TCP（pymodbus）、MQTT Broker（amqtt）                       │
 │   工作台接口 · 运行控制 · 分析 · 实验 · 报告 · 交付包                                              │
 │   教学（班级、沙箱、评分）· AI 助手和助教 · 账号、单位隔离、审计                                    │
 └────────────┬────────────────────────────────────────────────────────────────────────────────────┘
              │ SQLite（data/vf.db）、YAML 工厂文件（plants/*.yaml）、data/ 下的文件
```

- `vfactory/core.py`、`vfactory/models/`：仿真内核（时钟、点位、零件档案、缓存、故障）和工艺模型；`vfactory/flow/`：
  块目录、模型、编辑命令、校验、表达式。
- `vfactory/protocols/`、`vfactory/netmodel.py`、`vfactory/comm.py`：OPC UA、Modbus、MQTT 适配，网关和网络故障，通讯故障。
- `vfactory/control/`、`vfactory/plc/`：控制层、实训场景、软 PLC（编译器、运行时、PLCopen、外接 PLC 驱动）。
- `vfactory/server.py`、`editor_api.py`、`runctl.py`、`analysis.py`、`experiment.py`、`report_export.py`、`delivery.py`：
  多工厂管理和 HTTP 接口、工作台、运行控制、分析、实验、报告、交付包。
- `vfactory/teach/`、`vfactory/courses/`、`vfactory/tutor.py`：教学、课程、AI 助教；`vfactory/assistant.py`、`copilot.py`：
  AI 助手；`vfactory/tenancy/`：单位、席位、授权、SaaS、运维后台。
- `vfactory/locale/`、`vfactory/i18n.py`：后端翻译；内容的英文映射在 `*/i18n/*.en.json`。
- `vfmes/`：教学 MES；`desktop/`：Electron 外壳；`web/`：Vue 3 前端，构建到 `web/dist`，由后端提供。
- `plants/`、`templates/`：工厂文件和模板；`tests/`：离线和接口检查（`*_check.py`）、浏览器走查（`*_ui.js`）、测试剧本。

## 路线图

下面是可能的方向，不是承诺；欢迎在 issue 里讨论和贡献：

- 更多工艺模型和工厂模板（注塑、装配、流程工业）；
- 更多界面和内容语言；
- 在 CI 里跑浏览器走查（Playwright）；
- 发布的容器镜像和 Helm chart；
- SaaS 模式下作业的服务器复评；
- Linux 和 macOS 桌面客户端。

## 许可证

Copyright (C) 2026 蜂元科技（郑州）有限责任公司（HoneyMeta Technology (Zhengzhou) Co., Ltd.）

HoneyFactory 采用 **GNU Affero 通用公共许可证 v3.0 或更高版本**（[LICENSE](LICENSE)）。如果你修改后通过网络给用户使用，
AGPL 要求你向这些用户提供修改后的源代码。

需要不承担 AGPL 义务的使用方式（比如放进闭源的实训产品、做成托管服务），可以购买**商业许可证**，也可以包含带 SLA 的
技术支持。见 [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)，或联系 dev@honeymeta.com、https://www.honeymeta.com 。

第三方组件和致谢见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 参与贡献

欢迎提交问题报告、修复、翻译、工艺模型、工厂模板和课程。请先读 [CONTRIBUTING.md](CONTRIBUTING.md)。
贡献者需要签一次 [CLA](CLA.md)，第一次提交 pull request 时 CLA 机器人会提示。请遵守[行为准则](CODE_OF_CONDUCT.md)，
安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

主仓库：https://github.com/HoneyMeta/HoneyFactory 。Gitee 和 GitCode 上有只读镜像。
