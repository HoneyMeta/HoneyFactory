# 蜂元虚拟工厂 5.0 部署：自部署与 SaaS

同一套代码，两种部署方式：

| | 自部署（selfhost，默认） | SaaS（蜂元云） |
|---|---|---|
| 谁运维 | 学校 / 企业自己的服务器 | 蜂元 |
| 单位 | 一个（"默认单位"） | 多个，每个单位的数据互相隔离 |
| 席位从哪来 | 蜂元签发的授权文件（Ed25519 签名，离线激活） | 运维后台 `/ops` 里的设置 |
| 服务器跑工厂吗 | 能（4.x 的功能都在），但默认也是客户端本机跑 | 不跑：没有仿真、OPC UA、Modbus、MQTT |
| 浏览器里有什么 | 4.x 的全部页面 + 单位管理 `/org` + 班级进度 `/progress` | 单位管理、老师的班级与成绩、班级进度、账号页面；平台运维 `/ops` |
| 建模、仿真、做作业 | 客户端（或服务器网页） | 只在客户端（学生、老师自己的电脑上） |

切换：环境变量 `VF_MODE=saas`（或 `selfhost`），或 `<数据目录>/config/deploy.json`：

```json
{"mode": "saas", "license_required": false, "session_hours": 168, "ops_ips": ""}
```

环境变量优先于 deploy.json。数据目录 = 环境变量 `VF_HOME`（不设就是程序目录）。

---

## 1. 升级和数据迁移（4.x → 5.0）

- 第一次启动 5.0 时自动建新表（单位、会话、AI 用量、进度、运维账号、运维审计），**已有的账号、班级、作业、提交都归入"默认单位"（default）**。可以重复执行，不丢数据。
- 4.x 发的登录令牌到期前照样能用；5.0 的令牌带会话号，可以吊销。
- 新角色"单位管理员"（`orgadmin`）。自部署的"管理员"（`admin`）照样是全部权限，单位管理页面也能用。
- 依赖：`cryptography`（授权文件验签，已加进 `requirements.txt`）。没装的话授权文件验不了（按未授权处理），其余功能不受影响。
- 网页多了一个依赖 `qrcode-generator@1.4.4`（运维后台绑定 TOTP 的二维码）：`cd web && npm install` 后再构建。

---

## 2. 自部署

### 2.1 安装和启动

和 4.x 一样（`run.cmd` / Docker / `python -m vfactory serve`）。默认就是 selfhost，什么都不用改。

### 2.2 授权文件（离线激活）

1. 学校 / 企业把单位名称、需要的老师数和学生数、期限、功能包告诉蜂元；
2. 蜂元签发一个 `.vflic` 文件（见第 5 节），发给学校；
3. 学校的管理员登录网页 → **单位管理 → 授权文件 → 导入授权文件**。服务器当场验签（不连外网），通过才生效；
   也可以直接把文件放到 `<数据目录>/config/license.vflic`。
4. 生效后，"单位管理"页面上显示授权单位、席位、有效期、功能包；建老师、导入学生时按授权的席位检查。

规则：

- **没装授权文件**：默认不限席位（和 4.x 一样，页面提示"未激活"）。要强制授权：`deploy.json` 里 `"license_required": true`（或 `VF_LICENSE_REQUIRED=1`），这时按试用额度（5 名老师、50 名学生）。
- **授权到期**：已有账号照常能用；不能再新建老师、学生账号（提示续期）。导入新授权文件即可。
- **文件被改过 / 不是蜂元的密钥签的**：验不过，按未授权处理；页面上显示原因。

### 2.3 单位管理员能做什么（`/org`）

- 建老师（占老师席位；不填密码就生成临时密码，第一次登录要改）；
- 批量导入学生（粘贴"学号,姓名[,密码]"或 Excel 两列；新账号占学生席位，**超了整批不导**，先"检查"会告诉你还剩几个）；
- 学期结束**归档**学生（按选中的人或按班级）：不能登录、不占席位，成绩和提交保留，随时能恢复；
- 停用 / 启用老师、重置密码（会让他的登录全部失效）；
- 看用量（席位、30 天活跃、本月提交、本月 AI tokens）；
- **导出本单位全部数据**（zip：账号不含密码、班级与名单、作业、提交和作业包、进度、AI 用量、审计）——要再输一次自己的密码；
- **删除本单位全部数据**（输入单位名称 + 自己的密码；自部署保留操作者自己的管理员账号）。

---

## 3. SaaS（蜂元云）

### 3.1 服务器

```bash
# Linux 示例（数据目录 /srv/vf，只监听本机，前面放 HTTPS 反向代理）
export VF_MODE=saas
export VF_HOME=/srv/vf
export VF_HTTPS=1                      # 反向代理没传 X-Forwarded-Proto 时，告诉服务器"对外是 HTTPS"（Cookie 加 Secure、发 HSTS）
export FORWARDED_ALLOW_IPS=127.0.0.1   # uvicorn：只信任本机反向代理传来的客户端地址（登录限流、IP 白名单按真实地址算）
python -m vfactory serve --http 8800
```

