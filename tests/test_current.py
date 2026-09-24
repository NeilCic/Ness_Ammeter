import math
import time

import pytest

from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config

AMMETERS = list(load_config("config/config.yaml")["ammeters"])
assert AMMETERS, "config has no ammeters"
DEFAULT_AMMETER = AMMETERS[0]


@pytest.mark.parametrize("ammeter_type", AMMETERS)
def test_returns_a_finite_current(ammeter_type):
    current = AmmeterTestFramework().run_test(ammeter_type)
    assert isinstance(current, float)
    assert math.isfinite(current)


def test_collects_samples_on_schedule():
    framework = AmmeterTestFramework()
    sampling = framework.config["testing"]["sampling"]
    started = time.monotonic()
    samples = framework.collect_samples(DEFAULT_AMMETER)
    elapsed = time.monotonic() - started

    assert len(samples) == sampling["measurements_count"]
    assert all(isinstance(sample, float) and math.isfinite(sample) for sample in samples)
    expected_elapsed = (sampling["measurements_count"] - 1) / sampling["sampling_frequency_hz"]
    gaps = sampling["measurements_count"] - 1
    allowed_lateness = gaps * 0.02 + 0.02
    assert abs(elapsed - expected_elapsed) < allowed_lateness  # proving we took samples in periods along the duration


def test_analysis_matches_the_samples():
    result = AmmeterTestFramework().analyze(DEFAULT_AMMETER)
    samples = result["samples"]

    assert result["minimum"] == min(samples)
    assert result["maximum"] == max(samples)
    assert result["mean"] == pytest.approx(sum(samples) / len(samples))
    assert result["minimum"] <= result["median"] <= result["maximum"]
    assert result["standard_deviation"] >= 0


def test_first_run_has_no_previous(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    record = framework.record_run(DEFAULT_AMMETER)
    assert framework.compare_to_previous(record) == {"previous_count": 0, "compared": []}


def test_records_a_plot_and_compares_with_the_previous_run(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    limit = framework.config["result_management"]["compare_with_last"]
    previous = [framework.record_run(DEFAULT_AMMETER) for _ in range(limit + 1)]
    latest = framework.record_run(DEFAULT_AMMETER)

    plot_path = tmp_path / latest["plot"]
    assert plot_path.is_file()
    assert plot_path.stat().st_size > 0
    assert framework.load_run(previous[0]["run_id"])["samples"] == previous[0]["samples"]

    comparison = framework.compare_to_previous(latest)
    assert comparison["previous_count"] == limit + 1
    assert len(comparison["compared"]) == limit

    newest = comparison["compared"][0]
    assert newest["run_id"] == previous[-1]["run_id"]
    assert newest["mean_difference"] == pytest.approx(latest["mean"] - previous[-1]["mean"])
    assert newest["standard_deviation_difference"] == pytest.approx(
        latest["standard_deviation"] - previous[-1]["standard_deviation"]
    )
    assert comparison["compared"][-1]["run_id"] == previous[1]["run_id"]
