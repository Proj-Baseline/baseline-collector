"""Collector tunables. Same convention as engine/config.py: every value says
what it means, why it is what it is, and that it can be changed."""

from __future__ import annotations

from pathlib import Path

DEFAULT_DB = Path.home() / ".baseline" / "events.db"
# Under the user's home, not the repo. Event data is personal and must never
# land somewhere that could be committed — .gitignore already excludes *.db,
# but keeping it out of the working tree entirely is the stronger guarantee.

FLUSH_SECONDS: float = 5.0
# How often buffered events are written to SQLite. A crash loses at most this
# much. Low enough that a kill -9 costs seconds, high enough that a fast
# typist doesn't cause a disk write per keystroke. Tunable.

WINDOW_POLL_SECONDS: float = 1.0
# How often the foreground window is checked. A row is only written when the
# window actually CHANGES, so this is the resolution of switch detection, not
# the write rate. Must stay well under engine's SWITCH_TOLERANCE (20s) or
# brief flicks would be missed entirely and Residue would undercount
# interruptions. Tunable.

MOUSE_MOVE_MIN_INTERVAL: float = 1.0
# Minimum seconds between recorded mouse-move events. Moves fire hundreds of
# times a second and are only ever used as evidence that a human is present
# (engine.activity.active_runs), so recording every one would multiply the
# database size for no additional signal. Clicks and scrolls are NEVER
# throttled — they are discrete intentional acts and their timing carries
# information. Tunable.

SCHEMA_VERSION = 1
# In `meta` from day one, per AGENTS.md §5: "Retrofitting migrations onto
# users with existing data is miserable."

CLOCK_JUMP_TOLERANCE: float = 2.0
# Seconds of disagreement between wall-clock delta and monotonic delta before
# a jump is recorded in `sessions`. NTP corrections and DST shifts move
# time.time() backwards, which produces negative intervals that corrupt the
# inter-key-delay variance (AGENTS.md §5, known traps). Tunable.
