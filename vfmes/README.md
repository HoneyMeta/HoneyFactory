# 蜂元教学 MES（vfmes）

蜂元虚拟工厂自带的教学用制造执行系统。客户端（桌面模式）左侧「MES」给一座**本机**工厂按需启动它；5.0.1 起它只提供接口，页面在虚拟工厂自己的网页里（`web/src/mes/`）；
学员在里面下工单、看自动报工、找 OEE 最差的设备、一件一码追溯不合格品、读 SPC 控制图，MES 课从它评分取数。只在学员这台电脑上运行，学校服务器上不跑。

它是一套普通的 MES，没有智能化功能（问数、日报、助手、智能体等都不在这里）；智能 MOM（HoneyMOM）是另一个产品，虚拟工厂不依赖那个仓库。

功能：

| 模块 | 内容 |
|---|---|
| 生产 | 生产工单 → 排产（甘特）→ 派工 → 报工（设备自动 / 人工 / 手机扫码）、领料退料、在制品一件一码、安灯、物料申请 |
| 质量 | 检验模板、来料/过程/首件/出货检验、不合格品闭环（返修/报废/让步）、返修记录、SPC（X̄-R、判异、Cpk）、8D 报告（手工填写） |
| 设备 | 台账、实时监控、OEE（A×P×Q、停机时间线）、点检保养、维修工单、报警 |
| 仓储 / 能耗 | 库存、出入库、盘点、AGV 任务、发运；小时电耗、能耗分析 |
| 铸造 / 机加 | 炉次与球化记录、炉料倒冲；NC 程序审批下发、刀具寿命计数与换刀、机加不良统计、三坐标导入 |
| 看板 | 工作台、车间大屏、手机端 |

功能和数据结构参照开源 MES（ktg-mes）的模块划分；代码和界面均为自研。

## 目录

```
vfmes/__main__.py         命令行：python -m vfmes serve --http <端口> / seed
vfmes/app.py              应用：接口、未知 /api/* 一律 404（没有网页）
vfmes/edu.py              教学部分：本机学员、一次性登录票、客户端接口 /api/edu/*、评分取数（QUERIES）、空闲计时、自动导入、跟随客户端退出
vfmes/schema.py           实体定义：一份定义生成数据库表、通用增删改查接口和前端列表/表单
vfmes/crud.py             通用接口 /api/e/<实体>、实体动作、CSV 导出
vfmes/db.py               数据库（SQLAlchemy Core，SQLite <HM_DATA>/mes.db）、数据时钟
vfmes/auth.py             令牌、角色权限
vfmes/ingest.py           采集数据入库：点位 → 状态/能耗/报警/刀具；网关事件 → 一件一码/报工/检验/NCR/库存/炉次
vfmes/collector.py        MQTT / OPC UA / Modbus 连接器、从虚拟工厂导入（设备、产线、点表、刀具）
vfmes/seed.py             示范工厂的基础数据（工序、物料、BOM、工艺路线、班组、缺陷代码、检验模板、仓库、炉料）；没有演示工单
vfmes/services/           生产、质量、设备、仓储、铸造、机加、追溯与看板、安灯与物料申请
web/src/mes/              （虚拟工厂的网页里）MES 的页面、菜单（nav.ts）、外壳（MesShell.vue：状态行、按需启动、选工厂）
```

`vfmes` 包的上一级就是虚拟工厂目录（开发时是仓库根目录，安装包里是 `resources\vf`）。

## 客户端怎么启动它

`vfactory/mes/sidecar.py`（`POST /api/desktop/mes/start {pid}`）：

1. 只认本机工厂，同一时间只跑一个 MES；给这个工厂单独打开 OPC UA / Modbus / MQTT（端口被占就换）。
2. 用同一个 Python（安装包里的精简运行时）起子进程：`python -c <BOOT> <虚拟工厂目录> serve --http <空闲端口>`。
   BOOT 把虚拟工厂目录放在 `sys.path` 最前面，并去掉别处带 `vfmes` / `honeymes` 包的目录（开发机的 `._pth` 里可能有旧的 HoneyMES 仓库），保证用的是这一份。
3. 等 `/api/edu/status` 就绪后，写 `<客户端数据目录>\mes\current.json`（端口、钥匙；评分进程从这里找 MES）。
4. 页面（`/mes/...`）只和本地服务说话：`/api/mes/<路径>` 由 sidecar 转发到 MES 的 `/api/<路径>`（虚拟工厂的登录照常检查，下载用 `?token=`）。
   sidecar 用钥匙换一次性登录票、再换本机学员的会话令牌（`/api/edu/session` 只认本机），转发时带 `Authorization: Bearer`，401 就重新换；钥匙和令牌不给网页。

停止：点"停止"、工厂关掉、空闲太久（默认 30 分钟）、客户端本地服务退出（MES 盯着 `HM_WATCH_PID`，它没了就自己退出）。

## 环境变量（客户端设置）

