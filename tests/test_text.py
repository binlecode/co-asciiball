"""Tests for the sentence-ring text body (`rotating_text.py`) and its two pure
core helpers (`split_sentences`, `layout_rings`) plus the `tile_grid` extraction.

Property / structural, matching test_render.py's style: the pure functions are
exercised headless, the body through its REAL `--preview` CLI (pinned radius /
theme / glyph-source so nothing depends on the dev's terminal or README content).
The invariants pinned here are the three the spec names -- text-is-the-only-fill,
golden-ratio gaps (only between sentences), and the rigid marquee -- plus the
single-source-of-truth guard that `tile_grid` matches what `Globe` computes.
"""

import re
import sys
import subprocess
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(MODULE_DIR))

import ascii_sphere  # noqa: E402
from ascii_sphere import GOLDEN, layout_rings, split_sentences, tile_grid  # noqa: E402

RADIUS = "20"
ASPECT = "2.3"

# The body's shipped defaults, spelled out -- the drift guard (implicit == this).
TEXT_DEFAULTS = [
    "--far-dim",
    "0.85",
    "--far-fill",
    "0.5",
    "--fill",
    "1.0",
    "--fill-falloff",
    "0.0",
    "--pole-cap",
    "0.15",
    "--gap-ratio",
    repr(GOLDEN),
]


def _strip_ansi(frame):
    return re.sub(r"\033\[[0-9;]*m", "", frame)


def _fixture(tmp_path, text):
    src = tmp_path / "source.txt"
    src.write_text(text, encoding="utf-8")
    return str(src)


