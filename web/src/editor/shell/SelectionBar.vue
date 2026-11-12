<template>
  <div v-if="b && !ed.placing && !ed.pick" class="selbar">
    <i class="selbar-ly" :style="{ background: color }" /><b>{{ b.name }}</b><small class="muted">{{ t.label }}</small>
    <span class="selbar-sep" />
    <el-tooltip v-for="a in actions" :key="a.label" :content="a.tip || a.label" :show-after="300">
      <el-button size="small" text :type="a.danger ? 'danger' : ''" :data-tour="a.k ? 'sel-' + a.k : undefined" @click="a.run"><el-icon><component :is="a.icon" /></el-icon><span v-if="!a.iconOnly">&nbsp;{{ a.label }}</span></el-button>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Floating toolbar above the canvas when an object is selected (4.3): name + 4–5 common type-specific actions; full actions are in the right Objects panel and context menu.
import { computed } from 'vue';
import { canEdit } from '../../api';
import { askAssistant } from '../../assistant';
import { blocksById, ed, openFloat, removeSelected, typeOf } from '../store';
import { toggleDefaultBp } from './graphdebug';
import { panelById } from './panels';
import { relationsOf } from './relations';
import { addNetwork, addPlcControl } from './wiring';

const b = computed(() => (ed.sel.length === 1 ? blocksById.value[ed.sel[0]] : null));
const t = computed(() => typeOf(b.value));
const layer = computed(() => t.value.layer || 'process');
const color = computed(() => ed.cat?.layers?.[layer.value]?.color || '#888');
const actions = computed(() => {
  const x = b.value; if (!x) return [];
  const edit = canEdit() && !ed.modelLocked, out: any[] = [];
  out.push({ label: $t('common.attribute'), icon: 'EditPen', run: () => { ed.rightTab = 'props'; } });
  if (layer.value === 'process') {
    if (edit) out.push({ k: 'addplc', label: relationsOf(x.id).plcs.length ? $t('selectionBar.connectAnotherPlc') : $t('common.addPlc'), icon: 'Cpu', tip: $t('selectionBar.createAPlcNearbyTo'), run: () => addPlcControl(x.id) });
    const plc = relationsOf(x.id).plcs[0];
    if (plc) out.push({ k: 'prog', label: $t('common.program2'), icon: 'Monitor', tip: $t('selectionBar.openTheProgramOfThe'), run: () => { const p = panelById('plc-editor-float'); if (p) openFloat(p as any, { bid: plc }, plc); } });
    if (x.type === 'cell') out.push({ label: $t('common.operatorPanel'), icon: 'Operation', tip: $t('selectionBar.startStopAndEStop'), run: () => import('../../panels/cell/state').then((m) => { m.cs.bid = x.id; m.openConsole(true); }) });
    out.push({ label: $t('common.breakpoint'), icon: 'Flag', tip: $t('selectionBar.toggleBreakpointF9'), run: () => toggleDefaultBp([x.id]) });
  } else if (x.type === 'plc') {
    out.push({ k: 'prog', label: $t('common.program2'), icon: 'Monitor', run: () => { const p = panelById('plc-editor-float'); if (p) openFloat(p as any, { bid: x.id }, x.id); } });
    if (edit) out.push({ label: $t('archView.connectToNetwork'), icon: 'Connection', run: () => addNetwork(x.id) });
  } else if (edit) out.push({ label: $t('archView.connectToNetwork'), icon: 'Connection', run: () => addNetwork(x.id) });
  out.push({ label: $t('common.askAi'), icon: 'ChatDotRound', iconOnly: true, run: () => askAssistant($t('selectionBar.howIs01Doing', [x.name, x.id])) });
  if (edit) out.push({ label: $t('common.delete'), icon: 'Delete', iconOnly: true, danger: true, run: removeSelected });
  return out;
});
</script>

<style>
.selbar { position: absolute; z-index: 20; left: 64px; bottom: 14px; display: flex; align-items: center; gap: 4px; padding: 3px 6px 3px 10px;
  border-radius: var(--hm-r-pill); background: var(--hm-glass-strong); backdrop-filter: var(--hm-glass-blur); border: 1px solid var(--hm-border); box-shadow: var(--hm-e3); white-space: nowrap; max-width: calc(100% - 380px); overflow: hidden; }
.selbar-ly { width: 10px; height: 10px; border-radius: 3px; } .selbar b { max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.selbar-sep { width: 1px; height: 18px; background: var(--ln); margin: 0 4px; } .selbar .el-button + .el-button { margin-left: 0; }
</style>
