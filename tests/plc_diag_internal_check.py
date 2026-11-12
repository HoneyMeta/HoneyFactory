"""5.0.2：按了按钮没反应的诊断：内部继电器（别的梯级读它，不在 I/O 表）不能报"不在 I/O 表"；写了又没人读、也不在 I/O 表的（多半写错名字）还要报。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
from types import SimpleNamespace as NS

from vfactory.plc import explain as X
from vfactory.teach import coach as C

IO = [{'name': 'START', 'dir': 'in'}, {'name': 'M1_RUN', 'dir': 'out'}]
SNAP = {'state': 'RUN', 'hash': 'x', 'vars': {}, 'outputs': {}}
results = []


def run(rungs):
    prog = {'lang': 'LD', 'source': {'rungs': rungs}}
    obj = C.Coach.__new__(C.Coach)
    diags = []
    obj._diag = lambda d, *a: diags.append(d)
    obj.add = lambda *a, **k: None         # 正常提示（"条件还不满足"）不是诊断
    obj.plc_of = lambda c: (NS(), NS(prog=NS(program=prog)))
    C._io_rows, X.snapshot = (lambda p, c: IO), (lambda rp: SNAP)
    obj._generic_diag({'cell': None, 'held_snap': None}, NS(t=0), {'name': 'START', 'lab': '启动', 't': 0})
    return diags


def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name, detail)


NO, COIL = (lambda v: {'t': 'NO', 'var': v}), (lambda v: {'t': 'COIL', 'var': v})
assert X.rungs_of({'lang': 'LD', 'source': {'rungs': [{'elements': [NO('A')]}]}}), 'rungs_of 格式变了'
d = run([{'elements': [NO('START'), COIL('RUN')]}, {'elements': [NO('RUN'), COIL('M1_RUN')]}])
check('内部继电器 RUN 不报"不在 I/O 表"', not any(x.get('cause') == 'not_io' for x in d), d)
d = run([{'elements': [NO('START'), COIL('M1_RUNN')]}])
check('写错名字（没人读、不在 I/O 表）仍然提示', any(x.get('cause') == 'not_io' for x in d), d)
print(f'{sum(results)}/{len(results)} 通过')
raise SystemExit(0 if all(results) else 1)
