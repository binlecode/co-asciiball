# DESIGN-showcase-page — the rendering showcase & how it's published

This spec captures the **web page** side of the project: `docs/showcase.html`,
the self-contained visual companion to the terminal renderer, plus how it is built and
published. It is the page counterpart to [`DESIGN-system.md`](DESIGN-system.md) (which
covers the *rendering model*). Build recipe and the on-disk generator conventions live in
the [`showcase` skill](../.claude/skills/showcase/SKILL.md); the deploy
procedure lives in [`RUNBOOK-pages-publish.md`](RUNBOOK-pages-publish.md). This file is the
*why* behind both.

## What the page is

A single standalone HTML file that shows the **real engine output** — the actual rendered
ANSI frames, baked in as pre-colored HTML spans — so someone can see what the renderer
looks like without cloning and running it. It is linked from `README.md` and published to
a free public URL while the repo stays private:

> **https://asciiball.pages.dev/**

Three animated panels ship today: Earth on a dark terminal (shipped default), Earth on a
light terminal (`--theme light`), and the Moon on a dark terminal. Each panel is
**twinned**: the 256-color and 24-bit renders of the same view sit side by side (256 left,
truecolor right) and spin in lockstep off one shared control row, so the auto-adapted
gradient is compared directly. For performance each panel only animates while it's on
screen (an `IntersectionObserver` gates the rotation timer).

## Non-negotiable constraints

1. **Generated, never hand-edited.** The HTML is produced by `scripts/build_showcase.py`,
   which imports the real engine + body modules (from `src/`, which it puts on `sys.path`)
   and renders frames through the same code path as the CLI. Editing the HTML by hand would
   let it drift from the engine. Treat a regenerated page as a review checkpoint, like
   `tests/test_render.py --update`.
