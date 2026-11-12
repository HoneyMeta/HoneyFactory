<template>
  <div class="pv" ref="host" :class="{ placing: !!ed.placing, picking: !!ed.pick }" @drop="onDrop" @dragover.prevent>
    <!-- Toolbar: tools and view settings only; selected object properties are in the right-side "Properties" panel (4.4 removed floating property cards), so selection never wraps the toolbar. -->
    <div class="pv-bar" data-tour="pv-bar">
      <el-radio-group v-model="tool" size="small" class="pv-tools" data-tour="pv-tools">
        <el-tooltip v-for="t in TOOLS" :key="t[0]" :content="t[2] + (t[4] ? $t('planView.shortcut0', [t[4]]) : '')" placement="bottom" :show-after="300">
          <el-radio-button :value="t[0]" :disabled="t[0] === 'calib' && !ul?.url" :data-tour="'pv-tool-' + t[0]"><el-icon><component :is="t[3]" /></el-icon><span class="pv-lb">{{ t[1] }}</span></el-radio-button>
        </el-tooltip>
      </el-radio-group>
      <el-select v-if="floors.length > 1" v-model="ed.floor" size="small" style="width:90px" :title="$t('details.floor')">
        <el-option v-for="f in floors" :key="f.id" :value="f.id" :label="f.name" />
      </el-select>
      <el-select v-model="snap" size="small" style="width:100px" :title="$t('planView.snapToGridEndpointsMidpoints')">
        <el-option :value="0" :label="$t('planView.noGridSnap')" /><el-option :value="0.1" :label="$t('planView.grid01M')" /><el-option :value="0.5" :label="$t('planView.grid05M')" /><el-option :value="1" :label="$t('planView.grid1M')" />
      </el-select>
      <span class="grow" />
      <el-popover placement="bottom-end" :width="220" trigger="click">
        <template #reference><el-button size="small" data-tour="pv-layers"><el-icon><Files /></el-icon><span class="pv-lb">{{ $t('planView.layers') }}</span></el-button></template>
        <div class="v3-lay"><el-checkbox v-for="(n, k) in LAYER_CN" :key="k" v-model="show[k]">{{ n }}</el-checkbox></div>
      </el-popover>
      <el-popover placement="bottom-end" :width="320" trigger="click">
        <template #reference><el-button size="small" class="pv-hallbtn"><el-icon><House /></el-icon><span class="pv-lb">{{ $t('planView.factoryBuilding') }}</span></el-button></template>
        <div class="ulp pv-hall">
          <div class="row"><span>{{ $t('common.length') }}</span><el-input-number :model-value="hallWD[0]" size="small" :min="5" :controls="false" style="width:70px" @change="(x: any) => hallSize(x, hallWD[1])" /><span>m</span>
            <span>{{ $t('common.width') }}</span><el-input-number :model-value="hallWD[1]" size="small" :min="5" :controls="false" style="width:70px" @change="(x: any) => hallSize(hallWD[0], x)" /><span>m</span></div>
          <template v-if="outerW">
            <p class="muted small">{{ $t('planView.exteriorWall0IsA', [outerW.id, (outerW.doors || []).length, outerOk ? $t('planView.updatesWhenTheBuildingLength') : $t('planView.theShapeHasBeenEdited')]) }}</p>
            <div class="row"><el-button size="small" @click="selectOuter">{{ $t('planView.selectExteriorWall') }}</el-button>
              <el-button v-if="!outerOk" size="small" @click="rebuildOuter">{{ $t('planView.rebuildExteriorWallsToBuilding') }}</el-button></div>
          </template>
          <template v-else>
            <div class="row"><span>{{ $t('planView.wallThickness') }}</span><el-input-number v-model="hall.t" size="small" :min="0.1" :step="0.05" :controls="false" style="width:60px" /><span>m</span>
              <el-checkbox v-model="hall.door" size="small">{{ $t('planView.addMainDoorToFront') }}</el-checkbox><el-input-number v-model="hall.dw" size="small" :min="1" :controls="false" style="width:50px" :disabled="!hall.door" /><span>m</span></div>
            <el-button size="small" type="primary" @click="genOuter">{{ $t('planView.generateExteriorWallsEditable') }}</el-button>
            <p class="muted small">{{ $t('planView.generateExteriorWallsAroundThe') }}</p>
          </template>
          <div class="row"><span>{{ $t('planView.northDirection') }}</span><el-input-number :model-value="L.north || 0" size="small" :step="15" :controls="false" style="width:60px" @change="setNorth" /><span class="muted small">{{ $t('planView.clockwiseFromTheTopOf') }}</span></div>
        </div>
      </el-popover>
      <el-popover placement="bottom-end" :width="280" trigger="click">
        <template #reference><el-button size="small"><el-icon><OfficeBuilding /></el-icon><span class="pv-lb">{{ $t('details.floor') }}</span></el-button></template>
        <div class="ulp">
          <div v-for="(f, i) in floors" :key="f.id" class="row"><el-input :model-value="f.name" size="small" style="width:90px" @change="(x: string) => setFloor(i, { name: x })" />
            <span class="small muted">{{ $t('planView.elevation') }}</span><el-input-number :model-value="f.z" size="small" :step="0.5" :controls="false" style="width:60px" @change="(x: any) => setFloor(i, { z: x })" /><span class="small muted">m</span>
            <el-button v-if="i > 0" size="small" text type="danger" @click="delFloor(i)"><el-icon><Delete /></el-icon></el-button></div>
          <el-button size="small" @click="addFloor">{{ $t('planView.addFloor') }}</el-button>
          <p class="muted small">{{ $t('planView.changeAnEquipmentItemS') }}</p>
        </div>
      </el-popover>
      <el-popover placement="bottom-end" :width="300" trigger="click">
        <template #reference><el-button size="small" data-tour="pv-underlay"><el-icon><Picture /></el-icon><span class="pv-lb">{{ $t('planView.backgroundImage') }}</span></el-button></template>
        <div class="ulp">
          <template v-if="ul?.url">
            <div class="row"><span>{{ $t('common.show') }}</span><el-switch :model-value="ul.show !== false" @change="(x: any) => setUl({ show: x })" /></div>
            <div class="row"><span>{{ $t('planView.opacity') }}</span><el-slider :model-value="ul.opacity ?? 0.5" :min="0.1" :max="1" :step="0.05" style="flex:1" @change="(x: any) => setUl({ opacity: x })" /></div>
            <div class="row"><span>{{ $t('planView.topLeftX') }}</span><el-input-number :model-value="ul.x" size="small" :step="0.5" :controls="false" @change="(x: any) => setUl({ x })" /><span>m</span></div>
            <div class="row"><span>{{ $t('planView.topLeftY') }}</span><el-input-number :model-value="ul.y" size="small" :step="0.5" :controls="false" @change="(y: any) => setUl({ y })" /><span>m</span></div>
            <div class="row"><span>{{ $t('planView.width') }}</span><el-input-number :model-value="ul.w" size="small" :min="1" :controls="false" @change="(x: any) => setUl({ w: x, h: x * ul.h / ul.w })" /><span>m</span></div>
            <p class="muted small">{{ $t('planView.useCalibrateBackgroundImageTo') }}</p>
            <el-button size="small" type="danger" plain @click="exec([{ op: 'update_plant', set: { 'plant.underlay': null } }], $t('planView.removeBackgroundImage'))">{{ $t('planView.removeBackgroundImage') }}</el-button>
          </template>
          <p v-else class="muted small">{{ $t('planView.uploadACadScreenshotOr') }}</p>
          <el-button size="small" type="primary" @click="pickFile">{{ $t('planView.uploadImage') }}</el-button>
          <input ref="file" type="file" accept="image/*" hidden @change="upload" />
        </div>
      </el-popover>
      <el-button size="small" :title="$t('planView.fitAllHome')" @click="fit"><el-icon><FullScreen /></el-icon><span class="pv-lb">{{ $t('common.fitAll') }}</span></el-button>
      <GuideButton area="plan" size="sm" />
    </div>

    <div class="pv-main" ref="mainEl" data-tour="pv-canvas">
      <svg ref="svg" class="pv-svg" :class="['t-' + tool, { connecting: !!conn, panning: drag.pan, spacepan: spaceDown && !drag.pan, moving: edit.on && edit.mode === 'move' && edit.moved }]" @wheel.prevent="onWheel" @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onLeave"
        @mouseenter="hover = true" @contextmenu.prevent="onCtx" @dblclick="onDbl">
        <defs>
          <pattern id="g1" :width="gridStep" :height="gridStep" patternUnits="userSpaceOnUse"><path :d="`M ${gridStep} 0 L 0 0 0 ${gridStep}`" class="grid" /></pattern>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arr" /></marker>
          <marker id="arrp" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="arrp" /></marker>
        </defs>
        <g :transform="`translate(${v.tx},${v.ty}) scale(${v.k})`">
          <rect :x="bounds.x0 - 200" :y="bounds.y0 - 200" :width="bounds.x1 - bounds.x0 + 400" :height="bounds.y1 - bounds.y0 + 400" fill="url(#g1)" />
          <image v-if="ul?.url && ul.show !== false" :href="ul.url" :x="ul.x" :y="ul.y" :width="ul.w" :height="ul.h" :opacity="ul.opacity ?? 0.5" preserveAspectRatio="none" />
          <rect v-if="floor && !outerW" x="0" y="0" :width="floor[0]" :height="floor[1]" class="floor" />
          <g v-for="(a, i) in areas" :key="a.name">
            <rect :x="a.x[0]" :y="bounds.y0" :width="a.x[1] - a.x[0]" :height="bounds.y1 - bounds.y0" :class="['area', 'a' + (i % 4)]" />
            <text :x="(a.x[0] + a.x[1]) / 2" :y="bounds.y0 + 2.4" class="area-t" :font-size="Math.max(1.6, 12 / v.k)">{{ a.name }}</text>
          </g>
          <g v-if="show.zones">
            <g v-for="z in LL.zones || []" :key="z.id" :data-lk="'zones:' + z.id" :class="['lz', { sel: isLay('zones', z.id) }]">
              <polygon :points="pts(z.pts)" :style="{ fill: z.color || '#1463d6', stroke: z.color || '#1463d6' }" />
              <text :x="cen(z.pts)[0]" :y="cen(z.pts)[1]" :font-size="Math.max(0.9, 12 / v.k)">{{ z.name }}</text></g>
          </g>
          <g v-if="show.aisles">
            <g v-for="a in LL.aisles || []" :key="a.id" :data-lk="'aisles:' + a.id" :class="['la', { sel: isLay('aisles', a.id) }]">
              <polyline :points="pts(a.pts)" :stroke-width="a.w ?? 3" class="la-body" /><polyline :points="pts(a.pts)" class="la-mid" /></g>
          </g>
          <g v-if="show.walls">
            <g v-for="r in wallsR" :key="r.w.id" :data-lk="'walls:' + r.w.id" :class="['lwg', { sel: isLay('walls', r.w.id), outer: r.w.outer }]">
              <polyline :points="pts(r.w.pts)" :stroke-width="Math.max(r.w.t ?? 0.24, 10 / v.k)" class="lw-hit" />
              <polyline v-for="(pc, i) in r.pieces" :key="i" :points="pts(pc)" :stroke-width="r.w.t ?? 0.24" class="lw" />
              <g v-for="d in r.doors" :key="'d' + d.k" class="ldoor">
                <line v-if="d.w >= 2.5" :x1="d.a[0]" :y1="d.a[1]" :x2="d.b[0]" :y2="d.b[1]" class="ldoor-roll" />
                <path v-else :d="doorPath(d)" />
              </g>
            </g>
          </g>
          <g v-if="show.paths">
            <g v-for="e in LL.paths?.edges || []" :key="e.id" :data-lk="'edges:' + e.id" :class="['le', { sel: isLay('edges', e.id), one: e.oneway, iss: pathIss.has(e.id) }]">
              <template v-if="nodeAt(e.a) && nodeAt(e.b)">
                <line :x1="nodeAt(e.a).x" :y1="nodeAt(e.a).y" :x2="nodeAt(e.b).x" :y2="nodeAt(e.b).y" :marker-end="e.oneway ? 'url(#arrp)' : undefined" />
                <line class="le-hit" :x1="nodeAt(e.a).x" :y1="nodeAt(e.a).y" :x2="nodeAt(e.b).x" :y2="nodeAt(e.b).y" />
                <text v-if="e.vmax" class="le-v" :x="(nodeAt(e.a).x + nodeAt(e.b).x) / 2" :y="(nodeAt(e.a).y + nodeAt(e.b).y) / 2 - 4 / v.k" :font-size="10 / v.k">≤{{ e.vmax }} m/s</text></template></g>
            <g v-for="s in stationLinks" :key="'sl' + s.id" class="lsl">
              <line :x1="s.x" :y1="s.y" :x2="s.bx" :y2="s.by" /><text :x="s.x" :y="s.y + 14 / v.k" :font-size="10 / v.k">{{ s.name }}</text></g>
            <circle v-for="n in LL.paths?.nodes || []" :key="n.id" :data-lk="'nodes:' + n.id" :cx="n.x" :cy="n.y" :r="Math.max(0.35, (n.kind && n.kind !== 'node' ? 6 : 5) / v.k)"
              :class="['ln2', n.kind || 'node', { sel: isLay('nodes', n.id), pend: draw.node === n.id, iss: pathIss.has(n.id) }]"><title>{{ nodeTitle(n) }}</title></circle>
          </g>
          <g v-if="show.dims" class="ldim">
            <g v-for="d in LL.dims || []" :key="d.id" :data-lk="'dims:' + d.id" :class="{ sel: isLay('dims', d.id) }">
              <line :x1="d.a[0]" :y1="d.a[1]" :x2="d.b[0]" :y2="d.b[1]" /><line class="ldim-hit" :x1="d.a[0]" :y1="d.a[1]" :x2="d.b[0]" :y2="d.b[1]" />
              <circle :cx="d.a[0]" :cy="d.a[1]" :r="3 / v.k" /><circle :cx="d.b[0]" :cy="d.b[1]" :r="3 / v.k" />
              <text :x="(d.a[0] + d.b[0]) / 2" :y="(d.a[1] + d.b[1]) / 2 - 5 / v.k" :font-size="12 / v.k">{{ dist(d.a, d.b).toFixed(2) }} m</text></g>
          </g>
          <!-- Drawing in progress -->
          <g class="ldraw-g">
            <polygon v-if="tool === 'zones' && draw.pts.length >= 2" :points="pts([...draw.pts, tp.p])" class="ldraw zones" />
            <polyline v-else-if="draw.pts.length && ['walls', 'aisles', 'dims'].includes(tool)" :points="pts([...draw.pts, tp.p])" :class="['ldraw', tool]" />
            <polyline v-else-if="tool === 'zones' && draw.pts.length" :points="pts([...draw.pts, tp.p])" class="ldraw" />
            <rect v-if="draw.rect" :x="Math.min(draw.rect[0], tp.p[0])" :y="Math.min(draw.rect[1], tp.p[1])" :width="Math.abs(tp.p[0] - draw.rect[0])" :height="Math.abs(tp.p[1] - draw.rect[1])"
              :class="['ldraw', tool === 'rzone' ? 'zones' : 'walls']" />
            <line v-if="tool === 'paths' && nodeAt(draw.node)" :x1="nodeAt(draw.node).x" :y1="nodeAt(draw.node).y" :x2="tp.p[0]" :y2="tp.p[1]" class="ldraw" />
          </g>
          <!-- Connections (4.4): endpoints on object border ports, orthogonal routing around objects, rounded corners, offset parallel lines; material lines (gray, arrows),
               signal wires (equipment ⇄ PLC, orange dashed, bundles labeled "N channels"), network cables (purple) -->
          <g v-if="show.links" :class="['pv-links', { hov: !!hoverRel }]">
            <g v-for="l in lineViews" :key="l.key" :class="[l.kind === 'material' ? 'lm' : 'lc lc-' + l.kind, l.cls, relCls(l.ids), { sel: l.ids.includes(ed.selLink), bad: !!l.fault }]"
              :data-link="l.ids[0]" :data-kind="l.kind" :data-a="l.a" :data-b="l.b">
              <path :d="l.d" :class="l.kind === 'material' ? 'ln' : 'lc-l'" :marker-end="l.kind === 'material' ? 'url(#arr)' : undefined" /><path :d="l.d" class="lc-hit" />
              <g v-if="l.label" :transform="`translate(${l.m[0]},${l.m[1]}) scale(${1 / v.k})`" class="lc-tag">
                <rect :x="-l.label.length * 3.6 - 5" y="-8" :width="l.label.length * 7.2 + 10" height="15" rx="7.5" /><text y="3.5">{{ l.label }}</text></g>
              <title>{{ l.title }}</title>
            </g>
          </g>
          <g v-for="b in otherFloor" :key="'o' + b.id" :transform="`translate(${b.pos[0]},${b.pos[1]}) rotate(${b.rot || 0})`" class="blk ghost">
            <rect :x="-b.size[0] / 2" :y="-b.size[1] / 2" :width="b.size[0]" :height="b.size[1]" rx="0.25" class="body" /></g>
          <g v-for="b in procBlocks" :key="b.id" :transform="`translate(${b.pos[0] + (isSel(b.id) ? drag.dx : 0)},${b.pos[1] + (isSel(b.id) ? drag.dy : 0)}) rotate(${b.rot || 0})`"
            :class="['blk', relCls([], b.id), connCls(b.id), { sel: isSel(b.id), hl: ed.highlight.includes(b.id), err: issue[b.id] }]" :data-id="b.id">
            <title>{{ $t('archView.n0123', [b.name, typeOf(b).label, b.id, rtById[b.id] ? ' · ' + (STATE_CN[rtById[b.id].state] || rtById[b.id].state) : '']) }}</title>
            <rect :x="-b.size[0] / 2" :y="-b.size[1] / 2" :width="b.size[0]" :height="b.size[1]" rx="0.25" :style="{ fill: typeOf(b).color }" class="body" />
            <line :x1="b.size[0] / 2 - 0.6" :y1="0" :x2="b.size[0] / 2" :y2="0" class="dir" />
            <circle v-if="rtById[b.id] && ed.overlay" :cx="-b.size[0] / 2 + dotR(b)" :cy="-b.size[1] / 2 + dotR(b)" :r="dotR(b) * 0.62" class="stdot" :style="{ fill: STATE_COLOR[rtById[b.id].state] || '#888' }" />
            <circle v-if="bpMark(b.id)" :cx="b.size[0] / 2 - 0.55" :cy="-b.size[1] / 2 + 0.55" r="0.42" :class="['bpm', bpMark(b.id)]"><title>{{ $t('planView.breakpointRightClickToEdit') }}</title></circle>
          </g>
          <!-- Draw control / communication / information system symbols above production equipment (fixed screen size may overlap nearby equipment when zoomed out; keep symbols visible). -->
          <g v-for="b in symBlocks" :key="b.id" :transform="`translate(${b.pos[0] + (isSel(b.id) ? drag.dx : 0)},${b.pos[1] + (isSel(b.id) ? drag.dy : 0)})`"
            :class="['blk', 'symb', 'ly-' + layerOf(b.id), relCls([], b.id), connCls(b.id), { sel: isSel(b.id), hl: ed.highlight.includes(b.id) }]" :data-id="b.id">
            <title>{{ $t('planView.n01234', [b.name, typeOf(b).label, b.id, plcState(b.id) ? ' · ' + PLC_CN[plcState(b.id)] : '', b.type === 'plc' ? $t('planView.doubleClickToOpenThe') : '']) }}</title>
            <g :transform="`scale(${symScale / v.k})`">
              <rect x="-22" y="-19" width="44" height="38" rx="5" class="sym-hit" />
              <LayerSymbol :type="b.type" :color="layerColor(b.id)" :state="plcState(b.id)" />
              <text v-if="show.labels" y="29" class="sym-name">{{ fitText(b.name || b.id, 120, 11) }}</text>
              <text v-if="show.labels && v.k >= 9 && b.type === 'plc' && plcState(b.id)" y="42" :class="['sym-st', plcState(b.id)]">{{ PLC_EN[plcState(b.id)] }}</text>
            </g>
          </g>
          <!-- Equipment labels: type icon + name; scale font size with zoom in screen pixels, with a minimum size. -->
          <g v-if="show.labels" class="lbls">
            <g v-for="lb in blkLabels" :key="lb.id" :class="[relCls([], lb.id), { sel: isSel(lb.id) }]">
              <component :is="lb.icon" :x="lb.ix" :y="lb.iy" :width="lb.is" :height="lb.is" class="bico" />
              <text v-if="lb.text" :x="lb.tx" :y="lb.ty" :font-size="lb.fs" :text-anchor="lb.anchor">{{ lb.text }}</text>
              <!-- Zoomed in: one key metric (buffer count/capacity with a progress bar; OEE or status for other equipment), like graph cards. -->
              <template v-if="lb.kf">
                <text :x="lb.tx" :y="lb.ky" :font-size="lb.kfs" text-anchor="middle" class="kfig">{{ lb.kf }}</text>
                <g v-if="lb.fill !== undefined" class="kbar"><rect :x="lb.tx - lb.bw / 2" :y="lb.ky + lb.kfs * 0.35" :width="lb.bw" :height="lb.kfs * 0.32" rx="0.05" class="kbar-bg" />
                  <rect :x="lb.tx - lb.bw / 2" :y="lb.ky + lb.kfs * 0.35" :width="lb.bw * lb.fill" :height="lb.kfs * 0.32" rx="0.05" :class="['kbar-f', { hi: lb.fill > 0.85 }]" /></g>
              </template>
            </g>
            <text v-for="b in blocks.filter((x: any) => (ed.watches[x.id] || []).length)" :key="'w' + b.id" class="wtxt" :x="b.pos[0]" :y="b.pos[1] + b.size[1] / 2 + 0.9" :font-size="11 / v.k">{{ watchRows(b.id).map((w) => w[0] + ' ' + w[1]).join('  ') }}</text>
          </g>
          <g v-if="show.vehicles">
            <g v-for="a in vehicles" :key="a.id" :transform="`translate(${a.x},${a.y})`" class="veh"><circle r="0.7" /><text y="-1" font-size="0.9">{{ a.id }}</text></g>
          </g>
          <!-- Alignment guides (align with other equipment edges / centers while dragging) -->
          <g v-if="guides.length" class="pv-guides">
            <line v-for="(g, i) in guides" :key="i" :x1="g[0]" :y1="g[1]" :x2="g[2]" :y2="g[3]" />
          </g>
          <!-- Connection ports (appear at edge midpoints on hover; drag to another machine to connect) and "+" (append and connect a machine) -->
          <g v-if="portsOf" class="pv-ports" :data-hov="portsOf.id">
            <circle v-for="q in portsOf.pts" :key="q.s" :cx="q.p[0]" :cy="q.p[1]" :r="5 / v.k" class="pv-port" :data-port="portsOf.id + ':' + q.s">
              <title>{{ $t('planView.dragToAnotherDeviceTo') }}</title></circle>
            <g v-if="portsOf.plus" :transform="`translate(${portsOf.plus[0]},${portsOf.plus[1]}) scale(${1 / v.k})`" class="pv-plus" :data-plus="portsOf.id">
              <circle r="9" /><path d="M -4.5 0 H 4.5 M 0 -4.5 V 4.5" /><title>{{ $t('planView.addAndConnectADevice') }}</title></g>
          </g>
          <g v-if="conn" class="pv-conn-g">
            <path :d="conn.d" :class="['pv-conn', conn.kind || (conn.over ? 'bad' : '')]" />
            <g v-if="conn.tip" :transform="`translate(${conn.b[0]},${conn.b[1]}) scale(${1 / v.k})`" :class="['pv-conn-tip', conn.kind ? '' : 'bad']">
              <rect x="10" y="8" :width="conn.tip.length * 12 + 12" height="20" rx="10" /><text x="16" y="22">{{ conn.tip }}</text></g>
          </g>
          <rect v-if="box" :x="Math.min(box.x0, box.x1)" :y="Math.min(box.y0, box.y1)" :width="Math.abs(box.x1 - box.x0)" :height="Math.abs(box.y1 - box.y0)" class="rubber" />
          <g v-if="meas.a" class="meas">
            <line :x1="meas.a[0]" :y1="meas.a[1]" :x2="(meas.b || tp.p)[0]" :y2="(meas.b || tp.p)[1]" />
            <circle :cx="meas.a[0]" :cy="meas.a[1]" :r="4 / v.k" /><circle v-if="meas.b" :cx="meas.b[0]" :cy="meas.b[1]" :r="4 / v.k" />
            <text :x="((meas.a[0] + (meas.b || tp.p)[0]) / 2)" :y="((meas.a[1] + (meas.b || tp.p)[1]) / 2) - 6 / v.k" :font-size="13 / v.k">{{ measLen.toFixed(2) }} m</text>
          </g>
          <!-- Selected element: segment lengths, vertex / edge midpoint / doorway handles -->
          <g v-if="segLabels.length" class="lseg">
            <text v-for="(s, i) in segLabels" :key="i" :x="s.x" :y="s.y" :font-size="11 / v.k">{{ s.t }}</text>
          </g>
          <g v-if="handles" class="lh">
            <circle v-for="m in handles.mids" :key="'m' + m.i" :data-h="'m' + m.i" :cx="m.p[0]" :cy="m.p[1]" :r="4.5 / v.k" class="lh-m"><title>{{ $t('planView.dragToAddAVertex') }}</title></circle>
            <rect v-for="q in handles.verts" :key="'v' + q.i" :data-h="q.h" :x="q.p[0] - 5 / v.k" :y="q.p[1] - 5 / v.k" :width="10 / v.k" :height="10 / v.k" class="lh-v">
              <title>{{ $t('planView.dragToRepositionDoubleClick') }}</title></rect>
            <path v-for="d in handles.doors" :key="'o' + d.k" :data-h="'o' + d.k" :d="diamond(d.c, 6 / v.k)" class="lh-d"><title>{{ $t('planView.doorOpeningDragAlongThe') }}</title></path>
          </g>
          <!-- Snap hint -->
          <g v-if="snapShow" class="lsnap" :transform="`translate(${tp.p[0]},${tp.p[1]})`">
            <rect v-if="tp.kind === 'end' || tp.kind === 'blk'" :x="-6 / v.k" :y="-6 / v.k" :width="12 / v.k" :height="12 / v.k" />
            <path v-else-if="tp.kind === 'mid'" :d="`M 0 ${-7 / v.k} L ${6 / v.k} ${5 / v.k} L ${-6 / v.k} ${5 / v.k} Z`" />
            <path v-else-if="tp.kind === 'perp'" :d="`M ${-6 / v.k} ${6 / v.k} H ${6 / v.k} M 0 ${6 / v.k} V ${-6 / v.k}`" />
            <circle v-else-if="tp.kind === 'node'" :r="7 / v.k" />
            <path v-else-if="tp.kind === 'on'" :d="`M ${-5 / v.k} ${-5 / v.k} L ${5 / v.k} ${5 / v.k} M ${5 / v.k} ${-5 / v.k} L ${-5 / v.k} ${5 / v.k}`" />
            <text :x="9 / v.k" :y="-8 / v.k" :font-size="10 / v.k">{{ SNAP_CN[tp.kind] }}</text>
          </g>
        </g>
        <PlanRulers :k="v.k" :tx="v.tx" :ty="v.ty" :w="size.w" :h="size.h" :cursor="cursor" :north="L.north || 0" :rulers="show.rulers" v-if="size.w" />
      </svg>
      <!-- Multiple equipment selection: align / distribute / rotate (floating above the canvas, as in the graph); single-object properties stay in the right-side "Properties" panel. -->
      <div v-if="tool === 'select' && floorSel.length >= 2" class="pv-align">
        <span class="muted">{{ $t('planView.n0UnitsSelected', [floorSel.length]) }}</span>
        <el-tooltip v-for="a in ALIGN" :key="a[0]" :content="a[1]" :show-after="200"><el-button size="small" text @click="arrange(a[0], 'pos')">{{ a[2] }}</el-button></el-tooltip>
        <span class="pv-align-sep" />
        <el-tooltip :content="$t('planView.rotate90CounterclockwiseShiftR')" :show-after="200"><el-button size="small" text @click="rotateSel(-90)"><el-icon><RefreshLeft /></el-icon></el-button></el-tooltip>
        <el-tooltip :content="$t('planView.rotate90ClockwiseR')" :show-after="200"><el-button size="small" text @click="rotateSel(90)"><el-icon><RefreshRight /></el-icon></el-button></el-tooltip>
        <el-tooltip :content="$t('planView.duplicateInRowsAndColumns')" :show-after="200"><el-button size="small" text @click="pv.arrayOpen = true"><el-icon><Grid /></el-icon></el-button></el-tooltip>
      </div>
      <div v-if="emptyFloor" class="pv-empty">
        <b>{{ $t('planView.noEquipmentIn0Yet', [floors.length > 1 ? $t('planView.thisFloor') : $t('planView.floorPlan')]) }}</b>
        <p class="muted">{{ $t('planView.dragEquipmentFromTheAsset') }}</p>
        <div class="row"><el-button size="small" @click="tool = 'rwall'"><el-icon><FullScreen /></el-icon>{{ $t('planView.drawEnclosingWalls') }}</el-button>
          <el-button size="small" @click="pickFile"><el-icon><Picture /></el-icon>{{ $t('planView.uploadBuildingBackgroundImage') }}</el-button>
          <el-button size="small" @click="openQuick(null)"><el-icon><Plus /></el-icon>{{ $t('planView.addEquipment') }}</el-button></div>
      </div>
      <QuickAdd v-if="qa.show" :x="qa.x" :y="qa.y" :title="qa.title" :only="qa.only" @pick="quickPick" @close="qa.show = false" />
      <ArrayDialog />
      <div v-if="hud" class="pv-hud mono" :style="{ left: hud.x + 'px', top: hud.y + 'px' }">
        <span v-for="(t, i) in hud.rows" :key="i">{{ t }}</span>
        <span v-if="typed || hud.input" class="pv-typed">{{ $t('planView.enter0', [typed]) }}<i>▌</i></span>
      </div>
    </div>
    <div class="pv-foot mono" data-tour="pv-foot" :title="$t('planView.selectToolHoverOverEquipment')">
      {{ $t('planView.x0MY1', [cursor[0].toFixed(2), cursor[1].toFixed(2), v.k.toFixed(1)]) }}
      <template v-if="drag.dx || drag.dy"> {{ $t('planView.moveX0Y1', [drag.dx.toFixed(2), drag.dy.toFixed(2)]) }}</template>
      <template v-if="tool === 'calib'"> {{ $t('planView.clickTwoPointsOnThe') }}</template>
      <template v-else-if="tool === 'measure'"> {{ $t('planView.clickTwiceToMeasureDistance') }}</template>
      <template v-else-if="['walls', 'zones', 'aisles'].includes(tool)"> {{ $t('planView.clickEachPointTypeA') }}</template>
      <template v-else-if="tool === 'rwall' || tool === 'rzone'"> {{ $t('planView.clickTwoOppositeCornersOr') }}</template>
      <template v-else-if="tool === 'paths'"> {{ $t('planView.clickEmptySpaceToAdd') }}</template>
      <template v-else-if="tool === 'dims'"> {{ $t('planView.clickTwiceToAddA') }}</template>
      <template v-else-if="conn"> {{ $t('planView.releaseToConnectTo0', [conn.over ? (blocksById[conn.over]?.name || conn.over) : $t('planView.hereAddAndConnectA'), conn.kind ? $t('common.k546') + CONN_CN[conn.kind] : '']) }}</template>
      <template v-else> {{ $t('planView.hoverOverEquipmentAndDrag') }}</template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t, matches } from '../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { canEdit, P, post } from '../api';
