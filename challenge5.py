"""
challenge5.py
=============
Challenge 5 – Crime Risk Prediction
Techniques: K-Means clustering (k=3) · Decision-Tree classifier (max depth 5).
All implemented in pure Python — no sklearn / numpy dependencies.

Pipeline:
  1. Extract features from the shared CityGraph
  2. Cluster neighbourhoods with K-Means
  3. Generate synthetic labelled crime data from cluster profiles
  4. Train a Decision Tree on the synthetic data
  5. Predict risk for every node → update graph weights

The graph update uses CityGraph.update_risk_index() which propagates
crime_risk labels to edges and therefore to effective_cost().
"""

import math
import random
from collections import deque, defaultdict
from typing import Optional

from city_engine import (
    CityGraph, GRID_ROWS, GRID_COLS, TOTAL_NODES, CRIME_MULTIPLIERS,
)


# ─────────────────────────────────────────────────────────────
#  FEATURE EXTRACTION
# ─────────────────────────────────────────────────────────────

def _bfs_hops_to_type(graph: CityGraph, start: int, target_types: set[str],
                      max_depth: int = 20) -> int:
    """BFS hop count from *start* to nearest node whose type ∈ target_types."""
    visited, q = {start}, deque([(start, 0)])
    while q:
        nid, d = q.popleft()
        if d > 0 and graph.nodes[nid].type in target_types:
            return d
        if d >= max_depth:
            continue
        for e in graph.adj[nid]:
            nb = e.other(nid)
            if nb not in visited:
                visited.add(nb)
                q.append((nb, d + 1))
    return max_depth + 1          # unreachable


def _count_type_in_radius(graph: CityGraph, start: int,
                          target_types: set[str], radius: int = 2) -> int:
    """Count how many nodes of *target_types* lie within *radius* hops."""
    visited, q = {start}, deque([(start, 0)])
    count = 0
    while q:
        nid, d = q.popleft()
        if d > 0 and graph.nodes[nid].type in target_types:
            count += 1
        if d < radius:
            for e in graph.adj[nid]:
                nb = e.other(nid)
                if nb not in visited:
                    visited.add(nb)
                    q.append((nb, d + 1))
    return count


def extract_features(graph: CityGraph) -> dict[int, list[float]]:
    """
    Build a feature vector for every non-Empty node:
        [population_density, industrial_proximity,
         hospital_proximity, road_connectivity]
    Values are normalised to roughly 0–1.
    """
    features: dict[int, list[float]] = {}

    for nid in range(TOTAL_NODES):
        n = graph.nodes[nid]
        if n.type == "Empty":
            continue

        # Feature 1 – population density (residential neighbours in 2-hop radius)
        res_count = _count_type_in_radius(graph, nid, {"Residential"}, radius=2)
        pop_density = min(res_count / 12.0, 1.0)   # 12 is a generous max

        # Feature 2 – industrial proximity (inverse BFS distance)
        ind_hops = _bfs_hops_to_type(graph, nid, {"Industrial"})
        ind_prox = 1.0 / (ind_hops + 1)

        # Feature 3 – hospital proximity (inverse BFS distance)
        hosp_hops = _bfs_hops_to_type(graph, nid, {"Hospital"})
        hosp_prox = 1.0 / (hosp_hops + 1)

        # Feature 4 – road connectivity (fraction of non-flooded edges)
        total_edges = len(graph.adj[nid])
        live_edges  = sum(1 for e in graph.adj[nid] if not e.flooded)
        connectivity = live_edges / max(total_edges, 1)

        features[nid] = [pop_density, ind_prox, hosp_prox, connectivity]

    return features


# ─────────────────────────────────────────────────────────────
#  K-MEANS CLUSTERING
# ─────────────────────────────────────────────────────────────

def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


