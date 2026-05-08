---
description: Show or refresh your Health Jarvis council
argument-hint: [refresh | refresh-all | list]
---

The user invoked the `/council` command with arguments: **$ARGUMENTS**

Interpret the argument:

- **No arguments** or **list** → call `list_voices` and present a clean
  table: handle · display name · weight · post count · last refresh.
  Also include the dashboard path: `~/.health-jarvis/dashboard.html`.

- **refresh** → ask which voice (if not specified after "refresh"), then
  call `refresh_voice(handle, max_posts=200)`. Report the count of new
  passages added.

- **refresh-all** → call `refresh_all(max_posts=200)`. Warn the user this
  costs roughly `voices × max_posts × $0.005` against their X API balance
  before running. Then summarize the results: per-voice new passage counts.

- **add @handle [weight=N]** → call `add_voice(handle, weight)`. If they
  didn't specify a weight, default to 1.0. Then offer to refresh that voice.

- **anything else** → tell the user the supported subcommands.

Be terse. This is a status command, not a chat.
