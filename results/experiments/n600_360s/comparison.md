# Experiment: n = 600 with twice the common limit (360 s) for every solver

The 27 largest instances (n = 600) re-solved by cw, cw_ls, ortools and hexaly with a 360 s cap instead of 180 s, everything else identical to results/final (same machine, 2 workers, seed 42, one thread, same models - Hexaly in its published dummy-list formulation). Equal footing among the four at 360 s; the comparison with the 180 s rows says how much of each method's gap at the largest size was the time limit. Clarke-Wright stops after its 20 starts either way, so its 360 s row is the control: it must be identical.

27 instances (those present in both runs). Best known coverage and cost per instance are taken over **all** rows below, base and variant together, so a gap of 0 means the best of both.

| solver | missed | at best coverage | gap % mean | gap % max | best cost | ttb s |
|---|---|---|---|---|---|---|
| OR-Tools | 1 | 26 | 2.23 | 6.95 | 0 | 150.50 |
| OR-Tools 360s | 0 | 27 | 1.54 | 6.81 | 11 | 314.80 |
| Hexaly | 18 | 19 | 1.29 | 4.97 | 0 | 164.30 |
| Hexaly 360s | 15 | 19 | 0.57 | 4.55 | 15 | 319.80 |
| CW + local search | 13 | 19 | 4.00 | 8.28 | 1 | 82.30 |
| CW + local search 360s | 11 | 19 | 3.33 | 7.05 | 1 | 148.40 |
| Clarke-Wright | 37 | 18 | 19.46 | 37.67 | 0 | 0.70 |
| Clarke-Wright 360s | 37 | 18 | 19.46 | 37.67 | 0 | 0.60 |

## Head to head

**OR-Tools 360s vs OR-Tools** on 27 instances: OR-Tools 360s serves more customers on 1, fewer on 0; at equal coverage it is cheaper on 25, dearer on 0 (ties 1), cost -0.62 % on average (median -0.62 %, range -1.6 % to +0.0 %).

**Hexaly 360s vs Hexaly** on 27 instances: Hexaly 360s serves more customers on 3, fewer on 0; at equal coverage it is cheaper on 24, dearer on 0 (ties 0), cost -0.62 % on average (median -0.42 %, range -2.9 % to -0.0 %).

**CW + local search 360s vs CW + local search** on 27 instances: CW + local search 360s serves more customers on 2, fewer on 0; at equal coverage it is cheaper on 10, dearer on 0 (ties 15), cost -0.60 % on average (median +0.00 %, range -2.9 % to +0.0 %).

**Clarke-Wright 360s vs Clarke-Wright** on 27 instances: Clarke-Wright 360s serves more customers on 0, fewer on 0; at equal coverage it is cheaper on 0, dearer on 0 (ties 27), cost +0.00 % on average (median +0.00 %, range +0.0 % to +0.0 %).

**Hexaly 360s vs OR-Tools** on 27 instances: Hexaly 360s serves more customers on 0, fewer on 8; at equal coverage it is cheaper on 16, dearer on 3 (ties 0), cost -2.13 % on average (median -2.08 %, range -6.5 % to +4.3 %).

**CW + local search 360s vs OR-Tools** on 27 instances: CW + local search 360s serves more customers on 0, fewer on 8; at equal coverage it is cheaper on 7, dearer on 12 (ties 0), cost +0.54 % on average (median +0.97 %, range -4.3 % to +3.5 %).

**Clarke-Wright 360s vs OR-Tools** on 27 instances: Clarke-Wright 360s serves more customers on 0, fewer on 9; at equal coverage it is cheaper on 0, dearer on 18 (ties 0), cost +16.25 % on average (median +14.67 %, range +7.4 % to +36.5 %).

## By instance size

| n | solver | missed | at_best_cov | gap_mean | best_cost | ttb |
|---|---|---|---|---|---|---|
| 600 | OR-Tools | 1 | 26 | 2.23 | 0 | 150.45 |
| 600 | OR-Tools 360s | 0 | 27 | 1.54 | 11 | 314.84 |
| 600 | Hexaly | 18 | 19 | 1.29 | 0 | 164.26 |
| 600 | Hexaly 360s | 15 | 19 | 0.57 | 15 | 319.79 |
| 600 | CW + local search | 13 | 19 | 4.00 | 1 | 82.30 |
| 600 | CW + local search 360s | 11 | 19 | 3.33 | 1 | 148.44 |
| 600 | Clarke-Wright | 37 | 18 | 19.46 | 0 | 0.73 |
| 600 | Clarke-Wright 360s | 37 | 18 | 19.46 | 0 | 0.63 |

## Equal footing at 360 s (all four solvers at the doubled limit)

| pair | more customers | fewer | cheaper | dearer | cost, mean | median |
|---|---|---|---|---|---|---|
| Hexaly vs OR-Tools | 0 | 8 | 15 | 4 | −1.53 % | −1.74 % |
| CW + LS vs OR-Tools | 0 | 8 | 6 | 13 | +1.15 % | +1.29 % |
| Hexaly vs CW + LS | 1 | 4 | 19 | 3 | −2.79 % | −3.02 % |

The same pairs at 180 s (the published run): Hexaly vs OR-Tools 0 / 8 / 14 / 5, −1.43 % mean;
CW + LS vs OR-Tools 0 / 8 / 6 / 13, +1.18 %. Doubling the limit moved every time-bound method
by the same ≈ −0.6 % (OR-Tools also recovered the one customer it lacked at 180 s) and left the
differences between them unchanged; at 360 s the searches were still improving (time to best
315 s for OR-Tools, 320 s for Hexaly, of 360). The 180 s ranking at n = 600 is therefore not
an artefact of the limit. Clarke-Wright's 360 s row is identical to its 180 s row, as it must be.

Per-instance served / cost for every column: `comparison_by_instance.csv`; the full overall table: `comparison_overall.csv`.
