from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from self_improvement_release import RuntimeIdentityAuthority
from zenith_harness.config import HarnessConfig
from zenith_harness.runtime_identity import _register_node_runtime_identity
from zenith_harness.storage import ProjectStore


def main() -> int:
    harness_home = Path(sys.argv[1]).resolve()
    workspace = Path(sys.argv[2]).resolve()
    project_id = sys.argv[3]
    mission_id = sys.argv[4]
    task_id = sys.argv[5]
    attempt = sys.argv[6]
    identity_path = Path(sys.argv[7])
    config = HarnessConfig(
        bundled_dir=Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled",
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=None,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
    )
    store = ProjectStore(config)
    registration = _register_node_runtime_identity(
        store=store,
        project_id=project_id,
        mission_id=mission_id,
        task_id=task_id,
        spawn_ts=attempt,
        executor="claude-worker",
        provider="claude",
        task_type="work",
        execution_role="worker",
        workspace_dir=workspace,
    )
    if registration.endpoint is None or registration.capability is None:
        print("REJECTED")
        return 0
    with patch.dict(os.environ, registration.environment(), clear=False):
        identity = RuntimeIdentityAuthority.from_current_zenith_runtime().issue()
    identity_path.write_text(
        json.dumps(identity.to_mapping()),
        encoding="utf-8",
    )
    print("MINTED")
    registration.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
