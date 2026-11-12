"""块类型目录：编辑器的资源库、属性面板、端口都从这里来。

参数 t：num 数字 / int 整数 / expr 表达式 / text 文字 / bool 开关 / enum 选项 / ref 引用其他块 / json 结构化
"""

IMPLICIT_PORTS = {'melt', 'ladle', 'sand', 'mold'}   # 高级模型之间的内部耦合，只做显示

FAIL = {'mtbf_h': {'label': '平均故障间隔', 't': 'num', 'unit': 'h', 'default': 0, 'group': '故障', 'help': '0 表示不发生随机故障；故障间隔服从 Weibull(1.5)'},
        'mttr_min': {'label': '平均修复时间', 't': 'num', 'unit': 'min', 'default': 30, 'group': '故障', 'help': '对数正态分布'},
        'fail_basis': {'label': '故障计时口径', 't': 'enum', 'default': 'operating', 'group': '故障',
                       'options': {'operating': '按运行时间（只在加工时老化）', 'calendar': '按日历时间（停着也老化）'},
                       'help': '运行时间口径适合磨损类故障；日历时间口径适合腐蚀、电子元件等与是否开机无关的故障'},
        'fail_beta': {'label': '故障分布形状', 't': 'num', 'default': 1.5, 'group': '故障',
                      'help': 'Weibull 形状参数：1 = 完全随机（指数分布），>1 = 越用越容易坏（磨损），<1 = 早期故障多'}}
POWER = {'idle_kw': {'label': '待机功率', 't': 'num', 'unit': 'kW', 'default': 1, 'group': '能耗'},
         'run_kw': {'label': '运行功率', 't': 'num', 'unit': 'kW', 'default': 10, 'group': '能耗'},
         'power_by_state': {'label': '按状态功率', 't': 'json', 'default': {}, 'group': '能耗',
                            'help': '覆盖各状态下的功率 kW，如 {"starved":2,"blocked":2,"setup":5,"failed":0.5,"planned":0.3,"offshift":0}。'
                                    '状态键：run 运行、idle 待机、starved 缺料、blocked 堵料、failed 故障、setup 换型、planned 计划停机、offshift 非班次'}}
SETUP = {'setup_matrix': {'label': '换型矩阵', 't': 'json', 'default': {}, 'group': '节拍',
                          'help': '顺序相关换型（分钟）：{"A":{"B":10,"C":25},"B":{"A":15},"*":{"C":30}}，行是上一个产品、列是下一个产品，* 为通配；查不到时用"换型时间"'}}
QUALITY = {'defects': {'label': '缺陷规则', 't': 'json', 'default': [], 'group': '质量',
                       'help': '列表：[{"name":"气孔","prob":"0.02 + 0.01*(item.get(\'temp\',0)>1450)","size":"uniform(0.2,1)"}]，概率可以引用零件属性'},
           'attrs': {'label': '写入零件属性', 't': 'json', 'default': {}, 'group': '质量', 'help': '{"属性名":"表达式"}，如 {"bore":"normal(40.01,0.004)"}'}}
# 5.0 动作级信号（vfactory/actions.py）：通用加工块可选打开；高级 CNC / 造型线 / 去毛刺默认就有
ACT_FAULTS = {'action_faults': {'label': '动作故障（预置）', 't': 'json', 'default': [], 'group': '动作信号',
                                'help': '仿真开始就有的动作故障：[{"kind":"cyl_leak","cyl":"clamp","extra_s":1.5,"drift_s_per_day":0.3}]；'
                                        'kind：cyl_leak 气缸泄漏（伸出变慢）、sticky_clamp 夹具卡滞（松开变慢）、slow_door 防护门变慢'}}
ACTIONS = {'actions': {'label': '动作级信号', 't': 'enum', 'default': '', 'group': '动作信号',
                       'options': {'': '不发', 'cnc': '加工中心（门 / 夹具 / 主轴 / 程序段）', 'press': '压机 / 造型（射砂 / 压实 / 推型）',
                                   'robot': '机器人 / 取放（夹爪 / 工装夹紧）'},
                       'help': '发出循环内的动作信号（Actions/…，带精确时间戳），给 MES 做节拍分析；只跟第一个工位'}, **ACT_FAULTS}
SHIFT = {'follow_shifts': {'label': '跟随班次', 't': 'bool', 'default': True, 'group': '行为', 'help': '非生产时间（班次外、休息日）停下；关掉表示连续运行（如热处理炉、自动线）'}}
ROUTE = {'route': {'label': '出口分配', 't': 'enum', 'default': 'seq', 'group': '行为', 'options': {'seq': '依次（第一个有空位的）', 'ratio': '按比例', 'shortest': '最短队列'}}}


