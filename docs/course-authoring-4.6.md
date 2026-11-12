# 4.6 课程：学生课程页、老师做课程、本机评分与签名课程包、AI 辅助评分

对应用户问题 9：菜单名"教学"→"课程"；课程页改成卡片；老师能做课程、发布课程；本机评分怎么做才可信；老师用 AI 给学生作业打分。

## 1. 命名和入口

| 角色 | 菜单 | 地址 | 内容 |
|---|---|---|---|
| 学生（含客户端单机） | 课程 | `/courses`（`/teach` 也到这一页） | 课程卡片、课程详情、这一课、学校作业 |
| 老师 / 管理员 | 课程 | `/courses` | 我做的课程、课程库、课程编辑器、按学生预览、发布到班级 |
| 老师 / 管理员 | 教学 | `/teach` | 教学控制台（提交与复核、AI 建议）、班级与名单、单个作业 |

旧链接 `/teach?tab=courses` 转到 `/courses`；`/teach?l=<作业号>`（开始页、命令面板）照常打开那一课。

## 2. 学生课程页

- 页头插画 + 统计（课程数、完成的课、学校作业数）+"继续上次的课"。
- 工具条：进行中 / 已完成 / 全部，搜索（课程名、章名、课名），深浅色切换。
- 课程卡片（默认收起）：封面、课的类型、标题、两行简介、章数和课数、进度条、下一课、"继续/开始"。
- 点卡片 → 右侧抽屉"课程详情"：章（全部完成的章默认收起）→ 课（状态图标、类型、最高分、锁定原因：上一课没及格 / 先修课没完成）。
- 点一课 → "这一课"视图：左边只列这门课的章节（"‹ 全部课程"回去），右边任务书、作答、成绩；地址栏 `?l=` 记住这一课，刷新不丢。
- "学校作业"单独一块：老师单独布置的作业；客户端里另有学校服务器上的作业（"在本机做"）和"打开作业包"。
- 工作台左栏的"我的课程"窄面板：只展开有当前这一课的课程，其他课程点名称展开。

## 3. 老师做课程

课程编辑器存的就是课程文件的格式（`vfactory/courses/__init__.py`，4.6 之前的课程文件原样可用），左边大纲（课程信息 → 章 → 课，上移下移，跨章移动），右边编辑选中的那一项。

课的模板：

| 模板 | 课的 kind | 老师设置 | 评分 |
|---|---|---|---|
| PLC 实训 | `cell` | 选场景；是否锁定模型（`lock_model`）；选用场景的哪些评分项（`rubric`）；自加检查（"t 秒按 X，s 秒内输出 Y = 1"→ `tests` + `extra_rules`） | 场景的自动测试序列（`control/scoring.py`，`eval_cond` 和实时检查表同一份） |
| 产线任务 | `plant` | 工厂模板（课程自带的工厂或 `templates/`）；先改好的参数（`params`）；学生能改的参数（`lock.editable`）；不能增删设备（`lock.structure`）；仿真小时数、随机种子、预热 | `kpi` / `budget` / `limit` 规则，用固定种子跑 `time_h` 小时 |
| 测验 | `quiz` | 单选、多选、判断、填数（允许误差、单位） | `answer` 规则；没有沙箱 |
| 在图上点设备 | `point` | 工厂模板 + 点选题（答案是设备编号，可多个） | `answer` + `pick` |
| MES 操作 | `mes` | 声明式的 MES 检查（`query` / `op` / `value`） | 教学 MES 注册取数函数（见 5.3） |

先修和解锁（`lesson.unlock`）：`{min: 60}` 本课及格分；`{after: [课编号…]}` 指定先修课（全部达到各自的及格分才解锁，先修课必须排在前面）；`{free: true}` 不锁。不写时和以前一样：上一课及格解锁下一课。老师发布到班级时仍可"全部开放"。

流程：新建（空白或复制内置课程）→ 编辑（4 秒自动保存）→ 检查（服务器校验，错误不能预览和发布）→ 按学生预览 → 发布（版本号 +1，冻结，签名）→ 课程库里"发布到班级"（和内置课程同一个 `/api/teach/courses/{id}/publish`）。

