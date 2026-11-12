// 5.0 delivery package 3D models: reuse the UI models (FactoryScene.addStation) and export GLB in the browser with three.js GLTFExporter.
// Match server coordinates: factory origin at the building's bottom-left, Y up; glTF X = factory X, glTF Y = height, glTF Z = -factory Y (= floor plan y - building depth).
import { $t } from './i18n';
import * as THREE from 'three';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';
import { FactoryScene } from './scene';

const SKIP = new Set(['crew', 'operators', 'split', 'submodel']);
const safe = (s: string) => String(s).replace(/[^A-Za-z0-9_.-]+/g, '_') || 'device';

function b64(buf: ArrayBuffer) {
  const u = new Uint8Array(buf); let s = '';
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s);
}

function stripLabels(o: THREE.Object3D) {
  const kill: THREE.Object3D[] = [];
  o.traverse((c: any) => { if (c.isCSS2DObject) kill.push(c); });
  for (const c of kill) { c.parent?.remove(c); (c as any).element?.remove?.(); }
}

async function toGlb(exp: GLTFExporter, o: THREE.Object3D): Promise<ArrayBuffer> {
  return (await exp.parseAsync(o, { binary: true, onlyVisible: true })) as ArrayBuffer;
}

/** Return { models: {type: GLB base64}, scene: GLB base64 }; omit equipment types that fail to export (the server supplies simplified models). */
export async function buildDeliveryModels(meta: any): Promise<{ models: Record<string, string>; scene: string; failed: string[] }> {
  const div = document.createElement('div');
  div.style.cssText = 'position:fixed;left:-4000px;top:0;width:64px;height:64px;overflow:hidden;';
  document.body.appendChild(div);
  const fs = new FactoryScene(div);
  const failed: string[] = [];
  try {
    await fs.assets.load();
    fs.cx = 0; fs.cy = 0; fs.meta = meta;
    const depth = Number((meta.floor || [150, 56])[1]) || 56;
    for (const s of meta.stations) {
      if (SKIP.has(s.kind)) continue;
      try { fs.addStation(s); } catch (e) { failed.push(s.id); console.warn($t('delivery3d.n3dExportEquipment'), s.id, e); }
    }
    const exp = new GLTFExporter();
    const models: Record<string, string> = {};
    const first = new Map<string, any>();
    for (const s of meta.stations) if (!SKIP.has(s.kind) && fs.items.has(s.id) && !first.has(s.type)) first.set(s.type, s);
    for (const [typ, s] of first) {
      const it = fs.items.get(s.id); const g: THREE.Object3D = it.group;
      stripLabels(g);
      const p = g.position.clone(), r = g.rotation.clone(), parent = g.parent;
      const holder = new THREE.Group(); holder.name = typ; holder.add(g);      // Temporarily detach and zero the position for export
      g.position.set(0, 0, 0); g.rotation.set(0, 0, 0); g.name = typ;
      try { models[safe(typ)] = b64(await toGlb(exp, holder)); } catch (e) { failed.push(typ); console.warn($t('delivery3d.n3dExportType'), typ, e); }
      holder.remove(g); g.position.copy(p); g.rotation.copy(r);
      if (parent) parent.add(g);
    }
    const root = new THREE.Group(); root.name = 'Plant'; root.position.set(0, 0, -depth);
    for (const s of meta.stations) {
      const it = fs.items.get(s.id); if (!it) continue;
      stripLabels(it.group); it.group.name = s.id;
      it.group.userData = { code: s.id, name: s.name, type: s.type, model_file: `models/${safe(s.type)}.glb` };
      root.add(it.group);
    }
    const scene = b64(await toGlb(exp, root));
    return { models, scene, failed };
  } finally {
    try { fs.dispose(); } catch { /* */ }
    div.remove();
  }
}
