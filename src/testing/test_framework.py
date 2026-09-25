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
        return request_current_from_ammeter(ammeter["port"], ammeter["command"].encode("utf-8"))

    def collect_samples(self, ammeter_type: str) -> list[float]:
        count, frequency, _duration = self._resolve_sampling()
        period = 1.0 / frequency
        start = time.monotonic()
        samples = []
        for index in range(count):
            self._wait_until(start + index * period)
            self._simulated_error(ammeter_type, index + 1)
            samples.append(self.run_test(ammeter_type))
        return samples

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
            count = _whole_count(duration * frequency)

        if frequency is None:
            frequency = count / duration
        elif duration is None:
            duration = count / frequency

        expected_duration = count / frequency
        if abs(duration - expected_duration) > 1e-6:
            raise ValueError(
                f"Sampling settings disagree: duration should be {expected_duration}, got {duration}"
            )
        return count, frequency, expected_duration

    def analyze(self, ammeter_type: str) -> dict:
        samples = self.collect_samples(ammeter_type)
        metrics = self.config["analysis"]["statistical_metrics"]
        return {"samples": samples, **summarize_samples(samples, metrics)}

    def record_run(self, ammeter_type: str) -> dict:
        analysis = self.analyze(ammeter_type)
        run_id = uuid.uuid4().hex
        record = {
            "run_id": run_id,
            "ammeter_type": ammeter_type,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "sampling": self.config["testing"]["sampling"],
            "samples": analysis["samples"],
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

        (directory / f"{run_id}.json").write_text(json.dumps(record), encoding="utf-8")
        return record

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
            if run["run_id"] != record["run_id"] and run["started_at"] < record["started_at"]
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
        plot_types = visualization.get("plot_types") or []
        return bool(visualization.get("enabled")) and "samples" in plot_types

    def rank_meters(self) -> list[dict]:
        ranked = []
        for ammeter_type in self.config["ammeters"]:
            analysis = self.analyze(ammeter_type)
            mean = analysis["mean"]
            standard_deviation = analysis["standard_deviation"]
            if mean == 0:
                raise ValueError(f"{ammeter_type} mean is 0, so relative spread is undefined")
            ranked.append({
                "ammeter_type": ammeter_type,
                "mean": mean,
                "standard_deviation": standard_deviation,
                "coefficient_of_variation": standard_deviation / abs(mean),
            })
        return sorted(ranked, key=lambda row: row["coefficient_of_variation"])

    def _simulated_error(self, ammeter_type: str, sample_number: int) -> None:
        simulation = self.config.get("error_simulation") or {}
        if not simulation.get("enabled"):
            return
        mode = simulation.get("mode")
        if mode != "invalid_reading":
            raise ValueError(f"Unknown error simulation mode: {mode}")
        if sample_number != simulation.get("fail_on_sample"):
            return
        raise RuntimeError(
            f"Simulated error on sample {sample_number} for {ammeter_type}: invalid reading"
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
