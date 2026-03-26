"""Tests for shared OfficeQA benchmark/runtime primitives."""

import json
from pathlib import Path

import pytest

from benchmarks.officeqa.methods import base as benchmark_base
from benchmarks.officeqa.scripts import officeqa_benchmark as harness
from benchmarks.officeqa.scripts.officeqa_benchmark import normalize_method_names
from roma_dspy.config.schemas import StorageConfig
from roma_dspy.core.storage import FileStorage
from roma_dspy.officeqa import OfficeQAQuestion, extract_officeqa_answer
from roma_dspy.officeqa.dataset import load_source_documents
from roma_dspy.officeqa.runtime import (
    OfficeQARuntimeRunner,
    _extract_native_final_answer,
    resolve_officeqa_corpus_layout,
)
from roma_dspy.types import AgentType, LMBackend
from roma_dspy.tools.core.file import FileToolkit


def test_benchmark_base_reexports_shared_officeqa_primitives():
    assert benchmark_base.OfficeQAQuestion is OfficeQAQuestion
    assert benchmark_base.score_answer("36080", "36,080") == 1.0
    assert benchmark_base.extract_final_answer("FINAL_ANSWER: 123") == "123"
    assert benchmark_base.extract_officeqa_answer("synthesized_answer: 456") == "456"


def test_load_source_documents_reads_from_transformed_directory(tmp_path: Path):
    transformed = tmp_path / "transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    content = load_source_documents(
        "treasury_bulletin_1965_01.txt",
        corpus_dir=transformed,
    )

    assert "317274" in content


def test_load_officeqa_smoke_subset_has_expected_uid_order():
    questions = benchmark_base.load_officeqa_benchmark(subset="smoke")
    assert [question.uid for question in questions] == [
        "UID0001",
        "UID0007",
        "UID0012",
        "UID0013",
        "UID0017",
        "UID0025",
        "UID0028",
        "UID0084",
    ]


def test_load_officeqa_bench5_subset_has_expected_uid_order():
    questions = benchmark_base.load_officeqa_benchmark(subset="bench5")
    assert [question.uid for question in questions] == [
        "UID0001",
        "UID0012",
        "UID0017",
        "UID0025",
        "UID0028",
    ]


def test_resolve_officeqa_corpus_layout_accepts_transformed_directory(tmp_path: Path):
    transformed = tmp_path / "treasury_bulletins_transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("dummy")

    layout = resolve_officeqa_corpus_layout(transformed)
    runner = OfficeQARuntimeRunner(corpus_dir=transformed)
    workspace = runner.create_execution_workspace()

    assert layout.root == transformed.resolve()
    assert workspace.root != layout.root
    assert (workspace.root / "transformed").exists()
    assert workspace.transformed_dir.exists()


def test_extract_native_final_answer_parses_synthesized_answer_field():
    raw = (
        "synthesized_answer: 0.0247\n"
        'reasoning: "CAGR computed from two evidence cards"\n'
        "confidence: high"
    )
    assert _extract_native_final_answer(raw) == "0.0247"
    assert extract_officeqa_answer(raw) == "0.0247"


def test_runtime_can_disable_corpus_autodiscovery():
    with pytest.raises(FileNotFoundError):
        OfficeQARuntimeRunner(allow_autodiscovery=False)


def test_runtime_cli_override_disables_api_only_web_search_toolkits(tmp_path: Path):
    transformed = tmp_path / "transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    runner = OfficeQARuntimeRunner(
        corpus_dir=transformed,
        lm_model="claude-sonnet-4-5",
        lm_backend=LMBackend.CLAUDE,
    )
    config, workspace = runner.create_workspace_config()
    try:
        assert config.agents.executor.llm.backend == LMBackend.CLAUDE
        assert config.agents.planner.llm.model == "claude-sonnet-4-5"

        planner_web = [
            toolkit
            for toolkit in (config.agents.planner.toolkits or [])
            if toolkit.class_name == "WebSearchToolkit"
        ]
        executor_web = [
            toolkit
            for toolkit in (config.agents.executor.toolkits or [])
            if toolkit.class_name == "WebSearchToolkit"
        ]

        assert planner_web and not planner_web[0].enabled
        assert executor_web and not executor_web[0].enabled
    finally:
        runner.cleanup_workspace(workspace)


