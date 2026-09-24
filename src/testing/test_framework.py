import time

from Ammeters.client import request_current_from_ammeter
from ..utils.config import load_config


class AmmeterTestFramework:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = load_config(config_path)
        
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
