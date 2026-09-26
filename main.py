import sys

from Ammeters.client import CURRENT_UNIT
from src.testing.test_framework import AmmeterTestFramework, RunFailed
from src.utils.emulators import start_emulators

SEPARATOR = "------------------------------------------------------------"


def run(framework: AmmeterTestFramework) -> int:
    """Record one run per configured meter, rank the ones that finished, report the rest. Returns the exit code."""
    records, failures = [], []
    for name in framework.config["ammeters"]:
        try:
            records.append(framework.record_run(name))
        except RunFailed as error:
            failures.append((name, error))

    for place, record in enumerate(framework.rank_records(records), start=1):
        comparison = framework.compare_to_previous(record)
        print(
            f"{SEPARATOR}\n"
            f"{place}. {record['ammeter_type']}: "
            f"mean {record['mean']:.4f} {CURRENT_UNIT}, "
            f"median {record['median']:.4f} {CURRENT_UNIT}, "
            f"std {record['standard_deviation']:.4f} {CURRENT_UNIT}, "
            f"min {record['minimum']:.4f} {CURRENT_UNIT}, "
            f"max {record['maximum']:.4f} {CURRENT_UNIT}, "
            f"relative spread {record['coefficient_of_variation']:.4f}, "
            f"plot {record['plot']}"
        )
        compared = comparison["compared"]
        if not compared:
            print("no earlier runs")
            continue
        print(f"compared with {len(compared)} of {comparison['previous_count']} earlier runs:")
        for earlier in compared:
            print(
                f"  {earlier['run_id']}: "
                f"mean {earlier['mean_difference']:+.4f} {CURRENT_UNIT}, "
                f"std {earlier['standard_deviation_difference']:+.4f} {CURRENT_UNIT}"
            )

    for name, error in failures:
        print(
            f"{SEPARATOR}\n"
            f"FAILED {name} on sample {error.sample_number}: {error} "
            f"({len(error.readings)} samples saved)"
        )
    return 1 if failures else 0


def main() -> int:
    framework = AmmeterTestFramework()
    start_emulators(framework.config, wait_seconds=5)
    return run(framework)


if __name__ == "__main__":
    sys.exit(main())
