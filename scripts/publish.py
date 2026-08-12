#!/usr/bin/env python3
"""
Publish The Platero Brief: a public daily site built from the daily
intelligence briefs in /Users/jp/jose-cerebro/daily/.

Every run re-renders the WHOLE site from every day that has at least
one core brief: issue pages with anchored headings, an orientation
block, prev/next navigation, a month-grouped archive, and an RSS feed.
Re-rendering everything keeps prev/next links correct as new days
appear, and the render is deterministic: no model in the loop, so the
daily automation can never hallucinate content.

Only the four research briefs are ever published (plus the Monday
landscape scan). Triage and distilled notes are personal and excluded.

Usage:
  python3 scripts/publish.py                  # gate on today (America/Toronto)
  python3 scripts/publish.py --date 2026-08-02  # gate on a specific day
  python3 scripts/publish.py --backfill       # no gate, render all and push
  python3 scripts/publish.py --backfill --no-push

The --date gate exits nonzero if that day lacks the 4 core briefs, so
the daily pipeline retries on its next fire. --backfill skips the gate.
"""
import argparse
import html
import re
import subprocess
import sys
from datetime import datetime, time
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BRAIN_DAILY = Path("/Users/jp/jose-cerebro/daily")
SITE_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = SITE_ROOT / "archive"
BASE = "https://thejoseplatero.github.io/platero-brief/"
TZ = ZoneInfo("America/Toronto")
WPM = 220

# slug -> (display name, css class). Page order is fixed; missing briefs skip.
SECTIONS = [
    ("executive-pulse", "Executive Pulse", "exec"),
    ("practitioner-pulse", "Practitioner Pulse", "prac"),
    ("ai-stack-daily", "AI Stack Daily", "stack"),
    ("markets-signal", "Markets Signal", "mkts"),
    ("landscape-scan", "Landscape Scan", "land"),
]
CORE = {"executive-pulse", "practitioner-pulse", "ai-stack-daily", "markets-signal"}
META_KEYS = ("date:", "type:", "tags:", "related:", "source:", "escalate:")

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,700;1,400'
         '&family=Hanken+Grotesk:wght@400;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">')


# ---------- source handling ----------

def strip_frontmatter(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\A---\s*\n.*?\n---\s*\n?", "", text, flags=re.DOTALL)
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].strip().lower().startswith(META_KEYS):
        i += 1
    if i > 0:
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        text = "\n".join(lines[i:])
    text = re.sub(r"\A#\s+[^\n]+\n+", "", text)  # section chip replaces the H1
    return text.strip()


def normalize_dashes(text: str) -> str:
    # Brand rule: no em dashes anywhere published. Periods, commas, colons.
    text = re.sub(r"\s*—\s*", ", ", text)
    text = re.sub(r"(?<=\w)\s*–\s*(?=\w)", " to ", text)
    return text


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "s"


def md_inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def md_to_html(md: str, anchor_prefix: str):
    """Returns (html, [(anchor_id, heading_text)], word_count)."""
    out, para, in_list, heads = [], [], False, []
    words = len(re.findall(r"\S+", md))

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + md_inline(" ".join(para)) + "</p>")
            para = []

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in md.split("\n"):
        stripped = raw.strip()
        if not stripped:
            flush_para(); close_list()
            continue
        if stripped.startswith("### "):
            flush_para(); close_list()
            out.append("<h3>" + md_inline(stripped[4:]) + "</h3>")
        elif stripped.startswith("## "):
            flush_para(); close_list()
            title = stripped[3:].strip()
            aid = f"{anchor_prefix}-{slugify(title)}"
            heads.append((aid, title))
            out.append(f'<h2 id="{aid}"><a class="anch" href="#{aid}" aria-label="Link to this section">#</a>'
                       + md_inline(title) + "</h2>")
        elif stripped.startswith(("- ", "* ")):
            flush_para()
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append("<li>" + md_inline(stripped[2:]) + "</li>")
        else:
            para.append(stripped)
    flush_para(); close_list()
    return "\n".join(out), heads, words


