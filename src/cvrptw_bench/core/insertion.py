"""Mutable route with O(1) insertion feasibility checks (time windows + capacity).

Used by the generator's repair pass and, from Phase 3 on, by the Clarke-Wright
leftover insertion and the local search. Keeps, per stop, the earliest
schedule (departure at the horizon start) and the latest feasible start
(backward pass), so inserting customer ``c`` between positions ``pos-1`` and
``pos`` is checked without touching the rest of the route:

    arrival_c = departure[pos-1] + t(prev, c)        (or h0 + t(0, c) at pos 0)
    start_c   = max(arrival_c, e_c) <= l_c
    start_c + s_c + t(c, next) <= L[next]            (or <= h1 - ... at the end)

The validator has its own independent implementation of the same rules on
purpose: solver-side helpers are never the judge.
"""

from __future__ import annotations

import numpy as np

from cvrptw_bench.core.matrices import Matrices


class RouteSchedule:
    __slots__ = ("m", "seq", "capacity", "h0", "h1", "load", "dep", "L", "cumload")

    def __init__(self, m: Matrices, seq: list[int], capacity: int, h0: int, h1: int):
        self.m = m
        self.seq = list(seq)
        self.capacity = capacity
        self.h0 = h0
        self.h1 = h1
        self.load = 0
        self.dep = np.empty(0, dtype=np.int64)  # earliest departure from each stop
        self.L = np.empty(0, dtype=np.int64)  # latest feasible service start at each stop
        self.cumload = np.empty(0, dtype=np.int64)  # load carried up to and including each stop
        self.recompute()

    # ------------------------------------------------------------- state
    def recompute(self) -> None:
        m, seq = self.m, self.seq
        k = len(seq)
        dep = np.empty(k, dtype=np.int64)
        cum = np.empty(k, dtype=np.int64)
        t = self.h0
        prev = 0
        load = 0
        for i, c in enumerate(seq):
            t = max(t + int(m.time_s[prev, c]), int(m.tw_start[c])) + int(m.service[c])
            dep[i] = t
            load += int(m.demand[c])
            cum[i] = load
            prev = c
        L = np.empty(k, dtype=np.int64)
        limit = self.h1
        nxt = 0
        for i in range(k - 1, -1, -1):
            c = seq[i]
            L[i] = min(int(m.tw_end[c]), limit - int(m.service[c]) - int(m.time_s[c, nxt]))
            limit = L[i]
            nxt = c
        self.dep, self.L, self.cumload, self.load = dep, L, cum, load

    @property
    def feasible(self) -> bool:
        """Order feasible with departure at h0 (equivalently: latest departure >= h0)."""
        if not self.seq:
            return True
        return int(self.L[0]) - int(self.m.time_s[0, self.seq[0]]) >= self.h0

    def duration(self) -> int:
        """Earliest-schedule duration from h0 to the return at the depot."""
        if not self.seq:
            return 0
        return int(self.dep[-1]) + int(self.m.time_s[self.seq[-1], 0]) - self.h0

    # --------------------------------------------------------- insertion
    def insertion_feasible(self, c: int, pos: int) -> bool:
        m = self.m
        if self.load + int(m.demand[c]) > self.capacity:
            return False
        seq = self.seq
        if pos == 0:
            prev_dep, prev = self.h0, 0
        else:
            prev_dep, prev = int(self.dep[pos - 1]), seq[pos - 1]
        start = max(prev_dep + int(m.time_s[prev, c]), int(m.tw_start[c]))
        if start > m.tw_end[c]:
            return False
        leave = start + int(m.service[c])
        if pos == len(seq):
            return leave + int(m.time_s[c, 0]) <= self.h1
        return leave + int(m.time_s[c, seq[pos]]) <= self.L[pos]

    def insertion_delta(self, c: int, pos: int, matrix: np.ndarray | None = None) -> int:
        """Increase of route length (time_s by default, or any (n+1)x(n+1) matrix)."""
        mat = self.m.time_s if matrix is None else matrix
        seq = self.seq
        a = 0 if pos == 0 else seq[pos - 1]
        b = 0 if pos == len(seq) else seq[pos]
        return int(mat[a, c] + mat[c, b] - mat[a, b])

    def best_insertion(self, c: int, matrix: np.ndarray | None = None) -> tuple[int, int] | None:
        """(delta, pos) of the cheapest feasible insertion, or None."""
        if self.load + int(self.m.demand[c]) > self.capacity:
            return None
        best: tuple[int, int] | None = None
        for pos in range(len(self.seq) + 1):
            if not self.insertion_feasible(c, pos):
                continue
            d = self.insertion_delta(c, pos, matrix)
            if best is None or d < best[0]:
                best = (d, pos)
        return best

    def segment_insertion_feasible(
        self, seg: list[int], pos: int, check_capacity: bool = True
    ) -> bool:
        """Insert the ordered segment ``seg`` between positions pos-1 and pos (time + capacity)."""
        m = self.m
        if check_capacity and self.load + int(m.demand[seg].sum()) > self.capacity:
            return False
        seq = self.seq
        if pos == 0:
            t, prev = self.h0, 0
        else:
            t, prev = int(self.dep[pos - 1]), seq[pos - 1]
        for c in seg:
            start = max(t + int(m.time_s[prev, c]), int(m.tw_start[c]))
            if start > m.tw_end[c]:
                return False
            t = start + int(m.service[c])
            prev = c
        if pos == len(seq):
            return t + int(m.time_s[prev, 0]) <= self.h1
        return t + int(m.time_s[prev, seq[pos]]) <= self.L[pos]

    def replace_feasible(self, pos: int, c: int) -> bool:
        """Replace the stop at ``pos`` by customer ``c`` (time + capacity), O(1)."""
        m = self.m
        seq = self.seq
        old = seq[pos]
        if self.load - int(m.demand[old]) + int(m.demand[c]) > self.capacity:
            return False
        if pos == 0:
            prev_dep, prev = self.h0, 0
        else:
            prev_dep, prev = int(self.dep[pos - 1]), seq[pos - 1]
        start = max(prev_dep + int(m.time_s[prev, c]), int(m.tw_start[c]))
        if start > m.tw_end[c]:
            return False
        leave = start + int(m.service[c])
        if pos == len(seq) - 1:
            return leave + int(m.time_s[c, 0]) <= self.h1
        return leave + int(m.time_s[c, seq[pos + 1]]) <= self.L[pos + 1]

    def insert(self, c: int, pos: int) -> None:
        self.seq.insert(pos, c)
        self.recompute()

    def remove(self, pos: int) -> int:
        c = self.seq.pop(pos)
        self.recompute()
        return c

    def set_seq(self, seq: list[int]) -> None:
        self.seq = list(seq)
        self.recompute()
