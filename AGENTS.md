# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, opencode, Codex, etc.) when working with code in this repository.

## What this is

**co-asciiball** is a terminal-based renderer of rotating 3D ASCII celestial bodies (and text
balls), written in **pure-Python standard library** — nothing third-party is needed to *run* any
body (bare `python3` works). Each body maps a real surface dataset (or a text source) onto a
hollow, transparent sphere under a finite-eye **perspective** cast, and spins it.

The repo was split out of the `terminal-sphere` monorepo (2026-07-17) to stand alone as the
rendering engine **co** (`~/workspace_genai/co-cli`) consumes as an optional *inspection organ* —
rendering co's local state (memory, context pressure, dream work) as a readable planet in a spare
pane. The renderer itself is body-agnostic and provider-neutral: co supplies the meaning (the
`/asciiball` command + a skill live on co's side), this repo stays a general renderer. See
`docs/KILLER-USE-CASES-free-surface.md` (the co-serving use cases) and
`docs/KILLER-USE-CASES-geo.md` (the geo-data family).

`README.md` is the authoritative reference for every CLI flag and each body's data provenance, and
is *also the default `--glyph-source`* — each body is literally rendered out of its own
documentation, and the tests exercise that default path. `docs/DESIGN-system.md` holds the deeper,
body-agnostic rationale (the four-axis compositing model, the functional-core/imperative-shell
seam, the opacity/fill/void tuning methodology); `docs/DESIGN-earth.md` is the per-body design doc.
Read both before changing render behavior.

Shipped bodies: **Earth** (`src/rotating_earth.py` / `./bin/ascii-earth.sh`) and **Text**
(`src/rotating_text.py` / `./bin/ascii-text.sh`, the source text laid out one sentence per latitude
ring). The Moon body was removed 2026-07-17 (its code + data live in git history).

## Commands

Run from the repo root. The `.sh` launchers prefer the repo's `.venv/bin/python` when present
(resolved relative to their own `bin/` dir) and work from any directory; running the `src/*.py`
files directly is equivalent.

```bash
./bin/ascii-earth.sh                 # spin Earth (Ctrl+C to stop); extra args pass through
./bin/ascii-text.sh                  # spin the README as sentence rings

.venv/bin/pytest tests/ -q           # full test suite
.venv/bin/pytest tests/test_render.py::test_rotation_periodicity   # a single test
.venv/bin/ruff check .               # lint (ruff is the only linter)

python scripts/build_showcase.py     # regenerate docs/showcase.html (the `showcase` skill)
```

**Non-blocking runs (use these from a tool call — never a bare live spin, which blocks until
Ctrl+C):** `--frames N` renders N frames then exits 0; `--preview` prints 3 static frames without
clearing the screen — the same non-TTY path the tests drive.

```bash
python src/rotating_earth.py --preview
python src/rotating_earth.py --frames 1
```

The shipped code is **stdlib-only**. The `.venv` is purely for development (pytest + ruff, plus the
offline data-regen deps `numpy`/`Pillow`/`pyshp`/`global-land-mask` used only by `tmp/gen_*.py`).
There is no committed `pyproject.toml`; set up the dev `.venv` with **uv** (it is gitignored):

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv pytest ruff
git config core.hooksPath .githooks    # enable the ruff pre-commit hook (one-time per clone)
```

## Architecture

The one seam is **pure computation ┃ effects** — a **functional core / imperative shell** split.
It is two modules plus the composition roots; dependency is one-way and acyclic
(`ascii_sphere ← shell ← apps`):

- **`src/ascii_sphere.py` — the functional core (pure renderer + plan).** Stdlib-only, genuinely
  PURE (no filesystem, no terminal state — no argv/probe/size/file reads/loop). Holds:
  - `Surface` / `Material` (NamedTuples) — a body's grid + class codes, and the four flat optical
    properties per class (`opacity`, `palette`, `hashed`, `relief`).
  - `Globe` — precomputes angle-independent per-cell geometry once (`_build_cells`, a finite-eye
    perspective cast, `--eye`), then `render(angle)` runs the four axes: walk the shell stack
    front→back (opacity), pick one of three shade ramps (near-solid / near-screen / far), and apply
    the LIMB + FILL density masks (`--fill`/`--fill-falloff`/`--void-scale`/`--void-soft`).
  - Pure decoders/parsers (`unpack_bits`/`unpack_levels`/`glyphs_from_text`), and the pure plan
    types + sizing math (`Config`/`Plan`, `resolve_step`, `disc_radius`, `fit_globe`,
    `center_frame`, `frame_delay` — the terminal size is *injected*, keeping it headless-testable).
- **`src/shell.py` — the imperative shell (the single effects module).** Everything that touches
  the outside world, on the other side of the seam. Two kinds of effect: **filesystem**
  (`source_path`, `load_bits`/`load_levels`/`load_glyphs`/`load_source_text` — each does the
  open()/read() and delegates decode/parse to the core) and **terminal/OS** (argv via argparse, the
  theme/truecolor probe + size read, the interactive `run_loop`, signals, stdin/stdout). Its INPUT
  face (`build_common_parser`/`resolve_glyphs`/`resolve_request`) and OUTPUT face (`run_loop`,
  `render_preview`) are peers, bridged by `prepare(config, surface, *, reverse=False)` which reads
  the live size and returns a `Plan`. Owns the one `_ROOT_DIR` (repo root, the parent of `src/`) and
  the one `_term_size`.
- **Composition roots** — `src/rotating_earth.py`, `src/rotating_text.py`: name their data file,
  declare their `Material`s, and wire `resolve_request → make_surface(resolve_glyphs(...)) →
  prepare(...) →` the `--preview`/`run_loop` branch. Shared flags live once in `build_common_parser`;
  only per-body defaults (fill/falloff/void tuning) are set per body. Text passes a surface
  *factory* (`radius → Surface`) so its rings re-flow on resize, and `prepare(..., reverse=True)` so
  it reads left-to-right.
- **`bin/ascii-*.sh`** — thin symlink-safe launchers that exec `.venv` python (falling back to
  system `python3`) on the matching `src/rotating_*.py`.

### Runtime data

`data/earth.b64` IS the runtime source of truth — a `zlib`+base64 1-bit land/ocean mask, read by
`shell.load_bits` (anchored to `_ROOT_DIR`) and decoded by the core's `unpack_bits`. It is
*generated* offline by `tmp/gen_earth.py` (which needs `numpy`/`global-land-mask` in `.venv`); regen
recipes are in README's per-body sections.

## Tests (read before changing render output)

`tests/test_render.py` / `tests/test_text.py` are **property / structural**, not byte-golden: they
drive each body's real `--preview` / `Globe.render` end-to-end and assert invariants of the
four-axis model (determinism + rotation periodicity, the material/opacity occlusion model, defaults
self-consistency, rigid front-face marquee translation between snapped steps, and color — 256 by
default, valid 24-bit under truecolor). Run `.venv/bin/pytest tests/ -q`.

> **Byte-goldens are deferred.** When a body is (re)tuned, re-introduce its golden only after a
> **tmux visual sign-off** (ANSI carries the shading; stripped-HTML loses it) plus a
> defaults-unchanged test.

## Conventions

- **Scratch/working files go in `tmp/`** (gitignored) — never the repo root. The offline
  `gen_*.py` / calibration prototypes live there.
- **Longer-form SDLC docs** (design specs, roadmaps, runbooks) live in `docs/`, not the repo root;
  TODO files are `TODO-<YYYYMMDD-HHMM>-<slug>.md`. This AGENTS.md stays focused on
  build/run + architecture.
- **Descriptive names** for domain concepts even in hot loops (`opacity`, not `a`/`alpha`).
- Rebuild `docs/showcase.html` (via the `showcase` skill) after any change to the shade ramps or
  render output; publish it to Cloudflare Pages per `docs/RUNBOOK-pages-publish.md`.

## Adding a new body

Follow `README.md → "Surface tuning — fill ratio & void shape"`. In short: (1) if it uses real
data, add a `tmp/gen_<body>.py` writing a `zlib`+base64 blob to `data/` offline (procedural bodies
rasterize at startup, no `data/` file); (2) add `src/rotating_<body>.py` + `bin/ascii-<body>.sh`
importing `Material`/`Surface` from `ascii_sphere` and everything else from `shell`; (3) calibrate
opacity + fill/void with the `tmp/` tools and assert its tuned defaults; (4) extend the README body
table + add a per-body section; (5) rebuild the showcase. There is no body registry to update.
