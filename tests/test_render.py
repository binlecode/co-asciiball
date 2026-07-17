"""Regression tests for the shared ASCII-sphere engine and its bodies.

These exercise the REAL render path end to end -- no mocks, no fabricated data.
They are PROPERTY / structural tests: they assert invariants of the four-axis
compositing model (see docs/TODO-...-engine-core-compositing-model.md) through the
public API, rather than byte-for-byte goldens. The goldens are intentionally
deferred: the engine's output changes with the new model, and the bodies are
re-tuned + re-blessed in a separate pass, so chasing the old bytes here would be
noise. Coverage:

  * Determinism / periodicity: `render(angle)` is pure; a full revolution returns
    to frame 0.
  * The material model: opacity drives occlusion (solid stop / window / true hole)
    and prominence; relief is a per-material depth shift.
  * Self-consistency: each body renders identically from its implicit defaults and
    the same values passed explicitly (so a default can't silently drift), and the
    void knobs are inert at the flat, fully-inked fill.
  * Color: 256-indexed by default, valid 24-bit gray under truecolor.

Run via pytest.
"""

import re
import sys
import subprocess
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parent.parent / "src"

# Pinned, deterministic render inputs (independent of terminal size + README).
GLYPHS = "#%@&$MBNREW8"
RADIUS = "20"
ASPECT = "2.3"

# Earth's geo-specific tuning -- no radial dropout (sentences stay hole-free; the
# ball form comes from shade + limb dissolve + the sentence-gap/ocean windows).
EARTH_DEFAULTS = [
    "--fill",
    "1.0",
    "--fill-falloff",
    "0.0",
    "--void-scale",
    "2",
    "--void-soft",
    "0.6",
    "--far-dim",
    "1.0",
    "--far-fill",
    "0.85",
]


def _preview_cmd(script, extra):
    return [
        sys.executable,
        str(MODULE_DIR / script),
        "--preview",
        "--glyphs",
        GLYPHS,
        "--radius",
        RADIUS,
        "--aspect",
        ASPECT,
        # Pin the theme so goldens don't depend on the dev's terminal / $COLORFGBG
        # (--preview is non-TTY, so the OSC 11 query is skipped regardless).
        "--theme",
        "dark",
        *extra,
    ]


