#!/usr/bin/env python3
"""
Parse Saladino's SRT files into council DB passages.

Re-runnable: skips files already inserted (by source_id = YouTube video id).

Each SRT:
- has rolling/duplicate captions (auto-generated)
- needs dedupe: lines that are prefix-continuations of the next line
- needs timestamp stripping
- needs joining into a coherent transcript

Each video produces 2-3 SRT files (en-orig, en, en-en-US). We prefer en-orig
(verbatim before YouTube's "translation"), then en, then en-en-US.
"""
from __future__ import annotations
import os, re, sqlite3, time, sys
from pathlib import Path
from collections import OrderedDict

DB = Path.home() / ".dr-vitalis" / "council.db"
SRT_DIR = Path("/tmp/dv_transcripts/saladino")
META_FILE = SRT_DIR / "_metadata.txt"

# ----- parse SRT -----

INDEX_RE = re.compile(r"^\d+$")
TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}")

def parse_srt_to_text(path: Path) -> str:
    """
    Return clean transcript from an SRT, deduping rolling captions.

    YouTube's auto-caption rolling pattern: each block contains lines that
    overlap with the previous block (the previous block's last line is still
    on-screen). To dedupe: emit each line only the first time it appears,
    relative to the previous block's lines.
    """
    lines = path.read_text(errors="ignore").splitlines()
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if INDEX_RE.match(s) or TS_RE.match(s):
            continue
        cur.append(s)
    if cur:
        blocks.append(cur)

    out: list[str] = []
    prev_lines: set[str] = set()
    for block in blocks:
        for line in block:
            # skip music/sound markers like "[Music]"
            if line.startswith("[") and line.endswith("]"):
                continue
            if line in prev_lines:
                continue
            out.append(line)
        prev_lines = set(block)

    full = " ".join(out)
    full = re.sub(r"\s+", " ", full).strip()
    return full

# ----- metadata -----

def load_metadata() -> dict[str, dict]:
    """_metadata.txt is appended to: id|title|upload_date|view_count|duration"""
    by_id: dict[str, dict] = {}
    if not META_FILE.exists():
        return by_id
    for line in META_FILE.read_text(errors="ignore").splitlines():
        parts = line.split("|")
        if len(parts) < 5: continue
        vid = parts[0].strip()
        if not vid or vid == "NA": continue
        # title may itself contain |, so glue middle parts back
        # actually since fields are id|title|date|views|duration, we can rsplit on last 3
        if len(parts) > 5:
            # title contained |, so pieces 1..-3 form the title
            vid = parts[0].strip()
            duration = parts[-1].strip()
            view_count = parts[-2].strip()
            upload_date = parts[-3].strip()
            title = "|".join(parts[1:-3]).strip()
        else:
            vid, title, upload_date, view_count, duration = parts
        by_id[vid] = {
            "title": title.strip(),
            "upload_date": upload_date.strip(),
            "view_count": view_count.strip(),
            "duration": duration.strip(),
        }
    return by_id

def upload_date_to_unix(d: str) -> int | None:
    if not d or d == "NA" or len(d) != 8: return None
    try:
        from datetime import datetime, timezone
        return int(datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc).timestamp())
    except Exception:
        return None

# ----- chunking -----

def chunk_text(text: str, target_size: int = 4000, overlap: int = 200) -> list[str]:
    """
    Split a long transcript into ~target_size-char chunks with small overlap.

    Boundary preference:
      1. Speaker change (">>")
      2. Paragraph break ("\n\n")
      3. Sentence end (". ")
      4. Word boundary (" ")

    Overlap: last `overlap` chars of chunk N appear at start of chunk N+1 so
    concepts spanning the boundary are still retrievable.
    """
    if len(text) <= target_size:
        return [text] if text.strip() else []

    chunks: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + target_size, n)
        if end >= n:
            chunks.append(text[pos:].strip())
            break
        # Look back from end for a good split point
        window = text[pos:end]
        # Prefer speaker change near end
        split_rel = window.rfind(">>")
        if split_rel < target_size * 0.6:  # too far back, try next
            split_rel = window.rfind("\n\n")
            if split_rel < target_size * 0.6:
                split_rel = window.rfind(". ")
                if split_rel < target_size * 0.6:
                    split_rel = window.rfind(" ")
                else:
                    split_rel += 2  # past the ". "
        if split_rel <= 0:
            split_rel = target_size
        chunk = text[pos:pos + split_rel].strip()
        if chunk:
            chunks.append(chunk)
        # advance with overlap
        pos = pos + split_rel - overlap
        if pos <= 0:
            pos = split_rel  # shouldn't happen but safety
    return [c for c in chunks if len(c) >= 100]

