#!/usr/bin/env python3
"""analyze_gaps.py — Surface knowledge gaps in the Dr. Vitalis council corpus.

Reads query_log + passages from ~/.dr-vitalis/council.db (or $COUNCIL_DB_PATH)
and reports:
  - Topical clusters where coverage is thin (few voices, low diversity)
  - Topics dominated by a single voice (need triangulation)
  - Strong clusters (no action needed)
  - Suggested voices/sources to add

Pure stdlib. Markdown to stdout by default. --html writes an HTML fragment.

Calibrated thresholds: nothing is hard-coded. We compute corpus medians for
voice-diversity and passage-substance and flag clusters that fall below the
median by 1 standard deviation. Adapts as the corpus grows.

Usage:
  python3 analyze_gaps.py
  python3 analyze_gaps.py --html         # emit HTML fragment instead of markdown
  python3 analyze_gaps.py --json         # emit machine-readable JSON
  python3 analyze_gaps.py --min-queries 20  # require N queries before clustering
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("COUNCIL_DB_PATH", str(Path.home() / ".dr-vitalis" / "council.db")))

# Common English stopwords + health-domain filler words that don't help cluster topics
STOP = set("""
a an and are as at be because been but by can could do does for from had has have
he her his how i if in into is it its just like me my no nor not of off on once
only or other our out over own she should so some such than that the their them
then there these they this those through to too under up upon us very was we were
what when where which while who whom why will with would you your yours
about above after again against all am any before below being both did doing down
during each few further here him himself however itself more most myself ours
ourselves same self sham than themselves until what's whens whose
get got know let like long make many much new now old one see take well want way

ask asking advice question questions help my im i'm i've you you've
something thing things stuff really
""".split())

DOMAIN_HINTS = {
    # When a cluster's dominant keywords match these patterns, suggest the named voice category
    r"hormon|estrog|progester|menstrua|menopaus|perimenopau|cycle|fertility|pcos|endometr": "women's-health / hormone specialist (e.g. Mindy Pelz, Anna Cabeca, Lara Briden)",
    r"ayurved|dosha|vata|pitta|kapha": "ayurvedic practitioner",
    r"tcm|acupunct|qi |meridian|traditional chinese": "TCM / acupuncture voice",
    r"mold|mycotoxin|biotoxin|cirs": "mold-illness specialist (e.g. Crista Hannan, Jill Crista)",
    r"herb|tincture|infusion|decoction|apothecary|materia medica": "deeper herbal apothecary voice (e.g. Stephen Buhner, Rosemary Gladstar)",
    r"child|kid|toddler|pediatric|baby|infant": "pediatric / child-health voice",
    r"pregnan|prenatal|postpartum|breastfeed": "pregnancy / postpartum specialist",
    r"trauma|ptsd|nervous system|polyvagal|somatic": "nervous-system / trauma-resolution voice",
    r"mental health|depress|anxiety|bipolar|schizophren": "psychiatric / mental-health voice",
    r"dental|tooth|cavity|gum |periodonta|root canal": "biological dentist voice",
    r"sleep|insomnia|circadian|melatonin": "sleep specialist (already partial via Saladino, but a dedicated sleep voice would deepen)",
    r"autoimmun|hashimoto|lupus|rheumatoid|crohn|colitis|ms |multiple sclerosis": "autoimmune protocol specialist (e.g. Terry Wahls, Mickey Trescott)",
}


# ---------- IO helpers ----------

def load_queries(con):
    cur = con.execute("SELECT id, query, result_ids, created_at FROM query_log ORDER BY created_at")
    out = []
    for row in cur.fetchall():
        try:
            ids = json.loads(row[2]) if row[2] else []
        except (json.JSONDecodeError, TypeError):
            ids = []
        out.append({
            "id": row[0],
            "text": row[1] or "",
            "result_ids": ids,
            "created_at": row[3],
        })
    return out


def load_passages(con, ids):
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    cur = con.execute(
        f"SELECT id, voice, LENGTH(text) AS L FROM passages WHERE id IN ({placeholders})",
        ids,
    )
    return [{"id": r[0], "voice": r[1], "length": r[2]} for r in cur.fetchall()]


def load_voices(con):
    cur = con.execute("SELECT handle, display, weight FROM voices")
    return {r[0]: {"display": r[1], "weight": r[2]} for r in cur.fetchall()}


# ---------- analysis ----------

def per_query_metrics(query, passages):
    """Return diversity metrics for one query's retrieved passages."""
    if not passages:
        return {
            "distinct_voices": 0,
            "top_k": 0,
            "voices_present": [],
            "top_voice": None,
            "top_voice_share": 0.0,
            "avg_length": 0.0,
        }
    voice_counts = Counter(p["voice"] for p in passages)
    top_voice, top_count = voice_counts.most_common(1)[0]
    return {
        "distinct_voices": len(voice_counts),
        "top_k": len(passages),
        "voices_present": list(voice_counts.keys()),
        "top_voice": top_voice,
        "top_voice_share": top_count / len(passages),
        "avg_length": statistics.mean(p["length"] for p in passages),
    }


