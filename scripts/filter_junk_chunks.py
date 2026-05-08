#!/usr/bin/env python3
"""
CONSERVATIVE junk-filter for council passages.

Drops only chunks that are *clearly* pure filler — sponsor reads, outros,
welcomes. Keeps anything with substantive content even if it has some filler.

When in doubt, KEEP. The synthesis layer can ignore filler at retrieval time;
we just want to drop chunks that are LITERALLY just promotional copy.
"""
from __future__ import annotations
import re, sqlite3
from pathlib import Path

DB = Path.home() / ".dr-vitalis" / "council.db"

# Strong junk markers — phrases that almost always indicate filler
STRONG_JUNK = [
    r"\bthis episode is (?:brought to you by|sponsored by|presented by)\b",
    r"\b(?:use code|promo code|discount code) [A-Za-z0-9]+ (?:for|to get|to receive)\b",
    r"\bgo to (?:my|our) website (?:and|for|to)\b",
    r"\bsign up (?:for|to) (?:my|our) (?:newsletter|substack|patreon)\b",
    r"\b(?:rate|review) (?:this|the) (?:podcast|show) on (?:apple|spotify)\b",
    r"\bhit the (?:bell|like) (?:button|icon)\b",
    r"\bsmash that (?:like|subscribe)\b",
    r"\bdon'?t forget to subscribe\b",
]
STRONG_RE = re.compile("|".join(STRONG_JUNK), re.IGNORECASE)

# Soft junk markers — common but only filler if accompanied
SOFT_JUNK = [
    r"\bwelcome (?:to (?:this|the|another) (?:week'?s )?)?(?:episode|podcast|show)\b",
    r"\bif you (?:enjoyed|liked) (?:this|the) (?:episode|video|podcast)\b",
    r"\bthanks for (?:tuning in|listening|watching|subscribing|joining)\b",
    r"\bfollow (?:me|us) on\b",
    r"\bcheck out the show notes\b",
    r"\blink in the (?:show notes|description|bio)\b",
    r"\bwithout further ado\b",
    r"\b(?:see|catch) you (?:next time|next week|in the next one)\b",
]
SOFT_RE = re.compile("|".join(SOFT_JUNK), re.IGNORECASE)

def looks_like_pure_filler(text: str) -> bool:
    """
    Returns True ONLY if the chunk is essentially nothing but filler.

    Decision tree:
      - Strong junk hit (sponsor / discount code) AND chunk is short (<800 chars body) → drop
      - 3+ soft junk hits AND short (<600 chars body) → drop
      - Otherwise → keep
    """
    body = text.split("\n\n", 1)[-1].strip()
    body_len = len(body)

    if body_len < 200:
        return True  # too short to be useful

    strong_hits = len(STRONG_RE.findall(body))
    soft_hits = len(SOFT_RE.findall(body))

    # Sponsor read on a short chunk
    if strong_hits >= 1 and body_len < 800:
        return True
    # Strong sponsor pile on
    if strong_hits >= 2:
        return True
    # Pure outro/intro (lots of soft markers, not enough body)
    if soft_hits >= 3 and body_len < 600:
        return True

    return False

def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, voice, source_url, text
        FROM passages
        WHERE kind = 'youtube_transcript'
    """).fetchall()
    print(f"Scanning {len(rows)} youtube_transcript chunks...")

    to_delete: list[int] = []
    samples: list[str] = []
    for r in rows:
        if looks_like_pure_filler(r["text"]):
            to_delete.append(r["id"])
            if len(samples) < 6:
                preview = r["text"][:200].replace("\n", " ")
                samples.append(f"  - {preview}")

    print(f"\nWill remove: {len(to_delete)} chunks ({100*len(to_delete)/max(1,len(rows)):.1f}%)")
    print(f"Will keep:   {len(rows) - len(to_delete)} chunks")
    if samples:
        print("\nSample removed (verify these are actually junk):")
        for s in samples:
            print(s)

    if to_delete:
        for i in range(0, len(to_delete), 500):
            batch = to_delete[i:i+500]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(f"DELETE FROM passages WHERE id IN ({placeholders})", batch)
        conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    sal = conn.execute("SELECT COUNT(*) FROM passages WHERE voice='paulsaladinomd'").fetchone()[0]
    print(f"\nCouncil total passages: {total}")
    print(f"Saladino passages: {sal}")
    conn.close()

if __name__ == "__main__":
    main()
