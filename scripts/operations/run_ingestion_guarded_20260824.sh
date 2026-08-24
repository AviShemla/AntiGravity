#!/usr/bin/env bash
set -u -o pipefail

job_root=/home/codexops/jobs/ingest-20260824
git_root=/home/codexops/codex_git/AntiGravity
python_bin=/opt/antigravity/venv/bin/python
source_session=2026-08-24
universe_snapshot=market_features_2026-08-20_3a0e9feffc5ab92f
max_attempts=3
retry_seconds=900

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

fail() {
  log "PRECHECK_FAILED $*"
  exit 90
}

for unit in ag-sniper.service antigravity-nightly.timer antigravity-qa-watchdog.timer; do
  if systemctl is-active --quiet "$unit"; then
    fail "$unit is active"
  fi
done

test "$(stat -c '%a:%U:%G' /opt/antigravity/.env)" = "600:root:root" \
  || fail "unexpected /opt/antigravity/.env permissions"
test "$(stat -c '%a:%U:%G' /etc/antigravity/tiingo.token)" = "640:root:codexops" \
  || fail "unexpected /etc/antigravity/tiingo.token permissions"
test ! -e "$job_root/financial_data/api_keys.json" \
  || fail "legacy API-key file is present in the job tree"

for relative_path in \
  scripts/rebuild_market_features_to_turso.py \
  scripts/stage_market_features_to_turso.py \
  market_data_provider.py \
  market_data_guard.py \
  model_lineage.py \
  turso_read_pipeline.py; do
  cmp -s "$job_root/$relative_path" "$git_root/$relative_path" \
    || fail "job code drift: $relative_path"
done

PYTHONDONTWRITEBYTECODE=1 "$python_bin" -m py_compile \
  "$job_root/scripts/rebuild_market_features_to_turso.py" \
  || fail "ingestion script compilation failed"

if [ "${1:-}" = "--preflight-only" ]; then
  log "PRECHECK_SUCCEEDED source_session=$source_session"
  exit 0
fi

attempt=1
while [ "$attempt" -le "$max_attempts" ]; do
  log "INGESTION_ATTEMPT attempt=$attempt max_attempts=$max_attempts source_session=$source_session"
  if PYTHONDONTWRITEBYTECODE=1 "$python_bin" -u \
    "$job_root/scripts/rebuild_market_features_to_turso.py" \
    --source-session "$source_session" \
    --universe-snapshot "$universe_snapshot" \
    --required-tickers SPY \
    --workers 8 \
    --env-file /opt/antigravity/.env \
    --tiingo-token-file /etc/antigravity/tiingo.token; then
    log "INGESTION_SUCCEEDED attempt=$attempt source_session=$source_session status=STAGED_NOT_VALIDATED"
    exit 0
  else
    exit_code=$?
  fi
  log "INGESTION_FAILED attempt=$attempt exit_code=$exit_code"
  if [ "$attempt" -ge "$max_attempts" ]; then
    exit "$exit_code"
  fi
  sleep "$retry_seconds"
  attempt=$((attempt + 1))
done