class KMeansClustering:
    """
    K-Means with random initialisation.
    k = 4 clusters, max 50 iterations, convergence when centroids freeze.
    """

    def __init__(self, k: int = 4, max_iter: int = 50, seed: int = 42):
        self.k        = k
        self.max_iter = max_iter
        self.seed     = seed
        self.centroids: list[list[float]] = []
        self.labels:    dict[int, int]    = {}   # node_id → cluster_id

    def fit(self, features: dict[int, list[float]]):
        rng  = random.Random(self.seed)
        nids = list(features.keys())
        dim  = len(next(iter(features.values())))

        if len(nids) <= self.k:
            # Degenerate case: fewer points than clusters
            self.labels = {nid: i for i, nid in enumerate(nids)}
            self.centroids = [features[nid][:] for nid in nids]
            return

        # Random centroid initialisation (k-means++ flavour: pick spread seeds)
        init_ids = rng.sample(nids, self.k)
        self.centroids = [features[nid][:] for nid in init_ids]

        for iteration in range(self.max_iter):
            # ── Assign step ──
            new_labels: dict[int, int] = {}
            for nid in nids:
                dists = [_euclidean(features[nid], c) for c in self.centroids]
                new_labels[nid] = dists.index(min(dists))

            # ── Update step ──
            cluster_sums:   list[list[float]] = [[0.0] * dim for _ in range(self.k)]
            cluster_counts: list[int]         = [0] * self.k
            for nid, cid in new_labels.items():
                for d in range(dim):
                    cluster_sums[cid][d] += features[nid][d]
                cluster_counts[cid] += 1

            new_centroids = []
            for cid in range(self.k):
                if cluster_counts[cid] > 0:
                    new_centroids.append(
                        [s / cluster_counts[cid] for s in cluster_sums[cid]]
                    )
                else:
                    # Empty cluster: re-seed to a random point
                    new_centroids.append(features[rng.choice(nids)][:])

            # ── Convergence check ──
            moved = sum(
                _euclidean(old, new)
                for old, new in zip(self.centroids, new_centroids)
            )
            self.centroids = new_centroids
            self.labels    = new_labels

            if moved < 1e-6:
                break

    def cluster_profiles(self, features: dict[int, list[float]]) -> dict[int, list[float]]:
        """Return the mean feature vector for each cluster."""
        dim = len(next(iter(features.values())))
        sums:   dict[int, list[float]] = defaultdict(lambda: [0.0] * dim)
        counts: dict[int, int]         = defaultdict(int)
        for nid, cid in self.labels.items():
            for d in range(dim):
                sums[cid][d] += features[nid][d]
            counts[cid] += 1
        return {
            cid: [s / max(counts[cid], 1) for s in sums[cid]]
            for cid in range(self.k)
        }


# ─────────────────────────────────────────────────────────────
#  SYNTHETIC CRIME DATA GENERATION
# ─────────────────────────────────────────────────────────────

def _generate_crime_labels(
    features: dict[int, list[float]],
    kmeans: KMeansClustering,
    noise: float = 0.12,
) -> dict[int, str]:
    """
    Assign crime risk labels based on cluster profiles and node features.
    Logic:
        • High risk  → high industrial proximity AND high population density
        • Low risk   → high hospital proximity AND far from industry AND
                       low population density
        • Medium     → everything else

    Noise: ±12% random variation added to danger/safety scores to prevent the
    Decision Tree from memorising deterministic patterns (Q&A requirement).
    """
    profiles = kmeans.cluster_profiles(features)

    # Rank clusters by "danger score": industrial_prox × pop_density
    danger_scores = {
        cid: prof[1] * prof[0]          # ind_prox × pop_density
        for cid, prof in profiles.items()
    }
    # Rank clusters by "safety score":
    #   high hospital proximity + far from industry + low population
    safety_scores = {
        cid: prof[2] * (1.0 - prof[1]) * (1.0 - prof[0])
        for cid, prof in profiles.items()
    }

    # Classify each cluster
    sorted_danger = sorted(danger_scores.items(), key=lambda x: x[1], reverse=True)
    sorted_safety = sorted(safety_scores.items(), key=lambda x: x[1], reverse=True)

    # Top danger cluster → High, top safety cluster → Low, rest → Medium
    high_clusters  = {sorted_danger[0][0]}
    low_clusters   = {sorted_safety[0][0]} - high_clusters   # safety loses to danger

    labels: dict[int, str] = {}
    for nid, cid in kmeans.labels.items():
        feat = features[nid]
        pop_density  = feat[0]
        ind_prox     = feat[1]
        hosp_prox    = feat[2]
        connectivity = feat[3]

        # Per-node refinement on top of cluster baseline
        # Apply ±noise multiplier to prevent deterministic memorisation
        jitter = 1.0 + random.uniform(-noise, noise)
        danger = ind_prox * pop_density * jitter
        jitter = 1.0 + random.uniform(-noise, noise)
        safety = hosp_prox * (1.0 - ind_prox) * (1.0 - pop_density) * jitter

        if cid in high_clusters or danger > 0.25:
            labels[nid] = "High"
        elif cid in low_clusters or safety > 0.20:
            labels[nid] = "Low"
        else:
            labels[nid] = "Medium"

    return labels


