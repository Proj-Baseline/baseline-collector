"""Store behaviour, and the shape of what it writes.

The schema asserted here is the contract with the analysis engine, which
lives in the Baseline app repo and is not importable from this one. That
repo holds the other half — a test that reads a capture written by this
Store through the engine's own reader. Changing SCHEMA breaks that half
silently, so treat the table list below as versioned, not incidental.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from collector.store import AlreadyRunning, PidLock, Store


def test_writes_the_documented_schema(tmp_path):
    """keys/mouse/windows/sessions/meta, with the columns the engine reads.
    If this drifts, real captures stop being readable downstream."""
    db = tmp_path / "e.db"
    with Store(db) as store:
        store.key("char")
        store.mouse("click")
        store.window("Code.exe", "main.py")
        store.flush()

    conn = sqlite3.connect(db)
    try:
        columns = {
            table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for table in ("keys", "mouse", "windows", "sessions", "meta")
        }
        assert columns == {
            "keys": ["ts", "class"],
            "mouse": ["ts", "kind"],
            "windows": ["ts", "process", "title"],
            "sessions": ["ts", "event"],
            "meta": ["key", "value"],
        }
        assert conn.execute("SELECT class FROM keys").fetchall() == [("char",)]
        assert conn.execute("SELECT kind FROM mouse").fetchall() == [("click",)]
        assert conn.execute("SELECT process, title FROM windows").fetchall() == [
            ("Code.exe", "main.py")
        ]
    finally:
        conn.close()


def test_no_character_column_exists_anywhere(tmp_path):
    """Hard rule 2, enforced at the storage layer rather than only at the
    classifier: there must be nowhere in the database for a key to be put."""
    db = tmp_path / "e.db"
    with Store(db) as store:
        store.key("char")
        store.flush()

    conn = sqlite3.connect(db)
    try:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            names = [row[1].lower() for row in conn.execute(f"PRAGMA table_info({table})")]
            assert not any(
                name in ("char", "character", "key_char", "keycode", "vk", "text")
                for name in names
            ), f"{table} has a column that could hold typed content: {names}"
    finally:
        conn.close()


def test_schema_version_recorded_from_day_one(tmp_path):
    db = tmp_path / "e.db"
    with Store(db):
        pass
    conn = sqlite3.connect(db)
    value = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    conn.close()
    assert value is not None


def test_session_start_and_stop_are_recorded(tmp_path):
    db = tmp_path / "e.db"
    with Store(db):
        pass
    conn = sqlite3.connect(db)
    events = [r[0] for r in conn.execute("SELECT event FROM sessions ORDER BY ts")]
    conn.close()
    assert events[0] == "start"
    assert events[-1] == "stop"


def test_flush_is_idempotent_when_empty(tmp_path):
    db = tmp_path / "e.db"
    with Store(db) as store:
        store.flush()
        assert store.flush() == 0


def test_buffered_events_survive_until_flush(tmp_path):
    db = tmp_path / "e.db"
    with Store(db) as store:
        store.flush()  # clear the session-start row
        for _ in range(5):
            store.key("char")
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0] == 0
        conn.close()
        assert store.flush() == 5


def test_pid_lock_blocks_a_second_collector(tmp_path):
    """Duplicate collectors double every event — a known trap."""
    path = tmp_path / "x.pid"
    first = PidLock(path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning):
            PidLock(path).acquire()
    finally:
        first.release()


def test_pid_lock_reclaims_a_stale_lock(tmp_path):
    """A killed collector must not lock the user out forever."""
    path = tmp_path / "x.pid"
    # A PID that cannot be running: max_pid+1 on any sane system.
    path.write_text("999999999")
    lock = PidLock(path)
    lock.acquire()  # must not raise
    assert int(path.read_text()) == os.getpid()
    lock.release()


def test_pid_lock_reclaims_a_corrupt_lock(tmp_path):
    path = tmp_path / "x.pid"
    path.write_text("not-a-pid")
    lock = PidLock(path)
    lock.acquire()
    lock.release()


def test_lock_released_on_exit(tmp_path):
    path = tmp_path / "x.pid"
    lock = PidLock(path)
    lock.acquire()
    lock.release()
    assert not path.exists()
