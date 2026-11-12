// 任务栏按钮上的角标（待交作业数）：自己画一个 32×32 的红色圆点 + 白色数字（3×5 点阵字体放大），不依赖画布。
'use strict';
const { nativeImage } = require('electron');

const FONT = {      // 3×5 点阵，每行 3 位
  0: ['111', '101', '101', '101', '111'], 1: ['010', '110', '010', '010', '111'], 2: ['111', '001', '111', '100', '111'],
  3: ['111', '001', '111', '001', '111'], 4: ['101', '101', '111', '001', '001'], 5: ['111', '100', '111', '001', '111'],
  6: ['111', '100', '111', '101', '111'], 7: ['111', '001', '010', '010', '010'], 8: ['111', '101', '111', '101', '111'],
  9: ['111', '101', '111', '001', '111'], '+': ['000', '010', '111', '010', '000'],
};

function badgeImage(count) {
  const W = 32, H = 32, buf = Buffer.alloc(W * H * 4);
  const put = (x, y, r, g, b, a = 255) => {
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const i = (y * W + x) * 4;
    buf[i] = b; buf[i + 1] = g; buf[i + 2] = r; buf[i + 3] = a;   // BGRA
  };
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const d = Math.hypot(x + 0.5 - 16, y + 0.5 - 16);
      if (d <= 15.5) put(x, y, 0xd9, 0x30, 0x25, Math.round(255 * Math.min(1, 15.5 - d + 0.5)));
    }
  }
  const text = count > 9 ? '9+' : String(count);
  const s = text.length > 1 ? 3 : 4;                               // 点阵放大倍数
  const w = text.length * 3 * s + (text.length - 1) * s, h = 5 * s;
  let x0 = Math.round((W - w) / 2);
  const y0 = Math.round((H - h) / 2);
  for (const ch of text) {
    const g = FONT[ch];
    for (let r = 0; r < 5; r++) for (let c = 0; c < 3; c++) {
      if (g[r][c] !== '1') continue;
      for (let dy = 0; dy < s; dy++) for (let dx = 0; dx < s; dx++) put(x0 + c * s + dx, y0 + r * s + dy, 255, 255, 255);
    }
    x0 += 4 * s;
  }
  return nativeImage.createFromBitmap(buf, { width: W, height: H });
}

module.exports = { badgeImage };