def test_officeqa_profile_uses_tighter_artifact_injection_modes(tmp_path: Path):
    transformed = tmp_path / "transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    runner = OfficeQARuntimeRunner(corpus_dir=transformed)
    config, workspace = runner.create_workspace_config()
    try:
        assert config.agents.planner.artifact_injection_mode == "none"
        assert config.agents.executor.artifact_injection_mode == "dependencies"
        assert config.agents.aggregator.artifact_injection_mode == "dependencies"
    finally:
        runner.cleanup_workspace(workspace)


def test_officeqa_profile_executor_uses_chunked_file_tools(tmp_path: Path):
    transformed = tmp_path / "transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    runner = OfficeQARuntimeRunner(corpus_dir=transformed)
    config, workspace = runner.create_workspace_config()
    try:
        file_toolkit = next(
            toolkit
            for toolkit in (config.agents.executor.toolkits or [])
            if toolkit.class_name == "FileToolkit"
        )
        assert file_toolkit.include_tools == [
            "list_files",
            "search_files",
            "search_file_content",
            "read_file_lines",
        ]
        assert file_toolkit.toolkit_config["max_inline_read_chars"] == 50000
        assert file_toolkit.toolkit_config["max_excerpt_lines"] == 200
        assert file_toolkit.toolkit_config["max_search_matches"] == 12
    finally:
        runner.cleanup_workspace(workspace)


def test_runtime_stages_source_roots_for_file_and_mcp_toolkits(tmp_path: Path):
    corpus_root = tmp_path / "officeqa_corpus"
    transformed = corpus_root / "transformed"
    raw = corpus_root / "raw"
    transformed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")
    (raw / "bulletin.pdf").write_text("pdf placeholder")

    runner = OfficeQARuntimeRunner(
        corpus_dir=corpus_root,
        disable_filesystem_mcp=False,
    )
    config, workspace = runner.create_workspace_config()
    try:
        assert workspace.transformed_dir.parent == workspace.root
        assert workspace.transformed_dir.exists()
        assert workspace.transformed_dir.is_symlink()

        file_toolkit = next(
            toolkit
            for toolkit in (config.agents.executor.toolkits or [])
            if toolkit.class_name == "FileToolkit"
        )
        allowed_roots = set(file_toolkit.toolkit_config.get("additional_allowed_roots") or [])
        assert transformed.resolve().as_posix() in allowed_roots
        assert raw.resolve().as_posix() in allowed_roots

        filesystem_mcp = next(
            toolkit
            for toolkit in (config.agents.executor.toolkits or [])
            if toolkit.class_name == "MCPToolkit"
            and toolkit.toolkit_config.get("server_name") == "filesystem"
        )
        args = filesystem_mcp.toolkit_config.get("args") or []
        assert workspace.root.as_posix() in args
        assert transformed.resolve().as_posix() in args
        assert raw.resolve().as_posix() in args
        assert Path("/tmp").resolve().as_posix() in args
    finally:
        runner.cleanup_workspace(workspace)


def test_file_toolkit_allows_reads_but_blocks_writes_to_additional_roots(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "transformed").symlink_to(source_root, target_is_directory=True)

    storage = FileStorage(
        config=StorageConfig(base_path=str(workspace_root), flat_structure=True),
        execution_id="officeqa_test",
    )
    toolkit = FileToolkit(
        file_storage=storage,
        additional_allowed_roots=[str(source_root)],
        enable_delete=True,
    )

    read_result = json.loads(toolkit.read_file("transformed/treasury_bulletin_1965_01.txt"))
    assert read_result["success"] is True
    assert "317274" in read_result["content"]

    save_result = json.loads(toolkit.save_file("transformed/new_note.txt", "nope"))
    assert save_result["success"] is False
    assert "Write access denied" in save_result["error"]
    assert not (source_root / "new_note.txt").exists()

    create_result = json.loads(toolkit.create_directory("transformed/nested"))
    assert create_result["success"] is False
    assert "Write access denied" in create_result["error"]

    delete_result = json.loads(
        toolkit.delete_file("transformed/treasury_bulletin_1965_01.txt")
    )
    assert delete_result["success"] is False
    assert "Write access denied" in delete_result["error"]
    assert (source_root / "treasury_bulletin_1965_01.txt").exists()


