---
description: Show the voices Dr. Vitalis is drawing from
---

The user invoked `/dr-vitalis:council` to see the lineup of voices powering
Dr. Vitalis.

1. Call `list_voices` from the council MCP.
2. Present a clean table sorted by passage count (descending):

   | Voice | Display name | Weight | Passages |
   |---|---|---|---|

3. End with the dashboard path: `file://${HOME}/.dr-vitalis/dashboard.html`
4. End with a one-line note: _"Run `/dr-vitalis:gaps` to see which topics
   Dr. Vitalis's coverage is thin on."_

Be terse. This is a status command, not a chat. Don't editorialize the lineup.
