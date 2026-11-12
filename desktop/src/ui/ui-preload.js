// 启动画面、关闭询问框这些外壳自己的小窗口用的预加载脚本。
'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vfUi', {
  send: (action, data) => ipcRenderer.send('vf:ui', { action, data }),
  on: (cb) => ipcRenderer.on('vf:ui-state', (_e, v) => cb(v)),
});
