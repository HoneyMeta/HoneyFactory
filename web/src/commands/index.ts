// Command palette: register global commands (pages, factories, courses, help) here; load Workbench commands on entry to keep the panel registry out of the initial bundle.
// Other modules can add commands via import { registerCommand } from '../commands/registry'.
import type { Router } from 'vue-router';
import './core';
import './guides';

export { closeCommandPalette, openCommandPalette, registerCommand, registerCommands, registerProvider } from './registry';
export type { Command } from './registry';

let wb: Promise<any> | null = null;
export function installCommandLoaders(router: Router) {
  const need = (p: string) => { if (!wb && /^\/p\/[^/]+\/workbench/.test(p)) wb = import('./workbench'); };
  need(location.pathname);
  router.beforeEach((to) => { need(to.path); return true; });
}
