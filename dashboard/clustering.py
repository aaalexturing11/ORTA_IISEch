"""Per-route driver-style clustering.

Self-contained: pulls everything it needs (trip aggregates, UMAP, agglomerative
clustering with silhouette-based k selection) without depending on iise/ or
production/.

Usage:
    from dashboard.clustering import compute_route_clusters
    result = compute_route_clusters(route_slug)

The result is a dict ready to be JSON-serialised by FastAPI:
    {
      "route_slug": str,
      "n_trips": int,
      "n_drivers": int,
      "k": int,
      "silhouette": float,
      "feature_columns": [...],
      "clusters": [{cluster, n_trips, n_drivers, label_hint, centroid: {...}}],
      "trip_assignments": [{trip_id, driver_id, cluster, x, y}],
      "driver_profiles": [{driver_id, n_trips, dominant_cluster, purity, ...mean features}],
      "driver_cluster_mix": {driver_id: {cluster: share, ...}, ...},
    }
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import RobustScaler


ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = ROOT / "output" / "routes"


# Route-invariant per-trip features (driving style only).
FEATURE_COLUMNS = [
    "speed_ratio_mean", "speed_ratio_std",
    "rpm_mean", "rpm_std",
    "accel_std", "accel_p95",
    "brake_p95", "brake_mean",
    "engine_load_mean",
    "fuel_per_100km",
    "idle_frac",
    "harsh_brake_per_100km", "harsh_accel_per_100km", "harsh_turn_per_100km",
]


# --------------------------------------------------------------------------
# Per-trip feature engineering
# --------------------------------------------------------------------------

def _trip_aggregate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-trip route-invariant aggregates used for driver clustering."""
    df = df.copy()
    df["speed_ratio"] = df["speed_kmh"] / df["target_speed_kmh"].clip(lower=1.0)
    g = df.groupby("trip_id", sort=False)

    def per_100km(numerator_col: str) -> pd.Series:
        return g.apply(
            lambda x: float(x[numerator_col].sum())
                       / max(float(x["length_m"].sum()) / 1000.0, 0.1) * 100.0,
            include_groups=False,
        )

    out = pd.DataFrame({
        "driver_id":            g["driver_id"].first(),
        "truck_model":          g["truck_model"].first() if "truck_model" in df.columns else "unknown",
        "speed_ratio_mean":     g["speed_ratio"].mean(),
        "speed_ratio_std":      g["speed_ratio"].std().fillna(0),
        "rpm_mean":             g["rpm"].mean(),
        "rpm_std":              g["rpm"].std().fillna(0),
        "accel_std":            g["accel_ms2"].std().fillna(0),
        "accel_p95":            g["accel_ms2"].quantile(0.95),
        "brake_p95":            g["brake_pct"].quantile(0.95),
        "brake_mean":           g["brake_pct"].mean(),
        "engine_load_mean":     g["engine_load_pct"].mean(),
        "fuel_per_100km":       per_100km("fuel_used_l"),
        "idle_frac":            g.apply(lambda x: float(x["idle_event"].astype(float).mean()),
                                         include_groups=False),
        "harsh_brake_per_100km": per_100km("harsh_brake"),
        "harsh_accel_per_100km": per_100km("harsh_accel"),
        "harsh_turn_per_100km":  per_100km("harsh_turn"),
    }).reset_index()
    return out


# --------------------------------------------------------------------------
# Cluster labelling heuristic (adapted from production/export.py)
# --------------------------------------------------------------------------

def _label_for_centroid(c: dict) -> str:
    sr = c.get("speed_ratio_mean", 1.0)
    harsh = (c.get("harsh_brake_per_100km", 0)
             + c.get("harsh_accel_per_100km", 0)
             + c.get("harsh_turn_per_100km", 0))
    idle = c.get("idle_frac", 0)
    fuel = c.get("fuel_per_100km", 0)
    bits = []
    if sr >= 1.05:
        bits.append("rápido")
    elif sr <= 0.95:
        bits.append("lento")
    else:
        bits.append("constante")
    if harsh >= 8:
        bits.append("agresivo")
    elif harsh <= 2:
        bits.append("suave")
    if idle >= 0.30:
        bits.append("mucho ralentí")
    if fuel >= 35:
        bits.append("alto consumo")
    elif fuel <= 22:
        bits.append("eficiente")
    return ", ".join(bits) or "mixto"


# --------------------------------------------------------------------------
# Clustering core
# --------------------------------------------------------------------------

def _select_k(emb: np.ndarray, k_min: int, k_max: int,
              max_cluster_share: float, min_cluster_size: int,
              fallback_k: int) -> tuple[int, float, np.ndarray]:
    n = len(emb)
    k_max = min(k_max, n - 1)
    best_k, best_sil, best_labels = None, -np.inf, None
    for k in range(k_min, k_max + 1):
        labels = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(emb)
        sizes = pd.Series(labels).value_counts()
        if sizes.max() / n > max_cluster_share:
            continue
        if sizes.min() < min_cluster_size:
            continue
        sil = float(silhouette_score(emb, labels))
        if sil > best_sil:
            best_k, best_sil, best_labels = k, sil, labels
    if best_k is None:
        labels = AgglomerativeClustering(n_clusters=fallback_k, linkage="ward").fit_predict(emb)
        return fallback_k, float(silhouette_score(emb, labels)), labels
    return best_k, best_sil, best_labels


