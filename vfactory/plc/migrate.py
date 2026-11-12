"""4.3 迁移：控制单元里内置的 PLC → 独立的 `plc` 块 + 一条信号线。

    migrate_model(model)      就地修改 2.0 模型，返回改动说明列表（没有要迁的返回 []）；重复调用不会再改
    python -m vfactory.plc.migrate plants/a.yaml templates/cells/*.yaml …   把文件里的模型迁移后写回

迁移规则（和控制层、教学约定好）：
  - 单元 params.cell 里的 plc 段拿掉（单元不再自带 PLC）；HMI 画面 cell.hmi 搬到 PLC 块（画面绑定 PLC）；
  - 新 PLC 块：编号 PLC1、PLC2…（不和已有编号冲突，按单元顺序，结果固定），放在单元右边；
    params = {model, scan_ms, mode, program, external, hmi, migrated_from: <单元编号>, di/do/ai/ao}；
  - 信号线 {kind:'signal', from:<单元>, to:<PLC>, signals:[{point:<I/O 名>, ch:<地址，不带 %>, dir}], all_io: true}；
    all_io：以后在单元里新加的 I/O 点也自动接到这台 PLC（地址用单元 I/O 表里的）；
    PLC 里变量名 = 点位名，原来的程序不用改；
  - data/plc 里按单元编号存的程序：API 按 migrated_from 找回来（不用搬文件）。
"""
from ..i18n import _tr
import copy
import re
import sys

from ..plc.st import norm_addr


def _new_id(prefix, used):
    i = 1
    while f'{prefix}{i}' in used:
        i += 1
    used.add(f'{prefix}{i}')
    return f'{prefix}{i}'


def ch_of(addr):
    """PLC 地址 → 信号线通道写法（不带 %，位地址省掉 X）：%IX0.0 → I0.0，%QW64 → QW64。"""
    a = str(addr or '').strip()
    na = norm_addr(a if a.startswith('%') or not a else '%' + a)
    if not na:
        return None
    a = na[0].lstrip('%')
    m = re.match(r'^([IQM])X(\d+\.\d+)$', a)
    return m.group(1) + m.group(2) if m else a


def _io_of(cell):
    io = cell.get('io') or []
    if io:
        return io
    try:
        from ..control.catalog import auto_io
        return auto_io(cell, keep=[])
    except Exception:                                     # noqa: BLE001
        return []


def migrate_model(model):
    if not isinstance(model, dict) or 'blocks' not in model:
        return []
    blocks = model.get('blocks') or []
    links = model.setdefault('links', [])
    used_b = {b.get('id') for b in blocks}
    used_l = {l.get('id') for l in links}
    changes = []
    for b in list(blocks):
        if b.get('type') != 'cell':
            continue
        params = b.get('params') or {}
        cell = params.get('cell')
        if not isinstance(cell, dict) or 'plc' not in cell:
            continue
        plc = cell.pop('plc') or {}
        if plc.get('mode') == 'none':
            continue
        io = _io_of(cell)
        if io and not cell.get('io'):
            cell['io'] = io
        pid = _new_id('PLC', used_b)
        size = b.get('size') or [8, 4]
        pos = b.get('pos') or [0, 0]
        blk = {'id': pid, 'type': 'plc', 'name': f"{b.get('name') or b['id']} PLC", 'pos': [round(pos[0] + size[0] / 2 + 1.5, 1), round(pos[1] - size[1] / 2 + 0.5, 1)],
               'size': [1.2, 0.6], 'rot': 0,
               'params': {'model': 'generic', 'scan_ms': plc.get('scan_ms') or 20, 'mode': plc.get('mode') or 'internal',
                          'program': copy.deepcopy(plc.get('program')) if isinstance(plc.get('program'), dict) else None,
                          'di': sum(1 for e in io if e.get('dir') == 'in' and (e.get('type') or 'BOOL') == 'BOOL'),
                          'do': sum(1 for e in io if e.get('dir') == 'out' and (e.get('type') or 'BOOL') == 'BOOL'),
                          'ai': sum(1 for e in io if e.get('dir') == 'in' and (e.get('type') or 'BOOL') != 'BOOL'),
                          'ao': sum(1 for e in io if e.get('dir') == 'out' and (e.get('type') or 'BOOL') != 'BOOL'),
                          'migrated_from': b['id']}}
        if plc.get('external'):
            blk['params']['external'] = copy.deepcopy(plc['external'])
        if b.get('area'):
            blk['area'] = b['area']
        if b.get('node'):
            blk['node'] = [b['node'][0], b['node'][1] + 170]
        hmi = cell.pop('hmi', None)
        if hmi:
            blk['params']['hmi'] = [dict(h, cell=pid) for h in hmi if isinstance(h, dict)]
        blocks.insert(blocks.index(b) + 1, blk)
        sigs = []
        for e in io:
            if not e.get('name'):
                continue
            sigs.append({'point': e['name'], 'ch': ch_of(e.get('addr')) or str(e.get('addr') or e['name']).lstrip('%'), 'dir': e.get('dir') or 'in'})
        lid = 'SIG' + pid[3:] if f'SIG{pid[3:]}' not in used_l else _new_id('SIG', used_l)
        used_l.add(lid)
        links.append({'id': lid, 'kind': 'signal', 'from': b['id'], 'to': pid, 'signals': sigs, 'all_io': True})
        changes.append(_tr('控制单元 {id} 的内置 PLC → 独立 PLC 块 {pid}（信号线 {lid}，{len} 路）', id=b['id'], pid=pid, lid=lid, len=len(sigs)))
    return changes


def plc_of_cell(plant, cell_id):
    """控制这个单元的 PLC 块（PlcStation），没有返回 None。"""
    st = plant.find(cell_id)
    if st is None:
        return None
    from .station import controllers
    ps = controllers(st)
    if ps:
        return ps[0]
    for p in plant.all_stations():                        # 还没接线（第一步之前）：按信号线找
        if getattr(p, 'kind', '') == 'plc' and cell_id in [l.get('from') for l in p.links()] + [l.get('to') for l in p.links()]:
            return p
    return None


def set_cell_program(plant, cell_id, program, run=True):
    """给控制单元下载程序（下载到控制它的 PLC 块）。返回编译结果。"""
    p = plc_of_cell(plant, cell_id)
    if p is None or p.plc is None or not hasattr(p.plc, 'load'):
        return {'ok': False, 'errors': [{'msg': _tr('{cell_id} 没有接 PLC', cell_id=cell_id)}]}
    p.wire(force=True)
    r = p.plc.load(program, cold=True, io=p.io)
    if r.get('ok'):
        p.cfg['program'] = copy.deepcopy(program)
        if run:
            p.plc.run()
    return r


def main(argv):
    from ..server import read_yaml, write_yaml
    sys.stdout.reconfigure(encoding='utf-8')
    for f in argv:
        with open(f, encoding='utf-8') as fh:
            head = []
            for line in fh:
                if not line.startswith('#'):
                    break
                head.append(line)
        m = read_yaml(f)
        ch = migrate_model(m)
        if ch:
            write_yaml(f, m)
            if head:                                      # 保留文件开头的注释
                with open(f, encoding='utf-8') as fh:
                    body = fh.read()
                with open(f, 'w', encoding='utf-8') as fh:
                    fh.write(''.join(head) + body)
        print(f, _tr('；').join(ch) or _tr('不用迁移'))


if __name__ == '__main__':
    main(sys.argv[1:])
