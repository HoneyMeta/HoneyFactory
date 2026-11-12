"""初始化：示范工厂（某转向器壳体铸造厂）的基础主数据——工序、物料、BOM、工艺路线、班组员工、缺陷代码、检验模板、仓库、炉料；
本机学员账号见 edu.seed。没有演示工单（学员自己下达）。可重复执行（已存在的跳过）。"""
from datetime import timedelta

from . import db
from .db import clock
from .i18n import _tr, default_lang, en_text


def _row(row):
    """Seed data in the server language (VF_LANG): English values from vfactory/locale/data-en.json / en.json."""
    if default_lang() != 'en':
        return row
    return {k: (en_text(v) if isinstance(v, str) else v) for k, v in row.items()}


def _ins(c, entity, row, **kw):
    return db.insert(c, entity, _row(row), **kw)


def ensure(c, entity, key, row):
    r = db.get(c, entity, **{key: row[key]})
    if r:
        return r['id']
    return _ins(c, entity, row, raw=True)


def base(c):
    p = ensure(c, 'plant', 'code', {'code': 'GR', 'name': '某转向器壳体铸造厂', 'address': '示例厂区', 'vf_source': 'http://127.0.0.1:8800|foundry-housing'})
    procs = [('P05', '来料收货', 'receiving', 106), ('P10', '熔炼', 'melting', 20), ('P20', '球化孕育', 'treatment', 20), ('P30', '造型浇注', 'molding', 20),
             ('P40', '冷却落砂', 'cooling', 20), ('P50', '清理抛丸', 'cleaning', 25), ('P60', 'CNC 机加', 'machining', 430), ('P70', '去毛刺', 'deburr', 65),
             ('P80', '内窥检测', 'inspection', 60), ('P90', '成品入库', 'storage', 10)]
    pid = {}
    for code, name, t, ct in procs:
        pid[code] = ensure(c, 'process', 'code', {'code': code, 'name': name, 'ptype': t, 'std_cycle_s': ct})
    mats = [('SGH-450', 'SGH-450 转向器壳体', 'QT450-10 精加工', 'fg', 200, 380, 15.2), ('SGH-450-B', 'SGH-450 壳体毛坯', 'QT450-10 铸件', 'semi', 300, 160, 18.5),
            ('CM-PIG', 'Z14 生铁', '炉料', 'raw', 30, 3300, None), ('CM-STEEL', '废钢', '炉料', 'raw', 20, 2600, None), ('CM-RET', '回炉料', '浇冒口/废件', 'raw', 0, 1800, None),
            ('CM-CARB', '增碳剂', 'C≥95%', 'aux', 1, 4500, None), ('CM-FESI', '75 硅铁', 'Si 75%', 'aux', 1, 7500, None),
            ('AUX-NODU', '球化剂 FeSiMg6', 'Mg 6%', 'aux', 2, 12500, None), ('AUX-INOC', '孕育剂 FeSi75-Ba', '', 'aux', 1, 9800, None),
            ('AUX-SAND', '型砂', '膨润土湿型砂', 'aux', 50, 380, None), ('AUX-SHOT', '钢丸 S330', '', 'consumable', 2, 6200, None)]
    mid = {}
    for code, name, spec, t, ss, price, w in mats:
        mid[code] = ensure(c, 'material', 'code', {'code': code, 'name': name, 'spec': spec, 'unit': '件' if t in ('fg', 'semi') else 't', 'mtype': t,
                                                    'safety_stock': ss, 'price': price, 'weight_kg': w})
    if not db.get(c, 'bom', product=mid['SGH-450']):
        for comp, q in (('SGH-450-B', 1), ('AUX-SHOT', 0.0004)):
            _ins(c, 'bom', {'product': mid['SGH-450'], 'component': mid[comp], 'qty': q, 'unit': '件' if comp == 'SGH-450-B' else 't'}, raw=True)
        for comp, q in (('CM-PIG', 0.0095), ('CM-STEEL', 0.0053), ('CM-RET', 0.0059), ('AUX-NODU', 0.0003), ('AUX-SAND', 0.012)):
            _ins(c, 'bom', {'product': mid['SGH-450-B'], 'component': mid[comp], 'qty': q, 'unit': 't'}, raw=True)
    rid = ensure(c, 'route', 'code', {'code': 'RT-SGH450', 'name': 'SGH-450 铸造+机加一体', 'product': mid['SGH-450'], 'version': 'V3', 'status': 'active'})
    if not db.rows(c, 'route_step', route=rid):
        for seq, pc, grp, ct, insp, mode in ((10, 'P10', 'FUR', 20, False, 'auto'), (20, 'P20', 'TRT1', 20, False, 'auto'), (30, 'P30', 'MOLD1', 20, False, 'auto'),
                                             (40, 'P40', 'COOL1', 20, False, 'auto'), (50, 'P50', 'SHOT1', 25, True, 'auto'), (60, 'P60', 'CNC', 430, False, 'auto'),
                                             (70, 'P70', 'DEB1', 65, False, 'auto'), (80, 'P80', 'INS1', 60, True, 'auto'), (90, 'P90', 'ASRS1', 10, False, 'auto')):
            _ins(c, 'route_step', {'route': rid, 'seq': seq, 'process': pid[pc], 'station_group': grp, 'std_cycle_s': ct, 'inspection': insp, 'report_mode': mode}, raw=True)
    # 班次班组员工
    sh = {}
    for code, name, s, e in (('A', '早班', '07:00', '15:00'), ('B', '中班', '15:00', '23:00'), ('C', '夜班', '23:00', '07:00')):
        sh[code] = ensure(c, 'shift', 'code', {'code': code, 'name': name, 'start': s, 'end': e})
    teams = {}
    for code, name, s, leader in (('T1', '甲班', 'A', '张强'), ('T2', '乙班', 'B', '刘洋'), ('T3', '丙班', 'C', '陈刚')):
        teams[code] = ensure(c, 'team', 'code', {'code': code, 'name': name, 'shift': sh[s], 'leader': leader})
    emps = [('E001', '张强', 'T1', '班长'), ('E002', '王建国', 'T1', '炉前工'), ('E003', '李伟', 'T1', '球化浇包工'), ('E004', '马超', 'T1', '浇注工'),
            ('E005', '何军', 'T1', '抛丸挂件工'), ('E006', '赵磊', 'T1', 'CNC 操作工'), ('E007', '钱明', 'T1', 'CNC 操作工'), ('E008', '孙涛', 'T1', 'CNC 操作工'),
            ('E009', '冯杰', 'T1', '去毛刺/返修工'), ('E010', '吴芳', 'T1', '仓管员'), ('E011', '孙敏', 'T1', '质检员'), ('E012', '周涛', 'T1', '设备员'),
            ('E013', '郑凯', 'T1', '工艺工程师'), ('E014', '李娜', 'T1', '计划员'), ('E015', '刘洋', 'T2', '班长'), ('E016', '陈刚', 'T3', '班长')]
    for code, name, t, post in emps:
        ensure(c, 'employee', 'code', {'code': code, 'name': name, 'team': teams[t], 'post': post})
    # 缺陷代码
    P = pid
    for code, name, cat, sev, pc in (('D01', '气孔', 'casting', 'major', 'P30'), ('D02', '缩松', 'casting', 'major', 'P20'), ('D03', '冷隔/开裂', 'casting', 'critical', 'P30'),
                                     ('D04', '球化不良', 'casting', 'critical', 'P20'), ('D05', '内腔气孔/缩松', 'casting', 'major', 'P30'),
                                     ('D06', '残余毛刺', 'machining', 'minor', 'P70'), ('D07', '缸孔尺寸超差', 'machining', 'major', 'P60'), ('D08', '断刀报废', 'machining', 'major', 'P60'),
                                     ('D09', '毛刺返修后仍不合格', 'machining', 'major', 'P70'), ('D10', '误报/待复判', 'other', 'minor', 'P80')):
        ensure(c, 'defect_code', 'code', {'code': code, 'name': name, 'category': cat, 'severity': sev, 'process': P[pc]})
    # 检验模板
    tpls = [('T-BORE', 'CNC 在线测量（缸孔）', 'IPQC', 'SGH-450', 'P60', '100% 测头', [(10, '缸孔直径', 'BORE_DIA', '测头', 'Φ40 +0.025/0', 40.000, 40.025, 'mm', True)]),
            ('T-ENDO', '内窥检测（油道交叉孔）', 'IPQC', 'SGH-450', 'P80', '100% 自动', [(10, '交叉孔毛刺', 'ENDO_BURR', '自动内窥', '残余毛刺 ≤0.1 mm', None, 0.1, 'mm', True),
                                                                                    (20, '内腔气孔/缩松', 'ENDO_PORE', '自动内窥', '≤0.8 mm', None, 0.8, 'mm', True)]),
            ('T-SPEC', '炉前光谱（原铁水）', 'IPQC', None, 'P10', '每炉', [(10, '碳 C', 'C', '光谱仪', '3.60–3.80', 3.60, 3.80, '%', True), (20, '硅 Si', 'Si', '光谱仪', '1.40–1.70', 1.40, 1.70, '%', True),
                                                                      (30, '锰 Mn', 'Mn', '光谱仪', '≤0.40', None, 0.40, '%', False), (40, '硫 S', 'S', '光谱仪', '≤0.020', None, 0.020, '%', True),
                                                                      (50, '碳当量 CE', 'CE', '计算', '4.15–4.45', 4.15, 4.45, '', True)]),
            ('T-NODU', '球化检验（试块）', 'IPQC', 'SGH-450-B', 'P20', '每包', [(10, '残余镁', 'MG', '光谱', '0.030–0.055', 0.030, 0.055, '%', True), (20, '球化率', 'NODU', '金相', '≥85%', 85, None, '%', True)]),
            ('T-FAI', '首件检验', 'FAI', 'SGH-450', 'P60', '每班首件 / 换刀后', [(10, '缸孔直径', 'BORE_DIA', '三坐标', 'Φ40 +0.025/0', 40.000, 40.025, 'mm', True),
                                                                           (20, '端面平面度', 'FLAT', '三坐标', '≤0.03', None, 0.03, 'mm', True), (30, '油道孔位置度', 'POS_OIL', '三坐标', '≤0.1', None, 0.1, 'mm', True),
                                                                           (40, '螺纹 M10', 'THREAD', '通止规', '通规通、止规止', None, None, '', False)]),
            ('T-IQC', '炉料来料检验', 'IQC', 'CM-PIG', None, '每批', [(10, '碳', 'IQC_C', '光谱', '≥4.0', 4.0, None, '%', False), (20, '硫', 'IQC_S', '光谱', '≤0.04', None, 0.04, '%', True)]),
            ('T-OQC', '出货检验', 'OQC', 'SGH-450', 'P90', 'GB/T 2828.1 一般Ⅱ AQL 0.65', [(10, '外观', 'OQC_APP', '目视', '无磕碰锈蚀', None, None, '', False),
                                                                                    (20, '包装标识', 'OQC_PKG', '目视', '零件码清晰可扫', None, None, '', False)])]
    for code, name, it, mat, pc, rule, items in tpls:
        if db.get(c, 'insp_template', code=code):
            continue
        tid = _ins(c, 'insp_template', {'code': code, 'name': name, 'itype': it, 'material': mid.get(mat), 'process': P.get(pc), 'sample_rule': rule}, raw=True)
        for seq, iname, ch, method, std, lo, hi, unit, key in items:
            _ins(c, 'insp_item', {'template': tid, 'seq': seq, 'name': iname, 'char': ch, 'method': method, 'std': std, 'lo': lo, 'hi': hi, 'unit': unit, 'key': key}, raw=True)
    # 仓库与库存
    whs = {}
    for code, name, t in (('W-RAW', '原材料库', 'raw'), ('W-BLANK', '毛坯库', 'blank'), ('W-LINE', '机加线边库', 'wip'), ('W-FG', '成品立体仓库', 'fg'), ('W-AUX', '辅料库', 'aux')):
        whs[t] = ensure(c, 'warehouse', 'code', {'code': code, 'name': name, 'wtype': t})
        for i in range(1, 4):
            ensure(c, 'location', 'code', {'code': f'{code}-{i:02d}', 'name': _tr('{name} {i} 区', name=en_text(name) if default_lang() == 'en' else name, i=i), 'warehouse': whs[t], 'capacity': 200})
    # 炉料：价格 元/t，成分 %（炉次结束按常规配比倒冲，见 services/foundry.py）
    for code, name, price, C, Si, Mn, S, Pp, lo, hi, stock in (('CM-PIG', 'Z14 生铁', 3300, 4.2, 1.4, 0.30, 0.030, 0.060, 20, 70, 180),
                                                             ('CM-STEEL', '废钢', 2600, 0.20, 0.30, 0.50, 0.020, 0.020, 0, 45, 120),
                                                             ('CM-RET', '回炉料', 1800, 3.60, 2.40, 0.30, 0.012, 0.030, 15, 40, 60),
                                                             ('CM-CARB', '增碳剂', 4500, 95, 0, 0, 0.05, 0, 0, 3, 8),
                                                             ('CM-FESI', '75 硅铁', 7500, 0.1, 75, 0.4, 0.02, 0.04, 0, 2, 5)):
        if not db.get(c, 'charge_material', code=code):
            _ins(c, 'charge_material', {'code': code, 'name': name, 'price': price, 'C': C, 'Si': Si, 'Mn': Mn, 'S': S, 'P': Pp, 'min_ratio': lo, 'max_ratio': hi,
                                             'stock_t': stock, 'yield_pct': 92 if code == 'CM-CARB' else 95}, raw=True)
            from .services.warehouse import move
            move(c, 'in', mid[code], stock, whs['raw' if code in ('CM-PIG', 'CM-STEEL', 'CM-RET') else 'aux'], who='系统', reason='期初库存')
    for code, q in (('AUX-NODU', 6), ('AUX-INOC', 3), ('AUX-SAND', 400), ('AUX-SHOT', 4)):
        if not db.rows(c, 'stock', material=mid[code]):
            from .services.warehouse import move
            move(c, 'in', mid[code], q, whs['aux'], who='系统', reason='期初库存')
    # 数据源：虚拟工厂（MQTT 统一命名空间）
    ensure(c, 'datasource', 'code', {'code': 'VF', 'name': '虚拟工厂（示范工厂）', 'protocol': 'mqtt', 'endpoint': 'mqtt://127.0.0.1:1883', 'prefix': 'vfactory/foundry-housing/',
                                     'enabled': True, 'remark': '先点"从虚拟工厂导入"建设备和点表'})
    db.set_setting(c, 'company', '教学工厂', '公司名称')