def test_file_toolkit_supports_targeted_large_file_access(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    big_file = source_root / "treasury_bulletin_1970_06.txt"
    lines = [f"line {idx}" for idx in range(1, 301)]
    lines[149] = "yield spread between US corporate Aa bonds and US treasury bonds"
    lines[150] = "railroad retirement account trust receipts 37921314"
    big_file.write_text("\n".join(lines), encoding="utf-8")

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "transformed").symlink_to(source_root, target_is_directory=True)

    storage = FileStorage(
        config=StorageConfig(base_path=str(workspace_root), flat_structure=True),
        execution_id="officeqa_large_file_test",
    )
    toolkit = FileToolkit(
        file_storage=storage,
        additional_allowed_roots=[str(source_root)],
        max_inline_read_chars=100,
        max_excerpt_lines=25,
        max_search_matches=5,
    )

    oversized_read = json.loads(toolkit.read_file("transformed/treasury_bulletin_1970_06.txt"))
    assert oversized_read["success"] is False
    assert "Use search_file_content() and read_file_lines() instead" in oversized_read["error"]

    search_result = json.loads(
        toolkit.search_file_content(
            "transformed/treasury_bulletin_1970_06.txt",
            "railroad retirement account trust receipts",
            max_matches=3,
            context_lines=1,
        )
    )
    assert search_result["success"] is True
    assert search_result["total_matches"] == 1
    assert search_result["matches"][0]["line_number"] == 151

    slice_result = json.loads(
        toolkit.read_file_lines(
            "transformed/treasury_bulletin_1970_06.txt",
            start_line=149,
            num_lines=4,
        )
    )
    assert slice_result["success"] is True
    assert slice_result["start_line"] == 149
    assert slice_result["end_line"] == 152
    assert "railroad retirement account trust receipts 37921314" in slice_result["content"]


def test_hybrid_profile_uses_custom_officeqa_executor(tmp_path: Path):
    transformed = tmp_path / "transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    runner = OfficeQARuntimeRunner(profile="officeqa/hybrid", corpus_dir=transformed)
    config, workspace = runner.create_workspace_config()
    try:
        assert config.runtime.max_depth == 5
        assert config.runtime.max_concurrency == 1
        assert config.agents.executor.module_class == "roma_dspy.officeqa:OfficeQARLMExecutor"

        from roma_dspy.core.factory.agent_factory import AgentFactory
        from roma_dspy.officeqa import OfficeQARLMExecutor

        executor = AgentFactory().create_agent(AgentType.EXECUTOR, config.agents.executor)
        assert isinstance(executor, OfficeQARLMExecutor)
    finally:
        runner.cleanup_workspace(workspace)


def test_resolve_method_profile_only_auto_upgrades_rlm_methods_when_profile_is_omitted():
    assert harness.resolve_method_profile("rlm_runtime", None) == "officeqa/hybrid"
    assert harness.resolve_method_profile("rlm_dspy_program", None) == "officeqa/hybrid"
    assert (
        harness.resolve_method_profile(
            "rlm_runtime",
            "officeqa/default",
            profile_was_explicit=True,
        )
        == "officeqa/default"
    )
    assert (
        harness.resolve_method_profile(
            "roma_runtime",
            "officeqa/default",
            profile_was_explicit=True,
        )
        == "officeqa/default"
    )


def test_normalize_method_names_maps_legacy_and_track_a_aliases():
    assert normalize_method_names(
        "roma_lite,roma_runtime,roma_gepa_plus,roma_optimize_anything,rlm_runtime,dspy_baseline,dspy_program,dspy_gepa,optimize_anything_planner,rlm_dspy_program,rlm_dspy_gepa,rlm_optimize_anything"
    ) == [
        "legacy_prompt_chain_decompose_verify",
        "roma_runtime",
        "roma_gepa_plus",
        "roma_optimize_anything",
        "rlm_runtime",
        "legacy_two_stage_prompt",
        "track_a_dspy_program",
        "track_a_dspy_gepa",
        "track_a_optimize_anything_planner_text",
        "rlm_dspy_program",
        "rlm_dspy_gepa",
        "rlm_optimize_anything_planner_text",
    ]
