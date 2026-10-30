import ast
import unittest
from dataclasses import replace
from pathlib import Path

from model_lineage import LineageError
from oracle_research_dataset_turso_adapter import (
    _FREEZE_MUTATIONS,
    _SELECT_SQL,
    _STAGE_MUTATIONS,
    AtomicMigrationError,
    InjectedTursoImmediateTransactionRunner,
    OracleResearchProductionAuthorization,
    _sql,
)


ROOT = Path(__file__).resolve().parents[1]


def ok_payload(*, baton=None, columns=(), rows=(), affected=0):
    result = {
        "cols": [{"name": column} for column in columns],
        "rows": [
            [
                {"type": "null"} if value is None else
                {"type": "integer", "value": str(value)} if isinstance(value, int) else
                {"type": "float", "value": value} if isinstance(value, float) else
                {"type": "text", "value": value}
                for value in row
            ]
            for row in rows
        ],
        "affected_row_count": affected,
    }
    payload = {"results": [{"type": "ok", "response": {"result": result}}]}
    if baton is not None:
        payload["baton"] = baton
    return payload


class Transport:
    def __init__(self):
        self.calls = []
        self.counter = 0
        self.fail_sql = None
        self.extra_result_sql = None
        self.rollback_fails = False

    def send(self, requests, *, baton=None):
        self.calls.append((requests, baton))
        sql = requests[0]["stmt"]["sql"]
        normalized = _sql(sql)
        if normalized == "ROLLBACK" and self.rollback_fails:
            raise RuntimeError("rollback unavailable")
        if normalized == self.fail_sql:
            raise RuntimeError("injected transport failure")
        self.counter += 1
        next_baton = f"baton-{self.counter}"
        if normalized in {"BEGIN IMMEDIATE", "ROLLBACK", "COMMIT"}:
            payload = ok_payload(baton=next_baton if normalized == "BEGIN IMMEDIATE" else None)
        elif normalized in _SELECT_SQL:
            payload = ok_payload(baton=next_baton, columns=("value",), rows=((1,),))
        else:
            payload = ok_payload(baton=next_baton, affected=1)
        if normalized == self.extra_result_sql:
            payload["results"].append(payload["results"][0])
        return payload


AUTH = OracleResearchProductionAuthorization(
    contract_id="oracle-research-dataset-application-freeze-v1",
    contract_sha256="854a4d17e66a4f00a7192646feb2274d517ad731026740796ba2a52aa61cc447",
    target_database_id="theoracle-avishe",
    schema_application_gate_satisfied=True,
    schema_application_approval_id="schema-approval-1",
    schema_post_audit_evidence_sha256="b" * 64,
    dataset_freeze_gate_satisfied=True,
    dataset_freeze_approval_id="freeze-approval-1",
    content_audit_evidence_sha256="b0b775d6aa4ff37faacb3987a65019724b358cdc86d5aa5967aea927c1401df3",
    authorized_dataset_version_id="dataset-1",
    authorized_freeze_event_id="freeze-approval-1",
)


