# Killer Use Cases — Geo-based (two-layer: Earth basemap + data overlay)

> One of two use-case families for the Asciiball engine. This file covers the
> **geo-based** group, where a cell's location means a **real place (lat/lon)**.
> The sibling file [`KILLER-USE-CASES-free-surface.md`](KILLER-USE-CASES-free-surface.md)
> covers the **free-surface** group, where position is aesthetic / reading-order
> only and the surface *is* the payload.

> Engine context: a **pure-Python, stdlib-only** terminal renderer that projects
> a surface dataset onto a **hollow, transparent sphere** under a finite-eye
> **perspective** cast — you see through the planet to the far wall, which lands
> at different latitudes and is foreshortened smaller. Two bodies ship today:
> **Earth** (`src/rotating_earth.py`, Natural Earth continents as reading-order
> text over a see-through ocean) and **Text** (`src/rotating_text.py`, source
> text one sentence per latitude ring). The Moon body was removed 2026-07-17
> (git history); the interactive *terminal on a sphere* is the separate
> `glassball/` stack, out of scope here. Tags: **[shipped]** / **[ecosystem-gap]**
> / **[design]** (needs a new rendering primitive).

---

## What makes a use case geo-based

The discriminator across both families is one question: **does a cell's location
mean a place on Earth, or just a spot on the ball?** Geo-based = a real place.

| | **Geo-based (this file)** | Free-surface (sibling file) |
|---|---|---|
| Position means | a real place (lat/lon) | aesthetic / reading-order only |
| Layering | **two layers**: Earth basemap + data overlay | single layer: the surface *is* the payload |
| Earth required? | yes — as a geographic reference | no — Earth optional, Text body common |
| Engine posture | needs new primitives (below) | already shipped; ecosystem gaps only |
| Use cases | A1 geo-focal event globe · A2 git-activity heatmap | B1–B4 |

