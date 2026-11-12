// 面板组件测试页（tests/panels_ui.js 用，不进正式界面）。两种用法：
//   开发：VF_URL=http://127.0.0.1:8800 npx vite --config vite.panels.config.ts   → http://127.0.0.1:5183/panels-dev.html
//   构建：npx vite build --config vite.panels.config.ts（先跑主构建）→ web/dist/_panels/，由服务直接提供：http://<服务>/_panels/panels-dev.html
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

const B = process.env.VF_URL || 'http://127.0.0.1:8800';
export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === 'build' ? '/_panels/' : '/',
  server: { port: Number(process.env.VF_DEV_PORT || 5183), strictPort: true, host: '127.0.0.1',
    proxy: { '/api': B, '/ws': { target: B.replace('http', 'ws'), ws: true } } },
  build: { outDir: 'dist/_panels', emptyOutDir: true, chunkSizeWarningLimit: 3000, rollupOptions: { input: 'panels-dev.html' } },
}));
