// 外壳自己的设置（窗口位置、关闭按钮的行为、提示过没有），存在 <userData>\native.json。和本地服务的设置（desktop.json）分开。
'use strict';
const fs = require('fs');
const path = require('path');

const DEFAULTS = {
  closeBehaviour: 'ask',        // ask = 第一次关窗时问；tray = 最小化到托盘；quit = 退出
  trayNotified: false,          // 第一次缩到托盘时提示过了
  window: null,                 // {x, y, width, height, maximized}
  lastUpdateCheck: 0,
};

class Prefs {
  constructor(dir) {
    this.file = path.join(dir, 'native.json');
    this.data = { ...DEFAULTS };
    try { Object.assign(this.data, JSON.parse(fs.readFileSync(this.file, 'utf-8'))); } catch { /* 第一次 */ }
    if (!['ask', 'tray', 'quit'].includes(this.data.closeBehaviour)) this.data.closeBehaviour = 'ask';
  }
  get(k) { return this.data[k]; }
  set(k, v) { this.data[k] = v; this.save(); }
  save() {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.writeFileSync(this.file + '.tmp', JSON.stringify(this.data, null, 1));
      fs.renameSync(this.file + '.tmp', this.file);
    } catch { /* 写不了就算了（只读目录），下次再问 */ }
  }
}

module.exports = { Prefs };
