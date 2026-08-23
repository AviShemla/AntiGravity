"""Bounded, read-only Turso HTTPS pipeline adapter.

Only SELECT statements are accepted.  The adapter has no local database or
file fallback and never logs its bearer token or response body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import json as json_module

from model_lineage import LineageError


@dataclass(frozen=True)
class PipelineResult:
    columns: Sequence[str]
    rows: Sequence[Sequence[object]]


class _UrllibResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    def json(self):
        return json_module.loads(self._body.decode("utf-8"))


class _UrllibSession:
    """Minimal requests-compatible HTTPS client with no third-party dependency."""

    def post(self, url: str, *, headers: dict[str, str], json, timeout: float):
        body = json_module.dumps(json, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return _UrllibResponse(int(response.status), response.read())
        except HTTPError as exc:
            # Preserve only the status code. Never include a response body or
            # request headers because either may contain sensitive material.
            return _UrllibResponse(int(exc.code), b"{}")
        except URLError as exc:
            raise LineageError("Turso HTTPS connection failed.") from exc


def _encode_arg(value: object) -> dict[str, object]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise LineageError(f"Unsupported Turso argument type: {type(value).__name__}.")


def _decode_value(value: dict[str, Any]) -> object:
    kind = value.get("type")
    raw = value.get("value")
    if kind == "null":
        return None
    if kind == "integer":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "text":
        return str(raw)
    raise LineageError(f"Unsupported Turso result type: {kind!r}.")


class TursoReadPipeline:
    """A narrow libSQL-compatible ``execute`` surface for verified reads."""

    def __init__(self, endpoint: str, token: str, *, timeout_seconds: float = 10.0, session=None):
        if not endpoint.startswith("https://") or not endpoint.endswith("/v2/pipeline"):
            raise LineageError("Turso endpoint must be an HTTPS /v2/pipeline URL.")
        if not token:
            raise LineageError("Turso bearer token is required.")
        if timeout_seconds <= 0.0:
            raise LineageError("Turso timeout must be positive.")
        if session is None:
            try:
                import requests
            except ModuleNotFoundError:
                session = _UrllibSession()
            else:
                session = requests.Session()
        self._endpoint = endpoint
        self._token = token
        self._timeout = timeout_seconds
        self._session = session

    def execute(self, query: str, args: list[object]) -> PipelineResult:
        normalized = query.lstrip().upper()
        if not normalized.startswith("SELECT"):
            raise LineageError("Read pipeline accepts SELECT statements only.")
        response = self._session.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json={
                "requests": [
                    {
                        "type": "execute",
                        "stmt": {"sql": query, "args": [_encode_arg(arg) for arg in args]},
                    },
                    {"type": "close"},
                ]
            },
            timeout=self._timeout,
        )
        if response.status_code != 200:
            raise LineageError(f"Turso read failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
            item = payload["results"][0]
            if item.get("type") == "error":
                raise LineageError("Turso returned a statement error.")
            result = item["response"]["result"]
            columns = [column["name"] for column in result["cols"]]
            rows = [[_decode_value(value) for value in row] for row in result["rows"]]
        except LineageError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LineageError("Turso returned an invalid pipeline response.") from exc
        return PipelineResult(columns=columns, rows=rows)
