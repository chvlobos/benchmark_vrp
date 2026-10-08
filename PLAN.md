# CVRPTW-HF Benchmark — Santiago, Chile
## Clarke-Wright (own implementation) vs OR-Tools vs Hexaly

**Status:** plan v2.0 — 2026-09-23 (all phases delivered; `results/final/` holds the four-solver run — cw / cw_ls / ortools of 2026-09-02, the Hexaly column of 2026-09-16 replaced on 2026-09-23 by the dummy-list formulation, same 2-core machine, same limits, one thread — and `report.html`; secondary experiments in `results/experiments/` (§12.6): penalised objective (no effect), dummy-list formulation (adopted), 2 threads (Hexaly becomes the cheapest method), 360 s tier for n = 600 (ranking unchanged))
**Owner:** Christian Villalobos
**Scope of this document:** the working plan agreed after a 64-question requirements interview. Section 2 is the decision log (what was decided and why); the rest is the design and the phased delivery plan. Everything here is the contract for implementation; anything not listed under "Open points" is settled.

---

## 1. Problem statement (in operational terms)

A single distribution center somewhere in Greater Santiago serves *n* customers in one working day (default 10:00–18:00). Each customer has a known load (one dimension, "units", think kg), a service duration that grows with the load, and a delivery time window that can be wide, medium or tight. The fleet is heterogeneous: three vehicle types (small / medium / large) with different capacities, a limited number of vehicles per type, and different cost structures (fixed cost per vehicle used + cost per km). Every vehicle does at most one trip: it leaves the depot no earlier than opening, visits its customers inside their windows (arriving early and waiting is allowed and free), and is back at the depot no later than closing.

Travel is on a synthetic network: great-circle (Haversine) distance × 1.3 detour factor, at a constant 30 km/h for every vehicle type.

**Decisions the algorithm must make**

- *Selection*: which customers are served today and which are left out (the instance may be over-subscribed by design).
- *Assignment*: which vehicle (and therefore which type) serves each served customer.
- *Sequencing*: the order of visits on each vehicle.
- *Timing*: departure time from the depot and the resulting arrival/wait/start times at each stop (implied once the sequence is fixed, because waiting is free and unlimited).

**What makes one solution better than another** (lexicographic):

1. More customers served (each customer counts 1, regardless of load).
2. Among solutions with the same coverage, lower total cost = Σ fixed cost of vehicles used + Σ per-km cost × route distance.

**Hard rules** (never violated; a solution that breaks any of them is *invalid* and is reported as such):

- Vehicle capacity by type; number of vehicles per type.
- Time windows (hard): service must start within [e_i, l_i].
- Depot horizon: departure ≥ opening, return ≤ closing.
- One trip per vehicle; every served customer visited exactly once.

There are no soft constraints in v1. Unserved customers are not a violation: they are reported separately with a diagnostic reason.

**Why this benchmark exists:** to decide whether Hexaly is worth licensing for the consultancy's routing work, against a free solver (OR-Tools) and against what a senior OR engineer can build in a week (Clarke-Wright + local search). The deliverable will be shared publicly (GitHub) and with Hexaly's team, so reproducibility and a clean, fair comparison matter more than squeezing the last percent out of any method.

---

## 2. Decision log (from the requirements interview)

| # | Topic | Decision |
|---|---|---|
| 1 | Purpose | Evaluate Hexaly for the consultancy; share on GitHub and with Hexaly |
| 2 | Deadline | 1–2 weeks for everything that does not depend on the Hexaly license |
| 3 | Language | Code, comments, README, report: English |
| 4 | Stack | Python 3.11 (exactly: `python3.11 -m venv`, `.python-version`, CI on 3.11), `pip` + `venv` + `requirements.txt`, installable package with CLI, Git + public GitHub repo (MIT) |
| 5 | Geography | Customers sampled inside the Greater Santiago urban polygon (not a bounding box) |
| 6 | Spatial families | Solomon-style: R (uniform), C (clustered), RC (mixed) |
| 7 | Depot | One depot, random location per instance (inside the polygon) |
| 8 | Sizes | Medium and large instances; proposed n ∈ {100, 200, 400, 600} |
| 9 | Set size | ~60–100 instances, explicit factorial design, one replicate per cell |
| 10 | Instance format | One JSON per instance, with metadata |
| 11 | Horizon | Configurable, default 10:00–18:00 |
| 12 | Window widths | Three classes: wide / medium / tight |
| 13 | Window mix | Share of each class per instance is a design factor (profiles) |
| 14 | Window centers | Placed around the arrival times of a reference (seed) solution, Solomon-style, so infeasibility is never an artefact of the generator |
| 15 | Service time | Base + proportional to load |
| 16 | Load | One dimension; mixture of many small + few large orders; a large order may exceed the small vehicle's capacity but never the large vehicle's |
| 17 | Fleet | 3 types, fixed count per type, fixed cost per use + cost per km by type |
| 18 | Stress | Total demand ÷ total fleet capacity ∈ {0.60, 0.85, 1.05} |
| 19 | Route rules | One trip per vehicle; return before closing (hard); free departure time; 30 km/h; Haversine × 1.3 |
| 20 | Objective | Lexicographic: max customers served → min total cost |
| 21 | Windows | Hard; unlimited free waiting |
| 22 | Clarke-Wright | Parallel savings with λ, randomized multi-start; smallest-feasible-type assignment + availability repair; greedy insertion of leftovers; two reported variants: CW and CW+LS |
| 23 | OR-Tools | PATH_CHEAPEST_ARC + Guided Local Search; time limit scaled with n; meters/seconds; unserved via uniform large disjunction penalty |
| 24 | Hexaly | Common solver interface; adapter written now from the docs, tested when the license arrives; model design left to me (see §7.4); access type unknown → target local Python SDK |
| 25 | Quality reference | Best known solution among the methods per instance (no MIP bound) |
| 26 | Solution file | JSON, one schema for all solvers; full metric set; independent validator mandatory; post-hoc diagnostic reason for each unserved customer |
| 27 | Plots | Map: static PNG (300 dpi, basemap) + interactive HTML; x-t: Gantt per vehicle with windows; generated for every instance × solver |
| 28 | Report | Self-contained HTML; per-instance table, aggregates by factor, time-vs-size, gap-vs-factor, performance profiles, conclusions |
| 29 | Replicates | One run per instance × solver, fixed seed |
| 30 | Gap | Coverage compared first; cost gap only among solutions with the best coverage |
| 31 | Execution | Christian's Mac, sequential, in background; no practical compute limit; runner must be resumable |
| 32 | Working mode | Plan first; then implementation phase by phase with review between phases |

