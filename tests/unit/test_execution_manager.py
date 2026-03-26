import types

from roma_dspy.core.observability.execution_manager import ObservabilityManager
import roma_dspy.core.observability.execution_manager as execution_manager


class _StubSettings:
    def __init__(self, error_message: str | None = None):
        self._error_message = error_message
        self.execution_id = None
        self._roma_execution_id = None
        self._roma_thread_id = None

    def configure(self, **kwargs):
        if self._error_message:
            raise RuntimeError(self._error_message)


def test_configure_dspy_tracing_tolerates_async_task_reconfigure(monkeypatch):
    stub_settings = _StubSettings(
        "dspy.settings.configure(...) can only be called from the same async task that called it first. "
        "Please use `dspy.context(...)` in other async tasks instead."
    )
    stub_dspy = types.SimpleNamespace(settings=stub_settings)

    monkeypatch.setattr(execution_manager, "dspy", stub_dspy)
    monkeypatch.setattr(execution_manager, "MLFLOW_AVAILABLE", False)

    manager = ObservabilityManager()
    manager._configure_dspy_tracing("exec-123")

    assert stub_settings.execution_id == "exec-123"
    assert stub_settings._roma_execution_id == "exec-123"
    assert stub_settings._roma_thread_id is not None


def test_configure_dspy_tracing_tolerates_thread_reconfigure(monkeypatch):
    stub_settings = _StubSettings(
        "dspy.settings.configure() can only be called from the same thread that configured it first"
    )
    stub_dspy = types.SimpleNamespace(settings=stub_settings)

    monkeypatch.setattr(execution_manager, "dspy", stub_dspy)
    monkeypatch.setattr(execution_manager, "MLFLOW_AVAILABLE", False)

    manager = ObservabilityManager()
    manager._configure_dspy_tracing("exec-456")

    assert stub_settings.execution_id == "exec-456"
    assert stub_settings._roma_execution_id == "exec-456"
    assert stub_settings._roma_thread_id is not None