import { ctxTools, openBlockMenu, openCtx, openLinkMenu, openPaneMenu } from './shell/contextMenu';
import { layerOf, layerVisible, linkKind, linkVisible, loadFilter, relatedSet } from './shell/relations';
import { panelById } from './shell/panels';
import LayerSymbol from './plan/LayerSymbol.vue';
import { linkFault, PLC_CN, plcState, useLive } from './plan/live';
import { bpMark, watchRows } from './shell/graphdebug';
import { placeAt } from './shell/place';
import {
  arrange, blocksById, cloneOps, ed, exec, flash, makeBlock, nodePosNear, openFloat, paste, rtById, select, selBlocks, STATE_CN, STATE_COLOR, typeOf, type Op,
} from './store';
import { angleDeg, dist, doorShapes, extOf, isClosed, mid, ortho, polar, projSeg, r2, remapDoors, rp, sAt, segsOf, wallPieces, type Pt } from './plan/geom';
import ArrayDialog from './plan/ArrayDialog.vue';
import PlanRulers from './plan/PlanRulers.vue';
import QuickAdd from './plan/QuickAdd.vue';
import GuideButton from '../components/GuideButton.vue';
import { addConnected, CONN_CN, connectBlocks, connKind, connWhy, nextPos } from './plan/connect';
import { elbow, labelAt, pathD, placeLabels, routeAll, shift, type Conn, type End, type Rect, type Route } from './plan/route';
import {
  addOuterWall, allSels, clipCount, clone, copyLay, duplicateLay, getClip, isLay, itemOf, L, lid, listOf, LL, NODE_CN, outerMatches, outerOf, pasteLay, pointsOf, pv,
  rebuildOuter, removeLays, rotateSel, sel1, setHallSize, setItem, setLayout, translate, type LSel,
} from './plan/state';

