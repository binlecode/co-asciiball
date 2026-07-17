# Killer Use Cases — Free-surface × co (single-layer: the surface *is* co's state)

> One of two use-case families for the Asciiball engine. This file covers the
> **free-surface** group — a cell's location is aesthetic / reading-order only,
> the surface itself carries the signal — rethought with a single consumer in
> mind: **co** (`~/workspace_genai/co-cli`), the user's local personal
> intelligence agent. The sibling file
> [`KILLER-USE-CASES-geo.md`](KILLER-USE-CASES-geo.md) covers the **geo-based**
> group (cell = real lat/lon, two-layer basemap + overlay).

> Engine context: a **pure-Python, stdlib-only** terminal renderer that projects
> a surface dataset onto a **hollow, transparent sphere** under a finite-eye
> perspective cast. Surface classes carry **readable text** (any file via
> `--glyph-source`), and the fill/void system (`--fill`, `--fill-falloff`,
> `--void-scale`, `--void-soft`) tunes the ball from solid globe to sparse
> ghost. Shipped bodies: **Earth** (`src/rotating_earth.py`) and **Text**
> (`src/rotating_text.py`, source text one sentence per latitude ring).
> Tags: **[shipped]** / **[ecosystem-gap]** / **[design]**.

---

## Who co is (the consumer this file serves)

co's mission (its `docs/specs/00-mission.md`): *a trusted local personal
intelligence company* — Engelbart lineage, **local memory + bounded autonomy +
explicit user control**. Its stage roadmap runs Reliability → Personalization →
Bounded autonomy → Cross-surface continuity → Personal OS layer. The
architectural facts that make asciiball a natural organ for it:

1. **co's entire state is local text.** Memory items (`~/.co-cli/memory/*.md`),
   the user profile (`~/.co-cli/USER.md`), session transcripts
   (`~/.co-cli/sessions/*.jsonl`), skills (`~/.co-cli/skills/*/SKILL.md`),
   observability spans (structured JSONL, viewed via `co tail`/`co trace`), and
   the dream daemon's KICK queue (`$CO_HOME/daemons/dream/queue/`). Asciiball's
   free-surface premise — *text is the payload* — matches co's substrate
   exactly: any of these files goes onto the ball unmodified via
   `--glyph-source`.
2. **co executes through an approval-gated shell** with a safe-prefix
   auto-approve list and a sanitized env. Asciiball is stdlib-only (bare
   `python3`, no venv, no network, read-only on the filesystem): it is the rare
   visualization tool co can invoke without an approval prompt or an install
   step.
3. **co is an LLM agent, not a parser.** It reads `--preview` output as text
   and composes CLI flags natively. This dissolves most of the old
   "machine-integration" gaps (`--json`, `pip`) that this file used to rank
   HIGH — what co needs instead is *discoverability* (a SKILL.md) and a way to
   feed composed text without a temp-file write (stdin source).
4. **co has inspectability as doctrine.** Mission non-goal: "making memory or
   agent state opaque — the user's model is always inspectable and
   correctable." An ambient, readable rendering of that state is a mission
   feature, not decoration. (Counter-doctrine to respect: "no theatrical
   persona over completion quality" — every use case below must earn its pane
   as an *inspection surface*, never as theater.)

---

## C1: co Ambient State Planet — the `/asciiball` slash command  **[shipped mechanics, gap: the co command]**

**Entry point: `/asciiball`, a built-in-style local slash command.** The user
types it in `co chat`; co's dispatch runs a local handler that reads the state
files, picks flags, and spawns the render into a pane — and returns `LocalOnly`
(*no LLM turn, no tokens, deterministic*). This is deliberately **not** the
model-facing skills path: the agent does not decide to render — the human asks
for the pane. co already ships the exact precedent — `/status` is a "read-only,
no model call" textual state snapshot (see co `docs/specs/tui.md` §4); **`/asciiball`
is its ambient, visual sibling.** (`/status` prints the six-section snapshot once;
`/asciiball` paints the same state as a living planet you leave running.)

**What it shows.** A pane beside `co chat` whose planet optics encode co's live
operational state — grounded in co's *actual* observable state (every input
below is a local file the `/asciiball` handler reads), not hypothetical CI
metrics:

| co signal (source) | Asciiball axis (shipped flag) |
|---|---|
| Context pressure — tokens vs. window, compaction proximity (turn usage / realtime estimate, the same figure `/status` reports) | `--fill` — solid ball = fresh context, ghost = compaction imminent |
| Turn / daemon activity (spans log tail, `co tail`'s data) | `--speed` — idle drift vs. working spin |
| Queued dream KICKs (files in `daemons/dream/queue/`) | far-side glyphs showing through the hollow shell — queued work visibly waiting to rotate into view |
| Startup degradations (missing integrations) | `--void-scale`/`--void-soft` — punched voids where capability is missing |
| Session transcript (current `sessions/*.jsonl`) | the glyph source itself — the ball is *made of* the conversation |

**How the handler runs it.** On dispatch, `/asciiball` reads the state, maps it
to flags, and launches the non-blocking render path — `python3
src/rotating_text.py --frames N --glyph-source <state-file> --fill F --speed S`
(render N frames, exit 0, re-launch on the next state change). No asciiball
engine change needed; the work is the ~50-line command handler on **co's** side.

**Where the gap is (revised).** The old framing pointed this at a user-installed
skill. That was wrong for C1: a skill surfaces to the *model* and dispatches via
`DelegateToAgent` (an LLM turn), whereas launching an inspection pane is a
deterministic local op that must not cost a turn. The correct vehicle is a
built-in-style `LocalOnly` command registered in co's command registry — a
small co-core change, not a manifest entry. (The model-facing skill path still
fits the *agent-composed* cases — C3's dream screen, C5's capture — where co
generates the glyph text itself; see C4.)

**Why it serves the mission.** Stage 1 (Reliability) names "task observability"
and "compaction quality" as the focus; Stage 3 (Bounded autonomy) needs
glanceable supervision of background work. `co tail` and `/status` are the
precise instruments; `/asciiball` is the ambient one — you notice compaction
pressure in your peripheral vision before you'd think to invoke either.

---

## C2: The Memory Globe — the User Model, Inspectable at a Glance  **[shipped]**

**What.** co's mission: "the system's model of the user is the user's property
— viewable, correctable, and fully owned." The Text body makes that literal:

```bash
./bin/ascii-text.sh --glyph-source ~/.co-cli/USER.md            # the user profile on a ball
cat ~/.co-cli/memory/*.md > tmp/memory-all.md && \
  ./bin/ascii-text.sh --glyph-source tmp/memory-all.md          # the whole memory store as a ticker
```

Sentence-per-ring layout means memory items scroll past *readably* — this is a
review surface, not a lava lamp. Wrong or stale memories catch the eye in
passing, exactly the "correctable" loop the mission wants; the fix is one
`memory_manage` call away in the adjacent pane.

**Why the ball and not `cat`.** Reading the store front-to-back is a chore
nobody does; the globe makes inspection *ambient* — continuous, zero-effort
exposure to what co believes about you. Stage 2 (Personalization) names
"inspection surfaces" as a deliverable; this is one that costs zero co code
today.

**Refinement [design].** Memory items carry decay scores (recency + recall
frequency, maintained by the dream daemon). A composed source ordering items by
decay — fresh memories at the equator (widest, slowest-turning rings), decaying
ones toward the poles (shortest rings, first to fall off) — would make the
decay model itself visible. Pure composition on co's side; no engine change.

---

## C3: The Dream Screen  **[design]**

**What.** At session end, co's dream daemon runs offline: mining candidate
knowledge from transcripts, merging against existing artifacts, decaying and
archiving. Today this is invisible. The dream screen hands the vacated terminal
a slow-spinning Text ball whose glyph source is the freshly-mined memory
candidates — what co is *about to remember* scrolls past while the daemon
works.

**Why it isn't theater.** The non-goal doctrine bars persona spectacle, and a
"co is dreaming" animation for its own sake would violate it. This passes
because it is C2's review loop applied at the highest-leverage moment: the
seconds after mining and before merge are exactly when a user glancing at the
ball can spot a bad extraction ("that's not a preference, that was a one-off").
The visual *is* the audit.

**Mechanics.** Zero engine work — the daemon writes its candidate list to a
temp file and launches `rotating_text.py --glyph-source` on it; `--fill` can
track the merge/decay sweep. All co-side integration, listed here as the design
target the SKILL.md (C4) should eventually cover.

---

## C4: Two co-side vehicles — the `/asciiball` command *and* the skill  **[design, HIGH]**

co has **two** integration surfaces, and asciiball's use cases split cleanly
across them by *who initiates the render*:

1. **`/asciiball` — a built-in-style local command (user-initiated).** Carries
   **C1** (and the on-demand form of **C2**). Registered in co's command
   registry, returns `LocalOnly`, spends no LLM turn. This is the primary
   vehicle: the human wants a pane, co launches it deterministically. Sibling of
   the shipped `/status`.
2. **`~/.co-cli/skills/asciiball/SKILL.md` — a user-installed skill
   (agent-initiated).** Surfaced to the model via the `<available_skills>`
   manifest and dispatched through `DelegateToAgent` (an LLM turn). Carries the
   cases where **co itself decides to render from text it composed** — **C3**'s
   dream screen and **C5**'s frame capture into an artifact. The SKILL.md
   documents when to render, the non-blocking invocation rules (`--preview` /
   `--frames N` — never a bare spin from a tool call), the flag-to-meaning map
   from C1's table, and the capture recipe.

**Why this replaces the old `AGENTS.md` + `--json` + `pip` trio.** co
discoverability is the command registry (for `/asciiball`) and the skills
manifest (for the skill), not a repo file; structured output is unnecessary (co
reads text); installation is a git checkout plus bare `python3` (stdlib-only is
the killer install story). The command + skill pair delivers what three roadmap
items were pointed at.

**Shell-safety note.** The invocation `python3 <repo>/src/rotating_*.py
--preview …` is read-only and side-effect-free — a legitimate candidate for
co's `shell_safe_commands` auto-approve list, making renders frictionless
inside a turn.

---

## C5: Frame Capture into co's Artifacts  **[ecosystem-gap]**

**What.** co produces durable text artifacts constantly: memory items, session
summaries, notes in the Obsidian vault, the `co trace` HTML viewer. A captured
frame — `--preview` or `--frames 1` — embeds in any of them as plain
`<pre>`/fenced text: no image, no link rot, renders in every markdown viewer.
Concrete slots: a session summary headed by a one-frame ball of its own
transcript; a `co trace` HTML page headed by a state planet of that trace's
stats.

**Gap.** Clean capture wants a first-class emit path — today you scrape
`--preview` stdout (workable for an agent, inelegant). `--export html` (a
self-contained colored `<pre>`; `scripts/build_showcase.py` already emits this
internally, promoting it to a flag is the only work) serves the `co trace`
slot; plain-text single-frame capture works today.

---

## Roadmap — re-ranked for co

| Enabling feature | Old priority | co priority | Why the change |
|-----------------|-------------|-------------|----------------|
| `/asciiball` local command in co's registry (C1, C4) | — | **HIGH** | user-initiated inspection pane; `LocalOnly`, no LLM turn; sibling of `/status` |
| `SKILL.md` for co's skill system (C4) | — (was `AGENTS.md`, MED) | **HIGH** | agent-initiated renders from composed text (C3, C5) |
| stdin / `--glyph-text` source (feed composed text without a temp file) | — | **HIGH** | co composes state text in-memory; a file write costs an approval, stdin doesn't |
| `--export html` (promote showcase emit to a flag) | MED | MED | the `co trace` HTML slot (C5) |
| any-key exit + idle wrapper | LOW | LOW–MED | the dream screen (C3) wants clean lifecycle handoff |
| `--json` structured frames | HIGH | **LOW** | co reads `--preview` text natively; keep only for non-agent consumers |
| `pyproject.toml` → `pip install` | HIGH | **LOW** | stdlib-only + git checkout is already a zero-friction install for co's shell |
| Homebrew formula | LOW | drop | no co-serving path |

**Bottom line.** For co, free-surface asciiball is not a screensaver genre play
— it is an **inspection organ**: the mission demands the user's model and the
agent's state be visible and correctable, and a hollow readable planet in a
spare pane is that demand made ambient. Everything renders today; the real gaps
are co-side wiring — a `/asciiball` local command (user-initiated, C1) plus a
skill for the agent-initiated cases (C3, C5) — and a stdin text source on this
side. The old machine-integration roadmap (`--json`, `pip`) was solving for a
consumer co isn't.