def keywords(text, k=4):
    """Extract top-k content words for clustering."""
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", (text or "").lower())
    words = [w for w in words if w not in STOP and len(w) > 3]
    return [w for w, _ in Counter(words).most_common(k)]


def cluster_queries(queries):
    """Group queries that share at least one top-keyword. Simple but transparent."""
    # Map keyword -> list of query indices
    kw_to_queries = defaultdict(set)
    query_kws = []
    for i, q in enumerate(queries):
        kws = keywords(q["text"])
        query_kws.append(kws)
        for kw in kws:
            kw_to_queries[kw].add(i)

    # Greedy clustering: each query joins the cluster of its highest-frequency keyword
    seen = set()
    clusters = []
    for i, q in enumerate(queries):
        if i in seen:
            continue
        kws = query_kws[i]
        if not kws:
            continue
        best_kw = max(kws, key=lambda kw: len(kw_to_queries[kw]))
        members = sorted(kw_to_queries[best_kw])
        cluster = {"keyword": best_kw, "all_keywords": [], "queries": []}
        all_kws = Counter()
        for j in members:
            if j in seen:
                continue
            seen.add(j)
            cluster["queries"].append(queries[j])
            all_kws.update(query_kws[j])
        cluster["all_keywords"] = [w for w, _ in all_kws.most_common(5)]
        if cluster["queries"]:
            clusters.append(cluster)
    return clusters


def calibrate_thresholds(per_query):
    """Compute median + std for diversity metrics across all queries."""
    if len(per_query) < 2:
        return None
    diversities = [m["distinct_voices"] for m in per_query]
    shares = [m["top_voice_share"] for m in per_query]
    return {
        "median_diversity": statistics.median(diversities),
        "stdev_diversity": statistics.stdev(diversities) if len(diversities) > 1 else 0,
        "median_top_share": statistics.median(shares),
    }


def suggest_voice(cluster):
    """Heuristic: match cluster keywords against domain hints."""
    text = " ".join([cluster["keyword"]] + cluster["all_keywords"]).lower()
    for pattern, suggestion in DOMAIN_HINTS.items():
        if re.search(pattern, text):
            return suggestion
    return None


# ---------- rendering ----------

def render_markdown(report):
    out = []
    out.append("# Dr. Vitalis — Knowledge Gaps Report\n")
    out.append(f"_Based on {report['total_queries']} council queries._\n")

    if report["mode"] == "tracking":
        out.append("\n## Tracking mode\n")
        out.append(
            f"Need at least {report['min_queries']} queries before clustering surfaces "
            f"meaningful patterns. You have {report['total_queries']} so far. Keep using "
            "Dr. Vitalis — once you cross the threshold, this report will start showing "
            "topical weaknesses and recommending voices to add.\n"
        )
        if report["per_query"]:
            out.append("\n### Per-query coverage so far\n")
            out.append("| Query | Voices | Top voice | Top share |")
            out.append("|---|---|---|---|")
            for q, m in zip(report["queries"], report["per_query"]):
                txt = (q["text"][:60] + "…") if len(q["text"]) > 60 else q["text"]
                out.append(
                    f"| {txt} | {m['distinct_voices']} | "
                    f"{m['top_voice'] or '—'} | {m['top_voice_share']:.0%} |"
                )
        return "\n".join(out)

    # full report mode
    weak = [c for c in report["clusters"] if c["status"] == "weak"]
    single = [c for c in report["clusters"] if c["status"] == "single_voice"]
    strong = [c for c in report["clusters"] if c["status"] == "strong"]

    out.append(f"\n## 🔴 Weak coverage ({len(weak)})\n")
    if not weak:
        out.append("_None — your corpus is holding up well across the topics you've asked about._\n")
    for c in weak:
        kw = ", ".join(c["all_keywords"])
        out.append(f"### {c['keyword']} ({len(c['queries'])} queries)")
        out.append(f"- Keywords: {kw}")
        out.append(f"- Avg distinct voices: {c['avg_diversity']:.1f}")
        if c.get("suggestion"):
            out.append(f"- **Suggested addition:** {c['suggestion']}")
        out.append("")

    out.append(f"\n## 🟡 Single-voice clusters ({len(single)})\n")
    for c in single:
        kw = ", ".join(c["all_keywords"])
        out.append(f"### {c['keyword']} ({len(c['queries'])} queries)")
        out.append(f"- Keywords: {kw}")
        out.append(f"- Dominant voice: **{c['dominant_voice']}** ({c['top_share']:.0%} of matches)")
        out.append(f"- Add a 2nd voice in this domain for triangulation.")
        out.append("")

    out.append(f"\n## 🟢 Strong coverage ({len(strong)})\n")
    if strong:
        kws = ", ".join(c["keyword"] for c in strong[:8])
        out.append(f"_{kws}{' …' if len(strong) > 8 else ''}_\n")

    return "\n".join(out)


