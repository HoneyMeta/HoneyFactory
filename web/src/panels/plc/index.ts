// Register PLC panels (auto-loaded by shell web/src/editor/shell/panels.ts). Component props: { pid, bid? }.
// 4.3: bid = PLC block ID; a PLC-controlled equipment (control unit) ID or HMI block ID also resolves to its PLC (plc-hmi shows the HMI screen when given an HMI block).
// If bid is omitted, follow the PLC block selected in the Workbench (or the selected equipment's PLC).
//   plc-editor        Sidebar: PLC selection, PLC status/scan time, download/run/stop, I/O monitoring and forcing; the "Program" button opens the large floating panel
//   plc-editor-float  Floating panel: LD / ST editor, variable table, I/O monitoring, compiler messages, online monitoring (power-flow highlighting, live values, forcing, breakpoints, stepping)
//   plc-hmi           Floating panel: HMI screen configuration and runtime (buttons, switches, indicator lamps, values, bar graphs, trends)
//   plc-external      Sidebar: external PLCs (Modbus / OPC UA / S7) and signal mapping
import { $t } from '../../i18n';
import { defineAsyncComponent } from 'vue';

const A = (f: () => Promise<any>) => defineAsyncComponent(f);

export const panels = [
  { id: 'plc-editor', title: 'PLC', icon: 'Cpu', component: A(() => import('../../plc/PlcSide.vue')), workspaces: ['teach', 'debug'], place: 'left', order: 50 },
  { id: 'plc-editor-float', title: $t('common.plcProgramming'), icon: 'EditPen', component: A(() => import('../../plc/PlcWorkbench.vue')), workspaces: ['teach', 'debug'], place: 'float',
    size: [1240, 760], order: 51 },
  { id: 'plc-hmi', title: $t('plcIndex.hmiScreens'), icon: 'Monitor', component: A(() => import('../../plc/HmiPanel.vue')), workspaces: ['teach', 'debug'], place: 'float', size: [1100, 660], order: 52 },
  { id: 'plc-external', title: $t('common.externalPlc'), icon: 'Connection', component: A(() => import('../../plc/ExternalPanel.vue')), workspaces: ['debug', 'teach'], place: 'left', order: 53,
    roles: ['admin', 'engineer', 'teacher'] },
];
