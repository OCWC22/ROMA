#!/usr/bin/env python3
"""
OfficeQA Benchmark Harness

Clean benchmark comparing five methods on held-out OfficeQA data:
  A. Prompt Baseline — fixed strong prompt
  B. GEPA Prompt-Optimized — evolved system prompt via gepa.optimize()
  C. ROMA-lite — decomposition pipeline + verifier
  D. RLM-lite — recursive reasoning pipeline
  E. DSPy Baseline — structured two-stage program

Key guarantees:
  - GEPA optimization sees only train
  - Candidate selection uses val
  - Final metrics report only test
  - Same corpus policy for all methods
  - Same scorer for all methods
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# Ensure benchmarks package is importable
BENCHMARKS_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCHMARKS_ROOT.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.officeqa.methods.base import (
    OfficeQAQuestion, SolverResult, load_officeqa_benchmark,
    load_source_documents, make_splits, save_splits, score_answer,
)
from benchmarks.officeqa.scripts.question_typing import classify_question
from benchmarks.officeqa.scripts.failure_analysis import (
    classify_failure, generate_failure_notes,
)

# Method registry
METHOD_CLASSES = {}


def register_methods():
    """Lazy import to avoid loading unused methods."""
    from benchmarks.officeqa.methods.prompt_baseline import PromptBaselineSolver
    from benchmarks.officeqa.methods.gepa_prompt import GEPAPromptSolver
    from benchmarks.officeqa.methods.roma_lite import ROMALiteSolver
    from benchmarks.officeqa.methods.rlm_lite import RLMLiteSolver
    from benchmarks.officeqa.methods.dspy_baseline import DSPyBaselineSolver

    METHOD_CLASSES["prompt_baseline"] = PromptBaselineSolver
    METHOD_CLASSES["gepa_prompt"] = GEPAPromptSolver
    METHOD_CLASSES["roma_lite"] = ROMALiteSolver
    METHOD_CLASSES["rlm_lite"] = RLMLiteSolver
    METHOD_CLASSES["dspy_baseline"] = DSPyBaselineSolver


def run_benchmark(args):
    register_methods()

    # ----------------------------------------------------------------
    # Load data
    # ----------------------------------------------------------------
    print("=" * 70)
    print("OFFICEQA BENCHMARK HARNESS")
    print("=" * 70)

    print(f"\nLoading OfficeQA {args.subset}...")
    questions = load_officeqa_benchmark(subset=args.subset, limit=args.limit)
    print(f"Loaded {len(questions)} questions")

    # Tag question types
    for q in questions:
        q.question_type = classify_question(q.question)

    # ----------------------------------------------------------------
    # Splits: train / val / test
    # ----------------------------------------------------------------
    if args.debug:
        train_size, val_size = 5, 5
    else:
        train_size, val_size = args.train_size, args.val_size

    train, val, test = make_splits(questions, train_size, val_size, seed=args.split_seed)

    print(f"\nSplits (seed={args.split_seed}):")
    print(f"  train: {len(train)}")
    print(f"  val:   {len(val)}")
    print(f"  test:  {len(test)}")

    # Save splits
    splits_dir = BENCHMARKS_ROOT / "data_splits"
    save_splits(train, val, test, splits_dir)
    print(f"  Saved UIDs to {splits_dir}/")

    if len(test) == 0:
        print("\nERROR: No test questions. Increase --limit or reduce train/val sizes.")
        sys.exit(1)

    # ----------------------------------------------------------------
    # Corpus policy
    # ----------------------------------------------------------------
    corpus_dir = Path(args.corpus_dir) if args.corpus_dir else None
    modes = []
    if args.mode in ("with_corpus", "both"):
        modes.append(("with_corpus", corpus_dir))
    if args.mode in ("no_corpus", "both"):
        modes.append(("no_corpus", None))

    # ----------------------------------------------------------------
    # Parse methods
    # ----------------------------------------------------------------
    method_names = [m.strip() for m in args.methods.split(",")]
    for m in method_names:
        if m not in METHOD_CLASSES:
            print(f"ERROR: Unknown method '{m}'. Available: {list(METHOD_CLASSES.keys())}")
            sys.exit(1)

    # ----------------------------------------------------------------
    # Run benchmark for each corpus mode
    # ----------------------------------------------------------------
    all_run_results = {}

    for mode_name, mode_corpus_dir in modes:
        print(f"\n{'=' * 70}")
        print(f"MODE: {mode_name}")
        print(f"{'=' * 70}")

        # Initialize solvers
        solvers = {}
        for m in method_names:
            cls = METHOD_CLASSES[m]
            if m == "gepa_prompt":
                solver = cls(model=args.model, cli=args.cli, corpus_dir=mode_corpus_dir)
            else:
                solver = cls(model=args.model, cli=args.cli)
            solvers[m] = solver

        # ----------------------------------------------------------------
        # GEPA optimization (train only, val for selection)
        # ----------------------------------------------------------------
        if "gepa_prompt" in solvers and args.optimize:
            print(f"\n--- GEPA Prompt Optimization ---")
            print(f"  Using train ({len(train)} qs) for optimization")
            print(f"  Using val ({len(val)} qs) for candidate selection")
            solvers["gepa_prompt"].optimize(
                trainset=train,
                valset=val,
                max_metric_calls=args.optimize_budget,
            )
            # Save prompts
            prompts_dir = BENCHMARKS_ROOT / "prompts"
            solvers["gepa_prompt"].save_prompts(prompts_dir)
            print(f"  Prompts saved to {prompts_dir}/")

        # ----------------------------------------------------------------
        # Evaluate on TEST only
        # ----------------------------------------------------------------
        print(f"\n--- Evaluating on test set ({len(test)} questions) ---")

        results_by_method = {m: [] for m in method_names}

        for i, q in enumerate(test):
            print(f"\n  Q{i+1}/{len(test)} [{q.uid}] ({q.question_type}): {q.question[:60]}...")
            print(f"  Expected: {q.answer}")

            # Load context (same for all methods in this mode)
            if mode_corpus_dir:
                context = load_source_documents(q.source_files, mode_corpus_dir)
            else:
                context = ""

            for m in method_names:
                solver = solvers[m]
                print(f"    [{m}] ", end="", flush=True)
                try:
                    result = solver.solve(q, context=context)
                except Exception as e:
                    result = SolverResult(
                        method=m, predicted="", expected=q.answer,
                        error=str(e), raw_output=f"ERROR: {e}",
                    )

                # Enrich with failure analysis
                failure_type = classify_failure(
                    q.question, result.predicted, q.answer, result.raw_output, result.score,
                )
                failure_notes = ""
                if failure_type:
                    failure_notes = generate_failure_notes(
                        q.question, result.predicted, q.answer, result.raw_output, failure_type,
                    )

                # Attach metadata
                result.trace["question_uid"] = q.uid
                result.trace["question_type"] = q.question_type
                result.trace["failure_type"] = failure_type
                result.trace["failure_notes"] = failure_notes

                results_by_method[m].append(result)

                status = "OK" if result.score > 0 else "WRONG"
                print(f"{status} | {result.predicted[:50]} ({result.duration:.1f}s)")

        all_run_results[mode_name] = results_by_method

    # ----------------------------------------------------------------
    # Compute and print summary
    # ----------------------------------------------------------------
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for mode_name, results_by_method in all_run_results.items():
        print(f"\n{'=' * 70}")
        print(f"RESULTS — {mode_name}")
        print(f"{'=' * 70}")

        summary = compute_summary(results_by_method)
        print_summary(summary)

        # Per question-type breakdown
        type_breakdown = compute_per_type_accuracy(results_by_method)
        print_type_breakdown(type_breakdown)

        # Failure analysis
        failure_counts = compute_failure_counts(results_by_method)
        print_failure_counts(failure_counts)

        # Save results
        run_id = f"run_{int(time.time())}"
        save_results(
            output_dir, run_id, mode_name,
            summary, results_by_method, type_breakdown, failure_counts,
        )
        print(f"\nResults saved to {output_dir}/{run_id}_*")


# ============================================================================
# METRICS
# ============================================================================

def compute_summary(results_by_method):
    summary = {}
    for method, results in results_by_method.items():
        total = len(results)
        if total == 0:
            continue
        correct = sum(1 for r in results if r.score > 0)
        durations = [r.duration for r in results]
        errors = sum(1 for r in results if r.error)
        format_ok = sum(1 for r in results if r.predicted and len(r.predicted) < 100)

        summary[method] = {
            "total": total,
            "correct": correct,
            "accuracy": correct / total,
            "avg_latency": statistics.mean(durations),
            "median_latency": statistics.median(durations),
            "error_rate": errors / total,
            "format_compliance": format_ok / total,
        }
    return summary


def compute_per_type_accuracy(results_by_method):
    breakdown = {}
    for method, results in results_by_method.items():
        by_type = {}
        for r in results:
            qt = r.trace.get("question_type", "other")
            if qt not in by_type:
                by_type[qt] = {"correct": 0, "total": 0}
            by_type[qt]["total"] += 1
            if r.score > 0:
                by_type[qt]["correct"] += 1
        for qt in by_type:
            by_type[qt]["accuracy"] = by_type[qt]["correct"] / by_type[qt]["total"]
        breakdown[method] = by_type
    return breakdown


def compute_failure_counts(results_by_method):
    counts = {}
    for method, results in results_by_method.items():
        fc = {}
        for r in results:
            ft = r.trace.get("failure_type")
            if ft:
                fc[ft] = fc.get(ft, 0) + 1
        counts[method] = fc
    return counts


# ============================================================================
# PRINTING
# ============================================================================

def print_summary(summary):
    header = f"{'Method':<18} {'Acc':>7} {'Avg(s)':>8} {'Med(s)':>8} {'Err%':>7} {'Fmt%':>7}"
    print(f"\n{header}")
    print("-" * len(header))
    for method, s in summary.items():
        print(
            f"{method:<18} {s['accuracy']*100:>6.1f}% "
            f"{s['avg_latency']:>7.1f}s {s['median_latency']:>7.1f}s "
            f"{s['error_rate']*100:>6.1f}% {s['format_compliance']*100:>6.1f}%"
        )


def print_type_breakdown(breakdown):
    print("\nPer question-type accuracy:")
    # Collect all types
    all_types = set()
    for method_types in breakdown.values():
        all_types.update(method_types.keys())

    methods = list(breakdown.keys())
    header = f"  {'Type':<25}" + "".join(f" {m:>15}" for m in methods)
    print(header)
    print("  " + "-" * (len(header) - 2))

    for qt in sorted(all_types):
        row = f"  {qt:<25}"
        for m in methods:
            info = breakdown[m].get(qt, {"correct": 0, "total": 0, "accuracy": 0})
            row += f" {info['correct']}/{info['total']:>2} ({info['accuracy']*100:4.0f}%)"
        print(row)


def print_failure_counts(counts):
    print("\nFailure types:")
    for method, fc in counts.items():
        if not fc:
            print(f"  {method}: no failures")
            continue
        items = sorted(fc.items(), key=lambda x: -x[1])
        print(f"  {method}:")
        for ft, count in items:
            print(f"    {ft}: {count}")


# ============================================================================
# SAVING
# ============================================================================

def save_results(output_dir, run_id, mode_name, summary, results_by_method, type_breakdown, failure_counts):
    prefix = f"{run_id}_{mode_name}"

    # Summary
    with open(output_dir / f"{prefix}_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    # Detailed per-question results
    detailed = {}
    for method, results in results_by_method.items():
        detailed[method] = [r.to_dict() for r in results]
    with open(output_dir / f"{prefix}_detailed.json", "w") as f:
        json.dump(detailed, f, indent=2, default=str)

    # Failure analysis
    with open(output_dir / f"{prefix}_failures.json", "w") as f:
        json.dump({
            "failure_counts": failure_counts,
            "type_breakdown": type_breakdown,
        }, f, indent=2, default=str)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OfficeQA Benchmark: Prompt Baseline vs GEPA vs ROMA-lite vs RLM-lite vs DSPy"
    )
    parser.add_argument("--methods", type=str, default="prompt_baseline,gepa_prompt,roma_lite",
                        help="Comma-separated methods: prompt_baseline,gepa_prompt,roma_lite,rlm_lite,dspy_baseline")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max questions to load from dataset")
    parser.add_argument("--subset", choices=["pro", "full"], default="pro",
                        help="Dataset: 'pro' (133 hard) or 'full' (246)")
    parser.add_argument("--model", type=str, default="claude-haiku-4-5")
    parser.add_argument("--cli", choices=["claude", "codex"], default="claude")
    parser.add_argument("--corpus-dir", type=str, default=None,
                        help="Path to Treasury Bulletin transformed text files")
    parser.add_argument("--mode", choices=["with_corpus", "no_corpus", "both"], default="no_corpus",
                        help="Corpus policy for all methods")

    # Splits
    parser.add_argument("--train-size", type=int, default=20)
    parser.add_argument("--val-size", type=int, default=10)
    parser.add_argument("--split-seed", type=int, default=42)

    # GEPA
    parser.add_argument("--optimize", action="store_true",
                        help="Run GEPA prompt optimization before evaluation")
    parser.add_argument("--optimize-budget", type=int, default=30,
                        help="Max metric calls for GEPA optimization")

    # Output
    parser.add_argument("--output-dir", type=str, default="benchmarks/officeqa/results")
    parser.add_argument("--debug", action="store_true",
                        help="Debug mode: small splits (5/5/rest)")

    args = parser.parse_args()

    print(f"Methods: {args.methods}")
    print(f"Model: {args.model} | CLI: {args.cli}")
    print(f"Corpus mode: {args.mode}")
    print(f"Optimize: {args.optimize} (budget={args.optimize_budget})")

    run_benchmark(args)


if __name__ == "__main__":
    main()
