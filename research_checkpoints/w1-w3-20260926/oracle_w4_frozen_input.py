"""Supply frozen W2 observations to the existing stock dataset builder.

The caller provides its explicitly selected build_stock_model_dataset function
and governed calendar sessions. This adapter neither selects a model checkout
nor fits a model, writes to Turso, or changes the nightly pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Callable, Sequence

from oracle_w2_content_version import digest, read_version_rows
from oracle_w2_selector_reader import load_selector, read_sessions


_COLUMNS = {
    'ticker': 'Ticker', 'date': 'Date', 'close_price': 'Close',
    'daily_return_pct': 'Daily_Return_%', 'volume': 'Volume',
    'rsi_14d': 'RSI_14d', 'adx_14d': 'ADX_14d',
    'plus_di_14d': 'Plus_DI_14d', 'minus_di_14d': 'Minus_DI_14d',
    'atr_14d': 'ATR_14d', 'sector_momentum_score': 'Sector_Momentum_Score',
    'vix_close': 'VIX_Close', 'tnx_trend_5d': 'TNX_Trend_5d',
}


@dataclass(frozen=True)
class FrozenStockInput:
    dataset: Any
    lineage: dict[str, Any]


def prepare_frozen_stock_input(
    db: Any,
    selector_path: Path,
    universe_entry: Any,
    *,
    source_session_date: date,
    prediction_date: date,
    governed_sessions: Sequence[date],
    dataset_builder: Callable[..., Any],
    lookback_sessions: int = 30,
) -> FrozenStockInput:
    """Build only the model's required trailing window, without live-history reads.

    Calendar authority and lag-chain selection belong to the caller. The chain
    is bound here, not selected or statistically certified by this adapter.
    Historical revised values are not represented as point-in-time vintages.
    """
    if type(source_session_date) is not date or type(prediction_date) is not date:
        raise ValueError('source and prediction must be explicit session dates')
    if type(lookback_sessions) is not int or lookback_sessions < 30:
        raise ValueError('lookback requires at least 30 sessions')
    calendar = tuple(governed_sessions)
    if not calendar or any(type(d) is not date for d in calendar) or tuple(sorted(set(calendar))) != calendar:
        raise ValueError('governed sessions require unique ordered dates')
    if source_session_date not in calendar:
        raise ValueError('source is not in the supplied governed calendar')
    position = calendar.index(source_session_date)
    if position + 1 >= len(calendar) or prediction_date != calendar[position + 1]:
        raise ValueError('prediction must target the next governed session')
    depth = universe_entry.causal_depth
    lag_tickers = tuple(universe_entry.lag_tickers)
    if type(depth) is not int or not 0 <= depth <= 5 or len(lag_tickers) != depth:
        raise ValueError('lag chain does not match the existing configuration schema')
    bound = load_selector(Path(selector_path))
    if source_session_date > date.fromisoformat(bound['manifest']['cutoff']):
        raise ValueError('source exceeds the frozen data cutoff')
    if source_session_date.isoformat() not in read_sessions(db, bound):
        raise ValueError('source is absent from the frozen version')
    target = universe_entry.ticker
    required_tickers = {target, *lag_tickers}
    if not required_tickers <= bound['tickers']:
        raise ValueError('target or lag ticker is outside approved W1 membership')
    membership_path = Path(selector_path).resolve().parent / bound['selector']['membership_manifest']
    membership = json.loads(membership_path.read_text(encoding='ascii'))
    target_member = next(member for member in membership['members'] if member['ticker'] == target)
    if target_member.get('asset_class') != 'STOCK':
        raise ValueError('W4 target must be classified as STOCK in W1')
    warmup = 29 + depth if depth else 1
    required_count = lookback_sessions + warmup
    if position + 1 < required_count:
        raise ValueError('calendar lacks the required training and lag warmup sessions')
    window = calendar[position + 1 - required_count:position + 1]
    expected_dates = {d.isoformat() for d in window}
    columns = bound['manifest']['columns']
    if not set(_COLUMNS) <= set(columns):
        raise ValueError('frozen version lacks required model fields')
    records = []
    for ticker in sorted(required_tickers):
        frozen_rows = read_version_rows(db, bound['manifest'], ticker)
        by_date = {row[1]: dict(zip(columns, row)) for row in frozen_rows if row[1] in expected_dates}
        if set(by_date) != expected_dates:
            raise ValueError(f'{ticker}: missing required model-window sessions; no gap compression')
        for session in window:
            row = by_date[session.isoformat()]
            numeric = set(_COLUMNS) - {'ticker', 'date'} if ticker == target else {'daily_return_pct', 'volume'}
            if any(isinstance(row[c], bool) or not isinstance(row[c], (int, float)) or not math.isfinite(row[c]) for c in numeric):
                raise ValueError(f'{ticker}: invalid required numeric value at {session}')
            if row['volume'] < 0 or (ticker == target and row['close_price'] <= 0):
                raise ValueError(f'{ticker}: invalid volume or close at {session}')
            records.append({output: row[column] for column, output in _COLUMNS.items()})
    import pandas as pd

    frame = pd.DataFrame.from_records(records)
    dataset = dataset_builder(frame, universe_entry, source_session_date=source_session_date,
                              prediction_date=prediction_date, lookback_sessions=lookback_sessions)
    if (dataset.source_session_date != source_session_date or dataset.prediction_date != prediction_date
            or len(dataset.training_dates) != lookback_sessions
            or any(d > source_session_date for d in dataset.training_dates)):
        raise ValueError('dataset builder returned a different training or forecast context')
    lineage = {
        'version_id': bound['manifest']['version_id'],
        'version_manifest_sha256': bound['selector']['version_manifest_sha256'],
        'selector_sha256': bound['identity_sha256'],
        'membership_manifest_sha256': bound['selector']['membership_manifest_sha256'],
        'ticker': target, 'lag_tickers': list(lag_tickers), 'depth': depth,
        'lag_chain_sha256': digest({'ticker': target, 'lags': list(lag_tickers)}),
        'source_session_date': source_session_date.isoformat(),
        'prediction_date': prediction_date.isoformat(),
        'lookback_sessions': lookback_sessions,
        'window_start': window[0].isoformat(),
        'supplied_calendar_sha256': digest([d.isoformat() for d in calendar]),
        'historical_point_in_time_availability_proven': False,
        'input_content_sha256': {t: bound['manifest']['instruments'][t]['content_sha256'] for t in sorted(required_tickers)},
    }
    return FrozenStockInput(dataset=dataset, lineage=lineage)