class TursoAdapterTests(unittest.TestCase):
    def test_begin_read_commit_noop_is_idempotent_and_exact(self):
        transport = Transport()
        runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)
        select = next(iter(_SELECT_SQL))
        result = runner.run_immediate(
            "stage:dataset-1", lambda tx: (tx.execute(select, ["id"]), "NOOP")[1]
        )
        self.assertEqual(result, "NOOP")
        self.assertEqual(
            [_sql(call[0][0]["stmt"]["sql"]) for call in transport.calls],
            ["BEGIN IMMEDIATE", select, "COMMIT"],
        )
        self.assertIsNone(transport.calls[0][1])
        self.assertEqual(transport.calls[1][1], "baton-1")
        self.assertEqual(transport.calls[2][1], "baton-2")

    def test_exact_stage_and_freeze_sequences_commit(self):
        for operation, statements in (
            ("stage:dataset-1", _STAGE_MUTATIONS),
            ("freeze:dataset-1:freeze-approval-1", _FREEZE_MUTATIONS),
        ):
            with self.subTest(operation=operation):
                transport = Transport()
                runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)

                def callback(tx):
                    return [tx.execute_mutation(sql, [None] * sql.count("?")) for sql in statements]

                self.assertEqual(runner.run_immediate(operation, callback), [1, 1])
                sqls = [_sql(call[0][0]["stmt"]["sql"]) for call in transport.calls]
                self.assertEqual(sqls, ["BEGIN IMMEDIATE", *statements, "COMMIT"])

    def test_partial_sequence_and_transport_failure_roll_back(self):
        transport = Transport()
        runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)
        with self.assertRaisesRegex(AtomicMigrationError, "partial mutation"):
            runner.run_immediate(
                "stage:dataset-1",
                lambda tx: tx.execute_mutation(
                    _STAGE_MUTATIONS[0], [None] * _STAGE_MUTATIONS[0].count("?")
                ),
            )
        self.assertEqual(_sql(transport.calls[-1][0][0]["stmt"]["sql"]), "ROLLBACK")

        transport = Transport()
        transport.fail_sql = _STAGE_MUTATIONS[1]
        runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)
        with self.assertRaises(RuntimeError):
            runner.run_immediate(
                "stage:dataset-1",
                lambda tx: [
                    tx.execute_mutation(sql, [None] * sql.count("?"))
                    for sql in _STAGE_MUTATIONS
                ],
            )
        self.assertEqual(_sql(transport.calls[-1][0][0]["stmt"]["sql"]), "ROLLBACK")

    def test_ambiguous_failure_when_rollback_cannot_be_verified(self):
        transport = Transport()
        transport.fail_sql = "COMMIT"
        transport.rollback_fails = True
        runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)
        with self.assertRaisesRegex(AtomicMigrationError, "ambiguous"):
            runner.run_immediate("stage:dataset-1", lambda tx: "noop")

    def test_result_cardinality_and_affected_rows_fail_closed(self):
        transport = Transport()
        transport.extra_result_sql = next(iter(_SELECT_SQL))
        runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)
        with self.assertRaisesRegex(AtomicMigrationError, "cardinality"):
            runner.run_immediate(
                "stage:dataset-1", lambda tx: tx.execute(transport.extra_result_sql, ["id"])
            )
        self.assertEqual(_sql(transport.calls[-1][0][0]["stmt"]["sql"]), "ROLLBACK")

        class MissingResult(Transport):
            def send(self, requests, *, baton=None):
                payload = super().send(requests, baton=baton)
                if _sql(requests[0]["stmt"]["sql"]) in _SELECT_SQL:
                    payload["results"] = []
                return payload

        with self.assertRaisesRegex(AtomicMigrationError, "incomplete"):
            InjectedTursoImmediateTransactionRunner(MissingResult(), AUTH).run_immediate(
                "stage:dataset-1", lambda tx: tx.execute(next(iter(_SELECT_SQL)), ["id"])
            )

        class BadAffected(Transport):
            def send(self, requests, *, baton=None):
                payload = super().send(requests, baton=baton)
                if _sql(requests[0]["stmt"]["sql"]) == _STAGE_MUTATIONS[0]:
                    payload["results"][0]["response"]["result"]["affected_row_count"] = "1.0"
                return payload

        with self.assertRaisesRegex(AtomicMigrationError, "affected-row"):
            InjectedTursoImmediateTransactionRunner(BadAffected(), AUTH).run_immediate(
                "stage:dataset-1",
                lambda tx: tx.execute_mutation(
                    _STAGE_MUTATIONS[0], [None] * _STAGE_MUTATIONS[0].count("?")
                ),
            )

    def test_undeclared_sql_and_wrong_operation_never_execute_mutation(self):
        transport = Transport()
        runner = InjectedTursoImmediateTransactionRunner(transport, AUTH)
        with self.assertRaisesRegex(LineageError, "approved identity"):
            runner.run_immediate("stage:other", lambda tx: None)
        self.assertEqual(transport.calls, [])
        with self.assertRaisesRegex(LineageError, "undeclared mutation"):
            runner.run_immediate(
                "stage:dataset-1",
                lambda tx: tx.execute_mutation(
                    "INSERT INTO model_runs VALUES (?)", ["forbidden"]
                ),
            )
        sqls = [_sql(call[0][0]["stmt"]["sql"]) for call in transport.calls]
        self.assertEqual(sqls, ["BEGIN IMMEDIATE", "ROLLBACK"])

    def test_authorization_gates_distinct_approvals_and_zero_outputs_are_mandatory(self):
        invalid = (
            replace(AUTH, schema_application_gate_satisfied=False),
            replace(AUTH, dataset_freeze_gate_satisfied=False),
            replace(AUTH, schema_application_approval_id="freeze-approval-1"),
            replace(AUTH, dataset_freeze_approval_id="other"),
            replace(AUTH, contract_sha256="bad"),
            replace(AUTH, contract_sha256="d" * 64),
            replace(AUTH, content_audit_evidence_sha256="e" * 64),
            replace(AUTH, target_database_id="other"),
            replace(AUTH, model_run_count=1),
            replace(AUTH, model_scorecard_count=1),
            replace(AUTH, etf_prior_count=1),
            replace(AUTH, recommendation_count=1),
            replace(AUTH, order_count=1),
        )
        for auth in invalid:
            with self.subTest(auth=auth):
                transport = Transport()
                with self.assertRaises(LineageError):
                    InjectedTursoImmediateTransactionRunner(transport, auth)
                self.assertEqual(transport.calls, [])

    def test_adapter_sql_allowlists_exactly_match_writer_and_readback_literals(self):
        selects = set()
        mutations = set()
        for filename in ("oracle_research_dataset_writer.py", "oracle_research_dataset.py"):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"execute", "execute_mutation"} or not node.args:
                    continue
                try:
                    sql = ast.literal_eval(node.args[0])
                except (ValueError, TypeError):
                    continue
                if node.func.attr == "execute_mutation":
                    mutations.add(_sql(sql))
                else:
                    selects.add(_sql(sql))
        self.assertEqual(selects, set(_SELECT_SQL))
        self.assertEqual(mutations, set(_STAGE_MUTATIONS + _FREEZE_MUTATIONS))


if __name__ == "__main__":
    unittest.main()
