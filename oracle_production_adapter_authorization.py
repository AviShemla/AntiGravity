"""Minimal adapter integration: authorize first, construct transport second."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, TypeVar

from oracle_production_authorization_envelope import (
    AuthorizationEnvelopeError,
    validate_runtime_authorization,
)


T = TypeVar("T")


def authorize_then_create_transport(
    transport_factory: Callable[[], T],
    *,
    envelope: Mapping[str, object],
    authorization: Mapping[str, object],
    expected_envelope_sha256: str,
    application_contract_path: Path,
    adapter_release_root: Path,
    operation_id: str,
    observed_at_utc: datetime,
) -> tuple[T, str]:
    """Validate all immutable leaves before invoking an injected factory once."""

    if not callable(transport_factory):
        raise AuthorizationEnvelopeError("an unconstructed transport factory is required")
    trusted_envelope_sha256 = validate_runtime_authorization(
        envelope,
        authorization,
        expected_envelope_sha256=expected_envelope_sha256,
        application_contract_path=application_contract_path,
        adapter_release_root=adapter_release_root,
        operation_id=operation_id,
        observed_at_utc=observed_at_utc,
    )
    transport = transport_factory()
    if transport is None:
        raise AuthorizationEnvelopeError("transport factory returned no transport")
    return transport, trusted_envelope_sha256
