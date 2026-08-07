#!/usr/bin/env python3
"""Mock ACP agent for v5 integration tests.

Reads JSON-RPC messages from stdin (one per line) and responds on stdout.

Handles:
  - initialize: returns agent capabilities
  - session/new: returns a mock session id
  - session/set_mode: no-op ack
  - session/prompt: writes a synthesized handoff payload directly to
    `ZENITH_HANDOFF_PATH` (mimicking what the worker MCP server would do
    in production), then returns stop reason `end_turn`.

Environment variables read from os.environ:
  ZENITH_HANDOFF_PATH  — where to write the synthesized handoff file
  ZENITH_NODE_ID       — node id to embed in handoff
  ZENITH_NODE_TYPE     — work | validate | terminal_review (handoff shape)
  MOCK_ACP_SESSION_PARAMS_PATH — if set, dump session/new params here (JSON)
  ZENITH_VALIDATION_PASSED — '1' to mark items passed=true (validate only)
  MOCK_ACP_CRASH       — '1' to exit immediately without writing
  MOCK_ACP_REQUEST_ATTENTION — '1' to set request_attention=true
  MOCK_ACP_DONE        — '0' to set done=false (default '1')
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _write_handoff() -> None:
    path = os.environ.get("ZENITH_HANDOFF_PATH")
    if not path:
        return
    node_id = os.environ.get("ZENITH_NODE_ID", "unknown")
    node_type = os.environ.get("ZENITH_NODE_TYPE", "work")
    done = os.environ.get("MOCK_ACP_DONE", "1") != "0"
    request_attention = os.environ.get("MOCK_ACP_REQUEST_ATTENTION") == "1"
    if node_type == "terminal_review":
        payload = {
            "done": done,
            "report": "mock terminal review",
        }
    elif node_type == "validate":
        passed = os.environ.get("ZENITH_VALIDATION_PASSED", "1") != "0"
        payload = {
            "node_id": node_id,
            "done": done,
            "report": "mock validate handoff",
            "items": [{"item_id": "VAL-001", "passed": passed}],
            "passed": passed,
            "request_attention": request_attention,
        }
    else:
        payload = {
            "node_id": node_id,
            "done": done,
            "report": "mock work handoff",
            "request_attention": request_attention,
        }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(target)


def _response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main() -> None:
    if os.environ.get("MOCK_ACP_CRASH") == "1":
        sys.exit(1)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            resp = _response(req_id, {
                "protocolVersion": 1,
                "agentCapabilities": {
                    "loadSession": False,
                    "promptCapabilities": {
                        "audio": False,
                        "embeddedContent": False,
                        "image": False,
                    },
                },
                "authMethods": [],
            })
        elif method == "session/new":
            params_path = os.environ.get("MOCK_ACP_SESSION_PARAMS_PATH")
            if params_path:
                Path(params_path).write_text(
                    json.dumps(msg.get("params", {}), indent=2), encoding="utf-8"
                )
            resp = _response(req_id, {"sessionId": "mock-session-1"})
        elif method == "session/set_mode":
            resp = _response(req_id, {})
        elif method == "session/prompt":
            _write_handoff()
            resp = _response(req_id, {"stopReason": "end_turn"})
        else:
            resp = _error(req_id, -32601, "Method not found")
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
