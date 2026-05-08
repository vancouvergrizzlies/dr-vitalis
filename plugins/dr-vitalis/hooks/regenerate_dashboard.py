#!/usr/bin/env python3
"""
PostToolUse hook: regenerate the Dr. Vitalis dashboard whenever the council
state changes. The MCP server already regenerates on every mutating call, but
this hook is a belt-and-suspenders safety net so the dashboard stays fresh
even if the user pokes the database via another route.

Reads the same DB the MCP writes to. Best-effort only — never blocks Claude.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Reuse the MCP module's dashboard logic
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp"))

try:
    # The import auto-initializes the DB and is idempotent.
    from server import _regenerate_dashboard, DASHBOARD_PATH  # type: ignore
    _regenerate_dashboard()
    # Quiet success — hooks should not spam stdout
except Exception as e:
    print(f"[dr-vitalis hook] dashboard regen skipped: {e}", file=sys.stderr)

# Always exit 0 so the hook never blocks Claude
sys.exit(0)
