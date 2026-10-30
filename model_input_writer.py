"""Narrow administrative writes for model-input snapshot governance."""

from __future__ import annotations

from model_lineage import LineageError
from turso_read_pipeline import _encode_arg


class ModelInputSnapshotAdmin:
    def __init__(self, endpoint: str, token: str, *, timeout_seconds: float = 10.0, session=None):
        if not endpoint.startswith("https://") or not endpoint.endswith("/v2/pipeline"):
            raise LineageError("Turso endpoint must be an HTTPS /v2/pipeline URL.")
        if not token or timeout_seconds <= 0:
            raise LineageError("Valid Turso credentials and timeout are required.")
        if session is None:
            import requests
            session = requests.Session()
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout_seconds
        self.session = session

    def reject_staging_snapshot(self, snapshot_id: str, reason: str) -> None:
        if not snapshot_id or not reason.strip():
            raise LineageError("Snapshot rejection requires an identifier and evidence reason.")
        response = self.session.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json={
                "requests": [
                    {
                        "type": "execute",
                        "stmt": {
                            "sql": "UPDATE model_input_snapshots SET status='REJECTED', "
                                   "validation_notes=? WHERE snapshot_id=? AND status='STAGING'",
                            "args": [_encode_arg(reason.strip()), _encode_arg(snapshot_id)],
                        },
                    },
                    {"type": "close"},
                ]
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise LineageError(f"Snapshot rejection failed with HTTP {response.status_code}.")
        try:
            item = response.json()["results"][0]
            affected = int(item["response"]["result"].get("affected_row_count", 0))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LineageError("Turso returned an invalid snapshot rejection response.") from exc
        if item.get("type") != "ok" or affected != 1:
            raise LineageError("Snapshot rejection did not update exactly one STAGING row.")

    def validate_staging_snapshot(self, snapshot_id: str, evidence: str) -> None:
        if not snapshot_id or not evidence.strip():
            raise LineageError("Snapshot validation requires an identifier and QA evidence.")
        response = self.session.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json={
                "requests": [
                    {
                        "type": "execute",
                        "stmt": {
                            "sql": "UPDATE model_input_snapshots SET status='VALIDATED', "
                                   "validation_notes=? WHERE snapshot_id=? AND status='STAGING'",
                            "args": [_encode_arg(evidence.strip()), _encode_arg(snapshot_id)],
                        },
                    },
                    {"type": "close"},
                ]
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise LineageError(f"Snapshot validation failed with HTTP {response.status_code}.")
        try:
            item = response.json()["results"][0]
            affected = int(item["response"]["result"].get("affected_row_count", 0))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LineageError("Turso returned an invalid snapshot validation response.") from exc
        if item.get("type") != "ok" or affected != 1:
            raise LineageError("Snapshot validation did not update exactly one STAGING row.")
