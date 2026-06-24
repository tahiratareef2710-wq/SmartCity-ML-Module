"""
city_engine.py
==============
CityMind – Shared data layer (no GUI, no algorithm code).
Contains: constants, Node, Edge, CityGraph.
Algorithms live in challenge1.py (CSP) and challenge2.py (Kruskal MST).
"""

import math
import time
from collections import deque
from typing import Optional

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────

GRID_ROWS  = 20
GRID_COLS  = 20
TOTAL_NODES = GRID_ROWS * GRID_COLS   # 400

REQUIRED_COUNTS = {
    "Residential":    60,
    "Hospital":        2,
    "School":          3,
    "Industrial":      4,
    "PowerPlant":      2,
    "AmbulanceDepot":  1,
}

# Hard adjacency ban: type → set of types it may NOT touch
FORBIDDEN_ADJACENCY = {
    "Industrial": {"School", "Hospital"},
    "School":     {"Industrial"},
    "Hospital":   {"Industrial"},
}

CRIME_MULTIPLIERS = {"High": 1.5, "Medium": 1.2, "Low": 1.0}


# ─────────────────────────────────────────────────────────────
#  SHARED DATA STRUCTURES
# ─────────────────────────────────────────────────────────────

class Node:
    __slots__ = ("id", "row", "col", "type",
                 "population_density", "risk_index",
                 "accessible", "crime_risk", "active")

    def __init__(self, node_id: int):
        self.id   = node_id
        self.row  = node_id // GRID_COLS
        self.col  = node_id %  GRID_COLS
        self.type = "Empty"
        self.population_density: float = 0.0
        self.risk_index: float  = 0.0
        self.accessible: bool   = True
        self.crime_risk: str    = "Low"
        self.active: bool       = True

    def __repr__(self):
        return f"Node({self.id}, {self.type})"


class Edge:
    __slots__ = ("from_id", "to_id", "base_cost", "flooded", "crime_risk")

    def __init__(self, from_id: int, to_id: int, base_cost: float = 1.0):
        self.from_id   = from_id
        self.to_id     = to_id
        self.base_cost = base_cost
        self.flooded   = False
        self.crime_risk: str = "Low"

    def effective_cost(self) -> float:
        """Single cost function used by ALL modules. Never cache this."""
        if self.flooded:
            return float("inf")
        return self.base_cost * CRIME_MULTIPLIERS.get(self.crime_risk, 1.0)

    def other(self, nid: int) -> int:
        return self.to_id if self.from_id == nid else self.from_id


