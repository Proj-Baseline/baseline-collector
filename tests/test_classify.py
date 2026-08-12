"""Proof that no typed content can escape the classifier.

This is the test file that matters most in the repo. AGENTS.md hard rule 2
and the landing page both promise users that the characters they type are
never captured. These tests are that promise, mechanised: they assert over
the ENTIRE printable ASCII range that the classifier's output is one of six
constants and contains no trace of the input.
"""

from __future__ import annotations

import string

import pytest

from collector.classify import KeyClass, available, classify

pytestmark = pytest.mark.skipif(
    not available(), reason="pynput not installed on this machine"
)

VALID_CLASSES = {"char", "correction", "navigation", "modifier", "space", "enter"}


def _keycode(char: str):
    from pynput.keyboard import KeyCode

    return KeyCode.from_char(char)


@pytest.mark.parametrize("char", list(string.printable))
def test_no_printable_character_survives_classification(char: str):
    """The core guarantee. For every printable character, the returned value
    must be a fixed class constant that does not contain the character."""
    result = classify(_keycode(char))
    assert result in VALID_CLASSES
    # The class strings are ASCII words; a leaked character would show up as
    # a substring or as a longer-than-expected return value.
    if char not in string.ascii_letters:
        assert char not in result
    assert len(result) <= len("correction")


@pytest.mark.parametrize("char", list(string.ascii_letters + string.digits))
def test_printable_keys_classify_as_char(char: str):
    assert classify(_keycode(char)) == "char"


def test_digits_and_letters_are_indistinguishable_after_classification():
    """Password-shaped input must be indistinguishable from prose. If 'a' and
    '7' produced different classes, keystroke classes would leak the shape of
    what was typed."""
    assert classify(_keycode("a")) == classify(_keycode("7")) == classify(_keycode("$"))


def test_space_and_enter_are_their_own_classes():
    from pynput.keyboard import Key

    assert classify(Key.space) == "space"
    assert classify(Key.enter) == "enter"


def test_corrections():
    from pynput.keyboard import Key

    assert classify(Key.backspace) == "correction"
    assert classify(Key.delete) == "correction"


def test_navigation():
    from pynput.keyboard import Key

    for key in (Key.up, Key.down, Key.left, Key.right, Key.home, Key.end, Key.tab):
        assert classify(key) == "navigation"


def test_modifiers():
    from pynput.keyboard import Key

    for key in (Key.shift, Key.ctrl, Key.alt, Key.cmd, Key.caps_lock, Key.esc):
        assert classify(key) == "modifier"


def test_unknown_keys_fall_back_to_modifier_not_char():
    """Function and media keys must not inflate keystroke counts — Activity
    and the inter-key-delay signal are built on 'char' meaning a real
    character was typed."""
    from pynput.keyboard import Key

    assert classify(Key.f1) == "modifier"
    assert classify(Key.media_play_pause) == "modifier"


def test_keycode_without_a_character_is_not_a_char():
    from pynput.keyboard import KeyCode

    # A raw virtual-key code with no character mapping (e.g. some OEM keys).
    assert classify(KeyCode(vk=0xFF, char=None)) == "modifier"


def test_return_value_is_always_from_the_fixed_set():
    """Exhaustive sweep over every Key enum member plus printable chars —
    nothing may produce a value outside the six."""
    from pynput.keyboard import Key

    seen = {classify(k) for k in Key}
    seen |= {classify(_keycode(c)) for c in string.printable}
    assert seen <= VALID_CLASSES


def test_classifier_takes_no_other_arguments():
    """classify() must remain the only entry point and must not grow a
    'keep the raw key' option. Signature is part of the guarantee."""
    import inspect

    params = list(inspect.signature(classify).parameters)
    assert params == ["key"]


def test_keyclass_literal_is_the_documented_six():
    from typing import get_args

    assert set(get_args(KeyClass)) == VALID_CLASSES
