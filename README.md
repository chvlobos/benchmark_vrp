# CVRPTW-HF Benchmark — Santiago, Chile

Capacitated Vehicle Routing with Time Windows and a **heterogeneous fleet**, on synthetic
instances located in Greater Santiago, solved three ways and compared on identical numbers:

| Method | What it is |
|---|---|
| `cw` | Own Clarke-Wright savings heuristic, extended to time windows and vehicle types, randomised multi-start |
| `cw_ls` | The same, followed by a variable-neighbourhood local search |
| `ortools` | Google OR-Tools Routing (PATH_CHEAPEST_ARC + Guided Local Search) |
| `hexaly` | Hexaly Optimizer (list-variable model) — pending an evaluation license |

The full design and the phased plan are in [PLAN.md](PLAN.md).

## Status

| Phase | Content | State |
|---|---|---|
| 0 | Repository skeleton, shared core (instance schema, integer matrices, solution schema), independent validator, CLI `info`/`validate`, tests, CI | **done** |
| 1 | Instance generator (Greater Santiago polygon, R/C/RC families, window profiles, fleet sizing, seed solutions) | next |
| 2 | Maps (PNG + HTML) and x-t Gantt plots | |
| 3 | Clarke-Wright + local search | |
| 4 | OR-Tools adapter | |
| 5 | Hexaly adapter | |
| 6 | Full run, HTML report | |

## Requirements

**Python 3.11** (CPython 3.11.x). Everything in this repository — the pinned
`requirements.txt`, the CI job and the published results — uses this version. Do not run
it with whatever `python` happens to be first on your PATH.

Check that you have it:

```bash
python3.11 --version        # must print Python 3.11.x
```

If it is missing, on macOS either

```bash
brew install python@3.11    # Homebrew; provides the python3.11 command
```

or, with pyenv, `pyenv install 3.11` (the repo ships a `.python-version` file that selects it
automatically inside the project folder).

## Install

```bash
cd vrp_test_stgo
python3.11 -m venv .venv
source .venv/bin/activate
python --version            # Python 3.11.x — inside the venv, `python` is now 3.11
pip install --upgrade pip
pip install -r requirements.txt -e ".[dev]"
pytest -q                   # 49 tests
```

Hexaly is optional: `pip install hexaly` plus a license key, see Phase 5.

## Usage (Phase 0)

```bash
bench info tests/data/toy_instance.json                     # summary of an instance
bench validate tests/data/toy_solution.json --instance tests/data/toy_instance.json
bench validate tests/data/broken_capacity.json --instance tests/data/toy_instance.json
```

`bench validate` re-evaluates a solution **from the visiting orders only**: it recomputes
schedules, loads, distances and costs with the shared integer matrices, lists every violation
(capacity, time window, horizon, unknown vehicle/customer, duplicated customer), reports
discrepancies between the stored and recomputed numbers, and classifies each unserved
customer (`insertable`, `capacity`, `time_window`, `unreachable_window`, `oversized`).
Exit code 0 = valid and consistent, 1 = not.

## Design principles (short version)

* **One cost model.** `cvrptw_bench.core.matrices` computes Haversine × 1.3 distances in metres,
  travel times in seconds at 30 km/h and per-type arc costs in CLP, rounded once. Every solver
  and the validator use these integers; nobody recomputes distances.
* **One judge.** A solver returns only a plan (vehicle → ordered customers). The validator
  computes everything else, and its verdict is what the report shows.
* **Lexicographic objective.** Maximise customers served, then minimise total cost
  (fixed cost per vehicle used + cost per km by vehicle type). Time windows are hard; waiting
  is free; one trip per vehicle; back at the depot before closing.

## Layout

```
src/cvrptw_bench/
  core/       instance.py  matrices.py  solution.py  validator.py
  solvers/    base.py  (adapters arrive in Phases 3-5)
  generator/  viz/  report/  (Phases 1, 2, 6)
  cli.py      bench info | validate | version  (+ generate | plot | solve | run | report later)
configs/      generator.default.yaml  run.default.yaml
tests/        pytest suite; tests/data holds a hand-checked toy instance and broken solutions
instances/    generated benchmark set (Phase 1)
results/      run outputs (git-ignored except final summaries)
```

## License

MIT — see [LICENSE](LICENSE).
