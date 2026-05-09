#!/usr/bin/env python3
"""
Dr. Vitalis - Council MCP Server

Stores a corpus of posts from a curated council of trusted voices, fetched from the
official X (Twitter) API. Exposes search tools that return weighted, ranked passages
which Claude synthesizes into unified actionable advice (with attribution stripped at
the skill layer).

Internally, sources are tracked in full so the user can audit via /why if desired.
The user-facing skill enforces no-attribution synthesis.

Storage: SQLite + FTS5 (no embedding model dependency).
Refresh: X API v2 user timeline endpoint (httpx).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import httpx
from mcp.server.fastmcp import FastMCP


# --------------------------------------------------------------------------- paths/config

DB_PATH = Path(os.environ.get(
    "COUNCIL_DB_PATH",
    str(Path.home() / ".dr-vitalis" / "council.db"),
))
DASHBOARD_PATH = Path(os.environ.get(
    "COUNCIL_DASHBOARD_PATH",
    str(Path.home() / ".dr-vitalis" / "dashboard.html"),
))
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "dashboard.html"
SEED_DB_PATH = Path(os.environ.get(
    "COUNCIL_SEED_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "seed.db"),
))

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _maybe_seed_from_bundle() -> None:
    """
    First-run seeding: if the user has no local DB but a bundled seed.db
    exists in the plugin (data/seed.db), copy it. This lets installers see
    the plugin work immediately without an X API key. The user can refresh
    or replace the corpus once they wire up X_BEARER_TOKEN.
    """
    if DB_PATH.exists():
        return
    if not SEED_DB_PATH.exists():
        return
    try:
        import shutil
        shutil.copyfile(SEED_DB_PATH, DB_PATH)
        print(f"[dr-vitalis] seeded local DB from bundled corpus: {SEED_DB_PATH}", file=sys.stderr)
    except Exception as e:
        print(f"[dr-vitalis] seed copy failed (continuing with empty DB): {e}", file=sys.stderr)


_maybe_seed_from_bundle()

X_API_BASE = "https://api.x.com/2"
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "").strip()


# --------------------------------------------------------------------------- db

SCHEMA = """
CREATE TABLE IF NOT EXISTS voices (
    handle      TEXT PRIMARY KEY,         -- without leading @
    display     TEXT,                     -- human-readable name (e.g. "Paul Saladino")
    user_id     TEXT,                     -- X numeric user id, cached
    weight      REAL NOT NULL DEFAULT 1.0,
    notes       TEXT,
    added_at    INTEGER NOT NULL,
    refreshed_at INTEGER,
    recency_half_life_days INTEGER NOT NULL DEFAULT 180  -- per-voice recency curve; lower = newer content weighted more
);

CREATE TABLE IF NOT EXISTS passages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    voice       TEXT NOT NULL REFERENCES voices(handle) ON DELETE CASCADE,
    source_id   TEXT,                     -- X post id or arbitrary id for manual paste
    source_url  TEXT,
    text        TEXT NOT NULL,
    posted_at   INTEGER,                  -- unix seconds, nullable
    fetched_at  INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'x_post',  -- x_post | manual | other
    UNIQUE (voice, source_id)
);

CREATE INDEX IF NOT EXISTS idx_passages_voice ON passages(voice);
CREATE INDEX IF NOT EXISTS idx_passages_posted ON passages(posted_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text,
    voice UNINDEXED,
    content='passages',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts(rowid, text, voice) VALUES (new.id, new.text, new.voice);
END;
CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text, voice) VALUES('delete', old.id, old.text, old.voice);
END;
CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text, voice) VALUES('delete', old.id, old.text, old.voice);
    INSERT INTO passages_fts(rowid, text, voice) VALUES (new.id, new.text, new.voice);
END;

