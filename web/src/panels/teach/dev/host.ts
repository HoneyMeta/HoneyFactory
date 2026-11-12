// Temporary panel dev entry: mount teaching/design/integration test panels without the shell for isolated debugging and Playwright checks.
//   /panels-dev.html?panel=teach-task&pid=foundry-housing
import 'element-plus/dist/index.css';
import '../../../design/tokens.css';
import '../../../design/base.css';
import * as Icons from '@element-plus/icons-vue';
import ElementPlus from 'element-plus';
import { i18n, elLocale } from '../../../i18n';
import { createApp } from 'vue';
import DevHost from './DevHost.vue';

const app = createApp(DevHost);
for (const [k, c] of Object.entries(Icons)) app.component(k, c as any);
app.use(i18n).use(ElementPlus, { locale: elLocale }).mount('#app');
