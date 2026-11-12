// PLC 模块组件测试页（tests/plc_ui.js 用，不进正式构建）：npx vite --config vite.plc.config.ts，打开 /plc-dev.html?pid=<工厂>&view=workbench|side|hmi|ext
// 接口代理到 PLC_API（默认 http://127.0.0.1:8820，PLC 助手在 B 机的副本）。
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

const API = process.env.PLC_API || 'http://127.0.0.1:8820';
export default defineConfig({
  plugins: [vue()],
  build: { outDir: 'dist-plc', rollupOptions: { input: 'plc-dev.html' }, chunkSizeWarningLimit: 4000 },
  server: { port: Number(process.env.PLC_DEV_PORT || 5182), strictPort: true, proxy: { '/api': API, '/ws': { target: API.replace('http', 'ws'), ws: true } } },
});
