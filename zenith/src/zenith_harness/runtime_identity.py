from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import struct
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import ProjectStore


AUTHORITY_ENV_ENDPOINT = "SELF_IMPROVEMENT_ZENITH_AUTHORITY_ENDPOINT"
AUTHORITY_ENV_CAPABILITY = "SELF_IMPROVEMENT_ZENITH_AUTHORITY_CAPABILITY"
AUTHORITY_ENV_TOKEN = "SELF_IMPROVEMENT_ZENITH_AUTHORITY_TOKEN"
AUTHORITY_ID = "zenith-controller-channel-v1"
REGISTERED_RUNTIME_ROOT = Path(__file__).resolve().parents[2]
_MAX_MESSAGE_BYTES = 64 * 1024
_MAX_RECEIPTS = 4096
_RECEIPT_TTL_SECONDS = 60 * 60
_MAX_REQUESTS_PER_DISPATCH = 128
_CONNECTION_TIMEOUT_SECONDS = 1.0


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class _IdentityReceipt:
    identity: dict[str, object]
    runtime_receipt_hash: str
    controller_pid: int
    issued_monotonic: float
    consumed: bool = False


@dataclass(frozen=True)
class _VerificationReceipt:
    binding_hashes: tuple[str, ...]
    scope: tuple[str, str, str]
    issued_monotonic: float
    consumed: bool = False


class _ReceiptRegistry:
    """Controller-owned, bounded, atomic, one-use receipt registry."""

    def __init__(self) -> None:
        self._identities: OrderedDict[str, _IdentityReceipt] = OrderedDict()
        self._verifications: OrderedDict[str, _VerificationReceipt] = OrderedDict()
        self._lock = threading.Lock()

    def _prune_locked(self, now: float) -> None:
        minimum = now - _RECEIPT_TTL_SECONDS
        for records in (self._identities, self._verifications):
            expired = [key for key, value in records.items() if value.issued_monotonic < minimum]
            for key in expired:
                records.pop(key, None)
            while len(records) >= _MAX_RECEIPTS:
                records.popitem(last=False)

    def issue_identity(
        self,
        *,
        identity: dict[str, object],
        runtime_receipt_hash: str,
        nonce: str,
        capability: str,
    ) -> str:
        now = time.monotonic()
        receipt_hash = _content_hash(
            {
                "schema_version": 1,
                "authority_id": AUTHORITY_ID,
                "controller_pid": os.getpid(),
                "identity_hash": _content_hash(identity),
                "runtime_receipt_hash": runtime_receipt_hash,
                "nonce": nonce,
                "capability_hash": _content_hash(capability),
                "receipt_secret": secrets.token_hex(32),
            }
        )
        with self._lock:
            self._prune_locked(now)
            self._identities[receipt_hash] = _IdentityReceipt(
                identity=dict(identity),
                runtime_receipt_hash=runtime_receipt_hash,
                controller_pid=os.getpid(),
                issued_monotonic=now,
            )
        return receipt_hash

    def consume_identities(
        self,
        identities: list[dict[str, object]],
        *,
        nonce: str,
        authorizer_identity: dict[str, object] | None = None,
        verdict_binding: tuple[str, ...] | None = None,
    ) -> tuple[str, str | None]:
        parsed: list[tuple[str, str, str, dict[str, object]]] = []
        for envelope in identities:
            attestation = envelope.get("attestation")
            if not isinstance(attestation, dict):
                return "REJECTED", None
            claims = dict(envelope)
            claims.pop("attestation", None)
            identity_hash = _content_hash(claims)
            receipt_hash = attestation.get("channel_receipt_hash")
            runtime_hash = attestation.get("runtime_receipt_hash")
            controller_pid = attestation.get("controller_pid")
            if (
                not isinstance(receipt_hash, str)
                or len(receipt_hash) != 64
                or not isinstance(runtime_hash, str)
                or len(runtime_hash) != 64
                or controller_pid != os.getpid()
                or attestation.get("identity_hash") != identity_hash
                or attestation.get("authority_id") != AUTHORITY_ID
            ):
                return "REJECTED", None
            parsed.append((receipt_hash, runtime_hash, identity_hash, claims))
        if not parsed or len({item[0] for item in parsed}) != len(parsed):
            return "REJECTED", None
        if verdict_binding is not None:
            if len(parsed) != 2 or authorizer_identity is None:
                return "REJECTED", None
            builder = parsed[0][3]
            verifier = parsed[1][3]
            if (
                builder.get("task_type") != "work"
                or builder.get("execution_role") != "worker"
                or verifier.get("task_type") != "validate"
                or verifier.get("execution_role") != "validator"
                or authorizer_identity != verifier
                or any(
                    builder.get(name) != verifier.get(name)
                    for name in ("orchestrator", "project_id", "mission_id")
                )
                or any(
                    builder.get(name) == verifier.get(name)
                    for name in ("task_id", "task_attempt_id", "executor")
                )
                or len(verdict_binding) != 3
            ):
                return "REJECTED", None
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            records: list[_IdentityReceipt] = []
            for receipt_hash, runtime_hash, _identity_hash, claims in parsed:
                record = self._identities.get(receipt_hash)
                if record is None:
                    return "REJECTED", None
                if record.consumed:
                    return "REPLAY", None
                if (
                    record.identity != claims
                    or record.runtime_receipt_hash != runtime_hash
                    or record.controller_pid != os.getpid()
                ):
                    return "REJECTED", None
                records.append(record)
            for (receipt_hash, *_rest), record in zip(parsed, records, strict=True):
                self._identities[receipt_hash] = _IdentityReceipt(
                    identity=record.identity,
                    runtime_receipt_hash=record.runtime_receipt_hash,
                    controller_pid=record.controller_pid,
                    issued_monotonic=record.issued_monotonic,
                    consumed=True,
                )
            identity_hashes = tuple(item[2] for item in parsed)
            binding_hashes = (
                (*identity_hashes, *verdict_binding)
                if verdict_binding is not None
                else identity_hashes
            )
            scope_identity = authorizer_identity or parsed[0][3]
            raw_scope = tuple(
                scope_identity.get(name) for name in ("orchestrator", "project_id", "mission_id")
            )
            if any(not isinstance(item, str) for item in raw_scope):
                return "REJECTED", None
            scope = (str(raw_scope[0]), str(raw_scope[1]), str(raw_scope[2]))
            verification_hash = _content_hash(
                {
                    "schema_version": 1,
                    "authority_id": AUTHORITY_ID,
                    "controller_pid": os.getpid(),
                    "binding_hashes": binding_hashes,
                    "nonce": nonce,
                    "receipt_secret": secrets.token_hex(32),
                }
            )
            self._verifications[verification_hash] = _VerificationReceipt(
                binding_hashes=binding_hashes,
                scope=scope,
                issued_monotonic=now,
            )
        return "VERIFIED", verification_hash

    def consume_verification(
        self,
        receipt_hash: str,
        binding_hashes: tuple[str, ...],
        consumer_identity: dict[str, object],
    ) -> str:
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            record = self._verifications.get(receipt_hash)
            consumer_scope = tuple(
                consumer_identity.get(name) for name in ("orchestrator", "project_id", "mission_id")
            )
            if (
                record is None
                or record.consumed
                or record.binding_hashes != binding_hashes
                or consumer_scope != record.scope
            ):
                return "REJECTED"
            self._verifications[receipt_hash] = _VerificationReceipt(
                binding_hashes=record.binding_hashes,
                scope=record.scope,
                issued_monotonic=record.issued_monotonic,
                consumed=True,
            )
        return "VERIFIED"


