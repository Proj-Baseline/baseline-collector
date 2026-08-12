"""Batched SQLite writer, PID lock, and clock-jump detection.

Writes exactly the schema engine/db.py reads. That shared schema is the only
contract between capture and analysis — mock/mockgen.py writes it too, which
is why the same engine code runs unchanged over real and synthetic data.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from types import TracebackType

from collector.config import CLOCK_JUMP_TOLERANCE, SCHEMA_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS keys    (ts REAL NOT NULL, class TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mouse   (ts REAL NOT NULL, kind  TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS windows (ts REAL NOT NULL, process TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS sessions(ts REAL NOT NULL, event TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta    (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_keys_ts    ON keys(ts);
CREATE INDEX IF NOT EXISTS idx_mouse_ts   ON mouse(ts);
CREATE INDEX IF NOT EXISTS idx_windows_ts ON windows(ts);
"""


class AlreadyRunning(RuntimeError):
    pass


class PidLock:
    """One collector per database. Task Scheduler plus a manual run means
    every event lands twice, which silently doubles keystroke counts and
    halves inter-key delays — AGENTS.md §5 names this as a known trap.

    A stale lock (previous process killed without cleanup) is detected by
    probing the recorded PID rather than by age, so a long-running collector
    is never mistaken for a dead one.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def _pid_alive(self, pid: int) -> bool:
        if pid == os.getpid():
            return True
        try:
            # Signal 0 performs error checking without sending a signal.
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Exists but owned by another user — still alive.
            return True
        except OSError:
            return False
        return True

    def acquire(self) -> None:
        if self.path.exists():
            try:
                existing = int(self.path.read_text().strip())
            except (ValueError, OSError):
                existing = None
            if existing is not None and self._pid_alive(existing):
                raise AlreadyRunning(
                    f"another collector is running (pid {existing}). "
                    f"Stop it first, or delete {self.path} if you are sure it is dead."
                )
            self.path.unlink(missing_ok=True)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()))
        self._held = True

    def release(self) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False


class Store:
    """Buffers events in memory and flushes them on a timer.

    Thread-safe by design: pynput delivers keyboard and mouse events on their
    own listener threads while the window poller runs on a third, so every
    buffer append crosses a thread boundary.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._keys: list[tuple[float, str]] = []
        self._mouse: list[tuple[float, str]] = []
        self._windows: list[tuple[float, str | None, str | None]] = []
        self._sessions: list[tuple[float, str]] = []
        self._conn: sqlite3.Connection | None = None

        # Paired clocks. time.time() is what gets stored (features need real
        # calendar time), but it can jump backwards on NTP correction; the
        # monotonic clock cannot, so disagreement between the two deltas is
        # how a jump is detected.
        self._last_wall = time.time()
        self._last_mono = time.monotonic()
        self.clock_jumps = 0

    def __enter__(self) -> "Store":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # WAL: the dashboard's export can read while capture is still writing.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()
        self.session("start")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.session("stop")
        self.flush()
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def check_clock(self) -> None:
        """Called from the flush loop. Records a jump rather than trying to
        repair timestamps — engine/ discards absurd intervals on read, and
        rewriting history here would be worse than annotating it."""
        wall, mono = time.time(), time.monotonic()
        drift = abs((wall - self._last_wall) - (mono - self._last_mono))
        if drift > CLOCK_JUMP_TOLERANCE:
            self.clock_jumps += 1
            self.session(f"clock_jump:{drift:+.1f}s")
        self._last_wall, self._last_mono = wall, mono

    def key(self, key_class: str) -> None:
        with self._lock:
            self._keys.append((time.time(), key_class))

    def mouse(self, kind: str) -> None:
        with self._lock:
            self._mouse.append((time.time(), kind))

    def window(self, process: str | None, title: str | None) -> None:
        with self._lock:
            self._windows.append((time.time(), process, title))

    def session(self, event: str) -> None:
        with self._lock:
            self._sessions.append((time.time(), event))

    def flush(self) -> int:
        """Write buffered events. Returns the number of rows written."""
        if self._conn is None:
            return 0
        with self._lock:
            keys, self._keys = self._keys, []
            mouse, self._mouse = self._mouse, []
            windows, self._windows = self._windows, []
            sessions, self._sessions = self._sessions, []

        total = len(keys) + len(mouse) + len(windows) + len(sessions)
        if total == 0:
            return 0
        try:
            self._conn.executemany("INSERT INTO keys VALUES (?,?)", keys)
            self._conn.executemany("INSERT INTO mouse VALUES (?,?)", mouse)
            self._conn.executemany("INSERT INTO windows VALUES (?,?,?)", windows)
            self._conn.executemany("INSERT INTO sessions VALUES (?,?)", sessions)
            self._conn.commit()
        except sqlite3.Error:
            # Put them back and try again next tick rather than losing the
            # window. A disk-full or locked-db blip should cost latency, not
            # a hole in the day's data.
            with self._lock:
                self._keys = keys + self._keys
                self._mouse = mouse + self._mouse
                self._windows = windows + self._windows
                self._sessions = sessions + self._sessions
            raise
        return total

    def counts(self) -> dict[str, int]:
        if self._conn is None:
            return {}
        return {
            table: self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("keys", "mouse", "windows", "sessions")
        }
