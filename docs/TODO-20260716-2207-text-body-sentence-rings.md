# TODO — Text body with sentence-ring layout (keep the hollow-ball visual)

Status: PLANNED (impl-ready). Created 2026-07-16. Revised 2026-07-17: §1f
rewritten to reconcile the pre-existing unreproducible "Text ball · PROPOSED"
panel now sitting in `docs/showcase.html` (a rebuild would wipe it). Revised
again 2026-07-17 (pre-impl review): step negation must survive `run_loop`'s
rebuild sites (§1d), `--no-word-sep` pass-through fixed (§1d), §1f widened to
the hand-inserted panels-note + an explicit acceptance-target decision, Moon
references dropped (body removed 2026-07-17).

> **2026-07-17 update — engine groundwork landed, one non-goal overtaken.** The
> step-stable front-face marquee (rigid column lattice + tile-welded class
> sampling), sentence-gap windows in `load_glyphs` (whitespace after `.!?…` →
> real spaces; word gaps → `·`), and Earth's move to `--fill 1.0 --fill-falloff
> 0` shipped ahead of this body. The "No change to Earth output" non-goal below
> is therefore obsolete — Earth's output changed with that work and its tests
> were updated. Everything else here (the sentence-ring layout, `rotating_text`
> body, §1a–§1f) remains planned. Revised again 2026-07-17
(spec pinned by the user): fill:gap is the **golden ratio** (gaps sized
φ·sentence-rings, gaps ONLY between sentences), the sentence cycle **repeats**
to fill the sphere (no blank leftover band), and **rigid marquee** is a named
invariant — a front sentence's characters never drift or re-pick between
rotation steps (§1b, §1d, §1e).

## Goal

A third composition root, **`rotating_text.py`** — the source text displayed
**sentence by sentence** on the existing hollow, transparent, perspective 3D
ball. The ball's visual model (perspective shells, three depth ramps, limb
dissolve, far ghost) is untouched; every change lives in how the reading-order
palette is *laid out* and in two small pure extractions the layout needs.

The display model that falls out of the geometry (and drives the whole design):
**one sentence = one latitude ring, read as a marquee.** A ring holds
`tiles_x ≈ 2π·R·aspect·mag` characters (~430 at R=20) of which ~40–60 are
legible at front-center, so a sentence scrolls past the sharp zone as the ball
spins. Blank gap rings between sentences render as windows (space → per-tile
opacity 0, `ascii_sphere.py:947`), showing the far ghost through the glass —
the hollow read gets *stronger*, not weaker.

Three spec invariants (pinned 2026-07-17):

1. **Text is the only fill.** The input text source covers the sphere; each
   sentence is an unbreakable unit (contiguous rings, no holes inside it — no
   radial dropout, no mid-sentence windows).
2. **Golden-ratio fill:gap, gaps only between sentences.** Ink:hollow ≈ 1:φ —
   each sentence spanning k rings is followed by ~φ·k blank gap rings, and the
   sentence cycle repeats down the sphere so the whole body band holds the
   ratio (no blank leftover band).
3. **Rigid marquee.** A foreground sentence's characters never drift, shimmer,
   or re-pick between rotation steps: the surface advances a whole number of
   glyph tiles per frame (`resolve_step` snaps the step,
   `ascii_sphere.py:1057-1065`), so every glyph moves to the adjacent tile
   intact.

## Non-goals

- No change to Earth output (its tests must pass byte-identical).
- No pagination mode, no base-crust overlay material, no new render axis.
- Phase 1 ships no emphasis/highlight and no rotation pacing (Phases 2–3 below).

## Constraints discovered in review (why the plan has this shape)

1. **Layout is geometry-dependent.** Reading-order wrap width is `tiles_x`
   (`_pick`, `ascii_sphere.py:880`), computed inside `Globe.__init__`
   (`ascii_sphere.py:655-668`) from radius/aspect/eye. So sentence layout can
   only run *after* the disc radius is known, and must re-run on every
   resize/fullscreen rebuild (`Plan.rebuild`). Today `prepare`'s `make_globe`
   closure captures a **fixed** `Surface` (`terminal.py:866`) — the one
   structural change is letting the surface be a factory of the radius.
2. **The natural spin direction reads backwards.** The loop advances
   `angle -= step` (`terminal.py:451`); at a fixed screen cell
   `tx = int((lon+angle+π)/2π · tiles_x)` *decreases*, so reading-order text
   scrolls right — you'd see each sentence in reverse character order. The text
   body must negate the step so text scrolls ticker-style (new characters enter
   from the right, indices increase at a fixed cell).
3. **Poles are unusable for text.** Rings are uniform in colatitude but screen
   rows compress toward the poles (`_sample`, `ascii_sphere.py:792-797`).
   Polar-cap rings get a solid `·` filler so the ball keeps its silhouette
   (all-blank caps would erase the top/bottom of the sphere).
4. **The far wall counter-scrolls the same text, mirrored.** Exactly the case
   `far_dim`/`far_fill` were built for (`ascii_sphere.py:600-613`,
   `terminal.py:833-838` — "A text body can dim + sparsify its far wall").
   No body currently exposes those flags; this body adds them with tuned
   defaults so the back wall is a sparse dotted depth field, not readable
   (mirrored) text.
5. **`load_source_text` already exists for this** (`terminal.py:794`) — it
   returns the source verbatim so "a text body laying the source out with its
   own see-through gaps" can do its own layout. The seam was pre-cut; use it.
6. **The grid can be procedural and trivial.** One class covering the whole
   sphere; the palette does all the work. Grid dims must keep
   `cell_x = W/(2πR·aspect·mag) ≥ 1` so the tile math doesn't clamp
   (`ascii_sphere.py:659`): 1440×720 (Earth-sized) covers radii to R≈66.

---

## Phase 1 — sentence-ring layout (the substance)

### 1a. Core: two pure extractions (`src/ascii_sphere.py`)

**`fit_radius(rows, cols, *, aspect=2.3, scale=1.0, radius=0, fullscreen=False) -> int`**
— extract the radius math currently inline in `fit_globe`
(`ascii_sphere.py:1108-1110`: `disc_fill` pick, `disc_radius`, `scale`,
`max(5, …)`). `fit_globe` calls it; behavior unchanged. Add to `__all__`.

**`tile_grid(W, H, radius, aspect, eye=DEFAULT_EYE) -> TileGrid`**
— extract the tile math from `Globe.__init__` (`ascii_sphere.py:655-668`:
`mag`, `cell_x/cell_y`, `glyph_div_x/y`, `tiles_x/tiles_y`). Returns a public
NamedTuple `TileGrid(tiles_x, tiles_y, div_x, div_y)`; `Globe.__init__` calls
it and assigns its fields (single source of truth — a drifted copy would
misalign layout vs. render). Add `TileGrid` + `tile_grid` to `__all__`.

Self-check after 1a: full test suite byte-identical (pure refactor).

### 1b. Core: sentence segmentation + ring layout (`src/ascii_sphere.py`)

Pure text→palette functions, siblings of `load_glyphs` (text processing already
lives in the core, `ascii_sphere.py:349`). Both in `__all__`.

**`split_sentences(text, min_len=12) -> list[str]`**
- Split on `.`/`!`/`?`/`…` only when followed by whitespace or EOF (keeps
  `e.g.`/`3.14` intact in the common case; this is a display heuristic, not
  NLP — do not grow it).
- Keep the terminator with its sentence; treat blank lines (paragraph breaks)
  as boundaries too.
- Within each sentence: drop non-printables, collapse internal whitespace runs
  to a single space (the layout swaps spaces for `word_sep` later).
- Merge any fragment shorter than `min_len` into the following sentence
  (markdown headers, list markers, stray "1." fragments).
- Never returns empty strings; returns `[]` for empty/whitespace input.

**`layout_rings(sentences, tiles_x, tiles_y, *, word_sep="·", pole_frac=0.15, gap_ratio=GOLDEN) -> RingLayout`**

(`GOLDEN = (1 + 5 ** 0.5) / 2` — a module constant next to the function.)

`RingLayout(palette: str, spans: list, cap_rings: int)` — a public NamedTuple.
`palette` has length **exactly `tiles_x * tiles_y`** (sphere covered exactly
once; the `% len(palette)` in `_pick` becomes the identity — no accidental
modulo wrap: the sentence-cycle repetition below is baked into the palette
*content* deliberately, ring-aligned, never left to the modulo).
`spans` is `[(sentence_index, first_ring, ring_count), …]` — unused in Phase 1
rendering but returned now so Phases 2–3 don't change the signature.

Layout rules:
- `cap = min(round(tiles_y * pole_frac), (tiles_y - 1) // 2)` rings at each
  pole, filled solid with `word_sep` (`·`) — the silhouette-preserving cap.
- Body rings, top to bottom: for each sentence, replace its spaces with
  `word_sep` (no windows *inside* a sentence — mid-sentence holes read as
  noise; **gaps exist only between sentences**), wrap at `tiles_x` across as
  many consecutive rings as needed (k rings), pad the last ring to `tiles_x`
  with **real spaces** (windows), then `max(1, round(gap_ratio * k))`
  all-space gap rings — the golden-ratio hollow: a sentence's gap scales with
  the sentence, ink:hollow ≈ 1:φ across the body band. Every sentence starts
  at tile 0 of a fresh ring — so the ball has a "prime meridian" where all
  sentences begin (Phase 3 exploits this: one dwell per revolution presents
  every sentence's start at front).
- **Repeat the sentence cycle** until the body rings are exhausted: after the
  last sentence (+ its gap), start again from the first. Stop at the last
  whole sentence-plus-gap that fits; only the small remainder (< one
  sentence's rings) is all-space — the sphere is text all the way down, at
  the golden ratio, with no blank leftover band. `spans` records every
  placement (repeats included) so Phases 2–3 see each occurrence.
- If even the first sentence doesn't fit once, hard-truncate it (small radius
  degrades to a one-ring marquee, never crashes).
- `word_sep=""` (from `--no-word-sep`) is honored: words run together, caps
  fall back to `"·"` (a cap must have ink).

### 1c. Shell: surface factory through the fit (`src/ascii_sphere.py` + `src/terminal.py`)

`fit_globe(surface, rows, cols, …)` (`ascii_sphere.py:1082`): after computing
`r` via the new `fit_radius`, add one branch — **if `surface` is callable, call
`surface(r)`** to get the `Surface`, then construct the `Globe` as today.
Still pure (the injected factory is pure). Docstring gains the contract:
`factory(radius) -> Surface`, invoked on every fit, including the resize/
fullscreen rebuild — which is precisely what re-lays-out the rings per size.

`prepare` (`terminal.py:853`) needs **no code change** — `make_globe` already
routes through `fit_globe` on build and rebuild; only its docstring notes the
factory option. (`--radius` pins the footprint → `rebuild=None` → the factory
runs once. Correct: fixed radius = fixed layout.)

### 1d. New body: `src/rotating_text.py` (+ `bin/ascii-text.sh`)

Follows the "Adding a new body" recipe; procedural grid (no `data/` file).

```
GRID_W, GRID_H = 1440, 720          # keeps cell_x ≥ 1 through R ≈ 66
TEXT = 1                            # the one class

def make_surface(palette, provenance):
    return Surface(name="Text", provenance=provenance, W=GRID_W, H=GRID_H,
                   grid=bytearray(b"\x01" * (GRID_W * GRID_H)),
                   classes={TEXT: Material(opacity=1.0, palette=palette, hashed=False)})
```

`main()` wiring (the composition root owns all of this):
- `build_common_parser("Rotating 3D ASCII text ball — the source text, sentence by sentence.",
  body_noun="ball", fill_default=1.0, falloff_default=0.0, void_scale_default=1,
  void_soft_default=0.0)` — **no radial dropout**: punching fill voids into
  sentences destroys legibility; the ball form comes from shade + limb + gaps.
- Body-specific flags (all pass through `resolve_request`'s existing
  `getattr` reads, `terminal.py:837-838`):
  - `--far-dim` float default **0.6**, `--far-fill` float default **0.35** —
    starting points for the tmux tuning pass (see Verification); the far wall
    must read as dotted depth, not mirrored text.
  - `--pole-cap` float default 0.15 → `layout_rings(pole_frac=…)`.
  - `--gap-ratio` float default `GOLDEN` (≈1.618) → `layout_rings(gap_ratio=…)`
    — hollow rings per ink ring between sentences; the golden ratio is the
    spec default, the flag exists only for tuning experiments.
- Sentences: `text = load_source_text(args)`;
  `sentences = [args.glyphs] if args.glyphs else (split_sentences(text) if text else [DEFAULT_GLYPHS])`
  (explicit `--glyphs` = one literal sentence; unreadable source falls back,
  never crashes; guarantees a non-blank palette).
- Surface factory (the Phase-1 payoff — re-layout per fit):

```
def surface_for(radius):
    tg = tile_grid(GRID_W, GRID_H, radius, config.aspect, config.eye)
    layout = layout_rings(sentences, tg.tiles_x, tg.tiles_y,
                          word_sep=args.word_sep,
                          pole_frac=args.pole_cap, gap_ratio=args.gap_ratio)
    return make_surface(layout.palette, provenance)
```

  Pass `args.word_sep` through **unmodified** (no `or "·"` guard): the parser
  already defaults `--word-sep` to `"·"` (`terminal.py:686-694`), and
  `--no-word-sep` sets it to `""` — an `or` would map that explicit request
  back to `"·"`, contradicting §1b. `layout_rings` owns the empty-string cap
  fallback.

- `plan = prepare(config, surface_for)`, then **negate the step** (constraint
  2): `plan = plan._replace(step=-plan.step)` with a comment citing the
  reading-direction rationale. `--preview` / `run_loop` branch as Earth's.
- **Shell prerequisite — the negation must survive rebuilds.** `run_loop`
  reassigns `step = resolve_step(globe)` after every resize and full-screen
  toggle (`terminal.py:360`, `:437`, `:445`); `resolve_step` returns a positive
  step, so the body's negation would silently revert on the first resize or
  `f` press and the text would read backwards again. Fix in `run_loop`, once,
  body-agnostically: preserve the incoming sign at all three sites —
  `step = math.copysign(resolve_step(globe), step)`. Inert for Earth (its step
  is already positive). `render_preview`'s `render(-step * i * …)` needs no
  change — a negated step flips the preview's scroll direction consistently.
- **Rigid marquee comes free — do not break it.** `resolve_step` snaps the
  step to a whole number of glyph tiles (`ascii_sphere.py:1057-1065`) exactly
  so text never drifts across tile boundaries between frames; negating the
  step keeps its magnitude, so the snap survives. Nothing in this body may
  introduce a non-whole-tile angle (no easing, no fractional pacing offsets —
  Phase 3's dwell varies *time*, never the angle).
- `bin/ascii-text.sh`: copy `bin/ascii-earth.sh`, point at `rotating_text.py`.

### 1e. Tests (`tests/test_render.py` or a sibling `tests/test_text.py`)

Property/structural, matching the suite's style (real `--preview` end-to-end,
no goldens). Pin `--glyph-source` to a small fixture file written by the test
(`tmp_path`) with known sentences — never depend on README content.

Pure (headless, no subprocess):
- `split_sentences`: terminators kept; no empties; `min_len` merge; blank-line
  boundary; `e.g. foo` stays one sentence.
- `layout_rings`: `len(palette) == tiles_x * tiles_y` exactly; every sentence
  span starts at a ring boundary (index divisible by `tiles_x`); a k-ring
  sentence is followed by `max(1, round(gap_ratio * k))` all-space gap rings
  (the golden-ratio guard, asserted at the default `gap_ratio`); the sentence
  cycle repeats until fewer than one sentence-plus-gap remains (assert a short
  two-sentence input yields multiple spans of sentence 0 on a tall grid, and
  the trailing all-space remainder is smaller than the smallest
  sentence-plus-gap block); no window (space) tile inside any sentence span's
  ink rings except end-of-ring padding; cap rings are all-`word_sep`;
  over-long input truncates at a whole sentence; degenerate `tiles_y=1`
  returns a valid one-ring layout.
- `tile_grid` == the fields `Globe` exposes for the same inputs (the
  single-source-of-truth guard).

End-to-end (subprocess `--preview`, pinned radius/theme/glyph-source):
- Runs rc 0; two runs byte-identical (determinism).
- `test_text_defaults_unchanged`: implicit defaults == explicit
  `--far-dim 0.6 --far-fill 0.35 --fill 1.0 --fill-falloff 0 --pole-cap 0.15
  --gap-ratio 1.618033988749895` (the drift guard, same pattern as Earth).
- **Rigid-marquee test** (headless `Globe`, no subprocess): render two frames
  exactly one snapped step apart (`resolve_step(globe)`), strip ANSI; in the
  central legible band of the equator row (middle ~40% of columns), frame
  N+1's glyph sequence equals frame N's shifted by exactly one tile — no
  character changes identity except at the band edges. This pins invariant 3
  against float jitter in the tile pick (`tx = int(f * tiles_x)`), the one
  place drift could creep in.
- `--far-dim 0` output differs from default (the far ghost is really there).
- Earth's suite still passes untouched (the 1a/1c refactors are inert; the
  `copysign` change in `run_loop` is inert for positive steps).

### 1f. Docs + companion

- README: body table row + a "Text" section (layout model, flags, the
  reading-direction note, provenance = the glyph source itself). **README is
  the default glyph source — after editing it, rebuild the glassball web page**
  (per CLAUDE.md) and the showcase.
- CLAUDE.md: add the body to the composition-roots list (one line).
- CHANGELOG entry.
- **Showcase — reconcile the existing drift, do NOT just "add a panel."**
  Current on-disk state (discovered 2026-07-17): `docs/showcase.html` already
  carries **two** hand-inserted pieces `scripts/build_showcase.py` does not
  emit (no `text_ball()`, nothing in `panels()`), so both are unreproducible —
  the next `python scripts/build_showcase.py` **silently deletes them**. This
  violates the repo rule that `showcase.html` is a generated artifact:
  - the **"Text ball · PROPOSED"** panel (search `Text ball` — ~line 8859)
    with a hand-authored prototype render, and
  - a **`panels-note` paragraph** (~line 13180) describing that prototype:
    golden-ratio (1:φ) sentence gaps ≈ 38% ink, a custom depth-to-gray tone
    curve + lifted far wall, applied at showcase-build time by
    `tmp/build_showcase_preview.py` — a script that **no longer exists on
    disk** (tmp/ is scratch), so the render can't even be regenerated by hand.

  The fix is part of shipping the body, not an afterthought:
  1. Add a `text_ball()` panel builder to `scripts/build_showcase.py`
     (mirroring `panels()` / `eye_panel()`), capturing **real**
     `rotating_text.py --preview` frames at both color depths, and emitting the
     accompanying note — replacing BOTH hand-authored pieces so the panel
     regenerates like Earth's.
  2. **Acceptance target (decided): the tmux-tuned Phase-1 render, not the
     prototype's pixels.** With the golden-ratio gaps and sentence-cycle
     repetition now IN the spec (§1b), the regenerated panel matches the
     prototype's layout geometry; the remaining accepted deltas are (a) the
     prototype's post-processing tone curve + lifted far wall — the showcase
     rule (like Earth's panels) is real unretouched `--preview` frames, so
     shading comes from the stock ramps tuned via `--far-dim`/`--far-fill`
     only — and (b) the solid polar caps, which the prototype lacks and the
     spec requires (constraint 3). If flag tuning can't reach the prototype's
     hollow-glass read, ship the tuned engine look and note the delta in the
     panel copy rather than reintroducing render-time post-processing.
  3. Decide the `PROPOSED` badge: keep it while the body is behind Earth in
     tuning polish, or drop it once Phase 1 is signed off (tmux gate). Encode
     that choice in the builder, not as a manual HTML edit.
  4. Rebuild via the `showcase` skill and diff — the `Text ball` panel + note
     must now come from the script, and re-running the build must be
     idempotent (no more silent wipe).
  - Until this lands, treat the current `showcase.html` text-ball panel + note
    as throwaway: never hand-edit them further, and expect a rebuild to drop
    them.

### Verification (Phase 1 gate)

- `asciiball/.venv/bin/pytest asciiball/tests/ -q` and
  `asciiball/.venv/bin/ruff check asciiball/`.
- **tmux visual sign-off** (project rule: ANSI carries the shading; never
  judge from stripped output): spin `./asciiball/bin/ascii-text.sh` in a tmux
  pane on dark + light; confirm (a) sentences read left-to-right ticker-style
  at front-center **with zero character wobble frame-to-frame** (pause with
  space, step with →, watch one word cross the center), (b) gaps show the far
  ghost as sparse dots, not mirrored
  words — tune `--far-dim`/`--far-fill` here and re-pin the defaults + the
  drift-guard test, (c) polar caps keep the silhouette, (d) resize re-lays-out
  without artifacts, (e) `f` fullscreen toggle re-lays-out — and after BOTH
  (d) and (e), text still reads left-to-right (the `copysign` guard in §1d:
  a reverted step sign is exactly the regression those rebuilds would cause).

---

## Phase 2 — per-glyph emphasis (current sentence bright, rest dim)

Mechanism (chosen over per-`Material` relief and grid classes, both of which
can't address tile space — see review notes in git history of this doc):

- `Material` gains `emphasis: object = None` — an optional sequence of small
  signed ints parallel to a *reading-order* palette (per-index shade-band
  bias). `_ResolvedMaterial` carries it; the reading-order branch of the
  pick applies `bias = emphasis[idx]` and `render` clamps
  `shade_band + relief + bias` exactly where relief clamps today
  (`ascii_sphere.py:977`). Hashed palettes: unchanged, bias 0.
- `Globe.set_emphasis(code, seq)` — re-bakes one `_ResolvedMaterial`; the one
  sanctioned runtime mutation (cheap: no geometry, no ramps).
- `run_loop` gains an optional `tick(globe, angle)` callback, invoked once per
  frame advance (the timeout, unbound-key, and arrow-step sites). Loop stays
  body-agnostic; default None.
- The text body's tick derives the front-center tile
  `front_tx = int(((angle + π) / 2π) * tiles_x) % tiles_x`; when it wraps past
  the prime meridian (tile 0), advance the current-sentence index and
  `set_emphasis` from `RingLayout.spans` (current span bias 0, others ~−8).

## Phase 3 — read-mode pacing (dwell at the prime meridian)

- `tick` may return a float: extra dwell seconds. The loop uses it as that
  frame's input-wait instead of `delay` (a keypress still interrupts — the
  wait *is* `read_key`'s timeout, so pacing costs no responsiveness).
- Because every sentence starts at tile 0 (Phase 1 layout invariant), one
  dwell per revolution presents every visible sentence's start at
  front-center. Suggested default ~1.5s, flag `--dwell`.

## Risks / accepted limits

- Legibility is confined to the front-center band and degrades toward the limb
  (foreshortening) — inherent to the medium; Phases 2–3 are the mitigation.
- The far wall shows the same text mirrored; at the tuned `far_fill` it's an
  unreadable dot field by design. If tuning can't kill the "backwards words"
  read, fall back to `--far-fill 0` default (front-face only, still a ball via
  shade + limb).
- `split_sentences` heuristics are deliberately naive; README markdown renders
  verbatim (the body draws its own documentation, same philosophy as Earth).