SaaS 模式启动时不建示范工厂、不开 OPC UA / Modbus / MQTT 端口（`--opcua/--mqtt/--modbus` 参数被忽略），也不建演示账号（admin/honey123 这类）。

大模型（AI 代理用，密钥只在服务器上）：`<数据目录>/config/llm.local.json`

```json
{"base_url": "https://…/v1", "api_key": "…", "model": "…"}
```

或环境变量 `VF_LLM_BASE_URL / VF_LLM_API_KEY / VF_LLM_MODEL`。这个文件不进仓库、不进镜像。

### 3.2 第一个运维账号

在服务器本机上（和服务用同一个数据目录）：

```bash
VF_HOME=/srv/vf python tools/ops_admin.py create --username ops.zhang --name 张三
# → 打印初始密码（只显示这一次）
```

然后浏览器打开 `https://<域名>/ops`：输账号密码 → 手机验证器 App（Microsoft Authenticator、Google Authenticator、腾讯身份验证器等）扫二维码 → 输 6 位验证码 → **保存 10 个恢复码** → 改初始密码。之后每次登录都要验证码（手机不在身边用恢复码，每个只能用一次）。

其他命令：`tools/ops_admin.py reset --username …`（忘了密码或手机丢了：重置密码并清掉 TOTP，下次登录重新绑定）、`list`、`verify-audit`（检查审计哈希链）。

### 3.3 运维后台（`/ops`）

- **开户**：单位代码（小写字母开头，例 `zzu`）、名称、方案 / 合同号 / 起止日期（账单线下结算，这里只记录）、老师席位、学生席位、功能包（课程包、PLC、AI、客户端）、每月 AI 额度，同时建第一个单位管理员（初始密码只显示一次，第一次登录要改）。
- **试用账号**：30 天、5 名老师、50 名学生（不用再验证码）。
- **编辑 / 停用 / 恢复 / 导出单位数据 / 再加单位管理员**。
- **用量**：每个单位的 30 天活跃、老师 / 学生 / 归档数、班级、本月和累计提交、本月和累计 AI tokens。
- **运维账号**：新建（对方第一次登录绑定 TOTP、改密码）、停用、重置 TOTP。
- **审计**：每个运维操作一条，只增不改（数据库触发器拦截改和删），每条带前一条的哈希；"检查哈希链"能查出哪一条被改过或删过。
- **设置**：IP 白名单（例 `10.0.0.0/8, 203.0.113.7`；空 = 不限；保存时如果不包含你现在的地址会拒绝，防止把自己挡在外面）。环境变量 `VF_OPS_IPS` 设了就以它为准。

安全要点：

- 运维账号和单位账号完全分开；**没有"以单位身份登录"**——单位的数据只由单位自己的账号看。
- 会话：Cookie `vf_ops`（HttpOnly、SameSite=Strict、只发给 `/api/ops`、HTTPS 时 Secure），空闲 15 分钟（`VF_OPS_IDLE_MIN`）或满 8 小时（`VF_OPS_MAX_HOURS`）失效。写操作必须带 `X-CSRF-Token`（等于 Cookie `vf_ops_csrf`，双提交），跨站的 Origin 拒绝。
- **敏感操作再验 TOTP**：改席位 / 到期 / 功能包 / AI 额度 / 单位状态、开户、导出单位数据、建运维账号、停用运维账号、重置 TOTP、改 IP 白名单。同一个验证码只能用一次（防重放）。
- 连续输错 5 次锁 30 分钟。

### 3.4 单位怎么用

1. 单位管理员登录网页 → 改初始密码 → "单位管理"：建老师、导入学生（建议勾"账号前面加单位代码"，账号全平台唯一）；
2. 老师登录网页：建班级、发布课程（课程包、PLC 功能包按单位开通的检查）、看提交和成绩、复核改分、"班级进度"；
3. 学生装客户端，登录（默认就是蜂元云），在自己电脑上做作业、交作业；客户端定时把进度报给服务器，老师在"班级进度"里看到。

SaaS 里服务器不跑工厂，所以网页上没有工厂列表、工作台、旁观 / 接管 / 注入故障、复核沙箱；AI 助教在客户端里（看本机沙箱，大模型经服务器的 AI 代理）。
凡是要跑工厂的地方，网页上给的是"在客户端中打开"按钮（`vfactory://open?path=…`，装了客户端就直接跳到客户端的对应页面）加上手动步骤，不会只给一个 403。

**做课程（SaaS）**：在老师的客户端里做。

