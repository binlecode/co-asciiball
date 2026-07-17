"""Pytest config for the asciiball module tests.

Puts the `src/` dir (a sibling of this `tests/` folder, under the asciiball stack root) on
`sys.path` so the body modules can be imported by their top-level names --
`rotating_earth`, `ascii_sphere` -- exactly as they import each other at runtime.
"""

import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent / "src"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
