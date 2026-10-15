# Editorial Visualization System

Status: implemented visual primitives and reference preview (#191). Production
RPE selector adoption is implemented in #192; guidance belongs to #193. Existing
readiness, Diary and Analytics charts have not been restyled. Reference: [visual identity](VISUAL_IDENTITY.md).

## Preview and scope

Open `/today/visual-system` on the main domain (the existing `/today*` Basic Auth
boundary applies; API-domain access remains blocked). This SSR page contains
explicitly labelled synthetic examples, no athlete reads, forms, JavaScript,
external assets or API calls. Bars, a split area, numeric callouts and marginal
annotations demonstrate composition independently of RPE.

Primitives live in `backend/backend/templates/visualizations/primitives.html`;
opt-in tokens and styles in `visualizations/editorial.css`. The separate
`gallery.css` styles only the preview. Templates use existing Jinja2 rendering;
no frontend framework, new chart library or analytics service is introduced.

## Composition

Include the existing editorial styles, then `visualizations/editorial.css`.
Wrap the composition in `.viz-system` so fonts, paper, ink and pigment tokens
are available. Import only the macros needed:

```jinja
{% from "visualizations/primitives.html" import paper_surface, ink_grid,
    watercolor_fill, hand_drawn_stroke, chart_typography, editorial_annotation %}
{% call paper_surface(texture='subtle', transparent=false) %}
<svg viewBox="0 0 640 300" role="img" aria-labelledby="load-title load-desc"
     xmlns="http://www.w3.org/2000/svg">
  <title id="load-title">Recorded load</title>
  <desc id="load-desc">Supply accessible values, units and missingness here.</desc>
  {{ ink_grid('load-grid', 50, 30, 550, 200, minor=20, major=100) }}
  {{ watercolor_fill('load-wash', 'sage') }}
  <path d="{{ area_path }}" fill="url(#load-wash)"/>
  {{ hand_drawn_stroke(line_path) }}
  {{ chart_typography(50, 285, 'Day / units', kind='axis') }}
  {{ editorial_annotation(320, 40, 'Observation', leader=leader_path) }}
</svg>
{% endcall %}
```

`area_path`, `line_path` and `leader_path` are illustrative template inputs; they
must come from the consuming chart's existing renderer. The system never computes
load, scales, recommendations, baselines, interpolation or missing-value fallbacks.
Reuse existing utilities such as `today/history_figure.html` when adopting this
style in a later scoped task. Do not copy sample datasets into product fallbacks.

## Primitive contracts

| Primitive | Parameters and constraints |
| --- | --- |
| PaperSurface | `paper_surface(texture='subtle', transparent=false)` call block. Texture: `none`, `subtle`, `visible`; transparent removes the paper color while retaining optional grain. |
| InkGrid | `ink_grid(id, x, y, width, height, minor=20, major=100, horizontal=true, vertical=true)`. Positive spacing in SVG user units; major/minor origins align at x/y. Grid is decorative. |
| WatercolorFill | `watercolor_fill(id, tone='sage')` emits a `<defs>` pattern. Apply with `fill="url(#id)"` to any SVG shape. Tone: `sage`, `blue-gray`, `ochre`, `terracotta`, `burgundy`. |
| HandDrawnStroke | `hand_drawn_stroke(path, width=1, echo_path='')`. The primary path is exact. Optional caller-supplied echo is decorative and hidden from assistive technology; never deform the primary data geometry. |
| EditorialAnnotation | `editorial_annotation(x, y, label, leader='', callout='', handwritten=false)`. Leader is an explicit SVG path (including any arrow tip); labels use escaped text. Handwriting is optional local-font decoration. |
| ChartTypography | `chart_typography(x, y, text, kind='axis', anchor='start')`. Kinds: `heading`, `axis`, `number`, `callout`; normal SVG text anchors. Use numbers/axes for essential values. |

Pass a stable, unique per-instance prefix for all IDs, including title/description
and grid/fill IDs. If a page repeats a chart, use its stable chart-instance key;
never a random UUID or an athlete identifier. IDs are document-wide, not SVG-local.
Macros accept trusted template configuration, not arbitrary CSS classes/paths
from request parameters. Text is escaped by the existing HTML template environment.

## Tokens, accessibility and precision

Shared `--viz-*` tokens cover paper/ink, muted caption text, the five pigments,
major/minor grid opacity, texture opacity and serif/mono/handwritten typography.
Defaults inherit the existing Whatte paper, ink and fonts; override on the chart
wrapper for a scoped variant. Paper intensity presets are .035/.07, and `none`
is zero; a custom `--viz-texture-opacity` may be set on the surface itself.
Grid opacity defaults to .25/.10 and can be overridden on the chart wrapper.

Pigments are fills, never text colors. Axes and essential numbers use ink on
paper; captions use muted text on paper. Label values directly, outline bars,
mark observations and describe missing data without relying on color. Give SVGs
unique title/description links and provide accessible values (a table for dense
plots). Split area/line paths at gaps; the preview includes this example.

The preview keeps charts at a readable minimum width inside labelled keyboard
focusable scroll regions on narrow screens. Consuming charts may instead supply
an appropriate responsive composition. Preserve native controls, focus indicators,
44px hit targets for interactive applications, existing CSRF/user checks, source
precedence, error/loading states and no-JavaScript submission behavior. These
primitives add no interactivity; they do not implement an RPE selector.

No animation is enabled. Reduced-motion rules suppress future scoped transitions;
forced-colors mode removes paper grain and uses system ink/paper. Do not apply
visual jitter, rounding or displacement to data coordinates. Decorative echo
paths are optional and must stay clear of axes, labels and hit targets.

## Performance and verification

Textures use tiny repeatable vector tiles (48 user units), without raster assets,
SVG filters, turbulence, masks, JavaScript, font downloads or random seeds. Reuse
one fill definition per tone per SVG; use a unique ID for the next SVG instance.
The fixed tile makes re-renders stable. Grain is deliberately restrained, and
vector wash is an approximation of watercolor rather than a photorealistic effect.

Run from `backend/` with the normal test environment:

```sh
.venv/bin/python -m pytest tests/test_visualizations.py tests/test_today.py -q
```

The repository uses pytest SSR assertions. `tests/fixtures/visualizations/*.svg`
are reviewed rendered SVG baselines for bars, split area, grid and annotations;
canonical XML comparison catches coordinate, label, definition and composition
changes without whitespace noise. They are structural visual regressions, not
cross-browser pixel comparisons. Before changing baselines, inspect the actual
preview at desktop and 320/375px widths, keyboard scrolling, no-JS mode and reduced
motion. Shared CSS/font changes also require browser review because SVG fixtures
do not capture rasterization or computed CSS. Keep local screenshots under
`output/playwright/` (untracked). No browser package is added to backend CI.

Validation for #191 (2026-10-15): Chromium preview inspected at 1440, 375 and
320px; document width matched viewport at every size, while only chart regions
scrolled. ArrowRight moved the focused chart region; native tables opened with
JavaScript disabled. Reduced motion computed `animation: none`. Default text
contrast against paper: ink 12.63:1, captions 6.45:1. Three SVG baselines cover the
representative compositions. Local backend suite: 832 passed (integration checks
run separately in CI). Preview HTML including all inline styles/SVG: 38,700 bytes;
no additional chart assets/dependencies or network requests are required.

## RPE production composition (#192)

`today/rpe_selector.html` is the first interactive consumer. Its macro accepts
`id`, controlled nullable `value`, backend `options`, and optional `error`.
Use it inside a form; it renders required native `score` radios but never submits.
Include `today/rpe_selector.css` after the shared styles, and optionally
`today/rpe_selector.js` for live numeric announcements. Each instance needs its own
form/radio group and stable ID prefix. The caller owns confirmation and writes.
Ten exact increasing rectangles use shared vector washes, ink, paper and grid;
checked radios provide an outline and marginal check annotation. The entire
column, including empty space above the paint, is interactive. At 390px columns
are about 36px wide and 188px tall, keeping all ten values visible; desktop
columns expand up to 78px. No fractional values, chart gestures or guidance rules
are introduced. Native arrows, Space and focus remain browser-owned.

Validation on 2026-10-15: Chromium at 390/1440px had document widths exactly
matching the viewport. All ten values were selected by click and native arrows;
a 390px touch/no-JS context selected and saved 10 with a visible numeric preview.
Reduced motion computed no animation/transition. Selection emitted zero POSTs;
a pending request locked all ten radios and save, and a duplicate submit emitted
no extra POST. An aborted response retained the draft; only explicit retry sent
the second request and confirmed stored Web state/focus. A simulated persisted
pageshow restored all ten controls while invalidating the late save callback
(without retry). This last check exercises the lifecycle handler, not an actual
browser BFCache traversal. Local suite: 857 passed, 24 integration tests excluded;
exact-SHA database/release checks run in CI. Screenshots inspected at both widths.
