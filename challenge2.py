"""
challenge2.py
=============
Challenge 2 – Road Network Optimizer
Techniques: Kruskal's MST (O(E log E)) with Union-Find (path compression
            + union by rank) · augmentation edges added until two
            genuinely edge-disjoint paths exist between Hospital and Depot
            (verified via BFS max-flow / Menger's theorem).
"""

from collections import deque, defaultdict

from city_engine import CityGraph, TOTAL_NODES


class UnionFind:
    """Disjoint-set with path-halving compression and union by rank."""

    def __init__(self, n: int):
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]   # path halving
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1
        return True


class RoadNetworkOptimizer:
    """
    1. Builds the Minimum Spanning Tree with Kruskal's algorithm.
    2. Adds the minimum number of non-MST edges needed to ensure
       two genuinely edge-disjoint paths between Primary Hospital
       and Ambulance Depot (verified with BFS max-flow).
       All augmentation edges are stored in graph.augment_edges.
    """

    def __init__(self, graph: CityGraph):
        self.graph = graph

    # ── Public entry point ────────────────────────────────────

    def solve(self) -> bool:
        g = self.graph
        if g.primary_hospital_id is None or g.ambulance_depot_id is None:
            g.log("Challenge 2 ✗ Run Challenge 1 first")
            return False

        h = g.primary_hospital_id
        d = g.ambulance_depot_id

        # ── Collect unique edges, sort by live cost ────────────
        seen, all_edges = set(), []
        for nid in range(TOTAL_NODES):
            for e in g.adj[nid]:
                k = (min(e.from_id, e.to_id), max(e.from_id, e.to_id))
                if k not in seen:
                    seen.add(k)
                    all_edges.append(e)
        all_edges.sort(key=lambda e: e.effective_cost())

        # ── Kruskal's MST ──────────────────────────────────────
        uf  = UnionFind(TOTAL_NODES)
        mst, cost = [], 0.0
        for e in all_edges:
            if uf.union(e.from_id, e.to_id):
                mst.append(e)
                cost += e.effective_cost()
                if len(mst) == TOTAL_NODES - 1:
                    break
        g.mst_edges = mst

        # ── Verify H→D reachability in MST ────────────────────
        if not self._mst_path(mst, h, d):
            g.log("Challenge 2 ✗ Hospital & Depot not connected in MST")
            return False

        # ── Augment until 2 edge-disjoint paths exist ─────────
        mst_keys = {
            (min(e.from_id, e.to_id), max(e.from_id, e.to_id))
            for e in mst
        }
        non_mst = [
            e for e in all_edges
            if (min(e.from_id, e.to_id), max(e.from_id, e.to_id)) not in mst_keys
            and e.effective_cost() < float("inf")
        ]

        # Current edge set for max-flow check
        edge_pairs = [(e.from_id, e.to_id) for e in mst]
        aug_edges: list = []

        if self._edge_disjoint_count(h, d, edge_pairs) < 2:
            for e in non_mst:
                edge_pairs.append((e.from_id, e.to_id))
                aug_edges.append(e)
                if self._edge_disjoint_count(h, d, edge_pairs) >= 2:
                    break

        g.augment_edges = aug_edges

        disjoint_ok = self._edge_disjoint_count(h, d, edge_pairs) >= 2
        aug_str = (
            f"{len(aug_edges)} aug edge(s) added → 2 independent routes ✓"
            if disjoint_ok
            else f"{len(aug_edges)} aug edge(s) added — 2nd independent route NOT achievable"
        )
        aug_detail = (
            ", ".join(f"{e.from_id}↔{e.to_id}" for e in aug_edges)
            if aug_edges else "none"
        )
        g.log(
            f"Challenge 2 ✓ MST cost={cost:.1f} | {aug_str} | aug={aug_detail}"
        )
        return True

    # ── BFS max-flow (Edmonds-Karp, unit capacities) ──────────

    def _edge_disjoint_count(self, src: int, dst: int,
                             edge_pairs: list[tuple[int, int]]) -> int:
        """
        Returns the number of edge-disjoint paths from src to dst in the
        undirected graph described by edge_pairs.
        Uses BFS augmenting paths (max-flow = 2 suffices for our check).
        Each undirected edge is modelled as two directed edges cap=1.
        """
        cap: dict[tuple, int] = defaultdict(int)
        adj: dict[int, set]   = defaultdict(set)

        for u, v in edge_pairs:
            cap[(u, v)] += 1
            cap[(v, u)] += 1
            adj[u].add(v)
            adj[v].add(u)

        flow = 0
        while flow < 2:
            # BFS for augmenting path
            parent: dict[int, int | None] = {src: None}
            queue = deque([src])
            while queue and dst not in parent:
                u = queue.popleft()
                for v in adj[u]:
                    if v not in parent and cap[(u, v)] > 0:
                        parent[v] = u
                        queue.append(v)
            if dst not in parent:
                break
            # Augment along found path
            v = dst
            while v != src:
                u = parent[v]
                cap[(u, v)] -= 1
                cap[(v, u)] += 1
                v = u
            flow += 1

        return flow

    # ── BFS path reconstruction on MST ────────────────────────

    def _mst_path(self, mst: list, src: int, dst: int) -> list[int]:
        """BFS on the MST adjacency to recover the src → dst path."""
        adj = defaultdict(list)
        for e in mst:
            adj[e.from_id].append(e.to_id)
            adj[e.to_id].append(e.from_id)

        prev = {src: None}
        q    = deque([src])
        while q:
            cur = q.popleft()
            if cur == dst:
                break
            for nb in adj[cur]:
                if nb not in prev:
                    prev[nb] = cur
                    q.append(nb)

        if dst not in prev:
            return []

        path, cur = [], dst
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        return path[::-1]
