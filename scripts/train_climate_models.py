#!/usr/bin/env python3
"""Train/evaluate location-variable archive-origin estimates from the SQLite database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from earthscope.climate_model_suite import train_suite  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLite path; defaults to EARTHSCOPE_HISTORY_DB or bundled archive")
    parser.add_argument("--output", help="Model-bundle path; defaults to models/climate_models.json")
    args = parser.parse_args(argv)
    result = train_suite(args.db, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
