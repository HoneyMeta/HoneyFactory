// 主窗口的预加载脚本（contextIsolation + sandbox）：网页里的 window.vfNative。网页（web/src/native.ts）检测到它就用系统对话框、系统通知等；
// 没有它（浏览器里的网页版、旧的 C# 启动器）一切照旧。
'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const on = (channel) => (cb) => {
  if (typeof cb !== 'function') return () => {};
  const h = (_e, v) => { try { cb(v); } catch (e) { console.error(e); } };
  ipcRenderer.on(channel, h);
  ipcRenderer.send('vf:listening', channel);          // 主进程据此知道网页能接这个事件（不能接就重新加载页面带参数）
  return () => ipcRenderer.removeListener(channel, h);
};

contextBridge.exposeInMainWorld('vfNative', {
  isNative: true,
  /** {version, electron, chrome, packaged, home, logs, userData, exe, updateUrl, closeBehaviour} */
  getAppInfo: () => ipcRenderer.invoke('vf:app-info'),
  /** 系统"打开"对话框 → 选中的文件路径数组（取消 = []）。opts: {title, filters: [{name, extensions}], multi} */
  openFileDialog: (opts) => ipcRenderer.invoke('vf:open-dialog', opts || {}),
  /** 系统"另存为"对话框并写文件 → 保存的路径（取消 = null）。opts: {defaultName, filters, data: Uint8Array | ArrayBuffer} */
  saveFileDialog: (opts) => ipcRenderer.invoke('vf:save-dialog', opts || {}),
  /** Windows 系统通知 */
  notify: (title, body) => ipcRenderer.invoke('vf:notify', { title, body }),
  closeBehaviour: {
    get: () => ipcRenderer.invoke('vf:close-behaviour', null),
    set: (v) => ipcRenderer.invoke('vf:close-behaviour', String(v)),
  },
  openLogFolder: () => ipcRenderer.invoke('vf:open-logs'),
  /** 手动检查更新 → {status: latest|available|downloaded|error|nofeed|checking, version, message} */
  checkForUpdates: () => ipcRenderer.invoke('vf:check-updates'),
  /** 任务栏角标（待交作业数，0 = 去掉） */
  setBadge: (n) => ipcRenderer.invoke('vf:badge', Number(n) || 0),
  /** 网页里有变化（交了作业、打开了工厂）：让外壳马上刷新托盘菜单和角标 */
  refresh: () => ipcRenderer.send('vf:refresh'),
  /** 4.6.2 发新版后旧页面按需加载失败：外壳换一个新的一次性令牌，重新打开当前页（web/src/stale.ts） */
  reload: () => ipcRenderer.send('vf:reload'),
  onDeepLink: on('vf:deep-link'),        // {action, file?, plant?, path?, url}
  onOpenFile: on('vf:open-file'),        // 文件路径（双击 .vfhw / .vfplant，或拖到程序图标上）
  onNavigate: on('vf:navigate'),         // 站内路径（托盘"最近的工厂"、"设置"）
});
