"""Shared benchmark-family pipeline helpers for optimization CLIs."""

from __future__ import annotations

from typing import Optional

from prompt_optimization.benchmarking import get_family, resolve_family_name
from prompt_optimization.judge import ComponentJudge
from prompt_optimization.metrics import MetricWithFeedback
from prompt_optimization.solver_setup import create_benchmark_solver_module


def resolve_family(config, *, dataset: Optional[str] = None, profile: Optional[str] = None):
    if dataset:
        config.dataset_name = dataset
    if profile:
        config.profile_name = profile

    family_name = resolve_family_name(
        dataset_name=config.dataset_name,
        profile_name=config.profile_name,
        explicit=getattr(config, "benchmark_family", None),
    )
    return family_name, get_family(family_name)


def load_family_splits(config, family):
    return family.load_examples(config, no_split=False)


def create_feedback_metric(config, family):
    scoring_metric = family.create_scoring_metric(config)
    judge = ComponentJudge(lm_config=config.judge_lm)
    return scoring_metric, MetricWithFeedback(judge=judge, scoring_metric=scoring_metric)


def create_family_solver_module(
    config,
    *,
    family_name: str,
    profile: Optional[str] = None,
    mlflow_tracking_uri: Optional[str] = None,
):
    return create_benchmark_solver_module(
        config,
        family=family_name,
        profile=profile or config.profile_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
    )


def score_predictions(scoring_metric, examples, predictions):
    scores = [
        float(scoring_metric(example=example, prediction=prediction))
        for example, prediction in zip(examples, predictions)
    ]
    accuracy = sum(scores) / len(scores) if scores else 0.0
    return scores, accuracy
