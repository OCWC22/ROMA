import json
import multiprocessing
import pickle
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.officeqa.methods.base import (
    BaseSolver,
    OfficeQAQuestion,
    OfficeQAModuleBenchmarkSolver,
    OptimizableSolver,
    SolverResult,
    build_error_solver_result,
)
from benchmarks.officeqa.scripts import officeqa_benchmark as harness
from benchmarks.officeqa.scripts.failure_analysis import (
    classify_failure,
    generate_failure_notes,
)


class SlowSolver(BaseSolver):
    name = "slow"

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        time.sleep(1.0)
        return SolverResult(
            method=self.name,
            predicted="done",
            expected=question.answer,
            score=0.0,
            duration=1.0,
            used_context=bool(context),
            raw_output="done",
            final_answer="done",
            trace={},
            error=None,
        )


class InterruptingSolver(BaseSolver):
    name = "interrupting"

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        raise KeyboardInterrupt()


class ContextRecordingSolver(BaseSolver):
    name = "context_recording"

    def __init__(self):
        self.contexts = []

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        self.contexts.append(context)
        return SolverResult(
            method=self.name,
            predicted=question.answer,
            expected=question.answer,
            score=1.0,
            duration=0.0,
            used_context=bool(context),
            raw_output=question.answer,
            final_answer=question.answer,
            trace={},
            error=None,
        )


class ClosingSolver(BaseSolver):
    name = "closing"

    def __init__(self):
        self.closed = 0

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        return SolverResult(
            method=self.name,
            predicted=question.answer,
            expected=question.answer,
            score=1.0,
            duration=0.0,
            used_context=bool(context),
            raw_output=question.answer,
            final_answer=question.answer,
            trace={},
            error=None,
        )

    def close(self) -> None:
        self.closed += 1


class DummyConn:
    def __init__(self):
        self.payloads = []
        self.closed = False

    def send(self, payload) -> None:
        self.payloads.append(payload)

    def close(self) -> None:
        self.closed = True


class RecordingModule:
    def __init__(self):
        self.loaded_path = None

    def load(self, path: str) -> None:
        self.loaded_path = path


class RebuildTrackingSolver(OfficeQAModuleBenchmarkSolver):
    name = "rebuild_tracking"

    def __init__(self):
        super().__init__(model="sonnet", cli="api", profile="officeqa/hybrid")
        self.build_configs = []

    def _build_module(self, config=None):
        self.build_configs.append(config)
        return RecordingModule()


