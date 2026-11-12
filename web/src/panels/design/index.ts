// Register design panels: design report export and SOP walkthrough.
import { $t } from '../../i18n';
import { defineAsyncComponent } from 'vue';

const A = (f: () => Promise<any>) => defineAsyncComponent(f);

export const panels = [
  { id: 'design-report', title: $t('designIndex.designReport'), icon: 'Document', component: A(() => import('./ReportExport.vue')), workspaces: ['design'], place: 'float',
    size: [520, 680], order: 70 },
  { id: 'design-sop', title: $t('sopPanel.sopWalkthrough'), icon: 'Guide', component: A(() => import('./SopPanel.vue')), workspaces: ['design', 'teach'], place: 'left', order: 71 },
];
