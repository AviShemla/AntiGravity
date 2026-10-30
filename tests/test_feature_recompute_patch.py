from datetime import date

import pandas as pd
import pytest

from canonical_market_history import CanonicalReconciliation
from feature_recompute_patch import build_feature_replacement_patch
from feature_recompute_plan import FeatureRecomputePlan, plan_feature_recomputation
from model_lineage import LineageError


def reconciliation(*, appended=(), revised=(), unchanged=()):
    return CanonicalReconciliation(
        history=pd.DataFrame(),
        appended_keys=tuple(appended),
        revised_keys=tuple(revised),
        unchanged_keys=tuple(unchanged),
    )


def feature_frame():
    return pd.DataFrame(
        [
            {"Ticker": ticker, "Date": session, "value": value}
            for value, (ticker, session) in enumerate(
                [
                    ("AAA", "2026-08-20"), ("AAA", "2026-08-21"),
                    ("BBB", "2026-08-20"), ("BBB", "2026-08-21"),
                ],
                start=1,
            )
        ]
    )


def canonical_keys():
    return [
        ("AAA", "2026-08-20"), ("AAA", "2026-08-21"),
        ("BBB", "2026-08-20"), ("BBB", "2026-08-21"),
    ]


def test_latest_append_replaces_every_cross_market_row_for_latest_session():
    plan = plan_feature_recomputation(
        reconciliation(appended=(("AAA", "2026-08-21"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    patch = build_feature_replacement_patch(
        feature_frame(), plan, canonical_keys=canonical_keys()
    )
    assert patch.replacement_keys == (
        ("AAA", "2026-08-21"),
        ("BBB", "2026-08-21"),
    )
    assert len(patch.content_sha256) == 64


def test_historical_revision_propagates_cross_market_rows_forward():
    plan = plan_feature_recomputation(
        reconciliation(revised=(("AAA", "2026-08-20"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    patch = build_feature_replacement_patch(
        feature_frame(), plan, canonical_keys=canonical_keys()
    )
    assert patch.replacement_keys == tuple(sorted(canonical_keys()))


def test_hash_is_stable_across_input_row_order():
    plan = plan_feature_recomputation(
        reconciliation(appended=(("AAA", "2026-08-21"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    first = build_feature_replacement_patch(
        feature_frame(), plan, canonical_keys=canonical_keys()
    )
    second = build_feature_replacement_patch(
        feature_frame().iloc[::-1], plan, canonical_keys=reversed(canonical_keys())
    )
    assert first.content_sha256 == second.content_sha256


def test_missing_planned_key_fails_closed():
    plan = plan_feature_recomputation(
        reconciliation(appended=(("AAA", "2026-08-21"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    with pytest.raises(LineageError, match="missing 1 planned canonical keys"):
        build_feature_replacement_patch(
            feature_frame().query("not (Ticker == 'BBB' and Date == '2026-08-21')"),
            plan,
            canonical_keys=canonical_keys(),
        )


def test_noncanonical_feature_key_fails_closed():
    plan = plan_feature_recomputation(
        reconciliation(appended=(("AAA", "2026-08-21"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    extra = pd.concat(
        [feature_frame(), pd.DataFrame([{"Ticker": "CCC", "Date": "2026-08-21", "value": 9}])],
        ignore_index=True,
    )
    with pytest.raises(LineageError, match="absent from canonical history"):
        build_feature_replacement_patch(extra, plan, canonical_keys=canonical_keys())


def test_duplicate_feature_key_fails_closed():
    plan = plan_feature_recomputation(
        reconciliation(appended=(("AAA", "2026-08-21"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    duplicated = pd.concat([feature_frame(), feature_frame().iloc[[0]]], ignore_index=True)
    with pytest.raises(LineageError, match="duplicate ticker/session"):
        build_feature_replacement_patch(
            duplicated, plan, canonical_keys=canonical_keys()
        )


def test_no_change_plan_returns_empty_patch():
    plan = plan_feature_recomputation(
        reconciliation(unchanged=(("AAA", "2026-08-21"),)),
        available_sessions=("2026-08-20", "2026-08-21"),
    )
    patch = build_feature_replacement_patch(
        feature_frame(), plan, canonical_keys=canonical_keys()
    )
    assert patch.frame.empty
    assert patch.replacement_keys == ()
    assert len(patch.content_sha256) == 64


def test_no_change_plan_with_replacement_sessions_fails_closed():
    invalid = FeatureRecomputePlan(
        ticker_plans=(),
        cross_market_write_sessions=(date(2026, 8, 21),),
        changed_keys=(),
        unchanged_keys=(),
    )
    with pytest.raises(LineageError, match="No-change"):
        build_feature_replacement_patch(
            feature_frame(), invalid, canonical_keys=canonical_keys()
        )
