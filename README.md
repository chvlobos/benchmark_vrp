# CVRPTW-HF Benchmark — Santiago, Chile

Capacitated Vehicle Routing with Time Windows and a **heterogeneous fleet**, on synthetic
instances located in Greater Santiago, solved four ways and compared on identical numbers:

| Method | What it is |
|---|---|
| `cw` | Own Clarke-Wright savings heuristic, extended to time windows and vehicle types, randomised multi-start |
| `cw_ls` | The same, followed by a variable-neighbourhood local search |
| `ortools` | Google OR-Tools Routing (PATH_CHEAPEST_ARC + Guided Local Search) |
| `hexaly` | Hexaly Optimizer 15 (list-variable model), single thread |

The full design and the phased plan are in [PLAN.md](PLAN.md).

## Status

| Phase | Content | State |
|---|---|---|
| 0 | Repository skeleton, shared core (instance schema, integer matrices, solution schema), independent validator, CLI `info`/`validate`, tests, CI | **done** |
| 1 | Instance generator (Greater Santiago polygon, R/C/RC families, window profiles, fleet sizing, seed solutions); the 108-instance set under `instances/` | **done** |
| 2 | Maps (PNG + HTML) and x-t Gantt plots; `bench plot` | **done** |
| 3 | Clarke-Wright (`cw`) and Clarke-Wright + local search (`cw_ls`); `bench solve` | **done** |
| 4 | OR-Tools adapter (`ortools`) | **done** |
| 5 | Hexaly adapter (`hexaly`) | **done** — Hexaly 15 Python SDK, soft/hard time-window modes; its tests run when a license is present |
| 6 | Resumable full run (`bench run`), HTML report with conclusions (`bench report`); the four-solver run on the 108 instances in `results/final/` | **done** |

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
pytest -q                   # 104 tests (9 of them skipped without a Hexaly license)
```

The `hexaly` package installs with the requirements, but solving needs a license
(evaluation or commercial):

```bash
export HX_LICENSE_PATH=/absolute/path/to/license.dat
pytest -q tests/test_hexaly.py -ra
```

The nine license-dependent tests must show as *passed*, not *skipped* (a skip means the
license was not found). `HX_LICENSE_PATH` must be set in every shell that runs `bench`
(or put the file where Hexaly looks by default, `/opt/hexaly_15_0/license.dat`, or set
`hexaly.license_path` in `configs/run.default.yaml`). `HX_LICENSE_CONTENT` with the key text
itself also works. See the Hexaly section below for the model.

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

```bash
bench solve instances/RC-400-T-105.json --solver cw_ls          # -> results/solve/RC-400-T-105/cw_ls/
bench solve instances/RC-400-T-105.json --solver cw --time-limit 30 --no-plots --out /tmp/x
```

`bench solve` runs one solver on one instance with the time limit of its size tier
(`configs/run.default.yaml`: 60 s up to 200 customers, 120 s up to 400, 180 s up to 600),
evaluates the plan with the validator and writes `solution.json` plus the three plots.
**The same limit applies to every solver** — it is a cap: `cw` finishes its 20 starts in
seconds and reports that; `cw_ls`, OR-Tools and Hexaly use it fully.

### The full benchmark: `bench run` and `bench report`

```bash
bench run --out results/full --solvers cw,cw_ls,ortools --workers 2 --no-plots
bench run --out results/full --solvers cw,cw_ls,ortools --sizes 100,200      # a subset
bench run --out results/final --solvers hexaly --workers 2 --no-plots       # adds a solver to an existing run (resume)
bench report results/full                                                    # -> results/full/report.html + tables/*.csv
bench report results/final --gallery 3 --basemap esri-gray                   # rebuild the published report
```

`bench run` solves every instance under `instances/` with every solver named, instances in
order of size then name, and writes `results/full/{instance}/{solver}/solution.json` (plus the
plots unless `--no-plots`), one line per job in `log.jsonl`, and `run_meta.json` with the host,
package versions, configuration and worker count. It is **resumable**: a job whose
`solution.json` exists with status `feasible` is skipped, so an interrupted run continues where
it stopped and a solver added later (Hexaly) only runs its own missing jobs. `--workers N` runs
N jobs in parallel processes; every solver stays single-threaded, so keep N ≤ physical cores
if wall times are to be compared. `--no-resume` redoes everything.

`bench report` re-reads the solutions (never the log), joins the instance factors and the
generator's seed solutions, computes coverage-first gaps — the best known coverage per instance
is the maximum served among valid results, a result below it gets a coverage deficit and no
cost gap, among results at best coverage the gap is `cost / best cost − 1` — and writes a
self-contained `report.html` (Plotly inlined, no internet needed to view it) with overall and
per-factor tables and box plots, performance profiles, time-to-best, convergence traces, a small
gallery of maps and Gantt charts, data-driven conclusions and a "which tool when" section, plus
CSV twins of every table under `tables/`. Instances that lack a result from one of the solvers
present are left out of the page (and listed), so a half-finished run never biases the averages.

## Results (cw, cw_ls, ortools, hexaly)

The published run: 108 instances × 4 solvers = 432 results, all valid, one common wall-clock
cap per size (60 / 60 / 120 / 180 s), seed 42, single thread each, 2 parallel workers on the
same 2-core Linux box (Python 3.11.15, OR-Tools 9.15, Hexaly 15.0; a CPU probe recorded in
`run_meta.json` confirms two concurrent jobs get two full cores). The three open-source columns
were run on 2026-09-02; the Hexaly column was added on 2026-09-16 with the template's
disjoint-list formulation and replaced on 2026-09-23 by the dummy-list formulation (see
*Modelling choices for Hexaly* below), each time with `bench run` on the same run directory —
nothing else was recomputed. The report is [`results/final/report.html`](results/final/report.html)
(self-contained, open it in a browser) and the tables are in `results/final/tables/`;
`results/final/` is the complete run directory — every `solution.json` (re-validate any of
them with `bench validate`), `log.jsonl` and `run_meta.json` — minus the plots, so
`bench report results/final` rebuilds the page. Gaps are coverage-first: the best known
coverage per instance is the maximum served among valid results (seed included); a result
below it counts a coverage deficit and no cost gap; among results at best coverage,
gap = cost / best cost − 1.

| Solver | Instances at best coverage | Customers missed (sum) | Best cost (wins) | Mean cost gap | Median | Worst | Mean time to best |
|---|---|---|---|---|---|---|---|
| OR-Tools | 108 / 108 | 0 | 57 | 1.2 % | 0.0 % | 9.5 % | 79 s |
| Hexaly (1 thread) | 79 / 108 | 46 | 39 | 1.7 % | 0.2 % | 13.0 % | 87 s |
| CW + local search | 89 / 108 | 24 | 12 | 3.5 % | 3.3 % | 12.8 % | 48 s |
| Clarke-Wright | 80 / 108 | 71 | 0 | 20.0 % | 19.7 % | 52.8 % | 0.3 s (wall 0.9 s) |

What the numbers say, in short:

* **On cost, Hexaly and OR-Tools are at parity; on coverage, OR-Tools wins.** Head to head on
  the 108 instances, OR-Tools serves more customers on 29 and fewer on none; at equal
  coverage Hexaly is cheaper on 44 and dearer on 35, +0.3 % on average and −0.4 % in median
  (range −8.7 % to +13.0 %). Hexaly's cost gap shrinks with size (3.5 % at n = 100 → 0.7 % at
  n = 600) while OR-Tools' grows (0.6 % → 1.6 %); by outright wins it is 15 / 18 / 12 / 12 for
  OR-Tools against 6 / 6 / 13 / 14 for Hexaly by size. Under the benchmark's own objective —
  coverage first — OR-Tools is still the reference, because 45 of Hexaly's 46 missed customers
  are on the over-subscribed (105 %) instances, where it reaches the best known coverage on
  only 8 of 36 (and on those 8 its gap is 1.5 %).
* **Hexaly beats the own heuristic on cost, not on coverage.** Against CW + local search it is
  cheaper on 63 and dearer on 23 at equal coverage (−1.8 % on average, −2.5 % in median) and
  serves more customers on 2 instances, fewer on 20.
* **The own heuristic is close but not equal.** CW + local search is within 3.5 % on average
  and at full coverage everywhere at 60 % and 85 % stress; the 24 customers it misses are all
  on 105 % instances, where OR-Tools consolidates one or two more customers into the same
  fleet. Its gap grows with tighter windows (2.2 % on L → 4.5 % on T).
* **Both solvers are still improving at n = 600** (time to best 150 s of 180 for OR-Tools,
  164 s for Hexaly on average), so the gaps at the largest size say as much about the limit as
  about the methods — the reason for the 360 s experiment below.
* **Local search is what makes the heuristic usable.** Plain Clarke-Wright is 15.7 % more
  expensive than CW + LS at equal coverage and misses 71 customers, but answers in about a
  second; a first plan or a warm start, not an optimiser.
* **Everything is reproducible and re-judged.** Every result was re-evaluated from its visiting
  orders by the independent validator, and on all 432 results the (served, cost) the solver
  itself reported for its final solution — OR-Tools' objective net of the drop penalties,
  Hexaly's objective values — equals what the validator recomputed.

### Secondary experiments (`results/experiments/`)

Three questions the equal-footing table cannot answer by itself, each a full `bench run`
judged against `results/final` with `bench compare` (details, per-instance CSVs and the
reproduction commands in [`results/experiments/README.md`](results/experiments/README.md)):

* **Is the objective's shape the reason Hexaly misses customers?** No. With one penalised
  scalar (cost + P × unserved, the shape OR-Tools optimises) instead of the lexicographic pair,
  Hexaly missed 56 customers instead of 51 and cost +0.02 % at equal coverage
  (`hexaly_penalised/`, disjoint formulation, one thread).
* **What does Hexaly do with the whole machine?** With `nb_threads = 2` — its default setting,
  the two cores any laptop has — and the same limits, it becomes the best method of the table
  on cost and nearly closes the coverage gap: 17 customers missed instead of 46 (best known
  coverage on 93 of 108), best cost on 56 instances against 41 for single-threaded OR-Tools,
  cheaper than OR-Tools on 65 and dearer on 28 at equal coverage (−1.0 % mean, −0.9 % median);
  OR-Tools still serves more customers on 15 instances and fewer on none
  (`hexaly_2threads/`). Not equal footing with the single-threaded columns, and labelled so.
* **Are the n = 600 results a statement about the 180 s limit?** No. With 360 s for every
  solver, each time-bound method improved by the same ≈ 0.6 % and the differences between
  them stayed put: Hexaly vs OR-Tools −1.5 % at equal coverage and behind on coverage on 8 of
  27 instances (at 180 s: −1.4 %, 8); CW + LS vs OR-Tools +1.2 % either way. Both solvers were
  still improving at 360 s (time to best ≈ 315–320 s), so longer limits would move everyone
  again, together (`n600_360s/`, Clarke-Wright as the unchanged control).

**What this says about the license question.** At one thread and these limits, on a textbook
CVRPTW with a heterogeneous fleet, the free OR-Tools Routing library and Hexaly produce plans
of the same cost, OR-Tools squeezes in the last customer more often when the fleet is short,
and the in-house heuristic is 2–3 % behind both; doubling the time limit changes none of that.
Give Hexaly the second core and it is the cheapest method on the set, 1 % under OR-Tools at
equal coverage, with the coverage gap down to 15 customers in 108 instances. Its case is
therefore its default setting and its modelling style — plain arithmetic on list variables,
where any extra business rule is one more expression rather than a new Routing dimension or
callback, and where the formulation choices above were each a one-line change — rather than
single-core quality on a textbook problem, where OR-Tools remains the reference for free.

### Modelling choices for Hexaly

Two documented choices, both made on data at the common limits and one thread — the same kind
of choice that was made for OR-Tools (guided local search):

*Time windows.* Hexaly's own template handles them as a first-priority lateness objective
rather than as constraints (`hexaly.time_windows: soft`, the default); `hard` posts them as
constraints. Compared on three instances (2026-09-16, `configs/run.hexaly_hard.yaml` for the
hard side): soft 200 / 634 804 · **198** / 690 863 · **395** / 1 328 209 against hard
200 / 638 646 · 196 / 692 187 · 394 / 1 309 748 on C-200-M-85 · RC-200-T-105 · R-400-T-105 —
soft wins on all three under the coverage-first objective. Files in
`results/experiments/hexaly_time_windows/`.

*Optional customers.* The template's idiom is one list per vehicle and `disjoint` over them
(a customer may be in no list). The alternative — the vehicle lists plus one extra uncosted,
unconstrained list that collects the unserved customers, under `partition`
(`hexaly.unserved: dummy_list`, now the default) — has the same feasible set and objective,
but on this benchmark Hexaly 15 maintains the partition form about 2.8× faster (iterations
per second) and only parallelises partition models (a `disjoint` model stays on one core
whatever `nb_threads` says; measured, see `results/experiments/README.md`). Compared on all
108 instances at one thread (2026-09-23, `results/experiments/hexaly_dummy/comparison.md`):
the dummy-list formulation is cheaper on 54 instances and dearer on 36 at equal coverage
(−1.1 % on average), misses 46 customers instead of 51 and has the best cost on 33 instead of
13, so it replaced the disjoint column in `results/final/`; the disjoint run is kept whole in
`results/experiments/hexaly_disjoint/`.

**Re-running everything on another machine** (for instance a faster desktop, to see all four
methods more converged at the same limits):

```bash
export HX_LICENSE_PATH=/absolute/path/to/license.dat
bench run --out results/run_$(hostname) --solvers cw,cw_ls,ortools,hexaly --workers 2 --no-plots
bench report results/run_$(hostname) --gallery 3 --basemap esri-gray
```

The run is resumable (Ctrl-C and rerun the same command to continue). Keep `--workers` at or
below the number of *performance* cores so every job gets a full core; on macOS prefix the
run with `caffeinate -i`.

## OR-Tools: `ortools`

`solvers/ortools_solver.py` builds the Routing model on the shared integer matrices: one cost
matrix per vehicle type registered in C++ (`RegisterTransitMatrix`, no Python callbacks in the
search) and assigned per vehicle, `SetFixedCostOfVehicle` so the fixed cost is charged only when
a vehicle is used, a capacity dimension with per-vehicle capacities, and a time dimension whose
cumul is the service start (transit = service at origin + travel, slack = waiting, customer
cumuls inside their windows, vehicle start/end inside the operating horizon, free departure).
Every customer is optional through a disjunction with one uniform penalty larger than any
achievable routing cost, which makes OR-Tools' single objective exactly the benchmark's
lexicographic one: serve as many customers as possible, then minimise cost. This is checked, not
assumed — the tests assert that OR-Tools' objective equals the validator's cost plus penalty ×
dropped on every run. Search: `PATH_CHEAPEST_ARC` first solution + `GUIDED_LOCAL_SEARCH`,
single-threaded, with the common time limit; an at-solution callback records every improvement
for the time-to-best and the convergence trace.

## Hexaly: `hexaly`

`solvers/hexaly_solver.py` follows the list-variable idiom of Hexaly's own CVRPTW example,
on the shared integer matrices. One list variable per vehicle (the fleet expanded to
individual vehicles) and a `disjoint` constraint over the lists, so a customer is visited at
most once and may stay unserved; per vehicle, the load (a `sum` over the list) must fit its
capacity, the service starts are a recursive `array` — `start_0 = max(e, opening + travel)`,
`start_i = max(e_i, start_{i−1} + service + travel)`, i.e. free departure and free waiting —
and the route cost is the fixed cost if the list is not empty plus the arc costs read from the
matrix of the vehicle's type. The windows `start_i ≤ l_i` and the return before closing are
enforced the way Hexaly's own [CVRPTW template](https://www.hexaly.com/templates/vehicle-routing-problem-with-time-windows-cvrptw)
does it: total lateness is a first-priority objective driven to zero (`time_windows: soft`,
the default — it keeps the search space connected), with `time_windows: hard` posting them as
constraints instead; the validator accepts zero lateness only, and a run whose final lateness
is not zero is reported as an error, never as a result. Objectives in lexicographic order:
[minimise lateness,] maximise the customers served, minimise the total cost (`hexaly.objective:
penalised` folds the last two into one scalar, cost + P × unserved, for experiments). Optional customers are
modelled either as disjoint vehicle lists (`hexaly.unserved: disjoint`, the template idiom) or as a partition
of the vehicle lists plus one uncosted "unserved" list (`dummy_list`, the default — see *Modelling choices*). What differs
from the template is what the benchmark demands: `disjoint` instead of `partition` (customers
are optional, so *served* is an objective), per-vehicle capacities and per-type cost matrices
(heterogeneous fleet), fixed cost per vehicle used instead of a vehicle count, and integer
CLP instead of rounded distances. `nb_threads = 1`, the config seed and the common time limit (model build time
counts against it, as for OR-Tools); a `TIME_TICKED` callback records every improvement of the
incumbent for the time-to-best and the convergence trace, and the final (served, cost) Hexaly
reports is asserted equal to the validator's in the tests. Size, as a proxy for modelling
effort (code lines without comments): the Hexaly model is 69 lines and its adapter 145; the
OR-Tools model 42 and its adapter 109; the own heuristic about 890. On a textbook CVRPTW the
Routing library is the more compact of the two solvers — Hexaly's argument is that any extra
business rule is one more expression on the lists rather than a new dimension or callback,
plus multi-threading out of the box (not credited in this single-thread comparison).

## The own heuristic: `cw` and `cw_ls`

`cw` is Clarke-Wright savings adapted to hard time windows and a limited heterogeneous fleet
(`solvers/clarke_wright.py`). Start with one route per customer; for every pair (i, j) with j
among the 30 nearest neighbours of i, the saving of driving i → j instead of returning to the
depot is `d0i + dj0 − λ·dij`; pairs are taken from the largest saving down and the two routes are
joined when the joined load fits *some* vehicle type and every stop stays inside its window —
an O(1) check from the earliest departure at i and the latest feasible start at j. Two things
differ from the textbook: while there are more routes than vehicles every feasible merge is
taken (coverage first), and once routes ≤ vehicles a merge must lower the real cost with the
types the loads imply (fixed + per-km), so distance savings cannot push two cheap vans into one
expensive truck. Vehicle types and availability are settled afterwards: each route takes the
smallest available type that fits (largest routes first), routes left without a vehicle are
dismantled and their customers re-inserted at the cheapest feasible place — in a route, in a
route upgraded to a bigger spare vehicle, or alone on a spare vehicle — and whatever still does
not fit is reported unserved. Multi-start: run 0 is the deterministic classic (λ = 1), the next
19 draw λ ∈ [0.6, 1.4] and perturb the savings by ±10 %; best plan by (served, −cost) wins.

`cw_ls` continues from the `cw` starts with a variable-neighbourhood descent
(`solvers/local_search.py`): relocate, swap, 2-opt*, or-opt (chains of 2–3), intra-route 2-opt,
route split (two halves on cheaper vehicles), route elimination, vehicle re-typing, and after
every descent an insertion pass for the unserved customers (direct, by upgrading a vehicle, on a
spare vehicle, or by ejecting a neighbour that fits elsewhere). Moves are restricted to the 30
nearest neighbours, inter-route feasibility is O(1) from per-route forward/backward arrays,
first improvement, strict lexicographic acceptance (served, then cost). One descent converges in
1–25 s on this set (n = 100 … 600) and cuts the `cw` cost by 5–25 %; the rest of the common time
limit is spent the simple way — the descent is run again from the next-best `cw` starts (fresh
ones are built when the 20 are exhausted) and the best final plan is kept — which on the tight
instances recovers the last one or two customers.

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
  solvers/    base.py  routes.py  clarke_wright.py  local_search.py  ortools_solver.py  hexaly_solver.py
  run.py      solve_one (time-limit tiers, solver params, artefacts), run_benchmark (resumable, parallel)
  viz/        style.py  map_static.py  map_html.py  gantt.py
  report/     aggregate.py (tables, gaps, profiles)  charts.py (Plotly)  build_html.py (report + conclusions)
  cli.py      bench info | validate | generate | plot | solve | run | report | compare | version
configs/      generator.default.yaml  run.default.yaml
tests/        pytest suite; tests/data holds a hand-checked toy instance and broken solutions
instances/    the 108-instance benchmark set + seed solutions + index.csv
results/      run outputs (git-ignored) — except results/final/: the published run (solutions, tables, report)
```

## License

MIT — see [LICENSE](LICENSE).
