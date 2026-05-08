#!/usr/bin/env python3
"""
SessionStart hook: surface a one-line status banner for Health Jarvis when a
new session begins. Tells the user how many voices are loaded, when they last
refreshed, and where the dashboard lives. Output goes to additionalContext so
Claude sees it (and the user sees it via Claude's response, not as raw stdout).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(os.environ.get(
    "COUNCIL_DB_PATH",
    str(Path.home() / ".health-jarvis" / "council.db"),
))
DASHBOARD_PATH = Path(os.environ.get(
    "COUNCIL_DASHBOARD_PATH",
    str(Path.home() / ".health-jarvis" / "dashboard.html"),
))


def _format_age(ts: int | None) -> str:
    if not ts:
        return "never"
    age = int(time.time()) - int(ts)
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    return f"{age // 86400}d ago"


def main() -> None:
    if not DB_PATH.exists():
        # First run — gentle onboarding nudge
        msg = (
            "Health Jarvis is installed but no council is loaded yet. "
            "Set X_BEARER_TOKEN in your environment, then ask Jarvis to add "
            "your trusted voices (e.g. 'add @paulsaladinomd to my council') "
            "and refresh."
        )
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        voices = conn.execute(
            "SELECT COUNT(*) AS n, MAX(refreshed_at) AS last FROM voices"
        ).fetchone()
        passages = conn.execute("SELECT COUNT(*) AS n FROM passages").fetchone()
        conn.close()
    except Exception as e:
        print(f"[health-jarvis] welcome hook: {e}", file=sys.stderr)
        sys.exit(0)

    n_voices = voices["n"] or 0
    last = voices["last"]
    n_passages = passages["n"] or 0

    if n_voices == 0:
        msg = (
            "Health Jarvis is installed. Council is empty — ask Jarvis to add "
            "your trusted voices (e.g. 'add @paulsaladinomd, weight 2x'), then "
            "say 'refresh the council' to pull recent posts. "
            f"Dashboard: file://{DASHBOARD_PATH}"
        )
    else:
        msg = (
            f"Health Jarvis loaded · {n_voices} voices · {n_passages} passages · "
            f"last refresh {_format_age(last)} · dashboard: file://{DASHBOARD_PATH}"
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[health-jarvis] welcome hook failed: {e}", file=sys.stderr)
    sys.exit(0)
