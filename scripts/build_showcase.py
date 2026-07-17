#!/usr/bin/env python3
"""Build docs/showcase.html -- the visual companion to
docs/DESIGN-system.md.

The page opens on a live cover hero -- an ambient, auto-spinning flagship Earth --
then renders the real engine output (theme-aware depth shading: the radial gradient
+ limb-tapered front/back gap) for Earth on a dark terminal and Earth on a light
terminal, baking a full rotation of each in as pre-colored HTML spans and writing
one standalone file (no external assets; a little inline vanilla JS drives the hero
spin plus the per-panel rotation slider / play button).

Stdlib-only, like the renderers themselves -- it imports the engine and the body
modules from the repo root. Regenerate after any change to the shade ramps:

    python scripts/build_showcase.py

Chrome follows the browser's light/dark preference; each terminal frame keeps its
own black/white ground since the panel simulates a real terminal.
"""

import math
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from ascii_sphere import (  # noqa: E402
    DEFAULT_EYE,
    GOLDEN,
    Globe,
    layout_rings,
    split_sentences,
    tile_grid,
)
from shell import (  # noqa: E402
    load_source_text,
    source_path,
    build_common_parser,
    resolve_glyphs,
)
import rotating_earth as earth  # noqa: E402
import rotating_text as text  # noqa: E402

R, ASPECT = 20, 2.3
# One full rotation, sampled at evenly-spaced angles. Rotation is periodic in
# 2*pi (see test_rotation_periodicity), so frame N wraps seamlessly to 0 --
# the per-panel slider/play scrubs through these to simulate the live spin. The
# angle is *negated* so advancing frames matches the live loop's direction
# (run_loop steps `angle = (angle - step) % 2*pi` in steady state).
FRAMES = 48
ANGLES = [-i / FRAMES * 2.0 * math.pi for i in range(FRAMES)]
SGR = re.compile(r"\033\[([0-9;]*)m")


def _version():
    """Nearest git tag (e.g. v0.1.1), the version footer's source of truth."""
    try:
        return subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "dev"


def _glyphs():
    """The real CLI default: no --glyphs/--glyph-source, so this falls through to
    the bundled README.md (see resolve_glyphs) -- the same text a user actually
    sees, not a short pinned string that would tile visibly across a large
    contiguous surface."""
    args = build_common_parser(
        description="showcase", fill_default=1.0, fill_help="f"
    ).parse_args(["--radius", str(R), "--aspect", str(ASPECT)])
    return resolve_glyphs(args)


def gray_rgb(idx):
    """xterm-256 grayscale index -> #rrggbb (the engine only emits grays)."""
    v = 8 + (idx - 232) * 10 if 232 <= idx <= 255 else 128
    return f"#{v:02x}{v:02x}{v:02x}"


def sgr_color(params):
    """Resolve an SGR parameter string to a CSS color, or None if it sets none.

    Handles both grayscale forms the engine emits: 256-indexed (``38;5;N``) and
    24-bit truecolor (``38;2;r;g;b``, from --color-depth truecolor). Truecolor is
    checked first so a 24-bit run isn't misread as an index."""
    mm = re.search(r"38;2;(\d+);(\d+);(\d+)", params)
    if mm:
        r, g, b = (int(mm.group(k)) for k in (1, 2, 3))
        return f"#{r:02x}{g:02x}{b:02x}"
    mm = re.search(r"38;5;(\d+)", params)
    if mm:
        return gray_rgb(int(mm.group(1)))
    return None


def esc(ch):
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(ch, ch)


def frame_html(text):
    """Convert one ANSI frame (grayscale 38;5;N or 38;2;r;g;b + bold/normal) to
    HTML spans, coalescing runs of identical color the way the engine coalesces
    escapes."""
    out = []
    for line in text.split("\n"):
        spans, i, color, bold, pending = [], 0, None, False, []

        def flush():
            if not pending:
                return
            if color is None:
                spans.append("".join(pending))
            else:
                weight = "font-weight:700;" if bold else ""
                spans.append(
                    f'<span style="color:{color};{weight}">{"".join(pending)}</span>'
                )

        for m in SGR.finditer(line):
            for ch in line[i : m.start()]:
                pending.append(esc(ch))
            i = m.end()
            flush()
            pending = []
            params = m.group(1)
            if params in ("0", ""):
                color, bold = None, False
            else:
                pad = ";" + params + ";"
                if ";1;" in pad:
                    bold = True
                if ";22;" in pad:
                    bold = False
                resolved = sgr_color(params)
                if resolved is not None:
                    color = resolved
        for ch in line[i:]:
            pending.append(esc(ch))
        flush()
        out.append("".join(spans))
    return "\n".join(out)


