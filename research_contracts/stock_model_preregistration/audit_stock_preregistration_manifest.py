#!/usr/bin/env python3
"""Locally audit preregistration using the canonical perpetual-readback contract."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Mapping

try:
    from .current_baseline_readback_contract import (
        CurrentReadbackEvidence, ImmutableV4AuditLineage, NamedCount, OperationalBoundary,
        ReadbackContractError, ReadbackRequest, ReadbackStatus, VerifiedReadbackArtifact,
        audit_verified_readback)
    from .stock_model_preregistration import (
        BaselineReadbackProof, PreregistrationError, audit_preregistration_manifest)
    from .stock_model_preregistration_binding import (
        PINNED_EXECUTOR_COMMIT, PINNED_FINAL_MANIFEST_RAW_SHA256,
        PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256,
        PINNED_IMMUTABLE_AUDIT_RAW_SHA256, PINNED_MODEL_SLICE_SHA256,
        PINNED_UNIVERSE_SHA256, SESSION_SHA256, SNAPSHOT_ID, SNAPSHOT_SHA256)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from current_baseline_readback_contract import (
        CurrentReadbackEvidence, ImmutableV4AuditLineage, NamedCount, OperationalBoundary,
        ReadbackContractError, ReadbackRequest, ReadbackStatus, VerifiedReadbackArtifact,
        audit_verified_readback)
    from stock_model_preregistration import (
        BaselineReadbackProof, PreregistrationError, audit_preregistration_manifest)
    from stock_model_preregistration_binding import (
        PINNED_EXECUTOR_COMMIT, PINNED_FINAL_MANIFEST_RAW_SHA256,
        PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256,
        PINNED_IMMUTABLE_AUDIT_RAW_SHA256, PINNED_MODEL_SLICE_SHA256,
        PINNED_UNIVERSE_SHA256, SESSION_SHA256, SNAPSHOT_ID, SNAPSHOT_SHA256)
try:
    from .stock_preregistration_runtime import RuntimeBoundaryError, _utc, read_root_owned_0600_json
except ImportError:
    from stock_preregistration_runtime import RuntimeBoundaryError, _utc, read_root_owned_0600_json

_SHA = re.compile(r"[0-9a-f]{64}")
def _exact(v, keys, label):
    if type(v) is not dict or set(v) != set(keys): raise RuntimeBoundaryError(f"{label} schema differs")
    return v
def _sha(v, label):
    if type(v) is not str or not _SHA.fullmatch(v): raise RuntimeBoundaryError(f"{label} digest differs")
    return v
def _dt(v, label): return _utc(v, label) if type(v) is str else (_ for _ in ()).throw(RuntimeBoundaryError(f"{label} differs"))
def _counts(v, label):
    if type(v) is not list: raise RuntimeBoundaryError(f"{label} schema differs")
    out=[]
    for row in v:
        row=_exact(row,{"name","count"},label)
        if type(row["name"]) is not str or type(row["count"]) is not int: raise RuntimeBoundaryError(f"{label} type differs")
        out.append(NamedCount(row["name"],row["count"]))
    return tuple(out)

def parse_verified_readback(raw: Mapping[str,object]):
    raw=_exact(raw,{"artifact_id","contract_id","status","observed_at_utc","request_sha256","lineage","full_session_calendar_dates","model_session_dates","evidence","boundary"},"readback")
    lr=_exact(raw["lineage"],{"source_contract_id","snapshot_id","snapshot_sha256","universe_id","universe_sha256","full_session_calendar_sha256","model_session_dates_sha256","baseline_manifest_sha256","source_audit_artifact_sha256","embedded_audit_evidence_sha256","audit_envelope_sha256","source_code_git_sha","audit_completed_at_utc","audit_observed_at_utc"},"lineage")
    lineage=ImmutableV4AuditLineage(**{**lr,"audit_completed_at_utc":_dt(lr["audit_completed_at_utc"],"audit completion"),"audit_observed_at_utc":_dt(lr["audit_observed_at_utc"],"audit observation")})
    er=_exact(raw["evidence"],{"status","snapshot_id","snapshot_sha256","universe_id","universe_sha256","full_session_calendar_sha256","model_session_dates_sha256","baseline_manifest_sha256","source_audit_artifact_sha256","embedded_audit_evidence_sha256","audit_envelope_sha256","source_readback_artifact_sha256","source_readback_embedded_evidence_sha256","query_started_at_utc","query_completed_at_utc","source_readback_observed_at_utc","select_query_ids","coverage","side_effects","downstream_counts"},"evidence")
    if type(er["select_query_ids"]) is not list: raise RuntimeBoundaryError("query ID schema differs")
    evidence=CurrentReadbackEvidence(**{**er,"status":ReadbackStatus(er["status"]),"query_started_at_utc":_dt(er["query_started_at_utc"],"query start"),"query_completed_at_utc":_dt(er["query_completed_at_utc"],"query completion"),"source_readback_observed_at_utc":_dt(er["source_readback_observed_at_utc"],"source observation"),"select_query_ids":tuple(er["select_query_ids"]),"coverage":_counts(er["coverage"],"coverage"),"side_effects":_counts(er["side_effects"],"side effects"),"downstream_counts":_counts(er["downstream_counts"],"downstream")})
    br=_exact(raw["boundary"],{"fixture_only","evaluator_performed_io","database_writes","model_fit_performed","ready_state_available","model_fit_authorized"},"boundary")
    full,model=raw["full_session_calendar_dates"],raw["model_session_dates"]
    if type(full) is not list or type(model) is not list: raise RuntimeBoundaryError("calendar schema differs")
    artifact=VerifiedReadbackArtifact(raw["artifact_id"],raw["contract_id"],ReadbackStatus(raw["status"]),_dt(raw["observed_at_utc"],"artifact observation"),_sha(raw["request_sha256"],"request"),lineage,tuple(full),tuple(model),evidence,OperationalBoundary(**br))
    request=ReadbackRequest(lineage,tuple(full),tuple(model),evidence)
    audit_verified_readback(request,artifact,observed_at_utc=artifact.observed_at_utc)
    return request,artifact

def proof_from_verified_readback(raw):
    _,a=parse_verified_readback(raw); l,e=a.lineage,a.evidence
    pinned = {
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_sha256": SNAPSHOT_SHA256,
        "universe_sha256": PINNED_UNIVERSE_SHA256,
        "full_session_calendar_sha256": SESSION_SHA256,
        "model_session_dates_sha256": PINNED_MODEL_SLICE_SHA256,
        "baseline_manifest_sha256": PINNED_FINAL_MANIFEST_RAW_SHA256,
        "source_audit_artifact_sha256": PINNED_IMMUTABLE_AUDIT_RAW_SHA256,
        "embedded_audit_evidence_sha256": PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256,
        "source_code_git_sha": PINNED_EXECUTOR_COMMIT,
    }
    if any(getattr(l, name) != value for name, value in pinned.items()):
        raise RuntimeBoundaryError("readback source differs from pinned v4 baseline")
    c={x.name:x.count for x in e.coverage}; s={x.name:x.count for x in e.side_effects}; d={x.name:x.count for x in e.downstream_counts}
    return BaselineReadbackProof("VERIFIED",l.baseline_manifest_sha256,l.snapshot_id,l.snapshot_sha256,l.universe_id,l.universe_sha256,l.full_session_calendar_sha256,l.model_session_dates_sha256,l.source_audit_artifact_sha256,l.embedded_audit_evidence_sha256,l.audit_envelope_sha256,e.source_readback_artifact_sha256,e.source_readback_embedded_evidence_sha256,e.source_readback_observed_at_utc,e.source_readback_observed_at_utc,c["tickers"],c["folds"],c["oos_observations"],s,d)

def proof_for_manifest(raw,manifest):
    proof=proof_from_verified_readback(raw); ml=manifest["lineage"]
    names=("snapshot_id","snapshot_sha256","universe_id","universe_sha256","full_session_calendar_sha256","model_session_dates_sha256","baseline_manifest_sha256","source_audit_artifact_sha256","embedded_audit_evidence_sha256")
    if (any(getattr(proof,n)!=ml[n] for n in names) or
            proof.baseline_audit_sha256!=ml["baseline_audit_sha256"]):
        raise RuntimeBoundaryError("readback lineage differs")
    return proof

def audit_persisted_manifest(*,manifest,manifest_raw_sha256,current_readback,current_readback_raw_sha256,observed_at_utc):
    _sha(manifest_raw_sha256,"manifest raw"); _sha(current_readback_raw_sha256,"readback artifact raw")
    proof=proof_for_manifest(current_readback,manifest)
    audit_preregistration_manifest(manifest,observed_at_utc=observed_at_utc,current_readback=proof)
    return {"status":"VERIFIED_FIXTURE_ONLY","manifest_raw_sha256":manifest_raw_sha256,"checkpoint_identity_sha256":manifest["checkpoint_identity_sha256"],"current_readback_artifact_raw_sha256":current_readback_raw_sha256,"source_readback_raw_sha256":proof.source_readback_artifact_sha256,"source_readback_embedded_sha256":proof.source_readback_embedded_evidence_sha256,"observed_at_utc":observed_at_utc.astimezone(timezone.utc).isoformat(),"model_fit_authorized":False}

def audit_from_files(*,manifest_path,source_readback_path,current_readback_path,
                     final_manifest_path,immutable_audit_path,observed_at_utc):
    m,ms=read_root_owned_0600_json(manifest_path,"persisted preregistration")
    s,ss=read_root_owned_0600_json(source_readback_path,"readback source evidence")
    r,rs=read_root_owned_0600_json(current_readback_path,"current readback")
    f,fs=read_root_owned_0600_json(final_manifest_path,"final manifest")
    a,aas=read_root_owned_0600_json(immutable_audit_path,"immutable audit")
    try:
        from .verify_current_baseline_readback import verify
    except ImportError:
        from verify_current_baseline_readback import verify
    verify(source=s,source_raw_sha256=ss,artifact=r,artifact_raw_sha256=rs,
           final_manifest=f,final_raw_sha256=fs,immutable_audit=a,
           immutable_audit_raw_sha256=aas,
           proposed_model_git_commit=m["lineage"]["code_git_commit"])
    return audit_persisted_manifest(manifest=m,manifest_raw_sha256=ms,current_readback=r,current_readback_raw_sha256=rs,observed_at_utc=observed_at_utc)
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--current-readback-source",type=Path,required=True); p.add_argument("--current-readback",type=Path,required=True); p.add_argument("--final-manifest",type=Path,required=True); p.add_argument("--immutable-audit",type=Path,required=True); p.add_argument("--observed-at-utc",required=True); a=p.parse_args(argv)
    try: out=audit_from_files(manifest_path=a.manifest,source_readback_path=a.current_readback_source,current_readback_path=a.current_readback,final_manifest_path=a.final_manifest,immutable_audit_path=a.immutable_audit,observed_at_utc=_utc(a.observed_at_utc,"audit observation"))
    except (RuntimeBoundaryError,PreregistrationError,ReadbackContractError,ValueError) as exc: p.error(str(exc))
    print(json.dumps(out,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
