#!/usr/bin/env python3
"""
run_eval.py — run the audit engine against the synthetic dataset and score it.

Loads data/synthetic.jsonl, audits each (diff, corrupted_message) with the default
auditor panel, compares the flagged divergences to the recorded ground truth, and
computes precision / recall / F1 / false-positive-rate (overall and by corruption
type). Writes results/{timestamp}_{model_pair}.json and prints a summary.

Ground truth is single-label (one planted omission per corrupted commit), so:
  - a corrupted entry is a TRUE POSITIVE if a flagged divergence lands on the planted
    file (basename match); otherwise a FALSE NEGATIVE.
  - a CONTROL entry (message intact) is a FALSE POSITIVE if anything is flagged.
  - precision = TP / (TP + FP);  recall = TP / (TP + FN);  FPR = FP / N_control.
Extra unlabeled flags on corrupted entries are neither credited nor penalized.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from git_to_doc.auditor import run_audit, merge_audits, DEFAULT_AUDITORS

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "synthetic.jsonl"
RESULTS_DIR = HERE / "results"


def _basename(p):
    return p.rsplit("/", 1)[-1].lower()


def caught(divergences, expected):
    """Did any flagged divergence land on the expected file (basename match)?"""
    if not expected:
        return False
    want = _basename(expected["file"])
    return any(_basename(d.file) == want for d in divergences)


def evaluate(entries, auditors, confidence):
    """Audit each entry; return per-entry records (errors captured, not fatal)."""
    records = []
    for i, e in enumerate(entries):
        rec = {"commit_sha": e["commit_sha"], "repo": e["repo"],
               "corruption_type": e["corruption_type"],
               "expected": e.get("expected_divergence")}
        try:
            merged = merge_audits(run_audit(e["diff"], e["corrupted_message"],
                                            auditors=auditors))
            flagged = [m for m in merged if m.confidence == "high"] \
                if confidence == "high" else list(merged)
            rec.update(
                n_flagged=len(flagged),
                flagged=[{"file": m.file, "line": m.line, "confidence": m.confidence}
                         for m in flagged],
                caught=caught(flagged, e.get("expected_divergence")),
            )
        except Exception as ex:   # noqa: BLE001 — one bad audit shouldn't kill a long run
            rec.update(n_flagged=0, flagged=[], caught=False, error=str(ex))
        records.append(rec)
        tag = "ERROR" if rec.get("error") else f"flagged={rec['n_flagged']} caught={rec['caught']}"
        print(f"  [{i+1}/{len(entries)}] {e['corruption_type']:<10} "
              f"{e['repo']}@{e['commit_sha'][:7]}  {tag}", file=sys.stderr)
    return records


def _f1(p, r):
    return round(2 * p * r / (p + r), 4) if (p + r) else 0.0


def compute_metrics(records):
    valid = [r for r in records if not r.get("error")]
    n_errors = len(records) - len(valid)

    corrupted = [r for r in valid if r["corruption_type"] in ("OMISSION", "TRUNCATION")]
    controls = [r for r in valid if r["corruption_type"] == "CONTROL"]

    tp = sum(1 for r in corrupted if r["caught"])
    fn = len(corrupted) - tp
    fp = sum(1 for r in controls if r["n_flagged"] > 0)
    tn = len(controls) - fp

    precision = round(tp / (tp + fp), 4) if (tp + fp) else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) else 0.0
    fpr = round(fp / len(controls), 4) if controls else 0.0

    def recall_for(ctype):
        rs = [r for r in valid if r["corruption_type"] == ctype]
        c = sum(1 for r in rs if r["caught"])
        return {"recall": round(c / len(rs), 4) if rs else 0.0, "n": len(rs), "caught": c}

    return {
        "precision": precision, "recall": recall, "f1": _f1(precision, recall), "fpr": fpr,
        "counts": {"tp": tp, "fn": fn, "fp": fp, "tn": tn,
                   "n_corrupted": len(corrupted), "n_control": len(controls),
                   "n_errors": n_errors},
        "by_corruption_type": {
            "OMISSION": recall_for("OMISSION"),
            "TRUNCATION": recall_for("TRUNCATION"),
            "CONTROL": {"fpr": fpr, "n": len(controls), "flagged": fp},
        },
    }


def print_summary(results):
    m, bt = results["metrics"], results["metrics"]["by_corruption_type"]
    pct = lambda x: round(x * 100)
    print()
    print(f"  Synthetic Corruption Benchmark — {results['date']}")
    print(f"  Auditors: {' + '.join(results['auditors'])}")
    print()
    print(f"  Precision: {pct(m['precision']):>3}%  "
          f"(of divergences flagged, {pct(m['precision'])}% were real)")
    print(f"  Recall:    {pct(m['recall']):>3}%  "
          f"(of real omissions, we caught {pct(m['recall'])}%)")
    print(f"  FPR:       {pct(m['fpr']):>3}%  "
          f"(on unmodified commits, we falsely flagged {pct(m['fpr'])}%)")
    print()
    print("  By corruption type:")
    print(f"    OMISSION:   {pct(bt['OMISSION']['recall']):>3}% recall")
    print(f"    TRUNCATION: {pct(bt['TRUNCATION']['recall']):>3}% recall")
    c = m["counts"]
    print()
    print(f"  ({results['confidence']}-confidence · {results['n_evaluated']} entries · "
          f"tp={c['tp']} fp={c['fp']} fn={c['fn']} errors={c['n_errors']})")
    print()


def main():
    ap = argparse.ArgumentParser(description="Evaluate the auditor on the synthetic dataset.")
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--limit", type=int, default=None, help="cap entries (for smoke tests)")
    ap.add_argument("--auditors", help="comma-separated model override")
    ap.add_argument("--confidence", choices=["high", "any"], default="high",
                    help="which divergences count as flagged (default: high)")
    args = ap.parse_args()

    auditors = [m.strip() for m in args.auditors.split(",") if m.strip()] if args.auditors else None
    used = auditors or DEFAULT_AUDITORS

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"  ✗ dataset not found: {data_path}\n    build it first: "
              "python benchmarks/synthetic/build_dataset.py --commits 10", file=sys.stderr)
        sys.exit(1)
    entries = [json.loads(l) for l in data_path.read_text().splitlines() if l.strip()]
    if args.limit:
        entries = entries[:args.limit]
    if not entries:
        print("  ✗ no entries to evaluate", file=sys.stderr); sys.exit(1)

    print(f"  Evaluating {len(entries)} entries with {', '.join(used)}…", file=sys.stderr)
    records = evaluate(entries, auditors, args.confidence)
    metrics = compute_metrics(records)

    now = datetime.now()
    model_pair = "__".join(m.replace(":", "-").replace("/", "-") for m in used)
    results = {
        "date": now.strftime("%Y-%m-%d"),
        "timestamp": now.isoformat(timespec="seconds"),
        "auditors": used, "model_pair": model_pair, "confidence": args.confidence,
        "n_evaluated": len(records), "metrics": metrics, "per_entry": records,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{now.strftime('%Y-%m-%dT%H-%M-%S')}_{model_pair}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"  ✓ wrote {out}", file=sys.stderr)

    print_summary(results)


if __name__ == "__main__":
    main()
