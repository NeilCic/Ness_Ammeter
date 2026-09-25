import math
import socket
import threading
import time

import pytest

from Ammeters.client import CURRENT_UNIT, request_current_from_ammeter
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config
from src.utils.emulators import start_emulators
from src.utils.logger import SESSION_LOG

AMMETERS = list(load_config("config/config.yaml")["ammeters"])
assert AMMETERS, "config has no ammeters"
DEFAULT_AMMETER = AMMETERS[0]


def test_start_emulators_reports_a_taken_port():
    SESSION_LOG.info("starting emulators again -> should fail on the first port")
    with pytest.raises(OSError, match="Port 5000 is already taken") as caught:
        start_emulators(load_config("config/config.yaml"), wait_seconds=0)
    SESSION_LOG.info(f"caught {caught.value}")


def test_request_times_out_when_the_meter_stays_silent():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", 0))
    server.listen()
    port = server.getsockname()[1]
    SESSION_LOG.info(f"opened a listener on localhost port {port}")
    release = threading.Event()

    def accept_and_hold():
        connection, _ = server.accept()
        SESSION_LOG.info(f"listener on port {port} accepted a connection and will send nothing")
        with connection:
            connection.recv(1024)
            release.wait(2)

    threading.Thread(target=accept_and_hold, daemon=True).start()
    try:
        wrong_cmd = b"MEASURE"
        SESSION_LOG.info(f"sending {wrong_cmd=} to port {port} with a 0.2s timeout")
        with pytest.raises(RuntimeError, match=f"No response from port {port} within 0.2 seconds") as caught:
            request_current_from_ammeter(port, wrong_cmd, 0.2)
        SESSION_LOG.info(f"caught {caught.value}")
    finally:
        release.set()
        server.close()
        SESSION_LOG.info(f"released the hold and closed the listener on port {port}")


@pytest.mark.parametrize("ammeter_type", AMMETERS)
def test_returns_a_finite_current(ammeter_type):
    SESSION_LOG.info(f"requesting one current from {ammeter_type}")
    current = AmmeterTestFramework().run_test(ammeter_type)
    SESSION_LOG.info(f"{ammeter_type} returned {current} {CURRENT_UNIT}")
    assert isinstance(current, float)
    assert math.isfinite(current)


def test_collects_samples_on_schedule():
    framework = AmmeterTestFramework()
    sampling = framework.config["testing"]["sampling"]
    SESSION_LOG.info(
        f"collecting {sampling['measurements_count']} samples from {DEFAULT_AMMETER} "
        f"at {sampling['sampling_frequency_hz']} Hz"
    )
    started = time.monotonic()
    samples = framework.collect_samples(DEFAULT_AMMETER)
    elapsed = time.monotonic() - started
    SESSION_LOG.info(f"collected {len(samples)} samples in {elapsed:.3f}s")

    assert len(samples) == sampling["measurements_count"]
    assert all(isinstance(sample, float) and math.isfinite(sample) for sample in samples)
    expected_elapsed = (sampling["measurements_count"] - 1) / sampling["sampling_frequency_hz"]
    assert sampling["total_duration_seconds"] == pytest.approx(expected_elapsed)
    gaps = sampling["measurements_count"] - 1
    allowed_lateness = gaps * 0.02 + 0.02
    assert abs(elapsed - expected_elapsed) < allowed_lateness  # proving we took samples in periods along the duration


def test_analysis_matches_the_samples():
    SESSION_LOG.info(f"analyzing a sample run from {DEFAULT_AMMETER}")
    result = AmmeterTestFramework().analyze(DEFAULT_AMMETER)
    samples = result["samples"]
    SESSION_LOG.info(
        f"mean {result['mean']:.4f}, median {result['median']:.4f}, "
        f"std {result['standard_deviation']:.4f}, "
        f"min {result['minimum']:.4f}, max {result['maximum']:.4f}"
    )

    assert result["minimum"] == min(samples)
    assert result["maximum"] == max(samples)
    assert result["mean"] == pytest.approx(sum(samples) / len(samples))
    assert result["minimum"] <= result["median"] <= result["maximum"]
    assert result["standard_deviation"] >= 0