def _embed(Xs: np.ndarray, n_components: int, n_neighbors: int,
           min_dist: float, random_state: int) -> np.ndarray:
    import umap  # lazy: pulls numba
    n_neighbors = min(n_neighbors, max(2, len(Xs) - 1))
    reducer = umap.UMAP(
        n_components=n_components, n_neighbors=n_neighbors,
        min_dist=min_dist, random_state=random_state,
    )
    return reducer.fit_transform(Xs)


# --------------------------------------------------------------------------
# Per-route data loading
# --------------------------------------------------------------------------

def _load_route_trips(route_slug: str) -> pd.DataFrame:
    """Concatenate every sim's raw trips parquet for one route, across all trucks.

    Attaches `truck_model` and `driver_name` from each run's drivers.json.
    """
    route_dir = ROUTES_DIR / route_slug
    sims_root = route_dir / "sims"
    if not sims_root.exists():
        raise FileNotFoundError(f"No sims for route '{route_slug}'")

    frames: list[pd.DataFrame] = []
    for truck_dir in sorted(p for p in sims_root.iterdir() if p.is_dir()):
        for jf in sorted(truck_dir.glob("sim_*_drivers.json")):
            payload = json.loads(jf.read_text())
            truck_model = payload.get("truck", {}).get("model", truck_dir.name)
            names = {d["driver_id"]: d.get("name") for d in payload.get("drivers", [])}
            pq = jf.with_name(jf.name.replace("_drivers.json", "_trips.parquet"))
            if not pq.exists():
                continue
            df = pd.read_parquet(pq)
            df["truck_model"] = truck_model
            df["driver_name"] = df["driver_id"].map(names)
            frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No trip parquets under {sims_root}")
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------

@lru_cache(maxsize=16)
def compute_route_clusters(
    route_slug: str,
    k_min: int = 3,
    k_max: int = 10,
    umap_n_components: int = 5,
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    max_cluster_share: float = 0.50,
    min_cluster_size: int = 3,
    fallback_k: int = 5,
    random_state: int = 42,
) -> dict:
    raw = _load_route_trips(route_slug)
    trips = _trip_aggregate_features(raw)
    n = len(trips)
    if n < max(k_min + 1, 4):
        raise ValueError(f"Not enough trips ({n}) to cluster route '{route_slug}'")

    X = trips[FEATURE_COLUMNS].astype(float).values
    scaler = RobustScaler().fit(X)
    Xs = scaler.transform(X)

    emb_hd = _embed(Xs, umap_n_components, umap_n_neighbors,
                    umap_min_dist, random_state)
    chosen_k, sil, labels = _select_k(emb_hd, k_min, k_max,
                                       max_cluster_share, min_cluster_size,
                                       fallback_k)

    # 2D embedding for the scatter plot (separate fit for visual clarity).
    emb_2d = _embed(Xs, 2, umap_n_neighbors, umap_min_dist, random_state)

    trips["cluster"] = labels.astype(int)
    trips["x"] = emb_2d[:, 0].astype(float)
    trips["y"] = emb_2d[:, 1].astype(float)

    # Cluster summary
    clusters = []
    for c in range(chosen_k):
        sub = trips[trips["cluster"] == c]
        centroid = sub[FEATURE_COLUMNS].mean().to_dict()
        clusters.append({
            "cluster":   int(c),
            "n_trips":   int(len(sub)),
            "n_drivers": int(sub["driver_id"].nunique()),
            "label_hint": _label_for_centroid(centroid),
            "centroid":  {k: float(v) for k, v in centroid.items()},
        })

    # Driver profiles
    driver_profiles = []
    for drv, sub in trips.groupby("driver_id"):
        counts = sub["cluster"].value_counts()
        dom = int(counts.idxmax())
        purity = float(counts.max() / len(sub))
        mean_vec = {k: float(v) for k, v in sub[FEATURE_COLUMNS].mean().items()}
        # First non-null driver name we saw
        names = raw.loc[raw["driver_id"] == drv, "driver_name"].dropna()
        driver_profiles.append({
            "driver_id":        drv,
            "driver_name":      names.iloc[0] if len(names) else drv,
            "n_trips":          int(len(sub)),
            "dominant_cluster": dom,
            "purity":           round(purity, 3),
            **{k: round(v, 4) for k, v in mean_vec.items()},
        })
    driver_profiles.sort(key=lambda r: r["driver_id"])

    # Driver × cluster mix
    ct = pd.crosstab(trips["driver_id"], trips["cluster"])
    mix = ct.div(ct.sum(axis=1), axis=0).round(3)
    driver_cluster_mix = {
        drv: {int(c): float(mix.loc[drv, c]) for c in mix.columns}
        for drv in mix.index
    }

    trip_assignments = trips[["trip_id", "driver_id", "truck_model",
                              "cluster", "x", "y"]].to_dict(orient="records")

    return {
        "route_slug":         route_slug,
        "n_trips":            int(n),
        "n_drivers":          int(trips["driver_id"].nunique()),
        "k":                  int(chosen_k),
        "silhouette":         round(float(sil), 3),
        "feature_columns":    list(FEATURE_COLUMNS),
        "clusters":           clusters,
        "trip_assignments":   trip_assignments,
        "driver_profiles":    driver_profiles,
        "driver_cluster_mix": driver_cluster_mix,
    }