def after_import(c):
    """导入设备后补充依赖设备的数据：点检保养计划、NC 程序。"""
    today = clock.now().date()
    for e in db.rows(c, 'equipment'):
        if e['etype'] in ('crew', 'agv', 'cooling'):
            continue
        items = {'furnace': '冷却水流量/温度；炉衬漏电流；感应圈有无渗水；液压系统油位', 'cnc': '导轨润滑油位；切削液浓度；主轴异响；排屑器；气压 0.5 MPa',
                 'molding': '液压站油温油位；模板清洁；脱模剂', 'sand': '混砂机刮板磨损；水分仪校准；皮带跑偏', 'shotblast': '抛头叶片磨损；钢丸量；除尘器压差',
                 'inspection': '镜头清洁；光源亮度；标准件比对', 'deburr': '毛刷磨损；机器人原点', 'warehouse': '堆垛机限位；货叉；光电', 'treatment': '浇包包衬；吊具'}.get(e['etype'], '外观、紧固、润滑')
        code = f"MP-{e['code']}-D"
        if not db.get(c, 'maint_plan', code=code):
            _ins(c, 'maint_plan', {'code': code, 'name': _tr('{name} 日常点检', name=e['name']), 'equipment': e['id'], 'mtype': 'spot', 'cycle_days': 1, 'items': items,
                                        'next_due': today}, raw=True)
        code = f"MP-{e['code']}-M"
        if e['etype'] in ('furnace', 'cnc', 'molding', 'shotblast') and not db.get(c, 'maint_plan', code=code):
            _ins(c, 'maint_plan', {'code': code, 'name': _tr('{name} 月度保养', name=e['name']), 'equipment': e['id'], 'mtype': 'maint', 'cycle_days': 30,
                                        'items': '更换滤芯；检查液压/润滑系统；电气柜除尘；精度/参数检查', 'next_due': today + timedelta(days=7 + e['id'] % 20)}, raw=True)
    m = db.get(c, 'material', code='SGH-450')
    for code, name, ver, st, remark in (('O1201', 'SGH-450 壳体加工主程序', 'V3', 'released', '精镗余量 0.25→0.20，提高缸孔一致性'),
                                       ('O1201', 'SGH-450 壳体加工主程序', 'V4', 'draft', 'OP30 钻油道孔进给 0.15→0.13，降低交叉孔毛刺（待试切）'),
                                       ('O1202', 'SGH-450 测头程序', 'V1', 'released', '')):
        if not db.rows(c, 'nc_program', name=name, version=ver, code=f'{code}-{ver}'):
            _ins(c, 'nc_program', {'code': f'{code}-{ver}', 'name': name, 'product': m['id'] if m else None, 'station_group': 'CNC', 'version': ver, 'status': st,
                                        'content': f'%\n{code} ({name} {ver})\nG90 G54 G17\nT01 M06 (Φ80 面铣)\n...\nM30\n%', 'remark': remark,
                                        'approved_by': '郑凯' if st == 'released' else None, 'released_at': clock.now() if st == 'released' else None}, raw=True)


def run():
    from . import edu
    with db.engine.begin() as c:
        base(c)
        edu.seed(c)
