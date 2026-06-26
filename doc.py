#!/usr/bin/env python3
"""
git-to-doc — Generate Conventional Commit messages & changelogs from git diffs.

Accepts:
  - A GitHub PR URL   (github.com or patch-diff.githubusercontent.com)
  - A local .diff or .txt file
  - A folder of .diff files (processes all of them)

Flags:
  --output [md|json|both]   Save output file(s). Defaults to 'md' if omitted.
  --model MODEL             Ollama model to use (default: gemma4).

Examples:
  python doc.py https://github.com/pallets/flask/pull/5000
  python doc.py https://github.com/pallets/flask/pull/5000 --output
  python doc.py https://github.com/pallets/flask/pull/5000 --output json
  python doc.py https://github.com/pallets/flask/pull/5000 --output both
  python doc.py sample.diff --output md
  python doc.py ./diffs/ --output both
"""

import sys, re, json, argparse, time
from pathlib import Path
from datetime import date
from typing import Optional

import requests

from model import analyze_diff, CommitDoc
from renderer import render_full_output, render_markdown_file

# ── ANSI helpers ─────────────────────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
RED = "\033[31m"; CYAN = "\033[36m"; DIM = "\033[2m"; YELLOW = "\033[33m"

def _c(t, *c): return "".join(c) + t + RESET


# ── URL normalisation ─────────────────────────────────────────────────────────
_GH_PR  = re.compile(r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)', re.I)
_GH_RAW = re.compile(r'https?://patch-diff\.githubusercontent\.com/raw/([^/]+/[^/]+)/pull/(\d+)', re.I)

def normalise_url(url: str) -> tuple:
    """Return (fetch_url, slug) for any GitHub PR URL format."""
    url = url.rstrip("/")

    m = _GH_PR.match(url)
    if m:
        repo, pr = m.group(1), m.group(2)
        fetch = f"https://patch-diff.githubusercontent.com/raw/{repo}/pull/{pr}.diff"
        return fetch, f"PR-{pr}"

    m = _GH_RAW.match(url)
    if m:
        pr    = m.group(2)
        fetch = url if url.endswith(".diff") else url + ".diff"
        return fetch, f"PR-{pr}"

    # Generic URL — ensure .diff suffix
    fetch = url if url.endswith(".diff") else url + ".diff"
    slug  = re.sub(r'[^a-zA-Z0-9_-]', '-', Path(url).stem)[:40]
    return fetch, slug

def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")

def fetch_diff(url: str) -> str:
    fetch_url, _ = normalise_url(url)
    print(_c(f"  ↓ {fetch_url}", DIM))
    resp = requests.get(fetch_url, timeout=30, headers={"User-Agent": "git-to-doc/1.0"})
    resp.raise_for_status()
    return resp.text


# ── Diff stats ────────────────────────────────────────────────────────────────
def diff_stats(text: str) -> dict:
    lines = text.splitlines()
    files = [l[len("diff --git "):].split(" b/")[-1]
             for l in lines if l.startswith("diff --git ")]
    adds  = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    dels  = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {"files": files, "additions": adds, "deletions": dels}


# ── Auto filename ─────────────────────────────────────────────────────────────
def auto_stem(input_str: str) -> str:
    today = date.today().isoformat()
    if is_url(input_str):
        _, slug = normalise_url(input_str)
        return f"{slug}-changelog-{today}"
    p = Path(input_str)
    if p.is_dir():
        return f"{p.name}-changelog-{today}"
    return f"{p.stem}-changelog-{today}"


# ── Single diff processing ────────────────────────────────────────────────────
def process_diff(diff_text: str, stem: str, model: str, fmt: Optional[str]) -> CommitDoc:
    """
    fmt: None → terminal only | 'md' → save .md | 'json' → save .json | 'both' → both
    """
    stats = diff_stats(diff_text)
    print(_c(f"  Files changed : {len(stats['files'])}", DIM))
    for f in stats["files"]:
        print(_c(f"    • {f}", DIM))
    print(_c(f"  +{stats['additions']} additions  -{stats['deletions']} deletions", DIM))
    print()
    print(_c(f"  ⏳ Sending to {model}…", DIM))

    t0     = time.time()
    result = analyze_diff(diff_text, model=model)
    elapsed = time.time() - t0
    print(_c(f"  ⚡ Inference done in {elapsed:.1f}s", DIM))
    print(render_full_output(result))

    if fmt in ("md", "both"):
        md_path = Path(f"{stem}.md")
        md_path.write_text(render_markdown_file(result), encoding="utf-8")
        print(_c(f"  ✓ Markdown saved → {md_path}", GREEN))

    if fmt in ("json", "both"):
        json_path = Path(f"{stem}.json")
        json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(_c(f"  ✓ JSON saved    → {json_path}", GREEN))

    return result


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate Conventional Commit messages & changelogs from git diffs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input",
        help="GitHub PR URL, local .diff file, or folder of .diff files")
    parser.add_argument("--output", nargs="?", const="md", default=None,
        metavar="{md,json,both}",
        help="Save output: 'md' (default when flag used), 'json', or 'both'. Auto-names file.")
    parser.add_argument("--model", default="gemma4",
        help="Ollama model name (default: gemma4)")

    args = parser.parse_args()

    # Validate --output value
    valid_fmts = {"md", "json", "both", None}
    if args.output not in valid_fmts:
        print(_c(f"  ✗ --output must be md, json, or both (got '{args.output}')", RED))
        sys.exit(1)

    fmt = args.output  # None | 'md' | 'json' | 'both'

    # ── Banner ────────────────────────────────────────────────────────────────
    print(_c("\n  🔍  git-to-doc", BOLD, CYAN) +
          _c(f"  powered by {args.model}", DIM))
    print(_c("  " + "─" * 52, DIM))

    # ── Dispatch: URL / folder / file ─────────────────────────────────────────
    try:
        if is_url(args.input):
            print(_c("  ⚡ Source: URL", BOLD))
            diff_text = fetch_diff(args.input)
            process_diff(diff_text, auto_stem(args.input), args.model, fmt)

        elif Path(args.input).is_dir():
            diffs = sorted(Path(args.input).glob("**/*.diff"))
            if not diffs:
                print(_c(f"  ✗ No .diff files found in {args.input}", RED))
                sys.exit(1)
            print(_c(f"  ⚡ Source: folder ({len(diffs)} diff files)", BOLD))
            for diff_file in diffs:
                print(_c(f"\n  ── {diff_file.name} ──", BOLD, CYAN))
                stem = f"{diff_file.stem}-changelog-{date.today().isoformat()}"
                process_diff(diff_file.read_text(encoding="utf-8"), stem, args.model, fmt)

        else:
            path = Path(args.input)
            if not path.exists():
                print(_c(f"  ✗ File not found: {args.input}", RED))
                sys.exit(1)
            print(_c(f"  ⚡ Source: {path.name}", BOLD))
            process_diff(path.read_text(encoding="utf-8"), auto_stem(args.input), args.model, fmt)

    except requests.HTTPError as e:
        print(_c(f"\n  ✗ HTTP error: {e}", RED))
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
