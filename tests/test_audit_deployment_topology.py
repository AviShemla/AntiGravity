import unittest

from scripts.audit_deployment_topology import evaluate_topology


def evidence():
    return {
        "cwd": "/repo",
        "canonical_worktree": "/repo",
        "git_root": "/repo",
        "origin": "git@example/repo.git",
        "canonical_origin": "git@example/repo.git",
        "runtime_exists": True,
        "runtime_has_git": False,
        "python_runtime_exists": True,
        "unit_path_failures": [],
        "frozen_unit_failures": [],
        "world_writable_runtime_files": [],
        "runtime_hash_mismatches": ["legacy.py"],
    }


class EvaluateTopologyTests(unittest.TestCase):
    def test_code_preflight_allows_reported_runtime_drift(self):
        self.assertTrue(all(evaluate_topology(evidence(), "code").values()))

    def test_deploy_preflight_blocks_runtime_drift(self):
        checks = evaluate_topology(evidence(), "deploy")
        self.assertFalse(checks["runtime_matches_canonical_commit"])

    def test_wrong_worktree_fails(self):
        data = evidence()
        data["cwd"] = "/opt/antigravity"
        self.assertFalse(evaluate_topology(data, "code")["executed_from_canonical_worktree"])

    def test_world_writable_runtime_fails(self):
        data = evidence()
        data["world_writable_runtime_files"] = ["vix_monitor.py"]
        self.assertFalse(evaluate_topology(data, "audit")["runtime_files_not_world_writable"])


if __name__ == "__main__":
    unittest.main()
