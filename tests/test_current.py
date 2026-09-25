import math
import socket
import threading
import time

import pytest

from Ammeters.client import request_current_from_ammeter
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config

AMMETERS = list(load_config("config/config.yaml")["ammeters"])
assert AMMETERS, "config has no ammeters"
DEFAULT_AMMETER = AMMETERS[0]


def test_request_times_out_when_the_meter_stays_silent():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", 0))
    server.listen()
    port = server.getsockname()[1]
    release = threading.Event()

    def accept_and_hold():
        connection, _ = server.accept()
        with connection:
            connection.recv(1024)
            release.wait(2)

    threading.Thread(target=accept_and_hold, daemon=True).start()
    try:
        wrong_cmd = b"MEASURE"
        with pytest.raises(RuntimeError, match=f"No response from port {port} within 0.2 seconds"):
            request_current_from_ammeter(port, wrong_cmd, 0.2)
    finally:
        release.set()
        server.close()


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
    assert sampling["total_duration_seconds"] == pytest.approx(expected_elapsed)
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

    listed = [run["run_id"] for run in framework.list_runs(DEFAULT_AMMETER)]
    assert listed == [run["run_id"] for run in previous] + [latest["run_id"]]

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


def test_load_run_rejects_an_unknown_id(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    with pytest.raises(ValueError, match="missing"):
        framework.load_run("missing")


def test_ranks_meters_by_relative_spread():
    ranking = AmmeterTestFramework().rank_meters()

    assert {row["ammeter_type"] for row in ranking} == set(AMMETERS)
    spreads = [row["coefficient_of_variation"] for row in ranking]
    assert spreads == sorted(spreads)
    for row in ranking:
        assert row["coefficient_of_variation"] == pytest.approx(
            row["standard_deviation"] / abs(row["mean"])
        )


def test_simulated_invalid_reading_stops_the_run():
    framework = AmmeterTestFramework()
    framework.config["error_simulation"] = {
        "enabled": True,
        "mode": "invalid_reading",
        "fail_on_sample": 1,
    }
    with pytest.raises(RuntimeError, match=f"sample 1 for {DEFAULT_AMMETER}"):
        framework.collect_samples(DEFAULT_AMMETER)

    framework.config["error_simulation"] = {
        "enabled": True,
        "mode": "connection_error",
        "fail_on_sample": 1,
    }
    with pytest.raises(ValueError, match=f"Unknown error simulation mode: {framework.config['error_simulation']['mode']}"):
        framework.collect_samples(DEFAULT_AMMETER)


def test_simulated_failure_is_saved_and_skipped_in_comparison(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    first = framework.record_run(DEFAULT_AMMETER)
    framework.config["error_simulation"] = {
        "enabled": True,
        "mode": "invalid_reading",
        "fail_on_sample": 3,
    }
    with pytest.raises(RuntimeError, match=f"sample 3 for {DEFAULT_AMMETER}"):
        framework.record_run(DEFAULT_AMMETER)

    failed = next(run for run in framework.list_runs(DEFAULT_AMMETER) if "error" in run)
    assert len(failed["samples"]) == 2
    assert len(failed["sample_times"]) == 2
    assert "mean" not in failed
    assert "plot" not in failed
    assert failed["error"] == {
        "mode": "invalid_reading",
        "sample_number": 3,
        "message": f"Simulated error on sample 3 for {DEFAULT_AMMETER}: invalid reading",
    }

    framework.config["error_simulation"]["enabled"] = False
    latest = framework.record_run(DEFAULT_AMMETER)
    comparison = framework.compare_to_previous(latest)
    assert comparison["previous_count"] == 1
    assert comparison["compared"][0]["run_id"] == first["run_id"]
