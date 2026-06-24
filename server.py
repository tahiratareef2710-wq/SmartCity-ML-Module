"""
server.py
=========
CityMind Flask API backend — bridges the HTML/CSS/JS frontend to the
existing Python AI modules (city_engine, challenge1-5, simulation).

Progressive phase machine:
  BOOT → LAYOUT_READY → ROADS_READY → RISK_READY → SIM_READY → RUNNING → DONE

Run: python server.py
Open: http://localhost:5000
"""

import sys
import os
import threading
import json
import time

from flask import Flask, jsonify, request, render_template

# Import all existing backend modules (unchanged)
from city_engine import CityGraph, GRID_ROWS, GRID_COLS, TOTAL_NODES, REQUIRED_COUNTS
from challenge1 import CSPSolver
from challenge2 import RoadNetworkOptimizer
from challenge3 import AmbulancePlacer
from challenge4 import EmergencyRouter
from challenge5 import CrimeRiskPredictor
from simulation import Simulation

# ─────────────────────────────────────────────────────────────
#  Flask App
# ─────────────────────────────────────────────────────────────

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
#  Global State
# ─────────────────────────────────────────────────────────────

_graph           = CityGraph()
_csp             = CSPSolver(_graph)
_optimizer       = RoadNetworkOptimizer(_graph)
_placer          = AmbulancePlacer(_graph)
_router          = EmergencyRouter(_graph)
_crime_predictor = CrimeRiskPredictor(_graph)
_sim             = Simulation(_graph, _placer, _router, _crime_predictor)

_state_lock       = threading.Lock()
_phase            = "BOOT"
_flood_first      = None

# Progress tracking for background execution
_progress_current = 0
_progress_total   = 100
_progress_label   = ""

# Background thread tracking
_exec_thread      = None
_exec_running     = False

# ─────────────────────────────────────────────────────────────
#  Phase Validation Map
# ─────────────────────────────────────────────────────────────

# Which phase is required before this challenge can run
REQUIRED_PHASE = {
    "c1": ["BOOT"],
    "c2": ["LAYOUT_READY"],
    "c5": ["LAYOUT_READY", "ROADS_READY", "RISK_READY", "SIM_READY", "RUNNING", "DONE"],
    "c3": ["ROADS_READY", "RISK_READY", "SIM_READY", "DONE"],
    "sim": ["SIM_READY", "RUNNING"],
}

# Phase names for display
PHASE_LABELS = {
    "BOOT":              "System Ready",
    "SOLVING_LAYOUT":    "Generating City Layout…",
    "LAYOUT_READY":      "Layout Complete",
    "SOLVING_ROADS":     "Building Road Network…",
    "ROADS_READY":       "Roads Ready",
    "SOLVING_RISK":      "Analyzing Crime Patterns…",
    "RISK_READY":        "Risk Analysis Complete",
    "SOLVING_AMBULANCE": "Placing Ambulances…",
    "SIM_READY":         "Simulation Ready",
    "RUNNING":           "Simulation Active",
    "DONE":              "Simulation Complete",
}

# ─────────────────────────────────────────────────────────────
#  State Serializer
# ─────────────────────────────────────────────────────────────

def _safe_cost(val: float):
    """Convert float('inf') to None for JSON serialisation."""
    if val == float("inf"):
        return None
    return val


def _build_state():
    """Serialize the entire CityGraph + simulation into a JSON-ready dict."""
    g = _graph

    # Nodes
    nodes = []
    for n in g.nodes:
        nodes.append({
            "id":                 n.id,
            "row":                n.row,
            "col":                n.col,
            "type":               n.type,
            "crime_risk":         n.crime_risk,
            "risk_index":         n.risk_index,
            "population_density": n.population_density,
            "accessible":         n.accessible,
            "active":             n.active,
        })

    # Edges (deduplicate via _edge_map — single canonical per pair)
    edges = []
    for key, e in g._edge_map.items():
        edges.append({
            "from":           e.from_id,
            "to":             e.to_id,
            "flooded":        e.flooded,
            "base_cost":      e.base_cost,
            "effective_cost": _safe_cost(e.effective_cost()),
            "crime_risk":     e.crime_risk,
        })

    # MST edges → list of [from_id, to_id]
    mst = [[e.from_id, e.to_id] for e in g.mst_edges]

    # Augment edges → list of [from_id, to_id]
    aug = [[e.from_id, e.to_id] for e in g.augment_edges]

    # Node type counts
    counts = {}
    for t in g.required_counts:
        counts[t] = len(g.all_of_type(t))

    # Simulation state
    sim_state = {
        "step":              _sim.step,
        "running":           _sim.running,
        "complete":          _sim.complete,
        "total_steps":       _sim.TOTAL_STEPS,
        "team_position":     _router.position if _sim.running else None,
        "team_path":         _router.current_path if _sim.running else [],
        "current_target":    _router.current_target if _sim.running else None,
        "civilians":         [int(c) for c in _sim.civilians],
        "visited_civilians": [int(v) for v in _sim.router.visited_civilians],
        "skipped_civilians": [int(s) for s in _sim.router.skipped_civilians],
    }

    return {
        "phase":             _phase,
        "phase_label":       PHASE_LABELS.get(_phase, _phase),
        "progress_current":  _progress_current,
        "progress_total":    _progress_total,
        "progress_label":    _progress_label,
        "exec_running":      _exec_running,
        "grid_rows":         GRID_ROWS,
        "grid_cols":         GRID_COLS,
        "nodes":             nodes,
        "edges":             edges,
        "mst_edges":         mst,
        "augment_edges":     aug,
        "ambulance_positions":[int(a) for a in g.ambulance_positions],
        "primary_hospital_id":g.primary_hospital_id,
        "ambulance_depot_id": g.ambulance_depot_id,
        "simulation":        sim_state,
        "event_log":         g.event_log,
        "node_counts":       counts,
    }


