<template>
  <!-- Empty state when the factory has no PLCs: offer actionable next steps (banner mode uses a single-line hint) -->
  <div class="ecw">
  <div v-if="banner" class="plc-banner ecb" data-empty="cells">
    <span>{{ title || $t('emptyCells.thisFactoryHasNoPlc') }}</span>
    <button class="plc-btn pri" data-act="new-cell" @click="create()"><el-icon><Plus /></el-icon>{{ $t('emptyCells.newControlUnit') }}</button>
    <button class="plc-btn" data-act="from-scene" @click="openPicker"><el-icon><Collection /></el-icon>{{ $t('emptyCells.loadFromLabScenario') }}</button>
    <span v-if="pending.length" class="muted">{{ $t('emptyCells.n0IsAlreadyInThe', [pending.join($t('common.k360'))]) }}</span>
  </div>
  <div v-else class="ec" :class="{ compact }" data-empty="cells">
    <svg v-if="!compact" class="art" viewBox="0 0 120 70" aria-hidden="true">
      <rect x="6" y="20" width="70" height="40" rx="5" class="a1" />
      <line x1="16" y1="40" x2="66" y2="40" class="a2" />
      <rect x="30" y="34" width="12" height="12" rx="2" class="a3" />
      <circle cx="56" cy="40" r="5" class="a3" />
      <rect x="84" y="8" width="30" height="22" rx="3" class="a1" />
      <path d="M90 19h4m4 0h4m4 0h2" class="a2" />
      <path d="M80 30 L 72 36" class="a2" />
    </svg>
    <b class="t">{{ title || $t('emptyCells.thisFactoryHasNoPlc2') }}</b>
    <p class="d">{{ desc || $t('emptyCells.creatingAControlUnitAn') }}</p>
    <div class="bs">
      <button class="plc-btn pri" data-act="new-cell" @click="create()"><el-icon><Plus /></el-icon>{{ $t('emptyCells.newControlUnit') }}</button>
      <button class="plc-btn" data-act="from-scene" @click="openPicker"><el-icon><Collection /></el-icon>{{ $t('emptyCells.loadFromLabScenario') }}</button>
      <button v-if="sandbox" class="plc-btn" data-act="use-sandbox" @click="emit('sandbox')"><el-icon><Cpu /></el-icon>{{ $t('emptyCells.usePracticePlcNoEquipment') }}</button>
    </div>
    <p v-if="pending.length" class="pend">{{ $t('emptyCells.n0IsAlreadyInThe2', [pending.join($t('common.k360'))]) }}</p>

  </div>
    <el-dialog v-model="picker" :title="$t('emptyCells.loadControlUnitFromLab')" width="680px" append-to-body>
      <div class="sc-list">
        <div v-if="!scenes.length" class="muted pad">{{ $t('emptyCells.loadingScenarioLibrary') }}</div>
        <div v-for="s in scenes" :key="s.id" class="sc" :class="{ on: pick === s.id }" @click="pick = s.id" @dblclick="loadScene(s.id)">
          <span class="lv">{{ s.level ?? '' }}</span>
          <div class="sc-b"><b>{{ s.name }}</b><small>{{ s.desc }}</small>
            <small class="muted">{{ $t('details.n0Components1IO', [s.comp_count, s.io_count]) }}<template v-if="s.has_ld"> {{ $t('emptyCells.includesALadderDiagramReference') }}</template></small></div>
        </div>
      </div>
      <template #footer>
        <el-button @click="picker = false">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!pick" data-act="load-scene" @click="loadScene(pick)">{{ $t('emptyCells.loadIntoFactory') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { ed } from '../editor/store';
import { listScenes, newCell } from './cellActions';

const props = defineProps<{ compact?: boolean; banner?: boolean; sandbox?: boolean; title?: string; desc?: string; running?: string[] }>();
const emit = defineEmits<{ (e: 'sandbox'): void; (e: 'created', id: string): void }>();
const picker = ref(false);
const scenes = ref<any[]>([]);
const pick = ref('');
/** PLCs / control units present in the draft model but not yet in the running factory. */
const pending = computed(() => (ed.model?.blocks || []).filter((b: any) => (b.type === 'plc' || b.type === 'cell') && !(props.running || []).includes(b.id)).map((b: any) => b.name || b.id));

async function create(scene?: string) {
  const id = await newCell(scene ? { scene } : {});
  if (id) emit('created', id);
}
async function openPicker() {
  picker.value = true;
  if (!scenes.value.length) scenes.value = await listScenes();
}
async function loadScene(id: string) {
  if (!id) return;
  picker.value = false;
  await create(id);
}
</script>

<style scoped>
.ecb .plc-btn { height: 24px; font-size: 12px; }
.ec { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; padding: 28px 20px; color: var(--ld-tx); }
.ec.compact { padding: 14px 12px; align-items: stretch; text-align: left; }
.art { width: 150px; height: 88px; margin-bottom: 4px; }
.a1 { fill: var(--ld-info-bg); stroke: var(--ld-sel); stroke-width: 1.4; }
.a2 { stroke: var(--ld-sel); stroke-width: 1.6; fill: none; stroke-linecap: round; }
.a3 { fill: var(--ld-pow-bg); stroke: var(--ld-pow); stroke-width: 1.4; }
.t { font-size: 14px; }
.d { margin: 0; max-width: 460px; color: var(--ld-mu); font-size: 12px; line-height: 1.7; }
.bs { display: flex; gap: 6px; flex-wrap: wrap; justify-content: center; margin-top: 4px; }
.compact .bs { justify-content: flex-start; }
.pend { margin: 4px 0 0; padding: 6px 10px; border-radius: 5px; background: var(--ld-halt-bg); font-size: 12px; max-width: 460px; }
.sc-list { max-height: 420px; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
.sc { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border: 1px solid var(--el-border-color); border-radius: 6px; cursor: pointer; }
.sc:hover { border-color: var(--el-color-primary); }
.sc.on { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.lv { flex: none; width: 24px; height: 24px; line-height: 24px; text-align: center; border-radius: 50%; background: var(--el-fill-color-light); font-weight: 600; font-size: 12px; }
.sc-b { display: flex; flex-direction: column; gap: 2px; text-align: left; }
.sc-b small { font-size: 12px; color: var(--el-text-color-regular); }
.sc-b small.muted { color: var(--el-text-color-secondary); }
.pad { padding: 14px; }
</style>
