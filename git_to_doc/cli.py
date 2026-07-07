import sys, re, json, argparse, time, os, subprocess, tempfile, shutil, threading, itertools
from pathlib import Path
from datetime import date
from typing import Optional

import requests

from git_to_doc.model import analyze_diff, analyze_pr, CommitDoc, backend, GenerationError
from git_to_doc import auditor
from git_to_doc.renderer import (
    render_full_output, render_markdown_file,
    render_commit_message, render_pr_body, render_pr_full_output, render_audit_report,
)

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


def auto_stem(input_str: str, model: str) -> str:
    today = date.today().isoformat()
    clean_model = model.replace(":", "-")
    if is_url(input_str):
        _, slug = normalise_url(input_str)
        return f"{slug}-changelog-{clean_model}-{today}"
    p = Path(input_str)
    return f"{(p.name if p.is_dir() else p.stem)}-changelog-{clean_model}-{today}"


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
    print(_c(f"  Files changed : {len(stats['files'])}", DIM))
    for f in stats["files"]:
        print(_c(f"    • {f}", DIM))
    print(_c(f"  +{stats['additions']} additions  -{stats['deletions']} deletions", DIM))
    done = False
    def spinner():
        for char in itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']):
            if done:
                break
            sys.stdout.write(f"\r{_c('  ' + char + f' Sending to {model}…', DIM)}")
            sys.stdout.flush()
            time.sleep(0.1)

    t0 = time.time()
    t = threading.Thread(target=spinner)
    t.start()
    try:
        result = analyze_diff(diff_text, model=model)
    finally:
        done = True
        t.join()
        sys.stdout.write("\r" + " " * 50 + "\r")  # clear spinner line
    
    elapsed = time.time() - t0
    print(_c(f"  ⚡ Inference done in {elapsed:.1f}s", DIM))
    
    if fmt == "stdout":
        print(render_full_output(result))

    if fmt in ("md", "both"):
        md_path = Path(f"{stem}.md")
        md_path.write_text(render_markdown_file(result, model=model, source=source, stats=stats),
                           encoding="utf-8")
        print(_c(f"  ✓ Markdown saved → {md_path}", GREEN))
    if fmt in ("json", "both"):
        json_path = Path(f"{stem}.json")
        json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(_c(f"  ✓ JSON saved    → {json_path}", GREEN))
    return result