class SlowOptimizingSolver(OptimizableSolver):
    name = "slow_opt"

    def optimize(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        time.sleep(1.0)

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        raise AssertionError("solve should not run after optimization timeout")


class ExplodingOptimizingSolver(OptimizableSolver):
    name = "explode_opt"

    def optimize(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        raise RuntimeError("optimizer boom")

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        raise AssertionError("solve should not run after optimization failure")


class InterruptingOptimizingSolver(OptimizableSolver):
    name = "interrupt_opt"

    def optimize(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        raise KeyboardInterrupt()

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        raise AssertionError("solve should not run after optimization interruption")


def _question(uid: str = "UIDTEST") -> OfficeQAQuestion:
    return OfficeQAQuestion(
        uid=uid,
        question="What were total expenditures in 1940?",
        answer="2602",
        source_docs="",
        source_files="treasury_bulletin_1941_01.txt",
        difficulty="hard",
    )


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="Per-solve timeout test requires multiprocessing fork support.",
)
def test_execute_solve_with_timeout_returns_timeout_result():
    result = harness._execute_solve_with_timeout(
        solver=SlowSolver(),
        method_name="slow",
        question=_question(),
        context="some context",
        solve_timeout_seconds=0.1,
    )

    assert result.score == 0.0
    assert result.error is not None
    assert result.trace["error_type"] == "timeout"
    assert result.trace["timeout_seconds"] == 0.1
    assert result.used_context is True


def test_child_solve_entry_closes_solver_after_worker_run():
    solver = ClosingSolver()
    conn = DummyConn()

    harness._child_solve_entry(conn, solver, _question(), "worker context")

    assert solver.closed == 1
    assert conn.closed is True
    assert conn.payloads[0]["kind"] == "result"


def test_module_benchmark_solver_rebuilds_optimized_program_after_pickle(tmp_path: Path):
    solver = RebuildTrackingSolver()
    solver._module = RecordingModule()
    program_path = tmp_path / "optimized_program.json"
    program_path.write_text("{}", encoding="utf-8")
    solver._optimization_metadata = {
        "optimization_mode": "gepa",
        "program_path": str(program_path.resolve()),
    }

    restored = pickle.loads(pickle.dumps(solver))

    assert restored._module is None
    rebuilt_module = restored._ensure_module()

    assert isinstance(rebuilt_module, RecordingModule)
    assert rebuilt_module.loaded_path == str(program_path.resolve())
    assert len(restored.build_configs) == 1
    assert restored.build_configs[0] is None


def test_module_benchmark_solver_rebuilds_text_artifact_after_pickle(tmp_path: Path):
    solver = RebuildTrackingSolver()
    artifact_path = tmp_path / "planner_optimized.jinja"
    artifact_path.write_text("{{ question }}", encoding="utf-8")
    solver._optimization_metadata = {
        "optimization_mode": "optimize_anything",
        "artifact_component": "planner",
        "artifact_path": str(artifact_path.resolve()),
    }

    restored = pickle.loads(pickle.dumps(solver))
    rebuilt_module = restored._ensure_module()
    rebuilt_config = restored.build_configs[0]

    assert isinstance(rebuilt_module, RecordingModule)
    assert rebuilt_config is not None
    assert rebuilt_config.artifact_component == "planner"
    assert rebuilt_config.officeqa_artifact_component == "planner"
    assert rebuilt_config.artifact_path == str(artifact_path.resolve())
    assert rebuilt_config.officeqa_artifact_path == str(artifact_path.resolve())


def test_persist_run_snapshot_writes_canonical_files(tmp_path: Path):
    results_by_method = {
        "roma_runtime": [
            SolverResult(
                method="roma_runtime",
                predicted="2602",
                expected="2602",
                score=1.0,
                duration=2.5,
                used_context=True,
                raw_output="2602",
                final_answer="2602",
                trace={"question_uid": "UID0001", "question_type": "sum_or_aggregation"},
            )
        ],
        "roma_gepa_plus": [],
    }
    run_metadata = {
        "run_id": "run_test",
        "mode": "with_corpus",
        "methods": ["roma_runtime", "roma_gepa_plus"],
        "method_metadata": {},
        "profile": "officeqa/default",
        "subset": "bench5",
        "optimization_config": None,
        "optimize": False,
        "optimize_budget": 1,
        "solve_timeout_seconds": 300,
        "status": "running",
        "started_at": "2026-03-24T00:00:00+00:00",
        "updated_at": None,
        "finished_at": None,
        "error": None,
        "last_completed_question_uid": None,
        "last_completed_method": None,
    }

    harness._update_run_metadata(
        run_metadata,
        method_names=["roma_runtime", "roma_gepa_plus"],
        results_by_method=results_by_method,
        test_questions_total=1,
        status="running",
        last_completed_question_uid="UID0001",
        last_completed_method="roma_runtime",
    )
    harness._persist_run_snapshot(
        output_dir=tmp_path,
        run_id="run_test",
        mode_name="with_corpus",
        results_by_method=results_by_method,
        run_metadata=run_metadata,
    )

    summary_path = tmp_path / "run_test_with_corpus_summary.json"
    detailed_path = tmp_path / "run_test_with_corpus_detailed.json"
    failures_path = tmp_path / "run_test_with_corpus_failures.json"
    metadata_path = tmp_path / "run_test_with_corpus_run_metadata.json"

    assert summary_path.exists()
    assert detailed_path.exists()
    assert failures_path.exists()
    assert metadata_path.exists()

    detailed = json.loads(detailed_path.read_text())
    metadata = json.loads(metadata_path.read_text())

    assert list(detailed.keys()) == ["roma_runtime", "roma_gepa_plus"]
    assert metadata["progress"]["completed_solves"] == 1
    assert metadata["progress"]["last_completed_method"] == "roma_runtime"


def test_tool_search_methods_skip_preloading_raw_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    question = _question("UIDCTX")
    solver = ContextRecordingSolver()
    load_calls = {"count": 0}

    args = SimpleNamespace(
        methods="rlm_runtime",
        limit=1,
        subset="bench5",
        model="sonnet",
        cli="claude",
        profile="officeqa/default",
        corpus_dir=str(tmp_path),
        mode="with_corpus",
        native_override=[],
        train_size=0,
        val_size=0,
        split_seed=42,
        optimize=False,
        optimize_budget=1,
        optimize_timeout_seconds=0,
        solve_timeout_seconds=0,
        output_dir=str(tmp_path),
        debug=False,
    )

    monkeypatch.setattr(harness, "register_methods", lambda: None)
    monkeypatch.setattr(harness, "load_officeqa_benchmark", lambda subset, limit=None: [question])
    monkeypatch.setattr(harness, "save_splits", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "normalize_method_names", lambda _: ["rlm_runtime"])
    monkeypatch.setattr(
        harness,
        "load_optimization_config",
        lambda _args: (SimpleNamespace(dataset_name="officeqa"), None),
    )
    monkeypatch.setattr(harness, "instantiate_solver", lambda *args, **kwargs: solver)
    monkeypatch.setattr(
        harness,
        "maybe_optimize_solvers",
        lambda *args, **kwargs: {
            "rlm_runtime": {
                "status": "not_required",
                "error": None,
                "error_type": None,
                "artifact_dir": None,
                "trace": {},
            }
        },
    )

    def fake_load_source_documents(*args, **kwargs):
        load_calls["count"] += 1
        return "DOCUMENT CONTEXT SHOULD NOT BE LOADED"

    monkeypatch.setattr(harness, "load_source_documents", fake_load_source_documents)

    harness.run_benchmark(args)

    assert load_calls["count"] == 0
    assert solver.contexts == [""]


def test_failure_classification_handles_timeout_and_solver_errors():
    timeout_result = build_error_solver_result(
        method="roma_runtime",
        question=_question(),
        duration=3.0,
        error_message="Solve exceeded 3 seconds",
        error_type="timeout",
        used_context=True,
        trace={"timeout_seconds": 3},
        raw_output="TIMEOUT: Solve exceeded 3 seconds",
    )
    timeout_type = classify_failure(
        timeout_result.expected,
        timeout_result.predicted,
        timeout_result.expected,
        timeout_result.raw_output,
        timeout_result.score,
        error=timeout_result.error,
        trace=timeout_result.trace,
    )
    timeout_notes = generate_failure_notes(
        timeout_result.expected,
        timeout_result.predicted,
        timeout_result.expected,
        timeout_result.raw_output,
        timeout_type,
        error=timeout_result.error,
        trace=timeout_result.trace,
    )

    assert timeout_type == "timeout"
    assert "3" in timeout_notes

    error_result = build_error_solver_result(
        method="roma_runtime",
        question=_question(),
        duration=1.0,
        error_message="boom",
        error_type="solver_error",
        used_context=False,
        trace={"worker_exception_type": "RuntimeError"},
        raw_output="ERROR: boom",
    )
    error_type = classify_failure(
        error_result.expected,
        error_result.predicted,
        error_result.expected,
        error_result.raw_output,
        error_result.score,
        error=error_result.error,
        trace=error_result.trace,
    )
    error_notes = generate_failure_notes(
        error_result.expected,
        error_result.predicted,
        error_result.expected,
        error_result.raw_output,
        error_type,
        error=error_result.error,
        trace=error_result.trace,
    )

    assert error_type == "solver_error"
    assert "RuntimeError" in error_notes


def test_run_benchmark_persists_interrupted_partial_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    question = _question("UIDINT")
    args = SimpleNamespace(
        methods="roma_runtime",
        limit=1,
        subset="bench5",
        model="sonnet",
        cli="claude",
        profile="officeqa/default",
        corpus_dir=None,
        mode="no_corpus",
        native_override=[],
        optimization_config="unused.yaml",
        train_size=0,
        val_size=0,
        split_seed=42,
        optimize=False,
        optimize_budget=1,
        optimize_timeout_seconds=0,
        solve_timeout_seconds=0,
        output_dir=str(tmp_path),
        debug=False,
    )

    monkeypatch.setattr(harness, "register_methods", lambda: None)
    monkeypatch.setattr(harness, "load_officeqa_benchmark", lambda subset, limit=None: [question])
    monkeypatch.setattr(harness, "save_splits", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "normalize_method_names", lambda _: ["roma_runtime"])
    monkeypatch.setattr(
        harness,
        "load_optimization_config",
        lambda _args: (SimpleNamespace(dataset_name="officeqa"), None),
    )
    monkeypatch.setattr(harness, "instantiate_solver", lambda *args, **kwargs: InterruptingSolver())
    monkeypatch.setattr(
        harness,
        "maybe_optimize_solvers",
        lambda *args, **kwargs: {
            "roma_runtime": {
                "status": "not_required",
                "error": None,
                "error_type": None,
                "artifact_dir": None,
                "trace": {},
            }
        },
    )

    with pytest.raises(KeyboardInterrupt):
        harness.run_benchmark(args)

    metadata_paths = sorted(tmp_path.glob("*_run_metadata.json"))
    detailed_paths = sorted(tmp_path.glob("*_detailed.json"))

    assert metadata_paths
    assert detailed_paths

    metadata = json.loads(metadata_paths[0].read_text())
    detailed = json.loads(detailed_paths[0].read_text())
    result = detailed["roma_runtime"][0]

    assert metadata["status"] == "interrupted"
    assert metadata["progress"]["completed_solves"] == 1
    assert result["trace"]["error_type"] == "interrupted"
    assert result["trace"]["failure_type"] == "interrupted"


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="Timeout quarantine test requires multiprocessing fork support.",
)
def test_run_benchmark_disables_staged_solver_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    questions = [_question("UIDA"), _question("UIDB")]
    args = SimpleNamespace(
        methods="track_a_dspy_program",
        limit=2,
        subset="bench5",
        model="sonnet",
        cli="claude",
        profile="officeqa/default",
        corpus_dir=None,
        mode="no_corpus",
        native_override=[],
        optimization_config="unused.yaml",
        train_size=0,
        val_size=0,
        split_seed=42,
        optimize=False,
        optimize_budget=1,
        optimize_timeout_seconds=0,
        solve_timeout_seconds=0.1,
        output_dir=str(tmp_path),
        debug=False,
    )

    monkeypatch.setattr(harness, "register_methods", lambda: None)
    monkeypatch.setattr(harness, "load_officeqa_benchmark", lambda subset, limit=None: questions)
    monkeypatch.setattr(harness, "save_splits", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "normalize_method_names", lambda _: ["track_a_dspy_program"])
    monkeypatch.setattr(
        harness,
        "load_optimization_config",
        lambda _args: (SimpleNamespace(dataset_name="officeqa"), None),
    )
    monkeypatch.setattr(harness, "instantiate_solver", lambda *args, **kwargs: SlowSolver())
    monkeypatch.setattr(
        harness,
        "maybe_optimize_solvers",
        lambda *args, **kwargs: {
            "track_a_dspy_program": {
                "status": "not_required",
                "error": None,
                "error_type": None,
                "artifact_dir": None,
                "trace": {},
            }
        },
    )

    harness.run_benchmark(args)

    detailed_paths = sorted(tmp_path.glob("*_detailed.json"))
    assert detailed_paths
    detailed = json.loads(detailed_paths[0].read_text())
    results = detailed["track_a_dspy_program"]

    assert len(results) == 2
    assert results[0]["trace"]["error_type"] == "timeout"
    assert results[1]["trace"]["error_type"] == "solver_error"
    assert results[1]["trace"]["disabled_after_timeout"] is True


@pytest.mark.skipif(
    not harness._supports_optimization_timeout(),
    reason="Optimization timeout test requires SIGALRM/setitimer support.",
)
def test_run_benchmark_marks_optimization_timeout_and_emits_placeholder_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    questions = [_question("UIDA"), _question("UIDB"), _question("UIDC")]
    args = SimpleNamespace(
        methods="track_a_dspy_gepa",
        limit=2,
        subset="bench5",
        model="sonnet",
        cli="claude",
        profile="officeqa/default",
        corpus_dir=None,
        mode="no_corpus",
        native_override=[],
        optimization_config="unused.yaml",
        train_size=1,
        val_size=0,
        split_seed=42,
        optimize=True,
        optimize_budget=1,
        optimize_timeout_seconds=0.1,
        solve_timeout_seconds=0,
        output_dir=str(tmp_path),
        debug=False,
    )

    monkeypatch.setattr(harness, "register_methods", lambda: None)
    monkeypatch.setattr(harness, "load_officeqa_benchmark", lambda subset, limit=None: questions)
    monkeypatch.setattr(harness, "save_splits", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "normalize_method_names", lambda _: ["track_a_dspy_gepa"])
    monkeypatch.setattr(
        harness,
        "load_optimization_config",
        lambda _args: (SimpleNamespace(dataset_name="officeqa"), None),
    )
    monkeypatch.setattr(harness, "instantiate_solver", lambda *args, **kwargs: SlowOptimizingSolver())

    harness.run_benchmark(args)

    detailed_paths = sorted(tmp_path.glob("*_detailed.json"))
    metadata_paths = sorted(tmp_path.glob("*_run_metadata.json"))
    assert detailed_paths and metadata_paths

    detailed = json.loads(detailed_paths[0].read_text())
    metadata = json.loads(metadata_paths[0].read_text())
    results = detailed["track_a_dspy_gepa"]

    assert len(results) == 2
    assert all(result["trace"]["error_stage"] == "optimization" for result in results)
    assert all(result["trace"]["error_type"] == "timeout" for result in results)
    assert metadata["optimization"]["methods"]["track_a_dspy_gepa"]["status"] == "timed_out"


def test_run_benchmark_marks_optimization_failure_and_emits_placeholder_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    questions = [_question("UIDA"), _question("UIDB"), _question("UIDC")]
    args = SimpleNamespace(
        methods="track_a_dspy_gepa",
        limit=2,
        subset="bench5",
        model="sonnet",
        cli="claude",
        profile="officeqa/default",
        corpus_dir=None,
        mode="no_corpus",
        native_override=[],
        optimization_config="unused.yaml",
        train_size=1,
        val_size=0,
        split_seed=42,
        optimize=True,
        optimize_budget=1,
        optimize_timeout_seconds=0,
        solve_timeout_seconds=0,
        output_dir=str(tmp_path),
        debug=False,
    )

    monkeypatch.setattr(harness, "register_methods", lambda: None)
    monkeypatch.setattr(harness, "load_officeqa_benchmark", lambda subset, limit=None: questions)
    monkeypatch.setattr(harness, "save_splits", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "normalize_method_names", lambda _: ["track_a_dspy_gepa"])
    monkeypatch.setattr(
        harness,
        "load_optimization_config",
        lambda _args: (SimpleNamespace(dataset_name="officeqa"), None),
    )
    monkeypatch.setattr(harness, "instantiate_solver", lambda *args, **kwargs: ExplodingOptimizingSolver())

    harness.run_benchmark(args)

    detailed_paths = sorted(tmp_path.glob("*_detailed.json"))
    metadata_paths = sorted(tmp_path.glob("*_run_metadata.json"))
    detailed = json.loads(detailed_paths[0].read_text())
    metadata = json.loads(metadata_paths[0].read_text())

    assert len(detailed["track_a_dspy_gepa"]) == 2
    assert all(
        result["trace"]["error_stage"] == "optimization"
        for result in detailed["track_a_dspy_gepa"]
    )
    assert all(
        result["trace"]["error_type"] == "solver_error"
        for result in detailed["track_a_dspy_gepa"]
    )
    assert metadata["optimization"]["methods"]["track_a_dspy_gepa"]["status"] == "failed"


def test_run_benchmark_persists_interrupted_optimization_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    questions = [_question("UIDA"), _question("UIDB")]
    args = SimpleNamespace(
        methods="track_a_dspy_gepa",
        limit=2,
        subset="bench5",
        model="sonnet",
        cli="claude",
        profile="officeqa/default",
        corpus_dir=None,
        mode="no_corpus",
        native_override=[],
        optimization_config="unused.yaml",
        train_size=1,
        val_size=0,
        split_seed=42,
        optimize=True,
        optimize_budget=1,
        optimize_timeout_seconds=0,
        solve_timeout_seconds=0,
        output_dir=str(tmp_path),
        debug=False,
    )

    monkeypatch.setattr(harness, "register_methods", lambda: None)
    monkeypatch.setattr(harness, "load_officeqa_benchmark", lambda subset, limit=None: questions)
    monkeypatch.setattr(harness, "save_splits", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "normalize_method_names", lambda _: ["track_a_dspy_gepa"])
    monkeypatch.setattr(
        harness,
        "load_optimization_config",
        lambda _args: (SimpleNamespace(dataset_name="officeqa"), None),
    )
    monkeypatch.setattr(harness, "instantiate_solver", lambda *args, **kwargs: InterruptingOptimizingSolver())

    with pytest.raises(KeyboardInterrupt):
        harness.run_benchmark(args)

    metadata_paths = sorted(tmp_path.glob("*_run_metadata.json"))
    detailed_paths = sorted(tmp_path.glob("*_detailed.json"))
    assert metadata_paths and detailed_paths

    metadata = json.loads(metadata_paths[0].read_text())
    detailed = json.loads(detailed_paths[0].read_text())

    assert metadata["status"] == "interrupted"
    assert metadata["phase"] == "finished"
    assert detailed["track_a_dspy_gepa"] == []
