<template>
  <el-tooltip v-if="button" :content="$t('deliveryExport.standardDeliveryPackageEquipmentList')">
    <el-button :size="size" data-k="delivery-btn" @click="open"><el-icon><Files /></el-icon>{{ $t('deliveryExport.deliveryPackage') }}</el-button></el-tooltip>
  <el-dialog v-model="show" :title="$t('deliveryExport.standardDeliveryPackage')" width="600px" append-to-body class="delivery-dlg">
    <p class="small muted" style="margin-top:0">{{ $t('deliveryExport.handThisFactoryOverTo') }}</p>
    <el-form label-width="104px" size="small">
      <el-form-item :label="$t('deliveryExport.tagList')">
        <el-radio-group v-model="protocols"><el-radio value="primary">{{ $t('deliveryExport.oneRowPerTagUsing') }}</el-radio><el-radio value="all">{{ $t('deliveryExport.oneRowPerProtocol') }}</el-radio></el-radio-group>
      </el-form-item>
      <el-form-item :label="$t('deliveryExport.n3dModels')">
        <el-radio-group v-model="models"><el-radio value="ui">{{ $t('deliveryExport.modelsShownInTheUi') }}</el-radio><el-radio value="simple">{{ $t('deliveryExport.simplifiedModelsServerGenerated') }}</el-radio></el-radio-group>
      </el-form-item>
      <el-form-item :label="$t('deliveryExport.rawSiteMode')">
        <div class="rawrow"><el-switch v-model="raw" :disabled="!canEdit() || busyRaw" data-k="raw-site" @change="toggleRaw" />
          <span class="small muted">{{ $t('deliveryExport.whenEnabledOpcUaMqtt') }}</span></div>
      </el-form-item>
    </el-form>
    <div v-if="info" class="small muted info">{{ $t('deliveryExport.equipment0Tags12', [info.devices, info.points, Object.entries(info.by_protocol || {}).map(([k, v]) => `${PN[k] || k} ${v}`).join($t('common.k360')), (info.action_devices || []).join($t('common.k360')) || $t('common.none')]) }}</div>
    <div v-if="step" class="small dl-step">{{ step }}</div>
    <template #footer>
      <el-button @click="one('points.xlsx')">{{ $t('deliveryExport.tagListOnly') }}</el-button>
      <el-button @click="one('layout.dxf')">{{ $t('deliveryExport.floorPlanOnly') }}</el-button>
      <el-button type="primary" :loading="busy" data-k="delivery-go" @click="go">{{ $t('deliveryExport.downloadDeliveryPackage') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { ref } from 'vue';
import { canEdit, desk, download, get, P, put, session } from '../api';

const props = withDefaults(defineProps<{ pid: string; size?: '' | 'small' | 'default' | 'large'; button?: boolean }>(), { size: '', button: true });
const PN: Record<string, string> = { opcua: 'OPC UA', mqtt: 'MQTT', modbus: 'Modbus' };
const show = ref(false), busy = ref(false), busyRaw = ref(false), raw = ref(false), info = ref<any>(null), step = ref('');
const protocols = ref<'primary' | 'all'>('primary'), models = ref<'ui' | 'simple'>('ui');
const api = () => P(props.pid);

async function open() {
  show.value = true; step.value = '';
  try { info.value = await get(api() + '/delivery/info', true); raw.value = !!info.value?.raw_site; } catch { info.value = null; }
}
defineExpose({ open });

function one(name: string) { download(`${api()}/delivery/${name}${protocols.value === 'all' ? '?protocols=all' : ''}`); }

function save(blob: Blob, name: string) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
}

async function go() {
  if (models.value === 'simple') { download(`${api()}/delivery.zip${protocols.value === 'all' ? '?protocols=all' : ''}`); return; }
  busy.value = true;
  try {
    step.value = $t('deliveryExport.exportingThe3dModelsShown');
    const meta = await get(api() + '/meta');
    const { buildDeliveryModels } = await import('../delivery3d');
    const m = await buildDeliveryModels(meta);
    step.value = $t('deliveryExport.packaging');
    const r = await fetch(api() + '/delivery.zip', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.token, ...(desk.on ? { 'X-VF-Plant': props.pid } : {}) },
      body: JSON.stringify({ models: m.models, scene: m.scene, protocols: protocols.value }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || `HTTP ${r.status}`);
    save(await r.blob(), `${props.pid}-delivery.zip`);
    step.value = m.failed.length ? $t('deliveryExport.downloadedSimplifiedModelsUsedFor', [m.failed.join($t('common.k360'))]) : $t('deliveryExport.downloaded');
  } catch (e: any) {
    step.value = '';
    ElMessage.warning($t('deliveryExport.browserExportOf3dModels') + (e?.message || e));
    download(`${api()}/delivery.zip${protocols.value === 'all' ? '?protocols=all' : ''}`);
  } finally { busy.value = false; }
}

async function toggleRaw(v: string | number | boolean) {
  const on = !!v;
  try {
    await ElMessageBox.confirm(on ? $t('deliveryExport.theProtocolLayerOpcUa')
      : $t('deliveryExport.restoreStandardProtocolNamingVfactor'), on ? $t('deliveryExport.enableRawSiteMode') : $t('deliveryExport.disableRawSiteMode'), { type: 'warning' });
  } catch { raw.value = !on; return; }
  busyRaw.value = true;
  try {
    const r = await put(api() + '/delivery/raw_site', { on });
    raw.value = !!r.on;
    ElMessage.success(r.on ? $t('deliveryExport.rawSiteModeEnabled') : $t('deliveryExport.standardNamingRestored'));
    info.value = await get(api() + '/delivery/info', true);
  } catch { raw.value = !on; } finally { busyRaw.value = false; }
}
</script>

<style scoped>
.rawrow { display: flex; gap: 10px; align-items: flex-start; line-height: 1.5; }
.info { margin-top: 6px; } .dl-step { margin-top: 8px; color: var(--el-color-primary); }
</style>
