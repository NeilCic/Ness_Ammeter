from src.testing.test_framework import AmmeterTestFramework
from src.utils.emulators import STARTERS, start_emulators

if __name__ == "__main__":
    framework = AmmeterTestFramework()
    start_emulators(framework.config, wait_seconds=5)

    records = [framework.record_run(name) for name in STARTERS]

    def relative_spread(record: dict) -> float:
        return record["standard_deviation"] / abs(record["mean"])


    ranking = sorted(records, key=relative_spread)
    for place, record in enumerate(ranking, start=1):
        print(
            "------------------------------------------------------------\n"
            f"{place}. {record['ammeter_type']}: "
            f"mean {record['mean']:.4f} A, "
            f"std {record['standard_deviation']:.4f}, "
            f"relative spread {relative_spread(record):.4f}, "
            f"plot {record['plot']}"
        )
