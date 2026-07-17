# Design System — Asciiball

Recovered spec for the rendering model and engine architecture. `README.md` stays
the authoritative per-flag/per-body reference; this doc is the **body-agnostic**
"why it's built this way" companion — the engine (four axes), the module seam
(functional core / imperative shell), and the tuning *methodology* — read it before
extending the engine or adding a body. It names no body as canonical: the engine
only ever sees a `Surface` of `Material`s, and *how* a body fills that surface is a
pluggable **fill strategy** whose design lives in its own self-contained doc:

- **`docs/DESIGN-earth.md`** — the **text-fill** family (Earth's geographic
  continents; the screensaver's generated sentences).
- **`docs/DESIGN-moon.md`** — the **tone-fill** family (the Moon's albedo crust).
- (future) procedural bodies, dynamic terminal-content displays, … — each its own
  doc; the engine stays agnostic.

The web showcase has **`docs/DESIGN-showcase-page.md`**.

## Design goal

Render a **digital, hollow, transparent rotating 3D ASCII sphere** — a shell you
can see through — entirely in stdlib-only Python. The sphere is the core; *what is
mapped onto it* is a body concern (real planetary surface data → Earth/Moon,
generated text → the screensaver, and future sources). No 3D library, no runtime
dependencies — depth and structure read from **two-shell transparency + a
directional-light grayscale shade (a fixed sun the ball rotates under) + a stable
coverage dither** alone. "Planet" is the flagship application, not the primitive.

## The rendering model

The renderer is a first-principles compositing model for a hollow, rotating
sphere. It decomposes into **four orthogonal axes**, composed in a fixed order
A → B → C → D, each answering one independent question about a cell and never
reading another's knobs (the design contract: changing one axis's inputs must not
change another's output):

- **A — Sampling** (pure geometry): *where* on each shell does this cell land? A
  finite-eye **perspective** ray, so each shell it crosses lands at its own
  latitude/longitude/depth (see the shell walk).
- **B — Opacity** (the shell walk): does the ray stop at this shell or pass
  through?
- **C — Shade** (pure presentation): how deep + how prominent → what gray?
- **D — Density** (stylization): is the drawn ink painted, or thinned to a hole?

Two axes are stochastic (B, D) and share one stable, body-glued dither primitive
(`_hash2` keyed on surface-tile coords, with independent prime key offsets so they
stay decorrelated). This is the model the four subsections below detail.

### The shell walk (axis B — opacity)

Every screen cell inside the unit disc is a ray that pierces the sphere as an
ordered stack of samples, front → back. A hollow sphere is the **two-sample**
case — a near point and a far point — but the model never hard-codes two: the
shell stack is a `list`, so an atmosphere / rings / nested shells is a data
change, not a code change.

The ray is a true **perspective** ray, cast from an eye at `(0, 0, D)` (`D` =
`--eye`, default `2.6` sphere-radii) looking at the origin — *not* straight down
the axis. The screen-to-ray map is set so the disc edge (`d = 1`) is exactly the
sphere's tangent cone, so the silhouette is the same circle for any `D` and all
the disc-sizing math is unchanged. Because the ray is slanted, its two roots of
`|E + t·dir|² = 1` land at **different latitudes and longitudes**, and the far
hemisphere is foreshortened into a smaller inset — so the near and far walls never
line up row-by-row and the back-wall text reads *smaller*, a genuinely 3D read
rather than a 2D shaded disc with a mirrored dim copy behind it. As `D → ∞` the
rays become parallel and this collapses to the old orthographic
`near = (x, y, +z)` / `far = (x, y, −z)` (the `--eye 100` escape hatch). Each
shell's `(img_y, ty, shade_band, lon)` is precomputed per cell in `_build_cells`
(`_ShellSample`); the steady-state loop only adds `angle` to `lon`, so no
`sqrt`/`asin`/`atan2` runs per frame.

Each shell has an **opacity** `0..1`. Walk front → back; a shell stops the ray
with probability = its opacity (a stable per-tile dither), and the first shell
that stops wins. If none stop, the ray exits the back → **true hole** (blank).
This one walk collapses every old special case:

- **Solid** (opacity 1) → stops immediately, occludes, drawn bold on the near
  ramp — and short-circuits, so no deeper shell is even sampled (the cheap dense
  path).
- **Window** (opacity 0) → never stops → reveals whatever the next shell draws.
- **Screen-door** (0 < opacity < 1) → that fraction of tiles stop and draw dim,
  the rest fall through.
- **Text** (opacity 1, but blank tiles) → a blank glyph is per-tile opacity 0, so
  spaces are windows and ink is solid, with no special path. (The mnemonic "text =
  land, spaces = ocean" is one body's *reading* of this rule — the engine itself
  sees only opacity; see "The engine is fill-agnostic" below.)
- **Window-behind-window** → both shells pass → true hole through the globe.

These are the Porter-Duff "over" coverages collapsed to a single dithered sample.
Keying each shell's draw on its **own** tile (a per-shell salt in the dither) is
what lets the near screen-door slide with the near face and the far with the far.

**Far-wall visibility (`far_dim` / `far_fill`).** The far wall is the *same* surface
seen from behind, so its texture counter-scrolls against the near face; at full
strength that reads as a second surface fighting the front — through *any* large
window, not just a dense text globe (Earth's ocean is a ~71%-of-disc window). Two
body-agnostic engine defaults tame it, applied only to the far shell:

- `far_dim` (default `0.85`) scales the far ramp's brightness (capped by
  `FAR_CONTRAST` so even `1.0` stays a recessed ghost) — an axis-C effect.
- `far_fill` (default `0.5`) is a **per-shell SPARSITY keep**: after the far shell
  stops the ray, a second stable per-tile dither drops all but that fraction, so the
  back wall becomes a sparse *dotted depth field* rather than a dense wall. A thinned
  far tile passes through to a true hole. The near shell always keeps everything
  (`keep = 1000`).

Both were once per-body knobs on the text body; two independent tunings converged
(text `0.5`, Earth's ocean ghost measured `~0.45`), confirming the "far must not
out-shout the near" rule is geometry, not dataset — so it is one engine default, not
per-body tuning. Either knob at `0` truncates the walk to the near shell (front-face
only). `--far-fill 1` restores the old dense see-through.

### The material model (axis A/B/C inputs, per class)

A surface is a grid of class codes; each code maps to a **`Material`** — a flat
set of optical properties, one per axis, and nothing else. There is no `kind` tag
and no stipple sub-group; opaque, window, and screen-door are just three points on
the opacity scale:

- **`opacity`** (axis B, `0..1`) — 1.0 = solid/occluding, 0.0 = a window,
  fractional = a stable screen-door. Spelled `opacity` everywhere — never a bare
  `a`/`alpha`. It is the single most central scalar: it drives both occlusion
  (which shell) *and* prominence (which shade ramp, axis C).
- **`palette`** (axis A) — the glyph source. A pure window (opacity 0) needs none.
- **`hashed`** (axis A) — `False` indexes the palette in reading order (text reads
  across the surface), `True` hashes per tile (a texture with no reading order,
  e.g. crater rings). **Data contract:** a hashed palette carries no spaces, so a
  texture is guaranteed non-transparent (a blank is how per-tile opacity 0 is
  produced). The reading-order index is **lossless across window classes**: the
  near shell's `_packed_near` counts only drawable tiles, so a window class (a
  separate opacity-0 material, e.g. Earth's ocean) *splits* the text stream rather
  than chopping it — the covered characters are not consumed and lost, they resume
  on the next drawn tile. A body with no window class packs to the plain
  `ty·tiles_x + tx` identity, so this is a strict generalization (the text ball is
  byte-for-byte unchanged).
- **`relief`** (axis C) — a signed shade-band bias (topographic depth cue, not
  hue); see below.

The material count is a body's own choice and spans a wide range — the engine
treats them all identically:

- **1 material** — a solid marble (opacity 1, no windows).
- **2 materials** — one opaque feature + one window (opacity 1 + opacity 0): the
  minimal see-through body. A text-fill body draws its feature as reading-order text
  and lets blank tiles be the windows.
- **many materials** — e.g. a class *per tone level*, so a continuous albedo becomes
  theme-correct grayscale by riding `relief` into the shade ramp rather than glyph
  density, plus a screen-door window for partial transparency.

**The engine is fill-agnostic — it has no concept of "fill," "gap," "land," or
"ocean."** It sees only a stack of `Material`s and their four optical axes. "Fill
vs. gap" is merely the *binary* reading of the opacity axis — one opaque material
(opacity 1) over one window (opacity 0) — and "land vs. ocean" is one body's
vocabulary for that same reading. Both are storytelling laid over `opacity`, never
a code path: richer configs the engine draws identically — a screen-door
(`0 < opacity < 1`), N opaque tone bands differing only in `relief`, a recessed
crater ring — are neither "fill" nor "gap." So the primitive is more general than
either mnemonic: a hollow sphere of optical fragments, composited by the four axes.

Which materials a body declares — and how it decides where the windows fall — is
therefore its **fill strategy**, a body concern, not an engine one (the engine just
sees more or fewer `Material`s). The concrete strategies are documented per family:
**`docs/DESIGN-earth.md`** (text-fill) and **`docs/DESIGN-moon.md`** (tone-fill).

Choosing which real surface feature is opaque vs. window for a new body is an
elevated-vs-flat analogy: pick the elevated/rugged terrain as opaque (drawn), the
low/flat terrain as the window/screen-door. Getting this assignment wrong
(clustering the transparent class on one hemisphere) is why several candidates were
rejected (see "Choosing a new body" below).

### Color as a directional-light cue (axis C — shade)

Shade is a **directional-lighting** term rendered as grayscale *contrast against the
terminal background*. A single light, fixed in screen space, shades each wall by the
Lambert term `N · L` on its surface normal — so the ball reads as a lit sphere in
space (offset highlight, terminator, shadow side) rather than a flat disc. The
*absolute* shade is owned entirely by the engine (not per body/material); a material
carries only its optical properties plus, optionally, a `relief` depth bias (below).
Crucially, **prominence follows opacity, not a separate knob**: the shell walk
(axis B) produces one of three *fragment kinds*, and which one the ray hit selects
the ramp here.

- **Three fragment kinds, three ramps.** The walk already knows how the ray
  stopped, so it picks the ramp:
  - **NEAR-SOLID** — near shell stopped solid (opacity ≥ 1): the prominent front
    surface, **bold** and HIGH-contrast, brightest at centre (`NEAR_SOLID_CONTRAST`).
  - **NEAR-SCREEN** — near shell stopped on a screen-door (0 < opacity < 1): sparse
    texture on the same shell, so it reads dimmer and non-bold (`NEAR_SCREEN_CONTRAST`,
    the old stipple ramp).
  - **FAR** — a deeper shell stopped: the receding back wall, a faint ghost
    (`FAR_CONTRAST`).

  A fully opaque stop is the prominent front; a partial stop is sparse texture so
  it reads dimmer; a far stop recedes — all driven by the one opacity scalar, no
  `kind` field and no per-material ramp.
- **Contrast, not absolute gray.** NEAR-SOLID rides a HIGH-contrast ramp so it
  pops off the background as the prominent face; FAR rides a LOW ramp so it
  recedes toward the background as a faint ghost. The invariant — *foreground =
  far from the background luminance, far side = toward it* — holds on both dark and
  light terminals.
- **Graded by directional light (a lit sphere, both walls).** Each fragment picks a
  ramp band (`Z_LEVELS`) from `ambient + (1 − ambient) · max(0, N · L)`, where `N`
  is the unit surface normal (on a unit sphere, the surface point itself) and `L` a
  fixed light direction (`--light-az`/`--light-el`). Why lighting and not depth:
  distance-from-eye across a sphere's face is `√(1 − r²)` — flat through the middle,
  steep only at the rim — so a depth cue reads as a mostly **flat** disc with a thin
  dark ring. `N · L` instead offsets the highlight and grades across the *whole* face
  to a dark terminator.
  - The **near** wall's normal faces the eye, so a front-ish light lights an offset
    highlight and sweeps a full gradient diagonally across the face to a shadow
    crescent — the disc reads as a genuinely lit ball, no central plateau.
  - The **far** wall's normal faces *away*, so its centre falls into shadow and only
    its limb arc (curving toward the light) lights — the back reads as a lit sphere
    too (a bright crescent → dark), not a flat dim wash.

  `--ambient` floors the shadow side (0 = the terminator falls to pure black, most
  dramatic but the dark side's text goes unreadable; higher keeps it legible). Near
  and far ride different contrast envelopes (`NEAR_SOLID_CONTRAST` bright,
  `FAR_CONTRAST` scaled down since the back is seen through the glass), so the far
  wall stays recessed even where lit; the two are never co-visible in one cell (the
  near occludes), so no front/back cliff shows. The band is fixed per cell (the light
  is fixed in screen space; only the texture rotates), so it is precomputed once
  (`_ShellSample.shade_band`) — the render loop just indexes the ramp, no per-frame
  trig. (A separate *screen-radial* `_Cell.band` survives only to drive the axis-D
  fill dome, which is a screen-radius effect.)
- **Theme decides which end is "background."** `--theme dark|light|auto` (default
  `auto`). On dark, high contrast is bright (toward xterm-256 gray 255); on light
  it is dark (toward 232) — a mirror of the same ramp. `auto` asks the terminal
  for its background via an **OSC 11** query (TTY only, bounded so it can't hang),
  falling back to `$COLORFGBG`, then `dark`. See `detect_theme`.
- **Per-material relief (topography / tone, opt-in).** A `Material` may carry a
  signed `relief` — a shift of that material's shade band *within* the ramp the walk
  chose (negative = recessed/dimmer → sunken, positive = raised/brighter). It is a
  depth bias, **not** a hue and **not** a ramp swap: it nudges where a feature sits
  on the grayscale ramp, so an otherwise flat wall gets relief, but it cannot cross
  contrast envelopes or drop the bold attribute (that is the ramp choice's job).
  Because it is a *shade* shift, relief is **theme-correct** — a positive bias reads
  brighter on a dark terminal and darker on a light one — so it is the right axis for
  a body to encode either **topography** (recessed vs. raised features) or **tone**
  (a class per brightness level, so a continuous albedo becomes a grayscale gradient
  that glyph density could not carry theme-correctly). How aggressively a body uses
  it is a fill-strategy choice — a binary text body may leave it `0`, a tone body may
  ride it hard (see the per-body docs). Applied by clamping `band + relief` into
  `[0, Z_LEVELS-1]` at each draw site, so `relief=0` is the flush baseline.
- **Bold on the near-solid front only** (`--bold-front`, default on) makes it
  advance; NEAR-SCREEN and FAR stay normal-intensity (22) so bold can't bleed
  across a run change. `--no-bold-front` drops the bold (SGR 1) on NEAR-SOLID.
- Escape codes are batched (emitted only on a color-run change, not per glyph)
  to keep frame bytes low enough for smooth animation; quantising the depth band
  into `Z_LEVELS` levels keeps those runs long.

> Both shipped bodies are grayscale, so the ramp is grayscale. A future *hued*
> body (Mars, Jupiter) would keep this depth+theme grading but modulate a tint's
> luminance instead of a neutral gray — the shade ramp is the seam for that.

### Surface-locked glyphs (no flicker)

A feature cell's glyph is keyed to its *geographic* tile, not its screen
position — rotation transports glyphs across the screen, it never re-picks
them. The raw `720×360` data grid is quantized into tiles ~one screen cell in
size; both shells share the same tiling, so far features keep their true shape
while receding in color. Source text lays out in reading order, one latitude
row of text per grid row, wrapping the full 360° of longitude — the trade-off
is curvature (only the head-on band reads as clean text; it bends/compresses
toward the limb).

### Limb fade and word separators

- **Limb fade** (default on) is one of the axis-D density masks (see below): near
  the limb, foreshortening (`z` dropping below `EDGE_FADE = 0.45`) piles many
  surface tiles into one screen cell, which would crush into a solid wall. The
  LIMB mask thins glyphs to true holes there instead, keyed on a stable per-tile
  hash (fine grain) so the fade radius doesn't strobe frame to frame. The keep is
  a **per-cell** value baked from the exact `z` in `_build_cells` (not band-
  quantised) so the horizon dissolves smoothly rather than stepping. `--no-limb-fade`
  omits the mask entirely.
- **Word separators** (default `·`): a literal blank glyph would punch a window
  in an opaque feature, so a *body's* whitespace runs collapse to one visible
  marker glyph instead of vanishing (`load_glyphs`). The screensaver is the
  deliberate exception — its blanks *are* the windows.

### Coordinate convention

A body's `W×H` equirectangular grid: column `0` = longitude `-180°`
(east-increasing), row `0` = latitude `+90°` (north pole, south-increasing). The
renderer maps sphere points directly into this grid — no flips at runtime. `angle
= 0` faces
longitude `0°`.

## Surface tuning — opacity + the density masks (axis D)

This is the authoritative *methodology* (mirrored in `README.md`, which also
carries the exact numeric targets and worked examples — read it before tuning a
body). "Reads as a coherent, see-through, digital sphere" is set by two things:
the per-material **opacity** (axis B — how much of the disc is *drawn* vs.
see-through) and the **density void-masks** (axis D — how the drawn ink is then
thinned to holes, and at what grain). **Each body carries its own tuning** — the
knobs live once in the engine (`Globe.__init__` + the `build_common_parser`
per-body defaults), only the numbers differ, and the *choice* of numbers is a
fill-strategy concern documented in the per-body doc. The methodology is general;
two opposite calibrations bracket it: a **domed** fill (a legible-text body keeps a
dense, readable centre and thins to a rounded rim) versus the **flat identity**
`--fill 1.0 --fill-falloff 0` (a self-filling body — e.g. a tone-mapped crust —
where radial dropout would only re-introduce holes it exists to remove). See
`docs/DESIGN-earth.md` and `docs/DESIGN-moon.md` for the two worked calibrations.

**Coverage (axis B, per material).** A material's `opacity` sets its base draw
rate: `0.0` is a full window, `1.0` a solid feature, and a fraction (e.g. `0.25`) a
screen-door — that fraction of tiles drawn dim, the rest see-through. This is the
old `stipple_fill`, now just the opacity scalar; there is no separate stipple field.

**Void (axis D — a pipeline of masks).** After opacity picks a fragment, the
density masks may thin the drawn ink to a **true hole** (never a see-through — that
is axis B's job). Density is a *pipeline* because limb and fill want genuinely
different grains, and a single dither draw fixes one grain; ink survives iff it
passes every mask. Two default masks:

- **LIMB** — fine grain (per-tile), per-cell keep from the exact `z` (see "Limb
  fade" above).
- **FILL** — coarse grain, per-band keep, shaped by four knobs:
  1. **Fill ratio** — `--fill`, the keep rate at the disc **centre** (the peak) when
     a dome is on, else a flat target. A multiplier on the already-inked disc.
  2. **Fill dome** — `--fill-falloff`. At `0` the keep is flat across the disc, so
     the void reads as a uniform slab over the ball. A non-zero falloff tapers the
     keep from centre to limb, riding the precomputed **screen-radial** band
     (`_Cell.band`) — the dome is a screen-radius effect (the void field rounds
     with the disc), which is why it stays radial while the *shade* moved to true
     per-shell depth (`_ShellSample.shade_band`); the two were one field under the
     old orthographic model. Baked into a per-band `int[Z_LEVELS]` keep array on the
     mask at construction, so the hot loop just indexes it — no per-cell
     arithmetic, no per-frame `sqrt`.
  3. **Void shape** — `--void-scale` (the mask's `block`). At `1`, each tile hashes
     independently → salt-and-pepper specks. At `B`, `B×B` tile blocks toggle
     together → coherent tiled windows, which reads as "hollow shell" not "static."
  4. **Void softening** — `--void-soft` (the mask's `soft`). At `0` a block toggles
     as one crisp square; a non-zero value blends an independent per-tile jitter
     into the block decision, ragging the boundary so windows read as organic
     patches. Each mask (and its jitter) uses its own prime key offsets so it stays
     decorrelated from opacity and the other masks.

Both masks **self-elide when inert**: `--no-limb-fade` omits LIMB, and `--fill 1`
with `--fill-falloff 0` makes FILL's keep all-`1000` (a no-op), so it drops out of
the pipeline rather than costing a hash per cell — the flat, fully-inked path
(pinned by `test_full_flat_fill_ignores_void_knobs`).

Decompose the disc into **front / screen-door / window / void** components (each a
distinct shade, so it's measurable from rendered frames) and target: a dense,
rounded core thinning toward the rim, low isolated-void% (chunky/organic, not
spotty voids), low per-longitude fill variance (no ugly empty face as it spins).
`tmp/`'s calibration scripts (`measure_fill.py`, `decompose_fill.py`,
`morphology.py`, `validate_final.py`) are the tools that measure these.

## Choosing a new body (design criteria)

Not every celestial body is a good fit for this renderer. The bar (from the
Mars/Jupiter/Ganymede roadmap):

- Surface markings must be **mid-scale mottle** — not salt-and-pepper noise,
  not hemisphere-sized slabs.
- Roughly **balanced ~50/50** opaque/gap.
- **Distributed in both latitude and longitude**, so every rotated face shows
  the same fill-and-window character (no "empty face" as it spins).
- Threshold (for continuous-tone source data) is the master knob for ratio +
  granularity, but it **cannot fix bad geography** — a body whose gap naturally
  clusters on one hemisphere (rejected: Moon-like lopsidedness, Earth's Pacific
  "water hemisphere") needs a different body, not a different threshold.
- Near-featureless bodies (Venus, Uranus) don't work at all — there's no
  albedo/terrain signal for the engine's fill read (text or tone) to exploit.

Chosen next bodies and why: **Mars** (mottled dark albedo on bright dust — 2-D
mid patches after threshold calibration), **Jupiter** (latitude bands, the one
body needing added longitudinal turbulence so it doesn't read as flat stripes;
also the only *procedural*, no-embedded-data body), **Ganymede** (light
grooved vs. dark cratered terrain — naturally the cleanest 2-D mottle, least
tuning expected).

## Engine architecture — functional core / imperative shell

There is exactly **one load-bearing seam** in this program:

> **pure computation ┃ effects on the terminal / OS.**

Everything sorts onto one side of it. Pure functions form a DAG (their file layout
is cosmetic); effects form a read → compute → write sequence (splitting them across
files doesn't make layers). So the source is **two modules + apps**, not a
dependency ladder:

- `ascii_sphere.py` — **the functional core**: `Surface`/`Material`/`Globe`, the
  four-axis compositing model (shell walk, three shade ramps, density masks), one
  shared dither primitive, the pure `data/`-blob decoders, PLUS the pure planning
  math — `Config`/`Plan` (value types), `resolve_step`, `disc_radius`, `fit_globe`
  (size injected as a parameter), `center_frame` (size injected), `frame_delay`.
  Stdlib-only; genuinely PURE — touches no terminal state (no argv, no probe/size
  read, no loop) and no filesystem. It keeps only the pure decoders/parsers
  (`unpack_bits`/`unpack_levels`/`glyphs_from_text`) that the shell's file readers
  delegate to; the effectful `open()`/`read()` themselves live in the shell (the
  file-I/O concession the earlier "Phase-1 core" held has been lifted out — see
  "History" below). Declares its own core-only `__all__`.
- `shell.py` — **the imperative shell**: the ONE effectful module, owning every
  kind of effect. Faces are **peers not layers**:
  - a FILESYSTEM face (`source_path`, `load_bits`/`load_levels`, `load_glyphs`,
    `load_source_text`) that reads the runtime assets and hands the bytes/text to
    the core's pure decoders (owns the single `_ROOT_DIR`);
  - an INPUT face (`build_common_parser`, `resolve_glyphs`, `resolve_request`) that
    turns argv + a terminal probe into a pure `Config`;
  - an OUTPUT face (`run_loop`, cbreak input, the `?` overlay, `render_preview`,
    the theme/truecolor probes).
  - `prepare(config, surface)` bridges them: it reads the live terminal size
    (`_term_size` — the single size read in the program), feeds it to the core's
    pure `fit_globe`, builds the resize `rebuild` closure, and returns a `Plan`.
    `auto_radius` is a two-line effectful wrapper: read the size, hand it to the
    core's `disc_radius`.
- `rotating_earth.py` / `rotating_moon.py` / `screensaver.py` — **the composition
  roots** (data + wiring). Each `main()` wires `resolve_request` →
  `prepare(config, make_surface(...))` → its driver. The screensaver is a peer app
  for its own text body, not a process supervisor (see "Terminal lifecycle &
  interactive controls").

Dependency is one-way and acyclic: `ascii_sphere ← shell ← apps`. No package, no
facade, no body registry (nothing picks among bodies).

> **History.** This replaced a longer `ascii_sphere ← terminal ← session ← cli ←
> apps` chain (2026-07-12). `cli` and `terminal` were the same layer (the shell's
> input face vs. output face) drawn as two rungs; `session` was not a layer at all
> — its pure math (`resolve_step`, the disc-sizing formula, the frame delay) was
> core, its one effect (reading the live terminal size in `prepare`) was shell.
> Because it straddled the seam it had to import *outward* into `terminal`
> (`from terminal import fit_globe`) — the dependency inversion that flagged the
> smell. Collapsing to core + shell removed it. (The earlier 2026-07-11 flatten had
> already killed a short-lived 3-submodule `ascii_sphere/` package whose facade
> treated renderer + driver + CLI as co-equal peers.)

The pieces:

- **`Surface`** (`NamedTuple`): a body's identity (`name`/`provenance`, so the
  run-loop footer carries no body-specific literals), grid dimensions, the flat
  `grid: bytearray` of per-cell class codes, and `classes: {code: Material}`.
  Procedural bodies (Jupiter) rasterize `grid` at startup instead of decoding an
  embedded blob; the engine doesn't care which.
- **`Material`** (`NamedTuple`): declares how one class draws — the four flat
  optical properties (`opacity`, `palette`, `hashed`, `relief`) from "The material
  model" above; no `kind`, no stipple sub-group. A body's class table ranges from
  the minimal two-material case (1 opaque + 1 window) to a class-per-tone-level
  many-material case; the count is a fill-strategy choice (per-body docs), not an
  engine one.
- **`Globe`**: precomputes all angle-independent per-cell geometry once
  (`_build_cells` — the sphere never moves in screen space, only the texture
  rotates), then `render(angle)` walks the shell stack per on-disc cell and emits
  a colored frame. Owns the shell stack (axis B), the three shade ramps (axis C),
  and the density-mask pipeline (axis D: LIMB per-cell + FILL per-band, each a
  self-eliding `_Mask` with a `keep_at(cell)` interface). Validates at
  construction that every code in `grid` has a declared `Material` (fail fast at
  startup, not mid-render).
- **Pure planning math** (`ascii_sphere.py`): `Config` (terminal-agnostic render
  config), `Plan` (a prepared, inert spin), and the sizing/pacing helpers
  `disc_radius`/`fit_globe`/`center_frame`/`resolve_step`/`frame_delay`. These are
  core citizens: a value in, a value out. `fit_globe` and `center_frame` take the
  terminal `(rows, cols)` as parameters — the shell reads the live size and injects
  it — so the disc-sizing math (auto radius + `--scale`, the framed-vs-fullscreen
  disc *footprint* kept separate from the Globe's ink `--fill`) and the frame delay
  can be exercised headless. `resolve_step` snaps the per-frame rotation to a whole
  number of glyph tiles so text scrolls as a clean marquee (unconditionally, since
  removing the global `--hash` mode left one tile grid per body). On the near face
  the marquee is *rigid* (2026-07-17): each cell carries a fixed unit-slope tile
  column slot (`_Cell.tx0`, one tile per screen column along a ring) and the class
  is sampled at the tile's own centre, so between two snapped steps every
  front-face glyph — and its drawn/window clipping — translates whole, never
  re-quantized by the spherical cell→tile compression (which used to visibly
  reshuffle sentence characters each step). Deeper shells keep the true spherical
  longitude sampling, so the far ghost stays the foreshortened 3D read.
- **The shell** (`shell.py`): its INPUT face — `build_common_parser`,
  `resolve_glyphs`, `resolve_request` — holds every flag common to all bodies once,
  with per-body defaults passed as kwargs so each body keeps its own tuning (down
  from ~140 lines duplicated across Earth and Moon pre-refactor); `resolve_request`
  probes the terminal for the `auto` knobs and returns a pure `Config`. Its OUTPUT
  face is `run_loop` (live spin with interactive pause/step/quit, full-screen
  toggle, a themed `?` overlay, alt-screen + live resize, and a non-TTY fallback —
  see "Terminal lifecycle & interactive controls"), `render_preview`, and the
  theme/truecolor probes. `prepare(config, surface)` bridges the two faces: it reads
  the live size, calls the core's `fit_globe`, and **returns** a `Plan` — it does
  NOT run or choose the loop. A body's `main()` (composition root) then hands the
  `Plan` to whichever driver it picked, so control flows one way (main → prepare →
  core) and back with data, no callback. The shell imports only `RESET`,
  `gray_escape`, the `Config`/`Plan` types, and the sizing/step/delay helpers from
  the core, so the dependency runs one way (`ascii_sphere ← terminal ← apps`) and
  the core never reaches out for terminal state. `gray_escape` is public (not
  `_`-prefixed) precisely because the shell reuses it for the footer/help chrome;
  the core's own underscore-prefixed internals (`_Cell`, `_hash2`, ...) and the
  shell's (`_help_overlay`, `_query_osc11`, `_term_size`, ...) stay off their
  `__all__`.

### Terminal lifecycle & interactive controls

The live loop grew a full-screen toggle, resize handling, a help overlay, themed
chrome, and clean signal shutdown. Each was added under one guiding rule: **the
engine stays a pure renderer — a lifecycle *policy* lives in the shell (`run_loop`,
gated so it never touches the tested output path) or an app, never in the engine.**
Why each approach was chosen:

- **Screensaver = a peer app that runs the SAME `run_loop`, not a `--screensaver`
  engine flag and not a process supervisor** (`src/screensaver.py`). *(The
  screensaver app was removed 2026-07-13 — repo consolidated to Earth/Moon + the
  web glass ball; this decision record stays because the lifecycle lessons it
  produced — the any-key/kill-clean behavior living in `run_loop`, apps as plain
  composition roots — still govern the engine.)* The only thing
  that makes it "the screensaver" is its body (README text, below) — everything else
  is the one driver every app uses. It starts framed, `f` maximizes it, `q`/Ctrl+C
  quits, exactly like Earth/Moon. The *earliest* design made it an external process
  that shelled out to a body launcher and detached the child's stdin — a whole
  second process, a body-name map, SIGINT plumbing. A 2026-07-11 step replaced that
  with a self-contained app that had its OWN any-key `run_screensaver` driver; the
  later core/shell refactor folded even that away, because "spin, exit cleanly on a
  key or a kill signal" is not screensaver-specific — every long-running body wants
  it. So the any-key/kill-clean behavior moved INTO `run_loop` (below) and the
  screensaver became a plain composition root: `resolve_request` →
  `prepare(config, make_surface(...))` → `run_loop`, no bespoke driver. A future
  body wanting a genuinely different lifecycle (kiosk auto-cycler, record-to-gif,
  benchmark) still can — `prepare` returns an inert `Plan`, and `main()` is free to
  hand it to a different driver — but nothing needs to today.
- **Its body is Earth's structure — one opaque text material, blanks as windows.**
  Earth/Moon are "glass planets" where an opaque feature (land/highlands) sits over
  a transparent class (ocean/maria) that reveals the far shell. The screensaver is
  a uniform ball of README text, so it is ONE opaque (opacity 1), reading-order
  text material — and its **blank tiles are the windows**: a space in a
  reading-order palette is per-tile opacity 0, so the sentence characters draw as
  the bright NEAR-SOLID front feature and every blank is see-through onto the
  hollow interior (blank-behind-blank is a true hole). This needs no special engine
  path — it is exactly the per-tile-opacity rule of the shell walk. The layout
  (`sentence_fill`) lays the README across the sphere sentence by sentence, keeping
  each sentence's original text (a text-fill globe has no land-continuity concept, so
  word spaces stay in as see-through gaps) and separating sentences with wider blank
  runs so the drawn:gap ratio tracks `--stipple` — the golden proportion by default. Because the text rides the bright NEAR-SOLID ramp (not a dim
  screen-door), the screensaver gets the same bold, depth-shaded 3D read as Earth's
  land — the earlier build that routed the text through the dim gap stipple (capped
  at half-brightness, no bold) read as a flat ghost, which
  `test_screensaver_near_face_is_bright_and_bold` now guards against.
- **`run_loop` handles SIGTERM/SIGHUP, not just `try/finally`.** A long-running
  spin is often ended by the multiplexer (tmux `kill-pane`, `kill`, logout), not a
  keypress — and the default disposition for those signals terminates the process
  *past* the `finally`, stranding the terminal in cbreak with a hidden cursor and a
  half-drawn alt-screen. `run_loop` installs handlers that convert them into a
  `_Terminated` exception routed through the same cleanup as `q`/Ctrl+C. This lives
  in the shared loop (not per-app) precisely because it is not screensaver-specific:
  any body left spinning in a pane wants a clean restore. `cbreak_input` still leaves
  ISIG on so Ctrl+C keeps raising `KeyboardInterrupt`; the loop simply catches both.
- **Alt-screen is gated to a live infinite TTY spin** (`sys.stdout.isatty() and
  frames <= 0`). Restore-on-exit (leaving scrollback intact) is what polished
  TUIs do, but it must NOT wrap `--frames N` (inspection/pipe output would be
  erased on exit) or a non-TTY sink. This gating is also *why* these features can
  live in `run_loop` at all: the tests drive `--preview` → `render_preview`, a
  separate path that emits no control codes, and `run_loop`'s output is never
  byte-compared — so alt-screen, resize, and the controls are free to evolve here
  without breaking a test.
- **Resize and full-screen share one `rebuild` closure.** The disc size is frozen
  at `Globe` construction (radius, `cols`/`rows`, and `_build_cells` all computed
  once — deliberately, so the steady-state loop runs no per-frame trig). The only
  way to change size live is therefore to build a *new* `Globe`. Rather than two
  mechanisms, `prepare` puts a single `make_globe(fullscreen=False)` factory on the
  `Plan` as `rebuild`: a SIGWINCH handler just flips a flag (minimal →
  async-signal-safe) and the next frame rebuilds with the current mode; `run_loop`'s
  `f` key calls the same factory with `fullscreen=True`. Since the screensaver runs
  this same `run_loop`, it gets the identical `f` toggle — there is no per-app
  difference here. The whole mechanism is disabled when `--radius` is pinned (the
  footprint is then intentionally fixed, so `rebuild` is `None` and `f` is inert).
  Full-screen picks `fill ≈ 1/HALO_PAD` so the disc fills the binding axis without
  the halo footprint overflowing the screen.
- **ESC = reversible mode-exit; `q` = quit.** Following the browser/vim
  convention, ESC backs out of full-screen and is deliberately a *no-op* when
  already framed, so a stray ESC — or a mis-parsed arrow sequence — never
  disrupts the spin. Binding ESC is only safe because `read_key` already
  disambiguates a bare Escape (returns `"esc"`) from an arrow's `\033[…` sequence
  via a zero-timeout peek; making it a reversible action (not the quit) means a
  rare misread costs nothing.
- **The `?` overlay and footer reuse the depth ramp** rather than plain text. A
  stark default-white panel would read as bolted-on; instead both pull grays from
  the same `_gray_escape` ramp the sphere rides (title/keys at the near-face
  contrast, descriptions like the stipple, rule/hint receding like the far
  shell). They take `globe.theme`/`globe.truecolor` — the engine's
  *already-detected* depth (`detect_truecolor()` / `--color-depth`) — so they
  honor 256-vs-truecolor and dark-vs-light exactly as the body does, with no
  second detection path.

### Data pipeline: file-backed vs. procedural

Two ways a body supplies its `grid`, both body-agnostic to the engine:

1. **File-backed real data**: an offline `tmp/gen_<body>.py` (dataset-sampling libs
   in the dev `.venv`, never in the shipped script) samples a real dataset, packs
   the grid, `zlib`-compresses, and base64-encodes it into a `data/<body>*.b64`
   file. The body names that path as a constant and decodes it via the engine —
   **`load_bits`** for a 1-bit-per-cell boolean mask, or **`load_levels`** for a
   4-bit-per-cell grid (up to 16 class/tone levels, two cells per byte). Both
   resolve the path relative to `__file__`, so the shipped script reads only stdlib
   files and has zero runtime dependencies. The `data/*.b64` files ARE the runtime
   source of truth; `tmp/gen_*` merely regenerates them offline. A body may merge
   several files at startup (e.g. a tone grid with a feature mask overlaid).
2. **Procedural**: the class grid is rasterized as a function of latitude/longitude
   at startup — no data file, no offline generator.

**Which dataset, which packing, and the offline deps are per-body decisions**,
documented in the per-body doc (`docs/DESIGN-earth.md`, `docs/DESIGN-moon.md`), not
here — the only engine-level invariant is that whatever a `tmp/gen_*` script needs
(`numpy`/`Pillow`/`pyshp`/…) stays *out* of the shipped renderer, which reads only
the produced `.b64` via stdlib `zlib`/`base64`, so "zero runtime deps" holds no
matter how heavy the generators get. A body's `W`/`H` constants in its
`rotating_<body>.py` must match its shipped file's dimensions (they are the `w`/`h`
passed to `load_bits`/`load_levels`).

Bit/level unpacking is decode-once at startup, not per-frame: `unpack_bits` expands
the packed bytes through a precomputed 256-entry byte→8-bit table (`_BIT_EXPAND`)
rather than a per-bit shift loop. The property tests cover this indirectly — a wrong
decode would corrupt the grid, breaking the material-model and coverage invariants.

### Regression gate: property tests

`tests/test_render.py` asserts **structural invariants** of the four-axis model
through the public API, running each body's real `--preview` / `Globe.render`
end-to-end (no mocks): determinism/periodicity (`render(angle)` is pure; a full
revolution returns to frame 0), the material model (opacity drives occlusion —
opaque short-circuit fills the disc, pure-window → all-holes, screen-door partial
coverage — and relief is a per-material depth shift), the shell-walk transmittance
(near/far compose as independent Porter-Duff coverage at full far density),
lossless reading-order packing (a window class consumes no character — the text
splits across it, never chops — and an all-opaque surface packs to the identity),
self-consistency (each body renders identically from its implicit vs. explicit
defaults — now including the `far-dim`/`far-fill` values — so a default can't
silently drift; the void knobs are inert at flat full fill), and color
(256-indexed by default, valid 24-bit gray under truecolor).

> **Byte-goldens are intentionally deferred.** The four-axis rewrite changed the
> engine's output by design, and the bodies are re-tuned + re-blessed in a
> separate pass, so the old golden fixtures were dropped rather than chased. When
> the bodies are retuned, re-introduce a golden per body (captured after tmux
> visual sign-off) plus a defaults-unchanged test.

## Adding a new body — checklist

Condensed from `CLAUDE.md` and the roadmap; see those for full detail:

1. If using real data: `tmp/gen_<body>.py` → `data/<body>*.b64` `zlib`+base64
   file(s). Procedural bodies rasterize their grid at startup instead.
2. `rotating_<body>.py` + `ascii-<body>.sh`: name the `data/<body>*.b64` path
   constant(s), write `make_surface()` decoding them via `load_bits` and
   declaring the `Material`s (opacity/palette/hashed/relief per class), `main()`
   calling `build_common_parser` + body-specific flags, then `resolve_request` →
   `prepare` → the driver.
3. Calibrate opacity + fill/void with the `tmp/` tools against the targets above;
   add an explicit defaults-unchanged test like `test_moon_defaults_unchanged`
   (and, once retuned, a re-blessed golden — see "Regression gate").
4. Extend the body table and add a per-body README section (classes + data
   provenance).
5. If the body's **fill strategy** carries design beyond picking `Material` values
   (a new way to fill the disc, non-obvious calibration, a bespoke data pipeline),
   give it a self-contained `docs/DESIGN-<body>.md` like `DESIGN-earth.md` /
   `DESIGN-moon.md`, and point README + this doc's intro at it. A body that is just
   another instance of an existing strategy (e.g. a second text-fill body) needs no
   new doc.

## Open design decisions (not yet settled)

- **Color palette scope**: stay grayscale-only across all bodies (current), or
  give future bodies per-body 256-color hues (Mars ochre, Jupiter tan/red)? The
  engine already supports arbitrary per-class SGR strings — this is a policy
  choice, not an engine limitation.
- **`tmp/calibrate.py`**: not yet generalized from the existing one-off
  prototypes (`measure_fill.py`, `decompose_fill.py`, `morphology.py`,
  `validate_final.py`) into a single tool taking any `Surface` and reporting
  fill%, per-longitude SD, patch-size histogram, and a full-rotation audit —
  planned as the gate for every future body's threshold choice.