| 变量 | 说明 |
|---|---|
| `HM_DATA` | 数据目录（`mes.db`、`secret.key`），客户端每个工厂一份：`<客户端数据目录>\mes\<工厂>\`。不设时用 `<虚拟工厂目录>/data/mes-dev` |
| `HM_EDU_KEY` | 客户端专用钥匙（请求头 `x-hm-key`）：换登录票、查状态、评分取数 |
| `HM_PLANT` / `HM_PLANT_NAME` | 虚拟工厂里的工厂编号 / 名称（数据源主题前缀 `vfactory/<工厂>/`、公司名称） |
| `HM_VF_HTTP` | 虚拟工厂接口地址，如 `http://127.0.0.1:52011/api/p/local-xxx`（自动导入设备、点表、刀具用） |
| `HM_VF_TOKEN` | 虚拟工厂会话令牌（读工厂接口用） |
| `HM_MQTT` | 这个工厂的 MQTT 地址，如 `mqtt://127.0.0.1:52012`；不给就不采集 |
| `HM_USER_NAME` | 学员显示名（默认"学员"） |
| `HM_WATCH_PID` | 客户端本地服务的进程号：它退出了 MES 跟着退出 |
| `MES_DB` | 可选：别的数据库地址（默认 SQLite） |

只有一种模式：单用户（本机学员 `learner`，管理员权限，没有密码；数据库里别的账号启动时一律停用），只监听 127.0.0.1，第一次启动（还没有设备）自动"从虚拟工厂导入"。

## 客户端接口 /api/edu/*

| 接口 | 谁调 | 说明 |
|---|---|---|
| `GET /api/edu/info` | 公开 | 品牌（蜂元教学 MES）、本机工厂；`edu: true` |
| `POST /api/edu/ticket` | 钥匙 | 一次性登录票（2 分钟有效） |
| `POST /api/edu/session {ticket}` | 本机网页 | 登录票 → 本机学员的会话令牌（只认本机地址，票只能用一次） |
| `GET /api/edu/status` | 钥匙 | 运行状态：空闲秒数、请求数、导入情况、采集状态、数据量、数据时钟、进程号；`source`（vfmes 包所在目录）、`honeymes_loaded` / `honeymes_paths`（测试用来确认没混进别的 MES） |
| `POST /api/edu/import` | 钥匙 | 重新从虚拟工厂导入（工厂改了设备之后） |
| `POST /api/edu/check {query, where?, field?, answer_key?, answers?}` | 钥匙或学员令牌 | 一条声明式检查 → `{value}` |
| `POST /api/edu/snapshot {rules, answers}` | 钥匙或学员令牌 | 一次取多条（`kind: mes` 的规则）→ `{values: {key: value}, at, plant}`；交作业时带上，服务器按快照复评 |

评分取数（`edu.QUERIES`，MES 课的规则里写 `query`，见 `vfactory/mes/teach_rules.py`、`vfactory/courses/mes_intro.json`）：

| query | 说明 |
|---|---|
| `work_order.count` / `work_order.done` | 工单条数 / 完工数合计；where：product、status（可多个）、qty_gte、qty_lte、done_gte、customer |
| `report.count` / `report.good` | 报工条数 / 合格数合计；where：source、work_order_product |
| `oee.worst` / `oee.value` / `oee.count` | OEE 最差的设备（field 或 answer_key + rank）/ 某台设备的 OEE（field：A/P/Q/OEE）/ 有 OEE 数据的台数；where：hours（默认 2）、etype、equipment |
| `ncr.count` / `ncr.traced` | 不合格品条数（where：status、disposition、source）/ 原因分析里写对了机床和炉次的条数 |
| `repair.for_worst_oee` | 给 OEE 最差的 rank 台之一开了维修工单 → 1，否则 0 |
| `part.count` / `trace.part` / `trace.ncr_match` | 零件数 / 一个零件的追溯字段（heat、machine、status…）/ 学员写的零件、机床、炉次和追溯一致 → 1 |
| `spc.stable` / `spc.value` | 过程是否受控（可 answer_key 核对学员的判断）/ Cpk、Ppk、mean、count、violations |

## 单独跑（开发、调试）

依赖：虚拟工厂的 `requirements.txt` + `tools/client/mes-requirements.txt`（sqlalchemy）。在虚拟工厂目录里：

```bat
set HM_DATA=%TEMP%\mes-dev & set HM_EDU_KEY=test
python -m vfmes serve --http 8980
```

不给 `HM_MQTT` / `HM_VF_HTTP` 时不采集、不导入，只有基础数据。接口要会话：
`curl -X POST -H "x-hm-key: test" http://127.0.0.1:8980/api/edu/ticket` 拿到票，`POST /api/edu/session {"ticket": "<票>"}` 换令牌。

页面开发：在客户端（`dev-start.cmd`）里点左侧「MES」；页面源码在 `web/src/mes/`。`tools\build_electron.ps1` 把 `vfmes`（不带 `__pycache__`、数据库、密钥）放进 `resources\vf`。

测试：`tests/mes_edu_check.py`（客户端起 MES、导入、工单、报工、OEE、追溯、评分取数、空闲停止、退出）、`tests/mes_edu_ui.js`（Electron 界面走查）。

© 蜂元科技（郑州）有限责任公司
