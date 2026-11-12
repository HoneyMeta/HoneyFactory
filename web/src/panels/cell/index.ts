// Control cell panel registration (auto-loaded by web/src/editor/shell/panels.ts). Component props: { pid }; follows the control cell block selected in the Workbench.
//   cell-editor      Equipment interior sidebar: cell editor for control cells; control I/O panel (DeviceIo) for regular equipment. Cell editor: cell selection, component library, floor layout, component list, I/O table (auto-generate, rename, readdress, force), console / statistics / fault injection
//   cell-editor-float Floating window: large layout of the same editor (floor plan + 3D preview side by side)
//   cell-console     Floating window: cell console (large buttons, E-Stop, indicator lamps, reset); opens at the canvas bottom right when students enter a control cell sandbox
//   cell-inspector   Inspector: selected component properties, parameters, signals, and live values
// 3D rendering is in web/src/scene_ext/cell.ts (mk_cell / up_cell).
import { $t } from '../../i18n';
import { defineAsyncComponent } from 'vue';
import './state';            // Register the hook for 3D to read cell definitions from the draft

const A = (f: () => Promise<any>) => defineAsyncComponent(f);
const Editor = A(() => import('./CellEditor.vue'));

export const panels = [
  { id: 'cell-editor', title: $t('common.equipmentInterior'), icon: 'Cpu', component: Editor, workspaces: ['all', 'teach', 'debug'], place: 'left', order: 45 },
  { id: 'cell-editor-float', title: $t('cellEditor.controlCellEditor'), icon: 'Cpu', component: Editor, workspaces: ['all', 'teach', 'debug'], place: 'float', size: [1180, 760], order: 46, props: { wide: true } },
  { id: 'cell-console', title: $t('common.operatorPanel'), icon: 'Operation', component: A(() => import('./CellConsole.vue')), workspaces: ['all', 'teach', 'debug'], place: 'float', size: [600, 470], order: 46.5 },
  { id: 'cell-inspector', title: $t('common.components'), icon: 'SetUp', component: A(() => import('./CellInspector.vue')), workspaces: ['all'], place: 'inspector', order: 47 },
];
