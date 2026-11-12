<template>
  <!-- 4.6.2 After grading a quiz response: student answer, correct answer (per teacher settings), and explanation. Supplied by the server (teach/api.py with_reveal); local client score estimates exclude correct answers. -->
  <div class="qrv vp-small" data-k="answer-reveal" :data-ok="d.ok ? 1 : 0">
    <div class="qrv-row" data-k="your-answer"><span class="qrv-k">{{ $t('quizReveal.yourAnswer') }}</span><span class="qrv-v" :class="d.ok ? 'vp-pass' : 'vp-fail'">{{ d.your || $t('quizReveal.notAnswered') }}</span></div>
    <div v-if="d.correct" class="qrv-row" data-k="correct-answer"><span class="qrv-k">{{ $t('common.correctAnswer') }}</span><span class="qrv-v"><b>{{ d.correct }}</b></span></div>
    <div v-if="d.explain" class="qrv-row qrv-ex" data-k="answer-explain"><span class="qrv-k">{{ $t('courseEditor.explanation') }}</span><span class="qrv-v">{{ d.explain }}</span></div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ d: any }>();
</script>

<style scoped>
.qrv { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; line-height: 1.6; }
.qrv-row { display: flex; gap: 8px; align-items: baseline; }
.qrv-k { flex: none; min-width: 4.5em; color: var(--el-text-color-secondary); }
.qrv-v { flex: 1; min-width: 0; overflow-wrap: anywhere; color: var(--el-text-color-primary); }
.qrv-ex { background: var(--el-fill-color-light); border-radius: 4px; padding: 4px 6px; margin-top: 2px; }
.qrv-ex .qrv-v { color: var(--el-text-color-regular); }
</style>
