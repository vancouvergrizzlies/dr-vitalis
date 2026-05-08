#!/usr/bin/env python3
"""Parse O'Neill SRT files into council DB chunks. (Same logic as Brecka parser.)"""
from __future__ import annotations
import re, sqlite3, time, sys
from pathlib import Path

DB = Path.home() / ".dr-vitalis" / "council.db"
SRT_DIR = Path("/tmp/dv_transcripts/oneill")
META_FILE = SRT_DIR / "_metadata.txt"
VOICE = "BarbaraOneillAU"

INDEX_RE = re.compile(r"^\d+$")
TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}")

def parse_srt_to_text(path):
    lines = path.read_text(errors="ignore").splitlines()
    blocks, cur = [], []
    for line in lines:
        s = line.strip()
        if not s:
            if cur: blocks.append(cur); cur = []
            continue
        if INDEX_RE.match(s) or TS_RE.match(s): continue
        cur.append(s)
    if cur: blocks.append(cur)
    out, prev = [], set()
    for block in blocks:
        for line in block:
            if line.startswith("[") and line.endswith("]"): continue
            if line in prev: continue
            out.append(line)
        prev = set(block)
    return re.sub(r"\s+", " ", " ".join(out)).strip()

def chunk_text(text, target=4000, overlap=200):
    if len(text) <= target: return [text] if text.strip() else []
    chunks, pos, n = [], 0, len(text)
    while pos < n:
        end = min(pos + target, n)
        if end >= n: chunks.append(text[pos:].strip()); break
        window = text[pos:end]
        sp = window.rfind(">>")
        if sp < target * 0.6:
            sp = window.rfind(". ")
            if sp < target * 0.6: sp = window.rfind(" ")
            else: sp += 2
        if sp <= 0: sp = target
        chunk = text[pos:pos + sp].strip()
        if chunk: chunks.append(chunk)
        pos = pos + sp - overlap
    return [c for c in chunks if len(c) >= 100]

def upload_to_unix(d):
    if not d or d == "NA" or len(d) != 8: return None
    try:
        from datetime import datetime, timezone
        return int(datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc).timestamp())
    except: return None

def load_metadata():
    by_id = {}
    if not META_FILE.exists(): return by_id
    for line in META_FILE.read_text(errors="ignore").splitlines():
        parts = line.split("|")
        if len(parts) < 5: continue
        vid = parts[0].strip()
        if not vid or vid == "NA": continue
        if len(parts) > 5:
            duration = parts[-1].strip(); view = parts[-2].strip()
            upload = parts[-3].strip(); title = "|".join(parts[1:-3]).strip()
        else:
            _, title, upload, view, duration = parts
        by_id[vid] = {"title": title.strip(), "upload_date": upload.strip()}
    return by_id

def main():
    metadata = load_metadata()
    files_by_id = {}
    for f in SRT_DIR.glob("*.srt"):
        m = re.match(r"^(?:NA|\d{8})_([A-Za-z0-9_-]{11})\.(.+)\.srt$", f.name)
        if not m: continue
        files_by_id.setdefault(m.group(1), {})[m.group(2)] = f

    print(f"O'Neill: {len(files_by_id)} unique videos with SRTs, {len(metadata)} with metadata")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    existing = set(r["source_url"] for r in conn.execute(
        f"SELECT DISTINCT source_url FROM passages WHERE voice='{VOICE}' AND kind='youtube_transcript'"
    ).fetchall())
    print(f"Already in DB: {len(existing)} O'Neill video URLs")

    videos_p, chunks_i = 0, 0
    now = int(time.time())
    for vid, files in files_by_id.items():
        url = f"https://www.youtube.com/watch?v={vid}"
        if url in existing: continue
        srt = files.get("en-orig") or files.get("en") or next(iter(files.values()))
        text = parse_srt_to_text(srt)
        if len(text) < 200: continue
        meta = metadata.get(vid, {})
        title = meta.get("title", f"O'Neill video {vid}")
        upload = upload_to_unix(meta.get("upload_date", ""))
        full = f"{title}\n\n{text}"
        pieces = chunk_text(full, 4000, 200)
        for i, p in enumerate(pieces):
            sid = f"yt-oneill-{vid}-chunk-{i}"
            t = f"[{title} — part {i+1}/{len(pieces)}]\n\n{p}" if i > 0 else p
            try:
                conn.execute("""INSERT OR IGNORE INTO passages
                                (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                                VALUES (?, ?, ?, ?, ?, ?, 'youtube_transcript')""",
                             (VOICE, sid, url, t, upload, now))
                if conn.total_changes > 0: chunks_i += 1
            except sqlite3.Error: pass
        videos_p += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    oneill = conn.execute(f"SELECT COUNT(*) FROM passages WHERE voice='{VOICE}'").fetchone()[0]
    print(f"\nProcessed {videos_p} videos, inserted {chunks_i} chunks")
    print(f"O'Neill total: {oneill} passages")
    print(f"Council total: {total}")
    conn.close()

if __name__ == "__main__":
    main()
