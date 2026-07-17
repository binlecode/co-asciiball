"""Terminal-based rotating 3D ASCII Earth globe.

Renders a real Earth (Natural Earth land/ocean data) as a spinning sphere in the
terminal. The sphere is a hollow, transparent shell: a ray through any pixel
pierces the globe twice, so the near (front) continents are drawn dark like a
silhouette while the far (back) continents glow through the empty ocean in
lighter gray -- you see straight through the planet to its back side.

The continents are drawn out of the characters of the bundled README.md, laid
onto the surface in LATITUDE ROWS: each row of tiles is one line of the source
text wrapping the full 360 degrees of longitude, stacked pole to pole. The glyph
at a tile is fixed for the whole run, so rotation only transports the text across
the screen -- it never re-picks characters -- and the planet is literally built
from its own documentation. Toward the limb the surface foreshortens to nothing,
so the text is faded out there (a clean horizon) instead of crushing into a solid
rim; pass `--no-limb-fade` to keep the hard edge. Pass `--glyph-source` to draw
from a different text file.

The shared rendering engine is the `ascii_sphere` module; this app supplies only
the Earth land mask and the two-material surface (land = opaque feature, opacity
1; ocean = fully see-through window, opacity 0). No runtime dependencies beyond
the standard library; the land mask ships as a zlib+base64 data file
(`data/earth.b64`), loaded at startup.

Run `python rotating_earth.py` (Ctrl+C to stop) or `--help` for options. In an
interactive terminal it also takes live controls: space pauses/resumes, the
left/right arrows step the globe one tile at a time (pausing it), and q quits.
"""

from ascii_sphere import Material, Surface
from shell import (
    load_bits,
    build_common_parser,
    resolve_glyphs,
    resolve_request,
    prepare,
    render_preview,
    run_loop,
)

# ---------------------------------------------------------------------------
# Earth land/ocean mask
#
# 1440x720 boolean grid (1 = land, 0 = ocean) at 0.25 deg, row-major, MSB-first
# bit packing, zlib-compressed then base64-encoded, shipped as data/earth.b64.
# Generated offline from the Natural Earth coastline dataset via the
# `global-land-mask` package (see tmp/gen_earth.py), whose ~1/120 deg (~1 km)
# source easily resolves the 0.25 deg grid -- finer than the original 0.5 deg
# (720x360) so gulfs, channels, and small islands survive. Decoded once at startup
# (a stdlib file read -- still no runtime deps).
#   x index 0 -> longitude -180 (Pacific dateline), increasing eastward
#   y index 0 -> latitude  +90  (North pole), increasing southward
# ---------------------------------------------------------------------------
EARTH_W, EARTH_H = 1440, 720
EARTH_DATA = "data/earth.b64"

# Surface class codes (also the values stored in the decoded land mask).
OCEAN, LAND = 0, 1


def load_earth():
    """Decode the land mask into a flat bytearray of 0/1 (index = y*W + x)."""
    return load_bits(EARTH_DATA, EARTH_W, EARTH_H)


def make_surface(glyphs):
    """Build the Earth Surface: land = opaque text, ocean = see-through window.

    Land cells (code 1) are the drawn feature (opacity 1) -- the README text laid
    out in reading order. Ocean cells (code 0) are a fully transparent window
    (opacity 0), so every ocean cell reveals the far hemisphere (or a true hole
    where the far side is ocean too). Because ocean is a window CLASS (not a space
    in the palette), the engine's lossless reading-order packing skips it: the
    README stream advances only on land, so it SPLITS across the continents (a
    word cut by a coastline resumes intact on the next land tile) rather than
    dropping the glyphs the ocean covered. This is the minimal two-material case
    of the engine's Surface model. Color (near shell prominent, far shell a receding
    ghost, graded by curvature and the terminal theme) is the engine's business.

    `glyphs` comes from `resolve_glyphs`, which always returns a non-empty string
    (it falls back to `DEFAULT_GLYPHS` itself), so no fallback is needed here.
    """
    classes = {
        LAND: Material(opacity=1.0, palette=glyphs, hashed=False),
        OCEAN: Material(opacity=0.0),
    }
    return Surface(
        name="Earth",
        provenance="Natural Earth data",
        W=EARTH_W,
        H=EARTH_H,
        grid=load_earth(),
        classes=classes,
    )


# Earth's geo-specific fill tuning. Its land is drawn as legible README text laid
# out in SENTENCES (word gaps filled with the word-sep dot, sentence gaps left as
# see-through windows), so the default is NO radial dropout: fill 1.0 / falloff 0.
# Punching fill voids into a sentence lets the background bleed mid-text and
# destroys legibility -- the ball form comes from the depth shading, the limb
# dissolve, and the sentence-gap/ocean windows instead. void-scale 2 + soft 0.6
# still shape the dropout organically if a user lowers --fill by hand.
EARTH_FILL_HELP = (
    "Fraction (0..1) of land glyphs kept at the disc CENTRE; --fill-falloff tapers "
    "it toward the limb. Default 1.0 (no dropout): sentences stay hole-free, and "
    "only the sentence-gap/ocean windows let the far side show through. Lower it "
    "for a thinned, speckled crust."
)


def main():
    p = build_common_parser(
        "Rotating 3D ASCII Earth globe.",
        body_noun="globe",
        fill_default=1.0,
        fill_help=EARTH_FILL_HELP,
        falloff_default=0.0,
        void_scale_default=2,
        void_soft_default=0.6,
        # Earth's near oceans are big windows onto the far continents, so a brighter
        # (far_dim 1.0), denser (far_fill 0.85) back wall than the engine default
        # lets the far hemisphere read as an edge->centre depth cavity instead of an
        # almost-invisible ghost -- the 3D ball effect the faint default washed out.
        far_dim_default=1.0,
        far_fill_default=0.85,
    )
    args = p.parse_args()
    config = resolve_request(args)
    surface = make_surface(resolve_glyphs(args))
    # CLI entry owns the wiring: prepare the plan (reads the terminal size, sizes
    # the globe via the pure core), then pick the driver. Earth spins in run_loop.
    plan = prepare(config, surface)
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
