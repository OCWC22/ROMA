#!/usr/bin/env python3
"""CLI for running optimization experiments across benchmark families."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
import yaml

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from prompt_optimization.benchmarking import available_families
from prompt_optimization.config import (
    apply_optimization_lm_override,
    get_default_config,
    load_config_from_yaml,
    save_config_to_yaml,
)
from prompt_optimization.experiment_cli.pipeline import (
    create_family_solver_module,
    create_feedback_metric,
    load_family_splits,
    resolve_family,
    score_predictions,
)
from prompt_optimization.optimizer import create_optimizer
from roma_dspy.utils.lm_factory import backend_from_cli_name

from roma_dspy.config.schemas.observability import MLflowConfig
from roma_dspy.core.observability.mlflow_manager import MLflowManager
from roma_dspy.core.observability.span_manager import ROMASpanManager, set_span_manager
from roma_dspy.utils.async_executor import AsyncParallelExecutor


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
        description="Run ROMA optimization experiments across benchmark families",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", "-c", type=str, help="Path to YAML config file")
    parser.add_argument("--name", help="Experiment name")
    parser.add_argument(
        "--dataset",
        choices=available_families(),
        help="Benchmark family / dataset type",
    )
    parser.add_argument("--profile", help="ROMA config profile (e.g. officeqa/default, test)")
    parser.add_argument("--num-threads", type=int, help="GEPA num_threads")
    parser.add_argument("--selector", help="Component selector")
    parser.add_argument("--model", help="Override all optimization/runtime LMs with a single model")
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
    parser.add_argument("--mlflow-uri", default="http://localhost:5000", help="MLflow tracking URI")
    parser.add_argument("--mlflow-experiment", default="roma-optimization", help="MLflow experiment name")
    parser.add_argument("--no-mlflow", action="store_true", help="Disable MLflow tracking")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--save-config", help="Save effective config to this path")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    return parser.parse_args()


def setup_mlflow(args, config):
    if args.no_mlflow or not config.use_mlflow:
        return None

    try:
        mlflow_config = MLflowConfig(
            enabled=True,
            tracking_uri=os.getenv("MLFLOW_TRACKING_URI", args.mlflow_uri),
            experiment_name=args.mlflow_experiment,
            log_traces=True,
            log_traces_from_compile=True,
            log_traces_from_eval=True,
            log_compiles=True,
            log_evals=True,
        )
        mlflow_manager = MLflowManager(mlflow_config)
        mlflow_manager.initialize()
        span_manager = ROMASpanManager(
            enabled=True,
            tracking_uri=mlflow_config.tracking_uri,
        )
        set_span_manager(span_manager)
        logger.info(f"MLflow initialized via ROMA: {mlflow_config.tracking_uri}")
        return mlflow_manager
    except Exception as exc:  # noqa: BLE001
        logger.error(f"MLflow setup failed: {exc}")
        return None


async def evaluate_test(module, test_set, max_parallel):
    executor = AsyncParallelExecutor(max_concurrency=max_parallel)
    return await executor.execute_batch(module, test_set, show_progress=True)


def main():
    args = parse_args()

    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    config_path = None
    if args.config:
        config_path = (Path(__file__).parent / args.config).resolve()

    project_root = Path(__file__).parent.parent.parent
    os.chdir(project_root)
    logger.debug(f"Changed to project root: {project_root}")

    config = load_config_from_yaml(str(config_path)) if config_path else get_default_config()

    if config.env_file:
        from dotenv import load_dotenv

        env_path = Path(config.env_file)
        if not env_path.is_absolute():
            env_path = (Path(__file__).parent / env_path).resolve()
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Loaded environment from {env_path}")
        else:
            logger.warning(f"Env file not found: {env_path}")

    if args.num_threads is not None:
        config.num_threads = args.num_threads
    if args.selector:
        config.component_selector = args.selector
    if args.output_dir:
        config.output_path = args.output_dir
    if args.no_mlflow:
        config.use_mlflow = False
    config.dataset_options.update(_parse_option_overrides(args.dataset_option))
    config.runtime_options.update(_parse_option_overrides(args.runtime_option))
    if args.cli and not args.model:
        raise ValueError("--cli requires --model so the selected CLI gets a valid model identifier.")
    if args.model or args.cli:
        backend = backend_from_cli_name(args.cli) if args.cli else None
        apply_optimization_lm_override(config, model=args.model, backend=backend)

    family_name, family = resolve_family(config, dataset=args.dataset, profile=args.profile)
    profile = args.profile or config.profile_name or family.default_profile or "test"
    config.profile_name = profile
    config.dataset_name = family_name

    exp_name = args.name or f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    logger.info("=" * 80)
    logger.info(f"ROMA-DSPy Optimization: {exp_name}")
    logger.info("=" * 80)
    logger.info(
        f"Benchmark family: {family_name} (train={config.train_size}, val={config.val_size}, test={config.test_size})"
    )
    logger.info(f"ROMA Profile: {profile}")
    logger.info(
        f"GEPA: threads={config.num_threads}, selector={config.component_selector}, max_calls={config.max_metric_calls}"
    )
    logger.info(f"MLflow: {'enabled' if config.use_mlflow else 'disabled'}")
    logger.info("=" * 80)

    if args.save_config:
        save_config_to_yaml(config, args.save_config)
        logger.info(f"Saved effective config to {args.save_config}")

    mlflow_manager = setup_mlflow(args, config)
    run_name = None
    if mlflow_manager:
        import mlflow

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_name = f"optimization_{family_name}_{config.component_selector}_{timestamp}"
        mlflow.start_run(run_name=run_name)
        mlflow.log_params(
            {
                "dataset": family_name,
                "profile": profile,
                "train_size": config.train_size,
                "val_size": config.val_size,
                "test_size": config.test_size,
                "num_threads": config.num_threads,
                "component_selector": config.component_selector,
                "max_metric_calls": config.max_metric_calls,
            }
        )
        mlflow.set_tags(
            {
                "experiment_name": exp_name,
                "framework": "ROMA-DSPy",
                "optimizer": "GEPA",
                "benchmark_family": family_name,
            }
        )

    try:
        logger.info("Loading dataset...")
        train, val, test = load_family_splits(config, family)
        logger.info(f"Loaded {len(train)} train, {len(val)} val, {len(test)} test")

        logger.info("Creating solver...")
        mlflow_uri = mlflow_manager._mlflow.get_tracking_uri() if mlflow_manager else None
        solver_module = create_family_solver_module(
            config,
            family_name=family_name,
            profile=profile,
            mlflow_tracking_uri=mlflow_uri,
        )
        logger.info("Solver created")

        logger.info("Creating metrics...")
        scoring_metric, feedback_metric = create_feedback_metric(config, family)
        logger.info("Metrics created")

        logger.info("Creating optimizer...")
        optimizer = create_optimizer(config, feedback_metric, run_name=run_name)
        logger.info("Optimizer created")

        logger.info("=" * 80)
        logger.info("Starting GEPA optimization...")
        logger.info("=" * 80)
        start = datetime.now()
        optimized = optimizer.compile(solver_module, trainset=train, valset=val)
        duration = (datetime.now() - start).total_seconds()
        logger.info(f"Optimization complete ({duration:.1f}s)")

        if mlflow_manager:
            import mlflow

            mlflow.log_metrics({"optimization_time_seconds": duration})

        logger.info("Evaluating on test set...")
        test_results = asyncio.run(evaluate_test(optimized, test, config.max_parallel))
        scores, accuracy = score_predictions(scoring_metric, test, test_results)

        logger.info("=" * 80)
        logger.info(f"Test Accuracy: {accuracy:.2%} ({sum(scores):.1f}/{len(scores)})")
        logger.info("=" * 80)

        if mlflow_manager:
            import mlflow

            mlflow.log_metrics(
                {
                    "test_accuracy": accuracy,
                    "test_correct": float(sum(scores)),
                    "test_total": float(len(scores)),
                }
            )

        output_dir = Path(config.output_path or "outputs") / exp_name
        output_dir.mkdir(parents=True, exist_ok=True)
        program_path = output_dir / "optimized_program.json"
        optimized.save(str(program_path))
        logger.info(f"Saved to {program_path}")

        if mlflow_manager:
            import mlflow

            mlflow.log_artifact(str(program_path))

    finally:
        if mlflow_manager:
            import mlflow

            mlflow.end_run()
            logger.info(f"MLflow run ended: {exp_name}")

    logger.info("=" * 80)
    logger.info("Experiment complete")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
