"""The functional core of the rotating 3D ASCII sphere engine -- pure render + plan.

This is the core: a first-principles compositing model for a hollow, rotating
sphere drawn into a character grid, PLUS the pure planning math that sizes a globe
to a terminal (no I/O of its own -- callers inject the size). It imports only the
standard library and is genuinely PURE -- it holds nothing that touches the
filesystem or terminal: no argv, no file reads, no terminal probe/sizing/input,
and no run loop. All of those effects -- both filesystem reads (the `data/*.b64`
decoders + the glyph/text sources) and terminal/OS effects (argv, tty, the loop,
signals) -- live in the single effects module, the shell `shell.py`. This module
carries only the PURE decoders/parsers those readers delegate to
(`unpack_bits`/`unpack_levels`, `glyphs_from_text`). The single load-bearing seam
in the program is *pure computation* (here) vs. *effects* (`shell.py`); the body
apps (`rotating_earth.py`) are the
composition roots that wire the pieces together, supplying only their embedded
data and a `Surface` describing how each surface class is drawn.

The sphere is fixed in screen space; only the texture rotates under it, so all
per-cell geometry is angle-independent and precomputed once. A ray through an
on-disc cell pierces the shell as an ordered stack of samples, front -> back (a
hollow sphere is the two-sample near/far case; the model never hard-codes two).
A cell emits exactly one glyph + one color, or nothing -- we cannot alpha-blend
two glyphs, so continuous coverage is a stable, body-glued dither (an ordered
screen-door welded to the surface tile), never a blend.

Everything the engine does decomposes into FOUR orthogonal axes, composed in a
fixed order A -> B -> C -> D, each answering one independent question and never
reading another's knobs:

  * AXIS A -- Sampling (pure geometry): *where* on each shell does this cell land?
    A finite-eye PERSPECTIVE ray pierces each shell at its own latitude, longitude,
    and depth (precomputed per shell), so the near and far walls never share a row
    and the far wall is foreshortened smaller -- a true 3D read, not a shaded disc.
    The frame's `angle` is added to each base longitude; the steady-state loop does
    no sqrt/asin/atan2. (--eye -> infinity recovers the old orthographic near/far.)
  * AXIS B -- Opacity (the shell walk): does the ray stop at this shell or pass
    through? Each shell has an opacity 0..1; the walk (front -> back) stops at the
    first shell whose stable per-tile dither fires, else the ray exits to a HOLE.
    Opacity 1 = solid/occluding, 0 = window, fractional = screen-door. A shell also
    carries a per-shell SPARSITY keep (`far_fill` on the far wall): a stop may be
    thinned to a fraction of its tiles, turning the counter-scrolling far hemisphere
    into a sparse dotted depth field rather than a competing surface.
  * AXIS C -- Shade (pure presentation): how lit + how prominent -> what gray? A
    drawn fragment rides one of three precomputed ramps (near-solid bold, near
    screen-door dim, far ghost), selected by which branch of the walk stopped it,
    indexed by a directional-light term (Lambert N.L on the surface normal, for a
    fixed light) and shifted by the material's signed `relief` bias. Color is
    light+theme only (no per-material hue).
  * AXIS D -- Density (stylization): is the drawn ink painted, or thinned to a true
    hole? A pipeline of void-masks (limb dissolve at a fine grain, fill void at a
    coarse grain), each an independent dither; ink survives iff it passes every one.

A surface class maps to a `Material(opacity, palette, hashed, relief)` -- the four
axes and nothing else. Opaque *is* opacity 1.0; a fully transparent window *is*
opacity 0.0; a screen-door *is* opacity in (0, 1). A reading-order text material
(opacity 1 with real spaces in its palette) yields per-tile opacity 0 on its space
tiles and 1 on its ink tiles, so "text = land, spaces = ocean" falls out with no
special path. A minimal body is one material with opacity 1 (a solid marble) or
two (opacity-1 feature + opacity-0 window).

No runtime dependencies beyond the standard library.
"""

import re
import math
import zlib
import base64
from typing import Callable, NamedTuple, Optional


# The core's stable public API. Everything here that isn't listed (the
# underscore-prefixed internals like _Cell, _hash2, _build_cells) is
# implementation detail, excluded from `import *`. All effects (the loop, input,
# probe/sizing, argv, file reads) live in the imperative shell, `shell.py`, not
# here.
__all__ = [
    # constants
    "DEFAULT_GLYPHS",
    "RESET",
    "BASE_SPEED",
    "DEFAULT_EYE",
    "DEFAULT_FAR_DIM",
    "DEFAULT_FAR_FILL",
    "DEFAULT_LIGHT_AZ",
    "DEFAULT_LIGHT_EL",
    "DEFAULT_AMBIENT",
    "HALO_PAD",
    "EDGE_FADE",
    # shade helper (consumed by the shell's footer/help)
    "gray_escape",
    "GOLDEN",
    # surface model
    "Material",
    "Surface",
    "TileGrid",
    "tile_grid",
    # renderer
    "Globe",
    # plan (pure config/output value types + the sizing math)
    "Config",
    "Plan",
    "resolve_step",
    "disc_radius",
    "fit_radius",
    "fit_globe",
    "center_frame",
    "frame_delay",
    # data + glyphs (PURE decoders/parsers; file reads live in shell.py)
    "unpack_bits",
    "unpack_levels",
    "glyphs_from_text",
    "split_sentences",
    "layout_rings",
    "RingLayout",
]


# Feature glyphs are drawn from a string of characters; the glyph for a tile is
# taken from its position along the string (see Globe._pick and the near shell's
# lossless `_packed_near` index, which skips window tiles so the stream splits
# across a mask instead of dropping covered characters) so a reading-order source
# text lays out across the surface and slides with the body instead of
# flickering in screen space. This dense built-in set is the fallback when no
# source text is given or the file can't be read.
DEFAULT_GLYPHS = "#%@&$MBNREW8dPGHKahkbpq"

RESET = "\033[0m"

# Baseline rotation rate (radians of spin per frame) that corresponds to a
# --speed ratio of 1.0. Users give --speed as a multiple of this -- 2 = twice as
# fast, 0.5 = half -- so the knob is intuitive without exposing raw radians.
BASE_SPEED = 0.05

# AXIS A -- Perspective: the eye sits this many sphere-radii from the centre, on
# the viewing axis, looking at the origin. A FINITE distance is what makes the
# render truly 3D rather than a 2D shaded disc: the ray through a screen cell
# pierces the near and far walls at DIFFERENT latitudes (so the two layers never
# line up row-by-row) and the far wall's whole hemisphere is foreshortened into a
# smaller inset disc (so its text reads smaller, like a receding back wall). The
# silhouette is always the same circle regardless of distance (screen radius 1 maps
# to the tangent cone), so the disc footprint -- and all the sizing math -- is
# unchanged. Larger = gentler perspective; --eye -> infinity recovers the old
# orthographic look (near/far share a latitude, same scale). Must be > 1 (the eye
# is outside the unit sphere); clamped in Globe.
DEFAULT_EYE = 2.6

# The drawing canvas is the disc footprint scaled up by this factor so the globe
# never sits flush against (and gets clipped by) an edge -- it leaves a ~14% halo
# of margin all around. Used for the canvas size and mirrored by disc_radius'
# `footprint` so the disc is chosen to fit inside the padded footprint.
HALO_PAD = 1.14

# Limb dissolve threshold: the foreshortening factor z (= cos of the angle from
# the viewing axis) runs 1 at the disc centre to 0 at the limb. Below this z the
# LIMB density mask starts thinning glyphs to holes -- stably, per tile -- so the
# rim dissolves into a clean horizon instead of crushing into a solid wall of
# characters where many surface tiles pile into one screen cell.
EDGE_FADE = 0.45

