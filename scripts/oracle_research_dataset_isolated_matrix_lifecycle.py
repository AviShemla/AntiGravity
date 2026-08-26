"""Single fail-closed lifecycle for the approved disposable Turso matrix.

All external effects are injected.  The orchestrator issues at most one create,
one token, and one destroy command, reconciles ambiguous responses with exact
readback, persists redacted evidence atomically, and always enters cleanup after
creation becomes possible.  It never retries a mutating command.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from types import TracebackType
from typing import Protocol
from typing import Callable
from urllib.parse import urlparse

from model_lineage import LineageError
from scripts.oracle_research_dataset_isolated_matrix import (
    EXPECTED_SOURCE_COMMIT,
    IsolatedMatrixPlan,
    PreBranchIntent,
    _pre_branch_payload,
    bind_branch_identity,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    CLI,
    CliResult,
    BranchIdentityProof,
    derive_branch_identity_from_cli,
)
from scripts.oracle_research_dataset_matrix_secrets import (
    BranchSecrets,
    branch_secret_file,
)
from oracle_research_branch_cleanup_verifier import (
    read_production_fingerprint,
    verify_and_cleanup_bound_branch,
    verify_and_cleanup_isolated_branch,
)


EXPECTED_EXECUTOR_GIT_COMMIT = "39dc9dcdc07ad3a2b02354d1bca1ae4ae92031eb"
NOT_FOUND_TEMPLATE = (
    "Error: database {name} not found. List known databases using turso db list"
)
MAX_CLI_BYTES = 64 * 1024


class LifecycleError(RuntimeError):
    """Fail-closed lifecycle error whose message never contains credentials."""


class CleanupError(LifecycleError):
    """Raised when exact cleanup could not be independently verified."""


class IdentityPropagationPending(LifecycleError):
    """Exact absence persisted through one bounded reconciliation phase."""


class IdentityContradiction(LifecycleError):
    """Identity evidence contradicted the governed branch/parent contract."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    ambiguous: bool = False


class LifecycleCli(Protocol):
    def run(self, argv: tuple[str, ...], *, sensitive_stdout: bool = False) -> CommandResult: ...


class MatrixExecutor(Protocol):
    def execute(
        self,
        plan: IsolatedMatrixPlan,
        proof: BranchIdentityProof,
        secrets: BranchSecrets,
    ) -> dict[str, object]: ...


class GitIdentityReader(Protocol):
    def head(self) -> str: ...


class SubprocessLifecycleCli:
    """Shell-free command boundary; sensitive stdout is returned, never printed."""

    def run(self, argv: tuple[str, ...], *, sensitive_stdout: bool = False) -> CommandResult:
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                timeout=45,
            )
            return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
            return CommandResult(argv, -1, stdout, stderr, ambiguous=True)