class Brief:
    def __init__(self, slug, name, css, body_md):
        self.slug, self.name, self.css = slug, name, css
        self.html, self.heads, self.words = md_to_html(body_md, css)
        self.minutes = max(1, round(self.words / WPM))


def load_day(day: str):
    briefs = []
    for slug, name, css in SECTIONS:
        path = BRAIN_DAILY / f"{day}-{slug}.md"
        if slug == "markets-signal" and not path.exists():
            weekly = BRAIN_DAILY / f"{day}-markets-signal-weekly.md"
            if weekly.exists():
                path = weekly
        if not path.exists():
            continue
        body = normalize_dashes(strip_frontmatter(path.read_text(encoding="utf-8")))
        if body:
            briefs.append(Brief(slug, name, css, body))
    return briefs


def all_days():
    days = sorted({m.group(1) for p in BRAIN_DAILY.glob("*.md")
                   if (m := re.match(r"(\d{4}-\d{2}-\d{2})-", p.name))})
    return [d for d in days
            if any((BRAIN_DAILY / f"{d}-{s}.md").exists() for s in CORE)
            or (BRAIN_DAILY / f"{d}-markets-signal-weekly.md").exists()]


# ---------- rendering ----------

def human_date(day: str) -> str:
    return datetime.strptime(day, "%Y-%m-%d").strftime("%A, %B %-d, %Y")


def head_block(title: str, desc: str, canonical: str, css_prefix: str) -> str:
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{html.escape(desc, quote=True)}">
<title>{html.escape(title)}</title>
<link rel="canonical" href="{canonical}">
<link rel="alternate" type="application/rss+xml" title="The Platero Brief" href="{BASE}feed.xml">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(desc, quote=True)}">
{FONTS}
<link rel="stylesheet" href="{css_prefix}assets/brief.css">"""


def top_bar(css_prefix: str, right: str) -> str:
    return f"""<div id="progress"></div>
<header class="top">
  <div class="top-in">
    <a class="wordmark" href="{css_prefix if css_prefix else './'}">The Platero Brief</a>
    <div class="top-meta">{right}</div>
  </div>
</header>"""


def issue_page(day, briefs, issue_no, prev_day, next_day, prev_no, next_no,
               css_prefix, canonical):
    total_words = sum(b.words for b in briefs)
    minutes = max(1, round(total_words / WPM))
    has_land = any(b.slug == "landscape-scan" for b in briefs)
    badge = '<span class="badge">Landscape Scan</span>' if has_land else ""

    toc_rows = "\n".join(
        f'<div class="row"><i style="background:var(--{b.css})"></i><div class="body">'
        f'<a class="name" href="#{b.css}" style="color:var(--{b.css}-t)">{html.escape(b.name)}'
        f'<small>{b.minutes} min</small></a>'
        f'<div class="heads">' +
        '<span class="sep">&middot;</span>'.join(
            f'<a href="#{aid}">{html.escape(t)}</a>' for aid, t in b.heads) +
        "</div></div></div>"
        for b in briefs
    )

    side_items = []
    for b in briefs:
        side_items.append(
            f'<li class="grp"><a href="#{b.css}"><i style="background:var(--{b.css})"></i>{html.escape(b.name)}</a></li>')
        side_items.extend(
            f'<li class="sub"><a href="#{aid}">{html.escape(t)}</a></li>' for aid, t in b.heads)
    sidebar = ('<aside class="side"><div class="side-in">'
               '<p class="side-k">In this issue</p><ul>' + "\n".join(side_items) +
               "</ul></div></aside>")

    body = "\n".join(
        f'<section class="brief {b.css}" id="{b.css}">\n'
        f'<div class="kick"><span class="k">{html.escape(b.name)}</span>'
        f'<span class="wc">{b.words:,} words</span></div>\n'
        f'<div class="rule"></div>\n{b.html}\n</section>'
        for b in briefs
    )

    prev_link = (f'<a class="prev" href="{css_prefix}archive/{prev_day}.html">&larr; No. {prev_no}'
                 f'<b>{human_date(prev_day)}</b></a>') if prev_day else "<span></span>"
    next_link = (f'<a class="next" href="{css_prefix}archive/{next_day}.html">No. {next_no} &rarr;'
                 f'<b>{human_date(next_day)}</b></a>') if next_day else ""

    return f"""<!doctype html>
