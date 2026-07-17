"""The imperative shell for the rotating 3D ASCII planet engine.

The single effects module: everything that touches the outside world lives here,
on one side of the load-bearing seam (*pure computation* in `ascii_sphere` vs.
*effects* here). It owns two kinds of effect:

  - FILESYSTEM -- reading the runtime assets: the `data/*.b64` surface blobs and
    the glyph/text sources (`source_path`, `load_bits`, `load_levels`,
    `load_glyphs`, `load_source_text`). Each reader does the effectful
    open()/read() and delegates every decode/parse back to the core's pure
    functions (`unpack_bits`/`unpack_levels`/`glyphs_from_text`), so the core
    stays free of I/O.
  - TERMINAL/OS -- argv (argparse), the terminal probe (theme/truecolor) and
    size, the interactive run loop, signals, and stdin/stdout.

The terminal/OS work has two faces that are PEERS, not layers: an INPUT face
(`build_common_parser`/`resolve_glyphs`/`resolve_request`, which turn argv + a
terminal probe into a pure `Config`) and an OUTPUT face (the cbreak input
handling, the interactive `run_loop` with pause/step/full-screen/help/alt-screen/
resize, the `--preview` printer). `prepare` sits between them: it reads the live
terminal size, builds the resize `rebuild` closure, and returns a `Plan`.
`_term_size` is the single place the terminal size is read; `_ROOT_DIR` the single
anchor for asset paths; the pure sizing/decoding math both feed lives in the core.

The dependency runs one way, `ascii_sphere <- shell <- apps`: this module imports
the pure pieces it drives with from the core (RESET, the shade-escape helper, the
`Config`/`Plan` value types, the sizing/step/delay math, and the decoders/parsers)
and never reaches back for any body-specific state. Every app loads its data
through these readers and spins in this one `run_loop`.
"""

import os
import sys
import math
import time
import shutil
import signal
import argparse
import contextlib

from ascii_sphere import (
    RESET,
    DEFAULT_GLYPHS,
    DEFAULT_EYE,
    DEFAULT_FAR_DIM,
    DEFAULT_FAR_FILL,
    DEFAULT_LIGHT_AZ,
    DEFAULT_LIGHT_EL,
    DEFAULT_AMBIENT,
    Config,
    Plan,
    gray_escape,
    resolve_step,
    fit_globe,
    center_frame,
    frame_delay,
    unpack_bits,
    unpack_levels,
    glyphs_from_text,
)

# Interactive control needs raw-ish terminal input (unbuffered, no echo). These
# are POSIX-only; on platforms without them (e.g. Windows) we silently fall back
# to the non-interactive spin -- the globe still runs, it just can't be paused or
# stepped by hand.
try:
    import tty
    import select
    import termios

    _HAS_TTY = True
except ImportError:  # pragma: no cover - platform-dependent
    _HAS_TTY = False


# ---------------------------------------------------------------------------
# The FILESYSTEM face: reading the runtime assets (decode delegated to the core)
# ---------------------------------------------------------------------------
# The program's file reads + asset-path resolution. Each reader does the effectful
# open()/read() and hands the raw bytes/text to a PURE core decoder/parser
# (`unpack_bits`/`unpack_levels`/`glyphs_from_text`), so the core never touches the
# filesystem. Body apps call the data loaders from here at their composition root.

# The runtime assets -- data/*.b64 (surface blobs) and the bundled README.md (the
# default --glyph-source) -- live at the repo ROOT, the parent of src/. Anchor
# every asset lookup to that root so files resolve regardless of the caller's
# working directory (README.md must stay at the root: it is the default glyph
# source and the tests depend on it). This is the ONE canonical definition.
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root


def source_path(glyph_source=None):
    """Resolve the glyph/text source path: an explicit one, else the bundled README.

    The single place the `--glyph-source`-or-README default is spelled, shared by
    `resolve_glyphs` (feature palette) and the text body's `load_source_text`
    (verbatim source) so the fallback can't drift between them.
    """
    return glyph_source or os.path.join(_ROOT_DIR, "README.md")


def load_bits(filename, w, h):
    """Decode a bit-packed base64 data file into a 0/1 bytearray.

    Thin file-reading wrapper over the core's pure `unpack_bits`: reads the base64
    text from a `.b64` data file shipped under the repo-root `data/` dir (resolved
    against `_ROOT_DIR`, so it is found regardless of the caller's working
    directory). These files ARE the runtime source of truth -- keeping them out of
    the .py source (rather than inlining the blob) is still zero-dependency: a
    stdlib file read, no image/data libraries.
    """
    path = os.path.join(_ROOT_DIR, filename)
    with open(path, encoding="ascii") as f:
        return unpack_bits(f.read().strip(), w, h)


def load_levels(filename, w, h):
    """Decode a nibble-packed base64 tone file into a bytearray of 0..15 codes.

    The tone-grid analog of `load_bits`: reads the base64 text from a `.b64` data
    file under the repo-root `data/` dir and expands it via the core's pure
    `unpack_levels`. Zero runtime dependencies -- a stdlib file read plus
    zlib/base64.
    """
    path = os.path.join(_ROOT_DIR, filename)
    with open(path, encoding="ascii") as f:
        return unpack_levels(f.read().strip(), w, h)