def _set_progress(current, total, label=""):
    global _progress_current, _progress_total, _progress_label
    _progress_current = current
    _progress_total   = total
    _progress_label   = label


def _validate_phase(action):
    """Check if the current phase allows this action. Returns (ok, error_msg)."""
    allowed = REQUIRED_PHASE.get(action, [])
    if _phase not in allowed:
        msg = f"Cannot run {action}: phase is {_phase}, requires {allowed}"
        _graph.log(f"[BLOCKED] {msg}")
        return False
    return True


# ─────────────────────────────────────────────────────────────
#  Routes — Pages
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─────────────────────────────────────────────────────────────
#  Routes — State Queries (GET)
# ─────────────────────────────────────────────────────────────

@app.route("/api/state")
def api_state():
    with _state_lock:
        return jsonify(_build_state())


@app.route("/api/phase")
def api_phase():
    return jsonify({
        "phase":            _phase,
        "progress_current": _progress_current,
        "progress_total":   _progress_total,
        "progress_label":   _progress_label,
        "exec_running":     _exec_running,
    })


@app.route("/api/event-log")
def api_event_log():
    return jsonify(_graph.event_log)


@app.route("/api/node/<int:nid>")
def api_node(nid):
    if not (0 <= nid < TOTAL_NODES):
        return jsonify({"error": "Invalid node ID"}), 400
    n = _graph.nodes[nid]
    neighbors = []
    for e in _graph.adj[nid]:
        other = e.other(nid)
        neighbors.append({
            "to": other,
            "flooded": e.flooded,
            "base_cost": e.base_cost,
            "effective_cost": _safe_cost(e.effective_cost()),
        })
    return jsonify({
        "id":                 n.id,
        "row":                n.row,
        "col":                n.col,
        "type":               n.type,
        "crime_risk":         n.crime_risk,
        "risk_index":         n.risk_index,
        "population_density": n.population_density,
        "accessible":         n.accessible,
        "neighbors":          neighbors,
    })


# ─────────────────────────────────────────────────────────────
#  Routes — Challenge Actions (POST)
# ─────────────────────────────────────────────────────────────

@app.route("/api/run/c1", methods=["POST"])
def api_run_c1():
    global _phase, _exec_running
    with _state_lock:
        if not _validate_phase("c1"):
            return jsonify(_build_state())
        if _exec_running:
            return jsonify(_build_state())

        _graph.reset()
        _graph.log("[BOOT] System Ready")
        _graph.log("[C1] Starting CSP city layout…")
        _phase = "SOLVING_LAYOUT"
        _exec_running = True
        _set_progress(0, 72, "Assigning city nodes…")

        def _worker():
            global _phase, _exec_running

            def _progress_cb(n):
                _set_progress(n, 72, f"Placing nodes: {n}/72")

            ok = _csp.solve(progress_cb=_progress_cb)
            with _state_lock:
                if ok:
                    _phase = "LAYOUT_READY"
                    _set_progress(72, 72, "City layout complete")
                    hospitals = _graph.all_of_type("Hospital")
                    depots    = _graph.all_of_type("AmbulanceDepot")
                    _graph.log(f"[C1] CSP layout solved — {sum(1 for n in _graph.nodes if n.type != 'Empty')} buildings placed")
                    if hospitals:
                        _graph.log(f"[C1] Primary hospital at node {hospitals[0]}")
                    if depots:
                        _graph.log(f"[C1] Ambulance depot at node {depots[0]}")
                else:
                    _phase = "BOOT"
                    _set_progress(0, 72, "CSP failed")
                    _graph.log(f"[C1] CSP failed: {_csp.violation_reason}")
                _exec_running = False

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_build_state())


