# HoneyFactory Design System (= HoneyMOM Design System, Light · Tech)

> This design system is shared with [HoneyMOM](https://github.com/HoneyMeta/HoneyMOM). Some component paths and tests mentioned below (for example `components/home`, `ai`, `tour`, `pages_ui.js`) exist only in the HoneyMOM repository.

> Since 5.0.1, HoneyFactory and HoneyMOM share one design system. This directory was ported from HoneyMOM's `web/src/design` (tokens, base styles, chart theme, formatting, Hm* components).
> HoneyFactory only has a light theme (dark mode has been removed; legacy `vf_theme` settings are silently migrated by `web/src/theme.ts`). Differences from MES:
> - `index.ts`: No "Send to AI" selection layer; `v-ai` / `v-ai-rows` are no-op directives. No `HmPageHead` (page headers use `.page-head`; breadcrumbs are in the shell, `layout/Layout.vue`).
> - End of `tokens.css`: Legacy variables `--ln --mu --ok --warn --bad --acc --honey` also map to the new tokens; `--hm-scale` is fixed at 1 in `html.compact` (compact layout, `compact.ts`).
> - Charts: `components/Chart.vue` uses the `hm` theme from `chart.ts`; illustrations for `HmEmpty` are in `web/public/art/`.
> - The Workbench (`.ed` variables in `editor/editor.css`) and the 3D / floor plan / flow canvases also map to these tokens.
> Below is the original HoneyMOM documentation. MES-specific features—AI panel, Home widgets, and guided tour engine—are not included in HoneyFactory; use HoneyFactory's own implementations instead.

## Original Documentation

A precise, modern industrial system without visual clutter. White and very light gray surfaces, translucent "glass" panels, cobalt blue as the primary color and cyan for data, with Honey amber used only as an accent. All AI features use a subtle "cyan → blue → purple" gradient.

Files:

| File | Contents |
|---|---|
| `tokens.css` | All design tokens (CSS variables `--hm-*`), Element Plus primary color / border radius overrides, and legacy variable mappings (`--card` `--line` …) |
| `base.css` | Global baseline, utility classes (`.hm-*`), updated styling for legacy page classes (`.page` `.card` `.kpi` `.tag-st` …), tables, AI selection rings, animations |
| `format.ts` | Number formatting: `fmtNum` `fmtPct` `fmtUnit` `fmtCompact` `fmtDur` `fmtTime` `fmtDelta` `fmtBy`; code + name: `codeName` `bareName` (avoid repeating the code when it is already in the name, e.g., AGV / "AGV Fleet") |
| `motion.ts` | `useTickUp` (animated number transitions), `reducedMotion()` |
| `components/` | `HmPageHead` `HmKpi` `HmNumber` `HmStatus` `HmCard` `HmEmpty` `HmToolbar` `HmTag` `HmSkeleton` `HmDataTable` `HmAutoScroll` (globally registered; use directly in pages) |
| `chart.ts` | ECharts theme `hm`, `PALETTE`, semantic colors `CH`, `targetLine` (see "Charts" below) |
| `index.ts` | `installDesign`: Registers components and the `v-ai` / `v-ai-rows` directives |
| `MIGRATION.md` | How to apply the new styles and AI selection to legacy pages |

## Tokens

**Colors** (use variables only; do not hardcode color values)

- Surfaces: `--hm-canvas` (main canvas, with the fine grid from `.hm-grid-bg`), `--hm-surface` (cards / tables), `--hm-surface-2` (table headers / toolbars), `--hm-surface-3` (hover); glass: `--hm-glass` / `--hm-glass-strong` + `--hm-glass-blur` (or use `.hm-glass` directly)
- Borders: `--hm-border`, `--hm-border-strong`, `--hm-hairline`
- Text: `--hm-text` (primary), `--hm-text-2` (secondary), `--hm-text-3` (descriptions, units)
- Primary: `--hm-primary` (cobalt blue, buttons / links / selection), `--hm-primary-soft`; data: `--hm-cyan` (lines, graphics; use `--hm-cyan-ink` for text on cyan surfaces or as a background for white text); brand: `--hm-amber` (#d9822b, avatars, count badges, occasional accents)
- AI: `--hm-ai-grad` (gradient), `--hm-ai-soft`, `--hm-ai-ring` ("Selected for AI" ring)
- Status: Running `--hm-run`, idle `--hm-idle`, failure `--hm-fault`, offline `--hm-offline`, changeover `--hm-setup`; each has `-soft` (background) and `-ink` (text) variants
- Contrast: Text and background must have a contrast ratio of at least 3:1 (checked by `tests/pages_ui.js`). Use `-ink` as the background for white text on colored blocks (neither `--hm-idle` nor `--hm-cyan` provides enough contrast for white text). Use `--hm-text-3` only on white / `--hm-surface` backgrounds; use `--hm-text-2` for descriptive text on light colored backgrounds (`-soft`, gradients).

**Fonts**: Body text `--hm-font`; numbers `--hm-font-num` + `font-variant-numeric: tabular-nums` (class `.hm-num`); code / identifiers `--hm-font-mono` (class `.hm-mono`).
Font sizes: `--hm-fs-2xs`(11) `xs`(12) `sm`(13, body text) `md`(14, card titles) `lg`(16) `xl`(20, page titles) `2xl`(26) `3xl`(34, large KPI values).

**Spacing** `--hm-sp-1..8` (multiples of 4); **border radius** `--hm-r-xs/sm/md/lg/pill` (cards 12, buttons / inputs 6); **elevation** `--hm-e1` (cards) `--hm-e2` (hover) `--hm-e3` (popovers, AI panel overlays); **focus ring** `--hm-focus` (already applied globally via `:focus-visible`).

**Motion**: `--hm-dur-1/2/3` (120/200/320ms) + `--hm-ease`. Animated number transitions: `HmNumber`/`useTickUp`; status pulse: `.hm-pulse` (running and failure dots); panel slide-in: `<Transition name="hm-slide-right">`, fade: `hm-fade`; entrance: `.hm-enter`.
All motion is disabled when the system's "Reduce motion" setting is enabled (`prefers-reduced-motion` in tokens.css and base.css).

## Components

```vue
<HmKpi label="Average OEE" :value="0.724" format="pct" :delta="0.031" delta-pct hint="Last 8 hours" :spark="[0.6,0.7,0.72]" to="/equipment/oee" />
<HmKpi label="Today's Electricity Use" :value="12345" unit="kWh" format="int" status="warn" :ai="{ data: { consumptionPerTon: 612 } }" />
<HmStatus status="running" />            <!-- Running (pulsing green dot) --> <HmStatus status="down" variant="dot" />
<HmCard title="Equipment Status" sub="Live"> <template #actions><el-button link>All ›</el-button></template> … </HmCard>
<HmDataTable :columns="[{ key: 'code', label: 'Equipment' }, { key: 'oee', label: 'OEE', num: true, format: 'pct' }]" :rows="rows" entity="equipment" max-height="420" />
<HmEmpty icon="search" title="No results found" desc="Try different filters"><el-button>Clear Filters</el-button></HmEmpty>
<HmEmpty plain title="No messages yet" />   <!-- Single line of text, no illustration -->
<HmToolbar> <el-input … /> <template #right><el-button type="primary">Add</el-button></template> </HmToolbar>
<HmTag tone="ok">Pass</HmTag> <HmTag tone="ai" closable @close="…">CNC3</HmTag>
<HmSkeleton variant="kpi" /> <HmSkeleton variant="table" :rows="6" />
<HmNumber :value="1234.5" unit="kg" />
```

- `HmKpi` includes `v-ai` (kind=kpi) by default: Ctrl+click or right-click to send it to AI. Use `:ai="false"` to disable it or `:ai="{ id, entity, data }"` to add context.
- `HmDataTable`: sticky headers, click-to-sort columns, and right-aligned tabular numerals. Each row automatically gets `v-ai` (kind=row); customize it with `:ai="(row) => ({…})"`. For large tables or pagination, continue using `el-table` + `v-ai-rows`.
- Always use `format.ts` for formatting; do not write custom `toFixed` calls.
- `HmEmpty`: show an illustration only in the primary empty area on each page. Use `plain` (or `empty-plain` on `HmDataTable`) for other empty areas to avoid repeating the same illustration on a page.

- `HmAutoScroll`: scrolls content upward at a constant speed when it exceeds the container height, with seamless looping (for long tables and scrolling announcements on shop-floor displays). Pauses on hover. Props: `:speed` (pixels/second, default 24), `height`, `:paused`. Falls back to a standard scrollbar when the system's "Reduce motion" setting is enabled.
  ```vue
  <div class="th">…Header…</div>
  <HmAutoScroll :speed="22" style="flex:1;min-height:0"> <div v-for="r in rows" class="tr">…</div> </HmAutoScroll>
  ```

Home / Shop-Floor Display components are in `web/src/components/home/` (not registered globally): `FactoryMap` (virtual plant floor plan + live status, hover cards, click to open equipment, Ctrl+click or right-click to send to AI; falls back to a status grid when no layout is available),
`FeedList` (alerts and AI Watch feed; see `honeymes/services/home_feed.py` for the API and provider), `OrderTimeline` (mini Gantt chart for work orders), `AndonStrip` (Andon strip), and `usePoll` (polling, paused when the page is hidden). All components have a `big` prop for shop-floor displays.

AI result components are in `web/src/ai/`: `AiBlocks` (charts / tables / KPI cards / source blocks in AI responses, with a "Pin to Home" action), `PinnedBlocks` (pinned blocks; the "Pinned AI Results" component on Home, shown only when blocks are pinned and AI is enabled),
`WatchFeed` (AI Watch finding cards; also renders kind=ai entries in the Home feed), and `DraftCard` (action drafts: executed only after approval).

## Principles

1. Industrial precision: use right-aligned tabular numerals with units and five fixed status colors. Do not let decorative gradients or illustrations take space away from data.
2. Easy to find: breadcrumbs at the top of every page; global `Ctrl+K` for pages, document numbers, commands, and sending to AI; `/` to filter the left menu.
3. AI is always available but never intrusive: Ctrl+click or right-click any data to send it to AI. The AI panel can collapse to a narrow strip at any time, and the main area reflows rather than being obscured. Non-AI features work normally when AI is disabled.
4. Light theme only.

## Density (Large Displays)

`--hm-scale` is set to 1 / 1.125 / 1.25 based on viewport width (< 1800px / 1800–2299px / ≥ 2300px; see the end of `tokens.css`). Font sizes `--hm-fs-*`, spacing `--hm-sp-*`, grid gaps `--hm-gap`, shell dimensions (top bar, menu width, status bar), and Element Plus control heights and font sizes are all multiplied by this factor. The maximum page width scales up as well.
Pages using tokens adapt automatically; hard-coded px values do not scale. For dimensions that need to scale, use `calc(200px * var(--hm-scale))`. For equipment cards, dashboard cards, and similar layouts that should add columns on wider screens, use `.grid.g-auto` (`style="--min: 248px"` sets the minimum column width).

## Charts (`chart.ts`)

`components/Chart.vue` automatically applies the `hm` theme (text scales with `--hm-scale`): a consistent `PALETTE` (cobalt blue, cyan, amber, purple…), axes, gridlines, tooltips, and legends. Charts with axes automatically use `containLabel`.
Donut charts display "name + percentage" labels outside the ring, aligned in two columns by default. The outer radius is capped at 60% to prevent clipping. With more than 6 slices, a legend on the right replaces the labels. Use `CH.ok / warn / bad / ref` for semantic colors and `targetLine('Target 85%')` for reference lines.
`<Chart :option ai="Chart Name" />`: hover over a data point, then Ctrl+click or right-click to send that point to AI (for line charts, this sends values from all series at the hovered position). You can also pass a function to customize AiItem.

## Page Header `HmPageHead`

```vue
<HmPageHead title="Quality Overview" sub="Last 7 days…" art="quality"> …Action buttons… <template #meta><HmTag>Records: 3</HmTag></template></HmPageHead>
```
A built-in "?" next to the title opens guided tours (page tour, three guided tasks, welcome tour). `art` selects a module illustration (equipment / quality / production / material / foundry / energy). Use it only on overview pages, not on data-heavy pages.

## Illustrations (`public/art/`)

The inventory and generation prompts are in `public/art/manifest.json`: login page `login-hero`, empty states `empty-data / search / permission / ai-off / offline` (`HmEmpty icon="data|search|lock|ai|offline"`), module headers `head-*`, and shop-floor display background `screen-bg.webp` (dark original; on light displays, invert it, use only the bottom half, and overlay it at low opacity as a texture; hide it in high-contrast mode). Style: isometric line art, charcoal outlines, white/cool gray fills, cobalt blue + cyan data layers, amber accents, no text.

## Guided Tours (`web/src/tour/`)

Define tour content in `guides.ts` (module tours map to pages via `routes`; `task-*` entries are guided tasks; `welcome` runs automatically on first login). Target steps with `data-tour="name"` (if not found, fall back to the CSS selectors later in the array).
Entry points: the "?" next to the page title (built into `HmPageHead`; for pages without it, add one to the breadcrumb row) or Ctrl+K, then type "tour". The engine in `engine.ts` is ported from HoneyFactory's tour engine: spotlight, step cards (Previous / Next / Skip / Exit), cross-page navigation, resuming the current step after a refresh, and a "Resume from step N?" prompt when reopening after exiting.

