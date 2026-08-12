"""Wires the listeners to the store. The run loop.

Threading model: pynput runs the keyboard and mouse listeners on their own
threads and calls back into `Store`, which is lock-guarded. The main thread
polls the foreground window and flushes on a timer. Nothing here blocks on
anything except its own sleep, so Ctrl+C is always responsive.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from collector.classify import classify
from collector.config import (
    FLUSH_SECONDS,
    MOUSE_MOVE_MIN_INTERVAL,
    WINDOW_POLL_SECONDS,
)
from collector.store import PidLock, Store
from collector.window import active_window


def run(
    db_path: Path,
    *,
    seconds: float | None = None,
    capture_titles: bool = True,
    capture_keys: bool = True,
    on_tick: object = None,
) -> dict[str, int]:
    """Capture until interrupted, or for `seconds` if given.

    `capture_keys=False` records mouse and window activity only. Presence
    detection still works (engine treats mouse events as evidence of a human
    exactly like keystrokes), so Trace, Activity, Fragments, Bedrock and Core
    all still function — only the keystroke-derived rhythm signal is absent.
    It exists so the collector can be verified without recording anyone's
    typing.
    """
    from pynput import keyboard, mouse  # imported here so --help works anywhere

    lock = PidLock(db_path.with_suffix(".pid"))
    lock.acquire()

    last_move = 0.0
    started = time.monotonic()

    try:
        with Store(db_path) as store:
            def on_press(key: object) -> None:
                # classify() is the whole privacy boundary — the key object
                # goes in, one of six strings comes out, and the key itself
                # is never referenced again. See collector/classify.py.
                store.key(classify(key))

            def on_click(x: int, y: int, button: object, pressed: bool) -> None:
                if pressed:  # press only; a click would otherwise count twice
                    store.mouse("click")

            def on_scroll(x: int, y: int, dx: int, dy: int) -> None:
                store.mouse("scroll")

            def on_move(x: int, y: int) -> None:
                nonlocal last_move
                now = time.monotonic()
                if now - last_move >= MOUSE_MOVE_MIN_INTERVAL:
                    last_move = now
                    store.mouse("move")

            # pynput's keyboard and mouse Listeners are unrelated classes that
            # both derive from threading.Thread, which is the common type that
            # actually carries start/stop/daemon.
            listeners: list[threading.Thread] = []
            if capture_keys:
                listeners.append(keyboard.Listener(on_press=on_press))
            listeners.append(
                mouse.Listener(on_click=on_click, on_scroll=on_scroll, on_move=on_move)
            )
            for listener in listeners:
                listener.daemon = True
                listener.start()

            try:
                last_window = object()  # sentinel: never equal to a real reading
                last_flush = time.monotonic()

                while True:
                    current = active_window(capture_title=capture_titles)
                    if (current.process, current.title) != last_window:
                        store.window(current.process, current.title)
                        last_window = (current.process, current.title)

                    now = time.monotonic()
                    if now - last_flush >= FLUSH_SECONDS:
                        store.check_clock()
                        store.flush()
                        last_flush = now
                        if callable(on_tick):
                            on_tick(store)

                    if seconds is not None and now - started >= seconds:
                        break
                    time.sleep(WINDOW_POLL_SECONDS)
            finally:
                for listener in listeners:
                    # stop() is on pynput's Listener, not on Thread itself.
                    # Guarded so a half-constructed listener can't mask the
                    # original exception on the way out.
                    stop = getattr(listener, "stop", None)
                    if callable(stop):
                        stop()

            store.flush()
            return store.counts()
    finally:
        lock.release()
