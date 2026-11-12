"""场景：按时间编排的扰动脚本。每一步在"开始后第 N 分钟（仿真时间）"执行一个动作；带时长的动作到时自动恢复。

动作：
  fault      注入故障        target=设备, value=故障类型（见设备的 fault_kinds）
  clear      清除故障        target=设备
  write      写设定值        target=设备, tag=点位, value=值
  ramp       设定值渐变      target=设备, tag=点位, value=终值, minutes=用时（从当前值线性变到终值）
  disable    设备停用        target=设备, minutes=时长（到时自动启用）
  absent     人员缺勤        value=人数, minutes=时长
  comm       通讯故障        target=opcua|modbus|mqtt, value=freeze|bad|disconnect|latency, minutes=时长
  speed      仿真倍速        value=倍速
  note       记一条说明
"""
from .i18n import _tr
import copy

BUILTIN = [
    {'key': 'tool_break', 'name': '夜班断刀', 'descr': 'CNC3 的 Φ8 钻头在开始 30 分钟后断刀：设备停机、当件报废，换刀后恢复。用于测试 MES 报警、停机统计和刀具记录。',
     'steps': [{'at': 30, 'action': 'fault', 'target': 'CNC3', 'value': 'tool_break'}]},
    {'key': 'sand_drift', 'name': '型砂水分失控', 'descr': '砂处理切到手动并逐步加大加水量，型砂水分 2 小时内升高，气孔缺陷随之增多。用于测试质量追溯和缺陷回溯。',
     'steps': [{'at': 0, 'action': 'write', 'target': 'SAND1', 'tag': 'Setpoint/AutoControl', 'value': False},
               {'at': 0, 'action': 'ramp', 'target': 'SAND1', 'tag': 'Setpoint/WaterManual', 'value': 34, 'minutes': 120},
               {'at': 240, 'action': 'write', 'target': 'SAND1', 'tag': 'Setpoint/AutoControl', 'value': True}]},
    {'key': 'mg_low', 'name': '球化剂加入不足', 'descr': '球化剂加入量在 1 小时内从 1.5% 降到 1.1%，残镁下降、球化不良报废增加。',
     'steps': [{'at': 0, 'action': 'ramp', 'target': 'TRT1', 'tag': 'Setpoint/MgAlloyPct', 'value': 1.1, 'minutes': 60},
               {'at': 180, 'action': 'write', 'target': 'TRT1', 'tag': 'Setpoint/MgAlloyPct', 'value': 1.5}]},
    {'key': 'cooling_water', 'name': '电炉冷却水异常', 'descr': '1# 中频炉冷却水流量偏低，出水温度升高报警。用于测试设备报警和异常解释。',
     'steps': [{'at': 10, 'action': 'fault', 'target': 'FUR1', 'value': 'cooling_low'}, {'at': 70, 'action': 'clear', 'target': 'FUR1'}]},
    {'key': 'absent', 'name': '缺员两人', 'descr': '两名操作工缺勤 3 小时，CNC 上下料等人，产量下降。用于测试人员对产能的影响。',
     'steps': [{'at': 0, 'action': 'absent', 'value': 2, 'minutes': 180}]},
    {'key': 'chatter', 'name': '主轴轴承磨损', 'descr': 'CNC2 主轴振动逐步增大（不停机）。用于测试预测性维护算法能否提前发现。',
     'steps': [{'at': 20, 'action': 'fault', 'target': 'CNC2', 'value': 'chatter'}]},
    {'key': 'led', 'name': '检测光源衰减', 'descr': '内窥检测站光源亮度 4 小时内从 70% 降到 35%，漏检增加（仿真真值可对照）。',
     'steps': [{'at': 0, 'action': 'ramp', 'target': 'INS1', 'tag': 'Setpoint/LedBrightness', 'value': 35, 'minutes': 240},
               {'at': 300, 'action': 'write', 'target': 'INS1', 'tag': 'Setpoint/LedBrightness', 'value': 70}]},
    {'key': 'maint', 'name': '计划停机保养', 'descr': 'CNC5 停机保养 2 小时。',
     'steps': [{'at': 0, 'action': 'disable', 'target': 'CNC5', 'minutes': 120}]},
    {'key': 'comm', 'name': '通讯故障演练', 'descr': 'Modbus 断开 10 分钟、OPC UA 数据质量变坏 5 分钟、MQTT 数据冻结 8 分钟。用于测试数采网关和 MES 的断线处理。',
     'steps': [{'at': 5, 'action': 'comm', 'target': 'modbus', 'value': 'disconnect', 'minutes': 10},
               {'at': 20, 'action': 'comm', 'target': 'opcua', 'value': 'bad', 'minutes': 5},
               {'at': 30, 'action': 'comm', 'target': 'mqtt', 'value': 'freeze', 'minutes': 8}]},
    {'key': 'stress', 'name': '综合压力测试（一个班）', 'descr': '一个班内依次出现：缺员、断刀、型砂水分偏高、球化剂偏少、抛丸机故障、通讯中断。',
     'steps': [{'at': 0, 'action': 'speed', 'value': 60}, {'at': 30, 'action': 'absent', 'value': 1, 'minutes': 120},
               {'at': 60, 'action': 'fault', 'target': 'CNC4', 'value': 'tool_break'},
               {'at': 90, 'action': 'ramp', 'target': 'SAND1', 'tag': 'Setpoint/Moisture', 'value': 3.9, 'minutes': 60},
               {'at': 150, 'action': 'ramp', 'target': 'TRT1', 'tag': 'Setpoint/MgAlloyPct', 'value': 1.2, 'minutes': 30},
               {'at': 240, 'action': 'fault', 'target': 'SHOT1', 'value': 'failure'},
               {'at': 300, 'action': 'comm', 'target': 'modbus', 'value': 'disconnect', 'minutes': 5},
               {'at': 360, 'action': 'write', 'target': 'SAND1', 'tag': 'Setpoint/Moisture', 'value': 3.4},
               {'at': 360, 'action': 'write', 'target': 'TRT1', 'tag': 'Setpoint/MgAlloyPct', 'value': 1.5},
               {'at': 480, 'action': 'note', 'value': '综合压力测试结束'}]},
]
ACTIONS = {'fault': '注入故障', 'clear': '清除故障', 'write': '写设定值', 'ramp': '设定值渐变', 'disable': '设备停用', 'absent': '人员缺勤', 'comm': '通讯故障',
           'speed': '仿真倍速', 'note': '说明'}


