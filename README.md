# Dr. Vitalis

> Your private council, in one direct voice.

Dr. Vitalis is a personal health advisor for Claude Code. You curate a council of trusted X voices, and Dr. Vitalis silently ingests their thinking. When you ask a health question, you get one direct, actionable answer — synthesized invisibly from the council, not "expert X said Y." If you ever want to see the source tweets, type `/why`.

Built for [Bounty No. 02 — Build Your Own Jarvis](https://anewall.com).

## The wall this fixes

Plain Claude doesn't know who *you* trust. The carnivore / ancestral-health / anti-establishment voices that actually move the needle for some users live in a specific corner of X that Claude can't see. So every health conversation starts from scratch with generic establishment-medicine answers.

Dr. Vitalis closes that gap with three things:

- **Memory** — your conditions, meds, diet, prior attempts, persisted across sessions
- **Live data** — pulls posts from your council via the official X API and indexes them locally
- **Synthesis** — one unified answer from the council's collective ethos, no attribution, no hedging

## Install

```sh
/plugin marketplace add vancouvergrizzlies/dr-vitalis
/plugin install dr-vitalis@dr-vitalis-marketplace
```

A **108-passage seed corpus is bundled** so the moment you install, you can ask a health question and see the synthesis happen with no X token, no API spend, no setup. The seed pulls from:

- **BioavailableNd's Substack** (15 detailed articles on detox, mold, lymph, fertility) — weighted 2x
- **Abud Bakri MD's Substack** (9 articles on hormones, peptides, biohacking)
- **Paul Saladino's podcast** (10 most-recent episode descriptions)
- **Carnivore Aurelius blog** (74 long-form posts on diet, organ meats, seed oils)

Three voices ship empty in the seed (Sol Brah, Barbara O'Neill, Grimhood) because their content lives entirely on X (or YouTube, in O'Neill's case) — see *Optional: live X data* below to populate them.

## Required env vars

| Variable | Required | What |
| --- | --- | --- |
| `X_BEARER_TOKEN` | Required for live refresh; not needed to use the demo | Bearer token from your X dev app at [console.x.com](https://console.x.com). Pay-per-use pricing (~$0.005 per post read). |
| `COUNCIL_DB_PATH` | Optional | Override database location. Default: `~/.dr-vitalis/council.db` |
| `COUNCIL_DASHBOARD_PATH` | Optional | Override dashboard HTML output. Default: `~/.dr-vitalis/dashboard.html` |
| `COUNCIL_SEED_DB_PATH` | Optional | Path to bundled seed DB. Default: plugin's `data/seed.db` |

You can put these in your shell profile, or in a `.env` you source. The plugin's `.mcp.json` reads them from the environment that launches Claude.

## External dependencies

- **Python 3.9+** (for the MCP server)
- **`mcp` and `httpx` Python packages** — install once:
  ```sh
  pip3 install mcp httpx
  ```

That's it. SQLite is built into Python.

## What's in the box

**MCP server (`council`)** — Python, SQLite + FTS5, talks to X API v2

| Tool | Purpose |
|---|---|
| `add_voice`, `remove_voice`, `set_weight`, `list_voices` | Manage the council |
| `refresh_voice`, `refresh_all` | Incremental pulls (newest only) |
| `backfill_voice`, `backfill_all` | Deep history (up to 3,200 cap or full archive) |
| `estimate_voice_cost`, `estimate_council_cost` | Pre-spend cost estimation |
| `query_council`, `query_voice`, `list_recent` | Search the corpus |
| `save_passage` | Manual paste-in for content outside X |
| `last_sources` | Audit trail for `/why` |
| `set_profile`, `get_profile`, `delete_profile_key` | Persistent user health context |

**Skills**
- `health-context` — auto-loads your stored profile (conditions, meds, diet, goals) on every health conversation
- `consult-council` — triggers on health questions, queries the corpus, synthesizes one direct answer with no attribution

**Subagent**
- `research-symptom` — deeper investigations, returns a structured brief

**Hooks**
- `PostToolUse` on every council mutation → regenerates `dashboard.html`
- `SessionStart` → surfaces a one-line "Dr. Vitalis loaded" status with voice count and last refresh time

**Slash commands**
- `/council list | refresh @handle | refresh-all | add @handle weight=N`
- `/why` — show the source passages behind Dr. Vitalis's last answer
- `/dashboard` — open the dashboard HTML in your browser

## Cost expectations

Pay-per-use X API pricing (May 2026): **~$0.01 per post read** (X docs list $0.005 per "resource" but observed cost runs higher; budget conservatively at $0.01/read).

Two endpoints with different lookback:

- **Timeline endpoint** (`refresh_voice`, `backfill_voice mode=recent`) — capped by X at 3,200 most-recent tweets per user, regardless of what you pay
- **Full-archive search** (`backfill_voice mode=full`) — back to account creation in 2006, but costs the same per-tweet and may need entitlement on your X dev account

| Action | Reads | Cost |
| --- | --- | --- |
| **Use the bundled demo** | 0 | **$0** |
| Estimate cost for full council | 7 (1/voice) | ~$0.07 |
| Light refresh (7 voices × 200 posts) | 1,400 | ~$14 |
| Recent backfill (7 voices × 3,200 cap) | 22,400 | ~$224 |
| **True full archive** (highly variable) | varies, often 100k–400k | **$500–2,000+** |
| Ongoing refresh (200 new posts/voice/month) | 1,400/mo | ~$14/mo |
| Council queries | 0 | $0 (local DB) |

**Reality:** for the example council shipped in the seed, free long-form scraping (Substack RSS, podcast feeds, blog crawls) covers 4 of 7 voices richly, so most users only need to spend X credits on the 3 X-native voices. That's typically **$5–$15** for a meaningful corpus.

**Always run `estimate_council_cost` first before any backfill.** It costs ~4¢ and tells you exactly what each voice's full archive would cost based on their real lifetime tweet count, so you can decide which voices warrant the deep backfill.

The MCP uses `since_id` for incremental refreshes, so you only pay for new posts after the first backfill.

**Cost guardrails:** every backfill tool accepts a `confirm_cost_usd` parameter. If estimated cost exceeds it, the call refuses to run. Use this for hard caps on accidental spend (e.g. `backfill_all(mode='full', confirm_cost_usd=50)`).

## Privacy

Everything is local. The SQLite DB lives at `~/.dr-vitalis/council.db` and never leaves your machine. The dashboard is a static HTML file at `~/.dr-vitalis/dashboard.html`. The X API only sees your bearer token and the timeline requests it makes.

The bundled demo corpus contains a small set of public posts from a sample council, intended as a working demo. If you replace the corpus with your own council, the new content stays on your machine.

## Bounty submission note

**The wall I hit in plain Claude:** It forgets my health context — and more fundamentally, it has no idea who *I* trust. The carnivore / anti-seed-oil / ancestral-health voices I rely on aren't in any health database; they're in a specific corner of X that Claude can't see. So every health conversation started from scratch, with generic establishment-medicine answers I didn't want.

**What was missing:** memory (my profile), live data (their posts), and synthesis (one voice, not a survey).

This plugin closes all three.

## License

MIT — see `LICENSE`.

## Author

[@vancouvergrizzlies](https://github.com/vancouvergrizzlies)
