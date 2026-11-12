"""安全表达式引擎：自定义点位公式、节拍分布、质量规则、信号绑定、路由条件都用它。

只允许：数字、字符串、比较/算术/逻辑运算、条件表达式、白名单函数和变量。不能访问属性、下标以外的对象，不能导入、不能执行任意代码。

可用函数
  数学     abs min max round sqrt exp log log10 sin cos pi clip(x,lo,hi)
  分布     normal(m,sd) tri(a,mode,b) uniform(a,b) expo(mean) lognormal(mean,sd) const(x)
  动态     noise(sd)                白噪声
           walk(sd, lo, hi)         有界随机游走（每个点位各自记忆）
           lag(x, tau_s)            一阶滞后，时间常数 tau 秒
           ramp(t0_h, t1_h, v0, v1) 仿真时间 t0~t1 小时之间线性变化
           pulse(period_h, width_h) 周期脉冲 0/1
           if_(cond, a, b)          条件
  数据     tag('点位') / tag('设备/点位')    读点位当前值（本设备可省略设备）
           param('参数名')                  读本设备参数
           tbl('表名', 键, '列名')           查全局数据表（按第一列找键）
可用变量
  t（仿真小时）、dt（步长秒）、state（状态字符串）、busy（是否运行 0/1）、power（kW）、
  质量规则里另有 item（零件属性字典，用 item['pour_temp'] 或 item.get('x', 默认)）。
"""
from ..i18n import _tr
import ast
import math

ALLOWED_NODES = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp, ast.Call, ast.Name, ast.Load, ast.Constant,
                 ast.And, ast.Or, ast.Not, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv, ast.USub, ast.UAdd,
                 ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Subscript, ast.Attribute, ast.Tuple, ast.List, ast.keyword)
FUNCS = {'abs', 'min', 'max', 'round', 'sqrt', 'exp', 'log', 'log10', 'sin', 'cos', 'clip', 'normal', 'tri', 'uniform', 'expo', 'lognormal', 'const',
         'noise', 'walk', 'lag', 'ramp', 'pulse', 'if_', 'tag', 'param', 'tbl', 'int', 'float', 'str', 'len', 'bool'}
VARS = {'t', 'dt', 'state', 'busy', 'power', 'item', 'pi', 'True', 'False', 'None', 'x', 'value'}
_cache: dict[str, object] = {}


class ExprError(ValueError):
    pass


def check(src: str, extra_vars=()):
    """语法和安全检查，返回编译后的代码对象。"""
    key = src + '|' + ','.join(extra_vars)
    if key in _cache:
        return _cache[key]
    s = str(src).strip()
    if not s:
        raise ExprError(_tr('表达式为空'))
    if len(s) > 2000:
        raise ExprError(_tr('表达式太长'))
    try:
        tree = ast.parse(s, mode='eval')
    except SyntaxError as e:
        raise ExprError(_tr('语法错误：{msg}（第 {offset} 个字符附近）', msg=e.msg, offset=e.offset))
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise ExprError(_tr('不允许的写法：{v}', v=type(node).__name__))
        if isinstance(node, ast.Attribute) and node.attr not in ('get',):
            raise ExprError(_tr('不允许访问属性 .{attr}（零件属性请用 item["名称"] 或 item.get("名称", 默认)）', attr=node.attr))
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id not in FUNCS:
                raise ExprError(_tr('未知函数 {id}()', id=f.id))
            if isinstance(f, ast.Attribute) and not (isinstance(f.value, ast.Name) and f.value.id == 'item'):
                raise ExprError(_tr('只有 item.get() 可以这样调用'))
        if isinstance(node, ast.Name) and node.id not in FUNCS and node.id not in VARS and node.id not in extra_vars:
            raise ExprError(_tr('未知变量 {id}', id=node.id))
    code = compile(tree, '<expr>', 'eval')
    _cache[key] = code
    return code


