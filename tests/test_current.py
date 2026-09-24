import math
import time

import pytest

from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config

AMMETERS = list(load_config("config/config.yaml")["ammeters"])


@pytest.mark.parametrize("ammeter_type", AMMETERS)
def test_returns_a_finite_current(ammeter_type):
    current = AmmeterTestFramework().run_test(ammeter_type)
    assert isinstance(current, float)
    assert math.isfinite(current)


@pytest.mark.parametrize("ammeter_type", AMMETERS)
def test_collects_samples_on_schedule(ammeter_type):
    framework = AmmeterTestFramework()
    sampling = framework.config["testing"]["sampling"]
    started = time.monotonic()
    samples = framework.collect_samples(ammeter_type)
    elapsed = time.monotonic() - started

    assert len(samples) == sampling["measurements_count"]
    assert all(isinstance(sample, float) and math.isfinite(sample) for sample in samples)
    expected_elapsed = (sampling["measurements_count"] - 1) / sampling["sampling_frequency_hz"]
    gaps = sampling["measurements_count"] - 1
    allowed_lateness = gaps * 0.02 + 0.02
    assert abs(elapsed - expected_elapsed) < allowed_lateness  # proving we took samples in periods along the duration


@pytest.mark.parametrize("ammeter_type", AMMETERS)
def test_analysis_matches_the_samples(ammeter_type):
    result = AmmeterTestFramework().analyze(ammeter_type)
    samples = result["samples"]

    assert result["minimum"] == min(samples)
    assert result["maximum"] == max(samples)
    assert result["mean"] == pytest.approx(sum(samples) / len(samples))
    assert result["minimum"] <= result["median"] <= result["maximum"]
    assert result["standard_deviation"] >= 0
