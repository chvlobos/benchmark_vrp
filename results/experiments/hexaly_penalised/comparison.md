# Experiment: Hexaly with one penalised objective

Same model, machine, limits (60 / 60 / 120 / 180 s), seed and single thread as results/final, but the benchmark objective is given to Hexaly as ONE scalar, cost + P x unserved with P above any routing cost (the shape OR-Tools optimises), instead of the lexicographic pair maximise served -> minimise cost. Lateness stays the first-priority objective. Question: is Hexaly's coverage shortfall at 105 % stress an artefact of the lexicographic formulation?

108 instances (those present in both runs). Best known coverage and cost per instance are taken over **all** rows below, base and variant together, so a gap of 0 means the best of both.

| solver | missed | at best coverage | gap % mean | gap % max | best cost | ttb s |
|---|---|---|---|---|---|---|
| OR-Tools | 0 | 108 | 1.00 | 7.21 | 63 | 78.70 |
| Hexaly | 51 | 78 | 3.44 | 18.12 | 12 | 80.60 |
| Hexaly penalised | 56 | 77 | 3.20 | 13.60 | 23 | 83.80 |
| CW + local search | 24 | 89 | 3.18 | 12.84 | 10 | 47.60 |
| Clarke-Wright | 71 | 80 | 19.66 | 52.82 | 0 | 0.30 |

## Head to head

**Hexaly penalised vs Hexaly** on 108 instances: Hexaly penalised serves more customers on 6, fewer on 10; at equal coverage it is cheaper on 45, dearer on 47 (ties 0), cost +0.02 % on average (median +0.20 %, range -6.0 % to +12.4 %).

**Hexaly penalised vs OR-Tools** on 108 instances: Hexaly penalised serves more customers on 0, fewer on 31; at equal coverage it is cheaper on 30, dearer on 47 (ties 0), cost +2.02 % on average (median +1.01 %, range -6.7 % to +13.6 %).

## By instance size

| n | solver | missed | at_best_cov | gap_mean | best_cost | ttb |
|---|---|---|---|---|---|---|
| 100 | Hexaly | 4 | 23 | 5.10 | 4 | 34.52 |
| 100 | Hexaly penalised | 4 | 23 | 5.49 | 5 | 38.71 |
| 200 | Hexaly | 12 | 18 | 4.25 | 1 | 42.43 |
| 200 | Hexaly penalised | 12 | 18 | 3.82 | 4 | 39.95 |
| 400 | Hexaly | 15 | 19 | 2.34 | 3 | 104.45 |
| 400 | Hexaly penalised | 19 | 17 | 2.18 | 5 | 97.94 |
| 600 | Hexaly | 20 | 18 | 1.67 | 4 | 141.10 |
| 600 | Hexaly penalised | 21 | 19 | 0.75 | 9 | 158.60 |

Per-instance served / cost for every column: `comparison_by_instance.csv`; the full overall table: `comparison_overall.csv`.
