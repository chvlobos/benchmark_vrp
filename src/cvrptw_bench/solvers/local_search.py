"""Local search on top of Clarke-Wright (solver ``cw_ls``).

Variable-neighbourhood descent, first improvement, on the lexicographic
objective (customers served, then total cost = fixed + per-km by vehicle type).
Neighbourhoods, in order; after any improvement the descent restarts from the
first one:

1. relocate       move one customer next to one of its k nearest neighbours
2. swap           exchange two neighbouring customers of different routes
3. 2-opt*         exchange the tails of two routes after two neighbours
4. or-opt (2, 3)  move a chain of 2-3 consecutive customers next to a neighbour
5. 2-opt          reverse a segment inside a route (between two neighbours)
6. split          cut a route in two so that both halves ride cheaper vehicles
7. eliminate      empty a short route into the others and give the vehicle back
8. retype         re-assign vehicle types to routes, smallest that fits first

then ``insert unserved``: any unserved customer that now fits somewhere (in a
route, in a route upgraded to a bigger spare vehicle, or on a spare vehicle
alone) is inserted — coverage is the primary objective, so this always wins.

Efficiency: candidate lists (k nearest neighbours), O(1) feasibility checks for
inter-route moves from the forward/backward arrays kept per route
(:class:`RouteSchedule`), O(route length) only for intra-route moves and for
the bookkeeping of the two routes touched by an accepted move.
"""

from __future__ import annotations

import time

import numpy as np

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.core.solution import RoutePlan
from cvrptw_bench.solvers.base import ProgressCallback, register
from cvrptw_bench.solvers.clarke_wright import (
    DEFAULTS,
    ClarkeWrightSolver,
    CWState,
    construct,
    insert_leftovers,
    multistart,
)
from cvrptw_bench.solvers.routes import Fleet, VehicleRoute, segment_cost

LS_DEFAULTS = {"neighbours": 30, "report_interval_s": 0.5}