def load_glyphs(path, word_sep="·", sentence_sep="  "):
    """Return a feature-glyph string built from a text file's characters.

    The file-reading wrapper over the core's pure `glyphs_from_text`: read the
    source verbatim, then let the core collapse whitespace into word/sentence
    separators (see `glyphs_from_text` for the separator rules). Returns None if
    the file is missing/unreadable, or if it reduces to nothing, so the caller can
    fall back.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return None
    return glyphs_from_text(text, word_sep=word_sep, sentence_sep=sentence_sep)


def load_source_text(path):
    """Raw text of a source file, verbatim (used by the text body's own layout).

    Unlike `load_glyphs` -- which collapses whitespace to a word separator to
    build a hole-free feature palette -- this returns the file unchanged, so a
    caller can do its OWN layout over it (e.g. the text body laying the source out
    with its own see-through gaps). Returns None if the file is missing/unreadable
    (caller falls back).
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


# --preview renders 3 static frames; this is how many rotation steps apart they
# are, spread far enough to look visibly different from each other.
PREVIEW_STRIDE = 4


def _term_size():
    """The single place the shell reads the live terminal size -> (cols, rows).

    Keeps the `(80, 24)` fallback the pure sizing math was always fed, so a
    piped/headless run (no real terminal) stays deterministic.
    """
    return shutil.get_terminal_size((80, 24))  # (cols, rows)


# The `?` help overlay. Content is data (key, description) so the layout stays in
# one place; the colors are pulled from the SAME grayscale ramp the sphere rides
# (via gray_escape), so the panel reads as part of the body on either theme.
_HELP_TITLE = "ASCIIBALL · CONTROLS"
_HELP_ROWS = (
    ("space", "pause / resume"),
    ("← →", "step one tile"),
    ("f", "toggle full-screen"),
    ("esc", "exit full-screen"),
    ("?", "toggle this help"),
    ("q", "quit"),
)
_HELP_HINT = "press ? to close, or a listed key"


def _help_overlay(theme, truecolor):
    """Return a themed, centred key-map overlay (clears the screen, draws help).

    Grayscale is matched to the globe: a bright bold title/keys (the near-face
    end of the ramp), mid-gray descriptions (like the stipple), and a dim rule +
    hint that recede toward the background (like the far shell). `truecolor` is
    the engine's already-detected depth (globe.truecolor), so the panel emits
    24-bit or 256-indexed grays exactly as the sphere does -- no separate detect.
    """
    key_c = gray_escape(0.95, theme, "1", truecolor)  # bright bold (near face)
    desc_c = gray_escape(0.55, theme, "22", truecolor)  # mid gray (stipple)
    dim_c = gray_escape(0.22, theme, "", truecolor)  # faint (far ghost)
    key_w = max(len(k) for k, _ in _HELP_ROWS)
    rule = "─" * len(_HELP_TITLE)

    plain = [
        _HELP_TITLE,
        rule,
        *(f"  {k:<{key_w}}  {d}" for k, d in _HELP_ROWS),
        "",
        _HELP_HINT,
    ]
    width = max(len(p) for p in plain)
    cols, rows = shutil.get_terminal_size((80, 24))
    left = " " * max(0, (cols - width) // 2)
    top = max(0, (rows - len(plain)) // 2)

    out = [
        "\033[H\033[2J",
        "\n" * top,
        f"{left}{key_c}{_HELP_TITLE}{RESET}\n",
        f"{left}{dim_c}{rule}{RESET}\n",
    ]
    for k, d in _HELP_ROWS:
        out.append(f"{left}{key_c}  {k:<{key_w}}  {desc_c}{d}{RESET}\n")
    out.append(f"\n{left}{dim_c}{_HELP_HINT}{RESET}\n")
    return "".join(out)


@contextlib.contextmanager
def cbreak_input():
    """Put stdin in cbreak mode for the duration of the block, then restore it.

    cbreak delivers each keystroke immediately (no Enter, no echo) so the loop
    can read arrows and space as they're pressed. It deliberately leaves ISIG
    enabled, so Ctrl+C still raises KeyboardInterrupt -- the caller keeps its
    existing handler. Yields True when the mode was actually applied (an
    interactive TTY on a POSIX platform), False otherwise so the caller can fall
    back to the plain timed spin. The previous tty attributes are always
    restored, even if the body raises.
    """
    if not (_HAS_TTY and sys.stdin.isatty()):
        yield False
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# Arrow keys arrive as a CSI escape sequence (ESC [ A/B/C/D); this maps the final
# byte (what `_read_csi` returns) to a token. Only left/right are acted on; up/down
# ride through as unmapped input.
_ARROWS = {"C": "right", "D": "left", "A": "up", "B": "down"}


def _read_csi(fd):
    """Read the rest of a CSI sequence after the leading ESC '[', return it as text.

    A CSI ends at its FINAL byte (0x40-0x7E); the parameter/intermediate bytes
    before it are 0x20-0x3F. So we read until the first byte in the final range:
    an arrow yields just "C"/"D"/…; an SGR mouse report yields "<b;x;yM" (or "…m").
    Reads only what is already queued (zero-timeout select) so a lone "ESC[" can
    never block, and caps the length so a malformed stream can't spin.
    """
    seq = b""
    while len(seq) < 32:
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            break
        b1 = os.read(fd, 1)
        seq += b1
        if 0x40 <= b1[0] <= 0x7E:  # final byte -> sequence complete
            break
    return seq.decode("latin-1", "ignore")


def read_key(timeout):
    """Wait up to `timeout` seconds for input; return a token or None.

    Returns "left"/"right"/"up"/"down" for arrow keys, "mouse" for any mouse
    report (motion or button, once the caller has enabled reporting -- see
    `_MOUSE_ON`), "esc" for a bare Escape, "csi" for any other escape sequence, the
    literal character for an ordinary key, and None ONLY when `timeout` elapses
    with no input. A `timeout` of None blocks until input arrives (used while
    paused / on the help overlay, so a still globe idles at 0% CPU instead of
    busy-spinning).

    We read raw bytes from the fd with os.read, NOT sys.stdin.read: the latter is
    a buffered text wrapper that would slurp a whole chunk into Python's own
    buffer, leaving select() (which only sees the kernel fd) blind to bytes still
    queued there -- so a paused globe would hang on input it had already drained.
    """
    fd = sys.stdin.fileno()
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None
    ch = os.read(fd, 1)
    if ch != b"\033":
        return ch.decode("utf-8", "replace")
    r2, _, _ = select.select([fd], [], [], 0)
    if not r2:
        return "esc"  # bare Escape, not the lead-in of a sequence
    if os.read(fd, 1) != b"[":
        return "csi"  # some other ESC-prefixed input (Alt-key, ESC O …): unmapped
    seq = _read_csi(fd)
    if seq.startswith("<"):
        return "mouse"  # SGR mouse report: ESC [ < b ; x ; y (M|m)
    return _ARROWS.get(seq, "csi")  # arrow, else an unhandled sequence -> unmapped


# Mouse reporting, enabled ONLY while full-screen (see run_loop): any-motion
# (1003) + SGR extended coords (1006), so a move or click arrives as an ESC-[-<
# sequence `read_key` decodes to "mouse". Framed mode and non-interactive runs
# leave the host terminal's mouse untouched; cleanup always emits the off pair.
_MOUSE_ON = "\033[?1003h\033[?1006h"
_MOUSE_OFF = "\033[?1003l\033[?1006l"


class _Terminated(Exception):
    """Raised by our SIGTERM/SIGHUP handler so the cleanup `finally` runs.

    A long-idle spin is usually ended by the multiplexer, not a keypress
    (tmux kill-pane, `kill <pid>`, logout/SIGHUP).
    The default disposition for those signals terminates the process WITHOUT
    running `finally`, which would strand the terminal in cbreak mode with a
    hidden cursor, mouse reporting on, and a half-drawn alt-screen. Converting
    them into an exception funnels them through the same shutdown as q / Ctrl+C.
    """


def _raise_terminated(signum, frame):
    raise _Terminated


def run_loop(globe, step, delay, frames, rebuild=None):
    """Spin the globe in the live terminal until `frames` elapse or the user quits.

    `frames == 0` runs forever; a positive count renders exactly that many and
    returns. `step` is the per-frame surface rotation (radians); `delay` is the
    pace between frames (already scaled by --speed). `angle` is kept wrapped so it
    never accumulates error over long runs -- rotation is periodic in 2*pi. The
    text rides the surface, so there is nothing else to advance: the glued glyphs
    travel with `angle`. The body name and data provenance for the footer come
    from `globe.surface`, so the loop carries no body-specific labels.

    On an interactive terminal the pace `delay` doubles as the input wait: each
    frame we block on stdin for up to `delay` instead of sleeping, so a keypress
    takes effect at once. Space toggles pause; the left/right arrows nudge the
    globe one tile and pause (manual stepping); `f` maximizes the disc and `esc`
    backs out; `?` pops the key map; q quits. When paused (or on the help overlay)
    we wait on stdin with no timeout, so a still globe costs no CPU. A non-TTY
    (pipe, --frames in a script) falls back to the plain timed spin unchanged.

    FULL-SCREEN is a distinct interaction mode. The disc is maximized AND the loop
    tightens the input contract: only the mapped keys act, and any OTHER key --
    plus mouse motion / clicks, which we start reporting on entry -- surfaces the
    key map instead of being silently swallowed (so an immersive full-screen spin
    always tells you how to drive or leave it). Framed mode keeps the relaxed
    contract: an unbound key just advances a frame. `esc`/`f` return to framed and
    stop the mouse reporting.

    A live infinite run to a real terminal (`frames <= 0` and stdout is a TTY)
    uses the alternate screen buffer, so exiting restores whatever was on screen
    before instead of leaving the last frame in scrollback. A terminal resize
    (SIGWINCH) rebuilds the globe to the new size (when `rebuild` is given) so the
    planet re-fills the window; `angle` is preserved across the swap. SIGTERM and
    SIGHUP (the kill signals a multiplexer / logout sends an idle pane) are routed
    through the same cleanup so the terminal is always restored. None of this
    applies to the `--frames N` inspection/pipe path.
    """
    name = globe.surface.name
    provenance = globe.surface.provenance
    two_pi = 2.0 * math.pi
    angle = 0.0
    # frames <= 0 => run forever (sentinel -1 never reaches the 0 stop value);
    # a positive count decrements to 0 and stops. The `if remaining > 0` guard
    # below means the sentinel is never decremented, so it stays negative.
    remaining = frames if frames > 0 else -1
    paused = False
    # `f` toggles a maximized disc; only offered when we can actually re-size
    # (rebuild is None when --radius is pinned, so the footprint is fixed).
    fullscreen = False
    can_scale = rebuild is not None
    show_help = False  # `?` (or unmapped input in full-screen) pops a key-map overlay
    help_drawn = False  # the overlay is static -> draw it once, not every idle frame
    # Alt-screen only for a live infinite spin on a real terminal -- never for a
    # finite --frames run (those stay visible / pipeable) or a non-TTY sink.
    use_altscreen = sys.stdout.isatty() and frames <= 0

    # Rescale-on-resize: a SIGWINCH handler just flips a flag (kept minimal so it
    # is async-signal-safe); the next frame does the rebuild. select()/sleep()
    # auto-retry after the handler (PEP 475), so read_key is unaffected.
    resized = False

    def _on_winch(signum, frame):
        nonlocal resized
        resized = True

    # Signals a live spin is actually ended by: SIGWINCH (resize) plus the kill
    # signals a multiplexer / logout delivers (SIGTERM/SIGHUP), the latter routed
    # through the cleanup finally instead of terminating with the terminal
    # stranded. All guarded: absent on some platforms (Windows has no SIGHUP) or
    # uninstallable off the main thread; the spin still works either way.
    installed = {}
    handlers = [("SIGTERM", _raise_terminated), ("SIGHUP", _raise_terminated)]
    if rebuild is not None and sys.stdout.isatty():
        handlers.append(("SIGWINCH", _on_winch))
    for signame, handler in handlers:
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            installed[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):
            pass  # not the main thread -> skip; the spin still works

    mouse_on = False  # whether we've emitted the mouse-reporting enable escape

    def set_mouse(on):
        nonlocal mouse_on
        if on and not mouse_on:
            sys.stdout.write(_MOUSE_ON)
            mouse_on = True
        elif not on and mouse_on:
            sys.stdout.write(_MOUSE_OFF)
            mouse_on = False

    # Footer tinted from the same ramp (a mid gray) so the bottom bar reads as
    # part of the body rather than stark default-white; theme + depth come from
    # the globe, i.e. the engine's already-detected 256/truecolor setting.
    footer_c = gray_escape(0.5, globe.theme, "22", globe.truecolor)

    sys.stdout.write(
        ("\033[?1049h" if use_altscreen else "") + "\033[2J\033[?25l"
    )  # (enter alt-screen), clear screen, hide cursor
    try:
        with cbreak_input() as interactive:
            while remaining != 0:
                if resized and rebuild is not None:
                    resized = False
                    globe = rebuild(fullscreen)  # keep the current size mode
                    # `resolve_step` is always positive, but a body may spin the
                    # OTHER way (the text body negates the step so it reads
                    # left-to-right); preserve the incoming sign across rebuilds
                    # so a resize / `f`-toggle can't silently revert it.
                    step = math.copysign(resolve_step(globe), step)
                    sys.stdout.write("\033[2J")  # full clear for the new size
                    help_drawn = False  # overlay must be re-centred for the new size

                # --- draw ---
                if interactive and show_help:
                    if not help_drawn:  # static overlay: redraw only when it changes
                        sys.stdout.write(_help_overlay(globe.theme, globe.truecolor))
                        sys.stdout.flush()
                        help_drawn = True
                else:
                    sys.stdout.write("\033[H")  # home (no full clear -> less flicker)
                    cols, rows = _term_size()
                    body, pad = center_frame(
                        globe.render(angle), globe.cols, globe.rows, cols, rows
                    )
                    sys.stdout.write(body)
                    if interactive:
                        state = "paused " if paused else "spinning"
                        parts = ["space pause", "← → step"]
                        if can_scale:
                            fs = "on" if fullscreen else "off"
                            tog = "esc/f" if fullscreen else "f"
                            parts.append(f"{tog} full:{fs}")
                        parts += ["? help", "q quit"]
                        footer = f"  {name} | {state} | {'  '.join(parts)}"
                    else:
                        footer = f"  {name} | {provenance} | Ctrl+C to stop"
                    sys.stdout.write("\n" + pad + footer_c + footer + RESET)
                    sys.stdout.write("\033[J")  # erase below (stale lines on resize)
                    sys.stdout.flush()
                    if remaining > 0:
                        remaining -= 1

                # --- non-interactive: plain timed spin, honouring --frames ---
                if not interactive:
                    angle = (angle - step) % two_pi
                    if delay:
                        time.sleep(delay)
                    continue

                # --- input: the frame wait IS the input wait; block (no timeout)
                # while paused or on the overlay so a still globe burns no CPU ---
                key = read_key(None if (paused or show_help) else delay)

                if key == "?":
                    show_help = not show_help  # `?` toggles the key map
                    help_drawn = False
                    if not show_help:
                        sys.stdout.write("\033[2J")  # clear it before the globe returns
                    continue

                # A mapped key acts (and, from the overlay, also dismisses it).
                mapped = (
                    key in ("q", "Q", " ", "left", "right")
                    or (key in ("f", "F") and can_scale)
                    or (key == "esc" and fullscreen and can_scale)
                )
                if show_help:
                    if not mapped:
                        # On the overlay, an unmapped key / mouse event just keeps
                        # it up (no redraw -> mouse motion can't flicker it).
                        continue
                    show_help = False
                    sys.stdout.write("\033[2J")  # clear help; globe returns next frame

                if key in ("q", "Q"):
                    break
                elif key == " ":
                    paused = not paused
                elif key == "right":  # step forward (the natural spin direction)
                    paused, angle = True, (angle - step) % two_pi
                elif key == "left":  # step backward
                    paused, angle = True, (angle + step) % two_pi
                elif key in ("f", "F") and can_scale:
                    fullscreen = not fullscreen
                    globe = rebuild(fullscreen)
                    step = math.copysign(resolve_step(globe), step)  # keep sign
                    set_mouse(fullscreen)  # report the mouse only while full-screen
                    sys.stdout.write("\033[2J")  # size changed -> clear stale cells
                elif key == "esc" and fullscreen and can_scale:
                    # ESC backs out of full-screen (reversible mode-exit); it is
                    # deliberately NOT a quit -- `q` owns that.
                    fullscreen = False
                    globe = rebuild(fullscreen)
                    step = math.copysign(resolve_step(globe), step)  # keep sign
                    set_mouse(False)
                    sys.stdout.write("\033[2J")
                elif key is None:
                    # Timed out with no input while spinning -> advance one frame.
                    if not paused:
                        angle = (angle - step) % two_pi
                elif fullscreen:
                    # Full-screen input contract: any unmapped key / mouse move /
                    # click surfaces the key map instead of being swallowed.
                    show_help = True
                    help_drawn = False
                elif not paused:
                    # Framed: an unbound key just advances a frame (as a timeout
                    # would). While paused, an unbound key just redraws.
                    angle = (angle - step) % two_pi
    except (KeyboardInterrupt, _Terminated):
        pass
    finally:
        set_mouse(False)  # stop mouse reporting (idempotent) before restoring
        for sig, handler in installed.items():
            signal.signal(sig, handler)  # restore prior dispositions
        if use_altscreen:
            # Show cursor, then leave the alt-screen -> the pre-run screen is
            # restored (scrollback intact), no last frame left behind.
            sys.stdout.write("\033[?25h\033[?1049l")
        else:
            sys.stdout.write("\033[?25h\n")  # restore cursor
        sys.stdout.flush()


def render_preview(globe, step, frames=3):
    """Print `frames` static, rotation-separated frames (used by --preview)."""
    for i in range(frames):
        print(globe.render(-step * i * PREVIEW_STRIDE))
        print("---")


def _parse_osc11(reply):
    """Pick "dark"/"light" from an OSC 11 reply, or None if it isn't one.

    The reply looks like `ESC ] 11 ; rgb:RRRR/GGGG/BBBB (BEL|ST)` -- each channel
    is 1-4 hex digits. Relative luminance decides which side of mid-grey the
    background sits on.
    """
    marker = reply.find("rgb:")
    if marker < 0:
        return None
    spec = reply[marker + 4 :]
    parts = spec.replace("\a", "/").replace("\033", "/").replace("\\", "/").split("/")
    chans = [p for p in parts[:3] if p]
    if len(chans) < 3:
        return None
    try:
        rgb = [int(h, 16) / (16 ** len(h) - 1) for h in chans]
    except ValueError:
        return None
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return "light" if lum >= 0.5 else "dark"


def _query_osc11(timeout=0.15):
    """Ask the terminal for its background color via OSC 11; None if unavailable.

    Needs a TTY on both stdin and stdout. Puts the tty in cbreak, writes the
    query, and reads the reply with a bounded `select` so a terminal that doesn't
    answer can never hang startup. Terminal state is always restored.
    """
    if not (_HAS_TTY and sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    fd = sys.stdin.fileno()
    try:
        saved = termios.tcgetattr(fd)
    except (termios.error, ValueError):
        return None
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033]11;?\033\\")
        sys.stdout.flush()
        reply = ""
        while len(reply) < 64:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                break
            chunk = os.read(fd, 32).decode("latin-1", "ignore")
            if not chunk:
                break
            reply += chunk
            if "\a" in reply or "\033\\" in reply:  # BEL or ST terminator
                break
        return _parse_osc11(reply)
    except Exception:  # pragma: no cover - terminal quirk; fall back gracefully
        return None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        except Exception:  # pragma: no cover
            pass


def detect_theme(default="dark"):
    """Best-effort terminal-background detection, stdlib-only -> "dark"/"light".

    Order: an OSC 11 query the terminal answers (needs a TTY; bounded so it can't
    hang), then the $COLORFGBG env var many terminals export as "fg;bg", then
    `default`. Piped/redirected runs (no TTY, e.g. --preview under the golden
    tests) skip the query, so they stay deterministic on the fallback.
    """
    queried = _query_osc11()
    if queried is not None:
        return queried
    cfb = os.environ.get("COLORFGBG")
    if cfb:
        try:
            bg = int(cfb.split(";")[-1])
        except ValueError:
            bg = None
        if bg is not None:
            # ANSI palette: 0-6 and 8 are dark grounds; 7 and 9-15 are light.
            return "dark" if bg in (0, 1, 2, 3, 4, 5, 6, 8) else "light"
    return default


def detect_truecolor():
    """Best-effort 24-bit color detection, stdlib-only -> True/False.

    True only when stdout is a live TTY AND the environment advertises direct
    color -- $COLORTERM is "truecolor"/"24bit" (the de-facto signal every modern
    terminal exports) or $TERM names a *-direct entry. The TTY gate matters:
    piped/redirected runs (e.g. --preview under the golden tests, or `> file`)
    fall back to the deterministic 256-color ramp regardless of the environment,
    so the pinned goldens never depend on the runner's COLORTERM.
    """
    if not sys.stdout.isatty():
        return False
    if os.environ.get("COLORTERM", "").strip().lower() in ("truecolor", "24bit"):
        return True
    term = os.environ.get("TERM", "")
    return term.endswith("-direct") or "direct" in term


# ---------------------------------------------------------------------------
# The INPUT face: argv + a terminal probe -> a pure Config (peers with the loop)
# ---------------------------------------------------------------------------
# This is the shell's argparse-facing side: it builds the parser every app shares,
# turns parsed args into the feature-glyph palette, and resolves a parsed Namespace
# (probing the live terminal for the "auto" knobs) into the terminal-agnostic
# `Config` the core consumes. It is a PEER of the run loop above, not a layer over
# it: both are effect surfaces of the one shell.


def build_common_parser(
    description,
    *,
    body_noun="globe",
    fill_default=1.0,
    fill_help=None,
    falloff_default=0.0,
    void_scale_default=1,
    void_soft_default=0.0,
    far_dim_default=DEFAULT_FAR_DIM,
    far_fill_default=DEFAULT_FAR_FILL,
):
    """ArgumentParser preloaded with every flag common to all bodies.

    Bodies call this, then `.add_argument(...)` any body-specific flags of their
    own, then parse. `body_noun` fills the radius/aspect help text;
    `fill_default`/`fill_help` let each body set its own --fill centre keep rate.
    `falloff_default` sets --fill-falloff (the radial taper of that fill toward the
    limb), `void_scale_default`/`void_soft_default` the void block size + edge
    softening. `far_dim_default`/`far_fill_default` set the far (back) wall's
    brightness + density: a body seen through big windows (Earth's far continents
    behind the near oceans) may want a brighter, denser back wall so its
    edge->centre depth cavity reads, where a body already dense up front leaves the
    engine's fainter default. Each body passes its OWN geo-specific tuning of these
    knobs (different surfaces dome, soften, and show through differently); the knobs
    live once in the core, only the per-body defaults differ.
    """
    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--radius",
        type=int,
        default=0,
        help=f"{body_noun.capitalize()} radius in rows (0 = auto-fit terminal).",
    )
    p.add_argument(
        "--aspect",
        type=float,
        default=2.3,
        help="Font cell height/width ratio. ~2.0-2.3 suits most "
        f"terminals; lower it if the {body_noun} looks too wide, "
        "raise it if too tall (egg-shaped).",
    )
    p.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor on the (auto or given) radius. e.g. 0.75 = three-quarter size.",
    )
    p.add_argument(
        "--bold-front",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Draw the near (front) hemisphere in bold so it advances "
        "visually against the dimmer far side -- sharpens the 3D "
        "read (default on; pass --no-bold-front to disable).",
    )
    p.add_argument(
        "--eye",
        type=float,
        default=DEFAULT_EYE,
        metavar="DIST",
        help="Perspective eye distance in sphere-radii (must be > 1). Smaller = "
        "stronger perspective: the near and far walls split further apart in "
        "latitude (no row-by-row alignment) and the far wall is foreshortened "
        f"smaller, like a receding back wall. Default {DEFAULT_EYE:g}; a large "
        "value (e.g. 100) flattens to the old orthographic look.",
    )
    p.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Rotation speed as a ratio of the default (1 = normal, "
        "2 = twice as fast, 0.5 = half).",
    )
    p.add_argument("--fps", type=float, default=18.0, help="Target frames per second.")
    p.add_argument(
        "--frames",
        type=int,
        default=0,
        help="Render N frames then exit (0 = run until Ctrl+C).",
    )
    p.add_argument(
        "--glyphs",
        default=None,
        metavar="CHARS",
        help="Explicit string of characters to draw features with "
        "(overrides --glyph-source).",
    )
    p.add_argument(
        "--glyph-source",
        default=None,
        metavar="PATH",
        help="Text file whose characters are drawn across the surface "
        "(in order, verbatim). Default: the bundled README.md.",
    )
    p.add_argument(
        "--word-sep",
        nargs="?",
        const="·",
        default="·",
        metavar="CHAR",
        help="Glyph placed between words (default: middle dot ·). Pass "
        "a character to change it, e.g. --word-sep '*', or "
        "--no-word-sep to run words together with no separator.",
    )
    p.add_argument(
        "--no-word-sep",
        dest="word_sep",
        action="store_const",
        const="",
        help="Run words together (drop spaces) instead of separating them.",
    )
    p.add_argument(
        "--limb-fade",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Thin the glyphs to blanks toward the limb so the rim "
        "dissolves into a clean horizon instead of crushing into a "
        "solid edge (default on; pass --no-limb-fade to keep it).",
    )
    # Far-wall visibility (Axis B/C), common to every body: the back of the hollow
    # ball, seen through the windows, counter-scrolls against the front. The two
    # knobs are orthogonal -- far_dim moves only brightness, far_fill only density.
    p.add_argument(
        "--far-dim",
        type=float,
        default=far_dim_default,
        metavar="FRAC",
        help="Contrast of the far (back) wall seen through the glass (0..1). Lower "
        "= dimmer ghost. 0 drops the back wall entirely (front-face only). The far "
        f"ramp is capped well below the near face, so even 1.0 stays a ghost. "
        f"Default {far_dim_default:g}.",
    )
    p.add_argument(
        "--far-fill",
        type=float,
        default=far_fill_default,
        metavar="FRAC",
        help="Fraction of the far wall's tiles kept (0..1), thinning its "
        "counter-scrolling texture into a sparse dotted depth field rather than a "
        "dense second surface fighting the front. Above ~0.6 the back reads as a "
        "competing (mirrored, backwards) surface; 0 drops the back wall. Default "
        f"{far_fill_default:g} (pass 1 for the old dense see-through).",
    )
    # Directional lighting (Axis C): a fixed 'sun' the ball rotates under. Shades
    # by the surface normal (N . L), so the disc reads as a lit 3D sphere with an
    # offset highlight and a dark terminator -- both walls -- instead of a flat disc.
    p.add_argument(
        "--light-az",
        type=float,
        default=DEFAULT_LIGHT_AZ,
        metavar="DEG",
        help="Light azimuth in degrees: 0 = from the right, +90 = from straight "
        f"above, 180 = from the left. Default {DEFAULT_LIGHT_AZ:g} (upper-left).",
    )
    p.add_argument(
        "--light-el",
        type=float,
        default=DEFAULT_LIGHT_EL,
        metavar="DEG",
        help="Light elevation toward the viewer in degrees: 0 = pure side light "
        "(a thin lit crescent, strong terminator), 90 = head-on (lights the whole "
        f"front, no terminator). Default {DEFAULT_LIGHT_EL:g}.",
    )
    p.add_argument(
        "--ambient",
        type=float,
        default=DEFAULT_AMBIENT,
        metavar="FRAC",
        help="Shadow-side floor (0..1): 0 = the terminator falls to pure black "
        "(most dramatic, but the dark side's text/features go unreadable); higher "
        f"lifts the shadow so it stays legible. Default {DEFAULT_AMBIENT:g}.",
    )
    p.add_argument(
        "--fill",
        type=float,
        default=fill_default,
        metavar="FRAC",
        help=fill_help
        or "Target fraction (0..1) of the disc that shows a glyph; the "
        "rest is thinned to true voids (blanked, not see-through). "
        "With --fill-falloff > 0 this is the keep rate at the disc centre "
        "(the peak), tapering toward the limb. Default 1.0 (no thinning).",
    )
    p.add_argument(
        "--fill-falloff",
        type=float,
        default=falloff_default,
        metavar="FRAC",
        help="Radial taper (0..1) of --fill from the disc centre to the limb, so "
        "ink is dense through the middle and thins to sparser windows at the rim "
        "(the void field rounds with the ball instead of a flat slab). 0 = flat "
        "(uniform fill everywhere); e.g. 0.5 = the limb keeps half the centre "
        "rate. Default 0 (off).",
    )
    p.add_argument(
        "--void-scale",
        type=int,
        default=void_scale_default,
        metavar="N",
        help="Block size for the fill dropout: NxN surface-tile blocks toggle on/"
        "off together, so the void forms coherent tiled windows (a digital, hollow "
        "shell) instead of salt-and-pepper specks. 1 = per-tile speckle; raise it "
        "for bigger, blockier windows.",
    )
    p.add_argument(
        "--void-soft",
        type=float,
        default=void_soft_default,
        metavar="FRAC",
        help="Softening (0..1) of the void-scale block edges: blends a per-tile "
        "jitter into the block dropout so windows read as organic patches rather "
        "than hard NxN squares (a finer-grained void). 0 = crisp blocks; 1 = full "
        "per-tile speckle.",
    )
    p.add_argument(
        "--theme",
        choices=("auto", "dark", "light"),
        default="auto",
        help="Terminal background the depth shading is tuned against. The "
        "foreground (near) hemisphere is drawn to contrast with it and the "
        "far side recedes toward it. 'auto' (default) asks the terminal for "
        "its background color (falling back to $COLORFGBG, then dark).",
    )
    p.add_argument(
        "--color-depth",
        choices=("auto", "truecolor", "256"),
        default="auto",
        help="Grayscale resolution for the depth shading. 'auto' (default) uses "
        "24-bit color when the terminal advertises it ($COLORTERM=truecolor and a "
        "live TTY) for a smoother gradient, else the 256-color ramp. Force either "
        "with 'truecolor'/'256'. Non-TTY runs (pipes, --preview under the tests) "
        "always stay 256-color.",
    )
    p.add_argument(
        "--preview",
        action="store_true",
        help="Render 3 static frames with separators (no screen clear).",
    )
    return p


def resolve_glyphs(args):
    """Feature-glyph palette from args: explicit --glyphs wins, else --glyph-source
    (or the bundled README.md), else the built-in DEFAULT_GLYPHS.

    This is the argparse-facing INPUT side (it reads `args`); the actual file read
    goes through the shell's own filesystem readers (`load_glyphs` on the
    `source_path` that resolves --glyph-source-or-README).
    """
    if args.glyphs:
        return args.glyphs
    palette = load_glyphs(source_path(args.glyph_source), word_sep=args.word_sep)
    return palette or DEFAULT_GLYPHS


def resolve_request(args):
    """Resolve a parsed argparse Namespace into a terminal-agnostic `Config`.

    NOT a pure map: this is where the shell *probes the live terminal* to resolve
    the two "auto" knobs -- `--theme auto` -> `detect_theme()` (an OSC 11 query)
    and `--color-depth auto` -> `detect_truecolor()`. That terminal I/O is why this
    is `resolve_*`, not `*_from_args`. Constructing the `Config` value type is not
    an effect (a core data type is just a record), so everything downstream
    (`prepare`) sees concrete values and never argparse. Every flag read here is
    added unconditionally by `build_common_parser`, which every body calls, so the
    attributes are always present -- read them directly (a `getattr` fallback would
    only mask a renamed-flag bug).
    """
    theme = args.theme
    if theme == "auto":
        theme = detect_theme()
    truecolor = (
        detect_truecolor()
        if args.color_depth == "auto"
        else args.color_depth == "truecolor"
    )
    return Config(
        aspect=args.aspect,
        scale=args.scale,
        radius=args.radius,
        bold_front=args.bold_front,
        limb_fade=args.limb_fade,
        # Far-wall visibility (Axis B/C), body-agnostic defaults (DEFAULT_FAR_DIM /
        # DEFAULT_FAR_FILL): the back wall is dimmed + thinned to a dotted depth
        # field for EVERY body, so the front reads as one layer. `--far-fill 1`
        # opts back into the old dense see-through; 0 (either knob) drops it.
        far_dim=args.far_dim,
        far_fill=args.far_fill,
        light_az=args.light_az,
        light_el=args.light_el,
        ambient=args.ambient,
        fill=args.fill,
        fill_falloff=args.fill_falloff,
        void_scale=args.void_scale,
        void_soft=args.void_soft,
        eye=args.eye,
        theme=theme,
        truecolor=truecolor,
        speed=args.speed,
        fps=args.fps,
        frames=args.frames,
        preview=args.preview,
    )


def prepare(config, surface, *, reverse=False):
    """Build a `Plan` from a `Config` + a body-built `Surface`.

    The seam-crossing step: it reads the live terminal size (`_term_size`) and
    feeds it to the core's pure `fit_globe` (disc-sizing math -- auto radius +
    `--scale` + the framed/full disc footprint), snaps the step, and computes the
    frame delay + resize-rebuild policy, then returns the inert `Plan`. `make_globe`
    is recomputed on demand so a live resize (SIGWINCH -> rebuild) or a full-screen
    toggle re-fits to the CURRENT terminal size; an explicit `--radius` pins the
    footprint (so `rebuild` is None -- nothing to recompute). The ink knobs
    (fill/void/...) pass straight through to the `Globe`.

    `surface` may be a fixed `Surface` OR a pure factory `radius -> Surface`
    (`fit_globe` calls it on every fit) -- how a size-dependent layout (the text
    body's sentence rings) re-lays-out per resize / full-screen rebuild. With
    `--radius` the factory just runs once (fixed radius = fixed layout).

    `reverse` negates the (always-positive) snapped step so the surface spins the
    OTHER way -- the text body reads left-to-right this way, without mutating the
    returned Plan. `run_loop` preserves the sign across resize/full-screen rebuilds
    (`math.copysign`), so the reversed spin survives a re-fit.
    """

    def make_globe(fullscreen=False):
        cols, rows = _term_size()  # live size (resize / f-toggle re-reads)
        return fit_globe(
            surface,
            rows,
            cols,
            aspect=config.aspect,
            scale=config.scale,
            radius=config.radius,
            fullscreen=fullscreen,
            bold_front=config.bold_front,
            limb_fade=config.limb_fade,
            far_dim=config.far_dim,
            far_fill=config.far_fill,
            light_az=config.light_az,
            light_el=config.light_el,
            ambient=config.ambient,
            fill=config.fill,
            fill_falloff=config.fill_falloff,
            void_scale=config.void_scale,
            void_soft=config.void_soft,
            eye=config.eye,
            theme=config.theme,
            truecolor=config.truecolor,
        )

    globe = make_globe()
    step = resolve_step(globe)
    if reverse:
        step = -step
    delay = frame_delay(config.fps, config.speed)
    rebuild = None if config.radius else make_globe  # --radius pins the footprint
    return Plan(globe, step, delay, config.frames, rebuild)
