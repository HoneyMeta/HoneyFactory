"""logo.png → 多尺寸 .ico（启动器图标、作业包图标）。用法：python make_icon.py logo.png out.ico"""
import sys

from PIL import Image

src, out = sys.argv[1], sys.argv[2]
im = Image.open(src).convert('RGBA')
bbox = im.getbbox()                     # 去掉透明边
if bbox:
    im = im.crop(bbox)
side = max(im.size)
sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
sq = sq.resize((256, 256), Image.LANCZOS)
sq.save(out, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
print('icon', out)
