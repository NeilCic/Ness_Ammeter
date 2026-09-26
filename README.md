# Ammeter test framework

Measures current from the Greenlee, ENTES, and CIRCUTOR emulators through one interface, samples each meter on a schedule, computes statistics, saves every run with an id and a plot, compares a run with the meter's history, and ranks the meters by how tightly their readings cluster. A meter that fails mid-run is saved with the samples taken so far, and the other meters still complete.

Requires Python 3.10 or newer.

## Setup

```sh
python -m venv venv
```

Windows:

```sh
venv\Scripts\activate
```

macOS and Linux:

```sh
source venv/bin/activate
```

```sh
pip install -r requirements.txt
```

### Libraries

`requirements.txt` originally listed numpy, scipy, matplotlib, seaborn, pyyaml, and pandas. Only PyYAML (config) and Matplotlib (plots) are used, so the rest were removed to keep dependencies minimal. `pytest` was added for the test suite. Everything else is the standard library: `socket`, `threading`, `statistics`, `json`, `uuid`, `logging`, `datetime`, `pathlib`.

## Run a measurement

From the project root:

```sh
python main.py
```

This starts the three emulators in daemon threads, records one run per meter listed in `config/config.yaml`, prints the ranking (most consistent meter first), and for each meter prints the difference from its most recent earlier runs. Meters that failed are listed after the ranking. The exit code is 0 if every meter finished and 1 if any failed.

Example output:

```
GreenleeAmmeter is running on port 5000
EntesAmmeter is running on port 5001
CircutorAmmeter is running on port 5002
------------------------------------------------------------
1. circutor: mean 0.0285 A, median 0.0306 A, std 0.0123 A, min 0.0141 A, max 0.0415 A, relative spread 0.4326, plot b33b537333c145c49ef0c4813699427e.png
no earlier runs
------------------------------------------------------------
2. entes: ...
```

On later runs each meter is also compared with its most recent earlier runs:

```
compared with 2 of 2 earlier runs:
  b256c9c1b3a84af8b6886e61c5aa5bbd: mean +0.0069 A, std +0.0008 A
  ...
```

Each run writes a JSON record and a PNG under `results/` (gitignored). To see every request and the emulators' internal values, change the level in `main.py` to `logging.DEBUG`.

## Run the tests

```sh
pytest
```

The suite starts the emulators once per session and runs 22 tests: one reading per meter, sampling schedule and timing, rejected sampling settings, unknown meter, statistics, saving and loading runs, history comparison, ranking, a silent meter, a dead port, non-numeric and non-finite replies, simulated failures, a real failure saved with partial samples, and `main.py` continuing past a failed meter. A session log narrating each test is written to `results/logs/`.

## Configuration

Everything is driven by `config/config.yaml`:

| Key | Meaning |
|---|---|
| `testing.request_timeout_seconds` | How long to wait for a meter to answer one request. |
| `testing.sampling.measurements_count` | Number of samples per run. |
| `testing.sampling.total_duration_seconds` | Time from the first sample to the last. |
| `testing.sampling.sampling_frequency_hz` | Samples per second. |
| `ammeters.<name>.port` / `.command` | Where each meter listens and what to send it. Add a meter by adding an entry here. |
| `analysis.statistical_metrics` | Which of `mean`, `median`, `standard_deviation`, `minimum`, `maximum` to compute. |
| `analysis.visualization.enabled` | Save a PNG per run. |
| `result_management.directory` | Where runs are saved. |
| `result_management.compare_with_last` | How many earlier runs to compare a new run against. |
| `error_simulation.enabled` / `.mode` / `.fail_on_sample` | Make the sample numbered `fail_on_sample` fail instead of calling the meter. The only mode is `invalid_reading`. |

Any two of the three sampling settings are enough; the third is derived. If all three are given they must agree (see Design).

## Results

Every run that starts gets a record `results/<run_id>.json`:

```json
{
  "run_id": "5a9b886d0dfc4de1bf29992f92fbaabc",
  "ammeter_type": "entes",
  "unit": "A",
  "started_at": "2026-09-26T15:52:00.386853+00:00",
  "sampling": {"measurements_count": 5, "total_duration_seconds": 0.4, "sampling_frequency_hz": 10},
  "samples": [173.780, 98.275, 32.695, 158.837, 66.680],
  "sample_times": ["2026-09-26T15:52:00.386853+00:00", "..."],
  "mean": 106.053, "median": 98.275, "standard_deviation": 59.928,
  "minimum": 32.695, "maximum": 173.780,
  "plot": "5a9b886d0dfc4de1bf29992f92fbaabc.png"
}
```

A run that failed has the samples taken before the failure, no statistics or plot, and an `error` object instead:

```json
"error": {"kind": "simulated", "sample_number": 4, "message": "Simulated error on sample 4 for greenlee: invalid reading"}
```

`kind` is `"meter"` when the request failed (unreachable, silent, or a reply that is not a finite number) and `"simulated"` when error simulation caused it.

From Python:

```python
framework = AmmeterTestFramework()
framework.load_run(run_id)                 # one record
framework.list_runs("greenlee")            # every Greenlee record, oldest first
framework.compare_to_previous(record)      # mean and std differences from the last N finished runs
framework.rank_records(records)            # adds coefficient_of_variation and sorts by it
```

