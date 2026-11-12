<template>
  <!-- Cross reference: rungs/lines where each variable is written, read, or called; flag duplicate coils and unused I/O -->
  <div class="xr">
    <div class="xr-bar">
      <b>{{ $t('plcWorkbench.crossReference') }}</b>
      <span class="muted">{{ $t('xrefTable.clickALocationToJump') }}<span class="lg w">{{ $t('debugConsole.write') }}</span>{{ $t('xrefTable.coilAssignment') }} <span class="lg s">{{ $t('xrefTable.set') }}</span>{{ $t('ladderEditor.set') }} <span class="lg rs">{{ $t('xrefTable.reset') }}</span>{{ $t('common.reset') }} <span class="lg r">{{ $t('xrefTable.read') }}</span>{{ $t('xrefTable.contactExpression') }} <span class="lg cc">{{ $t('xrefTable.call') }}</span>{{ $t('xrefTable.functionBlockCall') }}</span>
      <span class="grow" />
      <el-checkbox v-model="onlyIssues" size="small">{{ $t('xrefTable.showOnlyProblems') }}</el-checkbox>
      <el-input v-model="q" size="small" clearable :placeholder="$t('xrefTable.variableName')" style="width: 150px" data-xref-filter />
      <button class="plc-btn" :title="$t('xrefTable.refreshAfterRecompiling')" @click="refresh"><el-icon><Refresh /></el-icon></button>
    </div>
    <div v-if="!S.compile" class="muted pad">{{ $t('xrefTable.compiling') }}</div>
    <div v-else class="xr-scroll">
      <table class="tbl">
        <thead><tr><th>{{ $t('common.variable') }}</th><th>{{ $t('common.type') }}</th><th>{{ $t('common.address') }}</th><th>{{ $t('debugConsole.write') }}</th><th>{{ $t('xrefTable.read') }}</th><th>{{ $t('common.hint') }}</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.name" :class="{ bad: r.issue, hl: focus && r.name.toUpperCase() === focus.toUpperCase() }" :data-xref="r.name">
            <td class="mono nm">{{ r.name }}<small v-if="r.dir" class="dir" :class="r.dir">{{ r.dir === 'in' ? $t('common.in') : $t('common.out') }}</small></td>
            <td class="mono muted">{{ r.type }}</td>
            <td class="mono muted">{{ r.addr || '' }}</td>
            <td><span v-for="(x, i) in r.w" :key="'w' + i" class="loc" :class="kcls(x.k)" :title="KN[x.k]" @click="emit('goto', x)">{{ KS[x.k] }} {{ where(x) }}</span></td>
            <td><span v-for="(x, i) in r.r" :key="'r' + i" class="loc" :class="kcls(x.k)" :title="KN[x.k] + (x.f ? $t('common.k459') + x.f + $t('common.k460') : '')" @click="emit('goto', x)">{{ KS[x.k] }} {{ where(x) }}<template v-if="x.f">.{{ x.f }}</template></span></td>
            <td class="issue">{{ r.issue }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="6" class="muted c pad">{{ $t('xrefTable.noMatchingVariables') }}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, ref, watch } from 'vue';
import type { Sess } from './session';

