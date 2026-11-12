<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('mesNav.schedulingDispatch') }}</h2><span class="sub">{{ $t('gantt.forwardFiniteCapacitySchedulingWork') }}</span>
      <span class="grow" /><el-button type="primary" :loading="busy" @click="reschedule">{{ $t('gantt.reschedule') }}</el-button></div>
    <el-alert v-if="late.length" type="warning" :closable="false" show-icon :title="$t('gantt.expectedLate0', [late.join($t('common.k360'))])" style="margin-bottom:12px" />
    <div class="card gantt" v-if="d">
      <div class="axis"><div class="lab">{{ $t('gantt.workOrderOperation') }}</div><div class="track">
        <span v-for="t in ticks" :key="t.x" class="tick" :style="{ left: t.x + '%' }">{{ t.label }}</span>
        <span class="now" :style="{ left: nowX + '%' }">{{ $t('common.current') }}</span></div></div>
      <template v-for="o in d.orders" :key="o.id">
        <div class="row wo"><div class="lab"><b class="click" @click="router.push('/mes/e/work_order?id=' + o.id)">{{ o.code }}</b>
          <span class="tag-st" :class="'st-' + o.status">{{ ST[o.status] }}</span><span class="muted small"> {{ o.customer }} {{ o.qty_done || 0 }}/{{ o.qty }}</span></div>
          <div class="track"><span v-if="o.due" class="due" :style="{ left: x(o.due) + '%' }" :title="$t('gantt.due') + o.due">{{ $t('gantt.due2') }}</span></div></div>
        <div v-for="op in ops(o.id)" :key="op.id" class="row"><div class="lab op">{{ op.seq }} {{ op.process__label?.split(' ').slice(1).join(' ') }} <span class="muted small">{{ op.station_group }}</span></div>
          <div class="track"><div v-if="op.plan_start" class="bar" :class="'b-' + op.status" :style="bar(op)" :title="$t('gantt.n01Completed23', [op.plan_start, op.plan_end, op.qty_good, op.qty_plan, op.qty_ng])">
            <div class="fill" :style="{ width: Math.min(100, (op.qty_good || 0) / (op.qty_plan || 1) * 100) + '%' }" /></div>
            <span v-if="op.plan_start" class="blab" :style="{ left: (x(op.plan_end) + 0.4) + '%' }">{{ op.qty_good || 0 }}/{{ op.qty_plan }}</span></div></div>
      </template>
      <p v-if="!d.orders.length" class="muted">{{ $t('gantt.noReleasedWorkOrdersCreate') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, post } from '../api';

const router = useRouter();
const d = ref<any>(null), busy = ref(false), late = ref<string[]>([]);
const ST: Record<string, string> = { released: $t('gantt.released'), in_progress: $t('gantt.inProduction'), completed: $t('gantt.completed') };
const T = (s: string) => new Date(s.replace(' ', 'T')).getTime();
const range = computed(() => {
  const ts: number[] = [T(d.value.now)];
  for (const o of d.value.ops) { if (o.plan_start) ts.push(T(o.plan_start)); if (o.plan_end) ts.push(T(o.plan_end)); }
  for (const o of d.value.orders) if (o.due) ts.push(T(o.due));
  const a = Math.min(...ts), b = Math.max(...ts);
  return [a - (b - a) * 0.02, b + (b - a) * 0.04 || a + 3600e3];
});
const x = (s: string) => ((T(s) - range.value[0]) / (range.value[1] - range.value[0])) * 100;
const nowX = computed(() => x(d.value.now));
const ticks = computed(() => {
  const [a, b] = range.value, out: any[] = [], span = b - a, step = span > 5 * 864e5 ? 864e5 : span > 2 * 864e5 ? 12 * 3600e3 : span > 864e5 ? 6 * 3600e3 : 3 * 3600e3;
  for (let t = Math.ceil(a / step) * step; t < b; t += step) { const dt = new Date(t); out.push({ x: ((t - a) / span) * 100, label: `${dt.getMonth() + 1}/${dt.getDate()} ${String(dt.getHours()).padStart(2, '0')}:00` }); }
  return out;
});
const ops = (id: number) => d.value.ops.filter((o: any) => o.work_order === id);
const bar = (op: any) => { const l = x(op.plan_start), r = x(op.plan_end); return { left: l + '%', width: Math.max(0.6, r - l) + '%' }; };
async function load() { d.value = await get('/api/production/gantt'); }
async function reschedule() { busy.value = true; try { const r = await post('/api/production/schedule'); late.value = r.late; ElMessage.success($t('gantt.scheduleUpdated')); await load(); } finally { busy.value = false; } }
onMounted(load);
</script>

<style scoped>
.gantt { overflow-x: auto; } .row, .axis { display: flex; align-items: center; min-width: 900px; } .row { height: 28px; border-bottom: 1px solid var(--hm-border); }
.row.wo { background: var(--hm-surface-2); height: 32px; } .lab { width: 280px; flex: none; font-size: var(--hm-fs-sm); padding-right: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--hm-text); }
.lab.op { padding-left: 18px; color: var(--hm-text-2); } .track { position: relative; flex: 1; height: 100%; }
.axis { height: 26px; border-bottom: 1px solid var(--hm-border-strong); font-size: var(--hm-fs-2xs); color: var(--hm-text-3); } .tick { position: absolute; top: 6px; transform: translateX(-50%); white-space: nowrap; font-family: var(--hm-font-num); }
.now { position: absolute; top: 3px; color: #fff; background: var(--hm-primary); border-radius: var(--hm-r-pill); padding: 0 6px; line-height: 18px; font-weight: 600; transform: translateX(-50%); }
.bar { position: absolute; top: 6px; height: 16px; border-radius: 3px; background: var(--hm-primary-soft-2, #d3e3fb); overflow: hidden; font-size: 11px; line-height: 16px; color: var(--hm-text-2); }
.blab { position: absolute; top: 6px; font-size: 11px; color: var(--hm-text-2); white-space: nowrap; font-family: var(--hm-font-num); } .fill { position: absolute; inset: 0 auto 0 0; background: var(--hm-primary); opacity: .8; }
.b-done .fill { background: var(--hm-run); } .b-running { box-shadow: 0 0 0 1px var(--hm-primary); }
.due { position: absolute; top: 8px; color: var(--hm-fault-ink); font-size: 11px; white-space: nowrap; transform: translateX(-4px); }
</style>