class RepositoryGitIdentity:
    def __init__(self, root: Path):
        try:
            resolved = Path(root).resolve(strict=True)
        except OSError as exc:
            raise LifecycleError("Executor repository root could not be resolved.") from exc
        if not resolved.is_absolute() or not resolved.is_dir():
            raise LifecycleError("Executor repository root is not an exact directory.")
        self.root = resolved

    def head(self) -> str:
        argv = (
            "git",
            "-c",
            f"safe.directory={self.root}",
            "rev-parse",
            "HEAD",
        )
        completed = subprocess.run(
            argv,
            cwd=self.root,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0 or completed.stderr.strip():
            raise LifecycleError("Executor Git identity could not be read exactly.")
        return completed.stdout.strip()


class _IdentityAdapter:
    def __init__(self, cli: LifecycleCli):
        self.cli = cli
        self.results: dict[tuple[str, ...], CommandResult] = {}

    def run(self, argv: tuple[str, ...]) -> CliResult:
        result = self.cli.run(argv, sensitive_stdout=False)
        self.results[argv] = result
        try:
            stdout = result.stdout.decode("utf-8")
            stderr = result.stderr.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LineageError("Turso CLI identity evidence is not UTF-8.") from exc
        return CliResult(result.argv, result.returncode, stdout, stderr)


class _CleanupAdapter:
    def __init__(self, cli: LifecycleCli):
        self.cli = cli

    def run(self, argv: tuple[str, ...]) -> CliResult:
        result = self.cli.run(argv, sensitive_stdout=False)
        if result.ambiguous:
            raise subprocess.TimeoutExpired(argv, 45)
        try:
            stdout = result.stdout.decode("utf-8")
            stderr = result.stderr.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LineageError("Cleanup CLI evidence is not UTF-8.") from exc
        return CliResult(result.argv, result.returncode, stdout, stderr)


@dataclass(frozen=True)
class LifecycleArtifacts:
    execution_evidence_path: Path | None
    terminal_evidence_path: Path
    cleanup_verified: bool
    branch_id: str | None


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_redacted_json(path: Path, payload: dict[str, object]) -> Path:
    """Atomically replace one mode-600 redacted artifact and fsync file+directory."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_json(payload)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise LifecycleError("Evidence write did not make progress.")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        os.chmod(path, 0o600, follow_symlinks=False)
        _fsync_directory(path.parent)
    except BaseException:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise LifecycleError("Durable evidence metadata is not exact.")
    if path.read_bytes() != raw:
        raise LifecycleError("Durable evidence readback differs from the written payload.")
    return path


def create_lifecycle_claim(path: Path, payload: dict[str, object]) -> Path:
    """Durably claim one intent exactly once without replacing prior evidence."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_json(payload)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError as exc:
        raise LifecycleError("Lifecycle intent already has a durable claim.") from exc
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise LifecycleError("Lifecycle claim write did not make progress.")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    else:
        os.close(descriptor)
    _fsync_directory(path.parent)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise LifecycleError("Lifecycle claim metadata is not exact.")
    if path.read_bytes() != raw:
        raise LifecycleError("Lifecycle claim readback differs.")
    return path


def _exception_type(error: BaseException | None) -> str | None:
    return None if error is None else type(error).__name__


def _result_digest(result: CommandResult) -> dict[str, object]:
    return {
        "argv": list(result.argv),
        "returncode": result.returncode,
        "ambiguous": result.ambiguous,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }


def _validate_executor_identity(
    intent: PreBranchIntent,
    git_reader: GitIdentityReader,
    expected_executor_git_commit: str,
) -> str:
    if intent.source_commit != EXPECTED_SOURCE_COMMIT:
        raise LifecycleError("Artifact source commit differs from the reviewed migration source.")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_executor_git_commit):
        raise LifecycleError("Preregistered executor Git identity is invalid.")
    observed = git_reader.head()
    if observed != expected_executor_git_commit:
        raise LifecycleError("Checked-out executor Git identity differs from preregistration.")
    return observed


def _validate_intent_commands(intent: PreBranchIntent) -> None:
    expected = (
        (
            "create_branch",
            (CLI, "db", "branch", "theoracle", intent.branch_name),
            False,
            False,
        ),
        (
            "read_branch_identity",
            (CLI, "db", "show", intent.branch_name),
            False,
            False,
        ),
        (
            "create_one_day_branch_token",
            (CLI, "db", "tokens", "create", intent.branch_name, "--expiration", "1d"),
            True,
            False,
        ),
    )
    observed = tuple(
        (command.purpose, command.argv, command.sensitive_stdout, command.destructive)
        for command in intent.commands
    )
    if observed != expected:
        raise LifecycleError("Pre-branch intent command count, order, or scope is not exact.")


def _prepare_secret_directory(directory: Path) -> Path:
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    except FileExistsError:
        pass
    metadata = os.lstat(directory)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise LifecycleError("Secret directory metadata is not exact mode-0700 owner-only.")
    return directory


