import 'element-plus/dist/index.css';
import './design/tokens.css';
import './design/base.css';
import './style.css';
import { i18n, elLocale } from './i18n';          // first: sets the UI language, <html lang> and the X-Lang header on fetch
import './theme';
import './compact';
import * as Icons from '@element-plus/icons-vue';
import ElementPlus from 'element-plus';
import { createApp } from 'vue';
import App from './App.vue';
import { router } from './router';
import { installStaleGuard } from './stale';
import { installDesign } from './design';

const app = createApp(App);
for (const [k, c] of Object.entries(Icons)) app.component(k, c as any);
installStaleGuard(app, router);                  // 4.6.2 Lazy loading fails on stale pages after a release: notify and reload once
app.use(i18n).use(ElementPlus, { locale: elLocale }).use(installDesign).use(router).mount('#app');
