"""Terminal-based rotating 3D ASCII text ball -- the source text, sentence by sentence.

Renders a text source (the bundled README.md by default, or any `--glyph-source`)
onto the same hollow, transparent, perspective 3D ball the planet bodies use, but
laid out as SENTENCE RINGS: one sentence per latitude ring (wrapping the full 360
degrees of longitude), read like a ticker as the ball spins. Between sentences the
layout leaves blank gap rings -- windows -- sized at the golden ratio (a k-ring
sentence is followed by ~phi*k blank rings), so the hollow read gets STRONGER, not
weaker: through each gap you see the far wall as a sparse dotted depth field --
the engine's common `--far-dim`/`--far-fill` defaults (0.85 / 0.5) keep it a
present ghost that reads as depth, not competing backwards text. The
sentence cycle repeats down the sphere so the whole ball is text at the golden
ratio, with solid polar caps preserving the silhouette.

Text scrolls LEFT-TO-RIGHT at front-center (the body negates the engine's natural
spin so new characters enter from the right and read in order), and because the
rotation snaps to whole glyph tiles each frame, a foreground sentence's characters
translate rigidly -- no wobble, no re-picking (a "rigid marquee").

The layout re-flows to the disc size: the surface is a factory of the fitted
radius (`ascii_sphere.tile_grid` -> `layout_rings`), so a resize or the `f`
full-screen toggle re-lays-out the rings. No runtime dependencies beyond the
standard library; the grid is procedural (one class covering the sphere -- the
palette does all the work), so there is no `data/` file.

Run `python rotating_text.py` (Ctrl+C to stop) or `--help` for options. In an
interactive terminal it also takes live controls: space pauses/resumes, the
left/right arrows step the ball one tile at a time (pausing it), and q quits.
"""

from ascii_sphere import (
    DEFAULT_GLYPHS,
    GOLDEN,
    Material,
    Surface,
    layout_rings,
    split_sentences,
    tile_grid,
)
from shell import (
    load_source_text,
    source_path,
    build_common_parser,
    prepare,
    render_preview,
    resolve_request,
    run_loop,
)

# Procedural grid. Earth-sized (1440x720) so cell_x = W/(2*pi*R*aspect*mag) >= 1
# through R ~ 66 -- the tile math never clamps at any realistic disc size. One
# class covers the whole sphere; the ring-laid palette carries the text and its
# between-sentence windows.
GRID_W, GRID_H = 1440, 720
TEXT = 1


def make_surface(palette, provenance):
    """The Text Surface: one class covering the sphere, the ring-laid palette.

    A single opaque text material (opacity 1) whose reading-order `palette` (from
    `layout_rings`) is the sentence rings plus their between-sentence windows
    (spaces) and solid polar caps. The grid is a flat field of that one code --
    the palette does all the layout work, so the body needs no `data/` file.
    """
    return Surface(
        name="Text",
        provenance=provenance,
        W=GRID_W,
        H=GRID_H,
        grid=bytearray(b"\x01" * (GRID_W * GRID_H)),
        classes={TEXT: Material(opacity=1.0, palette=palette, hashed=False)},
    )


def main():
    # No radial dropout: fill 1.0 / falloff 0. Punching fill voids into a sentence
    # lets the far wall bleed mid-text and destroys legibility -- the ball form
    # comes from the depth shading, the limb dissolve, and the between-sentence
    # windows + polar caps instead.
    p = build_common_parser(
        "Rotating 3D ASCII text ball -- the source text, sentence by sentence.",
        body_noun="ball",
        fill_default=1.0,
        fill_help=(
            "Fraction (0..1) of text glyphs kept at the disc CENTRE. Default 1.0 "
            "(no dropout): sentences stay hole-free and only the between-sentence "
            "gaps let the far side show through. Lowering it thins the text and "
            "hurts legibility -- prefer leaving it at 1.0 for this body."
        ),
        falloff_default=0.0,
        void_scale_default=1,
        void_soft_default=0.0,
    )
    # The far wall (--far-dim/--far-fill) is now a COMMON flag with body-agnostic
    # defaults (0.85 / 0.5) -- the same PRESENT-but-non-competing cavity this body
    # first tuned, now shared by every body. Nothing to add here.
    p.add_argument(
        "--pole-cap",
        type=float,
        default=0.15,
        metavar="FRAC",
        help="Fraction of rings at EACH pole filled solid (word-sep) so the "
        "silhouette survives where rows crush toward the poles. Default 0.15.",
    )
    p.add_argument(
        "--gap-ratio",
        type=float,
        default=GOLDEN,
        metavar="RATIO",
        help="Blank gap rings per ink ring between sentences (the golden ratio "
        f"~{GOLDEN:.3f} by default): a k-ring sentence is followed by round(RATIO*k) "
        "windows, so ink:hollow ~ 1:phi down the ball.",
    )
    args = p.parse_args()
    config = resolve_request(args)

    # Sentences: explicit --glyphs is one literal sentence; else segment the
    # source text; an unreadable/empty source falls back so it never crashes and
    # the palette is never blank.
    text = load_source_text(source_path(args.glyph_source))
    sentences = (
        [args.glyphs] if args.glyphs else (split_sentences(text) or [DEFAULT_GLYPHS])
    )
    provenance = (
        "literal --glyphs"
        if args.glyphs
        else (args.glyph_source or "bundled README.md")
    )

    def surface_for(radius):
        # The Phase-1 payoff: re-lay-out the rings against the JUST-FITTED radius,
        # so a resize / full-screen rebuild re-flows the text (fit_globe calls
        # this on every fit). Pure -- captures only args/config values.
        tg = tile_grid(GRID_W, GRID_H, radius, config.aspect, config.eye)
        layout = layout_rings(
            sentences,
            tg.tiles_x,
            tg.tiles_y,
            word_sep=args.word_sep,  # unmodified: --no-word-sep ("") must survive
            pole_frac=args.pole_cap,
            gap_ratio=args.gap_ratio,
        )
        return make_surface(layout.palette, provenance)

    # Reading direction (constraint 2): the loop advances angle -= step, so at a
    # fixed screen cell the reading-order index DECREASES -- text would scroll
    # right, i.e. each sentence in reverse character order. `reverse=True` negates
    # the step so the ball scrolls ticker-style (indices increase at front-center,
    # reads L->R). `run_loop` preserves this sign across resize/full-screen
    # rebuilds (copysign); the magnitude is still the whole-tile snap, so the rigid
    # marquee survives.
    plan = prepare(config, surface_for, reverse=True)
    if config.preview:
        render_preview(plan.globe, plan.step)
    else:
        run_loop(
            plan.globe,
            plan.step,
            plan.delay,
            plan.frames,
            rebuild=plan.rebuild,
        )


if __name__ == "__main__":
    main()