def T(label, cat, icon, color, ports_in, ports_out, params, size=(4, 3), kind=None, legacy=False, needs_in=True, needs_out=True, help=''):
    return {'label': label, 'cat': cat, 'icon': icon, 'color': color, 'in': ports_in, 'out': ports_out, 'params': params, 'size': list(size),
            'kind': kind, 'legacy': legacy, 'needs_in': needs_in, 'needs_out': needs_out, 'help': help}


BLOCK_TYPES = {
    # ---------------- 通用块 ----------------
    'source': T('来料', '出入口', 'Download', '#2e9d5b', [], ['out'], {
        'interval': {'label': '到达间隔', 't': 'expr', 'unit': 's', 'default': 'expo(120)', 'group': '节拍', 'help': '每批之间的时间（秒），可用分布函数，如 expo(120)、normal(100,10)'},
        'batch': {'label': '每批件数', 't': 'int', 'default': 1, 'group': '节拍'},
        'products': {'label': '产品比例', 't': 'json', 'default': [], 'group': '行为', 'help': '[{"code":"A","weight":3},{"code":"B","weight":1}]；空表示按生产计划'},
        'lot_prefix': {'label': '批次/供应商', 't': 'text', 'default': '', 'group': '行为'},
        'table': {'label': '按数据表放料', 't': 'text', 'default': '', 'group': '数据驱动',
                  'help': '填数据表名（"数据表"页面维护），表里有 时间（小时数或日期时间）、产品、数量、订单 列时按表放料，忽略到达间隔'},
        'repeat_h': {'label': '排程循环周期', 't': 'num', 'unit': 'h', 'default': 0, 'group': '数据驱动', 'help': '>0 时数据表排程每隔这么久重复一次（如 24 = 每天同样的到货计划）'},
        **QUALITY}, size=(4, 4), needs_in=False, help='按间隔产生零件（外购件、上道工序来料）'),
    'processor': T('加工', '加工', 'SetUp', '#d99a16', ['in'], ['out'], {
        'capacity': {'label': '并行工位数', 't': 'int', 'default': 1, 'group': '行为', 'help': '同时能加工几件'},
        'time': {'label': '加工时间', 't': 'expr', 'unit': 's', 'default': 'normal(60,3)', 'group': '节拍', 'help': '每件用时（秒），可用分布函数'},
        'product_factor': {'label': '乘产品节拍系数', 't': 'bool', 'default': True, 'group': '节拍', 'help': '按生产计划里当前产品的节拍系数放大/缩小'},
        'setup_min': {'label': '换型时间', 't': 'num', 'unit': 'min', 'default': 0, 'group': '节拍', 'help': '换产品时的准备时间'},
        **SETUP,
        'times_by_product': {'label': '按产品用时', 't': 'json', 'default': {}, 'group': '节拍',
                             'help': '{"A":"normal(60,3)","B":90}：不同产品不同用时（秒或表达式），没列出的产品用"加工时间"；可由工艺路线表导入'},
        'operator': {'label': '人员池', 't': 'ref', 'ref': 'operators', 'default': '', 'group': '人员', 'help': '需要人时，从这个人员池要人'},
        'skill': {'label': '所需技能', 't': 'text', 'default': '', 'group': '人员', 'help': '人员池配置了操作工技能时，只派会这项技能的人；空表示用本块编号作技能名'},
        'operator_mode': {'label': '要人方式', 't': 'enum', 'default': 'load', 'group': '人员', 'options': {'load': '只在上下料时', 'full': '全程'}},
        'load_s': {'label': '上下料时间', 't': 'num', 'unit': 's', 'default': 20, 'group': '人员'},
        'scrap_on_failure': {'label': '故障时当件报废', 't': 'bool', 'default': False, 'group': '故障'},
        **SHIFT, **ROUTE, **FAIL, **POWER, **QUALITY, **ACTIONS}, size=(4, 3.4)),
    'batch': T('批处理', '加工', 'Files', '#c47a1a', ['in'], ['out'], {
        'batch': {'label': '每批件数', 't': 'int', 'default': 10, 'group': '行为'},
        'time': {'label': '每批用时', 't': 'expr', 'unit': 's', 'default': '600', 'group': '节拍'},
        'max_wait_min': {'label': '凑批最长等待', 't': 'num', 'unit': 'min', 'default': 30, 'group': '节拍', 'help': '超时不满批也开始'},
        **SHIFT, **ROUTE, **FAIL, **POWER, **QUALITY}, size=(5, 5), help='热处理、清洗、抛丸等成批处理'),
    'buffer': T('缓存', '物流', 'Box', '#6b7680', ['in'], ['out'], {
        'capacity': {'label': '容量', 't': 'int', 'unit': '件', 'default': 50, 'group': '行为'}}, size=(3, 3), needs_in=False, needs_out=False,
        help='线边库、中间库。两个缓存之间要用"搬运"车队连接'),
    'conveyor': T('输送线', '物流', 'Right', '#3b82c4', ['in'], ['out'], {
        'length_m': {'label': '长度', 't': 'num', 'unit': 'm', 'default': 10, 'group': '行为'},
        'speed_mps': {'label': '速度', 't': 'num', 'unit': 'm/s', 'default': 0.2, 'group': '行为'},
        'pitch_m': {'label': '件间距', 't': 'num', 'unit': 'm', 'default': 1, 'group': '行为', 'help': '决定线上最多几件'},
        **ROUTE, **POWER}, size=(10, 1.2)),
    'inspect': T('检测', '质量', 'View', '#7a5af5', ['in'], ['out', 'ng'], {
        'time': {'label': '检测时间', 't': 'expr', 'unit': 's', 'default': '30', 'group': '节拍'},
        'pod_pct': {'label': '检出率', 't': 'num', 'unit': '%', 'default': 95, 'group': '质量', 'help': '有缺陷的件被判 NG 的概率'},
        'false_pct': {'label': '误判率', 't': 'num', 'unit': '%', 'default': 1, 'group': '质量', 'help': '好件被判 NG 的概率'},
        **SHIFT, **FAIL, **POWER}, size=(4, 4), help='合格走 out，不合格走 ng（没连 ng 时直接报废）'),
    'rework': T('返修', '质量', 'Tools', '#a14fd6', ['in'], ['out'], {
        'time': {'label': '返修时间', 't': 'expr', 'unit': 's', 'default': '120', 'group': '节拍'},
        'success_pct': {'label': '修复成功率', 't': 'num', 'unit': '%', 'default': 90, 'group': '质量'},
        'max_rework': {'label': '最多返修次数', 't': 'int', 'default': 1, 'group': '质量', 'help': '超过直接报废'},
        'fixes': {'label': '可修复的缺陷', 't': 'json', 'default': None, 'group': '质量', 'help': '缺陷名列表；空表示都能修'},
        **SHIFT, **POWER}, size=(4, 4)),
    'assembly': T('装配', '加工', 'Connection', '#14a3a3', ['in'], ['out'], {
        'parts': {'label': '几件合一', 't': 'int', 'default': 2, 'group': '行为'},
        'bom': {'label': 'BOM', 't': 'json', 'default': {}, 'group': '行为', 'help': '按子件类型取料：{"壳体":1,"轴":2}；空表示任意 parts 件合一。可由 BOM 表导入'},
        'out_product': {'label': '产出产品', 't': 'text', 'default': '', 'group': '行为', 'help': '装配后的产品代码；空表示沿用主件'},
        'time': {'label': '装配时间', 't': 'expr', 'unit': 's', 'default': '60', 'group': '节拍'}, **SHIFT, **FAIL, **POWER, **QUALITY}, size=(4, 4)),
    'split': T('拆分', '加工', 'Scissor', '#14a3a3', ['in'], ['out'], {
        'pieces': {'label': '拆成几件', 't': 'int', 'default': 2, 'group': '行为'}, **SHIFT}, size=(3, 3)),
    'sink': T('出口', '出入口', 'Upload', '#2f6fa8', ['in'], [], {
        'ship_every_h': {'label': '发运间隔', 't': 'num', 'unit': 'h', 'default': 0, 'group': '行为', 'help': '0 表示只入库不发运'},
        'scrap': {'label': '报废出口', 't': 'bool', 'default': False, 'group': '行为'},
        'scrap_cause': {'label': '报废原因', 't': 'text', 'default': '判废', 'group': '行为'}}, size=(4, 4), needs_out=False),
    'storage': T('仓库', '出入口', 'House', '#2f6fa8', ['in'], [], {
        'ship_every_h': {'label': '发运间隔', 't': 'num', 'unit': 'h', 'default': 4, 'group': '行为'}}, size=(10, 12), needs_out=False),
    'operators': T('人员池', '人员', 'User', '#e07a20', [], [], {
        'count': {'label': '人数', 't': 'int', 'default': 2, 'group': '行为'},
        'workers': {'label': '操作工与技能', 't': 'json', 'default': [], 'group': '行为',
                    'help': '[{"name":"张三","skills":["M1","M2"],"eff":1.1},{"name":"李四","skills":[],"eff":0.85}]：填了就按名单派人（人数=名单人数），'
                            'skills 为空表示都会；eff 效率 >1 更快（全程要人时用时 ÷ 效率）'}}, size=(2, 2), needs_in=False, needs_out=False,
        help='加工块的"人员池"参数指向这里；休息和非生产时间不可用'),
    'transporter': T('搬运车队', '物流', 'Van', '#f28c28', [], [], {
        'count': {'label': '车辆数', 't': 'int', 'default': 2, 'group': '行为'},
        'speed_mps': {'label': '速度', 't': 'num', 'unit': 'm/s', 'default': 1.2, 'group': '行为'},
        'capacity': {'label': '每车件数', 't': 'int', 'default': 4, 'group': '行为'},
        'load_s': {'label': '装卸时间', 't': 'num', 'unit': 's', 'default': 30, 'group': '行为'},
        'network': {'label': '按路网行驶', 't': 'bool', 'default': True, 'group': '行为', 'help': '平面图里画了 AGV 路网时，车辆沿路网最短路行驶（单向边只能顺着走），路网走不通时车停下报警；没画路网就走直线'}}, size=(2, 2), needs_in=False, needs_out=False,
        help='连线属性里"搬运"选这个车队，零件就由车辆在两端之间运送'),
    'submodel': T('子模型', '子模型', 'Grid', '#5b6bd6', ['in'], ['out'], {
        'def': {'label': '子模型定义', 't': 'text', 'default': '', 'group': '行为',
                'help': '模型 submodels 段里的定义编号/名称，或编辑器保存的模板编号（T 开头）。内部可以再套子模型'},
        'values': {'label': '参数值', 't': 'json', 'default': {}, 'group': '行为', 'help': '覆盖子模型暴露的参数，如 {"cycle":"normal(50,2)","mtbf":80}'}},
        size=(8, 6), help='把一段产线封装成一个可复用的块；来料进入定义里的入口块，出口块的产出从本块流出'),
    'cell': T('控制单元', '控制单元', 'Cpu', '#0f8b8d', ['in'], ['out', 'ng'], {
        'cell': {'label': '单元定义', 't': 'json', 'default': {'size': [8, 4], 'components': [], 'io': [], 'plc': {'mode': 'internal', 'scan_ms': 20}},
                 'group': '行为', 'help': '设备级场景：部件（输送机、传感器、执行器、面板）、I/O 表、PLC 设置。用"控制单元编辑器"编辑'},
        'substep_ms': {'label': '仿真子步长', 't': 'num', 'unit': 'ms', 'default': 20, 'group': '行为', 'help': '单元内部运动学和 PLC 扫描的步长'},
        'bypass_s': {'label': '预热旁路时间', 't': 'num', 'unit': 's', 'default': 30, 'group': '节拍',
                     'help': '整厂预热期间不做设备级仿真，零件按这个时间直接穿过单元'},
        'modbus_unit': {'label': 'Modbus 从站', 't': 'int', 'default': 0, 'group': '协议',
                        'help': '>0 时单元 I/O 发布到这个从站：%Ib.n → 线圈 b*8+n，%Qb.n → 线圈 128+b*8+n，%IWn → 保持寄存器 n，%QWn → 256+n'},
        'follow_shifts': {'label': '跟随班次', 't': 'bool', 'default': False, 'group': '行为'},
        **FAIL, 'idle_kw': {'label': '待机功率', 't': 'num', 'unit': 'kW', 'default': 0.5, 'group': '能耗'}},
        size=(8, 4), needs_in=False, needs_out=False,
        help='设备级控制单元：内部有传感器、执行器和零件的真实运动，由内置软 PLC 或外接 PLC 控制；单元入口接上游、单元出口接下游'),
    # ---------------- 高级模型（铸造 + 机加示范线） ----------------
    'induction_furnace': T('中频炉', '高级·铸造', 'HotWater', '#c0392b', [], ['melt'], {
        'capacity_kg': {'label': '容量', 't': 'num', 'unit': 'kg', 'default': 3000, 'group': '行为'},
        'power_kw': {'label': '额定功率', 't': 'num', 'unit': 'kW', 'default': 2000, 'group': '能耗'},
        'heel_kg': {'label': '起熔铁水', 't': 'num', 'unit': 'kg', 'default': 0, 'group': '行为'},
        'modbus_unit': {'label': 'Modbus 从站', 't': 'int', 'default': 3, 'group': '协议'}, **FAIL}, size=(4, 4), legacy=True,
        help='能量平衡模型：加料、熔化、取样光谱、保温出铁；冷却水、炉衬侵蚀'),
    'treatment': T('球化孕育站', '高级·铸造', 'Coffee', '#c0392b', ['melt'], ['ladle'], {
        'ladles': {'label': '浇包数', 't': 'int', 'default': 2, 'group': '行为'}, 'ladle_kg': {'label': '浇包容量', 't': 'num', 'unit': 'kg', 'default': 520, 'group': '行为'},
        'pour_point': {'label': '浇注点', 't': 'json', 'default': [0, 0], 'group': '几何'}, **FAIL}, size=(4, 3), legacy=True,
        help='出铁、球化、浇包调度；镁衰退、温降'),
    'sand_system': T('砂处理系统', '高级·铸造', 'MostlyCloudy', '#a0522d', [], ['sand'], {
        'modbus_unit': {'label': 'Modbus 从站', 't': 'int', 'default': 1, 'group': '协议'}, **FAIL}, size=(10, 6), legacy=True, help='水分 PI 控制、紧实率、湿压强度'),
    'molding_line': T('造型线', '高级·铸造', 'Grid', '#a0522d', ['ladle', 'sand'], ['mold'], {
        'cycle_s': {'label': '造型节拍', 't': 'num', 'unit': 's', 'default': 40, 'group': '节拍'},
        'castings_per_mold': {'label': '每型件数', 't': 'int', 'default': 2, 'group': '行为'},
        'pour_kg': {'label': '每型浇注量', 't': 'num', 'unit': 'kg', 'default': 45, 'group': '行为'},
        'casting_kg': {'label': '铸件重', 't': 'num', 'unit': 'kg', 'default': 18.5, 'group': '行为'},
        'pour_buffer': {'label': '待浇型数上限', 't': 'int', 'default': 8, 'group': '行为'}, **FAIL, **ACT_FAULTS}, size=(26, 4), legacy=True,
        help='造型浇注；按浇注温度、水分、紧实率、残镁、碳当量抽样气孔/缩松/冷隔/球化不良'),
    'cooling_line': T('冷却线', '高级·铸造', 'Sunny', '#a0522d', ['mold'], ['out'], {
        'cool_min': {'label': '冷却时间', 't': 'num', 'unit': 'min', 'default': 45, 'group': '节拍'},
        'capacity_molds': {'label': '容量（型）', 't': 'int', 'default': 80, 'group': '行为'}}, size=(32, 3), legacy=True),
    'shot_blast': T('抛丸机', '高级·铸造', 'Aim', '#8e5b3a', ['in'], ['out'], {
        'batch': {'label': '每批件数', 't': 'int', 'default': 24, 'group': '行为'},
        'modbus_unit': {'label': 'Modbus 从站', 't': 'int', 'default': 2, 'group': '协议'}, **FAIL}, size=(6, 6), legacy=True, help='吊钩批处理；目视检出冷隔、试块判球化'),
    'receiving': T('毛坯来料（高级）', '高级·机加', 'Download', '#2e9d5b', [], ['out'], {
        'pcs_per_hour': {'label': '到货节拍', 't': 'num', 'unit': '件/h', 'default': 34, 'group': '节拍'},
        'porosity_pct': {'label': '来料气孔率', 't': 'num', 'unit': '%', 'default': 3, 'group': '质量'},
        'supplier': {'label': '供应商', 't': 'text', 'default': '外购毛坯', 'group': '行为'}}, size=(6, 6), legacy=True),
    'cnc': T('加工中心（高级）', '高级·机加', 'Cpu', '#2f6fa8', ['in'], ['out'], {
        'group': {'label': '工位组', 't': 'text', 'default': 'CNC', 'group': '行为'}, **FAIL, **ACT_FAULTS}, size=(4, 3.4), legacy=True,
        help='Kienzle 切削力、Taylor 刀具寿命、后刀面磨损、断刀、热伸长与尺寸补偿；umati 风格点位；需要操作工上下料'),
    'deburr_cell': T('机器人去毛刺', '高级·机加', 'MagicStick', '#2f6fa8', ['in'], ['out'], {**FAIL, **ACT_FAULTS}, size=(5, 5), legacy=True),
    'inspection': T('内窥检测（高级）', '高级·机加', 'View', '#7a5af5', ['in'], ['out', 'rework'], {**FAIL}, size=(4, 4), legacy=True,
                    help='检出概率 POD、尺寸估计误差、光源与灵敏度影响漏检误判；毛刺返修一次'),
    'warehouse': T('立体仓库', '高级·机加', 'House', '#2f6fa8', ['in'], [], {
        'slots': {'label': '库位数', 't': 'int', 'default': 600, 'group': '行为'},
        'ship_every_h': {'label': '发运间隔', 't': 'num', 'unit': 'h', 'default': 4, 'group': '行为'}}, size=(12, 18), legacy=True, needs_out=False),
    'agv_fleet': T('AGV 车队（高级）', '高级·机加', 'Van', '#f28c28', [], [], {
        'count': {'label': 'AGV 台数', 't': 'int', 'default': 3, 'group': '行为'}, 'speed': {'label': '速度', 't': 'num', 'unit': 'm/s', 'default': 1.2, 'group': '行为'},
        'corridor_y': {'label': '通道 Y', 't': 'num', 'unit': 'm', 'default': 0, 'group': '几何'},
        'nodes': {'label': '站点', 't': 'json', 'default': {}, 'group': '几何', 'help': '{"raw":[x,y],"cnc_in":[x,y],...}'}}, size=(1, 1), legacy=True,
        needs_in=False, needs_out=False, help='VDA 5050 风格；电量与充电'),
    'worker_crew': T('生产班组（高级）', '高级·人员', 'Avatar', '#e07a20', [], [], {
        'roles': {'label': '岗位', 't': 'json', 'default': [], 'group': '人员', 'help': '[{"name":"CNC 操作工","count":3,"stations":["CNC1","CNC2"]}]'}},
        size=(1, 1), legacy=True, needs_in=False, needs_out=False, help='工人在厂区内走动到需要人的设备旁作业；位置按 UWB 风格发布'),

    # ---------------- 控制层 / 通讯层 / 信息系统（4.3：独立设备，用信号线、网络线连接） ----------------
    'plc': T('PLC', '控制与网络', 'Cpu', '#e07a20', [], [], {
        'model': {'label': '型号', 't': 'enum', 'default': 'generic', 'group': '基本',
                  'options': {'generic': '通用小型 PLC（类 S7-1200）', 'medium': '中型 PLC（类 S7-1500）', 'micro': '微型 PLC（类 FX/Smart）'}},
        'di': {'label': '数字量输入点数', 't': 'int', 'default': 16, 'group': 'I/O'}, 'do': {'label': '数字量输出点数', 't': 'int', 'default': 16, 'group': 'I/O'},
        'ai': {'label': '模拟量输入点数', 't': 'int', 'default': 4, 'group': 'I/O'}, 'ao': {'label': '模拟量输出点数', 't': 'int', 'default': 2, 'group': 'I/O'},
        'scan_ms': {'label': '扫描周期', 't': 'num', 'unit': 'ms', 'default': 20, 'group': '运行'},
        'mode': {'label': '控制方式', 't': 'enum', 'default': 'internal', 'group': '运行', 'options': {'internal': '内置软 PLC', 'external': '外接真实 PLC'}},
        'program': {'label': 'PLC 程序', 't': 'json', 'default': None, 'group': '程序', 'hidden': True},
        'ip': {'label': 'IP 地址', 't': 'text', 'default': '', 'group': '网络'}},
        size=(1.2, 0.6), needs_in=False, needs_out=False, help='可编程控制器：通过信号线读设备的状态和传感器、输出命令控制设备；一台 PLC 可以控制多台设备'),
    'hmi': T('HMI 触摸屏', '控制与网络', 'Monitor', '#e07a20', [], [], {
        'screen': {'label': '画面', 't': 'text', 'default': '', 'group': '基本'}, 'ip': {'label': 'IP 地址', 't': 'text', 'default': '', 'group': '网络'}},
        size=(0.6, 0.4), needs_in=False, needs_out=False, help='操作员触摸屏：显示和操作 PLC 的变量（启动、停止、设定值、报警）'),
    'gateway': T('工业网关', '控制与网络', 'Connection', '#7a5af5', [], [], {
        'south': {'label': '接入协议', 't': 'enum', 'default': 'auto', 'group': '基本', 'options': {'auto': '自动（按接入设备）', 's7': '西门子 S7', 'modbus': 'Modbus TCP', 'opcua': 'OPC UA'}},
        'north': {'label': '上报', 't': 'json', 'default': ['opcua', 'mqtt'], 'group': '基本', 'help': '对外提供的协议：opcua / mqtt / modbus'},
        'ip': {'label': 'IP 地址', 't': 'text', 'default': '', 'group': '网络'}},
        size=(0.8, 0.5), needs_in=False, needs_out=False, help='把现场各种协议的数据采上来，统一转成 OPC UA / MQTT 给 MES、SCADA 用'),
    'switch': T('交换机', '控制与网络', 'Share', '#7a5af5', [], [], {
        'ports': {'label': '端口数', 't': 'int', 'default': 16, 'group': '基本'}},
        size=(0.8, 0.3), needs_in=False, needs_out=False, help='工业以太网交换机：PLC、网关、HMI、服务器都接在它上面'),
    'scada': T('SCADA 监控站', '控制与网络', 'DataBoard', '#2e9d5b', [], [], {
        'ip': {'label': 'IP 地址', 't': 'text', 'default': '', 'group': '网络'}},
        size=(1, 0.8), needs_in=False, needs_out=False, help='中控室的监控电脑：看全厂状态、报警、趋势'),
    'mes': T('MES 系统', '控制与网络', 'Histogram', '#2e9d5b', [], [], {
        'url': {'label': '地址', 't': 'text', 'default': '', 'group': '基本', 'help': '外部 MES 的地址（如蜂元 MES http://127.0.0.1:8900）'}},
        size=(1, 0.8), needs_in=False, needs_out=False, help='制造执行系统：工单、报工、质量、追溯；从网关取数据'),
}

