"""5.0.1 只有浅色（和蜂元 MES 同一套设计系统）：源码和构建产物里不能再有深色主题。

查的东西：
- 网页源码（web/src）：html.dark / .ed.dark / .plc-root.dark 这类深色样式、Element Plus 深色变量（theme-chalk/dark）、
  主题切换（setTheme / toggleTheme / applyTheme / ed.theme / brand.dark）、读写 vf_theme / mes_theme（theme.ts 里删除旧记录的除外）、
  prefers-color-scheme: dark、?theme=dark。
- 构建好的网页（web/dist，有的话）：CSS 里没有 html.dark 选择器、没有 Element Plus 深色变量文件的内容。
- 命令面板里没有"切换深色 / 浅色"。
用法：python tests/light_only_check.py
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'web', 'src')
DIST = os.path.join(ROOT, 'web', 'dist')
res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'  {detail}'))


PATTERNS = [
    ('深色样式选择器 html.dark / .dark', re.compile(r'html\.dark|\.ed\.dark|\.plc-root\.dark|:root\.dark|\[data-theme=["\']?dark')),
    ('Element Plus 深色变量', re.compile(r'theme-chalk/dark')),
    ('主题切换函数', re.compile(r'\b(setTheme|toggleTheme|applyTheme)\s*\(')),
    ('工作台主题状态 ed.theme', re.compile(r'\bed\.theme\b|\(ed as any\)\.theme')),
    ('品牌素材按深色挑图 brand.dark', re.compile(r'brand\.dark\b')),
    ('系统深色偏好', re.compile(r'prefers-color-scheme:\s*dark')),
    ('?theme=dark 参数', re.compile(r'theme=dark')),
    ('切换 <html class="dark">', re.compile(r"classList\.(toggle|add)\(\s*['\"]dark['\"]")),
]
THEME_STORE = re.compile(r"""(get|set)Item\(\s*['"](vf_theme|mes_theme)['"]""")
hits = {name: [] for name, _ in PATTERNS}
store_hits = []
files = 0
for dp, dns, fns in os.walk(SRC):
    dns[:] = [d for d in dns if d not in ('node_modules', 'dist')]
    for fn in fns:
        if not fn.endswith(('.ts', '.vue', '.css', '.js', '.html')):
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT).replace('\\', '/')
        files += 1
        with open(p, encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, 1):
                code = line.split('//')[0] if fn.endswith(('.ts', '.js')) else line
                for name, rx in PATTERNS:
                    if rx.search(code):
                        hits[name].append(f'{rel}:{i}')
                if THEME_STORE.search(code) and not rel.endswith('web/src/theme.ts'):
                    store_hits.append(f'{rel}:{i}')
ok(f'扫了足够多的网页源码文件（{files} 个）', files > 150, files)
for name, _ in PATTERNS:
    ok(f'源码里没有{name}', not hits[name], ' '.join(hits[name][:8]))
ok('源码里不再读写 vf_theme / mes_theme（只有 theme.ts 删除旧记录）', not store_hits, ' '.join(store_hits[:8]))

ui = os.path.join(ROOT, 'desktop', 'src', 'ui')
dk = [fn for fn in (os.listdir(ui) if os.path.isdir(ui) else []) if fn.endswith('.html') and re.search(r'prefers-color-scheme:\s*dark', open(os.path.join(ui, fn), encoding='utf-8').read())]
ok('客户端自己的小窗口（关闭确认、启动画面）也只有浅色', not dk, ' '.join(dk))

theme_ts = os.path.join(SRC, 'theme.ts')
txt = open(theme_ts, encoding='utf-8').read() if os.path.exists(theme_ts) else ''
ok('theme.ts 把以前存的深色设置悄悄迁移成浅色', 'removeItem' in txt and 'vf_theme' in txt and "classList.remove('dark')" in txt)
main = open(os.path.join(SRC, 'main.ts'), encoding='utf-8').read()
ok('main.ts 引入设计令牌、基础样式和迁移', all(k in main for k in ("./design/tokens.css", "./design/base.css", "./theme")))
tokens = open(os.path.join(SRC, 'design', 'tokens.css'), encoding='utf-8').read()
ok('设计令牌是钴蓝主色（和蜂元 MES 一致）', '--hm-primary: #1463d6' in tokens and '--el-color-primary: #1463d6' in tokens)

wb = os.path.join(SRC, 'commands', 'workbench.ts')
ok('命令面板没有"切换深色 / 浅色"', '深色' not in open(wb, encoding='utf-8').read() if os.path.exists(wb) else True)

if os.path.isdir(os.path.join(DIST, 'assets')):
    bad = []
    n = 0
    for fn in os.listdir(os.path.join(DIST, 'assets')):
        if fn.endswith('.css'):
            n += 1
            s = open(os.path.join(DIST, 'assets', fn), encoding='utf-8', errors='replace').read()
            if re.search(r'html\.dark|\.ed\.dark|\.plc-root\.dark', s):
                bad.append(fn)
    # 构建目录会留最近两次构建的旧文件（vite.config.ts keepRecentAssets）：只看最近一次构建的（dist/.vf-builds.json）
    try:
        import json
        last = set(os.path.basename(f) for f in json.load(open(os.path.join(DIST, '.vf-builds.json'), encoding='utf-8'))['builds'][-1]['files'])
    except Exception:                       # noqa: BLE001  没有清单：全部算
        last = None
    cur = [b for b in bad if last is None or b in last]
    ok(f'最近一次构建的样式里没有深色选择器（{n} 个 CSS 文件）', not cur, ' '.join(cur))
else:
    print('（没有 web/dist，跳过构建产物检查）')

n_ok = sum(1 for _, c in res if c)
print(f'\n{n_ok}/{len(res)} 通过')
sys.exit(0 if n_ok == len(res) else 1)
