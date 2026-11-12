"""实体定义：一份定义同时生成数据库表、通用 CRUD 接口和前端列表/表单。

F(字段名, 中文名, 类型, ...)：类型 str/text/int/float/bool/date/datetime/enum/ref/json
E(实体名, 中文名, 模块, 字段..., children=[(子实体, 外键字段)], actions={动作: 中文名}, internal=只读/隐藏)
"""
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa


@dataclass
class F:
    name: str
    label: str
    t: str = 'str'
    ref: str | None = None
    enum: dict | None = None
    req: bool = False
    list: bool = True            # 是否出现在列表
    default: Any = None
    ro: bool = False             # 表单里只读（系统维护）
    auto: str | None = None      # 自动编号格式，如 'WO{d}{n:03}'
    search: bool = False
    unique: bool = False
    hint: str = ''


@dataclass
class E:
    name: str
    label: str
    module: str
    fields: list
    children: list = field(default_factory=list)
    actions: dict = field(default_factory=dict)
    internal: bool = False       # 系统写入、界面只读
    order: str = '-id'
    menu: bool = True


def S(n, l, **k): return F(n, l, 'str', **k)
def T(n, l, **k): return F(n, l, 'text', list=False, **k)
def I(n, l, **k): return F(n, l, 'int', **k)
def N(n, l, **k): return F(n, l, 'float', **k)
def B(n, l, **k): return F(n, l, 'bool', **k)
def D(n, l, **k): return F(n, l, 'date', **k)
def DT(n, l, **k): return F(n, l, 'datetime', **k)
def EN(n, l, enum, **k): return F(n, l, 'enum', enum=enum, **k)
def R(n, l, ref, **k): return F(n, l, 'ref', ref=ref, **k)
def J(n, l, **k): return F(n, l, 'json', list=False, **k)
def CODE(l='编码', auto=None): return F('code', l, 'str', req=auto is None, unique=True, search=True, auto=auto)
def NAME(l='名称'): return F('name', l, 'str', req=True, search=True)


PROCESS_T = {'melting': '熔炼', 'treatment': '球化孕育', 'molding': '造型浇注', 'cooling': '冷却落砂', 'cleaning': '清理抛丸', 'receiving': '来料',
             'machining': '机加工', 'deburr': '去毛刺', 'inspection': '检测', 'storage': '入库', 'other': '其他'}
EQUIP_T = {'furnace': '中频炉', 'treatment': '球化站', 'sand': '砂处理', 'molding': '造型线', 'cooling': '冷却线', 'shotblast': '抛丸机', 'receiving': '收货台',
           'cnc': '加工中心', 'deburr': '去毛刺单元', 'inspection': '检测站', 'warehouse': '立体仓库', 'agv': 'AGV', 'crew': '班组', 'other': '其他'}
ROLES = {'admin': '系统管理员', 'manager': '厂长/经理', 'planner': '计划员', 'leader': '班组长', 'operator': '操作工', 'qc': '质检员', 'maint': '设备员',
         'warehouse': '仓管员', 'engineer': '工艺工程师'}

