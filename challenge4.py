"""
challenge4.py
=============
Challenge 4 – Emergency Routing Under Changing Conditions
Technique: A* with consistent Euclidean heuristic.

Design Doc Requirement:
  h(n) = Euclidean_distance(n, goal) × min_edge_cost (0.8)
  
Admissibility: Euclidean distance never overestimates true path cost
Consistency: h(n) ≤ cost(n,n') + h(n') holds because moving one step
             reduces Euclidean distance by at most 1.0 while edge cost >= 0.8

Re-routes automatically when a road floods mid-journey.
Skips unreachable civilians (logs & moves to next target).
"""

import heapq
import math

from city_engine import CityGraph


# ── Heuristic (Euclidean as per design doc) ──────────────────

def _heuristic(graph: CityGraph, a: int, b: int) -> float:
    """
    Admissible & consistent for 4-connected grids:
      h(n) = Euclidean_distance(n, goal) × min_edge_cost (0.8)
    
    Euclidean distance is the straight-line distance between nodes.
    Multiplied by 0.8 (minimum possible edge cost) ensures admissibility
    because no path can be shorter than the straight line times min cost.
    """
    na, nb = graph.nodes[a], graph.nodes[b]
    dx = na.col - nb.col
    dy = na.row - nb.row
    euclidean_dist = math.sqrt(dx * dx + dy * dy)
    return euclidean_dist * 0.8  # min_edge_cost


# ── A* ────────────────────────────────────────────────────────

def astar(graph: CityGraph, start: int, goal: int
          ) -> tuple[list[int], float]:
    """
    Returns (path, total_cost).
    path is a list of node IDs from start to goal (inclusive).
    Returns ([], inf) if goal is unreachable.
    """
    # Early exit: start == goal
    if start == goal:
        return [start], 0.0
    
    g_cost = {start: 0.0}
    f_cost = {start: _heuristic(graph, start, goal)}
    prev   = {start: None}
    open_q = [(f_cost[start], start)]
    closed: set[int] = set()

    while open_q:
        _, u = heapq.heappop(open_q)

        if u in closed:
            continue
        closed.add(u)

        if u == goal:
            # Reconstruct path
            path, cur = [], goal
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            path.reverse()
            return path, g_cost[goal]

        for e in graph.adj[u]:
            v = e.other(u)
            cost = e.effective_cost()
            if cost == float("inf"):
                continue
            ng = g_cost[u] + cost
            if ng < g_cost.get(v, float("inf")):
                g_cost[v] = ng
                f_cost[v] = ng + _heuristic(graph, v, goal)
                prev[v] = u
                heapq.heappush(open_q, (f_cost[v], v))

    return [], float("inf")


# ── Emergency Router ──────────────────────────────────────────

class EmergencyRouter:
    """
    Manages the medical team's journey through a list of civilian nodes.
    
    Per design doc:
    - A* with Euclidean heuristic for pathfinding
    - Re-routes automatically when roads flood
    - Skips unreachable civilians with proper logging
    """

    def __init__(self, graph: CityGraph):
        self.graph = graph
        self.position = 0
        self.civilians: list[int] = []
        self.target_idx = 0
        self.current_path: list[int] = []
        self.path_cost = 0.0
        self.step = 0
        self.visited_civilians: list[int] = []
        self.skipped_civilians: list[int] = []

    def set_civilians(self, civilian_nodes: list[int], start: int):
        """Initialize the civilian sequence and starting position."""
        self.civilians = list(civilian_nodes)
        self.target_idx = 0
        self.position = start
        self.current_path = []
        self.path_cost = 0.0
        self.visited_civilians = []
        self.skipped_civilians = []
        self.step = 0
        self._plan_path()

    # ── Path planning (iterative, per design doc) ─────────────

    def _plan_path(self):
        """
        (Re-)compute A* path from current position to the current target.
        
        Per design doc: If civilian unreachable (A* exhausts all nodes),
        log and skip to next civilian. Uses iterative loop (not recursion)
        to handle long sequences of unreachable civilians safely.
        """
        while self.target_idx < len(self.civilians):
            goal = self.civilians[self.target_idx]
            
            # Don't bother A* if we're already at the goal
            if self.position == goal:
                self.current_path = [goal]
                self.path_cost = 0.0
                self.graph.log(
                    f"[S{self.step:02d}] Already at civilian node {goal}"
                )
                return
            
            path, cost = astar(self.graph, self.position, goal)

            if cost == float("inf"):
                # Design doc protocol: log and skip unreachable civilian
                self.graph.log(
                    f"[S{self.step:02d}] Civilian at node {goal} unreachable "
                    f"— all routes flooded. Skipping to next target."
                )
                self.skipped_civilians.append(goal)
                self.target_idx += 1
                # loop continues to next civilian automatically
            else:
                prev_cost = self.path_cost
                self.current_path = path
                self.path_cost = cost
                
                if prev_cost > 0 and abs(cost - prev_cost) > 0.01:
                    self.graph.log(
                        f"[S{self.step:02d}] A* re-route to node {goal}: "
                        f"cost {cost:.1f} (was {prev_cost:.1f})"
                    )
                else:
                    self.graph.log(
                        f"[S{self.step:02d}] A* path to node {goal}: "
                        f"cost {cost:.1f} ({len(path)-1} hops)"
                    )
                return  # found a reachable target

        # All remaining civilians are unreachable or list is exhausted
        self.current_path = []

    # ── Movement (per design doc) ─────────────────────────────

    def advance(self, step: int) -> int | None:
        """
        Move the team one step along the current path.
        
        Per design doc: Takes the current simulation step so log messages
        stay synchronized. Returns new position, or None if all civilians
        are handled.
        """
        self.step = step

        # Check if we're done with all civilians
        if self.target_idx >= len(self.civilians):
            return None

        # If no path or path is exhausted, try to plan a new one
        if not self.current_path or len(self.current_path) <= 1:
            # Check if we're at the current target
            if self.target_idx < len(self.civilians):
                if self.position == self.civilians[self.target_idx]:
                    self.graph.log(
                        f"[S{self.step:02d}] Reached civilian at node {self.position} ✓"
                    )
                    self.visited_civilians.append(self.position)
                    self.target_idx += 1
                    self._plan_path()
            return self.position

        # Take one step along the planned path
        # Current path includes current position at index 0
        self.current_path.pop(0)  # Remove current position
        self.position = self.current_path[0]  # Move to next node

        # Check if we've reached the target civilian
        goal = self.civilians[self.target_idx]
        if self.position == goal:
            self.graph.log(
                f"[S{self.step:02d}] Reached civilian at node {goal} ✓"
            )
            self.visited_civilians.append(goal)
            self.target_idx += 1
            self._plan_path()

        return self.position

    # ── Event handlers (per design doc) ───────────────────────

    def notify_flood(self, step: int):
        """
        Call after any flood event to trigger A* re-planning.
        
        Per design doc: The system re-routes the moment any road becomes
        impassable. This method is called when a flood event occurs.
        """
        self.step = step
        if self.target_idx < len(self.civilians):
            self.graph.log(
                f"[S{step:02d}] Flood detected — re-routing A* "
                f"from node {self.position}"
            )
            self._plan_path()

    # ── Properties ─────────────────────────────────────────────

    @property
    def done(self) -> bool:
        """Returns True if all civilians have been visited or skipped."""
        return self.target_idx >= len(self.civilians)

    @property
    def current_target(self) -> int | None:
        """Returns the current target civilian node ID, or None if done."""
        if self.target_idx < len(self.civilians):
            return self.civilians[self.target_idx]
        return None