1. 客户端登录蜂元云 → 左边"课程"→ 新建 / 复制一份来改 / 编辑：草稿、出题检查（试运行起始模型和参考做法）、"按学生预览"都在老师的电脑上跑，用的是同一套规则引擎；预览作业的编号从 10 亿开始，和云端的作业号分开。
2. 点"发布"：本机试运行通过 → 冻结 → 用本机的课程签名密钥签成 `.vfcourse` → 传到云端（`POST /api/teach/authoring/upload`，带草稿和公钥）。
3. 云端只验包，不跑工厂：结构、每个文件的哈希、签名（随包的公钥，key_id 对得上）、规则引擎版本、课程的静态校验、课程编号不能是别人的、PLC 功能包；通过后存成本单位的课程（版本号由服务器递增）。参考做法只留在老师电脑上。
4. 网页或客户端的课程库里"发布到班级"。学生的客户端打开作业时从云端下课程包——由服务器用自己的密钥重新签名，学生客户端只认服务器的公钥——装到本机，在本机沙箱里做。
5. 换了电脑：客户端的"我做的课程"里会列出云端上自己的课，点"下载到本机继续改"（`GET /api/teach/authoring/{课程}/draft`）。
   网页上的"新建课程 / 在客户端里编辑 / 复制一份来改"都给对应的客户端链接（`/courses?new=1`、`/courses?edit=<课程>`、`/courses?copy=<课程>`）。

**老师的实时看板（班级进度 `/progress`，教学控制台）**：学生的客户端开着就每分钟报一声（在线 = 3 分钟内报过），作业有变化（进沙箱、作答、本机评分、交作业）10 秒内上报进度和当前步骤。
看板上：在线 / 卡住 / 在做 / 还没开始 / 全部交了的人数（可点筛选），每个学生在线与否、最近一次上报、现在在做哪一课哪一步、停了多久（同一步超过 `VF_STUCK_MIN` 分钟、默认 10，标"卡住"），每一课的进度、本机分和成绩。
教学控制台在 SaaS 里按上报的数据给每个学生标状态，学生详情里是"进度"页签（替代旁观和注入故障）。

### 3.5 到期、停用、额度

- **单位到期**：老师和学生不能登录（提示到期日）；单位管理员还能登录（导出数据、联系续期）；不能新建账号。
- **单位停用**：全部账号不能登录，已登录的马上失效。
- **AI 额度**（每月 tokens，按单位）：用完了这个单位的 AI 助手、AI 助教、AI 辅助评分都停用到下个月（或运维加额度），提示"本单位本月的 AI 额度已经用完"。功能包里关掉 AI 也一样。

---

## 4. HTTPS 反向代理（两种部署都建议）

服务只监听本机，对外由 Nginx / Caddy 提供 HTTPS。WebSocket（`/ws/`，自部署的工厂实时画面）要升级连接。

### Nginx

```nginx
# 放在 http { } 里
map $http_upgrade $connection_upgrade { default upgrade; '' close; }

server {
    listen 443 ssl http2;
    server_name vf.example.edu.cn;
    ssl_certificate     /etc/ssl/vf/fullchain.pem;
    ssl_certificate_key /etc/ssl/vf/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 64m;          # 和服务器的 VF_MAX_BODY_MB 一致（作业包 5 MB、课程封面 3 MB、名单 Excel）

    location / {
        proxy_pass http://127.0.0.1:8800;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;     # WebSocket
        proxy_set_header Connection        $connection_upgrade;
        proxy_read_timeout 360s;                               # 交作业包时服务器评分（自部署）最多几分钟
    }
    # 运维后台只给公司网络（可选；服务器里还有一层 IP 白名单）
    location /ops    { allow 203.0.113.0/24; deny all; proxy_pass http://127.0.0.1:8800; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
    location /api/ops/ { allow 203.0.113.0/24; deny all; proxy_pass http://127.0.0.1:8800; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
}
server { listen 80; server_name vf.example.edu.cn; return 301 https://$host$request_uri; }
```

### Caddy

```
vf.example.edu.cn {
    reverse_proxy 127.0.0.1:8800
    request_body { max_size 64MB }
}
```

要点：

