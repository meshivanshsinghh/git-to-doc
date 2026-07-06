#!/usr/bin/env python3
"""
compare.py — Benchmark git-to-doc across diffs and/or models.

Without --judge: a fast timing table (how quick each model is).
With --judge MODEL: also runs the deterministic Conventional Commit check and an
LLM-as-judge rubric score, so you get quality + a hard CC pass-rate, not just speed.

Usage:
  git-to-doc-compare <diff1> [diff2 ...] [--models m1 m2] [--judge gpt-oss:120b]
  git-to-doc-compare ./diffs/ --models gemma3:4b gemma3:12b --judge gpt-oss:120b
"""

import sys, argparse, time, json
from pathlib import Path

import requests

from git_to_doc.model import analyze_diff
from git_to_doc.renderer import render_markdown_file
from git_to_doc.validate import validate_commit
from git_to_doc._internal.evaluate import judge_response, DEFAULT_JUDGE

RESET = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
RED = "\033[31m"; CYAN = "\033[36m"; DIM = "\033[2m"
YELLOW = "\033[33m"; WHITE = "\033[97m"

def _c(t, *c): return "".join(c) + t + RESET


def load_diff(source: str) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        url = source.rstrip("/")
        if not url.endswith(".diff"):
            url += ".diff"
        resp = requests.get(url, timeout=30, headers={"User-Agent": "git-to-doc/1.0"})
        resp.raise_for_status()
        return resp.text
    return Path(source).read_text(encoding="utf-8")


def benchmark(diff_text: str, label: str, model: str, judge: str = None) -> dict:
    t0 = time.time()
    result = analyze_diff(diff_text, model=model)
    elapsed = round(time.time() - t0, 2)
    row = {
        "label": label, "model": model, "elapsed": elapsed,
        "type": result.type, "scope": result.scope, "subject": result.subject,
        "breaking": result.breaking, "doc": result,
        "cc_ok": not validate_commit(result),   # deterministic, zero-variance
    }
    if judge:
        md = render_markdown_file(result, model=model)
        row["score"] = judge_response(md, diff_text, judge)["overall100"]
    return row


def print_table(results: list, judged: bool):
    has_score = judged and any("score" in r for r in results)
    print()
    print(_c("  " + "─" * 86, DIM))
    head = f"  {'SOURCE':<24} {'MODEL':<12} {'TIME':>6}  {'CC':>3}"
    if has_score:
        head += f"  {'SCORE':>6}"
    head += "  TYPE/SUBJECT"
    print(_c(head, BOLD, CYAN))
    print(_c("  " + "─" * 86, DIM))
    for r in results:
        elapsed = f"{r['elapsed']}s"
        color = GREEN if r["elapsed"] < 30 else YELLOW
        cc = _c("✓", GREEN) if r.get("cc_ok") else _c("✗", RED)
        line = f"  {r['label'][:23]:<24} {_c(r['model'][:11], DIM):<12} {_c(elapsed, color):>6}  {cc:>3}"
        if has_score:
            line += f"  {r.get('score', '—'):>6}"
        line += f"  {_c(r['type'], BOLD)}: {r['subject'][:36]}"
        print(line)
    print(_c("  " + "─" * 86, DIM))
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark git-to-doc across diffs and/or models.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("inputs", nargs="+", help="diff files, URLs, or a folder")
    parser.add_argument("--models", nargs="+", default=["gemma4"],
        help="one or more Ollama models to compare (default: gemma4)")
    parser.add_argument("--judge", nargs="?", const=DEFAULT_JUDGE, default=None,
        metavar="MODEL", help="also score quality with an LLM judge (default judge: %s)" % DEFAULT_JUDGE)
    parser.add_argument("--output", action="store_true", help="save compare_results.json")
    args = parser.parse_args()

    sources = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            found = sorted(p.glob("**/*.diff"))
            if not found:
                print(_c(f"  ✗ No .diff files in {inp}", RED)); sys.exit(1)
            sources.extend(str(f) for f in found)
        else:
            sources.append(inp)

    print(_c("\n  🔬  git-to-doc  compare", BOLD, CYAN))
    judging = f"  ·  judge: {args.judge}" if args.judge else ""
    print(_c(f"  {len(sources)} source(s) × {len(args.models)} model(s)"
             f"  =  {len(sources) * len(args.models)} run(s){judging}", DIM))
    print(_c("  " + "─" * 52, DIM))

    results = []
    for source in sources:
        label = source.split("/")[-1][:23]
        try:
            print(_c(f"\n  Loading: {source}", DIM))
            diff_text = load_diff(source)
        except Exception as e:
            print(_c(f"  ✗ Failed to load {source}: {e}", RED)); continue
        for model in args.models:
            print(_c(f"  ⏳ [{model}] {label}…", DIM), end="", flush=True)
            try:
                r = benchmark(diff_text, label, model, judge=args.judge)
                results.append(r)
                extra = f"  score {r['score']}" if "score" in r else ""
                print(_c(f"  {r['elapsed']}s{extra}", GREEN))
            except Exception as e:
                print(_c(f"  ✗ Error: {e}", RED))

    if not results:
        print(_c("\n  No results to display.", RED)); sys.exit(1)

    print_table(results, judged=bool(args.judge))

    if args.output:
        out = [{k: v for k, v in r.items() if k != "doc"} for r in results]
        Path("compare_results.json").write_text(json.dumps(out, indent=2))
        print(_c("  ✓ Saved compare_results.json", GREEN))


if __name__ == "__main__":
    main()
