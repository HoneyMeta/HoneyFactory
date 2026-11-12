<template>
  <div class="vt">
    <div class="vt-bar">
      <b>{{ $t('varTable.variableTable') }}</b><span class="muted">{{ $t('varTable.internalProgramVariablesInternalRela') }}</span>
      <span class="grow" />
      <el-input v-model="q" size="small" clearable :placeholder="$t('varTable.searchNameComment')" style="width: 160px" />
      <el-button size="small" type="primary" plain :disabled="ro" @click="add()"><el-icon><Plus /></el-icon>{{ $t('varTable.newVariable') }}</el-button>
    </div>
    <div class="vt-scroll">
      <table class="tbl">
        <thead><tr><th style="width: 26px" /><th>{{ $t('common.name') }}</th><th style="width: 128px">{{ $t('common.type') }}</th><th style="width: 92px">{{ $t('common.address') }}</th><th style="width: 90px">{{ $t('varTable.initialValue') }}</th>
          <th style="width: 50px">{{ $t('varTable.retain') }}</th><th>{{ $t('common.comment') }}</th><th style="width: 120px">{{ $t('varTable.onlineValue') }}</th><th style="width: 30px" /></tr></thead>
        <tbody>
          <tr v-for="(v, i) in shownVars" :key="'v' + i" :class="{ err: errOf(v.name) }">
            <td class="muted idx">{{ i + 1 }}</td>
            <td><input :disabled="ro" class="ci mono" :value="v.name" :placeholder="$t('common.name')" @change="setV(v, 'name', ($event.target as any).value)" /></td>
            <td>
              <input :disabled="ro" class="ci mono" :value="v.type" list="plc-types" placeholder="BOOL" @change="setV(v, 'type', ($event.target as any).value.toUpperCase())" />
            </td>
            <td><input :disabled="ro" class="ci mono" :value="v.addr || ''" :placeholder="$t('varTable.none')" @change="setV(v, 'addr', ($event.target as any).value)" /></td>
            <td><input :disabled="ro" class="ci mono" :value="v.init ?? ''" placeholder="—" @change="setV(v, 'init', ($event.target as any).value)" /></td>
            <td class="c"><input type="checkbox" :disabled="ro" :checked="!!v.retain" @change="setV(v, 'retain', ($event.target as any).checked)" /></td>
            <td><input :disabled="ro" class="ci" :value="v.comment || ''" :placeholder="$t('common.description')" @change="setV(v, 'comment', ($event.target as any).value)" /></td>
            <td class="mono live" :class="cls(v.name)">
              <span v-if="isFb(v.type)" class="fbv">{{ fbLive(v.name) }}</span>
              <template v-else>{{ live(v.name) }}<em v-if="forced(v.name)" class="fz">F</em></template>
            </td>
            <td><button v-if="!ro" class="x" :title="$t('common.delete')" @click="remove(v)">×</button></td>
          </tr>
          <tr v-if="!shownVars.length"><td colspan="9" class="muted c pad">{{ $t('varTable.noVariablesYetUndeclaredNames') }}</td></tr>
          <tr class="sec"><td colspan="9">{{ $t('varTable.iOSensorsButtonsActuators') }}</td></tr>
          <tr v-for="e in shownIo" :key="'io' + e.name" class="ro">
            <td class="c"><span class="dir" :class="e.dir">{{ e.dir === 'in' ? $t('common.in') : $t('common.out') }}</span></td>
            <td class="mono">{{ e.name }}</td><td class="mono">{{ e.type || 'BOOL' }}</td><td class="mono">{{ e.addr }}</td><td /><td />
            <td class="muted"><span v-if="e.contact" class="ctag" :class="e.contact" :title="e.contact === 'NC' ? $t('varTable.nc1WhenNotPressed') : $t('varTable.no0WhenNotPressed')">{{ $t('varTable.n0Idle1', [e.contact === 'NC' ? $t('common.nc') : $t('common.no3'), e.idle]) }}</span> {{ e.comment }}</td>
            <td class="mono live" :class="cls(e.name)">{{ live(e.name) }}<em v-if="forced(e.name)" class="fz">F</em></td><td />
          </tr>
          <template v-if="auto.length">
            <tr class="sec"><td colspan="9">{{ $t('varTable.automaticallyDeclaredFunctionBlockIn') }}</td></tr>
            <tr v-for="s in auto" :key="'a' + s.name" class="ro">
              <td /><td class="mono">{{ s.name }}</td><td class="mono">{{ s.type }}</td><td /><td /><td /><td class="muted">{{ s.comment }}</td>
              <td class="mono live"><span class="fbv">{{ fbLive(s.name) }}</span></td>
              <td><button v-if="!ro" class="x add" :title="$t('varTable.addToVariableTable')" @click="adopt(s)">{{ $t('varTable.k6399') }}</button></td>
            </tr>
          </template>
        </tbody>
      </table>
      <datalist id="plc-types"><option v-for="t in TYPES" :key="t" :value="t" /></datalist>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { canEdit } from '../api';
import { FB_TYPES, fmtVal, TYPES } from './plcApi';
import type { Sess } from './session';