def _branch_url_from_show(result: CommandResult, branch_name: str) -> str:
    if result.returncode != 0 or result.stderr.strip() or result.ambiguous:
        raise LifecycleError("Branch URL readback is not successful and exact.")
    if len(result.stdout) > MAX_CLI_BYTES:
        raise LifecycleError("Branch URL readback is oversized.")
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifecycleError("Branch URL readback is not UTF-8.") from exc
    values = []
    for line in text.split("\nDatabase Instances:", 1)[0].splitlines():
        if line.startswith("URL:"):
            values.append(line.split(":", 1)[1].strip())
    if len(values) != 1:
        raise LifecycleError("Branch URL readback is missing or ambiguous.")
    parsed = urlparse(values[0])
    if (
        parsed.scheme not in {"libsql", "https"}
        or not parsed.hostname
        or not parsed.hostname.startswith(branch_name + "-")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise LifecycleError("Branch URL readback does not match the governed branch.")
    return values[0].rstrip("/")


def _exact_not_found(result: CommandResult, branch_name: str) -> bool:
    if result.argv != (CLI, "db", "show", branch_name) or result.returncode == 0:
        return False
    try:
        stdout = result.stdout.decode("utf-8").strip()
        stderr = result.stderr.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    return not stdout and stderr == NOT_FOUND_TEMPLATE.format(name=branch_name)


def _derive_identity(intent: PreBranchIntent, cli: LifecycleCli, now: datetime):
    adapter = _IdentityAdapter(cli)
    proof = derive_branch_identity_from_cli(intent, adapter, observed_at=now)
    branch_result = adapter.results[(CLI, "db", "show", intent.branch_name)]
    return proof, branch_result


@dataclass
class _ReconciliationBudget:
    max_wait_seconds: float
    waited_seconds: float = 0.0

    def wait(self, requested: float, sleeper: Callable[[float], None]) -> bool:
        remaining = self.max_wait_seconds - self.waited_seconds
        if remaining <= 0:
            return False
        duration = min(requested, remaining)
        sleeper(duration)
        self.waited_seconds += duration
        return duration > 0


def _reconcile_identity_phase(
    intent: PreBranchIntent,
    cli: LifecycleCli,
    *,
    budget: _ReconciliationBudget,
    sleeper: Callable[[float], None],
    utc_clock: Callable[[], datetime],
    attempts: int,
    interval_seconds: float,
):
    if attempts <= 0 or interval_seconds <= 0:
        raise LifecycleError("Identity reconciliation bounds are invalid.")
    last_absence: CommandResult | None = None
    saw_unresolved = False
    for attempt in range(attempts):
        observed_at = utc_clock()
        if observed_at.tzinfo is None:
            raise LifecycleError("Identity reconciliation clock is not timezone-aware.")
        adapter = _IdentityAdapter(cli)
        try:
            proof = derive_branch_identity_from_cli(
                intent,
                adapter,
                observed_at=observed_at.astimezone(timezone.utc),
            )
        except LineageError as exc:
            branch = adapter.results.get((CLI, "db", "show", intent.branch_name))
            production = adapter.results.get((CLI, "db", "show", "theoracle"))
            if (
                branch is not None
                and _exact_not_found(branch, intent.branch_name)
                and production is not None
                and production.returncode == 0
                and not production.ambiguous
                and production.stderr.strip() == b""
                and bool(production.stdout)
            ):
                last_absence = branch
            else:
                saw_unresolved = True
        else:
            branch_result = adapter.results[(CLI, "db", "show", intent.branch_name)]
            return proof, branch_result
        if attempt + 1 < attempts and budget.wait(interval_seconds, sleeper):
            continue
        break
    if saw_unresolved:
        raise IdentityContradiction(
            "Branch identity remained unresolved through bounded propagation checks."
        )
    if last_absence is not None:
        raise IdentityPropagationPending(
            "Branch identity remained exactly absent through bounded propagation checks."
        )
    raise IdentityContradiction("Branch identity reconciliation ended without exact evidence.")


def _persist_failure_evidence(
    *,
    path: Path,
    intent: PreBranchIntent,
    proof: BranchIdentityProof,
    executor_commit: str,
    create_result: CommandResult | None,
    primary: BaseException | None,
    production_fingerprint: str,
    production_object_count: int,
) -> str:
    payload = {
        "evidence_contract": "oracle-isolated-matrix-lifecycle-failure-v1",
        "intent_id": intent.intent_id,
        "artifact_source_commit": intent.source_commit,
        "executor_git_commit": executor_commit,
        "branch_identity": asdict(proof),
        "create": None if create_result is None else _result_digest(create_result),
        "primary_failure_type": _exception_type(primary),
        "production_fingerprint_sha256": production_fingerprint,
        "production_oracle_object_count": production_object_count,
    }
    written = atomic_write_redacted_json(path, payload)
    return hashlib.sha256(written.read_bytes()).hexdigest()


def run_disposable_matrix_lifecycle(
    *,
    intent: PreBranchIntent,
    cli: LifecycleCli,
    matrix_executor: MatrixExecutor,
    git_reader: GitIdentityReader,
    production_reader,
    evidence_directory: Path,
    secret_directory: Path,
    now: datetime | None = None,
    expected_executor_git_commit: str = EXPECTED_EXECUTOR_GIT_COMMIT,
    reconciliation_sleeper: Callable[[float], None] = time.sleep,
    reconciliation_utc_clock: Callable[[], datetime] | None = None,
    reconciliation_max_wait_seconds: float = 45.0,
    reconciliation_interval_seconds: float = 5.0,
    reconciliation_attempts_per_phase: int = 4,
) -> LifecycleArtifacts:
    """Run one approved lifecycle; mutating commands are never retried."""

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise LifecycleError("Lifecycle timestamp must be timezone-aware.")
    moment = moment.astimezone(timezone.utc)
    if reconciliation_max_wait_seconds <= 0 or reconciliation_max_wait_seconds > 45:
        raise LifecycleError("Identity reconciliation total wait bound is invalid.")
    reconciliation_budget = _ReconciliationBudget(reconciliation_max_wait_seconds)
    if reconciliation_utc_clock is None:
        if now is None:
            reconciliation_utc_clock = lambda: datetime.now(timezone.utc)
        else:
            reconciliation_utc_clock = lambda: moment + timedelta(
                seconds=reconciliation_budget.waited_seconds
            )
    _validate_intent_commands(intent)
    executor_commit = _validate_executor_identity(
        intent, git_reader, expected_executor_git_commit
    )
    evidence_directory = Path(evidence_directory)
    secret_directory = _prepare_secret_directory(Path(secret_directory))
    prefix = intent.intent_id
    claim_path = evidence_directory / f"{prefix}-claim.json"
    intent_path = evidence_directory / f"{prefix}-intent.json"
    execution_path = evidence_directory / f"{prefix}-matrix-evidence.json"
    failure_path = evidence_directory / f"{prefix}-failure.json"
    terminal_path = evidence_directory / f"{prefix}-terminal.json"
    cleanup_incident_path = evidence_directory / f"{prefix}-cleanup-incident.json"
    secret_name = f".{prefix}-branch.env"

    protected_artifacts = (
        terminal_path,
        execution_path,
        failure_path,
        cleanup_incident_path,
    )
    if any(os.path.lexists(path) for path in protected_artifacts):
        raise LifecycleError("Lifecycle intent already has durable outcome evidence.")
    create_lifecycle_claim(
        claim_path,
        {
            "evidence_contract": "oracle-isolated-matrix-lifecycle-claim-v1",
            "intent_id": intent.intent_id,
            "artifact_source_commit": intent.source_commit,
            "executor_git_commit": executor_commit,
            "claimed_at_utc": moment.isoformat().replace("+00:00", "Z"),
        },
    )

    create_result: CommandResult | None = None
    bound_proof: BranchIdentityProof | None = None
    execution_written: Path | None = None
    primary: BaseException | None = None
    primary_tb: TracebackType | None = None
    cleanup_failure: BaseException | None = None
    cleanup_payload: dict[str, object] | None = None
    execution_file_sha256: str | None = None
    failure_file_sha256: str | None = None
    failure_evidence_error: BaseException | None = None
    identity_contradiction = False
    production_fingerprint, production_object_count = read_production_fingerprint(
        production_reader, label="Lifecycle pre-create"
    )
    atomic_write_redacted_json(intent_path, _pre_branch_payload(intent))
    create_attempted = False
    creation_absence_verified = False

    try:
        create_argv = intent.commands[0].argv
        if intent.commands[0].purpose != "create_branch":
            raise LifecycleError("Pre-branch create command scope is not exact.")
        create_attempted = True
        create_result = cli.run(create_argv, sensitive_stdout=False)
        try:
            bound_proof, branch_show = _reconcile_identity_phase(
                intent,
                cli,
                budget=reconciliation_budget,
                sleeper=reconciliation_sleeper,
                utc_clock=reconciliation_utc_clock,
                attempts=reconciliation_attempts_per_phase,
                interval_seconds=reconciliation_interval_seconds,
            )
        except IdentityPropagationPending:
            if create_result.returncode != 0 and not create_result.ambiguous:
                creation_absence_verified = True
                raise LifecycleError("Branch creation failed and exact absence was verified.")
            raise
        except IdentityContradiction:
            identity_contradiction = True
            raise
        if create_result.argv != create_argv:
            raise LifecycleError("Create result command identity is not exact.")
        plan = bind_branch_identity(
            intent,
            migration_bytes=(Path(__file__).resolve().parents[1] / "migrations" /
                             "20260826_oracle_research_dataset_versions_additive.sql").read_bytes(),
            branch_id=bound_proof.branch_id,
            parent_name=bound_proof.parent_name,
            parent_id=bound_proof.parent_id,
        )
        branch_url = _branch_url_from_show(branch_show, intent.branch_name)
        token_command = intent.commands[2]
        if token_command.purpose != "create_one_day_branch_token":
            raise LifecycleError("Pre-branch token command scope is not exact.")
        token_result = cli.run(token_command.argv, sensitive_stdout=True)
        if (
            token_result.argv != token_command.argv
            or token_result.returncode != 0
            or token_result.ambiguous
            or token_result.stderr.strip()
            or not token_result.stdout
        ):
            raise LifecycleError("One-day branch credential creation was not exact.")
        with branch_secret_file(
            secret_directory,
            secret_name,
            branch_url=branch_url,
            token_stdout=token_result.stdout,
        ) as (_, branch_secrets):
            matrix_evidence = matrix_executor.execute(plan, bound_proof, branch_secrets)
            serialized = _canonical_json(matrix_evidence)
            if branch_secrets.branch_token.encode("utf-8") in serialized:
                raise LifecycleError("Matrix evidence contains branch credential material.")
            if not isinstance(matrix_evidence, dict):
                raise LifecycleError("Matrix executor did not return an evidence object.")
            execution_written = atomic_write_redacted_json(execution_path, matrix_evidence)
            execution_file_sha256 = hashlib.sha256(execution_written.read_bytes()).hexdigest()
    except BaseException as exc:
        primary = exc
        primary_tb = sys.exc_info()[2]
        if bound_proof is not None:
            try:
                failure_file_sha256 = _persist_failure_evidence(
                    path=failure_path,
                    intent=intent,
                    proof=bound_proof,
                    executor_commit=executor_commit,
                    create_result=create_result,
                    primary=primary,
                    production_fingerprint=production_fingerprint,
                    production_object_count=production_object_count,
                )
            except BaseException as evidence_exc:
                failure_evidence_error = evidence_exc
    finally:
        if create_attempted:
            try:
                if (
                    bound_proof is None
                    and not identity_contradiction
                    and not creation_absence_verified
                ):
                    try:
                        bound_proof, _ = _reconcile_identity_phase(
                            intent,
                            cli,
                            budget=reconciliation_budget,
                            sleeper=reconciliation_sleeper,
                            utc_clock=reconciliation_utc_clock,
                            attempts=reconciliation_attempts_per_phase,
                            interval_seconds=reconciliation_interval_seconds,
                        )
                    except (IdentityPropagationPending, IdentityContradiction):
                        bound_proof = None
                if bound_proof is not None:
                    if failure_file_sha256 is None and execution_written is None:
                        failure_file_sha256 = _persist_failure_evidence(
                            path=failure_path,
                            intent=intent,
                            proof=bound_proof,
                            executor_commit=executor_commit,
                            create_result=create_result,
                            primary=primary,
                            production_fingerprint=production_fingerprint,
                            production_object_count=production_object_count,
                        )
                    cleanup_observed_at = reconciliation_utc_clock()
                    if cleanup_observed_at.tzinfo is None:
                        raise CleanupError("Cleanup reconciliation clock is not timezone-aware.")
                    cleanup_observed_at = cleanup_observed_at.astimezone(timezone.utc)
                    adapter = _CleanupAdapter(cli)
                    if execution_written is not None and execution_file_sha256 is not None:
                        cleanup = verify_and_cleanup_isolated_branch(
                            intent_path=intent_path,
                            persisted_evidence_path=execution_written,
                            expected_persisted_evidence_sha256=execution_file_sha256,
                            runner=adapter,
                            production_reader=production_reader,
                            observed_at=cleanup_observed_at,
                        )
                    elif failure_file_sha256 is not None:
                        cleanup = verify_and_cleanup_bound_branch(
                            intent_path=intent_path,
                            identity_proof=bound_proof,
                            durable_evidence_path=failure_path,
                            expected_durable_evidence_sha256=failure_file_sha256,
                            expected_production_fingerprint=production_fingerprint,
                            expected_production_object_count=production_object_count,
                            runner=adapter,
                            production_reader=production_reader,
                            observed_at=cleanup_observed_at,
                        )
                    else:
                        raise CleanupError(
                            "Bound branch lacks durable execution or failure evidence."
                        ) from failure_evidence_error
                    cleanup_payload = asdict(cleanup)
                    cleanup_payload["cleanup_verified"] = True
                elif not creation_absence_verified:
                    raise CleanupError(
                        "Branch creation may have succeeded but exact cleanup identity is unavailable."
                    )
            except BaseException as exc:
                if isinstance(exc, CleanupError):
                    cleanup_failure = exc
                else:
                    cleanup_failure = CleanupError(
                        "Exact shared cleanup verification failed."
                    )
                    cleanup_failure.__cause__ = exc

        terminal_payload = {
            "evidence_contract": "oracle-isolated-matrix-lifecycle-terminal-v1",
            "intent_id": intent.intent_id,
            "artifact_source_commit": intent.source_commit,
            "executor_git_commit": executor_commit,
            "branch_id": None if bound_proof is None else bound_proof.branch_id,
            "primary_failure_type": _exception_type(primary),
            "cleanup_failure_type": _exception_type(cleanup_failure),
            "cleanup": cleanup_payload,
            "intent_evidence_sha256": hashlib.sha256(intent_path.read_bytes()).hexdigest(),
            "matrix_evidence_file_sha256": execution_file_sha256,
            "failure_evidence_file_sha256": failure_file_sha256,
            "create": None if create_result is None else _result_digest(create_result),
            "execution_evidence_path": None if execution_written is None else execution_written.name,
        }
        try:
            atomic_write_redacted_json(terminal_path, terminal_payload)
            if cleanup_failure is not None:
                atomic_write_redacted_json(cleanup_incident_path, terminal_payload)
        except BaseException as evidence_exc:
            if primary is None:
                primary = evidence_exc
                primary_tb = sys.exc_info()[2]
            elif cleanup_failure is None:
                cleanup_failure = evidence_exc

    if primary is not None:
        raise primary.with_traceback(primary_tb)
    if cleanup_failure is not None:
        raise CleanupError("Lifecycle cleanup failed; durable incident evidence was requested.") from cleanup_failure
    return LifecycleArtifacts(
        execution_evidence_path=execution_written,
        terminal_evidence_path=terminal_path,
        cleanup_verified=bool(cleanup_payload and cleanup_payload.get("cleanup_verified")),
        branch_id=None if bound_proof is None else bound_proof.branch_id,
    )