class LocalSearch:
    def __init__(
        self,
        instance: Instance,
        m: Matrices,
        state: CWState,
        k: int = 30,
        time_budget_s: float = 60.0,
        t0: float | None = None,
        report: ProgressCallback | None = None,
        report_interval_s: float = 0.5,
        seed: int = 42,
    ):
        self.instance = instance
        self.m = m
        self.h0, self.h1 = instance.horizon.start, instance.horizon.end
        self.fleet: Fleet = state.fleet
        self.routes: list[VehicleRoute] = [r for r in state.routes if r.seq]
        self.unserved: list[int] = list(state.unserved)
        self.nb = m.neighbours(k)
        self.route_of: dict[int, VehicleRoute] = {}
        for r in self.routes:
            for c in r.seq:
                self.route_of[c] = r
        self.deadline = (time.perf_counter() if t0 is None else t0) + time_budget_s
        self.t0 = time.perf_counter() if t0 is None else t0
        self.report = report
        self.report_interval = report_interval_s
        self.last_report = -1e9
        self.rng = np.random.default_rng(seed)
        self.n_moves = 0

    # ------------------------------------------------------------ helpers
    def time_up(self) -> bool:
        return time.perf_counter() > self.deadline

    @property
    def served(self) -> int:
        return len(self.route_of)

    def total_cost(self) -> int:
        return sum(r.cost() for r in self.routes)

    def _touch(self, *routes: VehicleRoute) -> None:
        """Recompute arrays of touched routes, drop the empty ones, refresh route_of."""
        for r in routes:
            if not r.seq:
                if r in self.routes:
                    self.routes.remove(r)
                    self.fleet.release(r.vehicle_id)
                continue
            r.recompute()
            for c in r.seq:
                self.route_of[c] = r
        self.n_moves += 1
        self._maybe_report()

    def _maybe_report(self, force: bool = False) -> None:
        if self.report is None:
            return
        now = time.perf_counter()
        if force or now - self.last_report >= self.report_interval:
            self.report(now - self.t0, self.served, self.total_cost())
            self.last_report = now

    def _seq_ok_cost(
        self, seq: list[int], type_index: int, capacity: int, check_capacity: bool = True
    ) -> int | None:
        """Arc cost of ``seq`` for a type, or None if infeasible (time or capacity)."""
        m = self.m
        if check_capacity and int(m.demand[seq].sum()) > capacity:
            return None
        t = self.h0
        prev = 0
        for c in seq:
            start = max(t + int(m.time_s[prev, c]), int(m.tw_start[c]))
            if start > m.tw_end[c]:
                return None
            t = start + int(m.service[c])
            prev = c
        if t + int(m.time_s[prev, 0]) > self.h1:
            return None
        return segment_cost(m, type_index, [0, *seq, 0])

    def _arc(self, r: VehicleRoute, a: int, b: int) -> int:
        return int(self.m.cost[r.type_index, a, b])

    def _removal_delta(self, r: VehicleRoute, p: int) -> int:
        """Cost change of removing the stop at position p (negative), fixed cost included."""
        seq = r.seq
        prev = seq[p - 1] if p > 0 else 0
        nxt = seq[p + 1] if p + 1 < len(seq) else 0
        d = self._arc(r, prev, nxt) - self._arc(r, prev, seq[p]) - self._arc(r, seq[p], nxt)
        if len(seq) == 1:
            d -= r.fixed_cost
        return d

    def _insertion_delta(self, r: VehicleRoute, c: int, pos: int) -> int:
        seq = r.seq
        prev = seq[pos - 1] if pos > 0 else 0
        nxt = seq[pos] if pos < len(seq) else 0
        return self._arc(r, prev, c) + self._arc(r, c, nxt) - self._arc(r, prev, nxt)

    def _customers(self) -> list[int]:
        cs = list(self.route_of)
        self.rng.shuffle(cs)
        return cs

    def _neighbours(self, c: int):
        for d in self.nb[c].tolist():
            if d in self.route_of:
                yield d

    # ------------------------------------------------------------- moves
    def relocate(self) -> bool:
        improved = False
        for c in self._customers():
            if self.time_up():
                break
            if self._relocate_one(c):
                improved = True
        return improved

    def _relocate_one(self, c: int) -> bool:
        A = self.route_of[c]
        p = A.seq.index(c)
        rem = self._removal_delta(A, p)
        base_arc = A.arc_cost()
        for d in self._neighbours(c):
            B = self.route_of[d]
            q = B.seq.index(d)
            if B is A:
                for pos in (q, q + 1):  # before / after d, in the same route
                    if pos in (p, p + 1):
                        continue
                    seq = list(A.seq)
                    seq.pop(p)
                    seq.insert(pos - 1 if pos > p else pos, c)
                    new_cost = self._seq_ok_cost(seq, A.type_index, A.capacity, False)
                    if new_cost is not None and new_cost < base_arc:
                        A.set_seq(seq)
                        self._touch(A)
                        return True
                continue
            for pos in (q, q + 1):
                if not B.insertion_feasible(c, pos):
                    continue
                if self._insertion_delta(B, c, pos) + rem < 0:
                    A.seq.pop(p)
                    B.seq.insert(pos, c)
                    self._touch(A, B)
                    return True
        return False

    def swap(self) -> bool:
        improved = False
        for c in self._customers():
            if self.time_up():
                break
            if self._swap_one(c):
                improved = True
        return improved

    def _swap_one(self, c: int) -> bool:
        A = self.route_of[c]
        p = A.seq.index(c)
        if True:
            for d in self._neighbours(c):
                B = self.route_of[d]
                if B is A:
                    continue
                q = B.seq.index(d)
                if not (A.replace_feasible(p, d) and B.replace_feasible(q, c)):
                    continue
                pa = A.seq[p - 1] if p > 0 else 0
                na = A.seq[p + 1] if p + 1 < len(A.seq) else 0
                pb = B.seq[q - 1] if q > 0 else 0
                nbb = B.seq[q + 1] if q + 1 < len(B.seq) else 0
                delta = (
                    self._arc(A, pa, d)
                    + self._arc(A, d, na)
                    - self._arc(A, pa, c)
                    - self._arc(A, c, na)
                    + self._arc(B, pb, c)
                    + self._arc(B, c, nbb)
                    - self._arc(B, pb, d)
                    - self._arc(B, d, nbb)
                )
                if delta < 0:
                    A.seq[p], B.seq[q] = d, c
                    self._touch(A, B)
                    return True
        return False

    def two_opt_star(self) -> bool:
        improved = False
        for c in self._customers():
            if self.time_up():
                break
            if self._two_opt_star_one(c):
                improved = True
        return improved

    def _two_opt_star_one(self, c: int) -> bool:
        m = self.m
        A = self.route_of[c]
        p = A.seq.index(c)
        if True:
            for d in self._neighbours(c):
                B = self.route_of[d]
                if B is A:
                    continue
                q = B.seq.index(d)
                tail_a, tail_b = A.seq[p + 1 :], B.seq[q + 1 :]
                # capacity of the recombined routes
                load_a = int(A.cumload[p]) + (B.load - int(B.cumload[q]))
                load_b = int(B.cumload[q]) + (A.load - int(A.cumload[p]))
                if load_a > A.capacity or load_b > B.capacity:
                    continue
                # time: c -> first of tail_b within B's latest starts; d -> first of tail_a
                nxt_b = tail_b[0] if tail_b else 0
                lim_b = int(B.L[q + 1]) if tail_b else self.h1
                if int(A.dep[p]) + int(m.time_s[c, nxt_b]) > lim_b:
                    continue
                nxt_a = tail_a[0] if tail_a else 0
                lim_a = int(A.L[p + 1]) if tail_a else self.h1
                if int(B.dep[q]) + int(m.time_s[d, nxt_a]) > lim_a:
                    continue
                new_a = A.seq[: p + 1] + tail_b
                new_b = B.seq[: q + 1] + tail_a
                delta = (
                    segment_cost(m, A.type_index, [0, *new_a, 0])
                    + segment_cost(m, B.type_index, [0, *new_b, 0])
                    - A.arc_cost()
                    - B.arc_cost()
                )
                if delta < 0:
                    A.seq, B.seq = new_a, new_b
                    self._touch(A, B)
                    return True
        return False

    def or_opt(self, length: int) -> bool:
        improved = False
        for c in self._customers():
            if self.time_up():
                break
            if self._or_opt_one(c, length):
                improved = True
        return improved

    def _or_opt_one(self, c: int, length: int) -> bool:
        m = self.m
        A = self.route_of[c]
        p = A.seq.index(c)
        if p + length > len(A.seq):
            return False
        if True:
            seg = A.seq[p : p + length]
            prev = A.seq[p - 1] if p > 0 else 0
            nxt = A.seq[p + length] if p + length < len(A.seq) else 0
            inner_a = segment_cost(m, A.type_index, seg)
            rem = (
                self._arc(A, prev, nxt)
                - self._arc(A, prev, seg[0])
                - inner_a
                - self._arc(A, seg[-1], nxt)
            )
            if len(A.seq) == length:
                rem -= A.fixed_cost
            seg_set = set(seg)
            for d in self._neighbours(c):
                if d in seg_set:
                    continue
                B = self.route_of[d]
                q = B.seq.index(d)
                if B is A:
                    for pos in (q, q + 1):
                        if p <= pos <= p + length:
                            continue
                        rest = A.seq[:p] + A.seq[p + length :]
                        ins = pos - length if pos > p else pos
                        seq = rest[:ins] + seg + rest[ins:]
                        new_cost = self._seq_ok_cost(seq, A.type_index, A.capacity, False)
                        if new_cost is not None and new_cost < A.arc_cost():
                            A.set_seq(seq)
                            self._touch(A)
                            return True
                    continue
                for pos in (q, q + 1):
                    if not B.segment_insertion_feasible(seg, pos):
                        continue
                    pb = B.seq[pos - 1] if pos > 0 else 0
                    nb_ = B.seq[pos] if pos < len(B.seq) else 0
                    ins = (
                        self._arc(B, pb, seg[0])
                        + segment_cost(m, B.type_index, seg)
                        + self._arc(B, seg[-1], nb_)
                        - self._arc(B, pb, nb_)
                    )
                    if ins + rem < 0:
                        del A.seq[p : p + length]
                        B.seq[pos:pos] = seg
                        self._touch(A, B)
                        return True
        return False

    def two_opt(self) -> bool:
        improved = False
        for c in self._customers():
            if self.time_up():
                break
            if self._two_opt_one(c):
                improved = True
        return improved

    def _two_opt_one(self, c: int) -> bool:
        A = self.route_of[c]
        if len(A.seq) < 3:
            return False
        p = A.seq.index(c)
        base = A.arc_cost()
        if True:
            for d in self._neighbours(c):
                if self.route_of[d] is not A:
                    continue
                q = A.seq.index(d)
                i, j = (p, q) if p < q else (q, p)
                if j - i < 1:
                    continue
                seq = A.seq[:i] + A.seq[i : j + 1][::-1] + A.seq[j + 1 :]
                new_cost = self._seq_ok_cost(seq, A.type_index, A.capacity, False)
                if new_cost is not None and new_cost < base:
                    A.set_seq(seq)
                    self._touch(A)
                    return True
        return False

    def split(self) -> bool:
        improved = False
        for A in sorted(self.routes, key=lambda r: -r.load):
            if self.time_up():
                break
            if A.seq and self._split_one(A):
                improved = True
        return improved

    def _split_one(self, A: VehicleRoute) -> bool:
        fleet = self.fleet
        if True:
            if len(A.seq) < 2 or fleet.total_free() == 0:
                return False
            base = A.cost()
            for cut in range(1, len(A.seq)):
                pre, suf = A.seq[:cut], A.seq[cut:]
                load_pre, load_suf = int(A.cumload[cut - 1]), A.load - int(A.cumload[cut - 1])
                k2 = fleet.smallest_free_type(load_suf)
                if k2 is None:
                    continue
                # prefix keeps its vehicle or takes a smaller free one
                k1 = A.type_index
                for kk in fleet.by_capacity:
                    if fleet.capacity[kk] >= load_pre and (kk == A.type_index or fleet.free[kk]):
                        k1 = kk
                        break
                if k1 == k2 and fleet.free_count(k2) < (1 if k1 == A.type_index else 2):
                    continue
                suf_cost = self._seq_ok_cost(suf, k2, fleet.capacity[k2])
                if suf_cost is None:
                    continue
                new_cost = (
                    fleet.fixed[k1]
                    + segment_cost(self.m, k1, [0, *pre, 0])
                    + fleet.fixed[k2]
                    + suf_cost
                )
                if new_cost < base:
                    old_vid = A.vehicle_id
                    if k1 != A.type_index:
                        fleet.release(old_vid)
                        A.assign_vehicle(fleet, fleet.take(k1))
                    vid2 = fleet.take(k2)
                    B = VehicleRoute(
                        self.m, suf, vid2, k2, fleet.capacity[k2], fleet.fixed[k2], self.h0, self.h1
                    )
                    A.seq = pre
                    self.routes.append(B)
                    self._touch(A, B)
                    return True
        return False

    def eliminate(self) -> bool:
        improved = False
        for A in sorted(self.routes, key=lambda r: (len(r.seq), r.load)):
            if self.time_up() or len(A.seq) > 8:
                break
            if A.seq and A in self.routes and self._eliminate_one(A):
                improved = True
        return improved

    def _eliminate_one(self, A: VehicleRoute) -> bool:
        if True:
            saved = A.cost()
            others = [r for r in self.routes if r is not A]
            moved: list[tuple[VehicleRoute, int, int]] = []  # (route, pos, customer)
            delta = 0
            ok = True
            for c in list(A.seq):
                best = None
                for B in others:
                    res = B.best_insertion(c, self.m.cost[B.type_index])
                    if res is not None and (best is None or res[0] < best[0]):
                        best = (res[0], B, res[1])
                if best is None:
                    ok = False
                    break
                _, B, pos = best
                B.insert(c, pos)
                moved.append((B, pos, c))
                delta += best[0]
            if ok and delta - saved < 0:
                A.seq = []
                self._touch(A, *{b for b, _, _ in moved})
                return True
            for B, pos, _ in reversed(moved):  # rollback
                B.remove(pos)
        return False

    def retype(self) -> bool:
        """Re-assign vehicles so that each route rides the smallest type that fits."""
        fleet = self.fleet
        current = sum(r.cost() for r in self.routes)
        # free everything, then greedy by load descending (nested capacities -> feasible)
        free = {k: list(v) for k, v in fleet.free.items()}
        for r in self.routes:
            free[r.type_index].append(r.vehicle_id)
        plan: dict[VehicleRoute, int] = {}
        for r in sorted(self.routes, key=lambda r: -r.load):
            for kk in fleet.by_capacity:
                if fleet.capacity[kk] >= r.load and free[kk]:
                    plan[r] = free[kk].pop()
                    break
            else:
                return False  # cannot happen with nested capacities
        new_cost = sum(
            fleet.fixed[fleet.type_of[v]] + segment_cost(self.m, fleet.type_of[v], [0, *r.seq, 0])
            for r, v in plan.items()
        )
        if new_cost >= current:
            return False
        for r, v in plan.items():
            r.assign_vehicle(fleet, v)
        fleet.free = free
        self._touch(*self.routes)
        return True

    def insert_unserved(self) -> bool:
        """Insert unserved customers directly, then by ejecting a neighbour that fits elsewhere."""
        if not self.unserved:
            return False
        before = len(self.unserved)
        self.unserved = insert_leftovers(
            self.instance, self.m, self.routes, self.fleet, self.unserved
        )
        for r in self.routes:
            for c in r.seq:
                self.route_of[c] = r
        lateral = self.eject_insert()
        if len(self.unserved) < before or lateral:
            self._maybe_report(force=True)
            return True
        return False

    def eject_insert(self) -> bool:
        """For an unserved c: take the slot of a served neighbour d, then re-insert d elsewhere.

        Success serves one more customer. If d finds no place but has a larger demand
        than c, the exchange is kept anyway (same coverage, capacity freed for later);
        the strict demand decrease rules out cycling.
        """
        m = self.m
        changed = False
        for c in list(self.unserved):
            if self.time_up():
                break
            dc = int(m.demand[c])
            for d in self._neighbours(c):
                R = self.route_of[d]
                q = R.seq.index(d)
                if not R.replace_feasible(q, c):
                    continue
                R.seq[q] = c
                R.recompute()
                others = [r for r in self.routes if r is not R]
                left = insert_leftovers(self.instance, m, others, self.fleet, [d])
                if not left:
                    for r in others:  # a route opened on a spare vehicle is new to us
                        if r not in self.routes:
                            self.routes.append(r)
                    self.unserved.remove(c)
                    self._touch(*self.routes)
                    changed = True
                    break
                if int(m.demand[d]) > dc:
                    self.unserved.remove(c)
                    self.unserved.append(d)
                    del self.route_of[d]
                    self.route_of[c] = R
                    changed = True
                    break
                R.seq[q] = d
                R.recompute()
        return changed

    # -------------------------------------------------------------- driver
    def run(self) -> None:
        neighbourhoods = [
            self.relocate,
            self.swap,
            self.two_opt_star,
            lambda: self.or_opt(2),
            lambda: self.or_opt(3),
            self.two_opt,
            self.split,
            self.eliminate,
            self.retype,
        ]
        self.insert_unserved()
        while not self.time_up():
            improved = False
            for move in neighbourhoods:
                while not self.time_up() and move():
                    improved = True
            if self.insert_unserved():
                improved = True
            if not improved:
                break
        self._maybe_report(force=True)

    def plan(self) -> RoutePlan:
        return RoutePlan(routes={r.vehicle_id: list(r.seq) for r in self.routes if r.seq})


