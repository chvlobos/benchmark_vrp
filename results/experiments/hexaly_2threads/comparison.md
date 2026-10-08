# Experiment: Hexaly with two threads (the whole machine)

Same model (dummy-list formulation, soft lateness, lexicographic served -> cost), limits (60 / 60 / 120 / 180 s) and seed as the published Hexaly column, but nb_threads = 2 - every core of the machine, Hexaly's default setting - and one job at a time so each run owns the machine. NOT equal footing with the single-threaded columns: the question is what Hexaly gains from its natural setting, i.e. what a user who simply runs it with default parameters would see against single-threaded OR-Tools.

108 instances (those present in both runs). Best known coverage and cost per instance are taken over **all** rows below, base and variant together, so a gap of 0 means the best of both.

| solver | missed | at best coverage | gap % mean | gap % max | best cost | ttb s |
|---|---|---|---|---|---|---|
| OR-Tools | 0 | 108 | 1.70 | 10.48 | 41 | 78.70 |
| Hexaly | 46 | 79 | 2.16 | 13.00 | 23 | 86.80 |
| Hexaly 2threads | 17 | 93 | 0.88 | 7.77 | 56 | 89.40 |
| CW + local search | 24 | 89 | 3.96 | 13.12 | 7 | 47.60 |
| Clarke-Wright | 71 | 80 | 20.54 | 53.20 | 0 | 0.30 |

## Head to head

**Hexaly 2threads vs Hexaly** on 108 instances: Hexaly 2threads serves more customers on 23, fewer on 0; at equal coverage it is cheaper on 46, dearer on 4 (ties 35), cost -1.21 % on average (median -0.04 %, range -8.8 % to +1.8 %).

**Hexaly 2threads vs OR-Tools** on 108 instances: Hexaly 2threads serves more customers on 0, fewer on 15; at equal coverage it is cheaper on 65, dearer on 28 (ties 0), cost -1.01 % on average (median -0.89 %, range -9.5 % to +7.8 %).

## By instance size

| n | solver | missed | at_best_cov | gap_mean | best_cost | ttb |
|---|---|---|---|---|---|---|
| 100 | Hexaly | 6 | 22 | 3.63 | 4 | 38.70 |
| 100 | Hexaly 2threads | 1 | 26 | 1.49 | 11 | 38.91 |
| 200 | Hexaly | 11 | 18 | 2.18 | 5 | 43.80 |
| 200 | Hexaly 2threads | 3 | 24 | 1.29 | 9 | 48.58 |
| 400 | Hexaly | 12 | 20 | 1.07 | 11 | 100.27 |
| 400 | Hexaly 2threads | 6 | 21 | 0.29 | 17 | 99.09 |
| 600 | Hexaly | 17 | 19 | 1.59 | 3 | 164.26 |
| 600 | Hexaly 2threads | 7 | 22 | 0.27 | 19 | 171.15 |

Per-instance served / cost for every column: `comparison_by_instance.csv`; the full overall table: `comparison_overall.csv`.
