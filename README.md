# Dr. Vitalis

> Your private health council, in one direct voice.

A personal health advisor for Claude Code. Bring a symptom or question — get one direct, actionable answer, drawn from a curated knowledge base of trusted health perspectives.

## Who is Dr. Vitalis?

Dr. Vitalis is an AI health advisor steeped in the long-form work of leading practitioners across ancestral health, functional medicine, longevity research, and metabolic biology — distilled from thousands of hours of clinical podcast transcripts, hundreds of long-form articles, and decades of practitioner thinking, all unified into one direct voice.

Where a typical naturopath knows one framework deeply, Dr. Vitalis synthesizes across many — ancestral and animal-based nutrition, mineral and supplement protocols, mold and detoxification science, hormonal optimization, sleep and circadian biology, lab interpretation (clinical and functional ranges), and the bioenergetic / longevity literature.

**Why he changes how you think about getting health advice:**

- **Available 24/7.** No waiting weeks for an appointment.
- **Remembers you.** Conditions, meds, diet, prior attempts persist across every conversation.
- **Direct.** No defensive "consult your doctor" hedges on routine questions. Clinical-grade triage when something's actually emergent — chest pain, severe bleeding, suicidal ideation, anaphylaxis. Otherwise, real opinions.
- **Cross-school synthesis.** Pulls the best from carnivore, ancestral, bioenergetics, functional medicine, longevity — not chained to one ideology.
- **Specific protocols, not generalities.** "Take 400mg magnesium glycinate 30 min before bed for 14 days" beats "magnesium might help."
- **Personalized.** Knows your baseline, your medications, what you've already tried — so he doesn't waste your time re-suggesting things.
- **Auditable.** `/why` after any answer shows the source material behind it.

He's the second opinion you can't get from one person — because no one person has internalized the full breadth of modern integrative health thinking. Dr. Vitalis has.

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
