from pathlib import Path

import pytest

from earthscope.climate_model_suite import MODEL_BUNDLE_PATH, predict_suite
from earthscope.history_store import DEFAULT_DB_PATH


def test_packaged_archive_origin_estimates_and_empirical_interval_gating():
    if not MODEL_BUNDLE_PATH.is_file() or not Path(DEFAULT_DB_PATH).is_file():
        pytest.skip("Run scripts/train_climate_models.py with the bundled SQLite archive first.")
    result = predict_suite(["cairo-eg"])
    assert len(result["predictions"]) == 4
    for item in result["predictions"]:
        assert item["prediction_status"] == "estimated"
        assert item["target_date"] > item["as_of"]
        assert "not an operational weather forecast" in item["disclaimer"]
        interval = item["prediction_interval"]
        if interval is None:
            assert "not reliably quantified" in item["uncertainty_note"]
        else:
            assert interval["level"] == pytest.approx(0.90)
            assert 0.85 <= interval["test_coverage"] <= 0.95
            assert interval["test_period"] == item["periods"]["test"]