# Earth's shipped geo-specific fill/dome/void tuning, mirrored from its CLI
# defaults (build_common_parser kwargs in rotating_earth.py's main) so the
# showcase renders the real shipped look -- Earth domes its legible-text land
# toward the limb.
EARTH_TUNING = dict(
    fill=0.9,
    fill_falloff=0.4,
    void_scale=2,
    void_soft=0.6,
    # Mirror Earth's shipped far-wall defaults (rotating_earth.py main): a brighter,
    # denser back wall so the far hemisphere reads as an edge->centre depth cavity.
    far_dim=1.0,
    far_fill=0.85,
)


def _stack(globe, angles=ANGLES):
    """One rotation of `globe` as stacked <pre> frames (frame 0 active).

    `angles` defaults to the panels' full `ANGLES`; the ambient hero passes its own
    `HERO_ANGLES` (a different count, tuned for its fixed-tick spin speed)."""
    return "".join(
        f'<pre class="frame{" active" if i == 0 else ""}">'
        f"{frame_html(globe.render(a))}</pre>"
        for i, a in enumerate(angles)
    )


DEPTHS = ((False, "256-color"), (True, "24-bit truecolor"))

# The perspective panel renders the transparent README text globe (where near AND
# far walls both show, so the effect is most legible) at three eye distances. A
# smaller radius than the body panels so three panes fit side by side. The eye
# distance is the ONLY thing that differs across the three.
EYE_R, EYE_ASPECT = 13, 2.3
EYE_SPECS = (
    (100.0, "--eye ∞", "orthographic · the old flat look"),
    (2.6, "--eye 2.6", "default · moderate depth"),
    (2.0, "--eye 2.0", "strong perspective"),
)


def _controls():
    """The shared play / scrub / speed control row (identical across panels)."""
    speeds = "".join(
        f'<button type="button" data-speed="{s}"'
        f"{' class="active"' if s == '1' else ''}>{s}&#215;</button>"
        for s in ("1", "0.5", "0.25")
    )
    return (
        '<div class="controls">'
        '<button class="play" type="button" aria-label="Play rotation">&#9654;</button>'
        f'<input class="scrub" type="range" min="0" max="{FRAMES - 1}" '
        'value="0" step="1" aria-label="Rotation frame">'
        f'<span class="counter">01<span class="sep">/</span>{FRAMES:02d}</span>'
        f'<div class="speed" role="group" aria-label="Playback speed">{speeds}</div>'
        "</div>"
    )


def eye_panel():
    """A single panel with three side-by-side panes -- the SAME transparent globe
    at eye = infinity / 2.6 / 2.0 -- driven by one shared control row. (Earth's
    text surface; this panel used the removed screensaver's README globe before.)"""
    surface = earth.make_surface(_glyphs())
    panes = "".join(
        f'<div class="pane"><span class="plabel">{label}</span>'
        f'<div class="stack">'
        f"{_stack(Globe(surface, EYE_R, EYE_ASPECT, theme='dark', truecolor=True, eye=eye, fill=1.0, fill_falloff=0.0))}"
        f'</div><span class="psub">{sub}</span></div>'
        for eye, label, sub in EYE_SPECS
    )
    return (
        '<section class="panel eyes"><header class="ph">'
        "<h2>Perspective — the <code>--eye</code> knob</h2>"
        "<p>same Earth globe · eye distance in sphere-radii</p></header>"
        f'<div class="viewer twin" style="background:#000;">{panes}</div>'
        f"{_controls()}</section>"
    )


def panels():
    gl = _glyphs()
    # (name, subtitle, ground, surface, theme, tuning) -- each view is rendered at
    # BOTH color depths into twin panes, so the 256 fallback and the auto-detected
    # 24-bit ramp spin side by side off the identical geometry.
    specs = [
        (
            "Earth",
            "dark terminal · shipped default",
            "#000",
            earth.make_surface(gl),
            "dark",
            EARTH_TUNING,
        ),
        (
            "Earth",
            "light terminal · <code>--theme light</code>",
            "#f4f4f2",
            earth.make_surface(gl),
            "light",
            EARTH_TUNING,
        ),
    ]
    out = []
    for name, sub, ground, surface, theme, tuning in specs:
        panes = "".join(
            f'<div class="pane"><span class="plabel">{label}</span>'
            f'<div class="stack">'
            f"{_stack(Globe(surface, R, ASPECT, theme=theme, truecolor=tc, **tuning))}"
            f"</div></div>"
            for tc, label in DEPTHS
        )
        out.append(
            f'<section class="panel"><header class="ph">'
            f"<h2>{name}</h2><p>{sub}</p></header>"
            f'<div class="viewer twin" style="background:{ground};">{panes}</div>'
            f"{_controls()}</section>"
        )
    return "\n".join(out)


# The Text body's shipped defaults (rotating_text.py's main): the far wall dims +
# sparsifies into a dotted depth field, no radial dropout, golden-ratio gaps, and
# a 0.15 polar cap -- so the panel is the real unretouched engine look (stock
# ramps, no build-time post-processing), same rule as Earth's panels.
TEXT_TUNING = dict(far_dim=0.85, far_fill=0.5, fill=1.0, fill_falloff=0.0)
TEXT_POLE_CAP, TEXT_GAP_RATIO = 0.15, GOLDEN


