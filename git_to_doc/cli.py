#!/usr/bin/env python3
"""
git-to-doc — Conventional Commit messages, changelogs & PRs from git diffs.

Commands:
  git-to-doc <input> [--output md|json|both] [--model M]   generate commit + changelog
  git-to-doc <input> --commit-msg                          print ONLY the commit message
  git-to-doc pr [--base B] [--create] [--draft] [--model M]  generate / open a pull request
  git-to-doc install-hook                                   auto-fill commit messages via git hook

<input> is a GitHub PR URL, '-' for stdin, a local .diff/.txt file, or a folder of .diff files.

Examples:
  git-to-doc https://github.com/pallets/flask/pull/5000 --output both
  git-to-doc sample.diff
  git diff --cached | git-to-doc --commit-msg -
  git-to-doc pr --create
  git-to-doc install-hook
"""

import sys, re, argparse, time, os, subprocess, tempfile, shutil
from pathlib import Path
from datetime import date
from typing import Optional

import requests

from git_to_doc.model import analyze_diff, analyze_pr, CommitDoc, backend
from git_to_doc.renderer import (
    render_full_output, render_markdown_file,
    render_commit_message, render_pr_body, render_pr_full_output,
)

# ── Theme ────────────────────────────────────────────────────────────────────
from git_to_doc.theme import c as _c, BOLD, DIM, GREEN, BRIGHT, RED, section, rule


# ── URL normalisation ─────────────────────────────────────────────────────────
_GH_PR  = re.compile(r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)', re.I)
_GH_RAW = re.compile(r'https?://patch-diff\.githubusercontent\.com/raw/([^/]+/[^/]+)/pull/(\d+)', re.I)

def normalise_url(url: str) -> tuple:
    """Return (fetch_url, slug) for any GitHub PR URL format."""
    url = url.rstrip("/")
    m = _GH_PR.match(url)
    if m:
        repo, pr = m.group(1), m.group(2)
        return f"https://patch-diff.githubusercontent.com/raw/{repo}/pull/{pr}.diff", f"PR-{pr}"
    m = _GH_RAW.match(url)
    if m:
        pr = m.group(2)
        return (url if url.endswith(".diff") else url + ".diff"), f"PR-{pr}"
    fetch = url if url.endswith(".diff") else url + ".diff"
    slug = re.sub(r'[^a-zA-Z0-9_-]', '-', Path(url).stem)[:40]
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
    adds = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    dels = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {"files": files, "additions": adds, "deletions": dels}


def auto_stem(input_str: str) -> str:
    today = date.today().isoformat()
    if is_url(input_str):
        _, slug = normalise_url(input_str)
        return f"{slug}-changelog-{today}"
    p = Path(input_str)
    return f"{(p.name if p.is_dir() else p.stem)}-changelog-{today}"


def _read_source(input_str: str) -> str:
    """Diff text for a single source: '-' (stdin), a GitHub PR URL, or a file."""
    if input_str == "-":
        return sys.stdin.read()
    if is_url(input_str):
        return fetch_diff(input_str)
    p = Path(input_str)
    if not p.exists():
        print(_c(f"  ✗ File not found: {input_str}", RED)); sys.exit(1)
    return p.read_text(encoding="utf-8")


# ── git helpers ───────────────────────────────────────────────────────────────
def _git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)

def _ref_exists(ref: str) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", ref], capture_output=True).returncode == 0

def _detect_base() -> Optional[str]:
    for b in ("main", "master"):
        if _ref_exists(b) or _ref_exists(f"origin/{b}"):
            return b
    return None

def _resolve_ref(name: str) -> Optional[str]:
    for ref in (name, f"origin/{name}"):
        if _ref_exists(ref):
            return ref
    return None


# ── Single diff processing ────────────────────────────────────────────────────
def process_diff(diff_text: str, stem: str, model: str,
                 fmt: Optional[str], source: str = "") -> CommitDoc:
    stats = diff_stats(diff_text)
    print(_c(f"  files changed: {len(stats['files'])}", DIM))
    for f in stats["files"]:
        print(_c(f"    {f}", DIM))
    print(_c(f"  +{stats['additions']} / -{stats['deletions']}", DIM))
    print()
    print(_c(f"  sending to {model}…", DIM))

    t0 = time.time()
    result = analyze_diff(diff_text, model=model)
    print(_c(f"  done in {time.time() - t0:.1f}s", DIM))
    print(render_full_output(result))

    if fmt in ("md", "both"):
        md_path = Path(f"{stem}.md")
        md_path.write_text(render_markdown_file(result, model=model, source=source, stats=stats),
                           encoding="utf-8")
        print(_c(f"  ✓ saved  {md_path}", GREEN))
    if fmt in ("json", "both"):
        json_path = Path(f"{stem}.json")
        json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(_c(f"  ✓ saved  {json_path}", GREEN))
    return result