# 分层（看图纸时按颜色区分、可以按层过滤）。process 生产设备、field 传感器执行器（在设备内部）、control 控制层、network 通讯层、it 信息系统
LAYERS = {'process': {'label': '生产设备', 'color': '#3b82c4'}, 'field': {'label': '传感器/执行器', 'color': '#14a3a3'},
          'control': {'label': '控制（PLC/HMI）', 'color': '#e07a20'}, 'network': {'label': '通讯（网关/网络）', 'color': '#7a5af5'},
          'it': {'label': '信息系统（SCADA/MES）', 'color': '#2e9d5b'}}
_LAYER_OF = {'plc': 'control', 'hmi': 'control', 'gateway': 'network', 'switch': 'network', 'scada': 'it', 'mes': 'it'}
for _k, _v in BLOCK_TYPES.items():
    _v['layer'] = _LAYER_OF.get(_k, 'process')
# 连线种类：material 物料流（已有）；signal 信号线（设备 ⇄ PLC，一条线带多路信号）；network 网络线（PLC/网关/交换机/服务器之间）
LINK_KINDS = {'material': {'label': '物料', 'color': '#8b96a1'}, 'signal': {'label': '信号', 'color': '#e07a20'}, 'network': {'label': '网络', 'color': '#7a5af5'}}
# 生产设备的默认控制接口（PLC 通过信号线连接这些点）：in = 设备 → PLC（状态/传感器），out = PLC → 设备（命令/设定）
CONTROL_POINTS = {'in': [{'name': 'Running', 'label': '运行中', 'type': 'BOOL'}, {'name': 'Fault', 'label': '故障', 'type': 'BOOL'},
                         {'name': 'PartIn', 'label': '工件到位', 'type': 'BOOL'}, {'name': 'Count', 'label': '完成计数', 'type': 'INT'}],
                  'out': [{'name': 'Enable', 'label': '允许运行', 'type': 'BOOL'}, {'name': 'Reset', 'label': '故障复位', 'type': 'BOOL'}]}
