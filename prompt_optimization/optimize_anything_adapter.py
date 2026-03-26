"""Thin adapter around an optional optimize_anything API with GEPA fallback."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
from statistics import mean
from typing import Any, Callable, Optional


@dataclass
class OptimizeAnythingResult:
    best_candidate_text: str
    best_score: float
    metadata: dict[str, Any]


def _load_backend():
    candidates = (
        "gepa.optimize_anything",
        "optimize_anything",
    )
    for module_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        optimize_fn = getattr(module, "optimize_anything", None)
        if callable(optimize_fn):
            return module, optimize_fn
    return None, None


def _callable_accepts(fn, name: str) -> bool:
    signature = inspect.signature(fn)
    return (
        name in signature.parameters
        or any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
    )


def _build_config(module, *, budget: int, reflection_model: Optional[Any]):
    gepa_config = getattr(module, "GEPAConfig", None)
    if gepa_config is None:
        return None

    config_kwargs: dict[str, Any] = {}
    engine_config = getattr(module, "EngineConfig", None)
    reflection_config = getattr(module, "ReflectionConfig", None)
    refiner_config = getattr(module, "RefinerConfig", None)

    if engine_config is not None:
        engine_kwargs: dict[str, Any] = {}
        engine_sig = inspect.signature(engine_config)
        if "max_candidate_proposals" in engine_sig.parameters:
            engine_kwargs["max_candidate_proposals"] = budget
        elif "max_iterations" in engine_sig.parameters:
            engine_kwargs["max_iterations"] = budget
        config_kwargs["engine"] = engine_config(**engine_kwargs)
    elif "max_candidate_proposals" in inspect.signature(gepa_config).parameters:
        config_kwargs["max_candidate_proposals"] = budget
    elif "max_iterations" in inspect.signature(gepa_config).parameters:
        config_kwargs["max_iterations"] = budget

    if reflection_config is not None:
        reflection_kwargs: dict[str, Any] = {}
        if reflection_model:
            reflection_sig = inspect.signature(reflection_config)
            if "reflection_lm" in reflection_sig.parameters:
                reflection_kwargs["reflection_lm"] = reflection_model
        config_kwargs["reflection"] = reflection_config(**reflection_kwargs)

    if refiner_config is not None and reflection_model:
        refiner_sig = inspect.signature(refiner_config)
        if "refiner_lm" in refiner_sig.parameters:
            config_kwargs["refiner"] = refiner_config(refiner_lm=reflection_model)

    return gepa_config(**config_kwargs)


def _extract_result(
    result: Any,
    *,
    seed_text: str,
    component_name: str,
    backend_module: str,
    backend_mode: str,
) -> OptimizeAnythingResult:
    best_candidate = getattr(result, "best_candidate", seed_text)
    if isinstance(best_candidate, dict):
        best_candidate = best_candidate.get(component_name, seed_text)
    best_idx = getattr(result, "best_idx", 0)
    scores = list(getattr(result, "val_aggregate_scores", []) or [])
    best_score = (
        float(scores[best_idx])
        if scores and 0 <= best_idx < len(scores)
        else 0.0
    )
    metadata = {
        "backend_module": backend_module,
        "backend_mode": backend_mode,
        "best_idx": best_idx,
        "val_aggregate_scores": scores,
        "num_candidates": getattr(result, "num_candidates", None),
        "total_metric_calls": getattr(result, "total_metric_calls", None),
    }
    return OptimizeAnythingResult(
        best_candidate_text=str(best_candidate),
        best_score=best_score,
        metadata=metadata,
    )


def _aggregate_rollout(
    rollout: Callable[[str, Any], dict[str, Any]],
    candidate_text: str,
    batch: list[Any],
) -> tuple[float, dict[str, Any]]:
    scores = []
    for example in batch:
        result = rollout(candidate_text, example)
        scores.append(float(result.get("score", 0.0)))
    return (mean(scores) if scores else 0.0), {"num_examples": len(scores)}


def _run_gepa_fallback(
    *,
    seed_text: str,
    rollout: Callable[[str, Any], dict[str, Any]],
    trainset: list[Any],
    valset: list[Any],
    reflection_model: Optional[Any],
    budget: int,
    component_name: str,
) -> OptimizeAnythingResult:
    from gepa import EvaluationBatch, optimize as gepa_optimize

    class TextArtifactAdapter:
        def evaluate(self, batch, candidate, capture_traces=False):
            candidate_text = candidate[component_name]
            scores = []
            outputs = []
            trajectories = [] if capture_traces else None

            for example in batch:
                result = rollout(candidate_text, example)
                score = float(result.get("score", 0.0))
                scores.append(score)
                outputs.append(
                    {
                        "predicted": result.get("predicted", ""),
                        "expected": result.get("expected", ""),
                    }
                )
                if capture_traces:
                    trajectories.append(
                        {
                            "uid": result.get("uid"),
                            "question": result.get("question"),
                            "predicted": result.get("predicted", ""),
                            "expected": result.get("expected", ""),
                            "raw_output": result.get("raw_output", ""),
                            "score": score,
                        }
                    )

            return EvaluationBatch(
                outputs=outputs,
                scores=scores,
                trajectories=trajectories,
            )

        def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
            dataset = {}
            for component in components_to_update:
                dataset[component] = [
                    {
                        "Inputs": {
                            "question": trajectory.get("question", ""),
                            "uid": trajectory.get("uid", ""),
                        },
                        "Generated Outputs": {
                            "raw_output": trajectory.get("raw_output", ""),
                            "final_answer": trajectory.get("predicted", ""),
                        },
                        "Feedback": {
                            "expected_answer": trajectory.get("expected", ""),
                            "score": trajectory.get("score", 0.0),
                        },
                    }
                    for trajectory in (eval_batch.trajectories or [])
                ]
            return dataset

    effective_trainset = list(trainset or valset or [])
    effective_valset = list(valset or []) or None
    if not effective_trainset:
        raise RuntimeError("GEPA fallback requires at least one training example.")

    result = gepa_optimize(
        seed_candidate={component_name: seed_text},
        trainset=effective_trainset,
        valset=effective_valset,
        adapter=TextArtifactAdapter(),
        reflection_lm=reflection_model,
        max_metric_calls=budget,
        candidate_selection_strategy="pareto",
        reflection_minibatch_size=3,
    )
    return _extract_result(
        result,
        seed_text=seed_text,
        component_name=component_name,
        backend_module="gepa",
        backend_mode="gepa_text_fallback",
    )


def optimize_text_artifact(
    *,
    seed_text: str,
    rollout: Callable[[str, Any], dict[str, Any]],
    objective: str,
    background: Optional[str] = None,
    budget: int = 20,
    reflection_model: Optional[Any] = None,
    trainset: Optional[list[Any]] = None,
    valset: Optional[list[Any]] = None,
    component_name: str = "artifact",
) -> OptimizeAnythingResult:
    """Optimize a text artifact, preferring optimize_anything and falling back to GEPA."""
    backend_module, optimize_fn = _load_backend()
    if reflection_model is not None and not isinstance(reflection_model, str):
        backend_module = None
        optimize_fn = None
    if backend_module is not None and optimize_fn is not None:
        config = _build_config(
            backend_module,
            budget=budget,
            reflection_model=reflection_model,
        )

        evaluation_batch = list(valset or trainset or [])
        if not evaluation_batch:
            raise RuntimeError("optimize_text_artifact requires at least one evaluation example.")

        def evaluator(candidate_text: str):
            return _aggregate_rollout(rollout, candidate_text, evaluation_batch)

        call_kwargs: dict[str, Any] = {
            "seed_candidate": seed_text,
            "evaluator": evaluator,
            "objective": objective,
        }
        if background is not None and _callable_accepts(optimize_fn, "background"):
            call_kwargs["background"] = background
        if config is not None and _callable_accepts(optimize_fn, "config"):
            call_kwargs["config"] = config
        if trainset is not None and _callable_accepts(optimize_fn, "dataset"):
            call_kwargs["dataset"] = trainset
        if valset is not None and _callable_accepts(optimize_fn, "valset"):
            call_kwargs["valset"] = valset

        result = optimize_fn(**call_kwargs)
        return _extract_result(
            result,
            seed_text=seed_text,
            component_name=component_name,
            backend_module=backend_module.__name__,
            backend_mode="optimize_anything",
        )

    return _run_gepa_fallback(
        seed_text=seed_text,
        rollout=rollout,
        trainset=list(trainset or []),
        valset=list(valset or []),
        reflection_model=reflection_model,
        budget=budget,
        component_name=component_name,
    )