def _text_surface(radius, aspect=ASPECT, eye=DEFAULT_EYE):
    """The Text body's surface at `radius`: segment the bundled README into
    sentences and lay them out as rings against the SAME tile grid the Globe will
    sample (`tile_grid`, so layout and render never drift). Mirrors the body's own
    `surface_for` factory."""
    args = build_common_parser(
        description="showcase", fill_default=1.0, fill_help="f"
    ).parse_args(["--radius", str(radius), "--aspect", str(aspect)])
    src = load_source_text(source_path(args.glyph_source))
    sentences = (split_sentences(src) if src else None) or [_glyphs()]
    tg = tile_grid(text.GRID_W, text.GRID_H, radius, aspect, eye)
    layout = layout_rings(
        sentences,
        tg.tiles_x,
        tg.tiles_y,
        pole_frac=TEXT_POLE_CAP,
        gap_ratio=TEXT_GAP_RATIO,
    )
    return text.make_surface(layout.palette, "bundled README.md")


def text_ball():
    """The Text body panel -- the README laid out one sentence per latitude ring,
    twinned at both color depths (like Earth). Real `rotating_text` frames off the
    ring layout; the far wall reads as a dotted depth field through the gaps."""
    surface = _text_surface(R)
    panes = "".join(
        f'<div class="pane"><span class="plabel">{label}</span>'
        f'<div class="stack">'
        f"{_stack(Globe(surface, R, ASPECT, theme='dark', truecolor=tc, **TEXT_TUNING))}"
        f"</div></div>"
        for tc, label in DEPTHS
    )
    return (
        '<section class="panel"><header class="ph">'
        "<h2>Text — sentence rings</h2>"
        "<p>dark terminal · the README, one sentence per ring</p></header>"
        f'<div class="viewer twin" style="background:#000;">{panes}</div>'
        f"{_controls()}</section>"
    )


def _distinct_lumas(frame):
    """Count distinct gray luminances in one baked frame (both SGR forms)."""
    tc = {m for m in re.findall(r"38;2;(\d+);\d+;\d+", frame)}
    idx = {m for m in re.findall(r"38;5;(\d+)", frame)}
    return len(tc or idx)


