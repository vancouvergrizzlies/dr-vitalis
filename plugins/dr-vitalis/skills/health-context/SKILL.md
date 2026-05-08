---
name: health-context
description: Loads the user's persistent health profile (conditions, meds, allergies, goals, things they've tried) at the start of any health-related conversation so Dr. Vitalis can personalize advice. Use whenever the user discusses symptoms, supplements, diet, sleep, training, labs, or any other health topic.
---

# Health context

Before responding to anything health-related, call the `get_profile` tool from the
`council` MCP server to load the user's stored health context.

The profile is stored as key/value pairs the user has set over time. Treat it as
authoritative: if their profile says they have hypothyroidism or are pregnant or
already tried magnesium glycinate, factor that in instead of suggesting generic
first-line advice.

If the profile is empty (no rows), proceed without it but keep in mind:

- This is the user's first health conversation with Dr. Vitalis
- After answering, you may *briefly* offer to remember 1–2 specifics they
  mentioned (e.g. "Want me to remember you take 5000 IU vitamin D so I don't
  re-suggest it?") — using `set_profile`
- Don't push for context they didn't volunteer

When the user volunteers durable health information mid-conversation
(e.g. "I'm on Wellbutrin", "I had my appendix out", "I've been carnivore for 6
months"), call `set_profile` with a short, descriptive key — e.g.:

- `set_profile("medications", "Wellbutrin 150mg XL daily")`
- `set_profile("diet", "carnivore since Nov 2025")`
- `set_profile("conditions", "...")`
- `set_profile("goals", "lose 15lb, fix sleep")`
- `set_profile("tried_failed", "magnesium glycinate 400mg — no effect on sleep")`

Use one key per category. Updating an existing key replaces the value, so
include the full updated context, not just the new fact.

**Do not narrate the loading.** Don't say "Let me check your profile" or
"According to your profile…". Just use the information silently.
