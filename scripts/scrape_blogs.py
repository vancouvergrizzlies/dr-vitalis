#!/usr/bin/env python3
"""
Multi-blog scraper for the Dr. Vitalis council. Pulls from:
  - haidut.me (Georgi Dinkov - bioenergetics)
  - draxe.com (Josh Axe - natural medicine)
  - bengreenfieldlife.com (Ben Greenfield - biohacking)

Each site: find sitemap/index → fetch each post → extract main content → DB.
"""
from __future__ import annotations
import re, sqlite3, time, html, sys
from pathlib import Path
import httpx

DB = Path.home() / ".dr-vitalis" / "council.db"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
ARTICLE_RE = re.compile(r"<article[^>]*>(.*?)</article>", re.IGNORECASE | re.DOTALL)
ENTRY_CONTENT_RE = re.compile(r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)(?=<footer|<div class="entry-footer|<div class="comments|</main|</article)', re.IGNORECASE | re.DOTALL)
POST_CONTENT_RE = re.compile(r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)(?=<footer|</main|</article)', re.IGNORECASE | re.DOTALL)
MAIN_RE = re.compile(r"<main[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL)

UA = "Mozilla/5.0 (compatible; dr-vitalis-bot/0.1; personal health AI corpus)"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}

def strip_html(s: str) -> str:
    if not s: return ""
    s = re.sub(r"<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = WS_RE.sub(" ", s).strip()
    return s

def insert_passage(voice: str, source_id: str, url: str, text: str, posted_at, kind: str) -> bool:
    if not text or len(text) < 200:
        return False
    if len(text) > 50000:
        text = text[:50000] + " [...]"
    now = int(time.time())
    c = sqlite3.connect(DB)
    try:
        cur = c.execute("""INSERT OR IGNORE INTO passages
                           (voice, source_id, source_url, text, posted_at, fetched_at, kind)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (voice, source_id, url, text, posted_at, now, kind))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()

def get_sitemap_urls(domain: str, paths_filter: callable) -> set[str]:
    """Crawl sitemaps to extract content URLs matching the filter."""
    seen_sm = set()
    out: set[str] = set()
    queue = [
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"https://{domain}/wp-sitemap.xml",
    ]
    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as cli:
        while queue:
            sm = queue.pop(0)
            if sm in seen_sm:
                continue
            seen_sm.add(sm)
            try:
                r = cli.get(sm)
                if r.status_code != 200:
                    continue
                for u in re.findall(r"<loc>([^<]+)</loc>", r.text):
                    if any(s in u for s in ("sitemap", ".xml")):
                        if u not in seen_sm:
                            queue.append(u)
                    elif paths_filter(u):
                        out.add(u)
            except Exception as e:
                print(f"  ! sitemap {sm}: {e}", file=sys.stderr)
    return out

def extract_post_body(html_text: str) -> str:
    """Extract the main article body."""
    for pattern in (ENTRY_CONTENT_RE, POST_CONTENT_RE, ARTICLE_RE, MAIN_RE):
        m = pattern.search(html_text)
        if m:
            body = strip_html(m.group(1))
            if len(body) > 300:
                return body
    return strip_html(html_text)

def extract_title(html_text: str) -> str:
    m = TITLE_RE.search(html_text)
    return strip_html(m.group(1)) if m else ""

def scrape_site(domain: str, voice: str, url_filter: callable, max_posts: int = 200) -> int:
    print(f"\n=== Scraping {domain} -> @{voice} ===")
    urls = get_sitemap_urls(domain, url_filter)
    print(f"  Found {len(urls)} candidate URLs")
    n = 0
    skipped = 0
    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as cli:
        for i, url in enumerate(sorted(urls)[:max_posts]):
            if i and i % 25 == 0:
                print(f"  ... {i} processed, {n} indexed")
            try:
                r = cli.get(url)
                if r.status_code != 200:
                    skipped += 1
                    continue
                title = extract_title(r.text)
                body = extract_post_body(r.text)
                if len(body) < 300:
                    skipped += 1
                    continue
                full = f"{title}\n\n{body}"
                if insert_passage(voice, url, url, full, None, "blog"):
                    n += 1
                time.sleep(0.25)
            except Exception as e:
                skipped += 1
    print(f"  + {n} posts indexed ({skipped} skipped)")
    return n

# === Targets ===

def haidut_filter(u: str) -> bool:
    # haidut.me posts are under /YYYY/MM/DD/slug/ paths
    return "haidut.me/" in u and re.search(r"/\d{4}/", u) is not None

def draxe_filter(u: str) -> bool:
    # draxe.com articles often have /<slug>/ paths but skip categories/tags/products
    skip = ("/category/", "/tag/", "/author/", "/page/", "/products/", "/shop/", "/recipes/", "/podcast/", "/about", "/contact", "/wp-content/")
    return ("draxe.com/" in u and u.endswith("/")
            and not any(x in u for x in skip)
            and len(u.replace("https://draxe.com/", "")) > 5)

def greenfield_filter(u: str) -> bool:
    skip = ("/category/", "/tag/", "/author/", "/page/", "/products/", "/shop/", "/about", "/contact", "/podcast-episode-", "/wp-content/")
    return ("bengreenfieldlife.com/" in u
            and not any(x in u for x in skip))

if __name__ == "__main__":
    n_haidut = scrape_site("haidut.me", "haidut", haidut_filter, max_posts=200)
    n_axe = scrape_site("draxe.com", "DrJoshAxe", draxe_filter, max_posts=200)
    n_green = scrape_site("bengreenfieldlife.com", "bengreenfield", greenfield_filter, max_posts=200)

    # Tally
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT voice, COUNT(*) AS n FROM passages GROUP BY voice ORDER BY n DESC""").fetchall()
    total = c.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    print(f"\n=== TALLY ({total} total passages) ===")
    for r in rows:
        print(f"  @{r['voice']:<22} {r['n']:>5}")
    c.close()