# ---------------------------------------------------------------------------
# AXIS C -- Shade: directional light as color (theme-aware)
# ---------------------------------------------------------------------------
# Shade is carried entirely by grayscale *contrast against the terminal
# background*. Each drawn fragment picks a contrast level from a DIRECTIONAL-LIGHT
# term: the Lambert dot product N.L of the surface normal N (on a unit sphere, the
# pierced point itself) with a fixed light L, floored by ambient (AXIS A precomputes
# it per shell as `_ShellSample.shade_band`, 0 = shadow/terminator, Z_LEVELS-1 =
# fully lit). Why a light and not distance-from-eye: depth across a sphere's face is
# sqrt(1-r^2), flat through the middle and steep only at the rim, so a depth cue
# reads as a FLAT disc with a thin dark ring; a light offsets the highlight and
# grades across the whole face to a dark terminator, on BOTH walls. The walk (Axis
# B) produces one of three fragment kinds, each riding its own ramp:
#   * NEAR-SOLID  -- near shell stopped solid (opacity >= 1): the prominent front
#     surface, bold and high-contrast, lit highlight -> shadow crescent.
#   * NEAR-SCREEN -- near shell stopped on a screen-door (0 < opacity < 1): sparse
#     texture on the same shell, so it reads dimmer and non-bold.
#   * FAR         -- a deeper shell stopped: the receding back wall, scaled down
#     (seen through the glass); its normal faces away so its centre is in shadow and
#     only its limb arc (curving toward the light) lights -- a lit cavity, not a
#     mirrored dim copy of the front.
# Prominence follows opacity -- no separate knob -- which is why opacity is the
# single most central scalar: it drives both occlusion (B) and which ramp here.
#
# The light is fixed in SCREEN space, so the body rotates under it (a fixed sun) and
# the band is fixed per cell (the geometry never moves, only the texture rotates) --
# so the steady-state loop just indexes the ramps, no per-frame trig. A separate
# SCREEN-radial band (`_Cell.band`) drives the AXIS D fill dome.
Z_LEVELS = 24  # shade bands (== the count of distinct xterm grays) for a smooth ramp
# (shadow, lit) contrast per fragment kind -- the band that indexes each ramp is a
# directional-lighting term (see the light constants below), NOT a distance-from-eye
# depth: band 0 is the shadow/terminator end, band Z_LEVELS-1 the fully-lit end. The
# near ramp spans the full bright envelope; the far ramp is scaled DOWN (seen through
# the glass) but still carries a wide gradient so the back wall is not flat either.
NEAR_SOLID_CONTRAST = (
    0.10,
    1.00,
)  # solid front feature: prominent -- dark terminator up to a bright highlight
NEAR_SCREEN_CONTRAST = (0.10, 0.55)  # near screen-door: dimmer near-face texture
FAR_CONTRAST = (0.06, 0.45)  # far shell: recessed behind the glass, but still shaded

# Directional lighting (Axis C). The shade is a Lambert term on the surface normal
# (which, on a unit sphere, IS the surface point) for a light FIXED in screen space
# -- not the old distance-from-eye depth. Depth across a sphere's face is
# sqrt(1 - r^2): flat through the middle, steep only at the rim, so a depth cue reads
# as a mostly FLAT disc with a thin dark ring. A directional light instead offsets the
# highlight and falls across the WHOLE face to a dark terminator; and since the far
# wall's normal faces away from a front light, the back's centre darkens while its
# limb arc lights -- so BOTH walls read as a lit 3D sphere in space. The light is
# fixed in screen space, so the body rotates under it (a fixed sun) and every cell's
# shade stays angle-independent (precomputed once, no steady-state cost).
DEFAULT_LIGHT_AZ = 135.0  # degrees: 0 = from the right, +90 = from straight above
DEFAULT_LIGHT_EL = 50.0  # degrees toward the viewer (0 = pure side light, 90 = head-on)
DEFAULT_AMBIENT = 0.12  # shadow-side floor (0..1) so the dark side isn't pure black
# Default far-wall visibility, shared by every body (Axis B/C). The far wall is
# the SAME near-face ink counter-scrolling behind the windows, so at full density
# its ghost tracks the near face for ANY body -- geometry, not the dataset. Two
# independent tunings converged here: the text globe landed at 0.5, and Earth's
# ocean ghost (a ~71%-of-disc window) measured ~0.45. So the "far wall must not
# out-shout the near face" invariant gets ONE engine default, not per-body tuning.
# `far_dim` scales the far ramp's brightness (capped at FAR_CONTRAST[1]=0.20, so
# even 1.0 stays a ghost); `far_fill` is the far shell's per-tile keep fraction.
DEFAULT_FAR_DIM = 0.85
DEFAULT_FAR_FILL = 0.5
GRAY_LO, GRAY_HI = 232, 255  # xterm-256 grayscale index bounds
THEMES = ("dark", "light")


# The xterm-256 grayscale ramp (indices 232..255) walks RGB 8..238 in steps of
# 10. Truecolor reuses that SAME 8..238 envelope but continuously, so a 24-bit
# frame reads as a smoother version of the indexed one (identical endpoints), not
# a different palette -- and a narrow contrast slice (e.g. the far shell's
# 0.12..0.20) that the 24-index ramp rounds down to ~3 distinct grays now spans a
# distinct value per radial band instead of banding. Z_LEVELS is unchanged: the
# 24-band spatial quantisation was never the problem, index rounding was.
GRAY_RGB_LO, GRAY_RGB_HI = 8, 238


# ---------------------------------------------------------------------------
# The dither primitive (one function, shared by Axis B and Axis D)
# ---------------------------------------------------------------------------
# All stochastic coverage in the engine is one stable, body-glued uniform, keyed
# on surface-tile coords so the pattern is welded to the body and transported by
# rotation (never screen-static, never per-frame random). Axes B and D each get
# their own PRIME key offsets so their draws are statistically independent despite
# sharing _hash2; per-mille (% 1000) throughout so the hot loop is integer-only.

# Opacity (Axis B) dither keys. `SHELL_SALT` is added per shell (s * SHELL_SALT)
# so the near and far draws stay independent even where the two shells happen to
# sample the same tile column (e.g. nx = 0); OKX/OKY keep opacity decorrelated
# from every density mask.
OKX, OKY = 1523, 1741
SHELL_SALT = 2087
# Per-shell SPARSITY dither keys (Axis B) -- thins a shell's own fragments to a
# fraction (the `far_fill` speckle). Distinct primes so the far-layer dots stay
# decorrelated from the opacity screen-door (OKX/OKY) and every density mask.
FARKX, FARKY = 1301, 1699

# Density (Axis D) mask keys -- distinct primes so each mask, and its edge jitter,
# stays decorrelated from opacity and from the other masks.
LIMB_KX, LIMB_KY, LIMB_JKX, LIMB_JKY = 619, 863, 1039, 1237
FILL_KX, FILL_KY, FILL_JKX, FILL_JKY = 977, 491, 131, 557


def gray_escape(contrast, theme, attr, truecolor=False):
    """SGR escape for a grayscale `contrast` (0..1) against the theme background.

    High contrast is bright on a dark theme, dark on a light theme. `attr` is the
    leading SGR attribute emitted first (``"1"`` bold near / ``"22"`` normal / ``""``).
    With `truecolor`, emits a 24-bit gray (``38;2;v;v;v``) over the same brightness
    envelope as the 256-color ramp; otherwise a 256-indexed gray (``38;5;idx``).

    Public (not underscore-prefixed) because the terminal driver reuses it for the
    run-loop footer and the `?` help overlay, so those tints ride the same ramp as
    the sphere. The renderer's own ramps go through `_shade_ramp` below.
    """
    contrast = max(0.0, min(1.0, contrast))
    prefix = f"{attr};" if attr else ""
    if truecolor:
        span = GRAY_RGB_HI - GRAY_RGB_LO
        if theme == "light":
            v = GRAY_RGB_HI - int(round(contrast * span))  # dark = high contrast
        else:
            v = GRAY_RGB_LO + int(round(contrast * span))  # bright = high contrast
        v = max(0, min(255, v))
        return f"\033[{prefix}38;2;{v};{v};{v}m"
    span = GRAY_HI - GRAY_LO
    if theme == "light":
        idx = GRAY_HI - int(round(contrast * span))  # dark = high contrast on white
    else:
        idx = GRAY_LO + int(round(contrast * span))  # bright = high contrast on black
    idx = max(GRAY_LO, min(GRAY_HI, idx))
    return f"\033[{prefix}38;5;{idx}m"


def _shade_ramp(contrast_range, theme, attr, truecolor=False):
    """Precompute a Z_LEVELS-long escape list from the limb (band 0) to the disc
    centre (band Z_LEVELS-1)."""
    lo, hi = contrast_range
    return [
        gray_escape(lo + (hi - lo) * (i / (Z_LEVELS - 1)), theme, attr, truecolor)
        for i in range(Z_LEVELS)
    ]


def _hash2(a, b):
    """Stable 32-bit hash of two small integers -- the engine's one dither seed."""
    h = (a * 73856093) ^ (b * 19349663)
    return h & 0x7FFFFFFF


# Each byte -> its 8 bits, MSB-first, precomputed once at import. Lets
# unpack_bits expand a blob with one join over a lookup table instead of a
# per-bit Python loop across the ~259k-bit body masks.
_BIT_EXPAND = [bytes((byte >> s) & 1 for s in range(7, -1, -1)) for byte in range(256)]


def unpack_bits(b64, w, h):
    """Decode one MSB-first bit-packed base64 blob into a 0/1 bytearray.

    The blob is zlib-compressed, base64-encoded, row-major with MSB-first bit
    packing over a w*h grid. Returns a flat bytearray of length w*h
    (index = y*w + x); a blob that unpacks short is zero-padded, one that
    unpacks long is truncated -- matching the original fixed-size buffer.
    """
    raw = zlib.decompress(base64.b64decode(b64))
    total = w * h
    bits = bytearray().join(_BIT_EXPAND[byte] for byte in raw)
    if len(bits) < total:
        bits.extend(bytes(total - len(bits)))
    return bits[:total]


