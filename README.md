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
| 1 | Instance generator (Greater Santiago polygon, R/C/RC families, window profiles, fleet sizing, seed solutions); the 108-instance set under `instances/` | **done** |
| 2 | Maps (PNG + HTML) and x-t Gantt plots; `bench plot` | **done** |
| 3 | Clarke-Wright + local search | next |
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
pytest -q                   # 67 tests
```

Hexaly is optional: `pip install hexaly` plus a license key, see Phase 5.

## Usage

```bash
bench info instances/RC-400-T-105.json                      # summary of an instance
bench validate instances/RC-400-T-105.seed.json --instance instances/RC-400-T-105.json
bench validate tests/data/broken_capacity.json --instance tests/data/toy_instance.json

bench generate                                              # regenerate the 108-instance set (deterministic)
bench generate --sizes 100,200 --families R --out /tmp/small # a subset
bench generate --only C-600-T-85 --out /tmp/one              # one instance

bench plot instances/RC-400-T-105.seed.json --instance instances/RC-400-T-105.json --out results/plots/RC-400-T-105
#   -> map.png (routes over a light-gray Esri basemap; needs internet once, tiles are cached in .tile_cache/)
#      map.html (Leaflet: one toggleable layer per route, tooltips with the schedule of every stop)
#      gantt.png (x-t diagram: one row per vehicle, travel / waiting / service bars and each
#                 customer's time window as a bracket; unserved customers' windows at the bottom)
#   --basemap esri-gray|osm|esri-street|carto|none selects the tiles (keyless: esri-gray, osm,
#   esri-street; CartoDB requires an API key since 2026 and otherwise returns watermarked tiles);
#   when no provider answers the map falls back to plain axes with the urban polygon outline.
#   --dpi 300 is the default. results/ is git-ignored, a convenient place for outputs.
```

Colour is the same in every figure: blue = small vehicle, orange = medium, aqua = large,
hollow red = unserved customer, black square = depot. Routes are drawn as straight segments
between stops because the benchmark's travel model is great-circle × 1.3, not the road network.

## The instance set

`instances/` holds the benchmark set: 108 instances = 4 sizes (100, 200, 400, 600 customers) ×
3 spatial families (R uniform, C clustered, RC mixed) × 3 time-window profiles (L loose, M mixed,
T tight) × 3 capacity-stress levels (60 %, 85 %, 105 % of fleet capacity), named
`{family}-{n}-{profile}-{stress}`, plus `index.csv` with the factors and statistics of each one.
Every instance is regenerated bit-for-bit from `configs/generator.default.yaml` and its name
(`seed = sha256(global_seed, name)`).

* **Geography.** Depot and customers are sampled inside `src/cvrptw_bench/data/santiago_urban.geojson`,
  a hand-digitised envelope (~790 km²) of the consolidated urban area of Greater Santiago traced along
  the 2017 census urban limit — it keeps Quilicura, Huechuraba, La Dehesa, Las Condes, Peñalolén,
  La Florida, Puente Alto, San Bernardo, Maipú and Pudahuel and leaves out the airport, the foothills
  and the rural fringe. It is an approximation for synthetic instances, not an official boundary; swap
  the file to use another one. The depot is random per instance (its distance to the customer
  centroid is in the metadata: central depots and edge depots are both in the set).
* **Loads and fleet.** 90 % of orders are 10–60 units, 10 % are 200–1 000 units (they do not fit the
  small vehicle). Three vehicle types — small 800 / medium 1 600 / large 3 200 units, fixed cost
  20 000 / 30 000 / 45 000 CLP per vehicle used and 350 / 500 / 700 CLP per km — in blocks of 3:2:1,
  sized so that total demand ÷ fleet capacity hits the stress level (achieved values 0.59–0.61,
  0.82–0.86 and 1.01–1.07 across the set).
* **Time windows.** Whole minutes inside 10:00–18:00, three width classes (wide 4–8 h, medium 1.5–3 h,
  tight 30–60 min) mixed per profile (L = 70/20/10 %, M = 33/33/34 %, T = 10/20/70 %) and centred on
  the arrival times of a *seed solution* (sweep + nearest-neighbour/2-opt + repair) built on the
  real fleet. Consequences: no customer is ever unreachable; at 60 % stress the seed serves everyone,
  so a full-coverage solution is known to exist; at 105 % the leftovers are over-subscription by
  design. The seed solution is stored next to each instance (`*.seed.json`) and is a baseline row in
  the report — solvers never read it.
* **Two stress measures.** Besides capacity stress, `time_stress_est` (busy time of the seed routes ÷
  fleet-hours) is stored, because with tight windows the binding resource is often time, not capacity.

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
  core/       instance.py  matrices.py  solution.py  validator.py  insertion.py
  generator/  config.py  geo.py  sampling.py  demand.py  seed_solution.py  windows.py  generate.py
  data/       santiago_urban.geojson
  solvers/    base.py  (adapters arrive in Phases 3-5)
  viz/        style.py  map_static.py  map_html.py  gantt.py
  report/     (Phase 6)
  cli.py      bench info | validate | generate | plot | version  (+ solve | run | report later)
configs/      generator.default.yaml  run.default.yaml
tests/        pytest suite; tests/data holds a hand-checked toy instance and broken solutions
instances/    the 108-instance benchmark set + seed solutions + index.csv
results/      run outputs (git-ignored except final summaries)
```

## License

MIT — see [LICENSE](LICENSE).