def _render_preview(script, extra):
    """Run a body's real CLI `--preview` and return its stdout (the frames)."""
    proc = subprocess.run(
        _preview_cmd(script, extra),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, f"{script} exited {proc.returncode}:\n{proc.stderr}"
    return proc.stdout


def test_earth_defaults_unchanged():
    """Earth renders identically whether its tuned defaults are taken implicitly
    or passed explicitly -- i.e. the shipped defaults are still fill=1.0,
    fill-falloff=0, void-scale=2, void-soft=0.6, far-dim=1.0, far-fill=0.85 -- so
    a default can't silently drift out from under the golden (which runs on the
    implicit defaults)."""
    assert _render_preview("rotating_earth.py", []) == _render_preview(
        "rotating_earth.py", EARTH_DEFAULTS
    )


def _rigid_step_mismatches(globe):
    """Count front-face glyphs that fail to translate rigidly across one snapped
    rotation step. Each screen row is one text ring (constant `ty0`), so for every
    pair of on-disc cells `tps` columns apart in a row, the glyph at the later step
    must equal the glyph the earlier step drew at the upstream cell -- the marquee
    contract: characters (and their drawn/window clipping) transport whole along
    the row, never re-quantize. Returns (checked, mismatches). (Run with limb_fade
    off so the rim dissolve -- a screen effect, correctly NOT rigid -- doesn't
    count against the invariant.)"""
    import ascii_sphere

    step = ascii_sphere.resolve_step(globe)
    tps = round(step / globe.lon_per_tile)  # whole tiles per step
    f0 = _strip_ansi(globe.render(0.0)).split("\n")
    f1 = _strip_ansi(globe.render(-step)).split("\n")  # the loop spins angle down
    checked = mismatches = 0
    for r, cells in enumerate(globe._cells):
        for c, cell in enumerate(cells):
            if cell is None:
                continue
            c_prev = c - tps
            if c_prev < 0:
                continue
            prev = cells[c_prev]
            if prev is None or prev.ty0 != cell.ty0:
                continue  # off-disc or a different ring: nothing to transport
            checked += 1
            if f1[r][c] != f0[r][c_prev]:
                mismatches += 1
    return checked, mismatches


def test_sentence_marquee_is_step_stable():
    """Between two snapped steps a sentence must not have shifting characters:
    on an all-land text globe (no mask boundaries, no density thinning) every
    front-face glyph translates rigidly along its ring -- zero re-picked or
    dropped characters. This is the property the old spherical cell->tile
    quantization broke (different chars squeezed out at each step)."""
    import ascii_sphere

    surface = ascii_sphere.Surface(
        name="Text",
        provenance="test",
        W=1440,
        H=720,
        grid=bytearray([1] * (1440 * 720)),
        classes={1: ascii_sphere.Material(opacity=1.0, palette=GLYPHS)},
    )
    globe = ascii_sphere.Globe(
        surface, 14, 2.3, limb_fade=False, fill=1.0, fill_falloff=0.0, far_dim=0.0
    )
    checked, mismatches = _rigid_step_mismatches(globe)
    assert checked > 200, "degenerate geometry: almost nothing compared"
    assert mismatches == 0, f"{mismatches}/{checked} front-face glyphs re-quantized"


def test_front_face_rows_read_as_consecutive_text():
    """Each screen row is ONE text ring, so a row's front-face glyphs are a
    consecutive slice of the reading-order source -- the char/word flow reads
    left-to-right at every latitude, not just the equator. On an all-land text
    globe (no ocean gaps), within any drawn run the reading-order index must step
    by +1 from cell to cell; a spherical `ty` that drifted across the row would
    inject whole-line jumps mid-word (the bug this asserts against). Checked at a
    high, off-equator row where the old mapping garbled worst."""
    import ascii_sphere

    palette = "".join(chr(33 + (i % 90)) for i in range(4000))  # distinct, space-free
    surface = ascii_sphere.Surface(
        name="Text",
        provenance="test",
        W=1440,
        H=720,
        grid=bytearray([1] * (1440 * 720)),
        classes={1: ascii_sphere.Material(opacity=1.0, palette=palette)},
    )
    globe = ascii_sphere.Globe(
        surface, 20, 2.3, limb_fade=False, fill=1.0, fill_falloff=0.0, far_dim=0.0
    )
    tiles_x = globe.tiles_x
    consecutive = pairs = 0
    for cells in globe._cells:
        prev_idx = None
        for cell in cells:
            if cell is None:
                prev_idx = None
                continue
            idx = cell.ty0 * tiles_x + (cell.tx0 % tiles_x)
            if prev_idx is not None:
                pairs += 1
                if idx == prev_idx + 1:
                    consecutive += 1
            prev_idx = idx
    # Every adjacent on-disc pair in a row is consecutive text (flat ring lattice):
    # allow only the tiny fraction at the exact longitude wrap (tx0 % tiles_x rolls
    # over) to break the +1.
    assert pairs > 1000
    assert consecutive / pairs > 0.98, (
        f"only {consecutive}/{pairs} adjacent cells read as consecutive text"
    )


def test_earth_land_clipping_is_step_stable():
    """The land/ocean clipping is welded to the glyph tile: on Earth (far wall
    off, so ocean windows are bare holes) each front-face cell -- drawn char or
    clipped blank alike -- translates rigidly across a step. The old per-cell
    mask sampling drifted a fractional data-column per step, flipping coastline
    characters in and out between two steps."""
    import ascii_sphere
    import rotating_earth as re_body

    surface = re_body.make_surface(GLYPHS)
    globe = ascii_sphere.Globe(
        surface, 14, 2.3, limb_fade=False, fill=1.0, fill_falloff=0.0, far_dim=0.0
    )
    checked, mismatches = _rigid_step_mismatches(globe)
    assert checked > 200
    assert mismatches == 0, f"{mismatches}/{checked} coastline cells flickered"


def test_glyph_source_sentence_gaps_and_word_dots(tmp_path):
    """shell.load_glyphs builds a sentence-shaped palette (reading a real file and
    delegating the parse to the core's pure glyphs_from_text): word gaps inside a
    sentence fill with the word-sep dot (a sentence is a hole-free opaque run --
    the background shell cannot show through it), and only the gaps AFTER sentence
    terminators become real spaces (per-tile windows, the one place the far
    shell shows through the text)."""
    import shell

    src = tmp_path / "source.txt"
    src.write_text("One two. Three  four!\nFive six? Seven", encoding="utf-8")

    glyphs = shell.load_glyphs(str(src))
    assert glyphs == "One·two.  Three·four!  Five·six?  Seven"

    # Spaces (windows) appear ONLY right after a sentence terminator; every
    # other word boundary is the opaque middle dot.
    for i, ch in enumerate(glyphs):
        if ch == " ":
            before = glyphs[:i].rstrip(" ")
            assert before[-1] in ".!?…", (
                f"window not at a sentence gap: …{glyphs[: i + 1]!r}"
            )

    # --no-word-sep runs words together, but sentence gaps stay: they are
    # structural windows, not word decoration.
    packed = shell.load_glyphs(str(src), word_sep="")
    assert packed == "Onetwo.  Threefour!  Fivesix?  Seven"


def test_full_flat_fill_ignores_void_knobs():
    """At --fill 1.0 with --fill-falloff 0 every radial band sits at the full keep
    rate, so no cell is ever dropped and the void granularity/softening knobs
    can't matter -- the backward-compatible flat, fully-inked path. (With a
    non-zero falloff the rim DOES thin even at fill 1.0, which is the dome working
    as intended, so this identity is specifically the falloff-0 case.)"""
    base = ["--fill", "1.0", "--fill-falloff", "0"]
    crisp = _render_preview(
        "rotating_earth.py", base + ["--void-scale", "1", "--void-soft", "0"]
    )
    blocky = _render_preview(
        "rotating_earth.py", base + ["--void-scale", "5", "--void-soft", "1.0"]
    )
    assert crisp == blocky


def test_rotation_periodicity():
    """After a whole revolution (tiles_x wrapped steps) the globe returns to frame
    0. The live loop accumulates `angle = (angle - step) % 2pi`, so the wrap is
    not bit-exactly -2pi and a few cells on tile boundaries may differ by float
    epsilon; assert the residual is tiny rather than demanding exact equality."""
    import math

    import ascii_sphere
    import rotating_earth as re

    surface = re.make_surface(ascii_sphere.DEFAULT_GLYPHS)
    globe = ascii_sphere.Globe(surface, 13, 2.3, fill=0.5)
    step = ascii_sphere.resolve_step(globe)

    frame0 = globe.render(0.0)
    angle = 0.0
    tau = 2.0 * math.pi
    for _ in range(globe.tiles_x):
        angle = (angle - step) % tau
    wrapped = globe.render(angle)

    differing = sum(
        ca != cb
        for la, lb in zip(frame0.split("\n"), wrapped.split("\n"))
        for ca, cb in zip(la, lb)
    )
    assert differing <= 5, f"{differing} cells drifted over a full revolution"


def test_surface_material_model():
    """Earth is the minimal opaque+window surface (opacity 1 land, opacity 0 ocean)
    -- the two-material base case the shared render generalizes from. Also confirm
    each declared class code actually occurs in the grid and the engine resolves
    it without error."""
    import ascii_sphere
    import rotating_earth as re

    earth = re.make_surface(GLYPHS)
    opacities = sorted(m.opacity for m in earth.classes.values())
    assert opacities == [0.0, 1.0]
    assert earth.classes[re.OCEAN].opacity == 0.0  # fully transparent ocean window
    assert earth.classes[re.LAND].opacity == 1.0  # solid, occluding land
    assert all(spec.relief == 0 for spec in earth.classes.values())  # flush feature

    # Every declared class code must actually appear in the decoded grid.
    present = set(earth.grid)
    assert set(earth.classes).issubset(present), (
        f"{earth.name}: declared {set(earth.classes)} but grid has {present}"
    )

    # The engine resolves all classes without error and reports sane geometry.
    globe = ascii_sphere.Globe(earth, 15, 2.3, fill=0.5)
    assert globe.tiles_x > 0 and globe.tiles_y > 0
    assert isinstance(globe.render(0.0), str)


def test_globe_rejects_undeclared_code():
    """A grid byte with no matching Material is rejected at construction (fail
    fast) instead of raising KeyError deep in render()'s per-frame hot loop."""
    import ascii_sphere

    surface = ascii_sphere.Surface(
        name="Bogus",
        provenance="test",
        W=2,
        H=2,
        grid=bytearray([0, 0, 0, 9]),  # code 9 is never declared below
        classes={0: ascii_sphere.Material(opacity=0.0)},
    )
    with pytest.raises(ValueError, match="undeclared class codes"):
        ascii_sphere.Globe(surface, 8, 2.3)


def test_unpack_levels_roundtrips_nibbles():
    """unpack_levels decodes a nibble-packed blob back to the exact 0..15 level
    codes (two cells/byte, high nibble first), zero-padding short and truncating
    long -- the same fixed-size contract as unpack_bits, one level per cell."""
    import zlib
    import base64
    import ascii_sphere

    codes = bytes([0, 5, 15, 1, 2, 8])  # w*h = 6 cells, various levels
    packed = bytes([(codes[i] << 4) | codes[i + 1] for i in range(0, len(codes), 2)])
    blob = base64.b64encode(zlib.compress(packed)).decode("ascii")

    got = ascii_sphere.unpack_levels(blob, 3, 2)  # 3x2 = 6 cells
    assert bytes(got) == codes
    assert max(got) <= 15

    # Short blob zero-pads to w*h; a request for fewer cells truncates.
    assert bytes(ascii_sphere.unpack_levels(blob, 4, 2)) == codes + bytes(2)
    assert bytes(ascii_sphere.unpack_levels(blob, 2, 2)) == codes[:4]


def _strip_ansi(frame):
    return re.sub(r"\033\[[0-9;]*m", "", frame)


def _solid_globe(**kwargs):
    """A one-material globe whose near shell always stops solid (opacity 1, a
    space-free palette). AXIS B has no window path, so short-circuit behavior and
    the AXIS D masks can be observed in isolation."""
    import ascii_sphere

    surface = ascii_sphere.Surface(
        name="Solid",
        provenance="test",
        W=64,
        H=32,
        grid=bytearray(64 * 32),
        classes={0: ascii_sphere.Material(opacity=1.0, palette="#")},
    )
    return ascii_sphere.Globe(surface, 12, 2.3, **kwargs)


def test_opaque_short_circuit_fills_the_disc():
    """An all-opacity-1 body never leaves a hole INSIDE the disc: the near shell
    short-circuits every on-disc cell. With limb_fade off and a flat, full fill
    (no AXIS D thinning), each rendered row's on-disc span is a gap-free run of
    ink -- the opaque short-circuit guaranteeing no see-through / no void."""
    globe = _solid_globe(limb_fade=False, fill=1.0, fill_falloff=0.0)
    for line in _strip_ansi(globe.render(0.3)).split("\n"):
        core = line.strip()  # drop the off-disc margins
        assert " " not in core, f"interior hole in an all-opaque disc: {line!r}"


def test_full_window_is_all_holes():
    """A single opacity-0 material is a pure window on every shell, so every ray
    passes clean through to a true hole: the frame is entirely blank (AXIS B's
    window-behind-window == HOLE case, with no shell ever stopping the ray)."""
    import ascii_sphere

    surface = ascii_sphere.Surface(
        name="Void",
        provenance="test",
        W=32,
        H=16,
        grid=bytearray(32 * 16),
        classes={0: ascii_sphere.Material(opacity=0.0)},
    )
    frame = ascii_sphere.Globe(surface, 10, 2.3).render(0.0)
    assert _strip_ansi(frame).strip() == "", "a pure-window globe must be all holes"


def test_render_is_pure_in_angle():
    """render(angle) is a pure function of angle -- same angle, byte-identical
    frame (the dither is welded to surface tiles, never per-frame random)."""
    globe = _solid_globe(fill=0.6)
    assert globe.render(0.7) == globe.render(0.7)


def test_void_masks_thin_ink_to_holes():
    """AXIS D density: dropping the fill keep rate punches true holes into an
    otherwise solid disc (fewer drawn glyphs than at full fill), and those holes
    are voids, not see-through -- there is no far shell to reveal on a solid body."""
    dense = _strip_ansi(_solid_globe(limb_fade=False, fill=1.0).render(0.0))
    sparse = _strip_ansi(_solid_globe(limb_fade=False, fill=0.4).render(0.0))
    assert sparse.count("#") < dense.count("#")


def _screen_door_globe(opacity, **kwargs):
    """A one-material globe whose only class is a screen-door of the given opacity
    (space-free palette). Both shells sample it, so the rendered coverage is a
    direct read on the AXIS B walk."""
    import ascii_sphere

    surface = ascii_sphere.Surface(
        name="ScreenDoor",
        provenance="test",
        W=512,
        H=256,
        grid=bytearray(512 * 256),
        classes={0: ascii_sphere.Material(opacity=opacity, palette="#")},
    )
    return ascii_sphere.Globe(surface, 22, 2.3, limb_fade=False, **kwargs)


def test_shell_walk_coverage_matches_transmittance():
    """STATISTICAL, via the real render: for a single screen-door material of
    opacity `a` on a hollow (2-shell) globe, each shell stops the ray with
    probability ~a and the shells compose as independent transmittance, so the
    drawn fraction is the Porter-Duff coverage P(draw) = 1 - (1-a)^2 (§6). Measured
    over the actual rendered frames (pooled across a revolution), it must match
    that within tolerance -- confirming the per-tile opacity dither is a faithful
    ~a coin AND that near/far are independent (a shared/duplicated draw would
    collapse the coverage toward `a`, e.g. 0.50 not 0.75 at a=0.5). On-disc cell
    count comes functionally from an all-opaque render (every on-disc cell drawn),
    not from engine internals."""
    import math

    # far_fill=1.0 so BOTH shells sample fully -- this pins the pure Porter-Duff
    # composition of the walk, independent of the shipped sparse-far-wall default
    # (far_fill 0.5 would thin the far shell to a + (1-a)*a*0.5, a different test).
    angles = [i * 2.0 * math.pi / 8 for i in range(8)]  # spread over one revolution
    solid = _screen_door_globe(1.0, fill=1.0, fill_falloff=0.0)  # opaque -> full disc
    for a in (0.3, 0.5, 0.7):
        door = _screen_door_globe(a, fill=1.0, fill_falloff=0.0, far_fill=1.0)
        on_disc = drawn = 0
        for ang in angles:
            on_disc += _strip_ansi(solid.render(ang)).count("#")
            drawn += _strip_ansi(door.render(ang)).count("#")
        frac = drawn / on_disc
        expected = 1.0 - (1.0 - a) ** 2
        assert abs(frac - expected) < 0.05, (
            f"opacity {a}: rendered coverage {frac:.3f} != transmittance {expected:.3f}"
        )


def test_density_dither_is_independent_of_opacity():
    """STATISTICAL orthogonality, via the real render: AXIS B (opacity) and AXIS D
    (fill void) share one _hash2 primitive but must stay independent through
    distinct prime key offsets (§5). Two render-observable consequences:

      1. The void is purely SUBTRACTIVE over the walk's placement -- every glyph in
         the thinned frame is also in the full-fill frame at the same position (D
         never adds or relocates ink B placed).
      2. Among the tiles the walk drew, the void keeps each with probability ~fill,
         DECORRELATED from the opacity draw -- so the survivor ratio tracks `fill`.
         If the two dithers shared a key it would instead be ~fill/a (0.83 here),
         so this pins independence, not just 'fewer glyphs'."""
    import math

    a, f = 0.6, 0.5
    full = _screen_door_globe(a, fill=1.0, fill_falloff=0.0)
    thin = _screen_door_globe(a, fill=f, fill_falloff=0.0, void_scale=1, void_soft=0.0)
    angles = [i * 2.0 * math.pi / 6 for i in range(6)]
    full_ink = thin_ink = 0
    for ang in angles:
        rows_full = _strip_ansi(full.render(ang)).split("\n")
        rows_thin = _strip_ansi(thin.render(ang)).split("\n")
        for lf, lt in zip(rows_full, rows_thin):
            for cf, ct in zip(lf, lt):
                if ct != " ":  # (1) every surviving glyph was placed by the walk
                    assert cf == ct, (
                        "density added/moved ink the opacity walk didn't place"
                    )
        full_ink += sum(row.count("#") for row in rows_full)
        thin_ink += sum(row.count("#") for row in rows_thin)
    ratio = thin_ink / full_ink  # (2) survivor rate ~ fill (decorrelated), not fill/a
    assert abs(ratio - f) < 0.05, (
        f"survivor ratio {ratio:.3f} != fill {f} (dithers correlated?)"
    )


def test_reading_order_packing_is_lossless():
    """A window-class tile (opacity 0) consumes NO character of a reading-order
    palette: the stream SPLITS across the windows, it is never chopped (so a
    feature like Earth's continents shows the source text whole, resuming after
    each ocean, instead of dropping the glyphs the ocean covered). Concretely the
    near-shell packed index counts only drawable tiles -- contiguous 0..L-1 in
    row-major (reading) order, -1 at each window -- and a body with NO window class
    packs to the plain identity, so its output is byte-for-byte unchanged."""
    import ascii_sphere

    W = H = 16
    # A coastline: 2 of every 3 columns are land (opaque text), the rest ocean.
    grid = bytearray(1 if (x % 3) else 0 for _ in range(H) for x in range(W))
    surface = ascii_sphere.Surface(
        name="Stripe",
        provenance="test",
        W=W,
        H=H,
        grid=grid,
        classes={
            1: ascii_sphere.Material(opacity=1.0, palette="ABCDEFGHIJKLMNOP"),
            0: ascii_sphere.Material(opacity=0.0),  # window
        },
    )
    globe = ascii_sphere.Globe(surface, 12, 2.3)
    tx, ty = globe.tiles_x, globe.tiles_y
    packed = globe._packed_near
    expect = 0
    windows = 0
    for row in range(ty):
        base = globe._tile_iy[row] * W
        for col in range(tx):
            code = globe.grid[base + globe._tile_ix[col]]
            i = row * tx + col
            if code == 0:  # window: no character consumed
                assert packed[i] == -1
                windows += 1
            else:  # drawable: the very next character, nothing skipped
                assert packed[i] == expect, "window chopped the stream (lost a char)"
                expect += 1
    assert expect > 0 and windows > 0, "test must exercise both land and window"

    # No window class (the text-ball case) -> packing is the plain identity, so
    # the reading-order index -- and the rendered output -- is unchanged.
    allland = ascii_sphere.Surface(
        name="AllLand",
        provenance="test",
        W=W,
        H=H,
        grid=bytearray(b"\x01" * (W * H)),
        classes={1: ascii_sphere.Material(opacity=1.0, palette="ABC")},
    )
    g2 = ascii_sphere.Globe(allland, 12, 2.3)
    assert g2._packed_near == list(range(g2.tiles_x * g2.tiles_y))


def test_truecolor_emits_only_valid_24bit_gray():
    """With truecolor on, the engine emits 24-bit gray SGR (38;2;v;v;v) with equal,
    in-range channels and NO 256-indexed (38;5) codes -- and it stays a superset of
    the 256 ramp's dynamic range (finer, not different)."""
    import re

    import ascii_sphere
    import rotating_earth as re_body

    surface = re_body.make_surface(ascii_sphere.DEFAULT_GLYPHS)
    globe = ascii_sphere.Globe(surface, 15, 2.3, fill=0.5, truecolor=True)
    frame = globe.render(0.0)

    assert "38;5;" not in frame, "indexed gray leaked into a truecolor frame"
    triples = re.findall(r"38;2;(\d+);(\d+);(\d+)", frame)
    assert triples, "no 24-bit color emitted"
    vals = set()
    for r, g, b in triples:
        r, g, b = int(r), int(g), int(b)
        assert r == g == b, f"non-gray 24-bit color {(r, g, b)}"
        assert 0 <= r <= 255
        vals.add(r)
    # The 256 render of the same globe collapses to fewer distinct grays; truecolor
    # must resolve strictly more (the whole point of the feature).
    idx = set(
        re.findall(
            r"38;5;(\d+)",
            ascii_sphere.Globe(surface, 15, 2.3, fill=0.5, truecolor=False).render(0.0),
        )
    )
    assert len(vals) > len(idx)


def test_default_is_256_indexed():
    """The default (no truecolor) path is unchanged: 256-indexed gray, never 24-bit
    -- so the pinned goldens and every non-truecolor terminal keep byte-identical
    output."""
    import ascii_sphere
    import rotating_earth as re_body

    surface = re_body.make_surface(GLYPHS)
    frame = ascii_sphere.Globe(surface, 15, 2.3, fill=0.5).render(0.0)
    assert "38;5;" in frame and "38;2;" not in frame


def test_prepare_reverse_negates_step():
    """prepare(reverse=True) flips the (always-positive) snapped step so a body can
    spin the other way (the text ball reads left-to-right) WITHOUT mutating the
    returned Plan; the default keeps the positive step. Only the sign differs --
    the magnitude (the whole-tile snap) is identical, so the rigid marquee holds."""
    import shell
    import rotating_earth as re_body

    parser = shell.build_common_parser("test")
    args = parser.parse_args(["--radius", RADIUS, "--theme", "dark"])
    config = shell.resolve_request(args)
    surface = re_body.make_surface(GLYPHS)

    forward = shell.prepare(config, surface)
    reversed_ = shell.prepare(config, surface, reverse=True)
    assert forward.step > 0, "the snapped step is positive by default"
    assert reversed_.step == -forward.step, "reverse must negate exactly, not re-snap"


def test_detect_truecolor_requires_tty(monkeypatch):
    """detect_truecolor honors $COLORTERM only on a live TTY. The non-TTY gate is
    what keeps --preview / piped runs (and the goldens) deterministically 256-color
    regardless of the environment."""
    import sys

    import shell

    monkeypatch.setenv("COLORTERM", "truecolor")

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert shell.detect_truecolor() is False  # piped: always 256

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert shell.detect_truecolor() is True  # tty + COLORTERM: 24-bit

    monkeypatch.setenv("COLORTERM", "")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert shell.detect_truecolor() is False  # tty but no advertisement


if __name__ == "__main__":
    raise SystemExit("run via pytest")