const host = ref<HTMLElement>(), svg = ref<SVGSVGElement>(), file = ref<HTMLInputElement>(), mainEl = ref<HTMLElement>();
const tool = ref('select'), snap = ref(0.5);
const show = reactive<Record<string, boolean>>({ links: true, labels: true, vehicles: true, zones: true, aisles: true, walls: true, paths: true, dims: true, rulers: true });
const LAYER_CN: Record<string, string> = { walls: $t('planView.wall'), zones: $t('common.area'), aisles: $t('common.channel'), paths: $t('planView.agvPathNetwork'), dims: $t('planView.dimensions'), links: $t('planView.connectionsMaterialSignalNetwork'), labels: $t('planView.equipmentIconsNamesAndKey'), vehicles: $t('planView.vehicles'), rulers: $t('planView.rulerScaleBarAndNorth') };
const TOOLS: [string, string, string, string, string][] = [['select', $t('common.select'), $t('planView.selectAndDragEquipmentAnd'), 'Pointer', 'V'],
  ['walls', $t('planView.wall'), $t('planView.drawWallsClickEachPoint'), 'Postcard', 'W'], ['rwall', $t('planView.rectangularWalls'), $t('planView.drawRectangularWallsClickTwo'), 'FullScreen', ''],
  ['zones', $t('common.area'), $t('planView.drawAPolygonalAreaClick'), 'Crop', ''], ['rzone', $t('planView.rectangularArea'), $t('planView.drawARectangularAreaClick'), 'ScaleToOriginal', ''],
  ['aisles', $t('common.channel'), $t('planView.drawAnAisleClickEach'), 'Guide', ''],
  ['paths', $t('planView.pathNetwork'), $t('planView.drawAnAgvPathNetwork'), 'Share', 'P'], ['dims', $t('planView.dimension'), $t('planView.addADimensionClickTwice'), 'Odometer', 'D'],
  ['measure', $t('common.measureDistance'), $t('planView.measureTheDistanceBetweenTwo'), 'Aim', 'M'],
  ['calib', $t('planView.calibrate'), $t('planView.calibrateTheBackgroundImageClick'), 'Picture', '']];
const HOTKEY: Record<string, string> = Object.fromEntries(TOOLS.filter((t) => t[4]).map((t) => [t[4].toLowerCase(), t[0]]));
const ALIGN: [string, string, string][] = [['left', $t('common.alignLeft'), '⇤'], ['right', $t('planView.alignRight'), '⇥'], ['top', $t('planView.alignTop'), '⤒'], ['bottom', $t('planView.alignBottom'), '⤓'],
  ['hcenter', $t('planView.alignVerticalCenters'), '↔'], ['vcenter', $t('planView.alignHorizontalCenters'), '↕'], ['hdist', $t('graphView.distributeHorizontally'), '⋯'], ['vdist', $t('graphView.distributeVertically'), '⋮']];
const PLC_EN: Record<string, string> = { run: 'RUN', halt: 'HALT', stop: 'STOP', fault: 'FAULT' };
const POLY = ['walls', 'zones', 'aisles'], RECT = ['rwall', 'rzone'];
const DRAW = [...POLY, ...RECT, 'paths', 'dims', 'measure', 'calib'];
const SNAP_CN: Record<string, string> = { end: $t('planView.endpoint'), mid: $t('planView.midpoint'), perp: $t('planView.perpendicularFoot'), node: $t('planView.node'), on: $t('planView.onLine'), blk: $t('planView.equipmentCorner'), ortho: $t('planView.orthogonal'), grid: '' };
const draw = reactive<any>({ pts: [] as Pt[], node: '', rect: null as Pt | null });
const v = reactive({ k: 6, tx: 40, ty: 40 });
const size = reactive({ w: 0, h: 0 });
const cursor = ref<number[]>([0, 0]);
const tp = ref<{ p: Pt; kind: string }>({ p: [0, 0], kind: '' });   // Tool point: position after snapping / orthogonal constraint
const typed = ref('');
const hover = ref(false);
const drag = reactive({ dx: 0, dy: 0, pan: false, px: 0, py: 0 });
const box = ref<any>(null);
const meas = reactive<any>({ a: null, b: null });
// 4.6: "Cancel Measurement" is the first context menu item while measuring.
const cancelMeasure = () => { meas.a = meas.b = null; if (tool.value === 'measure') tool.value = 'select'; };
watch(tool, (t) => { ctxTools.measure.plan = t === 'measure' ? cancelMeasure : null; });
const edit = reactive<any>({ on: false, mode: '', s: null as LSel | null, idx: -1, start: [0, 0], base: null, moved: false, sx: 0, sy: 0, label: '' });
const hall = reactive({ t: 0.3, door: true, dw: 4 });
const RS = 18;   // Ruler width (px)

