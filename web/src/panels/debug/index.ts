// Register integration test panels: console (tag table, connection and communication faults, messages, test scripts).
// Register the same component twice: compact sidebar debug-console (open by default in the integration test workspace) and large floating panel debug-console-float.
import { $t } from '../../i18n';
import { defineAsyncComponent } from 'vue';

const A = (f: () => Promise<any>) => defineAsyncComponent(f);
const Console = A(() => import('./DebugConsole.vue'));

export const panels = [
  { id: 'debug-console', title: $t('debugIndex.integrationTestConsole'), icon: 'Connection', component: Console, workspaces: ['debug'], place: 'left', order: 80, roles: ['admin', 'engineer', 'viewer'] },
  { id: 'debug-console-float', title: $t('debugIndex.integrationTestConsoleLargeWindow'), icon: 'Monitor', component: Console, workspaces: ['debug'], place: 'float', size: [1100, 720], order: 81,
    roles: ['admin', 'engineer', 'viewer'] },
];