ENTITIES: list[E] = [
    # ---------------- 主数据 ----------------
    E('plant', '工厂', '主数据', [CODE(), NAME(), S('address', '地址'), S('vf_source', '虚拟工厂来源', list=False, hint='如 http://127.0.0.1:8800|foundry-housing')],
      children=[('workshop', 'plant')]),
    E('workshop', '车间', '主数据', [CODE(), NAME(), R('plant', '工厂', 'plant'),
                                   EN('wtype', '类型', {'foundry': '铸造', 'machining': '机加', 'warehouse': '仓储', 'other': '其他'})],
      children=[('line', 'workshop')]),
    E('line', '产线', '主数据', [CODE(), NAME(), R('workshop', '车间', 'workshop')], children=[('workstation', 'line')]),
    E('process', '工序', '主数据', [CODE(), NAME(), EN('ptype', '类型', PROCESS_T), N('std_cycle_s', '标准节拍 s'), T('desc', '说明')]),
    E('workstation', '工位', '主数据', [CODE(), NAME(), R('line', '产线', 'line'), R('process', '工序', 'process'), R('equipment', '设备', 'equipment'),
                                     S('group', '工位组', hint='同组工位可互相替代，如 CNC')]),
    E('material', '物料', '主数据', [CODE(), NAME(), S('spec', '规格'), S('unit', '单位', default='件'),
                                  EN('mtype', '类型', {'raw': '原材料', 'semi': '半成品', 'fg': '成品', 'aux': '辅料', 'consumable': '易耗品'}),
                                  N('safety_stock', '安全库存'), N('price', '单价 元'), N('weight_kg', '单重 kg')]),
    E('bom', 'BOM', '主数据', [R('product', '产品', 'material', req=True), R('component', '子件', 'material', req=True), N('qty', '用量', req=True),
                             S('unit', '单位'), S('remark', '备注')], order='product'),
    E('route', '工艺路线', '主数据', [CODE(), NAME(), R('product', '产品', 'material'), S('version', '版本', default='V1'),
                                   EN('status', '状态', {'draft': '草稿', 'active': '生效', 'obsolete': '作废'}, default='active')],
      children=[('route_step', 'route')]),
    E('route_step', '工艺步骤', '主数据', [R('route', '工艺路线', 'route', req=True), I('seq', '顺序', req=True), R('process', '工序', 'process', req=True),
                                       S('station_group', '工位组/工位', hint='如 CNC、MOLD1'), N('std_cycle_s', '标准节拍 s'),
                                       B('inspection', '检验点'), EN('report_mode', '报工方式', {'auto': '设备自动', 'manual': '人工', 'scan': '扫码'}, default='auto')],
      order='seq', menu=False),
    E('shift', '班次', '主数据', [CODE(), NAME(), S('start', '开始', hint='HH:MM'), S('end', '结束')]),
    E('team', '班组', '主数据', [CODE(), NAME(), R('shift', '班次', 'shift'), S('leader', '班组长')], children=[('employee', 'team')]),
    E('employee', '员工', '主数据', [CODE('工号'), NAME('姓名'), R('team', '班组', 'team'), S('post', '岗位'), S('phone', '电话'), S('skills', '技能')]),
    E('defect_code', '缺陷代码', '质量管理', [CODE(), NAME(), EN('category', '类别', {'casting': '铸造', 'machining': '机加', 'appearance': '外观', 'other': '其他'}),
                                         EN('severity', '严重度', {'critical': '致命', 'major': '严重', 'minor': '轻微'}), R('process', '责任工序', 'process')]),

    # ---------------- 生产 ----------------
    E('work_order', '生产工单', '生产管理', [
        CODE('工单号', auto='WO{d}{n:03}'), R('product', '产品', 'material', req=True), R('route', '工艺路线', 'route'), I('qty', '计划数量', req=True),
        I('qty_done', '完工', ro=True, default=0), I('qty_scrap', '报废', ro=True, default=0), DT('start_plan', '计划开始'), DT('due', '交期'),
        EN('status', '状态', {'draft': '草稿', 'released': '已下达', 'in_progress': '生产中', 'completed': '已完工', 'closed': '已关闭', 'cancelled': '已取消'},
           default='draft', ro=True),
        I('priority', '优先级', default=5, hint='1 最高'), S('customer', '客户'), S('remark', '备注', list=False),
        DT('released_at', '下达时间', ro=True, list=False), DT('completed_at', '完工时间', ro=True, list=False)],
      children=[('wo_op', 'work_order'), ('report', 'work_order'), ('material_issue', 'work_order')],
      actions={'release': '下达', 'close': '关闭', 'cancel': '取消'}),
    E('wo_op', '工单工序', '生产管理', [
        R('work_order', '工单', 'work_order', req=True), I('seq', '顺序'), R('process', '工序', 'process'), S('station_group', '工位组'),
        I('qty_plan', '计划'), I('qty_good', '合格', default=0), I('qty_ng', '不良', default=0), DT('plan_start', '计划开始'), DT('plan_end', '计划结束'),
        DT('act_start', '实际开始'), DT('act_end', '实际结束'),
        EN('status', '状态', {'waiting': '待开工', 'ready': '可开工', 'running': '进行中', 'done': '完成'}, default='waiting'),
        R('assignee', '派工给', 'employee')], order='seq', menu=False, actions={'dispatch': '派工'}),
    E('report', '报工记录', '生产管理', [
        CODE('报工单号', auto='BG{d}{n:04}'), R('work_order', '工单', 'work_order'), R('wo_op', '工序', 'wo_op', list=False), R('process', '工序', 'process'),
        R('employee', '报工人', 'employee'), R('equipment', '设备', 'equipment'), I('qty_good', '合格'), I('qty_ng', '不良'), R('defect', '缺陷', 'defect_code'),
        DT('start', '开始'), DT('end', '结束'), EN('source', '来源', {'auto': '设备自动', 'manual': '人工', 'mobile': '手机扫码'}, default='manual'),
        S('remark', '备注', list=False)]),
    E('material_issue', '领料退料', '生产管理', [
        CODE('单号', auto='LL{d}{n:03}'), EN('kind', '类型', {'issue': '领料', 'return': '退料'}, default='issue'), R('work_order', '工单', 'work_order'),
        R('material', '物料', 'material', req=True), N('qty', '数量', req=True), R('warehouse', '仓库', 'warehouse'), S('lot', '批次'),
        R('employee', '经办人', 'employee'), DT('time', '时间')]),
    E('part', '在制品/一件一码', '生产管理', [
        S('sn', '零件码', search=True, unique=True), R('product', '产品', 'material'), R('work_order', '工单', 'work_order'),
        EN('status', '状态', {'wip': '在制', 'good': '检验合格', 'fg': '成品入库', 'shipped': '已发运', 'scrap': '报废', 'raw_store': '毛坯库', 'rework': '返修中', 'hold': '冻结'}),
        S('station', '当前位置'), S('heat', '炉次/批次', search=True), S('ladle', '浇包', list=False), S('mold', '砂型', list=False), I('cavity', '型腔', list=False),
        N('pour_temp', '浇注温度'), N('mg', '残镁 %', list=False), N('sand_moisture', '型砂水分 %', list=False), N('compactability', '紧实率', list=False),
        N('ce', '碳当量', list=False), S('machine', '加工机床'), I('rework_count', '返修次数', default=0), S('scrap_cause', '报废原因'),
        DT('born_at', '投产时间'), DT('finished_at', '完成时间', list=False)], internal=True, order='-id'),
    E('part_event', '零件事件', '生产管理', [S('sn', '零件码', search=True), DT('t', '时间'), S('station', '工位'), S('event', '事件'), J('data', '数据')],
      internal=True, menu=False),
    E('shipment', '发运记录', '仓储物流', [CODE('发运单', auto='FY{d}{n:03}'), I('qty', '数量'), S('customer', '客户'), R('work_order', '工单', 'work_order'),
                                       DT('time', '时间')], internal=True),

    # ---------------- 质量 ----------------
    E('insp_template', '检验模板', '质量管理', [CODE(), NAME(), EN('itype', '检验类型', {'IQC': '来料检验', 'IPQC': '过程检验', 'FAI': '首件检验', 'OQC': '出货检验', 'patrol': '巡检'}),
                                           R('material', '物料', 'material'), R('process', '工序', 'process'), S('sample_rule', '抽样规则')],
      children=[('insp_item', 'template')]),
    E('insp_item', '检验项目', '质量管理', [R('template', '模板', 'insp_template', req=True), I('seq', '顺序'), NAME('项目'), S('char', '特性代码', hint='SPC 用，如 BORE_DIA'),
                                       S('method', '方法/量具'), S('std', '标准'), N('lo', '下限'), N('hi', '上限'), S('unit', '单位'), B('key', '关键特性')],
      order='seq', menu=False),
    E('insp_record', '检验记录', '质量管理', [
        CODE('检验单号', auto='JY{d}{n:04}'), R('template', '模板', 'insp_template'), EN('itype', '类型', {'IQC': '来料', 'IPQC': '过程', 'FAI': '首件', 'OQC': '出货', 'patrol': '巡检'}),
        R('work_order', '工单', 'work_order'), S('sn', '零件码', search=True), S('lot', '批次'), S('station', '工位'), I('qty_sample', '样本数', default=1),
        I('qty_ng', '不合格数', default=0), EN('result', '结论', {'OK': '合格', 'NG': '不合格', 'pending': '待判'}, default='pending'),
        R('inspector', '检验员', 'employee'), DT('time', '时间'), EN('source', '来源', {'auto': '设备自动', 'manual': '人工', 'import': '导入'}, default='manual'),
        S('remark', '备注', list=False)], children=[('insp_value', 'record')]),
    E('insp_value', '检验值', '质量管理', [R('record', '检验单', 'insp_record', req=True), R('item', '项目', 'insp_item'), S('char', '特性代码'),
                                       N('value', '测量值'), S('text', '文字结果'), B('ok', '合格')], internal=True, menu=False),
    E('ncr', '不合格品', '质量管理', [
        CODE('NCR 号', auto='NCR{d}{n:03}'), S('sn', '零件码', search=True), S('lot', '批次'), R('work_order', '工单', 'work_order'), R('material', '物料', 'material'),
        I('qty', '数量', default=1), R('defect', '缺陷', 'defect_code'), S('station', '发现工位'), DT('found_at', '发现时间'), S('found_by', '发现人'),
        EN('source', '来源', {'auto': '设备自动', 'manual': '人工'}, default='manual'),
        EN('disposition', '处置', {'pending': '待处置', 'rework': '返修', 'scrap': '报废', 'concession': '让步接收', 'return': '退供应商'}, default='pending'),
        EN('status', '状态', {'open': '待处理', 'reviewing': '评审中', 'closed': '已关闭'}, default='open'), T('root_cause', '原因分析'), T('action', '纠正措施'),
        DT('closed_at', '关闭时间', list=False)],
      children=[('rework', 'ncr')], actions={'rework': '返修', 'scrap': '报废', 'concession': '让步接收', 'close': '关闭', 'to8d': '发起 8D'}),
    E('rework', '返修记录', '质量管理', [CODE('单号', auto='FX{d}{n:03}'), R('ncr', 'NCR', 'ncr'), S('sn', '零件码', search=True), S('station', '返修工位'),
                                     R('employee', '返修人', 'employee'), EN('result', '结果', {'ok': '合格', 'fail': '仍不合格', 'doing': '进行中'}), DT('time', '时间'),
                                     S('remark', '备注')]),
    E('report_8d', '8D 报告', '质量管理', [
        CODE('编号', auto='8D{d}{n:02}'), S('title', '标题', req=True), R('ncr', 'NCR', 'ncr'), R('defect', '缺陷', 'defect_code'),
        T('d1', 'D1 团队'), T('d2', 'D2 问题描述'), T('d3', 'D3 临时措施'), T('d4', 'D4 根本原因'), T('d5', 'D5 永久措施'), T('d6', 'D6 验证'),
        T('d7', 'D7 预防再发'), T('d8', 'D8 总结'), EN('status', '状态', {'draft': '草稿', 'review': '评审', 'closed': '关闭'}, default='draft')]),

    # ---------------- 设备 ----------------
    E('equipment', '设备台账', '设备管理', [
        CODE('设备编号'), NAME('设备名称'), EN('etype', '类型', EQUIP_T), R('line', '产线', 'line'), S('model', '型号'), S('vendor', '厂家'),
        D('install_date', '投用日期', list=False), N('rated_kw', '额定功率 kW', list=False), N('ideal_cycle_s', '理想节拍 s'),
        EN('status', '状态', {'running': '运行', 'idle': '待机', 'setup': '换型', 'down': '停机', 'offline': '离线', 'scrapped': '报废'}, ro=True),
        S('source', '数据来源', list=False, hint='数据源编码:设备号，如 VF:CNC1'), S('location', '位置', list=False)],
      children=[('tag_point', 'equipment'), ('maint_plan', 'equipment'), ('repair_order', 'equipment'), ('tool', 'equipment')]),
    E('datasource', '数据源', '系统', [CODE(), NAME(), EN('protocol', '协议', {'mqtt': 'MQTT (UNS)', 'opcua': 'OPC UA', 'modbus': 'Modbus TCP'}),
                                    S('endpoint', '地址', hint='mqtt://host:1883 / opc.tcp://host:4840/… / host:5020'), S('prefix', '主题/节点前缀'),
                                    B('enabled', '启用', default=True), S('status', '运行状态', ro=True), S('remark', '备注', list=False)],
      children=[('tag_point', 'datasource')], actions={'import_vf': '从虚拟工厂导入', 'restart': '重连'}),
    E('tag_point', '采集点', '系统', [R('equipment', '设备', 'equipment'), R('datasource', '数据源', 'datasource'), S('name', '点位', search=True),
                                   S('address', '地址', hint='MQTT 主题 / OPC UA NodeId / Modbus unit:table:addr'), S('dtype', '类型'), S('unit', '单位'),
                                   N('scale', '缩放', list=False),
                                   EN('role', '用途', {'state': '运行状态', 'alarm': '报警', 'power': '功率', 'energy': '电能', 'count': '产量', 'load': '主轴负载',
                                                     'temp': '温度', 'quality': '质量值', 'other': '其他'}),
                                   S('desc', '说明'), B('enabled', '启用', default=True)], menu=False),
    E('equip_state', '设备状态记录', '设备管理', [R('equipment', '设备', 'equipment'), S('state', '状态'), DT('start', '开始'), DT('end', '结束'), N('dur_s', '时长 s'),
                                             S('reason', '原因')], internal=True, menu=False),
    E('alarm', '报警记录', '设备管理', [R('equipment', '设备', 'equipment'), S('msg', '报警内容', search=True), DT('start', '开始'), DT('end', '结束'), N('dur_s', '时长 s'),
                                     S('ack_by', '确认人'), DT('ack_at', '确认时间', list=False), S('note', '处理说明')], actions={'ack': '确认'}),
    E('maint_plan', '点检保养计划', '设备管理', [CODE(), NAME(), R('equipment', '设备', 'equipment'), EN('mtype', '类型', {'spot': '日常点检', 'maint': '定期保养', 'lube': '润滑'}),
                                             I('cycle_days', '周期 天', default=1), T('items', '内容'), D('last_done', '上次完成'), D('next_due', '下次到期'),
                                             R('owner', '负责人', 'employee')], children=[('maint_record', 'plan')], actions={'execute': '执行'}),
    E('maint_record', '点检保养记录', '设备管理', [CODE('单号', auto='DJ{d}{n:03}'), R('plan', '计划', 'maint_plan'), R('equipment', '设备', 'equipment'),
                                               R('executor', '执行人', 'employee'), DT('time', '时间'), EN('result', '结果', {'ok': '正常', 'abnormal': '异常'}), S('notes', '说明')]),
    E('repair_order', '维修工单', '设备管理', [
        CODE('维修单号', auto='WX{d}{n:03}'), R('equipment', '设备', 'equipment', req=True), S('fault', '故障描述', req=True), S('reported_by', '报修人'),
        DT('reported_at', '报修时间'), EN('level', '紧急程度', {'urgent': '紧急', 'normal': '一般'}, default='normal'),
        EN('status', '状态', {'reported': '已报修', 'assigned': '已派工', 'repairing': '维修中', 'done': '已修复', 'verified': '已验收'}, default='reported', ro=True),
        R('assignee', '维修人', 'employee'), DT('start', '开始维修', list=False), DT('end', '修复时间', list=False), N('downtime_min', '停机 min'),
        T('cause', '故障原因'), T('solution', '处理方法'), S('parts_used', '更换备件', list=False)],
      actions={'assign': '派工', 'start': '开始维修', 'finish': '修复完成', 'verify': '验收'}),

    # ---------------- 仓储 ----------------
    E('warehouse', '仓库', '仓储物流', [CODE(), NAME(), EN('wtype', '类型', {'raw': '原材料库', 'blank': '毛坯库', 'wip': '线边库', 'fg': '成品库', 'aux': '辅料库'})],
      children=[('location', 'warehouse'), ('stock', 'warehouse')]),
    E('location', '库位', '仓储物流', [CODE(), NAME(), R('warehouse', '仓库', 'warehouse'), I('capacity', '容量')], menu=False),
    E('stock', '库存', '仓储物流', [R('material', '物料', 'material'), R('warehouse', '仓库', 'warehouse'), R('location', '库位', 'location'), S('lot', '批次'),
                                  N('qty', '数量'), DT('updated_at', '更新时间')], internal=True),
    E('stock_txn', '出入库记录', '仓储物流', [
        CODE('单号', auto='CK{d}{n:04}'), EN('ttype', '类型', {'in': '入库', 'out': '出库', 'transfer': '移库', 'adjust': '盘点调整'}),
        R('material', '物料', 'material', req=True), N('qty', '数量', req=True), R('warehouse', '仓库', 'warehouse', req=True), R('location', '库位', 'location', list=False),
        R('to_warehouse', '调入仓库', 'warehouse', list=False), S('lot', '批次'), S('ref_doc', '关联单据'), S('employee', '经办'), DT('time', '时间'), S('reason', '原因')]),
    E('agv_task', 'AGV 任务', '仓储物流', [S('agv', 'AGV'), S('task', '任务'), S('src', '起点'), S('dst', '终点'), I('load', '件数'), DT('start', '开始'), DT('end', '结束'),
                                       S('state', '状态')], internal=True),

    # ---------------- 能源 ----------------
    E('energy_hour', '小时电耗', '能源管理', [R('equipment', '设备', 'equipment'), S('area', '区域'), DT('hour', '小时'), N('kwh', '电量 kWh')], internal=True, menu=False),

    # ---------------- 铸造 ----------------
    E('heat', '炉次记录', '铸造', [
        CODE('炉次号'), R('furnace', '电炉', 'equipment'), DT('start', '开始'), DT('end', '结束'), N('kg', '出铁量 kg'), N('kwh', '电耗 kWh'), N('kwh_per_t', '吨耗 kWh/t'),
        N('C', 'C %'), N('Si', 'Si %'), N('Mn', 'Mn %', list=False), N('S', 'S %', list=False), N('P', 'P %', list=False), N('CE', '碳当量'), N('tap_temp', '出铁温度'),
        N('lining', '炉衬余厚 mm', list=False), I('castings', '铸件数', ro=True, default=0), I('scrap', '报废数', ro=True, default=0),
        EN('status', '状态', {'melting': '熔炼中', 'holding': '保温出铁', 'done': '结束'})], children=[('treatment_rec', 'heat_code')], internal=True),
    E('treatment_rec', '球化记录', '铸造', [S('ladle', '浇包'), S('heat_code', '炉次'), N('temp', '温度 °C'), N('mg', '残镁 %'), N('kg', '铁水 kg'), DT('time', '时间')],
      internal=True),
    E('charge_material', '炉料', '铸造', [CODE(), NAME(), N('price', '价格 元/t', req=True), N('C', 'C %'), N('Si', 'Si %'), N('Mn', 'Mn %'), N('S', 'S %'), N('P', 'P %'),
                                       N('min_ratio', '最小配比 %'), N('max_ratio', '最大配比 %'), N('stock_t', '库存 t'), N('yield_pct', '收得率 %', default=95)]),

    # ---------------- 机加 ----------------
    E('nc_program', 'NC 程序', '机加', [CODE('程序号'), NAME(), R('product', '产品', 'material'), S('station_group', '适用机床/组'), S('version', '版本', default='V1'),
                                     EN('status', '状态', {'draft': '编制', 'approved': '已审核', 'released': '已下发', 'obsolete': '作废'}, default='draft', ro=True),
                                     T('content', '程序内容'), S('approved_by', '审核人', ro=True), DT('released_at', '下发时间', ro=True), S('remark', '变更说明')],
      actions={'approve': '审核通过', 'release': '下发到机床', 'obsolete': '作废'}),
    E('tool', '刀具台账', '机加', [S('code', '刀位', req=True, search=True), NAME('刀具'), R('equipment', '机床', 'equipment'), S('ttype', '类型'), I('life_limit', '寿命 件'), I('used', '已用 件', ro=True),
                                I('changes', '换刀次数', ro=True, default=0), DT('last_change', '上次换刀', ro=True),
                                EN('status', '状态', {'ok': '正常', 'warn': '预警', 'change': '待换刀'}, ro=True, default='ok')], actions={'change': '换刀'}),
    E('tool_change', '换刀记录', '机加', [R('equipment', '机床', 'equipment'), S('tool', '刀位'), S('tool_name', '刀具'), I('used', '使用件数'),
                                       EN('reason', '原因', {'life': '到寿命', 'broken': '断刀', 'manual': '人工'}), DT('time', '时间')], internal=True),

    # ---------------- 安灯 / 物料申请 ----------------
    E('andon', '安灯', '生产管理', [
        CODE('安灯号', auto='AD{d}{n:03}'), EN('atype', '类型', {'equipment': '设备', 'quality': '质量', 'material': '物料', 'safety': '安全', 'other': '其他'}, default='equipment'),
        R('equipment', '设备', 'equipment'), S('station', '工位'), S('description', '问题描述', req=True), S('raised_by', '发起人'), DT('raised_at', '发起时间'),
        EN('status', '状态', {'open': '待响应', 'responding': '处理中', 'closed': '已关闭'}, default='open', ro=True), S('responder', '响应人'),
        DT('response_at', '响应时间', list=False), DT('closed_at', '关闭时间', list=False), S('close_note', '处理结果', list=False),
        EN('source', '来源', {'manual': '人工', 'auto': '设备自动'}, default='manual')],
      actions={'respond': '响应', 'close': '关闭'}),
    E('material_request', '物料申请', '生产管理', [
        CODE('申请单号', auto='WL{d}{n:03}'), R('material', '物料', 'material', req=True), N('qty', '数量', req=True), R('warehouse', '发料仓库', 'warehouse'),
        R('work_order', '工单', 'work_order'), S('reason', '原因'), S('requested_by', '申请人'), DT('requested_at', '申请时间'),
        EN('status', '状态', {'submitted': '已提交', 'issued': '已发料', 'rejected': '已退回'}, default='submitted', ro=True)],
      actions={'issue': '发料', 'reject': '退回'}),

    # ---------------- 系统 ----------------
    E('sys_user', '用户', '系统', [S('username', '账号', req=True, unique=True, search=True), S('name', '姓名'), S('roles', '角色', hint='逗号分隔：' + ','.join(ROLES)),
                                 R('employee', '员工', 'employee'), B('active', '启用', default=True), S('password_hash', '密码', list=False, ro=True)]),
    E('setting', '系统参数', '系统', [S('key', '参数', req=True, unique=True), S('value', '值'), S('remark', '说明')], menu=False),
]

