// Select the PLC to program (since 4.3, PLCs are separate plc blocks in the factory): prefer the PLC block selected in the Workbench,
// resolve selected PLC-controlled equipment (control unit) or HMI blocks to their PLC; otherwise use the first PLC, or "Practice PLC" if none exist.
import { $t } from '../i18n';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { ed } from '../editor/store';
import { plcApi } from './plcApi';

const lastPick: Record<string, string> = {};

export function useCells(pid: () => string, fixed?: () => string | undefined) {
  const cells = ref<any[]>([]);
  const hmis = ref<any[]>([]);
  const sandbox = ref<any>(null);
  const loaded = ref(false);
  const bid = ref<string>(fixed?.() || lastPick[pid()] || '');
  let timer: any = null;
  /** Any object ID → PLC ID to program (PLC block itself / PLC bound to an HMI block / PLC controlling this equipment). */
  function resolve(id?: string): string {
    if (!id) return '';
    if (id === '_sandbox' || cells.value.some((c) => c.id === id)) return id;
    const h = hmis.value.find((x) => x.id === id);
    if (h?.plc && cells.value.some((c) => c.id === h.plc)) return h.plc;
    const c = cells.value.find((x) => (x.devices || []).includes(id));
    return c ? c.id : '';
  }
  async function refresh() {
    try {
      const r = await plcApi.cells(pid());
      const had = cells.value.length;
      cells.value = r.plcs || r.cells || [];
      hmis.value = r.hmis || [];
      sandbox.value = r.sandbox;
      const first = !loaded.value;
      loaded.value = true;
      // New PLC is available: switch to it automatically from the practice PLC
      if (!fixed?.() && !first && !had && cells.value.length && bid.value === '_sandbox') bid.value = cells.value[0].id;
      if (bid.value && bid.value !== '_sandbox' && !cells.value.some((c) => c.id === bid.value)) bid.value = resolve(bid.value);
      if (!bid.value) bid.value = cells.value[0]?.id || '_sandbox';
    } catch { /* Factory unavailable */ }
  }
  refresh();
  timer = setInterval(refresh, 5000);
  onBeforeUnmount(() => clearInterval(timer));
  // Follow the Workbench selection
  watch(() => (ed.sel || []).slice(), (sel: string[]) => {
    if (fixed?.()) return;
    for (const id of sel) { const r = resolve(id); if (r && r !== '_sandbox') { bid.value = r; return; } }
  });
  watch(bid, (v) => { if (v) lastPick[pid()] = v; });
  const label = (c: any) => {
    const devs = (c.devices || []).map((d: string) => c.device_names?.[d] || d);
    return `${c.id} ${c.name}` + (devs.length ? $t('cells.controls01', [devs.slice(0, 3).join($t('common.k360')), devs.length > 3 ? $t('cells.andOthers') : '']) : '');
  };
  const options = computed(() => [...cells.value.map((c) => ({ id: c.id, label: label(c) })), { id: '_sandbox', label: $t('cells.practicePlcNoEquipmentConnected') }]);
  /** Factory has no PLCs (only valid after the list loads). */
  const noCells = computed(() => loaded.value && !cells.value.length);
  const running = computed(() => [...cells.value.map((c) => c.id), ...cells.value.flatMap((c) => c.devices || [])]);
  /** Screen specified by fixed when it is an HMI block. */
  const hmiScreen = computed(() => hmis.value.find((h) => h.id === fixed?.())?.screen || '');
  return { cells, hmis, sandbox, bid, options, refresh, loaded, noCells, running, resolve, hmiScreen };
}
