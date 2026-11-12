"""Electron 客户端的图片资源：把 desktop/build/ 里美术给的文件拷到输出目录，缺的用 logo.png 生成占位图。

    python make_placeholders.py <desktop/build> <logo.png> <输出目录>

文件（和美术约定的名字、尺寸）：icon.ico（多尺寸）、icon.png（256）、tray-16/32.png、tray-dark-16/32.png（深色任务栏用的浅色图标）、
splash.png（640×400 启动画面）、installerSidebar.bmp（164×314，安装/卸载向导左侧）、installerHeader.bmp（150×57，向导右上角）。
打印每个文件是"美术"还是"占位"。
"""
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

src_dir, logo_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
BG, ACCENT = (30, 35, 41), (242, 201, 76)


def logo(size):
    im = Image.open(logo_path).convert('RGBA')
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    side = max(im.size)
    sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return sq.resize((size, size), Image.LANCZOS)


def font(px):
    for f in (r'C:\Windows\Fonts\msyhbd.ttc', r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf'):
        if os.path.exists(f):
            return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def light_glyph(size):
    """深色任务栏用：logo 变成浅色剪影。"""
    im = logo(size)
    a = im.split()[3]
    w = Image.new('RGBA', im.size, (240, 240, 240, 255))
    w.putalpha(a)
    return w


def splash(p):
    im = Image.new('RGB', (640, 400), BG)
    d = ImageDraw.Draw(im)
    for y in range(400):                                  # 竖向渐变
        c = tuple(int(BG[i] + (12 - y / 400 * 18)) for i in range(3))
        d.line([(0, y), (640, y)], fill=c)
    lg = logo(150)
    im.paste(lg, (440, 90), lg)
    d.text((48, 118), '蜂元虚拟工厂', font=font(38), fill=(255, 255, 255))
    d.text((50, 176), '工艺模型 · 控制层 · 教学实训', font=font(15), fill=ACCENT)
    im.save(p)


def sidebar(p):
    im = Image.new('RGB', (164, 314), BG)
    lg = logo(96)
    im.paste(lg, (34, 40), lg)
    d = ImageDraw.Draw(im)
    d.text((22, 160), '蜂元虚拟工厂', font=font(19), fill=(255, 255, 255))
    d.rectangle([22, 192, 64, 195], fill=ACCENT)
    im.save(p, format='BMP')


def header(p):
    im = Image.new('RGB', (150, 57), (255, 255, 255))
    lg = logo(44)
    im.paste(lg, (100, 6), lg)
    im.save(p, format='BMP')


def make(name, p):
    if name == 'icon.ico':
        logo(256).save(p, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    elif name == 'icon.png':
        logo(256).save(p)
    elif name.startswith('tray-dark-'):
        light_glyph(int(name[10:12])).save(p)
    elif name.startswith('tray-'):
        logo(int(name[5:7])).save(p)
    elif name == 'splash.png':
        splash(p)
    elif name == 'installerSidebar.bmp':
        sidebar(p)
    elif name == 'installerHeader.bmp':
        header(p)


NAMES = ['icon.ico', 'icon.png', 'tray-16.png', 'tray-32.png', 'tray-dark-16.png', 'tray-dark-32.png', 'splash.png',
         'installerSidebar.bmp', 'installerHeader.bmp']
for n in NAMES:
    s, d = os.path.join(src_dir, n), os.path.join(out, n)
    if os.path.isfile(s):
        shutil.copyfile(s, d)
        print('美术', n)
    else:
        make(n, d)
        print('占位', n)
# 美术目录里的其他文件（以后加的）也一起拷过去
if os.path.isdir(src_dir):
    for n in os.listdir(src_dir):
        if n not in NAMES and os.path.isfile(os.path.join(src_dir, n)):
            shutil.copyfile(os.path.join(src_dir, n), os.path.join(out, n))
