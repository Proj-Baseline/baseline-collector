"""Baseline collector CLI.

    python -m collector doctor                 # check the machine can capture
    python -m collector run                    # capture until Ctrl+C
    python -m collector run --seconds 60       # bounded run
    python -m collector run --no-keys          # mouse + windows only
    python -m collector status                 # what's in the database

Writes to ~/.baseline/events.db by default. Point engine at it with:

    python -m engine.export --db ~/.baseline/events.db --source real
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from collector import classify, window
from collector.config import DEFAULT_DB


def cmd_doctor(args: argparse.Namespace) -> int:
    """Verify capture works before asking anyone to trust a long run."""
    ok = True
    print(f"platform            {sys.platform}")
    print(f"python              {sys.version.split()[0]}")

    if classify.available():
        print("keyboard (pynput)   available")
    else:
        print("keyboard (pynput)   MISSING — pip install pynput")
        ok = False

    if window.available():
        current = window.active_window()
        print("window (win32)      available")
        print(f"  foreground now    {current.process or '(unknown)'}")
        # Title is deliberately not printed: doctor output tends to end up in
        # screenshots and bug reports, and the title is the most sensitive
        # field the collector touches.
        print(f"  title captured    {'yes' if current.title else 'no'}")
    else:
        print("window (win32)      UNAVAILABLE (not Windows?)")
        ok = False

    print(f"database            {args.db}")
    print(f"  exists            {'yes' if Path(args.db).exists() else 'no (will be created)'}")
    print()
    print("OK — ready to capture." if ok else "NOT READY — fix the above first.")
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    from collector.capture import run
    from collector.store import AlreadyRunning

    db = Path(args.db).expanduser()
    print(f"capturing to {db}")
    print(f"  keys    {'no (--no-keys)' if args.no_keys else 'yes, class only, never the character'}")
    print(f"  titles  {'no (--no-titles)' if args.no_titles else 'yes'}")
    print("  Ctrl+C to stop\n" if args.seconds is None else f"  stopping after {args.seconds}s\n")

    def tick(store: object) -> None:
        counts = store.counts()  # type: ignore[attr-defined]
        print(
            f"\r  keys {counts['keys']:>7}  mouse {counts['mouse']:>7}  "
            f"windows {counts['windows']:>5}",
            end="",
            flush=True,
        )

    try:
        counts = run(
            db,
            seconds=args.seconds,
            capture_titles=not args.no_titles,
            capture_keys=not args.no_keys,
            on_tick=tick,
        )
    except AlreadyRunning as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0

    print(f"\ndone. {counts}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    db = Path(args.db).expanduser()
    if not db.exists():
        print(f"{db} does not exist yet — run `python -m collector run` first.")
        return 1

    conn = sqlite3.connect(db)
    try:
        print(f"{db}  ({db.stat().st_size / 1024:,.0f} KB)\n")
        for table in ("keys", "mouse", "windows", "sessions"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<9} {n:>9,}")

        span = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM (SELECT ts FROM keys UNION ALL SELECT ts FROM mouse)"
        ).fetchone()
        if span and span[0]:
            lo = datetime.fromtimestamp(span[0])
            hi = datetime.fromtimestamp(span[1])
            days = len({
                datetime.fromtimestamp(r[0]).date()
                for r in conn.execute("SELECT ts FROM mouse UNION ALL SELECT ts FROM keys")
            })
            print(f"\n  span      {lo:%Y-%m-%d %H:%M} .. {hi:%Y-%m-%d %H:%M}")
            print(f"  days      {days}")
            # 14 days is the minimum before any drift comparison is meaningful
            # (AGENTS.md §4). Say so plainly rather than letting a thin
            # dataset look ready.
            if days < 14:
                print(f"  note      {14 - days} more day(s) before baselines mean anything")

        top = conn.execute(
            "SELECT process, COUNT(*) c FROM windows WHERE process IS NOT NULL "
            "GROUP BY process ORDER BY c DESC LIMIT 5"
        ).fetchall()
        if top:
            print("\n  most-switched-to apps")
            for process, count in top:
                print(f"    {process:<28} {count:>6,}")
    finally:
        conn.close()
    return 0


def main() -> int:
    # --db lives on a shared parent so it works in either position:
    # `-m collector --db X run` and `-m collector run --db X` both parse.
    # The second reads more naturally and is what anyone types first.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(DEFAULT_DB), help=f"default: {DEFAULT_DB}")

    parser = argparse.ArgumentParser(
        prog="collector", description=__doc__, parents=[common]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "doctor", help="check this machine can capture", parents=[common]
    ).set_defaults(func=cmd_doctor)

    run_p = sub.add_parser("run", help="capture events", parents=[common])
    run_p.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    run_p.add_argument("--no-titles", action="store_true", help="don't record window titles")
    run_p.add_argument(
        "--no-keys",
        action="store_true",
        help="mouse and windows only; records no keystrokes at all",
    )
    run_p.set_defaults(func=cmd_run)

    sub.add_parser(
        "status", help="summarise the database", parents=[common]
    ).set_defaults(func=cmd_status)

    args = parser.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
