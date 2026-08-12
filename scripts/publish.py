#!/usr/bin/env python3
"""
Publish The Platero Brief: a public daily page built from the four
daily intelligence briefs in /Users/jp/jose-cerebro/daily/.

Reads the day's briefs, renders index.html (today) plus a permanent
archive/YYYY-MM-DD.html page, regenerates archive/index.html, and
optionally commits and pushes so GitHub Pages redeploys.

Only the four public-safe research briefs are published (plus the
Monday landscape scan when present). Triage and distilled notes are
personal and never included.

Usage:
  python3 scripts/publish.py                  # today (America/Toronto)
  python3 scripts/publish.py --date 2026-08-02
  python3 scripts/publish.py --latest         # newest date with all 4 briefs
  python3 scripts/publish.py --latest --no-push
"""
import argparse
import html
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BRAIN_DAILY = Path("/Users/jp/jose-cerebro/daily")
SITE_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = SITE_ROOT / "archive"

# slug -> (display name, css class). Order = page order.
SECTIONS = [
    ("executive-pulse", "Executive Pulse", "executive"),
    ("practitioner-pulse", "Practitioner Pulse", "practitioner"),
    ("ai-stack-daily", "AI Stack Daily", "stack"),
    ("markets-signal", "Markets Signal", "markets"),
    ("landscape-scan", "Landscape Scan", "landscape"),  # Mondays only
]

META_KEYS = ("date:", "type:", "tags:", "related:", "source:", "escalate:")


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
    # Drop the H1 title line; each section gets its own chip header.
    text = re.sub(r"\A#\s+[^\n]+\n+", "", text)
    return text.strip()


def normalize_dashes(text: str) -> str:
    # Brand rule: no em dashes in anything published. Periods, commas, colons.
    text = re.sub(r"\s*—\s*", ", ", text)
    text = re.sub(r"(?<=\w)\s*–\s*(?=\w)", " to ", text)  # ranges read as "to"
    return text


def md_inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def md_to_html(md: str) -> str:
    out, para, in_list = [], [], False

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
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_para()
            close_list()
            continue
        if stripped.startswith("### "):
            flush_para(); close_list()
            out.append("<h3>" + md_inline(stripped[4:]) + "</h3>")
        elif stripped.startswith("## "):
            flush_para(); close_list()
            out.append("<h2>" + md_inline(stripped[3:]) + "</h2>")
        elif stripped.startswith(("- ", "* ")):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + md_inline(stripped[2:]) + "</li>")
        else:
            para.append(stripped)
    flush_para()
    close_list()
    return "\n".join(out)


def load_sections(day: str):
    found = []
    for slug, name, css in SECTIONS:
        path = BRAIN_DAILY / f"{day}-{slug}.md"
        if slug == "markets-signal" and not path.exists():
            weekly = BRAIN_DAILY / f"{day}-markets-signal-weekly.md"
            if weekly.exists():
                path = weekly
        if not path.exists():
            continue
        body = strip_frontmatter(path.read_text(encoding="utf-8"))
        body = normalize_dashes(body)
        found.append((name, css, md_to_html(body)))
    return found


def human_date(day: str) -> str:
    return datetime.strptime(day, "%Y-%m-%d").strftime("%A, %B %-d, %Y")


