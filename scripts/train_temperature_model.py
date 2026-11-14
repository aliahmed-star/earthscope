#!/usr/bin/env python3
"""Train and evaluate the Cairo one-day-ahead T2M statistical model.

Run from the repository root with:
    python scripts/train_temperature_model.py

The command expects the HistoryStore integration to be available. Its default
SQLite path is EARTHSCOPE_HISTORY_DB when set, otherwise the repository's
``data/historical/earthscope_power.sqlite3``.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from earthscope.prediction_model import (  # noqa: E402
    LOCATION_ID,
    VARIABLE,
    InsufficientDataError,
    save_metadata,
    save_model,
    train_temperature_model,
)
from earthscope.history_store import DEFAULT_DB_PATH  # noqa: E402


def _history_store_class():
    """Load HistoryStore lazily so this script imports before that agent lands."""
    for module_name in (
        "earthscope.history_store",
        "earthscope.history",
        "earthscope.history_db",
    ):
        try:
            module = importlib.import_module(module_name)
            return getattr(module, "HistoryStore")
        except (ImportError, AttributeError):
            continue
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="HistoryStore database path (defaults to EARTHSCOPE_HISTORY_DB or repo DB)")
    parser.add_argument(
        "--model-path",
        default=str(REPO_ROOT / "models" / "cairo_t2m_next_day.json"),
        help="Destination for model JSON artifact",
    )
    parser.add_argument("--location-id", default=LOCATION_ID)
    parser.add_argument("--variable", default=VARIABLE)
    parser.add_argument(
        "--alphas", nargs="+", type=float, default=[0.01, 0.1, 1.0, 10.0, 100.0],
        help="Positive ridge alpha candidates tuned by validation MAE",
    )
    args = parser.parse_args(argv)

    history_class = _history_store_class()
    if history_class is None:
        parser.error(
            "HistoryStore is not available yet. Install the history-store integration "
            "providing variable_series/register_model_version/register_evaluation."
        )

    database_path = args.db or os.environ.get("EARTHSCOPE_HISTORY_DB") or str(DEFAULT_DB_PATH)
    store = history_class(path=database_path)
    records = store.variable_series(
        args.location_id,
        args.variable,
        start_date="1980-01-01",
        end_date="2025-12-31",
    )
    if not records:
        store.close()
        parser.error(
            f"No {args.variable} history found for {args.location_id} in {database_path}; "
            "ingest the daily archive first."
        )

    try:
        model, metadata = train_temperature_model(
            records,
            alpha_candidates=args.alphas,
            sources=[f"NASA POWER Daily SQLite archive ({Path(database_path).name}): "
                     f"{args.location_id}/{args.variable}"],
            history_store=store,
        )
    except InsufficientDataError as exc:
        parser.error(str(exc))
    finally:
        store.close()

    model_path = Path(args.model_path)
    metadata_path = model_path.with_suffix(".metadata.json")
    save_model(model, model_path)
    save_metadata(metadata, metadata_path)
    print(f"Model artifact: {model_path}")
    print(f"Metadata:       {metadata_path}")
    print(f"Model version:  {metadata['model_version']}")
    print(f"Rows:           {metadata['counts']}")
    print(f"Validation MAE: {metadata['validation_metrics']['mae']:.3f} {metadata['units']}")
    print("Held-out test metrics (same rows for all methods):")
    for method, metrics in metadata["test_metrics"].items():
        print(
            f"  {method:16} MAE={metrics['mae']:.3f} {metadata['units']}; "
            f"RMSE={metrics['rmse']:.3f}; bias={metrics['bias']:.3f}; "
            f"R2={metrics['r2']}; n={metrics['sample_count']}"
        )
    if metadata.get("persistence_warning"):
        print(f"History persistence warning: {metadata['persistence_warning']}")
    else:
        print("HistoryStore model/evaluation metadata persisted.")
    print("Statistical model estimate; not an operational weather forecast.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
