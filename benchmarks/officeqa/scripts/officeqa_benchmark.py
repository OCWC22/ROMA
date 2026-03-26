#!/usr/bin/env python3
"""OfficeQA benchmark harness.

Supports three families:
- Native runtime: real config-driven ROMA OfficeQA execution (`roma_runtime`)
- Track A: real DSPy OfficeQA program + optimization variants (`track_a_*`)
- Legacy ablations: prompt-chain baselines kept for comparison (`legacy_*`)
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import signal
import statistics
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo packages are importable when running as a script
BENCHMARKS_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCHMARKS_ROOT.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from benchmarks.officeqa.methods.base import (
    OfficeQAQuestion,
    OptimizationOutcome,
    OptimizationTimeoutError,
    OptimizableSolver,
    SolverResult,
    atomic_write_json,
    build_error_solver_result,
    load_officeqa_benchmark,
    load_source_documents,
    make_splits,
    save_splits,
)
from benchmarks.officeqa.scripts.failure_analysis import (
    classify_failure,
    generate_failure_notes,
)
from benchmarks.officeqa.scripts.question_typing import classify_question
from prompt_optimization.config import get_default_config, load_config_from_yaml

DEFAULT_OPTIMIZATION_CONFIG = Path(
    "prompt_optimization/experiment_cli/configs/officeqa_track_a.yaml"
)

METHOD_CLASSES = {}
METHOD_ALIASES = {
    "prompt_baseline": "prompt_baseline",
    "gepa_prompt": "legacy_single_prompt_gepa",
    "legacy_single_prompt_gepa": "legacy_single_prompt_gepa",
    "roma_lite": "legacy_prompt_chain_decompose_verify",
    "legacy_prompt_chain_decompose_verify": "legacy_prompt_chain_decompose_verify",
    "rlm_lite": "legacy_recursive_prompt_chain",
    "legacy_recursive_prompt_chain": "legacy_recursive_prompt_chain",
    "dspy_baseline": "legacy_two_stage_prompt",
    "legacy_two_stage_prompt": "legacy_two_stage_prompt",
    "roma_runtime": "roma_runtime",
    "rlm_runtime": "rlm_runtime",
    "roma_gepa_plus": "roma_gepa_plus",
    "roma_optimize_anything": "roma_optimize_anything",
    "track_a_dspy_program": "track_a_dspy_program",
    "dspy_program": "track_a_dspy_program",
    "track_a_dspy_gepa": "track_a_dspy_gepa",
    "dspy_gepa": "track_a_dspy_gepa",
    "track_a_optimize_anything_planner_text": "track_a_optimize_anything_planner_text",
    "optimize_anything_planner": "track_a_optimize_anything_planner_text",
    "rlm_dspy_program": "rlm_dspy_program",
    "rlm_dspy_gepa": "rlm_dspy_gepa",
    "rlm_optimize_anything_planner_text": "rlm_optimize_anything_planner_text",
    "rlm_optimize_anything": "rlm_optimize_anything_planner_text",
}
METHOD_METADATA = {
    "prompt_baseline": {
        "family": "prompt_baseline",
        "optimization": "none",
    },
    "roma_runtime": {
        "family": "native_runtime",
        "optimization": "none",
    },
    "rlm_runtime": {
        "family": "recursive_runtime",
        "optimization": "none",
    },
    "track_a_dspy_program": {
        "family": "track_a",
        "optimization": "none",
    },
    "roma_gepa_plus": {
        "family": "roma_runtime",
        "optimization": "required",
    },
    "roma_optimize_anything": {
        "family": "roma_runtime",
        "optimization": "required",
    },
    "track_a_dspy_gepa": {
        "family": "track_a",
        "optimization": "required",
    },
    "track_a_optimize_anything_planner_text": {
        "family": "track_a",
        "optimization": "required",
    },
    "rlm_dspy_program": {
        "family": "rlm_runtime",
        "optimization": "none",
    },
    "rlm_dspy_gepa": {
        "family": "rlm_runtime",
        "optimization": "required",
    },
    "rlm_optimize_anything_planner_text": {
        "family": "rlm_runtime",
        "optimization": "required",
    },
    "legacy_single_prompt_gepa": {
        "family": "legacy_prompt_ablation",
        "optimization": "optional",
    },
    "legacy_prompt_chain_decompose_verify": {
        "family": "legacy_prompt_ablation",
        "optimization": "none",
    },
    "legacy_recursive_prompt_chain": {
        "family": "legacy_prompt_ablation",
        "optimization": "none",
    },
    "legacy_two_stage_prompt": {
        "family": "legacy_prompt_ablation",
        "optimization": "none",
    },
}
LEGACY_METHODS = {
    method
    for method, metadata in METHOD_METADATA.items()
    if metadata["family"] == "legacy_prompt_ablation"
}
TRACK_A_METHODS = {
    method for method, metadata in METHOD_METADATA.items() if metadata["family"] == "track_a"
}
PROGRAM_OPTIMIZATION_METHODS = TRACK_A_METHODS | {
    "roma_gepa_plus",
    "roma_optimize_anything",
    "rlm_dspy_program",
    "rlm_dspy_gepa",
    "rlm_optimize_anything_planner_text",
}
METHOD_CONTEXT_POLICY = {
    "prompt_baseline": "raw_context",
    "legacy_single_prompt_gepa": "raw_context",
    "legacy_prompt_chain_decompose_verify": "raw_context",
    "legacy_recursive_prompt_chain": "raw_context",
    "legacy_two_stage_prompt": "raw_context",
    "roma_runtime": "tool_search",
    "rlm_runtime": "tool_search",
    "track_a_dspy_program": "tool_search",
    "track_a_dspy_gepa": "tool_search",
    "track_a_optimize_anything_planner_text": "tool_search",
    "roma_gepa_plus": "tool_search",
    "roma_optimize_anything": "tool_search",
    "rlm_dspy_program": "tool_search",
    "rlm_dspy_gepa": "tool_search",
    "rlm_optimize_anything_planner_text": "tool_search",
}

_WORKER_POLL_SECONDS = 0.1
_WORKER_JOIN_GRACE_SECONDS = 5.0
_WORKER_INTERRUPT_GRACE_SECONDS = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _supports_fork_timeout() -> bool:
    try:
        return "fork" in multiprocessing.get_all_start_methods()
    except Exception:  # noqa: BLE001
        return False


def _require_fork_timeout_support() -> None:
    pass # Mac explicitly needs spawn; we rely on safe pickling instead


def _supports_optimization_timeout() -> bool:
    return hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")


def _require_optimization_timeout_support() -> None:
    if not _supports_optimization_timeout():
        raise RuntimeError(
            "Per-method optimization timeouts require SIGALRM/setitimer support on this platform. "
            "Set --optimize-timeout-seconds 0 to disable optimization timeout enforcement."
        )


def _child_solve_entry(conn, solver, question, context) -> None:
    try:
        result = solver.solve(question, context=context)
        payload = {
            "kind": "result",
            "result": result.to_dict() if hasattr(result, "to_dict") else result,
        }
    except BaseException as exc:  # noqa: BLE001
        payload = {
            "kind": "exception",
            "error": str(exc),
            "exception_type": exc.__class__.__name__,
            "traceback": traceback.format_exc(),
        }
    import json
    try:
        payload = json.loads(json.dumps(payload, default=str))
    except Exception as e:
        payload = {
            "kind": "exception",
            "error": f"JSON serialization failed in worker: {e}",
            "exception_type": "SerializationError",
            "traceback": "",
        }

    try:
        conn.send(payload)
    except BaseException as send_exc:  # noqa: BLE001
        try:
            conn.send({
                "kind": "exception",
                "error": f"Failed to send payload over pipe: {send_exc}",
                "exception_type": "SendError",
                "traceback": ""
            })
        except BaseException:
            pass
    finally:
        _close_solver_quietly(solver)
        conn.close()


def _interrupt_then_terminate_worker(worker) -> None:
    if worker is None:
        return
    if not worker.is_alive():
        worker.join(timeout=0.1)
        return

    if worker.pid:
        try:
            os.kill(worker.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001
            pass
    worker.join(_WORKER_INTERRUPT_GRACE_SECONDS)

    if worker.is_alive():
        worker.terminate()
        worker.join(_WORKER_INTERRUPT_GRACE_SECONDS)

    if worker.is_alive() and hasattr(worker, "kill"):
        worker.kill()
        worker.join(_WORKER_INTERRUPT_GRACE_SECONDS)


def _coerce_solver_result_payload(
    payload,
    *,
    method_name: str,
    question: OfficeQAQuestion,
    duration: float,
    used_context: bool,
) -> SolverResult:
    if isinstance(payload, SolverResult):
        return payload
    if isinstance(payload, dict):
        try:
            payload = dict(payload)
            payload.setdefault("method", method_name)
            payload.setdefault("expected", question.answer)
            payload.setdefault("duration", duration)
            payload.setdefault("used_context", used_context)
            payload.setdefault("trace", {})
            return SolverResult(**payload)
        except TypeError:
            pass
    return build_error_solver_result(
        method=method_name,
        question=question,
        duration=duration,
        error_message="Worker returned an invalid result payload",
        error_type="solver_error",
        used_context=used_context,
        trace={"worker_payload_type": type(payload).__name__},
        raw_output=f"ERROR: Invalid result payload: {payload!r}",
    )


def _execute_solve_with_timeout(
    *,
    solver,
    method_name: str,
    question: OfficeQAQuestion,
    context: str,
    solve_timeout_seconds: float,
) -> SolverResult:
    if solve_timeout_seconds <= 0:
        return solver.solve(question, context=context)

    used_context = bool(context)
    
    # Use native default multiprocess context to avoid macOS CFNetwork poison during forks
    ctx = multiprocessing.get_context()
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    worker = ctx.Process(
        target=_child_solve_entry,
        args=(child_conn, solver, question, context),
        daemon=True,
    )
    started_at = time.time()
    worker.start()
    child_conn.close()

    try:
        deadline = started_at + float(solve_timeout_seconds)
        payload = None

        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                if parent_conn.poll(min(_WORKER_POLL_SECONDS, remaining)):
                    try:
                        payload = parent_conn.recv()
                    except EOFError:
                        payload = None
                    break
                if not worker.is_alive():
                    break
        except KeyboardInterrupt:
            _interrupt_then_terminate_worker(worker)
            raise

        duration = time.time() - started_at

        if payload is not None:
            worker.join(_WORKER_JOIN_GRACE_SECONDS)
            if worker.is_alive():
                _interrupt_then_terminate_worker(worker)

            kind = payload.get("kind")
            if kind == "result":
                return _coerce_solver_result_payload(
                    payload.get("result"),
                    method_name=method_name,
                    question=question,
                    duration=duration,
                    used_context=used_context,
                )
            if kind == "exception":
                error_message = payload.get("error") or "Worker raised an exception"
                return build_error_solver_result(
                    method=method_name,
                    question=question,
                    duration=duration,
                    error_message=error_message,
                    error_type="solver_error",
                    used_context=used_context,
                    trace={
                        "worker_exception_type": payload.get("exception_type"),
                        "worker_traceback": payload.get("traceback"),
                        "worker_exit_code": worker.exitcode,
                    },
                    raw_output=f"ERROR: {error_message}",
                )
            return build_error_solver_result(
                method=method_name,
                question=question,
                duration=duration,
                error_message="Worker returned an unknown payload type",
                error_type="solver_error",
                used_context=used_context,
                trace={
                    "worker_payload_kind": payload.get("kind"),
                    "worker_exit_code": worker.exitcode,
                },
                raw_output=f"ERROR: Unknown payload {payload!r}",
            )

        if not worker.is_alive():
            worker.join(timeout=0.1)
            return build_error_solver_result(
                method=method_name,
                question=question,
                duration=duration,
                error_message="Worker exited without returning a result",
                error_type="solver_error",
                used_context=used_context,
                trace={"worker_exit_code": worker.exitcode},
                raw_output=f"ERROR: Worker exited without returning a result (exit={worker.exitcode})",
            )

        _interrupt_then_terminate_worker(worker)
        return build_error_solver_result(
            method=method_name,
            question=question,
            duration=duration,
            error_message=f"Solve exceeded {solve_timeout_seconds} seconds",
            error_type="timeout",
            used_context=used_context,
            trace={
                "timeout_seconds": solve_timeout_seconds,
                "worker_exit_code": worker.exitcode,
            },
            raw_output=f"TIMEOUT: Solve exceeded {solve_timeout_seconds} seconds",
        )
    finally:
        parent_conn.close()


def _execute_optimization_with_timeout(
    *,
    solver: OptimizableSolver,
    train: list[OfficeQAQuestion],
    val: list[OfficeQAQuestion],
    optimize_budget: int,
    artifact_dir: Path,
    optimize_timeout_seconds: float,
) -> None:
    if optimize_timeout_seconds <= 0:
        solver.optimize(
            trainset=train,
            valset=val,
            optimize_budget=optimize_budget,
            artifact_dir=artifact_dir,
        )
        return

    _require_optimization_timeout_support()

    def _handle_timeout(_signum, _frame):
        raise OptimizationTimeoutError(
            f"Optimization exceeded {optimize_timeout_seconds} seconds"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(optimize_timeout_seconds))
    try:
        solver.optimize(
            trainset=train,
            valset=val,
            optimize_budget=optimize_budget,
            artifact_dir=artifact_dir,
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer and any(previous_timer):
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _result_status_label(result: SolverResult) -> str:
    if result.score > 0:
        return "OK"
    error_type = (result.trace or {}).get("error_type")
    if error_type == "timeout":
        return "TIMEOUT"
    if error_type == "interrupted":
        return "INTERRUPTED"
    if result.error:
        return "ERROR"
    return "WRONG"


def _optimization_status_label(status: str) -> str:
    return {
        "completed": "COMPLETED",
        "timed_out": "TIMEOUT",
        "failed": "ERROR",
        "interrupted": "INTERRUPTED",
        "running": "RUNNING",
        "pending": "PENDING",
        "not_required": "SKIPPED",
        "not_requested": "SKIPPED",
    }.get(status, status.upper())


def _build_optimization_progress(run_metadata: dict) -> dict[str, int]:
    statuses = {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "timed_out": 0,
        "interrupted": 0,
        "running": 0,
        "pending": 0,
        "not_requested": 0,
        "not_required": 0,
    }
    for outcome in (run_metadata.get("optimization", {}).get("methods", {}) or {}).values():
        statuses["total"] += 1
        status = outcome.get("status")
        if status in statuses:
            statuses[status] += 1
    return statuses


def _build_progress(
    *,
    method_names: list[str],
    results_by_method: dict[str, list[SolverResult]],
    test_questions_total: int,
    last_completed_question_uid: str | None,
    last_completed_method: str | None,
) -> dict:
    completed_by_method = {
        method_name: len(results_by_method.get(method_name, []))
        for method_name in method_names
    }
    completed_solves = sum(completed_by_method.values())
    return {
        "test_questions_total": test_questions_total,
        "methods_total": len(method_names),
        "expected_solves": test_questions_total * len(method_names),
        "completed_solves": completed_solves,
        "completed_by_method": completed_by_method,
        "last_completed_question_uid": last_completed_question_uid,
        "last_completed_method": last_completed_method,
        "optimization": {},
    }


def _update_run_metadata(
    run_metadata: dict,
    *,
    method_names: list[str],
    results_by_method: dict[str, list[SolverResult]],
    test_questions_total: int,
    status: str | None = None,
    last_completed_question_uid: str | None = None,
    last_completed_method: str | None = None,
    error: str | None = None,
    phase: str | None = None,
    finished: bool = False,
) -> None:
    if status is not None:
        run_metadata["status"] = status
    if error is not None:
        run_metadata["error"] = error
    if phase is not None:
        run_metadata["phase"] = phase
    if last_completed_question_uid is not None:
        run_metadata["last_completed_question_uid"] = last_completed_question_uid
    if last_completed_method is not None:
        run_metadata["last_completed_method"] = last_completed_method

    run_metadata["updated_at"] = _now_iso()
    if finished:
        run_metadata["finished_at"] = run_metadata["updated_at"]
        if phase is None:
            run_metadata["phase"] = "finished"

    progress = _build_progress(
        method_names=method_names,
        results_by_method=results_by_method,
        test_questions_total=test_questions_total,
        last_completed_question_uid=run_metadata.get("last_completed_question_uid"),
        last_completed_method=run_metadata.get("last_completed_method"),
    )
    progress["optimization"] = _build_optimization_progress(run_metadata)
    run_metadata["progress"] = progress


def _persist_run_snapshot(
    *,
    output_dir: Path,
    run_id: str,
    mode_name: str,
    results_by_method: dict[str, list[SolverResult]],
    run_metadata: dict,
) -> None:
    summary = compute_summary(results_by_method)
    type_breakdown = compute_per_type_accuracy(results_by_method)
    failure_counts = compute_failure_counts(results_by_method)
    save_results(
        output_dir,
        run_id,
        mode_name,
        summary,
        results_by_method,
        type_breakdown,
        failure_counts,
        run_metadata,
    )


def _atomic_write_json(path: Path, payload) -> None:
    atomic_write_json(path, payload)


def _initialize_optimization_methods(
    *,
    method_names: list[str],
    optimize_requested: bool,
    artifact_root: Path,
) -> dict[str, dict]:
    methods: dict[str, dict] = {}
    for method_name in method_names:
        optimization_mode = METHOD_METADATA[method_name]["optimization"]
        required = optimization_mode == "required"
        if optimization_mode == "none":
            status = "not_required"
            artifact_dir = None
        else:
            status = "pending" if optimize_requested else "not_requested"
            artifact_dir = str((artifact_root / method_name).resolve())
        methods[method_name] = OptimizationOutcome(
            method=method_name,
            required=required,
            optimization_mode=optimization_mode,
            status=status,
            artifact_dir=artifact_dir,
        ).to_dict()
    return methods


def _initialize_run_metadata(
    *,
    run_id: str,
    mode_name: str,
    method_names: list[str],
    subset: str,
    profile: str | None,
    effective_profiles: dict[str, str],
    resolved_config_path: str | None,
    optimize: bool,
    optimize_budget: int,
    optimize_timeout_seconds: float,
    solve_timeout_seconds: float,
    artifact_root: Path,
) -> dict:
    return {
        "run_id": run_id,
        "mode": mode_name,
        "methods": method_names,
        "method_metadata": {name: METHOD_METADATA[name] for name in method_names},
        "profile": profile or "auto",
        "effective_profiles": dict(effective_profiles),
        "subset": subset,
        "optimization_config": resolved_config_path,
        "optimize": optimize,
        "optimize_budget": optimize_budget,
        "optimize_timeout_seconds": optimize_timeout_seconds,
        "solve_timeout_seconds": solve_timeout_seconds,
        "phase": "optimization",
        "optimization": {
            "optimize_requested": optimize,
            "optimize_budget": optimize_budget,
            "timeout_seconds": optimize_timeout_seconds,
            "methods": _initialize_optimization_methods(
                method_names=method_names,
                optimize_requested=optimize,
                artifact_root=artifact_root,
            ),
        },
        "status": "running",
        "started_at": _now_iso(),
        "updated_at": None,
        "finished_at": None,
        "error": None,
        "last_completed_question_uid": None,
        "last_completed_method": None,
    }


def _close_solver_quietly(solver) -> None:
    close = getattr(solver, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001
            pass


def _build_disabled_method_result(
    *,
    method_name: str,
    question: OfficeQAQuestion,
    used_context: bool,
    disabled_reason: dict,
) -> SolverResult:
    stage = disabled_reason.get("stage", "evaluation")
    if stage == "optimization":
        error_message = disabled_reason.get(
            "error_message",
            "Method disabled because optimization did not complete successfully",
        )
        trace = {
            "disabled_before_evaluation": True,
            "optimization_status": disabled_reason.get("status"),
            "optimization_artifact_dir": disabled_reason.get("artifact_dir"),
            "timeout_seconds": disabled_reason.get("timeout_seconds"),
        }
        raw_output = f"ERROR: {error_message}"
    else:
        error_message = disabled_reason.get(
            "error_message",
            "Method disabled after a prior timeout to avoid reusing possibly corrupted staged state",
        )
        trace = {
            "disabled_after_timeout": True,
            "prior_timeout_question_uid": disabled_reason.get("question_uid"),
        }
        raw_output = (
            "ERROR: Method disabled after timeout on "
            f"{disabled_reason.get('question_uid')}"
        )
    return build_error_solver_result(
        method=method_name,
        question=question,
        duration=0.0,
        error_message=error_message,
        error_type=disabled_reason.get("error_type", "solver_error"),
        used_context=used_context,
        trace=trace,
        raw_output=raw_output,
        error_stage=stage,
    )


def register_methods():
    """Lazy import to avoid loading unused methods."""
    from benchmarks.officeqa.methods.dspy_baseline import DSPyBaselineSolver
    from benchmarks.officeqa.methods.gepa_prompt import GEPAPromptSolver
    from benchmarks.officeqa.methods.prompt_baseline import PromptBaselineSolver
    from benchmarks.officeqa.methods.rlm_lite import RLMLiteSolver
    from benchmarks.officeqa.methods.rlm_dspy_gepa import RLMDSPyGEPASolver
    from benchmarks.officeqa.methods.rlm_dspy_program import RLMDSPyProgramSolver
    from benchmarks.officeqa.methods.rlm_optimize_anything import (
        RLMOptimizeAnythingPlannerTextSolver,
    )
    from benchmarks.officeqa.methods.rlm_runtime import RLMRuntimeSolver
    from benchmarks.officeqa.methods.roma_gepa_plus import ROMAGEPAPlusSolver
    from benchmarks.officeqa.methods.roma_lite import ROMALiteSolver
    from benchmarks.officeqa.methods.roma_optimize_anything import ROMAOptimizeAnythingSolver
    from benchmarks.officeqa.methods.roma_runtime import ROMARuntimeSolver
    from benchmarks.officeqa.methods.track_a_dspy_gepa import TrackADSPyGEPASolver
    from benchmarks.officeqa.methods.track_a_dspy_program import TrackADSPyProgramSolver
    from benchmarks.officeqa.methods.track_a_optimize_anything import (
        TrackAOptimizeAnythingPlannerTextSolver,
    )

    METHOD_CLASSES["prompt_baseline"] = PromptBaselineSolver
    METHOD_CLASSES["legacy_single_prompt_gepa"] = GEPAPromptSolver
    METHOD_CLASSES["legacy_prompt_chain_decompose_verify"] = ROMALiteSolver
    METHOD_CLASSES["legacy_recursive_prompt_chain"] = RLMLiteSolver
    METHOD_CLASSES["rlm_runtime"] = RLMRuntimeSolver
    METHOD_CLASSES["legacy_two_stage_prompt"] = DSPyBaselineSolver
    METHOD_CLASSES["roma_runtime"] = ROMARuntimeSolver
    METHOD_CLASSES["roma_gepa_plus"] = ROMAGEPAPlusSolver
    METHOD_CLASSES["roma_optimize_anything"] = ROMAOptimizeAnythingSolver
    METHOD_CLASSES["track_a_dspy_program"] = TrackADSPyProgramSolver
    METHOD_CLASSES["track_a_dspy_gepa"] = TrackADSPyGEPASolver
    METHOD_CLASSES[
        "track_a_optimize_anything_planner_text"
    ] = TrackAOptimizeAnythingPlannerTextSolver
    METHOD_CLASSES["rlm_dspy_program"] = RLMDSPyProgramSolver
    METHOD_CLASSES["rlm_dspy_gepa"] = RLMDSPyGEPASolver
    METHOD_CLASSES[
        "rlm_optimize_anything_planner_text"
    ] = RLMOptimizeAnythingPlannerTextSolver


def normalize_method_names(methods_arg: str) -> list[str]:
    normalized = []
    for raw_name in methods_arg.split(","):
        raw_name = raw_name.strip()
        if not raw_name:
            continue
        canonical = METHOD_ALIASES.get(raw_name)
        if canonical is None:
            available = sorted(METHOD_ALIASES.keys())
            raise ValueError(f"Unknown method '{raw_name}'. Available: {available}")
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def resolve_method_profile(
    method_name: str,
    requested_profile: str | None,
    *,
    profile_was_explicit: bool = False,
) -> str:
    if requested_profile not in (None, "", "officeqa/default"):
        return requested_profile
    if method_name.startswith("rlm_") and not profile_was_explicit:
        return "officeqa/hybrid"
    return requested_profile or "officeqa/default"


def load_optimization_config(args):
    raw_path = Path(args.optimization_config)
    config_path = raw_path
    if not config_path.is_absolute():
        config_path = (PROJECT_ROOT / config_path).resolve()
    if config_path.exists():
        config = load_config_from_yaml(str(config_path))
        resolved_path = str(config_path)
    elif raw_path == DEFAULT_OPTIMIZATION_CONFIG or config_path == (
        PROJECT_ROOT / DEFAULT_OPTIMIZATION_CONFIG
    ).resolve():
        config = get_default_config()
        resolved_path = None
    else:
        raise FileNotFoundError(
            f"Optimization config not found: {args.optimization_config}"
        )

    config.dataset_name = config.dataset_name or "officeqa"
    config.profile_name = config.profile_name or args.profile or "officeqa/default"
    config.officeqa_subset = args.subset
    if args.corpus_dir:
        config.officeqa_corpus_dir = args.corpus_dir
    return config, resolved_path


def instantiate_solver(
    method_name,
    args,
    *,
    corpus_dir,
    optimization_config,
    allow_autodiscovery,
):
    cls = METHOD_CLASSES[method_name]
    effective_profile = resolve_method_profile(
        method_name,
        args.profile,
        profile_was_explicit=args.profile is not None,
    )
    if method_name == "legacy_single_prompt_gepa":
        return cls(model=args.model, cli=args.cli, corpus_dir=corpus_dir)
    if method_name in {"roma_runtime", "rlm_runtime"}:
        return cls(
            model=args.model,
            cli=args.cli,
            profile=effective_profile,
            corpus_dir=corpus_dir,
            overrides=args.native_override,
            allow_autodiscovery=allow_autodiscovery,
        )
    if method_name in PROGRAM_OPTIMIZATION_METHODS:
        return cls(
            model=args.model,
            cli=args.cli,
            profile=effective_profile,
            corpus_dir=corpus_dir,
            overrides=args.native_override,
            allow_autodiscovery=allow_autodiscovery,
            optimization_config=optimization_config,
        )
    return cls(model=args.model, cli=args.cli)


def maybe_optimize_solvers(
    solvers,
    method_names,
    train,
    val,
    *,
    optimize: bool,
    optimize_budget: int,
    optimize_timeout_seconds: float,
    artifact_root: Path,
    output_dir: Path,
    run_id: str,
    mode_name: str,
    results_by_method: dict[str, list[SolverResult]],
    run_metadata: dict,
    test_questions_total: int,
):
    required_methods = [
        method_name
        for method_name in method_names
        if METHOD_METADATA[method_name]["optimization"] == "required"
    ]
    if required_methods and not optimize:
        message = (
            "The following methods require --optimize before evaluation: "
            + ", ".join(required_methods)
        )
        _update_run_metadata(
            run_metadata,
            method_names=method_names,
            results_by_method=results_by_method,
            test_questions_total=test_questions_total,
            status="failed",
            error=message,
            phase="finished",
            finished=True,
        )
        _persist_run_snapshot(
            output_dir=output_dir,
            run_id=run_id,
            mode_name=mode_name,
            results_by_method=results_by_method,
            run_metadata=run_metadata,
        )
        raise ValueError(message)

    if not optimize:
        return run_metadata["optimization"]["methods"]

    for method_name, solver in solvers.items():
        optimization_mode = METHOD_METADATA[method_name]["optimization"]
        if optimization_mode == "none":
            continue
        if not isinstance(solver, OptimizableSolver):
            outcome = run_metadata["optimization"]["methods"][method_name]
            outcome["status"] = "failed"
            outcome["error"] = (
                f"Method '{method_name}' requires optimization metadata but solver "
                "does not implement OptimizableSolver"
            )
            outcome["error_type"] = "solver_error"
            outcome["finished_at"] = _now_iso()
            outcome["trace"] = {"error_stage": "optimization"}
            _update_run_metadata(
                run_metadata,
                method_names=method_names,
                results_by_method=results_by_method,
                test_questions_total=test_questions_total,
                phase="optimization",
            )
            _persist_run_snapshot(
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
            )
            print(f"\n--- Optimization: {method_name} ---")
            print(f"  {_optimization_status_label(outcome['status'])} | {outcome['error']}")
            continue

        outcome = run_metadata["optimization"]["methods"][method_name]
        outcome["status"] = "running"
        outcome["started_at"] = _now_iso()
        outcome["error"] = None
        outcome["error_type"] = None
        outcome["trace"] = {}
        _update_run_metadata(
            run_metadata,
            method_names=method_names,
            results_by_method=results_by_method,
            test_questions_total=test_questions_total,
            phase="optimization",
        )
        _persist_run_snapshot(
            output_dir=output_dir,
            run_id=run_id,
            mode_name=mode_name,
            results_by_method=results_by_method,
            run_metadata=run_metadata,
        )

        print(f"\n--- Optimization: {method_name} ---")
        print(f"  train={len(train)} | val={len(val)} | budget={optimize_budget}")
        started_at = time.time()
        try:
            _execute_optimization_with_timeout(
                solver=solver,
                train=train,
                val=val,
                optimize_budget=optimize_budget,
                artifact_dir=artifact_root / method_name,
                optimize_timeout_seconds=optimize_timeout_seconds,
            )
            outcome["status"] = "completed"
            print(
                f"  {_optimization_status_label(outcome['status'])} "
                f"({time.time() - started_at:.1f}s)"
            )
        except OptimizationTimeoutError as exc:
            _close_solver_quietly(solver)
            outcome["status"] = "timed_out"
            outcome["error"] = str(exc)
            outcome["error_type"] = "timeout"
            outcome["trace"] = {
                "error_stage": "optimization",
                "timeout_seconds": optimize_timeout_seconds,
            }
            print(
                f"  {_optimization_status_label(outcome['status'])} | {exc} "
                f"({time.time() - started_at:.1f}s)"
            )
        except KeyboardInterrupt:
            _close_solver_quietly(solver)
            outcome["status"] = "interrupted"
            outcome["error"] = "Optimization interrupted by user"
            outcome["error_type"] = "interrupted"
            outcome["trace"] = {"error_stage": "optimization"}
            print(
                f"  {_optimization_status_label(outcome['status'])} "
                f"({time.time() - started_at:.1f}s)"
            )
            outcome["duration"] = time.time() - started_at
            outcome["finished_at"] = _now_iso()
            _update_run_metadata(
                run_metadata,
                method_names=method_names,
                results_by_method=results_by_method,
                test_questions_total=test_questions_total,
                status="interrupted",
                error=outcome["error"],
                phase="finished",
                finished=True,
            )
            _persist_run_snapshot(
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            _close_solver_quietly(solver)
            outcome["status"] = "failed"
            outcome["error"] = str(exc)
            outcome["error_type"] = "solver_error"
            outcome["trace"] = {
                "error_stage": "optimization",
                "timeout_seconds": None,
            }
            print(
                f"  {_optimization_status_label(outcome['status'])} | {exc} "
                f"({time.time() - started_at:.1f}s)"
            )
        finally:
            outcome["duration"] = time.time() - started_at
            outcome["finished_at"] = _now_iso()
            _update_run_metadata(
                run_metadata,
                method_names=method_names,
                results_by_method=results_by_method,
                test_questions_total=test_questions_total,
                phase=(
                    "optimization"
                    if run_metadata.get("status") != "interrupted"
                    else None
                ),
            )
            _persist_run_snapshot(
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
            )
    return run_metadata["optimization"]["methods"]


def run_benchmark(args):
    register_methods()
    run_id = f"run_{int(time.time())}"

    print("=" * 70)
    print("OFFICEQA BENCHMARK HARNESS")
    print("=" * 70)

    print(f"\nLoading OfficeQA {args.subset}...")
    questions = load_officeqa_benchmark(subset=args.subset, limit=args.limit)
    print(f"Loaded {len(questions)} questions")

    for q in questions:
        q.question_type = classify_question(q.question)

    if args.debug:
        train_size, val_size = 5, 5
    else:
        train_size, val_size = args.train_size, args.val_size

    train, val, test = make_splits(questions, train_size, val_size, seed=args.split_seed)

    print(f"\nSplits (seed={args.split_seed}):")
    print(f"  train: {len(train)}")
    print(f"  val:   {len(val)}")
    print(f"  test:  {len(test)}")

    splits_dir = BENCHMARKS_ROOT / "data_splits"
    save_splits(train, val, test, splits_dir)
    print(f"  Saved UIDs to {splits_dir}/")

    if len(test) == 0:
        print("\nERROR: No test questions. Increase --limit or reduce train/val sizes.")
        sys.exit(1)

    try:
        method_names = normalize_method_names(args.methods)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    try:
        optimization_config, resolved_config_path = load_optimization_config(args)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    if args.solve_timeout_seconds > 0:
        try:
            _require_fork_timeout_support()
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
    if args.optimize and args.optimize_timeout_seconds > 0:
        try:
            _require_optimization_timeout_support()
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)

    corpus_dir = Path(args.corpus_dir) if args.corpus_dir else None
    modes = []
    if args.mode in ("with_corpus", "both"):
        modes.append(("with_corpus", corpus_dir))
    if args.mode in ("no_corpus", "both"):
        modes.append(("no_corpus", None))

    all_run_results = {}
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for mode_name, mode_corpus_dir in modes:
        print(f"\n{'=' * 70}")
        print(f"MODE: {mode_name}")
        print(f"{'=' * 70}")

        effective_profiles = {
            method_name: resolve_method_profile(
                method_name,
                args.profile,
                profile_was_explicit=args.profile is not None,
            )
            for method_name in method_names
        }
        solvers = {
            method_name: instantiate_solver(
                method_name,
                args,
                corpus_dir=mode_corpus_dir,
                optimization_config=optimization_config,
                allow_autodiscovery=mode_name != "no_corpus",
            )
            for method_name in method_names
        }

        artifact_root = Path(args.output_dir) / f"{run_id}_{mode_name}_artifacts"
        results_by_method = {method_name: [] for method_name in method_names}
        run_metadata = _initialize_run_metadata(
            run_id=run_id,
            mode_name=mode_name,
            method_names=method_names,
            subset=args.subset,
            profile=args.profile,
            effective_profiles=effective_profiles,
            resolved_config_path=resolved_config_path,
            optimize=args.optimize,
            optimize_budget=args.optimize_budget,
            optimize_timeout_seconds=args.optimize_timeout_seconds,
            solve_timeout_seconds=args.solve_timeout_seconds,
            artifact_root=artifact_root,
        )
        _update_run_metadata(
            run_metadata,
            method_names=method_names,
            results_by_method=results_by_method,
            test_questions_total=len(test),
            status="running",
            phase="optimization",
        )
        _persist_run_snapshot(
            output_dir=output_dir,
            run_id=run_id,
            mode_name=mode_name,
            results_by_method=results_by_method,
            run_metadata=run_metadata,
        )

        try:
            optimization_outcomes = maybe_optimize_solvers(
                solvers,
                method_names,
                train,
                val,
                optimize=args.optimize,
                optimize_budget=args.optimize_budget,
                optimize_timeout_seconds=args.optimize_timeout_seconds,
                artifact_root=artifact_root,
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
                test_questions_total=len(test),
            )

            print(f"\n--- Evaluating on test set ({len(test)} questions) ---")
            disabled_methods: dict[str, dict[str, str | float | None]] = {
                method_name: {
                    "stage": "optimization",
                    "status": outcome["status"],
                    "error_type": outcome.get("error_type") or "solver_error",
                    "error_message": outcome.get("error")
                    or "Method disabled because optimization did not complete successfully",
                    "artifact_dir": outcome.get("artifact_dir"),
                    "timeout_seconds": (outcome.get("trace") or {}).get("timeout_seconds"),
                }
                for method_name, outcome in optimization_outcomes.items()
                if outcome["status"] in {"timed_out", "failed"}
            }
            _update_run_metadata(
                run_metadata,
                method_names=method_names,
                results_by_method=results_by_method,
                test_questions_total=len(test),
                status="running",
                phase="evaluation",
            )
            _persist_run_snapshot(
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
            )

            methods_requiring_raw_context = {
                method_name
                for method_name in method_names
                if METHOD_CONTEXT_POLICY.get(method_name, "raw_context") == "raw_context"
            }

            for i, q in enumerate(test):
                print(f"\n  Q{i+1}/{len(test)} [{q.uid}] ({q.question_type}): {q.question[:60]}...")
                print(f"  Expected: {q.answer}")

                raw_context = ""
                if mode_corpus_dir and methods_requiring_raw_context:
                    raw_context = load_source_documents(q.source_files, mode_corpus_dir)

                for method_name in method_names:
                    solver = solvers[method_name]
                    method_context = (
                        raw_context
                        if METHOD_CONTEXT_POLICY.get(method_name, "raw_context") == "raw_context"
                        else ""
                    )
                    print(f"    [{method_name}] ", end="", flush=True)
                    disabled_reason = disabled_methods.get(method_name)
                    if disabled_reason:
                        result = _build_disabled_method_result(
                            method_name=method_name,
                            question=q,
                            used_context=bool(method_context),
                            disabled_reason=disabled_reason,
                        )
                    else:
                        try:
                            result = _execute_solve_with_timeout(
                                solver=solver,
                                method_name=method_name,
                                question=q,
                                context=method_context,
                                solve_timeout_seconds=args.solve_timeout_seconds,
                            )
                        except KeyboardInterrupt:
                            result = build_error_solver_result(
                                method=method_name,
                                question=q,
                                duration=0.0,
                                error_message="Benchmark interrupted during solve",
                                error_type="interrupted",
                                used_context=bool(method_context),
                                trace={},
                                raw_output="INTERRUPTED: Benchmark interrupted during solve",
                            )
                            failure_type = classify_failure(
                                q.question,
                                result.predicted,
                                q.answer,
                                result.raw_output,
                                result.score,
                                error=result.error,
                                trace=result.trace,
                            )
                            failure_notes = generate_failure_notes(
                                q.question,
                                result.predicted,
                                q.answer,
                                result.raw_output,
                                failure_type,
                                error=result.error,
                                trace=result.trace,
                            )
                            result.trace["question_uid"] = q.uid
                            result.trace["question_type"] = q.question_type
                            result.trace["failure_type"] = failure_type
                            result.trace["failure_notes"] = failure_notes
                            result.trace["method_metadata"] = METHOD_METADATA.get(method_name, {})
                            results_by_method[method_name].append(result)
                            _update_run_metadata(
                                run_metadata,
                                method_names=method_names,
                                results_by_method=results_by_method,
                                test_questions_total=len(test),
                                status="interrupted",
                                last_completed_question_uid=q.uid,
                                last_completed_method=method_name,
                                error="Benchmark interrupted by user",
                                finished=True,
                            )
                            _persist_run_snapshot(
                                output_dir=output_dir,
                                run_id=run_id,
                                mode_name=mode_name,
                                results_by_method=results_by_method,
                                run_metadata=run_metadata,
                            )
                            print(f"{_result_status_label(result)} | {result.error} ({result.duration:.1f}s)")
                            raise
                        except Exception as exc:  # noqa: BLE001
                            result = build_error_solver_result(
                                method=method_name,
                                question=q,
                                duration=0.0,
                                error_message=str(exc),
                                error_type="solver_error",
                                used_context=bool(method_context),
                                trace={"worker_exception_type": exc.__class__.__name__},
                                raw_output=f"ERROR: {exc}",
                            )

                    failure_type = classify_failure(
                        q.question,
                        result.predicted,
                        q.answer,
                        result.raw_output,
                        result.score,
                        error=result.error,
                        trace=result.trace,
                    )
                    failure_notes = ""
                    if failure_type:
                        failure_notes = generate_failure_notes(
                            q.question,
                            result.predicted,
                            q.answer,
                            result.raw_output,
                            failure_type,
                            error=result.error,
                            trace=result.trace,
                        )

                    result.trace["question_uid"] = q.uid
                    result.trace["question_type"] = q.question_type
                    result.trace["failure_type"] = failure_type
                    result.trace["failure_notes"] = failure_notes
                    result.trace["method_metadata"] = METHOD_METADATA.get(method_name, {})

                    results_by_method[method_name].append(result)
                    if (
                        result.trace.get("error_type") == "timeout"
                        and method_name in PROGRAM_OPTIMIZATION_METHODS
                        and method_name not in disabled_methods
                    ):
                        _close_solver_quietly(solver)
                        disabled_methods[method_name] = {
                            "stage": "evaluation",
                            "status": "timed_out",
                            "error_type": "solver_error",
                            "error_message": (
                                "Method disabled after a prior timeout to avoid reusing "
                                "possibly corrupted staged state"
                            ),
                            "question_uid": q.uid,
                        }

                    _update_run_metadata(
                        run_metadata,
                        method_names=method_names,
                        results_by_method=results_by_method,
                        test_questions_total=len(test),
                        status="running",
                        last_completed_question_uid=q.uid,
                        last_completed_method=method_name,
                    )
                    _persist_run_snapshot(
                        output_dir=output_dir,
                        run_id=run_id,
                        mode_name=mode_name,
                        results_by_method=results_by_method,
                        run_metadata=run_metadata,
                    )

                    status = _result_status_label(result)
                    display_value = result.predicted[:50] if result.predicted else (result.error or "")
                    print(f"{status} | {display_value[:50]} ({result.duration:.1f}s)")

            all_run_results[mode_name] = results_by_method
            _update_run_metadata(
                run_metadata,
                method_names=method_names,
                results_by_method=results_by_method,
                test_questions_total=len(test),
                status="completed",
                phase="finished",
                finished=True,
            )
            _persist_run_snapshot(
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
            )

            print(f"\n{'=' * 70}")
            print(f"RESULTS — {mode_name}")
            print(f"{'=' * 70}")

            summary = compute_summary(results_by_method)
            print_summary(summary)

            type_breakdown = compute_per_type_accuracy(results_by_method)
            print_type_breakdown(type_breakdown)

            failure_counts = compute_failure_counts(results_by_method)
            print_failure_counts(failure_counts)

            print(f"\nResults saved to {output_dir}/{run_id}_*")
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
        except KeyboardInterrupt:
            all_run_results[mode_name] = results_by_method
            if run_metadata.get("status") != "interrupted":
                _update_run_metadata(
                    run_metadata,
                    method_names=method_names,
                    results_by_method=results_by_method,
                    test_questions_total=len(test),
                    status="interrupted",
                    error="Benchmark interrupted by user",
                    phase="finished",
                    finished=True,
                )
                _persist_run_snapshot(
                    output_dir=output_dir,
                    run_id=run_id,
                    mode_name=mode_name,
                    results_by_method=results_by_method,
                    run_metadata=run_metadata,
                )
            raise
        except Exception as exc:  # noqa: BLE001
            all_run_results[mode_name] = results_by_method
            _update_run_metadata(
                run_metadata,
                method_names=method_names,
                results_by_method=results_by_method,
                test_questions_total=len(test),
                status="failed",
                error=str(exc),
                phase="finished",
                finished=True,
            )
            _persist_run_snapshot(
                output_dir=output_dir,
                run_id=run_id,
                mode_name=mode_name,
                results_by_method=results_by_method,
                run_metadata=run_metadata,
            )
            raise
        finally:
            for solver in solvers.values():
                _close_solver_quietly(solver)


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
            **METHOD_METADATA.get(method, {}),
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


def print_summary(summary):
    header = f"{'Method':<44} {'Acc':>7} {'Avg(s)':>8} {'Med(s)':>8} {'Err%':>7} {'Fmt%':>7}"
    print(f"\n{header}")
    print("-" * len(header))
    for method, s in summary.items():
        print(
            f"{method:<44} {s['accuracy']*100:>6.1f}% "
            f"{s['avg_latency']:>7.1f}s {s['median_latency']:>7.1f}s "
            f"{s['error_rate']*100:>6.1f}% {s['format_compliance']*100:>6.1f}%"
        )


def print_type_breakdown(breakdown):
    print("\nPer question-type accuracy:")
    all_types = set()
    for method_types in breakdown.values():
        all_types.update(method_types.keys())

    methods = list(breakdown.keys())
    header = f"  {'Type':<25}" + "".join(f" {m[:22]:>22}" for m in methods)
    print(header)
    print("  " + "-" * (len(header) - 2))

    for qt in sorted(all_types):
        row = f"  {qt:<25}"
        for method in methods:
            info = breakdown[method].get(qt, {"correct": 0, "total": 0, "accuracy": 0})
            cell = f"{info['correct']}/{info['total']:>2} ({info['accuracy']*100:4.0f}%)"
            row += f" {cell:>21}"
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


def save_results(
    output_dir,
    run_id,
    mode_name,
    summary,
    results_by_method,
    type_breakdown,
    failure_counts,
    run_metadata,
):
    prefix = f"{run_id}_{mode_name}"

    detailed = {}
    for method, results in results_by_method.items():
        detailed[method] = [r.to_dict() for r in results]
    _atomic_write_json(output_dir / f"{prefix}_summary.json", summary)
    _atomic_write_json(output_dir / f"{prefix}_detailed.json", detailed)
    _atomic_write_json(
        output_dir / f"{prefix}_failures.json",
        {
            "failure_counts": failure_counts,
            "type_breakdown": type_breakdown,
        },
    )
    _atomic_write_json(output_dir / f"{prefix}_run_metadata.json", run_metadata)


def main():
    parser = argparse.ArgumentParser(
        description="OfficeQA benchmark: native runtime, Track A DSPy rows, and legacy prompt ablations"
    )
    parser.add_argument(
        "--methods",
        type=str,
        default="prompt_baseline,roma_runtime",
        help=(
            "Comma-separated methods. Track A: track_a_dspy_program,track_a_dspy_gepa,"
            "track_a_optimize_anything_planner_text. Native runtime: roma_runtime. "
            "Legacy: legacy_single_prompt_gepa,legacy_prompt_chain_decompose_verify,"
            "legacy_recursive_prompt_chain,legacy_two_stage_prompt. Short aliases: "
            "dspy_program,dspy_gepa,optimize_anything_planner and legacy aliases "
            "roma_lite,rlm_lite,dspy_baseline,gepa_prompt."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Max questions to load from dataset")
    parser.add_argument(
        "--subset",
        choices=["pro", "full", "smoke", "bench5"],
        default="pro",
        help="Dataset subset",
    )
    parser.add_argument("--model", type=str, default="claude-haiku-4-5")
    parser.add_argument("--cli", choices=["claude", "codex", "api"], default="api")
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="ROMA profile used by native runtime and Track A methods. Omit to allow method-specific defaults/auto-routing.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=str,
        default=None,
        help="Path to OfficeQA corpus root or transformed text directory",
    )
    parser.add_argument(
        "--mode",
        choices=["with_corpus", "no_corpus", "both"],
        default="with_corpus",
        help="Corpus policy for all methods",
    )
    parser.add_argument(
        "--native-override",
        action="append",
        default=[],
        help="Extra config override(s) passed to roma_runtime and Track A native module setup (repeatable).",
    )
    parser.add_argument(
        "--optimization-config",
        type=str,
        default=str(DEFAULT_OPTIMIZATION_CONFIG),
        help="OptimizationConfig YAML used by Track A methods.",
    )

    parser.add_argument("--train-size", type=int, default=20)
    parser.add_argument("--val-size", type=int, default=10)
    parser.add_argument("--split-seed", type=int, default=42)

    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Run optimization for trainable methods. Required for track_a_dspy_gepa and track_a_optimize_anything_planner_text.",
    )
    parser.add_argument("--optimize-budget", type=int, default=30, help="Max metric calls / optimization budget")
    parser.add_argument(
        "--solve-timeout-seconds",
        type=int,
        default=300,
        help="Hard timeout per solver/question evaluation. Set 0 to disable timeout enforcement.",
    )
    parser.add_argument(
        "--optimize-timeout-seconds",
        type=float,
        default=1800.0,
        help="Hard timeout per method optimization. Set 0 to disable optimization timeout enforcement.",
    )

    parser.add_argument("--output-dir", type=str, default="benchmarks/officeqa/results")
    parser.add_argument("--debug", action="store_true", help="Debug mode: small splits (5/5/rest)")

    args = parser.parse_args()

    method_names = normalize_method_names(args.methods)
    print(f"Methods: {', '.join(method_names)}")
    if any(method in TRACK_A_METHODS for method in method_names):
        print("Track A methods selected: real DSPy OfficeQA program rows.")
    if any(method in LEGACY_METHODS for method in method_names):
        print("Legacy prompt-chain ablations selected; these are not the native ROMA runtime or Track A program rows.")
    print(f"Model arg: {args.model} | CLI arg: {args.cli}")
    print(f"ROMA profile: {args.profile or 'auto'}")
    print(f"Corpus mode: {args.mode}")
    print(f"Optimization config: {args.optimization_config}")
    print(f"Optimize: {args.optimize} (budget={args.optimize_budget})")
    print(f"Optimize timeout: {args.optimize_timeout_seconds}s")
    print(f"Solve timeout: {args.solve_timeout_seconds}s")

    run_benchmark(args)


if __name__ == "__main__":
    main()
