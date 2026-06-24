"""
simulation.py
=============
Member B – shared duties:
  • 20-step simulation loop
  • Random flood event generator
  • Live event log system integration
"""

import random
from city_engine import CityGraph, TOTAL_NODES
from challenge3 import AmbulancePlacer
from challenge4 import EmergencyRouter


# ── Flood event generator ─────────────────────────────────────

class FloodGenerator:
    """
    At each simulation step, randomly floods 0–2 edges and may
    unflood previously flooded edges to keep roads dynamic.
    """
    FLOOD_PROB   = 0.30
    UNFLD_PROB   = 0.25
    MAX_PER_STEP = 2

    def __init__(self, graph: CityGraph):
        self.graph       = graph
        self.flooded_log: list[tuple[int, int]] = []

    def tick(self, step: int) -> list[tuple[int, int]]:
        """
        Returns list of (a, b) pairs newly flooded this step.
        Also probabilistically restores some existing floods.
        """
        g     = self.graph
        edges = list(g._edge_map.values())
        new_floods: list[tuple[int, int]] = []

        if random.random() < self.UNFLD_PROB:
            flooded_edges = [e for e in edges if e.flooded]
            if flooded_edges:
                e = random.choice(flooded_edges)
                g.unflood_edge(e.from_id, e.to_id)

        if random.random() < self.FLOOD_PROB:
            count      = random.randint(1, self.MAX_PER_STEP)
            candidates = [e for e in edges if not e.flooded]
            random.shuffle(candidates)
            for e in candidates[:count]:
                g.flood_edge(e.from_id, e.to_id)
                new_floods.append((e.from_id, e.to_id))

        return new_floods


# ── 20-step simulation loop ───────────────────────────────────

