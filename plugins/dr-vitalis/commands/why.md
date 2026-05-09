---
description: Show the source passages that powered Dr. Vitalis's last health answer
---

The user is asking to see the audit trail behind Dr. Vitalis's most recent
health synthesis. This is the explicit attribution escape hatch.

1. Call `last_sources(limit=8)` from the council MCP.
2. If `ok` is false (no queries yet), tell the user: "Dr. Vitalis hasn't been
   asked anything yet — ask me a health question first and `/dr-vitalis:why`
   will show you the sources."
3. Otherwise, present each source passage as:
   ```
   @{handle} · {posted_at}
   {text}
   {url}
   ```
   …with a one-line header showing the original query.

Don't editorialize, don't re-synthesize, don't apologize. The user explicitly
asked to see sources — show them.
