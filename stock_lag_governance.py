"""Owner-approved governance for stock predictive lag searches.

This module defines the currently approved research envelope.  It does not run
models, select features, access data, write evidence, or authorize trading.
Changing the envelope requires a reviewed code change after the scheduled
research reassessment.
"""

from __future__ import annotations

from dataclasses import dataclass

from model_lineage import LineageError


INITIAL_STOCK_LAG_CONTRACT_ID = "stock-lag-horizon-v1-20260824"
INITIAL_MAX_LAG_SESSIONS = 7
INITIAL_MIN_CHAIN_DEPTH = 1
INITIAL_MAX_CHAIN_DEPTH = 5
HORIZON_REVIEW_INTERVAL_SESSIONS = 63


@dataclass(frozen=True)
class StockLagGovernance:
    contract_id: str = INITIAL_STOCK_LAG_CONTRACT_ID
    minimum_chain_depth: int = INITIAL_MIN_CHAIN_DEPTH
    maximum_chain_depth: int = INITIAL_MAX_CHAIN_DEPTH
    approved_max_lag_sessions: int = INITIAL_MAX_LAG_SESSIONS
    review_interval_completed_sessions: int = HORIZON_REVIEW_INTERVAL_SESSIONS

    def validate_search(
        self,
        *,
        minimum_depth: int,
        maximum_depth: int,
        candidate_lags: tuple[int, ...],
        purge_sessions: int,
    ) -> None:
        if not self.contract_id.strip():
            raise LineageError("Lag-horizon governance contract ID is blank.")
        if not (
            self.minimum_chain_depth
            <= minimum_depth
            <= maximum_depth
            <= self.maximum_chain_depth
        ):
            raise LineageError(
                "Requested chain-depth range exceeds the approved lag-search contract."
            )
        if not candidate_lags:
            raise LineageError("At least one preregistered candidate lag is required.")
        if any(not isinstance(lag, int) or lag <= 0 for lag in candidate_lags):
            raise LineageError("Candidate lags must be positive integer session offsets.")
        if len(set(candidate_lags)) != len(candidate_lags):
            raise LineageError("Candidate lags must be unique.")
        if max(candidate_lags) > self.approved_max_lag_sessions:
            raise LineageError(
                "Candidate lag exceeds the currently approved maximum horizon "
                f"of {self.approved_max_lag_sessions} sessions."
            )
        if purge_sessions < max(candidate_lags):
            raise LineageError("Purge/embargo must cover the maximum candidate lag.")

    def horizon_review_due(self, completed_sessions_since_review: int) -> bool:
        if completed_sessions_since_review < 0:
            raise LineageError("Completed sessions since review cannot be negative.")
        return completed_sessions_since_review >= self.review_interval_completed_sessions


INITIAL_STOCK_LAG_GOVERNANCE = StockLagGovernance()