---

## 3. Modelling notes that drive the design

**Two kinds of stress, not one.** Capacity stress (demand ÷ fleet capacity) is the design factor, but in an 8-hour day with tight windows the binding resource is often *time*: a large truck with capacity for 35 orders cannot make 35 stops with 30-minute windows spread over the city. Therefore the generator also computes and stores an estimated *time stress* (Σ service time + estimated travel time of the reference solution) ÷ (vehicles × horizon). Both are reported in the analysis; otherwise "85 % capacity stress" instances that are actually time-infeasible would be misread.

**The shared cost model is the fairness guarantee.** All solvers and the validator consume the *same* integer matrices (distance in meters, travel time in seconds, arc cost per type in CLP) built once per instance by one function. Nobody computes Haversine on its own. Rounding differences between solvers would otherwise show up as fake "gaps".

**Lexicographic objective, implemented natively in each solver.**
- Clarke-Wright: coverage is maximised constructively (leftover insertion pass); the local search never removes a customer and tries to insert unserved ones after each improvement pass.
- OR-Tools: one `AddDisjunction` per customer with a uniform penalty larger than any possible routing cost, so dropping a customer is never worth a cost saving.
- Hexaly: two objectives declared in order (`maximize served`, `minimize cost`).
- Validator: recomputes `(served, cost)` from the routes and is the only source of truth for the report.

**Fixed costs make "number of vehicles" part of the cost, not a separate objective.** The 3-level lexicographic objective of academic VRPTW (customers → vehicles → distance) is replaced by the two-level one because fixed costs per type already price the vehicles. This keeps all three solvers on exactly the same objective.

**Free departure time is a scheduling convenience, not an extra decision.** With free unlimited waiting, a route is feasible iff the earliest-start forward schedule respects all deadlines. Solvers can therefore work with earliest schedules; the reported departure is post-processed by the validator with the `min_wait` policy: delay the departure by `min(forward time slack, total waiting)`, i.e. the earliest departure that attains the minimum waiting for that order (no pointless waiting at the first stops, maximum buffer kept). `latest` and `earliest` policies exist for analysis. Cost and coverage never depend on the policy, and all solvers get the same treatment.

---

## 4. Instance generator

### 4.1 Design factors and naming

| Factor | Levels | Notes |
|---|---|---|
| Size n | 100, 200, 400, 600 | 100–200 = medium, 400–600 = large |
| Spatial family | R, C, RC | C: k clusters (k ≈ n/40 ± jitter), Gaussian σ ≈ 1.2 km around cluster seeds; RC: 50 % of customers clustered, 50 % uniform |
| Window profile | L (loose), M (mixed), T (tight) | Shares of wide/medium/tight windows: L = 70/20/10 %, M = 33/33/34 %, T = 10/20/70 % |
| Capacity stress | 60, 85, 105 (%) | Fleet is sized to hit the target ratio; the exact achieved ratio is stored |

Full factorial: 4 × 3 × 3 × 3 = **108 instances** (81 if n = 600 is dropped). Given no compute limit, the plan assumes 108; the `--sizes` flag controls it.

Instance name: `{family}-{n}-{profile}-{stress}` e.g. `RC-400-T-105`. Seed = hash(global_seed, name), so any instance can be regenerated alone and the set is stable when instances are added.

### 4.2 Geography

