"""开发辅助：打印 GLB 的包围盒、动画名、骨骼/节点名、外部贴图引用（不依赖第三方库）。

    python tests/glbinfo.py a.glb b.glb ...
"""
import json
import struct
import sys

sys.stdout.reconfigure(encoding='utf-8')
for f in sys.argv[1:]:
    with open(f, 'rb') as fh:
        data = fh.read()
    n = struct.unpack('<I', data[12:16])[0]
    j = json.loads(data[20:20 + n])
    lo, hi = [1e9] * 3, [-1e9] * 3
    for m in j.get('meshes', []):
        for p in m['primitives']:
            a = j['accessors'][p['attributes']['POSITION']]
            lo = [min(x, y) for x, y in zip(lo, a['min'])]
            hi = [max(x, y) for x, y in zip(hi, a['max'])]
    anims = [a.get('name') for a in j.get('animations', [])]
    nodes = [nd.get('name') for nd in j.get('nodes', [])]
    imgs = [i.get('uri') for i in j.get('images', []) if i.get('uri')]
    print(f.split('\\')[-1].split('/')[-1], 'size', [round(h - l, 2) for l, h in zip(lo, hi)], 'min', [round(x, 2) for x in lo],
          'anims', anims if anims else '-', 'imgs', imgs)
    if '-v' in sys.argv[0:1] or len(sys.argv) == 2:
        print('  nodes', nodes)
