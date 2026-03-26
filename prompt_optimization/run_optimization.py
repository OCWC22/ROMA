#!/usr/bin/env python3
"""Compatibility CLI for running prompt optimization."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import yaml

from roma_dspy.utils import log_async_execution
from roma_dspy.utils.async_executor import AsyncParallelExecutor

from .benchmarking import available_families
from .config import apply_optimization_lm_override, get_default_config
from .experiment_cli.pipeline import (
    create_family_solver_module,
    create_feedback_metric,
    load_family_splits,
    resolve_family,
    score_predictions,
)
from .optimizer import create_optimizer
from roma_dspy.utils.lm_factory import backend_from_cli_name

logger = logging.getLogger(__name__)


def _parse_option_overrides(entries: list[str] | None) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for entry in entries or []:
        if "=" not in entry:
            raise ValueError(f"Invalid option override '{entry}'. Expected KEY=VALUE.")
        key, raw_value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid option override '{entry}'. Key cannot be empty.")
        parsed[key] = yaml.safe_load(raw_value)
    return parsed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run ROMA-DSPy prompt optimization with GEPA",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        choices=available_families(),
        default="aimo",
        help="Benchmark family / dataset type",
    )
    parser.add_argument("--profile", type=str, help="ROMA profile override")
    parser.add_argument("--train-size", type=int, default=5, help="Number of training examples")
    parser.add_argument("--val-size", type=int, default=5, help="Number of validation examples")
    parser.add_argument("--test-size", type=int, default=15, help="Number of test examples")
    parser.add_argument("--max-parallel", type=int, default=12, help="Maximum parallel executions")
    parser.add_argument("--concurrency", type=int, default=12, help="Concurrency limit for solver")
    parser.add_argument("--max-metric-calls", type=int, default=10, help="Maximum GEPA metric calls")
    parser.add_argument("--num-threads", type=int, default=4, help="Number of GEPA threads")
    parser.add_argument(
        "--selector",
        choices=["planner_only", "atomizer_only", "executor_only", "aggregator_only", "round_robin"],
        default="planner_only",
        help="Component selector strategy",
    )
    parser.add_argument("--model", type=str, help="Override all optimization/runtime LMs with a single model")
    parser.add_argument(
        "--cli",
        choices=["claude", "codex"],
        help="Use a subscription CLI backend instead of API-backed LMs",
    )
    parser.add_argument(
        "--dataset-option",
        action="append",
        default=[],
        help="Dataset option override as KEY=VALUE (repeatable)",
    )
    parser.add_argument(
        "--runtime-option",
        action="append",
        default=[],
        help="Runtime option override as KEY=VALUE (repeatable)",
    )
    parser.add_argument("--output", type=str, help="Output path for optimized program")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--skip-eval", action="store_true", help="Skip test set evaluation")
    return parser.parse_args()


async def evaluate_async(module, examples, max_parallel=12):
    executor = AsyncParallelExecutor(max_concurrency=max_parallel)
    return await executor.execute_batch(module, examples, show_progress=True)


def main():
    args = parse_args()
    log_async_execution(verbose=args.verbose)

    config = get_default_config()
    config.dataset_name = args.dataset
    if args.profile:
        config.profile_name = args.profile
    config.train_size = args.train_size
    config.val_size = args.val_size
    config.test_size = args.test_size
    config.max_parallel = args.max_parallel
    config.concurrency = args.concurrency
    config.max_metric_calls = args.max_metric_calls
    config.num_threads = args.num_threads
    config.output_path = args.output
    config.component_selector = args.selector
    config.dataset_options.update(_parse_option_overrides(args.dataset_option))
    config.runtime_options.update(_parse_option_overrides(args.runtime_option))
    if args.cli and not args.model:
        raise ValueError("--cli requires --model so the selected CLI gets a valid model identifier.")
    if args.model or args.cli:
        backend = backend_from_cli_name(args.cli) if args.cli else None
        apply_optimization_lm_override(config, model=args.model, backend=backend)

    family_name, family = resolve_family(config, dataset=args.dataset, profile=args.profile)
    profile = args.profile or config.profile_name or family.default_profile or None
    config.profile_name = profile

    logger.info("=" * 60)
    logger.info("ROMA-DSPy Prompt Optimization")
    logger.info("=" * 60)
    logger.info(f"Family: {family_name}")
    logger.info(
        f"Loading datasets (train={config.train_size}, val={config.val_size}, test={config.test_size})..."
    )
    train_set, val_set, test_set = load_family_splits(config, family)
    logger.info(
        f"Loaded {len(train_set)} train, {len(val_set)} val, {len(test_set)} test examples"
    )

    logger.info("Creating solver module...")
    solver_module = create_family_solver_module(
        config,
        family_name=family_name,
        profile=profile,
    )
    logger.info("Solver module created")

    logger.info("Initializing judge and metric...")
    scoring_metric, feedback_metric = create_feedback_metric(config, family)
    logger.info("Judge and metric initialized")

    logger.info(f"Creating GEPA optimizer (selector={args.selector})...")
    optimizer = create_optimizer(config, feedback_metric, component_selector=args.selector)
    logger.info("Optimizer created")

    logger.info("=" * 60)
    logger.info("Starting optimization...")
    logger.info("=" * 60)
    optimized_program = optimizer.compile(
        solver_module,
        trainset=train_set,
        valset=val_set,
    )
    logger.info("Optimization complete")

    if config.output_path:
        output_path = Path(config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Saving optimized program to {output_path}...")
        optimized_program.save(str(output_path))
        logger.info("Saved optimized program")

    if not args.skip_eval:
        logger.info("=" * 60)
        logger.info("Evaluating on test set...")
        logger.info("=" * 60)
        test_results = asyncio.run(
            evaluate_async(optimized_program, test_set, max_parallel=config.max_parallel)
        )
        scores, accuracy = score_predictions(scoring_metric, test_set, test_results)
        logger.info("=" * 60)
        logger.info(f"Test Accuracy: {accuracy:.2%} ({sum(scores):.1f}/{len(scores)})")
        logger.info("=" * 60)

    logger.info("Done")


if __name__ == "__main__":
    main()
