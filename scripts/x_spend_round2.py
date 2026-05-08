#!/usr/bin/env python3
"""
Round 2 X spend: pull OLDER content for Grimhood + BioavailableNd.

Strategy:
1. Get oldest tweet ID we already have for each voice
2. Use until_id to paginate backwards in time
3. Plus retry the rate-limited topic searches across full archive

INSERT OR IGNORE means duplicates are silently skipped — we never pay twice
for the same tweet.

Hard cap: $18 (you have $20 left in X credits, leave $2 buffer).
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
HARD_CAP_USD = 18.00

_total_reads = 0
def cost(): return _total_reads * PRICE_PER_READ
def check_budget(action: str, expected: int) -> bool:
    proj = cost() + expected * PRICE_PER_READ
    if proj > HARD_CAP_USD:
        print(f"  ⚠ would exceed cap (${proj:.2f}); skipping: {action}")
        return False
    return True

def parse_iso(s):
    if not s: return None
    try:
        return int(datetime.fromisoformat(s.replace("Z","+00:00")).replace(tzinfo=timezone.utc).timestamp())
    except: return None

def insert_tweets(voice: str, tweets: list) -> int:
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
        sid = f"x-{voice}-{tid}"
        try:
            cur = c.execute("""INSERT OR IGNORE INTO passages
                               (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                               VALUES (?, ?, ?, ?, ?, ?, 'x_post')""",
                            (voice, sid, url, text, posted, now))
            if cur.rowcount > 0: n += 1
        except sqlite3.Error: pass
    c.commit(); c.close()
    return n

def get_oldest_tweet_id(voice: str) -> str | None:
    """Return the oldest source_id (X tweet id) we already have for this voice."""
    c = sqlite3.connect(DB)
    row = c.execute("""SELECT source_id FROM passages
                       WHERE voice = ? AND kind = 'x_post'
                       ORDER BY posted_at ASC NULLS LAST LIMIT 1""", (voice,)).fetchone()
    c.close()
    if not row: return None
    sid = row[0]
    # source_id is like "x-VOICE-TWEET_ID"
    parts = sid.split("-", 2)
    return parts[-1] if len(parts) == 3 else None

def get_user_id(handle: str) -> str:
    global _total_reads
    with httpx.Client(timeout=20.0, headers=HEADERS) as c:
        r = c.get(f"https://api.x.com/2/users/by/username/{handle.lstrip('@')}",
                  params={"user.fields": "name"})
    _total_reads += 1
    return r.json()["data"]["id"]

def fetch_timeline_older(user_id: str, until_id: str, max_results: int) -> list:
    """Pull tweets older than until_id."""
    global _total_reads
    out = []
    next_token = None
    pulled = 0
    with httpx.Client(timeout=30.0, headers=HEADERS) as cli:
        while pulled < max_results:
            params = {
                "max_results": min(100, max_results - pulled),
                "tweet.fields": "id,text,created_at,public_metrics",
                "exclude": "retweets,replies",
                "until_id": until_id,
            }
            if next_token: params["pagination_token"] = next_token
            if params["max_results"] < 5: break  # X requires 5+
            r = cli.get(f"https://api.x.com/2/users/{user_id}/tweets", params=params)
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 90:
                    print(f"    ⚠ rate limited; bailing"); break
                time.sleep(wait); continue
            if r.status_code != 200:
                print(f"    ! status {r.status_code}: {r.text[:150]}"); break
            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            _total_reads += len(tweets)
            pulled += len(tweets)
            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets: break
            print(f"    ... {pulled} pulled (cost: ${cost():.2f})")
    return out

def fetch_search_all(query: str, max_results: int) -> list:
    global _total_reads
    out = []
    next_token = None
    pulled = 0
    with httpx.Client(timeout=60.0, headers=HEADERS) as cli:
        while pulled < max_results:
            params = {
                "query": query,
                "max_results": min(100, max_results - pulled),
                "tweet.fields": "id,text,created_at,public_metrics,author_id",
            }
            if next_token: params["next_token"] = next_token
            if params["max_results"] < 10: break
            r = cli.get("https://api.x.com/2/tweets/search/all", params=params)
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 120:
                    print(f"    ⚠ rate limited >2min, bailing"); break
                print(f"    sleeping {wait}s for rate limit reset")
                time.sleep(wait); continue
            if r.status_code == 403:
                print(f"    ! search/all 403 (entitlement issue)"); return out
            if r.status_code != 200:
                print(f"    ! status {r.status_code}: {r.text[:150]}"); break
            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            _total_reads += len(tweets)
            pulled += len(tweets)
            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets: break
            print(f"    ... '{query[:40]}': {pulled} (cost: ${cost():.2f})")
    return out

def main():
    print(f"Round 2 X spend, hard cap ${HARD_CAP_USD}\n")

    # === GRIMHOOD older ===
    print("=== @Grimhood — older timeline + topic searches ===")
    gid = get_user_id("Grimhood")
    print(f"  user_id: {gid}  [cost: ${cost():.2f}]")
    grim_oldest = get_oldest_tweet_id("Grimhood")
    print(f"  oldest tweet id we have: {grim_oldest}")

    if grim_oldest and check_budget("Grimhood older timeline (1500)", 1500):
        print(f"\n  [1] Older originals (until_id={grim_oldest}, max 1500)...")
        tweets = fetch_timeline_older(gid, grim_oldest, 1500)
        n = insert_tweets("Grimhood", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")

    # Wait then retry topic searches
    print("\n  Sleeping 60s before search/all to let rate limit reset...")
    time.sleep(60)

    grim_topics = [
        "from:Grimhood (magnesium OR mineral OR potassium) -is:retweet -is:reply",
        "from:Grimhood (sleep OR cortisol OR insomnia OR melatonin) -is:retweet -is:reply",
        "from:Grimhood (herb OR adaptogen OR tincture OR protocol) -is:retweet -is:reply",
        "from:Grimhood (detox OR liver OR drainage OR toxin) -is:retweet -is:reply",
    ]
    for q in grim_topics:
        if not check_budget(f"topic", 100): break
        print(f"\n  [topic] {q[:80]}...")
        tweets = fetch_search_all(q, 100)
        n = insert_tweets("Grimhood", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")
        time.sleep(15)  # gentle pacing between searches

    # === BIOAVAILABLEND older ===
    print("\n=== @BioavailableNd — older timeline + topic searches ===")
    bid = get_user_id("BioavailableNd")
    print(f"  user_id: {bid}  [cost: ${cost():.2f}]")
    bio_oldest = get_oldest_tweet_id("BioavailableNd")
    print(f"  oldest tweet id we have: {bio_oldest}")

    if bio_oldest and check_budget("BioavailableNd older (800)", 800):
        print(f"\n  [1] Older originals (until_id={bio_oldest}, max 800)...")
        tweets = fetch_timeline_older(bid, bio_oldest, 800)
        n = insert_tweets("BioavailableNd", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")

    print("\n  Sleeping 30s...")
    time.sleep(30)

    bio_topics = [
        "from:BioavailableNd (mold OR mycotoxin OR detox OR binder) -is:retweet -is:reply",
        "from:BioavailableNd (lymph OR drainage OR fertility OR cycle) -is:retweet -is:reply",
        "from:BioavailableNd (mineral OR magnesium OR potassium) -is:retweet -is:reply",
    ]
    for q in bio_topics:
        if not check_budget(f"topic", 100): break
        print(f"\n  [topic] {q[:80]}...")
        tweets = fetch_search_all(q, 100)
        n = insert_tweets("BioavailableNd", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")
        time.sleep(15)

    print(f"\n=== DONE ===")
    print(f"Reads used:    {_total_reads}")
    print(f"Cost:          ${cost():.2f}")
    print(f"Budget left:   ${HARD_CAP_USD - cost():.2f} (of ${HARD_CAP_USD} cap)")

    c = sqlite3.connect(DB)
    rows = c.execute("SELECT voice, COUNT(*) FROM passages GROUP BY voice ORDER BY COUNT(*) DESC").fetchall()
    total = c.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    print(f"\nCouncil total: {total}")
    for v, n in rows:
        print(f"  @{v:<22} {n:>5}")
    c.close()

if __name__ == "__main__":
    main()
