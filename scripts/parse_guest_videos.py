#!/usr/bin/env python3
"""
Parse specific YouTube videos as content for a designated voice (e.g. when
they're a guest on someone else's podcast). Maps video IDs → voice handle.

Usage: edit VIDEO_TO_VOICE then run.
"""
from __future__ import annotations
import re, sqlite3, time, sys
from pathlib import Path

DB = Path.home() / ".dr-vitalis" / "council.db"
SRT_DIR = Path("/tmp/dv_transcripts/grimhood_guest")
META_FILE = SRT_DIR / "_metadata.txt"

# video_id -> voice (the SPEAKER who matters for the council)
VIDEO_TO_VOICE = {
    "EkRizVrLx6k": "Grimhood",       # Arthaus #15 with Grimhood
    "xiZW1lxP3J4": "Grimhood",       # Tristan Scott + Grimhood
    "3znhwCGDdUY": "BioavailableNd", # Andra on Mitolife Radio
}

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
                blocks.append(cur); cur = []
            continue
        if INDEX_RE.match(s) or TS_RE.match(s): continue
        cur.append(s)
    if cur: blocks.append(cur)
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
            chunks.append(text[pos:].strip()); break
        window = text[pos:end]
        split_rel = window.rfind(">>")
        if split_rel < target_size * 0.6:
            split_rel = window.rfind(". ")
            if split_rel < target_size * 0.6:
                split_rel = window.rfind(" ")
            else:
                split_rel += 2
        if split_rel <= 0:
            split_rel = target_size
        chunk = text[pos:pos + split_rel].strip()
        if chunk: chunks.append(chunk)
        pos = pos + split_rel - overlap
    return [c for c in chunks if len(c) >= 100]

def upload_date_to_unix(d: str) -> int | None:
    if not d or d == "NA" or len(d) != 8: return None
    try:
        from datetime import datetime, timezone
        return int(datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc).timestamp())
    except Exception: return None

def load_metadata() -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    if not META_FILE.exists(): return by_id
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
    metadata = load_metadata()
    print(f"Metadata for {len(metadata)} videos: {list(metadata.keys())}")

    files_by_id: dict[str, dict[str, Path]] = {}
    for f in SRT_DIR.glob("*.srt"):
        m = re.match(r"^(?:NA|\d{8})_([A-Za-z0-9_-]{11})\.(.+)\.srt$", f.name)
        if not m: continue
        vid = m.group(1); lang = m.group(2)
        files_by_id.setdefault(vid, {})[lang] = f

    print(f"SRTs for {len(files_by_id)} videos\n")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = int(time.time())
    total_chunks = 0

    for vid, voice in VIDEO_TO_VOICE.items():
        files = files_by_id.get(vid)
        if not files:
            print(f"  ! no SRTs for {vid}, skip")
            continue
        srt = files.get("en-orig") or files.get("en") or next(iter(files.values()))
        text = parse_srt_to_text(srt)
        if len(text) < 200:
            print(f"  ! {vid} too short, skip"); continue
        meta = metadata.get(vid, {})
        title = meta.get("title", f"video {vid}")
        upload = upload_date_to_unix(meta.get("upload_date", ""))
        url = f"https://www.youtube.com/watch?v={vid}"
        full_text = f"{title}\n\n{text}"
        chunks = chunk_text(full_text, 4000, 200)
        n = 0
        for i, piece in enumerate(chunks):
            sid = f"yt-guest-{vid}-chunk-{i}"
            t = f"[{title} — part {i+1}/{len(chunks)}]\n\n{piece}" if i > 0 else piece
            try:
                conn.execute("""INSERT OR IGNORE INTO passages
                                (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                                VALUES (?, ?, ?, ?, ?, ?, 'youtube_transcript')""",
                             (voice, sid, url, t, upload, now))
                if conn.total_changes > 0: n += 1
            except sqlite3.Error: pass
        total_chunks += n
        print(f"  + {vid} -> @{voice}: {len(chunks)} chunks, {n} new ({title[:50]}...)")
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    print(f"\nInserted {total_chunks} new chunks")
    print(f"Council total: {total}")
    print()
    rows = conn.execute("SELECT voice, COUNT(*) AS n FROM passages GROUP BY voice ORDER BY n DESC").fetchall()
    for r in rows:
        print(f"  @{r['voice']:<22} {r['n']:>5}")
    conn.close()

if __name__ == "__main__":
    main()
