"""Run the existing simple-baseline evaluator against a frozen W2 selector."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

from oracle_w2_selector_reader import load_selector, read_daily_returns, read_sessions


class W3BridgeError(RuntimeError):
    pass


def load_existing_evaluator(module_path: Path) -> Callable[..., dict[str, Any]]:
    """Load only the existing pure baseline evaluator from its reviewed source file."""
    module_path = module_path.resolve()
    specification = importlib.util.spec_from_file_location("oracle_existing_baselines", module_path)
    if specification is None or specification.loader is None:
        raise W3BridgeError("existing baseline module cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    evaluator = getattr(module, "evaluate_ticker", None)
    if not callable(evaluator):
        raise W3BridgeError("existing baseline evaluator is unavailable")
    return evaluator


def evaluate_frozen_universe(
    db: Any,
    selector_path: Path,
    evaluator: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate all governed members with unchanged baseline calculations.

    Results remain in memory. Artifact persistence belongs to the existing W3
    checkpoint/audit contract and is intentionally not introduced here.
    """
    bound = load_selector(selector_path)
    sessions = read_sessions(db, bound)
    if not sessions:
        raise W3BridgeError("W2 selector resolved no sessions")
    results: dict[str, dict[str, Any]] = {}
    for ticker in sorted(bound["tickers"]):
        rows = [
            {"date": date, "daily_return_pct": daily_return}
            for date, daily_return in read_daily_returns(db, bound, ticker)
        ]
        results[ticker] = evaluator(ticker, sessions, rows)
    return {
        "selector_identity_sha256": bound["identity_sha256"],
        "as_of_session_date": bound["selector"]["as_of_session_date"],
        "instrument_count": len(results),
        "results": results,
    }