BY_NAME = {e.name: e for e in ENTITIES}
COLTYPE = {'str': sa.String(200), 'text': sa.Text, 'int': sa.Integer, 'float': sa.Float, 'bool': sa.Boolean, 'date': sa.Date, 'datetime': sa.DateTime,
           'enum': sa.String(40), 'ref': sa.Integer, 'json': sa.JSON}
# 非 int 外键：按字段名特判
STR_REF = set()

metadata = sa.MetaData()
TABLES: dict[str, sa.Table] = {}
for e in ENTITIES:
    cols = [sa.Column('id', sa.Integer, primary_key=True, autoincrement=True)]
    for f in e.fields:
        cols.append(sa.Column(f.name, COLTYPE[f.t], unique=f.unique, index=f.unique or f.t == 'ref' or f.search or f.name in ('sn', 't', 'time', 'hour', 'start')))
    names = {f.name for f in e.fields}
    cols += [sa.Column(n, sa.DateTime) for n in ('created_at', 'updated_at') if n not in names]
    TABLES[e.name] = sa.Table(e.name, metadata, *cols)

# 设备点位最新值（采集写，界面读）
tag_latest = sa.Table('tag_latest', metadata, sa.Column('key', sa.String(300), primary_key=True), sa.Column('equipment', sa.Integer, index=True),
                      sa.Column('name', sa.String(200)), sa.Column('value', sa.String(200)), sa.Column('num', sa.Float), sa.Column('ts', sa.DateTime))
# 少量时序（主轴负载、温度等）用于趋势
tag_sample = sa.Table('tag_sample', metadata, sa.Column('id', sa.Integer, primary_key=True), sa.Column('equipment', sa.Integer, index=True),
                      sa.Column('name', sa.String(200), index=True), sa.Column('ts', sa.DateTime, index=True), sa.Column('num', sa.Float))


def spec_json():
    out = []
    for e in ENTITIES:
        out.append({'name': e.name, 'label': e.label, 'module': e.module, 'internal': e.internal, 'menu': e.menu, 'children': e.children,
                    'actions': e.actions,
                    'fields': [{k: v for k, v in f.__dict__.items() if v not in (None, '', False) or k in ('list',)} for f in e.fields]})
    return out
