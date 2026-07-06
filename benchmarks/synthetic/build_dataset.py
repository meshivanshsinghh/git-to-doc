#!/usr/bin/env python3
"""
build_dataset.py — synthetic corruption benchmark dataset builder.

Collects well-documented commits (via the GitHub API, from Flask/Django/requests/…)
and, for each, emits three variants used to measure the auditor's precision/recall:

  CONTROL     — original message intact           (tool should flag nothing)
  OMISSION    — one file-describing sentence cut   (tool should flag that file)
  TRUNCATION  — body dropped, subject only         (tool should flag that file)

For OMISSION/TRUNCATION we record the {file, line, description} the removed content
referred to, giving the eval single-label ground truth. Output: data/synthetic.jsonl.

CommitChronicle (JetBrains-Research/commit-chronicle on HuggingFace) is an alternative
source; we scrape GitHub here to avoid a heavy `datasets` dependency and keep the
harness self-contained. Set GITHUB_TOKEN to raise the API rate limit for large runs.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

DEFAULT_REPOS = ["pallets/flask", "django/django", "psf/requests", "pallets/click"]
API = "https://api.github.com"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"


def _headers():
    h = {"User-Agent": "git-to-doc-benchmark/1.0",
         "Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def list_commits(repo, per_page=100, max_pages=5):
    """Yield {sha, message, repo} from a repo's default branch (newest first)."""
    for page in range(1, max_pages + 1):
        r = requests.get(f"{API}/repos/{repo}/commits", headers=_headers(),
                         params={"per_page": per_page, "page": page}, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            print(f"  ! GitHub rate limit hit on {repo} — set GITHUB_TOKEN to raise it",
                  file=sys.stderr)
            return
        r.raise_for_status()
        batch = r.json()
        if not batch:
            return
        for c in batch:
            yield {"sha": c["sha"], "message": c["commit"]["message"], "repo": repo}


def fetch_diff(repo, sha):
    """Raw unified diff for a commit (codeload .diff URL — not API-rate-limited)."""
    r = requests.get(f"https://github.com/{repo}/commit/{sha}.diff",
                     headers={"User-Agent": "git-to-doc-benchmark/1.0"}, timeout=30)
    r.raise_for_status()
    return r.text


# ── Diff parsing ────────────────────────────────────────────────────────────────
_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.M)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", re.M)
_IDENT_RE = re.compile(r"(?:def|class)\s+(\w+)")

# Plant omissions only on source files: the auditor is designed to ignore docs/config
# (non-behavioral) changes, so a docs/.txt omission would penalize it for behaving as
# intended. Restricting ground truth to code files keeps the benchmark honest.
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".c",
             ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala",
             ".sh", ".pl", ".lua", ".m", ".mm"}


def is_code_file(path):
    return Path(path).suffix.lower() in CODE_EXTS


def parse_diff(diff):
    """Return {file_path: {start_line, symbols:set, stem, basename}} for changed files."""
    files = {}
    for part in re.split(r"(?=^diff --git )", diff, flags=re.M):
        m = _FILE_RE.search(part)
        if not m:
            continue
        path = m.group(2).strip()
        hunk = _HUNK_RE.search(part)
        files[path] = {
            "start_line": int(hunk.group(1)) if hunk else 1,
            "symbols": set(_IDENT_RE.findall(part)),
            "stem": Path(path).stem,
            "basename": Path(path).name,
        }
    return files


# ── Message parsing ───────────────────────────────────────────────────────────
def split_body_sentences(message):
    """Return (subject, [sentence, ...]); sentences come from the body (after line 1)."""
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    if not body:
        return subject, []
    raw = re.split(r"(?<=[.!?])\s+|\n[-*]\s+|\n\n", body)
    sentences = [s.strip(" -*\n\t") for s in raw if len(s.strip(" -*\n\t")) >= 20]
    return subject, sentences


