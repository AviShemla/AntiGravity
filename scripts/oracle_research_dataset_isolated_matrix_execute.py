"""Execute the approved Oracle schema matrix on an injected disposable branch.

The executor never creates or destroys a branch. Credentials and URLs are
injected directly or loaded from explicitly named env files by the CLI. The
cleanup command is generated separately and is never executed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from model_lineage import LineageError
from scripts.apply_atomic_migration import (
    AtomicMigrationError,
    _post_pipeline,
    _require_baton,
    apply_atomic_migration,
    parse_atomic_bundle,
    verify_pipeline_results,
)
from scripts.oracle_research_dataset_isolated_matrix import (
    BEHAVIOR_ASSERTION_IDS,
    EXPECTED_PRODUCTION_ID,
    EXPECTED_PRODUCTION_NAME,
    MIGRATION_PATH,
    PreBranchIntent,
    IsolatedBranchIdentity,
    IsolatedMatrixPlan,
    IsolatedMatrixReadback,
    TemporaryBranchApproval,
    _pre_branch_payload,
    bind_branch_identity,
    build_pre_branch_intent,
    execute_with_adapter,
)
from turso_read_pipeline import PipelineResult, TursoReadPipeline, _encode_arg


ROOT = Path(__file__).resolve().parents[1]
CLI = "/home/codexops/.turso/turso"
PROOF_SOURCE = "turso-cli-v1.0.32-db-show-text"
MAX_SHOW_BYTES = 64 * 1024
MAX_PROOF_AGE = timedelta(minutes=5)
SHOW_FIELD = re.compile(r"^([A-Za-z][A-Za-z ]*):[ \t]+(\S(?:.*\S)?)$")
PRODUCTION_SCHEMA_SQL = (
    "SELECT type,name,COALESCE(sql,'') AS sql FROM sqlite_schema "
    "WHERE name LIKE 'oracle_research_dataset_%' OR name LIKE 'trg_oracle_research_%' "
    "ORDER BY type,name"
)
PRODUCTION_LEDGER_SQL = (
    "SELECT event_id,migration_id,schema_version,artifact_sha256,operation,parent_event_id,"
    "actor,target_database_id,evidence_json,executed_at_utc FROM schema_migration_events_v2 "
    "WHERE migration_id=? ORDER BY executed_at_utc,event_id"
)
SCHEMA_READBACK_SQL = (
    "SELECT name FROM sqlite_schema WHERE name LIKE 'oracle_research_dataset_%' "
    "OR name LIKE 'idx_oracle_research_%' OR name LIKE 'trg_oracle_research_%' ORDER BY name"
)
APPLY_READBACK_SQL = (
    "SELECT event_id,COUNT(*) AS event_count FROM schema_migration_events_v2 "
    "WHERE migration_id=? AND operation='APPLY' AND artifact_sha256=? GROUP BY event_id"
)
ROLLBACK_READBACK_SQL = (
    "SELECT event_id,parent_event_id,COUNT(*) AS event_count FROM schema_migration_events_v2 "
    "WHERE migration_id=? AND operation='ROLLBACK' AND artifact_sha256=? "
    "GROUP BY event_id,parent_event_id"
)
RESIDUE_READBACK_SQL = (
    "SELECT "
    "(SELECT COUNT(*) FROM oracle_research_dataset_versions WHERE dataset_version_id=?) AS versions,"
    "(SELECT COUNT(*) FROM oracle_research_dataset_provider_lineage WHERE dataset_version_id=?) AS providers,"
    "(SELECT COUNT(*) FROM oracle_research_dataset_events WHERE dataset_version_id=?) AS events,"
    "(SELECT COUNT(*) FROM sqlite_schema WHERE name='oracle_matrix_failed_ddl_probe') AS ddl_probe"
)
ROLLBACK_EVENT_SQL = (
    "INSERT INTO schema_migration_events_v2 "
    "(event_id,migration_id,schema_version,artifact_sha256,operation,parent_event_id,actor,"
    "target_database_id,evidence_json,executed_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)"
)


@dataclass(frozen=True)
class CliResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CliRunner(Protocol):
    def run(self, argv: tuple[str, ...]) -> CliResult: ...


class SubprocessCliRunner:
    """Shell-free runner used only for exact read-only Turso identity commands."""

    def run(self, argv: tuple[str, ...]) -> CliResult:
        completed = subprocess.run(
            argv,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
        )
        return CliResult(argv, completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class BranchIdentityProof:
    proof_source: str
    branch_name: str
    branch_id: str
    parent_name: str
    parent_id: str
    observed_at_utc: str
    branch_show_sha256: str = ""
    production_show_sha256: str = ""

    def validate(
        self,
        expected: IsolatedBranchIdentity,
        *,
        intent_created_at_utc: str | None = None,
        verified_at: datetime | None = None,
    ) -> None:
        expected.validate()
        if self.proof_source != PROOF_SOURCE:
            raise LineageError("Branch identity proof source is not exact.")
        if (self.branch_name, self.branch_id, self.parent_name, self.parent_id) != (
            expected.branch_name,
            expected.branch_id,
            expected.parent_name,
            expected.parent_id,
        ):
            raise LineageError("Branch identity or parent proof differs from the approved plan.")
        try:
            parsed = datetime.fromisoformat(self.observed_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LineageError("Branch proof timestamp is invalid.") from exc
        if parsed.tzinfo is None:
            raise LineageError("Branch proof timestamp must be timezone-aware.")
        parsed = parsed.astimezone(timezone.utc)
        if intent_created_at_utc is not None:
            try:
                intent_time = datetime.strptime(
                    intent_created_at_utc, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise LineageError("Pre-branch intent timestamp is invalid.") from exc
            if parsed < intent_time:
                raise LineageError("Branch proof predates the preserved pre-branch intent.")
        if verified_at is not None:
            if verified_at.tzinfo is None:
                raise LineageError("Branch proof verification timestamp must be timezone-aware.")
            age = verified_at.astimezone(timezone.utc) - parsed
            if age < timedelta(seconds=-5) or age > MAX_PROOF_AGE:
                raise LineageError("Branch identity proof is stale or future-dated.")
        for value in (self.branch_show_sha256, self.production_show_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise LineageError("Branch identity proof evidence hash is invalid.")


def _canonical_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise LineageError("Evidence timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _show_result(result: CliResult, expected_argv: tuple[str, ...]) -> dict[str, str]:
    if result.argv != expected_argv:
        raise LineageError("Turso CLI evidence command identity is not exact.")
    if result.returncode != 0:
        raise LineageError("Turso CLI identity command did not succeed.")
    if result.stderr.strip():
        raise LineageError("Turso CLI identity command emitted unexpected stderr.")
    raw = result.stdout.encode("utf-8")
    if not raw or len(raw) > MAX_SHOW_BYTES or "\x00" in result.stdout or "\x1b" in result.stdout:
        raise LineageError("Turso CLI identity output is empty, oversized, or contains controls.")
    header = result.stdout.split("\nDatabase Instances:", 1)[0]
    fields: dict[str, str] = {}
    for raw_line in header.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        match = SHOW_FIELD.fullmatch(line)
        if match is None:
            raise LineageError("Turso CLI identity output contains an ambiguous header line.")
        key, value = match.groups()
        if key in fields:
            raise LineageError("Turso CLI identity output contains a duplicate field.")
        fields[key] = value
    return fields


def derive_branch_identity_from_cli(
    intent: PreBranchIntent,
    runner: CliRunner,
    *,
    observed_at: datetime | None = None,
) -> BranchIdentityProof:
    """Derive identity only from two exact, fresh Turso v1.0.32 show calls."""

    branch_argv = (CLI, "db", "show", intent.branch_name)
    production_argv = (CLI, "db", "show", EXPECTED_PRODUCTION_NAME)
    branch_result = runner.run(branch_argv)
    production_result = runner.run(production_argv)
    branch_fields = _show_result(branch_result, branch_argv)
    production_fields = _show_result(production_result, production_argv)
    for label, fields, required in (
        ("branch", branch_fields, {"Name", "ID", "Parent"}),
        ("production", production_fields, {"Name", "ID"}),
    ):
        missing = sorted(required - set(fields))
        if missing:
            raise LineageError(
                f"Turso CLI {label} identity output is missing required fields."
            )
    if "Parent" in production_fields:
        raise LineageError("Production identity unexpectedly reports a parent.")
    if branch_fields["Name"] != intent.branch_name:
        raise LineageError("Turso CLI branch name differs from the preserved intent.")
    if production_fields["Name"] != EXPECTED_PRODUCTION_NAME:
        raise LineageError("Turso CLI production name differs from the governed parent.")
    if production_fields["ID"] != EXPECTED_PRODUCTION_ID:
        raise LineageError("Turso CLI production ID differs from the governed parent.")
    if branch_fields["Parent"] != production_fields["Name"]:
        raise LineageError("Turso CLI branch parent differs from production readback.")
    timestamp = observed_at or datetime.now(timezone.utc)
    proof = BranchIdentityProof(
        proof_source=PROOF_SOURCE,
        branch_name=branch_fields["Name"],
        branch_id=branch_fields["ID"],
        parent_name=production_fields["Name"],
        parent_id=production_fields["ID"],
        observed_at_utc=_canonical_utc(timestamp),
        branch_show_sha256=hashlib.sha256(branch_result.stdout.encode("utf-8")).hexdigest(),
        production_show_sha256=hashlib.sha256(
            production_result.stdout.encode("utf-8")
        ).hexdigest(),
    )
    expected = IsolatedBranchIdentity(
        intent.branch_name,
        proof.branch_id,
        intent.parent_name,
        intent.parent_id,
    )
    proof.validate(
        expected,
        intent_created_at_utc=intent.created_at_utc,
        verified_at=timestamp,
    )
    return proof


def _reject_duplicate_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LineageError("Pre-branch intent JSON contains a duplicate key.")
        result[key] = value
    return result


def load_pre_branch_intent(path: Path) -> PreBranchIntent:
    """Rebuild and exactly compare the preserved redacted Phase-A artifact."""

    raw = Path(path).read_bytes()
    if not raw or len(raw) > MAX_SHOW_BYTES:
        raise LineageError("Pre-branch intent file is empty or oversized.")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LineageError("Pre-branch intent JSON is invalid.") from exc
    if not isinstance(payload, dict):
        raise LineageError("Pre-branch intent JSON must be an object.")
    try:
        created_at = datetime.strptime(
            str(payload["created_at_utc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        approval = TemporaryBranchApproval(
            str(payload["approval_id"]), True, True, True, True, True, True
        )
        intent = build_pre_branch_intent(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch_name=str(payload["branch_name"]),
            approval=approval,
            source_commit=str(payload["source_commit"]),
            created_at=created_at,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LineageError("Pre-branch intent fields are missing or invalid.") from exc
    if payload != _pre_branch_payload(intent):
        raise LineageError("Pre-branch intent artifact identity or scope does not match.")
    return intent


@dataclass(frozen=True)
class MatrixCredentials:
    branch_url: str
    branch_token: str
    production_url: str
    production_token: str


@dataclass(frozen=True)
class BehaviorProbe:
    assertion_id: str
    setup: tuple[tuple[str, tuple[object, ...]], ...]
    action_sql: str
    action_args: tuple[object, ...]
    expect_error: bool
    expected_affected_rows: int | None = None


class MatrixBranch(Protocol):
    def apply(self, plan: IsolatedMatrixPlan) -> None: ...
    def select(self, sql: str, args: list[object]) -> PipelineResult: ...
    def run_probe(self, probe: BehaviorProbe) -> bool: ...
    def append_logical_rollback(self, plan: IsolatedMatrixPlan) -> None: ...


def _endpoint(raw: str, *, expected_name: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise LineageError("Turso URL is required.")
    normalized = raw.replace("libsql://", "https://", 1).rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise LineageError("Turso URL must be credential-free HTTPS/libsql.")
    if parsed.query or parsed.fragment:
        raise LineageError("Turso URL cannot contain query or fragment data.")
    label = parsed.hostname.split(".")[0]
    if label != expected_name and not label.startswith(expected_name + "-"):
        raise LineageError("Turso URL hostname does not match the exact target name.")
    return normalized + "/v2/pipeline"


def validate_credentials(
    plan: IsolatedMatrixPlan, proof: BranchIdentityProof, credentials: MatrixCredentials
) -> tuple[str, str]:
    proof.validate(plan.branch)
    branch_endpoint = _endpoint(credentials.branch_url, expected_name=plan.branch.branch_name)
    production_endpoint = _endpoint(
        credentials.production_url, expected_name=EXPECTED_PRODUCTION_NAME
    )
    if branch_endpoint == production_endpoint:
        raise LineageError("Disposable branch target resolves to production.")
    if not credentials.branch_token or not credentials.production_token:
        raise LineageError("Both injected Turso tokens are required.")
    if credentials.branch_token == credentials.production_token:
        raise LineageError("Disposable and production read-only tokens must be distinct.")
    return branch_endpoint, production_endpoint


def _canonical_sha256(payload: object) -> str:
    raw = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fingerprint(reader) -> tuple[str, int]:
    schema = reader.execute(PRODUCTION_SCHEMA_SQL, [])
    ledger = reader.execute(
        PRODUCTION_LEDGER_SQL,
        ["20260826_oracle_research_dataset_versions_additive"],
    )
    payload = {
        "schema": {"columns": list(schema.columns), "rows": [list(row) for row in schema.rows]},
        "ledger": {"columns": list(ledger.columns), "rows": [list(row) for row in ledger.rows]},
    }
    return _canonical_sha256(payload), len(schema.rows)


def _fixture(plan: IsolatedMatrixPlan) -> dict[str, object]:
    suffix = plan.plan_id.rsplit("-", 1)[-1]
    return {
        "source": f"matrix-source-{suffix}",
        "unbound": f"matrix-unbound-{suffix}",
        "version": f"matrix-version-{suffix}",
        "freeze_event": f"matrix-freeze-{suffix}",
        "second_event": f"matrix-freeze-duplicate-{suffix}",
        "now": plan.created_at_utc,
    }


def _probe_sql(plan: IsolatedMatrixPlan) -> tuple[BehaviorProbe, ...]:
    f = _fixture(plan)
    source = f["source"]
    version = f["version"]
    now = f["now"]
    snapshot_insert = (
        "INSERT INTO model_input_snapshots "
        "(snapshot_id,dataset_type,source_session_date,available_at_utc,provider,code_version,"
        "source_checksum_sha256,expected_row_count,expected_ticker_count,status,validation_notes,created_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (source, "MARKET_FEATURES", "2026-08-25", now, "YAHOO_FINANCE", plan.source_commit,
         "a" * 64, 1, 1, "VALIDATED", "isolated-matrix-fixture", now),
    )
    unbound_insert = (snapshot_insert[0], (f["unbound"],) + snapshot_insert[1][1:])
    feature_insert = (
        "INSERT INTO market_daily_features (snapshot_id,ticker,date,close_price) VALUES (?,?,?,?)",
        (source, "AAA", "2026-08-25", 1.0),
    )
    source_lineage_insert = (
        "INSERT INTO market_data_provider_lineage "
        "(snapshot_id,ticker,provider,requested_source_session_date,first_available_date,"
        "last_available_date,source_row_count,source_checksum_sha256,created_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (source, "AAA", "YAHOO_FINANCE", "2026-08-25", "2026-08-25", "2026-08-25", 1,
         "d" * 64, now),
    )
    stage_sql = (
        "INSERT INTO oracle_research_dataset_versions "
        "(dataset_version_id,market_snapshot_id,market_snapshot_checksum_sha256,source_session_date,"
        "evidence_cutoff_utc,first_session_date,last_session_date,expected_row_count,"
        "expected_ticker_count,expected_session_count,expected_provider_lineage_count,content_sha256,"
        "ticker_universe_sha256,provider_lineage_sha256,schema_version,code_version,status,created_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    stage_args = (version, source, "a" * 64, "2026-08-25", now, "2026-08-25", "2026-08-25",
                  1, 1, 1, 1, "b" * 64, "c" * 64, "d" * 64, "1", plan.source_commit,
                  "STAGING", now)
    provider_sql = (
        "INSERT INTO oracle_research_dataset_provider_lineage "
        "(dataset_version_id,ticker,provider,requested_source_session_date,first_available_date,"
        "last_available_date,source_row_count,source_checksum_sha256,created_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?)"
    )
    provider_args = (version, "AAA", "YAHOO_FINANCE", "2026-08-25", "2026-08-25",
                     "2026-08-25", 1, "d" * 64, now)
    event_sql = (
        "INSERT INTO oracle_research_dataset_events "
        "(event_id,dataset_version_id,event_type,market_snapshot_checksum_sha256,content_sha256,"
        "ticker_universe_sha256,provider_lineage_sha256,actor,decided_at_utc,evidence_sha256,created_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    )
    event_args = (f["freeze_event"], version, "FREEZE", "a" * 64, "b" * 64, "c" * 64,
                  "d" * 64, "codexops", now, "e" * 64, now)
    freeze_sql = (
        "UPDATE oracle_research_dataset_versions SET status='FROZEN',freeze_approval_id=?,"
        "frozen_by=?,frozen_at_utc=? WHERE dataset_version_id=? AND status='STAGING'"
    )
    freeze_args = (f["freeze_event"], "codexops", now, version)
    source_setup = (snapshot_insert, feature_insert, source_lineage_insert)
    stage_setup = source_setup + ((stage_sql, stage_args),)
    event_setup = stage_setup + ((event_sql, event_args),)
    frozen_setup = event_setup + ((freeze_sql, freeze_args),)
    provider_setup = stage_setup + ((provider_sql, provider_args),)

    def p(assertion_id, setup, sql, args=(), *, error=False, affected=None):
        return BehaviorProbe(assertion_id, setup, sql, tuple(args), error, affected)

    direct_frozen = list(stage_args); direct_frozen[0] = f"{version}-direct"; direct_frozen[16] = "FROZEN"
    missing_event = list(event_args); missing_event[0] = f"{f['freeze_event']}-missing"; missing_event[1] = f"{version}-missing"
    revoke = list(event_args); revoke[0] = f"{f['freeze_event']}-revoke"; revoke[2] = "REVOKE"
    duplicate = list(event_args); duplicate[0] = f["second_event"]
    return (
        p("staging_insert_allowed", source_setup, stage_sql, stage_args, affected=1),
        p("direct_frozen_insert_rejected", source_setup, stage_sql, direct_frozen, error=True),
        p("staging_provider_binding_allowed", stage_setup, provider_sql, provider_args, affected=1),
        p("freeze_event_requires_staging", source_setup, event_sql, missing_event, error=True),
        p("freeze_transition_exactly_one", event_setup, freeze_sql, freeze_args, affected=1),
        p("duplicate_freeze_event_rejected", event_setup, event_sql, duplicate, error=True),
        p("revoke_requires_frozen", stage_setup, event_sql, revoke, error=True),
        p("frozen_version_update_rejected", frozen_setup,
          "UPDATE oracle_research_dataset_versions SET code_version=? WHERE dataset_version_id=?",
          ("changed", version), error=True),
        p("version_delete_rejected", stage_setup,
          "DELETE FROM oracle_research_dataset_versions WHERE dataset_version_id=?", (version,), error=True),
        p("provider_insert_after_freeze_rejected", frozen_setup, provider_sql, provider_args, error=True),
        p("provider_update_rejected", provider_setup,
          "UPDATE oracle_research_dataset_provider_lineage SET provider=? WHERE dataset_version_id=? AND ticker=?",
          ("TIINGO_EOD", version, "AAA"), error=True),
        p("provider_delete_rejected", provider_setup,
          "DELETE FROM oracle_research_dataset_provider_lineage WHERE dataset_version_id=? AND ticker=?",
          (version, "AAA"), error=True),
        p("event_update_rejected", event_setup,
          "UPDATE oracle_research_dataset_events SET actor=? WHERE event_id=?",
          ("changed", f["freeze_event"]), error=True),
        p("event_delete_rejected", event_setup,
          "DELETE FROM oracle_research_dataset_events WHERE event_id=?", (f["freeze_event"],), error=True),
        p("bound_source_metadata_update_rejected", frozen_setup,
          "UPDATE model_input_snapshots SET validation_notes=? WHERE snapshot_id=?", ("changed", source), error=True),
        p("bound_source_metadata_delete_rejected", frozen_setup,
          "DELETE FROM model_input_snapshots WHERE snapshot_id=?", (source,), error=True),
        p("bound_feature_insert_rejected", frozen_setup, feature_insert[0],
          (source, "BBB", "2026-08-25", 2.0), error=True),
        p("bound_feature_update_rejected", frozen_setup,
          "UPDATE market_daily_features SET close_price=? WHERE snapshot_id=? AND ticker=? AND date=?",
          (2.0, source, "AAA", "2026-08-25"), error=True),
        p("bound_feature_delete_rejected", frozen_setup,
          "DELETE FROM market_daily_features WHERE snapshot_id=? AND ticker=? AND date=?",
          (source, "AAA", "2026-08-25"), error=True),
        p("bound_source_lineage_insert_rejected", frozen_setup, source_lineage_insert[0],
          (source, "BBB", "YAHOO_FINANCE", "2026-08-25", "2026-08-25", "2026-08-25", 1, "f" * 64, now), error=True),
        p("bound_source_lineage_update_rejected", frozen_setup,
          "UPDATE market_data_provider_lineage SET provider=? WHERE snapshot_id=? AND ticker=?",
          ("TIINGO_EOD", source, "AAA"), error=True),
        p("bound_source_lineage_delete_rejected", frozen_setup,
          "DELETE FROM market_data_provider_lineage WHERE snapshot_id=? AND ticker=?",
          (source, "AAA"), error=True),
        p("unbound_source_fixture_remains_mutable", frozen_setup + (unbound_insert,),
          "UPDATE model_input_snapshots SET validation_notes=? WHERE snapshot_id=?",
          ("mutable", f["unbound"]), affected=1),
        p("injected_ddl_failure_rolled_back",
          (("CREATE TABLE oracle_matrix_failed_ddl_probe (id TEXT PRIMARY KEY)", ()),),
          "CREATE TABLE oracle_matrix_failed_ddl_probe (id TEXT PRIMARY KEY", (), error=True),
    )


class TursoMatrixBranch:
    """Concrete branch surface using atomic-runner and read-pipeline patterns."""

    def __init__(self, endpoint: str, token: str, *, session, timeout: float = 45.0):
        self.endpoint = endpoint
        self.token = token
        self.session = session
        self.timeout = timeout
        self.reader = TursoReadPipeline(endpoint, token, timeout_seconds=timeout, session=session)

    def apply(self, plan: IsolatedMatrixPlan) -> None:
        migration = parse_atomic_bundle(MIGRATION_PATH.read_bytes())
        apply_atomic_migration(
            self.session, self.endpoint, self.token, migration,
            event_id=plan.apply_event_id, actor="codexops", target_database_id=plan.branch.branch_id,
            evidence={"approval_id": plan.approval.approval_id, "branch_id": plan.branch.branch_id,
                      "branch_name": plan.branch.branch_name, "plan_id": plan.plan_id,
                      "scope": "isolated-oracle-research-dataset-matrix"},
            executed_at_utc=plan.created_at_utc,
        )

    def select(self, sql: str, args: list[object]) -> PipelineResult:
        return self.reader.execute(sql, args)

    def _send(self, sql: str, args: tuple[object, ...], *, baton: str | None = None) -> dict:
        return _post_pipeline(
            self.session, self.endpoint, self.token,
            [{"type": "execute", "stmt": {"sql": sql, "args": [_encode_arg(v) for v in args]}}],
            baton=baton, timeout=self.timeout,
        )

    def run_probe(self, probe: BehaviorProbe) -> bool:
        begin = self._send("BEGIN IMMEDIATE", ())
        verify_pipeline_results(begin, 1)
        baton = _require_baton(begin)
        try:
            for sql, args in probe.setup:
                result = self._send(sql, args, baton=baton)
                baton = _require_baton(result)
                verify_pipeline_results(result, 1)
            action = self._send(probe.action_sql, probe.action_args, baton=baton)
            item = action.get("results", [{}])[0]
            errored = isinstance(item, dict) and item.get("type") == "error"
            if not errored:
                verify_pipeline_results(action, 1)
                baton = _require_baton(action)
                affected = item.get("response", {}).get("result", {}).get("affected_row_count")
                if probe.expected_affected_rows is not None:
                    passed = str(affected) == str(probe.expected_affected_rows)
                else:
                    passed = True
            else:
                baton = _require_baton(action)
                passed = probe.expect_error
            if probe.expect_error and not errored:
                passed = False
            rollback = self._send("ROLLBACK", (), baton=baton)
            verify_pipeline_results(rollback, 1)
            return passed
        except Exception:
            try:
                rollback = self._send("ROLLBACK", (), baton=baton)
                verify_pipeline_results(rollback, 1)
            except Exception as rollback_exc:
                raise AtomicMigrationError("Probe failed and rollback was not verified.") from rollback_exc
            raise

    def append_logical_rollback(self, plan: IsolatedMatrixPlan) -> None:
        evidence = json.dumps(
            {"apply_event_id": plan.apply_event_id, "approval_id": plan.approval.approval_id,
             "branch_id": plan.branch.branch_id, "branch_name": plan.branch.branch_name,
             "logical_rollback": True, "plan_id": plan.plan_id,
             "scope": "isolated-oracle-research-dataset-matrix"},
            sort_keys=True, separators=(",", ":"),
        )
        args = (plan.rollback_event_id, plan.migration_id, plan.schema_version,
                plan.migration_sha256, "ROLLBACK", plan.apply_event_id, "codexops",
                plan.branch.branch_id, evidence, plan.created_at_utc)
        begin = self._send("BEGIN IMMEDIATE", ())
        verify_pipeline_results(begin, 1); baton = _require_baton(begin)
        try:
            written = self._send(ROLLBACK_EVENT_SQL, args, baton=baton)
            verify_pipeline_results(written, 1); baton = _require_baton(written)
            committed = self._send("COMMIT", (), baton=baton)
            verify_pipeline_results(committed, 1)
        except Exception:
            rollback = self._send("ROLLBACK", (), baton=baton)
            verify_pipeline_results(rollback, 1)
            raise


class IsolatedMatrixExecutionAdapter:
    def __init__(self, branch: MatrixBranch, production_reader):
        self.branch = branch
        self.production_reader = production_reader

    @staticmethod
    def _one(result: PipelineResult, width: int, label: str) -> tuple[object, ...]:
        if len(result.rows) != 1 or len(result.rows[0]) != width:
            raise LineageError(f"{label} readback is not exact.")
        return tuple(result.rows[0])

    def run(self, plan: IsolatedMatrixPlan) -> IsolatedMatrixReadback:
        before, before_count = _fingerprint(self.production_reader)
        applied = False
        try:
            self.branch.apply(plan)
            applied = True
            schema = self.branch.select(SCHEMA_READBACK_SQL, [])
            schema_objects = tuple(str(row[0]) for row in schema.rows)
            apply_row = self._one(
                self.branch.select(
                    APPLY_READBACK_SQL, [plan.migration_id, plan.migration_sha256]
                ), 2, "APPLY event",
            )
            assertions = {key: False for key in BEHAVIOR_ASSERTION_IDS}
            assertions["migration_apply_event_exact"] = apply_row == (
                plan.apply_event_id, 1
            )
            for probe in _probe_sql(plan):
                assertions[probe.assertion_id] = self.branch.run_probe(probe)
            assertions["ambiguous_apply_requires_exact_readback"] = apply_row == (
                plan.apply_event_id, 1
            )
        finally:
            if applied:
                self.branch.append_logical_rollback(plan)
            after, after_count = _fingerprint(self.production_reader)
        rollback_row = self._one(
            self.branch.select(
                ROLLBACK_READBACK_SQL, [plan.migration_id, plan.migration_sha256]
            ), 3, "ROLLBACK event",
        )
        fixture_id = _fixture(plan)["version"]
        residue = self._one(
            self.branch.select(RESIDUE_READBACK_SQL, [fixture_id, fixture_id, fixture_id]), 4,
            "Fixture residue",
        )
        return IsolatedMatrixReadback(
            branch_name=plan.branch.branch_name, branch_id=plan.branch.branch_id,
            migration_sha256=plan.migration_sha256, statement_count=plan.statement_count,
            schema_objects=tuple(sorted(schema_objects)), apply_event_id=str(apply_row[0]),
            apply_event_count=int(apply_row[1]), assertion_results=assertions,
            rollback_event_id=str(rollback_row[0]), rollback_parent_event_id=str(rollback_row[1]),
            rollback_event_count=int(rollback_row[2]), fixture_version_rows=int(residue[0]),
            fixture_provider_rows=int(residue[1]), fixture_event_rows=int(residue[2]),
            failed_ddl_probe_rows=int(residue[3]), production_fingerprint_before=before,
            production_fingerprint_after=after,
            production_oracle_object_count_before=before_count,
            production_oracle_object_count_after=after_count,
        )


def build_redacted_evidence(
    plan: IsolatedMatrixPlan,
    readback: IsolatedMatrixReadback,
    *,
    intent: PreBranchIntent | None = None,
    proof: BranchIdentityProof | None = None,
) -> dict[str, object]:
    payload = {
        "evidence_contract": "oracle-research-isolated-matrix-execution-v1",
        "plan_id": plan.plan_id,
        "source_commit": plan.source_commit,
        "created_at_utc": plan.created_at_utc,
        "branch_identity": asdict(plan.branch),
        "approval_id": plan.approval.approval_id,
        "migration": {"id": plan.migration_id, "sha256": plan.migration_sha256,
                      "schema_version": plan.schema_version, "statement_count": plan.statement_count},
        "readback": asdict(readback),
        "redaction": {"branch_url_included": False, "production_url_included": False,
                      "token_included": False, "response_bodies_included": False},
    }
    if intent is not None:
        payload["pre_branch_intent"] = {
            "intent_id": intent.intent_id,
            "created_at_utc": intent.created_at_utc,
            "approval_id": intent.approval.approval_id,
            "source_commit": intent.source_commit,
        }
    if proof is not None:
        payload["branch_identity_proof"] = asdict(proof)
    payload["evidence_sha256"] = _canonical_sha256(payload)
    return payload


def exact_cleanup_command(proof: BranchIdentityProof) -> tuple[str, ...]:
    identity = IsolatedBranchIdentity(
        proof.branch_name, proof.branch_id, proof.parent_name, proof.parent_id
    )
    proof.validate(identity)
    if identity.parent_id != EXPECTED_PRODUCTION_ID or identity.branch_id == EXPECTED_PRODUCTION_ID:
        raise LineageError("Cleanup target is not the exact disposable branch.")
    return ("/home/codexops/.turso/turso", "db", "destroy", identity.branch_name, "--yes")


def _env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise LineageError("Credential env file contains a malformed line.")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in values:
            raise LineageError("Credential env file contains a duplicate key.")
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _proof_file(path: Path) -> BranchIdentityProof:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != set(BranchIdentityProof.__annotations__):
        raise LineageError("Branch proof JSON keys are not exact.")
    return BranchIdentityProof(**value)


def main(
    argv: list[str] | None = None,
    *,
    cli_runner: CliRunner | None = None,
    observed_at: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    cleanup = sub.add_parser("cleanup-command")
    cleanup.add_argument("--branch-proof-json", type=Path, required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--intent-json", type=Path, required=True)
    execute.add_argument("--branch-env-file", type=Path, required=True)
    execute.add_argument("--production-env-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "cleanup-command":
        proof = _proof_file(args.branch_proof_json)
        print(json.dumps({"branch_id": proof.branch_id, "command": list(exact_cleanup_command(proof)),
                          "destructive": True, "executed": False}, sort_keys=True, separators=(",", ":")))
        return 0
    intent = load_pre_branch_intent(args.intent_json)
    proof = derive_branch_identity_from_cli(
        intent,
        cli_runner or SubprocessCliRunner(),
        observed_at=observed_at,
    )
    plan = bind_branch_identity(
        intent,
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_id=proof.branch_id,
        parent_name=proof.parent_name,
        parent_id=proof.parent_id,
    )
    branch_env = _env_file(args.branch_env_file)
    production_env = _env_file(args.production_env_file)
    credentials = MatrixCredentials(
        branch_env.get("TURSO_ISOLATED_DATABASE_URL", ""),
        branch_env.get("TURSO_ISOLATED_AUTH_TOKEN", ""),
        production_env.get("TURSO_DATABASE_URL", ""),
        production_env.get("TURSO_AUTH_TOKEN", ""),
    )
    branch_endpoint, production_endpoint = validate_credentials(plan, proof, credentials)
    import requests
    branch_session = requests.Session()
    production_session = requests.Session()
    adapter = IsolatedMatrixExecutionAdapter(
        TursoMatrixBranch(branch_endpoint, credentials.branch_token, session=branch_session),
        TursoReadPipeline(production_endpoint, credentials.production_token,
                          timeout_seconds=45.0, session=production_session),
    )
    readback = execute_with_adapter(plan, adapter)
    print(json.dumps(
        build_redacted_evidence(plan, readback, intent=intent, proof=proof),
        sort_keys=True,
        separators=(",", ":"),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