const floors = computed<any[]>(() => L.value.floors?.length ? L.value.floors : [{ id: 'F1', name: $t('planView.floor1'), z: 0 }]);
if (!ed.floor) ed.floor = 'F1';
const onFloor = (b: any) => (b.floor || 'F1') === (ed.floor || 'F1');
const blocks = computed(() => (ed.model?.blocks || []).filter((b: any) => onFloor(b) && layerVisible(b.id)));
// Draw production equipment as footprints + type icons; use schematic symbols for control (PLC/HMI), communication (gateway/switch), and information systems (SCADA/MES).
const procBlocks = computed(() => blocks.value.filter((b: any) => layerOf(b.id) === 'process'));
const symBlocks = computed(() => blocks.value.filter((b: any) => layerOf(b.id) !== 'process'));
const symScale = computed(() => Math.max(0.8, Math.min(1.3, v.k / 7)));
const layerColor = (id: string) => ed.cat?.layers?.[layerOf(id)]?.color || '#888';
// Hover: highlight related objects and connections (upstream/downstream material flow, PLC and signals, network paths); dim the rest.
const hoverId = ref('');
// Do not dim other objects while dragging connections or equipment (keep targets and alignment visible).
const hoverRel = computed(() => (hoverId.value && blocksById.value[hoverId.value] && !conn.value && !(edit.on && edit.moved) ? relatedSet(hoverId.value) : null));
function relCls(ids: string[], id = '') {
  const r = hoverRel.value; if (!r) return '';
  if (id) return r.ids.has(id) ? 'rel' : 'dim';
  return ids.some((x) => r.links.has(x)) ? 'rel' : 'dim';
}
const PROTO_CN: Record<string, string> = { profinet: 'PROFINET', modbus_tcp: 'Modbus TCP', modbus: 'Modbus TCP', s7: 'S7', opcua: 'OPC UA', mqtt: 'MQTT', ethernet: $t('archView.ethernet') };
const otherFloor = computed(() => (floors.value.length > 1 ? (ed.model?.blocks || []).filter((b: any) => !onFloor(b)) : []));
const areas = computed(() => ed.model?.areas || []);
const floor = computed(() => ed.model?.plant?.floor);
const ul = computed(() => ed.model?.plant?.underlay);
const isSel = (id: string) => ed.sel.includes(id);
const issue = computed(() => Object.fromEntries((ed.validation?.issues || []).filter((i: any) => i.id && (i.cat_code === 'layout' || matches(i.cat, 'details.layout'))).map((i: any) => [i.id, 1])));
const pathIss = computed(() => new Set((ed.validation?.issues || []).filter((i: any) => typeof i.id === 'string' && i.id.startsWith('path:')).map((i: any) => i.id.slice(5))));
const gridStep = computed(() => (v.k < 3 ? 10 : v.k < 14 ? 5 : 1));
const bounds = computed(() => {
  const xs: number[] = [], ys: number[] = [];
  for (const b of blocks.value) { xs.push(b.pos[0] - b.size[0] / 2, b.pos[0] + b.size[0] / 2); ys.push(b.pos[1] - b.size[1] / 2, b.pos[1] + b.size[1] / 2); }
  for (const a of areas.value) xs.push(a.x[0], a.x[1]);
  for (const s of allSels(L.value)) for (const q of pointsOf(L.value, s)) { xs.push(q[0]); ys.push(q[1]); }
  if (floor.value) { xs.push(0, floor.value[0]); ys.push(0, floor.value[1]); }
  if (!xs.length || !ys.length) return { x0: 0, x1: floor.value?.[0] || 60, y0: 0, y1: floor.value?.[1] || 40 };
  return { x0: Math.min(...xs) - 4, x1: Math.max(...xs) + 4, y0: Math.min(...ys) - 6, y1: Math.max(...ys) + 6 };
});
// ---------- Connections: ports + orthogonal routing (4.4) ----------
// Recompute routes only on geometry changes (equipment position / size, connections, filters, symbol size after zoom settles); not on hover, selection, or drag:
// While dragging, use simple orthogonal lines for moving connections; reroute everything after committing on release.
/** Control / communication / information system symbol size (fixed screen pixels, so world size varies with zoom). */
const symK = (k: number) => Math.max(0.8, Math.min(1.3, k / 7)) / k;
function rectOf(b: any, k: number): Rect {
  if (layerOf(b.id) === 'process') { const [w, h] = extOf(b); return { x0: b.pos[0] - w / 2, y0: b.pos[1] - h / 2, x1: b.pos[0] + w / 2, y1: b.pos[1] + h / 2 }; }
  const s = symK(k); return { x0: b.pos[0] - 22 * s, y0: b.pos[1] - 19 * s, x1: b.pos[0] + 22 * s, y1: b.pos[1] + 19 * s };
}
// Routing zoom: update 160 ms after scrolling stops (used for symbol sizes and clearances).
const routeK = ref(6);
let rkTimer: any = null;
watch(() => v.k, (k) => { clearTimeout(rkTimer); rkTimer = setTimeout(() => { if (Math.abs(Math.log(k / routeK.value)) > 0.02) routeK.value = k; }, 160); });
const routeOpts = computed(() => { const m = Math.max(0.3, Math.min(1.5, 14 / routeK.value)); return { margin: m, bend: m * 3, gap: Math.max(0.08, Math.min(0.6, 6 / routeK.value)), close: m * 2 }; });
const rects = computed<Record<string, Rect>>(() => Object.fromEntries(blocks.value.map((b: any) => [b.id, rectOf(b, routeK.value)])));
/** Connections to draw: one line per material connection; bundle signal wires / network cables between each object pair. */
const conns = computed(() => {
  const R = rects.value, out: (Conn & { ids: string[]; link?: any })[] = [], g: Record<string, any> = {};
  for (const l of ed.model?.links || []) {
    if (!R[l.from] || !R[l.to] || l.from === l.to || !linkVisible(l)) continue;
    const k = linkKind(l);
    if (k === 'material') { out.push({ key: l.id, a: l.from, b: l.to, kind: k, ids: [l.id], link: l }); continue; }
    const key = k + ':' + [l.from, l.to].sort().join('|');
    if (g[key]) { g[key].ids.push(l.id); continue; }
    g[key] = { key, a: l.from, b: l.to, kind: k, ids: [l.id] }; out.push(g[key]);
  }
  return out;
});
const routed = computed<Record<string, Route>>(() => routeAll(rects.value, conns.value, routeOpts.value));
/** Bundle details (channel count, protocol, failures): update with live state without affecting routing. */
function bundleMeta(c: any) {
  const by = blocksById.value, A = by[c.a], B = by[c.b];
  let n = 0; const protos = new Set<string>(), sigs: string[] = []; let fault = '';
  for (const id of c.ids) {
    const l = (ed.model?.links || []).find((x: any) => x.id === id); if (!l) continue;
    n += (l.signals || []).length; if (l.protocol) protos.add(PROTO_CN[l.protocol] || l.protocol);
    for (const q of (l.signals || []).slice(0, 12)) sigs.push(`${q.ch || '?'} ${q.dir === 'out' ? '→' : '←'} ${q.point}`);
    const f = linkFault(l); if (f) fault = f;
  }
  return { A, B, n, protos: [...protos], sigs, fault };
}
const moving = computed(() => (edit.on && edit.mode === 'move' && (drag.dx || drag.dy) ? new Set<string>(selBlocks.value.map((b: any) => b.id)) : null));
/** Rendered connections: paths, labels, styles. */
const lineViews = computed(() => {
  const R = routed.value, mv = moving.value, dx = drag.dx, dy = drag.dy, k = v.k;
  // Limit network cables in the floor plan (dozens of star connections would obscure it): show only those for selected / hovered objects or with faults;
  // Show all when "Production Equipment" is disabled in filters (control and network only). See "Architecture" for the full topology.
  const allNet = ed.filter?.layers?.process === false, sel = new Set<string>(ed.sel || []), hr = hoverRel.value;
  const out: any[] = [];
  for (const c of conns.value as any[]) {
    const r = R[c.key]; if (!r) continue;
    const meta = c.kind === 'material' ? null : bundleMeta(c);
    if (c.kind === 'network' && !(allNet || meta!.fault || sel.has(c.a) || sel.has(c.b) || c.ids.includes(ed.selLink) || (hr && c.ids.some((i: string) => hr.links.has(i))))) continue;
    let pts = r.pts;
    if (mv && (mv.has(c.a) || mv.has(c.b))) {
      if (mv.has(c.a) && mv.has(c.b)) pts = shift(pts, dx, dy);
      else {
        const mvE = (e: End): End => (mv.has(e.id) ? { ...e, p: [e.p[0] + dx, e.p[1] + dy] } : e);
        pts = elbow(mvE(r.a), mvE(r.b), routeOpts.value.margin);
      }
    }
    const lab = labelAt(pts), scr = lab.len * k;
    const base = { key: c.key, kind: c.kind, ids: c.ids, a: c.a, b: c.b, d: pathD(pts, Math.min(routeOpts.value.margin * 0.7, 9 / k)), m: lab.m, pts };
    if (c.kind === 'material') {
      const l = c.link, imp = ['melt', 'ladle', 'sand', 'mold'].includes(l.from_port);
      out.push({ ...base, cls: [imp ? 'imp' : '', l.via ? 'via' : '', ed.selLink === l.id ? 'sel' : ''].join(' '), label: '',
        title: $t('planView.materialFlow012', [blocksById.value[c.a]?.name || c.a, blocksById.value[c.b]?.name || c.b, l.via ? $t('planView.transportedBy') + (blocksById.value[l.via]?.name || l.via) + $t('planView.k1237') : '']) });
      continue;
    }
    const x = meta!;
    const label = c.kind === 'signal' ? (x.n && scr > 36 ? $t('common.n0Channels', [x.n]) : '') : x.fault ? '⚠ ' + x.fault : scr > 110 ? x.protos.join('/') : '';
    const title = c.kind === 'signal' ? $t('planView.signalWire012', [x.A?.name, x.B?.name, x.n, x.sigs.join('\n'), x.n > 12 ? '\n…' : ''])
      : $t('archView.networkCable012', [x.A?.name, x.B?.name, x.protos.length ? $t('common.k459') + x.protos.join('/') + $t('common.k460') : '', x.fault ? $t('planView.communicationFault') + x.fault : '']);
    out.push({ ...base, cls: '', label, title, fault: x.fault });
  }
  // Keep labels clear of each other and equipment: always show signal counts and faults; omit protocols if space is tight (view on hover)
  const lab = out.filter((x) => x.label), obst = blocks.value.map((b: any) => liveRect(b));
  lab.sort((p, q) => +!!q.fault - +!!p.fault || +(q.kind === 'signal') - +(p.kind === 'signal'));
  const at = placeLabels(lab.map((x) => ({ key: x.key, pts: x.pts, w: (x.label.length * 7.2 + 14) / k, h: 17 / k, required: x.kind === 'signal' || !!x.fault })), obst);
  for (const x of lab) { if (at[x.key]) x.m = at[x.key]; else x.label = ''; }
  return out;
});
const vehicles = computed(() => (ed.runtime?.stations || []).flatMap((s: any) => s.agvs || []));
const measLen = computed(() => { const b = meas.b || tp.value.p; return meas.a ? dist(meas.a, b) : 0; });

// ---------- Layout element display ----------
const pts = (a: number[][]) => a.map((q) => q.join(',')).join(' ');
const cen = (a: number[][]) => [a.reduce((t, q) => t + q[0], 0) / a.length, a.reduce((t, q) => t + q[1], 0) / a.length];
const nodeAt = (id: string) => (LL.value.paths?.nodes || []).find((n: any) => n.id === id);
const nodeTitle = (n: any) => `${NODE_CN[n.kind || 'node']} ${n.id}${n.block ? $t('planView.pickPlace') + (blocksById.value[n.block]?.name || n.block) : ''}`;
const wallsR = computed(() => (LL.value.walls || []).map((w: any) => ({ w, pieces: wallPieces(w), doors: doorShapes(w) })));
const stationLinks = computed(() => (LL.value.paths?.nodes || []).filter((n: any) => n.block && blocksById.value[n.block]).map((n: any) => {
  const b = blocksById.value[n.block]; return { id: n.id, x: n.x, y: n.y, bx: b.pos[0], by: b.pos[1], name: v.k > 4 ? b.name : '' };
}));
/** Door: leaf + swing arc (use dashed roller-door lines for widths ≥ 2.5 m). */
function doorPath(d: any) {
  const n = [-d.u[1], d.u[0]], tip = [d.a[0] + n[0] * d.w, d.a[1] + n[1] * d.w];
  return `M ${d.a[0]} ${d.a[1]} L ${tip[0]} ${tip[1]} A ${d.w} ${d.w} 0 0 0 ${d.b[0]} ${d.b[1]}`;
}
const diamond = (c: Pt, s: number) => `M ${c[0]} ${c[1] - s} L ${c[0] + s} ${c[1]} L ${c[0]} ${c[1] + s} L ${c[0] - s} ${c[1]} Z`;

/** Equipment label: icon + name. Clamp font size to 11–15 screen px; truncate the name or show only the icon if needed. Omit labels on tiny equipment (hover for name). */
const textW = (s: string, px: number) => [...s].reduce((t, c) => t + (c.charCodeAt(0) > 0x2e80 ? px : px * 0.58), 0);
function fitText(s: string, maxW: number, px: number) {
  if (textW(s, px) <= maxW) return s;
  const cs = [...s]; while (cs.length > 1 && textW(cs.join(''), px) + px > maxW) cs.pop();
  return cs.length >= 2 ? cs.join('') + '…' : '';
}
/** Key equipment metrics (as on flowchart cards): buffer count/capacity with progress bar, processing equipment OEE, warehouse inventory, otherwise status. */
function keyFig(b: any): { text: string; fill?: number } | null {
  const rt = rtById.value[b.id]; if (!rt || !ed.overlay) return null;
  if (rt.alarm) return { text: '⚠ ' + String(rt.alarm).slice(0, 8) };
  if (rt.cap) return { text: `${rt.count ?? 0}/${rt.cap}`, fill: Math.max(0, Math.min(1, (rt.count || 0) / rt.cap)) };
  if (rt.oee) return { text: `OEE ${Math.round(rt.oee.OEE * 100)}%` };
  if (rt.stock !== undefined) return { text: $t('blockNode.inventory0', [rt.stock]) };
  return { text: STATE_CN[rt.state] || rt.state || '' };
}
/** Status dot: at least 4 screen px, but no larger than 1/4 of the equipment's shorter side. */
const dotR = (b: any) => Math.min(Math.min(b.size[0], b.size[1]) / 4, Math.max(0.45, 6 / v.k));
const blkLabels = computed(() => {
  const k = v.k, out: any[] = [], placed: number[][] = [];
  // Place names for selected and large equipment first; use only icons if names overlap existing labels (hover for full name)
  const order = [...procBlocks.value].sort((a: any, b: any) => (+isSel(b.id) - +isSel(a.id)) || b.size[0] * b.size[1] - a.size[0] * a.size[1]);
  for (const b of order) {
    const [ew, eh] = extOf(b), sw = ew * k, sh = eh * k;
    if (Math.min(sw, sh) < 9) continue;
    const x = b.pos[0] + (isSel(b.id) ? drag.dx : 0), y = b.pos[1] + (isSel(b.id) ? drag.dy : 0);
    const ipx = Math.max(11, Math.min(26, Math.min(sw, sh) * 0.42)), fpx = Math.max(11, Math.min(15, sh * 0.16 + 6));
    const name = b.name || b.id, t = typeOf(b);
    const lb: any = { id: b.id, icon: t.icon || 'Box', is: ipx / k, fs: fpx / k, anchor: 'middle' };
    const kf = keyFig(b), kpx = Math.max(10, fpx - 2), withKf = !!kf && sw >= 48 && sh >= ipx + fpx + kpx + 16;
    if (sw >= 24 && sh >= ipx + fpx + 6) {                              // Vertical: icon above name (add a metrics row when zoomed in)
      lb.text = fitText(name, Math.max(sw * 1.25, 60), fpx) || fitText(b.id, sw * 1.4, fpx);
      const extra = withKf ? 3 + kpx + (kf!.fill !== undefined ? 6 : 0) : 0, hh = (ipx + 3 + fpx + extra) / k;
      lb.ix = x - ipx / 2 / k; lb.iy = y - hh / 2; lb.tx = x; lb.ty = lb.iy + (ipx + 3 + fpx * 0.82) / k;
      if (withKf) { lb.kf = kf!.text; lb.fill = kf!.fill; lb.kfs = kpx / k; lb.ky = lb.ty + (3 + kpx) / k; lb.bw = Math.min(sw * 0.6, 64) / k; }
    } else if (sw >= ipx + 30) {                                        // Horizontal: icon on the left (for narrow equipment such as conveyors)
      lb.text = fitText(name, sw - ipx - 10, fpx) || fitText(b.id, sw - ipx - 10, fpx);
      const tw = lb.text ? textW(lb.text, fpx) : 0, x0 = x - (ipx + 4 + tw) / 2 / k;
      lb.ix = x0; lb.iy = y - ipx / 2 / k; lb.tx = x0 + (ipx + 4) / k; lb.ty = y + fpx * 0.36 / k; lb.anchor = 'start';
    } else {                                                            // Only the icon fits: place the name below the equipment
      lb.ix = x - ipx / 2 / k; lb.iy = y - ipx / 2 / k;
      lb.text = sw >= 16 ? fitText(name, 90, 11) : ''; lb.fs = 11 / k; lb.tx = x; lb.ty = y + eh / 2 + 12 / k;
    }
    if (lb.text) {
      const fp = lb.fs * k, tw = textW(lb.text, fp), sx = lb.tx * k, sy = lb.ty * k;
      const r = [lb.anchor === 'start' ? sx : sx - tw / 2, sy - fp, lb.anchor === 'start' ? sx + tw : sx + tw / 2, sy + 2];
      if (placed.some((q) => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1])) lb.text = '';
      else placed.push(r);
    }
    out.push(lb);
  }
  return out;
});

