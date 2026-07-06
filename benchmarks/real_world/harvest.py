#!/usr/bin/env python3
"""
harvest.py — collect real-world AI-authored commits from public GitHub.

Searches for commits authored / co-authored by known AI coding tools, filters for
quality (repo stars, diff size, message length), and saves them for the real-world
benchmark. Output: data/real_world.jsonl. Requires GITHUB_TOKEN.

API note: GitHub's *GraphQL* API cannot search commit messages or co-author trailers
— its `search` connection only covers issues, PRs, repos, users, and discussions. The
correct tool for finding commits by co-author is the REST commit-search endpoint
(GET /search/commits). We use it here and pace requests politely (its limit is ~30
req/min), which is what "rate-limit friendly" needs in practice.
"""
import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

API = "https://api.github.com"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

# ai_tool -> commit-search query. Free text matches the commit message / trailers,
# so a co-author trailer like "Co-authored-by: Copilot" is found as a phrase.
SOURCES = {
    "copilot": '"Co-authored-by: Copilot"',
    "claude":  '"claude[bot]"',
    "cursor":  '"Cursor Agent"',
    "devin":   '"devin-ai-integration"',
    "jules":   '"google-labs-jules[bot]"',
}

MIN_STARS = 50
MIN_DIFF_LINES = 20
MAX_DIFF_LINES = 500
MIN_MSG_CHARS = 100


def _headers(token):
    return {"Authorization": f"Bearer {token}",
            "User-Agent": "git-to-doc-benchmark/1.0",
            "Accept": "application/vnd.github+json"}


def _stars(repo, token, cache):
    if repo not in cache:
        r = requests.get(f"{API}/repos/{repo}", headers=_headers(token), timeout=30)
        cache[repo] = r.json().get("stargazers_count", 0) if r.ok else 0
    return cache[repo]


def _diff(repo, sha):
    r = requests.get(f"https://github.com/{repo}/commit/{sha}.diff",
                     headers={"User-Agent": "git-to-doc-benchmark/1.0"}, timeout=30)
    r.raise_for_status()
    return r.text


def _diff_line_count(diff):
    return sum(1 for l in diff.splitlines()
               if (l.startswith("+") and not l.startswith("+++"))
               or (l.startswith("-") and not l.startswith("---")))


def harvest_source(tool, query, token, target, star_cache, seen):
    """Collect up to `target` qualifying commits for one AI tool."""
    rows, page = [], 1
    while len(rows) < target and page <= 10:
        r = requests.get(f"{API}/search/commits", headers=_headers(token),
                         params={"q": query, "per_page": 100, "page": page,
                                 "sort": "committer-date", "order": "desc"}, timeout=30)
        if r.status_code in (403, 429):   # rate limited
            wait = int(r.headers.get("Retry-After", "60"))
            print(f"  [{tool}] rate-limited; sleeping {wait}s…", file=sys.stderr)
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"  [{tool}] search error {r.status_code}: {r.text[:120]}", file=sys.stderr)
            break
        items = r.json().get("items", [])
        if not items:
            break
        for it in items:
            if len(rows) >= target:
                break
            sha, repo = it["sha"], it["repository"]["full_name"]
            msg = it["commit"]["message"]
            if sha in seen or len(msg) < MIN_MSG_CHARS:
                continue
            if _stars(repo, token, star_cache) < MIN_STARS:
                continue
            try:
                diff = _diff(repo, sha)
            except requests.RequestException:
                continue
            if not (MIN_DIFF_LINES <= _diff_line_count(diff) <= MAX_DIFF_LINES):
                continue
            seen.add(sha)
            rows.append({"commit_sha": sha, "repo": repo, "ai_tool": tool, "diff": diff,
                         "original_message": msg, "harvest_date": date.today().isoformat()})
            print(f"  [{tool}] {len(rows)}/{target}  {repo}@{sha[:7]}", file=sys.stderr)
            time.sleep(0.3)   # polite to codeload
        page += 1
        time.sleep(2)         # commit search is ~30/min — pace the pages
    return rows


def main():
    ap = argparse.ArgumentParser(
        description="Harvest AI-authored commits for the real-world benchmark.")
    ap.add_argument("--total", type=int, default=200, help="total commits (default 200)")
    ap.add_argument("--out", default=str(DATA_DIR / "real_world.jsonl"))
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("  ✗ GITHUB_TOKEN is required — the commit-search API needs auth.\n"
              "    export GITHUB_TOKEN=ghp_… then re-run.", file=sys.stderr)
        sys.exit(1)

    per_source = max(1, args.total // len(SOURCES))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    star_cache, seen, total = {}, set(), 0
    with out_path.open("w", encoding="utf-8") as f:
        for tool, query in SOURCES.items():
            print(f"\n  == {tool} (target {per_source}) ==", file=sys.stderr)
            rows = harvest_source(tool, query, token, per_source, star_cache, seen)
            for row in rows:
                f.write(json.dumps(row) + "\n")
            total += len(rows)
            print(f"  {tool}: collected {len(rows)}", file=sys.stderr)

    print(f"\n  Wrote {total} commits → {out_path}")
    if total < args.total:
        print(f"  (only {total}/{args.total}; some tools may have fewer public, "
              "well-starred, right-sized commits)", file=sys.stderr)


if __name__ == "__main__":
    main()
