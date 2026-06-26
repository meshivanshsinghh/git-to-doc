#!/usr/bin/env python3
"""
compare.py — Benchmark git-to-doc across multiple diffs or models.

Usage:
  python compare.py <diff1> [diff2 ...] [--models m1 m2]
  python compare.py ./diffs/ --models gemma4 llama3

Examples:
  python compare.py sample.diff
  python compare.py sample.diff https://github.com/pallets/flask/pull/5000
  python compare.py ./diffs/ --models gemma4
"""

import sys, argparse, time, json
from pathlib import Path
from typing import List

import requests

from model import analyze_diff, CommitDoc

# ── ANSI helpers ─────────────────────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
RED = "\033[31m"; CYAN = "\033[36m"; DIM = "\033[2m"
YELLOW = "\033[33m"; WHITE = "\033[97m"

def _c(t, *c): return "".join(c) + t + RESET


# ── Fetch / read diff ─────────────────────────────────────────────────────────
def load_diff(source: str) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        url = source.rstrip("/")
        if not url.endswith(".diff"):
            url += ".diff"
        resp = requests.get(url, timeout=30, headers={"User-Agent": "git-to-doc/1.0"})
        resp.raise_for_status()
        return resp.text
    return Path(source).read_text(encoding="utf-8")


# ── Benchmark single diff against one model ───────────────────────────────────
def benchmark(diff_text: str, label: str, model: str) -> dict:
    t0 = time.time()
    result = analyze_diff(diff_text, model=model)
    elapsed = time.time() - t0
    return {
        "label":    label,
        "model":    model,
        "elapsed":  round(elapsed, 2),
        "type":     result.type,
        "scope":    result.scope,
        "subject":  result.subject,
        "breaking": result.breaking,
        "doc":      result,
    }


# ── Pretty table ──────────────────────────────────────────────────────────────
def print_table(results: list):
    print()
    print(_c("  " + "─" * 78, DIM))
    print(_c(f"  {'SOURCE':<28} {'MODEL':<12} {'TIME':>6}  {'TYPE':<10} SUBJECT", BOLD, CYAN))
    print(_c("  " + "─" * 78, DIM))
    for r in results:
        label   = r["label"][:27]
        model   = r["model"][:11]
        elapsed = f"{r['elapsed']}s"
        typ     = r["type"]
        subject = r["subject"][:38]
        color   = GREEN if r["elapsed"] < 30 else YELLOW
        print(f"  {label:<28} {_c(model, DIM):<12} {_c(elapsed, color):>6}  {_c(typ, BOLD):<10} {subject}")
    print(_c("  " + "─" * 78, DIM))
    print()

    if len(results) > 1:
        fastest = min(results, key=lambda r: r["elapsed"])
        print(_c(f"  ⚡ Fastest: {fastest['model']} on '{fastest['label']}' "
                 f"({fastest['elapsed']}s)", BOLD, GREEN))
        print()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Benchmark git-to-doc across multiple diffs and/or models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("inputs", nargs="+",
        help="One or more diff files, URLs, or a folder")
    parser.add_argument("--models", nargs="+", default=["gemma4"],
        help="One or more Ollama model names to compare (default: gemma4)")
    parser.add_argument("--output", action="store_true",
        help="Save a compare_results.json summary file")
    args = parser.parse_args()

    # Expand folders to .diff files
    sources = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            found = sorted(p.glob("**/*.diff"))
            if not found:
                print(_c(f"  ✗ No .diff files in {inp}", RED))
                sys.exit(1)
            sources.extend(str(f) for f in found)
        else:
            sources.append(inp)

    # ── Banner ────────────────────────────────────────────────────────────────
    print(_c("\n  🔬  git-to-doc  compare", BOLD, CYAN))
    print(_c(f"  {len(sources)} source(s)  ×  {len(args.models)} model(s)"
             f"  =  {len(sources) * len(args.models)} run(s)", DIM))
    print(_c("  " + "─" * 52, DIM))

    # ── Run benchmarks ────────────────────────────────────────────────────────
    results = []
    for source in sources:
        label = source.split("/")[-1][:27]
        try:
            print(_c(f"\n  Loading: {source}", DIM))
            diff_text = load_diff(source)
        except Exception as e:
            print(_c(f"  ✗ Failed to load {source}: {e}", RED))
            continue

        for model in args.models:
            print(_c(f"  ⏳ [{model}] {label}…", DIM), end="", flush=True)
            try:
                r = benchmark(diff_text, label, model)
                results.append(r)
                print(_c(f"  {r['elapsed']}s", GREEN))
            except Exception as e:
                print(_c(f"  ✗ Error: {e}", RED))

    if not results:
        print(_c("\n  No results to display.", RED))
        sys.exit(1)

    # ── Results table ─────────────────────────────────────────────────────────
    print_table(results)

    # ── Per-result detail ─────────────────────────────────────────────────────
    for r in results:
        doc = r["doc"]
        print(_c(f"  [{r['model']}] {r['label']}", BOLD))
        print(f"    Commit : {_c(doc.type + (f'({doc.scope})' if doc.scope else '') + ': ' + doc.subject, WHITE)}")
        print(f"    Summary: {doc.plain_english[:120]}")
        print()

    # ── Save JSON summary ─────────────────────────────────────────────────────
    if args.output:
        out = [
            {k: v for k, v in r.items() if k != "doc"}
            for r in results
        ]
        Path("compare_results.json").write_text(json.dumps(out, indent=2))
        print(_c("  ✓ Saved compare_results.json", GREEN))


if __name__ == "__main__":
    main()
