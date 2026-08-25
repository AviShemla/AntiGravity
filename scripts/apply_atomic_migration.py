"""Hash-pinned failure-atomic Turso migration runner; check-only by default."""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from turso_read_pipeline import _encode_arg

_ID=re.compile(r"^[a-z0-9][a-z0-9_]{7,127}$")
_SHA=re.compile(r"^[0-9a-f]{64}$")
_UTC=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_START=re.compile(r"^-- statement: ([a-z0-9][a-z0-9_]*)$")
_END="-- end-statement"
_ALLOWED=("CREATE TABLE IF NOT EXISTS ","CREATE INDEX IF NOT EXISTS ",
          "CREATE UNIQUE INDEX IF NOT EXISTS ","CREATE TRIGGER IF NOT EXISTS ")


@dataclass(frozen=True)
class AtomicMigration:
    migration_id: str
    schema_version: int
    artifact_sha256: str
    statements: tuple[tuple[str,str],...]


class AtomicMigrationError(ValueError):
    """Raised when Turso cannot prove a failure-atomic migration outcome."""


def canonical_utc_seconds(value: datetime|None=None)->str:
    moment=value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("Migration timestamp must be timezone-aware.")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_atomic_bundle(raw: bytes)->AtomicMigration:
    try: text=raw.decode("utf-8")
    except UnicodeDecodeError as exc: raise ValueError("Migration must be UTF-8.") from exc
    migration_id=None; version=None; statements=[]; names=set(); name=None; lines=[]
    for line in text.splitlines():
        if name is None:
            if line.startswith("-- migration-id: "):
                if migration_id is not None: raise ValueError("Migration id is duplicated.")
                migration_id=line.split(":",1)[1].strip()
            elif line.startswith("-- schema-version: "):
                if version is not None: raise ValueError("Schema version is duplicated.")
                try: version=int(line.split(":",1)[1].strip())
                except ValueError as exc: raise ValueError("Schema version must be an integer.") from exc
            elif (match:=_START.fullmatch(line)):
                name=match.group(1)
                if name in names: raise ValueError("Migration statement name is duplicated.")
                lines=[]
            elif line==_END: raise ValueError("Migration has an unmatched end marker.")
            elif line.strip() and not line.lstrip().startswith("--"):
                raise ValueError("SQL must be enclosed by statement markers.")
        else:
            if _START.fullmatch(line): raise ValueError("Migration statement markers cannot be nested.")
            if line==_END:
                sql="\n".join(lines).strip()
                if not sql: raise ValueError("Migration statement is empty.")
                if not " ".join(sql.split()).upper().startswith(_ALLOWED):
                    raise ValueError("Migration contains a non-additive statement.")
                statements.append((name,sql)); names.add(name); name=None
            else: lines.append(line)
    if name is not None: raise ValueError("Migration statement is missing an end marker.")
    if migration_id is None or not _ID.fullmatch(migration_id):
        raise ValueError("Migration id is missing or invalid.")
    if version is None or version<=0: raise ValueError("Schema version must be positive.")
    if not statements: raise ValueError("Migration contains no statements.")
    return AtomicMigration(migration_id,version,hashlib.sha256(raw).hexdigest(),tuple(statements))


def verify_expected_hash(migration: AtomicMigration, expected: str)->None:
    if not _SHA.fullmatch(expected):
        raise ValueError("Expected SHA-256 must be 64 lowercase hex characters.")
    if migration.artifact_sha256!=expected:
        raise ValueError("Migration SHA-256 does not match the reviewed artifact.")