const props = defineProps<{ sess: Sess; focus?: string }>();
const emit = defineEmits<{ (e: 'goto', x: any): void }>();
const S = props.sess.s;
const q = ref(props.focus || '');
const onlyIssues = ref(false);
watch(() => props.focus, (v) => { if (v) q.value = v; });
const KS: Record<string, string> = { W: $t('debugConsole.write'), S: $t('xrefTable.set'), RS: $t('xrefTable.reset'), R: $t('xrefTable.read'), C: $t('xrefTable.call') };
const KN: Record<string, string> = { W: $t('xrefTable.writeCoilAssignmentOutput'), S: $t('common.setCoil'), RS: $t('common.resetCoil'), R: $t('xrefTable.readContactExpression'), C: $t('xrefTable.functionBlockCall') };
const kcls = (k: string) => ({ W: 'w', S: 's', RS: 'rs', R: 'r', C: 'cc' } as any)[k] || '';
const where = (x: any) => (x.rung !== undefined && x.rung !== null ? $t('common.rung0', [x.rung + 1]) : x.line ? $t('common.row0', [x.line]) : '');
const rows = computed(() => {
  const xref = S.compile?.xref || {};
  const syms = new Map((S.compile?.symbols || []).map((s: any) => [s.name.toUpperCase(), s]));
  const names = new Set<string>(Object.keys(xref));
  for (const e of S.io || []) names.add(e.name);
  for (const v of S.program?.vars || []) if (v.name) names.add(v.name);
  const lang = S.program?.lang;
  const out: any[] = [];
  for (const n of names) {
    const refs = xref[n] || Object.entries(xref).find(([k]) => k.toUpperCase() === n.toUpperCase())?.[1] || [];
    const s: any = syms.get(n.toUpperCase()) || {};
    const io = (S.io || []).find((e: any) => e.name.toUpperCase() === n.toUpperCase());
    const w = refs.filter((x: any) => ['W', 'S', 'RS'].includes(x.k));
    const r = refs.filter((x: any) => ['R', 'C'].includes(x.k));
    let issue = '';
    const coilRungs = new Set(w.filter((x: any) => x.k === 'W' && x.rung !== undefined && !x.f).map((x: any) => x.rung));
    if (lang === 'LD' && coilRungs.size > 1) issue = $t('xrefTable.duplicateCoils0RungsWrite', [coilRungs.size]);
    else if (io?.dir === 'out' && !w.length) issue = $t('xrefTable.thisOutputIsNeverWritten');
    else if (io?.dir === 'in' && !r.length) issue = $t('xrefTable.thisInputIsUnused');
    else if (!io && refs.length && !r.length && !s.type?.match?.(/^(TON|TOF|TP|CT|R_TRIG|F_TRIG|SR|RS)/)) issue = $t('xrefTable.writtenButNeverRead');
    else if (!io && !refs.length) issue = $t('xrefTable.declaredButUnused');
    out.push({ name: s.name || io?.name || n, type: s.type || io?.type || '', addr: s.addr || io?.addr, dir: io?.dir, w, r, issue });
  }
  const qq = q.value.trim().toUpperCase();
  return out.filter((x) => (!qq || x.name.toUpperCase().includes(qq)) && (!onlyIssues.value || x.issue))
    .sort((a, b) => (a.dir === 'in' ? 0 : a.dir === 'out' ? 1 : 2) - (b.dir === 'in' ? 0 : b.dir === 'out' ? 1 : 2) || String(a.addr || '~').localeCompare(String(b.addr || '~')) || a.name.localeCompare(b.name));
});
async function refresh() { await props.sess.compileQuiet(); }
onMounted(() => { if (!S.compile) refresh(); });
</script>

<style scoped>
.xr { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-card); color: var(--ld-tx); }
.xr-bar { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--ld-ln); font-size: 12px; flex-wrap: wrap; }
.xr-scroll { flex: 1; overflow: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th { position: sticky; top: 0; z-index: 1; background: var(--ld-bar); color: var(--ld-mu); font-weight: 500; text-align: left; padding: 5px 6px; border-bottom: 1px solid var(--ld-ln); }
.tbl td { padding: 3px 6px; border-bottom: 1px solid var(--ld-ln); vertical-align: top; }
.tbl tr.bad td { background: var(--ld-bad-bg); }
.tbl tr.hl td { box-shadow: inset 0 0 0 9999px var(--ld-selbg); }
.nm { font-weight: 600; white-space: nowrap; }
.dir { margin-left: 5px; font-size: 10.5px; padding: 0 3px; border-radius: 3px; font-family: inherit; }
.dir.in { background: var(--ld-in-bg); color: var(--ld-in); } .dir.out { background: var(--ld-pow-bg); color: var(--ld-pow); }
.loc { display: inline-block; margin: 1px 4px 1px 0; padding: 0 6px; border-radius: 10px; font-size: 11.5px; cursor: pointer; border: 1px solid var(--ld-ln); white-space: nowrap; }
.loc:hover { border-color: var(--ld-sel); }
.lg { display: inline-block; padding: 0 4px; border-radius: 3px; font-size: 11px; margin: 0 2px 0 6px; }
.w { background: var(--ld-pow-bg); } .s { background: var(--ld-info-bg); } .rs { background: var(--ld-halt-bg); } .r { background: var(--ld-bar); } .cc { background: var(--ld-selbg); }
.issue { color: var(--ld-bad); font-size: 12px; }
.muted { color: var(--ld-mu); } .pad { padding: 14px; } .c { text-align: center; } .grow { flex: 1; }
</style>