def test_first_run_has_no_previous(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    SESSION_LOG.info(f"recording the first {DEFAULT_AMMETER} run in a fresh directory")
    record = framework.record_run(DEFAULT_AMMETER)
    comparison = framework.compare_to_previous(record)
    SESSION_LOG.info(f"run {record['run_id']} has {comparison['previous_count']} earlier runs")
    assert comparison == {"previous_count": 0, "compared": []}


def test_records_a_plot_and_compares_with_the_previous_run(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    limit = framework.config["result_management"]["compare_with_last"]
    SESSION_LOG.info(f"recording {limit + 1} {DEFAULT_AMMETER} runs, then one more")
    previous = [framework.record_run(DEFAULT_AMMETER) for _ in range(limit + 1)]
    latest = framework.record_run(DEFAULT_AMMETER)

    listed = [run["run_id"] for run in framework.list_runs(DEFAULT_AMMETER)]
    assert listed == [run["run_id"] for run in previous] + [latest["run_id"]]

    plot_path = tmp_path / latest["plot"]
    assert plot_path.is_file()
    assert plot_path.stat().st_size > 0
    SESSION_LOG.info(f"saved plot {plot_path.name}")
    assert framework.load_run(previous[0]["run_id"])["samples"] == previous[0]["samples"]

    comparison = framework.compare_to_previous(latest)
    SESSION_LOG.info(
        f"compared run {latest['run_id']} with {len(comparison['compared'])} "
        f"of {comparison['previous_count']} earlier runs"
    )
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
    SESSION_LOG.info("loading a run id that was never saved")
    with pytest.raises(ValueError, match="missing") as caught:
        framework.load_run("missing")
    SESSION_LOG.info(f"caught {caught.value}")


def test_ranks_meters_by_relative_spread():
    SESSION_LOG.info("ranking every meter by standard deviation divided by mean")
    ranking = AmmeterTestFramework().rank_meters()
    order = ", ".join(
        f"{row['ammeter_type']} {row['coefficient_of_variation']:.4f}" for row in ranking
    )
    SESSION_LOG.info(f"tightest first: {order}")

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
    SESSION_LOG.info(f"simulating an invalid reading on sample 1 for {DEFAULT_AMMETER}")
    with pytest.raises(RuntimeError, match=f"sample 1 for {DEFAULT_AMMETER}") as caught:
        framework.collect_samples(DEFAULT_AMMETER)
    SESSION_LOG.info(f"caught {caught.value}")

    framework.config["error_simulation"] = {
        "enabled": True,
        "mode": "connection_error",
        "fail_on_sample": 1,
    }
    SESSION_LOG.info("simulating an unknown mode connection_error")
    with pytest.raises(ValueError, match="Unknown error simulation mode: connection_error") as caught:
        framework.collect_samples(DEFAULT_AMMETER)
    SESSION_LOG.info(f"caught {caught.value}")


def test_simulated_failure_is_saved_and_skipped_in_comparison(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    SESSION_LOG.info(f"recording a finished {DEFAULT_AMMETER} run")
    first = framework.record_run(DEFAULT_AMMETER)
    framework.config["error_simulation"] = {
        "enabled": True,
        "mode": "invalid_reading",
        "fail_on_sample": 3,
    }
    SESSION_LOG.info("recording a run that fails on sample 3")
    with pytest.raises(RuntimeError, match=f"sample 3 for {DEFAULT_AMMETER}") as caught:
        framework.record_run(DEFAULT_AMMETER)
    SESSION_LOG.info(f"caught {caught.value}")

    failed = next(run for run in framework.list_runs(DEFAULT_AMMETER) if "error" in run)
    SESSION_LOG.info(
        f"saved run {failed['run_id']} with {len(failed['samples'])} samples and no statistics"
    )
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
    SESSION_LOG.info("recording another finished run and comparing it with earlier ones")
    latest = framework.record_run(DEFAULT_AMMETER)
    comparison = framework.compare_to_previous(latest)
    SESSION_LOG.info(
        f"comparison kept {comparison['compared'][0]['run_id']} and skipped the failed run"
    )
    assert comparison["previous_count"] == 1
    assert comparison["compared"][0]["run_id"] == first["run_id"]