def find_omission(sentences, files):
    """First sentence that references a changed file/symbol → (sentence, file, line, why)."""
    for sent in sentences:
        low = sent.lower()
        for path, info in files.items():
            if info["basename"].lower() in low:
                return sent, path, info["start_line"], "filename"
            stem = info["stem"].lower()
            if len(stem) >= 4 and re.search(rf"\b{re.escape(stem)}\b", low):
                return sent, path, info["start_line"], "stem"
            for sym in info["symbols"]:
                if len(sym) >= 4 and re.search(rf"\b{re.escape(sym)}\b", sent):
                    return sent, path, info["start_line"], f"symbol:{sym}"
    return None


def build_variants(commit, diff):
    """Three variant rows for a commit, or None if it can't yield clean ground truth."""
    files = {p: i for p, i in parse_diff(diff).items() if is_code_file(p)}
    if not files:
        return None
    subject, sentences = split_body_sentences(commit["message"])
    if not subject or len(sentences) < 2:
        return None
    found = find_omission(sentences, files)
    if not found:
        return None
    sent, path, line, _why = found

    base = {"commit_sha": commit["sha"], "repo": commit["repo"], "diff": diff,
            "original_message": commit["message"]}
    expected = {"file": path, "line": line, "description": sent}

    omission_msg = re.sub(r"\n{3,}", "\n\n", commit["message"].replace(sent, "", 1).strip())

    return [
        {**base, "corrupted_message": commit["message"],
         "corruption_type": "CONTROL", "expected_divergence": None},
        {**base, "corrupted_message": omission_msg,
         "corruption_type": "OMISSION", "expected_divergence": expected},
        {**base, "corrupted_message": subject,
         "corruption_type": "TRUNCATION", "expected_divergence": expected},
    ]


def main():
    ap = argparse.ArgumentParser(description="Build the synthetic corruption dataset.")
    ap.add_argument("--commits", type=int, default=200,
                    help="number of source commits to collect (default 200)")
    ap.add_argument("--repos", nargs="+", default=DEFAULT_REPOS, help="owner/name repos")
    ap.add_argument("--out", default=str(DATA_DIR / "synthetic.jsonl"))
    ap.add_argument("--max-diff-bytes", type=int, default=20000,
                    help="skip commits whose diff exceeds this (keeps audits tractable)")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    collected = rows = 0
    gens = [list_commits(r) for r in args.repos]
    exhausted = [False] * len(gens)
    with out_path.open("w", encoding="utf-8") as f:
        while collected < args.commits and not all(exhausted):
            for i, gen in enumerate(gens):
                if collected >= args.commits:
                    break
                if exhausted[i]:
                    continue
                try:
                    commit = next(gen)
                except StopIteration:
                    exhausted[i] = True
                    continue
                if "\n" not in commit["message"].strip():   # needs a body
                    continue
                try:
                    diff = fetch_diff(commit["repo"], commit["sha"])
                except requests.RequestException as e:
                    print(f"  ! diff fetch failed {commit['repo']}@{commit['sha'][:7]}: {e}",
                          file=sys.stderr)
                    continue
                if not diff.strip() or len(diff) > args.max_diff_bytes:
                    continue
                variants = build_variants(commit, diff)
                if not variants:
                    continue
                for v in variants:
                    f.write(json.dumps(v) + "\n")
                    rows += 1
                collected += 1
                print(f"  ✓ [{collected}/{args.commits}] {commit['repo']}@{commit['sha'][:7]}"
                      f"  omission→ {variants[1]['expected_divergence']['file']}")
                time.sleep(0.2)   # be polite to codeload

    print(f"\n  Wrote {rows} rows ({collected} commits × 3) → {out_path}")
    if collected < args.commits:
        print(f"  (only {collected} qualifying commits found; add --repos or a bigger "
              "page budget, and set GITHUB_TOKEN)", file=sys.stderr)


if __name__ == "__main__":
    main()
