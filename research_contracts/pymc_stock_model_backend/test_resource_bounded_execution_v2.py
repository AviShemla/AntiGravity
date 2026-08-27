from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

try:
    from .resource_bounded_execution_v2 import (
        CAPACITY_VERIFIED_STATUS, MEASURED_PEAK_MEMORY_BYTES,
        RESOURCE_BLOCKED_STATUS,
        ExactScienceIdentity, IngestionSafeCapacity, MeasuredFourChainEvidence,
        ResourceContractV2Error, audit_resource_bounded_execution_plan_v2,
        build_resource_bounded_execution_plan_v2, derived_memory_limit_bytes,
        derived_runtime_limit_seconds,
    )
except ImportError:  # isolated workspace execution
    from resource_bounded_execution_v2 import (
        CAPACITY_VERIFIED_STATUS, MEASURED_PEAK_MEMORY_BYTES,
        RESOURCE_BLOCKED_STATUS,
        ExactScienceIdentity, IngestionSafeCapacity, MeasuredFourChainEvidence,
        ResourceContractV2Error, audit_resource_bounded_execution_plan_v2,
        build_resource_bounded_execution_plan_v2, derived_memory_limit_bytes,
        derived_runtime_limit_seconds,
    )


NOW = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)


def science(**changes):
    values = dict(
        dependency_lock_sha256="1" * 64, fixture_sha256="2" * 64,
        model_config_sha256="3" * 64, sampler_sha256="4" * 64,
        chains=4, draws=1_000, tune=1_000, max_rhat=1.01,
        min_bulk_ess=400, min_tail_ess=400, min_bfmi=0.3,
        max_divergences=0, max_treedepth_fraction=0.01,
    )
    values.update(changes)
    return ExactScienceIdentity(**values)


def measurement(**changes):
    values = dict(
        contract_id="codex-oracle-s08-four-chain-measurement-v1",
        evidence_raw_sha256="a" * 64, run_id="four-chain-measured-fixture",
        started_at_utc=datetime(2026, 8, 27, 12, 52, 22, tzinfo=timezone.utc),
        finished_at_utc=datetime(2026, 8, 27, 14, 58, 32, tzinfo=timezone.utc),
        elapsed_seconds=7_425, invocation_id="e8a9f0c2b3834aaf88c3ffbd333a77a6",
        cpu_usage_nsec=14_782_971_921_000, exit_status=1,
        science=science(), cpu_quota_percent=200,
        peak_memory_bytes=MEASURED_PEAK_MEMORY_BYTES, maximum_checkpoint_gap_seconds=None,
        measurement_complete=True, fixture_only=True, database_writes=0,
        downstream_counts={"predictions": 0, "recommendations": 0,
                           "orders": 0, "etf_outputs": 0},
    )
    values.update(changes)
    return MeasuredFourChainEvidence(**values)


def capacity(**changes):
    values = dict(
        observed_at_utc=NOW - timedelta(seconds=30), available_cpu_count=4,
        ingestion_cpu_reservation_percent=100,
        system_cpu_reservation_percent=100,
        available_memory_bytes=8 * 1024**3, available_disk_bytes=50 * 1024**3,
        ingestion_memory_reservation_bytes=2 * 1024**3,
        system_memory_reservation_bytes=1 * 1024**3,
        expected_output_bytes=2 * 1024**3, guarded_ingestion_active=False,
        next_guarded_ingestion_at_utc=NOW + timedelta(hours=5),
        ingestion_priority_reserved=True, no_duplicate_worker_observed=True,
    )
    values.update(changes)
    return IngestionSafeCapacity(**values)


def test_exact_measurement_is_represented_but_blocked_without_durable_progress():
    evidence = measurement()
    observed = capacity()
    plan = build_resource_bounded_execution_plan_v2(
        evidence=evidence, capacity=observed, now_utc=NOW,
    )
    assert plan.runtime_limit_seconds == 9_300
    assert plan.runtime_headroom_seconds == 1_875
    assert plan.memory_max_bytes == derived_memory_limit_bytes(MEASURED_PEAK_MEMORY_BYTES)
    assert plan.cpu_quota_percent == 200
    assert plan.status == RESOURCE_BLOCKED_STATUS
    assert plan.required_cpu_capacity_percent == 400
    assert plan.available_cpu_capacity_percent == 400
    assert plan.checkpoint_max_age_seconds is None
    assert plan.blockers == ("DURABLE_PROGRESS_UNOBSERVED",)
    assert plan.ingestion_time_buffer_seconds == 3_600
    assert plan.fixture_only is True
    assert plan.database_write_scope == "NONE"
    assert plan.downstream_authorized is plan.execution_authorized is False
    audit_resource_bounded_execution_plan_v2(
        plan, evidence=evidence, capacity=observed, now_utc=NOW,
    )


def test_runtime_is_derived_not_user_selected():
    assert derived_runtime_limit_seconds(7_425) == 9_300
    for value in (7_424, 7_426, 3_600, True):
        with pytest.raises(ResourceContractV2Error, match="7425"):
            derived_runtime_limit_seconds(value)


@pytest.mark.parametrize(
    "changed",
    [
        {"chains": 3}, {"draws": 999}, {"tune": 999}, {"max_rhat": 1.02},
        {"min_bulk_ess": 399}, {"min_tail_ess": 399}, {"min_bfmi": 0.29},
        {"max_divergences": 1}, {"max_treedepth_fraction": 0.02},
    ],
)
def test_no_scientific_or_convergence_threshold_can_be_weakened(changed):
    with pytest.raises(ResourceContractV2Error, match="threshold|sampler"):
        build_resource_bounded_execution_plan_v2(
            evidence=measurement(science=science(**changed)),
            capacity=capacity(), now_utc=NOW,
        )


