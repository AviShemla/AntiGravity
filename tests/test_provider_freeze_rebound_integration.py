"""Canonical-path verification for the provider freeze rebound package."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(os.environ.get("CODEX_REBOUND_CANONICAL_ROOT", Path(__file__).resolve().parents[1])).resolve()
MAP_PATH = ROOT / "governance/provider_freeze_rebound/canonical_integration_map.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def integration_map():
    return load(MAP_PATH)


def test_inventory_paths_hashes_modes_and_create_only_policy():
    manifest = integration_map()
    destinations = []
    for item in manifest["files"]:
        destination = ROOT / item["destination"]
        destinations.append(item["destination"])
        assert destination.is_file()
        assert sha(destination) == item["sha256"]
        assert item["mode"] == "0644"
        assert item["overwrite_policy"] == "CREATE_ONLY"
    assert len(destinations) == len(set(destinations))
    assert "governance/oracle_research_dataset_application_contract_v2.json" not in destinations


def test_old_v2_contract_is_preserved_and_new_contract_is_side_by_side():
    manifest = integration_map()
    requirement = manifest["preexisting_requirements"]["application_contract_v2"]
    old_path = ROOT / requirement["path"]
    new_path = ROOT / "governance/corrected_application_contract_v2.json"
    assert sha(old_path) == requirement["sha256"] == "da2a83dd7e83ce5d8e93fe4381b0c53e5f96dc9f09b2c8640ffca70ddc4525a6"
    old, new = load(old_path), load(new_path)
    new_descriptor = new["artifacts"]["freeze_manifest_builder"]
    old["artifacts"]["freeze_manifest_builder"] = new_descriptor
    assert old == new
    assert new_descriptor["path"] == "corrected_freeze_manifest.py"
    assert new_descriptor["sha256"] == sha(ROOT / "corrected_freeze_manifest.py")


def test_old_and_new_envelope_evidence_are_both_immutable_and_single_leaf_diff():
    old_path = ROOT / "docs/evidence/provider_freeze_rebound/superseded_envelope_665fe03c.json"
    new_path = ROOT / "governance/authorization_envelopes/oracle-production-envelope-456179cd/envelope.json"
    assert sha(old_path) == "665fe03c889a96ec095e0b51ff69697b94e84de314d43af6a7c2fcfa880a796e"
    assert sha(new_path) == "456179cd172ce882f304b461d47f3e24d91e94b180d5dbf29e853f0d1f70480e"
    old, new = load(old_path), load(new_path)
    old["application_contract"]["sha256"] = new["application_contract"]["sha256"]
    assert old == new
    assert new["adapter_release"]["manifest_sha256"] == "4e278ca52a838551c51b9da3b0afb7bfb3c8c5a0b16459228a53bd4c46899c05"
    assert new["target_database_id"] == "theoracle-avishe"
    assert new["allowed_operations"] == ["STAGE_RESEARCH_DATASET", "FREEZE_RESEARCH_DATASET"]


def test_launcher_pins_new_envelope_dataset_manifest_provider_and_event():
    launcher = ROOT / "scripts/oracle_production_schema_freeze_provider_rebound.py"
    source = launcher.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant):
                constants[node.targets[0].id] = node.value.value
    assert constants["ENVELOPE_SHA256"] == "456179cd172ce882f304b461d47f3e24d91e94b180d5dbf29e853f0d1f70480e"
    assert constants["DATASET_VERSION_ID"] == "oracle-research-20260825-843955ade32387172c33e5c3eec167dc"
    assert constants["FREEZE_MANIFEST_SHA256"] == "d5f6c520d3bd5db1c4927133037a80611f18baabdc46b011a96d85ae79604c57"
    assert constants["PROVIDER_SHA256"] == "d0ae4b277bd63f8668fdb6898961bbb0b46f153c35fcb6bc15e8d1d616c23a1d"
    assert constants["FREEZE_APPROVAL_ID"] == "avi-freeze-oracle-rd-20260827-d0ae4b277bd6"


def test_old_runtime_authorization_is_rejected_by_new_envelope_before_operation_use():
    auth_path = ROOT / "docs/evidence/provider_freeze_rebound/superseded_runtime_authorization.json"
    old_authorization = load(auth_path)
    assert old_authorization["envelope_sha256"] == "665fe03c889a96ec095e0b51ff69697b94e84de314d43af6a7c2fcfa880a796e"
    module_path = ROOT / "oracle_production_authorization_envelope.py"
    spec = importlib.util.spec_from_file_location("rebound_auth_gate", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    new_envelope = load(ROOT / "governance/authorization_envelopes/oracle-production-envelope-456179cd/envelope.json")
    with mock.patch.object(module, "verify_envelope_artifacts", return_value="456179cd172ce882f304b461d47f3e24d91e94b180d5dbf29e853f0d1f70480e") as leaf_gate:
        with pytest.raises(module.AuthorizationEnvelopeError, match="another envelope"):
            module.validate_runtime_authorization(
                new_envelope,
                old_authorization,
                expected_envelope_sha256="456179cd172ce882f304b461d47f3e24d91e94b180d5dbf29e853f0d1f70480e",
                application_contract_path=ROOT / "governance/corrected_application_contract_v2.json",
                adapter_release_root=ROOT,
                operation_id="stage:oracle-research-20260825-843955ade32387172c33e5c3eec167dc",
                observed_at_utc=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
            )
    leaf_gate.assert_called_once()


def test_new_runtime_authorization_remains_a_non_executable_template():
    template = load(ROOT / "governance/runtime_authorization_templates/provider_freeze_rebound.json")
    proposed = template["proposed_runtime_authorization"]
    assert template["template_status"] == "AWAITING_AVI_APPROVAL/NOT_EXECUTABLE"
    assert proposed["dataset_freeze_gate_satisfied"] is False
    assert all(proposed[key] is None for key in (
        "authorization_id", "authorized_by", "authorized_at_utc", "expires_at_utc"
    ))
    assert set(template["blockers"]) == {
        "AVI_FREEZE_APPROVAL_NOT_RECORDED", "AUTHORIZATION_TIMESTAMPS_NOT_ISSUED"
    }


def test_bridge_and_safety_invariants_are_explicit():
    manifest = integration_map()
    assert manifest["required_external_evidence"] == {
        "provider_bridge_evidence_sha256": "34ad27e1defdf1f5333c8c7d044945383f60a826b4374ab6734af05dfcca37a3",
        "provider_canonical_sha256": "d0ae4b277bd63f8668fdb6898961bbb0b46f153c35fcb6bc15e8d1d616c23a1d",
        "provider_legacy_sha256": "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a",
    }
    assert manifest["execution_state"] == "AWAITING_AVI_APPROVAL/NOT_EXECUTABLE"
    assert set(manifest["forbidden_actions"]) >= {
        "PRODUCTION_WRITE", "SCHEMA_APPLY", "DATASET_STAGE", "DATASET_FREEZE", "TRADING"
    }