def _generate_training_data(
    features: dict[int, list[float]],
    labels: dict[int, str],
) -> tuple[list[list[float]], list[str]]:
    """Return (X, y) training set from features and generated labels."""
    X, y = [], []
    for nid in features:
        if nid in labels:
            X.append(features[nid])
            y.append(labels[nid])
    return X, y


# ─────────────────────────────────────────────────────────────
#  DECISION TREE CLASSIFIER
# ─────────────────────────────────────────────────────────────

class _DTNode:
    """Internal node of the decision tree."""
    __slots__ = ("feature_idx", "threshold", "left", "right", "label")

    def __init__(self):
        self.feature_idx: int           = -1
        self.threshold:   float         = 0.0
        self.left:        Optional["_DTNode"] = None
        self.right:       Optional["_DTNode"] = None
        self.label:       Optional[str] = None    # leaf label


class DecisionTreeClassifier:
    """
    Pure-Python decision tree.
    Splits by information gain (entropy), max_depth = 5.
    """

    def __init__(self, max_depth: int = 5):
        self.max_depth = max_depth
        self.root: Optional[_DTNode] = None

    # ── Entropy / IG ──────────────────────────────────────────

    @staticmethod
    def _entropy(labels: list[str]) -> float:
        if not labels:
            return 0.0
        counts: dict[str, int] = defaultdict(int)
        for l in labels:
            counts[l] += 1
        total = len(labels)
        ent = 0.0
        for c in counts.values():
            p = c / total
            if p > 0:
                ent -= p * math.log2(p)
        return ent

    @staticmethod
    def _majority(labels: list[str]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for l in labels:
            counts[l] += 1
        return max(counts, key=counts.get)

    def _best_split(self, X: list[list[float]], y: list[str]
                    ) -> tuple[int, float, float]:
        """
        Find the feature index and threshold that maximise information gain.
        Returns (feature_idx, threshold, best_gain).
        """
        best_gain = -1.0
        best_feat = 0
        best_thr  = 0.0
        parent_ent = self._entropy(y)
        n = len(y)

        if n <= 1:
            return best_feat, best_thr, best_gain

        num_features = len(X[0])
        for fi in range(num_features):
            # Collect unique thresholds (midpoints between sorted unique values)
            vals = sorted(set(row[fi] for row in X))
            thresholds = [(vals[i] + vals[i + 1]) / 2 for i in range(len(vals) - 1)]

            for thr in thresholds:
                left_y  = [y[i] for i in range(n) if X[i][fi] <= thr]
                right_y = [y[i] for i in range(n) if X[i][fi] >  thr]

                if not left_y or not right_y:
                    continue

                wl = len(left_y) / n
                wr = len(right_y) / n
                gain = parent_ent - wl * self._entropy(left_y) - wr * self._entropy(right_y)

                if gain > best_gain:
                    best_gain = gain
                    best_feat = fi
                    best_thr  = thr

        return best_feat, best_thr, best_gain

    # ── Build tree ────────────────────────────────────────────

    def _build(self, X: list[list[float]], y: list[str], depth: int) -> _DTNode:
        node = _DTNode()

        # Leaf conditions
        if depth >= self.max_depth or len(set(y)) == 1 or len(y) <= 2:
            node.label = self._majority(y)
            return node

        fi, thr, gain = self._best_split(X, y)
        if gain <= 0:
            node.label = self._majority(y)
            return node

        node.feature_idx = fi
        node.threshold   = thr

        left_X  = [X[i] for i in range(len(y)) if X[i][fi] <= thr]
        left_y  = [y[i] for i in range(len(y)) if X[i][fi] <= thr]
        right_X = [X[i] for i in range(len(y)) if X[i][fi] >  thr]
        right_y = [y[i] for i in range(len(y)) if X[i][fi] >  thr]

        node.left  = self._build(left_X, left_y, depth + 1)
        node.right = self._build(right_X, right_y, depth + 1)
        return node

    def fit(self, X: list[list[float]], y: list[str]):
        self.root = self._build(X, y, 0)

    # ── Predict ───────────────────────────────────────────────

    def predict_one(self, sample: list[float]) -> str:
        node = self.root
        while node is not None:
            if node.label is not None:
                return node.label
            if sample[node.feature_idx] <= node.threshold:
                node = node.left
            else:
                node = node.right
        return "Low"   # fallback

    def predict(self, X: list[list[float]]) -> list[str]:
        return [self.predict_one(row) for row in X]


# ─────────────────────────────────────────────────────────────
#  CRIME RISK PREDICTOR  (public API)
# ─────────────────────────────────────────────────────────────

RISK_VALUE = {"High": 0.85, "Medium": 0.55, "Low": 0.15}


class CrimeRiskPredictor:
    """
    Orchestrates the full Challenge 5 pipeline:
        extract features → K-Means → synthetic labels → train DT → predict → update graph

    Decision Tree justification (over KNN / Logistic Regression):
      - KNN is instance-based: every prediction requires scanning the full training
        set, O(N) per node on a 400-node grid. DT predicts in O(log N) via tree
        traversal — better for real-time dashboard updates.
      - Logistic Regression assumes a linear decision boundary. Crime risk factors
        (industrial proximity × population density) interact non-linearly — DT
        captures these interactions via axis-aligned splits without feature
        engineering.
      - DT is interpretable: the split rules (feature > threshold) can be printed
        and explained in the viva, whereas logistic coefficients are opaque.

    Retraining policy (documented assumption):
      - If node count changes by ≤10%: classify new nodes with existing centroids
        and tree (fast path, no re-clustering).
      - If node count changes by >10%: re-run K-Means to update centroids, then
        re-train the Decision Tree (full pipeline).
    """

    RETRAIN_THRESHOLD = 0.10   # >10% node-count change → full retrain

    def __init__(self, graph: CityGraph, k: int = 3, max_depth: int = 5):
        self.graph     = graph
        self.k         = k
        self.max_depth = max_depth
        self.kmeans    = KMeansClustering(k=k)
        self.tree      = DecisionTreeClassifier(max_depth=max_depth)
        self._trained_node_count: int = 0

        # Stored for inspection / terminal UI
        self.features:    dict[int, list[float]] = {}
        self.labels:      dict[int, str]         = {}
        self.predictions: dict[int, str]         = {}

    def solve(self) -> bool:
        """
        Run the full pipeline and update the shared CityGraph.
        On subsequent calls, uses the retraining threshold to decide
        whether to re-cluster or just re-classify.
        Returns True on success.
        """
        g = self.graph
        g.log("▶ Challenge 5 – Crime Risk Prediction starting…")

        # 1. Feature extraction
        self.features = extract_features(g)
        node_count = len(self.features)
        if node_count < self.k:
            g.log("Challenge 5 ✗ Not enough placed nodes for clustering")
            return False

        # Retraining threshold check
        if self._trained_node_count > 0:
            delta = abs(node_count - self._trained_node_count) / max(self._trained_node_count, 1)
            if delta <= self.RETRAIN_THRESHOLD:
                g.log(f"  Node count Δ={delta*100:.0f}% ≤ threshold — "
                      f"classifying with existing model")
                self._classify_all(g)
                return True
            g.log(f"  Node count Δ={delta*100:.0f}% > threshold — "
                  f"re-running full pipeline")

        # 2. K-Means clustering
        self.kmeans = KMeansClustering(k=self.k)
        self.kmeans.fit(self.features)

        cluster_counts = defaultdict(int)
        for cid in self.kmeans.labels.values():
            cluster_counts[cid] += 1
        g.log(f"  K-Means (k={self.k}): clusters = "
              f"{dict(sorted(cluster_counts.items()))}")

        # 3. Synthetic crime labels (with ±12% noise to prevent memorisation)
        self.labels = _generate_crime_labels(self.features, self.kmeans)

        # 4. Train decision tree
        X_train, y_train = _generate_training_data(self.features, self.labels)
        if not X_train:
            g.log("Challenge 5 ✗ No training data generated")
            return False

        self.tree = DecisionTreeClassifier(max_depth=self.max_depth)
        self.tree.fit(X_train, y_train)
        self._trained_node_count = node_count

        # 5. Predict for all nodes and update graph
        self._classify_all(g)
        return True

    def _classify_all(self, g):
        """Classify all feature nodes using the trained tree and update graph."""
        self.predictions = {}
        counts: dict[str, int] = defaultdict(int)

        for nid, feat in self.features.items():
            risk_label = self.tree.predict_one(feat)
            self.predictions[nid] = risk_label
            risk_value = RISK_VALUE[risk_label]
            g.update_risk_index(nid, risk_value)
            counts[risk_label] += 1

        g.log(
            f"Challenge 5 ✓ Crime prediction complete | "
            f"High={counts.get('High', 0)}  "
            f"Medium={counts.get('Medium', 0)}  "
            f"Low={counts.get('Low', 0)}"
        )