// ---------- Selection handles ----------
const handles = computed(() => {
  const s = sel1.value; if (!s || tool.value !== 'select' || (edit.on && edit.mode === 'move')) return null;
  const it = itemOf(LL.value, s); if (!it) return null;
  const verts: any[] = [], mids: any[] = [], doors: any[] = [];
  if (s.kind === 'dims') { verts.push({ i: 0, h: 'a', p: it.a }, { i: 1, h: 'b', p: it.b }); return { verts, mids, doors }; }
  if (!it.pts) return null;
  const closed = s.kind === 'walls' && isClosed(it.pts);
  const n = closed ? it.pts.length - 1 : it.pts.length;
  for (let i = 0; i < n; i++) verts.push({ i, h: 'v' + i, p: it.pts[i] });
  segsOf(s.kind, it.pts).forEach(([a, b], i) => { if (dist(a, b) * v.k > 28) mids.push({ i, p: mid(a, b) }); });
  if (s.kind === 'walls') doors.push(...doorShapes(it));
  return { verts, mids, doors };
});
const segLabels = computed(() => {
  const s = sel1.value; if (!s || !['walls', 'zones', 'aisles'].includes(s.kind)) return [];
  const it = itemOf(LL.value, s); if (!it?.pts) return [];
  return segsOf(s.kind, it.pts).filter(([a, b]) => dist(a, b) * v.k > 60).map(([a, b]) => {
    const m = mid(a, b), L2 = dist(a, b), n = [-(b[1] - a[1]) / L2, (b[0] - a[0]) / L2];
    const off = (12 + Math.abs(n[0]) * 16) / v.k;   // Offset vertical edge dimensions to clear midpoint handles
    return { x: m[0] + n[0] * off, y: m[1] + n[1] * off + 4 / v.k, t: L2.toFixed(2) };
  });
});
const snapShow = computed(() => !!tp.value.kind && tp.value.kind !== 'grid' && hover.value && (DRAW.includes(tool.value) || (edit.on && edit.mode !== 'move')));

// ---------- Flowchart-style interactions: connection points, drag to connect, "+", alignment guides, quick add (4.4) ----------
const spaceDown = ref(false);
const conn = ref<{ from: string; a: Pt; side: number; b: Pt; over: string; kind: string; d: string; tip: string; sx: number; sy: number } | null>(null);
const guides = ref<number[][]>([]);
const floorSel = computed(() => selBlocks.value.filter((b: any) => onFloor(b)));
const editable = () => canEdit() && !ed.modelLocked;
/** Current object rectangle, without routing scale: used for connection points and alignment. */
const liveRect = (b: any) => rectOf(b, v.k);
/** Connection points (edge midpoints) and "+" on equipment hover. */
const portsOf = computed(() => {
  if (tool.value !== 'select' || !editable() || ed.placing || ed.pick || drag.pan || box.value || (edit.on && edit.moved)) return null;
  const id = conn.value ? conn.value.over || '' : hoverId.value;
  const b = id && blocksById.value[id]; if (!b || !onFloor(b) || !layerVisible(id)) return null;
  const r = liveRect(b), c = [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2];
  const pts = [{ s: 0, p: [r.x1, c[1]] }, { s: 1, p: [c[0], r.y1] }, { s: 2, p: [r.x0, c[1]] }, { s: 3, p: [c[0], r.y0] }];
  // Straddle the top-right corner with "+" (half over the equipment) so moving to it crosses no gap that would hide it
  const plus = !conn.value && layerOf(id) === 'process' && typeOf(b).out.length ? [r.x1, r.y0] : null;
  return { id, pts, plus };
});
/** Target equipment styling while dragging a connection: allowed / blocked. */
const connCls = (id: string) => (conn.value && conn.value.over === id ? (conn.value.kind ? 'cn-ok' : 'cn-bad') : conn.value && conn.value.from === id ? 'cn-src' : '');
function startConn(id: string, side: number, e: MouseEvent) {
  const b = blocksById.value[id]; if (!b) return;
  const q = portsOf.value?.pts.find((x) => x.s === side)?.p || b.pos;
  conn.value = { from: id, a: [...q], side, b: world(e), over: '', kind: '', d: '', tip: '', sx: e.clientX, sy: e.clientY };
  updateConn(e);
}
function updateConn(e: MouseEvent) {
  const c = conn.value; if (!c) return;
  c.b = world(e);
  const t = (e.target as Element).closest?.('[data-id]')?.getAttribute('data-id') || (e.target as Element).closest?.('[data-hov]')?.getAttribute('data-hov') || '';
  c.over = t && t !== c.from && blocksById.value[t] ? t : '';
  c.kind = c.over ? connKind(c.from, c.over) : '';
  c.tip = c.over ? (c.kind ? CONN_CN[c.kind] : $t('common.cannotConnect')) : layerOf(c.from) === 'process' && !typeOf(blocksById.value[c.from]).out.length ? '' : $t('planView.addAMachine');
  // Preview: extend from the port along the edge normal, then turn at right angles toward the pointer
  const m = 12 / v.k, N = [[1, 0], [0, 1], [-1, 0], [0, -1]][c.side], S = [c.a[0] + N[0] * m, c.a[1] + N[1] * m];
  const elb = c.side % 2 === 0 ? [c.b[0], S[1]] : [S[0], c.b[1]];
  c.d = pathD([c.a, S, elb, c.b], 8 / v.k);
}
function endConn(e: MouseEvent) {
  const c = conn.value; conn.value = null; if (!c) return;
  if (Math.hypot(e.clientX - c.sx, e.clientY - c.sy) < 6) return;          // Connection point was only clicked
  if (c.over) { connectBlocks(c.from, c.over); return; }
  if (!c.tip) return;
  // Dropped on empty space: add equipment there and connect it (same as dropping on empty space in the flowchart)
  const r = mainEl.value!.getBoundingClientRect();
  openQuick(c.from, e.clientX - r.left, e.clientY - r.top, [sn(c.b[0]), sn(c.b[1])]);
}
// Quick add: if source is set, connect the new block after it (material / signal / network by layer); if pos is omitted, place along the outlet direction
const qa = reactive<any>({ show: false, x: 0, y: 0, from: '', pos: null as Pt | null, title: '', only: '' });
function openQuick(from: string | null, x?: number, y?: number, pos?: Pt | null) {
  const r = mainEl.value?.getBoundingClientRect(); if (!r) return;
  if (x === undefined || y === undefined) { x = r.width / 2 - 125; y = Math.max(40, r.height / 2 - 160); }
  const A = from ? blocksById.value[from] : null, la = from ? layerOf(from) : '';
  Object.assign(qa, { show: true, x: Math.max(4, Math.min(x, r.width - 262)), y: Math.max(4, Math.min(y, r.height - 330)), from: from || '', pos: pos || null,
    title: A ? $t('planView.connectAfter0', [A.name]) : $t('workbench.addEquipment2'), only: la === 'process' ? 'in' : la && A?.type !== 'plc' ? 'ctl' : '' });
}
function quickPick(type: string) {
  const from = qa.from, pos = qa.pos; qa.show = false;
  if (from) { addConnected(type, from, pos || nextPos(from, type)); return; }
  const w = pos || [sn(cursor.value[0]), sn(cursor.value[1])];
  const b: any = makeBlock(type, w, nodePosNear(w));
  if ((ed.floor || 'F1') !== 'F1') b.floor = ed.floor;
  exec([{ op: 'add_block', block: b }], $t('common.add2') + typeOf(b).label); select([b.id]); flash([b.id], 1500);
}
/** Close quick add on pointer down outside it. */
function closeQa(e: MouseEvent) { if (qa.show && !(e.target as Element)?.closest?.('.pv-qa')) qa.show = false; }
const emptyFloor = computed(() => !!ed.model && !blocks.value.length && !otherFloor.value.length && !allSels(L.value).length && tool.value === 'select' && !ul.value?.url);
/** Snap dragged equipment to other equipment edges / centers (8 px tolerance); return snapped displacement and guides. */
function alignSnap(id: string, dx: number, dy: number) {
  const me = blocksById.value[id]; if (!me) return null;
  const r0 = liveRect(me), tol = 8 / v.k, sel = new Set(ed.sel);
  const mine = [[r0.x0 + dx, (r0.x0 + r0.x1) / 2 + dx, r0.x1 + dx], [r0.y0 + dy, (r0.y0 + r0.y1) / 2 + dy, r0.y1 + dy]];
  const best: any[] = [null, null];
  for (const b of blocks.value) {
    if (sel.has(b.id) || ['transporter', 'operators'].includes(b.type)) continue;
    const r = liveRect(b), theirs = [[r.x0, (r.x0 + r.x1) / 2, r.x1], [r.y0, (r.y0 + r.y1) / 2, r.y1]];
    for (const ax of [0, 1]) for (const m of mine[ax]) for (const t of theirs[ax]) {
      const d = t - m;
      if (Math.abs(d) <= tol && (!best[ax] || Math.abs(d) < Math.abs(best[ax].d) - 1e-9)) best[ax] = { d, at: t, r };
    }
  }
  const nd = [dx + (best[0]?.d || 0), dy + (best[1]?.d || 0)], gl: number[][] = [];
  const mr = { x0: r0.x0 + nd[0], x1: r0.x1 + nd[0], y0: r0.y0 + nd[1], y1: r0.y1 + nd[1] }, pad = 1.5;
  if (best[0]) gl.push([best[0].at, Math.min(mr.y0, best[0].r.y0) - pad, best[0].at, Math.max(mr.y1, best[0].r.y1) + pad]);
  if (best[1]) gl.push([Math.min(mr.x0, best[1].r.x0) - pad, best[1].at, Math.max(mr.x1, best[1].r.x1) + pad, best[1].at]);
  return { dx: best[0] ? nd[0] : null, dy: best[1] ? nd[1] : null, guides: gl };
}

// ---------- Coordinates and snapping ----------
function world(e: MouseEvent) {
  const r = svg.value!.getBoundingClientRect();
  return [(e.clientX - r.left - v.tx) / v.k, (e.clientY - r.top - v.ty) / v.k];
}
const sn = (x: number, alt = false) => (snap.value && !alt ? Math.round(x / snap.value) * snap.value : Math.round(x * 100) / 100);
type Skip = { s: LSel; idx: number } | null;
/** Snap priority: endpoints (including road network nodes and equipment corners) > midpoints > perpendicular foot (from previous point) > lines > grid. skip: dragged vertex (no self-snapping). */
function snapPt(w: Pt, alt = false, o: { ref?: Pt | null; skip?: Skip } = {}): { p: Pt; kind: string } {
  if (alt) return { p: rp(w), kind: '' };
  const tol = Math.max(0.15, 10 / v.k), l = edit.on && edit.base ? edit.base : L.value, sk = o.skip;
  const ends: [Pt, string][] = [], segs: [Pt, Pt][] = [];
  for (const kind of ['walls', 'zones', 'aisles']) for (const it of l[kind] || []) {
    const me = sk && sk.s.kind === kind && sk.s.id === it.id;
    const p = it.pts || [], cl = kind === 'walls' && isClosed(p), n = p.length;
    p.forEach((q: Pt, i: number) => { if (!(me && (i === sk!.idx || (cl && sk!.idx === 0 && i === n - 1)))) ends.push([q, 'end']); });
    segsOf(kind, p).forEach(([a, b], i) => {
      if (me) {   // Do not snap to edges adjacent to the dragged vertex
        const j = sk!.idx, m = kind === 'zones' ? n : cl ? n - 1 : 0;
        if (m ? i === j % m || i === (j - 1 + m) % m : i === j || i === j - 1) return;
      }
      segs.push([a, b]);
    });
  }
  for (const d of l.dims || []) { if (!(sk && sk.s.kind === 'dims' && sk.s.id === d.id)) ends.push([d.a, 'end'], [d.b, 'end']); }
  const ns = l.paths?.nodes || [];
  for (const nd of ns) if (!(sk && sk.s.kind === 'nodes' && sk.s.id === nd.id)) ends.push([[nd.x, nd.y], 'node']);
  for (const e of l.paths?.edges || []) {
    if (sk && sk.s.kind === 'nodes' && (e.a === sk.s.id || e.b === sk.s.id)) continue;
    const a = ns.find((x: any) => x.id === e.a), b = ns.find((x: any) => x.id === e.b); if (a && b) segs.push([[a.x, a.y], [b.x, b.y]]);
  }
  draw.pts.forEach((q: Pt) => ends.push([q, 'end']));
  for (const b of blocks.value) {
    if (['transporter', 'operators'].includes(b.type)) continue;
    const [ew, eh] = extOf(b);
    if (Math.abs(b.pos[0] - w[0]) > ew / 2 + tol || Math.abs(b.pos[1] - w[1]) > eh / 2 + tol) continue;
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) ends.push([[b.pos[0] + sx * ew / 2, b.pos[1] + sy * eh / 2], 'blk']);
  }
  let best: { p: Pt; kind: string } | null = null, bd = tol;
  for (const [q, kind] of ends) { const d = dist(q, w); if (d < bd) { bd = d; best = { p: [...q], kind }; } }
  if (best) return best;
  bd = tol;
  for (const [a, b] of segs) { const m = mid(a, b), d = dist(m, w); if (d < bd) { bd = d; best = { p: rp(m), kind: 'mid' }; } }
  if (best) return best;
  if (o.ref) {
    bd = tol;
    for (const [a, b] of segs) { const r = projSeg(o.ref, a, b); if (r.t > 0 && r.t < 1) { const d = dist(r.q, w); if (d < bd) { bd = d; best = { p: rp(r.q), kind: 'perp' }; } } }
    if (best) return best;
  }
  bd = tol * 0.6;
  for (const [a, b] of segs) { const r = projSeg(w, a, b); if (r.d < bd) { bd = r.d; best = { p: rp(r.q), kind: 'on' }; } }
  if (best) return best;
  return { p: [sn(w[0]), sn(w[1])], kind: snap.value ? 'grid' : '' };
}
/** Orthogonal (Shift): constrain to X or Y; round length to grid increments. */
function orthoPt(ref: Pt, w: Pt): { p: Pt; kind: string } {
  const o = ortho(ref, w);
  return { p: o[1] === ref[1] ? [r2(ref[0] + sn(o[0] - ref[0])), ref[1]] : [ref[0], r2(ref[1] + sn(o[1] - ref[1]))], kind: 'ortho' };
}
function refPoint(): Pt | null {
  const t = tool.value;
  if (POLY.includes(t)) return draw.pts[draw.pts.length - 1] || null;
  if (t === 'dims') return draw.pts[0] || null;
  if (t === 'paths') { const n = nodeAt(draw.node); return n ? [n.x, n.y] : null; }
  if (RECT.includes(t)) return draw.rect;
  if (t === 'measure' || t === 'calib') return meas.a && !meas.b ? meas.a : null;
  return null;
}
function toolPoint(w: Pt, e: { shiftKey: boolean; altKey: boolean }) {
  if (tool.value === 'calib') return { p: rp(w), kind: '' };      // Calibrate background image: use actual image coordinates without snapping
  const ref = refPoint();
  if (e.shiftKey && ref && RECT.includes(tool.value)) {          // Square
    const s = Math.max(Math.abs(w[0] - ref[0]), Math.abs(w[1] - ref[1]));
    return { p: [r2(ref[0] + Math.sign(w[0] - ref[0] || 1) * sn(s)), r2(ref[1] + Math.sign(w[1] - ref[1] || 1) * sn(s))], kind: 'ortho' };
  }
  if (e.shiftKey && ref) return orthoPt(ref, w);
  return snapPt(w, e.altKey, { ref });
}
const nodeNear = (p: Pt) => (L.value.paths?.nodes || []).find((n: any) => dist([n.x, n.y], p) < Math.max(0.15, 8 / v.k))?.id || '';

