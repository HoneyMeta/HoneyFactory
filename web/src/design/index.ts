// Design system entry (5.0.1: ported from HoneyMOM's web/src/design, sharing light-theme tokens, components, and chart themes). app.use(installDesign) in main.ts globally registers Hm* components.
// HoneyFactory has no "Hand off to AI" selection layer: register v-ai / v-ai-rows as no-op directives so ported HoneyMOM pages and HmKpi work unchanged.
import type { App, Directive } from 'vue';
import HmAutoScroll from './components/HmAutoScroll.vue';
import HmCard from './components/HmCard.vue';
import HmDataTable from './components/HmDataTable.vue';
import HmEmpty from './components/HmEmpty.vue';
import HmKpi from './components/HmKpi.vue';
import HmNumber from './components/HmNumber.vue';
import HmSkeleton from './components/HmSkeleton.vue';
import HmStatus from './components/HmStatus.vue';
import HmTag from './components/HmTag.vue';
import HmToolbar from './components/HmToolbar.vue';

export { HmAutoScroll, HmCard, HmDataTable, HmEmpty, HmKpi, HmNumber, HmSkeleton, HmStatus, HmTag, HmToolbar };
export * from './format';
export { reducedMotion, useTickUp } from './motion';
export { CH, PALETTE, STATE_COLOR, seq, targetLine } from './chart';

const noop: Directive = {};
export function installDesign(app: App) {
  app.component('HmCard', HmCard).component('HmDataTable', HmDataTable).component('HmEmpty', HmEmpty).component('HmKpi', HmKpi)
    .component('HmNumber', HmNumber).component('HmSkeleton', HmSkeleton).component('HmStatus', HmStatus).component('HmTag', HmTag).component('HmToolbar', HmToolbar)
    .component('HmAutoScroll', HmAutoScroll);
  app.directive('ai', noop).directive('ai-rows', noop);
}
