"""Baseline collector — passive capture to local SQLite.

AGPL, public, and deliberately small: this is the component users have to
audit rather than trust (AGENTS.md hard rule 7). Start with classify.py,
which is the only code that ever sees a keystroke.

Writes the same three tables engine/db.py reads, which is why the same
analysis runs unchanged over real and synthetic data.
"""