# ── doc: diff → commit message + changelog ────────────────────────────────────
def cmd_doc(argv):
    parser = argparse.ArgumentParser(
        prog="git-to-doc",
        description="Generate Conventional Commit messages & changelogs from git diffs.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("input",
        help="GitHub PR URL, '-' for stdin, a local .diff file, or a folder of .diff files")
    parser.add_argument("--output", nargs="?", const="md", default="md",
        metavar="{md,json,both,stdout}",
        help="Save output: 'md' (default), 'json', 'both', or 'stdout' (print to terminal).")
    parser.add_argument("--model", default="gemma4", help="Ollama model name (default: gemma4)")
    parser.add_argument("--commit-msg", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.commit_msg:
        diff_text = _read_source(args.input)
        if not diff_text.strip():
            return
        try:
            print(render_commit_message(analyze_diff(diff_text, model=args.model)))
        except GenerationError as e:
            print(f"git-to-doc: {e}", file=sys.stderr); sys.exit(1)
        return

    if args.output not in {"md", "json", "both", "stdout"}:
        print(_c(f"  ✗ --output must be md, json, both, or stdout (got '{args.output}')", RED)); sys.exit(1)
    fmt = args.output

    print(_c("\n  🔍  git-to-doc", BOLD, CYAN) + _c(f"  {args.model} · {backend()}", DIM))
    print(_c("  " + "─" * 52, DIM))
    try:
        if not is_url(args.input) and args.input != "-" and Path(args.input).is_dir():
            diffs = sorted(Path(args.input).glob("**/*.diff"))
            if not diffs:
                print(_c(f"  ✗ No .diff files found in {args.input}", RED)); sys.exit(1)
            print(_c(f"  ⚡ Source: folder ({len(diffs)} diff files)", BOLD))
            for diff_file in diffs:
                print(_c(f"\n  ── {diff_file.name} ──", BOLD, CYAN))
                clean_model = args.model.replace(":", "-")
                stem = f"{diff_file.stem}-changelog-{clean_model}-{date.today().isoformat()}"
                process_diff(diff_file.read_text(encoding="utf-8"), stem, args.model, fmt, source=str(diff_file))
        else:
            label = "URL" if is_url(args.input) else ("stdin" if args.input == "-" else Path(args.input).name)
            print(_c(f"  ⚡ Source: {label}", BOLD))
            process_diff(_read_source(args.input), auto_stem(args.input, args.model), args.model, fmt, source=args.input)
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", "?")
        print(_c(f"\n  ✗ Could not fetch diff (HTTP {code}). Check the PR URL is public.", RED)); sys.exit(1)
    except requests.RequestException as e:
        print(_c(f"\n  ✗ Network error fetching diff: {e}", RED)); sys.exit(1)
    except GenerationError as e:
        print(_c(f"\n  ✗ {e}", RED)); sys.exit(1)
    print()


# ── pull-request: branch diff → PR title + body, optionally opened via gh ──────
def cmd_pr(argv):
    parser = argparse.ArgumentParser(
        prog="git-to-doc pull-request",
        description="Generate (and optionally open) a pull request from the current branch.")
    parser.add_argument("--base", help="base branch (default: auto-detect main/master)")
    parser.add_argument("--model", default="gemma4", help="Ollama model name (default: gemma4)")
    parser.add_argument("--create", action="store_true", help="open the PR on GitHub via gh")
    parser.add_argument("--draft", action="store_true", help="open as a draft PR (implies --create)")
    parser.add_argument("--skip-audit", action="store_true",
        help="skip auditing the generated description against the diff")
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

    print(_c("\n  🔀  git-to-doc pull-request", BOLD, CYAN) + _c(f"  {head} → {base}  ·  {args.model}", DIM))
    print(_c("  " + "─" * 52, DIM))
    done = False
    def spinner():
        for char in itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']):
            if done:
                break
            sys.stdout.write(f"\r{_c('  ' + char + f' Generating pull request…', DIM)}")
            sys.stdout.flush()
            time.sleep(0.1)

    t = threading.Thread(target=spinner)
    t.start()
    err = None
    try:
        pr = analyze_pr(diff_text, model=args.model, verbose=True)
    except GenerationError as e:
        err = e
    finally:
        done = True
        t.join()
        sys.stdout.write("\r" + " " * 50 + "\r")
    if err:
        print(_c(f"  ✗ {err}", RED)); sys.exit(1)

    # Audit the AI-generated description against the diff before it's posted.
    audit = None
    if not args.skip_audit:
        claim = f"{pr.title}\n\n{pr.summary}\n\n" + "\n".join(f"- {c}" for c in pr.changes)
        print(_c(f"  🔎 auditing the generated description with "
                 f"{len(auditor.DEFAULT_AUDITORS)} model(s)…", DIM))
        try:
            reports = auditor.run_audit(diff_text, claim)
            audit = [m for m in auditor.merge_audits(reports) if m.confidence == "high"]
        except Exception as e:
            print(_c(f"  ⚠ audit skipped: {_explain_ollama_error(e, auditor.DEFAULT_AUDITORS)}",
                     YELLOW))
            audit = None

    print(render_pr_full_output(pr, audit=audit))

    if not (args.create or args.draft):
        print(_c("  (preview only — re-run with --create to open the PR)\n", DIM)); return

    print(_c(f"  ↑ pushing {head}…", DIM))
    push = subprocess.run(["git", "push", "-u", "origin", head], capture_output=True, text=True)
    if push.returncode != 0:
        print(_c(f"  ✗ push failed: {push.stderr.strip()}", RED)); sys.exit(1)

    body = render_pr_body(pr, audit=audit)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body); body_file = f.name
    cmd = ["gh", "pr", "create", "--base", base, "--head", head,
           "--title", pr.title, "--body-file", body_file]
    if args.draft:
        cmd.append("--draft")
    print(_c("  🚀 opening PR via gh…", DIM))
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(body_file)
    if r.returncode == 0:
        print(_c(f"  ✓ {r.stdout.strip()}\n", GREEN))
    else:
        print(_c(f"  ✗ gh failed: {r.stderr.strip()}", RED)); sys.exit(1)