_receipt_registry = _ReceiptRegistry()


@dataclass
class _RegistrationState:
    claims: dict[str, object]
    task_state_path: Path
    provider_config_path: Path
    task_record_hash: str
    provider_config_hash: str

    def is_current(self) -> bool:
        try:
            value = json.loads(self.task_state_path.read_text(encoding="utf-8"))
            task_id = str(self.claims["identity"]["task_id"])  # type: ignore[index]
            task = value["tasks"][task_id]
            task_record = {
                "task_id": task_id,
                "status": task["status"],
                "last_attempt": task["last_attempt"],
            }
            return (
                task["status"] == "running"
                and task["last_attempt"] == self.claims["identity"]["task_attempt_id"]  # type: ignore[index]
                and _content_hash(task_record) == self.task_record_hash
                and _file_hash(self.provider_config_path) == self.provider_config_hash
            )
        except (KeyError, OSError, TypeError, ValueError):
            return False


class _DispatchAuthorityServer:
    def __init__(self, state: _RegistrationState) -> None:
        self.capability = secrets.token_hex(32)
        self.endpoint = f"@zenith-runtime-identity-{secrets.token_hex(24)}"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.settimeout(0.25)
        try:
            listener.bind("\0" + self.endpoint[1:])
            listener.listen(4)
        except OSError:
            listener.close()
            raise
        self._state = state
        self._listener = listener
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._serve,
            name="zenith-runtime-identity-dispatch",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)

    def _serve(self) -> None:
        request_count = 0
        while not self._stop.is_set() and request_count < _MAX_REQUESTS_PER_DISPATCH:
            try:
                connection, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            request_count += 1
            self._handle(connection)

    def _handle(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(_CONNECTION_TIMEOUT_SECONDS)
            try:
                payload = bytearray()
                while len(payload) <= _MAX_MESSAGE_BYTES:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if b"\n" in chunk:
                        break
                if len(payload) > _MAX_MESSAGE_BYTES or b"\n" not in payload:
                    response = {"schema_version": 1, "state": "REJECTED"}
                else:
                    response = self._dispatch(json.loads(bytes(payload).split(b"\n", 1)[0]))
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                response = {"schema_version": 1, "state": "REJECTED"}
            try:
                connection.sendall(_canonical_json(response) + b"\n")
            except OSError:
                pass

    def _dispatch(self, request: Any) -> dict[str, object]:
        if not isinstance(request, dict) or request.get("schema_version") != 1:
            return {"schema_version": 1, "state": "REJECTED"}
        capability = request.get("capability")
        nonce = request.get("nonce")
        action = request.get("action")
        if (
            not secrets.compare_digest(
                capability if isinstance(capability, str) else "",
                self.capability,
            )
            or not isinstance(nonce, str)
            or len(nonce) != 64
            or action
            not in {
                "attest",
                "consume",
                "authorize_verdict",
                "consume_verification",
            }
        ):
            return {"schema_version": 1, "state": "REJECTED"}
        if not self._state.is_current():
            return {"schema_version": 1, "state": "REJECTED"}
        if action == "attest":
            identity = self._state.claims["identity"]
            if not isinstance(identity, dict):
                return {"schema_version": 1, "state": "REJECTED"}
            channel_receipt_hash = _receipt_registry.issue_identity(
                identity=identity,
                runtime_receipt_hash=str(self._state.claims["runtime_receipt_hash"]),
                nonce=nonce,
                capability=self.capability,
            )
            return {
                "schema_version": 1,
                "state": "ATTESTED",
                "authority_id": AUTHORITY_ID,
                "controller_pid": os.getpid(),
                "nonce": nonce,
                "claims": self._state.claims,
                "channel_receipt_hash": channel_receipt_hash,
            }
        if action in {"consume", "authorize_verdict"}:
            identities = request.get("identities")
            if (
                not isinstance(identities, list)
                or len(identities) > 8
                or any(not isinstance(item, dict) for item in identities)
            ):
                return {"schema_version": 1, "state": "REJECTED"}
            verdict_binding: tuple[str, ...] | None = None
            authorizer_identity: dict[str, object] | None = None
            if action == "authorize_verdict":
                worker_manifest_hash = request.get("worker_manifest_hash")
                verdict_set_hash = request.get("verdict_set_hash")
                bundle_digest = request.get("bundle_digest")
                if any(
                    not isinstance(item, str) or len(item) != 64
                    for item in (
                        worker_manifest_hash,
                        verdict_set_hash,
                        bundle_digest,
                    )
                ):
                    return {"schema_version": 1, "state": "REJECTED"}
                current_identity = self._state.claims.get("identity")
                if not isinstance(current_identity, dict):
                    return {"schema_version": 1, "state": "REJECTED"}
                authorizer_identity = current_identity
                verdict_binding = (
                    str(worker_manifest_hash),
                    str(verdict_set_hash),
                    str(bundle_digest),
                )
            state, receipt_hash = _receipt_registry.consume_identities(
                identities,
                nonce=nonce,
                authorizer_identity=authorizer_identity,
                verdict_binding=verdict_binding,
            )
            return {
                "schema_version": 1,
                "state": state,
                "authority_id": AUTHORITY_ID,
                "controller_pid": os.getpid(),
                "nonce": nonce,
                "verification_receipt_hash": receipt_hash,
            }
        receipt_hash = request.get("verification_receipt_hash")
        binding_hashes = request.get("binding_hashes")
        if (
            not isinstance(receipt_hash, str)
            or len(receipt_hash) != 64
            or not isinstance(binding_hashes, list)
            or len(binding_hashes) != 5
            or any(not isinstance(item, str) or len(item) != 64 for item in binding_hashes)
        ):
            return {"schema_version": 1, "state": "REJECTED"}
        current_identity = self._state.claims.get("identity")
        if (
            not isinstance(current_identity, dict)
            or current_identity.get("task_type") != "validate"
            or current_identity.get("execution_role") != "validator"
        ):
            return {"schema_version": 1, "state": "REJECTED"}
        state = _receipt_registry.consume_verification(
            receipt_hash,
            tuple(binding_hashes),
            current_identity,
        )
        return {
            "schema_version": 1,
            "state": state,
            "authority_id": AUTHORITY_ID,
            "controller_pid": os.getpid(),
            "nonce": nonce,
        }


@dataclass
class RuntimeIdentityRegistration:
    endpoint: str | None
    capability: str | None
    reason_code: str = "PASS"
    _server: _DispatchAuthorityServer | None = None

    def environment(self) -> dict[str, str]:
        if self.endpoint is None or self.capability is None:
            return {}
        return {
            AUTHORITY_ENV_ENDPOINT: self.endpoint,
            AUTHORITY_ENV_CAPABILITY: self.capability,
        }

    def close(self) -> None:
        server = self._server
        self._server = None
        self.endpoint = None
        self.capability = None
        if server is not None:
            server.close()


def _register_node_runtime_identity(
    *,
    store: ProjectStore,
    project_id: str,
    mission_id: str,
    task_id: str,
    spawn_ts: str,
    executor: str,
    provider: str,
    task_type: str,
    execution_role: str,
    workspace_dir: Path,
) -> RuntimeIdentityRegistration:
    config_relative_paths = {
        "codex": Path(".codex/config.toml"),
        "claude": Path(".claude/settings.json"),
    }
    try:
        config_relative = config_relative_paths[provider]
        workspace = workspace_dir.resolve(strict=True)
        provider_config_path = (workspace / config_relative).resolve(strict=True)
        task_state_path = (
            store.mission_runtime_dir(project_id, mission_id) / "task-state.json"
        ).resolve(strict=True)
        task_state = store.load_task_state(project_id, mission_id)
        task = task_state.tasks[task_id]
        if task.status != "running" or task.last_attempt != spawn_ts:
            return RuntimeIdentityRegistration(None, None, "TASK_ATTEMPT_NOT_RUNNING")
        provider_config_hash = _file_hash(provider_config_path)
        task_record = {
            "task_id": task_id,
            "status": task.status,
            "last_attempt": task.last_attempt,
        }
        task_record_hash = _content_hash(task_record)
        if (task_type, execution_role) not in {
            ("work", "worker"),
            ("validate", "validator"),
        }:
            return RuntimeIdentityRegistration(
                None,
                None,
                "REGISTRATION_ROLE_INVALID",
            )
        identity = {
            "schema_version": 1,
            "orchestrator": "zenith",
            "project_id": project_id,
            "mission_id": mission_id,
            "task_id": task_id,
            "task_attempt_id": spawn_ts,
            "executor": executor,
            "provider": provider,
            "task_type": task_type,
            "execution_role": execution_role,
            "provider_config_hash": provider_config_hash,
            "attestation_state": "ATTESTED",
        }
        claims_base: dict[str, object] = {
            "schema_version": 1,
            "authority_id": AUTHORITY_ID,
            "controller_runtime_root": str(REGISTERED_RUNTIME_ROOT),
            "store_root": str(store.config.harness_home.resolve()),
            "projects_root": str(store.config.projects_dir.resolve()),
            "workspace_root": str(workspace),
            "task_state_path": str(task_state_path),
            "provider_config_path": str(provider_config_path),
            "task_record_hash": task_record_hash,
            "provider_config_hash": provider_config_hash,
            "identity": identity,
        }
        claims = {
            **claims_base,
            "runtime_receipt_hash": _content_hash(claims_base),
        }
        state = _RegistrationState(
            claims=claims,
            task_state_path=task_state_path,
            provider_config_path=provider_config_path,
            task_record_hash=task_record_hash,
            provider_config_hash=provider_config_hash,
        )
        server = _DispatchAuthorityServer(state)
        return RuntimeIdentityRegistration(
            server.endpoint,
            server.capability,
            _server=server,
        )
    except KeyError:
        return RuntimeIdentityRegistration(None, None, "REGISTRATION_STATE_INVALID")
    except FileNotFoundError:
        return RuntimeIdentityRegistration(None, None, "REGISTRATION_INPUT_UNAVAILABLE")
    except OSError as exc:
        return RuntimeIdentityRegistration(
            None,
            None,
            f"REGISTRATION_OS_ERROR_{exc.errno or 0}",
        )
    except (TypeError, ValueError):
        return RuntimeIdentityRegistration(None, None, "REGISTRATION_INPUT_INVALID")


def peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    return struct.unpack(
        "3i",
        connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
    )
