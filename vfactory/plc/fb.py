"""标准功能块（IEC 61131-3）与标准函数。

时间统一用整数：PLC 内部时钟 now 是微秒，TIME 类型的值是毫秒。
功能块实例是普通对象（可 deepcopy），字段名大写；下划线开头的是内部状态，不在在线监视里显示。
"""
import math

INT_MAX, INT_MIN = 32767, -32768


class FBInst:
    def __init__(self, typ):
        self.t = typ
        d = FB_DEFS[typ]
        self.f = {k: _zero(v) for k, v in {**d['in'], **d['out']}.items()}
        self.f.update(d.get('state', {}))

    def public(self):
        return {k: v for k, v in self.f.items() if not k.startswith('_')}

    def __repr__(self):
        return f'{self.t}{self.public()}'


def _zero(t):
    return False if t == 'BOOL' else 0.0 if t in ('REAL', 'LREAL') else 0


def _ton(f, now):
    if f['IN']:
        if not f['_R']:
            f['_R'], f['_S'] = True, now
        et = (now - f['_S']) // 1000
        pt = max(0, int(f['PT']))
        if et >= pt:
            f['Q'], f['ET'] = True, pt
        else:
            f['Q'], f['ET'] = False, et
    else:
        f['_R'], f['Q'], f['ET'] = False, False, 0


def _tof(f, now):
    if f['IN']:
        f['Q'], f['ET'], f['_R'] = True, 0, False
    elif f['Q'] or f['_R']:
        if not f['_R']:
            f['_R'], f['_S'] = True, now
        et = (now - f['_S']) // 1000
        pt = max(0, int(f['PT']))
        if et >= pt:
            f['Q'], f['ET'] = False, pt
        else:
            f['ET'] = et


def _tp(f, now):
    pin, f['_P'] = f['_P'], f['IN']
    if not f['_R'] and f['IN'] and not pin and not f['Q']:
        f['_R'], f['_S'] = True, now
    if f['_R']:
        et = (now - f['_S']) // 1000
        pt = max(0, int(f['PT']))
        if et >= pt:
            f['_R'], f['Q'], f['ET'] = False, False, pt
        else:
            f['Q'], f['ET'] = True, et
    elif not f['IN']:
        f['ET'] = 0


def _ctu(f, now):
    if f['R']:
        f['CV'] = 0
    elif f['CU'] and not f['_M'] and f['CV'] < INT_MAX:
        f['CV'] += 1
    f['_M'] = f['CU']
    f['Q'] = f['CV'] >= f['PV']


def _ctd(f, now):
    if f['LD']:
        f['CV'] = f['PV']
    elif f['CD'] and not f['_M'] and f['CV'] > INT_MIN:
        f['CV'] -= 1
    f['_M'] = f['CD']
    f['Q'] = f['CV'] <= 0


def _ctud(f, now):
    if f['R']:
        f['CV'] = 0
    elif f['LD']:
        f['CV'] = f['PV']
    else:
        if f['CU'] and not f['_MU'] and f['CV'] < INT_MAX:
            f['CV'] += 1
        if f['CD'] and not f['_MD'] and f['CV'] > INT_MIN:
            f['CV'] -= 1
    f['_MU'], f['_MD'] = f['CU'], f['CD']
    f['QU'] = f['CV'] >= f['PV']
    f['QD'] = f['CV'] <= 0


def _rtrig(f, now):
    f['Q'] = bool(f['CLK'] and not f['_M'])
    f['_M'] = f['CLK']


def _ftrig(f, now):
    # 按"下降沿"的本意实现：上一次为真、这一次为假才输出一个扫描周期（避免首次调用误触发）
    f['Q'] = bool(f['_M'] and not f['CLK'])
    f['_M'] = f['CLK']


def _sr(f, now):
    f['Q1'] = bool(f['S1'] or (not f['R'] and f['Q1']))


def _rs(f, now):
    f['Q1'] = bool(not f['R1'] and (f['S'] or f['Q1']))


