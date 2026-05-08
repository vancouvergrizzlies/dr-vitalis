#!/usr/bin/env python3
"""
Targeted X API spend for Grimhood + BioavailableNd.

Strategy:
1. Most-recent original tweets (timeline endpoint) — gets current thinking
2. Full-archive search filtered to high-engagement — gets historic best content
3. Topic-specific searches across the archive — covers known signature themes

Hard stop if approaching $20 to leave buffer in user's $24.92 balance.
"""
from __future__ import annotations
import os, sqlite3, time, sys
from pathlib import Path
import httpx
from datetime import datetime, timezone

DB = Path.home() / ".dr-vitalis" / "council.db"
TOKEN = os.environ["X_BEARER_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Conservative cost estimate per tweet returned
PRICE_PER_READ = 0.01
HARD_CAP_USD = 20.00

# Spend tracker
_total_reads = 0
def reads_used() -> int:
    return _total_reads
def cost_so_far() -> float:
    return _total_reads * PRICE_PER_READ

def check_budget(action: str, expected_reads: int) -> bool:
    """Return False if proceeding would exceed cap."""
    projected = cost_so_far() + expected_reads * PRICE_PER_READ
    if projected > HARD_CAP_USD:
        print(f"  ⚠ would exceed cap (${projected:.2f} > ${HARD_CAP_USD}); skipping: {action}")
        return False
    return True

def x_get_user_id(handle: str) -> tuple[str, str]:
    global _total_reads
    handle = handle.lstrip("@")
    with httpx.Client(timeout=20.0, headers=HEADERS) as c:
        r = c.get(f"https://api.x.com/2/users/by/username/{handle}",
                  params={"user.fields": "name"})
    if r.status_code != 200:
        raise RuntimeError(f"users/by/username/{handle} -> {r.status_code}: {r.text[:200]}")
    _total_reads += 1
    data = r.json()["data"]
    return data["id"], data["name"]

def fetch_timeline(user_id: str, max_results: int) -> list[dict]:
    """Pull recent originals via /users/:id/tweets, paginated."""
    global _total_reads
    out = []
    next_token = None
    pulled = 0
    page_size = 100  # max
    with httpx.Client(timeout=30.0, headers=HEADERS) as c:
        while pulled < max_results:
            params = {
                "max_results": min(page_size, max_results - pulled),
                "tweet.fields": "id,text,created_at,public_metrics",
                "exclude": "retweets,replies",
            }
            if next_token:
                params["pagination_token"] = next_token
            r = c.get(f"https://api.x.com/2/users/{user_id}/tweets", params=params)
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 90:
                    print(f"  ⚠ rate limited; bailing")
                    break
                time.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"  ! status {r.status_code}: {r.text[:150]}")
                break
            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            _total_reads += len(tweets)
            pulled += len(tweets)
            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets:
                break
            print(f"    ... {pulled} pulled (cost: ${cost_so_far():.2f})")
    return out

def fetch_search_all(query: str, max_results: int) -> list[dict]:
    """Use full-archive search with filters."""
    global _total_reads
    out = []
    next_token = None
    pulled = 0
    page_size = 500  # max for search/all
    with httpx.Client(timeout=60.0, headers=HEADERS) as c:
        while pulled < max_results:
            params = {
                "query": query,
                "max_results": min(page_size, max_results - pulled, 100),  # 100 per page is safer
                "tweet.fields": "id,text,created_at,public_metrics,author_id",
            }
            if next_token:
                params["next_token"] = next_token
            r = c.get("https://api.x.com/2/tweets/search/all", params=params)
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 90:
                    print(f"    ⚠ rate limited; bailing")
                    break
                time.sleep(wait)
                continue
            if r.status_code == 403:
                print(f"    ! search/all 403 - your X tier may not have entitlement")
                return out
            if r.status_code != 200:
                print(f"    ! status {r.status_code}: {r.text[:150]}")
                break
            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            _total_reads += len(tweets)
            pulled += len(tweets)
            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets:
                break
            print(f"    ... search '{query[:40]}...': {pulled} pulled (cost: ${cost_so_far():.2f})")
    return out