CREATE TABLE IF NOT EXISTS query_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    voice       TEXT,                     -- null for council-wide queries
    top_k       INTEGER,
    result_ids  TEXT,                     -- JSON array of passage ids returned
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);
"""


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        # Migration: add recency_half_life_days column to existing DBs (idempotent)
        try:
            conn.execute("ALTER TABLE voices ADD COLUMN recency_half_life_days INTEGER NOT NULL DEFAULT 180")
        except sqlite3.OperationalError:
            pass  # column already exists


# --------------------------------------------------------------------------- X API

class XAPIError(RuntimeError):
    pass


def _x_headers() -> dict[str, str]:
    if not X_BEARER_TOKEN:
        raise XAPIError(
            "X_BEARER_TOKEN is not set. Get one at https://console.x.com and add it to your environment."
        )
    return {"Authorization": f"Bearer {X_BEARER_TOKEN}"}


def x_get_user(handle: str) -> dict[str, Any]:
    """
    Resolve @handle -> {id, name, tweet_count, created_at}. Costs 1 read.
    tweet_count is the user's lifetime tweet count, useful for cost estimation.
    """
    handle = handle.lstrip("@")
    url = f"{X_API_BASE}/users/by/username/{handle}"
    with httpx.Client(timeout=20.0) as client:
        r = client.get(
            url,
            headers=_x_headers(),
            params={"user.fields": "name,public_metrics,created_at"},
        )
    if r.status_code != 200:
        raise XAPIError(f"users/by/username/{handle} -> {r.status_code}: {r.text[:200]}")
    data = r.json().get("data") or {}
    if not data.get("id"):
        raise XAPIError(f"No user data returned for @{handle}")
    metrics = data.get("public_metrics") or {}
    return {
        "id": data["id"],
        "name": data.get("name") or handle,
        "tweet_count": int(metrics.get("tweet_count") or 0),
        "created_at": data.get("created_at"),
    }


def x_get_user_id(handle: str) -> tuple[str, str]:
    """Compatibility shim. Returns (user_id, display_name)."""
    info = x_get_user(handle)
    return info["id"], info["name"]


def x_full_archive_search(
    handle: str,
    max_results: int = 500,
    since_id: str | None = None,
    until_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Full-archive search for a user's tweets via /2/tweets/search/all.
    Goes back to 2006. Excludes retweets and replies. Costs 1 read per tweet.

    NOTE: search/all may require Pro-tier on legacy plans, but is generally
    accessible on pay-per-use accounts in 2026. If you hit a 403, your account
    needs the search/all entitlement enabled.
    """
    handle = handle.lstrip("@")
    out: list[dict[str, Any]] = []
    next_token: str | None = None
    pulled = 0
    page_size = 500  # max per page on search/all

    query = f"from:{handle} -is:retweet -is:reply"

    with httpx.Client(timeout=60.0, headers=_x_headers()) as client:
        while pulled < max_results:
            params: dict[str, Any] = {
                "query": query,
                "max_results": min(page_size, max_results - pulled),
                "tweet.fields": "id,text,created_at,public_metrics,author_id,entities",
            }
            if since_id:
                params["since_id"] = since_id
            if until_id:
                params["until_id"] = until_id
            if next_token:
                params["next_token"] = next_token

            url = f"{X_API_BASE}/tweets/search/all"
            r = client.get(url, params=params)
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 90:
                    raise XAPIError(f"Rate limited on search/all; reset in {wait}s.")
                time.sleep(wait)
                continue
            if r.status_code == 403:
                raise XAPIError(
                    "search/all returned 403. Your X dev account may not have full-archive "
                    "search enabled. Use mode='recent' (timeline endpoint, 3200-tweet cap) instead."
                )
            if r.status_code != 200:
                raise XAPIError(f"tweets/search/all -> {r.status_code}: {r.text[:200]}")

            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            pulled += len(tweets)

            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets:
                break

    return out


def x_fetch_timeline(user_id: str, max_results: int = 100, since_id: str | None = None) -> list[dict[str, Any]]:
    """
    Pull a user's recent posts. Costs ~max_results/100 reads (paginated at 100 max per call).
    Returns list of {id, text, created_at, ...}.
    """
    out: list[dict[str, Any]] = []
    next_token: str | None = None
    pulled = 0
    page_size = min(100, max_results)

    with httpx.Client(timeout=30.0, headers=_x_headers()) as client:
        while pulled < max_results:
            params: dict[str, Any] = {
                "max_results": min(page_size, max_results - pulled),
                "tweet.fields": "id,text,created_at,public_metrics,referenced_tweets,entities",
                "exclude": "retweets,replies",
            }
            if since_id:
                params["since_id"] = since_id
            if next_token:
                params["pagination_token"] = next_token

            url = f"{X_API_BASE}/users/{user_id}/tweets"
            r = client.get(url, params=params)
            if r.status_code == 429:
                # rate limited
                reset = int(r.headers.get("x-rate-limit-reset", "0")) or (int(time.time()) + 60)
                wait = max(1, reset - int(time.time()))
                if wait > 90:
                    raise XAPIError(f"Rate limited; reset in {wait}s. Try again later.")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                raise XAPIError(f"users/{user_id}/tweets -> {r.status_code}: {r.text[:200]}")

            payload = r.json()
            tweets = payload.get("data") or []
            out.extend(tweets)
            pulled += len(tweets)

            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token or not tweets:
                break

    return out


