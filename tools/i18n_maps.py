"""Content translation maps (see docs/translating-content.md).

    python tools/i18n_maps.py            list content files whose map misses texts (or has stale entries)
    python tools/i18n_maps.py --sync     add missing texts with an empty translation ("" = not translated yet, shown in the
                                         source language) and drop entries whose source text is gone

Every content file <dir>/<name>.json|yaml has its English strings in <dir>/i18n/<name>.en.json = {"<source text>": "<English>"}.
Only display texts are listed: values under the keys in vfactory.i18n.CONTENT_SKIP (ids, codes, PLC source, expressions...) are never
translated. tests/i18n_check.py fails on texts that are missing from a map (and not allowlisted).
"""
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
GLOBS = ['templates/*.yaml', 'templates/cells/*.yaml', 'plants/*.yaml', 'vfactory/courses/*.json', 'vfactory/courses/plants/*.yaml',
         'vfactory/control/scenes/*.json', 'vfactory/teach/tours/*.json', 'vfactory/samples/*.json', 'vfactory/samples/*.yaml']


def texts(d):
    from vfactory.i18n import CJK, CONTENT_SKIP
    out = []

    def walk(x, key=None):
        if isinstance(x, str):
            if x[:1] in '[{':                    # JSON stored as a string (sample experiments): its texts
                try:
                    return walk(json.loads(x), key)
                except ValueError:
                    pass
            if key not in CONTENT_SKIP and CJK.search(x):
                out.append(x)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
    walk(d)
    return list(dict.fromkeys(out))


def main():
    import yaml
    from vfactory.i18n import content_map_path
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    sync = '--sync' in sys.argv
    total_missing = 0
    for g in GLOBS:
        for p in sorted(glob.glob(os.path.join(REPO, g))):
            with open(p, encoding='utf-8') as f:
                d = json.load(f) if p.endswith('.json') else yaml.safe_load(f)
            ts = texts(d)
            mp = content_map_path(p)
            m = {}
            if os.path.exists(mp):
                with open(mp, encoding='utf-8') as f:
                    m = json.load(f)
            missing = [t for t in ts if not m.get(t)]
            stale = [k for k in m if k not in ts]
            if not missing and not stale:
                continue
            total_missing += len(missing)
            print(f'{os.path.relpath(p, REPO)}: {len(missing)} missing, {len(stale)} stale')
            if sync and ts:
                new = {t: m.get(t, '') for t in ts}
                os.makedirs(os.path.dirname(mp), exist_ok=True)
                with open(mp, 'w', encoding='utf-8', newline='\n') as f:
                    json.dump(new, f, ensure_ascii=False, indent=1)
    print('missing texts:', total_missing)


if __name__ == '__main__':
    main()
