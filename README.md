# Asciiball

Terminal-based rotating 3D ASCII celestial bodies, written in pure Python
(standard library only). A body maps a real surface dataset onto a sphere and
spins it continuously. It is rendered as a **hollow, transparent shell**:
because a viewing ray pierces the sphere twice you see *both* sides at once — the
near features drawn in high contrast (the prominent front face) and the far
features receding to a faint ghost seen through the shell. The shading is
theme-aware (`--theme`, auto-detected): the front pops off your terminal
background and the far side melts toward it, so the effect works on dark *and*
light terminals. The result is a see-through glass planet.

> 🌍 **See it without installing anything:** open the
> [**rendering showcase**](https://asciiball.pages.dev/) — a self-contained
> page of the actual rendered frames (Earth on dark and light terminals).
> *(Source: [`docs/showcase.html`](docs/showcase.html);
> publishing steps in [`docs/RUNBOOK-pages-publish.md`](docs/RUNBOOK-pages-publish.md).)*

> 🔮 **Glass-ball terminal demo:** a scripted shell session — real frames from
> this engine — playing on a transparent three.js sphere. One self-contained
> file, [`docs/glassball-demo.html`](docs/glassball-demo.html): download it and
> open it in a browser, no server or install (it is also published as a private
> Claude Artifact, shareable on request). Drag to orbit; regenerate with
> `python scripts/build_glassball_demo.py` (build model in
> [`docs/DESIGN-glassball-demo-page.md`](docs/DESIGN-glassball-demo-page.md)).

![The glass-ball terminal demo: Earth spinning inside a transparent sphere, rendered from this repo's own ANSI output](docs/glassball-demo-screenshot.png)

| Body | Script | Launcher | Surface drawn |
|------|--------|----------|---------------|
| **Earth** | `src/rotating_earth.py` | `./bin/ascii-earth.sh` | Continents (text) over see-through ocean |
| **Text** | `src/rotating_text.py` | `./bin/ascii-text.sh` | The source text, one sentence per latitude ring (a ticker on the ball) |

The engine and body module live in `src/`; the shell launcher lives in `bin/`.
The body ships its surface data as a **`zlib`+base64 file under `data/`** at the repo
root (loaded at startup, resolved relative to the repo root) — no runtime
downloads, no image libraries, decoded once in pure Python. It defaults its `--glyph-source` to *this* README, so
the planet is quite literally rendered out of its own documentation.

---

## The shared engine

The engine is body-agnostic; Earth supplies its own embedded data and materials.
This section is the practical summary; see `docs/DESIGN-system.md` for the full
rendering-model rationale and the fill/void tuning methodology, and the
[rendering showcase](https://asciiball.pages.dev/) for a visual companion
(source `docs/showcase.html`, regenerate with
`python scripts/build_showcase.py`; publish with
[`docs/RUNBOOK-pages-publish.md`](docs/RUNBOOK-pages-publish.md)). The showcase's
own design rationale and build/publish model live in
[`docs/DESIGN-showcase-page.md`](docs/DESIGN-showcase-page.md).

### 3D spherical projection

Rendered mathematically, with no external 3D library. Each character cell
inside the unit disc ($x^2+y^2 \le 1$, aspect-corrected for the terminal's
~2:1 character cells) maps to a sphere point at **two depths** sharing the same
screen $(x, y)$: a near point at $z=+\sqrt{1-x^2-y^2}$ and a far point at
$z=-\sqrt{1-x^2-y^2}$. Sampling both is what makes the body transparent. All
per-cell geometry (both base longitudes, plus `z`) is precomputed once in
`_build_cells`; each frame just adds the current rotation angle to those base
longitudes, so no `sqrt`/`asin`/`atan2` runs in the steady-state loop.

### Transparent shell rendering

*   **True perspective projection:** the ray through each screen cell is cast
    from a finite eye (`--eye`, default `2.6` sphere-radii), not straight down the
    axis. So it pierces the near and far walls at **different latitudes** — the two
    layers never line up row-by-row or char-by-char — and the far hemisphere is
    foreshortened into a smaller inset, so the back-wall text reads **smaller**,
    like a receding wall. A large `--eye` flattens back to the old orthographic
    look (near/far aligned, same scale).
*   **Front/back occlusion:** the near shell wins if it's an opaque feature;
    where it's the see-through class (ocean for Earth), the
    far shell shows through; otherwise the cell is empty. How present that far
    wall is has two engine knobs — `far_dim` (its brightness) and `far_fill` (the
    fraction of its tiles drawn, a stable per-tile speckle). Both default to a
    dimmed, thinned ghost (`far_dim 0.85` / `far_fill 0.5`) for **every** body,
    because the far wall is the same near-face ink counter-scrolling behind the
    windows — at full density it competes with the front through any large window
    (Earth's ocean is one), not just a dense text globe. Pass `--far-fill 1` for
    the old dense see-through; either knob at `0` collapses to a front-face-only
    marble.
*   **Directional lighting — a lit sphere, not a flat disc:** shade is grayscale
    *contrast against the terminal background*, graded by a **fixed directional
    light** (the Lambert term `N·L` on each point's surface normal). The ball spins
    under the light like a planet under a fixed sun: a bright highlight sits off
    toward the light, a gradient sweeps across the *whole* face, and a shadow
    terminator falls on the far side. Both walls are lit — the far (back) wall's
    normal faces away, so its centre falls into shadow and only its limb arc lights,
    reading as a real lit cavity. (A distance-from-eye depth cue was tried first; it
    reads as a *flat* disc, because depth across a sphere's face is `√(1−r²)` — flat
    in the middle, steep only at the rim.) Tune it with `--light-az`/`--light-el`
    (light direction) and `--ambient` (shadow-side floor: `0` = pure-black
    terminator, most dramatic; higher keeps the dark side legible). `--theme`
    (default `auto`) picks which end of the ramp is "background" — bright-front on
    a dark terminal, dark-front on a light one. The near shell is also drawn
    **bold** by default (`--no-bold-front` turns it off). Color is owned by the
    engine (the shade ramps in `src/ascii_sphere.py`), not per body.
*   **Surface-locked glyphs, never flicker:** a feature's glyph is keyed to its
    *geographic* tile, not screen position, so rotation transports glyphs
    across the screen instead of re-picking them. Source text lays out in
    reading order, one latitude ring of text per tile row, wrapping the full
    360° of longitude.
*   **Rigid front-face marquee:** the near face maps one tile to one screen
    column along each ring (a fixed column lattice, anchored to longitude 0 at
    the disc centre), and rotation slides the text whole tiles per step — so
    between two steps a sentence just translates, with **no shifting or
    re-quantized characters**, and its land/ocean clipping is welded to the
    tile (whole characters appear or clip, stably). Only the far ghost keeps
    the true spherical (foreshortened) sampling.
*   **Limb fade (default on):** toward the limb, foreshortening piles many
    surface tiles into one screen cell; glyphs thin to blanks there instead of
    crushing into a solid wall, using a stable per-tile hash so the fade radius
    doesn't strobe. Pass `--no-limb-fade` to keep the hard edge.
*   **Word separators (default `·`) & sentence gaps:** a literal blank glyph
    would punch a see-through hole *inside* a sentence, so whitespace runs
    within a sentence collapse to one visible marker glyph — the sentence is a
    hole-free opaque run the background shell can never show through. Whitespace
    **after a sentence terminator** (`.` `!` `?` `…`) becomes real spaces
    instead: per-tile windows, the only places the text lets the far side show.
    Change the word marker with `--word-sep '*'`, or `--no-word-sep` to run
    words together (sentence gaps remain).

### Coordinate convention

Column `0` is longitude `-180°` (increasing eastward); row `0` is latitude `+90°`
(North pole, increasing southward), on an equirectangular grid. The grid
*resolution* is per body (Earth `1440×720` at 0.25°) — the
engine reads the body's `W`/`H`, so the convention is resolution-independent. The
renderer maps sphere points back into the grid directly, so no flips are needed at
runtime. At `angle = 0` the renderer faces longitude `0°`.

### Surface tuning — fill ratio & void shape (every body)

Four independent axes shape a body's "digital, hollow planet" look, and
**each body carries its own geo-specific tuning of them** (Earth's readable
continents want a gentle hand):

* `--fill` — ink density: the keep rate at the disc **centre** (the peak).
* `--fill-falloff` — the radial **dome**: how much that keep rate tapers toward
  the limb, so ink is dense through the middle and thins to sparser windows at
  the rim. `0` = flat (uniform fill everywhere); higher = a rounder ball. This
  rides the same radial band the grayscale depth ramp does, so the *ink density*
  and the *shading* finally agree about where the sphere's volume is — the fix
  for a disc that reads as a flat, uniform field of voids.
* `--void-scale` — void clustering: `N×N` tile blocks toggle together, so voids
  form coherent windows instead of specks.
* `--void-soft` — void-edge softening: raggeds those block edges with a per-tile
  jitter so windows read as organic patches rather than hard `N×N` squares.

Tune all four for a new body; see `docs/DESIGN-system.md` for the full
methodology, decomposition metrics, targets, and calibration tools (in `tmp/`).

> **Note — `--fill` is a multiplier, not an absolute target.** A planet's disc is
> mostly inked before dropout, and with a dome the centre is denser than the rim,
> so actual average fill ≈ `--fill × pre-dropout-ink × (dome average)` — e.g.
> `--fill 0.9 --fill-falloff 0.4` renders a dense core thinning toward the limb.

---

## Earth — continents & ocean

*   **Source:** the [Natural Earth](https://www.naturalearthdata.com/) coastline
    dataset, sampled via the `global-land-mask` package (native ~1/120° ≈ 1 km).
    Each cell of the `1440×720` grid (**0.25°**) is queried for land vs. ocean
    (`1 = land`, `0 = ocean`), including Antarctica. This is 4× the cells of the
    original 0.5° (`720×360`) grid — it traces the coastline ~2.5× more finely, so
    gulfs, channels, and small islands (Aegean, Indonesian, Caribbean, …) that
    fell between the old ~56 km sample points now survive. The payoff scales with
    render size (the disc point-samples one cell per screen cell), so it reads most
    at large radii.
*   **Mapping:** **land** is the drawn feature (the README as reading-order text);
    **ocean** is the see-through gap. Because ocean is a *window class* (not a
    blank in the text), the engine packs the text **losslessly** onto land: the
    stream advances only on land tiles, so a word cut by a coastline resumes
    intact on the next continent — the front reads as continuous sentences that
    *split* across the oceans, never chopped mid-word. Near continents are the
    prominent high-contrast front face, far continents recede to a faint ghost
    seen through the glassy front — the exact shades follow `--theme` (bright-front
    on dark terminals, dark-front on light), graded by the directional light
    (`--light-az`/`--light-el`/`--ambient`) so the disc reads as a lit 3D ball with
    a highlight and a shadow terminator.
*   **Fill (its own tuning):** Earth ships with **no radial dropout**
    (`--fill 1.0 --fill-falloff 0`) — its land is *readable sentences*, and
    punching fill voids into a sentence lets the background bleed mid-text; the
    ball form comes from the depth shading, the limb dissolve, and the
    sentence-gap/ocean windows instead. Lower `--fill` by hand for a thinned,
    speckled crust (`--void-scale 2 --void-soft 0.6` keep that dropout organic
    rather than blocky). The full text-fill design (why text, the calibration,
    the data pipeline) is in `docs/DESIGN-earth.md`; the engine it rides on is
    in `docs/DESIGN-system.md`.
*   **Embedding:** the boolean grid is bit-packed (MSB-first), `zlib`-compressed,
    and base64-encoded into `data/earth.b64` (~16 KB), loaded at startup.

> Regenerating: `uv pip install --python .venv numpy global-land-mask`, then
> `python tmp/gen_earth.py 1440 720 data/earth.b64` (resolution is a CLI arg,
> bounded only by the ~1 km source). Keep `EARTH_W`/`EARTH_H` in
> `src/rotating_earth.py` in sync with the chosen dimensions.

---

## Text — the source, sentence by sentence

*   **Source:** any text file (`--glyph-source`), defaulting to *this* README —
    so, like Earth, the ball is rendered out of its own documentation. Explicit
    `--glyphs "…"` draws one literal sentence instead. There is **no `data/`
    file**: the grid is procedural (one class covering the whole sphere), so the
    palette does all the work.
*   **Mapping — one sentence = one latitude ring.** The text is segmented into
    display sentences (a naive `.!?…`-plus-whitespace heuristic, blank lines as
    boundaries) and each sentence is laid across a ring of
    `tiles_x ≈ 2π·R·aspect·mag` characters, read like a **ticker** as the ball
    spins: only the ~40–60 characters at front-center are legible, so a sentence
    scrolls past the sharp zone and foreshortens toward the limb. Text scrolls
    **left-to-right** (the body negates the engine's natural spin so characters
    enter from the right and read in order), and because the rotation snaps to
    whole glyph tiles per frame the characters translate **rigidly** — no wobble,
    no re-picking (the "rigid marquee").
*   **Golden-ratio gaps, only between sentences.** A sentence spanning `k` rings
    is followed by `round(--gap-ratio · k)` blank gap rings (default the golden
    ratio φ ≈ 1.618), so ink:hollow ≈ 1:φ down the ball. Gaps exist **only
    between** sentences — never inside one (a mid-sentence window would read as
    noise); word gaps fill with the `--word-sep` dot. The sentence cycle
    **repeats** to fill the sphere, so there is no blank leftover band; only a
    small sub-sentence remainder above the bottom cap is empty.
*   **The far wall & poles.** Through each gap the far (back) wall shows the same
    text mirrored and counter-scrolling; the common `--far-dim`/`--far-fill` flags
    dim and sparsify it into a dotted depth field (engine defaults `0.85`/`0.5`)
    rather than readable backwards words — set either to `0` for a front-face-only
    ball. (These are the same body-agnostic knobs Earth rides.) Rows crush
    toward the poles, so `--pole-cap` (default `0.15`) fills that fraction of
    rings at each pole solid to keep the silhouette.
*   **Fill (its own tuning):** like Earth, **no radial dropout**
    (`--fill 1.0 --fill-falloff 0`) — punching fill voids into a sentence destroys
    legibility; the ball form comes from the depth shading, the limb dissolve, the
    between-sentence windows, and the polar caps. The engine it rides on is in
    `docs/DESIGN-system.md`.

> Body-specific flags: `--pole-cap`, `--gap-ratio` (both also in the Options
> table). `--far-dim`/`--far-fill`, `--word-sep`/`--no-word-sep`, and
> `--glyph-source`/`--glyphs` are common flags shared with Earth.

---

## Usage

No dependencies are required to *run* either body (the data-regeneration step is
the only thing that needs extra packages). Launch with the helper script, which
uses the project `.venv` when present and works from any directory:

```bash
./bin/ascii-earth.sh        # spin the Earth
./bin/ascii-text.sh         # spin the source text as a sentence ticker
```

Or run the Python file directly:

```bash
python src/rotating_earth.py
```

Press `Ctrl+C` to stop. Extra arguments pass through the launcher.

### Live controls

In an interactive terminal the body takes keyboard input while it runs:

| Key | Action |
|-----|--------|
| `space` | Pause / resume the spin. |
| `→` | Step one tile forward (in the natural spin direction) and pause. |
| `←` | Step one tile backward and pause. |
| `q` | Quit (so does `Ctrl+C`). |

Stepping is by a whole glyph tile, the same unit the auto-spin advances each
frame. While paused the process blocks on input rather than busy-looping, so a
still body uses no CPU. Controls only activate on a real TTY — piped output or
`--frames` in a script runs the plain spin unchanged. (Requires a POSIX
terminal; elsewhere it falls back to the non-interactive spin.)

### Options

**The transparent shell needs a 256-color terminal** (it uses grayscale escapes).
The flags below are the body's controls:

| Flag | Default | Description |
|------|---------|-------------|
| `--bold-front` / `--no-bold-front` | bold | Draw the near hemisphere in bold so it advances against the dimmer far side. |
| `--eye DIST` | `2.6` | Perspective eye distance in sphere-radii (must be `> 1`). The render is a true **perspective** projection: the ray through each cell pierces the near and far walls at different latitudes (so the two layers never line up row-by-row) and the far wall is foreshortened **smaller**, like a receding back wall. Lower = stronger perspective; a large value (e.g. `100`) flattens to a near-orthographic look. |
| `--theme auto\|dark\|light` | `auto` | Terminal background the depth shading is tuned against: the near (front) face is drawn to contrast with it, the far side recedes toward it. `auto` queries the terminal (OSC 11), falling back to `$COLORFGBG`, then `dark`. Set it explicitly if auto-detection guesses wrong. |
| `--color-depth auto\|truecolor\|256` | `auto` | Grayscale resolution of the depth gradient. `auto` emits 24-bit color when the terminal advertises it (`$COLORTERM=truecolor`/`24bit` and a live TTY) for a smoother ramp — the far shell alone jumps from ~3 to ~27 distinct grays — else the 256-color ramp. Force with `truecolor`/`256`. Non-TTY runs (pipes, `--preview` under the tests) always stay 256-color, so redirected output is deterministic. |
| `--glyphs CHARS` | — | Explicit string of characters to draw features with (overrides `--glyph-source`). |
| `--glyph-source PATH` | bundled `README.md` | Text file whose characters are drawn across the surface (whitespace stripped, otherwise kept verbatim and in order). Falls back to the built-in dense set if unreadable. |
| `--word-sep [CHAR]` / `--no-word-sep` | `·` | Glyph placed between words *inside a sentence* so the text reads hole-free. Gaps **after sentence terminators** become real spaces (see-through windows) regardless. `--no-word-sep` runs words together. |
| `--limb-fade` / `--no-limb-fade` | on | Thin the text to blanks toward the limb so the rim dissolves into a clean horizon. |
| `--fill FRAC` | Earth `1.0` | Fraction of resolved glyphs kept at the disc **centre** (the peak); `--fill-falloff` tapers it toward the limb. The rest are thinned to true voids (blanked, not see-through). A multiplier on the already-inked disc. Earth defaults to `1.0` (no dropout) so sentences stay hole-free; lower it for a thinned crust. |
| `--fill-falloff FRAC` | Earth `0` | Radial **dome**: how much `--fill` tapers from the disc centre to the limb, so ink is dense through the middle and thins to sparser windows at the rim (the void field rounds with the ball). `0` = flat/off (uniform fill); e.g. `0.5` = the limb keeps half the centre rate. |
| `--void-scale N` | Earth `2` | Block size for the `--fill` dropout: `N×N` surface-tile blocks toggle together, so the void forms coherent tiled windows (digital, hollow shell) instead of specks. `1` = per-tile speckle; higher = bigger, blockier windows. |
| `--void-soft FRAC` | Earth `0.6` | Softening of the `--void-scale` block edges: blends a per-tile jitter into the block dropout so windows read as organic patches rather than hard `N×N` squares. `0` = crisp blocks; `1` = full per-tile speckle. |
| `--far-dim FRAC` | `0.85` | Contrast of the far (back) wall seen through the glass. Lower = dimmer ghost; `0` drops the back wall (front-face only). The far ramp is capped well below the near face, so even `1.0` stays a ghost, not a competing surface. |
| `--far-fill FRAC` | `0.5` | Fraction of the far wall's tiles kept, thinning its counter-scrolling texture into a sparse dotted depth field rather than a dense second surface fighting the front. The far wall is the same near-face ink counter-scrolling behind the windows, so this matters for any large window (Earth's ocean too), not just text. Above ~`0.6` the back reads as a competing (mirrored) surface; `--far-fill 1` restores the old dense see-through; `0` drops the back wall. |
| `--light-az DEG` | `135` | Direction of the fixed light, in degrees: `0` = from the right, `+90` = from straight above, `180` = from the left. Sets where the highlight sits and which way the shadow terminator falls. |
| `--light-el DEG` | `50` | Light elevation toward the viewer, in degrees: `0` = pure side light (a thin lit crescent, strong terminator across the face), `90` = head-on (lights the whole front, terminator pushed to the limb). The default `50` reads as a rounded lit ball (highlight offset up-left, gentle terminator); lower it toward the dramatic side-lit crescent, raise it toward front-lit. |
| `--ambient FRAC` | `0.12` | Shadow-side floor (0–1): `0` = the terminator falls to pure black (most dramatic, but the dark side's text/features go unreadable); higher lifts the shadow so it stays legible. |
| `--pole-cap FRAC` | Text `0.15` | *(Text body)* Fraction of rings at **each** pole filled solid (`--word-sep`) so the silhouette survives where rows crush toward the poles. |
| `--gap-ratio RATIO` | Text `φ ≈ 1.618` | *(Text body)* Blank gap rings per ink ring between sentences: a `k`-ring sentence is followed by `round(RATIO·k)` windows, so ink:hollow ≈ 1:φ. |
| `--radius N` | auto | Body radius in rows (`0` = auto-size to ~60% of the terminal, centred with margin). |
| `--scale F` | `1.0` | Scale factor on the radius (`1.2` = larger, `0.75` = smaller). |
| `--aspect F` | `2.3` | Font cell height/width ratio. **Lower it if the body looks too wide, raise it if it looks like a tall egg.** Most terminals land around `2.0`–`2.3`. |
| `--speed RATIO` | `1.0` | Rotation speed as a ratio of the default (`2` = twice as fast, `0.5` = half). |
| `--fps F` | `18` | Target frames per second. |
| `--frames N` | `0` | Render `N` frames then exit (`0` = until `Ctrl+C`). |
| `--preview` | off | Render 3 static frames with separators (no screen clear). |

Examples:

```bash
./bin/ascii-earth.sh --speed 2                   # double-speed Earth
./bin/ascii-earth.sh --theme light               # tune shading for a light terminal
./bin/ascii-earth.sh --no-bold-front             # flat (non-bold) near side
./bin/ascii-earth.sh --fill 0.85 --fill-falloff 0.4  # domed, thinned crust (dropout back on)
./bin/ascii-earth.sh --fill 0.9 --fill-falloff 0.7   # steeper dome — denser core, sparser rim
./bin/ascii-earth.sh --void-scale 5 --void-soft 0    # bigger, crisp-edged hollow windows
./bin/ascii-earth.sh --glyph-source notes.txt    # render a body out of any text
python src/rotating_earth.py --preview           # static frames for inspection
./bin/ascii-text.sh                              # spin the README as a sentence ticker
./bin/ascii-text.sh --glyph-source notes.txt     # read your own text off the ball
./bin/ascii-text.sh --gap-ratio 1 --far-dim 0    # tighter gaps, front-face only
```
