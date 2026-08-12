# baseline-collector

Passive capture to a local SQLite database. This is the collector for
[Baseline](https://github.com/Vivaan-crypto/project-baseline), split out into
its own repository so it can be read on its own: it is AGPL and public because
it is the component users have to audit rather than trust.

Nothing here talks to a network. Capture is written to a file on your machine
and read by software that also runs on your machine.

## Read this first

`collector/classify.py` is the only code in the project that ever sees a
keystroke. It takes a key and returns one of six strings — `char`,
`correction`, `navigation`, `modifier`, `space`, `enter` — and the key itself
is never stored, logged, buffered, or passed on.

That guarantee is mechanised in `tests/test_classify.py`, which asserts over
the whole printable ASCII range that no character survives classification, and
that `'a'`, `'7'` and `'$'` are indistinguishable afterwards. If they weren't,
keystroke classes would leak the shape of a password. `tests/test_store.py`
enforces the same rule one layer down: there is nowhere in the database schema
for a character to be put.

## Install

```bash
pip install git+https://github.com/Proj-Baseline/baseline-collector
```

Or from a clone, if you want to read it first — which is the point of it being
public:

```bash
git clone https://github.com/Proj-Baseline/baseline-collector
cd baseline-collector
pip install -r requirements.txt   # just pynput
```

Either way `python -m collector` is the entry point. Installed, the console
script `baseline-collector` runs the same CLI.

## Quick start

```bash
python -m collector doctor
```

`doctor` checks that keyboard hooks and Win32 window queries work on this
machine and prints the current foreground app. It captures nothing.

Then capture:

```bash
python -m collector run
```

Writes to `~/.baseline/events.db` (outside any repo, deliberately — event data
is personal and must never be near a git working tree). Ctrl+C to stop.

```bash
python -m collector status   # what's captured so far
```

## Seeing your own numbers

The analysis engine and dashboard live in the Baseline app repo. Point them at
the database this writes:

```bash
python -m engine.export --db ~/.baseline/events.db --source real
```

`--source real` drops the "Simulated data" badge. Nothing else changes: the
engine reads the same three tables whether they were written by this collector
or by the synthetic generator, which is exactly why the analysis code needed no
modification to go from synthetic to real data.

Capture is deliberately separate from the dashboard, so starting a dev server
never starts recording your keystrokes as a side effect. Two terminals, not
one.

Give it a full day before the numbers mean much, and 14 days before any
baseline comparison does.

## Flags worth knowing

| Flag | Effect |
|---|---|
| `--no-keys` | Records no keystrokes at all. Mouse and window activity still drive presence detection, so Trace, Activity, Fragments, Bedrock and Core all still work — only the typing-rhythm signal is missing. Good for a first look. |
| `--no-titles` | Drops window titles at the source. Titles are the most sensitive thing captured (a browser title carries the page, an editor title the filename) and the engine does not currently use them. |
| `--seconds N` | Bounded run, for verification. |
| `--db PATH` | Capture elsewhere. |

## What gets written

Exactly the schema the engine reads:

```sql
keys    (ts REAL, class TEXT)      -- class only, never the character
mouse   (ts REAL, kind TEXT)       -- click / scroll / move
windows (ts REAL, process TEXT, title TEXT)
sessions(ts REAL, event TEXT)      -- start / stop / clock_jump
meta    (key TEXT, value TEXT)     -- schema_version, from day one
```

That schema is the only contract between this repository and the engine, and
it is now a contract across a repo boundary. Changing it here breaks reading
there, so treat it as versioned: `meta.schema_version` exists from day one for
exactly that reason.

Mouse *moves* are throttled to one per second (`collector/config.py`): they
fire hundreds of times a second and are only ever used as evidence a human is
present. Clicks and scrolls are never throttled — they are discrete
intentional acts whose timing carries information.

## Running it continuously

Task Scheduler, at logon:

```
Program:   pythonw.exe
Arguments: -m collector run
Start in:  C:\path\to\baseline-collector
```

`pythonw.exe` rather than `python.exe` so no console window appears. A PID
lock file prevents a scheduled instance and a manual one from both running —
duplicates would double every event, silently halving inter-key delays.

## Tests

```bash
pip install -e ".[test]"
python -m pytest tests -q
```

`test_classify.py` skips itself when `pynput` isn't installed, since there is
no key type to classify without it.

## Known limits

- **Windows only.** macOS is ~15 lines different (`NSWorkspace` via pyobjc)
  but blocked on notarization and the Input Monitoring permission flow.
- **Elevated apps are invisible.** A process running as admin refuses to be
  opened by a non-elevated collector, so its span records as active time with
  an unknown app rather than being attributed. That is the correct failure —
  the time is real even when the label isn't available.
- **Antivirus may flag the keyboard hook.** A global hook is the same
  mechanism a keylogger uses; the difference is what happens to the key, which
  is why `classify.py` is small enough to read in one sitting.

## A note on the comments

Source comments cite `AGENTS.md` sections and `engine/` modules. Both live in
the Baseline app repo, not this one — the citations are kept because they say
*why* a line is the way it is, and rewriting them would lose the reasoning
that makes this code auditable. Nothing here imports anything from that repo.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
