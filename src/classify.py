"""The privacy boundary. Read this file first.

This is the ONLY code in the project that ever sees an actual keystroke.
Everything downstream — store.py, engine/, the dashboard — receives one of
six fixed strings and nothing else.

AGENTS.md hard rule 2: "The characters you type" are never captured. The
landing page repeats that promise to users. `classify()` is where that
promise is either kept or broken, which is why it is a separate module with
its own exhaustive test file rather than three lines inlined into the
listener callback.

The design that makes the guarantee structural rather than aspirational:

  * classify() returns a KeyClass — a Literal of six values. There is no
    code path that returns anything derived from the key. A mistake here is
    a type error, not a silent leak.
  * It takes the key and returns immediately. The key object is never
    stored, logged, buffered, or passed on. Nothing else in collector/
    accepts a key argument at all.
  * The mapping is by IDENTITY against pynput's Key enum, never by string
    formatting. `str(key)` on a printable key yields "'a'" — the character
    itself — so it is deliberately never called on the key.

If a future feature needs the actual key pressed, the feature is designed
wrong (AGENTS.md §8). Change the feature, not this file.
"""

from __future__ import annotations

from typing import Literal

KeyClass = Literal["char", "correction", "navigation", "modifier", "space", "enter"]

# Sets are keyed on pynput's Key enum members, resolved once at import.
# Importing inside a try means the classifier stays unit-testable (and this
# module stays importable) on a machine without pynput, e.g. CI on Linux.
_KeyCodeType: type | None

try:
    from pynput.keyboard import Key, KeyCode

    _KeyCodeType = KeyCode
    _CORRECTION = {Key.backspace, Key.delete}
    _NAVIGATION = {
        Key.up, Key.down, Key.left, Key.right,
        Key.home, Key.end, Key.page_up, Key.page_down,
        Key.tab,
    }
    _MODIFIER = {
        Key.shift, Key.shift_l, Key.shift_r,
        Key.ctrl, Key.ctrl_l, Key.ctrl_r,
        Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
        Key.cmd, Key.cmd_l, Key.cmd_r,
        Key.caps_lock, Key.num_lock, Key.scroll_lock,
        Key.esc, Key.insert,
    }
    _SPACE = {Key.space}
    _ENTER = {Key.enter}
    _PYNPUT = True
except Exception:  # pragma: no cover - exercised only on non-Windows CI
    _KeyCodeType = None
    _CORRECTION = _NAVIGATION = _MODIFIER = _SPACE = _ENTER = set()
    _PYNPUT = False


def classify(key: object) -> KeyClass:
    """Map a pynput key to its coarse class. Returns one of six constants.

    Every branch returns a literal. No branch returns, formats, or embeds any
    part of `key`. Function keys and anything otherwise unrecognised fall to
    "modifier" rather than "char", because misfiling an unknown key as a
    character would inflate the keystroke counts that Activity and the
    inter-key-delay signal are built on.
    """
    if key in _SPACE:
        return "space"
    if key in _ENTER:
        return "enter"
    if key in _CORRECTION:
        return "correction"
    if key in _NAVIGATION:
        return "navigation"
    if key in _MODIFIER:
        return "modifier"

    # A KeyCode is a printable key. We check only that it HAS a character,
    # never what the character is: `.char` is compared to None and then
    # discarded when this function returns.
    if _KeyCodeType is not None and isinstance(key, _KeyCodeType):
        return "char" if getattr(key, "char", None) is not None else "modifier"

    # Unrecognised Key enum member (F1-F20, media keys, and anything a future
    # pynput adds). Not a character.
    return "modifier"


def available() -> bool:
    """Whether keyboard classification can actually run in this process."""
    return _PYNPUT