def _to_unix(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        # X uses RFC3339 like "2024-12-30T15:30:00.000Z"
        from datetime import datetime, timezone
        ts = iso_ts.replace("Z", "+00:00")
        return int(datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return None


# --------------------------------------------------------------------------- mcp server

mcp = FastMCP("dr-vitalis-council")
init_db()


@dataclass
class Voice:
    handle: str
    display: str
    weight: float
    user_id: str | None
    notes: str | None
    refreshed_at: int | None


def _row_to_voice(row: sqlite3.Row) -> Voice:
    return Voice(
        handle=row["handle"],
        display=row["display"] or row["handle"],
        weight=float(row["weight"]),
        user_id=row["user_id"],
        notes=row["notes"],
        refreshed_at=row["refreshed_at"],
    )


# ----- voice management

@mcp.tool()
def add_voice(handle: str, display: str | None = None, weight: float = 1.0, notes: str | None = None) -> dict[str, Any]:
    """
    Add a trusted voice (X handle) to the council.

    Args:
        handle: X username, with or without leading @ (e.g. "paulsaladinomd").
        display: Human-readable name (e.g. "Paul Saladino"). If omitted, will be filled
                 on first refresh from the X API.
        weight: Ranking weight applied to this voice's passages in council search.
                1.0 is normal; 2.0 doubles; 0.5 halves. Useful for emphasizing voices
                you trust most.
        notes: Free-form notes (e.g. "carnivore, anti-seed-oil").
    """
    handle = handle.lstrip("@").strip()
    if not handle:
        return {"ok": False, "error": "handle is required"}
    with db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO voices (handle, display, weight, notes, added_at, refreshed_at, user_id)
               VALUES (?, ?, ?, ?, ?, COALESCE((SELECT refreshed_at FROM voices WHERE handle = ?), NULL),
                       COALESCE((SELECT user_id FROM voices WHERE handle = ?), NULL))""",
            (handle, display, weight, notes, int(time.time()), handle, handle),
        )
    _regenerate_dashboard()
    return {"ok": True, "voice": handle, "weight": weight}


@mcp.tool()
def remove_voice(handle: str) -> dict[str, Any]:
    """Remove a voice and all their passages from the council."""
    handle = handle.lstrip("@").strip()
    with db() as conn:
        cur = conn.execute("DELETE FROM voices WHERE handle = ?", (handle,))
    _regenerate_dashboard()
    return {"ok": True, "removed": handle, "rows": cur.rowcount}


@mcp.tool()
def set_weight(handle: str, weight: float) -> dict[str, Any]:
    """Update the ranking weight for an existing voice."""
    handle = handle.lstrip("@").strip()
    with db() as conn:
        cur = conn.execute("UPDATE voices SET weight = ? WHERE handle = ?", (weight, handle))
    _regenerate_dashboard()
    return {"ok": cur.rowcount > 0, "voice": handle, "weight": weight}


@mcp.tool()
def set_recency_half_life(handle: str, days: int) -> dict[str, Any]:
    """
    Set the recency half-life (in days) for a voice. Newer content gets ranked
    higher; older content decays.

    - 90 days: aggressive (Saladino-style — voice has evolved their views)
    - 180 days: default (mild boost for recent)
    - 365+ days: nearly no recency tilt (voice's older content is still valid)
    - 9999: effectively no recency adjustment

    Use when a voice has clearly shifted their position over time (e.g. Saladino
    pivoting from full-carnivore to animal-based) and you want their newer
    thinking to dominate.
    """
    handle = handle.lstrip("@").strip()
    if days < 7:
        return {"ok": False, "error": "days must be >= 7"}
    with db() as conn:
        cur = conn.execute("UPDATE voices SET recency_half_life_days = ? WHERE handle = ?", (days, handle))
    _regenerate_dashboard()
    return {"ok": cur.rowcount > 0, "voice": handle, "recency_half_life_days": days}


@mcp.tool()
def list_voices() -> dict[str, Any]:
    """List all voices in the council with their weights, post counts, and refresh times."""
    with db() as conn:
        rows = conn.execute(
            """SELECT v.*, COUNT(p.id) AS post_count
               FROM voices v LEFT JOIN passages p ON p.voice = v.handle
               GROUP BY v.handle ORDER BY v.weight DESC, v.handle"""
        ).fetchall()
    voices = [
        {
            "handle": r["handle"],
            "display": r["display"] or r["handle"],
            "weight": r["weight"],
            "post_count": r["post_count"],
            "refreshed_at": r["refreshed_at"],
            "notes": r["notes"],
        }
        for r in rows
    ]
    return {"voices": voices, "count": len(voices)}


# ----- refresh

@mcp.tool()
def refresh_voice(handle: str, max_posts: int = 200) -> dict[str, Any]:
    """
    Pull recent posts for a voice from the X API and store them.

    Args:
        handle: X username (with or without @).
        max_posts: Max number of recent posts to pull. Each post costs ~$0.005 via
                   X pay-per-use pricing. 200 is a good default for ongoing refresh;
                   use up to 3200 (X's per-user timeline cap) for initial backfill.

    Returns count of new passages added.
    """
    handle = handle.lstrip("@").strip()
    with db() as conn:
        row = conn.execute("SELECT * FROM voices WHERE handle = ?", (handle,)).fetchone()
    if not row:
        return {"ok": False, "error": f"@{handle} not in council. Use add_voice first."}
    voice = _row_to_voice(row)

    # Resolve user_id if needed
    if not voice.user_id:
        try:
            info = x_get_user(handle)
        except XAPIError as e:
            return {"ok": False, "error": str(e)}
        with db() as conn:
            conn.execute(
                "UPDATE voices SET user_id = ?, display = COALESCE(display, ?) WHERE handle = ?",
                (info["id"], info["name"], handle),
            )
        voice.user_id = info["id"]

    # Find newest stored post id, used as since_id
    with db() as conn:
        latest = conn.execute(
            "SELECT source_id FROM passages WHERE voice = ? AND kind = 'x_post' ORDER BY posted_at DESC NULLS LAST LIMIT 1",
            (handle,),
        ).fetchone()
    since_id = latest["source_id"] if latest else None

    try:
        tweets = x_fetch_timeline(voice.user_id, max_results=max_posts, since_id=since_id)
    except XAPIError as e:
        return {"ok": False, "error": str(e)}

    added = 0
    now = int(time.time())
    with db() as conn:
        for t in tweets:
            tid = str(t.get("id"))
            text = t.get("text") or ""
            if not tid or not text.strip():
                continue
            posted = _to_unix(t.get("created_at"))
            url = f"https://x.com/{handle}/status/{tid}"
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO passages
                       (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                       VALUES (?, ?, ?, ?, ?, ?, 'x_post')""",
                    (handle, tid, url, text, posted, now),
                )
                if conn.total_changes > 0:
                    added += 1
            except sqlite3.Error:
                continue
        conn.execute("UPDATE voices SET refreshed_at = ? WHERE handle = ?", (now, handle))

    _regenerate_dashboard()
    return {"ok": True, "voice": handle, "fetched": len(tweets), "added": added}


@mcp.tool()
def refresh_all(max_posts: int = 200) -> dict[str, Any]:
    """Refresh every voice in the council. See refresh_voice for max_posts cost notes."""
    with db() as conn:
        rows = conn.execute("SELECT handle FROM voices ORDER BY handle").fetchall()
    results = []
    for r in rows:
        results.append(refresh_voice(handle=r["handle"], max_posts=max_posts))
    _regenerate_dashboard()
    return {"ok": True, "results": results}


# ----- backfill (deep history) and cost estimation

PRICE_PER_READ_USD = 0.01  # X API pay-per-use rate observed May 2026 (~$0.005-$0.01 per resource depending on call type; $0.01 is conservative)


@mcp.tool()
def estimate_voice_cost(handle: str) -> dict[str, Any]:
    """
    Look up a single voice's lifetime tweet count and estimate the cost to
    backfill their entire archive. Costs 1 read (~$0.005) for the lookup.

    Returns:
        - tweet_count: lifetime total (includes RTs/replies/originals)
        - estimated_originals: ~40-60% of tweet_count after filtering RTs/replies
        - cost_recent_only: cost for the 3,200 timeline cap (X's hard limit on
          the standard timeline endpoint)
        - cost_full_archive: cost for the entire archive via search/all
    """
    handle = handle.lstrip("@").strip()
    try:
        info = x_get_user(handle)
    except XAPIError as e:
        return {"ok": False, "error": str(e)}

    # Cache user_id + display for later refreshes
    with db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO voices (handle, weight, added_at) VALUES (?, 1.0, ?);""",
            (handle, int(time.time())),
        )
        conn.execute(
            "UPDATE voices SET user_id = ?, display = COALESCE(display, ?) WHERE handle = ?",
            (info["id"], info["name"], handle),
        )

    total = info["tweet_count"]
    estimated_originals = int(total * 0.5)  # rough — varies by user
    cost_recent = min(3200, total) * PRICE_PER_READ_USD
    cost_full = total * PRICE_PER_READ_USD

    return {
        "ok": True,
        "handle": handle,
        "display": info["name"],
        "user_id": info["id"],
        "tweet_count": total,
        "estimated_originals": estimated_originals,
        "cost_recent_only_usd": round(cost_recent, 2),
        "cost_full_archive_usd": round(cost_full, 2),
        "note": "recent_only uses the timeline endpoint capped at 3200 tweets; full_archive uses search/all and may require entitlement on your X dev account.",
    }


@mcp.tool()
def estimate_council_cost() -> dict[str, Any]:
    """
    Estimate the cost to backfill EVERY voice in the council. Costs N reads
    (one profile lookup per voice, ~$0.07-$0.14 for a typical 7-voice council).
    Returns a breakdown so you can decide which voices warrant the deep backfill.
    """
    with db() as conn:
        rows = conn.execute("SELECT handle FROM voices ORDER BY handle").fetchall()
    if not rows:
        return {"ok": False, "error": "No voices in council yet."}

    estimates = []
    total_recent = 0.0
    total_full = 0.0
    total_tweets = 0

    for r in rows:
        est = estimate_voice_cost(handle=r["handle"])
        if not est.get("ok"):
            estimates.append({"handle": r["handle"], "error": est.get("error")})
            continue
        estimates.append({
            "handle": est["handle"],
            "display": est["display"],
            "tweet_count": est["tweet_count"],
            "cost_recent_only_usd": est["cost_recent_only_usd"],
            "cost_full_archive_usd": est["cost_full_archive_usd"],
        })
        total_recent += est["cost_recent_only_usd"]
        total_full += est["cost_full_archive_usd"]
        total_tweets += est["tweet_count"]

    return {
        "ok": True,
        "voices": estimates,
        "totals": {
            "tweet_count": total_tweets,
            "cost_recent_only_usd": round(total_recent, 2),
            "cost_full_archive_usd": round(total_full, 2),
        },
        "note": "These are upper bounds. Actual cost is lower because we filter RTs/replies before storing, and search/all paginates 500/page so partial pulls let you stop early.",
    }


@mcp.tool()
def backfill_voice(
    handle: str,
    mode: str = "recent",
    max_posts: int = 3200,
    confirm_cost_usd: float | None = None,
) -> dict[str, Any]:
    """
    Pull deeper history for a voice than refresh_voice does.

    Args:
        handle: X username (with or without @).
        mode: "recent" (use timeline endpoint, capped at 3200) or "full"
              (use search/all, can go back to account creation).
        max_posts: Cap on how many to pull. For mode='recent', X enforces
                   3200 max. For mode='full', this is your spend cap.
        confirm_cost_usd: Safety check — if you set this, the call will
                          refuse to run if the estimated cost exceeds it.
                          Useful for "don't spend more than $20" guardrails.

    Returns count of new passages added.
    """
    handle = handle.lstrip("@").strip()
    if mode not in ("recent", "full"):
        return {"ok": False, "error": "mode must be 'recent' or 'full'"}

    # cost guardrail
    if confirm_cost_usd is not None:
        est_cost = max_posts * PRICE_PER_READ_USD
        if est_cost > confirm_cost_usd:
            return {
                "ok": False,
                "error": f"Estimated cost ${est_cost:.2f} exceeds your cap ${confirm_cost_usd:.2f}. "
                         f"Either raise the cap or lower max_posts.",
                "estimated_cost_usd": round(est_cost, 2),
            }

    with db() as conn:
        row = conn.execute("SELECT * FROM voices WHERE handle = ?", (handle,)).fetchone()
    if not row:
        return {"ok": False, "error": f"@{handle} not in council. Use add_voice first."}
    voice = _row_to_voice(row)

    # ensure user_id cached
    if not voice.user_id:
        try:
            info = x_get_user(handle)
        except XAPIError as e:
            return {"ok": False, "error": str(e)}
        with db() as conn:
            conn.execute(
                "UPDATE voices SET user_id = ?, display = COALESCE(display, ?) WHERE handle = ?",
                (info["id"], info["name"], handle),
            )
        voice.user_id = info["id"]

    # Fetch tweets via the chosen mode
    try:
        if mode == "recent":
            tweets = x_fetch_timeline(voice.user_id, max_results=min(max_posts, 3200))
        else:  # full
            tweets = x_full_archive_search(handle, max_results=max_posts)
    except XAPIError as e:
        return {"ok": False, "error": str(e), "mode": mode}

    added = 0
    now = int(time.time())
    with db() as conn:
        for t in tweets:
            tid = str(t.get("id"))
            text = t.get("text") or ""
            if not tid or not text.strip():
                continue
            posted = _to_unix(t.get("created_at"))
            url = f"https://x.com/{handle}/status/{tid}"
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO passages
                       (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                       VALUES (?, ?, ?, ?, ?, ?, 'x_post')""",
                    (handle, tid, url, text, posted, now),
                )
                if cur.rowcount > 0:
                    added += 1
            except sqlite3.Error:
                continue
        conn.execute("UPDATE voices SET refreshed_at = ? WHERE handle = ?", (now, handle))

    _regenerate_dashboard()
    return {
        "ok": True,
        "voice": handle,
        "mode": mode,
        "fetched": len(tweets),
        "added": added,
        "approx_cost_usd": round(len(tweets) * PRICE_PER_READ_USD, 2),
    }


@mcp.tool()
def backfill_all(
    mode: str = "recent",
    max_posts_per_voice: int = 3200,
    confirm_cost_usd: float | None = None,
) -> dict[str, Any]:
    """
    Backfill EVERY voice in the council. Same args as backfill_voice but
    the cost cap applies to total council spend.

    Strongly recommended: call estimate_council_cost first to see what
    you're committing to before running this with mode='full'.
    """
    with db() as conn:
        rows = conn.execute("SELECT handle FROM voices ORDER BY handle").fetchall()
    if not rows:
        return {"ok": False, "error": "No voices in council yet."}

    if confirm_cost_usd is not None:
        est_total = len(rows) * max_posts_per_voice * PRICE_PER_READ_USD
        if est_total > confirm_cost_usd:
            return {
                "ok": False,
                "error": f"Worst-case total ${est_total:.2f} exceeds your cap ${confirm_cost_usd:.2f}.",
                "estimated_cost_usd": round(est_total, 2),
                "voices": len(rows),
            }

    results = []
    total_added = 0
    total_fetched = 0
    for r in rows:
        res = backfill_voice(handle=r["handle"], mode=mode, max_posts=max_posts_per_voice)
        results.append(res)
        if res.get("ok"):
            total_added += res.get("added", 0)
            total_fetched += res.get("fetched", 0)

    _regenerate_dashboard()
    return {
        "ok": True,
        "mode": mode,
        "total_fetched": total_fetched,
        "total_added": total_added,
        "approx_cost_usd": round(total_fetched * PRICE_PER_READ_USD, 2),
        "results": results,
    }


# ----- search

def _fts_query(q: str) -> str:
    """Sanitize a freeform query into an FTS5 MATCH expression."""
    # escape FTS-special characters; treat each whitespace-separated token as required
    cleaned = []
    for tok in q.split():
        # drop FTS operators / special chars
        t = "".join(ch for ch in tok if ch.isalnum() or ch in "-_")
        if not t:
            continue
        cleaned.append(f'"{t}"')
    return " OR ".join(cleaned) if cleaned else q


@mcp.tool()
def query_council(query: str, top_k: int = 8, recency_boost: bool = True) -> dict[str, Any]:
    """
    Search the entire council corpus for passages relevant to the query.

    Returns the top_k passages ranked by (FTS5 BM25 score) * (voice weight) and,
    if recency_boost is on, with a mild recency tilt. Each result includes the
    source voice handle, post URL, and full text.

    IMPORTANT for the consuming skill: do NOT cite individual voices in the
    user-facing answer. Synthesize across passages and speak in one direct voice.

    Args:
        query: Freeform search query (e.g. "bloating after meals", "3am wakeup", "ApoB").
        top_k: How many passages to return.
        recency_boost: If true, more recent passages get a small ranking bump.
    """
    if not query.strip():
        return {"results": [], "error": "empty query"}

    fts_q = _fts_query(query)
    now = int(time.time())

    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.voice, p.source_id, p.source_url, p.text, p.posted_at, p.fetched_at,
                   v.weight, v.display, v.recency_half_life_days,
                   bm25(passages_fts) AS bm25
            FROM passages_fts
            JOIN passages p ON p.id = passages_fts.rowid
            JOIN voices v ON v.handle = p.voice
            WHERE passages_fts MATCH ?
            ORDER BY bm25 ASC
            LIMIT 200
            """,
            (fts_q,),
        ).fetchall()

    scored = []
    for r in rows:
        # bm25 returns lower-is-better; convert to higher-is-better
        base = -float(r["bm25"])
        weighted = base * float(r["weight"])
        if recency_boost and r["posted_at"]:
            age = max(0, now - int(r["posted_at"]))
            half_life_days = r["recency_half_life_days"] or 180
            half_life = half_life_days * 86400
            decay = 0.5 ** (age / half_life)
            # newer = up to 1.0x boost; ancient = down to 0.5x
            weighted *= 0.5 + 0.5 * decay
        scored.append((weighted, r))
    scored.sort(key=lambda x: x[0], reverse=True)

    top = scored[:top_k]
    result_ids = [int(r["id"]) for _, r in top]

    with db() as conn:
        conn.execute(
            "INSERT INTO query_log (query, voice, top_k, result_ids, created_at) VALUES (?, NULL, ?, ?, ?)",
            (query, top_k, json.dumps(result_ids), now),
        )

    _regenerate_dashboard()
    return {
        "query": query,
        "count": len(top),
        "results": [
            {
                "id": int(r["id"]),
                "voice": r["voice"],
                "display": r["display"] or r["voice"],
                "url": r["source_url"],
                "text": r["text"],
                "posted_at": r["posted_at"],
                "score": round(float(score), 4),
            }
            for score, r in top
        ],
    }


@mcp.tool()
def query_voice(handle: str, query: str, top_k: int = 5) -> dict[str, Any]:
    """Search a single voice's passages for relevance to a query."""
    handle = handle.lstrip("@").strip()
    if not query.strip():
        return {"results": []}
    fts_q = _fts_query(query)
    now = int(time.time())

    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.voice, p.source_id, p.source_url, p.text, p.posted_at,
                   v.display, bm25(passages_fts) AS bm25
            FROM passages_fts
            JOIN passages p ON p.id = passages_fts.rowid
            JOIN voices v ON v.handle = p.voice
            WHERE passages_fts MATCH ? AND p.voice = ?
            ORDER BY bm25 ASC
            LIMIT ?
            """,
            (fts_q, handle, top_k),
        ).fetchall()
        result_ids = [int(r["id"]) for r in rows]
        conn.execute(
            "INSERT INTO query_log (query, voice, top_k, result_ids, created_at) VALUES (?, ?, ?, ?, ?)",
            (query, handle, top_k, json.dumps(result_ids), now),
        )

    _regenerate_dashboard()
    return {
        "voice": handle,
        "query": query,
        "results": [
            {
                "id": int(r["id"]),
                "url": r["source_url"],
                "text": r["text"],
                "posted_at": r["posted_at"],
            }
            for r in rows
        ],
    }


@mcp.tool()
def list_recent(handle: str | None = None, limit: int = 20) -> dict[str, Any]:
    """List most recent passages, optionally filtered to a single voice."""
    with db() as conn:
        if handle:
            handle = handle.lstrip("@").strip()
            rows = conn.execute(
                "SELECT * FROM passages WHERE voice = ? ORDER BY posted_at DESC NULLS LAST LIMIT ?",
                (handle, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM passages ORDER BY posted_at DESC NULLS LAST LIMIT ?",
                (limit,),
            ).fetchall()
    return {
        "results": [
            {
                "id": r["id"],
                "voice": r["voice"],
                "url": r["source_url"],
                "text": r["text"],
                "posted_at": r["posted_at"],
            }
            for r in rows
        ]
    }


@mcp.tool()
def save_passage(voice: str, text: str, source_url: str | None = None, posted_at: int | None = None) -> dict[str, Any]:
    """
    Manually save a passage (e.g. a thread you want to remember, or content from
    outside X). Useful when X scraping fails or when you want to curate by hand.
    """
    voice = voice.lstrip("@").strip()
    if not text.strip():
        return {"ok": False, "error": "text is required"}
    now = int(time.time())
    with db() as conn:
        # ensure voice exists (auto-create with weight 1.0)
        conn.execute(
            "INSERT OR IGNORE INTO voices (handle, weight, added_at) VALUES (?, 1.0, ?)",
            (voice, now),
        )
        cur = conn.execute(
            """INSERT INTO passages (voice, source_id, source_url, text, posted_at, fetched_at, kind)
               VALUES (?, ?, ?, ?, ?, ?, 'manual')""",
            (voice, f"manual-{now}", source_url, text, posted_at, now),
        )
    _regenerate_dashboard()
    return {"ok": True, "id": cur.lastrowid}


# ----- last sources (for /why)

@mcp.tool()
def last_sources(limit: int = 8) -> dict[str, Any]:
    """
    Return the source passages for the most recent council query. This is the
    audit trail for /why — it lets the user see which voices' passages powered
    the last synthesized answer.
    """
    with db() as conn:
        last = conn.execute(
            "SELECT * FROM query_log ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not last:
            return {"ok": False, "error": "no queries yet"}
        ids = json.loads(last["result_ids"] or "[]")[:limit]
        if not ids:
            return {"ok": True, "query": last["query"], "results": []}
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT p.*, v.display FROM passages p JOIN voices v ON v.handle = p.voice WHERE p.id IN ({placeholders})",
            ids,
        ).fetchall()
    return {
        "ok": True,
        "query": last["query"],
        "asked_at": last["created_at"],
        "results": [
            {
                "voice": r["voice"],
                "display": r["display"] or r["voice"],
                "url": r["source_url"],
                "text": r["text"],
                "posted_at": r["posted_at"],
            }
            for r in rows
        ],
    }


# ----- user profile (for the health-context skill)

@mcp.tool()
def set_profile(key: str, value: str) -> dict[str, Any]:
    """
    Store a piece of user health context (conditions, allergies, meds, goals,
    things you've tried). The health-context skill reads this on every health
    conversation so Jarvis personalizes its advice.
    """
    now = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
    _regenerate_dashboard()
    return {"ok": True, "key": key}


@mcp.tool()
def get_profile() -> dict[str, Any]:
    """Read the entire user health profile."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM user_profile ORDER BY key").fetchall()
    return {
        "profile": {r["key"]: r["value"] for r in rows},
        "count": len(rows),
    }


@mcp.tool()
def delete_profile_key(key: str) -> dict[str, Any]:
    """Remove a key from the user health profile."""
    with db() as conn:
        cur = conn.execute("DELETE FROM user_profile WHERE key = ?", (key,))
    return {"ok": cur.rowcount > 0, "key": key}


# --------------------------------------------------------------------------- dashboard

DASHBOARD_FALLBACK = """<!doctype html>
<html><head><meta charset="utf-8"><title>Dr. Vitalis</title>
<style>body{font:14px/1.5 ui-sans-serif,system-ui;max-width:840px;margin:32px auto;padding:0 16px;color:#222}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px;border-bottom:1px solid #eee;padding-bottom:4px}
table{border-collapse:collapse;width:100%}td,th{padding:6px 8px;border-bottom:1px solid #eee;text-align:left}
.muted{color:#888}.weight{font-variant-numeric:tabular-nums}.pill{display:inline-block;padding:1px 6px;border-radius:8px;background:#f3f3f3;font-size:12px}
code{background:#f6f6f6;padding:1px 4px;border-radius:3px}</style></head><body>
<h1>Dr. Vitalis</h1>
<p class="muted">Your private health advisor, in one direct voice · {{generated_at}}</p>
{{body}}
</body></html>"""


def _format_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _regenerate_dashboard() -> None:
    """Best-effort regeneration; never raises."""
    try:
        with db() as conn:
            voices = conn.execute(
                """SELECT v.*, COUNT(p.id) AS post_count
                   FROM voices v LEFT JOIN passages p ON p.voice = v.handle
                   GROUP BY v.handle ORDER BY v.weight DESC, v.handle"""
            ).fetchall()
            recent_q = conn.execute(
                "SELECT * FROM query_log ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            total_passages = conn.execute("SELECT COUNT(*) AS c FROM passages").fetchone()["c"]
            profile = conn.execute("SELECT * FROM user_profile ORDER BY key").fetchall()

        rows_html = "\n".join(
            f"<tr><td><a href='https://x.com/{v['handle']}'>@{v['handle']}</a></td>"
            f"<td>{(v['display'] or '').replace('<','&lt;')}</td>"
            f"<td class='weight'>{v['weight']:.1f}x</td>"
            f"<td>{v['post_count']}</td>"
            f"<td class='muted'>{_format_ts(v['refreshed_at'])}</td></tr>"
            for v in voices
        ) or "<tr><td colspan=5 class='muted'>No voices loaded.</td></tr>"

        queries_html = "\n".join(
            f"<tr><td class='muted'>{_format_ts(q['created_at'])}</td>"
            f"<td>{(q['query'] or '').replace('<','&lt;')[:140]}</td>"
            f"<td class='muted'>{('@' + q['voice']) if q['voice'] else 'all voices'}</td></tr>"
            for q in recent_q
        ) or "<tr><td colspan=3 class='muted'>No queries yet.</td></tr>"

        # Knowledge Gaps panel — best-effort, never blocks dashboard render
        gaps_html = ""
        try:
            from analyze_gaps import analyze, render_html  # type: ignore
            gaps_report = analyze(DB_PATH, min_queries=20)
            gaps_html = render_html(gaps_report)
        except Exception as e:
            gaps_html = f"<p class='muted'><em>Gaps panel unavailable: {e}</em></p>"

        profile_html = "\n".join(
            f"<tr><td><code>{p['key']}</code></td><td>{(p['value'] or '').replace('<','&lt;')}</td></tr>"
            for p in profile
        ) or "<tr><td colspan=2 class='muted'>No profile set yet.</td></tr>"

        body = f"""
<p><span class='pill'>{len(voices)} voices</span> <span class='pill'>{total_passages} passages</span></p>
<h2>Voices</h2>
<table><thead><tr><th>Handle</th><th>Name</th><th>Weight</th><th>Passages</th><th>Last refresh</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<h2>Your profile</h2>
<table><tbody>{profile_html}</tbody></table>
<h2>Recent queries</h2>
<table><thead><tr><th>When</th><th>Query</th><th>Scope</th></tr></thead>
<tbody>{queries_html}</tbody></table>
<h2>Knowledge gaps</h2>
{gaps_html}
"""
        # Use template if present, else fallback
        tmpl = TEMPLATE_PATH.read_text() if TEMPLATE_PATH.exists() else DASHBOARD_FALLBACK
        html = tmpl.replace("{{generated_at}}", _format_ts(int(time.time()))).replace("{{body}}", body)
        DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_PATH.write_text(html)
    except Exception as e:  # never break the MCP because the dashboard failed
        print(f"[dashboard] regenerate failed: {e}", file=sys.stderr)


# --------------------------------------------------------------------------- main

def main() -> None:
    _regenerate_dashboard()  # initial render
    mcp.run()


if __name__ == "__main__":
    main()