- 预览：冻结一份 `_preview-<编号>`，发到老师自己的隐藏班"课程预览"（不出现在班级列表和控制台），老师按学生的样子做，提交是"老师试做"，不进成绩册。
- 发布：校验通过才行；产线课把工厂模型（模板 + 改好的参数）内嵌进课程（`lesson.model`），以后模板改了也不影响已发布的课；冻结到 `data/teach/courses/<编号>.json`（服务器评分只用这一份），历史版本在 `data/teach/courses/versions/`。
- 共享：课程信息里打开"共享"后，其他老师在课程库里能看到、发布、复制。

接口见 `vfactory/teach/authoring.py` 文件头。

## 4. 本机评分（难点）的设计

### 4.1 原则

1. 评分规则全是数据，没有任何可执行代码。校验时拒绝 `code / expr / eval / script` 之类的字段。
2. 同一个评分引擎在两边跑：学校服务器（权威分）和客户端（本机后端就是同一个 `vfactory` 包，离线时给本机预估分）。规则判断在 `vfactory/courses/rules.py`，指标在 `scoring.py`（产线）和 `control/scoring.py`（PLC）。只要课程、学生的作答 / 模型 / 程序、随机种子一样，两边的分数就一样。
3. 服务器总是用自己冻结的那份课程重新评分，客户端交上来的本机分只做参考。

### 4.2 规则格式（`rules.RULES_VERSION = 1`）

```
rule = {key, kind, label?, weight, …}
  kpi     {metric, op, value}                 仿真指标（本课 time_h 小时、seed、warmup_h）：good、good_per_h、oee_avg、oee.<块>、util.<块>、orders_late …
  budget  {op, value}                         投资合计（万元）
  limit   {metric, op, value}                 count.<类型>、count_all、buffer_total、operators、vehicles、overlap、outside
  answer  {choices, answer: 1}                单选（qtype 缺省 single）
          {qtype: 'multi', choices, answer: [0, 2]}     多选：集合完全一致
          {qtype: 'tf', answer: true}                   判断
          {qtype: 'number', answer: 12.5, tol: 0.5, unit?}   填数：|作答 − answer| ≤ tol
          {pick: true, kinds?, answer: ['M3']}          在图上点设备：点中其中之一
  mes     {query, field?, where?, op, value}  MES 状态
op: >= > <= < == !=
PLC 课：场景的 {key, op, value, weight}（key = 统计量或测试序列里 check 的 key），
        课上的 rubric = [场景评分项 key]，tests = [测试步骤]（press / release / set / check+within/hold / watch / fault），extra_rules = [评分项]
```

例子：

- "种子 S 跑 8 小时，合格品 ≥ K"：`{"kind": "kpi", "metric": "good", "op": ">=", "value": K}`，课上 `time_h: 8, seed: S`
- "OEE(CNC3) ≥ x"：`{"kind": "kpi", "metric": "oee.CNC3", "op": ">=", "value": x}`
- "按 START 后 1 秒内 Q0.0 = 1"：`tests: [{"t": 122, "press": "START"}, {"t": 122.05, "key": "chk1", "check": {"out": "Q0.0", "eq": true}, "within": 1}]`，`extra_rules: [{"key": "chk1", "op": ">=", "value": 1, "weight": 20}]`
- "测验答案是 B"：`{"kind": "answer", "choices": ["A", "B", "C"], "answer": 1}`
- "点的设备是 CNC3"：`{"kind": "answer", "pick": true, "answer": ["CNC3"]}`

### 4.3 课程包 `.vfcourse`（`vfactory/courses/coursepkg.py`）

```
manifest.json   {format: 'vfcourse', version: 1, engine: 1, course: {id, name, version}, created, server,
                 files: {文件名: sha256}, content_sha256}
                 content_sha256 = sha256(按文件名排序的 "文件名:哈希\n")，就是"这门课这一版"的内容指纹
signature.json  {alg: 'ed25519', key_id, sig}       Ed25519(规范化的 manifest.json 字节)
course.json     引擎格式的课程：去掉参考答案，作答题答案封存（seal）
assets/…        封面等图片
```

