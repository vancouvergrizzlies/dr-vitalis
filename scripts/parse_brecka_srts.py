#!/usr/bin/env python3
"""
Parse Brecka SRT files into DB chunks. Same logic as parse_saladino_srts.py
but targeting voice='thegarybrecka' from /tmp/dv_transcripts/brecka/.
"""
from __future__ import annotations
import os, re, sqlite3, time, sys
from pathlib import Path

DB = Path.home() / ".dr-vitalis" / "council.db"
SRT_DIR = Path("/tmp/dv_transcripts/brecka")
META_FILE = SRT_DIR / "_metadata.txt"

INDEX_RE = re.compile(r"^\d+$")
TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}")

def parse_srt_to_text(path: Path) -> str:
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
            if line.startswith("[") and line.endswith("]"): continue
            if line in prev_lines: continue
            out.append(line)
        prev_lines = set(block)
    return re.sub(r"\s+", " ", " ".join(out)).strip()

def chunk_text(text: str, target_size: int = 4000, overlap: int = 200) -> list[str]:
    if len(text) <= target_size:
        return [text] if text.strip() else []
    chunks: list[str] = []
    pos, n = 0, len(text)
    while pos < n:
        end = min(pos + target_size, n)
        if end >= n:
            chunks.append(text[pos:].strip())
            break
        window = text[pos:end]
        split_rel = window.rfind(">>")
        if split_rel < target_size * 0.6:
            split_rel = window.rfind("\n\n")
            if split_rel < target_size * 0.6:
                split_rel = window.rfind(". ")
                if split_rel < target_size * 0.6:
                    split_rel = window.rfind(" ")
                else:
                    split_rel += 2
        if split_rel <= 0:
            split_rel = target_size
        chunk = text[pos:pos + split_rel].strip()
        if chunk:
            chunks.append(chunk)
        pos = pos + split_rel - overlap
    return [c for c in chunks if len(c) >= 100]

def upload_date_to_unix(d: str) -> int | None:
    if not d or d == "NA" or len(d) != 8: return None
    try:
        from datetime import datetime, timezone
        return int(datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc).timestamp())
    except Exception:
        return None

def load_metadata() -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    if not META_FILE.exists():
        return by_id
    for line in META_FILE.read_text(errors="ignore").splitlines():
        parts = line.split("|")
        if len(parts) < 5: continue
        vid = parts[0].strip()
        if not vid or vid == "NA": continue
        if len(parts) > 5:
            duration = parts[-1].strip()
            view_count = parts[-2].strip()
            upload_date = parts[-3].strip()
            title = "|".join(parts[1:-3]).strip()
        else:
            _, title, upload_date, view_count, duration = parts
        by_id[vid] = {"title": title.strip(), "upload_date": upload_date.strip()}
    return by_id

def main() -> None:
    if not SRT_DIR.exists():
        print(f"SRT dir not found: {SRT_DIR}"); return
    metadata = load_metadata()
    print(f"Brecka metadata for {len(metadata)} videos")

    files_by_id: dict[str, dict[str, Path]] = {}
    for f in SRT_DIR.glob("*.srt"):
        m = re.match(r"^(?:NA|\d{8})_([A-Za-z0-9_-]{11})\.(.+)\.srt$", f.name)
        if not m: continue
        vid = m.group(1); lang = m.group(2)
        files_by_id.setdefault(vid, {})[lang] = f

    print(f"Brecka SRTs for {len(files_by_id)} unique videos")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    existing_urls = set(r["source_url"] for r in conn.execute(
        "SELECT DISTINCT source_url FROM passages WHERE voice='thegarybrecka' AND kind='youtube_transcript'"
    ).fetchall())
    print(f"Already in DB: {len(existing_urls)} Brecka video URLs")

    videos_p = 0; chunks_i = 0; skipped = 0
    now = int(time.time())
    for vid, files in files_by_id.items():
        url = f"https://www.youtube.com/watch?v={vid}"
        if url in existing_urls:
            skipped += 1; continue
        srt = files.get("en-orig") or files.get("en") or files.get("en-en-US") or next(iter(files.values()))
        try:
            text = parse_srt_to_text(srt)
        except Exception:
            continue
        if len(text) < 200: continue
        meta = metadata.get(vid, {})
        title = meta.get("title", f"Brecka video {vid}")
        upload = upload_date_to_unix(meta.get("upload_date", ""))
        full_text = f"{title}\n\n{text}"
        pieces = chunk_text(full_text, 4000, 200)
        for i, piece in enumerate(pieces):
            sid = f"yt-brecka-{vid}-chunk-{i}"
            t = f"[{title} — part {i+1}/{len(pieces)}]\n\n{piece}" if i > 0 else piece
            try:
                conn.execute("""INSERT OR IGNORE INTO passages
                                (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                                VALUES (?, ?, ?, ?, ?, ?, 'youtube_transcript')""",
                             ("thegarybrecka", sid, url, t, upload, now))
                if conn.total_changes > 0:
                    chunks_i += 1
            except sqlite3.Error: pass
        videos_p += 1
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    brecka = conn.execute("SELECT COUNT(*) FROM passages WHERE voice='thegarybrecka'").fetchone()[0]
    brecka_v = conn.execute("SELECT COUNT(DISTINCT source_url) FROM passages WHERE voice='thegarybrecka' AND kind='youtube_transcript'").fetchone()[0]
    conn.close()
    print(f"\nProcessed {videos_p} videos, inserted {chunks_i} chunks (skipped {skipped} already-done)")
    print(f"Brecka: {brecka_v} videos / {brecka} passages")
    print(f"Council total: {total} passages")

if __name__ == "__main__":
    main()