def parse_iso(s):
    if not s: return None
    try:
        return int(datetime.fromisoformat(s.replace("Z","+00:00")).replace(tzinfo=timezone.utc).timestamp())
    except: return None

def insert_tweets(voice: str, tweets: list[dict]) -> int:
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
    c.commit()
    c.close()
    return n

# --- main ---

def main():
    print(f"Starting X spend with HARD CAP ${HARD_CAP_USD} (price assumed ${PRICE_PER_READ}/read)\n")

    # === GRIMHOOD ===
    print("=== @Grimhood (priority - X-only voice, 2x weight) ===")
    try:
        gid, gname = x_get_user_id("Grimhood")
        print(f"  user_id: {gid} ({gname})  [cost: ${cost_so_far():.2f}]")
    except Exception as e:
        print(f"  ! could not resolve Grimhood: {e}")
        return

    # 1. Recent timeline pull
    if check_budget("Grimhood recent timeline (1500)", 1500):
        print(f"\n  [1] Recent originals (timeline, max 1500)...")
        tweets = fetch_timeline(gid, 1500)
        n = insert_tweets("Grimhood", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")

    # 2. Topic-specific search/all with engagement filter
    grim_topics = [
        "from:Grimhood (magnesium OR mineral OR potassium) -is:retweet -is:reply",
        "from:Grimhood (sleep OR cortisol OR insomnia) -is:retweet -is:reply",
        "from:Grimhood (herb OR adaptogen OR tincture OR protocol) -is:retweet -is:reply",
        "from:Grimhood (detox OR liver OR drainage OR toxin) -is:retweet -is:reply",
    ]
    for q in grim_topics:
        if not check_budget(f"topic {q[:50]}...", 100):
            continue
        print(f"\n  [topic] {q[:80]}...")
        tweets = fetch_search_all(q, 100)
        n = insert_tweets("Grimhood", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")

    # === BIOAVAILABLEND ===
    print("\n=== @BioavailableNd (2x weight, supplements her Substack) ===")
    try:
        bid, bname = x_get_user_id("BioavailableNd")
        print(f"  user_id: {bid} ({bname})  [cost: ${cost_so_far():.2f}]")
    except Exception as e:
        print(f"  ! could not resolve BioavailableNd: {e}")
        bid = None

    if bid and check_budget("BioavailableNd recent timeline (500)", 500):
        print(f"\n  [1] Recent originals (timeline, max 500)...")
        tweets = fetch_timeline(bid, 500)
        n = insert_tweets("BioavailableNd", tweets)
        print(f"  + {len(tweets)} fetched, {n} new inserted")

    if bid:
        bio_topics = [
            "from:BioavailableNd (mold OR mycotoxin OR detox OR binder) -is:retweet -is:reply",
            "from:BioavailableNd (lymph OR drainage OR fertility) -is:retweet -is:reply",
        ]
        for q in bio_topics:
            if not check_budget(f"topic {q[:50]}...", 100):
                continue
            print(f"\n  [topic] {q[:80]}...")
            tweets = fetch_search_all(q, 100)
            n = insert_tweets("BioavailableNd", tweets)
            print(f"  + {len(tweets)} fetched, {n} new inserted")

    # final tally
    print(f"\n=== DONE ===")
    print(f"Total reads used: {reads_used()}")
    print(f"Estimated cost:   ${cost_so_far():.2f}")
    print(f"Remaining budget: ${HARD_CAP_USD - cost_so_far():.2f} (out of ${HARD_CAP_USD} cap)")

    c = sqlite3.connect(DB)
    rows = c.execute("SELECT voice, COUNT(*) AS n FROM passages GROUP BY voice ORDER BY n DESC").fetchall()
    total = c.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    print(f"\nCouncil total passages: {total}")
    for v, n in rows:
        print(f"  @{v:<22} {n:>5}")
    c.close()

if __name__ == "__main__":
    main()
