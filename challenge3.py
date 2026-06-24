"""
challenge3.py
=============
Challenge 3 – Ambulance Placement via Genetic Algorithm
Technique: GA with tournament selection, uniform crossover, mutation.
Fitness  : negative of max Dijkstra distance from any Residential node
           to its nearest ambulance (using effective_cost()).
Re-eval  : warm-starts from previous best when called mid-simulation.
"""

import heapq
import random

from city_engine import CityGraph, TOTAL_NODES


# ── Multi-source Dijkstra (single pass, cost-weighted) ───────

def _multi_source_dijkstra(graph: CityGraph, sources: list[int]) -> dict[int, float]:
    """
    Single Dijkstra run from multiple sources.
    Returns {node_id: shortest cost from nearest source}.
    O(E log V) instead of O(sources × E log V).
    """
    dist = {s: 0.0 for s in sources}
    pq = [(0.0, s) for s in sources]
    heapq.heapify(pq)
    
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for e in graph.adj[u]:
            v = e.other(u)
            cost = e.effective_cost()
            if cost == float("inf"):
                continue
            nd = d + cost
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


# ── Fitness ───────────────────────────────────────────────────

def _fitness(graph: CityGraph, placement: tuple[int, int, int], residential: list[int]) -> float:
    """
    Returns negative max-distance (higher = better).
    Unreachable residential nodes are treated as distance 1e9.
    """
    if not residential:
        return 0.0
    
    # Single multi-source Dijkstra instead of 3 separate runs
    dist_from_ambulances = _multi_source_dijkstra(graph, list(placement))
    
    worst = 0.0
    for r in residential:
        best = dist_from_ambulances.get(r, 1e9)
        if best > worst:
            worst = best
    
    return -worst


# ── Genetic Algorithm ─────────────────────────────────────────