2. **One file, zero external assets.** No CDN, no external CSS/JS/fonts/images. Everything
   is inline: CSS in a `<style>`, JS in a `<script>`, the favicon as a `data:` URI. This is
   both an aesthetic choice (it mirrors the renderer's "no runtime deps" ethos) and a
   hard requirement for the way it's published (see "Publishing").
3. **Stdlib-only generator.** `build_showcase.py` uses only the standard library, like the
   renderers themselves. It is committed under `scripts/` (reusable), not `tmp/` (scratch).
4. **Grayscale-depth identity.** The engine's whole thesis is that depth reads from
   grayscale contrast alone — no lighting model, no hue. The page's own chrome stays in a
   cool, near-monochrome palette so it never upstages or contradicts that story.

## Visual system

- **Palette.** Cool neutrals with a single teal accent (`--accent` = `#0e7c8b` light /
  `#5ec8d8` dark). Deliberately *not* a warm/multi-hue scheme — the page is a quiet frame
  around monochrome frames.
- **Theme-aware chrome, fixed-ground frames.** The page chrome follows
  `prefers-color-scheme` and can be overridden via a `◐ theme` toggle that flips
  `:root[data-theme]`. The **terminal frames keep their own fixed black/white ground**
  regardless of page theme, because each panel simulates a real terminal (a dark-terminal
  frame stays dark even on a light page). `color-scheme: light dark` is set so native
  controls/scrollbars match.
- **Ambient "void" wash.** A fixed `body::before` layers two faint teal radial gradients
  for depth — a starless-nebula backdrop — behind `z-index:1` content. Purely cosmetic; it
  never touches the frames.
- **Typography.** A system sans for prose, a monospace for the eyebrow/captions/terminal.
  No serif display face — kept technical on purpose.
- **Frame geometry must stay circular.** The baked frames are rendered at `--aspect 2.3`
  (see `ASPECT` below), which assumes a *real terminal's* character-cell height:width ratio.
  Webfont monospace stacks rendered at `line-height:1.0` are flatter than that (closer to
  ~1.6-1.7:1), so `.frame` sets `line-height:1.3` to bring the browser's rendered cell back
  to the assumed ratio — without it the disc renders as a flattened oval (poles reading as
  cut off) instead of a circle. If the font stack in `--mono` ever changes materially,
  re-verify circularity (screenshot a panel, check the disc's bounding box is ~square)
  before shipping.
- **Motion.** Subtle hover lifts on cue cards and panels; everything is gated behind
  `@media (prefers-reduced-motion: reduce)`.

## Interactivity — the rotation scrubber

Each panel bakes in **one full rotation** as `FRAMES` stacked `<pre>` frames (default 48,
at evenly-spaced angles `i/FRAMES · 2π`). Rotation is periodic in 2π (asserted by
`test_moon_rotation_periodicity`), so frame `N` wraps seamlessly back to frame 0.

- Frames are stacked in a single CSS grid cell; only the `.active` one is visible.
  Inactive frames use `visibility:hidden` (not `display:none`) so the viewer holds a
  **stable size** and scrubbing never reflows.
- A styled `<input type=range>` slider scrubs frames; a play/pause button auto-advances
  (`setInterval`, base 90 ms). A `NN / NN` counter mirrors the position.
- A per-panel **speed toggle** (`1×`/`0.5×`/`0.25×` pills) scales that interval
  (`90ms / speed`) so slower speeds re-sample the *same* baked frames more slowly rather
  than baking a second frame set — clicking a speed while playing re-arms the running
  timer immediately at the new rate.
- **Autoplay on load**, unless the visitor prefers reduced motion.
- All of it is a small block of inline vanilla JS — DOM class toggles, no libraries. This
  is the only JS on the page besides the theme toggle.

Trade-off: baking a full rotation for every pane is what drives the file size. Today that is
`FRAMES` (48) × 3 panels × 2 color depths = **288 baked frame-stacks**, and the truecolor
panes (`38;2;r;g;b` per cell) are more verbose than the 256-color ones, so the page is
**~8.8 MiB**. That is still under Cloudflare's 25 MiB/file limit (the ceiling to watch when
raising `FRAMES` or adding panels), and it keeps the page self-contained (the alternative —
a data file + client-side renderer — would violate the "one file, real baked frames"
constraints).

## Implementation — `scripts/build_showcase.py`

- `R, ASPECT` — pinned render inputs (kept in sync with what the footer copy claims).
  `_glyphs()` deliberately resolves the real CLI default (no `--glyphs`/`--glyph-source`,
  so it falls through to the bundled README.md) rather than a short pinned string — a short
  string cycles quickly enough to tile visibly across a large contiguous surface (e.g. the
  Moon's highlands cover ~75% of the sphere as one opaque region, versus Earth's land broken
  up by oceans). `FRAMES` (48) — how many angles of one rotation to bake per panel; `ANGLES`
  derives from it. Each panel bakes `FRAMES` × 2 depths, so more frames = smoother scrub,
  bigger file (~60 KB per panel per frame across both twin panes).
- `panels()` — the `specs` list: `(name, subtitle, ground, surface, theme, tuning)`. Add a
  body by appending a row (e.g. `moon.make_surface(gl, 0.25)`); ground `"#000"` for a
  dark-terminal panel, a light hex (e.g. `"#f4f4f2"`) for a `--theme light` panel. Each
  panel renders the surface at BOTH depths (`_stack` per `Globe(..., truecolor=...)` over
  `DEPTHS`) into two side-by-side `.pane`s and emits a shared `.controls` row (play +
  slider + counter + speed) that drives both stacks in lockstep.
- `_stack()` — one rotation of a globe as stacked `<pre>` frames (frame 0 active).
- `frame_html()` — converts one ANSI frame to HTML spans, coalescing runs of identical
  color the way the engine coalesces escape codes.
- `sgr_color()` — resolves an SGR param string to a CSS color: both grayscale forms the
  engine emits, 256-indexed (`38;5;N`, via `gray_rgb`) and 24-bit truecolor
  (`38;2;r;g;b`, from `--color-depth truecolor`). **Only grayscale is handled.** A future
  hued body would need this extended to parse the full 256-color cube / arbitrary RGB, or
  its frames fall back to gray.
- `gray_rgb()` — maps xterm-256 grayscale indices (232–255) to `#rrggbb`.
- `_distinct_lumas()` / `depth_gain()` — count distinct grays in a frame; `depth_gain`
  returns the (256, truecolor) counts for one representative Moon frame, injected into the
  lead-in copy so the quoted numbers can't go stale.
- `PAGE` — the HTML template; `__PANELS__`, `__N256__`, `__NTC__`, `__FRAMES__`, and
  `__VERSION__` are substituted in `main()`. The inline JS drives the scrubber and an
  `IntersectionObserver` that only spins on-screen panels.

## What we borrowed (and didn't) from the sibling page

The sibling repo's page (`menubar-load-runner.pages.dev`) is a warm, editorial,
atmospheric design. We reviewed it and borrowed **palette-agnostic techniques**, not its
look:

- **Borrowed:** custom-styled range slider (gradient track + round thumb), an in-page theme
  toggle, a mock-terminal quickstart block (traffic-light dots + syntax-colored commands),
  an ambient background wash (reskinned cool), an inline-SVG emoji favicon,
  `color-scheme: light dark`, footer pill badges, and hover lifts.
- **Deliberately not borrowed:** its warm river→lantern→ember palette, serif display
  headings, and the GIF-driven demo. Those are that app's identity; ours is
  monochrome-depth. Copying the palette would fight our whole thesis.

## Publishing (summary)

Published to **Cloudflare Pages** via Direct Upload (Wrangler CLI or Dashboard) so the
private repo stays private and only the one built HTML file becomes public. The
self-contained constraint above is what makes this safe and simple — Cloudflare only ever
receives the built HTML, never the repo. Full procedure, prerequisites (Node 22 for
wrangler v4, `pages project create` before first deploy), and troubleshooting are in
[`RUNBOOK-pages-publish.md`](RUNBOOK-pages-publish.md).

## Regen & change workflow

```bash
python scripts/build_showcase.py     # rewrites docs/showcase.html
```

Rebuild in the **same change** that alters the shading (the `NEAR/FAR/STIPPLE_CONTRAST`
ramps, `Z_LEVELS`, radial-band/limb-taper logic) or adds a body, and sanity-check the diff.
The `showcase` skill has the full recipe and a well-formedness check
(doctype present, no leaked ANSI escapes, placeholders substituted). After regenerating,
republish per the runbook if the live page should reflect the change.
