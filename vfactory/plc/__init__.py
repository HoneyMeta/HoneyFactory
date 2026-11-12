"""PLC 层：内置软 PLC（LD 梯形图 + ST 结构化文本，IEC 61131-3 子集）、外接 PLC 驱动、PLCopen XML 交换。

控制单元（vfactory/control 的 Cell 块）这样用：

    from vfactory import plc
    station.plc = plc.for_cell(cell_def)            # 按 cell_def['plc'] 建内置 PLC 或外接 PLC，都有 scan()
    ...每 20 ms 子步：
    outs = station.plc.scan(sim.inputs(), dt)       # 读输入映像 → 执行程序 → 返回输出（按 I/O 名）
    sim.apply_outputs(outs)
"""
from .compiler import PlcError
from .program import blank_program, compile_program, check, program_hash
from .runtime import PlcRuntime
from .st import StError, fmt_time, parse_time


def compile(program, io=None):          # noqa: A001  与设计文档里的名字一致
    """compile(program) -> {ok, errors:[{line|rung, msg}], warnings, symbols, …}"""
    return check(program, io)


def for_cell(cell_def, program=None):
    """按控制单元定义建 PLC：plc.mode == 'external' 时返回外接 PLC 代理（同样有 scan），否则内置软 PLC。
    program 不给时用 cell_def['plc']['program']（内联程序 dict）；没有程序时是一个空 PLC（STOP）。"""
    if 'plc' not in (cell_def or {}):                # 4.3：控制单元的 PLC 拆成了独立的 plc 块，单元自己不再带 PLC
        return None
    cfg = (cell_def or {}).get('plc') or {}
    io = (cell_def or {}).get('io') or []
    scan_ms = float(cfg.get('scan_ms') or 20)
    if cfg.get('mode') == 'external':
        from .external import ExternalPlc
        return ExternalPlc(cfg.get('external') or {}, io, scan_ms=scan_ms)
    if program is None and isinstance(cfg.get('program'), dict):
        program = cfg['program']
    return PlcRuntime(program, scan_ms=scan_ms, io=io)


__all__ = ['PlcRuntime', 'PlcError', 'StError', 'compile', 'compile_program', 'check', 'blank_program', 'program_hash', 'for_cell',
           'fmt_time', 'parse_time']
