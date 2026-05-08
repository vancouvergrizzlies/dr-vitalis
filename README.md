# Health Jarvis

> Personal health advisor that synthesizes actionable advice from your private council of trusted voices on X. Speaks as itself — no "expert X said Y," just direct guidance.

Built for [Bounty No. 02 — Build Your Own Jarvis](https://anewall.com).

## What it does

You curate a council of health voices on X you trust. Health Jarvis pulls their
recent posts via the official X API, indexes them locally with full-text search
and weighting, and when you ask a health question, synthesizes one direct,
actionable recommendation drawing on their thinking — without naming any of
them. If you ever want to see the source tweets behind an answer, you type
`/why`.

The wall in plain Claude that this fixes:

> Plain Claude doesn't know who YOU trust, can't see new posts from these
> specific people, forgets your health context every chat, and gives you
> wishy-washy "consult a doctor" answers instead of opinions. This plugin
> fixes all four.

## Install

```sh
/plugin marketplace add vancouvergrizzlies/health-jarvis
/plugin install health-jarvis@health-jarvis-marketplace
```

Then set up your X API access (see *Required env vars* below) and start adding
voices.

## Required env vars

| Variable | Required | What |
| --- | --- | --- |
| `X_BEARER_TOKEN` | **Yes** for `refresh_voice` / `refresh_all` | Bearer token from your X dev app at [console.x.com](https://console.x.com). Pay-per-use pricing (~$0.005 per post read). |
| `COUNCIL_DB_PATH` | Optional | Override database location. Default: `~/.health-jarvis/council.db` |
| `COUNCIL_DASHBOARD_PATH` | Optional | Override dashboard HTML output. Default: `~/.health-jarvis/dashboard.html` |

You can put these in your shell profile, or in a `.env` you source. The
plugin's `.mcp.json` reads them from the environment that launches Claude.

## External dependencies

- **Python 3.9+** (for the MCP server)
- **`mcp` and `httpx` Python packages** — install with:
  ```sh
  pip install -r ~/.claude/plugins/marketplaces/*/plugins/health-jarvis/mcp/requirements.txt
  ```
  …or run the one-liner the plugin offers on first use.

That's it. SQLite is built into Python.

## What's in the box

- **MCP server (`council`)** — Python, SQLite + FTS5, talks to X API v2
  - Tools: `add_voice`, `remove_voice`, `set_weight`, `list_voices`,
    `refresh_voice`, `refresh_all`, `query_council`, `query_voice`,
    `list_recent`, `save_passage`, `last_sources`,
    `set_profile`, `get_profile`, `delete_profile_key`
- **Skills**
  - `health-context` — auto-loads your stored profile (conditions, meds,
    diet, goals) on every health conversation
  - `consult-council` — triggers on health questions, queries the corpus,
    synthesizes one direct answer with no attribution
- **Subagent**
  - `research-symptom` — deeper investigations, returns a structured brief
- **Hooks**
  - `PostToolUse` on every council mutation → regenerates `dashboard.html`
  - `SessionStart` → surfaces a one-line "Jarvis loaded" status with voice
    count and last refresh time
- **Slash commands**
  - `/council list | refresh @handle | refresh-all | add @handle weight=N`
  - `/why` — show the source passages behind Jarvis's last answer
  - `/dashboard` — open the dashboard HTML in your browser

## Cost expectations

Pay-per-use X API pricing (May 2026): **$0.005 per post read**.

There are two endpoints with different lookback:

- **Timeline endpoint** (`refresh_voice`, `backfill_voice mode=recent`) —
  capped by X at 3,200 most-recent tweets per user, regardless of what you pay
- **Full-archive search** (`backfill_voice mode=full`) — back to account
  creation in 2006, but costs the same per-tweet and may need entitlement on
  your X dev account

| Action | Reads | Cost |
| --- | --- | --- |
| Estimate cost for full council | 8 (1/voice) | **~$0.04** |
| Light refresh (8 voices × 200 posts) | 1,600 | ~$8 |
| Recent backfill (8 voices × 3,200 cap) | 25,600 | ~$128 |
| **True full archive** (highly variable) | varies, often 100k–400k | **$500–2,000+** |
| Ongoing refresh (200 new posts/voice/month) | 1,600/mo | ~$8/mo |
| Council queries | 0 | $0 (local DB) |

**Always run `estimate_council_cost` first before any backfill.** It costs ~4¢
and tells you exactly what each voice's full archive would cost based on their
real lifetime tweet count, so you can decide which voices warrant the deep
backfill and which just get the 3,200-tweet cap.

The MCP uses `since_id` for incremental refreshes, so you only pay for new
posts after the first backfill.

**Cost guardrails:** every backfill tool accepts a `confirm_cost_usd` parameter.
If estimated cost exceeds it, the call refuses to run. Use this to put a hard
cap on accidental spend (e.g. `backfill_all(mode='full', confirm_cost_usd=50)`).

## Privacy

Everything is local. The SQLite DB lives at `~/.health-jarvis/council.db` and
never leaves your machine. The dashboard is a static HTML file at
`~/.health-jarvis/dashboard.html`. The X API only sees your bearer token and
the timeline requests it makes.

## Bounty submission note

**The wall I hit in plain Claude:** It forgets my health context — and more
fundamentally, it has no idea who *I* trust. The carnivore / anti-seed-oil /
ancestral-health voices I rely on aren't in any health database; they're in a
specific corner of X that Claude can't see. So every health conversation
started from scratch, with generic establishment-medicine answers I didn't
want.

**What was missing:** memory (my profile), live data (their posts), and
synthesis (one voice, not a survey).

This plugin closes all three.

## License

MIT — see `LICENSE`.

## Author

[@vancouvergrizzlies](https://github.com/vancouvergrizzlies)
