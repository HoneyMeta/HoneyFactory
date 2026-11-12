import { $t } from '../i18n';
// HoneyFactory Teaching MES menu (5.0.1: MES pages share the HoneyFactory UI under /mes; expanding "MES" in the sidebar shows these groups).
// Group → pages. The e/ prefix denotes a generic entity page (EntityPage).
export type MesNavGroup = { group: string; icon: string; items: [string, string][] };

export const MES_NAV: MesNavGroup[] = [
  { group: $t('common.home'), icon: 'Odometer', items: [['/mes', $t('common.home')], ['/mes/screen', $t('mesNav.shopFloorDisplay')], ['/mes/m', $t('mesNav.mobileScanToReport')]] },
  { group: $t('mesNav.productionManagement'), icon: 'Operation', items: [['/mes/e/work_order', $t('mesNav.workOrders')], ['/mes/production/gantt', $t('mesNav.schedulingDispatch')], ['/mes/e/report', $t('mesNav.productionReports')], ['/mes/e/material_issue', $t('mesNav.materialIssueReturn')],
    ['/mes/e/part', $t('mesNav.wipSerializedParts')], ['/mes/trace', $t('common.traceability')], ['/mes/andon', $t('mesNav.andonBoard')], ['/mes/e/andon', $t('mesNav.andonRecords')], ['/mes/e/material_request', $t('mesNav.materialRequests')]] },
  { group: $t('mesNav.qualityManagement'), icon: 'CircleCheck', items: [['/mes/quality', $t('mesNav.qualityOverview')], ['/mes/e/insp_record', $t('mesNav.inspectionRecords')], ['/mes/e/ncr', $t('mesNav.nonconformances')], ['/mes/e/rework', $t('mesNav.reworkRecords')],
    ['/mes/quality/spc', $t('mesNav.spc')], ['/mes/e/report_8d', $t('mesNav.n8dReports')], ['/mes/e/insp_template', $t('mesNav.inspectionTemplates')], ['/mes/e/defect_code', $t('mesNav.defectCodes')]] },
  { group: $t('mesNav.equipmentManagement'), icon: 'Monitor', items: [['/mes/equipment/monitor', $t('mesNav.liveMonitor')], ['/mes/equipment/oee', $t('mesNav.oee')], ['/mes/e/equipment', $t('mesNav.equipmentRegister')], ['/mes/equipment/maint', $t('mesNav.checksPm')],
    ['/mes/e/repair_order', $t('mesNav.repairOrders')], ['/mes/e/alarm', $t('mesNav.alarmRecords')]] },
  { group: $t('mesNav.warehousingLogistics'), icon: 'Box', items: [['/mes/warehouse', $t('common.stock')], ['/mes/e/stock_txn', $t('mesNav.inventoryTransactions')], ['/mes/e/warehouse', $t('mesNav.warehousesLocations')], ['/mes/e/agv_task', $t('mesNav.agvTasks')], ['/mes/e/shipment', $t('mesNav.shipmentRecords')]] },
  { group: $t('mesNav.energyManagement'), icon: 'Lightning', items: [['/mes/energy', $t('mesNav.energyAnalysis')]] },
  { group: $t('mesNav.foundry'), icon: 'HotWater', items: [['/mes/foundry/heats', $t('mesNav.heatAnalysis')], ['/mes/e/heat', $t('mesNav.heatRecords')], ['/mes/e/treatment_rec', $t('mesNav.nodularizationRecords')], ['/mes/e/charge_material', $t('view3DHover.chargeMaterial')]] },
  { group: $t('common.machining'), icon: 'Tools', items: [['/mes/machining/tools', $t('mesNav.toolLife')], ['/mes/e/tool', $t('mesNav.cuttingToolRegister')], ['/mes/e/nc_program', $t('mesNav.ncPrograms')], ['/mes/machining/defects', $t('mesNav.machiningDefectStats')]] },
  { group: $t('mesNav.masterData'), icon: 'Files', items: [['/mes/e/material', $t('common.material')], ['/mes/e/bom', 'BOM'], ['/mes/e/route', $t('mesNav.routings')], ['/mes/e/process', $t('mesNav.operation')], ['/mes/e/plant', $t('common.factory')], ['/mes/e/workshop', $t('mesNav.workshop')],
    ['/mes/e/line', $t('common.line')], ['/mes/e/workstation', $t('livePanel.workstation')], ['/mes/e/shift', $t('mesNav.shift')], ['/mes/e/team', $t('common.teams')], ['/mes/e/employee', $t('mesNav.employees')]] },
  { group: $t('layout.system'), icon: 'Setting', items: [['/mes/e/datasource', $t('mesNav.dataSourcesTags')], ['/mes/system', $t('mesNav.systemStatus')]] },
];

/** Current path's MES menu location: [group, page]; use the longest prefix match for unlisted paths (e.g. details). */
export function findMesNav(path: string): { group: MesNavGroup; item: [string, string] } | null {
  let best: { group: MesNavGroup; item: [string, string] } | null = null;
  for (const g of MES_NAV) for (const it of g.items) {
    if (it[0] === path) return { group: g, item: it };
    if (it[0] !== '/mes' && path.startsWith(it[0] + '/') && (!best || it[0].length > best.item[0].length)) best = { group: g, item: it };
  }
  return best;
}

/** Breadcrumbs: MES / Group / Page */
export function mesCrumbs(path: string): { label: string; to?: string }[] {
  const out: { label: string; to?: string }[] = [{ label: 'MES', to: '/mes' }];
  const n = findMesNav(path);
  if (n && n.item[0] !== '/mes') out.push({ label: n.group.group, to: n.group.items[0][0] }, { label: n.item[1], to: n.item[0] });
  else if (n) out.push({ label: n.item[1] });
  return out;
}
