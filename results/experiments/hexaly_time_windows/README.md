# Hexaly: soft vs hard time windows (modelling choice, 2026-09-16)

Hexaly's own CVRPTW template handles the time windows as a first-priority
*lateness* objective driven to zero rather than as constraints. The adapter
supports both (`hexaly.time_windows: soft | hard`); this experiment picked the
mode for the published run. Three instances, the common limits (60 / 60 / 120 s),
one thread, seed 42, on the same 2-core Linux container as `results/final/`.

| instance (limit)     | soft: served / cost | hard: served / cost |
|----------------------|---------------------|---------------------|
| C-200-M-85 (60 s)    | 200 / 634 804       | 200 / 638 646       |
| RC-200-T-105 (60 s)  | **198** / 690 863   | 196 / 692 187       |
| R-400-T-105 (120 s)  | **395** / 1 328 209 | 394 / 1 309 748     |

`soft` wins on all three under the coverage-first objective and is the default in
`configs/run.default.yaml`. Every `solution.json` here is re-validatable with
`bench validate <file> --instance instances/<name>.json`.

Reproduce (needs a Hexaly license, `HX_LICENSE_PATH` set):

```bash
bench run --out /tmp/hx_soft --solvers hexaly --only RC-200-T-105,C-200-M-85,R-400-T-105 --no-plots
bench run --out /tmp/hx_hard --solvers hexaly --only RC-200-T-105,C-200-M-85,R-400-T-105 --no-plots --config configs/run.hexaly_hard.yaml
```
