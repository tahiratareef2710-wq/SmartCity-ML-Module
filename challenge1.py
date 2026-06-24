"""
challenge1.py
=============
Challenge 1 – CSP City Layout Solver
Techniques: AC-3 arc-consistency · MRV variable ordering ·
            Backtracking · Forward checking

Failure handling: if no valid layout is found after retries, the solver
identifies which specific constraint is blocking and proposes a
minimum-conflict layout (one constraint relaxed) as required by the spec.
"""

from collections import deque, defaultdict
import random

from city_engine import (
    CityGraph, FORBIDDEN_ADJACENCY, TOTAL_NODES
)

# Human-readable names for the three hard constraints
_CONSTRAINT_NAMES = {
    "adj":   "Industrial adjacency ban (Industrial ↔ School / Hospital)",
    "hosp":  "Hospital reachability  (every Residential ≤ 3 hops from a Hospital)",
    "power": "PowerPlant proximity   (every PowerPlant ≤ 2 hops from an Industrial zone)",
}


class CSPSolver:
    """
    Assigns node types to a random subset of grid cells while satisfying:
      • Forbidden adjacency (Industrial ↔ Hospital / School)
      • Residential ≤ 3 hops from a Hospital
      • PowerPlant  ≤ 2 hops from an Industrial node

    On failure the solver:
      1. retries up to MAX_RETRIES times with fresh random candidate pools
      2. identifies which specific constraint is blocking
      3. proposes a minimum-conflict layout by relaxing only that constraint
    """

    MAX_RETRIES           = 5    # fresh random pools to try before giving up
    MAX_BACKTRACK_VISITS  = 80000  # abort one attempt if it visits this many nodes

    def __init__(self, graph: CityGraph):
        self.graph = graph
        self.violation_reason       = ""
        self._last_violated: str    = ""   # most recent constraint tag
        self._violation_counts: dict[str, int] = {"adj": 0, "hosp": 0, "power": 0}
        self._dead_ends: int        = 0
        self._bt_visits: int        = 0

    # ── Constraint predicates ──────────────────────────────────

    def _adj_ok(self, nid: int, t: str, assigned: dict) -> bool:
        banned = FORBIDDEN_ADJACENCY.get(t, set())
        for e in self.graph.adj[nid]:
            nb_type = assigned.get(e.other(nid))
            if nb_type in banned:
                return False
            if nb_type and t in FORBIDDEN_ADJACENCY.get(nb_type, set()):
                return False
        return True

    def _hosp_reach(self, nid: int, assigned: dict, rem_h: int) -> bool:
        """Residential must be ≤ 3 hops from a Hospital."""
        hospitals = [i for i, t in assigned.items() if t == "Hospital"]
        if not hospitals:
            return rem_h > 0   # optimistic — hospitals will be placed later

        visited, frontier = {nid}, {nid}
        for _ in range(3):
            nxt = set()
            for cur in frontier:
                for e in self.graph.adj[cur]:
                    nb = e.other(cur)
                    if nb not in visited:
                        if assigned.get(nb) == "Hospital":
                            return True
                        visited.add(nb)
                        nxt.add(nb)
            frontier = nxt
        return False

    def _power_reach(self, nid: int, assigned: dict, rem_i: int) -> bool:
        """PowerPlant must be ≤ 2 hops from an Industrial node."""
        industrial = {i for i, t in assigned.items() if t == "Industrial"}
        if not industrial:
            return rem_i > 0

        visited, frontier = {nid}, {nid}
        for _ in range(2):
            nxt = set()
            for cur in frontier:
                for e in self.graph.adj[cur]:
                    nb = e.other(cur)
                    if nb not in visited:
                        if nb in industrial:
                            return True
                        visited.add(nb)
                        nxt.add(nb)
            frontier = nxt
        return False

    def _consistent(self, nid: int, t: str, assigned: dict,
                    counts: dict) -> bool:
        if t == "Empty":
            return True
        if not self._adj_ok(nid, t, assigned):
            self._last_violated = "adj"
            self._violation_counts["adj"] += 1
            return False
        rem_h = self.graph.required_counts["Hospital"]   - counts.get("Hospital",   0)
        rem_i = self.graph.required_counts["Industrial"] - counts.get("Industrial", 0)
        if t == "Residential" and not self._hosp_reach(nid, assigned, rem_h):
            self._last_violated = "hosp"
            self._violation_counts["hosp"] += 1
            return False
        if t == "PowerPlant"  and not self._power_reach(nid, assigned, rem_i):
            self._last_violated = "power"
            self._violation_counts["power"] += 1
            return False
        return True

    # ── AC-3 arc-consistency ───────────────────────────────────

    def _ac3(self, domains: dict) -> bool:
        q = deque(
            (i, e.other(i))
            for i in domains
            for e in self.graph.adj[i]
            if e.other(i) in domains
        )
        while q:
            xi, xj = q.popleft()
            new_dom = [
                t for t in domains[xi]
                if any(
                    t2 not in FORBIDDEN_ADJACENCY.get(t,  set()) and
                    t  not in FORBIDDEN_ADJACENCY.get(t2, set())
                    for t2 in domains[xj]
                )
            ]
            if len(new_dom) < len(domains[xi]):
                if not new_dom:
                    return False
                domains[xi] = new_dom
                for e in self.graph.adj[xi]:
                    nb = e.other(xi)
                    if nb in domains and nb != xj:
                        q.append((nb, xi))
        return True

    # ── Backtracking + MRV + Forward checking ─────────────────

    def solve(self, progress_cb=None) -> bool:
        g     = self.graph
        total = sum(self.graph.required_counts.values())   # 72

        all_types = list(self.graph.required_counts.keys()) + ["Empty"]

        # Small buffer so the CSP can leave a few cells explicitly Empty.
        extra_slots = 5
        pool_size   = total + extra_slots

        # Retry with different random candidate pools
        for attempt in range(self.MAX_RETRIES):
            pool = list(range(TOTAL_NODES))
            random.shuffle(pool)
            candidates = pool[:pool_size]

            domains = {nid: list(all_types) for nid in candidates}

            if not self._ac3(domains):
                self._last_violated = "adj"
                self._violation_counts["adj"] += 1
                continue   # try a fresh pool

            assigned: dict[int, str] = {}
            counts:   dict[str, int] = defaultdict(int)
            self._last_violated = ""
            self._violation_counts = {"adj": 0, "hosp": 0, "power": 0}
            self._dead_ends = 0
            self._bt_visits  = 0

            if self._bt(list(candidates), domains, assigned, counts, progress_cb):
                for nid, t in assigned.items():
                    g.set_node_type(nid, t)
                hospitals = g.all_of_type("Hospital")
                depots    = g.all_of_type("AmbulanceDepot")
                if hospitals: g.primary_hospital_id = hospitals[0]
                if depots:    g.ambulance_depot_id  = depots[0]
                if attempt > 0:
                    g.log(f"Challenge 1 ✓ CSP solved on attempt {attempt + 1} (AC-3 + Backtrack + MRV)")
                else:
                    g.log("Challenge 1 ✓ CSP layout solved (AC-3 + Backtrack + MRV)")
                return True

            # If we hit the visit limit, log it and try a fresh pool
            if self._bt_visits > self.MAX_BACKTRACK_VISITS:
                g.log(f"Challenge 1 ⚠ Attempt {attempt + 1} cut short "
                      f"({self._bt_visits} visits, {self._dead_ends} dead-ends) — "
                      f"retrying with fresh pool…")

        # All retries failed — identify blocking constraint and propose repair
        repair_ok = self._identify_and_repair(all_types, progress_cb)
        g.log(f"Challenge 1 {'⚠' if repair_ok else '✗'} {self.violation_reason}")
        # Return True when a minimum-conflict layout was placed so C2 can proceed;
        # the violation_reason makes clear this is a relaxed solution.
        return repair_ok

    def _bt(self, unassigned, domains, assigned, counts, cb) -> bool:
        self._bt_visits += 1
        if self._bt_visits > self.MAX_BACKTRACK_VISITS:
            return False  # abort this attempt, try next random pool
        if all(counts.get(t, 0) >= self.graph.required_counts[t] for t in self.graph.required_counts):
            return True
        if not unassigned:
            self._dead_ends += 1
            return False

        # MRV: pick variable with smallest remaining domain
        nid  = min(unassigned, key=lambda n: len(domains.get(n, [])))
        rest = [n for n in unassigned if n != nid]

        for t in list(domains.get(nid, [])):
            if t != "Empty" and counts.get(t, 0) >= self.graph.required_counts[t]:
                continue
            if not self._consistent(nid, t, assigned, counts):
                continue

            assigned[nid] = t
            counts[t]     = counts.get(t, 0) + 1

            # Forward checking: prune neighbours' domains
            pruned, ok = {}, True
            for e in self.graph.adj[nid]:
                nb = e.other(nid)
                if nb not in domains or nb in assigned:
                    continue
                banned = FORBIDDEN_ADJACENCY.get(t, set())
                new_d  = [v for v in domains[nb]
                          if v not in banned
                          and t not in FORBIDDEN_ADJACENCY.get(v, set())]
                if not new_d:
                    ok = False
                    break
                if new_d != domains[nb]:
                    pruned[nb]  = domains[nb]
                    domains[nb] = new_d

            if ok:
                if cb:
                    cb(len(assigned))
                if self._bt(rest, domains, assigned, counts, cb):
                    return True

            # Undo assignment and domain pruning
            del assigned[nid]
            counts[t] -= 1
            for nb, old_dom in pruned.items():
                domains[nb] = old_dom

        # Leave this cell Empty and continue
        return self._bt(rest, domains, assigned, counts, cb)

    # ── Minimum-conflict repair ────────────────────────────────

    def _identify_and_repair(self, all_types: list, progress_cb=None) -> bool:
        """
        Spec requirement: when no valid layout is possible, identify which
        specific rule is causing the conflict and propose a minimum-conflict
        solution (one constraint relaxed).
        Returns True if any layout (even partial) was successfully placed.
        """
        g = self.graph

        # Build a detailed violation summary for the log
        total_v = sum(self._violation_counts.values())
        detail_parts = []
        for tag, name in _CONSTRAINT_NAMES.items():
            c = self._violation_counts.get(tag, 0)
            if c > 0:
                detail_parts.append(f"'{name}' → {c} violations")
        detail = "; ".join(detail_parts) if detail_parts else "no specific violations tracked"
        self.violation_reason = (
            f"All {self.MAX_RETRIES} retries exhausted ({self._dead_ends} dead-ends). "
            f"Violations: {detail}. "
        )
        g.log(f"[C1] ✗ CSP could not find valid layout: {self.violation_reason}")

        # Try relaxing constraints in order of most → least violated
        ranked = sorted(
            _CONSTRAINT_NAMES.items(),
            key=lambda item: self._violation_counts.get(item[0], 0),
            reverse=True,
        )
        for skip_tag, name in ranked:
            ok, assigned = self._solve_relaxed(all_types, skip_tag, progress_cb)
            if ok:
                for nid, t in assigned.items():
                    g.set_node_type(nid, t)
                hospitals = g.all_of_type("Hospital")
                depots    = g.all_of_type("AmbulanceDepot")
                if hospitals: g.primary_hospital_id = hospitals[0]
                if depots:    g.ambulance_depot_id  = depots[0]

                self.violation_reason = (
                    f"Constraint '{name}' is blocking a fully valid layout "
                    f"({self._violation_counts.get(skip_tag, 0)} violations across "
                    f"{self.MAX_RETRIES} retries). "
                    f"Minimum-conflict solution applied: '{name}' was relaxed."
                )
                g.log(f"  ↳ Minimum-conflict layout: '{name}' relaxed — "
                      f"{len(assigned)} nodes placed")
                return True

        # If no single-constraint relaxation works either, apply greedy assignment
        assigned = self._greedy_assign(all_types)
        for nid, t in assigned.items():
            g.set_node_type(nid, t)
        hospitals = g.all_of_type("Hospital")
        depots    = g.all_of_type("AmbulanceDepot")
        if hospitals: g.primary_hospital_id = hospitals[0]
        if depots:    g.ambulance_depot_id  = depots[0]
        self.violation_reason = (
            "Multiple constraints conflict simultaneously. "
            "Greedy partial layout applied (may have violations)."
        )
        g.log(f"  ↳ Greedy partial layout: {len(assigned)} nodes placed with possible violations")
        return bool(assigned)

    def _consistent_relaxed(self, nid: int, t: str, assigned: dict,
                            counts: dict, skip: str) -> bool:
        """Consistency check with one named constraint skipped."""
        if t == "Empty":
            return True
        if skip != "adj" and not self._adj_ok(nid, t, assigned):
            return False
        rem_h = self.graph.required_counts["Hospital"]   - counts.get("Hospital",   0)
        rem_i = self.graph.required_counts["Industrial"] - counts.get("Industrial", 0)
        if skip != "hosp" and t == "Residential" and not self._hosp_reach(nid, assigned, rem_h):
            return False
        if skip != "power" and t == "PowerPlant" and not self._power_reach(nid, assigned, rem_i):
            return False
        return True

    def _solve_relaxed(self, all_types: list, skip: str,
                       progress_cb=None) -> tuple[bool, dict]:
        """
        Attempt to solve with one constraint disabled.
        Returns (success, assignment_dict).
        """
        total = sum(self.graph.required_counts.values())
        pool  = list(range(TOTAL_NODES))
        random.shuffle(pool)
        candidates = pool[:total]

        domains = {nid: list(all_types) for nid in candidates}

        # Only run AC-3 when adjacency constraint is still active
        if skip != "adj":
            if not self._ac3(domains):
                return False, {}

        assigned: dict[int, str] = {}
        counts:   dict[str, int] = defaultdict(int)

        ok = self._bt_relaxed(list(candidates), domains, assigned, counts,
                              skip, progress_cb)
        return ok, assigned

    def _bt_relaxed(self, unassigned, domains, assigned, counts,
                    skip, cb) -> bool:
        """Backtracking without forward-checking, one constraint relaxed."""
        if all(counts.get(t, 0) >= self.graph.required_counts[t] for t in self.graph.required_counts):
            return True
        if not unassigned:
            return False

        all_types = list(self.graph.required_counts.keys()) + ["Empty"]
        nid  = min(unassigned, key=lambda n: len(domains.get(n, all_types)))
        rest = [n for n in unassigned if n != nid]

        for t in list(domains.get(nid, all_types)):
            if t != "Empty" and counts.get(t, 0) >= self.graph.required_counts[t]:
                continue
            if not self._consistent_relaxed(nid, t, assigned, counts, skip):
                continue
            assigned[nid] = t
            counts[t]     = counts.get(t, 0) + 1
            if cb:
                cb(len(assigned))
            if self._bt_relaxed(rest, domains, assigned, counts, skip, cb):
                return True
            del assigned[nid]
            counts[t] -= 1

        return self._bt_relaxed(rest, domains, assigned, counts, skip, cb)

    def _greedy_assign(self, all_types: list) -> dict[int, str]:
        """Last-resort greedy assignment — ignores all hard constraints."""
        total = sum(self.graph.required_counts.values())
        pool  = list(range(TOTAL_NODES))
        random.shuffle(pool)
        candidates = pool[:total]

        assigned: dict[int, str] = {}
        counts:   dict[str, int] = defaultdict(int)

        for nid in candidates:
            for t in all_types:
                if counts.get(t, 0) < self.graph.required_counts[t]:
                    # prefer adjacency-safe assignment
                    if self._adj_ok(nid, t, assigned):
                        assigned[nid] = t
                        counts[t]     = counts.get(t, 0) + 1
                        break
            else:
                # adjacency violated — assign first available type
                for t in all_types:
                    if counts.get(t, 0) < self.graph.required_counts[t]:
                        assigned[nid] = t
                        counts[t]     = counts.get(t, 0) + 1
                        break

        return assigned
