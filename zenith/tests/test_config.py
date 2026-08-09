"""Harness configuration defaults."""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig

_EFFORT_ENV_VARS = (
    "ZENITH_WORKER_REASONING_EFFORT",
    "ZENITH_VALIDATOR_REASONING_EFFORT",
    "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT",
)


_MODEL_ENV_VARS = (
    "ZENITH_WORKER_MODEL",
    "ZENITH_VALIDATOR_MODEL",
    "ZENITH_TERMINAL_REVIEWER_MODEL",
)


def _clear_effort_env(monkeypatch) -> None:
    for var in _EFFORT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _clear_model_env(monkeypatch) -> None:
    for var in _MODEL_ENV_VARS:
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


def test_discover_model_defaults_to_none(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)

    config = HarnessConfig.discover()

    # None means "whatever the provider picks" — no pin.
    assert config.worker_model is None
    assert config.validator_model is None
    assert config.terminal_reviewer_model is None


def test_discover_model_per_role(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "claude-opus-5[1m]")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_MODEL", "gpt-5.5")

    config = HarnessConfig.discover()

    assert config.worker_model == "opus"
    assert config.validator_model == "claude-opus-5[1m]"
    assert config.terminal_reviewer_model == "gpt-5.5"


def test_discover_model_with_shell_metacharacters_rejected(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    # The resolved value is spliced into a shell command line for codex
    # (`-c model="..."`), so anything that could break out of the quotes is
    # rejected at discovery rather than executed.
    monkeypatch.setenv("ZENITH_WORKER_MODEL", 'opus"; rm -rf /; #')

    with pytest.raises(ValueError, match="ZENITH_WORKER_MODEL"):
        HarnessConfig.discover()


def test_discover_model_with_trailing_newline_rejected(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    # `$` matches before a trailing newline, so a pattern anchored with it
    # would accept "opus\n" — which then gets written into .codex/config.toml
    # as an unescaped newline inside a TOML basic string and corrupts the file.
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus\n")

    with pytest.raises(ValueError, match="ZENITH_WORKER_MODEL"):
        HarnessConfig.discover()


def test_for_role_model_cascade(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus")

    config = HarnessConfig.discover()

    # Same inheritance chain as providers/commands/effort:
    # terminal_reviewer -> validator -> worker.
    assert config.for_role("worker").worker_model == "opus"
    assert config.for_role("validator").worker_model == "opus"
    assert config.for_role("terminal_reviewer").worker_model == "opus"


def _clear_provider_env(monkeypatch) -> None:
    for var in (
        "ZENITH_WORKER_PROVIDER",
        "ZENITH_VALIDATOR_PROVIDER",
        "ZENITH_TERMINAL_REVIEWER_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)


def test_for_role_model_does_not_cascade_across_providers(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "codex")
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "gpt-5.5")
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")

    config = HarnessConfig.discover()

    # Reasoning efforts are provider-neutral vocabulary, so they cascade freely.
    # Model ids are not: inheriting the codex worker's pin would hand
    # ANTHROPIC_MODEL="gpt-5.5" to a claude validator and break every
    # validation session. An unpinned role on a different provider falls back
    # to that provider's own default instead.
    assert config.for_role("worker").worker_model == "gpt-5.5"
    assert config.for_role("validator").worker_model is None
    assert config.for_role("terminal_reviewer").worker_model is None


def test_for_role_model_cascades_when_provider_matches(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus")
    # Spelling the provider out explicitly must not defeat inheritance.
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")

    config = HarnessConfig.discover()

    assert config.for_role("validator").worker_model == "opus"
    assert config.for_role("terminal_reviewer").worker_model == "opus"


def test_for_role_model_explicit_pin_survives_provider_switch(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "codex")
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "gpt-5.5")
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")

    config = HarnessConfig.discover()

    # Only inheritance is provider-gated; a pin set for this role is obeyed.
    assert config.for_role("validator").worker_model == "opus"


def test_for_role_terminal_reviewer_model_does_not_inherit_across_providers(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", "codex")

    config = HarnessConfig.discover()

    # The validator's claude pin must not reach a codex terminal reviewer.
    assert config.for_role("terminal_reviewer").worker_model is None


def test_for_role_terminal_reviewer_explicit_model_beats_validator_pin(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "sonnet")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_MODEL", "claude-opus-5[1m]")

    config = HarnessConfig.discover()

    # Precedence within the chain: own pin first, then validator, then worker.
    assert config.for_role("terminal_reviewer").worker_model == "claude-opus-5[1m]"


def test_for_role_model_explicit_override_wins(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "sonnet")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")

    config = HarnessConfig.discover()

    assert config.for_role("worker").worker_model == "sonnet"
    assert config.for_role("validator").worker_model == "opus"
    # terminal_reviewer falls back to the validator setting first.
    assert config.for_role("terminal_reviewer").worker_model == "opus"