const props = defineProps<{ sess: Sess }>();
const sess = props.sess;
const S = sess.s;
const q = ref('');
const ro = computed(() => !canEdit());
const match = (x: any) => !q.value || `${x.name} ${x.comment || ''}`.toLowerCase().includes(q.value.toLowerCase());
const shownVars = computed(() => (S.program?.vars || []).filter(match));
const shownIo = computed(() => (S.io || []).filter(match));
const auto = computed(() => (S.compile?.symbols || []).filter((s: any) => s.section === 'VAR' && !s.line && FB_TYPES[s.type] &&
  !(S.program?.vars || []).some((v: any) => v.name?.toUpperCase() === s.name.toUpperCase())));
const isFb = (t: string) => !!FB_TYPES[(t || '').toUpperCase()];
const onl = () => (S.online && S.monitor ? S.online : null);
function key(name: string) { const vars = onl()?.vars || {}; return Object.keys(vars).find((k) => k.toUpperCase() === String(name).toUpperCase()); }
function live(name: string) { const k = key(name); if (!k) return ''; return fmtVal(onl().vars[k], onl().types?.[k]); }
function cls(name: string) { const k = key(name); const v = k ? onl().vars[k] : undefined; return v === true ? 'on' : v === false ? 'off' : ''; }
function forced(name: string) { return Object.keys(onl()?.forced || {}).some((k) => k.toUpperCase() === String(name).toUpperCase()); }
function fbLive(name: string) {
  const k = key(name); const v = k ? onl().vars[k] : null;
  if (!v || typeof v !== 'object') return '';
  return Object.entries(v).map(([f, x]) => `${f}=${fmtVal(x, f === 'ET' || f === 'PT' ? 'TIME' : '')}`).join('  ');
}
function errOf(name: string) { return (S.errors || []).some((e: any) => e.var === name); }
function add() {
  sess.change((p) => {
    let i = p.vars.length + 1;
    while (p.vars.some((v: any) => v.name === 'M' + i)) i++;
    p.vars.push({ name: 'M' + i, type: 'BOOL', comment: '' });
  });
}
function setV(v: any, k: string, val: any) {
  const i = S.program.vars.indexOf(v);
  sess.change((p) => {
    const x = p.vars[i];
    if (val === '' || val === null) delete x[k]; else x[k] = val;
    if (k === 'type' && x.addr && FB_TYPES[val]) delete x.addr;
  });
}
function remove(v: any) { const i = S.program.vars.indexOf(v); sess.change((p) => p.vars.splice(i, 1)); }
function adopt(s: any) { sess.change((p) => p.vars.push({ name: s.name, type: s.type, comment: FB_TYPES[s.type]?.cn || '' })); }
</script>

<style scoped>
.vt { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-card); color: var(--ld-tx); }
.vt-bar { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--ld-ln); font-size: 12px; }
.vt-scroll { flex: 1; overflow: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th { position: sticky; top: 0; z-index: 1; background: var(--ld-bar); color: var(--ld-mu); font-weight: 500; text-align: left; padding: 5px 6px; border-bottom: 1px solid var(--ld-ln); }
.tbl td { padding: 1px 6px; border-bottom: 1px solid var(--ld-ln); height: 27px; }
.tbl tr.err td { background: var(--ld-bad-bg); }
.tbl tr.sec td { background: var(--ld-bar); color: var(--ld-mu); font-size: 11.5px; padding: 4px 8px; height: auto; }
.tbl tr.ro td { color: var(--ld-tx); }
.ci { width: 100%; height: 23px; border: 1px solid transparent; border-radius: 3px; background: transparent; color: var(--ld-tx); padding: 0 5px; font-size: 12.5px; outline: none; }
.ci:hover { border-color: var(--ld-ln); } .ci:focus { border-color: var(--ld-sel); background: var(--ld-bg); }
.mono { font-family: Consolas, monospace; }
.muted { color: var(--ld-mu); } .c { text-align: center; } .pad { padding: 14px !important; } .idx { font-size: 11px; text-align: right; }
.live { white-space: nowrap; } .live.on { color: var(--ld-pow); font-weight: 600; } .live.off { color: var(--ld-mu); }
.fbv { font-size: 11px; color: var(--ld-live); }
.fz { font-style: normal; margin-left: 4px; padding: 0 3px; border-radius: 2px; background: var(--ld-force); color: #fff; font-size: 10px; }
.dir { display: inline-block; width: 18px; height: 18px; line-height: 18px; border-radius: 3px; font-size: 11px; text-align: center; }
.dir.in { background: var(--ld-in-bg); color: var(--ld-in); } .dir.out { background: var(--ld-pow-bg); color: var(--ld-pow); }
.x { border: 0; background: none; color: var(--ld-mu); font-size: 16px; cursor: pointer; } .x:hover { color: var(--ld-bad); } .x.add:hover { color: var(--ld-pow); }
.ctag { font-size: 11px; padding: 0 5px; border-radius: 3px; background: var(--ld-bar); color: var(--ld-mu); margin-right: 4px; }
.ctag.NC { background: var(--ld-halt-bg); color: var(--ld-tx); font-weight: 600; }
.grow { flex: 1; }
</style>
