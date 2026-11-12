<template>
  <!-- Read-only accounts / teacher observation: disable the entire form (Element Plus propagates disabled to all nested inputs and buttons) -->
  <el-form class="dt" :disabled="!canEdit() || ed.modelLocked" @submit.prevent>
    <div v-if="!canEdit()" class="dt-ro">{{ $t('details.readOnlyYourAccountCan') }}</div>
    <div v-else-if="ed.modelLocked" class="dt-ro">{{ $t('details.onlyThePlcProgramCan') }}</div>
    <!-- Connections -->
    <template v-if="link">
      <div class="dt-head"><el-icon class="dt-ic" style="background:#1463d6"><Share /></el-icon>
        <div><b>{{ $t('details.connection0', [link.id]) }}</b><small>{{ nameOf(link.from) }} → {{ nameOf(link.to) }}</small></div></div>
      <div class="dt-actions">
        <el-button size="small" @click="askAI"><el-icon><ChatDotRound /></el-icon> {{ $t('common.askAi') }}</el-button>
        <el-button size="small" type="danger" plain @click="removeSelected"><el-icon><Delete /></el-icon> {{ $t('common.delete') }}</el-button>
      </div>
      <div class="dt-sec">
        <div class="f"><label>{{ $t('details.start') }}</label><span class="mono">{{ link.from }} · {{ PORT_CN[link.from_port] || link.from_port }}</span></div>
        <div class="f"><label>{{ $t('details.end') }}</label><span class="mono">{{ link.to }} · {{ PORT_CN[link.to_port] || link.to_port }}</span></div>
        <div class="f"><label>{{ $t('common.transport') }}</label>
          <el-select :model-value="link.via || ''" size="small" clearable :placeholder="$t('details.directTransferNoVehicle')" @change="(v: any) => setLink({ via: v || null })">
            <el-option v-for="b in movers" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" />
          </el-select></div>
        <div class="f"><label>{{ $t('details.queueCapacity') }}</label><el-input-number :model-value="link.capacity" size="small" :min="1" :controls="false" :placeholder="$t('details.default')"
          @change="(v: any) => setLink({ capacity: v || null })" /><span class="unit">{{ $t('common.pcs') }}</span></div>
        <div class="f"><label>{{ $t('details.onlyTheseProducts') }}</label>
          <el-select :model-value="link.products || []" multiple filterable allow-create size="small" :placeholder="$t('details.allProducts')" @change="(v: any) => setLink({ products: v.length ? v : null })">
            <el-option v-for="c in productCodes" :key="c" :value="c" :label="c" />
          </el-select></div>
        <div class="f"><label>{{ $t('details.condition') }}</label><ExprInput :model-value="link.cond || ''" :placeholder="$t('details.partAttributeConditionEG')" @change="(v: any) => setLink({ cond: v || null })" /></div>
        <div class="f"><label>{{ $t('details.routingWeight') }}</label><el-input-number :model-value="link.weight" size="small" :min="0" :controls="false" placeholder="1"
          @change="(v: any) => setLink({ weight: v || null })" /></div>
        <p class="muted small">{{ $t('details.theSourceBlockSOutput') }}</p>
      </div>
    </template>

    <!-- Floor Plan layout elements (walls, zones, aisles, road network, annotations): shown when no equipment is selected (4.4, Assistant V) -->
    <template v-else-if="pv.lsel.length && !ed.sel.length">
      <LayoutProps />
    </template>

    <!-- Single block -->
    <template v-else-if="b">
      <div class="dt-head"><el-icon class="dt-ic" :style="{ background: t.color }"><component :is="t.icon" /></el-icon>
        <div><el-input v-model="nameEdit" size="small" class="dt-name" @change="(v: string) => v.trim() && set({ name: v.trim() })" />
          <small><span class="mono">{{ b.id }}</span> · {{ t.label }}<span v-if="t.legacy"> {{ $t('details.advancedModel') }}</span></small></div></div>
      <p v-if="t.help" class="muted small dt-help">{{ t.help }}</p>
      <!-- The Objects panel hides model-editing actions based on permissions; programming, operator panel, equipment internals, and Ask AI remain accessible in locked lessons (unaffected by the parent form's disabled state) -->
      <el-form class="dt-op" @submit.prevent><ObjectPanel :id="b.id" /></el-form>
      <div class="dt-actions">
        <el-button size="small" type="primary" plain @click="askAI"><el-icon><ChatDotRound /></el-icon> {{ $t('common.askAi') }}</el-button>
        <el-button size="small" @click="duplicateSel"><el-icon><CopyDocument /></el-icon> {{ $t('common.copy') }}</el-button>
        <el-button size="small" @click="emit('template')"><el-icon><Collection /></el-icon> {{ $t('details.saveTemplate') }}</el-button>
        <el-button size="small" type="danger" plain @click="removeSelected"><el-icon><Delete /></el-icon></el-button>
      </div>
      <div class="dt-mode"><span class="muted small">{{ ed.expert ? $t('details.advancedModeShowAllParameters') : $t('details.simpleModeShowCommonParameters') }}</span>
        <el-switch :model-value="ed.expert" size="small" :active-text="$t('details.advanced')" @change="setExpert" /></div>
      <el-collapse v-model="open">
        <el-collapse-item name="rt" v-if="rt">
          <template #title><span class="sec-t">{{ $t('details.runState') }} <i class="dot" :style="{ background: STATE_COLOR[rt.state] }" /> {{ STATE_CN[rt.state] || rt.state }}</span></template>
          <div v-if="rt.alarm" class="bad small">⚠ {{ rt.alarm }}</div>
          <div v-if="rt.oee" class="oee"><span>OEE <b>{{ pct(rt.oee.OEE) }}</b></span><span>{{ $t('details.availability0', [pct(rt.oee.A)]) }}</span><span>{{ $t('details.performance0', [pct(rt.oee.P)]) }}</span><span>{{ $t('details.quality0', [pct(rt.oee.Q)]) }}</span></div>
          <div v-if="rt.cap" class="small">{{ $t('details.inventory01', [rt.count, rt.cap]) }}</div>
          <div v-if="rt.power !== undefined" class="small muted">{{ $t('details.power0Kw', [rt.power]) }}</div>
          <el-button size="small" text type="primary" @click="ed.rightTab = 'live'">{{ $t('details.viewLiveDataTrendsAnd') }}</el-button>
        </el-collapse-item>
        <el-collapse-item name="layout" :title="$t('details.layout')">
          <div class="grid2">
            <div class="f"><label>X</label><el-input-number :model-value="b.pos[0]" size="small" :step="0.5" :controls="false" @change="(v: any) => set({ pos: [v, b.pos[1]] })" /><span class="unit">m</span></div>
            <div class="f"><label>Y</label><el-input-number :model-value="b.pos[1]" size="small" :step="0.5" :controls="false" @change="(v: any) => set({ pos: [b.pos[0], v] })" /><span class="unit">m</span></div>
            <div class="f"><label>{{ $t('common.length') }}</label><el-input-number :model-value="b.size[0]" size="small" :min="0.2" :controls="false" @change="(v: any) => set({ size: [v, b.size[1]] })" /><span class="unit">m</span></div>
            <div class="f"><label>{{ $t('common.width') }}</label><el-input-number :model-value="b.size[1]" size="small" :min="0.2" :controls="false" @change="(v: any) => set({ size: [b.size[0], v] })" /><span class="unit">m</span></div>
            <div class="f"><label>{{ $t('details.rotation') }}</label><el-select :model-value="b.rot || 0" size="small" @change="(v: any) => set({ rot: v })"><el-option v-for="r in [0, 90, 180, 270]" :key="r" :value="r" :label="r + '°'" /></el-select></div>
            <div class="f"><label>{{ $t('details.zone') }}</label><span class="muted">{{ areaOf(b.pos) || '—' }}</span></div>
          </div>
          <div class="f"><label>{{ $t('common.group') }}</label>
            <el-select :model-value="b.group || ''" size="small" clearable :placeholder="$t('details.ungrouped')" @change="(v: any) => set({ group: v || null })">
              <el-option v-for="g in ed.model.groups || []" :key="g.id" :value="g.id" :label="g.name" /></el-select></div>
          <div v-if="(ed.model.plant?.layout?.floors || []).length > 1" class="f"><label>{{ $t('details.floor') }}</label>
            <el-select :model-value="b.floor || 'F1'" size="small" @change="(v: any) => set({ floor: v === 'F1' ? null : v })">
              <el-option v-for="f in ed.model.plant.layout.floors" :key="f.id" :value="f.id" :label="$t('details.n0Elevation1M', [f.name, f.z])" /></el-select></div>
        </el-collapse-item>
        <el-collapse-item v-for="(ks, g) in paramGroups" :key="g" :name="'p:' + g" :title="String(g)">
          <div v-for="k in ks" :key="k" class="f" :class="{ wide: ['expr', 'json'].includes(t.params[k]?.t || 'json') }">
            <label :title="t.params[k]?.help || k">{{ t.params[k]?.label || k }}<el-tooltip v-if="t.params[k]?.help" :content="t.params[k].help" placement="left"><el-icon class="hq"><QuestionFilled /></el-icon></el-tooltip></label>
            <!-- Control unit definitions are large; omit JSON here and edit in the control unit editor -->
            <div v-if="b.type === 'cell' && k === 'cell'" class="dt-cell">
              {{ $t('details.n0Components1IO', [(b.params?.cell?.components || []).length, (b.params?.cell?.io || []).length]) }}
              <el-button size="small" @click="openCellEditor">{{ $t('details.editInTheControlUnit') }}</el-button></div>
            <ParamInput v-else :d="t.params[k] || guess(b.params[k])" :value="b.params?.[k] ?? t.params[k]?.default" @set="(v: any) => set({ ['params.' + k]: v })" />
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="ed.expert" name="sig">
          <template #title><span class="sec-t">{{ $t('blockNode.customTags') }} <small class="muted">{{ (b.signals || []).length }}</small></span></template>
          <p class="muted small">{{ ed.cat.signal_help }}</p>
          <div v-for="(s, i) in b.signals || []" :key="i" class="sig">
            <div class="row"><el-input :model-value="s.name" size="small" :placeholder="$t('details.tagNameEGMold')" class="mono" @change="(v: string) => setSig(i, { name: v })" />
              <el-input :model-value="s.unit" size="small" :placeholder="$t('common.unit')" style="width:70px" @change="(v: string) => setSig(i, { unit: v })" />
              <el-button size="small" text type="danger" @click="delSig(i)"><el-icon><Delete /></el-icon></el-button></div>
            <el-input :model-value="s.desc" size="small" :placeholder="$t('common.description')" @change="(v: string) => setSig(i, { desc: v })" />
            <ExprInput :model-value="s.expr" :placeholder="$t('details.formulaEGLagPower')" @change="(v: any) => setSig(i, { expr: v })" />
            <el-checkbox :model-value="!!s.writable" size="small" @change="(v: any) => setSig(i, { writable: v })">{{ $t('details.writableExternalSystemsCanWrite') }}</el-checkbox>
          </div>
          <el-button size="small" @click="addSig"><el-icon><Plus /></el-icon> {{ $t('details.addTag') }}</el-button>
          <div class="sub-t">{{ $t('details.parameterBinding') }} <small class="muted">{{ $t('details.useFormulasToDriveParameters') }}</small></div>
          <div v-for="(x, i) in b.bindings || []" :key="'b' + i" class="sig">
            <div class="row"><el-select :model-value="x.target" size="small" filterable allow-create :placeholder="$t('details.target')" @change="(v: string) => setBind(i, { target: v })">
              <el-option v-for="k in Object.keys(t.params)" :key="k" :value="'param.' + k" :label="$t('details.parameters0', [t.params[k].label])" />
              <el-option v-for="s in b.signals || []" :key="s.name" :value="s.name" :label="$t('details.tags0', [s.name])" /></el-select>
              <el-button size="small" text type="danger" @click="delBind(i)"><el-icon><Delete /></el-icon></el-button></div>
            <ExprInput :model-value="x.expr" @change="(v: any) => setBind(i, { expr: v })" />
          </div>
          <el-button size="small" @click="addBind"><el-icon><Plus /></el-icon> {{ $t('details.addBinding') }}</el-button>
        </el-collapse-item>
        <el-collapse-item name="links">
          <template #title><span class="sec-t">{{ $t('common.connection') }} <small class="muted">{{ $t('details.in0Out1', [linksIn.length, linksOut.length]) }}</small></span></template>
          <div v-for="l in linksIn" :key="l.id" class="lk click" @click="selLink(l.id)">← {{ nameOf(l.from) }}<small class="muted"> {{ l.id }}{{ l.via ? ' · 🚚 ' + l.via : '' }}</small></div>
          <div v-for="l in linksOut" :key="l.id" class="lk click" @click="selLink(l.id)">→ {{ nameOf(l.to) }}<small class="muted"> {{ PORT_CN[l.from_port] || l.from_port }} · {{ l.id }}{{ l.via ? ' · 🚚 ' + l.via : '' }}</small></div>
          <div v-if="!linksIn.length && !linksOut.length" class="muted small">{{ $t('details.noConnectionsInTheGraph') }}</div>
        </el-collapse-item>
      </el-collapse>
    </template>

    <!-- Groups / annotations -->
    <template v-else-if="group">
      <div class="dt-head"><el-icon class="dt-ic" :style="{ background: group.color }"><FolderOpened /></el-icon>
        <div><el-input v-model="groupNameEdit" size="small" class="dt-name" @change="(v: string) => v.trim() && exec([{ op: 'update_group', id: group.id, set: { name: v.trim() } }], $t('details.renameGroup'))" />
          <small class="mono">{{ $t('details.n0Group', [group.id]) }}</small></div></div>
      <div class="dt-sec">
        <div class="f"><label>{{ $t('common.color') }}</label><el-color-picker :model-value="group.color" size="small" @change="(v: any) => exec([{ op: 'update_group', id: group.id, set: { color: v } }], $t('details.changeGroupColor'))" /></div>
        <div class="f"><label>{{ $t('details.collapse') }}</label><el-switch :model-value="!!group.collapsed" size="small" @change="(v: any) => exec([{ op: 'update_group', id: group.id, set: { collapsed: v } }], v ? $t('details.collapseGroup') : $t('common.expandGroup'))" /></div>
        <div class="sub-t">{{ $t('details.members') }}</div>
        <div v-for="m in members" :key="m.id" class="lk click" @click="select([m.id])">{{ m.name }} <small class="muted mono">{{ m.id }}</small></div>
        <el-button size="small" style="margin-top:8px" @click="askAI"><el-icon><ChatDotRound /></el-icon> {{ $t('details.askAiAboutThisGroup') }}</el-button>
        <el-button size="small" type="danger" plain style="margin-top:8px" @click="removeSelected">{{ $t('details.ungroup') }}</el-button>
      </div>
    </template>
    <template v-else-if="note">
      <div class="dt-head"><el-icon class="dt-ic" style="background:#c9b458"><Memo /></el-icon><div><b>{{ $t('common.comment') }}</b><small class="mono">{{ note.id }}</small></div></div>
      <div class="dt-sec"><el-input type="textarea" :model-value="note.text" :rows="6" @change="(v: string) => exec([{ op: 'update_note', id: note.id, set: { text: v } }], $t('details.editComment'))" />
        <el-button size="small" type="danger" plain style="margin-top:8px" @click="removeSelected">{{ $t('details.deleteComment') }}</el-button></div>
    </template>

    <!-- Multiple selection -->
    <template v-else-if="selBlocks.length > 1">
      <div class="dt-head"><el-icon class="dt-ic" style="background:#5b6b80"><Files /></el-icon><div><b>{{ $t('details.blocksSelected0', [selBlocks.length]) }}</b>
        <small>{{ sameType ? $t('details.allAre0ParametersCan', [typeOf(selBlocks[0]).label]) : $t('details.differentTypesOnlyLayoutCan') }}</small></div></div>
      <div class="dt-actions">
        <el-button size="small" type="primary" plain @click="askAI"><el-icon><ChatDotRound /></el-icon> {{ $t('common.askAi') }}</el-button>
        <el-button size="small" @click="groupSel">{{ $t('common.group') }}</el-button>
        <el-button size="small" @click="emit('template')">{{ $t('details.saveTemplate') }}</el-button>
        <el-button size="small" type="danger" plain @click="removeSelected"><el-icon><Delete /></el-icon></el-button>
      </div>
      <div class="chips"><span v-for="x in selBlocks" :key="x.id" class="chip click" @click="select([x.id])">{{ x.name }}</span></div>
      <el-collapse v-if="sameType" v-model="open">
        <el-collapse-item v-for="(ks, g) in paramGroups" :key="g" :name="'p:' + g" :title="String(g)">
          <div v-for="k in ks" :key="k" class="f" :class="{ wide: ['expr', 'json'].includes(t.params[k]?.t) }">
            <label>{{ t.params[k]?.label || k }}</label>
            <ParamInput :d="t.params[k] || guess(selBlocks[0].params[k])" :value="common(k)" :mixed="common(k) === MIXED"
              @set="(v: any) => exec(selBlocks.map((x: any) => ({ op: 'update_block', id: x.id, set: { ['params.' + k]: v } })), $t('details.bulkEdit0', [t.params[k]?.label || k]))" />
          </div>
        </el-collapse-item>
      </el-collapse>
    </template>

    <!-- Factory -->
    <template v-else-if="ed.model">
      <div class="dt-head"><el-icon class="dt-ic" style="background:#d99a16"><OfficeBuilding /></el-icon><div><b>{{ ed.model.plant?.name }}</b><small>{{ $t('details.factoryPropertiesShownWhenNothing') }}</small></div></div>
      <div class="dt-sec">
        <div class="f"><label>{{ $t('details.factoryName') }}</label><el-input :model-value="ed.model.plant?.name" size="small" @change="(v: string) => setPlant({ 'plant.name': v })" /></div>
        <div class="f"><label>{{ $t('details.mainProduct') }}</label><el-input :model-value="ed.model.plant?.product" size="small" @change="(v: string) => setPlant({ 'plant.product': v })" /></div>
        <div class="grid2">
          <div class="f"><label>{{ $t('details.buildingLength') }}</label><el-input-number :model-value="ed.model.plant?.floor?.[0]" size="small" :controls="false" @change="(v: any) => setPlant({ 'plant.floor': [v, ed.model.plant?.floor?.[1] || 50] })" /><span class="unit">m</span></div>
          <div class="f"><label>{{ $t('details.buildingWidth') }}</label><el-input-number :model-value="ed.model.plant?.floor?.[1]" size="small" :controls="false" @change="(v: any) => setPlant({ 'plant.floor': [ed.model.plant?.floor?.[0] || 100, v] })" /><span class="unit">m</span></div>
          <div class="f"><label>{{ $t('details.randomSeed') }}</label><el-input-number :model-value="ed.model.plant?.seed" size="small" :controls="false" @change="(v: any) => setPlant({ 'plant.seed': v })" /></div>
          <div class="f"><label>{{ $t('common.warmUp') }}</label><el-input-number :model-value="ed.model.plant?.warmup_h" size="small" :controls="false" @change="(v: any) => setPlant({ 'plant.warmup_h': v })" /><span class="unit">h</span></div>
        </div>
        <div class="sub-t">{{ $t('details.zone') }} <small class="muted">{{ $t('details.dividedByXRangeShown') }}</small></div>
        <div v-for="(a, i) in ed.model.areas || []" :key="i" class="row area-row">
          <el-input :model-value="a.name" size="small" @change="(v: string) => setArea(i, { name: v })" />
          <el-input-number :model-value="a.x[0]" size="small" :controls="false" @change="(v: any) => setArea(i, { x: [v, a.x[1]] })" />
          <el-input-number :model-value="a.x[1]" size="small" :controls="false" @change="(v: any) => setArea(i, { x: [a.x[0], v] })" />
          <el-button size="small" text type="danger" @click="delArea(i)"><el-icon><Delete /></el-icon></el-button>
        </div>
        <el-button size="small" @click="addArea"><el-icon><Plus /></el-icon> {{ $t('details.addZone') }}</el-button>
        <div class="sub-t">{{ $t('details.overview') }}</div>
        <div class="stats"><span v-for="(n, c) in byCat" :key="c">{{ c }} <b>{{ n }}</b></span><span>{{ $t('common.connections') }} <b>{{ (ed.model.links || []).length }}</b></span></div>
      </div>
    </template>
  </el-form>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import ObjectPanel from './shell/ObjectPanel.vue';
import LayoutProps from './plan/LayoutProps.vue';
import { pv } from './plan/state';
import { computed, ref, watch } from 'vue';
import { canEdit, pct } from '../api';
import { askAssistant } from '../assistant';
import ExprInput from './ExprInput.vue';
import ParamInput from './ParamInput.vue';
import { areaOf, blocksById, duplicateSel, ed, exec, groupSel, PORT_CN, removeSelected, rtById, select, selBlocks, STATE_CN, STATE_COLOR, typeOf } from './store';

const emit = defineEmits<{ (e: 'template'): void }>();
const MIXED = Symbol('mixed') as any;
const open = ref<string[]>(['rt', 'layout', $t('details.pCycleTime'), $t('details.pBehavior'), $t('details.pStaffing'), $t('details.pQuality'), $t('details.pFailure'), $t('details.pOther'), $t('details.pProtocol'), $t('details.pGeometry'), $t('details.pEnergy'), 'sig', 'links']);
const b = computed(() => (ed.sel.length === 1 ? blocksById.value[ed.sel[0]] : null));
const t = computed(() => typeOf(b.value || selBlocks.value[0]));
const rt = computed(() => (b.value ? rtById.value[b.value.id] : null));
const link = computed(() => (ed.selLink ? (ed.model?.links || []).find((l: any) => l.id === ed.selLink) : null));
const group = computed(() => (ed.sel.length === 1 ? (ed.model?.groups || []).find((g: any) => g.id === ed.sel[0]) : null));
// Use a local value for the name input (binding only :model-value makes Element Plus overwrite unfinished input on every render); sync when the model name changes.
const nameEdit = ref(''), groupNameEdit = ref('');
watch(() => b.value?.name, (v) => { nameEdit.value = v || ''; }, { immediate: true });
watch(() => group.value?.name, (v) => { groupNameEdit.value = v || ''; }, { immediate: true });
const note = computed(() => (ed.sel.length === 1 ? (ed.model?.notes || []).find((g: any) => g.id === ed.sel[0]) : null));
const members = computed(() => (group.value ? ed.model.blocks.filter((x: any) => x.group === group.value.id) : []));
const sameType = computed(() => selBlocks.value.length > 1 && selBlocks.value.every((x: any) => x.type === selBlocks.value[0].type));
const nameOf = (id: string) => blocksById.value[id]?.name || id;
const movers = computed(() => (ed.model?.blocks || []).filter((x: any) => x.type === 'transporter' || x.type === 'agv_fleet'));
const productCodes = computed(() => (ed.model?.plan?.products || []).map((p: any) => p.code).filter(Boolean));
const linksIn = computed(() => (b.value ? (ed.model.links || []).filter((l: any) => l.to === b.value.id && (l.kind || 'material') === 'material') : []));
const linksOut = computed(() => (b.value ? (ed.model.links || []).filter((l: any) => l.from === b.value.id && (l.kind || 'material') === 'material') : []));
const byCat = computed(() => {
  const m: Record<string, number> = {};
  for (const x of ed.model?.blocks || []) { const c = typeOf(x).cat || $t('common.other'); m[c] = (m[c] || 0) + 1; }
  return m;
});

const paramGroups = computed(() => {
  const src = b.value || selBlocks.value[0]; if (!src) return {};
  const out: Record<string, string[]> = {};
  // Simple mode (default): list common parameters only; hidden, JSON, and unregistered parameters appear only in "Expert Mode".
  const simple = !ed.expert;
  for (const [k, d] of Object.entries(t.value.params) as any) {
    if (d.hidden || (simple && (d.adv || (d.t === 'json' && k !== 'cell')))) continue;
    (out[d.group || $t('common.other')] ||= []).push(k);
  }
  if (!simple) for (const k of Object.keys(src.params || {})) if (!t.value.params[k] && !['nodes', 'roles'].includes(k)) (out[$t('common.other')] ||= []).push(k);
  return out;
});
function setExpert(v: any) { ed.expert = !!v; try { localStorage.setItem('vf_expert', v ? '1' : ''); } catch { /* */ } }
const guess = (v: any) => ({ t: typeof v === 'number' ? 'num' : typeof v === 'boolean' ? 'bool' : typeof v === 'string' ? 'text' : 'json' });
function common(k: string) {
  const vals = selBlocks.value.map((x: any) => JSON.stringify(x.params?.[k] ?? t.value.params[k]?.default));
  return vals.every((v: string) => v === vals[0]) ? selBlocks.value[0].params?.[k] ?? t.value.params[k]?.default : MIXED;
}

function set(s: any) { exec([{ op: 'update_block', id: b.value.id, set: s }], $t('details.edit0', [b.value.name])); }
function setLink(s: any) { exec([{ op: 'update_link', id: link.value.id, set: s }], $t('details.editConnection0', [link.value.id])); }
function setPlant(s: any) { exec([{ op: 'update_plant', set: s }], $t('details.editFactoryProperties')); }
const sigs = () => JSON.parse(JSON.stringify(b.value.signals || []));
function setSig(i: number, s: any) { const a = sigs(); Object.assign(a[i], s); set({ signals: a }); }
function addSig() { const a = sigs(); a.push({ name: `Custom/Signal${a.length + 1}`, unit: '', desc: '', expr: 'if_(busy, 50 + noise(1), 20)' }); set({ signals: a }); }
function delSig(i: number) { const a = sigs(); a.splice(i, 1); set({ signals: a.length ? a : null }); }
const binds = () => JSON.parse(JSON.stringify(b.value.bindings || []));
function setBind(i: number, s: any) { const a = binds(); Object.assign(a[i], s); set({ bindings: a }); }
function addBind() { const a = binds(); a.push({ target: 'param.time', expr: 'normal(60,3)' }); set({ bindings: a }); }
function delBind(i: number) { const a = binds(); a.splice(i, 1); set({ bindings: a.length ? a : null }); }
const areasCopy = () => JSON.parse(JSON.stringify(ed.model.areas || []));
function setArea(i: number, s: any) { const a = areasCopy(); Object.assign(a[i], s); setPlant({ areas: a }); }
function addArea() { const a = areasCopy(); const x0 = a.length ? a[a.length - 1].x[1] : 0; a.push({ name: $t('details.zone0', [a.length + 1]), x: [x0, x0 + 30] }); setPlant({ areas: a }); }
function delArea(i: number) { const a = areasCopy(); a.splice(i, 1); setPlant({ areas: a }); }
function selLink(id: string) { ed.sel = []; ed.selLink = id; }
function askAI() {
  const what = link.value ? $t('details.connection012', [link.value.id, nameOf(link.value.from), nameOf(link.value.to)]) : group.value ? $t('details.group0', [group.value.name])
    : b.value ? $t('common.n012', [b.value.name, b.value.id]) : $t('details.these0Blocks', [selBlocks.value.length]);
  askAssistant($t('details.n0HowIsItRunning', [what]));
}

function openCellEditor() { window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'cell-editor' } })); }
</script>
