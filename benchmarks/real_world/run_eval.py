#!/usr/bin/env python3
"""
run_eval.py — real-world benchmark: audit harvested AI-authored commits.

There is no ground truth here (nothing was corrupted), so precision/recall can't be
computed directly. Instead we report population statistics:
  a. divergence rate — % of commits with >=1 HIGH-confidence divergence
  b. inter-auditor agreement — % of all flagged divergences that are high-confidence
     (i.e. both auditors independently agreed) — the credibility metric
  c. divergences-per-commit distribution
…broken down by AI tool (Copilot / Claude / Cursor / Devin / Jules).
Writes results/{timestamp}_{model_pair}.json.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from git_to_doc.auditor import run_audit, merge_audits, DEFAULT_AUDITORS

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "real_world.jsonl"
RESULTS_DIR = HERE / "results"


def evaluate(entries, auditors):
    records = []
    for i, e in enumerate(entries):
        rec = {"commit_sha": e["commit_sha"], "repo": e["repo"], "ai_tool": e["ai_tool"]}
        try:
            merged = merge_audits(run_audit(e["diff"], e["original_message"], auditors=auditors))
            rec.update(
                n_divergences=len(merged),
                n_high=sum(1 for m in merged if m.confidence == "high"),
                flagged=[{"file": m.file, "line": m.line, "confidence": m.confidence}
                         for m in merged],
            )
        except Exception as ex:   # noqa: BLE001 — one bad audit shouldn't kill a long run
            rec.update(n_divergences=0, n_high=0, flagged=[], error=str(ex))
        records.append(rec)
        tag = "ERROR" if rec.get("error") else f"div={rec['n_divergences']} high={rec['n_high']}"
        print(f"  [{i+1}/{len(entries)}] {e['ai_tool']:<8} {e['repo']}@{e['commit_sha'][:7]}  {tag}",
              file=sys.stderr)
    return records


def _stats(records):
    valid = [r for r in records if not r.get("error")]
    n = len(valid)
    total_div = sum(r["n_divergences"] for r in valid)
    total_high = sum(r["n_high"] for r in valid)
    return {
        "n": n, "n_errors": len(records) - n,
        "divergence_rate": round(sum(1 for r in valid if r["n_high"] > 0) / n, 4) if n else 0.0,
        "inter_auditor_agreement": round(total_high / total_div, 4) if total_div else 0.0,
        "divergences_per_commit": {
            "mean": round(total_div / n, 3) if n else 0.0,
            "distribution": dict(sorted(Counter(r["n_divergences"] for r in valid).items())),
        },
        "totals": {"divergences": total_div, "high": total_high},
    }


def compute_metrics(records):
    by_tool = defaultdict(list)
    for r in records:
        by_tool[r["ai_tool"]].append(r)
    return {"overall": _stats(records),
            "by_tool": {tool: _stats(rs) for tool, rs in sorted(by_tool.items())}}


def print_summary(results):
    o = results["metrics"]["overall"]
    pct = lambda x: round(x * 100)
    print()
    print(f"  Real-World Benchmark — {results['date']}")
    print(f"  Auditors: {' + '.join(results['auditors'])}   ({o['n']} commits)")
    print()
    print(f"  Divergence rate:         {pct(o['divergence_rate']):>3}%  "
          "(commits with >=1 high-confidence divergence)")
    print(f"  Inter-auditor agreement: {pct(o['inter_auditor_agreement']):>3}%  "
          "(of all flags, both auditors agreed)")
    print(f"  Divergences / commit:    {o['divergences_per_commit']['mean']}")
    print()
    print("  By AI tool:")
    for tool, s in results["metrics"]["by_tool"].items():
        print(f"    {tool:<9} n={s['n']:<3}  div-rate={pct(s['divergence_rate']):>3}%  "
              f"agreement={pct(s['inter_auditor_agreement']):>3}%")
    print()


def main():
    ap = argparse.ArgumentParser(description="Real-world benchmark eval.")
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--limit", type=int, default=None, help="cap entries (for smoke tests)")
    ap.add_argument("--auditors", help="comma-separated model override")
    args = ap.parse_args()

    auditors = [m.strip() for m in args.auditors.split(",") if m.strip()] if args.auditors else None
    used = auditors or DEFAULT_AUDITORS

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"  ✗ dataset not found: {data_path}\n    harvest first: "
              "GITHUB_TOKEN=… python benchmarks/real_world/harvest.py", file=sys.stderr)
        sys.exit(1)
    entries = [json.loads(l) for l in data_path.read_text().splitlines() if l.strip()]
    if args.limit:
        entries = entries[:args.limit]
    if not entries:
        print("  ✗ no entries", file=sys.stderr); sys.exit(1)

    print(f"  Evaluating {len(entries)} entries with {', '.join(used)}…", file=sys.stderr)
    records = evaluate(entries, auditors)
    metrics = compute_metrics(records)

    now = datetime.now()
    model_pair = "__".join(m.replace(":", "-").replace("/", "-") for m in used)
    results = {"date": now.strftime("%Y-%m-%d"), "timestamp": now.isoformat(timespec="seconds"),
               "auditors": used, "model_pair": model_pair,
               "n_evaluated": len(records), "metrics": metrics, "per_entry": records}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{now.strftime('%Y-%m-%dT%H-%M-%S')}_{model_pair}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"  ✓ wrote {out}", file=sys.stderr)

    print_summary(results)


if __name__ == "__main__":
    main()