## Sample results

`examples/sample_run/` holds one run of `main.py` with the default config: a JSON record and a plot per meter, and `console_output.txt` with what was printed.

## Design

**One interface for every meter.** `run_test(ammeter_type)` looks up the port and command in the config and asks the meter for one reading. Adding a meter is a config entry plus an emulator class in `src/utils/emulators.py`. An unknown name raises `ValueError` listing the known ones.

**Sampling.** N samples span `(N - 1) / frequency` seconds: the first reading is immediate, then one per period, with no wait after the last. Five samples at 10 Hz last 0.4 s. Any two settings are enough; if all three are set and disagree the run is rejected rather than silently picking one. Each sample waits until its scheduled time with `time.monotonic()`, so drift does not accumulate, and each record stores the time every sample was taken. `time.sleep` can wake up late, so the timing test allows a small lateness per gap.

**Statistics.** Mean, median, sample standard deviation, minimum, maximum, from the standard library. Standard deviation needs two readings, so `measurements_count` must be at least 2.

**Ranking.** Meters are ranked by coefficient of variation (standard deviation divided by mean). This measures how tightly a meter repeats, not closeness to a true current: the emulators do not share one reference current, and their ranges differ by orders of magnitude, so a raw standard deviation would favor the smallest numbers. The winner can change from run to run because every reading is random.

**Failures.** The client (`Ammeters/client.py`) turns every wire problem into `AmmeterError` with a specific message: no meter listening on the port, no reply within the timeout, an empty reply, a reply that is not a number, or a non-finite number. `connect` and `send/recv` are separate `try` blocks because Windows reports a dead port as a timeout, so the position of the failure is the only way to tell "nothing listening" from "listening but silent". The framework prefixes the meter name. Inside a run, an `AmmeterError` or a simulated failure becomes `RunFailed`, which carries the samples taken so far; `record_run` saves them with an `error` object and re-raises. `main.py` catches `RunFailed` per meter, ranks the meters that finished, lists the failures, and exits 1. Comparison skips saved runs that have an error.

**Error simulation.** Off unless `error_simulation.enabled` is true. Then the sample numbered `fail_on_sample` raises instead of calling the meter. It exercises the same `RunFailed` path as a real meter failure.

**Logging.** The emulators and client log through `logging` (`ammeters` and `ammeters.client`), so `main.py` output is the report and three startup lines. Tests write a narrated session log to `results/logs/` through `src/utils/logger.py`.

## Fixes to the provided code

- `main.py` started the emulators on ports 5001–5003 and requested from those ports with the commands `MEASURE_GREENLEE`, `MEASURE_ENTES`, `MEASURE_CIRCUTOR`. The README documents ports 5000–5002 and commands like `MEASURE_GREENLEE -get_measurement`; the emulators only answer the exact command, so every request got an empty reply. Ports and commands now come from `config/config.yaml`.
- `Ammeters/Circutor_Ammeter.py` expected `MEASURE_CIRCUTOR -get_measurement -current`, but the README documents `MEASURE_CIRCUTOR -get_measurement`. The emulator was changed to match the README.
- `Ammeters/client.py` printed the reading and returned `None`, had no timeout, and printed "No data received." on an empty reply. It now returns a `float`, times out, and raises `AmmeterError` for every failure.
- `Ammeters/base_ammeter.py` bound the port inside the server thread, so a port already in use only printed a traceback from that thread while `main.py` carried on and then timed out. Binding now happens in the caller's thread and raises `OSError("Port N is already taken")` before the thread starts.
- The emulators printed every connection and their internal values to stdout. Those messages go through `logging` at DEBUG now.
- `src/testing/test_framework.py` annotated `run_test` as `-> Dict` without importing `Dict`, so the module raised `NameError` on import.
- `src/utils/logger.py` created a logger but never attached a handler, formatter, or level, so it wrote nothing. Rewritten to write to `results/logs/`.
- `examples/run_tests.py` called `framework.run_test()` with no argument and the README said not to use it. Removed.
- `config/config.yaml` had every value `NULL` or commented out. Filled in; the empty `plot_types` list was dropped since there is one plot.
- `requirements.txt` listed four unused libraries. See Libraries above.

## Meters

| Meter | Port | Command | Model |
|---|---|---|---|
| Greenlee | 5000 | `MEASURE_GREENLEE -get_measurement` | Ohm's law, `I = V / R` |
| ENTES | 5001 | `MEASURE_ENTES -get_data` | Hall effect, `I = B × K` |
| CIRCUTOR | 5002 | `MEASURE_CIRCUTOR -get_measurement` | Rogowski coil, `I = Σ V·dt` |

## Project structure

```
main.py                        run every meter, rank, report, exit code
config/config.yaml             all settings
Ammeters/                      the emulators (provided) and the socket client
src/testing/test_framework.py  sampling, statistics, saving, comparison, ranking, plots
src/utils/emulators.py         start the emulators from the config
src/utils/config.py            load the YAML
src/utils/logger.py            narrated test log
tests/                         pytest suite and session fixture
examples/sample_run/           one saved run and its console output
```