// ---------- Drawing ----------
function addPoint(p: Pt) {
  const t = tool.value;
  if (POLY.includes(t)) { const last = draw.pts[draw.pts.length - 1]; if (!last || dist(last, p) > 1e-3) draw.pts.push(p); }
  else if (t === 'dims') {
    if (!draw.pts.length) draw.pts = [p];
    else { const a = draw.pts[0]; if (dist(a, p) > 1e-3) setLayout((l) => listOf(l, 'dims').push({ id: lid(l, 'D'), a, b: p }), $t('planView.addDimension')); draw.pts = []; }
  } else if (t === 'paths') pathClick(p, nodeNear(p));
  else if (RECT.includes(t)) { if (!draw.rect) draw.rect = p; else { finishRect(draw.rect, p); draw.rect = null; } }
  else if (t === 'measure' || t === 'calib') {
    if (!meas.a || meas.b) { meas.a = p; meas.b = null; } else { meas.b = p; if (t === 'calib') calibrate(); }
  }
}
function finishDraw() {
  const kind = tool.value, p = draw.pts.map((q: Pt) => [...q]);
  if (kind === 'zones' && p.length >= 4 && dist(p[0], p[p.length - 1]) < 1e-3) p.pop();
  if (kind === 'zones' ? p.length >= 3 : p.length >= 2) {
    setLayout((l) => {
      const id = lid(l, { walls: 'W', zones: 'Z', aisles: 'A' }[kind as 'walls'] || 'X');
      const it: any = { id, pts: p };
      if (kind === 'walls') it.t = 0.24;
      if (kind === 'aisles') it.w = 3;
      if (kind === 'zones') { it.name = $t('planView.area') + id.slice(1); it.color = ['#1463d6', '#15a34a', '#d99a16', '#8e5bd1'][(l.zones || []).length % 4]; }
      listOf(l, kind).push(it);
      pv.lsel = [{ kind, id }];
    }, $t('planView.draw') + ({ walls: $t('planView.wall'), zones: $t('common.area'), aisles: $t('common.channel') } as any)[kind]);
  }
  draw.pts = [];
}
function finishRect(a: Pt, b: Pt) {
  const x0 = r2(Math.min(a[0], b[0])), x1 = r2(Math.max(a[0], b[0])), y0 = r2(Math.min(a[1], b[1])), y1 = r2(Math.max(a[1], b[1]));
  if (x1 - x0 < 0.1 || y1 - y0 < 0.1) return;
  const zone = tool.value === 'rzone';
  setLayout((l) => {
    const id = lid(l, zone ? 'Z' : 'W');
    const it: any = zone ? { id, pts: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], name: $t('planView.area') + id.slice(1), color: ['#1463d6', '#15a34a', '#d99a16', '#8e5bd1'][(l.zones || []).length % 4] }
      : { id, pts: [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], t: 0.24 };
    listOf(l, zone ? 'zones' : 'walls').push(it);
    pv.lsel = [{ kind: zone ? 'zones' : 'walls', id }];
  }, zone ? $t('planView.drawRectangularArea') : $t('planView.drawRectangularWalls'));
}
function pathClick(w: Pt, hitNode: string) {
  setLayout((l) => {
    const nodes = listOf(l, 'nodes'), edges = listOf(l, 'edges');
    let id = hitNode;
    if (!id) { id = lid(l, 'N'); nodes.push({ id, x: r2(w[0]), y: r2(w[1]), kind: 'node' }); }
    if (draw.node && draw.node !== id && !edges.some((e: any) => (e.a === draw.node && e.b === id) || (e.a === id && e.b === draw.node))) {
      edges.push({ id: lid(l, 'E'), a: draw.node, b: id, oneway: false });
    }
    draw.node = id;
  }, $t('planView.drawPathNetwork'));
}
/** Typed input: 12.5 (current direction), 12.5<30 (length<angle), @3,4 (relative to previous point), 10,5 (absolute coordinates); rectangle tool: 8,5 (length,width). */
function applyTyped() {
  const s = typed.value.trim(); typed.value = ''; if (!s) return;
  const ref = refPoint(), num = (x: string) => parseFloat(x);
  let m: RegExpMatchArray | null;
  if (RECT.includes(tool.value) && ref && (m = s.match(/^@?(-?\d*\.?\d+)\s*,\s*(-?\d*\.?\d+)$/))) {
    const c = tp.value.p, sx = Math.sign(c[0] - ref[0]) || 1, sy = Math.sign(c[1] - ref[1]) || 1;
    return addPoint([r2(ref[0] + sx * Math.abs(num(m[1]))), r2(ref[1] + sy * Math.abs(num(m[2])))]);
  }
  if ((m = s.match(/^@(-?\d*\.?\d+)\s*,\s*(-?\d*\.?\d+)$/)) && ref) return addPoint([r2(ref[0] + num(m[1])), r2(ref[1] + num(m[2]))]);
  if ((m = s.match(/^(-?\d*\.?\d+)\s*,\s*(-?\d*\.?\d+)$/))) return addPoint([r2(num(m[1])), r2(num(m[2]))]);
  if ((m = s.match(/^(\d*\.?\d+)\s*<\s*(-?\d*\.?\d+)$/)) && ref) return addPoint(polar(ref, num(m[1]), num(m[2])).map(r2));
  if ((m = s.match(/^(\d*\.?\d+)$/)) && ref) {
    const c = tp.value.p, d = dist(ref, c), len = num(m[1]);
    const u = d < 1e-6 ? [1, 0] : [(c[0] - ref[0]) / d, (c[1] - ref[1]) / d];
    return addPoint([r2(ref[0] + u[0] * len), r2(ref[1] + u[1] * len)]);
  }
  ElMessage.info(ref ? $t('planView.inputFormatLength125') : $t('planView.clickTheFirstPointOr'));
}
const hud = computed(() => {
  if (!hover.value && !typed.value) return null;
  const sp = toScreen(tp.value.p); if (!sp) return null;
  const rows: string[] = [];
  if (edit.on && edit.mode === 'vertex') {
    const it = itemOf(pv.preview || L.value, edit.s); if (!it?.pts) return null;
    const p = it.pts, n = p.length, cl = edit.s.kind === 'walls' && isClosed(p), nn = cl ? n - 1 : n, i = edit.idx;
    const wrap = edit.s.kind === 'zones' || cl;
    const prev = i > 0 ? p[i - 1] : wrap ? p[nn - 1] : null, next = i < nn - 1 ? p[i + 1] : wrap ? p[0] : null;
    rows.push(`X ${p[i][0].toFixed(2)}  Y ${p[i][1].toFixed(2)}`);
    if (prev) rows.push($t('planView.previousSegment0M', [dist(prev, p[i]).toFixed(2)]));
    if (next) rows.push($t('planView.nextSegment0M', [dist(p[i], next).toFixed(2)]));
  } else if (DRAW.includes(tool.value)) {
    const ref = refPoint();
    if (!ref && !typed.value) return null;
    if (ref && RECT.includes(tool.value)) rows.push(`${Math.abs(tp.value.p[0] - ref[0]).toFixed(2)} × ${Math.abs(tp.value.p[1] - ref[1]).toFixed(2)} m`);
    else if (ref) rows.push($t('planView.length0M', [dist(ref, tp.value.p).toFixed(2)]), $t('planView.angle0', [angleDeg(ref, tp.value.p).toFixed(1)]));
  } else return null;
  return { x: sp[0] + 16, y: sp[1] + 14, rows, input: !!typed.value };
});
function toScreen(p: Pt) { return [p[0] * v.k + v.tx, p[1] * v.k + v.ty]; }

// ---------- Floors / Buildings ----------
function setFloor(i: number, set: any) { setLayout((l) => { l.floors = clone(floors.value); Object.assign(l.floors[i], set); }, $t('planView.editFloor')); }
function addFloor() {
  setLayout((l) => { l.floors = clone(floors.value); const n = l.floors.length + 1; l.floors.push({ id: 'F' + n, name: [$t('planView.n1'), $t('planView.n2'), $t('planView.n3'), $t('planView.n4'), $t('planView.n5')][n - 1] + $t('planView.level'), z: (n - 1) * 6 }); }, $t('planView.addFloor'));
}
function delFloor(i: number) { setLayout((l) => { l.floors = clone(floors.value); const f = l.floors.splice(i, 1)[0]; if (ed.floor === f.id) ed.floor = 'F1'; }, $t('planView.deleteFloor')); }
const outerW = computed(() => outerOf(L.value));
const outerOk = computed(() => outerMatches(outerW.value, floor.value));
const hallWD = computed(() => floor.value || [Math.ceil(Math.max(20, bounds.value.x1)), Math.ceil(Math.max(20, bounds.value.y1))]);
function hallSize(W: number, D: number) {
  if (!W || !D) return;
  const had = !!outerW.value, follow = setHallSize(W, D);
  if (had && !follow) ElMessage.info($t('planView.theExteriorWallsHaveA'));
}
function genOuter() { const [W, D] = hallWD.value; addOuterWall(W, D, hall.t, hall.door ? hall.dw : 0); tool.value = 'select'; }
function selectOuter() { if (outerW.value) { pv.lsel = [{ kind: 'walls', id: outerW.value.id }]; ed.sel = []; tool.value = 'select'; } }
function setNorth(x: any) { setLayout((l) => { if (x) l.north = ((+x % 360) + 360) % 360; else delete l.north; }, $t('planView.changeNorthDirection')); }

// ---------- View ----------
function fit() {
  const r = svg.value?.getBoundingClientRect(); if (!r || !r.width) return;
  const b = bounds.value, w = b.x1 - b.x0, h = b.y1 - b.y0;
  v.k = Math.max(0.5, Math.min((r.width - 40 - RS) / w, (r.height - 40 - RS) / h));
  v.tx = RS + (r.width - RS - w * v.k) / 2 - b.x0 * v.k; v.ty = RS + (r.height - RS - h * v.k) / 2 - b.y0 * v.k;
}
function onWheel(e: WheelEvent) {
  const r = svg.value!.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  const k2 = Math.max(0.5, Math.min(80, v.k * Math.exp(-e.deltaY * 0.0015)));
  v.tx = mx - (mx - v.tx) * k2 / v.k; v.ty = my - (my - v.ty) * k2 / v.k; v.k = k2;
}

