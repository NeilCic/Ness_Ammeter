import math
import socket
import threading
import time
from contextlib import contextmanager

import pytest

import main as main_script
from Ammeters.client import CURRENT_UNIT, AmmeterError, request_current_from_ammeter
from src.testing.test_framework import AmmeterTestFramework, RunFailed
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


@contextmanager
def _fake_meter(*replies: bytes | None):
    """Listen on a free port and answer one request per reply, in order. A None reply stays silent."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", 0))
    server.listen()
    port = server.getsockname()[1]
    SESSION_LOG.info(f"opened a fake meter on localhost port {port} that replies {replies!r}")
    release = threading.Event()

    def serve():
        for reply in replies:
            connection, _ = server.accept()
            with connection:
                connection.recv(1024)
                if reply is None:
                    release.wait(2)
                else:
                    connection.sendall(reply)

    threading.Thread(target=serve, daemon=True).start()
    try:
        yield port
    finally:
        release.set()
        server.close()
        SESSION_LOG.info(f"closed the fake meter on port {port}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def test_request_times_out_when_the_meter_stays_silent():
    with _fake_meter(None) as port:
        SESSION_LOG.info(f"requesting from port {port} with a 0.2s timeout")
        with pytest.raises(AmmeterError, match=f"No response from port {port} within 0.2 seconds") as caught:
            request_current_from_ammeter(port, b"MEASURE", 0.2)
        SESSION_LOG.info(f"caught {caught.value}")


def test_request_fails_clearly_when_no_meter_is_listening():
    port = _free_port()
    SESSION_LOG.info(f"requesting from port {port}, which nothing listens on")
    with pytest.raises(AmmeterError, match=f"No meter is reachable on port {port}") as caught:
        request_current_from_ammeter(port, b"MEASURE", 0.3)
    SESSION_LOG.info(f"caught {caught.value}")


@pytest.mark.parametrize(
    ("reply", "reason"),
    [(b"ERR: sensor fault", "is not a number"), (b"nan", "is not a finite current")],
)
def test_request_rejects_a_reply_that_is_not_a_current(reply, reason):
    with _fake_meter(reply) as port:
        with pytest.raises(AmmeterError, match=reason) as caught:
            request_current_from_ammeter(port, b"MEASURE", 1)
        SESSION_LOG.info(f"caught {caught.value}")


def test_run_test_names_the_meter_that_failed():
    framework = AmmeterTestFramework()
    framework.config["ammeters"][DEFAULT_AMMETER]["port"] = _free_port()
    framework.config["testing"]["request_timeout_seconds"] = 0.3
    SESSION_LOG.info(f"pointing {DEFAULT_AMMETER} at a port nothing listens on")
    with pytest.raises(AmmeterError, match=f"^{DEFAULT_AMMETER}: No meter is reachable") as caught:
        framework.run_test(DEFAULT_AMMETER)
    SESSION_LOG.info(f"caught {caught.value}")


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


def test_sampling_needs_at_least_two_settings():
    framework = AmmeterTestFramework()
    framework.config["testing"]["sampling"] = {"measurements_count": 5}
    SESSION_LOG.info("resolving sampling with only measurements_count set")
    with pytest.raises(ValueError, match="Set at least two of") as caught:
        framework._resolve_sampling()
    SESSION_LOG.info(f"caught {caught.value}")


def test_sampling_rejects_a_duration_that_disagrees():
    framework = AmmeterTestFramework()
    framework.config["testing"]["sampling"] = {
        "measurements_count": 5,
        "total_duration_seconds": 0.5,
        "sampling_frequency_hz": 10,
    }
    SESSION_LOG.info("resolving 5 samples at 10 Hz over 0.5s, which does not match the span between samples")
    with pytest.raises(ValueError, match=r"duration should be 0\.4") as caught:
        framework._resolve_sampling()
    SESSION_LOG.info(f"caught {caught.value}")


def test_run_test_rejects_an_unknown_meter():
    framework = AmmeterTestFramework()
    SESSION_LOG.info("requesting a current from a meter that is not in the config")
    with pytest.raises(ValueError, match="Unknown ammeter 'not-a-meter'") as caught:
        framework.run_test("not-a-meter")
    SESSION_LOG.info(f"caught {caught.value}")


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
        "kind": "simulated",
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


def test_meter_failure_is_saved_with_the_samples_taken_so_far(tmp_path):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    with _fake_meter(b"1.0", b"2.0", b"ERR: sensor fault") as port:
        framework.config["ammeters"][DEFAULT_AMMETER]["port"] = port
        SESSION_LOG.info(f"recording {DEFAULT_AMMETER} from a meter that answers twice, then sends garbage")
        with pytest.raises(RunFailed, match="is not a number") as caught:
            framework.record_run(DEFAULT_AMMETER)
    SESSION_LOG.info(f"caught {caught.value}")
    assert caught.value.kind == "meter"
    assert caught.value.sample_number == 3

    (failed,) = framework.list_runs(DEFAULT_AMMETER)
    SESSION_LOG.info(f"saved run {failed['run_id']} with samples {failed['samples']}")
    assert failed["samples"] == [1.0, 2.0]
    assert len(failed["sample_times"]) == 2
    assert "mean" not in failed
    assert failed["error"] == {
        "kind": "meter",
        "sample_number": 3,
        "message": f"{DEFAULT_AMMETER}: Port {port} replied with 'ERR: sensor fault', which is not a number",
    }


def test_main_reports_a_failed_meter_and_ranks_the_rest(tmp_path, capsys):
    framework = AmmeterTestFramework(results_dir=tmp_path)
    framework.config["ammeters"][DEFAULT_AMMETER]["port"] = _free_port()
    framework.config["testing"]["request_timeout_seconds"] = 0.3
    SESSION_LOG.info(f"running main with {DEFAULT_AMMETER} pointed at a dead port")

    exit_code = main_script.run(framework)
    output = capsys.readouterr().out
    SESSION_LOG.info(f"main exited with {exit_code}")

    assert exit_code == 1
    assert f"FAILED {DEFAULT_AMMETER} on sample 1: {DEFAULT_AMMETER}: No meter is reachable" in output
    assert "(0 samples saved)" in output
    others = [name for name in AMMETERS if name != DEFAULT_AMMETER]
    for place, name in enumerate(others, start=1):
        assert any(line.startswith(f"{place}. ") for line in output.splitlines()), f"no rank {place}"
        assert f". {name}: mean" in output
    assert len(framework.list_runs(DEFAULT_AMMETER)) == 1
    assert all(len(framework.list_runs(name)) == 1 for name in others)
