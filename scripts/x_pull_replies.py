#!/usr/bin/env python3
"""
Pull REPLIES from Grimhood + BioavailableNd. Replies often contain Q&A
where they answer specific health questions — high signal density per tweet.

Strategy:
1. Use search/all with `from:VOICE is:reply` filter (server-side)
2. Keep retrying through rate limits with patient backoff
3. INSERT OR IGNORE skips any duplicates
4. Hard cap at $13 (leaves ~$4 buffer in user's $17 remaining credit)
"""
from __future__ import annotations
import os, sqlite3, time, sys
from pathlib import Path
import httpx
from datetime import datetime, timezone

DB = Path.home() / ".dr-vitalis" / "council.db"
TOKEN = os.environ["X_BEARER_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

PRICE_PER_READ = 0.01
HARD_CAP_USD = 13.00

_total_reads = 0
def cost(): return _total_reads * PRICE_PER_READ
def can_spend(n): return cost() + n * PRICE_PER_READ <= HARD_CAP_USD

def parse_iso(s):
    if not s: return None
    try:
        return int(datetime.fromisoformat(s.replace("Z","+00:00")).replace(tzinfo=timezone.utc).timestamp())
    except: return None

def insert_tweets(voice: str, tweets: list, kind: str = "x_reply") -> int:
    if not tweets: return 0
    now = int(time.time())
    c = sqlite3.connect(DB)
    n = 0
    for t in tweets:
        tid = str(t.get("id"))
        text = t.get("text") or ""
        if not tid or len(text) < 50: continue
        url = f"https://x.com/{voice}/status/{tid}"
        posted = parse_iso(t.get("created_at"))
        sid = f"x-reply-{voice}-{tid}"
        try:
            cur = c.execute("""INSERT OR IGNORE INTO passages
                               (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (voice, sid, url, text, posted, now, kind))
            if cur.rowcount > 0: n += 1
        except sqlite3.Error: pass
    c.commit(); c.close()
    return n

def fetch_replies(voice_handle: str, max_results: int) -> list:
    """Pull replies via search/all with patient rate-limit handling."""
    global _total_reads
    out = []
    next_token = None
    pulled = 0
    query = f"from:{voice_handle} is:reply"
    consecutive_429s = 0

    with httpx.Client(timeout=60.0, headers=HEADERS) as cli:
        while pulled < max_results and consecutive_429s < 3:
            params = {
                "query": query,
                "max_results": min(100, max_results - pulled),
                "tweet.fields": "id,text,created_at,public_metrics",
            }
            if next_token: params["next_token"] = next_token
            if params["max_results"] < 10: break

            r = cli.get("https://api.x.com/2/tweets/search/all", params=params)

            if r.status_code == 429:
                consecutive_429s += 1
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 180:
                    print(f"    ⚠ rate limit reset in {wait}s (>3min); patient sleep")
                    if consecutive_429s >= 2: break
                print(f"    sleeping {wait}s for rate limit reset (attempt {consecutive_429s})")
                time.sleep(wait)
                continue
            consecutive_429s = 0

            if r.status_code == 403:
                print(f"    ! 403 entitlement issue"); break
            if r.status_code != 200:
                print(f"    ! status {r.status_code}: {r.text[:150]}"); break

            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            _total_reads += len(tweets)
            pulled += len(tweets)
            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets: break

            print(f"    ... {pulled} replies (cost: ${cost():.2f})")
            time.sleep(2)  # gentle pacing

    return out

def main():
    print(f"Pulling replies. Hard cap: ${HARD_CAP_USD}\n")

    # === GRIMHOOD replies ===
    print("=== @Grimhood replies ===")
    if can_spend(800):
        tweets = fetch_replies("Grimhood", 800)
        n = insert_tweets("Grimhood", tweets, kind="x_reply")
        print(f"  + {len(tweets)} fetched, {n} new inserted")
        print(f"  Cost so far: ${cost():.2f}")
    else:
        print("  ⚠ budget already exhausted")

    print("\n  Sleeping 60s before next voice...")
    time.sleep(60)

    # === BIOAVAILABLEND replies ===
    print("\n=== @BioavailableNd replies ===")
    if can_spend(500):
        tweets = fetch_replies("BioavailableNd", 500)
        n = insert_tweets("BioavailableNd", tweets, kind="x_reply")
        print(f"  + {len(tweets)} fetched, {n} new inserted")
    else:
        print("  ⚠ budget already exhausted")

    print(f"\n=== DONE ===")
    print(f"Reads: {_total_reads}")
    print(f"Cost:  ${cost():.2f}")
    print(f"Budget left in cap: ${HARD_CAP_USD - cost():.2f}")

    c = sqlite3.connect(DB)
    rows = c.execute("SELECT voice, COUNT(*) FROM passages GROUP BY voice ORDER BY COUNT(*) DESC").fetchall()
    total = c.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    print(f"\nCouncil total: {total}")
    for v, n in rows:
        print(f"  @{v:<22} {n:>5}")
    c.close()

if __name__ == "__main__":
    main()
