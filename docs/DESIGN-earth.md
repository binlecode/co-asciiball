# Design — Earth: the text-fill continents

Earth is the **text-fill** body and the engine's **minimal reference config** (one
opaque material + one window). This doc is its self-contained "why it's built this
way" companion: the design problem (render real continents as a hollow, legible,
spinning sphere) and how it maps onto the body-agnostic engine. See
`README.md → "Earth"` for the per-flag reference + exact provenance/regen commands,
and `docs/DESIGN-system.md` for the four-axis engine this rides on. Earth shares its
*fill strategy* — text — with the screensaver (see the bottom of this doc); the
Moon's is a different strategy (`docs/DESIGN-moon.md`).

## The problem

Render Earth's real land/ocean geography as a hollow, transparent, rotating sphere —
and do it *legibly and literally*: the planet is built out of the characters of its
own documentation, so a reader sees the continents spelled from the README.

## Core idea: text-fill

The disc is filled with **text**, not tone. Land is drawn as **opaque
reading-order text** — the README's characters laid across the surface in latitude
rows, one line of source per grid row wrapping the full 360° of longitude. Each
tile's glyph is fixed for the run and welded to the *surface* tile, so rotation
*transports* the text across the screen (a marquee) and never re-picks it (no
flicker). Ocean is a **pure window** (opacity 0): every ocean cell reveals the far
hemisphere, or a true hole where the far side is ocean too. The mnemonic —
**text = land, blanks = ocean** — is exactly the engine's per-tile-opacity rule,
no special path.

The reading-order index is **lossless** across that window: because ocean is a
window *class* (not a blank glyph), the engine's `_packed_near` index counts only
land tiles, so the README stream advances only where it is drawn. A word cut by a
coastline resumes **intact** on the next land tile — the text *splits* across the
oceans rather than being *chopped* (the earlier behavior dropped whichever glyphs
the ocean happened to cover, shredding the front into unreadable fragments). This
is a strict generalization of the plain `ty·tiles_x + tx` index: the all-land text
ball has no window class, so packing is the identity and its output is unchanged.

**Why text-fill for Earth.** Earth's structure is essentially *binary* (land vs.
water), so there's no continuous tone to map (contrast the Moon's albedo). Text
makes the land legible, and makes the planet literally its own README (the default
`--glyph-source`). A different text source just re-letters the same continents.

## Mapping onto the engine (2 Materials — the minimal window body)

Every class is a plain `Material(opacity, palette, hashed, relief)`. Earth is the
smallest non-trivial body — one opaque feature over one window:

| Class | Real Earth | `Material` | Role |
|---|---|---|---|
| **Land** | continents | `opacity=1`, `palette=`README glyphs, `hashed=False`, `relief=0` | Opaque **NEAR-SOLID** reading-order text — the bright, bold front feature. |
| **Ocean** | seas | `opacity=0` (no palette) | Pure **window** — passes the ray through to the far shell (or a hole). |

That's the whole class table: `{LAND: opacity 1, OCEAN: opacity 0}`. No relief (the
land is a single flush feature), no screen-door, no tone bands — the canonical
two-material case the engine was designed around.

## No dropout — Earth's tuning

Earth ships **`--fill 1.0 --fill-falloff 0 --void-scale 2 --void-soft 0.6`** — no
radial dropout by default. (It formerly shipped a gentle `0.9/0.4` dome; that was
retired 2026-07-17 with the sentence model.)

- **Why no dropout.** The land is legible **sentences**: any fill void punched into
  a sentence lets the background bleed mid-text and shreds legibility. The
  requirement is that a foreground sentence is a hole-free opaque run — only the
  gaps *between* sentences (and the ocean) let the far side show through. The ball
  form comes from the directional-light shading, the limb dissolve, and those windows.
- **The dome is still there for the asking.** Lowering `--fill` by hand re-enables
  the dropout, and `--void-scale 2` + `--void-soft 0.6` keep those thinned cells
  dropping out in small soft-edged clusters (organic patches), not hard `2×2`
  squares — so a hand-thinned rim reads as coherent coastline, not pixel noise.

## Glyph source — the planet from its own docs