<html lang="en">
<head>
{head_block(f"The Platero Brief, No. {issue_no}", f"The Platero Brief for {human_date(day)}. {total_words:,} words, {minutes} minute read. Executive, practitioner, AI stack, and markets intelligence.", canonical, css_prefix)}
</head>
<body>
{top_bar(css_prefix, f'<span>{day}</span><a href="{css_prefix}archive/">Archive</a><a href="{BASE}feed.xml">RSS</a>')}
<div class="layout">
{sidebar}
<main>
  <div class="issue-head">
    <p class="no">No. {issue_no}</p>
    <h1>{human_date(day)}{badge}</h1>
    <p class="meta">{total_words:,} words &middot; {minutes} min read</p>
  </div>
  <div class="toc">
    <p class="toc-k">In this issue</p>
{toc_rows}
  </div>
{body}
  <footer class="foot">
    <div class="nav-row">
      {prev_link}
      {next_link}
    </div>
    <p class="fine">Researched and written each morning by the agent pipeline Jose Platero built on his second brain. Curated, not hand-polished. The weekly synthesis with his own take is <a href="https://loopsandletters.substack.com" target="_blank" rel="noopener">Loops &amp; Letters</a>.</p>
    <p class="fine">Jose Platero &middot; <a href="https://joseplatero.com" target="_blank" rel="noopener">joseplatero.com</a> &middot; <a href="{css_prefix}archive/">All issues</a></p>
  </footer>
</main>
</div>
<script src="{css_prefix}assets/brief.js" defer></script>
</body>
</html>
"""


def render_archive_index(rendered):
    """rendered: list of (day, issue_no, briefs) newest first."""
    by_month = {}
    for day, no, briefs in rendered:
        key = day[:7]
        by_month.setdefault(key, []).append((day, no, briefs))

    blocks = []
    for month in sorted(by_month, reverse=True):
        label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
        rows = []
        for day, no, briefs in sorted(by_month[month], reverse=True):
            words = sum(b.words for b in briefs)
            core_n = sum(1 for b in briefs if b.slug in CORE)
            dots = "".join(f'<i style="background:var(--{b.css})"></i>' for b in briefs)
            partial = f" &middot; {core_n} of 4 briefs" if core_n < 4 else ""
            rows.append(
                f'<li><a href="{day}.html"><span class="d">{human_date(day)}</span>'
                f'<span class="m"><span class="dots">{dots}</span>'
                f'<span class="n">No. {no} &middot; {words:,} words{partial}</span></span></a></li>')
        blocks.append(f'<p class="arch-month">{label}</p>\n<ul class="arch-list">\n'
                      + "\n".join(rows) + "\n</ul>")

    (ARCHIVE_DIR / "index.html").write_text(f"""<!doctype html>
<html lang="en">
<head>
{head_block("The Platero Brief, Archive", "Every issue of The Platero Brief, newest first.", f"{BASE}archive/", "../")}
</head>
<body>
{top_bar("../", f'<a href="../">Latest issue</a><a href="{BASE}feed.xml">RSS</a>')}
<div class="layout">
<main>
  <div class="arch-head">
    <h1>Archive</h1>
    <p>Every issue, newest first. {len(rendered)} issues so far.</p>
  </div>
{chr(10).join(blocks)}
  <footer class="foot" style="border-top:none;">
    <p class="fine">Jose Platero &middot; <a href="https://joseplatero.com" target="_blank" rel="noopener">joseplatero.com</a></p>
  </footer>