def render_html(report):
    md = render_markdown(report)
    # extremely simple md→html (just enough for embedding in dashboard)
    html = ["<style>",
            ".gaps h1{font-size:1.4em;margin:0.5em 0}.gaps h2{font-size:1.1em;margin:1em 0 0.3em;border-bottom:1px solid #eee;padding-bottom:0.2em}",
            ".gaps h3{font-size:0.95em;margin:0.6em 0 0.2em}",
            ".gaps table{border-collapse:collapse;width:100%;font-size:0.85em}",
            ".gaps th,.gaps td{border:1px solid #ddd;padding:0.3em 0.5em;text-align:left}",
            ".gaps em{color:#666}",
            "</style>",
            "<div class='gaps'>"]
    in_table = False
    for line in md.splitlines():
        if line.startswith("# "):
            html.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            if in_table:
                html.append("</table>"); in_table = False
            html.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            if in_table:
                html.append("</table>"); in_table = False
            html.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("|---"):
            continue
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            tag = "th" if not in_table else "td"
            if not in_table:
                html.append("<table>"); in_table = True
            html.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        elif line.startswith("- "):
            html.append(f"<li>{line[2:]}</li>")
        elif line.startswith("_") and line.endswith("_"):
            html.append(f"<p><em>{line.strip('_')}</em></p>")
        elif line.strip():
            html.append(f"<p>{line}</p>")
    if in_table:
        html.append("</table>")
    html.append("</div>")
    return "\n".join(html)


# ---------- main ----------

def analyze(db_path: Path, min_queries: int = 20):
    con = sqlite3.connect(str(db_path))
    queries = load_queries(con)
    voices = load_voices(con)

    per_query = []
    for q in queries:
        passages = load_passages(con, q["result_ids"])
        per_query.append(per_query_metrics(q, passages))

    report = {
        "db_path": str(db_path),
        "total_queries": len(queries),
        "min_queries": min_queries,
        "queries": queries,
        "per_query": per_query,
        "voices": voices,
    }

    if len(queries) < min_queries:
        report["mode"] = "tracking"
        report["clusters"] = []
        return report

    report["mode"] = "report"
    cal = calibrate_thresholds(per_query)
    report["calibration"] = cal

    clusters = cluster_queries(queries)
    enriched = []
    for c in clusters:
        # Aggregate metrics across cluster members
        member_indices = [queries.index(q) for q in c["queries"] if q in queries]
        member_metrics = [per_query[i] for i in member_indices]
        if not member_metrics:
            continue
        avg_div = statistics.mean(m["distinct_voices"] for m in member_metrics)
        avg_top_share = statistics.mean(m["top_voice_share"] for m in member_metrics)

        # Status: weak < median - 1stdev; single_voice if any query >=70% from one voice; else strong
        thin_threshold = cal["median_diversity"] - cal["stdev_diversity"]
        if avg_div < thin_threshold:
            status = "weak"
        elif avg_top_share >= 0.7:
            status = "single_voice"
        else:
            status = "strong"

        # Find dominant voice across the cluster
        all_voices = Counter()
        for m in member_metrics:
            for v in m["voices_present"]:
                all_voices[v] += 1
        dominant = all_voices.most_common(1)[0][0] if all_voices else None

        enriched.append({
            **c,
            "avg_diversity": avg_div,
            "top_share": avg_top_share,
            "status": status,
            "dominant_voice": dominant,
            "suggestion": suggest_voice(c),
        })
    report["clusters"] = enriched
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB), help="Path to council.db")
    p.add_argument("--html", action="store_true", help="Emit HTML fragment")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.add_argument("--min-queries", type=int, default=20, help="Min queries before clustering")
    args = p.parse_args()

    report = analyze(Path(args.db), args.min_queries)

    if args.json:
        # Strip non-serializable bits
        slim = {k: v for k, v in report.items() if k not in ("queries",)}
        print(json.dumps(slim, indent=2, default=str))
    elif args.html:
        print(render_html(report))
    else:
        print(render_markdown(report))


if __name__ == "__main__":
    main()
