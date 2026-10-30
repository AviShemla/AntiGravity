#!/bin/sh
set -eu

umask 077
exec /opt/antigravity/venv/bin/python \
  /home/codexops/codex_git/AntiGravity/scripts/oracle_production_schema_freeze.py \
  "$@" --env-file /opt/antigravity/.env
