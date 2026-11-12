<template>
  <el-dialog :model-value="ui.whatsNew" width="min(720px, 94vw)" class="wn-dlg" append-to-body align-center :show-close="true" @close="closeWhatsNew" @update:model-value="(v: boolean) => !v && closeWhatsNew()">
    <template #header>
      <div class="wn-h"><b>{{ ui.whatsNewAuto ? $t('whatsNew.updatedWhatSNew') : $t('common.whatSNew') }}</b><small v-if="ui.version" class="muted">{{ $t('whatsNew.currentVersion0', [ui.version]) }}</small></div>
    </template>
    <div class="wn" data-k="whatsnew">
      <div class="wn-hero" :class="{ ph: !hero.src }">
        <img v-if="hero.src" :src="hero.src" :srcset="hero.srcset || undefined" alt="" @error="heroBad = true" />
        <div v-if="hero.src" class="wn-ttl"><small>{{ $t('common.honeyfactory') }}</small><b>{{ $t('whatsNew.whatSNewIn0', [latest?.version]) }}</b></div>
        <div v-else class="wn-ph"><el-icon :size="34"><MagicStick /></el-icon><span>{{ $t('whatsNew.honeyfactory0', [latest?.version]) }}</span></div>
      </div>
      <div v-for="e in ui.whatsNewEntries" :key="e.version" class="wn-ver" :data-ver="e.version">
        <div class="wn-vh"><span class="wn-v">{{ e.version }}</span><b>{{ e.title }}</b><small class="muted">{{ e.date }}</small></div>
        <ul>
          <li v-for="(it, i) in e.items" :key="i"><span v-if="it.tag" class="wn-tag">{{ it.tag }}</span><span>{{ it.text }}</span>
            <a v-if="it.help" class="wn-more" @click="more(it.help)">{{ $t('whatsNew.learnMore') }}</a></li>
        </ul>
      </div>
    </div>
    <template #footer><el-button type="primary" data-k="whatsnew-ok" @click="closeWhatsNew">{{ $t('common.gotIt') }}</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { brand, loadBrand, themed } from '../brand';
import { closeWhatsNew, openHelp, ui } from '../start/ui';

loadBrand();
const heroBad = ref(false);
const hero = computed(() => (brand.loaded && !heroBad.value ? themed('whatsnew') : { src: '', srcset: '' }));
const latest = computed(() => ui.whatsNewEntries[0]);
function more(id: string) { closeWhatsNew(); openHelp(id, 'whatsnew'); }
</script>

<style scoped>
.wn-h { display: flex; align-items: baseline; gap: 10px; } .wn-h b { font-size: 16px; }
.wn { max-height: min(64vh, 620px); overflow: auto; margin: -6px -4px 0; padding: 0 4px; }
.wn-hero { position: relative; border-radius: 10px; overflow: hidden; margin-bottom: 14px; aspect-ratio: 4 / 1; background: var(--hm-surface-2); border: 1px solid var(--hm-border); }
.wn-ttl { position: absolute; left: 4.5%; top: 50%; transform: translateY(-50%); display: grid; gap: 2px; color: var(--hm-text); }
.wn-ttl small { color: var(--hm-amber-ink); letter-spacing: 1.5px; font-size: 12px; } .wn-ttl b { font-size: 22px; letter-spacing: .5px; }
.wn-hero img { width: 100%; height: 100%; object-fit: cover; display: block; }
.wn-ph { height: 100%; display: flex; align-items: center; justify-content: center; gap: 10px; color: var(--hm-setup-ink); font-size: 18px; font-weight: 600; letter-spacing: 1px;
  background: radial-gradient(500px 200px at 90% -20%, rgba(11, 165, 196, .12), transparent 60%), linear-gradient(120deg, var(--hm-primary-soft) 0%, var(--hm-surface) 70%); }
.wn-ver { margin-bottom: 14px; }
.wn-vh { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.wn-v { font-family: var(--hm-font-mono); font-weight: 700; color: var(--hm-setup-ink); background: var(--hm-primary-soft); border-radius: var(--hm-r-sm); padding: 1px 8px; font-size: 12.5px; }
.wn-vh b { font-size: 14px; }
ul { margin: 0; padding-left: 0; list-style: none; }
li { display: flex; gap: 8px; align-items: baseline; padding: 6px 0; border-bottom: 1px dashed var(--hm-border); line-height: 1.6; font-size: 13px; }
li:last-child { border-bottom: 0; }
.wn-tag { flex: none; font-size: 11.5px; color: var(--hm-amber-ink); background: var(--hm-amber-soft); border-radius: var(--hm-r-xs); padding: 0 6px; line-height: 20px; }
.wn-more { flex: none; font-size: 12px; cursor: pointer; white-space: nowrap; }
</style>
