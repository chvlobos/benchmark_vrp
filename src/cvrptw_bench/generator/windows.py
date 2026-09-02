"""Time windows centred on the seed arrival times (PLAN.md §4.4)."""

from __future__ import annotations

import numpy as np

from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.generator.config import TW_CLASSES, TimeWindowsCfg


def assign_classes(
    rng: np.random.Generator, n: int, profile: str, cfg: TimeWindowsCfg
) -> list[str]:
    """Exact class counts for the profile shares (largest remainder), shuffled."""
    shares = cfg.profiles[profile]
    raw = [s * n for s in shares]
    counts = [int(x) for x in raw]
    for _ in range(n - sum(counts)):
        j = int(np.argmax([r - c for r, c in zip(raw, counts, strict=True)]))
        counts[j] += 1
        raw[j] = counts[j]  # remainder consumed
    classes = [c for c, k in zip(TW_CLASSES, counts, strict=True) for _ in range(k)]
    rng.shuffle(classes)
    return classes


def make_windows(
    rng: np.random.Generator,
    m: Matrices,
    arrival: np.ndarray,
    classes: list[str],
    cfg: TimeWindowsCfg,
    h0: int,
    h1: int,
) -> tuple[np.ndarray, np.ndarray]:
    """(tw_start, tw_end) arrays of shape (n+1,), whole minutes, seed arrival inside each window."""
    n = m.n
    e = np.empty(n + 1, dtype=np.int64)
    late = np.empty(n + 1, dtype=np.int64)
    e[0], late[0] = h0, h1
    for c in range(1, n + 1):
        lo, hi = cfg.widths_s[classes[c - 1]]
        w = int(rng.integers(lo, hi + 1))
        a = int(arrival[c])
        jitter = int(rng.uniform(-cfg.center_jitter_frac, cfg.center_jitter_frac) * w)
        center = a + jitter
        start = center - w // 2
        end = start + w
        # clip to the horizon, keeping the width when possible
        if start < h0:
            start, end = h0, min(h1, h0 + w)
        if end > h1:
            end, start = h1, max(h0, h1 - w)
        # the seed arrival must be inside
        if a < start:
            start = a
        if a > end:
            end = a
        # never unreachable: a dedicated vehicle can serve it and be back before closing
        latest_ok = h1 - int(m.service[c]) - int(m.time_s[c, 0])
        if start > latest_ok:
            start = max(h0, latest_ok)
        # whole minutes, widening outwards
        start = (start // 60) * 60
        end = -((-end) // 60) * 60
        e[c] = max(h0, start)
        late[c] = min(h1, max(end, e[c]))
    return e, late