</main>
</div>
</body>
</html>
""", encoding="utf-8")


def render_feed(rendered):
    """RSS 2.0, newest 30, full content."""
    items = []
    for day, no, briefs in rendered[:30]:
        url = f"{BASE}archive/{day}.html"
        pub = format_datetime(datetime.combine(
            datetime.strptime(day, "%Y-%m-%d").date(), time(8, 0), tzinfo=TZ))
        content = "\n".join(
            f"<h1>{html.escape(b.name)}</h1>\n{b.html}" for b in briefs)
        items.append(f"""<item>
<title>The Platero Brief, No. {no}: {human_date(day)}</title>
<link>{url}</link>
<guid isPermaLink="true">{url}</guid>
<pubDate>{pub}</pubDate>
<description>{html.escape(f"{sum(b.words for b in briefs):,} words across {len(briefs)} briefs.")}</description>
<content:encoded><![CDATA[{content}]]></content:encoded>
</item>""")
    (SITE_ROOT / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>The Platero Brief</title>
<link>{BASE}</link>
<atom:link href="{BASE}feed.xml" rel="self" type="application/rss+xml"/>
<description>The daily intelligence brief Jose Platero's research pipeline writes each morning. Executive, practitioner, AI stack, and markets.</description>
<language>en</language>
{chr(10).join(items)}
</channel>
</rss>
""", encoding="utf-8")


# ---------- main ----------

def git(args):
    return subprocess.run(["git", "-C", str(SITE_ROOT)] + args,
                          capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", action="store_true", help="render all days, no gate")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    if not args.backfill:
        gate_day = args.date or datetime.now(TZ).strftime("%Y-%m-%d")
        gate = load_day(gate_day)
        if sum(1 for b in gate if b.slug in CORE) < 4:
            print(f"{gate_day}: fewer than 4 core briefs present, not publishing",
                  file=sys.stderr)
            sys.exit(1)

    days = all_days()
    if not days:
        print("no briefs found", file=sys.stderr)
        sys.exit(1)

    ARCHIVE_DIR.mkdir(exist_ok=True)
    loaded = [(d, i + 1, load_day(d)) for i, d in enumerate(days)]
    loaded = [(d, n, b) for d, n, b in loaded if b]

    for idx, (day, no, briefs) in enumerate(loaded):
        prev_day, prev_no = (loaded[idx - 1][0], loaded[idx - 1][1]) if idx > 0 else (None, None)
        next_day, next_no = (loaded[idx + 1][0], loaded[idx + 1][1]) if idx + 1 < len(loaded) else (None, None)
        (ARCHIVE_DIR / f"{day}.html").write_text(
            issue_page(day, briefs, no, prev_day, next_day, prev_no, next_no,
                       "../", f"{BASE}archive/{day}.html"), encoding="utf-8")

    latest_day, latest_no, latest_briefs = loaded[-1]
    prev_day, prev_no = (loaded[-2][0], loaded[-2][1]) if len(loaded) > 1 else (None, None)
    (SITE_ROOT / "index.html").write_text(
        issue_page(latest_day, latest_briefs, latest_no, prev_day, None, prev_no, None,
                   "", BASE), encoding="utf-8")

    newest_first = list(reversed(loaded))
    render_archive_index(newest_first)
    render_feed(newest_first)
    print(f"rendered {len(loaded)} issues, latest {latest_day} (No. {latest_no})")

    if args.no_push:
        return
    git(["add", "-A"])
    if not git(["diff", "--cached", "--name-only"]).stdout.strip():
        print("no changes to commit")
        return
    git(["commit", "-m", f"Publish through {latest_day} (No. {latest_no})"])
    r = git(["push"])
    print("pushed" if r.returncode == 0 else f"push failed: {r.stderr.strip()}")


if __name__ == "__main__":
    main()