@app.route("/api/run/c2", methods=["POST"])
def api_run_c2():
    global _phase, _exec_running
    with _state_lock:
        if not _validate_phase("c2"):
            return jsonify(_build_state())
        if _exec_running:
            return jsonify(_build_state())

        _graph.log("[C2] Generating Kruskal MST road network…")
        _phase = "SOLVING_ROADS"
        _exec_running = True
        _set_progress(0, 100, "Building road network…")

        def _worker():
            global _phase, _exec_running
            _set_progress(30, 100, "Computing minimum spanning tree…")
            ok = _optimizer.solve()
            with _state_lock:
                if ok:
                    _phase = "ROADS_READY"
                    _set_progress(100, 100, "Road network complete")
                    mst_count = len(_graph.mst_edges)
                    aug_count = len(_graph.augment_edges)
                    _graph.log(f"[C2] MST road network ready — {mst_count} primary edges, {aug_count} backup paths")
                else:
                    _phase = "LAYOUT_READY"
                    _set_progress(0, 100, "MST failed")
                    _graph.log("[C2] MST generation failed")
                _exec_running = False

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_build_state())


@app.route("/api/run/c5", methods=["POST"])
def api_run_c5():
    global _phase, _exec_running
    with _state_lock:
        if not _validate_phase("c5"):
            return jsonify(_build_state())
        if _exec_running:
            return jsonify(_build_state())

        _graph.log("[C5] Analyzing crime risk patterns…")
        _phase = "SOLVING_RISK"
        _exec_running = True
        _set_progress(0, 100, "Running K-Means clustering…")

        def _worker():
            global _phase, _exec_running
            _set_progress(30, 100, "Clustering crime zones…")
            # Small delay so the frontend can show the intermediate step
            time.sleep(0.05)
            _set_progress(60, 100, "Training decision tree…")
            ok = _crime_predictor.solve()
            with _state_lock:
                if ok:
                    _phase = "RISK_READY"
                    _set_progress(100, 100, "Crime analysis complete")
                    high  = sum(1 for n in _graph.nodes if n.crime_risk == "High")
                    med   = sum(1 for n in _graph.nodes if n.crime_risk == "Medium")
                    _graph.log(f"[C5] Crime risk mapped — {high} high-risk, {med} medium-risk zones")
                else:
                    _phase = "ROADS_READY"
                    _set_progress(0, 100, "Crime analysis failed")
                    _graph.log("[C5] Crime prediction failed")
                _exec_running = False

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_build_state())


@app.route("/api/run/c3", methods=["POST"])
def api_run_c3():
    global _phase, _exec_running
    with _state_lock:
        if not _validate_phase("c3"):
            return jsonify(_build_state())
        if _exec_running:
            return jsonify(_build_state())

        _graph.log("[C3] Evolving ambulance placement (GA)…")
        _phase = "SOLVING_AMBULANCE"
        _exec_running = True
        _set_progress(0, 100, "Initializing genetic algorithm…")

        def _worker():
            global _phase, _exec_running
            _set_progress(10, 100, "Evolving ambulance placements…")
            ok = _sim.initialise()
            with _state_lock:
                if ok:
                    _phase = "SIM_READY"
                    _set_progress(100, 100, "Ambulances deployed")
                    amb_count = len(_graph.ambulance_positions)
                    civ_count = len(_sim.civilians)
                    _graph.log(f"[C3] GA placed {amb_count} ambulances at {list(_graph.ambulance_positions)}")
                    _graph.log(f"[C3] {civ_count} civilians generated for emergency routing")
                else:
                    _phase = "RISK_READY"
                    _set_progress(0, 100, "GA placement failed")
                    _graph.log("[C3] Ambulance placement failed")
                _exec_running = False

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_build_state())


@app.route("/api/run/sim-tick", methods=["POST"])
def api_sim_tick():
    global _phase, _exec_running
    with _state_lock:
        if not _validate_phase("sim"):
            return jsonify(_build_state())
        if _exec_running:
            return jsonify(_build_state())

        if not _sim.running:
            _graph.log("[SIM] Start simulation with Challenge 3 first")
            return jsonify(_build_state())

        _phase = "RUNNING"
        _exec_running = True
        
        def _worker():
            global _phase, _exec_running
            still_going = _sim.tick()
            with _state_lock:
                if not still_going:
                    _phase = "DONE"
                    _graph.log("[SIM] All 20 steps complete — simulation finished")
                _exec_running = False

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_build_state())


