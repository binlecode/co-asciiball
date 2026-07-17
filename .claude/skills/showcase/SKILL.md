---
name: showcase
description: >-
  Rebuild or update docs/showcase.html, the self-contained visual
  companion to the co-asciiball renderer (real engine frames for Earth on
  dark/light terminals). Use whenever the depth-shading changes
  (the NEAR/FAR/STIPPLE_CONTRAST ramps, Z_LEVELS, the radial-band or limb-taper
  logic in ascii_sphere.py), when a new body is added, or when someone asks to
  regenerate / refresh / restyle the showcase or "design page".
---

# Rebuild the rendering showcase

`docs/showcase.html` is a **generated** artifact — never hand-edit the
HTML. It is produced by `scripts/build_showcase.py`, which imports the real engine
and bodies and bakes the actual rendered ANSI frames in as pre-colored HTML spans
(stdlib-only, no external assets). Each panel bakes in a **full rotation**
(`FRAMES` evenly-spaced angles) and a small block of inline vanilla JS drives a
per-panel slider + play button that scrubs through those frames to simulate the
live spin — the only JS on the page. It is the visual companion to
`docs/DESIGN-system.md` and is linked from `README.md`.

## Regenerate (the common case)

After any change to the shade ramps or render output, rebuild and eyeball it:

```bash
python scripts/build_showcase.py            # writes docs/showcase.html
```

Then verify the output is well-formed (no leaked terminal escapes, panels/frames
present, placeholder replaced):

```bash
python3 - <<'PY'
h = open("docs/showcase.html").read()
assert h.startswith("<!doctype"), "missing doctype"
assert "\x1b" not in h, "raw ANSI escape leaked into HTML"
assert "__PANELS__" not in h, "template placeholder not replaced"
print("panels", h.count('class="panel"'), "frames", h.count('class="frame"'))
PY
```

The page is committed to the repo (unlike the golden `.b64` fixtures it is not
byte-pinned by a test), so **regenerating it is a review checkpoint** the same way
`python tests/test_render.py --update` is: rebuild it in the same change that
alters the shading, and sanity-check the diff looks intended.

## What the page shows / how to change it

Everything is driven by `scripts/build_showcase.py`:

- **Panels** — the `specs` list in `panels()`: `(name, subtitle, ground, Globe)`.
  Add a body by appending a `Globe(<body>.make_surface(...), R, ASPECT, theme=...)`
  row; use ground `"#000"` for a dark-terminal panel and a light hex (e.g.
  `"#f4f4f2"`) for a `--theme light` panel.
- **Frames** — `FRAMES` (how many evenly-spaced angles of one full rotation to
  bake per panel; `ANGLES` is derived from it). More frames = smoother scrub but a
  bigger file (~90 KB/frame/panel). **Render size** — `R`, `ASPECT`, `GLYPHS` at
  the top. Keep them in sync with what the copy claims (the footer prints
  `FRAMES`).
- **Copy** — the `.cues` cards and `.foot` text in the `PAGE` template. If you
  change the shading model (e.g. how the gradient or taper works), update these to
  match `docs/DESIGN-system.md` → "Color as a pure depth cue".
- **Only grayscale is handled.** `gray_rgb()` maps xterm-256 grays (232–255). If a
  future body emits non-gray SGR (a hued planet), extend `gray_rgb` / `frame_html`
  to parse the full 256-color cube, or the frames will render as fallback gray.

## Styling / design changes

The chrome is theme-aware (`prefers-color-scheme` + `:root[data-theme]`), but the
terminal frames keep fixed black/white grounds because each panel simulates a real
terminal. For a substantive visual redesign (not just a data refresh), load the
`artifact-design` skill first to calibrate the treatment, then edit the `PAGE`
template's `<style>` block and regenerate.

## Conventions

Per this repo's layout: the **builder lives in `scripts/`** (committed, reusable —
not `tmp/`, which is for one-off scratch), and its output lives in `docs/`. Keep
the regen recipe in the page footer, `README.md`, and this skill pointing at
`python scripts/build_showcase.py`.
