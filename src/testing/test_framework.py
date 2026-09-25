import time
import statistics
import json
import uuid

from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from Ammeters.client import request_current_from_ammeter
from ..utils.config import load_config


class SimulatedReadingError(RuntimeError):
    def __init__(self, message: str, *, mode: str, sample_number: int, started_at: str, readings: list):
        super().__init__(message)
        self.mode = mode
        self.sample_number = sample_number
        self.started_at = started_at
        self.readings = readings


class AmmeterTestFramework:
    def __init__(self, config_path: str = "config/config.yaml", results_dir: str | None = None):
        self.config = load_config(config_path)
        configured_dir = self.config.get("result_management", {}).get("directory", "results")
        self.results_dir = results_dir or configured_dir
        
    def run_test(self, ammeter_type: str) -> float:
        try:
            ammeter = self.config["ammeters"][ammeter_type]
        except KeyError:
            known = ", ".join(self.config.get("ammeters", {}))
            raise ValueError(f"Unknown ammeter '{ammeter_type}'. Known: {known}") from None
        timeout = self.config["testing"]["request_timeout_seconds"]
        return request_current_from_ammeter(
            ammeter["port"], ammeter["command"].encode("utf-8"), timeout
        )

    def collect_samples(self, ammeter_type: str) -> list[float]:
        readings = self._collect_readings(ammeter_type)["readings"]
        return [reading["current"] for reading in readings]

    def _collect_readings(self, ammeter_type: str) -> dict:
        count, frequency, _duration = self._resolve_sampling()
        period = 1.0 / frequency
        started_at = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()
        readings = []
        for index in range(count):
            self._wait_until(start + index * period)
            taken_at = datetime.now(timezone.utc).isoformat()
            try:
                self._simulated_error(ammeter_type, index + 1)
            except SimulatedReadingError as error:
                raise SimulatedReadingError(
                    str(error),
                    mode=error.mode,
                    sample_number=error.sample_number,
                    started_at=started_at,
                    readings=list(readings),
                ) from None
            readings.append({
                "current": self.run_test(ammeter_type),
                "taken_at": taken_at,
            })
        return {"started_at": started_at, "readings": readings}

    def _resolve_sampling(self) -> tuple[int, float, float]:
        sampling = self.config["testing"]["sampling"]
        count = _optional_positive(sampling.get("measurements_count"), "measurements_count")
        duration = _optional_positive(sampling.get("total_duration_seconds"), "total_duration_seconds")
        frequency = _optional_positive(sampling.get("sampling_frequency_hz"), "sampling_frequency_hz")
        provided_count = sum(1 for value in (count, duration, frequency) if value is not None)
        if provided_count < 2:
            raise ValueError(
                "Set at least two of measurements_count, total_duration_seconds, and sampling_frequency_hz"
            )

        if count is not None:
            count = _whole_count(count)
        else:
            count = _whole_count(duration * frequency + 1)
        if count < 2:
            raise ValueError("measurements_count must be at least 2 so the samples have a spacing")

        if frequency is None:
            frequency = (count - 1) / duration
        elif duration is None:
            duration = (count - 1) / frequency

        expected_duration = (count - 1) / frequency
        if abs(duration - expected_duration) > 1e-6:
            raise ValueError(
                f"Sampling settings disagree: duration should be {expected_duration} "
                f"((measurements_count - 1) / sampling_frequency_hz), got {duration}"
            )
        return count, frequency, expected_duration

    def analyze(self, ammeter_type: str) -> dict:
        collected = self._collect_readings(ammeter_type)
        samples = [reading["current"] for reading in collected["readings"]]
        metrics = self.config["analysis"]["statistical_metrics"]
        return {
            "started_at": collected["started_at"],
            "samples": samples,
            "sample_times": [reading["taken_at"] for reading in collected["readings"]],
            **summarize_samples(samples, metrics),
        }

    def record_run(self, ammeter_type: str) -> dict:
        try:
            analysis = self.analyze(ammeter_type)
        except SimulatedReadingError as error:
            record = {
                "run_id": uuid.uuid4().hex,
                "ammeter_type": ammeter_type,
                "started_at": error.started_at,
                "sampling": self.config["testing"]["sampling"],
                "samples": [reading["current"] for reading in error.readings],
                "sample_times": [reading["taken_at"] for reading in error.readings],
                "error": {
                    "mode": error.mode,
                    "sample_number": error.sample_number,
                    "message": str(error),
                },
            }
            self._write_record(record)
            raise
        run_id = uuid.uuid4().hex
        record = {
            "run_id": run_id,
            "ammeter_type": ammeter_type,
            "started_at": analysis["started_at"],
            "sampling": self.config["testing"]["sampling"],
            "samples": analysis["samples"],
            "sample_times": analysis["sample_times"],
            "mean": analysis["mean"],
            "median": analysis["median"],
            "standard_deviation": analysis["standard_deviation"],
            "minimum": analysis["minimum"],
            "maximum": analysis["maximum"],
            "plot": None,
        }

        directory = Path(self.results_dir)
        directory.mkdir(parents=True, exist_ok=True)
        if self._plots_enabled():
            plot_name = f"{run_id}.png"
            save_sample_plot(directory / plot_name, ammeter_type, record)
            record["plot"] = plot_name

        self._write_record(record)
        return record

    def _write_record(self, record: dict) -> None:
        directory = Path(self.results_dir)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{record['run_id']}.json").write_text(json.dumps(record), encoding="utf-8")

    def load_run(self, run_id: str) -> dict:
        path = Path(self.results_dir) / f"{run_id}.json"
        if not path.is_file():
            raise ValueError(f"No run with id {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self, ammeter_type: str) -> list[dict]:
        directory = Path(self.results_dir)
        if not directory.exists():
            return []
        runs = []
        for path in directory.glob("*.json"):
            run = json.loads(path.read_text(encoding="utf-8"))
            if run["ammeter_type"] == ammeter_type:
                runs.append(run)
        return sorted(runs, key=lambda run: run["started_at"])

    def compare_to_previous(self, record: dict) -> dict:
        earlier = [
            run for run in self.list_runs(record["ammeter_type"])
            if run["run_id"] != record["run_id"] and run["started_at"] < record["started_at"] and "error" not in run
        ]
        limit = self.config["result_management"]["compare_with_last"]
        recent = list(reversed(earlier[-limit:]))
        return {
            "previous_count": len(earlier),
            "compared": [
                {
                    "run_id": run["run_id"],
                    "mean_difference": record["mean"] - run["mean"],
                    "standard_deviation_difference": record["standard_deviation"] - run["standard_deviation"],
                }
                for run in recent
            ],
        }

    def _plots_enabled(self) -> bool:
        visualization = self.config.get("analysis", {}).get("visualization", {})
        return bool(visualization.get("enabled"))

    def rank_records(self, records: list[dict]) -> list[dict]:
        ranked = []
        for record in records:
            mean = record["mean"]
            if mean == 0:
                raise ValueError(f"{record['ammeter_type']} mean is 0, so relative spread is undefined")
            ranked.append({
                **record,
                "coefficient_of_variation": record["standard_deviation"] / abs(mean),
            })
        return sorted(ranked, key=lambda row: row["coefficient_of_variation"])

    def rank_meters(self) -> list[dict]:
        records = []
        for ammeter_type in self.config["ammeters"]:
            analysis = self.analyze(ammeter_type)
            records.append({"ammeter_type": ammeter_type, **analysis})
        return self.rank_records(records)

    def _simulated_error(self, ammeter_type: str, sample_number: int) -> None:
        simulation = self.config.get("error_simulation") or {}
        if not simulation.get("enabled"):
            return
        mode = simulation.get("mode")
        if mode != "invalid_reading":
            raise ValueError(f"Unknown error simulation mode: {mode}")
        if sample_number != simulation.get("fail_on_sample"):
            return
        raise SimulatedReadingError(
            f"Simulated error on sample {sample_number} for {ammeter_type}: invalid reading",
            mode=mode,
            sample_number=sample_number,
            started_at="",
            readings=[],
        )

    @staticmethod
    def _wait_until(deadline: float) -> None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(remaining)  # when taking a lot of measurements sleep can mess up accuracy


def _optional_positive(value, name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def _whole_count(value: float) -> int:
    if abs(value - round(value)) > 1e-6:
        raise ValueError("measurements_count must be a whole number")
    return int(round(value))


def summarize_samples(samples: list[float], metrics: list[str]) -> dict[str, float]:
    if "standard_deviation" in metrics and len(samples) < 2:
        raise ValueError("At least two measurements are required to compute a standard deviation")
    available = {
        "mean": statistics.mean(samples),
        "median": statistics.median(samples),
        "standard_deviation": statistics.stdev(samples),
        "minimum": min(samples),
        "maximum": max(samples),
    }
    return {name: available[name] for name in metrics}


def save_sample_plot(path: Path, ammeter_type: str, record: dict) -> None:
    samples = record["samples"]
    mean = record["mean"]
    standard_deviation = record["standard_deviation"]
    indexes = list(range(1, len(samples) + 1))
    figure, axis = plt.subplots()
    axis.plot(indexes, samples, marker="o", label="current")
    axis.axhline(mean, linestyle="--", label="mean")
    axis.fill_between(
        indexes,
        [mean - standard_deviation] * len(samples),
        [mean + standard_deviation] * len(samples),
        alpha=0.2,
        label="mean ± standard deviation",
    )
    axis.set_xticks(indexes)
    axis.set_xlabel("Sample")
    axis.set_ylabel("Current (A)")
    axis.set_title(ammeter_type)
    axis.legend()
    figure.savefig(path)
    plt.close(figure)