// ---------- Mouse ----------
let space = false;
let rdown: number[] | null = null;
let lastMouse: { x: number; y: number; shiftKey: boolean; altKey: boolean } | null = null;
let downAt: number[] | null = null;
function startEdit(mode: string, s: LSel | null, idx: number, w: Pt, e: MouseEvent, base?: any, label = '') {
  Object.assign(edit, { on: true, mode, s, idx, start: w, base: base || clone(L.value), moved: false, sx: e.clientX, sy: e.clientY, label, prim: '' });
}
function onDown(e: MouseEvent) {
  host.value?.focus();
  if (e.button === 2) rdown = [e.clientX, e.clientY];
  const w = world(e);
  if (e.button === 2 && tool.value === 'paths') draw.node = '';
  if (e.button === 1 || e.button === 2 || space) { Object.assign(drag, { pan: true, px: e.clientX - v.tx, py: e.clientY - v.ty }); return; }
  if (e.button !== 0) return;
  const tgt = e.target as Element;
  if (ed.pick) { const pid0 = tgt.closest('[data-id]')?.getAttribute('data-id'); if (pid0) { const pk = ed.pick; ed.pick = null; pk.onPick(pid0); } return; }
  if (ed.placing) { placeAt(e, { pos: [sn(w[0]), sn(w[1])] }); return; }
  if (qa.show) qa.show = false;
  const port = tool.value === 'select' && tgt.closest('[data-port]')?.getAttribute('data-port');
  if (port) { const i = port.lastIndexOf(':'); startConn(port.slice(0, i), +port.slice(i + 1), e); return; }
  const plus = tool.value === 'select' && tgt.closest('[data-plus]')?.getAttribute('data-plus');
  if (plus) {
    e.preventDefault();          // Prevent pointer down from stealing focus from the quick-add search field
    const r = mainEl.value!.getBoundingClientRect(), bb = (tgt.closest('[data-plus]') as Element).getBoundingClientRect();
    select([plus]); pv.lsel = []; openQuick(plus, bb.right - r.left + 8, bb.top - r.top); return;
  }
  const lk = tgt.closest('[data-lk]')?.getAttribute('data-lk');
  tp.value = toolPoint(w, e);
  if (POLY.includes(tool.value) || tool.value === 'dims' || tool.value === 'measure' || tool.value === 'calib') { if (e.detail < 2) addPoint(tp.value.p); return; }
  if (RECT.includes(tool.value)) { downAt = [e.clientX, e.clientY]; addPoint(tp.value.p); return; }
  if (tool.value === 'paths') {
    if (lk?.startsWith('edges:') && e.shiftKey) { const s = { kind: 'edges', id: lk.slice(6) }; setItem({ oneway: !itemOf(L.value, s)?.oneway || null }, s); return; }
    if (lk?.startsWith('edges:')) { pv.lsel = [{ kind: 'edges', id: lk.slice(6) }]; return; }
    pathClick(lk?.startsWith('nodes:') ? [0, 0] : tp.value.p, lk?.startsWith('nodes:') ? lk.slice(6) : nodeNear(tp.value.p));
    return;
  }
  // ---- Selection tool ----
  const h = tgt.closest('[data-h]')?.getAttribute('data-h');
  const s1 = sel1.value;
  if (h && s1) {
    if (h[0] === 'v' && e.altKey) { delVertex(s1, +h.slice(1)); return; }
    if (h[0] === 'v') return startEdit('vertex', s1, +h.slice(1), w, e, undefined, $t('planView.edit') + LKN[s1.kind] + $t('planView.vertex'));
    if (h === 'a' || h === 'b') return startEdit('dim' + h, s1, -1, w, e, undefined, $t('planView.editDimension'));
    if (h[0] === 'o') return startEdit('door', s1, +h.slice(1), w, e, undefined, $t('planView.moveDoorOpening'));
    if (h[0] === 'm') {           // Edge midpoint: insert a vertex, then drag it
      const base = clone(L.value), it = itemOf(base, s1), i = +h.slice(1), p = it.pts, q = segsOf(s1.kind, p)[i];
      p.splice(i + 1, 0, rp(mid(q[0], q[1])));
      return startEdit('vertex', s1, i + 1, w, e, base, $t('planView.add') + LKN[s1.kind] + $t('planView.vertex'));
    }
  }
  const id = tgt.closest('[data-id]')?.getAttribute('data-id');
  const lnk = !id && tgt.closest('[data-link]')?.getAttribute('data-link');
  if (lnk) { ed.sel = []; pv.lsel = []; ed.selLink = lnk; return; }     // Connection: select to show properties in the right panel
  if (id) {
    if (e.shiftKey || e.ctrlKey) { if (isSel(id)) { ed.sel = ed.sel.filter((x: string) => x !== id); return; } select([id], true); }
    else if (!isSel(id)) { select([id]); pv.lsel = []; }
    startEdit('move', null, -1, w, e, undefined, $t('planView.move')); edit.prim = id;
    return;
  }
  if (lk) {
    const [kind, lid2] = lk.split(':'), s = { kind, id: lid2 }, had = isLay(kind, lid2);
    if (e.shiftKey || e.ctrlKey) {
      if (had) { pv.lsel = pv.lsel.filter((x: LSel) => !(x.kind === kind && x.id === lid2)); return; }
      pv.lsel = [...pv.lsel, s];
    } else if (!had) {
      if (kind === 'zones' || kind === 'aisles') {   // Large areas / aisles: click to select before dragging; dragging over unselected ones starts box selection
        if (!e.shiftKey) { ed.sel = []; ed.selLink = ''; }
        box.value = { x0: w[0], y0: w[1], x1: w[0], y1: w[1], add: false, pend: s };
        return;
      }
      pv.lsel = [s]; ed.sel = []; showProps();
    }
    if (kind === 'nodes' && pv.lsel.length === 1) return startEdit('vertex', s, 0, w, e, undefined, $t('planView.moveRoadNetworkNode'));
    return startEdit('move', null, -1, w, e, undefined, $t('planView.move'));
  }
  if (!e.shiftKey) { ed.sel = []; ed.selLink = ''; pv.lsel = []; }
  box.value = { x0: w[0], y0: w[1], x1: w[0], y1: w[1], add: e.shiftKey };
}
const LKN: Record<string, string> = { walls: $t('planView.wall'), zones: $t('common.area'), aisles: $t('common.channel'), dims: $t('planView.dimension'), nodes: $t('planView.node'), edges: $t('common.connections') };
function updateEdit(w: Pt, e: MouseEvent) {
  if (!edit.moved && Math.hypot(e.clientX - edit.sx, e.clientY - edit.sy) < 3) return;
  edit.moved = true;
  const l = clone(edit.base);
  if (edit.mode === 'move') {
    let dx = sn(w[0] - edit.start[0], e.altKey), dy = sn(w[1] - edit.start[1], e.altKey);
    // Drag equipment: snap to neighboring edges / centers first (show guides), then the grid if unaligned; Alt disables all snapping
    const al = edit.prim && !e.altKey && !pv.lsel.length ? alignSnap(edit.prim, w[0] - edit.start[0], w[1] - edit.start[1]) : null;
    if (al) { if (al.dx !== null) dx = r2(al.dx); if (al.dy !== null) dy = r2(al.dy); guides.value = al.guides; } else guides.value = [];
    translate(l, pv.lsel, dx, dy); drag.dx = dx; drag.dy = dy;
  } else {
    const it = itemOf(l, edit.s); if (!it) return;
    if (edit.mode === 'door') {
      const total = it.pts.slice(1).reduce((t: number, q: Pt, i: number) => t + dist(it.pts[i], q), 0), d = it.doors[edit.idx];
      d.s = r2(Math.max(d.w / 2, Math.min(total - d.w / 2, Math.round(sAt(it.pts, w).s * 10) / 10)));
      tp.value = { p: w, kind: '' };
    } else if (edit.s.kind === 'nodes') {
      tp.value = snapPt(w, e.altKey, { skip: { s: edit.s, idx: 0 } }); it.x = tp.value.p[0]; it.y = tp.value.p[1];
    } else if (edit.mode === 'dima' || edit.mode === 'dimb') {
      const other = edit.mode === 'dima' ? it.b : it.a;
      tp.value = e.shiftKey ? orthoPt(other, w) : snapPt(w, e.altKey, { ref: other, skip: { s: edit.s, idx: 0 } });
      it[edit.mode === 'dima' ? 'a' : 'b'] = tp.value.p;
    } else {
      const p = it.pts, i = edit.idx, cl = edit.s.kind === 'walls' && isClosed(p), nn = cl ? p.length - 1 : p.length;
      const wrap = edit.s.kind === 'zones' || cl;
      const ref = i > 0 ? p[i - 1] : wrap ? p[nn - 1] : p[i + 1] || null;
      tp.value = e.shiftKey && ref ? orthoPt(ref, w) : snapPt(w, e.altKey, { ref, skip: { s: edit.s, idx: i } });
      const old = p.map((q: Pt) => [...q]);
      p[i] = tp.value.p; if (cl && i === 0) p[p.length - 1] = [...tp.value.p];
      if (edit.s.kind === 'walls' && it.doors?.length) it.doors = remapDoors(old, p, it.doors);
    }
  }
  pv.preview = l;
}
function commitEdit() {
  const moved = edit.moved, mode = edit.mode;
  edit.on = false;
  if (moved) {
    const ops: Op[] = [];
    if (mode === 'move' && (drag.dx || drag.dy)) {
      for (const b of selBlocks.value.filter(onFloor)) ops.push({ op: 'update_block', id: b.id, set: { pos: [+(b.pos[0] + drag.dx).toFixed(2), +(b.pos[1] + drag.dy).toFixed(2)] } });
    }
    const layoutChanged = pv.preview && (mode !== 'move' || pv.lsel.length) && (mode !== 'move' || drag.dx || drag.dy);
    if (layoutChanged) ops.push({ op: 'update_plant', set: { 'plant.layout': pv.preview } });
    if (ops.length) exec(ops, edit.label || $t('planView.move'));
  }
  pv.preview = null; drag.dx = drag.dy = 0; edit.base = null; edit.prim = ''; guides.value = [];
}
function onMove(e: MouseEvent) {
  hover.value = true;
  if (!edit.on && !drag.pan && !box.value && !conn.value) {
    const el = e.target as Element;
    let hid = el.closest?.('[data-id]')?.getAttribute('data-id') || el.closest?.('[data-hov]')?.getAttribute('data-hov') || '';
    // Just left the equipment (within 14 px): keep hover active so connection points and "+" stay visible as the pointer approaches
    if (!hid && hoverId.value && blocksById.value[hoverId.value]) {
      const r = liveRect(blocksById.value[hoverId.value]), w0 = world(e), pad = 14 / v.k;
      if (w0[0] > r.x0 - pad && w0[0] < r.x1 + pad && w0[1] > r.y0 - pad && w0[1] < r.y1 + pad) hid = hoverId.value;
    }
    if (hid !== hoverId.value) hoverId.value = hid;
  }
  const w = world(e); cursor.value = w; ed.cursor = w;
  if (conn.value) { updateConn(e); return; }
  lastMouse = { x: e.clientX, y: e.clientY, shiftKey: e.shiftKey, altKey: e.altKey };
  if (drag.pan) { v.tx = e.clientX - drag.px; v.ty = e.clientY - drag.py; return; }
  if (edit.on) { updateEdit(w, e); return; }
  if (box.value) { box.value.x1 = w[0]; box.value.y1 = w[1]; return; }
  if (DRAW.includes(tool.value)) tp.value = toolPoint(w, e);
}
function onUp(e?: MouseEvent) {
  if (drag.pan) { drag.pan = false; return; }
  if (conn.value) { if (e) endConn(e); else conn.value = null; return; }
  if (edit.on) { commitEdit(); return; }
  if (RECT.includes(tool.value) && draw.rect && downAt && e && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 8) addPoint(tp.value.p);   // Rectangle drawn by dragging
  downAt = null;
  if (box.value) {
    const b = box.value, x0 = Math.min(b.x0, b.x1), x1 = Math.max(b.x0, b.x1), y0 = Math.min(b.y0, b.y1), y1 = Math.max(b.y0, b.y1);
    if (x1 - x0 > 0.3 || y1 - y0 > 0.3) {
      select(blocks.value.filter((k: any) => k.pos[0] >= x0 && k.pos[0] <= x1 && k.pos[1] >= y0 && k.pos[1] <= y1).map((k: any) => k.id), b.add);
      const inside = (q: Pt) => q[0] >= x0 && q[0] <= x1 && q[1] >= y0 && q[1] <= y1;
      const got = allSels(L.value).filter((s) => { const ps = pointsOf(L.value, s); return ps.length && ps.every(inside); });
      pv.lsel = b.add ? [...pv.lsel, ...got.filter((s) => !isLay(s.kind, s.id))] : got;
    } else if (b.pend) { pv.lsel = [b.pend]; ed.sel = []; }
    box.value = null;
  }
}
function onLeave() { hover.value = false; hoverId.value = ''; if (conn.value) conn.value = null; onUp(); }

// ---------- Right-click ----------
function onCtx(e: MouseEvent) {
  if (rdown && Math.hypot(e.clientX - rdown[0], e.clientY - rdown[1]) > 5) { rdown = null; return; }
  rdown = null;
  const w = world(e), tgt = e.target as Element, id = tgt.closest('[data-id]')?.getAttribute('data-id');
  const lk = tgt.closest('[data-lk]')?.getAttribute('data-lk'), h = tgt.closest('[data-h]')?.getAttribute('data-h');
  if (h && h[0] === 'v' && sel1.value) {
    const s = sel1.value;
    openCtx(e, [{ title: LKN[s.kind] + $t('planView.vertex2') + (+h.slice(1) + 1), items: [{ label: $t('planView.deleteThisVertex'), kbd: $t('archView.doubleClick'), danger: true, run: () => delVertex(s, +h.slice(1)) }] }]);
  } else if (!id && tgt.closest('[data-link]')) {
    const lid3 = tgt.closest('[data-link]')!.getAttribute('data-link')!; ed.sel = []; pv.lsel = []; ed.selLink = lid3; openLinkMenu(e, lid3);
  } else if (id && blocksById.value[id]) {
    if (!isSel(id)) { select([id]); pv.lsel = []; }
    const b = blocksById.value[id], la = layerOf(id), r = mainEl.value!.getBoundingClientRect();
    openBlockMenu(e, id, 'plan', [
      ...(b.type === 'plc' ? [{ label: $t('common.openPlcProgram'), kbd: $t('archView.doubleClick'), run: () => openInside(id) }] : la === 'process' ? [{ label: $t('common.equipmentInterior'), kbd: $t('archView.doubleClick'), run: () => openInside(id) }] : []),
      { label: $t('planView.renameProperties'), kbd: 'F2', run: () => focusProps(id) },
      ...(la === 'process' && typeOf(b).out.length ? [{ label: $t('planView.addAMachineAfterThis'), run: () => openQuick(id, e.clientX - r.left + 10, e.clientY - r.top) }] : []),
      { label: $t('planView.rotate90'), kbd: 'R', run: () => rotateSel(90) },
      { label: $t('planView.array'), run: () => { tool.value = 'select'; pv.arrayOpen = true; } }]);
  } else if (lk) {
    const [kind, lid2] = lk.split(':'), s = { kind, id: lid2 };
    if (!isLay(kind, lid2)) { pv.lsel = [s]; ed.sel = []; }
    tool.value = 'select';
    const it = itemOf(L.value, s), multi = pv.lsel.length > 1;
    const own: any[] = [];
    if (!multi && kind === 'edges') own.push({ label: $t('planView.oneWayTraffic'), checked: !!it?.oneway, run: () => setItem({ oneway: !it?.oneway || null }, s) }, { label: $t('planView.reverseDirection'), run: () => setItem({ a: it.b, b: it.a }, s) });
    if (!multi && kind === 'nodes') own.push({ label: $t('common.type'), children: Object.entries(NODE_CN).map(([k, n]) => ({ label: n, checked: (it?.kind || 'node') === k, run: () => setItem({ kind: k }, s) })) },
      { label: $t('planView.assignPickupDropOffEquipment'), run: () => { ed.pick = { prompt: $t('planView.clickAMachineToUse'), onPick: (bid: string) => setItem({ block: bid, kind: it?.kind && it.kind !== 'node' ? it.kind : 'station' }, s) }; } });
    if (!multi && kind === 'walls') own.push({ label: $t('planView.addDoorOpeningHere'), run: () => addDoorAt(s, w) });
    if (!multi && ['walls', 'zones', 'aisles'].includes(kind)) own.push({ label: $t('planView.addVertexHere'), run: () => addVertexAt(s, w) });
    openCtx(e, [{ title: multi ? $t('planView.layoutElementsSelected0', [pv.lsel.length]) : `${LKN[kind] || kind} ${lid2}`, items: [
      ...own,
      { label: $t('common.copy'), kbd: 'Ctrl+C', run: copyLay }, { label: $t('common.duplicate'), kbd: 'Ctrl+D', run: duplicateLay }, { label: $t('planView.array'), run: () => { pv.arrayOpen = true; } },
      { label: $t('common.delete'), kbd: 'Del', danger: true, run: () => removeLays() },
    ] }]);
  } else {
    const c = getClip();
    const r = mainEl.value!.getBoundingClientRect();
    openPaneMenu(e, [
      { label: $t('workbench.addEquipment'), kbd: 'Tab', run: () => openQuick(null, e.clientX - r.left, e.clientY - r.top, [sn(w[0]), sn(w[1])]) },
      ...(pv.clipKind === 'layout' && clipCount(c) ? [{ label: $t('planView.pasteWallsAreasEtc0', [clipCount(c)]), kbd: 'Ctrl+V', run: () => pasteLay(w, sn) }] : []),
      { label: $t('planView.draw'), children: TOOLS.filter((t) => !['select', 'calib'].includes(t[0])).map((t) => ({ label: t[1], hint: '', run: () => { tool.value = t[0]; } })) },
      { label: $t('planView.fitToWindow'), kbd: 'Home', run: fit },
    ], { pos: [sn(w[0]), sn(w[1])], node: nodePosNear(w) });
  }
}
function delVertex(s: LSel, i: number) {
  const it = itemOf(L.value, s); if (!it?.pts) return;
  const cl = s.kind === 'walls' && isClosed(it.pts), n = cl ? it.pts.length - 1 : it.pts.length;
  if (n <= (s.kind === 'zones' || cl ? 3 : 2)) { ElMessage.info($t('planView.tooFewVerticesToDelete')); return; }
  setLayout((l) => {
    const x = itemOf(l, s), old = x.pts.map((q: Pt) => [...q]);
    x.pts.splice(i, 1); if (cl && i === 0) x.pts[x.pts.length - 1] = [...x.pts[0]];
    if (x.doors?.length) x.doors = remapDoors(old.filter((_: any, j: number) => j !== i), x.pts, x.doors);
  }, $t('planView.deleteVertex'));
}
function addVertexAt(s: LSel, w: Pt) {
  const it = itemOf(L.value, s); if (!it?.pts) return;
  let bi = 0, bd = Infinity, bq: Pt = w;
  segsOf(s.kind, it.pts).forEach(([a, b], i) => { const r = projSeg(w, a, b); if (r.d < bd) { bd = r.d; bi = i; bq = r.q; } });
  setLayout((l) => { itemOf(l, s).pts.splice(bi + 1, 0, rp(bq)); }, $t('planView.addVertex'));
}
function addDoorAt(s: LSel, w: Pt) {
  const it = itemOf(L.value, s); if (!it?.pts) return;
  const total = it.pts.slice(1).reduce((t: number, q: Pt, i: number) => t + dist(it.pts[i], q), 0), dw = it.outer ? 4 : 1.2;
  const at = Math.max(dw / 2, Math.min(total - dw / 2, sAt(it.pts, w).s));
  setItem({ doors: [...(it.doors || []), { s: r2(at), w: Math.min(dw, total) }] }, s);
}
const showProps = () => { if (ed.rightTab !== 'props') ed.rightTab = 'props'; };
/** Rename / view properties: focus the name field in the right Properties panel (F2 or right-click "Rename / Properties"). */
async function focusProps(id: string) {
  select([id]); pv.lsel = []; tool.value = 'select'; showProps();
  for (let i = 0; i < 6; i++) {
    await nextTick();
    const inp = document.querySelector('.ed-right .dt-name input, .dt .dt-name input') as HTMLInputElement | null;
    if (inp) { inp.focus(); inp.select(); return; }
    await new Promise((r) => setTimeout(r, 40));
  }
}
/** Double-click: open the PLC program; open equipment internals for production equipment (control unit editing / control tag I/O); show properties for others. */
function openInside(id: string) {
  const b = blocksById.value[id]; if (!b) return;
  select([id]); pv.lsel = [];
  if (b.type === 'plc') {
    const p = panelById('plc-editor-float');
    if (p) openFloat(p as any, { bid: id }, id); else window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
  } else if (layerOf(id) === 'process') {
    ed.interior = id; window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'cell-editor' } }));
  } else focusProps(id);
}
function onDbl(e: MouseEvent) {
  if (POLY.includes(tool.value)) { finishDraw(); return; }
  if (tool.value !== 'select') return;
  const tgt = e.target as Element, h = tgt.closest('[data-h]')?.getAttribute('data-h');
  if (h && h[0] === 'v' && sel1.value) { delVertex(sel1.value, +h.slice(1)); return; }
  const id = tgt.closest('[data-id]')?.getAttribute('data-id');
  if (id) { openInside(id); return; }           // Double-click equipment = equipment internals / PLC program (same as the flowchart); use F2 to rename
  const lk = tgt.closest('[data-lk]')?.getAttribute('data-lk');
  if (lk?.startsWith('zones:')) { pv.lsel = [{ kind: 'zones', id: lk.slice(6) }]; ed.sel = []; showProps(); pv.focusName++; }
}