class Simulation:
    """
    Orchestrates the 20-step city simulation.

    Step 0  – run Challenge 5 (one-shot crime prediction) → place ambulances (GA)
    S1–S20  – each step:
                1. Generate flood events
                2. Re-route medical team (A*) if flooded
                3. Advance medical team one hop
                4. Re-place ambulances if flood changed roads (GA warm-start)

    Crime prediction is computed once at initialisation. It can be manually
    re-triggered via the Challenge 5 button in the UI, but floods do NOT
    automatically re-run it — the city layout is static during simulation.
    """

    TOTAL_STEPS   = 20
    NUM_CIVILIANS = 8

    def __init__(self, graph: CityGraph,
                 placer: AmbulancePlacer,
                 router: EmergencyRouter,
                 crime_predictor=None):
        self.graph           = graph
        self.placer          = placer
        self.router          = router
        self.crime_predictor = crime_predictor
        self.flood_gen       = FloodGenerator(graph)

        self.step          = 0
        self.running       = False
        self.complete      = False

        self.civilians:  list[int] = []
        self.team_start: int       = 0

    # ── Setup ─────────────────────────────────────────────────

    def initialise(self) -> bool:
        """
        Call after Challenge 1 & 2 are done.
        Returns False if prerequisites are not met.
        """
        g = self.graph

        if not g.mst_edges:
            g.log("Simulation ✗ Run Challenge 2 (MST) before starting simulation")
            return False

        residential = g.all_of_type("Residential")
        if not residential:
            g.log("Simulation ✗ Run Challenge 1 first")
            return False

        # S0: run Challenge 5 first so crime weights and edge effective_costs
        # are set before the GA evaluates fitness and A* plans any path.
        # Without this, all nodes default to "Low" risk (multiplier ×1.0)
        # and the GA/A* never see the real cost landscape.
        if self.crime_predictor is not None:
            g.log("▶ S0 – running Challenge 5 (crime risk) before placement…")
            ok5 = self.crime_predictor.solve()
            if not ok5:
                g.log("Simulation ✗ Challenge 5 failed at initialisation")
                return False
        else:
            g.log("Simulation ⚠ No crime predictor set — risk weights will be default Low")

        g.log("▶ Simulation – initialising (GA ambulance placement)…")

        ok = self.placer.solve(warm_start=False)
        if not ok:
            g.log("Simulation ✗ GA failed")
            return False

        amb_set = set(self.placer.ambulance_positions)
        pool    = [r for r in residential if r not in amb_set]
        random.shuffle(pool)
        candidates = pool[:self.NUM_CIVILIANS]

        if g.primary_hospital_id is None:
            g.log("Simulation ✗ No primary hospital set — run Challenge 1 first")
            return False
        self.team_start = g.primary_hospital_id

        # Sort civilians by hop distance from hospital (closest first)
        # so the team reaches the nearest ones first within the 20-step limit.
        from challenge4 import astar
        def _hop_dist(nid):
            path, cost = astar(g, self.team_start, nid)
            return len(path) if path else 9999
        candidates.sort(key=_hop_dist)
        self.civilians = candidates

        self.router.set_civilians(self.civilians, self.team_start)

        g.log(
            f"Simulation ✓ S0 ready | "
            f"ambulances={self.placer.ambulance_positions} | "
            f"civilians={self.civilians} | "
            f"team starts at node {self.team_start}"
        )
        self.step     = 0
        self.running  = True
        self.complete = False
        return True

    # ── Single step ───────────────────────────────────────────

    def tick(self) -> bool:
        """
        Advance simulation by one step.
        Returns True while still running, False when done.
        """
        if self.complete or not self.running:
            return False

        self.step += 1
        g = self.graph
        g.log(f"── Step {self.step:02d} / {self.TOTAL_STEPS} ──")

        decision_flood   = "none"
        decision_reroute = "none"
        decision_ga      = "none"

        # 1. Flood events
        new_floods = self.flood_gen.tick(self.step)
        if new_floods:
            flooded_ids = [f"{a}↔{b}" for a, b in new_floods]
            decision_flood = f"flooded {', '.join(flooded_ids)}"

        # 2. Re-route medical team if a flood hit the current path
        if new_floods:
            prev_target = self.router.current_target
            self.router.notify_flood(self.step)
            new_target = self.router.current_target
            if prev_target != new_target:
                decision_reroute = (
                    f"A* re-routed from civilian {prev_target} → {new_target}"
                )
            else:
                decision_reroute = (
                    f"A* re-planned path to civilian {new_target} "
                    f"(avoiding flooded edge)"
                )

        # 3. Advance medical team one hop
        pos = self.router.advance(self.step)
        if pos is not None:
            g.log(f"[S{self.step:02d}] Medical team at node {pos}")

        # 4. Warm-start GA re-placement if floods changed road connectivity
        if new_floods:
            g.log(f"[S{self.step:02d}] GA re-evaluating ambulance placement "
                  f"(trigger: flood)…")
            self.placer.solve(warm_start=True, extra_gens=20)
            decision_ga = (
                f"GA warm-restarted (flood) → ambulances at "
                f"{self.placer.ambulance_positions}"
            )

        # Decision summary for this step
        g.log(f"[DECISION S{self.step:02d}] flood={decision_flood} | "
              f"reroute={decision_reroute} | ga={decision_ga}")

        # 5. Check completion
        if self.router.done or self.step >= self.TOTAL_STEPS:
            self._finish()
            return False

        return True


    def _finish(self):
        g       = self.graph
        visited = self.router.visited_civilians
        skipped = self.router.skipped_civilians
        total   = len(self.civilians)
        remaining = total - len(visited) - len(skipped)

        g.log("═" * 50)
        g.log("  SIMULATION COMPLETE")
        g.log(f"  Steps taken:        {self.step} / {self.TOTAL_STEPS}")
        g.log(f"  Civilians reached:  {len(visited)} / {total}  {visited}")
        g.log(f"  Civilians skipped:  {len(skipped)}  {skipped}")
        g.log(f"  Civilians remaining:{remaining}")
        g.log(f"  Team final position: node {self.router.position}")
        g.log(f"  Ambulances at:      {self.placer.ambulance_positions}")
        g.log("═" * 50)

        self.running  = False
        self.complete = True