# Ammeter test framework

Measures current from the Greenlee, ENTES, and CIRCUTOR emulators, saves each run, and ranks the meters by how tightly their readings cluster.

## Setup

```sh
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

`pytest` is the package added for this project. PyYAML and Matplotlib were already in `requirements.txt` and are the ones the framework uses.

## Run a measurement

From the project root:

```sh
python main.py
```

This starts the three emulators, records one run per meter, and prints the ranking. The most consistent meter is first. Rank is standard deviation divided by the mean. Each run is a JSON file and a PNG under `results/`. That folder is gitignored.

A saved example is in `examples/sample_run/`.

## Run the tests

```sh
pytest
```

## Design

One reading works for any meter in the config. Sampling uses the count, duration, and frequency together: duration is count divided by frequency, and the last reading is one period earlier because there is no wait after it. `time.sleep` can wake up late, so the timing check allows a small lateness per gap.

Statistics are mean, median, standard deviation, minimum, and maximum. Standard deviation needs two readings. Thirty was not required.

Each run gets an id, metadata, samples, statistics, and a plot of the readings with the mean and a mean ± standard deviation band. History for one meter can be listed and compared with the last N runs.

The cross-meter rank uses standard deviation divided by the mean. The emulators do not measure one shared current, and their ranges differ by orders of magnitude, so a raw standard deviation would favor the smallest numbers. The winner can change from run to run because every reading is random.

Error simulation is off unless `error_simulation.enabled` is true. Then the sample numbered by `fail_on_sample` fails instead of calling the meter.

## Meters

Greenlee, port 5000, `I = V / R`. ENTES, port 5001, `I = B × K`. CIRCUTOR, port 5002, `I = Σ V·dt`.