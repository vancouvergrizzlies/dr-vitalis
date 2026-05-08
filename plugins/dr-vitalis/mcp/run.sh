#!/bin/bash
# Wrapper that finds a Python 3.10+ interpreter and runs the MCP server.
# The mcp package requires 3.10+; system Python on macOS is often 3.9.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="${SCRIPT_DIR}/server.py"

# Try Python interpreters in preference order
for py in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
        # Check version >= 3.10
        if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            # Verify mcp + httpx are importable
            if "$py" -c "import mcp, httpx" 2>/dev/null; then
                exec "$py" "$SERVER" "$@"
            fi
        fi
    fi
done

# If we get here, no suitable Python found
echo "[dr-vitalis] ERROR: No Python 3.10+ with 'mcp' and 'httpx' installed found." >&2
echo "[dr-vitalis] Fix:" >&2
echo "[dr-vitalis]   1. Install Python 3.12+ (e.g. 'brew install python@3.12')" >&2
echo "[dr-vitalis]   2. Install deps: 'python3.12 -m pip install --user mcp httpx'" >&2
echo "[dr-vitalis]   3. Restart Claude Code" >&2
exit 1