@register
class ClarkeWrightLSSolver(ClarkeWrightSolver):
    """Local search from successive constructive starts until the common time limit.

    A descent converges long before the limit on this set, so the remaining
    time is used the simple way: run it again from the next-best Clarke-Wright
    start (different λ and savings noise leave different customers out and
    give different route shapes); when the precomputed starts are exhausted,
    fresh ones are built on the fly. The best final plan by (served, −cost)
    is returned. Every solver in the benchmark gets the same wall-clock cap.
    """

    name = "cw_ls"
    version = "0.3.0"

    def _solve(self, instance, matrices, config, report):
        t0 = time.perf_counter()
        p = {**LS_DEFAULTS, **DEFAULTS, **config.params}
        deadline = t0 + float(config.time_limit_s)
        states = multistart(instance, matrices, config, report, t0=t0, keep_all=True)
        rng = np.random.default_rng(config.seed + 1000)
        lo, hi = p["lambda_range"]
        best_key: tuple[int, int] | None = None
        best_plan: RoutePlan | None = None
        i = 0
        while True:
            if i > 0 and time.perf_counter() >= deadline:
                break
            if i < len(states):
                state = states[i]
            else:  # starts exhausted: build a fresh one
                state = construct(
                    instance,
                    matrices,
                    lam=float(rng.uniform(lo, hi)),
                    seed=int(rng.integers(2**31 - 1)),
                    noise=float(p["savings_noise"]),
                    k=int(p["neighbours"]),
                )
            ls = LocalSearch(
                instance,
                matrices,
                state,
                k=int(p["neighbours"]),
                time_budget_s=max(0.0, deadline - time.perf_counter()),
                t0=t0,
                report=None,
                report_interval_s=float(p["report_interval_s"]),
                seed=config.seed + i,
            )
            ls.deadline = deadline
            ls.run()
            key = (ls.served, -ls.total_cost())
            if best_key is None or key > best_key:
                best_key, best_plan = key, ls.plan()
                if report is not None:
                    report(time.perf_counter() - t0, key[0], -key[1])
            i += 1
        assert best_plan is not None
        return best_plan