# ── verify: audit a commit (or PR) against its message ─────────────────────────
def _resolve_pr(url):
    """Return (diff_text, message) for a GitHub PR URL.

    The diff comes from the .diff endpoint; the message we audit against is the
    PR's title + body from the public API (best-effort — empty if unreachable).
    """
    diff_text = fetch_diff(url)
    message = ""
    m = _GH_PR.match(url.rstrip("/"))
    if m:
        repo, num = m.group(1), m.group(2)
        try:
            r = requests.get(
                f"https://api.github.com/repos/{repo}/pulls/{num}",
                timeout=30,
                headers={"User-Agent": "git-to-doc/1.0",
                         "Accept": "application/vnd.github+json"})
            if r.ok:
                j = r.json()
                message = f"{j.get('title') or ''}\n\n{j.get('body') or ''}".strip()
        except requests.RequestException:
            pass
    return diff_text, message


def _explain_ollama_error(e, models) -> str:
    """Map a run_audit exception to an actionable, human-readable hint."""
    name = type(e).__name__
    msg = str(e).strip()
    low = msg.lower()
    if name in ("ConnectError", "ConnectionError", "ConnectTimeout") or any(
            k in low for k in ("connection refused", "failed to establish",
                               "max retries", "cannot connect", "connect")):
        return ("Can't reach the ollama daemon — is it running?\n"
                "       start it:  ollama serve\n"
                "       install:   https://ollama.com/download")
    if getattr(e, "status_code", None) == 404 or any(
            k in low for k in ("not found", "try pulling", "no such model")):
        pulls = "\n".join(f"         ollama pull {m}" for m in models)
        return "A required model isn't installed locally. Pull it:\n" + pulls
    if "context length" in low or "longer than the context" in low:
        return ("The diff is too large for a model's context window. Try a model "
                "with a longer context, or audit a smaller commit.")
    return f"Audit failed ({name}): {msg}"


def cmd_verify(argv):
    parser = argparse.ArgumentParser(
        prog="git-to-doc verify",
        description="Audit a commit (or GitHub PR) against its message with a panel of models.")
    parser.add_argument("commit", nargs="?", default="HEAD", metavar="commit-sha",
        help="commit to audit (default: HEAD); ignored when --url is given")
    parser.add_argument("--auditors", metavar="m1,m2",
        help="comma-separated models to use instead of the default pair")
    parser.add_argument("--url", metavar="PR_URL",
        help="audit a GitHub PR URL instead of a local commit")
    parser.add_argument("--json", action="store_true",
        help="print merged divergences as JSON instead of pretty text")
    args = parser.parse_args(argv)

    auditors = None
    if args.auditors:
        auditors = [m.strip() for m in args.auditors.split(",") if m.strip()]
        if not auditors:
            print(_c("  ✗ --auditors was empty", RED)); sys.exit(1)

    # ── Resolve (diff, original message, source label) ──────────────────────────
    if args.url:
        try:
            diff_text, message = _resolve_pr(args.url)
        except requests.HTTPError as e:
            code = getattr(e.response, "status_code", "?")
            print(_c(f"  ✗ Could not fetch PR diff (HTTP {code}). Is the URL public?", RED)); sys.exit(1)
        except requests.RequestException as e:
            print(_c(f"  ✗ Network error fetching PR: {e}", RED)); sys.exit(1)
        source = args.url
    else:
        if subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True).returncode != 0:
            print(_c("  ✗ Not inside a git repository. cd into your repo, or pass --url.", RED)); sys.exit(1)
        sha = args.commit
        if not _ref_exists(sha):
            print(_c(f"  ✗ Commit '{sha}' not found in this repository.", RED)); sys.exit(1)
        # --format= strips the commit header so the message doesn't leak into the
        # diff — the auditor's first pass must stay blind to it.
        shown = _git("show", sha, "--format=", "--no-color", check=False)
        if shown.returncode != 0:
            print(_c(f"  ✗ Could not read commit '{sha}': {shown.stderr.strip()}", RED)); sys.exit(1)
        diff_text = shown.stdout
        message = _git("log", "-1", "--format=%B", sha, check=False).stdout.strip()
        source = _git("rev-parse", "--short", sha, check=False).stdout.strip() or sha

    if not diff_text.strip():
        print(_c(f"  ✗ No diff to audit for {source} (empty or a merge commit?).", RED)); sys.exit(1)

    used = auditors or auditor.DEFAULT_AUDITORS
    # Progress + warnings go to stderr so --json keeps stdout clean/parseable.
    if not message:
        print(_c("  ⚠ No original message found — auditing against an empty message.", YELLOW),
              file=sys.stderr)
    print(_c(f"  🔎 auditing {source} with {len(used)} model(s) — this can take a moment…", DIM),
          file=sys.stderr)

    try:
        reports = auditor.run_audit(diff_text, message, auditors=auditors)
    except Exception as e:
        print(_c("  ✗ " + _explain_ollama_error(e, used), RED), file=sys.stderr); sys.exit(1)

    merged = auditor.merge_audits(reports)

    if args.json:
        print(json.dumps([m.model_dump() for m in merged], indent=2))
        return
    print(render_audit_report(merged, message, used, source=source))


