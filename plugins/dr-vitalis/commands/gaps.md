---
description: Surface topics where Dr. Vitalis's coverage is thin
---

The user invoked `/dr-vitalis:gaps` to see Dr. Vitalis's self-assessment of
his own knowledge gaps — which topics his answers will be weakest on, based
on the queries he's been asked and the spread of voices that responded.

1. Run the gaps analyzer using the same Python the MCP server uses:

   ```bash
   bash -c '
     SCRIPT="${CLAUDE_PLUGIN_ROOT}/mcp/analyze_gaps.py"
     # Prefer dedicated venv
     if [ -x "${HOME}/.dr-vitalis/venv/bin/python" ]; then
       "${HOME}/.dr-vitalis/venv/bin/python" "$SCRIPT"
     else
       # Fall back to system python3.10+
       for py in python3.13 python3.12 python3.11 python3.10 python3; do
         if command -v "$py" >/dev/null && "$py" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>/dev/null; then
           "$py" "$SCRIPT"; exit
         fi
       done
       echo "[gaps] No suitable Python found. Set up the venv per the README." >&2
       exit 1
     fi
   '
   ```

2. The script emits markdown. Pass it through to the user verbatim — don't
   editorialize, don't re-summarize. The report IS the answer.

3. If the report shows "tracking mode" (fewer than 20 queries logged so far),
   tell the user: _"Dr. Vitalis needs at least 20 questions before he can spot
   patterns of weakness. Keep asking him health questions and come back."_

This is Dr. Vitalis being honest about what he doesn't know yet — show that
self-awareness, don't paper over it.
