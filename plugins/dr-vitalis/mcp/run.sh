#!/bin/bash
# Wrapper that finds a Python 3.10+ interpreter with mcp+httpx installed
# and runs the MCP server.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="${SCRIPT_DIR}/server.py"

# 1. Prefer a dedicated venv at ~/.dr-vitalis/venv (cleanest, recommended setup)
VENV_PYTHON="${HOME}/.dr-vitalis/venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    if "$VENV_PYTHON" -c "import mcp, httpx" 2>/dev/null; then
        exec "$VENV_PYTHON" "$SERVER" "$@"
    fi
fi

# 2. Fall back to system Python interpreters in preference order
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
echo "[dr-vitalis] ERROR: Cannot find Python 3.10+ with 'mcp' and 'httpx' installed." >&2
echo "[dr-vitalis] Recommended fix (one-time setup):" >&2
echo "[dr-vitalis]   brew install python@3.12" >&2
echo "[dr-vitalis]   python3.12 -m venv ~/.dr-vitalis/venv" >&2
echo "[dr-vitalis]   ~/.dr-vitalis/venv/bin/pip install mcp httpx" >&2
echo "[dr-vitalis] Then restart Claude Code." >&2
exit 1
