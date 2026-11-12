<template>
  <el-dialog v-model="ui.shortcuts" :title="$t('common.keyboardShortcuts')" width="min(680px, 94vw)" append-to-body>
    <div class="kb" data-k="shortcuts">
      <div v-for="g in GROUPS" :key="g[0]" class="kb-g">
        <div class="kb-h">{{ g[0] }}</div>
        <div v-for="k in g[1]" :key="k[0]" class="kb-r"><span class="kb-k"><kbd v-for="x in k[0].split(' ')" :key="x">{{ x }}</kbd></span><span>{{ k[1] }}</span></div>
      </div>
      <p class="muted small">{{ $t('shortcutsDialog.pressCtrlInTheWorkbench') }}</p>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ui } from '../start/ui';

const GROUPS: [string, [string, string][]][] = [
  [$t('shortcutsDialog.anyPage'), [['Ctrl+K', $t('shortcutsDialog.commandPaletteSearchPagesFactories')], ['F1', $t('shortcutsDialog.openHelpForTheCurrent')], ['Esc', $t('shortcutsDialog.closeDialogsCommandPaletteOr')]]],
  [$t('shortcutsDialog.workbenchRun'), [[$t('shortcutsDialog.space'), $t('shortcutsDialog.runPause')], ['F5 F6', $t('shortcutsDialog.runPause')], ['F10', $t('workbench.stepToNextEvent')], ['F9', $t('shortcutsDialog.toggleABreakpointOnThe')]]],
  [$t('shortcutsDialog.workbenchViews'), [['Alt+1 Alt+2 Alt+3 Alt+4', $t('shortcutsDialog.n3dGraphFloorPlanArchitecture')], ['Ctrl+F', $t('common.findEquipmentPlcChannelsOr')], ['F', $t('common.focusOnSelectedEquipment')], ['Home', $t('common.fitAll')], ['Alt+← Alt+→', $t('shortcutsDialog.goBackForwardBetweenRelated')]]],
  [$t('shortcutsDialog.workbenchEdit'), [['Ctrl+Z Ctrl+Y', $t('shortcutsDialog.undoRedo')], ['Ctrl+C Ctrl+V Ctrl+D', $t('shortcutsDialog.copyPasteDuplicate')], ['Delete', $t('common.deleteSelected')], ['Ctrl+A', $t('common.selectAll')], ['Ctrl+G', $t('common.group')], ['Ctrl+S', $t('common.saveVersion')], ['Tab', $t('shortcutsDialog.searchForEquipmentToAdd')]]],
];
</script>

<style scoped>
.kb { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 22px; }
.kb > p { grid-column: 1 / -1; margin: 6px 0 0; }
.kb-g { margin-bottom: 8px; } .kb-h { font-weight: 600; font-size: 13px; margin: 4px 0 6px; color: var(--el-text-color-primary); }
.kb-r { display: flex; gap: 10px; align-items: baseline; padding: 4px 0; font-size: 12.5px; border-bottom: 1px dashed var(--el-border-color-lighter); }
.kb-k { flex: none; display: inline-flex; gap: 3px; flex-wrap: wrap; min-width: 120px; }
kbd { font-family: var(--hm-font-mono); font-size: 11px; line-height: 18px; padding: 0 5px; border-radius: 4px; border: 1px solid var(--el-border-color); border-bottom-width: 2px; background: var(--el-fill-color-light); }
@media (max-width: 700px) { .kb { grid-template-columns: 1fr; } }
</style>
