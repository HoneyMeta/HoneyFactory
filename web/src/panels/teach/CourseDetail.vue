<template>
  <div v-if="course" class="cd course" :data-course="course.course" data-k="course-detail">
    <div class="cd-cover">
      <img v-if="courseCover(course)" :src="courseCover(course)" alt="" />
      <div class="cd-shade" />
      <div class="cd-head">
        <span v-if="course.preview" class="cd-pv">{{ $t('courseDetail.teacherPreviewStudentView') }}</span>
        <h2>{{ course.name }}</h2>
        <span class="vp-small">{{ course.class_name }}</span>
      </div>
    </div>
    <div class="cd-body">
      <p v-if="course.desc" class="cd-desc">{{ course.desc }}</p>
      <div class="cd-stats">
        <div><b>{{ pct(course) }}%</b><span>{{ $t('common.done') }}</span></div>
        <div><b>{{ course.done }}/{{ course.total }}</b><span>{{ $t('courseDetail.lesson') }}</span></div>
        <div><b>{{ avg ?? '—' }}</b><span>{{ $t('courseDetail.averageScore') }}</span></div>
        <div class="grow" />
        <el-button v-if="course.next" type="primary" data-k="detail-continue" @click="emit('open', course.next)">{{ course.done ? $t('courseDetail.continue') : $t('courseDetail.start') }}{{ nextLesson(course)?.title }}</el-button>
        <el-tag v-else-if="course.total && course.done >= course.total" type="success" effect="plain">{{ $t('courseDetail.allComplete') }}</el-tag>
      </div>
      <div class="cd-bar"><i :style="{ width: pct(course) + '%' }" /></div>

      <div v-for="(ch, ci) in course.chapters" :key="ch.id" class="cd-ch chapter" :class="{ shut: !isOpen(ch) }">
        <div class="cd-ch-h" @click="toggle(ch)">
          <span class="num">{{ ci + 1 }}</span>
          <span class="t">{{ ch.title }}</span>
          <span class="vp-small vp-muted">{{ ch.lessons.filter((l: any) => l.state === 'done').length }}/{{ ch.lessons.length }}</span>
          <el-icon><ArrowDown v-if="isOpen(ch)" /><ArrowRight v-else /></el-icon>
        </div>
        <template v-if="isOpen(ch)">
          <div v-for="l in ch.lessons" :key="l.aid" class="lesson cd-l" :class="[l.state, { cur: l.aid === course.next }]" :data-aid="l.aid"
               :title="l.state === 'locked' ? lockText(l) : ''" @click="l.state !== 'locked' && emit('open', l.aid)">
            <span class="st"><el-icon v-if="l.state === 'locked'"><Lock /></el-icon><el-icon v-else-if="l.state === 'done'"><CircleCheckFilled /></el-icon>
              <el-icon v-else-if="l.aid === course.next"><VideoPlay /></el-icon><span v-else class="ring" /></span>
            <span class="lt">{{ l.title }}<small v-if="l.state === 'locked'">{{ lockText(l) }}</small></span>
            <span class="kchip" :class="l.kind"><el-icon><component :is="KIND_ICON[l.kind] || 'Reading'" /></el-icon>{{ KIND_CN[l.kind] || l.kind }}</span>
            <span class="sc" :class="l.best === null || l.best === undefined ? '' : l.best >= 60 ? 'vp-pass' : 'vp-fail'">{{ l.best ?? '' }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// 4.6 Course details (right drawer on the student courses page): chapters, lesson status (locked / available / completed), and grades; click a lesson to open it.
import { computed, reactive, watch } from 'vue';
import { courseCover, KIND_CN, KIND_ICON, nextLesson, pct } from './courses';
import './panel.css';

const props = defineProps<{ course: any }>();
const emit = defineEmits<{ (e: 'open', aid: number): void }>();
const open = reactive<Record<string, boolean>>({});
watch(() => props.course?.course, () => { for (const k of Object.keys(open)) delete open[k]; });
// For many chapters: collapse completed chapters by default; expand the rest.
function isOpen(ch: any) { return ch.id in open ? open[ch.id] : !(ch.lessons.length && ch.lessons.every((l: any) => l.state === 'done')) || (props.course?.chapters?.length || 0) <= 2; }
function toggle(ch: any) { open[ch.id] = !isOpen(ch); }
const avg = computed(() => {
  const s = (props.course?.chapters || []).flatMap((ch: any) => ch.lessons).map((l: any) => l.best).filter((x: any) => x !== null && x !== undefined);
  return s.length ? Math.round(s.reduce((a: number, b: number) => a + b, 0) / s.length) : null;
});
function lockText(l: any) { return l.prereq?.length ? $t('courseDetail.completePrerequisite0First', [l.prereq.join($t('common.k360'))]) : $t('courseDetail.passThePreviousLesson60'); }
</script>

<style scoped>
/* 5.0.1: light theme (shared with HoneyMOM) */
.cd { color: var(--hm-text); display: flex; flex-direction: column; min-height: 100%; background: var(--hm-surface); }
.cd-cover { position: relative; aspect-ratio: 16 / 7; background: var(--hm-surface-2); overflow: hidden; flex: none; border-bottom: 1px solid var(--hm-border); }
.cd-cover img { width: 100%; height: 100%; object-fit: cover; }
.cd-shade { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(255, 255, 255, 0) 40%, rgba(255, 255, 255, .92) 100%); }
.cd-head { position: absolute; left: 20px; right: 20px; bottom: 12px; color: var(--hm-text); }
.cd-head h2 { margin: 2px 0; font-size: var(--hm-fs-xl); font-weight: var(--hm-fw-semibold); }
.cd-head .vp-small { color: var(--hm-text-2); }
.cd-pv { font-size: var(--hm-fs-2xs); background: var(--hm-amber-soft); color: var(--hm-amber-ink); border-radius: var(--hm-r-pill); padding: 1px 8px; }
.cd-body { padding: 16px 20px 28px; }
.cd-desc { margin: 0 0 12px; line-height: 1.7; font-size: var(--hm-fs-sm); color: var(--hm-text-2); }
.cd-stats { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cd-stats > div:not(.grow) { display: flex; flex-direction: column; min-width: 76px; padding: 6px 12px; border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); }
.cd-stats b { font-size: var(--hm-fs-lg); font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; font-weight: 600; }
.cd-stats span { font-size: var(--hm-fs-2xs); color: var(--hm-text-3); }
.grow { flex: 1; }
.cd-bar { height: 6px; background: var(--hm-surface-3); border-radius: 3px; margin: 12px 0 16px; overflow: hidden; }
.cd-bar i { display: block; height: 100%; background: var(--hm-primary); }
.cd-ch { border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); margin-bottom: 10px; overflow: hidden; background: var(--hm-surface); }
.cd-ch-h { display: flex; align-items: center; gap: 10px; padding: 9px 12px; cursor: pointer; background: var(--hm-surface-2); user-select: none; }
.cd-ch-h .num { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: var(--hm-fs-xs); font-family: var(--hm-font-num); background: var(--hm-primary-soft); color: var(--hm-setup-ink); flex: none; }
.cd-ch-h .t { flex: 1; font-weight: 600; }
.cd-l { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-top: 1px solid var(--hm-border); cursor: pointer; font-size: var(--hm-fs-sm); }
.cd-l:hover { background: var(--hm-surface-3); }
.cd-l.locked { cursor: not-allowed; color: var(--hm-text-3); }
.cd-l.cur { background: var(--hm-primary-soft); box-shadow: inset 3px 0 0 var(--hm-primary); }
.cd-l .st { width: 18px; display: grid; place-items: center; flex: none; }
.cd-l.done .st { color: var(--hm-run); } .cd-l.open .st { color: var(--hm-primary); }
.cd-l .ring { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--hm-border-strong); box-sizing: border-box; }
.cd-l .lt { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.cd-l .lt small { font-size: var(--hm-fs-2xs); color: var(--hm-text-3); }
.cd-l .sc { width: 34px; text-align: right; font-weight: 700; font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; }
.kchip { font-size: var(--hm-fs-2xs); padding: 1px 7px; border-radius: var(--hm-r-xs); background: var(--hm-offline-soft); color: var(--hm-offline-ink); display: inline-flex; align-items: center; gap: 3px; flex: none; }
.kchip.cell { background: var(--hm-setup-soft); color: var(--hm-setup-ink); } .kchip.plant, .kchip.point { background: var(--hm-amber-soft); color: var(--hm-amber-ink); } .kchip.quiz, .kchip.factory { background: var(--hm-run-soft); color: var(--hm-run-ink); }
.kchip.diagnose { background: var(--hm-fault-soft); color: var(--hm-fault-ink); } .kchip.mes { background: var(--hm-cyan-soft); color: var(--hm-cyan-ink); }
</style>