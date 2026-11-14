#!/usr/bin/env python3
"""Command-line entry point for historical NASA POWER ingestion."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from earthscope.history_ingest import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