class AmbulancePlacer:
    """
    Places NUM_AMBULANCES ambulances to minimise worst-case response time.
    Per design spec, ambulances may be placed on ANY node (not restricted to
    depots) to maximise coverage geometry.
    All parameters are runtime-configurable via set_params().
    """

    # Defaults — overridable per instance
    _DEFAULT_PARAMS = {
        "num_ambulances": 3,
        "pop_size":       60,
        "generations":    50,
        "mutation_rate":  0.05,
        "tournament_k":   5,
        "patience":       20,
    }

    def __init__(self, graph: CityGraph):
        self.graph      = graph
        self.best_placement: tuple | None = None
        self.ambulance_positions: list[int] = []
        # Initialise with defaults
        self.num_ambulances = self._DEFAULT_PARAMS["num_ambulances"]
        self.pop_size       = self._DEFAULT_PARAMS["pop_size"]
        self.generations    = self._DEFAULT_PARAMS["generations"]
        self.mutation_rate  = self._DEFAULT_PARAMS["mutation_rate"]
        self.tournament_k   = self._DEFAULT_PARAMS["tournament_k"]
        self.patience       = self._DEFAULT_PARAMS["patience"]

    def set_params(self, **kwargs):
        """Update GA parameters at runtime (demo-configurable)."""
        for key, val in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, val)
        self.graph.log(
            f"[CONFIG] GA params: pop={self.pop_size} gens={self.generations} "
            f"mut={self.mutation_rate} k={self.tournament_k} amb={self.num_ambulances}"
        )

    # ── Public API ────────────────────────────────────────────

    def solve(self, warm_start: bool = False, extra_gens: int = 0) -> bool:
        g = self.graph
        total_nodes = TOTAL_NODES

        gens = extra_gens if (warm_start and extra_gens > 0) else self.generations

        # Valid nodes: exclude Empty cells (no inhabitants to serve)
        # All other types (Residential, Hospital, School, Industrial, 
        # PowerPlant, AmbulanceDepot) are valid placement locations.
        valid_nodes = [nd.id for nd in self.graph.nodes if nd.type != "Empty"]
        if len(valid_nodes) < self.num_ambulances:
            valid_nodes = list(range(total_nodes))   # absolute fallback

        # ── Initialise population ──────────────────────────────
        population: list[tuple] = []

        if warm_start and self.best_placement:
            population.append(self.best_placement)

        while len(population) < self.pop_size:
            ind = tuple(random.sample(valid_nodes,
                                      min(self.num_ambulances, len(valid_nodes))))
            population.append(ind)

        best_fit = float("-inf")
        stale    = 0
        
        # Cache residential list once to avoid 400-node loop per evaluation
        residential_list = [n.id for n in self.graph.nodes if n.type == "Residential"]
        
        # Cache fitness values for identical placements across generations
        fitness_cache: dict[tuple, float] = {}

        for gen in range(gens):
            scored = []
            for ind in population:
                if ind not in fitness_cache:
                    fitness_cache[ind] = self._fitness(ind, residential_list)
                scored.append((fitness_cache[ind], ind))
            
            scored.sort(reverse=True)

            top_fit, top_ind = scored[0]
            if top_fit > best_fit:
                best_fit            = top_fit
                self.best_placement = top_ind
                stale = 0
            else:
                stale += 1

            if stale >= self.patience:
                break

            next_pop = [top_ind]   # elitism: always keep best individual
            while len(next_pop) < self.pop_size:
                p1 = self._tournament(scored)
                p2 = self._tournament(scored)
                child = self._crossover(p1, p2, valid_nodes)
                child = self._mutate(child, valid_nodes)
                next_pop.append(child)
            population = next_pop

        if self.best_placement:
            self.ambulance_positions = list(self.best_placement)
            g.ambulance_positions = self.ambulance_positions
            # worst-case distance is -best_fit (since best_fit is negative)
            worst_dist = -best_fit if best_fit != float("-inf") else 0.0
            mode = "warm-start" if warm_start else "fresh"
            g.log(
                f"Challenge 3 ✓ GA ({mode}, {gens} gens) "
                f"ambulances={list(self.best_placement)} "
                f"worst-case dist={worst_dist:.1f}"
            )
            return True

        g.log("Challenge 3 ✗ GA failed to place ambulances")
        return False

    # ── GA operators ─────────────────────────────────────────

    def _fitness(self, ind: tuple, residential: list[int]) -> float:
        return _fitness(self.graph, ind, residential)

    def _tournament(self, scored: list) -> tuple:
        contestants = random.sample(scored, min(self.tournament_k, len(scored)))
        return max(contestants, key=lambda x: x[0])[1]

    def _crossover(self, p1: tuple, p2: tuple,
                   valid_nodes: list[int]) -> tuple:
        """
        True uniform crossover — each position slot independently inherits
        from p1 or p2 with equal probability (50/50).
        Duplicates are resolved by sampling from valid_nodes without replacement.
        """
        child: set[int] = set()

        # Per-slot independent inheritance
        for i in range(self.num_ambulances):
            child.add(p1[i] if random.random() < 0.5 else p2[i])

        # If duplicates reduced the set below NUM_AMBULANCES, pad with
        # random valid nodes that are not already chosen.
        remaining = [v for v in valid_nodes if v not in child]
        random.shuffle(remaining)
        for v in remaining:
            if len(child) == self.num_ambulances:
                break
            child.add(v)

        # Last-resort fallback (shouldn't be needed with a proper valid_nodes list)
        if len(child) < self.num_ambulances:
            all_nodes = list(range(TOTAL_NODES))
            random.shuffle(all_nodes)
            for v in all_nodes:
                if len(child) == self.num_ambulances:
                    break
                child.add(v)

        return tuple(sorted(child))

    def _mutate(self, ind: tuple, valid_nodes: list[int]) -> tuple:
        """
        Mutation: with probability MUTATION_RATE, replace one ambulance 
        position with a random valid node. Guarantees exactly NUM_AMBULANCES 
        unique positions after mutation.
        """
        ind_list = list(ind)

        for i in range(len(ind_list)):
            if random.random() < self.mutation_rate:
                ind_list[i] = random.choice(valid_nodes)

        # Remove duplicates while preserving order
        seen: set[int] = set()
        unique: list[int] = []
        for v in ind_list:
            if v not in seen:
                seen.add(v)
                unique.append(v)

        # Pad with random unique valid nodes until we have exactly NUM_AMBULANCES
        candidates = [v for v in valid_nodes if v not in seen]
        random.shuffle(candidates)
        for v in candidates:
            if len(unique) == self.num_ambulances:
                break
            unique.append(v)
            seen.add(v)

        # Absolute fallback across all nodes (extremely unlikely to be needed)
        if len(unique) < self.num_ambulances:
            all_nodes = [v for v in range(TOTAL_NODES) if v not in seen]
            random.shuffle(all_nodes)
            for v in all_nodes:
                if len(unique) == self.num_ambulances:
                    break
                unique.append(v)

        return tuple(sorted(unique[:self.num_ambulances]))