def build_atomic_statement_batch(migration: AtomicMigration, *, event_id: str, actor: str,
                                  target_database_id: str, evidence: dict[str,object],
                                  executed_at_utc: str)->list[dict]:
    if not all(v.strip() for v in (event_id,actor,target_database_id)):
        raise ValueError("Migration ledger identity is incomplete.")
    if not _UTC.fullmatch(executed_at_utc):
        raise ValueError("Migration timestamp must be canonical UTC seconds.")
    requests=[{"type":"execute","stmt":{"sql":sql,"args":[]}}
              for _,sql in migration.statements]
    values=[event_id,migration.migration_id,migration.schema_version,
            migration.artifact_sha256,"APPLY",actor,target_database_id,
            json.dumps(evidence,sort_keys=True,separators=(",",":")),executed_at_utc]
    requests.append({"type":"execute","stmt":{"sql":
        "INSERT INTO schema_migration_events_v2 "
        "(event_id,migration_id,schema_version,artifact_sha256,operation,actor,"
        "target_database_id,evidence_json,executed_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
        "args":[_encode_arg(v) for v in values]}})
    return requests


def verify_pipeline_results(payload: object, expected: int)->None:
    if not isinstance(payload,dict) or not isinstance(payload.get("results"),list):
        raise AtomicMigrationError("Turso returned invalid migration JSON.")
    results=payload["results"]
    if len(results)<expected:
        raise AtomicMigrationError("Turso returned an incomplete migration result set.")
    failed=[i for i,item in enumerate(results[:expected])
            if not isinstance(item,dict) or item.get("type")!="ok"]
    if failed:
        raise AtomicMigrationError(f"Turso rejected the atomic migration at result indexes {failed}.")


def _post_pipeline(session, endpoint: str, token: str, requests_: list[dict], *,
                   baton: str|None=None, timeout: float=45.0)->dict:
    body={"requests":requests_}
    if baton is not None: body["baton"]=baton
    response=session.post(endpoint,headers={"Authorization":f"Bearer {token}",
        "Content-Type":"application/json"},json=body,timeout=timeout)
    if response.status_code!=200:
        raise AtomicMigrationError(f"Atomic migration failed with HTTP {response.status_code}.")
    try: payload=response.json()
    except (ValueError,json.JSONDecodeError) as exc:
        raise AtomicMigrationError("Turso returned invalid migration JSON.") from exc
    if not isinstance(payload,dict):
        raise AtomicMigrationError("Turso returned invalid migration JSON.")
    return payload


def _require_baton(payload: dict)->str:
    baton=payload.get("baton")
    if not isinstance(baton,str) or not baton:
        raise AtomicMigrationError("Turso did not return a transaction baton.")
    return baton


def _close_connection(session, endpoint: str, token: str, baton: str)->None:
    payload=_post_pipeline(session,endpoint,token,[{"type":"close"}],baton=baton)
    verify_pipeline_results(payload,1)


def _rollback_connection(session, endpoint: str, token: str, baton: str)->None:
    payload=_post_pipeline(session,endpoint,token,[{"type":"execute","stmt":{
        "sql":"ROLLBACK","args":[]}}],baton=baton)
    verify_pipeline_results(payload,1)
    # COMMIT and ROLLBACK terminate the Hrana transaction. Turso normally
    # returns no baton after either terminal statement, so there is no
    # connection left to close.


def apply_atomic_migration(session, endpoint: str, token: str, migration: AtomicMigration, *,
                           event_id: str, actor: str, target_database_id: str,
                           evidence: dict[str,object], executed_at_utc: str)->None:
    """Apply all statements and the ledger inside one rollback-capable transaction."""
    begin=_post_pipeline(session,endpoint,token,[{"type":"execute","stmt":{
        "sql":"BEGIN IMMEDIATE","args":[]}}])
    verify_pipeline_results(begin,1)
    baton=_require_baton(begin)
    try:
        requests_=build_atomic_statement_batch(migration,event_id=event_id,actor=actor,
            target_database_id=target_database_id,evidence=evidence,
            executed_at_utc=executed_at_utc)
        applied=_post_pipeline(session,endpoint,token,requests_,baton=baton)
        baton=_require_baton(applied)
        verify_pipeline_results(applied,len(requests_))
        committed=_post_pipeline(session,endpoint,token,[{"type":"execute","stmt":{
            "sql":"COMMIT","args":[]}}],baton=baton)
        verify_pipeline_results(committed,1)
        # A successful COMMIT is terminal and normally returns no baton.
    except Exception as exc:
        try: _rollback_connection(session,endpoint,token,baton)
        except Exception as rollback_exc:
            raise AtomicMigrationError(
                f"Migration failed and rollback could not be verified: {rollback_exc}"
            ) from exc
        raise