# ── doc: diff → commit message + changelog ────────────────────────────────────
def cmd_doc(argv):
    parser = argparse.ArgumentParser(
        prog="git-to-doc",
        description="Generate Conventional Commit messages & changelogs from git diffs.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("input",
        help="GitHub PR URL, '-' for stdin, a local .diff file, or a folder of .diff files")
    parser.add_argument("--output", nargs="?", const="md", default=None,
        metavar="{md,json,both}",
        help="Save output: 'md' (default when flag used), 'json', or 'both'.")
    parser.add_argument("--model", default="gemma4", help="Ollama model name (default: gemma4)")
    parser.add_argument("--commit-msg", action="store_true",
        help="Print ONLY the Conventional Commit message (for git hooks / piping)")
    args = parser.parse_args(argv)

    if args.commit_msg:
        diff_text = _read_source(args.input)
        if not diff_text.strip():
            return
        print(render_commit_message(analyze_diff(diff_text, model=args.model)))
        return

    if args.output not in {"md", "json", "both", None}:
        print(_c(f"  ✗ --output must be md, json, or both (got '{args.output}')", RED)); sys.exit(1)
    fmt = args.output

    print(_c("\n  git-to-doc", BOLD, BRIGHT) + _c(f"  ·  {args.model} · {backend()}", DIM))
    print(rule())
    try:
        if not is_url(args.input) and args.input != "-" and Path(args.input).is_dir():
            diffs = sorted(Path(args.input).glob("**/*.diff"))
            if not diffs:
                print(_c(f"  ✗ No .diff files found in {args.input}", RED)); sys.exit(1)
            print(_c(f"  source: folder ({len(diffs)} diff files)", DIM))
            for diff_file in diffs:
                print("\n" + section(diff_file.name))
                stem = f"{diff_file.stem}-changelog-{date.today().isoformat()}"
                process_diff(diff_file.read_text(encoding="utf-8"), stem, args.model, fmt, source=str(diff_file))
        else:
            label = "URL" if is_url(args.input) else ("stdin" if args.input == "-" else Path(args.input).name)
            print(_c(f"  source: {label}", DIM))
            process_diff(_read_source(args.input), auto_stem(args.input), args.model, fmt, source=args.input)
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", "?")
        print(_c(f"\n  ✗ Could not fetch diff (HTTP {code}). Check the PR URL is public.", RED)); sys.exit(1)
    except requests.RequestException as e:
        print(_c(f"\n  ✗ Network error fetching diff: {e}", RED)); sys.exit(1)
    print()


# ── pr: branch diff → PR title + body, optionally opened via gh ────────────────
def cmd_pr(argv):
    parser = argparse.ArgumentParser(
        prog="git-to-doc pr",
        description="Generate (and optionally open) a pull request from the current branch.")
    parser.add_argument("--base", help="base branch (default: auto-detect main/master)")
    parser.add_argument("--model", default="gemma4", help="Ollama model name (default: gemma4)")
    parser.add_argument("--create", action="store_true", help="open the PR on GitHub via gh")
    parser.add_argument("--draft", action="store_true", help="open as a draft PR (implies --create)")
    args = parser.parse_args(argv)

    if subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True).returncode != 0:
        print(_c("  ✗ Not inside a git repository.", RED)); sys.exit(1)

    base = args.base or _detect_base()
    if not base:
        print(_c("  ✗ Could not detect a base branch (main/master). Use --base.", RED)); sys.exit(1)
    head = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if head == base:
        print(_c(f"  ✗ You are on '{base}'. Checkout a feature branch first.", RED)); sys.exit(1)
    base_ref = _resolve_ref(base)
    if not base_ref:
        print(_c(f"  ✗ Base '{base}' not found locally or on origin.", RED)); sys.exit(1)

    diff_text = _git("diff", f"{base_ref}...HEAD", check=False).stdout
    if not diff_text.strip():
        print(_c(f"  ✗ No changes between {base} and {head}.", RED)); sys.exit(1)

    print(_c("\n  git-to-doc pr", BOLD, BRIGHT) + _c(f"  ·  {head} → {base} · {args.model}", DIM))
    print(rule())
    print(_c("  generating pull request…", DIM))
    pr = analyze_pr(diff_text, model=args.model, verbose=True)
    print(render_pr_full_output(pr))

    if not (args.create or args.draft):
        print(_c("  (preview only — re-run with --create to open the PR)\n", DIM)); return

    print(_c(f"  pushing {head}…", DIM))
    push = subprocess.run(["git", "push", "-u", "origin", head], capture_output=True, text=True)
    if push.returncode != 0:
        print(_c(f"  ✗ push failed: {push.stderr.strip()}", RED)); sys.exit(1)

    body = render_pr_body(pr)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body); body_file = f.name
    cmd = ["gh", "pr", "create", "--base", base, "--head", head,
           "--title", pr.title, "--body-file", body_file]
    if args.draft:
        cmd.append("--draft")
    print(_c("  opening PR via gh…", DIM))
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(body_file)
    if r.returncode == 0:
        print(_c(f"  ✓ {r.stdout.strip()}\n", GREEN))
    else:
        print(_c(f"  ✗ gh failed: {r.stderr.strip()}", RED)); sys.exit(1)