class Ctx:
    """一个表达式的运行环境：随机数、状态记忆（walk/lag）、取点位。"""

    def __init__(self, rng, station=None, plant=None):
        self.rng, self.st, self.plant = rng, station, plant
        self.mem: dict = {}
        self.n = 0

    def env(self, **extra):
        r, st, p = self.rng, self.st, self.plant
        self.n = 0
        mem = self.mem

        def nxt():
            self.n += 1
            return self.n

        def walk(sd, lo=-math.inf, hi=math.inf):
            k = ('w', nxt())
            v = mem.get(k, (lo + hi) / 2 if math.isfinite(lo) and math.isfinite(hi) else 0.0) + r.normal(0, sd)
            v = min(hi, max(lo, v))
            mem[k] = v
            return v

        def lag(x, tau):
            k = ('l', nxt())
            prev = mem.get(k, x)
            dt_ = getattr(p, 'dt', 1.0) * 5 if p else 1.0
            v = prev + (x - prev) * min(1.0, dt_ / max(1e-6, tau))
            mem[k] = v
            return v

        def tag(name):
            if '/' in name and p is not None:
                sid, _, rest = name.partition('/')
                s2 = p.stations.get(sid)
                if s2 is not None and rest in s2.tags:
                    return s2.tags[rest].value
            if st is not None and name in st.tags:
                return st.tags[name].value
            return 0.0

        def param(name):
            return (st.cfg.get(name) if st is not None else None) or 0.0

        def tbl(name, key, column):
            if p is None:
                return 0.0
            from ..datatables import lookup
            return lookup(p, name, key, column)

        th = (p.t / 3600) if p is not None else 0.0
        env = {
            'abs': abs, 'min': min, 'max': max, 'round': round, 'sqrt': math.sqrt, 'exp': math.exp, 'log': math.log, 'log10': math.log10,
            'sin': math.sin, 'cos': math.cos, 'pi': math.pi, 'int': int, 'float': float, 'str': str, 'len': len, 'bool': bool,
            'clip': lambda x, lo, hi: min(hi, max(lo, x)),
            'normal': lambda m, sd: float(r.normal(m, sd)), 'tri': lambda a, mo, b: float(r.triangular(a, mo, b)),
            'uniform': lambda a, b: float(r.uniform(a, b)), 'expo': lambda m: float(r.exponential(m)),
            'lognormal': lambda m, sd: float(r.lognormal(math.log(max(1e-9, m)) - 0.5 * math.log(1 + (sd / max(1e-9, m)) ** 2),
                                                    math.sqrt(math.log(1 + (sd / max(1e-9, m)) ** 2)))),
            'const': lambda x: x, 'noise': lambda sd: float(r.normal(0, sd)), 'walk': walk, 'lag': lag,
            'ramp': lambda t0, t1, v0, v1: v0 if th <= t0 else v1 if th >= t1 else v0 + (v1 - v0) * (th - t0) / (t1 - t0),
            'pulse': lambda per, w: 1.0 if (th % per) < w else 0.0, 'if_': lambda c, a, b: a if c else b,
            'tag': tag, 'param': param, 'tbl': tbl, 't': th, 'dt': getattr(p, 'dt', 1.0) if p else 1.0,
            'state': getattr(st, 'state', ''), 'busy': 1.0 if getattr(st, 'state', '') == 'Executing' else 0.0, 'power': getattr(st, 'power_kw', 0.0),
            'True': True, 'False': False, 'None': None,
        }
        env.update(extra)
        return env


def evaluate(src, ctx: Ctx, **extra):
    code = check(src, tuple(extra))
    try:
        return eval(code, {'__builtins__': {}}, ctx.env(**extra))
    except ExprError:
        raise
    except Exception as e:
        raise ExprError(_tr('计算出错：{e}', e=e))


def try_eval(src, rng, **extra):
    """编辑器里试算：返回 (ok, 值或错误)。"""
    try:
        return True, evaluate(src, Ctx(rng), **extra)
    except ExprError as e:
        return False, str(e)
