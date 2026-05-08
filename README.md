# Dr. Vitalis

> Your private health council, in one direct voice.

A personal health advisor for Claude Code. Bring a symptom or question — get one direct, actionable answer, drawn from a curated knowledge base of trusted health perspectives.

## Install

```sh
/plugin marketplace add vancouvergrizzlies/dr-vitalis
/plugin install dr-vitalis@dr-vitalis-marketplace
```

A working knowledge base ships bundled with the plugin, so you can ask questions immediately — no API keys or setup required for read-only use.

## Requirements

- **Python 3.9+** (for the MCP server)
- One-time install of two Python packages:
  ```sh
  pip3 install mcp httpx
  ```

That's it. SQLite is built into Python.

## Optional: live data refresh

To keep the knowledge base fresh with content from public sources, set:

```sh
export X_BEARER_TOKEN="your-token-here"
```

Get a token at [console.x.com](https://console.x.com). Without it, the plugin still works fully against the bundled corpus — refresh is optional.

## What you get

- **Persistent memory** — Dr. Vitalis remembers your conditions, medications, diet, goals across sessions
- **Direct answers** — no "consult your doctor" hedging on routine questions; clinical-grade triage when actually warranted
- **Local-first** — all data stays on your machine in `~/.dr-vitalis/`
- **Dashboard** — auto-updated HTML view of your knowledge base at `~/.dr-vitalis/dashboard.html`
- **Audit trail** — `/why` after any answer shows the source material

## Slash commands

| Command | Purpose |
|---|---|
| `/dashboard` | Open the local dashboard in your browser |
| `/why` | Show source passages for the most recent answer |
| `/council` | Manage your knowledge base |

## Privacy

Everything runs locally. The knowledge base lives at `~/.dr-vitalis/council.db` on your machine and never leaves it. The dashboard is a static HTML file. No telemetry. No external services unless you explicitly configure live refresh.

## License

MIT — see [`LICENSE`](LICENSE).

## Author

[@vancouvergrizzlies](https://github.com/vancouvergrizzlies)
