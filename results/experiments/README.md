# Secondary experiments

Everything here is a run directory of `bench run` (every `solution.json` re-validatable with
`bench validate <file> --instance instances/<name>.json`, `log.jsonl`, `run_meta.json`) plus a
`comparison.md` produced by `bench compare results/final <dir> --suffix <s>`, which joins the
variant to the published run and judges both with the same coverage-first gaps (the best known
coverage and cost per instance are taken over base and variant together). All on the same
2-core Linux machine as `results/final/` (the CPU probe in each `run_meta.json` confirms two
concurrent jobs get two full cores), seed 42, Hexaly 15.0, OR-Tools 9.15.

| directory | question | what changes vs `results/final` | headline |
|---|---|---|---|
| `hexaly_time_windows/` | soft (lateness objective) or hard time windows for Hexaly? | 3 instances, both modes | soft wins on all three; it is the default |
| `hexaly_penalised/` | is Hexaly's coverage shortfall an artefact of the lexicographic pair (served → cost)? | one scalar objective, cost + P × unserved, disjoint lists, 1 thread, 108 instances | no: 56 missed vs 51, +0.02 % cost at equal coverage |
| `hexaly_dummy/` | disjoint vehicle lists (template) or a partition with an uncosted "unserved" list? | `unserved: dummy_list`, 1 thread, 108 instances | dummy list: −1.1 % cost at equal coverage, 46 missed vs 51, best cost on 33 vs 13 → **now the published formulation** |
| `hexaly_disjoint/` | (archive) the disjoint-list Hexaly column first published on 2026-09-16 | — | replaced in `results/final` on 2026-09-23 |
| `hexaly_2threads/` | what does Hexaly gain from its natural multi-threaded setting? | `nb_threads: 2`, one job at a time so each run owns the machine; **not equal footing** with the single-threaded columns | 17 missed vs 46, best cost on 56 vs OR-Tools' 41, −1.0 % vs OR-Tools at equal coverage; OR-Tools still ahead on coverage in 15 instances |
| `n600_360s/` | are the n = 600 results at 180 s a statement about the limit? | the 27 largest instances at 360 s for every solver (equal footing among them) | no: every time-bound method −0.6 %, differences unchanged (Hexaly vs OR-Tools −1.5 % / 8 instances behind on coverage) |
| `n600_360s_hexaly_disjoint/` | the same doubled limit for the disjoint formulation | Hexaly only, judged against `n600_360s` | disjoint stays behind dummy-list at 360 s too: 20 missed vs 15, +1.7 % cost at equal coverage |

## Thread finding (2026-09-23)

Hexaly 15 keeps a model whose optional customers are expressed with `disjoint(lists)` on one
core whatever `nb_threads` says; with `partition(lists)` the parallel search engages. Measured
on RC-200-T-105 (CPU time / wall time over a 20 s solve, `time.process_time()` around
`optimizer.solve()`): disjoint 0.99 with `nb_threads = 2`; partition + dummy list 1.96. The
partition form is also maintained about 2.8× faster (1.88 M vs 0.68 M iterations in 20 s at
one thread). Bisection on a synthetic 300-customer model: `partition` 1.72 cores,
`disjoint` 1.00, `disjoint` + a second lexicographic objective 0.98, `partition` + a
recursive time array 1.95 — the constraint type, not the objectives or the recursion, is what
decides. This is an empirical observation about Hexaly 15.0.20260914, not documented
behaviour; the modelling consequence is in the README (*Modelling choices for Hexaly*).

## Reproducing

```bash
export HX_LICENSE_PATH=/absolute/path/to/license.dat
bench run --out results/experiments/hexaly_time_windows/soft --solvers hexaly --only RC-200-T-105,C-200-M-85,R-400-T-105 --no-plots --config configs/run.hexaly_soft_disjoint.yaml
bench run --out results/experiments/hexaly_time_windows/hard --solvers hexaly --only RC-200-T-105,C-200-M-85,R-400-T-105 --no-plots --config configs/run.hexaly_hard.yaml
bench run --out results/experiments/hexaly_penalised --solvers hexaly --workers 2 --no-plots --config configs/run.hexaly_penalised.yaml
bench run --out results/experiments/hexaly_dummy --solvers hexaly --workers 2 --no-plots --config configs/run.hexaly_dummy.yaml
bench run --out results/experiments/hexaly_2threads --solvers hexaly --workers 1 --no-plots --config configs/run.hexaly_2threads.yaml
bench run --out results/experiments/n600_360s --solvers cw,cw_ls,ortools,hexaly --sizes 600 --workers 2 --no-plots --config configs/run.n600_360s.yaml
bench run --out results/experiments/n600_360s_hexaly_disjoint --solvers hexaly --sizes 600 --workers 2 --no-plots --config configs/run.n600_360s_hexaly_disjoint.yaml
bench compare results/final results/experiments/hexaly_penalised --suffix _penalised
```

The three-instance time-window runs of 2026-09-16 predate the `unserved` parameter; they used
the disjoint formulation (`configs/run.hexaly_soft_disjoint.yaml` reproduces the soft side).