# 4.3 生产设备的控制接口：类型自有点（与 CONTROL_POINTS 合并）。tag = 对应的设备点位；count / partin = 计数、到位用哪个点位；
# exclude = 不要的默认点；none = 这类设备没有控制接口（人员、PLC/网络设备本身）。实现见 vfactory/control/iface.py
def _cp(name, label, typ='BOOL', tag=None, unit='', help=''):
    d = {'name': name, 'label': label, 'type': typ}
    if tag:
        d['tag'] = tag
    if unit:
        d['unit'] = unit
    if help:
        d['help'] = help
    return d


_CONTROL = {
    'processor': {'out': [_cp('SpeedPct', '速度倍率', 'INT', 'Setpoint/SpeedPct', '%', '30–150')]},
    'source': {'in': [_cp('Waiting', '等待放行件数', 'INT', 'Queue/Waiting', '件')], 'exclude': ['Reset']},
    'buffer': {'in': [_cp('Level', '库存件数', 'INT', 'Queue/Count', '件'), _cp('Full', '已满', 'BOOL')], 'exclude': ['Running', 'Fault', 'Enable', 'Reset'],
               'partin': 'Queue/Count', 'count': 'Queue/Count'},
    'conveyor': {'in': [_cp('OnBelt', '线上件数', 'INT', 'Conveyor/Count', '件')],
                 'out': [_cp('Run', '运行命令', 'BOOL', help='接了这一路时，只有 Run=1 输送带才走'), _cp('Speed', '速度', 'REAL', 'Conveyor/Speed', 'm/s')]},
    'batch': {'in': [_cp('Loaded', '本批已装', 'INT', 'Batch/Loaded', '件')]},
    'sink': {'exclude': ['Running', 'Fault', 'Reset']},
    'storage': {'exclude': ['Running', 'Fault', 'Reset']},
    'cell': {'none': True},                       # 控制单元的控制点就是它的 I/O 表（models/cell.py）
    'induction_furnace': {'in': [_cp('Temp', '铁水温度', 'REAL', 'Bath/Temperature', '℃'), _cp('Weight', '炉内铁水', 'REAL', 'Bath/Weight', 'kg'),
                                 _cp('Power', '实际功率', 'REAL', 'Electrical/Power', 'kW')],
                          'out': [_cp('PowerSP', '功率设定', 'REAL', 'Setpoint/PowerKW', 'kW'), _cp('TapTempSP', '出铁温度设定', 'REAL', 'Setpoint/TapTemp', '℃')],
                          'count': 'Heat/Number', 'partin': 'Bath/Weight'},
    'treatment': {'in': [_cp('LadleTemp', '浇包温度', 'REAL', 'Ladle/Temperature', '℃'), _cp('ResidualMg', '残镁', 'REAL', 'Ladle/ResidualMg', '%')],
                  'out': [_cp('MgAlloySP', '球化剂加入量', 'REAL', 'Setpoint/MgAlloyPct', '%')], 'count': 'Treatment/Count', 'partin': 'Ladle/Weight'},
    'sand_system': {'in': [_cp('Moisture', '型砂水分', 'REAL', 'Sand/Moisture', '%'), _cp('Compactability', '紧实率', 'REAL', 'Sand/Compactability', '%')],
                    'out': [_cp('MoistureSP', '水分设定', 'REAL', 'Setpoint/Moisture', '%')], 'count': [], 'partin': 'Mixer/Running'},
    'molding_line': {'in': [_cp('WaitingMolds', '待浇型数', 'INT', 'Production/WaitingMolds')],
                     'out': [_cp('CycleSP', '造型节拍设定', 'REAL', 'Setpoint/CycleSec', 's')], 'count': 'Production/MoldCount', 'partin': 'Production/WaitingMolds'},
    'cooling_line': {'in': [_cp('Molds', '线上型数', 'INT', 'Line/Molds')], 'count': 'Line/ShakeoutCount', 'partin': 'Line/Molds'},
    'shot_blast': {'out': [_cp('BlastSP', '抛丸时间设定', 'REAL', 'Setpoint/BlastMin', 'min')], 'count': 'Batch/Count'},
    'receiving': {'count': 'Received/Count', 'exclude': ['Reset']},
    'cnc': {'in': [_cp('ProgramNo', '当前程序号', 'INT', help='程序名 O1201 → 1201'), _cp('SpindleLoad', '主轴负载', 'REAL', 'Monitoring/Spindle/Load', '%'),
                   _cp('ToolNo', '当前刀号', 'INT')],
            'out': [_cp('FeedOverride', '进给倍率', 'REAL', 'Monitoring/Feed/Override', '%')], 'count': 'Production/PartsProduced',
            'partin': 'Production/CurrentPart'},
    'deburr_cell': {'out': [_cp('CycleSP', '去毛刺节拍设定', 'REAL', 'Setpoint/CycleSec', 's')], 'count': 'Production/PartsDone', 'partin': 'Production/CurrentPart'},
    'inspection': {'in': [_cp('LastOK', '上一件合格', 'BOOL')], 'count': ['Result/OK', 'Result/NG']},
    'warehouse': {'in': [_cp('Stock', '库存件数', 'INT', 'Stock/Count', '件')], 'count': 'Stock/Count'},
    'agv_fleet': {'in': [_cp('Queue', '待执行任务', 'INT', 'Fleet/Queue')], 'count': 'Fleet/TasksDone', 'partin': 'Fleet/Queue'},
}
for _k in ('operators', 'transporter', 'worker_crew', 'submodel', 'plc', 'hmi', 'gateway', 'switch', 'scada', 'mes'):
    _CONTROL[_k] = {'none': True}