- 签名密钥：学校服务器第一次用时生成 Ed25519 私钥，存在服务器数据库的 settings 表（和会话密钥同一个地方，不进代码库、不进课程包）。`key_id = sha256(公钥)[:16]`。
- 客户端信任哪个公钥：第一次登录学校服务器时取 `/api/teach/courses/pubkey`，存进本机 `data/client/school.json` 的 `course_keys`（先到先信）。之后服务器换了密钥，新包验不过，要重新登录确认。
- 装包：学校作业用到老师做的课（`task?client=1` 里 `course_origin = authored`）时，客户端从 `/api/teach/courses/<编号>/package` 下载，验签名后装到 `data/client/courses/<编号>.vfcourse`；学校发了新版本（`course_version` 更大）自动更新。也可以手动装（`POST /api/client/courses/install`）。
- 每次读包都重新验：清单外的文件、任何一个文件的哈希、内容指纹、签名，有一处不对就不加载这门课（`courses.package_error` 记原因，评分时提示"课程包校验没通过"）。改答案、改分值、改评分规则、换掉整个 course.json 都过不了签名。
- 没有 `cryptography` 组件的服务器退回 HMAC：客户端不能离线验，只在线装包，装时给包封一个本机印章（本机密钥的 HMAC），之后离线读包验这个印章。
- 答案封存：作答题的 `answer` 换成 `seal`（按课程 / 课 / 题号派生的异或混淆）。客户端能离线判分，就一定能还原答案，所以这只是"不让答案直接摆在 JSON 里"，不是保密；权威分永远是服务器重评的分。

### 4.4 一次离线作业的全过程

1. 学生在客户端"在本机做"学校作业 → 客户端装（或更新）签名课程包 → 本机建同样的作业。
2. 离线作答 → "本机评分"：本机后端用课程包里的规则判分（本机预估分）。
3. 联网"提交给老师"：作业包 `.vfhw`（测验课只有 answers.json，版本 2）→ 学校服务器 `submit_package` 用冻结的课程重新评分 → 服务器分 = 成绩；两边规则、作答一样，所以和本机分一致（`tests/courses_ui.js` 核对）。

## 5. AI 辅助评分（`vfactory/teach/aigrade.py`）

- 教学控制台 → 学生 → "提交与复核"：每次提交下面有"AI 建议"框，"让 AI 看一遍"→ 每个评分项的建议分和评语 + 建议总分和总评；"采用评语"（逐项）、"采用分数和评语"只是填进下面的复核框，老师点"保存复核"才算成绩。界面写明"AI 建议 · 仅供参考 · 你确认后才算成绩"。
- AI 读的内容：任务书节选、评分项（自动检查的要求、结果、得分）、学生的程序 / 模型摘要 / 作答、运行统计、自动试运行记录。规则：不能和自动检查矛盾（没通过的项最多给一半分并说明），总分只能在逐项合计 ±10 分内（服务器端再夹一次）。
- 批量："给全班生成 AI 建议"→ 后台跑每个学生最近一次提交（并发 3），顶部进度条，跑完回到每个学生的复核里逐个确认。
- 记录：`ai_suggestions` 表存建议和老师的处理（采用 / 改过 / 没用），审计用，不影响分数。
- 大模型走 `copilot.chat`（`config/llm.local.json` 或 `VF_LLM_*` 环境变量），不存密钥。测试用 `VF_LLM_FAKE=1`（假模型按自动检查写建议，结果确定）。

### 5.3 给教学 MES 的接口

MES 课的检查在评分进程里跑。教学 MES 模块在 `vfactory/teachmes/rules.py`（或 `vfactory/mes/teach_rules.py`，或环境变量 `VF_MES_RULE_MODULES` 指定）里调用

```python
from vfactory.courses.rules import register_mes
@register_mes
def mes_value(rule, ctx):          # ctx = {username, assignment_id, lesson, course, class_id}
    ...                            # 按 rule['query'] / rule.get('where') 返回数值或字符串；不认识的 query 返回 None
```

没有注册时 MES 检查判"没有连上 MES"，不得分。教学 MES 已经接上：`vfactory/mes/teach_rules.py`（内置课程 `mes_intro`，4 课）。

评分时传给取数函数的 `ctx`：`{kind, username, assignment_id, lesson, course, class_id, pid, answers, mes_snapshot}`。

权威复评怎么做（学校服务器上没有 MES）：

1. 客户端交作业（本机评分）这一刻调用 `teach_rules.snapshot(rules, answers, pid)`，在本机 MES 上一次取好全部 MES 规则的值，存进这次提交的 `program.mes_snapshot`；本机分按这份快照判。
2. "提交给老师"/导出作业包时，作业包里多一个 `mes_snapshot.json`（取最近一次本机评分的快照，没有就现取），作答在 `answers.json`。
3. 学校服务器复评：取数函数先看 `ctx['mes_snapshot'][rule.key]`，所以和本机分一致。网页上直接交（没有快照、也没有 MES）时 MES 检查判"没有连上 MES"。