# power_in / power_out：梯形图里功能块盒子左边接能流的输入、右边送出能流的输出
FB_DEFS = {
    'TON': {'in': {'IN': 'BOOL', 'PT': 'TIME'}, 'out': {'Q': 'BOOL', 'ET': 'TIME'}, 'state': {'_R': False, '_S': 0}, 'run': _ton,
            'pin': 'IN', 'pout': 'Q', 'cn': '接通延时定时器'},
    'TOF': {'in': {'IN': 'BOOL', 'PT': 'TIME'}, 'out': {'Q': 'BOOL', 'ET': 'TIME'}, 'state': {'_R': False, '_S': 0}, 'run': _tof,
            'pin': 'IN', 'pout': 'Q', 'cn': '断开延时定时器'},
    'TP': {'in': {'IN': 'BOOL', 'PT': 'TIME'}, 'out': {'Q': 'BOOL', 'ET': 'TIME'}, 'state': {'_R': False, '_S': 0, '_P': False}, 'run': _tp,
           'pin': 'IN', 'pout': 'Q', 'cn': '脉冲定时器'},
    'CTU': {'in': {'CU': 'BOOL', 'R': 'BOOL', 'PV': 'INT'}, 'out': {'Q': 'BOOL', 'CV': 'INT'}, 'state': {'_M': False}, 'run': _ctu,
            'pin': 'CU', 'pout': 'Q', 'cn': '加计数器'},
    'CTD': {'in': {'CD': 'BOOL', 'LD': 'BOOL', 'PV': 'INT'}, 'out': {'Q': 'BOOL', 'CV': 'INT'}, 'state': {'_M': False}, 'run': _ctd,
            'pin': 'CD', 'pout': 'Q', 'cn': '减计数器'},
    'CTUD': {'in': {'CU': 'BOOL', 'CD': 'BOOL', 'R': 'BOOL', 'LD': 'BOOL', 'PV': 'INT'}, 'out': {'QU': 'BOOL', 'QD': 'BOOL', 'CV': 'INT'},
             'state': {'_MU': False, '_MD': False}, 'run': _ctud, 'pin': 'CU', 'pout': 'QU', 'cn': '加减计数器'},
    'R_TRIG': {'in': {'CLK': 'BOOL'}, 'out': {'Q': 'BOOL'}, 'state': {'_M': False}, 'run': _rtrig, 'pin': 'CLK', 'pout': 'Q', 'cn': '上升沿检测'},
    'F_TRIG': {'in': {'CLK': 'BOOL'}, 'out': {'Q': 'BOOL'}, 'state': {'_M': False}, 'run': _ftrig, 'pin': 'CLK', 'pout': 'Q', 'cn': '下降沿检测'},
    'SR': {'in': {'S1': 'BOOL', 'R': 'BOOL'}, 'out': {'Q1': 'BOOL'}, 'run': _sr, 'pin': 'S1', 'pout': 'Q1', 'cn': '置位优先触发器'},
    'RS': {'in': {'S': 'BOOL', 'R1': 'BOOL'}, 'out': {'Q1': 'BOOL'}, 'run': _rs, 'pin': 'S', 'pout': 'Q1', 'cn': '复位优先触发器'},
}


# ---------------------------------------------------------------- 标准函数（纯函数，类型检查在编译器里做）
def _real(x):
    return float(x)


def _round_half_away(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


MATH1 = {'SQRT': math.sqrt, 'LN': math.log, 'LOG': math.log10, 'EXP': math.exp, 'SIN': math.sin, 'COS': math.cos, 'TAN': math.tan,
         'ASIN': math.asin, 'ACOS': math.acos, 'ATAN': math.atan}
FUNC_CN = {
    'ABS': '绝对值', 'MIN': '最小值', 'MAX': '最大值', 'LIMIT': '限幅 LIMIT(MN, IN, MX)', 'SEL': '二选一 SEL(G, IN0, IN1)',
    'MUX': '多选一 MUX(K, IN0, IN1, …)', 'SQRT': '平方根', 'LN': '自然对数', 'LOG': '常用对数', 'EXP': '指数', 'SIN': '正弦', 'COS': '余弦',
    'TAN': '正切', 'ASIN': '反正弦', 'ACOS': '反余弦', 'ATAN': '反正切', 'EXPT': '乘方 EXPT(底, 指数)', 'TRUNC': '取整（截断）',
    'SHL': '左移 SHL(IN, N)', 'SHR': '右移 SHR(IN, N)', 'ROL': '循环左移', 'ROR': '循环右移', 'MOVE': '传送',
}