- `X-Forwarded-Proto https` → 服务器给 Cookie 加 Secure、发 `Strict-Transport-Security`。代理没传这个头时设 `VF_HTTPS=1`。
- 客户端地址：uvicorn 只信任 `FORWARDED_ALLOW_IPS`（默认 127.0.0.1）里的代理传来的 `X-Forwarded-For`；代理不在本机时把代理的地址加进去。登录限流、运维 IP 白名单、审计里的 IP 都按它算。
- 主界面用 `Authorization: Bearer` 令牌（存在浏览器本地存储，不用 Cookie），天然不受 CSRF 影响；运维后台用 Cookie + CSRF 令牌。
- 服务器还会加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: same-origin`。

---

## 5. 授权文件的签发流程（蜂元内部）

私钥**绝不**进仓库、安装包、服务器镜像；放在加密 U 盘或密码管理器里，只在签发的电脑上用。

### 5.1 生成密钥对（只做一次）

```bash
python tools/license_sign.py keygen --out D:\secure\vf-license
```

- 私钥写到 `D:\secure\vf-license\vf-license-signing.key`（工具拒绝写在仓库目录里）；
- 屏幕上打印公钥那一行，粘进 `vfactory/tenancy/license_keys.py` 的 `TRUSTED`，随下一版发布。仓库里**只有公钥**。

### 5.2 签发

```bash
set VF_LICENSE_KEY=D:\secure\vf-license\vf-license-signing.key
python tools/license_sign.py sign --org-name "郑州某职业技术学院" --org-code zzvtc ^
    --teachers 20 --students 600 --starts 2026-09-01 --expires 2027-08-31 ^
    --features plc,ai,client --courses all --ai-quota 2000000 --out zzvtc-2026.vflic
python tools/license_sign.py verify zzvtc-2026.vflic        # 用仓库里的公钥验一遍
```

文件内容是 JSON：`payload`（授权号、单位、席位、起止日期、功能包、AI 额度）+ `key_id` + `sig`（对规范化 payload 的 Ed25519 签名）。改动任何一个字节都验不过。

### 5.3 换密钥

生成新密钥对，把新公钥**加进** `TRUSTED`（旧的先留着），发新版；之后用新私钥签发；旧授权都到期后再把旧公钥删掉。私钥泄露时：立刻删掉对应公钥并发版，给所有单位重签。

---

## 6. 客户端

- 登录页默认连**蜂元云**。地址配置（先到先用）：环境变量 `VF_CLOUD_URL` → 安装目录 `server.json` 的 `"cloud"` → `<数据目录>/config/client.json` 的 `"VF_CLOUD_URL"`。域名还没定，现在是占位地址（`https://vf-cloud.invalid`，登录页提示"还没有配置"）。
- 学校 / 单位自己部署的服务器：登录页点"学校 / 单位自己的服务器"填地址（安装包可以用 `server.json` 的 `"server"` 预置）。
- "不连服务器，单机使用"照旧。
- 登录记住 7 天（`VF_SESSION_HOURS`），期间断网也能打开本机工厂、做已装到本机的作业；交的作业和上报的进度在本机排队，联网后自动补交 / 补报。
- AI 助手 / 助教：客户端本机没配大模型时，经登录的服务器的 AI 代理（`/api/ai/proxy/chat/completions`，按单位计量）。

---

## 7. 安全清单

| 项 | 做法 |
|---|---|
| 单位隔离 | 每个接口按用户所属单位检查（`tenancy/policy.py` + 教学接口的 `teaches / need_class / need_assignment` + 账号、令牌、审计按单位过滤）；`tests/tenant_check.py` 枚举全部接口证明 |
| 登录 | 连续输错 5 次锁 15 分钟（`VF_LOCKOUT_N` / `VF_LOCKOUT_MIN`）；同一 IP 10 分钟失败 30 次暂停 10 分钟 |
| 密码 | SaaS（或 `VF_PW_POLICY=strict`）：至少 8 位、字母和数字都有、不含账号名、不是常见密码；管理员发的都是随机临时密码，第一次登录必须改 |
| 会话 | 带会话号、可吊销：退出登录、改密码（别处的登录失效）、重置密码、归档、停用账号 / 单位；`/api/me/sessions` 看自己的登录 |
| 请求大小 | 超过 `VF_MAX_BODY_MB`（默认 64）直接 413；作业包 5 MB、封面 3 MB、授权文件 64 KB 各有上限 |
| 文件路径 | 网页文件、课程封面按真实路径检查在允许的目录里面（防 `..` 和同名前缀目录） |
| 备份 | 单位管理员"导出本单位数据"、运维"导出单位数据"（zip）；整库备份 = 停服务后拷贝 `<数据目录>/data` |
| 运维 | TOTP、敏感操作再验、IP 白名单、短会话、Cookie + CSRF、哈希链审计、没有代登录 |
| AI | 密钥只在服务器；按单位、按月计量，超额停用 |

---

## 8. 还没做的（留了接口）

- **服务器复评 / 防作弊**：SaaS 里作业包按客户端本机评的分记（提交明细里 `verified=false`）。`vfactory/tenancy/hooks.py` 的 `register_rescorer(fn)` 留了挂钩：以后另起评分机或抽查时注册一个函数即可。
- 在线支付：账单线下结算，运维后台只记方案、合同号和起止日期。
- 网页依赖 `qrcode-generator@1.4.4`：合并时在 `web/` 里运行 `npm install qrcode-generator@1.4.4 --save-exact`（更新 package-lock.json 并装进 node_modules）。