快照是学生的客户端交上来的数据，和本机分一样不是防作弊手段；它保证的是"同一份 MES 状态 → 两边同一个分"。

## 6. 出题检查（4.6.1）

起因：老师随手做的一门测试课（一课产线任务、评分项名称"1"、20 分、任务书空、目标"合格品 ≥ 100"、没有任何限制），学生端看到"✓ 1　20 分 / 目标：至少 100"，说明还写着"试运行你的程序"；起始模型 8 小时本来就做出 371 件，学生什么都不改就满分。

学生看到的目标：

- 每条规则有生成的说明 `goal`（`rules.describe`，按 `rules.METRICS` 的名称和单位）："8 小时合格品 ≥ 100 件"、"M1 的 OEE ≥ 75%"、"投资合计 ≤ 220 万元"、"答案：单选题，选出正确的一项"、"MES：工单数 ≥ 1"。比例指标（OEE、利用率、废品率）显示成百分数。
- 标题 `title`：老师的名称有意义就用它；空的、只有数字 / 标点、只有一两个字时用说明（`rules.title_of`）。`public_lesson`、实时进度、评分明细都带 `title` / `goal`（明细的 `label` 也是这个标题）。
- "目标与作答"开头的说明按课的类型：PLC "你的程序"，产线 "你的方案（模型和参数）"，测验 "你的答案"，MES "你在 MES 里的操作"，点选 "你的答案"。

编辑器的"出题检查"面板（保存、发布时都跑；错误不能发布，提醒和备注不挡；出题检查的错误不挡"按学生预览"）：

| 检查 | 级别 | 修法 |
|---|---|---|
| 任务书空（PLC 课的场景自带任务书时不算） | 错误 | 去改 |
| 评分项合计 ≠ 100 | 提醒 | "按比例凑成 100"（四舍五入，差的分补在分值最大的一项） |
| 名称空 / 没意义；名称像旧的说明但目标值改过 | 提醒 | "用作名称"（生成的说明） |
| 产线课有 kpi 目标，但没有预算 / 数量限制，也没有 `lock.editable` / `structure` | 提醒 | 加限制或锁定 |
| 比例指标的目标写成了 75（应该 0.75） | 提醒 | |
| 测验没有正确答案（多选没勾、正确选项是空的）；点选答案不在工厂里；MES query 不认识 | 错误 | |
| 填数题没设允许误差；有空选项 | 提醒 | |
| 试运行：起始模型（学生什么都不改 / PLC 不写程序）就能及格，或者某条 kpi 目标已经达到 | 提醒 | 例："学生什么都不改就能得 100 分（及格 60）：合格品 8 小时约 371 件，目标 ≥ 100" |
| 试运行：老师存的参考做法拿不到及格分 | 错误 | "参考做法也拿不到及格分，目标可能做不到" |
| 没有参考做法（PLC 课用场景自带的参考程序） | 备注 | "没有参考做法：无法确认目标做得到" |

试运行（`courses/verify.baseline`）在学生交作业的同一个评分进程池里、走同一条评分路径（产线课 `score_lesson`，固定种子和 `time_h`；PLC 课 `score_scene` + 课的评分改动）。结果按"和评分有关的课的内容 + 工厂模板 / 场景展开后的内容 + 参考做法 + 引擎版本"的指纹缓存在 `authoring_baselines` 表里，改任务书、名称不用重跑。保存后后台跑，编辑器显示进度；发布前没跑完的先跑完。

参考做法：老师在"按学生预览"里把这一课做好，点"存为参考做法"（`POST /api/teach/authoring/{cid}/reference {aid}`，取老师沙箱里的模型 / PLC 程序和作答），存在服务器的 `authored_refs` 表，不进冻结的课程，也不进课程包。面板里列出它改了什么（"B1.capacity：1 → 20"）和它的得分。

## 7. 兼容

- 课程文件格式只加字段；旧课程、旧作业、旧作业包都照常可用。作业包里测验课是版本 2（4.4 起服务器就认版本 2）。
- `courses.list_courses()` 默认只列内置课程（客户端"本机自学"用）；服务器课程库列内置 + 老师发布的，客户端另列装好的课程包。