# ── install-hook: prepare-commit-msg auto-fill ─────────────────────────────────
_HOOK_TEMPLATE = """#!/bin/sh
# git-to-doc prepare-commit-msg hook — auto-fills the message from the staged diff.
COMMIT_MSG_FILE="$1"
COMMIT_SOURCE="$2"
# Skip when a message is already supplied (-m, merge, squash, template, amend).
[ -n "$COMMIT_SOURCE" ] && exit 0
DIFF="$(git diff --cached)"
[ -z "$DIFF" ] && exit 0
GENERATED="$(printf '%s' "$DIFF" | {invoke} --commit-msg - 2>/dev/null)"
[ -z "$GENERATED" ] && exit 0
EXISTING="$(cat "$COMMIT_MSG_FILE")"
printf '%s\\n\\n%s\\n' "$GENERATED" "$EXISTING" > "$COMMIT_MSG_FILE"
"""

def cmd_install_hook(argv):
    r = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, text=True)
    if r.returncode != 0:
        print(_c("  ✗ Not inside a git repository.", RED)); sys.exit(1)
    # Prefer the installed console command; fall back to running the module.
    if shutil.which("git-to-doc"):
        invoke = "git-to-doc"
    else:
        invoke = f'"{sys.executable}" -m git_to_doc.cli'
    hooks = Path(r.stdout.strip()) / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook_path = hooks / "prepare-commit-msg"
    hook_path.write_text(_HOOK_TEMPLATE.format(invoke=invoke), encoding="utf-8")
    hook_path.chmod(0o755)
    print(_c(f"  ✓ Installed prepare-commit-msg hook → {hook_path}", GREEN))
    print(_c(f"    using: {invoke} --commit-msg -", DIM))
    print(_c("    `git commit` (no -m) now auto-fills a Conventional Commit message.", DIM))
    print(_c('    Bypass anytime with `git commit -m "..."`.', DIM))


# ── Top-level help ────────────────────────────────────────────────────────────
def _top_help():
    print(f"""
{_c("  git-to-doc", BOLD, BRIGHT)} {_c("— Conventional Commits, changelogs & PRs from git diffs, via Gemma", DIM)}

{_c("  COMMANDS", BOLD, BRIGHT)}
    {_c("git-to-doc <input>", BOLD)} [--output md|json|both] [--model M]
        Generate a Conventional Commit message + changelog + plain-English summary.
        <input> = a GitHub PR URL, '-' for stdin, a .diff/.txt file, or a folder of .diff files.

    {_c("git-to-doc <input> --commit-msg", BOLD)}
        Print ONLY the commit message (for piping / git hooks).

    {_c("git-to-doc pr", BOLD)} [--base B] [--create] [--draft] [--model M]
        Generate a pull request from the current branch. Preview by default;
        --create pushes the branch and opens the PR via gh.

    {_c("git-to-doc install-hook", BOLD)}
        Install a git hook so `git commit` (no -m) auto-fills the message.

    {_c("git-to-doc-compare <diffs...>", BOLD)} [--models ...] [--judge [MODEL]]
        Benchmark models (timing; --judge adds rubric quality + CC pass-rate).

{_c("  EXAMPLES", BOLD, BRIGHT)}
    git-to-doc sample.diff
    git-to-doc https://github.com/pallets/flask/pull/5000 --output both
    git diff --cached | git-to-doc --commit-msg -
    git-to-doc pr --create

{_c("  Run", DIM)} {_c("git-to-doc <command> --help", BOLD)} {_c("for command-specific options.", DIM)}
""")


# ── Main dispatcher ───────────────────────────────────────────────────────────
def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        _top_help()
        return
    if argv[0] == "pr":
        return cmd_pr(argv[1:])
    if argv[0] == "install-hook":
        return cmd_install_hook(argv[1:])
    return cmd_doc(argv)


if __name__ == "__main__":
    main()
