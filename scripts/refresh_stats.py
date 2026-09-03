#!/usr/bin/env python3
"""Refresh the live numbers baked into the profile README and its SVG cards.

Pulls stars / downloads / commits / releases straight from the GitHub API and
rewrites the matching values in README.md and assets/*.svg. Every substitution
is anchored to the label that sits next to the number (the STARS text element,
the "downloads" word, the aria-label phrasing) so nothing else in the markup
can be hit by accident.

Run with GITHUB_TOKEN set to avoid the 60/hour anonymous rate limit.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
MAIN_REPO = "varunsalian/debrify"
OTHER_REPO = "varunsalian/stremio-addon-importer"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


def request(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "varunsalian-profile-stats")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode()), resp.headers


def get_json(url):
    return request(url)[0]


def paginate(url):
    """Yield every item across a paginated collection endpoint."""
    page = 1
    while True:
        sep = "&" if "?" in url else "?"
        batch = get_json(f"{url}{sep}per_page=100&page={page}")
        if not batch:
            return
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def commit_count(repo):
    """Total commits on the default branch, via the Link header's last page."""
    _, headers = request(f"{API}/repos/{repo}/commits?per_page=1")
    link = headers.get("Link", "")
    match = re.search(r'[?&]page=(\d+)[^>]*>;\s*rel="last"', link)
    if match:
        return int(match.group(1))
    # Fewer than one full page: count what we can see.
    return len(get_json(f"{API}/repos/{repo}/commits?per_page=100"))


def collect():
    releases = [r for r in paginate(f"{API}/repos/{MAIN_REPO}/releases") if not r.get("draft")]
    downloads = sum(a.get("download_count", 0) for r in releases for a in r.get("assets", []))
    return {
        "stars": get_json(f"{API}/repos/{MAIN_REPO}")["stargazers_count"],
        "downloads": downloads,
        "commits": commit_count(MAIN_REPO),
        "releases": len(releases),
        "importer_stars": get_json(f"{API}/repos/{OTHER_REPO}")["stargazers_count"],
    }


NUM = r"[\d,]+"


def rewrite(text, stats):
    stars = f"{stats['stars']:,}"
    downloads = f"{stats['downloads']:,}"
    commits = f"{stats['commits']:,}"
    releases = f"{stats['releases']:,}"
    importer = f"{stats['importer_stars']:,}"

    # Stat tiles in the Debrify card: <text ...>433★</text><text ...>STARS</text>
    for label, value in (
        ("STARS", stars + "★"),
        ("DOWNLOADS", downloads),
        ("COMMITS", commits),
        ("RELEASES", releases),
    ):
        text = re.sub(
            rf"(>){NUM}★?(</text>\s*<text\b[^>]*>{label}</text>)",
            lambda m, v=value: m.group(1) + v + m.group(2),
            text,
        )

    # Terminal "ls ~/ships" lines in the boot SVGs — one repo per line.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if ">debrify/<" in line:
            line = re.sub(rf"(>){NUM}★(</tspan>)", rf"\g<1>{stars}★\g<2>", line)
            line = re.sub(rf"{NUM} downloads", f"{downloads} downloads", line)
        elif ">stremio-addon-importer/<" in line:
            line = re.sub(rf"(>){NUM}★(</tspan>)", rf"\g<1>{importer}★\g<2>", line)
        lines[i] = line
    text = "\n".join(lines)

    # Prose numbers in aria-label / alt attributes.
    text = re.sub(rf"{NUM} stars", f"{stars} stars", text)
    text = re.sub(rf"{NUM} downloads", f"{downloads} downloads", text)
    text = re.sub(rf"{NUM} commits", f"{commits} commits", text)
    text = re.sub(rf"{NUM} releases", f"{releases} releases", text)
    return text


def main():
    try:
        stats = collect()
    except (urllib.error.URLError, KeyError) as err:
        print(f"could not fetch stats: {err}", file=sys.stderr)
        return 1

    print(json.dumps(stats, indent=2))

    targets = [ROOT / "README.md"] + sorted((ROOT / "assets").glob("*.svg"))
    changed = []
    for path in targets:
        before = path.read_text()
        after = rewrite(before, stats)
        if after != before:
            path.write_text(after)
            changed.append(path.relative_to(ROOT).as_posix())

    print("changed: " + (", ".join(changed) if changed else "nothing"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
