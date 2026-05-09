#!/usr/bin/env python3
"""
SessionStart hook: surface a one-line status banner for Dr. Vitalis when a
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
    str(Path.home() / ".dr-vitalis" / "council.db"),
))
DASHBOARD_PATH = Path(os.environ.get(
    "COUNCIL_DASHBOARD_PATH",
    str(Path.home() / ".dr-vitalis" / "dashboard.html"),
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
            "Dr. Vitalis is installed but his knowledge base hasn't loaded yet. "
            "If you installed via the marketplace, the bundled corpus should appear "
            "automatically on next session. If it doesn't, the seed file is at "
            "${CLAUDE_PLUGIN_ROOT}/data/seed.db — copy it to ~/.dr-vitalis/council.db."
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
        print(f"[dr-vitalis] welcome hook: {e}", file=sys.stderr)
        sys.exit(0)

    n_voices = voices["n"] or 0
    last = voices["last"]
    n_passages = passages["n"] or 0

    if n_voices == 0:
        msg = (
            "Dr. Vitalis is installed. The bundled corpus appears empty — try "
            "restarting Claude Code, or check that ~/.dr-vitalis/council.db exists. "
            f"Dashboard: file://{DASHBOARD_PATH}"
        )
    else:
        msg = (
            f"Dr. Vitalis loaded · {n_voices} voices · {n_passages} passages · "
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
        print(f"[dr-vitalis] welcome hook failed: {e}", file=sys.stderr)
    sys.exit(0)
