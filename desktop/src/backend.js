// 本机 Python 服务（python -m vfactory desktop）：启动、等就绪、换一次性令牌、轮询外壳用的信息、退出时连同子进程一起结束。
// 服务写出 <home>\run.json {port, pid, token, key, …}：token 是一次性的（窗口用它换会话），key 只给外壳用（x-vf-key 请求头）。
'use strict';
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');
const { EventEmitter } = require('events');

function pidAlive(pid) {
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

/** 本机 HTTP 请求（不走代理）。返回 {status, body(解析过的 JSON 或文本)}。 */
function request(port, method, p, { key, body, timeout = 5000 } = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body));
    const req = http.request({ host: '127.0.0.1', port, method, path: p, timeout,
      headers: { ...(key ? { 'x-vf-key': key } : {}), ...(data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {}) } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const s = Buffer.concat(chunks).toString('utf-8');
        let j = s;
        try { j = JSON.parse(s); } catch { /* 文本 */ }
        resolve({ status: res.statusCode, body: j });
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Backend extends EventEmitter {
  /**
   * @param {object} o  python（解释器）、entry（脚本，空 = -m vfactory）、cwd、home（数据目录）、log（写日志的函数）
   */
  constructor(o) {
    super();
    this.o = o;
    this.child = null;
    this.info = null;        // run.json
    this.owned = false;      // 是不是这个外壳起的（接管已经在运行的服务时为 false，退出时不结束它）
    this.stopping = false;
    this.runJson = path.join(o.home, 'run.json');
  }

  readRun() {
    try { return JSON.parse(fs.readFileSync(this.runJson, 'utf-8')); } catch { return null; }
  }

  async healthy(port) {
    try {
      const r = await request(port, 'GET', '/api/health', { timeout: 3000 });
      return r.status === 200 && r.body && r.body.desktop === true;
    } catch { return false; }
  }

  /** 启动（或接管同一数据目录下已经在运行的服务）。progress(text) 给启动画面。 */
  async start(progress = () => {}) {
    this.stopping = false;
    const old = this.readRun();
    if (old && old.port && pidAlive(old.pid) && (await this.healthy(old.port))) {
      this.o.log(`接管已在运行的本地服务 pid=${old.pid} 端口 ${old.port}`);
      this.info = old; this.owned = false; this.child = null;
      const t = await this.ticket().catch(() => null);
      if (t) { this.info = { ...old, token: t }; return this.info; }
      this.o.log('接管失败（key 对不上），另起一个');
    }
    try { fs.rmSync(this.runJson, { force: true }); } catch { /* */ }
    fs.mkdirSync(path.join(this.o.home, 'logs'), { recursive: true });
    const args = [...(this.o.entry ? [this.o.entry] : ['-m', 'vfactory']), 'desktop', '--port', String(this.o.port || 0), '--home', this.o.home,
      '--watch-pid', String(process.pid)];
    const env = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONNOUSERSITE: '1', PYTHONUTF8: '1' };
    for (const k of ['PYTHONHOME', 'PYTHONPATH', 'VF_HOME', 'ELECTRON_RUN_AS_NODE']) delete env[k];
    this.o.log(`启动本地服务：${this.o.python} ${args.join(' ')}（目录 ${this.o.cwd}）`);
    const out = fs.openSync(path.join(this.o.home, 'logs', 'backend-console.log'), 'a');
    const child = spawn(this.o.python, args, { cwd: this.o.cwd, env, windowsHide: true, stdio: ['ignore', out, out] });
    fs.closeSync(out);
    this.child = child; this.owned = true;
    let exited = null;
    child.on('error', (e) => { exited = { code: -1, error: e.message }; });
    child.on('exit', (code, signal) => {
      exited = exited || { code, signal };
      this.o.log(`本地服务退出 code=${code} signal=${signal || ''}`);
      if (this.child === child) this.child = null;
      if (!this.stopping) this.emit('died', exited);
    });
    progress('启动本地服务…');
    const t0 = Date.now();
    while (Date.now() - t0 < (this.o.timeoutMs || 240000)) {
      if (exited) throw new Error(exited.error ? `本地服务没能启动：${exited.error}` : `本地服务启动失败（退出码 ${exited.code}）`);
      const r = this.readRun();
      if (r && r.pid === child.pid && r.port && (await this.healthy(r.port))) {
        this.info = r;
        this.o.log(`本地服务就绪 端口 ${r.port}（${((Date.now() - t0) / 1000).toFixed(1)} 秒）`);
        return r;
      }
      await sleep(300);
    }
    throw new Error('本地服务 4 分钟内没有就绪');
  }

  get port() { return this.info && this.info.port; }
  get base() { return `http://127.0.0.1:${this.port}`; }

  async call(method, p, body, timeout) {
    if (!this.info) throw new Error('本地服务没在运行');
    const r = await request(this.info.port, method, p, { key: this.info.key, body, timeout });
    if (r.status !== 200) throw new Error(`${p} → ${r.status} ${typeof r.body === 'object' ? r.body.detail || '' : ''}`);
    return r.body;
  }

  /** 新的一次性令牌（再开窗口、重新加载页面）。 */
  async ticket() { return (await this.call('POST', '/api/desktop/ticket', {})).token; }

  /** 外壳用的信息：模式、服务器、最近的工厂、待交作业数、通知事件、更新地址。 */
  native(since = 0) { return this.call('GET', `/api/desktop/native?since=${since}`, undefined, 4000); }

  /** 结束本地服务：先请它自己退出，等几秒，不行就连同子进程强制结束。 */
  async stop() {
    this.stopping = true;
    const child = this.child;
    if (!this.owned || !child) { this.info = null; return; }
    const pid = child.pid;
    const kids = await descendants(pid).catch(() => []);
    try { await this.call('POST', '/api/desktop/shutdown', {}, 2000); } catch { /* 已经不响应了 */ }
    const t0 = Date.now();
    while (pidAlive(pid) && Date.now() - t0 < 6000) await sleep(150);
    if (pidAlive(pid)) {
      this.o.log('本地服务没有按时退出，强制结束（含子进程）');
      await killTree(pid);
    }
    for (const k of kids) if (pidAlive(k)) { try { process.kill(k); } catch { /* */ } }
    this.child = null; this.info = null;
  }
}

/** 某进程的所有子孙进程（Windows：查 Win32_Process 的父进程号）。 */
function descendants(root) {
  return new Promise((resolve) => {
    if (process.platform !== 'win32') return resolve([]);
    const ps = 'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId)" }';
    execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps], { windowsHide: true, timeout: 8000 }, (err, stdout) => {
      if (err) return resolve([]);
      const kids = {};
      for (const line of String(stdout).split(/\r?\n/)) {
        const [p, pp] = line.trim().split(/\s+/).map(Number);
        if (p && pp !== undefined) (kids[pp] = kids[pp] || []).push(p);
      }
      const out = [], q = [root];
      while (q.length) for (const k of kids[q.shift()] || []) if (!out.includes(k) && k !== root) { out.push(k); q.push(k); }
      resolve(out);
    });
  });
}

function killTree(pid) {
  return new Promise((resolve) => {
    if (process.platform !== 'win32') { try { process.kill(pid, 'SIGKILL'); } catch { /* */ } return resolve(); }
    execFile('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, timeout: 10000 }, () => resolve());
  });
}

module.exports = { Backend, request, pidAlive, killTree };