- A simplified polygon of the consolidated urban area of Greater Santiago (≈ 40–60 vertices) is embedded in the package as GeoJSON (`data/santiago_urban.geojson`), derived from public comuna boundaries (IDE Chile / OSM), excluding the pre-cordillera and rural fringes. A `--bbox` fallback exists for sanity tests.
- Sampling: rejection sampling inside the polygon (shapely). Cluster seeds are sampled the same way; cluster points that fall outside are re-sampled.
- Depot: uniform inside the polygon, one per instance (decision #7). Because a corner depot makes the instance much harder than a central one, the depot's distance to the customers' centroid is stored in metadata for the analysis.

### 4.3 Demand, service time, fleet

Default parameters (all in the generator config, YAML/JSON, overridable):

| Parameter | Default | Rationale |
|---|---|---|
| Small orders | 90 % of customers, U[10, 60] units | Parcel/retail-like |
| Large orders | 10 % of customers, U[200, 1000] units | Exceed small-vehicle capacity (800) but never the large (3200) |
| Service time | 3 min + 0.05 min/unit (→ ~5 min small, 13–53 min large) | Base + proportional (decision #15) |
| Vehicle types | small 800 / medium 1600 / large 3200 units | ≈ 9 / 17 / 35 average orders per full vehicle |
| Fixed cost per use | 20 000 / 30 000 / 45 000 CLP | Larger truck, larger daily cost |
| Cost per km | 350 / 500 / 700 CLP/km | Larger truck, higher running cost |
| Fleet mix | counts in ratio 3 : 2 : 1 (small : medium : large) | One "block" = 6 vehicles, 8 800 units |

Fleet sizing: sample demands first; total fleet capacity target = Σ demand ÷ stress; candidates are *b* full blocks plus any partial block (at most the block's count of each type), keeping only fleets with at least one large vehicle; for stress ≤ 100 % take the candidate closest to the target among those with capacity ≥ demand, for stress > 100 % the closest among those with capacity < demand (so an over-subscribed cell really is over-subscribed even at n = 100, where a 5-vehicle fleet is coarse); store the achieved ratio (0.59–0.61 / 0.82–0.86 / 1.01–1.07 on the generated set).

### 4.4 Time windows around a reference solution

1. Build a *seed solution* on the real fleet: customers sorted by angle around the depot from a random start; vehicles taken in repeating blocks mirroring the fleet mix, **smallest type first** inside each block (small vehicles fill up on small orders, big orders are deferred to medium/large vehicles); each vehicle takes consecutive customers while capacity and a route-duration cap (horizon minus a 10 % margin) hold; each route is re-ordered with nearest-neighbour + 2-opt. Deferred and leftover customers go to the cheapest feasible insertion in a real route, else to a route opened on an unused real vehicle, else to *virtual* large vehicles — these exist only to place windows and are not part of the fleet.
2. Each seed route gets a random departure offset within its slack so windows spread over the whole day instead of clustering at 10:00.
3. Each customer draws a window class from the profile; width: wide U[4 h, 8 h], medium U[1.5 h, 3 h], tight U[30 min, 60 min]. The window is centred on the seed arrival time with a small jitter (±10 % of width), clipped to the horizon, shifted if needed so that the seed arrival is inside it and `e_i + s_i + t_i0 ≤ closing` holds (a customer is never unreachable by construction), and rounded outwards to whole minutes.
4. With the windows in place, a second repair pass tries once more to insert the virtual customers into real routes against the actual windows (shared O(1) insertion primitive in `core/insertion.py`).
5. Consequences (measured on the generated set): at 60 % stress the seed serves everyone → *a feasible full-coverage solution exists*; at 85 % it leaves at most 0.5 % of customers; at 105 % the leftovers (1–20 %, capacity-bound) are over-subscription by design. Tight profiles can still make instances time-infeasible for the solvers — that is the intended experiment, and the time-stress metadata explains it.
6. The seed solution is written to a sidecar file (`<name>.seed.json`), validated by the independent validator, and used as (a) a smoke test for the validator and plots in Phase 2, and (b) a "generator reference" row in the report. Solvers never read it.

### 4.5 Instance JSON schema (v1)

```json
{
  "schema_version": 1,
  "name": "RC-400-T-105",
  "meta": {
    "seed": 123456789, "global_seed": 42, "generator_version": "0.1.0", "created": "2026-09-05T12:00:00Z",
    "factors": {"n": 400, "family": "RC", "tw_profile": "T", "capacity_stress": 105},
    "stats": {"total_demand": 36510, "fleet_capacity": 35200, "capacity_stress_achieved": 1.037,
              "time_stress_est": 0.91, "depot_to_centroid_km": 9.4,
              "seed_solution": {"served": 371, "cost": 1234567, "vehicles_used": 24}}
  },
  "horizon": {"start": 36000, "end": 64800},
  "travel": {"speed_kmh": 30, "detour_factor": 1.3, "distance": "haversine"},
  "depot": {"lat": -33.4489, "lon": -70.6693},
  "customers": [
    {"id": 1, "lat": -33.41, "lon": -70.61, "demand": 45, "service_time": 315,
     "tw_start": 41400, "tw_end": 43200, "tw_class": "tight"}
  ],
  "vehicle_types": [
    {"type": "small", "capacity": 800, "count": 12, "fixed_cost": 20000, "cost_per_km": 350},
    {"type": "medium", "capacity": 1600, "count": 8, "fixed_cost": 30000, "cost_per_km": 500},
    {"type": "large", "capacity": 3200, "count": 4, "fixed_cost": 45000, "cost_per_km": 700}
  ]
}
```

Times are integer seconds since midnight; distances are not stored (recomputed deterministically by the shared matrix builder). Customer ids are 1..n; the depot is node 0 everywhere.

---

## 5. Shared core (used by every solver, the validator and the plots)

- `Instance` dataclass + loader/saver with schema validation.
- `Matrices`: `dist_m[i][j]` (int, round(haversine_km × 1.3 × 1000)), `time_s[i][j]` (int, round(dist_m / 1000 / 30 × 3600)), `cost[t][i][j]` (int CLP, round(cost_per_km_t × dist_m / 1000)). Built with numpy once per instance; n ≤ 600 → ≤ 361k entries per matrix, trivial.
- `Solution` dataclass (§8.1) + JSON I/O.
- `Validator`: recomputes the full schedule from the visiting order (earliest schedule), checks capacity, windows, horizon, fleet counts, uniqueness; computes every metric; classifies unserved customers; normalises departure times (`min_wait`). Returns `valid: bool` + list of violations, and keeps the raw plan in the solution file even when it is invalid, so an audit can see exactly what the solver produced. **A solver's own numbers are never used in the report.**
- `Solver` protocol: `solve(instance, matrices, config, seed, time_limit_s) -> Solution`, plus optional progress callback `(elapsed_s, served, cost)` used to record time-to-best and a convergence trace.

---

## 6. Own heuristic: Clarke-Wright for heterogeneous fleet with time windows

### 6.1 Representation and precomputation

Routes are Python lists of customer indices; per route we keep: load, assigned type, and two arrays that make merge and insertion checks O(1): the forward earliest schedule (arrival, start, departure at each stop) and the backward *latest feasible start* at each stop, `L_i = min(l_i, L_next − s_i − t_i,next)`, with `L_last = min(l_last, closing − s_last − t_last,0)`. Candidate lists: the k = 30 nearest neighbours of each customer (by travel time) restrict which savings and moves are considered.

### 6.2 Constructive: parallel savings with time windows and vehicle types

Plain-language version: start with one route per customer (depot → i → depot). Look at every pair (i, j) where i is the last stop of one route and j the first stop of another, and compute how much we would save by joining them into one route, i → j, instead of going back to the depot. Take the pairs from largest saving to smallest and join whenever the joined route still fits in some vehicle type and every stop can still be reached inside its window.

Formally, savings are direction-specific (time windows make the problem asymmetric): `s_ij = d_0i + d_j0 − λ·d_ij`, computed only for j in the candidate list of i (and vice-versa) to keep the list at O(n·k) instead of O(n²). A merge A→B is feasible iff `load_A + load_B ≤ cap(largest type)` and `departure_A(last) + t_ij ≤ L_B(first)` — both O(1) thanks to the precomputed arrays. After a merge the route's type is set to the smallest type whose capacity fits, and the forward/backward arrays are recomputed for the merged route (O(route length)).

Merge acceptance is coverage-aware: while there are more routes than vehicles every feasible merge is taken (even with a negative saving); once routes ≤ vehicles a merge is accepted only if it lowers the real cost with the smallest types the loads imply (fixed + per-km), so distance savings cannot push two cheap vans into one expensive truck (this replaces the planned Golden-style cost-aware savings).

Fleet availability is *not* enforced during merging (there are n routes at the start, far more than vehicles). It is repaired afterwards:

1. **Type assignment with availability.** Routes are sorted by number of customers (descending) and each gets the smallest available type that fits its load; a route that fits no remaining vehicle is dismantled and its customers join the *leftover pool*. Greedy by customer count is the right proxy for the primary objective (max customers served); a tiny exact assignment can replace it later if the report shows it matters.
2. **Leftover insertion.** Each leftover customer is tried at its cheapest feasible position in any route (capacity within the route's current type or an available upgrade; O(1) time feasibility check per position). Order: by fewest feasible positions first (a mild regret criterion). Whatever remains is *unserved* with its exact reason (capacity / time window / no vehicle).

### 6.3 Randomised multi-start

Run 1 is deterministic (λ = 1, no noise). Runs 2..K (default K = 20, or a time budget, default 30 s) draw λ ~ U[0.6, 1.4] and multiply each saving by U[0.9, 1.1]. Keep the best solution by `(served, −cost)`. Seeded; the winning (λ, seed) is recorded in the solution's config block so it can be replayed.

### 6.4 Local search (variant "CW+LS")

Variable-neighbourhood descent, first-improvement, candidate lists, evaluated with O(1) deltas on cost and O(1) time-feasibility (forward/backward arrays refreshed only for the routes touched by an accepted move):

- Inter-route: relocate (1 customer), swap (1↔1), 2-opt* (exchange tails), Or-opt between routes (chain of 2–3).
- Intra-route: 2-opt (segment reversal — feasibility re-checked along the reversed segment, O(segment)), Or-opt.
- Fleet-aware moves: a move that pushes a route above its type's capacity is allowed only if a larger type is available (types are swapped in the fleet ledger); a route left empty releases its vehicle. Explicit *route elimination* move: try to relocate every customer of the smallest route elsewhere (fixed costs make this valuable).
- Route split: cut a route in two when both halves ride cheaper vehicles for less total cost (the counterpart of route elimination; needed because CW merges are distance-driven).
- Coverage move: after each descent, try to insert each unserved customer (best feasible position, upgrade allowed, spare vehicle), then by *ejection*: take the slot of a served neighbour and re-insert that neighbour elsewhere; an exchange that frees capacity (bigger demand out, smaller in) is kept even when the neighbour finds no place. Any success restarts the descent.

Stop: no improving move in any neighbourhood; then the descent is repeated from the next-best constructive start (fresh starts when the 20 are exhausted) until the common time limit — the same cap OR-Tools and Hexaly get. The whole CW+LS is expected to run in well under a minute at n = 600 in pure Python + numpy; profiling (cProfile) is part of Phase 3, and the hot loop is written with integer indices and preallocated arrays, no object creation.

### 6.5 Known limitations (stated in the report)

Savings are distance-based; the type-dependent cost is only felt at type assignment, so CW can prefer a merge that a cost-aware saving (Golden et al. style) would reject. The report will say so; the LS corrects most of it. Multi-start CW is not a metaheuristic: it is a constructive with restarts, deliberately, because the question is "what does a solid week of engineering buy you", not "can we beat Hexaly with ALNS".

---

## 7. Solver adapters

### 7.1 OR-Tools Routing (v9.15)

- Nodes: 0 = depot, 1..n customers; vehicles: the fleet expanded to individual vehicles (`count` per type), all starting and ending at node 0.
- Cost: `SetArcCostEvaluatorOfVehicle(cost[type], v)` and `SetFixedCostOfVehicle(fixed_cost[type], v)` — the exact shared cost model.
- Capacity: one dimension with per-vehicle capacities from the type.
- Time: dimension with transit = travel + service of the origin, slack unbounded (waiting), cumul windows per customer, `[opening, closing]` at each vehicle start and end; start cumul left free (late departure allowed).
- Unserved: `AddDisjunction([node], penalty)` with `penalty = 2 × (Σ fixed costs + Σ_i max_j cost_max[i][j] + V × max_j cost_max[0][j]) + 1` — twice an upper bound on any plan's routing cost — so every served customer beats any cost (implemented; the tests assert objective = validator cost + penalty × dropped).
- Search: `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`, time limit by size (default 60 s for n ≤ 200, 120 s for 400, 180 s for 600; configurable, and given no compute limit a 300 s tier is a one-line change). **The same tier limit is the cap for every solver** (decision 2026-09-02: comparisons must be fair); `cw` stops after its 20 starts and reports its shorter wall time, `cw_ls` uses the limit fully with successive starts. `AddAtSolutionCallback` records `(elapsed, objective)` for time-to-best and the convergence trace. Single-threaded (OR-Tools local search is).
- Output mapped to the common `Solution`, then validated.

### 7.2 Hexaly (Python SDK `hexaly`, v15)

Written from the documented CVRPTW example and left untested until the license arrives; a pytest marker skips it when no license is found. Recommended model (decision #24, "your call"):

- One list variable per vehicle (fleet expanded to individual vehicles); `disjoint(lists)` instead of `partition` so a customer may be in no list; `served = Σ_v count(list_v)`.
- Per vehicle: `used_v = count(list_v) > 0`; load = Σ demand over the list ≤ capacity; route distance and cost via the shared integer matrices loaded as `array`s and indexed with `at`; time recursion with a lambda: `start_k = max(e_{c_k}, prev_departure + travel)`, `start_k ≤ l_{c_k}`, `return ≤ closing`; departure from depot free (start of the recursion = `max(opening, e_{c_1} − t_{0,c_1})`).
- Objectives, in order: `maximize served`, `minimize Σ_v (used_v × fixed_v + Σ arc costs)`.
- Same time limit as OR-Tools per instance; `nb_threads = 1` for the primary comparison (fairness with single-threaded OR-Tools), plus an optional multi-thread run as a secondary experiment if time allows — Hexaly's parallelism is part of its value proposition and deserves its own row.
- Progress callback (`ITERATION_TICKED` / `TIME_TICKED`) records time-to-best.
- Checked in Phase 5: the pip package (`hexaly` 15.0 on PyPI) has no trial mode — creating the optimizer without a license fails — so the adapter was written blind and dry-run against a fake model (structure: 1 disjoint + 3 constraints per vehicle, 2 objectives); the first real run is on the licensed machine. Hexaly counts a lambda's parameters with `inspect.signature`, so lambdas capture through closure scope, never default arguments. Compared against Hexaly's published CVRPTW template (2026-09-15): same list/`at`/recursive-array idioms; deliberate differences are `disjoint` + maximise served (optional customers), per-vehicle capacity and per-type cost matrices, fixed cost instead of vehicle count, integer CLP; the template's soft-lateness-objective treatment of the windows is now the default (`hexaly.time_windows: soft`), with `hard` constraints as the alternative. Picked on 2026-09-16 with the license, three instances at the common limits, one thread (`configs/run.hexaly_hard.yaml` for the hard side): soft 200/634 804 · 198/690 863 · 395/1 328 209 vs hard 200/638 646 · 196/692 187 · 394/1 309 748 on C-200-M-85 · RC-200-T-105 · R-400-T-105 → soft wins on all three (coverage first) and stays the default. All six Hexaly tests passed at the first licensed run (both modes build, toy optimum 119 546 reached, objective == validator, RC-100-T-105 valid inside the limit). Decision 2026-09-15, superseded 2026-09-16: the license turned out to work in the same container that produced the 324 open-source results, so the Hexaly column was added there with `bench run --solvers hexaly` (resume; identical hardware and limits) instead of re-running everything on the Mac. Headline (108 instances, one thread): OR-Tools best coverage 108/108, best cost 74, mean gap 0.8 %; Hexaly best coverage 78/108 (51 customers missed, 50 of them at 105 % stress), best cost 20, mean gap 3.2 % (1.4 % at n = 600), +2.2 % vs OR-Tools at equal coverage, a draw with cw_ls on cost; cw_ls 89/108, 24 missed, 2.9 %; cw 71 missed, 19.3 %. Solver-reported (served, cost) == validator on all 432.

### 7.3 Common runner

`bench run --instances instances/ --solvers cw,cw_ls,ortools,hexaly --out results/<run_id>/ --resume`: iterates instance × solver sequentially, skips pairs already present in the output folder (resumable over several days), writes `solution.json`, `map.png`, `map.html`, `gantt.png`, a `log.jsonl` line with metrics, and captures host info (CPU model, Python, package versions) once per run. Failures (exception, timeout without a solution) are recorded as `status: error` rows, never as silent gaps.

---

## 8. Outputs

### 8.1 Solution JSON schema (v1)

```json
{
  "schema_version": 1,
  "instance": "RC-400-T-105",
  "solver": "cw_ls", "solver_version": "0.1.0",
  "config": {"time_limit_s": 120, "seed": 42, "lambda": 0.93, "multistart_runs": 20},
  "status": "feasible",
  "compute": {"wall_time_s": 41.2, "time_to_best_s": 33.8, "host": "Apple M2 Pro", "threads": 1},
  "routes": [
    {"vehicle_id": 3, "vehicle_type": "medium", "depart": 36900, "return": 62110,
     "load": 1450, "distance_m": 48210, "cost": 54105,
     "stops": [{"customer": 17, "arrival": 38200, "wait": 300, "service_start": 38500, "departure": 38815}]}
  ],
  "unserved": [{"customer": 5, "demand": 640, "tw_start": 41400, "tw_end": 43200, "reason": "capacity"}],
  "metrics": {
    "served": 371, "unserved": 29, "unserved_demand": 8120,
    "total_cost": 1180450, "fixed_cost": 660000, "distance_km": 812.4,
    "vehicles_used": {"small": 12, "medium": 8, "large": 4},
    "route_time_h": 151.2, "wait_h": 9.3, "service_h": 62.0,
    "capacity_utilisation_mean": 0.87, "stops_per_vehicle_mean": 15.5, "tw_slack_mean_min": 22.4
  },
  "validation": {"valid": true, "violations": []},
  "trace": [[0.8, 340, 1420000], [12.5, 371, 1210000], [33.8, 371, 1180450]]
}
```

### 8.2 Diagnostic reason for unserved customers

Computed post-hoc by the validator on the final routes, in this order: `oversized` (demand above every capacity — impossible with this generator), `unreachable_window` (cannot be served even alone by a dedicated vehicle — impossible with this generator), `insertable` (a feasible insertion into an existing route exists, or an unused vehicle with enough capacity could do a dedicated route — a quality flag for the solver; for CW+LS this must be zero by construction), `capacity` (no route has room for it and no unused vehicle can take it), `time_window` (some route has room but no position is time-feasible, and no unused vehicle is left). "Fleet exhausted" is therefore folded into the last two: it is the reason a new route is not an option.

### 8.3 Plots

- **Map** (`map.png`, 300 dpi, `map.html`): depot marker, routes as straight great-circle segments coloured by *vehicle type* (blue/orange/aqua, fixed across all figures; neighbouring routes of the same type alternate three shades of the hue), customer markers sized by demand, unserved customers as hollow red markers, CartoDB Positron tiles via contextily (tile cache; graceful fallback to plain axes with the urban polygon outline when offline). HTML via folium with one toggleable layer per route and stop tooltips (window, arrival, wait, service).
- **x-t Gantt** (`gantt.png`): one row per used vehicle (grouped by type), time of day on x; per stop a thin travel bar, a hatched waiting bar and a solid service bar in the type's colour, plus a bracket for the customer's window drawn at two alternating heights (neighbouring brackets do not merge) and tied to its bar by a connector; departure/return ticks; unserved customers' windows packed into red lanes at the bottom with their ids.

### 8.4 Report (`report.html`, self-contained)

Generated by `bench report results/<run_id>/`: summary table per instance (served, cost, km, vehicles by type, wall time, time-to-best, gap, validity); aggregates by n, family, window profile, stress; charts (plotly embedded, no CDN): wall time vs n, coverage deficit and cost gap vs each factor, performance profiles (Dolan–Moré on cost among max-coverage solutions; coverage profile separately), convergence traces for a few instances; a gallery of maps/Gantts for selected instances; hardware and versions; conclusions and a "when to use which" recommendation. CSV twins of every table are written next to it.

**Gap definition** (decision #30): per instance, `best_served = max over solvers`; a solver with fewer served customers gets `coverage_deficit = best_served − served` and `cost_gap = n/a`; among solvers reaching `best_served`, `cost_gap = (cost − best_cost) / best_cost`. Invalid solutions are excluded from best-of and flagged.

---

## 9. Repository layout

```
vrp_test_stgo/
├── README.md                 # what, how to run, results summary
├── PLAN.md                   # this document
├── LICENSE                   # MIT
├── pyproject.toml            # package `cvrptw_bench`, console script `bench`
├── requirements.txt          # pinned; hexaly listed as optional extra
├── configs/
│   ├── generator.default.yaml
│   └── run.default.yaml      # solvers, time limits per size, seeds
├── src/cvrptw_bench/
│   ├── core/       (instance.py, matrices.py, solution.py, validator.py, costs.py)
│   ├── generator/  (geo.py, sampling.py, seed_solution.py, windows.py, fleet.py, generate.py)
│   ├── solvers/    (base.py, clarke_wright.py, local_search.py, ortools_solver.py, hexaly_solver.py)
│   ├── viz/        (map_static.py, map_html.py, gantt.py)
│   ├── report/     (aggregate.py, charts.py, build_html.py, templates/)
│   ├── data/santiago_urban.geojson
│   └── cli.py      (bench generate | solve | run | plot | validate | report)
├── tests/          (pytest; hexaly tests skipped without license)
├── instances/      (generated set + .seed.json sidecars; committed for reproducibility)
└── results/        (git-ignored except the final run's summary CSVs and report.html)
```

Python 3.11. Dependencies: numpy, shapely, pydantic (schema), pyyaml, matplotlib, contextily, folium, plotly, pandas, jinja2, ortools==9.15.*, pytest; `hexaly` as an optional extra.

---

## 10. Phased delivery (review checkpoint at the end of each phase)

| Phase | Days | Deliverable | Done when |
|---|---|---|---|
| 0 — Skeleton | 1 | Repo, package, CLI stub, CI (tests on push), shared core (instance, matrices, cost model, solution schema, validator) | **Done.** `bench validate` accepts a hand-written toy instance/solution and rejects six deliberately broken ones |
| 1 — Generator | 1–3 | Polygon, sampling families, demand/fleet sizing, seed solution, windows, JSON, `bench generate` | **Done.** 108 instances in 7 s; all seed solutions pass the validator; `instances/index.csv` holds the statistics |
| 2 — Plots | 3–4 | Static map, HTML map, Gantt; `bench plot` | **Done.** `viz/` renders map.png (basemap, offline fallback), map.html (folium, per-route layers) and gantt.png (two-level window brackets, unserved lanes); seed solutions of every family rendered and reviewed |
| 3 — Clarke-Wright | 4–7 | CW multi-start, type/availability repair, leftover insertion, LS, `bench solve --solver cw|cw_ls` | **Done.** Valid on all 108; `insertable` = 0; cw_ls converges in ≤ 20 s at n = 600; 81 tests |
| 4 — OR-Tools | 7–9 | Adapter, callbacks, time limits, mapping to schema | **Done.** Objective recomputed by the validator equals OR-Tools' own exactly (asserted in tests); matrices registered in C++; 86 tests |
| 5 — Hexaly | 9–10 | Adapter written from docs; skip-if-no-license test; smoke test if the trial edition allows | **Done (2026-09-15).** `solvers/hexaly_solver.py` as in §7.2 (disjoint lists, recursive start times, hard windows, lexicographic served → cost, nb_threads 1, TIME_TICKED trace); license via HX_LICENSE_PATH / `hexaly.license_path`; tests skip without a license (the pip package has no trial mode: `HexalyOptimizer()` needs the key). First licensed run on Christian's Mac |
| 6 — Run & report | 10–14 | Resumable full run (CW, CW+LS, OR-Tools; Hexaly when available), report builder, README with results | **Done; Hexaly column added 2026-09-16 (same machine, resume).** `bench run` (resumable, parallel, log.jsonl + run_meta.json) and `bench report` (coverage-first gaps, per-factor tables and box plots, performance profiles, time-to-best, convergence, gallery, data-driven conclusions, CSV twins); 324/324 results valid; OR-Tools at best coverage on 108/108 with the best cost on 88, CW+LS within 2.5 % on average (24 customers missed, all at 105 % stress), CW 18.8 % / 71 missed in ~1 s; 93 tests; report in `results/final/` |

Follow-ups (secondary experiments, clearly labelled as not equal-footing): Hexaly with `nb_threads` = core count; a longer tier for n = 600 for every solver; a single penalised objective for Hexaly (served × big-M − cost); optionally the whole four-solver run on a faster desktop (`bench run --out results/run_<host> ...`) to see all methods more converged at the same limits.

---

## 11. Risks and mitigations

- **Urban polygon source.** A clean Greater Santiago polygon must be obtained/curated once (Phase 1). Mitigation: bounding-box fallback already in the CLI; the polygon is a data file, not code.
- **Time stress confounding capacity stress.** Mitigated by design (§3) — both are stored and analysed; the report never claims "85 % stress" without showing the time side.
- **Unfair comparison through different cost models or rounding.** Mitigated by the single shared matrices and the validator as sole judge.
- **OR-Tools GLS at n = 600 under-converged at 180 s.** The convergence traces will show it; the time-limit tiers are configuration, and compute is not a constraint — a second tier (e.g., 600 s) can be run for the largest size only.
- **Hexaly adapter written blind.** Model kept close to the documented CVRPTW example; first-day-with-license task is a smoke run on the smallest instances and a validator check. Access modality unknown (local SDK assumed); a remote/cloud API would need a thin transport change only.
- **Threads.** Hexaly is multi-threaded by default; primary comparison at 1 thread, documented; secondary multi-thread row optional.
- **Python speed in CW+LS.** Integer indices, numpy matrices, O(1) feasibility arrays, candidate lists; profiled in Phase 3 before any micro-optimisation.
- **Multi-day run interrupted.** Resumable runner; every result is written atomically per instance × solver.

---

## 12. Open points (defaults assumed unless you say otherwise)

1. Instance count: 108 (four sizes) vs 81 (drop n = 600). Assumed 108.
2. Demand/capacity/cost defaults in §4.3 are calibrated in Phase 1 with the generator's summary statistics; you review them before the set is frozen.
3. Time-limit tiers: 60 / 60 / 120 / 180 s for n = 100 / 200 / 400 / 600 (an optional 300–600 s tier for n = 600 if the traces show under-convergence).
4. Cluster parameters (k, σ) and window widths are generator config; defaults in §4.
5. The seed (sweep) solution is shown in the report as a reference row. Assumed yes.
6. (2026-09-16) Secondary Hexaly experiments before the license decision: `nb_threads` = core count; longer n = 600 tier for all solvers; single penalised objective. (2026-09-23) Run, see `results/experiments/README.md`: the penalised objective changes nothing (56 missed vs 51, +0.02 % cost); the search for why `nb_threads = 2` had no effect found that Hexaly 15 does not parallelise `disjoint`-list models — with `partition` and an uncosted dummy list for the unserved it does (1.96 cores measured) and the constraint is ~2.8× cheaper to maintain; at one thread the dummy-list formulation is −1.1 % cost at equal coverage, 46 missed vs 51, best cost on 33 vs 13, so it replaced the disjoint column in `results/final` (decision Christian, 2026-09-23; disjoint archived in `results/experiments/hexaly_disjoint`). New four-solver headline: OR-Tools 108/108 at best coverage, best cost 57, mean gap 1.2 %; Hexaly 79/108, 46 missed (45 at 105 %), best cost 39, mean gap 1.7 % (median 0.2 %), at cost parity with OR-Tools (+0.3 % mean, −0.4 % median) and −1.8 % vs cw_ls; cw_ls 89/108, 3.5 %; cw 71 missed, 20.0 %. 2 threads (dummy-list, one job at a time): 17 missed vs 46, best cost on 56 vs OR-Tools' 41, −1.0 % vs OR-Tools at equal coverage, OR-Tools still ahead on coverage in 15 instances — Hexaly's default setting makes it the cheapest method of the table. n = 600 at 360 s for all four: every time-bound method −0.6 %, differences unchanged (Hexaly vs OR-Tools −1.5 % / behind on coverage in 8 of 27; CW+LS +1.2 %), searches still improving at 360 s — the 180 s ranking is not a limit artefact. Conclusion for the license question (README): at one core OR-Tools and Hexaly tie on cost and OR-Tools wins coverage; with the second core Hexaly is the cheapest method with the coverage gap down to 15 customers; Hexaly's case is its default setting and modelling style, not single-core quality on a textbook problem.

---

## 13. How the results will be validated before publication

- Every solution passes the independent validator; invalid ones are shown as invalid, not dropped.
- Cross-check: the validator's cost for OR-Tools solutions equals OR-Tools' objective minus penalties (within integer rounding) on every instance.
- Sanity: no solver should have `insertable` unserved customers on loose instances; CW+LS must dominate CW on `(served, cost)`; OR-Tools should dominate CW on most instances — if not, the adapter is suspect before the report is.
- Spot-check five maps and Gantts by eye for geographic absurdities (zigzags, crossings), as a planner would.
- Perturbation test (optional, if time allows): re-simulate the best solutions with travel times +15 % to report how fragile each solver's schedules are — a business-relevant metric that a pure cost comparison hides.