# ── doctor: hardware + model readiness ─────────────────────────────────────────
def cmd_doctor(argv):
    argparse.ArgumentParser(
        prog="git-to-doc doctor",
        description="Report RAM, installed models, and the recommended auditor pair."
    ).parse_args(argv)

    print(_c("\n  🩺  git-to-doc doctor", BOLD, CYAN))
    print(_c("  " + "─" * 52, DIM))

    try:
        import psutil
        gb = psutil.virtual_memory().total / (1024 ** 3)
        print(f"  RAM         : {_c(f'{gb:.0f} GB', BOLD)}")
    except Exception:
        print(f"  RAM         : {_c('unknown (pip install psutil)', YELLOW)}")

    rec = auditor.recommend_auditors()
    tier = next((t for t, models in auditor.AUDITOR_TIERS.items() if models == rec), "?")
    print(f"  Recommended : {_c(', '.join(rec), BOLD)}  {_c(f'({tier} tier)', DIM)}")

    r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if r.returncode != 0:
        print(_c("  Ollama      : ✗ can't reach ollama — is it installed and running?", RED))
        print(_c("                start it with `ollama serve`\n", DIM))
        return
    installed = {line.split()[0] for line in r.stdout.splitlines()[1:] if line.strip()}
    print(f"  Installed   : {_c(', '.join(sorted(installed)) or '(none)', DIM)}")

    missing = [m for m in rec if m not in installed]
    if missing:
        print(_c(f"\n  Pull {len(missing)} model(s) to use the recommended pair:", YELLOW))
        for m in missing:
            print(_c(f"      ollama pull {m}", YELLOW))
    else:
        print(_c("\n  ✓ Recommended auditors are installed — you're ready to verify.", BOLD, GREEN))
    print()


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
{_c("  git-to-doc", BOLD, CYAN)} {_c("— Conventional Commits, changelogs & PRs from git diffs, via Gemma", DIM)}

{_c("  COMMANDS", BOLD)}
    {_c("git-to-doc <input>", BOLD)} [--output md|json|both|stdout] [--model M]
        Generate a Conventional Commit message + changelog + plain-English summary.
        <input> = a GitHub PR URL, '-' for stdin, a .diff/.txt file, or a folder of .diff files.

    {_c("git-to-doc verify <commit-sha>", BOLD)} [--url PR] [--auditors m1,m2] [--json]
        Audit a commit (or GitHub PR) against its message with a panel of models,
        merging their findings into high/possible-confidence divergences.

    {_c("git-to-doc pull-request", BOLD)} [--base B] [--create] [--draft] [--skip-audit]
        Generate a pull request from the current branch, then audit the generated
        description against the diff. Preview by default; --create opens it via gh.

    {_c("git-to-doc doctor", BOLD)}
        Report RAM, installed Ollama models, and the recommended auditor pair.

    {_c("git-to-doc install-hook", BOLD)}
        Install a git hook so `git commit` (no -m) auto-fills the message.

{_c("  EXAMPLES", BOLD)}
    git-to-doc sample.diff
    git-to-doc https://github.com/pallets/flask/pull/5000 --output both
    git-to-doc pull-request --create

{_c("  Run", DIM)} {_c("git-to-doc <command> --help", BOLD)} {_c("for command-specific options.", DIM)}
""")


# ── Main dispatcher ───────────────────────────────────────────────────────────
def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        _top_help()
        return
    if argv[0] == "verify":
        return cmd_verify(argv[1:])
    if argv[0] == "doctor":
        return cmd_doctor(argv[1:])
    if argv[0] in ("pull-request", "pr"):
        return cmd_pr(argv[1:])
    if argv[0] == "install-hook":
        return cmd_install_hook(argv[1:])
    return cmd_doc(argv)


if __name__ == "__main__":
    main()