_NIBBLE_EXPAND = [bytes(((byte >> 4) & 0xF, byte & 0xF)) for byte in range(256)]


def unpack_levels(b64, w, h):
    """Decode a nibble-packed base64 blob into a bytearray of 0..15 level codes.

    The companion to `unpack_bits` for surfaces that need TONE, not a boolean
    mask: instead of one bit per cell it packs one 4-bit level per cell (two
    cells per byte, high nibble first), row-major over the w*h grid, then
    zlib-compressed and base64-encoded. Returns a flat bytearray of length w*h
    (index = y*w + x); a short blob is zero-padded, a long one truncated -- the
    same fixed-size contract as `unpack_bits`. 16 levels is plenty of surface
    tone for an ASCII sphere, and the smooth grid zlib-compresses well.
    """
    raw = zlib.decompress(base64.b64decode(b64))
    total = w * h
    levels = bytearray().join(_NIBBLE_EXPAND[byte] for byte in raw)
    if len(levels) < total:
        levels.extend(bytes(total - len(levels)))
    return levels[:total]


# A whitespace run counts as a SENTENCE gap when the character before it is one
# of these terminators. A display heuristic, not NLP (per the sentence-ring
# design): it keeps `e.g.`-style abbreviations "wrong" occasionally, and that is
# fine -- the gap is a visual window, not a parse.
_SENTENCE_ENDS = ".!?…"


def glyphs_from_text(text, word_sep="·", sentence_sep="  "):
    """Build a feature-glyph string from raw `text` (pure). Read by `shell.load_glyphs`.

    Non-printable characters are dropped; the rest are kept verbatim, in order
    and *with duplicates* -- the duplicates and sequence are the text, which is
    what lets it read across the surface.

    Whitespace can't be drawn as-is inside a sentence (a blank glyph would punch
    a see-through hole mid-sentence, so the far shell would bleed into the
    text). Each whitespace run collapses to ONE separator, picked by what it
    follows:

      * inside a sentence -- `word_sep` (default a middle dot), which both marks
        the word boundary and fills the cell, so a sentence is a hole-free,
        fully opaque run: the background shell can never show through it.
      * after a sentence terminator (.!?…) -- `sentence_sep` (default two real
        spaces). Spaces in a reading-order palette are per-tile windows, so the
        gaps BETWEEN sentences are the only places the text lets the far shell
        (or a true hole) show through.

    Pass word_sep="" to run words together; sentence gaps are still emitted
    (they are structural windows, not word decoration). Returns None if `text` is
    empty or reduces to nothing, so the caller can fall back. Pure: the file read
    lives in `shell.load_glyphs`, which delegates the parsing here.
    """
    out = []
    pending_sep = False
    for ch in text:
        if ch.isspace():
            pending_sep = True
        elif ch.isprintable():
            # Collapse the pending whitespace run to one separator: a window
            # after a sentence end, a word_sep dot inside a sentence.
            if pending_sep and out:
                out.append(sentence_sep if out[-1] in _SENTENCE_ENDS else word_sep)
            out.append(ch)
            pending_sep = False
        # non-printable: drop, leaving any pending separator state untouched
    glyphs = "".join(out).strip((word_sep or "") + " ")
    return glyphs or None


# The golden ratio -- the spec default for the sentence-ring body's gap:ink
# balance (a sentence spanning k rings is followed by ~GOLDEN*k blank rings, so
# ink:hollow ~ 1:phi down the sphere).
GOLDEN = (1 + 5**0.5) / 2

# Split AFTER a sentence terminator that is followed by whitespace (lookbehind
# keeps the terminator with its sentence; `3.14` isn't split because the dot is
# followed by a digit, not whitespace). Abbreviations like `e.g.` DO split here
# but their short fragment is re-merged by `split_sentences`'s min_len rule -- a
# deliberate display heuristic, not NLP.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text, min_len=12):
    """Segment `text` into display sentences (pure). Siblings `glyphs_from_text`.

    A display heuristic, NOT NLP (do not grow it): split on `.!?…` followed by
    whitespace/EOF, treat blank lines (paragraph breaks) as hard boundaries,
    collapse each sentence's internal whitespace to single spaces and drop
    non-printables, and merge any sub-`min_len` fragment (markdown headers, list
    markers, stray `1.`/`e.g.` bits) into the following sentence (a short
    trailing fragment folds into the previous one). Never returns empty strings;
    returns `[]` for empty/whitespace input.
    """
    if not text or not text.strip():
        return []
    merged = []
    for para in re.split(r"\n\s*\n", text):  # blank line = hard boundary
        raw = []
        for piece in _SENTENCE_SPLIT.split(para):
            kept = "".join(ch for ch in piece if ch.isprintable() or ch.isspace())
            cleaned = " ".join(kept.split())  # collapse internal whitespace runs
            if cleaned:
                raw.append(cleaned)
        para_merged, carry = [], ""
        for s in raw:
            s = (carry + " " + s) if carry else s
            carry = ""
            if len(s) < min_len:
                carry = s  # too short -- fold into the NEXT sentence
            else:
                para_merged.append(s)
        if carry:  # short trailing fragment stays within its paragraph
            if para_merged:
                para_merged[-1] = para_merged[-1] + " " + carry
            else:
                para_merged.append(carry)
        merged.extend(para_merged)
    return merged


class RingLayout(NamedTuple):
    """A sentence-ring palette for one disc size (see `layout_rings`).

    `palette` is exactly `tiles_x * tiles_y` chars (the sphere covered once, so
    `_pick`'s modulo is the identity -- the sentence-cycle repetition is baked
    into the CONTENT, ring-aligned, never left to an accidental modulo wrap).
    `spans` is `[(sentence_index, first_ring, ring_count), ...]` (unused by Phase
    1 rendering, returned now so Phases 2-3 keep the signature). `cap_rings` is
    the solid-filler ring count at EACH pole.
    """

    palette: str
    spans: list
    cap_rings: int


