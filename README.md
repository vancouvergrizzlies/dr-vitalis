# Dr. Vitalis

> Your private health advisor, in one direct voice.

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
- **Self-aware.** `/dr-vitalis:gaps` shows you which topics Dr. Vitalis is thin on, so you know where his answers will be weakest.
- **Auditable.** `/dr-vitalis:why` after any answer shows the source material behind it.

He's the second opinion you can't get from one person — because no one person has internalized the full breadth of modern integrative health thinking. Dr. Vitalis has.

## Install

```sh
/plugin marketplace add vancouvergrizzlies/dr-vitalis
/plugin install dr-vitalis@dr-vitalis-marketplace
```

The bundled knowledge base ships with the plugin and is fixed — you ask questions, Dr. Vitalis answers from what he knows. No API keys, no configuration, no editing required.

## Requirements

- **Python 3.10+** (for the MCP server)
- The plugin's wrapper script (`mcp/run.sh`) auto-detects:
  1. A dedicated venv at `~/.dr-vitalis/venv` (recommended), OR
  2. Any system Python 3.10+ that has `mcp` and `httpx` installed.

If neither is present, the wrapper prints a one-line setup command and exits cleanly. The recommended one-time setup:

```sh
brew install python@3.12
python3.12 -m venv ~/.dr-vitalis/venv
~/.dr-vitalis/venv/bin/pip install mcp httpx
```

That's it. SQLite is built into Python.

## What you get

- **Direct answers** — no "consult your doctor" hedging on routine questions; clinical-grade triage when actually warranted
- **Persistent memory** — Dr. Vitalis remembers your conditions, medications, diet, and goals across sessions
- **Local-first** — everything runs on your machine in `~/.dr-vitalis/`. Nothing leaves.
- **Dashboard** — auto-updated HTML view at `~/.dr-vitalis/dashboard.html`, including a Knowledge Gaps panel that surfaces what Dr. Vitalis is thin on
- **Audit trail** — `/dr-vitalis:why` after any answer shows the source passages behind it

## Slash commands

| Command | Purpose |
|---|---|
| `/dr-vitalis:dashboard` | Open the local dashboard in your browser |
| `/dr-vitalis:why` | Show source passages for the most recent answer |
| `/dr-vitalis:gaps` | Surface topics where Dr. Vitalis's coverage is thin |

## Privacy

Everything runs locally. Your data lives at `~/.dr-vitalis/council.db` on your machine and never leaves it. The dashboard is a static HTML file. No telemetry. No external services.

## License

MIT — see [`LICENSE`](LICENSE).

## Author

[@vancouvergrizzlies](https://github.com/vancouvergrizzlies)
