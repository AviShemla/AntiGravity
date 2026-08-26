#!/usr/bin/env python3
"""Root entry point for the SELECT-only common full-universe baselines."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from full_universe_simple_baselines import main


if __name__ == "__main__":
    raise SystemExit(main())
