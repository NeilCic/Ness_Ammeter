from src.testing.test_framework import AmmeterTestFramework
from src.utils.emulators import STARTERS, start_emulators

if __name__ == "__main__":
    framework = AmmeterTestFramework()
    start_emulators(framework.config, wait_seconds=5)

    records = [framework.record_run(name) for name in STARTERS]
    for place, record in enumerate(framework.rank_records(records), start=1):
        comparison = framework.compare_to_previous(record)
        print(
            "------------------------------------------------------------\n"
            f"{place}. {record['ammeter_type']}: "
            f"mean {record['mean']:.4f} A, "
            f"median {record['median']:.4f} A, "
            f"std {record['standard_deviation']:.4f}, "
            f"min {record['minimum']:.4f} A, "
            f"max {record['maximum']:.4f} A, "
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
                f"mean {earlier['mean_difference']:+.4f} A, "
                f"std {earlier['standard_deviation_difference']:+.4f}"
            )
