<template>
  <div class="dev">
    <div class="bar">
      <b>{{ $t('devHost.panelDevelopmentPage') }}</b>
      <span v-if="user">{{ $t('common.n012', [user.name, user.role]) }}</span>
      <el-select v-model="pid" size="small" style="width: 200px" filterable allow-create :placeholder="$t('devHost.factoryId')">
        <el-option v-for="p in plants" :key="p.id" :value="p.id" :label="$t('common.n012', [p.name, p.id])" />
      </el-select>
      <el-radio-group v-model="cur" size="small">
        <el-radio-button v-for="p in PANELS" :key="p.id" :value="p.id">{{ p.title }}</el-radio-button>
      </el-radio-group>
      <span class="grow" />
      <el-input v-model="lu" size="small" :placeholder="$t('common.username')" style="width: 100px" />
      <el-input v-model="lp" size="small" :placeholder="$t('common.password')" style="width: 90px" type="password" />
      <el-button size="small" @click="login">{{ $t('common.signIn') }}</el-button>
    </div>
    <div v-if="ed.pick" class="pickbar" data-pickbar>
      <b>{{ ed.pick.prompt }}</b>
      <span>{{ $t('devHost.developmentSimulationClickingEquipme') }}</span>
      <el-button v-for="b in pickBlocks" :key="b.id" size="small" :data-pick="b.id" @click="doPick(b.id)">{{ b.id }} {{ b.name }}</el-button>
      <el-button size="small" text @click="ed.pick = null">{{ $t('common.cancel') }}</el-button>
    </div>
    <div class="stage">
      <div class="frame" v-if="panel && user" :style="frameStyle" :data-panel="panel.id">
        <div class="ftitle">{{ panel.title }} <span>{{ panel.place }}{{ panel.size ? ' ' + panel.size.join('×') : '' }}</span></div>
        <div class="fbody"><component :is="panel.component" :pid="pid" :key="panel.id + pid" /></div>
      </div>
      <div v-else class="hint">{{ $t('devHost.logInFirst') }}</div>
      <div class="canvas-wrap" v-if="panel?.id === 'design-report'">
        <div class="ftitle">{{ $t('devHost.simulatedCanvasScreenshotSource') }}</div>
        <canvas ref="cv" width="900" height="420" />
      </div>
      <div class="state" v-if="user">
        <div class="ftitle">ed.teach / ed.sop / ed.highlight</div>
        <pre>{{ JSON.stringify({ teach: ed.teach, sop: ed.sop, highlight: ed.highlight, focusReq: ed.focusReq }, null, 1) }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../../i18n';
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { get, post, session } from '../../../api';
import { ed } from '../../../editor/store';
import { panels as design } from '../../design/index';
import { panels as debug } from '../../debug/index';
import { panels as teach } from '../index';

const PANELS: any[] = [...teach, ...design, ...debug];
const qs = new URLSearchParams(location.search);
const cur = ref(qs.get('panel') || 'teach-task');
const pid = ref(qs.get('pid') || 'foundry-housing');
const plants = ref<any[]>([]);
const user = ref<any>(null);
const lu = ref(''), lp = ref('');
const cv = ref<HTMLCanvasElement | null>(null);
const panel = computed(() => PANELS.find((p) => p.id === cur.value));
const frameStyle = computed(() => {
  const p = panel.value;
  if (!p) return {};
  if (p.place === 'left') return { width: (qs.get('w') || '380') + 'px', height: 'calc(100vh - 70px)' };
  const [w, h] = p.size || [900, 600];
  return { width: Math.min(w, window.innerWidth - 40) + 'px', height: Math.min(h, window.innerHeight - 70) + 'px' };
});
ed.teach = { handled: true };       // Do not navigate routes on the dev page
(window as any).__vfEd = ed;
const pickBlocks = ref<any[]>([]);
watch(() => ed.pick, async (v) => {
  if (!v) return;
  const p = ed.teach?.pid || pid.value;
  try {
    const m = (await get(`/api/p/${encodeURIComponent(p)}/model`, true)).model;
    pickBlocks.value = (m.blocks || []).filter((b: any) => !v.kinds || v.kinds.includes(b.type));
  } catch { pickBlocks.value = []; }
});
function doPick(id: string) { const f = ed.pick?.onPick; ed.pick = null; f?.(id); }

async function init() {
  try {
    user.value = session.user = await get('/api/me', true);
    plants.value = (await get('/api/overview', true)).plants;
  } catch { user.value = null; }
}
async function login() {
  const r = await post('/api/login', { username: lu.value, password: lp.value });
  session.token = r.token; localStorage.setItem('vf_token', r.token);
  await init();
}
function drawCanvas() {
  const c = cv.value; if (!c) return;
  const g = c.getContext('2d')!;
  g.fillStyle = '#e8eef4'; g.fillRect(0, 0, c.width, c.height);
  const cols = ['#d99a16', '#3b82c4', '#2e9d5b', '#c83a3a', '#7d7aa8'];
  for (let i = 0; i < 14; i++) { g.fillStyle = cols[i % 5]; g.fillRect(30 + (i % 7) * 120, 40 + Math.floor(i / 7) * 180, 90, 110); }
  g.fillStyle = '#33404d'; g.font = '20px sans-serif'; g.fillText($t('devHost.simulated3dViewScreenshotDevelopment'), 30, 400);
}
watch(cur, async () => { await nextTick(); drawCanvas(); history.replaceState(null, '', `?panel=${cur.value}&pid=${pid.value}`); });
onMounted(async () => { await init(); await nextTick(); drawCanvas(); });
</script>

<style>
html, body { margin: 0; height: 100%; font-family: var(--hm-font); }
.dev { min-height: 100vh; background: var(--hm-canvas); }
.bar { display: flex; gap: 8px; align-items: center; padding: 6px 10px; background: var(--el-bg-color); border-bottom: 1px solid var(--el-border-color); flex-wrap: wrap; }
.bar .grow { flex: 1; }
.stage { display: flex; gap: 14px; padding: 12px; align-items: flex-start; }
.frame { background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e2); display: flex; flex-direction: column; overflow: hidden; }
.ftitle { font-size: 12px; padding: 6px 10px; border-bottom: 1px solid var(--el-border-color-lighter); color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
.ftitle span { float: right; }
.fbody { flex: 1; min-height: 0; overflow: hidden; }
.canvas-wrap, .state { background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 8px; overflow: hidden; }
.state pre { margin: 0; padding: 8px; font-size: 11px; max-width: 360px; max-height: 60vh; overflow: auto; }
.hint { padding: 40px; color: var(--hm-text-3); }
.pickbar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; padding: 6px 12px; background: var(--el-color-warning-light-9); border-bottom: 1px solid var(--el-color-warning-light-5); }
</style>
