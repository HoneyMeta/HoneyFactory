<template>
  <div class="course-progress">
    <div class="vp-row" style="margin-bottom: 8px">
      <b>{{ data?.course.name }}</b>
      <el-switch v-if="data" :model-value="data.open_all" size="small" :active-text="$t('sections.openAll')" :inactive-text="$t('courseProgress.unlockInOrder')" @change="toggleOpen" />
      <span class="vp-grow" />
      <span class="vp-small vp-muted">{{ $t('courseProgress.cellsShowTheHighestScore') }}</span>
      <el-button size="small" text @click="load"><el-icon><Refresh /></el-icon></el-button>
    </div>
    <div class="wrap" v-if="data">
      <table class="vp-tbl mx">
        <tr>
          <th class="sticky">{{ $t('common.student') }}</th><th class="num">{{ $t('common.done') }}</th>
          <th v-for="(l, i) in data.lessons" :key="l.aid" class="lh" :title="`${l.chapter} · ${l.title}`" @click="emit('lesson', l.aid)">
            <div class="ln">{{ i + 1 }}</div><div class="lt">{{ l.title }}</div><span class="kind" :class="l.kind">{{ KIND_CN[l.kind] }}</span>
          </th>
        </tr>
        <tr v-for="r in data.rows" :key="r.username">
          <td class="sticky"><b>{{ r.name }}</b> <span class="vp-muted vp-small">{{ r.username }}</span></td>
          <td class="num">{{ r.done }}/{{ data.lessons.length }}</td>
          <td v-for="(c, i) in r.cells" :key="i" class="cell" :class="c.state" @click="emit('lesson', c.aid, r.username)">
            <template v-if="c.best !== null && c.best !== undefined">{{ c.best }}</template>
            <el-icon v-else-if="c.state === 'locked'"><Lock /></el-icon>
            <span v-else class="vp-muted">·</span>
          </td>
        </tr>
        <tr class="avg">
          <td class="sticky vp-muted">{{ $t('courseProgress.averageSubmitted') }}</td><td></td>
          <td v-for="p in data.per_lesson" :key="p.aid" class="num vp-small">{{ p.avg ?? '—' }}<div class="vp-muted">{{ $t('courseProgress.n0Students', [p.submitted]) }}</div></td>
        </tr>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { onMounted, ref, watch } from 'vue';
import { get, patch } from '../../api';
import './panel.css';

const props = defineProps<{ course: string; classId: number }>();
const emit = defineEmits<{ (e: 'lesson', aid: number, username?: string): void }>();
const KIND_CN: Record<string, string> = { cell: 'PLC', plant: $t('common.line'), diagnose: $t('common.troubleshooting') };
const data = ref<any>(null);
async function load() { data.value = await get(`/api/teach/courses/${props.course}/progress?class_id=${props.classId}`); }
async function toggleOpen(v: any) {
  await patch(`/api/teach/courses/${props.course}/classes/${props.classId}`, { open_all: !!v });
  await load();
}
watch(() => [props.course, props.classId], load);
onMounted(load);
defineExpose({ load });
</script>

<style scoped>
.wrap { overflow: auto; max-height: calc(100% - 40px); }
.mx { border-collapse: separate; border-spacing: 0; }
.mx .sticky { position: sticky; left: 0; background: var(--el-bg-color); z-index: 1; white-space: nowrap; min-width: 110px; }
.mx .lh { min-width: 64px; max-width: 80px; vertical-align: bottom; cursor: pointer; text-align: center; }
.mx .lh .ln { font-weight: 700; }
.mx .lh .lt { font-size: 11px; line-height: 1.25; white-space: normal; color: var(--el-text-color-regular); }
.mx .cell { text-align: center; cursor: pointer; font-variant-numeric: tabular-nums; font-weight: 600; }
.mx .cell.done { background: var(--el-color-success-light-9); color: var(--ok, var(--el-color-success)); }
.mx .cell.open { background: var(--el-fill-color-lighter); }
.mx .cell.locked { color: var(--el-text-color-placeholder); }
.mx .cell:hover { outline: 1px solid var(--el-color-primary); }
.kind { font-size: 10px; padding: 0 4px; border-radius: 3px; background: var(--el-fill-color); color: var(--el-text-color-secondary); }
.kind.plant { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.kind.diagnose { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.avg td { border-top: 2px solid var(--el-border-color); }
</style>