// ---------- Keyboard (capture phase: handle layout copy/paste and length entry before Workbench global shortcuts) ----------
const stop = (e: KeyboardEvent) => { e.preventDefault(); e.stopImmediatePropagation(); };
function nudge(dx: number, dy: number) {
  const ops: Op[] = selBlocks.value.filter(onFloor).map((b: any) => ({ op: 'update_block', id: b.id, set: { pos: [+(b.pos[0] + dx).toFixed(2), +(b.pos[1] + dy).toFixed(2)] } }));
  if (pv.lsel.length) { const l = clone(L.value); translate(l, pv.lsel, dx, dy); ops.push({ op: 'update_plant', set: { 'plant.layout': l } }); }
  exec(ops, $t('planView.nudgePosition'));
}
function refreshTp(shiftKey: boolean) {
  if (!lastMouse || !svg.value || !DRAW.includes(tool.value) || edit.on) return;
  tp.value = toolPoint(cursor.value, { shiftKey, altKey: lastMouse.altKey });
}
function onKey(e: KeyboardEvent) {
  if (ed.view !== 'plan' || (e.target as HTMLElement).closest?.('input:not([type=radio]):not([type=checkbox]),textarea,[contenteditable],.el-dialog,.el-message-box')) return;
  if (e.code === 'Space') { space = e.type === 'keydown'; spaceDown.value = space; if (tool.value === 'select' || DRAW.includes(tool.value)) e.preventDefault(); return; }
  if (e.key === 'Shift') { refreshTp(e.type === 'keydown'); return; }
  if (e.type !== 'keydown') return;
  const k = e.key, mod = e.ctrlKey || e.metaKey, lk = k.toLowerCase(), drawing = DRAW.includes(tool.value) && tool.value !== 'measure' && tool.value !== 'calib';
  if (drawing && !mod && !e.altKey && /^[0-9.,<@-]$/.test(k)) { typed.value += k; stop(e); return; }
  if (drawing && typed.value && k === 'Backspace') { typed.value = typed.value.slice(0, -1); stop(e); return; }
  if (drawing && typed.value && k === 'Enter') { applyTyped(); stop(e); return; }
  if (k === 'Backspace' && POLY.includes(tool.value) && draw.pts.length) { draw.pts.pop(); stop(e); return; }
  if (mod && lk === 'c' && pv.lsel.length) { copyLay(); stop(e); return; }
  if (mod && lk === 'v' && pv.clipKind === 'layout' && clipCount(getClip())) { pasteLay(hover.value ? cursor.value : null, sn); tool.value = 'select'; stop(e); return; }
  if (mod && lk === 'd' && pv.lsel.length) { duplicateLay(); stop(e); return; }
  // Paste equipment at the pointer (global Ctrl+V uses a slight offset)
  if (mod && lk === 'v' && pv.clipKind !== 'layout' && hover.value && (ed.clipboard || localStorage.getItem('vf_ed_clip'))) { paste({ pos: [sn(cursor.value[0]), sn(cursor.value[1])] }); stop(e); return; }
  if (k === 'Escape' && (conn.value || qa.show)) { conn.value = null; qa.show = false; stop(e); return; }
  if (k === 'F2' && ed.sel.length === 1 && blocksById.value[ed.sel[0]]) { focusProps(ed.sel[0]); stop(e); return; }
  if (k === 'Tab' && !mod && tool.value === 'select' && editable()) {
    const r = mainEl.value!.getBoundingClientRect(), sp = toScreen(cursor.value);
    openQuick(ed.sel.length === 1 && blocksById.value[ed.sel[0]] && layerOf(ed.sel[0]) === 'process' ? ed.sel[0] : null, hover.value ? sp[0] : undefined, hover.value ? sp[1] : undefined,
      hover.value && ed.sel.length !== 1 ? [sn(cursor.value[0]), sn(cursor.value[1])] : null);
    stop(e); return;
  }
  if (!mod && !e.altKey && !e.shiftKey && HOTKEY[lk] && !typed.value) { tool.value = HOTKEY[lk]; stop(e); return; }
  const st = e.shiftKey ? 0.1 : snap.value || 0.5;
  const map: Record<string, number[]> = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st] };
  if (map[k] && (selBlocks.value.length || pv.lsel.length)) { e.preventDefault(); nudge(map[k][0], map[k][1]); }
  else if (lk === 'r' && !mod && selBlocks.value.length) rotateSel(e.shiftKey ? -90 : 90);
  else if (k === 'Enter' && draw.pts.length) finishDraw();
  else if (k === 'Escape') {
    if (typed.value) typed.value = '';
    else if (draw.pts.length || draw.node || draw.rect) { draw.pts = []; draw.node = ''; draw.rect = null; }
    else { meas.a = meas.b = null; tool.value = 'select'; pv.lsel = []; }
  } else if ((k === 'Delete' || k === 'Backspace') && pv.lsel.length) removeLays();   // The Workbench deletes any equipment selected alongside these elements
}
watch(() => ed.clipboard, () => { pv.clipKind = 'blocks'; });

// ---------- Background image ----------
function setUl(set: any) { exec([{ op: 'update_plant', set: { 'plant.underlay': { ...ul.value, ...set } } }], $t('planView.adjustBackgroundImage')); }
function pickFile() { file.value?.click(); }
function upload() {
  const f = file.value?.files?.[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = async () => {
    const data = String(rd.result);
    const img = new Image();
    img.onload = async () => {
      const r = await post(P(ed.pid) + '/underlay', { data_url: data });
      const w = floor.value?.[0] || bounds.value.x1 - bounds.value.x0;
      exec([{ op: 'update_plant', set: { 'plant.underlay': { url: r.url, x: bounds.value.x0, y: bounds.value.y0, w, h: w * img.height / img.width, opacity: 0.5, show: true } } }], $t('planView.uploadBackgroundImage'));
      ElMessage.success($t('planView.backgroundImageUploadedUseCalibrate'));
    };
    img.src = data;
  };
  rd.readAsDataURL(f);
  file.value!.value = '';
}
async function calibrate() {
  const d = dist(meas.a, meas.b);
  try {
    const { value } = await ElMessageBox.prompt($t('planView.theseTwoPointsAreCurrently', [d.toFixed(2)]), $t('planView.calibrateBackgroundImage'), { inputValue: d.toFixed(2), inputPattern: /^\d+(\.\d+)?$/, inputErrorMessage: $t('planView.enterANumber') });
    const s = parseFloat(value) / d, u = ul.value, p = meas.a;
    setUl({ x: p[0] - (p[0] - u.x) * s, y: p[1] - (p[1] - u.y) * s, w: u.w * s, h: u.h * s });
    ElMessage.success($t('planView.backgroundImageScaledToActual'));
  } catch { /* Cancel */ }
  meas.a = meas.b = null; tool.value = 'select';
}

// ---------- Drag and drop ----------
function onDrop(e: DragEvent) {
  const w = world(e as any).map((x) => sn(x));
  const type = e.dataTransfer?.getData('vf/type'), tpl = e.dataTransfer?.getData('vf/tpl');
  if (type) {
    const b: any = makeBlock(type, w, nodePosNear(w));
    if ((ed.floor || 'F1') !== 'F1') b.floor = ed.floor;
    exec([{ op: 'add_block', block: b }], $t('common.add2') + typeOf(b).label); select([b.id]); flash([b.id], 1500);
  } else if (tpl) {
    const t = (ed.templates || []).find((x: any) => x.id === tpl); if (!t?.blocks?.length) return;
    const b0 = t.blocks[0], node = nodePosNear(w);
    const { ops, ids } = cloneOps(t.blocks, t.links || [], [w[0] - b0.pos[0], w[1] - b0.pos[1]], [node[0] - (b0.node?.[0] || 0), node[1] - (b0.node?.[1] || 0)]);
    exec(ops, $t('graphView.insertTemplate') + t.name); select(ids); flash(ids);
  }
}

watch(() => ed.focusReq, (r) => {
  if (!r || ed.view !== 'plan') return;
  if (!r.id) return fit();
  if (String(r.id).startsWith('path:')) {     // Road network issues in model validation: select and center the node / connection
    const id = r.id.slice(5), s = (L.value.paths?.nodes || []).some((n: any) => n.id === id) ? { kind: 'nodes', id } : { kind: 'edges', id };
    const q = pointsOf(L.value, s); if (!q.length) return;
    tool.value = 'select'; pv.lsel = [s]; ed.sel = [];
    const rr = svg.value!.getBoundingClientRect(), c = [q.reduce((t, x) => t + x[0], 0) / q.length, q.reduce((t, x) => t + x[1], 0) / q.length];
    v.k = Math.max(v.k, 10); v.tx = rr.width / 2 - c[0] * v.k; v.ty = rr.height / 2 - c[1] * v.k;
    return;
  }
  const b = blocksById.value[r.id]; if (!b) return;
  const rr = svg.value!.getBoundingClientRect();
  v.k = Math.max(v.k, 10); v.tx = rr.width / 2 - b.pos[0] * v.k; v.ty = rr.height / 2 - b.pos[1] * v.k;
});
watch(tool, () => { meas.a = meas.b = null; draw.pts = []; draw.node = ''; draw.rect = null; typed.value = ''; });
// After undo or switching factories, clear layout selections that no longer exist
watch(L, (l) => { const keep = pv.lsel.filter((s: LSel) => itemOf(l, s)); if (keep.length !== pv.lsel.length) pv.lsel = keep; });
watch(() => ed.pid, () => { pv.lsel = []; pv.preview = null; });
// Deselect connections when selecting layout elements (show layout elements in the right Properties panel)
watch(() => pv.lsel.length, (n) => { if (n && ed.selLink) ed.selLink = ''; });
let ro: ResizeObserver | null = null;
let stopLive: (() => void) | null = null;
onMounted(() => {
  if (!ed.filter) loadFilter();
  stopLive = useLive();
  fit(); routeK.value = v.k;
  addEventListener('keydown', onKey, true); addEventListener('keyup', onKey, true); addEventListener('mousedown', closeQa, true);
  ro = new ResizeObserver(() => { const r = svg.value?.getBoundingClientRect(); if (r) { size.w = r.width; size.h = r.height; } });
  if (svg.value) ro.observe(svg.value);
});
onUnmounted(() => { if (ctxTools.measure.plan === cancelMeasure) ctxTools.measure.plan = null; stopLive?.(); removeEventListener('keydown', onKey, true); removeEventListener('keyup', onKey, true); removeEventListener('mousedown', closeQa, true); ro?.disconnect(); pv.lsel = []; pv.preview = null; });
defineExpose({ fit });
</script>