# ----- main -----

def main() -> None:
    if not SRT_DIR.exists():
        print(f"SRT dir not found: {SRT_DIR}")
        return
    metadata = load_metadata()
    print(f"Metadata for {len(metadata)} videos loaded")

    # Group SRTs by video id, prefer en-orig > en > en-en-US
    files_by_id: dict[str, dict[str, Path]] = {}
    for f in SRT_DIR.glob("*.srt"):
        # filename: YYYYMMDD_VIDEOID.LANGTAG.srt or YYYYMMDD_VIDEOID.srt
        name = f.name
        # extract video id
        m = re.match(r"^(\d{8})_([A-Za-z0-9_-]{11})\.(.+)\.srt$", name)
        if not m:
            m = re.match(r"^(?:NA|\d{8})_([A-Za-z0-9_-]{11})\.srt$", name)
            if m:
                vid = m.group(1)
                files_by_id.setdefault(vid, {})["default"] = f
            continue
        vid = m.group(2)
        lang = m.group(3)
        files_by_id.setdefault(vid, {})[lang] = f

    print(f"Found SRTs for {len(files_by_id)} unique videos")

    # check which videos are already chunked in DB (by source_url, since chunks
    # share the same URL but have different source_ids like yt-VID-chunk-0..N)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    existing_urls = set(r["source_url"] for r in conn.execute(
        "SELECT DISTINCT source_url FROM passages WHERE voice = ? AND kind = 'youtube_transcript'",
        ("paulsaladinomd",)
    ).fetchall())
    print(f"Already in DB: {len(existing_urls)} Saladino video URLs (across all chunks)")

    videos_processed = 0
    chunks_inserted = 0
    skipped_short = 0
    skipped_existing = 0
    now = int(time.time())

    for vid, files in files_by_id.items():
        url = f"https://www.youtube.com/watch?v={vid}"
        if url in existing_urls:
            skipped_existing += 1
            continue
        # prefer en-orig, then en, then en-en-US, then anything
        srt = files.get("en-orig") or files.get("en") or files.get("en-en-US") or files.get("default") or next(iter(files.values()))
        try:
            text = parse_srt_to_text(srt)
        except Exception as e:
            print(f"  parse error {vid}: {e}", file=sys.stderr)
            continue
        if len(text) < 200:
            skipped_short += 1
            continue
        meta = metadata.get(vid, {})
        title = meta.get("title", f"Saladino video {vid}")
        upload = upload_date_to_unix(meta.get("upload_date", ""))
        full_text = f"{title}\n\n{text}"
        # chunk
        pieces = chunk_text(full_text, target_size=4000, overlap=200)
        for i, piece in enumerate(pieces):
            chunk_sid = f"yt-{vid}-chunk-{i}"
            # Add chunk metadata header so it's clear which episode this came from
            chunk_text_with_header = (
                f"[{title} — part {i+1}/{len(pieces)}]\n\n{piece}"
                if i > 0  # first chunk already has the title from full_text
                else piece
            )
            try:
                conn.execute("""INSERT OR IGNORE INTO passages
                                (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                                VALUES (?, ?, ?, ?, ?, ?, 'youtube_transcript')""",
                             ("paulsaladinomd", chunk_sid, url, chunk_text_with_header, upload, now))
                if conn.total_changes > 0:
                    chunks_inserted += 1
            except sqlite3.Error as e:
                print(f"  db error {vid} chunk {i}: {e}", file=sys.stderr)
        videos_processed += 1

    conn.commit()

    # tally
    total = conn.execute("SELECT COUNT(*) AS n FROM passages").fetchone()["n"]
    sal_yt = conn.execute(
        "SELECT COUNT(*) AS n FROM passages WHERE voice='paulsaladinomd' AND kind='youtube_transcript'"
    ).fetchone()["n"]
    sal_total = conn.execute("SELECT COUNT(*) AS n FROM passages WHERE voice='paulsaladinomd'").fetchone()["n"]
    sal_videos = conn.execute(
        "SELECT COUNT(DISTINCT source_url) AS n FROM passages WHERE voice='paulsaladinomd' AND kind='youtube_transcript'"
    ).fetchone()["n"]
    conn.close()

    print()
    print(f"  videos processed: {videos_processed}")
    print(f"  chunks inserted: {chunks_inserted}")
    print(f"  skipped (already in DB): {skipped_existing}")
    print(f"  skipped (too short): {skipped_short}")
    print()
    print(f"Saladino unique videos: {sal_videos}")
    print(f"Saladino YouTube chunks: {sal_yt}")
    print(f"Saladino total passages: {sal_total}")
    print(f"Council total passages: {total}")


if __name__ == "__main__":
    main()