def layout_rings(
    sentences, tiles_x, tiles_y, *, word_sep="·", pole_frac=0.15, gap_ratio=GOLDEN
):
    """Lay `sentences` out as latitude rings on a `tiles_x` x `tiles_y` sphere.

    One sentence = a contiguous block of rings (wrapped at `tiles_x`, its last
    ring padded to width with real spaces = windows), followed by
    `max(1, round(gap_ratio * k))` all-space gap rings -- the golden-ratio
    hollow, gaps ONLY between sentences (no window inside a sentence). The
    sentence cycle repeats down the body until the next whole sentence-plus-gap
    no longer fits; the small remainder is all-space. `pole_frac` of the rings at
    each pole are solid `word_sep` filler so the silhouette survives (a cap must
    have ink, so an empty `word_sep` falls back to `·` there only). Pure.
    """
    tiles_x = max(1, int(tiles_x))
    tiles_y = max(1, int(tiles_y))
    cap_char = word_sep or "·"  # a cap must have ink even under --no-word-sep
    cap = max(0, min(round(tiles_y * pole_frac), (tiles_y - 1) // 2))
    body_rings = tiles_y - 2 * cap

    prepped = [s.replace(" ", word_sep) for s in (sentences or [""])]
    if not any(prepped):  # guarantee a non-blank body
        prepped = [cap_char]
    n = len(prepped)

    rings, spans, idx, placed_any = [], [], 0, False
    while len(rings) < body_rings:
        s = prepped[idx % n]
        chunks = [s[i : i + tiles_x] for i in range(0, len(s), tiles_x)] or [""]
        k = len(chunks)
        gap = max(1, round(gap_ratio * k))
        remaining = body_rings - len(rings)
        if k + gap <= remaining:  # whole sentence-plus-gap fits
            first = cap + len(rings)
            rings.extend(c.ljust(tiles_x) for c in chunks)  # tail pad = windows
            spans.append((idx % n, first, k))
            rings.extend(" " * tiles_x for _ in range(gap))
            idx += 1
            placed_any = True
        elif not placed_any:  # first sentence won't fit once -> hard-truncate
            first = cap + len(rings)
            take = min(k, remaining)
            rings.extend(c.ljust(tiles_x) for c in chunks[:take])
            spans.append((idx % n, first, take))
            break
        else:
            break  # remainder stays all-space (< the next unit)
    rings.extend(" " * tiles_x for _ in range(body_rings - len(rings)))

    cap_ring = cap_char * tiles_x
    palette = "".join([cap_ring] * cap + rings + [cap_ring] * cap)
    return RingLayout(palette=palette, spans=spans, cap_rings=cap)


# ---------------------------------------------------------------------------
# Surface description (body-supplied)
# ---------------------------------------------------------------------------
class Material(NamedTuple):
    """How one surface class draws -- a flat set of optical properties, one per axis.

    This is the whole material model: a class contributes to exactly the four
    render axes and nothing else. There is no `kind` tag and no stipple sub-group;
    opaque, window, and screen-door are just three points on the `opacity` scale.

      * `opacity` (AXIS B) -- 0..1. 1.0 = solid/occluding (the ray stops, drawn
        bold on the front); 0.0 = a window (the ray passes through to the next
        shell); fractional = a stable screen-door (that fraction of tiles stop and
        draw dim, the rest pass through). Spelled `opacity` everywhere -- never a
        bare `a`/`alpha`.
      * `palette` (AXIS A) -- the glyph source. A material that is a pure window
        (opacity 0) needs none; any drawing material carries one.
      * `hashed` (AXIS A) -- False indexes the palette in reading order (text reads
        across the surface); True hashes per tile (a texture with no reading order,
        e.g. crater rings). Fixed per tile either way, so rotation transports the
        glyph rather than re-picking it. DATA CONTRACT: a hashed palette must carry
        NO spaces, so a texture is guaranteed non-transparent (a blank glyph is how
        per-tile opacity 0 is produced -- see the walk in Globe.render).
      * `relief` (AXIS C) -- a signed shade-band bias, a topographic DEPTH cue (not
        hue): < 0 recessed/dimmer (sunken bowl/valley), > 0 raised/brighter, 0
        flush with the surrounding crust. Shifts *within* the ramp the walk chose;
        it cannot cross to another ramp. `relief=0` (default) is the flush case.

    Color (the absolute shade) is NOT specified here: it is the engine's pure
    light+theme cue (near shell prominent, far shell a recessed ghost, both graded
    by a fixed directional light -- see the NEAR_SOLID/NEAR_SCREEN/FAR contrast
    constants and the light constants).
    """

    opacity: float = 1.0
    palette: str = ""
    hashed: bool = False
    relief: int = 0


class Surface(NamedTuple):
    """A body's full surface: metadata, dimensions, class grid, and materials.

    `grid` is a flat bytearray of class codes (index = y*W + x), decoded from an
    embedded blob or procedurally rasterized. `classes` maps each code to its
    `Material`. `name`/`provenance` feed the run-loop footer so the engine carries
    no body-specific labels.
    """

    name: str
    provenance: str
    W: int
    H: int
    grid: bytearray
    classes: dict  # {code: Material}


class TileGrid(NamedTuple):
    """The surface-tile quantisation for a given disc size (AXIS A layout).

    A tile is one screen cell at the disc centre; `tiles_x`/`tiles_y` count the
    tiles over the WHOLE sphere and `div_x`/`div_y` are the data-grid cells per
    tile. `tiles_x` doubles as the reading-order line width, so a text body can
    lay its rings out against the SAME grid the renderer samples -- the single
    source of truth (`Globe.__init__` and the layout share `tile_grid`; a drifted
    copy would misalign the text against the surface it's drawn on).
    """

    tiles_x: int
    tiles_y: int
    div_x: float
    div_y: float


def tile_grid(W, H, radius, aspect, eye=DEFAULT_EYE):
    """Tile quantisation for a `W`x`H` data grid on a `radius` disc. Pure.

    The perspective magnification `mag` (see `Globe.__init__`) scales the grid so
    one tile ~ one screen cell at the disc centre. Extracted so `Globe` and the
    text body's ring layout compute `tiles_x`/`tiles_y` identically.
    """
    mag = math.sqrt(eye * eye - 1.0) / (eye - 1.0)
    div_y = max(1.0, H / (math.pi * radius * mag))
    div_x = max(1.0, W / (2.0 * math.pi * radius * aspect * mag))
    return TileGrid(
        tiles_x=max(1, round(W / div_x)),
        tiles_y=max(1, round(H / div_y)),
        div_x=div_x,
        div_y=div_y,
    )


class _ShellSample(NamedTuple):
    """Where the ray through one screen cell pierces ONE shell (AXIS A, per shell).

    Under the perspective projection the ray is slanted, so each shell it crosses
    lands at its own latitude AND its own depth -- unlike the old orthographic
    model where near and far shared a latitude row and only longitude differed.
    Everything here is fixed for the life of the globe (the texture rotates, the
    geometry does not); the renderer adds the current `angle` to `lon` each frame
    and does integer lookups, so no sqrt/asin/atan2 runs in the steady-state loop.

      * img_y / ty -- data-grid + surface-tile row for THIS shell's latitude.
      * shade_band -- AXIS C light band (0 = shadow/terminator, Z_LEVELS-1 = fully
        lit), from the Lambert term N.L on this shell's surface normal for a fixed
        light: the near wall lights an offset highlight fading to a shadow crescent,
        the far wall (facing away) lights only its limb arc -- both read as a lit
        sphere, not a flat disc.
      * lon -- base longitude (atan2(px, pz) of the pierce point); `angle` is added.
    """

    img_y: int
    ty: int
    shade_band: int
    lon: float


class _Cell(NamedTuple):
    """Precomputed, angle-independent geometry for one on-disc screen cell (AXIS A).

    Everything here is fixed for the life of the globe -- the sphere never moves
    in screen space, only the texture rotates underneath it.

    `shells` holds one `_ShellSample` per shell, front -> back, carrying that
    shell's own latitude/tile/depth/longitude (perspective slants the ray, so they
    genuinely differ per shell). `band` and `limb_keep` are the two quantities that
    stay SCREEN-radial and shared by every shell: `band` drives the AXIS D FILL
    dome (the `--fill-falloff` taper that rounds the void field with the ball --
    a screen-radius effect, not a depth one), and `limb_keep` is the AXIS D rim
    dissolve. Keeping those radial leaves each body's fill/void tuning untouched
    by the perspective change.

    `tx0`/`ty0` are the NEAR shell's fixed tile SLOT -- the front face reads text
    as a flat lattice so a whole sentence stays legible AND translates rigidly:

      * `tx0` -- a unit-slope column lattice (one tile per screen column, anchored
        so the disc-centre column shows longitude 0). Each snapped rotation step
        slides every glyph exactly whole cells, so a sentence's characters are
        never re-quantized (dropped/reshuffled) by the spherical cell->tile
        compression between steps.
      * `ty0` -- the tile ROW is constant across a whole screen row (the latitude
        ring at that row's meridian), so one screen row == one text ring, read
        left-to-right. Without this, `ty` would follow the true (curved) latitude
        and drift across the row, so the reading-order index would jump a whole
        line mid-word everywhere off the equator -- the text only read cleanly on
        the centre line. Vertical ring SPACING still follows the true sphere
        (rings compress toward the poles), so the front keeps its foreshortened
        read; only the within-row latitude is flattened to make text legible.

    Deeper shells keep the true per-cell spherical `lon`/`ty` sampling (the
    foreshortened, counter-scrolling 3D ghost) -- `tx0`/`ty0` are near-face only.
    """

    band: int  # radial band (0 = limb, Z_LEVELS-1 = centre) for the AXIS D dome
    limb_keep: int  # AXIS D LIMB per-cell keep (per-mille) from the exact z
    tx0: int  # near-shell tile-column slot (unit-slope screen-column lattice)
    ty0: int  # near-shell tile-row slot (constant per screen row = one ring)
    shells: tuple  # one _ShellSample per shell, front -> back


class _ResolvedMaterial(NamedTuple):
    """A `Material` with its opacity baked to an integer per-mille for the run.

    Color lives on the Globe (the theme/depth shade ramps), not per material, so
    this carries only shape: opacity, which glyph the tile draws, and relief.
    """

    opacity_permille: int  # int over 1000 so the hot loop avoids float math
    palette: str
    hashed: bool
    relief: int  # signed shade-band bias (negative = recessed/dimmer feature)


class _Mask(NamedTuple):
    """One AXIS D density void-mask: a stable dither that thins ink to true holes.

    `keep_at(cell)` returns this mask's per-mille keep for a cell -- either a
    PER-CELL precompute (LIMB -> cell.limb_keep) or a PER-BAND lookup (FILL ->
    keep_band[cell.band]); that one degree of freedom lets LIMB stay smooth while
    FILL stays cheap. `block` sets the grain (dither sampled on block x block tile
    blocks; 1 = per-tile). `soft` (0..1000) blends toward a per-tile jitter to rag
    block edges. The key offsets keep this mask (and its jitter) decorrelated.
    Ink survives iff its dither score is below keep for EVERY mask in the pipeline.
    """

    keep_at: object  # callable(cell) -> int per-mille keep
    block: int
    soft: int  # 0..1000 edge-softening weight
    kx: int
    ky: int
    jkx: int
    jky: int


class Globe:
    def __init__(
        self,
        surface,
        radius,
        aspect,
        bold_front=True,
        limb_fade=True,
        fill=1.0,
        fill_falloff=0.0,
        void_scale=1,
        void_soft=0.0,
        theme="dark",
        truecolor=False,
        eye=DEFAULT_EYE,
        far_dim=DEFAULT_FAR_DIM,
        far_fill=DEFAULT_FAR_FILL,
        light_az=DEFAULT_LIGHT_AZ,
        light_el=DEFAULT_LIGHT_EL,
        ambient=DEFAULT_AMBIENT,
    ):
        self.surface = surface
        self.W = surface.W
        self.H = surface.H
        self.grid = surface.grid
        self.radius = radius
        self.aspect = aspect
        # Perspective eye distance in sphere-radii; must sit outside the unit
        # sphere. Clamped just above 1 so an extreme value can't make the tangent
        # cone singular (1/sqrt(D^2-1) -> inf). Large values approach orthographic.
        self.eye = max(1.05, float(eye))

        # Directional-light unit vector (Axis C), fixed in screen space: x right,
        # y up, z toward the eye. Azimuth sweeps x->y; elevation tilts it toward the
        # viewer. Shade = ambient + (1 - ambient) * max(0, N . L) with N the unit
        # surface normal (the sphere point itself) -- precomputed per cell in
        # _build_cells, so the light costs nothing in the steady-state loop.
        az = math.radians(light_az)
        el = math.radians(light_el)
        cos_el = math.cos(el)
        self._light = (cos_el * math.cos(az), cos_el * math.sin(az), math.sin(el))
        self._ambient = max(0.0, min(1.0, float(ambient)))

        # Fail fast if the grid references a class code the surface never
        # declared: catch it once here with a clear message rather than a cryptic
        # per-frame KeyError deep in render()'s hot loop. A new procedural body
        # (Jupiter rasterizes its own grid) could otherwise ship a stray code and
        # crash only when that tile happens to be drawn.
        undeclared = set(self.grid) - set(surface.classes)
        if undeclared:
            raise ValueError(
                f"{surface.name}: grid contains undeclared class codes "
                f"{sorted(undeclared)} (declared: {sorted(surface.classes)})"
            )

        self.theme = theme if theme in THEMES else "dark"
        self.truecolor = bool(truecolor)

        # AXIS C -- the three shade ramps (pure light+theme cue, owned here, never
        # per material). Each ramp is a contrast envelope; the per-cell band that
        # indexes it is the directional-light term (N.L, precomputed in _build_cells).
        # The walk (render) picks the ramp by which branch stopped the ray: a solid
        # near stop -> NEAR-SOLID (bold, high contrast); a near screen-door stop ->
        # NEAR-SCREEN (normal, mid); any deeper stop -> FAR (normal, recessed). With
        # bold_front the near-solid front carries bold (1) so it advances; the others
        # assert normal intensity (22) so bold can't bleed onto them when the
        # renderer switches color runs without a reset.
        near_attr = "1" if bold_front else ""
        back_attr = "22" if bold_front else ""
        tc = self.truecolor
        near_solid_ramp = _shade_ramp(NEAR_SOLID_CONTRAST, self.theme, near_attr, tc)
        near_screen_ramp = _shade_ramp(NEAR_SCREEN_CONTRAST, self.theme, back_attr, tc)
        # `far_dim` (0..1) scales the far ramp's whole contrast span toward the
        # background. The terminal cannot alpha-blend the far layer under the near
        # one -- a cell holds a single glyph -- so recessing the back wall is done
        # in the only channel a grid has: grayscale contrast against the background.
        # The far wall is still lit (N.L grades its limb arc), just scaled down since
        # it is seen through the glass; lower `far_dim` pushes it further toward a
        # faint wash so it reads as depth, not a competing surface.
        far_dim = max(0.0, min(1.0, far_dim))
        far_lo, far_hi = FAR_CONTRAST
        far_ramp = _shade_ramp(
            (far_lo * far_dim, far_hi * far_dim), self.theme, back_attr, tc
        )

        # AXIS B -- the shell stack, front -> back. Each entry is
        # (solid_ramp, screen_ramp, keep_permille): the pair of ramps that shell may
        # draw on (solid stop, screen-door stop) plus a per-shell SPARSITY keep --
        # the fraction of that shell's own fragments that survive, as a stable
        # per-tile dither. The per-cell base longitudes live on _Cell.shells in the
        # same order. A hollow sphere is the two-shell near/far case: near draws
        # bold/dim, far is the dim ghost (solid == screen-door there). The stack is a
        # LIST so n > 2 (atmosphere, rings, nested shells) is a data change, not a
        # code change -- but we ship only the two concrete shells; no speculative
        # ramp-derivation machinery.
        #
        # `far_fill` (0..1) is the far shell's keep. The far wall is seen from behind,
        # so its texture counter-scrolls against the near face; at full density that
        # reads as a second surface fighting the front. This is body-agnostic: it
        # bites through ANY large window -- Earth's ocean is a ~71%-of-disc window,
        # not a sparse one, so its dense back wall drowns the continents just as it
        # does the text globe. Thinning it to a fraction (DEFAULT_FAR_FILL) turns
        # the back wall into a sparse dotted depth field welded to the far surface --
        # the closest a character grid gets to a translucent interior, since it
        # cannot actually blend the far glyph beneath the near one. The near shell
        # always keeps everything (keep 1000), so the front face is never thinned by
        # this (the Axis-D density masks are the separate, front-facing thinning).
        far_fill = max(0.0, min(1.0, far_fill))
        self._shells = [
            (near_solid_ramp, near_screen_ramp, 1000),  # near: full, never thinned
            (far_ramp, far_ramp, int(far_fill * 1000)),  # far ghost, sparse speckle
        ]
        # far_dim 0 or far_fill 0 => no back wall at all: truncate the walk to the
        # near shell, so a near-face gap exits straight to the background (front-face
        # only). The disc still reads as a sphere via the near shade + limb dissolve.
        if far_dim <= 0.0 or far_fill <= 0.0:
            self._shells = self._shells[:1]

        # AXIS A resolution: bake each Material to integer per-mille opacity. A
        # material's optical properties are its whole contract; the absolute shade
        # is the engine's business (the ramps above).
        self._materials = {
            code: _ResolvedMaterial(
                opacity_permille=int(max(0.0, min(1.0, m.opacity)) * 1000),
                palette=m.palette,
                hashed=m.hashed,
                relief=int(m.relief),
            )
            for code, m in surface.classes.items()
        }

        # Glyph resolution. The surface is sampled at the full data grid, far finer
        # than the screen, so we quantise into tiles. Each tile maps to one
        # character, fixed for the whole run, so rotation can only *transport* the
        # characters across the screen, not re-pick them.
        #
        # Tile size = one screen cell *at the disc centre*. On the NEAR face the
        # cell->tile map is a fixed unit-slope column lattice (_Cell.tx0): one
        # tile per screen column along each ring, so a scrolling sentence
        # translates rigidly -- a spherical (foreshortening) map would drop a
        # different character at each step where several tiles pile into one
        # cell, visibly reshuffling the text between steps. Curvature still
        # reads through the latitude rings, the limb dissolve, and the depth
        # shading; deeper shells keep the true spherical longitude sampling.
        # Consecutive tiles carry consecutive characters, so text just scrolls
        # sideways like a marquee (coherent) -- no anti-alias floor needed.
        #
        # PERSPECTIVE (AXIS A) magnifies the near hemisphere at the disc centre: a
        # longitude/latitude interval d(ang) maps to a screen-radius interval
        # `mag * d(ang)`, where mag = sqrt(D^2-1)/(D-1) is the on-axis magnification
        # of the near wall (D = eye distance; derivative of screen radius w.r.t.
        # angle at the centre). The ORTHOGRAPHIC circumference (2*pi*R*aspect) would
        # therefore under-count tiles by exactly `mag` -- one tile would span ~mag
        # screen cells at the centre, so every glyph draws `mag` times over (doubled
        # text) and the doubling migrates as the whole-tile rotation slides the
        # varying tile->cell width across the disc. Scaling the tile grid by `mag`
        # restores one tile ~ one screen cell at the centre. As D -> infinity mag ->
        # 1, recovering the orthographic count.
        # Tile counts over the full sphere, from the shared `tile_grid` (single
        # source of truth -- the text body lays its rings out against the same
        # grid). tiles_x is also the "line width" used to lay the source string
        # out in reading order. lon_per_tile is the angular width of one tile --
        # snapping the rotation step to a multiple of it makes the text scroll a
        # whole number of tiles per frame (clean marquee) instead of drifting
        # across tile boundaries.
        tg = tile_grid(self.W, self.H, radius, aspect, self.eye)
        self.glyph_div_x = tg.div_x
        self.glyph_div_y = tg.div_y
        self.tiles_x = tg.tiles_x
        self.tiles_y = tg.tiles_y
        self.lon_per_tile = 2.0 * math.pi / self.tiles_x

        # NEAR-shell class sampling is welded to the TILE, not the screen cell:
        # each tile reads the data grid at its own centre, via these two lookup
        # tables. Sampling at the cell instead (the old int(f*W) read) drifted a
        # fractional W/tiles_x per snapped step, so a tile's land/ocean class --
        # and with it a character of the front-face text -- could flip between
        # two steps. Per-tile sampling makes a glyph's drawn/window decision a
        # pure function of its tile: whole characters appear or clip, stably.
        self._tile_ix = [
            int((t + 0.5) * self.W / self.tiles_x) % self.W for t in range(self.tiles_x)
        ]
        self._tile_iy = [
            min(self.H - 1, int((t + 0.5) * self.H / self.tiles_y))
            for t in range(self.tiles_y)
        ]

        # The drawing canvas is a little larger than the disc (by HALO_PAD) so it
        # never sits flush against (and clipped by) an edge. The disc is sized
        # well inside it (see fit_radius/disc_radius) so the globe floats with margin.
        self.cols = int(round(radius * 2 * aspect * HALO_PAD))
        self.rows = int(round(radius * 2 * HALO_PAD))

        # Precompute the per-cell geometry once. Each frame only adds `angle`.
        self._cells = self._build_cells()

        # LOSSLESS reading-order packing (near shell). A reading-order text palette
        # is laid across the surface skipping WINDOW-class tiles (opacity 0): the
        # stream advances only on drawable tiles, so a character is never consumed
        # by a hole and silently lost. This turns a window into a lossless SPLIT
        # rather than a lossy CHOP -- Earth's ocean splits the README across the
        # continents (a word interrupted by a coastline resumes intact on the next
        # land tile) instead of chopping the glyphs the ocean happened to cover.
        # It is a strict generalization of the old `ty*tiles_x + tx` index: a body
        # with NO window class (the text ball -- one opaque class) skips nothing,
        # so `_packed_near` IS that identity and its output is byte-for-byte
        # unchanged. Computed per surface tile in reading order (row-major: each
        # latitude ring left-to-right, then down), so the glyph stays welded to its
        # tile and transports rigidly under rotation, exactly like the raw index.
        packed = []
        counter = 0
        for ty in range(self.tiles_y):
            base = self._tile_iy[ty] * self.W
            for tx in range(self.tiles_x):
                code = self.grid[base + self._tile_ix[tx]]
                if self._materials[code].opacity_permille == 0:
                    packed.append(-1)  # window class: undrawn, consumes no char
                else:
                    packed.append(counter)
                    counter += 1
        self._packed_near = packed

        # AXIS D -- the density void-mask pipeline (built after _cells so FILL can
        # be a per-band array indexed by the precomputed band). Ink survives iff it
        # passes every mask. Two default masks, at deliberately different grains:
        self._density_masks = self._build_density_masks(
            limb_fade, fill, fill_falloff, void_scale, void_soft
        )

    def _build_density_masks(
        self, limb_fade, fill, fill_falloff, void_scale, void_soft
    ):
        """Assemble the AXIS D void-mask pipeline (LIMB per-cell + FILL per-band).

        LIMB and FILL are the same *concept* (thin-to-void, erasing to a true hole)
        but genuinely different *grains* -- a single dither draw fixes one grain --
        so density is a pipeline of independent masks, not one scalar. Each mask
        self-configures out of the list when it would be a no-op, so the hot loop
        pays only for the masks that actually thin.
        """
        masks = []

        # LIMB -- fine grain (block=1), per-cell keep from the exact z. The
        # dissolve lives entirely in the outermost ~3 bands, so a per-band bake
        # would step the horizon in ~3 jumps; a per-cell keep fades it smoothly.
        # `limb_fade=False` OMITS the mask (it does not linger as a no-op keep).
        if limb_fade:
            masks.append(
                _Mask(
                    keep_at=lambda cell: cell.limb_keep,
                    block=1,
                    soft=0,
                    kx=LIMB_KX,
                    ky=LIMB_KY,
                    jkx=LIMB_JKX,
                    jky=LIMB_JKY,
                )
            )

        # FILL -- coarse grain (block=void_scale), per-band keep baked from fill +
        # fill_falloff: centre band = fill*1000, tapering to fill*(1-falloff)*1000
        # at the limb, so the void field rounds with the ball. Per-band is fine
        # here because fill grades slowly across the whole disc. `void_soft` blends
        # a per-tile jitter into the block decision to rag the block edges.
        fill_thresh = int(max(0.0, min(1.0, fill)) * 1000)
        f = max(0.0, min(1.0, fill_falloff))
        edge = int(round(fill_thresh * (1.0 - f)))
        keep_band = [
            edge + int(round((fill_thresh - edge) * (i / (Z_LEVELS - 1))))
            for i in range(Z_LEVELS)
        ]
        # fill=1 with falloff=0 makes every band 1000 (keep everything): the mask
        # is a pure no-op, so it self-elides rather than costing a hash per cell.
        if any(k < 1000 for k in keep_band):
            masks.append(
                _Mask(
                    keep_at=lambda cell: keep_band[cell.band],
                    block=max(1, int(void_scale)),
                    soft=int(max(0.0, min(1.0, void_soft)) * 1000),
                    kx=FILL_KX,
                    ky=FILL_KY,
                    jkx=FILL_JKX,
                    jky=FILL_JKY,
                )
            )
        return masks

    def _build_cells(self):
        """Precompute the angle-independent geometry for every screen cell (AXIS A).

        Returns a grid (list of rows, each a list of `_Cell | None`) where None
        marks an off-disc cell (drawn blank). This runs once and is the whole
        PERSPECTIVE model: the eye sits at (0, 0, D) with D = self.eye, looking
        down -z at the unit sphere. A screen cell maps to a point on the disc
        (nx, ny in [-1, 1]); the ray from the eye through it is cast so that the
        disc edge (d = 1) is exactly the tangent cone of the sphere -- so the
        silhouette is the same circle for any D and the footprint math is
        unchanged. The ray pierces the sphere at two depths (the near root and the
        far root of |E + t*dir|^2 = 1); because the ray is slanted, those two
        points sit at DIFFERENT latitudes and longitudes, and the far hemisphere
        is foreshortened toward the centre -- the source of the true 3D read. As
        D -> infinity the rays become parallel and this collapses to the old
        orthographic near = (x, y, +z) / far = (x, y, -z).

        `z` and the depth `t` are used only here -- to derive per-shell latitude,
        longitude, and the surface normal (which feeds the directional-light shade
        band), plus the radial band + limb keep -- and never enter the steady-state
        loop.
        """
        rscale_x = self.radius * self.aspect
        rscale_y = self.radius
        half_c = self.cols / 2.0
        half_r = self.rows / 2.0
        height = self.H

        # Perspective constants (all from the eye distance D). tan_alpha is the
        # tangent of the sphere's angular radius (sin_alpha = 1/D), so a screen
        # radius d maps to a ray angle theta with tan(theta) = d * tan_alpha and
        # d = 1 lands exactly on the tangent (theta = alpha). The two ray roots give
        # the near/far surface points; their shade now comes from the directional
        # light (N . L), not the along-ray depth, so no depth-span normalisation is
        # needed here any more.
        D = self.eye
        tan_alpha = 1.0 / math.sqrt(D * D - 1.0)

        lx, ly, lz = self._light
        ambient = self._ambient
        light_gain = 1.0 - ambient

        def _sample(t, dx, dy):
            """Build a `_ShellSample` for one root `t` of the ray (dir dx,dy,dz)."""
            px = t * dx
            py = t * dy
            pz = D - t * cos_t  # dz = -cos_t, so pz = D + t*dz
            lat = math.asin(max(-1.0, min(1.0, py)))
            colat = (math.pi / 2 - lat) / math.pi  # 0 at N pole .. 1 at S pole
            img_y = int(colat * height)
            img_y = 0 if img_y < 0 else height - 1 if img_y >= height else img_y
            ty = int(colat * self.tiles_y)
            ty = 0 if ty < 0 else self.tiles_y - 1 if ty >= self.tiles_y else ty
            # Shade band from directional light: on the unit sphere the point
            # (px, py, pz) IS the surface normal, so N . L is the Lambert term.
            # Clamp the back-facing half to 0 (terminator), floor with ambient, and
            # map [0, 1] across the ramp. The near wall's normal faces the eye so a
            # front light lights its centre-ish highlight and shadows the far side;
            # the far wall's normal faces away, so its centre falls into shadow and
            # only its limb arc (curving toward the light) lights -- the back reads
            # as a lit sphere too, not a flat wash.
            ndotl = px * lx + py * ly + pz * lz
            lit = ambient + light_gain * (ndotl if ndotl > 0.0 else 0.0)
            band = int(lit * (Z_LEVELS - 1) + 0.5)
            band = 0 if band < 0 else Z_LEVELS - 1 if band >= Z_LEVELS else band
            return _ShellSample(img_y, ty, band, math.atan2(px, pz))

        def _meridian_ty(nyd):
            """Near-shell tile ROW at this screen row's meridian (nx = 0).

            One value per screen row, used for EVERY cell in the row (see
            _Cell.ty0), so a screen row is one text ring read left-to-right. The
            vertical spacing of these rings still follows the true sphere (this
            is the real latitude at the meridian), so the front stays
            foreshortened; only the within-row latitude drift is flattened.
            """
            d = abs(nyd)
            if d >= 1.0:  # row's centre is off-disc; value unused (all cells None)
                d = 1.0
            theta = math.atan(d * tan_alpha)
            sin_t = math.sin(theta)
            cos_t = math.cos(theta)
            dy = sin_t * (-nyd / d) if d > 0.0 else 0.0  # nx=0 -> azimuth is +/-y
            t_near = D * cos_t - math.sqrt(max(0.0, 1.0 - D * D * sin_t * sin_t))
            py = t_near * dy
            lat = math.asin(max(-1.0, min(1.0, py)))
            colat = (math.pi / 2 - lat) / math.pi
            ty = int(colat * self.tiles_y)
            return 0 if ty < 0 else self.tiles_y - 1 if ty >= self.tiles_y else ty

        grid = []
        for r in range(self.rows):
            ny_down = (r + 0.5 - half_r) / rscale_y
            ty0 = _meridian_ty(ny_down)
            row = []
            for c in range(self.cols):
                nx = (c + 0.5 - half_c) / rscale_x
                d2 = nx * nx + ny_down * ny_down
                if d2 > 1.0:
                    row.append(None)  # off-disc -> blank
                    continue
                d = math.sqrt(d2)

                # Ray from the eye through this screen point. theta = angle off the
                # view axis; azimuth taken from (nx, y_up) so screen up = sphere up.
                theta = math.atan(d * tan_alpha)
                sin_t = math.sin(theta)
                cos_t = math.cos(theta)
                if d > 0.0:
                    cphi = nx / d  # cos(azimuth)
                    sphi = -ny_down / d  # sin(azimuth); y_up = -ny_down
                else:
                    cphi = sphi = 0.0
                dx = sin_t * cphi
                dy = sin_t * sphi

                # Two roots of |E + t*dir|^2 = 1 (disc = 1 - D^2 sin^2(theta) >= 0
                # for d <= 1). Near = the smaller t, far = the larger.
                root = math.sqrt(max(0.0, 1.0 - D * D * sin_t * sin_t))
                t_near = D * cos_t - root
                t_far = D * cos_t + root

                # Radial band for the AXIS D dome (screen-radius, shell-shared):
                # (1 - d) peaks at the centre. Distinct from the per-shell depth
                # band above, which drives the shade.
                band = int((1.0 - d) * (Z_LEVELS - 1) + 0.5)
                band = 0 if band < 0 else Z_LEVELS - 1 if band >= Z_LEVELS else band

                # AXIS D LIMB per-cell keep from the near-shell foreshortening
                # z = sqrt(1 - d^2): full keep above EDGE_FADE, tapering to 0 at
                # the silhouette so the rim dissolves smoothly (a screen effect,
                # so it stays keyed to d, not the perspective depth).
                z = math.sqrt(1.0 - d2)
                if z >= EDGE_FADE:
                    limb_keep = 1000
                else:
                    limb_keep = int(round(z / EDGE_FADE * 1000))

                # NEAR-shell column lattice: one tile per screen column, the
                # disc-centre column anchored to longitude 0 (tile tiles_x/2).
                # Rotation adds whole tiles (see render), so the front face's
                # glyphs translate rigidly -- no per-step re-quantization.
                tx0 = (self.tiles_x // 2 + c - self.cols // 2) % self.tiles_x

                row.append(
                    _Cell(
                        band=band,
                        limb_keep=limb_keep,
                        tx0=tx0,
                        ty0=ty0,
                        shells=(_sample(t_near, dx, dy), _sample(t_far, dx, dy)),
                    )
                )
            grid.append(row)
        return grid

    def _pick(self, palette, hashed, tx, ty):
        """Glyph for a tile from `palette` (AXIS A <-> B seam).

        Reading-order index (so source text reads across the surface) unless
        `hashed` (a class with no reading order, e.g. a rendered texture), in which
        case the tile is hashed into the palette. Fixed per tile either way, so
        rotation transports the glyph rather than re-picking it. A blank is only
        producible by a reading-order palette that contains spaces; a hashed
        palette carries no space (the Material data contract), so a texture is
        guaranteed non-transparent.
        """
        if hashed:
            return palette[_hash2(tx, ty) % len(palette)]
        return palette[(ty * self.tiles_x + tx) % len(palette)]

    def render(self, angle):
        """Render one frame: shell walk (B) -> shade (C) -> density pipeline (D).

        For each on-disc cell, walk the shell stack front -> back (AXIS B): sample
        each shell's tile (AXIS A) and pick its glyph, then let opacity decide. A
        solid stop (opacity >= 1, incl. a per-tile ink glyph of a text material)
        short-circuits -- it occludes, drawn BOLD on the near ramp, and no deeper
        shell is sampled. A screen-door stop (0 < opacity < 1 and its stable
        per-tile dither fires) draws DIM on that shell's screen ramp. A stop may then
        be thinned by the shell's own SPARSITY keep (`far_fill` on the far shell) --
        a stable per-tile dither that lets only a fraction survive, so the far wall
        becomes a sparse dotted depth field instead of a dense counter-scrolling
        surface. Otherwise (blank tile, missed screen-door, or thinned) the ray
        passes through to the next shell; if none stop, it exits to a true HOLE.

        The fragment's gray (AXIS C) rides the ramp the winning branch chose,
        shifted by the material's relief. Finally the density void-masks (AXIS D)
        may thin the drawn ink to a true hole (limb dissolve at a fine grain, fill
        void at a coarse grain). Geometry is fixed per cell -- only `angle` moves
        the texture -- so the glued glyphs stay welded to the surface as they spin.
        """
        # Locals for the hot loop -- avoids attribute lookups per cell.
        grid = self.grid
        materials = self._materials
        W = self.W
        tiles_x = self.tiles_x
        tile_ix = self._tile_ix
        tile_iy = self._tile_iy
        # Whole tiles of rotation. The loop's step is already snapped to
        # lon_per_tile multiples (resolve_step); rounding here means even an
        # unsnapped caller gets whole-tile motion -- the marquee never lands
        # between tiles.
        k = round(angle / self.lon_per_tile)
        shells = self._shells
        density_masks = self._density_masks
        pick = self._pick
        packed = self._packed_near  # lossless near-shell reading-order index
        two_pi = 2.0 * math.pi
        pi = math.pi
        okx = OKX
        oky = OKY
        salt = SHELL_SALT
        farkx = FARKX
        farky = FARKY
        zmax = Z_LEVELS - 1  # clamp bound for per-material relief band shifts
        out = []

        for row in self._cells:
            buf = []
            cur = ""  # color escape currently active on this row ("" = default)
            for cell in row:
                if cell is None:
                    glyph, color = " ", ""
                else:
                    cell_shells = cell.shells

                    # ---- AXIS B: walk the shells front -> back, first hit wins ----
                    # Each shell has its OWN latitude/tile row + light band
                    # (perspective slants the ray), so the sample is read per shell.
                    drawn = None
                    for s, (solid_ramp, screen_ramp, keep) in enumerate(shells):
                        smp = cell_shells[s]
                        if s == 0:
                            # NEAR shell: flat, rigid marquee. The tile is the
                            # cell's fixed (column, ring) slot + whole tiles of
                            # rotation, and the class is read at that TILE's own
                            # centre. ty0 is constant across the screen row (one
                            # ring per row), so a sentence reads left-to-right;
                            # tx0+k slides it whole tiles per step -- so between
                            # two steps every front glyph (and its drawn/window
                            # decision) just translates, never re-quantizes.
                            tx = (cell.tx0 + k) % tiles_x
                            ty = cell.ty0
                            m = materials[grid[tile_iy[ty] * W + tile_ix[tx]]]
                        else:
                            # Deeper shells: true per-cell spherical sampling --
                            # the far wall stays the foreshortened, counter-
                            # scrolling 3D ghost.
                            ty = smp.ty
                            f = (smp.lon + angle + pi) / two_pi
                            tx = int(f * tiles_x) % tiles_x
                            ix = int(f * W) % W
                            m = materials[grid[smp.img_y * W + ix]]
                        if m.opacity_permille == 0:
                            continue  # pure window: no glyph, ray passes through
                        if s == 0 and not m.hashed:
                            # NEAR reading-order text: index the palette by the
                            # LOSSLESS packed count (skips window tiles), so ocean
                            # SPLITS the stream across continents rather than
                            # chopping characters. `packed[...]` is >= 0 here (the
                            # opacity-0 window tiles were skipped just above).
                            g = m.palette[packed[ty * tiles_x + tx] % len(m.palette)]
                        else:
                            g = pick(m.palette, m.hashed, tx, ty)
                        # A blank in a reading-order palette contributes per-tile
                        # opacity 0 -- a window (this is how text spaces become the
                        # see-through "ocean"). A hashed palette never yields one.
                        opacity = 0 if g == " " else m.opacity_permille
                        if opacity >= 1000:
                            ramp = solid_ramp  # solid stop: occludes, drawn bold
                        elif (
                            opacity > 0
                            and _hash2(tx + okx + s * salt, ty + oky) % 1000 < opacity
                        ):
                            ramp = screen_ramp  # screen-door stop: dim texture
                        else:
                            continue  # blank tile or screen-door missed -> pass through
                        # Per-shell SPARSITY (Axis B): thin this shell's own fragments
                        # to `keep`, stable per surface-tile so the survivors are
                        # welded to the shell and transported by rotation. Near keeps
                        # everything (keep 1000 -> guard skipped); the far shell's
                        # `far_fill` turns its counter-scrolling wall into a sparse
                        # dotted depth field. A thinned far tile passes through, so the
                        # last shell -> a true hole (background), not a drawn glyph.
                        if keep < 1000 and (
                            _hash2(tx + farkx + s * salt, ty + farky) % 1000 >= keep
                        ):
                            continue
                        drawn = (ramp, g, m.relief, tx, ty, smp.shade_band)
                        break

                    if drawn is None:
                        glyph, color = " ", ""  # ray exited the back: a true hole
                    else:
                        ramp, glyph, relief, tx, ty, shade_band = drawn
                        # ---- AXIS C: shade by the winning fragment's LIGHT band
                        # (Lambert N.L on its normal), shifted by relief ----
                        nz = shade_band + relief
                        color = ramp[0 if nz < 0 else zmax if nz > zmax else nz]

                        # ---- AXIS D: density void-masks (thin ink to true holes) ----
                        for M in density_masks:
                            score = (
                                _hash2(tx // M.block + M.kx, ty // M.block + M.ky)
                                % 1000
                            )
                            if M.soft:
                                jit = _hash2(tx + M.jkx, ty + M.jky) % 1000
                                score = (score * (1000 - M.soft) + jit * M.soft) // 1000
                            if score >= M.keep_at(cell):
                                glyph, color = " ", ""  # thinned to a void
                                break

                # Emit a color escape only when the run changes, not per glyph.
                if color != cur:
                    buf.append(color if color else RESET)
                    cur = color
                buf.append(glyph)
            if cur:
                buf.append(RESET)  # leave the terminal in its default color
            out.append("".join(buf))
        return "\n".join(out)


# ---------------------------------------------------------------------------
# The plan: pure config/output value types + the terminal-sizing math
# ---------------------------------------------------------------------------
# A `Config` (terminal-agnostic render request) plus a `Surface` become a `Plan`
# (a prepared, inert spin) via the shell's `prepare`. The math that sizes the disc
# to a rows*cols terminal is PURE and lives here -- callers in the shell read the
# live terminal size and inject it, so nothing here touches the terminal. The
# `Config`/`Plan` types are core citizens: a value in, a value out, no effects.


class Config(NamedTuple):
    """Terminal-agnostic render config -- the plan's input boundary.

    A plain value object the shell's `resolve_request` builds from a parsed
    argparse Namespace, so the core (and `prepare`) never sees argparse. `theme`
    and `truecolor` are already RESOLVED here (no "auto"): the shell probes the
    terminal and passes the concrete values in. (Formerly `RenderRequest`.)
    """

    aspect: float
    scale: float
    radius: int
    bold_front: bool
    limb_fade: bool
    far_dim: float
    far_fill: float
    light_az: float
    light_el: float
    ambient: float
    fill: float
    fill_falloff: float
    void_scale: int
    void_soft: float
    eye: float
    theme: str
    truecolor: bool
    speed: float
    fps: float
    frames: int
    preview: bool


class Plan(NamedTuple):
    """A prepared, ready-to-run spin: a sized `Globe`, its rotation `step` and
    frame `delay`, the `frames` budget (0 = forever), and a `rebuild` closure that
    re-fits the globe to the current terminal on resize (None when `--radius` pins
    the footprint). A driver (`run_loop`) consumes this; it is inert data until
    then. (Formerly `Session`.)"""

    globe: "Globe"
    step: float
    delay: float
    frames: int
    rebuild: Optional[Callable[..., "Globe"]]


def resolve_step(globe):
    """Per-frame rotation `step`, snapped to whole tiles for legible text.

    We always snap the step to a whole number of glyph tiles, so the surface
    advances a whole character per frame instead of drifting across tile
    boundaries -- a clean marquee. (A mixed body -- hashed-texture classes over
    reading-order text -- shares one tile grid, so the snap serves both.)
    """
    return max(1, round(BASE_SPEED / globe.lon_per_tile)) * globe.lon_per_tile


def disc_radius(rows, cols, aspect, footprint=0.6):
    """Pure disc radius that leaves clear margin in a rows*cols terminal.

    `footprint` is the fraction of the binding axis the disc occupies (a screen
    FOOTPRINT fraction -- distinct from `Globe`'s ink `fill`). The rendered disc
    is then padded by HALO_PAD for the halo (see Globe), so with footprint=0.6 the
    whole globe occupies roughly two-thirds of the binding axis -- comfortably
    inside the screen even if the terminal under-reports its usable height (prompt
    line, status bars, scroll). Pure: the shell reads the live terminal size and
    passes it in (via `prepare`/`fit_globe`).
    """
    r_by_rows = (rows - 2) / 2.0
    r_by_cols = (cols / aspect) / 2.0
    return max(5, int(min(r_by_rows, r_by_cols) * footprint))


def fit_radius(rows, cols, *, aspect=2.3, scale=1.0, radius=0, fullscreen=False):
    """The disc radius `fit_globe` will use for a rows*cols terminal. Pure.

    An explicit `radius` (> 0) pins the footprint; otherwise `disc_radius` fits
    the disc to the terminal (`footprint_frac` = the disc's screen FOOTPRINT, 0.87
    full-screen vs. 0.6 framed), then `scale` multiplies it (min 5). Extracted so
    a body's surface factory can size its layout to the SAME radius the globe will
    be built at.
    """
    footprint_frac = 0.87 if fullscreen else 0.6
    r = radius or disc_radius(rows, cols, aspect, footprint_frac)
    return max(5, int(r * scale))


def fit_globe(
    surface,
    rows,
    cols,
    *,
    aspect=2.3,
    scale=1.0,
    radius=0,
    fullscreen=False,
    **globe_kwargs,
):
    """Build a `Globe` sized to a rows*cols terminal (pure -- size injected).

    Holds the disc-sizing math shared by every app (via `fit_radius`): an
    explicit `radius` (> 0) pins the footprint, otherwise the disc fits the given
    terminal size, then `scale` multiplies it (min 5). `fullscreen` maximises the
    disc to the binding axis; framed leaves the ~60% margin default. The ink
    knobs (fill, fill_falloff, void_scale, void_soft, bold_front, limb_fade,
    theme, truecolor) pass straight through in `globe_kwargs`.

    `surface` may be a fixed `Surface` OR a pure factory `radius -> Surface`
    (called with the fitted radius) -- the seam a size-dependent layout uses.

    Recompute-friendly: the shell's resize (SIGWINCH) or full-screen toggle just
    calls this again with the new size + `fullscreen`, and it re-fits.
    """
    r = fit_radius(
        rows, cols, aspect=aspect, scale=scale, radius=radius, fullscreen=fullscreen
    )
    if callable(surface):
        # A body may inject a surface FACTORY (radius -> Surface) instead of a
        # fixed Surface, so a size-dependent layout (the text body's sentence
        # rings) can rebuild against the just-computed radius. Invoked on every
        # fit, including the resize / full-screen rebuild -- which is exactly
        # what re-lays-out the rings per size. The factory must be pure.
        surface = surface(r)
    return Globe(surface, r, aspect, **globe_kwargs)


def center_frame(frame, canvas_cols, canvas_rows, term_cols, term_rows, footer_rows=2):
    """Pad a rendered frame so the globe sits centred in a term_cols*term_rows
    terminal (pure -- size injected).

    Padding is clamped so the total never exceeds the screen: the globe always
    floats inside the view with margin rather than overflowing. The shell reads
    the live terminal size (following resizes) and passes it in.
    """
    left = max(0, (term_cols - canvas_cols) // 2)
    top = max(0, (term_rows - footer_rows - canvas_rows) // 2)
    pad = " " * left
    body = "\n".join(pad + ln for ln in frame.split("\n"))
    return "\n" * top + body, pad


def frame_delay(fps, speed):
    """Seconds per frame from `fps` and a `speed` ratio (0 => no delay). Pure."""
    speed = speed if speed > 0 else 1.0
    return (1.0 / fps) / speed if fps > 0 else 0.0
