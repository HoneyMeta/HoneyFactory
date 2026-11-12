<template>
  <!-- Browser / server web / SaaS web: explain that Teaching MES connects to local factories only in the desktop client + open the same page in the desktop client -->
  <div class="page mes-co" data-k="mes-client-only">
    <div class="page-head" data-tour="mes-head">
      <h2>MES</h2>
      <span class="sub">{{ $t('mesClientOnly.teachingMesWorkOrdersScheduling') }}</span>
    </div>
    <div class="co-grid">
      <ClientLink :path="route.fullPath" :title="$t('mesClientOnly.useMesInTheDesktop')"
        :why="$t('mesClientOnly.teachingMesRunsOnlyIn')"
        :steps="$t('mesClientOnly.inTheDesktopClientClick')" />
      <div class="card feats">
        <h3>{{ $t('mesClientOnly.whatYouCanDoIn') }}</h3>
        <ul>
          <li v-for="g in MES_NAV.slice(0, 7)" :key="g.group"><el-icon><component :is="g.icon" /></el-icon><b>{{ g.group }}</b>
            <span class="muted">{{ g.items.slice(0, 4).map((i) => i[1]).join($t('common.k360')) }}</span></li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router';
import ClientLink from '../components/ClientLink.vue';
import { MES_NAV } from './nav';

const route = useRoute();
</script>

<style scoped>
.co-grid { display: grid; grid-template-columns: minmax(0, 640px) minmax(0, 420px); gap: var(--hm-gap); align-items: start; }
@media (max-width: 1180px) { .co-grid { grid-template-columns: minmax(0, 640px); } }
.feats ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.feats li { display: flex; align-items: center; gap: 8px; font-size: var(--hm-fs-sm); min-width: 0; }
.feats li .el-icon { color: var(--hm-primary); flex: none; }
.feats li b { flex: none; color: var(--hm-text); font-weight: 600; }
.feats li .muted { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: var(--hm-fs-xs); }
</style>