class CityGraph:
    """
    Single shared data structure for all five challenges.
    No module may store a local copy of any edge cost.
    """

    def __init__(self):
        self.nodes: list[Node] = [Node(i) for i in range(TOTAL_NODES)]
        self.adj: dict[int, list[Edge]] = {i: [] for i in range(TOTAL_NODES)}
        self._edge_map: dict[tuple, Edge] = {}   # (min_id, max_id) → Edge
        self._build_grid()

        # Configurable counts — defaults from REQUIRED_COUNTS, overridable at runtime
        self.required_counts: dict[str, int] = dict(REQUIRED_COUNTS)

        # Challenge 1 / 2 results
        self.primary_hospital_id: Optional[int]  = None
        self.ambulance_depot_id:  Optional[int]  = None
        self.mst_edges:   list[Edge]             = []
        self.augment_edges: list[Edge]           = []   # all backup edges (Challenge 2)

        # Challenge 3 result — kept here so all modules share one source of truth
        self.ambulance_positions: list[int]      = []

        # Shared event log
        self.event_log: list[str] = []

    # ── Build ──────────────────────────────────────────────────

    def _build_grid(self):
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                nid = r * GRID_COLS + c
                for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)):
                    nr, nc = r+dr, c+dc
                    if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                        nbr = nr * GRID_COLS + nc
                        key = (min(nid,nbr), max(nid,nbr))
                        if key not in self._edge_map:
                            e = Edge(nid, nbr)
                            self._edge_map[key] = e
                        self.adj[nid].append(self._edge_map[key])

    # ── Public API ─────────────────────────────────────────────

    def get_node(self, nid: int) -> Node:
        return self.nodes[nid]

    def get_neighbors(self, nid: int) -> list[Edge]:
        """Non-flooded edges only."""
        return [e for e in self.adj[nid] if not e.flooded]

    def get_edge(self, a: int, b: int) -> Optional[Edge]:
        return self._edge_map.get((min(a,b), max(a,b)))

    def set_node_type(self, nid: int, t: str):
        self.nodes[nid].type = t
        if t == "Residential":
            for e in self.adj[nid]:
                self._edge_map[(min(e.from_id,e.to_id),
                                max(e.from_id,e.to_id))].base_cost = 0.8

    def flood_edge(self, a: int, b: int):
        e = self.get_edge(a, b)
        if e:
            e.flooded = True
            self.log(f"[FLOOD] Road {a}↔{b} blocked")

    def unflood_edge(self, a: int, b: int):
        e = self.get_edge(a, b)
        if e:
            e.flooded = False
            self.log(f"[RESTORE] Road {a}↔{b} reopened")

    def update_risk_index(self, nid: int, value: float):
        n = self.nodes[nid]
        n.risk_index = value
        n.crime_risk = ("High" if value >= 0.7
                        else "Medium" if value >= 0.4
                        else "Low")
        for e in self.adj[nid]:
            e.crime_risk = n.crime_risk

    def all_of_type(self, t: str) -> list[int]:
        return [n.id for n in self.nodes if n.type == t]

    def toggle_node(self, nid: int, active: bool):
        """Mark a node as active or inactive. Inactive nodes are excluded from
        routing and facility placement but remain in the graph."""
        n = self.nodes[nid]
        was_active = n.active
        n.active = active
        n.accessible = active
        status = "activated" if active else "deactivated"
        self.log(f"[NODE] Node {nid} ({n.type}) {status}")

    def get_active_nodes(self) -> list[int]:
        """Return IDs of all nodes where accessible=True and active=True."""
        return [n.id for n in self.nodes if n.active and n.accessible]

    def find_placement_candidate(self, node_type: str) -> Optional[int]:
        """Return the best candidate node for placing a new facility of the
        given type. Follows the 3-step priority order:
          1. Empty node that satisfies placement constraints
          2. Inactive / repurposable node (non-essential type)
          3. Return None — caller must inform user that expansion is needed
        """
        # Step 1: find an Empty node that satisfies adjacency constraints
        banned_adj = FORBIDDEN_ADJACENCY.get(node_type, set())
        for n in self.nodes:
            if n.type != "Empty" or not n.active:
                continue
            ok = True
            for e in self.adj[n.id]:
                nb = self.nodes[e.other(n.id)]
                if nb.type in banned_adj:
                    ok = False
                    break
                if nb.type and node_type in FORBIDDEN_ADJACENCY.get(nb.type, set()):
                    ok = False
                    break
            if ok:
                return n.id

        # Step 2: find a repurposable inactive node
        for n in self.nodes:
            if n.active:
                continue
            ok = True
            for e in self.adj[n.id]:
                nb = self.nodes[e.other(n.id)]
                if nb.type in banned_adj:
                    ok = False
                    break
                if nb.type and node_type in FORBIDDEN_ADJACENCY.get(nb.type, set()):
                    ok = False
                    break
            if ok:
                return n.id

        # Step 3: no candidate found
        return None

    def bfs_hops(self, start: int, targets: set[str]) -> int:
        """Hop count from start to nearest node whose type is in targets.
        Uses only non-flooded edges — consistent with the 'blocked = impassable' rule."""
        visited, q = {start}, deque([(start, 0)])
        while q:
            nid, d = q.popleft()
            if self.nodes[nid].type in targets:
                return d
            for e in self.get_neighbors(nid):   # respects flooded edges
                nb = e.other(nid)
                if nb not in visited:
                    visited.add(nb)
                    q.append((nb, d+1))
        return 9999

    def set_required_counts(self, counts: dict[str, int]):
        """Update the required node counts at runtime (demo-configurable)."""
        for t, c in counts.items():
            if t in REQUIRED_COUNTS:
                self.required_counts[t] = max(0, c)
        self.log(f"[CONFIG] Required counts updated: {self.required_counts}")

    def reset(self):
        """Clear layout and results, keep graph topology."""
        for n in self.nodes:
            n.type       = "Empty"
            n.risk_index = 0.0
            n.crime_risk = "Low"
            n.accessible = True
            n.active     = True
        self.required_counts = dict(REQUIRED_COUNTS)  # restore defaults
        for e in self._edge_map.values():
            e.flooded    = False
            e.base_cost  = 1.0
            e.crime_risk = "Low"
        self.mst_edges           = []
        self.augment_edges       = []
        self.ambulance_positions = []
        self.primary_hospital_id = None
        self.ambulance_depot_id  = None
        self.event_log           = []

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.event_log.append(entry)
        if len(self.event_log) > 300:
            self.event_log = self.event_log[-300:]

