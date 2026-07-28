"""Harness configuration defaults."""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.providers import ProviderSelection, get_provider

_PROVIDER_ENV_KEYS = (
    "ZENITH_ORCHESTRATOR_PROVIDER",
    "ZENITH_WORKER_PROVIDER",
    "ZENITH_WORKER_ACP_COMMAND",
    "ZENITH_VALIDATOR_PROVIDER",
    "ZENITH_VALIDATOR_ACP_COMMAND",
    "ZENITH_TERMINAL_REVIEWER_PROVIDER",
    "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
)


def _apply_selection_env(
    monkeypatch, harness_home: Path, selection: ProviderSelection
) -> HarnessConfig:
    """Write selection.env() to a clean environment and re-discover from it."""
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in selection.env().items():
        monkeypatch.setenv(key, value)
    return HarnessConfig.discover()


_EFFORT_ENV_VARS = (
    "ZENITH_WORKER_REASONING_EFFORT",
    "ZENITH_VALIDATOR_REASONING_EFFORT",
    "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT",
)


def _clear_effort_env(monkeypatch) -> None:
    for var in _EFFORT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_discover_defaults_to_four_parallel_nodes(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECTS_DIR", raising=False)
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.delenv("ZENITH_MAX_PARALLEL_NODES", raising=False)

    config = HarnessConfig.discover()

    assert config.max_parallel_nodes == 4


def test_discover_explicit_one_uses_serial_parallelism(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_MAX_PARALLEL_NODES", "1")

    config = HarnessConfig.discover()

    assert config.max_parallel_nodes == 1


def test_discover_invalid_parallelism_falls_back_to_default(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_MAX_PARALLEL_NODES", "not-an-int")

    config = HarnessConfig.discover()

    assert config.max_parallel_nodes == 4


def test_discover_reasoning_effort_defaults_to_none(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)

    config = HarnessConfig.discover()

    assert config.worker_reasoning_effort is None
    assert config.validator_reasoning_effort is None
    assert config.terminal_reviewer_reasoning_effort is None


def test_discover_reasoning_effort_per_role(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "high")
    monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "medium")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", "max")

    config = HarnessConfig.discover()

    assert config.worker_reasoning_effort == "high"
    assert config.validator_reasoning_effort == "medium"
    assert config.terminal_reviewer_reasoning_effort == "max"


def test_discover_invalid_reasoning_effort_rejected(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)
    # Not silently ignored: the value lands in a shell command line, and a
    # typo'd downgrade would silently keep spending xhigh.
    monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "extra-high")

    with pytest.raises(ValueError, match="ZENITH_VALIDATOR_REASONING_EFFORT"):
        HarnessConfig.discover()


def test_for_role_reasoning_effort_cascade(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "medium")

    config = HarnessConfig.discover()

    # Unset roles inherit down the same chain as providers/commands:
    # terminal_reviewer -> validator -> worker.
    assert config.for_role("worker").worker_reasoning_effort == "medium"
    assert config.for_role("validator").worker_reasoning_effort == "medium"
    assert config.for_role("terminal_reviewer").worker_reasoning_effort == "medium"


def test_for_role_reasoning_effort_explicit_override_wins(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "xhigh")
    monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "low")

    config = HarnessConfig.discover()

    assert config.for_role("worker").worker_reasoning_effort == "xhigh"
    assert config.for_role("validator").worker_reasoning_effort == "low"
    # terminal_reviewer falls back to the validator setting first.
    assert config.for_role("terminal_reviewer").worker_reasoning_effort == "low"


def test_validator_inherits_custom_worker_command_same_provider(
    monkeypatch,
    harness_home: Path,
) -> None:
    """A custom worker command cascades to a same-provider validator.

    Regression: the or-chain preferred the provider default (always
    truthy) over inheritance, so validators silently ran the stock
    adapter while workers ran the custom command (model flags, wrapper
    scripts, mocks).
    """
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        worker_acp_command="claude-agent-acp --model custom",
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert (
        config.resolved_validator_acp_command
        == "claude-agent-acp --model custom"
    )
    assert (
        config.resolved_terminal_reviewer_acp_command
        == "claude-agent-acp --model custom"
    )
    # for_role is the dispatch-time consumer of the cascade.
    assert (
        config.for_role("validator").worker_acp_command
        == "claude-agent-acp --model custom"
    )
    assert (
        config.for_role("terminal_reviewer").worker_acp_command
        == "claude-agent-acp --model custom"
    )


def test_validator_provider_switch_uses_provider_default(
    monkeypatch,
    harness_home: Path,
) -> None:
    """A different validator provider must NOT inherit the worker command."""
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        worker_acp_command="claude-agent-acp --model custom",
        validation_worker=get_provider("codex"),
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert config.resolved_validator_acp_command == "codex-acp"
    # Reviewer cascades from the validator (same provider as validator).
    assert config.resolved_terminal_reviewer_acp_command == "codex-acp"


def test_explicit_validator_command_beats_inheritance(
    monkeypatch,
    harness_home: Path,
) -> None:
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        worker_acp_command="claude-agent-acp --model custom",
        validation_worker=get_provider("claude"),
        validation_worker_acp_command="claude-agent-acp --model validator",
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert (
        config.resolved_validator_acp_command
        == "claude-agent-acp --model validator"
    )
    # Reviewer inherits the validator's explicit command, not the worker's.
    assert (
        config.resolved_terminal_reviewer_acp_command
        == "claude-agent-acp --model validator"
    )


def test_config_resolution_matches_provider_selection(
    monkeypatch,
    harness_home: Path,
) -> None:
    """config.py and providers.py implement the same cascade — the read
    side of env() must resolve identically to the write side.
    """
    cases = [
        ProviderSelection(
            orchestrator=get_provider("claude"),
            worker=get_provider("claude"),
            worker_acp_command="claude-agent-acp --model custom",
        ),
        ProviderSelection(
            orchestrator=get_provider("claude"),
            worker=get_provider("claude"),
            worker_acp_command="claude-agent-acp --model custom",
            validation_worker=get_provider("codex"),
        ),
        ProviderSelection(
            orchestrator=get_provider("claude"),
            worker=get_provider("codex"),
            worker_acp_command='codex-acp -c model="custom"',
            validation_worker=get_provider("claude"),
        ),
    ]
    for selection in cases:
        config = _apply_selection_env(monkeypatch, harness_home, selection)
        assert (
            config.resolved_validator_acp_command
            == selection.resolved_validation_worker_acp_command
        ), selection