def _preview(source, extra=()):
    cmd = [
        sys.executable,
        str(MODULE_DIR / "rotating_text.py"),
        "--preview",
        "--glyph-source",
        source,
        "--radius",
        RADIUS,
        "--aspect",
        ASPECT,
        "--theme",
        "dark",
        *extra,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, f"exited {proc.returncode}:\n{proc.stderr}"
    return proc.stdout


def _rings(layout, tiles_x):
    p = layout.palette
    return [p[i : i + tiles_x] for i in range(0, len(p), tiles_x)]


# --------------------------------------------------------------------------- #
# split_sentences
# --------------------------------------------------------------------------- #


def test_split_sentences_keeps_terminators_and_drops_empties():
    out = split_sentences("The quick brown fox jumps. The lazy dog is sleeping!")
    assert out == ["The quick brown fox jumps.", "The lazy dog is sleeping!"]
    assert all(s and s[-1] in ".!?…" for s in out)


def test_split_sentences_merges_short_fragments():
    # "Hi." (3 chars) is below min_len, so it folds into the following sentence.
    out = split_sentences("Hi. This is a sufficiently long sentence to keep.")
    assert out == ["Hi. This is a sufficiently long sentence to keep."]


def test_split_sentences_blank_line_is_a_boundary():
    out = split_sentences(
        "First paragraph runs on without a period\n\n"
        "Second paragraph also has no period"
    )
    assert out == [
        "First paragraph runs on without a period",
        "Second paragraph also has no period",
    ]


def test_split_sentences_does_not_merge_short_fragment_across_blank_line():
    out = split_sentences("Hi.\n\nThis is a sufficiently long sentence to keep.")
    assert out == ["Hi.", "This is a sufficiently long sentence to keep."]


def test_split_sentences_keeps_abbreviation_with_following_word():
    # "e.g." splits off but is under min_len, so the merge rejoins it -- the
    # abbreviation stays with its word "in the common case" (a display heuristic).
    assert split_sentences("e.g. foo") == ["e.g. foo"]


def test_split_sentences_empty_input():
    assert split_sentences("") == []
    assert split_sentences("   \n\t  ") == []


def test_split_sentences_collapses_internal_whitespace():
    (s,) = split_sentences("Lots   of\t\tinner   whitespace collapses here.")
    assert "  " not in s and "\t" not in s


# --------------------------------------------------------------------------- #
# layout_rings
# --------------------------------------------------------------------------- #


def test_layout_palette_covers_sphere_exactly():
    tiles_x, tiles_y = 40, 30
    layout = layout_rings(["One sentence here."], tiles_x, tiles_y)
    assert len(layout.palette) == tiles_x * tiles_y


def test_layout_spans_start_on_ring_boundaries_and_stay_in_bounds():
    tiles_x, tiles_y = 24, 40
    sents = ["First sentence is here.", "Second sentence is here."]
    layout = layout_rings(sents, tiles_x, tiles_y)
    for si, first, k in layout.spans:
        assert 0 <= si < len(sents)
        assert layout.cap_rings <= first  # body starts below the top cap
        assert first + k <= tiles_y
        # A span begins at tile 0 of a fresh ring: the ring's first char is ink,
        # never a between-sentence window (space).
        assert layout.palette[first * tiles_x] != " "


def test_layout_gap_after_each_sentence_is_golden_ratio():
    tiles_x, tiles_y = 20, 120
    sents = [
        "Alpha beta gamma delta epsilon zeta.",
        "Eta theta iota kappa lambda mu nu.",
    ]
    layout = layout_rings(sents, tiles_x, tiles_y)
    spans = layout.spans
    assert len(spans) >= 2
    for (_, first, k), (_, nxt_first, _) in zip(spans, spans[1:]):
        gap = nxt_first - (first + k)
        assert gap == max(1, round(GOLDEN * k)), f"gap {gap} != phi*{k}"


def test_layout_no_window_inside_a_sentence_except_tail_padding():
    tiles_x, tiles_y = 18, 60
    layout = layout_rings(
        ["Alpha beta gamma delta epsilon zeta eta theta."], tiles_x, tiles_y
    )
    rings = _rings(layout, tiles_x)
    for _, first, k in layout.spans:
        for r in range(first, first + k):
            # No interior window: spaces may appear only as end-of-ring padding
            # on the sentence's last ring.
            assert " " not in rings[r].rstrip(" "), f"interior window in ring {r}"


def test_layout_repeats_cycle_with_small_remainder():
    tiles_x, tiles_y = 16, 200
    # Two equal-length sentences -> every sentence-plus-gap block is the same size,
    # so the trailing all-space remainder must be smaller than one block.
    sents = ["Sentence number one here now.", "Sentence number two here now."]
    layout = layout_rings(sents, tiles_x, tiles_y)
    seen = [si for si, _, _ in layout.spans]
    assert seen.count(0) >= 2 and seen.count(1) >= 2, "cycle did not repeat"

    consumed = sum(k + max(1, round(GOLDEN * k)) for _, _, k in layout.spans)
    body_rings = tiles_y - 2 * layout.cap_rings
    remainder = body_rings - consumed
    block = min(k + max(1, round(GOLDEN * k)) for _, _, k in layout.spans)
    assert 0 <= remainder < block, f"remainder {remainder} not < block {block}"


def test_layout_caps_are_solid_word_sep():
    tiles_x, tiles_y = 20, 40
    layout = layout_rings(
        ["A sentence goes here."], tiles_x, tiles_y, word_sep="·", pole_frac=0.2
    )
    cap = layout.cap_rings
    assert cap >= 1
    top = layout.palette[: cap * tiles_x]
    bottom = layout.palette[(tiles_y - cap) * tiles_x :]
    assert set(top) == {"·"} and set(bottom) == {"·"}


def test_layout_no_word_sep_caps_fall_back_to_dot():
    # --no-word-sep ("") runs words together, but a cap must still have ink.
    tiles_x, tiles_y = 20, 30
    layout = layout_rings(
        ["Words run together here now."], tiles_x, tiles_y, word_sep="", pole_frac=0.2
    )
    top = layout.palette[: layout.cap_rings * tiles_x]
    assert set(top) == {"·"}


def test_layout_overlong_sentence_truncates():
    tiles_x, tiles_y = 12, 5
    huge = "word " * 400  # far more than tiles_x*tiles_y tiles
    layout = layout_rings([huge], tiles_x, tiles_y)
    assert len(layout.palette) == tiles_x * tiles_y
    assert len(layout.spans) == 1  # one sentence, hard-truncated to fit


def test_layout_degenerate_single_ring():
    layout = layout_rings(["One tall-thin ring of text."], 30, 1)
    assert len(layout.palette) == 30
    assert layout.cap_rings == 0 and len(layout.spans) == 1


# --------------------------------------------------------------------------- #
# tile_grid single-source-of-truth guard
# --------------------------------------------------------------------------- #


def test_tile_grid_matches_globe():
    surface = ascii_sphere.Surface(
        name="T",
        provenance="test",
        W=1440,
        H=720,
        grid=bytearray(b"\x01" * (1440 * 720)),
        classes={1: ascii_sphere.Material(opacity=1.0, palette="abc")},
    )
    globe = ascii_sphere.Globe(surface, 20, 2.3)
    tg = tile_grid(1440, 720, 20, 2.3)
    assert (tg.tiles_x, tg.tiles_y) == (globe.tiles_x, globe.tiles_y)
    assert tg.div_x == globe.glyph_div_x and tg.div_y == globe.glyph_div_y


# --------------------------------------------------------------------------- #
# Rigid marquee (headless, the invariant-3 guard)
# --------------------------------------------------------------------------- #


def test_text_layout_marquee_is_step_stable():
    """A real sentence-ring layout translates rigidly across one snapped step:
    every on-disc front-face cell shows the glyph its upstream neighbour showed
    one step earlier -- zero re-quantized characters (pins invariant 3 against
    float jitter in the tile pick)."""
    tg = tile_grid(1440, 720, 16, 2.3)
    sents = split_sentences(
        "The quick brown fox jumps over the lazy dog again and again. "
        "Pack my box with five dozen liquor jugs right now please."
    )
    layout = layout_rings(sents, tg.tiles_x, tg.tiles_y)
    surface = ascii_sphere.Surface(
        name="Text",
        provenance="test",
        W=1440,
        H=720,
        grid=bytearray(b"\x01" * (1440 * 720)),
        classes={1: ascii_sphere.Material(opacity=1.0, palette=layout.palette)},
    )
    globe = ascii_sphere.Globe(
        surface, 16, 2.3, limb_fade=False, fill=1.0, fill_falloff=0.0, far_dim=0.0
    )
    step = ascii_sphere.resolve_step(globe)
    tps = round(step / globe.lon_per_tile)
    f0 = _strip_ansi(globe.render(0.0)).split("\n")
    f1 = _strip_ansi(globe.render(-step)).split("\n")
    checked = mismatches = 0
    for r, cells in enumerate(globe._cells):
        for c, cell in enumerate(cells):
            if cell is None or c - tps < 0:
                continue
            prev = cells[c - tps]
            if prev is None or prev.ty0 != cell.ty0:  # same text ring (one per row)
                continue
            checked += 1
            if f1[r][c] != f0[r][c - tps]:
                mismatches += 1
    assert checked > 200, "degenerate geometry: almost nothing compared"
    assert mismatches == 0, f"{mismatches}/{checked} glyphs re-quantized"


# --------------------------------------------------------------------------- #
# End-to-end CLI
# --------------------------------------------------------------------------- #


def test_text_preview_runs_and_is_deterministic(tmp_path):
    src = _fixture(tmp_path, "Alpha beta gamma delta. Epsilon zeta eta theta iota.")
    assert _preview(src) == _preview(src)


def test_text_defaults_unchanged(tmp_path):
    """Implicit defaults render identically to spelling them out -- so the shipped
    far-dim/far-fill/pole-cap/gap-ratio/fill defaults can't silently drift."""
    src = _fixture(tmp_path, "Alpha beta gamma delta. Epsilon zeta eta theta iota.")
    assert _preview(src) == _preview(src, TEXT_DEFAULTS)


def test_text_far_wall_really_renders(tmp_path):
    """--far-dim 0 drops the back wall, so the frame differs from the default (the
    far ghost is genuinely composited, not decorative)."""
    src = _fixture(tmp_path, "Alpha beta gamma delta. Epsilon zeta eta theta iota.")
    assert _preview(src) != _preview(src, ["--far-dim", "0"])


if __name__ == "__main__":
    raise SystemExit("run via pytest")