for _k, _v in _CONTROL.items():
    if _k in BLOCK_TYPES:
        BLOCK_TYPES[_k]['control'] = _v
LEGACY_PORTS = {k for k, v in BLOCK_TYPES.items() if v['legacy']}
CATS = ['出入口', '加工', '物流', '质量', '人员', '子模型', '控制单元', '控制与网络', '高级·铸造', '高级·机加', '高级·人员']
ID_PREFIX = {'source': 'SRC', 'processor': 'M', 'batch': 'BAT', 'buffer': 'B', 'conveyor': 'CV', 'inspect': 'QC', 'rework': 'RW', 'assembly': 'ASM', 'split': 'SPL',
             'sink': 'OUT', 'storage': 'WH', 'operators': 'OP', 'transporter': 'TR', 'submodel': 'SUB', 'cell': 'CELL', 'induction_furnace': 'FUR', 'treatment': 'TRT', 'sand_system': 'SAND',
             'molding_line': 'MOLD', 'cooling_line': 'COOL', 'shot_blast': 'SHOT', 'receiving': 'RCV', 'cnc': 'CNC', 'deburr_cell': 'DEB', 'inspection': 'INS',
             'warehouse': 'ASRS', 'agv_fleet': 'AGV', 'worker_crew': 'CREW', 'plc': 'PLC', 'hmi': 'HMI', 'gateway': 'GW', 'switch': 'SW', 'scada': 'SCADA', 'mes': 'MES'}
SIGNAL_HELP = '自定义点位：name 点位名（如 Mold/Temp），unit 单位，desc 说明，expr 公式（如 lag(power*0.8+25, 300) + noise(0.3)）；writable 可写时 expr 只是初值'


def public():
    return {'types': BLOCK_TYPES, 'cats': CATS, 'prefix': ID_PREFIX, 'signal_help': SIGNAL_HELP, 'layers': LAYERS, 'link_kinds': LINK_KINDS, 'control_points': CONTROL_POINTS}
