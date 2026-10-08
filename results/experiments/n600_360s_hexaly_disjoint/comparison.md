# Experiment: the disjoint (template) formulation of Hexaly at n = 600 with 360 s

Companion of n600_360s: the same 27 instances at the doubled limit, Hexaly with disjoint vehicle lists instead of the published dummy-list formulation, one thread, seed 42. Base run here is results/experiments/n600_360s (all four solvers at 360 s), so 'Hexaly' below is the dummy-list formulation at 360 s and 'Hexaly disjoint' the template idiom at 360 s.

27 instances (those present in both runs). Best known coverage and cost per instance are taken over **all** rows below, base and variant together, so a gap of 0 means the best of both.

| solver | missed | at best coverage | gap % mean | gap % max | best cost | ttb s |
|---|---|---|---|---|---|---|
| OR-Tools | 0 | 27 | 1.98 | 8.02 | 10 | 314.80 |
| Hexaly | 15 | 19 | 0.95 | 4.55 | 12 | 319.80 |
| Hexaly disjoint | 20 | 18 | 2.95 | 7.40 | 4 | 295.20 |
| CW + local search | 11 | 19 | 3.72 | 7.05 | 1 | 148.40 |
| Clarke-Wright | 37 | 18 | 19.91 | 37.67 | 0 | 0.60 |

## Head to head

**Hexaly disjoint vs Hexaly** on 27 instances: Hexaly disjoint serves more customers on 2, fewer on 6; at equal coverage it is cheaper on 7, dearer on 12 (ties 0), cost +1.72 % on average (median +3.11 %, range -3.7 % to +7.4 %).

**Hexaly disjoint vs OR-Tools** on 27 instances: Hexaly disjoint serves more customers on 0, fewer on 9; at equal coverage it is cheaper on 7, dearer on 11 (ties 0), cost +0.17 % on average (median +1.30 %, range -7.4 % to +4.7 %).

## By instance size

| n | solver | missed | at_best_cov | gap_mean | best_cost | ttb |
|---|---|---|---|---|---|---|
| 600 | Hexaly | 15 | 19 | 0.95 | 12 | 319.79 |
| 600 | Hexaly disjoint | 20 | 18 | 2.95 | 4 | 295.22 |

Per-instance served / cost for every column: `comparison_by_instance.csv`; the full overall table: `comparison_overall.csv`.
