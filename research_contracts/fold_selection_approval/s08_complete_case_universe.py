"""Pure presence-only complete-case universe audit for the S08 panel.

No price magnitude enters eligibility or any digest.  ``adjusted_close`` is
used only to prove that an observed key has a finite, strictly positive value.
The module performs no I/O, persistence, selection, model, or downstream work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
import re


CONTRACT_ID = "codex-oracle-s08-complete-case-universe-v1"
PRESENCE_MASK_CONTRACT = "s08-474-ticker-417-date-presence-mask-v1"
EXPECTED_UPSTREAM_TICKERS = 474
EXPECTED_REQUIRED_DATES = 417
EXPECTED_ELIGIBLE_TICKERS = 472
EXPECTED_EXCLUSION_COUNTS = {"FISV": 416, "SNDK": 358}
_TICKER = re.compile(r"[A-Z0-9.^-]{1,24}")


class CompleteCaseUniverseError(ValueError):
    pass


@dataclass(frozen=True)
class ExclusionEvidence:
    ticker: str
    observed_session_count: int
    required_session_count: int
    missing_session_dates: tuple[str, ...]
    reason: str = "INCOMPLETE_REQUIRED_417_SESSION_PRESENCE"


@dataclass(frozen=True)
class CompleteCaseUniverseAudit:
    contract_id: str
    upstream_tickers: tuple[str, ...]
    required_session_dates: tuple[str, ...]
    eligible_tickers: tuple[str, ...]
    exclusions: tuple[ExclusionEvidence, ...]
    upstream_universe_sha256: str
    required_dates_sha256: str
    presence_mask_bytes: bytes
    presence_mask_sha256: str
    eligible_universe_sha256: str
    exclusion_evidence_sha256: str
    observed_row_count: int
    execution_authorized: bool = False
    database_writes: int = 0
    selections: int = 0
    model_runs: int = 0
    downstream_outputs: int = 0
    imputation_count: int = 0


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _date_text(value: object) -> str:
    if isinstance(value, datetime):
        raise CompleteCaseUniverseError("required/row session must be a date, not timestamp")
    if isinstance(value, date):
        return value.isoformat()
    if type(value) is str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise CompleteCaseUniverseError("session is not a canonical ISO date") from exc
        if parsed.isoformat() == value:
            return value
    raise CompleteCaseUniverseError("session is not a canonical ISO date")


def audit_complete_case_universe(
    *,
    upstream_tickers: tuple[str, ...],
    required_session_dates: tuple[str, ...],
    canonical_presence_rows: tuple[tuple[object, object, object], ...],
) -> CompleteCaseUniverseAudit:
    if (type(upstream_tickers) is not tuple
            or len(upstream_tickers) != EXPECTED_UPSTREAM_TICKERS
            or tuple(sorted(set(upstream_tickers))) != upstream_tickers
            or any(type(ticker) is not str or not _TICKER.fullmatch(ticker)
                   for ticker in upstream_tickers)):
        raise CompleteCaseUniverseError("upstream universe must be exact sorted unique 474")
    if not set(EXPECTED_EXCLUSION_COUNTS).issubset(upstream_tickers):
        raise CompleteCaseUniverseError("expected excluded tickers are absent upstream")
    if type(required_session_dates) is not tuple or len(required_session_dates) != EXPECTED_REQUIRED_DATES:
        raise CompleteCaseUniverseError("required calendar must contain exactly 417 sessions")
    normalized_dates = tuple(_date_text(item) for item in required_session_dates)
    if normalized_dates != required_session_dates or tuple(sorted(set(normalized_dates))) != normalized_dates:
        raise CompleteCaseUniverseError("required calendar is unordered, duplicated, or noncanonical")
    if type(canonical_presence_rows) is not tuple:
        raise CompleteCaseUniverseError("canonical presence rows must be an immutable tuple")

    ticker_set = set(upstream_tickers)
    date_set = set(required_session_dates)
    present: dict[str, set[str]] = {ticker: set() for ticker in upstream_tickers}
    previous: tuple[str, str] | None = None
    for raw in canonical_presence_rows:
        if type(raw) is not tuple or len(raw) != 3:
            raise CompleteCaseUniverseError("presence row must be exact (ticker,date,adjusted_close)")
        ticker, raw_session, adjusted_close = raw
        if type(ticker) is not str or ticker not in ticker_set:
            raise CompleteCaseUniverseError("presence row has an extra or malformed ticker")
        session = _date_text(raw_session)
        if session not in date_set:
            raise CompleteCaseUniverseError("presence row has an extra session")
        key = (ticker, session)
        if previous is not None and key <= previous:
            raise CompleteCaseUniverseError("presence rows are duplicated or not ticker/date ordered")
        previous = key
        if isinstance(adjusted_close, bool) or not isinstance(adjusted_close, (int, float)):
            raise CompleteCaseUniverseError("observed adjusted_close is not numeric")
        number = float(adjusted_close)
        if not math.isfinite(number) or number <= 0:
            raise CompleteCaseUniverseError("observed adjusted_close is nonfinite/nonpositive")
        present[ticker].add(session)

    counts = {ticker: len(values) for ticker, values in present.items()}
    observed_exclusions = {ticker: count for ticker, count in counts.items()
                           if count != EXPECTED_REQUIRED_DATES}
    if observed_exclusions != EXPECTED_EXCLUSION_COUNTS:
        raise CompleteCaseUniverseError("complete-case exclusions/counts differ from FISV=416,SNDK=358")
    eligible = tuple(ticker for ticker in upstream_tickers
                     if ticker not in EXPECTED_EXCLUSION_COUNTS)
    if len(eligible) != EXPECTED_ELIGIBLE_TICKERS or any(counts[ticker] != 417 for ticker in eligible):
        raise CompleteCaseUniverseError("eligible 472-ticker complete-case coverage differs")
    exclusions = tuple(ExclusionEvidence(
        ticker=ticker,
        observed_session_count=counts[ticker],
        required_session_count=EXPECTED_REQUIRED_DATES,
        missing_session_dates=tuple(session for session in required_session_dates
                                    if session not in present[ticker]),
    ) for ticker in sorted(EXPECTED_EXCLUSION_COUNTS))
    exclusion_payload = [{
        "ticker": item.ticker,
        "observed_session_count": item.observed_session_count,
        "required_session_count": item.required_session_count,
        "missing_session_dates": list(item.missing_session_dates),
        "reason": item.reason,
    } for item in exclusions]
    presence_mask_bytes = _canonical_bytes({
        "contract": PRESENCE_MASK_CONTRACT,
        "session_dates": list(required_session_dates),
        "ticker_order": list(upstream_tickers),
        "presence_rows": [
            "".join("1" if session in present[ticker] else "0"
                    for session in required_session_dates)
            for ticker in upstream_tickers
        ],
    })
    return CompleteCaseUniverseAudit(
        contract_id=CONTRACT_ID,
        upstream_tickers=upstream_tickers,
        required_session_dates=required_session_dates,
        eligible_tickers=eligible,
        exclusions=exclusions,
        upstream_universe_sha256=_sha(list(upstream_tickers)),
        required_dates_sha256=_sha(list(required_session_dates)),
        presence_mask_bytes=presence_mask_bytes,
        presence_mask_sha256=hashlib.sha256(presence_mask_bytes).hexdigest(),
        eligible_universe_sha256=_sha(list(eligible)),
        exclusion_evidence_sha256=_sha(exclusion_payload),
        observed_row_count=len(canonical_presence_rows),
    )
