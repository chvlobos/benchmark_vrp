# Experiment: Hexaly with the unserved customers in a dummy list (partition) instead of disjoint lists

Same machine, limits (60 / 60 / 120 / 180 s), seed, single thread, lateness-first objective and lexicographic served -> cost as results/final; the only change is how optional customers are modelled: the vehicle lists plus one extra uncosted, unconstrained list under a partition constraint, instead of disjoint vehicle lists. Same feasible set and objective. Motivation: Hexaly 15 keeps disjoint-list models on one thread whatever nb_threads says and maintains the partition constraint about 2.8x faster (iterations per second); this run isolates the formulation effect at one thread before the multi-thread run.

108 instances (those present in both runs). Best known coverage and cost per instance are taken over **all** rows below, base and variant together, so a gap of 0 means the best of both.

| solver | missed | at best coverage | gap % mean | gap % max | best cost | ttb s |
|---|---|---|---|---|---|---|
| OR-Tools | 0 | 108 | 1.40 | 9.51 | 52 | 78.70 |
| Hexaly | 51 | 78 | 4.04 | 18.12 | 13 | 80.60 |
| Hexaly dummy | 46 | 79 | 1.96 | 13.00 | 33 | 86.80 |
| CW + local search | 24 | 89 | 3.67 | 12.84 | 10 | 47.60 |
| Clarke-Wright | 71 | 80 | 20.30 | 52.82 | 0 | 0.30 |

## Head to head

**Hexaly dummy vs Hexaly** on 108 instances: Hexaly dummy serves more customers on 11, fewer on 7; at equal coverage it is cheaper on 54, dearer on 36 (ties 0), cost -1.14 % on average (median -1.06 %, range -12.5 % to +12.8 %).

**Hexaly dummy vs OR-Tools** on 108 instances: Hexaly dummy serves more customers on 0, fewer on 29; at equal coverage it is cheaper on 44, dearer on 35 (ties 0), cost +0.29 % on average (median -0.37 %, range -8.7 % to +13.0 %).

## By instance size

| n | solver | missed | at_best_cov | gap_mean | best_cost | ttb |
|---|---|---|---|---|---|---|
| 100 | Hexaly | 4 | 23 | 5.17 | 4 | 34.52 |
| 100 | Hexaly dummy | 6 | 22 | 3.57 | 5 | 38.70 |
| 200 | Hexaly | 12 | 18 | 4.47 | 1 | 42.43 |
| 200 | Hexaly dummy | 11 | 18 | 2.06 | 5 | 43.80 |
| 400 | Hexaly | 15 | 19 | 3.38 | 4 | 104.45 |
| 400 | Hexaly dummy | 12 | 20 | 0.89 | 11 | 100.27 |
| 600 | Hexaly | 20 | 18 | 2.86 | 4 | 141.10 |
| 600 | Hexaly dummy | 17 | 19 | 1.13 | 12 | 164.26 |

Per-instance served / cost for every column: `comparison_by_instance.csv`; the full overall table: `comparison_overall.csv`.