class Runner:
    """一个工厂同时只跑一个场景；挂在 plant.step_hooks 上逐步检查。"""

    def __init__(self, rt):
        self.rt = rt
        self.run = None
        self.history = []

    def start(self, sc: dict):
        p = self.rt.plant
        self.stop(_tr('被新场景替换'))
        steps = sorted(copy.deepcopy(sc['steps']), key=lambda s: float(s.get('at', 0)))
        for s in steps:
            s['_t'] = p.t + float(s.get('at', 0)) * 60
            s['_done'] = False
        self.run = {'id': sc.get('id') or sc.get('key'), 'name': sc['name'], 'start': p.t, 'start_time': p.clock_str(), 'steps': steps, 'ramps': [],
                    'reverts': [], 'log': []}
        p.log('SCENARIO', 'scenario', _tr('场景开始：{name}', name=sc['name']))
        p.label_open('SCENARIO', 'scenario', sc['name'])
        if self.tick not in p.step_hooks:
            p.step_hooks.append(self.tick)

    def stop(self, why='手动停止'):
        r = self.run
        if not r:
            return
        p = self.rt.plant
        for rv in r['reverts']:
            self._do(rv, revert=True)
        p.log('SCENARIO', 'scenario', _tr('场景结束：{name}（{why}）', name=r['name'], why=why))
        p.label_close('SCENARIO', 'scenario')
        self.history.insert(0, {'name': r['name'], 'start': r['start_time'], 'end': p.clock_str(), 'why': why, 'steps': len(r['steps']),
                                'log': r['log'][-50:]})
        self.history = self.history[:20]
        self.run = None

    def tick(self):
        r = self.run
        if not r:
            return
        p = self.rt.plant
        t = p.t
        for s in r['steps']:
            if not s['_done'] and t >= s['_t']:
                s['_done'] = True
                self._do(s)
        for rp in r['ramps']:
            if t >= rp['next'] or t >= rp['t1']:
                f = min(1.0, (t - rp['t0']) / max(1, rp['t1'] - rp['t0']))
                v = rp['v0'] + (rp['v1'] - rp['v0']) * f
                st = p.stations.get(rp['target'])
                if st:
                    st.write(rp['tag'], round(v, 4))
                rp['next'] = t + 60
        r['ramps'] = [x for x in r['ramps'] if t < x['t1']]
        for rv in list(r['reverts']):
            if t >= rv['_t']:
                self._do(rv, revert=True)
                r['reverts'].remove(rv)
        if all(s['_done'] for s in r['steps']) and not r['ramps'] and not r['reverts']:
            self.stop(_tr('全部步骤完成'))

    def _do(self, s, revert=False):
        p, rt, r = self.rt.plant, self.rt, self.run
        a, tgt, val = s['action'], s.get('target'), s.get('value')
        st = p.stations.get(tgt) if tgt else None
        msg = ''
        try:
            if a == 'fault' and st:
                err = st.inject(str(val))
                msg = err or _tr('{tgt} 注入：{get}', tgt=tgt, get=st.fault_kinds.get(val, val))
            elif a == 'clear' and st:
                st.inject('clear')
                msg = _tr('{tgt} 清除故障', tgt=tgt)
            elif a == 'write' and st:
                err = st.write(s['tag'], val)
                msg = err or f"{tgt} {s['tag']} = {val}"
            elif a == 'ramp' and st:
                cur = st.get(s['tag'])
                mins = float(s.get('minutes', 60))
                r['ramps'].append({'target': tgt, 'tag': s['tag'], 'v0': float(cur), 'v1': float(val), 't0': p.t, 't1': p.t + mins * 60, 'next': p.t})
                msg = _tr('{tgt} {tag} 在 {mins:g} 分钟内从 {cur} 变到 {val}', tgt=tgt, tag=s['tag'], mins=mins, cur=cur, val=val)
            elif a == 'disable' and st:
                st.enabled = revert
                msg = f"{tgt} {_tr('恢复启用') if revert else _tr('停用')}"
                if revert:
                    p.label_close(tgt, 'planned')
                else:
                    p.label_open(tgt, 'planned', _tr('场景停用'))
            elif a == 'absent':
                crew = next((x for x in p.stations.values() if x.kind == 'crew'), None)
                if crew:
                    n = int(val or 1)
                    if revert:
                        for w in crew.workers:
                            if w.get('_scn_absent'):
                                w['absent'] = 0
                                w.pop('_scn_absent')
                        msg = _tr('缺勤人员回岗')
                        p.label_close('CREW', 'fault')
                    else:
                        free = [w for w in crew.workers if not w['absent']][:n]
                        for w in free:
                            w['absent'] = 10 ** 9
                            w['_scn_absent'] = True
                            w['serving'] = None
                        msg = _tr('{len} 人缺勤：{join}', len=len(free), join=_tr('、').join(w['role'] for w in free))
                        p.label_open('CREW', 'fault', _tr('缺勤 {len} 人', len=len(free)))
            elif a == 'comm':
                # 可选 station / tag / drop_pct / stuck / rate：按设备或点位注入（规则引擎见 vfactory/comm.py）
                where = (f" {s['station']}" + (f"/{s['tag']}" if s.get('tag') else '')) if s.get('station') else ''
                if revert:
                    rt.comm_set(tgt, None, station=s.get('station'), tag=s.get('tag'))
                    msg = _tr('{tgt}{where} 通讯恢复', tgt=tgt, where=where)
                else:
                    rt.comm_set(tgt, str(val), latency=float(s.get('latency', 5)), station=s.get('station'), tag=s.get('tag'),
                                drop_pct=s.get('drop_pct'), value=s.get('stuck'), rate=s.get('rate'))
                    msg = _tr('{tgt}{where} 通讯故障：{val}', tgt=tgt, where=where, val=val)
            elif a == 'speed':
                p.speed = float(val)
                msg = _tr('仿真倍速 {val}×', val=val)
            elif a == 'note':
                msg = str(val)
            else:
                msg = _tr('跳过：找不到设备 {tgt}', tgt=tgt) if tgt and not st else _tr('未知动作 {a}', a=a)
        except Exception as ex:
            msg = _tr('执行失败：{ex}', ex=ex)
        if not revert and s.get('minutes') and a in ('disable', 'absent', 'comm'):
            r['reverts'].append({**s, '_t': p.t + float(s['minutes']) * 60})
        p.log(tgt or 'SCENARIO', 'scenario', (_tr('（恢复）') if revert else '') + msg)
        p.label_point(tgt or 'PLANT', 'scenario', msg)
        if r is not None:
            r['log'].append({'t': p.clock_str(), 'msg': (_tr('（恢复）') if revert else '') + msg})

    def view(self):
        r = self.run
        if not r:
            return {'running': None, 'history': self.history}
        p = self.rt.plant
        steps = [{'at': s.get('at'), 'action': ACTIONS.get(s['action'], s['action']), 'target': s.get('target'), 'tag': s.get('tag'), 'value': s.get('value'),
                  'minutes': s.get('minutes'), 'done': s['_done'], 'eta_min': round(max(0, s['_t'] - p.t) / 60, 1)} for s in r['steps']]
        return {'running': {'name': r['name'], 'start': r['start_time'], 'elapsed_min': round((p.t - r['start']) / 60, 1), 'steps': steps, 'log': r['log'][-30:],
                            'ramps': len(r['ramps']), 'reverts': len(r['reverts'])}, 'history': self.history}