def depth_gain():
    """(256-grays, truecolor-grays) in one representative Earth frame, for the copy
    -- computed at build time so the quoted numbers can never go stale."""
    gl = _glyphs()
    surface = earth.make_surface(gl)
    angle = ANGLES[FRAMES // 3]
    n256 = _distinct_lumas(
        Globe(surface, R, ASPECT, theme="dark", truecolor=False, **EARTH_TUNING).render(
            angle
        )
    )
    ntc = _distinct_lumas(
        Globe(surface, R, ASPECT, theme="dark", truecolor=True, **EARTH_TUNING).render(
            angle
        )
    )
    return n256, ntc


# The cover hero bakes its own rotation, denser than the panels' FRAMES. The
# ambient spin advances one baked frame per fixed 90ms tick (see the hero JS), so
# the frame count alone sets the angular speed: at 64 frames a full revolution
# takes 64*90ms = 5760ms -- twice as smooth AND half the angular speed of the
# earlier 32-frame loop (32*90ms = 2880ms), in one knob.
HERO_FRAMES = 64
HERO_ANGLES = [-i / HERO_FRAMES * 2.0 * math.pi for i in range(HERO_FRAMES)]
# A touch smaller radius than the panels (R): fewer glyph columns (~94 vs ~105)
# means the centerpiece can be set at a larger font and still fit its column
# without clipping. The CSS font ramp in .hero-globe .frame is sized to this width.
HERO_R = 18


def hero_globe():
    """The cover centerpiece: one seamless rotation of the flagship Earth (24-bit,
    dark ground), baked as an auto-spinning stack. Mostly ambient -- unlike the
    instructive twin panels it carries only a minimal 1x/0.5x speed toggle (1x is
    the shipped 64-frame/90ms tick; 0.5x doubles the tick to 180ms) and click-to-
    pause. Real engine frames, the SAME tuning as the Earth panel, just sampled at
    HERO_ANGLES. Earth's ocean cells are windows (opacity 0), so the near oceans
    already reveal the far continents -- the 'hollow glass planet' of the headline,
    spinning on its own."""
    surface = earth.make_surface(_glyphs())
    stack = _stack(
        Globe(surface, HERO_R, ASPECT, theme="dark", truecolor=True, **EARTH_TUNING),
        HERO_ANGLES,
    )
    return (
        '<figure class="hero-globe" id="heroGlobe"'
        ' title="Real engine output — click to pause">'
        f'<div class="stack">{stack}</div>'
        "<figcaption>real engine output · Earth · 24-bit truecolor</figcaption>"
        '<div class="speed hero-speed" role="group" aria-label="Spin speed">'
        '<button type="button" data-mult="1" class="active">1&#215;</button>'
        '<button type="button" data-mult="0.5">0.5&#215;</button>'
        "</div>"
        "</figure>"
    )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Asciiball — rendering showcase</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>%F0%9F%AA%90</text></svg>">
<style>
  :root{
    color-scheme:light dark;
    --ground:#f7f8f9; --panel:#ffffff; --edge:#e2e6ea; --strip:#0b0d10;
    --ink:#1c2126; --dim:#5b6570; --accent:#0e7c8b;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
    --sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  @media (prefers-color-scheme: dark){
    :root{ --ground:#0a0b0d; --panel:#101318; --edge:#1e242c; --strip:#050608;
      --ink:#c9d3d9; --dim:#83909c; --accent:#5ec8d8; }
  }
  :root[data-theme="light"]{ --ground:#f7f8f9; --panel:#fff; --edge:#e2e6ea;
    --strip:#0b0d10; --ink:#1c2126; --dim:#5b6570; --accent:#0e7c8b; }
  :root[data-theme="dark"]{ --ground:#0a0b0d; --panel:#101318; --edge:#1e242c;
    --strip:#050608; --ink:#c9d3d9; --dim:#83909c; --accent:#5ec8d8; }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
    line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden;
    padding:clamp(24px,5vw,64px) clamp(18px,4vw,56px);}
  /* Faint cool "void" glow behind the content -- a starless nebula wash that
     gives the page depth without touching the baked terminal frames. */
  body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
    background:
      radial-gradient(120% 80% at 82% -10%, rgba(94,200,216,.10), transparent 55%),
      radial-gradient(90% 70% at 8% 4%, rgba(94,200,216,.06), transparent 55%);}
  .wrap{position:relative;z-index:1;max-width:1080px;margin:0 auto;}
  .topline{display:flex;align-items:center;justify-content:space-between;gap:16px;
    margin-bottom:16px;}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.22em;
    text-transform:uppercase;color:var(--accent);margin:0;}
  .theme-toggle{flex:none;font-family:var(--mono);font-size:12px;letter-spacing:.04em;
    color:var(--dim);background:var(--panel);border:1px solid var(--edge);
    padding:7px 12px;border-radius:999px;cursor:pointer;
    transition:color .2s,border-color .2s;}
  .theme-toggle:hover{color:var(--ink);border-color:var(--accent);}
  .theme-toggle:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  h1{font-size:clamp(28px,4vw,44px);line-height:1.08;margin:0 0 18px;
    font-weight:680;letter-spacing:-.015em;text-wrap:balance;}
  .lede{max-width:64ch;color:var(--dim);font-size:17px;margin:0 0 6px;}
  a{color:var(--accent);}
  .cues{list-style:none;padding:0;margin:28px 0 8px;display:grid;gap:14px;
    grid-template-columns:repeat(auto-fit,minmax(240px,1fr));}
  .cues li{border:1px solid var(--edge);border-radius:10px;padding:16px 18px;
    background:var(--panel);transition:transform .18s,border-color .18s;}
  .cues li:hover{transform:translateY(-3px);border-color:var(--accent);}
  .cues h3{margin:0 0 6px;font-size:14px;letter-spacing:-.005em;}
  .cues p{margin:0;font-size:13.5px;color:var(--dim);}
  .cues code{font-family:var(--mono);font-size:12px;color:var(--accent);}
  /* ---- Hero: the h1, then the live cover globe (left) beside a short lede + cue
     chips (right); columns collapse to a stack below 950px. The globe spins on its
     own with a small 1×/0.5× speed toggle; the twin panels further down carry the
     full scrub/play controls. ---- */
  .hero{margin:0 0 8px;}
  .hero h1{margin:0;}
  .hero-body{display:grid;gap:clamp(22px,4vw,44px);align-items:center;
    grid-template-columns:1fr;margin-top:clamp(20px,3vw,30px);}
  /* Two columns only once the globe column is wide enough (~480px+) to seat the
     ~94-col frame comfortably; below that the globe stacks full-width over the copy. */
  @media (min-width:950px){
    .hero-body{grid-template-columns:minmax(0,1.12fr) minmax(0,0.88fr);}
  }
  .hero-globe{margin:0;position:relative;background:var(--strip);
    border:1px solid var(--edge);border-radius:16px;
    padding:clamp(14px,2.4vw,26px) 8px 13px;display:grid;justify-items:center;
    gap:11px;overflow:hidden;cursor:pointer;
    box-shadow:0 34px 66px -40px rgba(0,0,0,.8);}
  .hero-globe .stack{justify-items:center;}
  /* Bigger cells than the panels (this is the centerpiece), still driven by the
     shared .frame / .frame.active visibility. The ramp is sized so the ~94-col
     frame fills its column at each width without clipping (HERO_R in the builder).
     No inset shadow / padding here -- the figure supplies the ground. */
  .hero-globe .frame{font-size:5.5px;line-height:1.3;box-shadow:none;padding:0;}
  @media (min-width:520px){ .hero-globe .frame{font-size:7.5px;} }
  @media (min-width:950px){ .hero-globe .frame{font-size:8.5px;} }
  .hero-globe figcaption{font-family:var(--mono);font-size:11px;color:#8b93a3;
    letter-spacing:.02em;text-align:center;}
  /* Minimal speed toggle -- reuses the panels' .speed / .speed button styling,
     just centered under the caption (the figure is a centered grid already). */
  .hero-speed{justify-content:center;margin-top:1px;}
  .hero-copy .lede{max-width:none;font-size:16px;margin:0;}
  .hero-copy .cues{margin:18px 0 0;gap:11px;
    grid-template-columns:repeat(auto-fit,minmax(188px,1fr));}
  .hero-copy .cues li{padding:13px 15px;}
  .hero-copy .cues h3{font-size:12.5px;}
  .hero-copy .cues p{font-size:12.5px;line-height:1.5;}
  .panels-note{max-width:66ch;color:var(--dim);font-size:14px;margin:24px 0 16px;}
  .panels-note strong{color:var(--ink);font-weight:600;}
  .panels-note code{font-family:var(--mono);font-size:12.5px;color:var(--accent);}
  .panel{border:1px solid var(--edge);border-radius:12px;background:var(--panel);
    margin:22px 0;overflow:hidden;transition:border-color .2s,box-shadow .2s;}
  .panel:hover{border-color:var(--accent);
    box-shadow:0 24px 44px -30px rgba(0,0,0,.5);}
  .ph{display:flex;align-items:baseline;gap:12px;padding:15px 20px;
    border-bottom:1px solid var(--edge);}
  .ph h2{margin:0;font-size:17px;font-weight:640;}
  .ph p{margin:0;font-family:var(--mono);font-size:12.5px;color:var(--dim);}
  .ph code{color:var(--accent);}
  /* All frames of one rotation are stacked in a single grid cell; only the
     .active one is visible. Inactive frames keep visibility:hidden (not
     display:none) so the viewer holds a stable size and scrubbing never
     reflows. */
  .viewer{padding:20px;background:var(--strip);}
  /* Twin panes: the 256-color and 24-bit renders of the SAME view, side by side
     on wide screens (stacked below ~640px), driven by one shared control row. */
  .viewer.twin{display:grid;gap:14px;align-items:start;
    grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));}
  .pane{position:relative;display:grid;justify-items:center;min-width:0;}
  .stack{display:grid;justify-items:center;}
  /* A dark translucent chip so the label reads on either terminal ground (black
     panels and the light-terminal Earth alike). */
  .plabel{position:absolute;top:7px;left:8px;z-index:2;font-family:var(--mono);
    font-size:10.5px;letter-spacing:.03em;color:#eef3f6;
    background:rgba(12,14,18,.66);border:1px solid rgba(255,255,255,.16);
    padding:2px 8px;border-radius:999px;pointer-events:none;}
  /* Per-pane caption under the perspective panes (eye = ∞ / 2.6 / 2.0). */
  .psub{margin-top:6px;font-family:var(--mono);font-size:11px;color:#9aa6b2;
    text-align:center;letter-spacing:.02em;}
  /* line-height:1.3 (not the font's natural ~1.0-1.2) makes one text row as tall,
     relative to a character's width, as the ASPECT the frames were rendered with
     (see ASPECT in build_showcase.py) assumes a terminal cell to be. Without it
     these monospace webfonts render flatter than a real terminal cell, so the
     disc comes out an oblate ellipse -- squashed top-to-bottom, poles reading as
     cut off -- instead of a circle. */
  .frame{grid-area:1/1;margin:0;font-family:var(--mono);font-size:6px;
    line-height:1.3;white-space:pre;border-radius:6px;padding:9px 7px;
    color:transparent;visibility:hidden;
    box-shadow:0 1px 0 rgba(255,255,255,.04) inset;}
  .frame.active{visibility:visible;}
  @media (min-width:760px){ .frame{font-size:7.5px;} }
  .controls{display:flex;align-items:center;gap:14px;
    padding:13px 20px;border-top:1px solid var(--edge);}
  .play{flex:none;width:34px;height:34px;border-radius:50%;cursor:pointer;
    border:1px solid var(--edge);background:var(--panel);color:var(--ink);
    font-size:12px;line-height:1;display:grid;place-items:center;
    transition:border-color .15s,color .15s;}
  .play:hover{border-color:var(--accent);color:var(--accent);}
  .play:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  /* Custom range: a slim gradient track (edge -> accent, reads as progress
     through the rotation) with a round thumb echoing the play button. */
  .scrub{-webkit-appearance:none;appearance:none;flex:1;min-width:0;height:6px;
    border-radius:999px;cursor:pointer;outline:none;
    background:linear-gradient(90deg,var(--edge),var(--accent));}
  .scrub::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:20px;height:20px;border-radius:50%;background:var(--panel);
    border:2px solid var(--accent);box-shadow:0 2px 8px rgba(0,0,0,.35);cursor:grab;}
  .scrub::-webkit-slider-thumb:active{cursor:grabbing;}
  .scrub::-moz-range-thumb{width:20px;height:20px;border-radius:50%;
    background:var(--panel);border:2px solid var(--accent);
    box-shadow:0 2px 8px rgba(0,0,0,.35);cursor:grab;}
  .scrub::-moz-range-track{height:6px;border-radius:999px;
    background:linear-gradient(90deg,var(--edge),var(--accent));}
  .scrub:focus-visible::-webkit-slider-thumb{outline:2px solid var(--accent);
    outline-offset:2px;}
  .counter{flex:none;font-family:var(--mono);font-size:12.5px;color:var(--dim);
    font-variant-numeric:tabular-nums;min-width:5.5ch;text-align:right;}
  .counter .sep{margin:0 .4ch;opacity:.6;}
  /* Speed toggle: a tight pill group next to the counter -- same visual family
     as .theme-toggle, sized down to fit the controls row. */
  .speed{display:flex;gap:4px;flex:none;}
  .speed button{font-family:var(--mono);font-size:11px;letter-spacing:.02em;
    color:var(--dim);background:var(--panel);border:1px solid var(--edge);
    border-radius:999px;padding:4px 9px;cursor:pointer;
    transition:color .15s,border-color .15s;}
  .speed button:hover{color:var(--ink);border-color:var(--accent);}
  .speed button.active{color:var(--accent);border-color:var(--accent);}
  .speed button:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  .foot{max-width:64ch;color:var(--dim);font-size:13.5px;margin-top:20px;
    padding-top:20px;border-top:1px solid var(--edge);}
  .foot code{font-family:var(--mono);color:var(--accent);font-size:12.5px;}
  /* ---- Run it: a mock terminal (fixed dark in both themes, like a real one) ---- */
  .run{margin-top:40px;}
  .run h2{font-size:18px;font-weight:640;margin:0 0 4px;letter-spacing:-.01em;}
  .run p{margin:0 0 16px;color:var(--dim);font-size:14px;max-width:60ch;}
  .terminal{background:#0b0d10;border:1px solid var(--edge);border-radius:12px;
    overflow:hidden;box-shadow:0 26px 50px -34px rgba(0,0,0,.7);}
  .terminal .tbar{display:flex;align-items:center;gap:8px;padding:11px 14px;
    background:#15181d;border-bottom:1px solid #23272e;}
  .terminal .tbar i{width:11px;height:11px;border-radius:50%;display:inline-block;}
  .terminal .tbar i:nth-child(1){background:#f0605c;}
  .terminal .tbar i:nth-child(2){background:#f5be4f;}
  .terminal .tbar i:nth-child(3){background:#61c554;}
  .terminal .tbar span{margin-left:8px;font-family:var(--mono);font-size:11.5px;
    color:#8b93a3;}
  .terminal pre{margin:0;padding:18px;font-family:var(--mono);font-size:13px;
    line-height:1.75;color:#d7dce6;overflow-x:auto;white-space:pre;}
  .terminal .c{color:#6fb7b3;}   /* comment */
  .terminal .p{color:#5ec8d8;}   /* command */
  .terminal .f{color:#c7a0e0;}   /* flag */
  .badges{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px;}
  .badge{font-family:var(--mono);font-size:11px;letter-spacing:.04em;color:var(--dim);
    border:1px solid var(--edge);border-radius:999px;padding:6px 12px;}
  @media (prefers-reduced-motion:reduce){ *{transition:none !important;} }
</style>
</head>
<body>
<div class="wrap">
  <div class="topline">
    <p class="eyebrow">asciiball · rendering showcase</p>
    <button class="theme-toggle" id="themeBtn" type="button"
      aria-label="Toggle color theme">◐ theme</button>
  </div>
  <header class="hero">
    <h1>A hollow glass planet, drawn in perspective</h1>
    <div class="hero-body">
      __HERO__
      <div class="hero-copy">
        <p class="lede">Every globe here is the real engine output — no lighting
        model, no 3D library. A finite-eye <strong>perspective projection</strong>
        sets the geometry and grayscale <strong>contrast by true depth</strong>
        paints it; together they carry the whole three-dimensional read.</p>
        <ul class="cues">
          <li><h3>See through it</h3><p>A ray pierces the sphere twice: the near
            face draws opaque, and its see-through windows reveal the far
            side.</p></li>
          <li><h3>Perspective → true&nbsp;3D</h3><p>Cast from a finite eye
            (<code>--eye</code>), the two walls land at <em>different latitudes</em>
            and the far one recedes <em>smaller</em> — not a mirrored copy.</p></li>
          <li><h3>Depth → roundness</h3><p>Shade grades by true distance: the near
            wall domes bright-to-dim, the far wall inverts into a cavity.</p></li>
          <li><h3>Pure stdlib</h3><p>Zero runtime dependencies and real Natural
            Earth data; 24-bit color auto-detected, with a 256 fallback.</p></li>
        </ul>
      </div>
    </div>
  </header>

  <p class="panels-note">Each view below is <strong>twinned</strong>: the 256-color
  fallback (left) and the auto-detected 24-bit ramp (right) spin off the identical
  geometry. Truecolor draws the <em>same</em> brightness envelope continuously, so
  the gradient and the faint far-shell ghost step per-cell instead of banding — one
  held Earth frame resolves __N256__ distinct grays in 256-color versus __NTC__ in
  truecolor. Piped/redirected runs always stay 256-color, so output is
  deterministic.</p>

__PANELS__

  <p class="panels-note"><strong>Perspective, side by side.</strong> Earth's far
  continents show through its near oceans as a dim back wall — brightest at the rim
  and fading toward the centre, so the hemisphere reads as a depth cavity. The
  transparent README globe below makes both walls fully explicit — spin all three and
  watch the far wall shrink and split away from the front as <code>--eye</code> drops
  from <code>∞</code> (orthographic, the old look) to <code>2.0</code>.
  <code>2.6</code> ships as the default.</p>

__EYEPANEL__

  <p class="panels-note"><strong>Text — the source, sentence by sentence.</strong>
  The same hollow ball, but the surface is the README laid out <em>one sentence per
  latitude ring</em> and read like a ticker as it spins. Blank gap rings between
  sentences — sized at the golden ratio (a <code>k</code>-ring sentence is followed
  by ≈<code>φ·k</code> windows) — let the far wall show through as a sparse dotted
  depth field, and solid polar caps keep the silhouette. The rotation snaps to whole
  glyph tiles, so a foreground sentence's characters translate rigidly. Spin it:
  <code>./bin/ascii-text.sh</code>.</p>

__TEXTPANEL__

  <section class="run">
    <h2>Run it</h2>
    <p>Pure standard-library Python — no runtime dependencies, no image libraries.
    The globe is spun straight in your terminal:</p>
    <div class="terminal">
      <div class="tbar"><i></i><i></i><i></i><span>zsh — asciiball</span></div>
<pre><span class="c"># spin Earth (Ctrl+C to stop)</span>
<span class="p">./bin/ascii-earth.sh</span>

<span class="c"># spin twice as fast</span>
<span class="p">./bin/ascii-earth.sh</span> <span class="f">--speed</span> 2

<span class="c"># 24-bit color is auto-detected; force it (or the 256 fallback) if needed</span>
<span class="p">./bin/ascii-earth.sh</span> <span class="f">--color-depth</span> truecolor

<span class="c"># render a few static frames and exit (no animation loop)</span>
<span class="p">python src/rotating_earth.py</span> <span class="f">--preview</span>

<span class="c"># spin the README as a sentence ticker (the Text body)</span>
<span class="p">./bin/ascii-text.sh</span></pre>
    </div>
    <div class="badges">
      <span class="badge">pure-Python stdlib</span>
      <span class="badge">zero runtime deps</span>
      <span class="badge">real Natural Earth data</span>
      <span class="badge">auto truecolor / 256</span>
      <span class="badge">self-contained page</span>
    </div>
  </section>

  <p class="foot">Frames rendered at <code>--radius 20 --aspect 2.3</code> with the
  shipped default glyph source (this bundled README.md) — one full rotation
  sampled at __FRAMES__ evenly-spaced angles.
  Drag the slider to scrub or press play to spin (each strip loops seamlessly
  because rotation is periodic in 2&pi;); the 256-color and 24-bit renders sit side
  by side per view. Panels only animate while on screen. This page is generated
  from the engine —
  regenerate after changing the shade ramps with
  <code>python scripts/build_showcase.py</code>. Tuning lives in the
  <code>NEAR_SOLID / NEAR_SCREEN / FAR_CONTRAST</code> tuples in
  <code>ascii_sphere.py</code> (first element = limb, second = centre) and the
  <code>--eye</code> perspective default (<code>DEFAULT_EYE</code>).</p>
  <p class="foot">asciiball __VERSION__</p>
</div>
<script>
// Manual theme toggle: the page chrome defaults to the OS preference, and this
// flips :root[data-theme] so a visitor can override it (the baked terminal
// frames keep their own fixed dark/light ground regardless).
(function () {
  var root = document.documentElement;
  var btn = document.getElementById("themeBtn");
  function sysDark() {
    return matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  }
  btn.addEventListener("click", function () {
    var cur = root.getAttribute("data-theme");
    var isDark = cur ? cur === "dark" : sysDark();
    root.setAttribute("data-theme", isDark ? "light" : "dark");
  });
})();

// Each panel bakes in a full rotation as stacked <pre> frames; this drives the
// scrubber -- flip the .active class, mirror the range input and counter, and
// optionally auto-advance. No external assets; pure DOM class toggles.
(function () {
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var BASE_MS = 90; // interval at speed 1x; slower speeds scale this up
  document.querySelectorAll(".panel").forEach(function (panel) {
    // Each panel holds two .stack columns (256 + truecolor); one shared control
    // advances the same frame index across both in lockstep.
    var stacks = [];
    panel.querySelectorAll(".stack").forEach(function (s) {
      stacks.push(s.querySelectorAll(".frame"));
    });
    var scrub = panel.querySelector(".scrub");
    var play = panel.querySelector(".play");
    var counter = panel.querySelector(".counter");
    var speedBtns = panel.querySelectorAll(".speed button");
    var n = stacks[0].length, timer = null, speed = 1;
    function pad(x) { return (x < 10 ? "0" : "") + x; }
    function show(i) {
      i = ((i % n) + n) % n;
      stacks.forEach(function (frames) {
        for (var k = 0; k < n; k++) frames[k].classList.toggle("active", k === i);
      });
      scrub.value = i;
      counter.innerHTML = pad(i + 1) + '<span class="sep">/</span>' + pad(n);
    }
    function stop() {
      if (!timer) return;
      clearInterval(timer); timer = null;
      play.innerHTML = "&#9654;"; play.setAttribute("aria-label", "Play rotation");
    }
    function start() {
      if (timer) clearInterval(timer);
      play.innerHTML = "&#10074;&#10074;";
      play.setAttribute("aria-label", "Pause rotation");
      timer = setInterval(function () { show(+scrub.value + 1); }, BASE_MS / speed);
    }
    // wantPlay = the user's intent to spin; visible = panel is on screen. The
    // panel animates only when BOTH hold, so off-screen panels burn no CPU and a
    // manual pause survives scrolling away and back.
    var wantPlay = !reduce, visible = false;
    function sync() { (wantPlay && visible) ? start() : stop(); }
    scrub.addEventListener("input", function () {
      wantPlay = false; stop(); show(+scrub.value);
    });
    play.addEventListener("click", function () { wantPlay = !timer; sync(); });
    speedBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        speed = +btn.dataset.speed;
        speedBtns.forEach(function (b) { b.classList.toggle("active", b === btn); });
        if (timer) start(); // re-arm the interval at the new speed immediately
      });
    });
    show(0);

    // Only spin while the panel is on screen (perf/battery); resume on return.
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting; sync();
      }, { threshold: 0.15 }).observe(panel);
    } else {
      visible = true; sync();
    }
  });
})();

// The cover globe spins mostly on its own -- the only controls are a 1x/0.5x speed
// toggle and click-to-pause (the twin panels below carry the full scrub/play).
// Advances the .active frame on a timer; pauses off-screen, on click, and under
// reduced-motion (which just holds the first frame).
(function () {
  var fig = document.getElementById("heroGlobe");
  if (!fig) return;
  var frames = fig.querySelectorAll(".frame"), n = frames.length, i = 0, timer = null;
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var BASE_MS = 90, mult = 1; // 1x = the shipped 64-frame tick; 0.5x doubles it
  function show(k) {
    for (var j = 0; j < n; j++) frames[j].classList.toggle("active", j === k);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function start() {
    if (reduce) return;
    stop(); // re-arm cleanly so a speed change takes effect at once
    timer = setInterval(function () { i = (i + 1) % n; show(i); }, BASE_MS / mult);
  }
  var want = !reduce, visible = false;
  function sync() { (want && visible) ? start() : stop(); }
  fig.addEventListener("click", function () { if (!reduce) { want = !want; sync(); } });
  fig.querySelectorAll(".hero-speed button").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.stopPropagation(); // don't also toggle the globe's click-to-pause
      mult = +btn.dataset.mult;
      fig.querySelectorAll(".hero-speed button").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      if (timer) start(); // spinning -> re-arm at the new speed now
    });
  });
  show(0);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (e) {
      visible = e[0].isIntersecting; sync();
    }, { threshold: 0.2 }).observe(fig);
  } else { visible = true; sync(); }
})();
</script>
</body>
</html>
"""


def main():
    out_path = os.path.join(REPO, "docs", "showcase.html")
    n256, ntc = depth_gain()
    page = (
        PAGE.replace("__HERO__", hero_globe())
        .replace("__PANELS__", panels())
        .replace("__EYEPANEL__", eye_panel())
        .replace("__TEXTPANEL__", text_ball())
        .replace("__N256__", str(n256))
        .replace("__NTC__", str(ntc))
        .replace("__FRAMES__", str(FRAMES))
        .replace("__VERSION__", _version())
    )
    with open(out_path, "w") as fh:
        fh.write(page)
    print("wrote", os.path.relpath(out_path, REPO), os.path.getsize(out_path), "bytes")


if __name__ == "__main__":
    main()
