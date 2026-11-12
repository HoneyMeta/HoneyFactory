import { defineConfig, type Plugin } from 'vite';
import vue from '@vitejs/plugin-vue';
import fs from 'node:fs';
import path from 'node:path';

// 4.6.2 发新版不打断开着的页面：构建时不清空 dist（emptyOutDir: false），旧版本按需加载的文件（assets/Outliner-xxx.js …）留着，
// 开着的旧页面还能接着加载面板。构建完只删"最近 2 次构建都没用到"的旧文件；dist/.vf-builds.json 记着每次构建的编号和文件。
// 有这个清单之前留下的文件算成"上一次构建"，下一次构建时再删。页面那边另有兜底：真拿不到文件时提示并刷新一次（src/stale.ts）。
// 打客户端安装包时（tools/build_client.ps1、build_electron.ps1）设 VF_KEEP_BUILDS=1：本机服务随客户端一起升级，不用留旧文件，安装包不变大
const KEEP_BUILDS = Math.max(1, Number(process.env.VF_KEEP_BUILDS) || 2);
function keepRecentAssets(): Plugin {
  let outDir = '';
  const id = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14) + '-' + Math.random().toString(36).slice(2, 6);
  const list = (dir: string): string[] => {
    const out: string[] = [];
    const walk = (d: string) => {
      if (!fs.existsSync(d)) return;
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) walk(p); else out.push(path.relative(outDir, p).split(path.sep).join('/'));
      }
    };
    walk(dir);
    return out;
  };
  return {
    name: 'vf-keep-recent-assets',
    apply: 'build',
    configResolved(c) { outDir = path.resolve(c.root, c.build.outDir); },
    transformIndexHtml() { return [{ tag: 'meta', attrs: { name: 'vf-build', content: id }, injectTo: 'head' }]; },
    writeBundle(_o, bundle) {
      const man = path.join(outDir, '.vf-builds.json');
      let builds: { id: string; at: string; files: string[] }[] = [];
      try { builds = JSON.parse(fs.readFileSync(man, 'utf8')).builds || []; } catch { /* 第一次 */ }
      const files = Object.keys(bundle).filter((f) => f.startsWith('assets/'));
      const known = new Set([...builds.flatMap((b) => b.files), ...files]);
      const legacy = list(path.join(outDir, 'assets')).filter((f) => !known.has(f));
      if (legacy.length) builds.push({ id: 'legacy', at: new Date().toISOString(), files: legacy });
      builds.push({ id, at: new Date().toISOString(), files });
      const keep = builds.slice(-KEEP_BUILDS);
      const keepSet = new Set(keep.flatMap((b) => b.files));
      let removed = 0;
      for (const f of list(path.join(outDir, 'assets'))) {
        if (keepSet.has(f)) continue;
        try { fs.rmSync(path.join(outDir, f)); removed++; } catch { /* 被占用：下次再删 */ }
      }
      fs.writeFileSync(man, JSON.stringify({ keep: KEEP_BUILDS, builds: keep }, null, 1));
      console.log(`[vf] 构建 ${id}：保留最近 ${keep.length} 次构建的文件，删掉 ${removed} 个更旧的`);
    },
  };
}

export default defineConfig({
  plugins: [vue(), keepRecentAssets()],
  // 构建标记：平时是空的（内容不变、文件名就不变，浏览器缓存照用）；tests/chunk_reload_ui.js 设 VF_BUILD_TAG 造一次"内容变了的新版本"
  define: { __VF_BUILD_TAG__: JSON.stringify(process.env.VF_BUILD_TAG || '') },
  base: '/',
  server: { proxy: { '/api': 'http://127.0.0.1:8800', '/ws': { target: 'ws://127.0.0.1:8800', ws: true }, '/docs': 'http://127.0.0.1:8800', '/openapi.json': 'http://127.0.0.1:8800' } },
  build: { outDir: 'dist', emptyOutDir: false, chunkSizeWarningLimit: 3000 },
});