@pytest.mark.parametrize(
    "changed, blocker",
    [
        ({"guarded_ingestion_active": True}, "GUARDED_INGESTION_ACTIVE"),
        ({"ingestion_priority_reserved": False}, "INGESTION_PRIORITY_NOT_RESERVED"),
        ({"no_duplicate_worker_observed": False}, "DUPLICATE_WORKER_NOT_CLEARED"),
        ({"next_guarded_ingestion_at_utc": NOW + timedelta(hours=3)}, "INGESTION_TIME_BUFFER"),
        ({"available_cpu_count": 1}, "CPU_CAPACITY_REQUIRED_400_AVAILABLE_100"),
    ],
)
def test_ingestion_and_host_capacity_classifies_resource_blocked(changed, blocker):
    plan = build_resource_bounded_execution_plan_v2(
        evidence=measurement(), capacity=capacity(**changed), now_utc=NOW,
    )
    assert plan.status == RESOURCE_BLOCKED_STATUS
    assert blocker in plan.blockers
    assert plan.execution_authorized is False


def test_stale_capacity_fails_closed_instead_of_claiming_blocked_or_safe():
    with pytest.raises(ResourceContractV2Error, match="stale"):
        build_resource_bounded_execution_plan_v2(
            evidence=measurement(),
            capacity=capacity(observed_at_utc=NOW - timedelta(minutes=3)),
            now_utc=NOW,
        )


def test_current_three_cpu_host_is_explicitly_resource_blocked_not_rewritten_to_50_percent():
    plan = build_resource_bounded_execution_plan_v2(
        evidence=measurement(), capacity=capacity(available_cpu_count=3), now_utc=NOW,
    )
    assert plan.cpu_quota_percent == 200
    assert plan.available_cpu_capacity_percent == 300
    assert plan.required_cpu_capacity_percent == 400
    assert plan.blockers == (
        "DURABLE_PROGRESS_UNOBSERVED",
        "CPU_CAPACITY_REQUIRED_400_AVAILABLE_300",
    )
    assert plan.status == RESOURCE_BLOCKED_STATUS


def test_measured_memory_plus_explicit_reservations_must_fit():
    required = derived_memory_limit_bytes(MEASURED_PEAK_MEMORY_BYTES) + 3 * 1024**3
    plan = build_resource_bounded_execution_plan_v2(
        evidence=measurement(),
        capacity=capacity(available_memory_bytes=required - 1), now_utc=NOW,
    )
    assert "MEMORY_CAPACITY" in plan.blockers
    assert plan.status == RESOURCE_BLOCKED_STATUS


def test_cpu_quota_is_exactly_bound_to_authoritative_200_percent_measurement():
    for changed in (50, 199, 201):
        with pytest.raises(ResourceContractV2Error, match="200%"):
            build_resource_bounded_execution_plan_v2(
                evidence=measurement(cpu_quota_percent=changed),
                capacity=capacity(), now_utc=NOW,
            )


def test_peak_memory_and_systemd_measurement_identity_are_exactly_bound():
    for changed in (
        {"peak_memory_bytes": MEASURED_PEAK_MEMORY_BYTES - 1},
        {"cpu_usage_nsec": 14_782_971_920_999},
        {"invocation_id": "f" * 32},
        {"exit_status": 0},
    ):
        with pytest.raises(ResourceContractV2Error, match="MemoryPeak|CPUUsage|Invocation|exit"):
            build_resource_bounded_execution_plan_v2(
                evidence=measurement(**changed), capacity=capacity(), now_utc=NOW,
            )


def test_unobserved_checkpoint_gap_cannot_be_replaced_with_invented_interval():
    with pytest.raises(ResourceContractV2Error, match="UNKNOWN"):
        build_resource_bounded_execution_plan_v2(
            evidence=measurement(maximum_checkpoint_gap_seconds=600),
            capacity=capacity(), now_utc=NOW,
        )


def test_cpu_reservations_cannot_be_silently_reduced():
    for changed in (
        {"ingestion_cpu_reservation_percent": 99},
        {"system_cpu_reservation_percent": 99},
    ):
        with pytest.raises(ResourceContractV2Error, match="CPU reservation"):
            build_resource_bounded_execution_plan_v2(
                evidence=measurement(), capacity=capacity(**changed), now_utc=NOW,
            )


def test_measurement_chronology_side_effects_and_hashes_fail_closed():
    invalid = (
        measurement(finished_at_utc=datetime(2026, 8, 27, 14, 58, 33, tzinfo=timezone.utc)),
        measurement(database_writes=1),
        measurement(evidence_raw_sha256="bad"),
        measurement(measurement_complete=False),
    )
    for evidence in invalid:
        with pytest.raises(ResourceContractV2Error):
            build_resource_bounded_execution_plan_v2(
                evidence=evidence, capacity=capacity(), now_utc=NOW,
            )


def test_plan_tamper_fails_independent_rebuild():
    evidence = measurement()
    observed = capacity()
    plan = build_resource_bounded_execution_plan_v2(
        evidence=evidence, capacity=observed, now_utc=NOW,
    )
    with pytest.raises(ResourceContractV2Error, match="identity"):
        audit_resource_bounded_execution_plan_v2(
            replace(plan, runtime_limit_seconds=plan.runtime_limit_seconds + 60),
            evidence=evidence, capacity=observed, now_utc=NOW,
        )


def test_module_has_no_execution_or_io_capability():
    try:
        from . import resource_bounded_execution_v2 as module
    except ImportError:  # isolated workspace execution
        import resource_bounded_execution_v2 as module

    names = set(vars(module))
    assert names.isdisjoint({
        "os", "subprocess", "socket", "requests", "urllib", "sqlite3", "Path",
    })
