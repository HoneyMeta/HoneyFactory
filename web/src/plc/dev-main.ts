// PLC module self-test entry point (only used by the vite.plc.config.ts dev server; see web/plc-dev.html).
import 'element-plus/dist/index.css';
import '../design/tokens.css';
import '../design/base.css';
import '../style.css';
import '../editor/editor.css';
import * as Icons from '@element-plus/icons-vue';
import ElementPlus from 'element-plus';
import { i18n, elLocale } from '../i18n';
import { createApp } from 'vue';
import DevPage from './DevPage.vue';

const app = createApp(DevPage);
for (const [k, c] of Object.entries(Icons)) app.component(k, c as any);
app.use(i18n).use(ElementPlus, { locale: elLocale }).mount('#app');