**The two-layer model.** A geo use case is standard GIS: a **basemap layer**
(Earth geography as dim reference context, so you know *where* you're looking)
plus a **data layer** (the geolocated signal, composited on top). The current
engine is **single-layer** — a body is *one* `Surface` (one grid + one `classes`
map), and Earth's land is the *payload* (README text), not a neutral basemap.
Making the two-layer model real needs three unshipped pieces, called out per case:

1. **Basemap mode** — render Earth's land/ocean as muted, desaturated context
   (not README text) so the data reads as foreground. *(nothing covers this yet)*
2. **Data layer** — a `heat: float` array riding alongside `grid`, composited on
   **orthogonal channels** (geography keeps lightness/shape, data gets
   hue/saturation only) so the sphere doesn't flatten. *(scoped in A2)*
3. **Per-shell composition** — because the sphere is hollow, "on top of Earth"
   means *front→back*: a near-wall point vs. one bleeding through from the far
   wall. *(scoped in A2)*

---

## A1: Geo-Focal Event Globe — Network, Honeypot, Traceroute, Satellite, Infra  **[design]**

**Why.** Geolocated events — attacks, packet hops, satellites, region outages —
are invisible in text logs. A rotating globe that lights up where an event lands,
**auto-focuses to the active region**, and shows a per-point info panel turns an
ephemeral stream into spatial awareness. The hollow transparency means a far-side
event **shows through** the planet, visible before it rotates into view — a depth
cue no other terminal Earth renderer has.

**Community proof — this direction is repeatedly, independently built:**

| Project | Domain | What it shows |
|---------|--------|---------------|
| **SecKC-MHN-Globe** | cyber | Live honeypot attacks on a 3D ASCII globe + attack info panels — used by an actual SOC, hand-rolled renderer (120×60 bitmap, no transparency) |
| **DEATH_STAR** | cyber | Firewall-log attacks on a 3D ASCII globe: IP geolocation + threat intel, 100% local/defensive |
| **honeypot-dashboard** | cyber | Cowrie SSH honeypot + live world map + LLM session summaries |
| **termtrack** | space | Satellites/ISS *in the terminal* with orbit + coverage overlays |
| **adamsky/globe** | generic | ASCII globe whose experimental mode **reads coordinates from stdin and animates the camera to focus each** — the focal primitive, as a CLI contract |
| TraceMapper · GeoTraceroute · Globalping | network | Traceroute hops on a world map — a whole tool class, **all web/desktop, zero terminal-globe** |
| AWS / Vercel / Cloudflare region maps · USGS quakes · World Monitor | infra / geo | Region health, seismic + outage feeds — geolocated point streams, **web-only** |

Every one is the same shape: **a stream of `(lat, lon, magnitude, label)` events
→ plot on the hollow globe → focus to the hottest region → info panel for the
focused point.** Cyber is the most-validated feed (three ASCII-globe clones);
traceroute and infra are wide-open (a live tool class with no terminal option).

**How asciiball wins.**
- **Per-class semantics.** Encode event type as a surface class (SSH brute-force
  = opaque glyph, web shell = screen-door stipple, port scan = void). The class
  map becomes the threat/protocol map.
- **Through-Earth events.** Far-wall hits bleed through the near-side windows — a
  path that goes "through" the planet is legible, not hidden.
- **Focal display.** Auto-rotate/zoom to the active coordinate + a side info
  panel (the SecKC "attack panel", the adamsky stdin-coordinate primitive).

**Blocking gaps (the two-layer pieces).** This needs the **basemap mode** (Earth
as dim context, not README text), the **`heat`/event data layer** (A2), the
**focus-to-coordinate + info-panel** mode, and `--json` to feed dashboards. Today
the surface is baked (`data/earth.b64`) or a text `--glyph-source` — there is no
live per-cell data path.

**Hardware note.** Runs headless on a Raspberry Pi with a dedicated terminal in
the SOC corner — zero GUI overhead, SSH-accessible.

---

## A2: Git Activity Heatmap — Contributors & Codebase  **[design]**

**Why.** Two related impulses: render *where* a repo's contributors are active on
the real Earth, and render a "planet of the codebase" whose continents are active
modules and whose transparent gaps are eroding, stale code. Both are git-log →
heat-on-the-sphere; both are from-first-principles (no shipped project does
either credibly), so the constraints below come from what the data actually
provides, not from an existing implementation. This case also **defines the data
layer + composition rules that A1 reuses.**

**Constraint 1 — there is no real per-commit geo signal.** Git commits carry an
author timestamp with UTC offset (`git log --date=iso-strict` → `+09:00`), not a
lat/lon; GitHub doesn't expose committer IPs. Two honest strategies:
1. **Timezone-band bucketing (default, zero-dependency).** Bucket commits by UTC
   offset into ~15°-wide longitude bands. Coarse (no latitude signal — draw a
   full meridian strip or spread across a plausible latitude range) but always
   available, no network.
2. **Profile-location geocoding (opt-in).** Resolve each contributor's free-text
   GitHub `location` through a geocoder, cached offline (a `tmp/`-style
   enrichment, not a live per-run call). Richer lat/lon, but sparse and noisy.

Ship (1) as the default; treat (2) as enrichment. For the codebase variant, map
each source file to a stable cell (hash → lat/lon) and accumulate its commit
density there.

**Constraint 2 — "per-char resolution" is a rendering ceiling, not precision.**
The Earth grid (`data/earth.b64`) is the natural bucket grid — one heat scalar
per cell. At practical render radii that's country/region resolution; multiple
contributors aliasing into one cell is what a heatmap bucket *is*. Heat should be
a **time-decayed accumulation** (exponential half-life over `--span`), not a raw
lifetime count, so one old dump doesn't permanently outshine recent work.

**Constraint 3 — the data layer needs a new primitive.** Today the model is
single-layer, per-**class**: each cell code maps to one fixed `Material`
(`opacity`/`palette`/`hashed`/`relief`), and color is the engine's *depth* cue,
not a per-cell value. The data layer is a `heat: float` array **alongside**
`grid`/`classes`, blended through a gradient (theme base → yellow → orange →
red). This is layer 2 of the two-layer model.

**The hard part — orthogonal composition, so the globe stays 3D.** The sphere
reads as 3D almost entirely through non-color cues: the fill-falloff dome, the
limb fade, and per-class `relief`. Lay a heat ramp on top *as a replacement for
shading* and it flattens into a disc. Keep the basemap and data layers on
strictly orthogonal channels, composed in HSL/HSV:
- **Lightness** stays driven by the radial shade-band + limb fade — a hot cell at
  the limb must still read dimmer than the same heat at disc center.
- **Hue/saturation only** carries heat — cold cells desaturate to the theme base;
  hot cells gain saturation and shift toward red, never touching lightness.
- **Fill/void dropout stays untouched** — porosity is a structural cue; a sparse
  cold region and a sparse hot region must drop out identically, or heat silently
  fights the void system.
- **Per-shell** — composite the data layer front→back so a far-wall value ghosts
  correctly through the near-side windows.
- Optionally route heat into `relief` too (hot = slightly raised) so it survives
  `NO_COLOR`/monochrome as an emboss, not a color that vanishes.

**Implementation note.** This data is per-repo and time-varying, so it doesn't
belong in a baked `data/*.b64`. Compute it live from `git log` the way
`--glyph-source` reads a file at startup — a `--heat-source` flag (or sibling
script) that buckets into the Earth grid and hands the renderer a heat layer.

---

## Roadmap — the Group A layer stack

| Enabling feature | Priority | Unlocks |
|-----------------|----------|---------|
| `heat: float` data layer + `--heat-source` (layer 2) | HIGH | A1, A2 |
| Earth **basemap mode** (muted geography, not README text) | HIGH | A1, A2 |
| Focus-to-coordinate + info-panel mode | HIGH | A1 |
| `--json` output (schema + structured frames) | HIGH | A1 |
| Per-shell data-layer composition (front→back) | MED | A1, A2 |
| `--quiet` / `NO_COLOR` monochrome fallback (relief emboss) | LOW | A2 |
| `pyproject.toml` → `pip install` · Homebrew formula | — | install path (shared with free-surface) |

**Bottom line.** Geo-based is where the differentiated engine work lives: the
two-layer model (Earth basemap + data overlay) needs three unshipped primitives —
the `heat` data layer, a basemap mode, and per-shell composition — plus a focal
panel for A1. The demand is proven: the geolocated-event-on-a-globe pattern is
independently reinvented across cyber (SecKC-MHN-Globe, DEATH_STAR), space
(termtrack), network (the entire traceroute-viz tool class), and infra/geo feeds.
Build this layer stack and asciiball has no terminal-native competitor.