def page(day: str, sections, css_prefix: str, canonical: str) -> str:
    body = "\n".join(
        f'<section class="brief {css}">\n<div class="wrap">\n'
        f'<span class="chip">{html.escape(name)}</span>\n{content}\n</div>\n</section>'
        for name, css, content in sections
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="The Platero Brief for {human_date(day)}. The daily intelligence brief Jose Platero's research pipeline writes for him each morning, published.">
<title>The Platero Brief &middot; {day}</title>
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="The Platero Brief &middot; {day}">
<meta property="og:description" content="Executive, practitioner, AI stack, and markets intelligence. Written by Jose Platero's research pipeline each morning.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,700;1,400&family=Hanken+Grotesk:wght@400;500;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{css_prefix}assets/brief.css">
</head>
<body>
<header class="mast">
  <div class="wrap">
    <p class="kicker">Daily &middot; Signal, not noise</p>
    <h1>The Platero Brief</h1>
    <p class="dateline">{human_date(day)}</p>
    <p class="tag">The intelligence brief my research pipeline writes for me every morning. I read it with coffee. Now you can too.</p>
    <nav>
      <a href="{css_prefix}archive/">Archive</a>
      <a href="https://loopsandletters.substack.com" target="_blank" rel="noopener">Loops &amp; Letters</a>
      <a href="https://joseplatero.com" target="_blank" rel="noopener">joseplatero.com</a>
    </nav>
  </div>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <div class="rule"></div>
    <p>Researched and written each morning by the agent pipeline Jose built on his second brain. Curated, not hand-polished. The weekly synthesis with his own take is <a href="https://loopsandletters.substack.com" target="_blank" rel="noopener">Loops &amp; Letters</a>.</p>
    <p>Jose Platero &middot; Director, Product &amp; Design &middot; <a href="https://joseplatero.com" target="_blank" rel="noopener">joseplatero.com</a></p>
  </div>
</footer>
</body>
</html>
"""


def render_archive_index():
    days = sorted(
        (p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")),
        reverse=True,
    )
    items = "\n".join(
        f'<li><a href="{d}.html"><span class="d">{human_date(d)}</span>'
        f'<span class="n">{d}</span></a></li>'
        for d in days
    )
    (ARCHIVE_DIR / "index.html").write_text(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Platero Brief &middot; Archive</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,700&family=Hanken+Grotesk:wght@400;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/brief.css">
</head>
<body>
<header class="mast">
  <div class="wrap">
    <p class="kicker">Archive</p>
    <h1>The Platero Brief</h1>
    <p class="tag">Every issue, newest first.</p>
    <nav><a href="../">Today's brief</a></nav>
  </div>
</header>
<main>
  <div class="wrap">
    <ul class="arch-list">
{items}
    </ul>
  </div>
</main>
</body>
</html>
""", encoding="utf-8")


def git(args):
    return subprocess.run(["git", "-C", str(SITE_ROOT)] + args,
                          capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--latest", action="store_true",
                    help="publish the newest date that has all 4 core briefs")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    if args.latest:
        dates = sorted({m.group(1) for p in BRAIN_DAILY.glob("*.md")
                        if (m := re.match(r"(\d{4}-\d{2}-\d{2})-", p.name))},
                       reverse=True)
        day = next((d for d in dates if len(load_sections(d)) >= 4), None)
        if not day:
            print("no date with all 4 core briefs found", file=sys.stderr)
            sys.exit(1)
    else:
        day = args.date or datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d")

    sections = load_sections(day)
    if len(sections) < 4:
        print(f"only {len(sections)}/4 core briefs present for {day}, not publishing",
              file=sys.stderr)
        sys.exit(1)

    base = "https://thejoseplatero.github.io/platero-brief/"
    ARCHIVE_DIR.mkdir(exist_ok=True)
    (ARCHIVE_DIR / f"{day}.html").write_text(
        page(day, sections, "../", f"{base}archive/{day}.html"), encoding="utf-8")
    (SITE_ROOT / "index.html").write_text(
        page(day, sections, "", base), encoding="utf-8")
    render_archive_index()
    print(f"rendered {day}: index.html, archive/{day}.html, archive/index.html")

    if args.no_push:
        return
    git(["add", "-A"])
    if "nothing to commit" in git(["status"]).stdout and not git(["diff", "--cached", "--name-only"]).stdout.strip():
        print("no changes to commit")
        return
    git(["commit", "-m", f"Publish brief for {day}"])
    r = git(["push"])
    print("pushed" if r.returncode == 0 else f"push failed: {r.stderr.strip()}")


if __name__ == "__main__":
    main()
