"""Spatial families (Solomon-style) and depot placement."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cvrptw_bench.generator.config import GeographyCfg
from cvrptw_bench.generator.geo import Region


@dataclass
class SpatialLayout:
    depot: tuple[float, float]  # (lon, lat)
    customers: np.ndarray  # (n, 2) as (lon, lat)
    n_clusters: int
    cluster_of: np.ndarray  # (n,) cluster index, -1 for uniform points


def sample_layout(
    rng: np.random.Generator, region: Region, n: int, family: str, geo: GeographyCfg
) -> SpatialLayout:
    """Depot uniform in the region; customers by family R (uniform), C (clusters), RC (mixed)."""
    depot = tuple(region.sample_uniform(rng, 1)[0])
    if family == "R":
        pts = region.sample_uniform(rng, n)
        return SpatialLayout(depot, pts, 0, np.full(n, -1))

    n_clustered = n if family == "C" else int(round(n * geo.rc_cluster_share))
    n_uniform = n - n_clustered
    k = max(2, int(round(n_clustered / geo.clusters.customers_per_cluster)))
    centers = region.sample_uniform(rng, k)
    # uneven cluster sizes (some neighbourhoods are denser than others)
    weights = rng.dirichlet(np.full(k, 2.0))
    sizes = rng.multinomial(n_clustered, weights)
    parts: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for j in range(k):
        if sizes[j] == 0:
            continue
        parts.append(
            region.sample_gaussian(rng, tuple(centers[j]), geo.clusters.sigma_km, int(sizes[j]))
        )
        labels.append(np.full(int(sizes[j]), j))
    if n_uniform:
        parts.append(region.sample_uniform(rng, n_uniform))
        labels.append(np.full(n_uniform, -1))
    pts = np.vstack(parts)
    lab = np.concatenate(labels)
    order = rng.permutation(n)  # customer ids must not reveal the cluster structure
    return SpatialLayout(depot, pts[order], k, lab[order])
