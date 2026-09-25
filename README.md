# Ammeter test framework

Measures current from the Greenlee, ENTES, and CIRCUTOR emulators, saves each run, and ranks the meters by how tightly their readings cluster.

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

`pytest` is the package added for this project. PyYAML and Matplotlib were already in `requirements.txt` and are the ones the framework uses.

## Run a measurement

From the project root:

```sh
python main.py
```

This starts the three emulators, records one run per meter, and prints the ranking. The most consistent meter is first. Rank is standard deviation divided by the mean. Current is in amperes. Each run is a JSON file and a PNG under `results/`. That folder is gitignored. Pytest writes a session log under `results/logs/`.

A saved example of one of those runs is in `examples/sample_run/`.

## Run the tests

```sh
pytest
```

## Design

One reading works for any meter in the config. The original `main.py` called the wrong ports and sent commands that did not match the emulators. The ports and commands now come from `config/config.yaml`.

Sampling uses the count, duration, and frequency together. N samples span `(N - 1) / frequency` seconds: the first reading is immediate, then one per period, with no wait after the last. Five samples at 10 Hz last 0.4 s, and the config has to match that span. `time.sleep` can wake up late, so the timing check allows a small lateness per gap.

`started_at` is the moment collection begins. Each sample also stores the time its wait finished. Statistics are mean, median, standard deviation, minimum, and maximum, and the record says `"unit": "A"`. Standard deviation needs two readings.

Each finished run gets an id, that metadata, the samples, the statistics, and a plot of the readings with the mean and a mean ± standard deviation band. History for one meter can be listed and compared with the last N runs.

The cross-meter rank uses standard deviation divided by the mean. This measures how tightly a meter repeats, not closeness to a true current. The emulators do not share one reference current, and their ranges differ by orders of magnitude, so a raw standard deviation would favor the smallest numbers. The winner can change from run to run because every reading is random.

A meter request gives up after `request_timeout_seconds` with no reply. Starting the emulators when a port is already taken raises before any emulator thread starts.

Error simulation is off unless `error_simulation.enabled` is true. Then the sample numbered by `fail_on_sample` fails instead of calling the meter. The samples taken before that failure are saved with an `error` object and no statistics, and the exception is raised again. Comparison skips a saved run that has an error.

## Meters

Greenlee, port 5000, `I = V / R`. ENTES, port 5001, `I = B × K`. CIRCUTOR, port 5002, `I = Σ V·dt`.