The default `--glyph-source` is the repo `README.md`; its characters lay out in
reading order across the surface, so **the planet is rendered out of its own
documentation**. `--glyph-source PATH` swaps in any text file. Whitespace runs
*inside a sentence* collapse to a word-separator glyph (`·` by default) so a literal
blank never punches an accidental window mid-sentence; whitespace **after a sentence
terminator** (`.` `!` `?` `…`) becomes real spaces — per-tile windows, so the gaps
between sentences are the only places the text lets the far shell show through.
(This is one reason `README.md` must stay at the repo root — it is the shipped
default source.)

## Data pipeline

- **`data/earth.b64`** — a **1-bit land mask** (1 = land, 0 = ocean), row-major
  MSB-first, `zlib`+base64. Decoded by the engine's pure `unpack_bits` (via
  `load_bits`). Coordinate convention: `x=0 → longitude −180°` (east-increasing),
  `y=0 → latitude +90°` (south-increasing).
- **Resolution `1440×720` (0.25°).** Fine enough that gulfs, channels, and small
  islands survive (the earlier `720×360` / 0.5° grid dropped them), while the
  point-sampled render stays cheap. `EARTH_W`/`EARTH_H` in `rotating_earth.py` must
  match the shipped file's dimensions (they're the `w`/`h` passed to `load_bits`).
- **Offline gen — `tmp/gen_earth.py W H out.b64`** (dev `.venv` only; the shipped
  renderer reads only the `.b64` via stdlib). Uses `global-land-mask` (a
  Natural-Earth-derived `is_land(lat, lon)` boolean mask at ~1/120° / ~1 km native,
  offline and pip-installable — no shapefile/API step) gridded by `numpy`
  (`meshgrid → is_land → np.packbits`, MSB-first to match `unpack_bits`). Resolution
  is a parameter, bounded only by the ~1 km source.

## Relationship to the screensaver (same fill family)

*(The screensaver was removed 2026-07-13; kept as fill-family rationale — the
text-fill mechanism it proved out is engine-level and body-agnostic.)*

The screensaver was the *other* text-fill body: also one opaque reading-order text
material over windows. The difference is only the **Surface source** — Earth's
windows are geographic (ocean cells from real data); the screensaver's are the
whitespace of the README text laid over a uniform grid — the word spaces plus the
wider blank runs *between sentences* (no embedded data, see `sentence_fill`; a
text-fill globe has no land-continuity concept, so no whitespace is squeezed out, and
the drawn:gap split defaults to the golden proportion). Same engine path, same
NEAR-SOLID bright text; different way of deciding where the windows fall. Text-fill is thus a *family* — geographic
(Earth) and generated (screensaver) — not a one-body trick.

## Tests

- `test_surface_material_model` (Earth part) — asserts the two-material structure:
  opacities `[0.0, 1.0]`, ocean is the window, land is opaque, no relief.
- `test_earth_defaults_unchanged` — pins the shipped defaults (`fill 1.0 /
  fill-falloff 0 / void-scale 2 / void-soft 0.6 / far-dim 0.85 / far-fill 0.5`) so
  they can't silently drift.
- `test_reading_order_packing_is_lossless` — a window-class tile consumes no
  character (the stream splits, never chops); an all-land surface packs to the
  identity, so the text ball is unaffected.
- `test_sentence_marquee_is_step_stable` / `test_earth_land_clipping_is_step_stable`
  — the front-face marquee translates rigidly between snapped steps (no shifting
  characters in a sentence; coastline clipping welded to the tile).
- `test_glyph_source_sentence_gaps_and_word_dots` — word gaps fill with `·`
  (hole-free sentences); only sentence gaps are see-through windows.
- `test_full_flat_fill_ignores_void_knobs` — drives Earth to prove the void knobs
  are inert on the flat, fully-inked path.

## Future

Earth today is a *binary* land/water text-fill. Genuine Earth-specific design worth
adding here (and only here) would be elevation/bathymetry shading (relief bands,
the way the Moon carries albedo), a day/night terminator, or hued oceans — none
exist yet. When one does, it lands in this doc; the engine stays agnostic to it, as
it is agnostic to whether a body fills by text (Earth/screensaver), tone (Moon), or
some future strategy (procedural bodies, dynamic terminal-content displays).
