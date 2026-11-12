// 自动更新（electron-updater，generic 提供方）。更新地址：连着的服务器 <服务器>/api/client/update/（vfactory/client_update.py），
// 没连服务器时用配置文件里的地址（<数据目录>\electron\update.json、安装目录 resources\update.json 的 {"url": "…"}，环境变量 VF_UPDATE_URL 优先）。
// 联网模式：启动后检查一次、之后每 6 小时；后台下载；下好后问"现在重启更新 / 下次启动时"。单机模式只在手动"检查更新"时查。
'use strict';
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

const SIX_HOURS = 6 * 3600 * 1000;

class Updater {
  /** @param {object} o  log、notify(title, body)、ask(info) → Promise<boolean 现在重启>、beforeInstall() → Promise、configDirs[]、feedFromBackend() → Promise<string> */
  constructor(o) {
    this.o = o;
    this.state = { status: 'idle', version: null, message: '', url: '' };
    this.u = null;
    this.timer = null;
    this.asked = false;
  }

  lib() {
    if (this.u) return this.u;
    const { autoUpdater } = require('electron-updater');
    const u = autoUpdater;
    u.autoDownload = process.env.VF_UPDATE_NO_DOWNLOAD !== '1';
    u.autoInstallOnAppQuit = true;                    // "下次启动时"：退出时装好，下次打开就是新版
    u.allowDowngrade = false;
    u.forceDevUpdateConfig = !app.isPackaged;         // 开发版也能测（版本号取 desktop/package.json）
    u.logger = { info: (m) => this.o.log('[update] ' + m), warn: (m) => this.o.log('[update] ' + m), error: (m) => this.o.log('[update] ' + m), debug: () => {} };
    u.on('checking-for-update', () => this.set('checking', '正在检查更新…'));
    u.on('update-not-available', (i) => this.set('latest', `已是最新版本（${app.getVersion()}）`, i && i.version));
    u.on('update-available', (i) => {
      this.set('available', `有新版本 ${i.version}${u.autoDownload ? '，正在后台下载' : ''}`, i.version);
      this.o.notify('有新版本', `蜂元虚拟工厂 ${i.version} 正在后台下载，下好后提示你重启更新。`);
    });
    u.on('download-progress', (p) => { this.state.percent = Math.round(p.percent || 0); });
    u.on('error', (e) => this.set('error', '检查更新失败：' + ((e && e.message) || e).toString().split('\n')[0]));
    u.on('update-downloaded', async (i) => {
      this.set('downloaded', `新版本 ${i.version} 已下载`, i.version);
      if (this.asked || process.env.VF_UPDATE_NO_PROMPT === '1') return;   // 测试：不弹"现在重启更新"，由测试自己装
      this.asked = true;
      const now = await this.o.ask(i);
      if (now) {
        await this.o.beforeInstall();
        u.quitAndInstall(false, true);
      }
    });
    this.u = u;
    return u;
  }

  set(status, message, version) {
    this.state = { ...this.state, status, message, version: version || this.state.version, at: Date.now() };
    this.o.log(`[update] ${status} ${message}`);
  }

  /** 配置文件里的更新地址（不连服务器时用）。 */
  configUrl() {
    if (process.env.VF_UPDATE_URL) return process.env.VF_UPDATE_URL;
    for (const d of this.o.configDirs) {
      try {
        const j = JSON.parse(fs.readFileSync(path.join(d, 'update.json'), 'utf-8'));
        if (j && j.url) return String(j.url);
      } catch { /* 没有 */ }
    }
    return '';
  }

  async feed() {
    if (process.env.VF_UPDATE_URL) return process.env.VF_UPDATE_URL;
    const s = await this.o.feedFromBackend().catch(() => '');
    return s || this.configUrl();
  }

  /** manual：托盘/设置里点"检查更新"。返回状态（给页面和测试）。 */
  async check(manual = false) {
    const url = await this.feed();
    if (!url) {
      this.set('nofeed', '没有更新地址：单机使用时请在服务器管理员处获取新版安装包，或在 update.json 里配置更新地址');
      return this.state;
    }
    const u = this.lib();
    u.setFeedURL({ provider: 'generic', url: url.endsWith('/') ? url : url + '/', channel: 'latest' });
    this.state.url = url;
    try {
      await u.checkForUpdates();
    } catch (e) {
      this.set('error', '检查更新失败：' + String((e && e.message) || e).split('\n')[0]);
    }
    if (manual) this.asked = false;                   // 手动检查：下好了就再问一次
    return this.state;
  }

  /** 自动检查：只在联网模式（有服务器）或配置了地址时，启动后一次、之后每 6 小时。 */
  schedule(isServerMode) {
    clearInterval(this.timer);
    const run = async () => {
      if (!(await isServerMode()) && !process.env.VF_UPDATE_URL) return;
      await this.check(false);
    };
    setTimeout(run, Number(process.env.VF_UPDATE_DELAY_MS || 15000));
    this.timer = setInterval(run, SIX_HOURS);
  }
}

module.exports = { Updater };
