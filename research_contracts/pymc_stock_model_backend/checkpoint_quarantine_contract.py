"""Durable fixture-only checkpoint and quarantine store for S08 rehearsals.

The store is intentionally incapable of writing to production paths or a
database.  It accepts only a newly created ``codex-s08-fixture-*`` directory,
uses exclusive content-addressed files, fsyncs file and directory metadata on
POSIX, and verifies the full hash-linked sequence on every readback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping


STORE_CONTRACT_ID = "codex-oracle-s08-fixture-durable-store-v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{64}")
_ZERO_DOWNSTREAM = {
    "predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0,
}


class FixtureStoreError(RuntimeError):
    """Raised when fixture durability or quarantine evidence differs."""


@dataclass(frozen=True)
class FixtureStoreManifest:
    contract_id: str
    run_id: str
    plan_sha256: str
    fixture_only: bool
    database_write_scope: str
    created_at_utc: str


@dataclass(frozen=True)
class FixtureCheckpoint:
    contract_id: str
    run_id: str
    sequence: int
    observed_at_utc: str
    state: str
    completed_targets: int
    total_targets: int
    completed_folds: int
    total_folds: int
    divergences: int
    previous_checkpoint_sha256: str | None
    fixture_only: bool
    scientific_evidence: bool
    downstream_counts: Mapping[str, int]
    payload_sha256: str


@dataclass(frozen=True)
class FixtureTerminal:
    contract_id: str
    run_id: str
    state: str
    observed_at_utc: str
    last_checkpoint_sha256: str
    completed_targets: int
    total_targets: int
    completed_folds: int
    total_folds: int
    convergence_claimed: bool
    outputs_quarantined: bool
    failure_class: str | None
    fixture_only: bool
    scientific_evidence: bool
    downstream_counts: Mapping[str, int]
    payload_sha256: str


def _primitive(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _primitive(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _utc_text(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FixtureStoreError("checkpoint time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise FixtureStoreError(f"{label} is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise FixtureStoreError(f"{label} is not canonical UTC") from exc
    if _utc_text(parsed) != value:
        raise FixtureStoreError(f"{label} is not canonical UTC")
    return parsed


def _safe_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise FixtureStoreError(f"{label} is missing or unsafe")


def _zero_downstream(value: object) -> None:
    if not isinstance(value, Mapping) or dict(value) != _ZERO_DOWNSTREAM:
        raise FixtureStoreError("fixture checkpoint contains downstream outputs")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exclusive_write(path: Path, payload: object) -> str:
    raw = _canonical_bytes(payload) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise FixtureStoreError("durable fixture write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    return hashlib.sha256(raw[:-1]).hexdigest()


def _read_json_exact(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise FixtureStoreError("fixture evidence path is missing or symbolic")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise FixtureStoreError("fixture evidence permissions are not private")
    raw = path.read_bytes()
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise FixtureStoreError("fixture evidence framing differs")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureStoreError("fixture evidence is not canonical JSON") from exc
    if _canonical_bytes(value) + b"\n" != raw:
        raise FixtureStoreError("fixture evidence bytes are not canonical")
    return value


class DurableFixtureStore:
    """A newly created, private, fixture-only append-only evidence directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_absolute() or not self.root.name.startswith("codex-s08-fixture-"):
            raise FixtureStoreError("fixture root is not an exact isolated fixture path")
        temp_root = Path(tempfile.gettempdir()).resolve()
        resolved = self.root.resolve()
        if resolved.parent != temp_root and temp_root not in resolved.parents:
            raise FixtureStoreError("fixture root is outside temporary storage")
        if self.root.is_symlink() or not self.root.is_dir():
            raise FixtureStoreError("fixture root is absent or symbolic")
        if os.name != "nt" and self.root.stat().st_mode & 0o077:
            raise FixtureStoreError("fixture root permissions are not private")
        self.checkpoints = self.root / "checkpoints"
        self.terminal = self.root / "terminal"
        self.quarantine = self.root / "quarantine"
        for path in (self.checkpoints, self.terminal, self.quarantine):
            if path.is_symlink() or not path.is_dir():
                raise FixtureStoreError("fixture store topology differs")

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        run_id: str,
        plan_sha256: str,
        created_at_utc: datetime,
    ) -> "DurableFixtureStore":
        root = Path(root)
        _safe_id(run_id, "run_id")
        if not _SHA.fullmatch(plan_sha256):
            raise FixtureStoreError("plan identity must be a lowercase SHA-256")
        if not root.is_absolute() or not root.name.startswith("codex-s08-fixture-"):
            raise FixtureStoreError("fixture root is not an exact isolated fixture path")
        temp_root = Path(tempfile.gettempdir()).resolve()
        resolved_parent = root.parent.resolve()
        if resolved_parent != temp_root and temp_root not in resolved_parent.parents:
            raise FixtureStoreError("fixture root is outside temporary storage")
        if root.parent.is_symlink() or not root.parent.is_dir():
            raise FixtureStoreError("fixture parent is absent or symbolic")
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        for name in ("checkpoints", "terminal", "quarantine"):
            (root / name).mkdir(mode=0o700)
        manifest = FixtureStoreManifest(
            contract_id=STORE_CONTRACT_ID,
            run_id=run_id,
            plan_sha256=plan_sha256,
            fixture_only=True,
            database_write_scope="NONE",
            created_at_utc=_utc_text(created_at_utc),
        )
        _exclusive_write(root / "manifest.json", manifest)
        _fsync_directory(root)
        return cls(root)

    def manifest(self) -> FixtureStoreManifest:
        raw = _read_json_exact(self.root / "manifest.json")
        value = FixtureStoreManifest(**raw)
        if value.contract_id != STORE_CONTRACT_ID or value.fixture_only is not True or value.database_write_scope != "NONE":
            raise FixtureStoreError("fixture store manifest boundary differs")
        _safe_id(value.run_id, "manifest run_id")
        if not _SHA.fullmatch(value.plan_sha256):
            raise FixtureStoreError("manifest plan identity differs")
        _parse_utc(value.created_at_utc, "manifest creation time")
        return value

    def read_checkpoints(self) -> tuple[FixtureCheckpoint, ...]:
        manifest = self.manifest()
        files = sorted(self.checkpoints.glob("*.json"))
        result: list[FixtureCheckpoint] = []
        previous: str | None = None
        previous_time = _parse_utc(manifest.created_at_utc, "manifest creation time")
        for expected_sequence, path in enumerate(files, 1):
            raw = _read_json_exact(path)
            checkpoint = FixtureCheckpoint(**raw)
            payload = dict(raw)
            claimed = payload.pop("payload_sha256")
            actual = _sha256(payload)
            expected_name = f"{expected_sequence:06d}-{actual}.json"
            if path.name != expected_name or claimed != actual:
                raise FixtureStoreError("checkpoint content address differs")
            if checkpoint.contract_id != STORE_CONTRACT_ID or checkpoint.run_id != manifest.run_id:
                raise FixtureStoreError("checkpoint lineage differs")
            if checkpoint.sequence != expected_sequence or checkpoint.previous_checkpoint_sha256 != previous:
                raise FixtureStoreError("checkpoint sequence or hash chain differs")
            if checkpoint.state != "RUNNING" or checkpoint.fixture_only is not True or checkpoint.scientific_evidence is not False:
                raise FixtureStoreError("checkpoint fixture state differs")
            observed = _parse_utc(checkpoint.observed_at_utc, "checkpoint observation time")
            if observed < previous_time:
                raise FixtureStoreError("checkpoint chronology differs")
            _zero_downstream(checkpoint.downstream_counts)
            counts = (
                checkpoint.completed_targets, checkpoint.total_targets,
                checkpoint.completed_folds, checkpoint.total_folds,
                checkpoint.divergences,
            )
            if any(type(item) is not int for item in counts):
                raise FixtureStoreError("checkpoint counts use an invalid type")
            if checkpoint.total_targets <= 0 or checkpoint.total_folds <= 0 or not 0 <= checkpoint.completed_targets <= checkpoint.total_targets or not 0 <= checkpoint.completed_folds <= checkpoint.total_folds:
                raise FixtureStoreError("checkpoint progress differs")
            if checkpoint.divergences < 0:
                raise FixtureStoreError("checkpoint divergence count differs")
            result.append(checkpoint)
            previous = actual
            previous_time = observed
        return tuple(result)

    def append_checkpoint(
        self,
        *,
        observed_at_utc: datetime,
        completed_targets: int,
        total_targets: int,
        completed_folds: int,
        total_folds: int,
        divergences: int,
    ) -> FixtureCheckpoint:
        manifest = self.manifest()
        existing = self.read_checkpoints()
        if any(self.terminal.iterdir()) or any(self.quarantine.iterdir()):
            raise FixtureStoreError("fixture store is already terminal")
        sequence = len(existing) + 1
        previous = existing[-1].payload_sha256 if existing else None
        payload = {
            "contract_id": STORE_CONTRACT_ID,
            "run_id": manifest.run_id,
            "sequence": sequence,
            "observed_at_utc": _utc_text(observed_at_utc),
            "state": "RUNNING",
            "completed_targets": completed_targets,
            "total_targets": total_targets,
            "completed_folds": completed_folds,
            "total_folds": total_folds,
            "divergences": divergences,
            "previous_checkpoint_sha256": previous,
            "fixture_only": True,
            "scientific_evidence": False,
            "downstream_counts": dict(_ZERO_DOWNSTREAM),
        }
        digest = _sha256(payload)
        checkpoint = FixtureCheckpoint(**payload, payload_sha256=digest)
        _exclusive_write(self.checkpoints / f"{sequence:06d}-{digest}.json", checkpoint)
        return self.read_checkpoints()[-1]

    def finish(
        self,
        *,
        observed_at_utc: datetime,
        success: bool,
        completed_targets: int,
        total_targets: int,
        completed_folds: int,
        total_folds: int,
        failure_class: str | None = None,
    ) -> FixtureTerminal:
        manifest = self.manifest()
        checkpoints = self.read_checkpoints()
        if not checkpoints or any(self.terminal.iterdir()) or any(self.quarantine.iterdir()):
            raise FixtureStoreError("fixture terminal transition is unavailable")
        exact_coverage = completed_targets == total_targets and completed_folds == total_folds
        if success and not exact_coverage:
            raise FixtureStoreError("fixture success coverage is incomplete")
        if success and failure_class is not None:
            raise FixtureStoreError("successful fixture cannot contain a failure class")
        if not success and (not isinstance(failure_class, str) or not _SAFE_ID.fullmatch(failure_class)):
            raise FixtureStoreError("failed fixture requires a safe failure class")
        state = "TERMINAL_FIXTURE_SMOKE" if success else "TERMINAL_FIXTURE_FAILURE"
        payload = {
            "contract_id": STORE_CONTRACT_ID,
            "run_id": manifest.run_id,
            "state": state,
            "observed_at_utc": _utc_text(observed_at_utc),
            "last_checkpoint_sha256": checkpoints[-1].payload_sha256,
            "completed_targets": completed_targets,
            "total_targets": total_targets,
            "completed_folds": completed_folds,
            "total_folds": total_folds,
            "convergence_claimed": False,
            "outputs_quarantined": not success,
            "failure_class": failure_class,
            "fixture_only": True,
            "scientific_evidence": False,
            "downstream_counts": dict(_ZERO_DOWNSTREAM),
        }
        digest = _sha256(payload)
        terminal = FixtureTerminal(**payload, payload_sha256=digest)
        destination = (self.terminal if success else self.quarantine) / f"{digest}.json"
        _exclusive_write(destination, terminal)
        return self.read_terminal()

    def read_terminal(self) -> FixtureTerminal:
        terminal_files = tuple(self.terminal.glob("*.json"))
        quarantine_files = tuple(self.quarantine.glob("*.json"))
        if len(terminal_files) + len(quarantine_files) != 1:
            raise FixtureStoreError("fixture terminal evidence is absent or duplicated")
        path = (terminal_files + quarantine_files)[0]
        raw = _read_json_exact(path)
        terminal = FixtureTerminal(**raw)
        payload = dict(raw)
        claimed = payload.pop("payload_sha256")
        actual = _sha256(payload)
        if path.name != f"{actual}.json" or claimed != actual:
            raise FixtureStoreError("fixture terminal content address differs")
        checkpoints = self.read_checkpoints()
        if not checkpoints or terminal.last_checkpoint_sha256 != checkpoints[-1].payload_sha256:
            raise FixtureStoreError("fixture terminal checkpoint lineage differs")
        if terminal.fixture_only is not True or terminal.scientific_evidence is not False or terminal.convergence_claimed is not False:
            raise FixtureStoreError("fixture terminal claim boundary differs")
        observed = _parse_utc(terminal.observed_at_utc, "terminal observation time")
        if observed < _parse_utc(checkpoints[-1].observed_at_utc, "latest checkpoint time"):
            raise FixtureStoreError("fixture terminal chronology differs")
        _zero_downstream(terminal.downstream_counts)
        if terminal.state == "TERMINAL_FIXTURE_SMOKE":
            if terminal.outputs_quarantined or terminal.failure_class is not None or terminal.completed_targets != terminal.total_targets or terminal.completed_folds != terminal.total_folds:
                raise FixtureStoreError("successful fixture terminal differs")
        elif terminal.state == "TERMINAL_FIXTURE_FAILURE":
            if not terminal.outputs_quarantined or not isinstance(terminal.failure_class, str) or not _SAFE_ID.fullmatch(terminal.failure_class):
                raise FixtureStoreError("failed fixture output is not quarantined")
        else:
            raise FixtureStoreError("fixture terminal state differs")
        return terminal