def resolve_target_environment(environment: str, production_approval_id: str|None)->tuple[str,str]:
    if environment=="isolated":
        raw_url=os.environ.get("TURSO_ISOLATED_DATABASE_URL","")
        token=os.environ.get("TURSO_ISOLATED_AUTH_TOKEN","")
        production_url=os.environ.get("TURSO_DATABASE_URL","")
        if not raw_url or not token:
            raise ValueError("Isolated Turso environment variables are unavailable.")
        if production_url and raw_url.rstrip("/")==production_url.rstrip("/"):
            raise ValueError("Isolated Turso target resolves to production.")
    elif environment=="production":
        if not production_approval_id:
            raise ValueError("Production apply requires a recorded approval id.")
        raw_url=os.environ.get("TURSO_DATABASE_URL","")
        token=os.environ.get("TURSO_AUTH_TOKEN","")
        if not raw_url or not token:
            raise ValueError("Production Turso environment variables are unavailable.")
    else:
        raise ValueError("Unsupported Turso target environment.")
    return raw_url.replace("libsql://","https://").rstrip("/")+"/v2/pipeline",token


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("migration"); parser.add_argument("--apply",action="store_true")
    parser.add_argument("--expected-sha256"); parser.add_argument("--event-id")
    parser.add_argument("--actor"); parser.add_argument("--target-database-id")
    parser.add_argument("--target-environment",choices=("isolated","production"),default="isolated")
    parser.add_argument("--production-approval-id")
    parser.add_argument("--evidence-json",default="{}"); args=parser.parse_args()
    root=ROOT
    path=(root/args.migration).resolve()
    if path.parent!=(root/"migrations").resolve() or path.suffix!=".sql":
        raise SystemExit("Migration must be a direct .sql file under migrations/.")
    try: migration=parse_atomic_bundle(path.read_bytes())
    except (OSError,ValueError) as exc: raise SystemExit(str(exc)) from exc
    if not args.apply:
        print(f"CHECKED_ATOMIC_MIGRATION id={migration.migration_id} "
              f"version={migration.schema_version} statements={len(migration.statements)} "
              f"sha256={migration.artifact_sha256} no_changes=true")
        return 0
    required={"--expected-sha256":args.expected_sha256,"--event-id":args.event_id,
              "--actor":args.actor,"--target-database-id":args.target_database_id}
    missing=[key for key,value in required.items() if not value]
    if missing: raise SystemExit(f"--apply requires {', '.join(missing)}.")
    try:
        verify_expected_hash(migration,args.expected_sha256)
        evidence=json.loads(args.evidence_json)
        if not isinstance(evidence,dict): raise ValueError("Evidence JSON must be an object.")
    except (ValueError,json.JSONDecodeError) as exc: raise SystemExit(str(exc)) from exc
    from dotenv import load_dotenv
    import requests
    load_dotenv(root/".env")
    try: endpoint,token=resolve_target_environment(args.target_environment,args.production_approval_id)
    except ValueError as exc: raise SystemExit(str(exc)) from exc
    try:
        apply_atomic_migration(requests,endpoint,token,migration,event_id=args.event_id,
            actor=args.actor,target_database_id=args.target_database_id,evidence=evidence,
            executed_at_utc=canonical_utc_seconds())
    except (AtomicMigrationError,ValueError) as exc: raise SystemExit(str(exc)) from exc
    print(f"APPLIED_ATOMIC_MIGRATION id={migration.migration_id} "
          f"version={migration.schema_version} statements={len(migration.statements)} "
          f"sha256={migration.artifact_sha256}")
    return 0


if __name__=="__main__": raise SystemExit(main())