# ─────────────────────────────────────────────────────────────
#  Routes — Reset
# ─────────────────────────────────────────────────────────────

@app.route("/api/reset", methods=["POST"])
def api_reset():
    global _phase, _flood_first, _exec_running, _progress_current, _progress_total, _progress_label
    with _state_lock:
        _graph.reset()
        _placer.best_placement = None
        _placer.ambulance_positions = []
        _router.__init__(_graph)
        _sim.__init__(_graph, _placer, _router, _crime_predictor)
        _phase            = "BOOT"
        _flood_first      = None
        _exec_running     = False
        _progress_current = 0
        _progress_total   = 100
        _progress_label   = ""
        _graph.log("[BOOT] System Ready — grid cleared, awaiting commands")
        return jsonify(_build_state())


# ─────────────────────────────────────────────────────────────
#  Routes — Flood Control
# ─────────────────────────────────────────────────────────────

@app.route("/api/flood", methods=["POST"])
def api_flood():
    data = request.get_json()
    a = data.get("a")
    b = data.get("b")
    if a is None or b is None:
        return jsonify({"error": "Missing a or b node IDs"}), 400
    with _state_lock:
        e = _graph.get_edge(a, b)
        if e:
            if e.flooded:
                _graph.unflood_edge(a, b)
            else:
                _graph.flood_edge(a, b)
        return jsonify(_build_state())


@app.route("/api/flood/clear", methods=["POST"])
def api_flood_clear():
    with _state_lock:
        for e in _graph._edge_map.values():
            e.flooded = False
        _graph.log("[SIM] All floods cleared")
        return jsonify(_build_state())


@app.route("/api/toggle-node", methods=["POST"])
def api_toggle_node():
    """Toggle a node active/inactive (damaged hospital, closed school, etc.)."""
    data = request.get_json()
    nid    = data.get("id")
    active = data.get("active", False)
    if nid is None:
        return jsonify({"error": "Missing node id"}), 400
    with _state_lock:
        _graph.toggle_node(nid, active)
        return jsonify(_build_state())


@app.route("/api/find-placement", methods=["POST"])
def api_find_placement():
    """Find the best candidate node for a new facility of the given type."""
    data = request.get_json()
    node_type = data.get("type")
    if not node_type:
        return jsonify({"error": "Missing node type"}), 400
    with _state_lock:
        candidate = _graph.find_placement_candidate(node_type)
        if candidate is not None:
            _graph.log(f"[PLACEMENT] Candidate for {node_type}: node {candidate}")
        else:
            _graph.log(f"[PLACEMENT] No candidate for {node_type} — expansion needed")
        state = _build_state()
        state["placement_candidate"] = candidate
        return jsonify(state)


@app.route("/api/replan", methods=["POST"])
def api_replan():
    """Re-run CSP layout + MST when city topology changes (node toggled, etc.)."""
    global _phase, _exec_running
    with _state_lock:
        if _exec_running:
            return jsonify(_build_state())

        _graph.log("[REPLAN] Triggering city re-plan…")
        _phase = "SOLVING_LAYOUT"
        _exec_running = True
        _set_progress(0, 72, "Re-planning city layout…")

        def _worker():
            global _phase, _exec_running
            def _progress_cb(n):
                _set_progress(n, 72, f"Re-placing nodes: {n}/72")

            ok = _csp.solve(progress_cb=_progress_cb)
            with _state_lock:
                if ok:
                    _graph.log("[REPLAN] CSP re-solved — rebuilding MST…")
                    _set_progress(72, 100, "Rebuilding road network…")
                    _optimizer.solve()
                    _phase = "ROADS_READY"
                    _set_progress(100, 100, "Re-plan complete")
                    _graph.log("[REPLAN] City re-plan complete")
                else:
                    _phase = "BOOT"
                    _set_progress(0, 72, "Re-plan failed")
                    _graph.log(f"[REPLAN] Re-plan failed: {_csp.violation_reason}")
                _exec_running = False

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_build_state())


@app.route("/api/configure", methods=["POST"])
def api_configure():
    """Update required node counts at runtime (demo-configurable)."""
    data = request.get_json()
    if not data or "counts" not in data:
        return jsonify({"error": "Missing counts dict"}), 400
    with _state_lock:
        _graph.set_required_counts(data["counts"])
        return jsonify(_build_state())


@app.route("/api/configure-ga", methods=["POST"])
def api_configure_ga():
    """Update GA parameters at runtime (demo-configurable)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing GA params"}), 400
    with _state_lock:
        _placer.set_params(**data)
        return jsonify(_build_state())


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
