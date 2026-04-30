"""FastAPI backend for the truck telemetry dashboard.

Reads outputs produced by ``datosDeRuta.py`` and ``simulate2.py`` from the
nested layout::

    output/routes/<route_slug>/route.{json,parquet}
    output/routes/<route_slug>/sims/<truck_slug>/sim_<run>_drivers.json
    output/routes/<route_slug>/sims/<truck_slug>/sim_<run>_trips.parquet

All KPI endpoints accept ``route``, ``truck`` and ``since`` query params.
``since`` is an ISO8601 datetime; trips with ``departure_iso`` strictly before
it are dropped. Baselines (fuel, idle) are derived from the data itself.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .clustering import compute_route_clusters
from .route_coach import build_coaching_payload

ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = ROOT / "output" / "routes"
STATIC_DIR = Path(__file__).resolve().parent / "static"

CO2_KG_PER_L_DIESEL = 2.68
IDLE_FUEL_LPH = 3.2

app = FastAPI(title="Heavy Truck Ops Dashboard")


# ---------------------------------------------------------------------------
# Schema normalization (sim writer column names -> dashboard names)
# ---------------------------------------------------------------------------

_SUMMARY_RENAME = {
    "total_distance_km": "distance_km",
    "total_fuel_l": "fuel_l",
    "avg_speed_kmh": "avg_speed_kph",
    "fuel_efficiency_l_per_100km": "fuel_l_per_100km",
    "n_harsh_brake": "harsh_brake_events",
    "n_harsh_accel": "harsh_accel_events",
}
_TRIPS_RENAME = {
    "segment_id": "seg_idx",
    "speed_kmh": "speed_kph",
    "length_m": "seg_len_m",
    "fuel_used_l": "fuel_l",
}


def _normalize_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.rename(columns={k: v for k, v in _SUMMARY_RENAME.items() if k in df.columns})
    if "anomaly_count" not in df.columns and "anomalies" in df.columns:
        df["anomaly_count"] = df["anomalies"].apply(
            lambda x: len(x) if isinstance(x, (list, tuple)) else 0
        )
    if "pct_time_overspeed" not in df.columns:
        df["pct_time_overspeed"] = 0.0
    return df


def _normalize_route(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "seg_idx" not in df.columns and "segment_id" in df.columns:
        df = df.rename(columns={"segment_id": "seg_idx"})
    if "lat_mid" not in df.columns:
        if "start_lat" in df.columns and "end_lat" in df.columns:
            df = df.assign(
                lat_mid=(df["start_lat"] + df["end_lat"]) / 2.0,
                lon_mid=(df["start_lon"] + df["end_lon"]) / 2.0,
            )
        elif "lat" in df.columns and "lon" in df.columns:
            df = df.assign(lat_mid=df["lat"], lon_mid=df["lon"])
    return df


def _normalize_trips(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.rename(columns={k: v for k, v in _TRIPS_RENAME.items() if k in df.columns})
    for bcol in ("harsh_brake", "harsh_accel"):
        if bcol in df.columns and df[bcol].dtype == bool:
            df[bcol] = df[bcol].astype(int)
    return df


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _list_route_dirs() -> list[Path]:
    if not ROUTES_DIR.exists():
        return []
    return sorted([p for p in ROUTES_DIR.iterdir() if (p / "route.json").exists()])


def _list_truck_dirs(route_slug: str) -> list[Path]:
    sims_dir = ROUTES_DIR / route_slug / "sims"
    if not sims_dir.exists():
        return []
    return sorted([p for p in sims_dir.iterdir() if p.is_dir()])


def _list_sim_files(route_slug: str, truck_slug: str) -> list[Path]:
    truck_dir = ROUTES_DIR / route_slug / "sims" / truck_slug
    if not truck_dir.exists():
        return []
    return sorted(truck_dir.glob("sim_*_drivers.json"))


@app.get("/api/routes")
def list_routes() -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for rd in _list_route_dirs():
        try:
            meta = json.loads((rd / "route.json").read_text())
        except Exception:
            continue
        trucks: list[dict[str, Any]] = []
        for td in _list_truck_dirs(rd.name):
            sim_files = _list_sim_files(rd.name, td.name)
            departures: list[str] = []
            truck_label = td.name
            for sf in sim_files:
                try:
                    payload = json.loads(sf.read_text())
                except Exception:
                    continue
                truck_label = payload.get("truck", {}).get("model_name", truck_label)
                for trip in payload.get("trips", []):
                    dep = trip.get("departure_iso")
                    if dep:
                        departures.append(dep)
            trucks.append({
                "slug": td.name,
                "label": truck_label,
                "n_runs": len(sim_files),
                "n_trips": len(departures),
                "earliest": min(departures) if departures else None,
                "latest": max(departures) if departures else None,
            })
        routes.append({
            "slug": rd.name,
            "origin": meta.get("origin_query"),
            "destination": meta.get("destination_query"),
            "distance_km": (meta.get("total_distance_m") or 0) / 1000.0
                if meta.get("total_distance_m") is not None else meta.get("distance_km"),
            "n_segments": meta.get("n_segments"),
            "trucks": trucks,
        })
    return {"routes": routes}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _load_raw(route_slug: str, truck_slug: str) -> dict[str, Any]:
    route_dir = ROUTES_DIR / route_slug
    if not (route_dir / "route.json").exists():
        raise HTTPException(404, f"Unknown route '{route_slug}'")
    route_meta = json.loads((route_dir / "route.json").read_text())
    route_parquet = route_dir / "route.parquet"
    if not route_parquet.exists():
        raise HTTPException(500, f"Missing route.parquet for {route_slug}")
    route_df = pd.read_parquet(route_parquet)
    route_df = _normalize_route(route_df)

    sim_files = _list_sim_files(route_slug, truck_slug)
    if not sim_files:
        raise HTTPException(404, f"No simulations for {route_slug}/{truck_slug}")

    trip_rows: list[dict[str, Any]] = []
    truck_meta: dict[str, Any] = {}
    generated_runs: list[str] = []
    trips_frames: list[pd.DataFrame] = []
    drivers_meta: list[dict[str, Any]] = []
    seen_drivers: set[str] = set()
    for sf in sim_files:
        payload = json.loads(sf.read_text())
        truck_meta = payload.get("truck", truck_meta)
        generated_runs.append(payload.get("run_id", sf.stem))
        # driver metadata (no trips) — name lookup
        names: dict[str, str] = {}
        for d in payload.get("drivers", []):
            did = d.get("driver_id")
            names[did] = d.get("name")
            if did not in seen_drivers:
                seen_drivers.add(did)
                drivers_meta.append({k: v for k, v in d.items() if k != "trips"})
        # trip summary lives at payload["trips"] in current format;
        # legacy format may also nest trips inside each driver.
        for trip in payload.get("trips", []):
            row = dict(trip)
            row.setdefault("driver_name", names.get(row.get("driver_id")))
            trip_rows.append(row)
        for d in payload.get("drivers", []):
            for trip in d.get("trips", []):
                row = {**trip, "driver_id": d.get("driver_id"),
                       "driver_name": d.get("name")}
                trip_rows.append(row)
        trips_parquet = sf.with_name(sf.name.replace("_drivers.json", "_trips.parquet"))
        if trips_parquet.exists():
            trips_frames.append(pd.read_parquet(trips_parquet))

    trip_summary = pd.DataFrame(trip_rows)
    trips = pd.concat(trips_frames, ignore_index=True) if trips_frames else pd.DataFrame()

    trip_summary = _normalize_summary(trip_summary)
    trips = _normalize_trips(trips)

    return {
        "route_meta": route_meta,
        "route_df": route_df,
        "truck_meta": truck_meta,
        "trip_summary": trip_summary,
        "trips": trips,
        "drivers_meta": drivers_meta,
        "runs": generated_runs,
    }


def load_data(route_slug: str, truck_slug: str, since: str | None = None) -> dict[str, Any]:
    raw = _load_raw(route_slug, truck_slug)
    summary = raw["trip_summary"].copy()
    trips = raw["trips"].copy()
    if since and not summary.empty and "departure_iso" in summary.columns:
        mask = summary["departure_iso"] >= since
        summary = summary[mask]
        if not trips.empty and "trip_id" in trips.columns:
            trips = trips[trips["trip_id"].isin(summary["trip_id"])]
    return {
        **raw,
        "trip_summary": summary.reset_index(drop=True),
        "trips": trips.reset_index(drop=True),
    }


def _resolve_selection(route: str | None, truck: str | None) -> tuple[str, str]:
    rdirs = _list_route_dirs()
    if not rdirs:
        raise HTTPException(404, "No routes available. Run datosDeRuta.py first.")
    route_slug = route or rdirs[0].name
    if not (ROUTES_DIR / route_slug / "route.json").exists():
        raise HTTPException(404, f"Unknown route '{route_slug}'")
    tdirs = _list_truck_dirs(route_slug)
    if not tdirs:
        raise HTTPException(404, f"No truck simulations for {route_slug}")
    truck_slug = truck or tdirs[0].name
    if not (ROUTES_DIR / route_slug / "sims" / truck_slug).exists():
        raise HTTPException(404, f"Unknown truck '{truck_slug}' for {route_slug}")
    return route_slug, truck_slug


# ---------------------------------------------------------------------------
# Baselines & helpers
# ---------------------------------------------------------------------------

def _fuel_baseline_l_per_100km(summary: pd.DataFrame) -> float | None:
    if summary.empty or "fuel_l_per_100km" not in summary.columns:
        return None
    vals = summary["fuel_l_per_100km"].dropna()
    return float(vals.min()) if len(vals) else None


def _idle_per_driver(trips: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    if trips.empty or summary.empty:
        return pd.DataFrame(columns=["driver_id", "idle_h", "total_km", "idle_h_per_100km"])
    if "driver_id" not in trips.columns:
        trips = trips.merge(summary[["trip_id", "driver_id"]], on="trip_id", how="left")
    # Prefer the simulator's explicit idle_event flag; fall back to a low-speed heuristic.
    if "idle_event" in trips.columns:
        idle_seconds = trips["idle_event"].astype(bool).astype(int) * trips["dt_s"]
    else:
        idle_seconds = (trips["speed_kph"] < 3).astype(int) * trips["dt_s"]
    idle = (
        trips.assign(idle=idle_seconds / 3600.0)
        .groupby("driver_id", as_index=False)["idle"].sum()
        .rename(columns={"idle": "idle_h"})
    )
    km = summary.groupby("driver_id", as_index=False)["distance_km"].sum().rename(
        columns={"distance_km": "total_km"})
    out = idle.merge(km, on="driver_id", how="outer").fillna(0.0)
    out["idle_h_per_100km"] = np.where(
        out["total_km"] > 0, out["idle_h"] / out["total_km"] * 100.0, 0.0
    )
    return out


def _idle_baseline_h_per_100km(idle_df: pd.DataFrame) -> float | None:
    if idle_df.empty:
        return None
    pos = idle_df[idle_df["total_km"] > 0]
    return float(pos["idle_h_per_100km"].min()) if not pos.empty else None


# ---------------------------------------------------------------------------
# KPI endpoints
# ---------------------------------------------------------------------------

@app.get("/api/kpis")
def kpis(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    s = data["trip_summary"]
    if s.empty:
        return {"empty": True, "route": rs, "truck": ts}
    total_km = float(s["distance_km"].sum())
    total_fuel = float(s["fuel_l"].sum())
    fuel_per_100km = total_fuel / total_km * 100.0 if total_km else 0.0
    co2_per_km = total_fuel * CO2_KG_PER_L_DIESEL / total_km if total_km else 0.0
    avg_speed = float(s["avg_speed_kph"].mean())

    # Utilization = moving time / total trip time. Use explicit idle_event when present.
    trips = data["trips"]
    if not trips.empty:
        total_time_s = float(trips["dt_s"].sum())
        if "idle_event" in trips.columns:
            idle_s = float((trips["idle_event"].astype(bool).astype(int) * trips["dt_s"]).sum())
        else:
            idle_s = float(((trips["speed_kph"] < 3) * trips["dt_s"]).sum())
        utilization = (total_time_s - idle_s) / total_time_s if total_time_s else 0.0
    else:
        utilization = 0.0

    return {
        "route": rs,
        "truck": ts,
        "n_trips": int(len(s)),
        "fuel_l_per_100km": fuel_per_100km,
        "co2_kg_per_km": co2_per_km,
        "avg_speed_kph": avg_speed,
        "utilization_pct": utilization * 100.0,
    }


@app.get("/api/drivers")
def drivers(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    s = data["trip_summary"]
    if s.empty:
        return {"drivers": [], "baseline_fuel_l_per_100km": None,
                "baseline_idle_h_per_100km": None}

    by = s.groupby(["driver_id", "driver_name"], as_index=False).agg(
        n_trips=("trip_id", "count"),
        distance_km=("distance_km", "sum"),
        fuel_l=("fuel_l", "sum"),
        avg_speed_kph=("avg_speed_kph", "mean"),
        harsh_brakes=("harsh_brake_events", "sum"),
        harsh_accels=("harsh_accel_events", "sum"),
        overspeed_pct=("pct_time_overspeed", "mean"),
    )
    by["fuel_l_per_100km"] = by["fuel_l"] / by["distance_km"] * 100.0

    fuel_base = _fuel_baseline_l_per_100km(s)
    idle_df = _idle_per_driver(data["trips"], s)
    idle_base = _idle_baseline_h_per_100km(idle_df)

    by = by.merge(idle_df[["driver_id", "idle_h", "idle_h_per_100km"]],
                  on="driver_id", how="left").fillna(0.0)

    if fuel_base:
        by["excess_fuel_pct"] = (by["fuel_l_per_100km"] - fuel_base) / fuel_base * 100.0
        by["excess_fuel_l"] = (by["fuel_l_per_100km"] - fuel_base) / 100.0 * by["distance_km"]
    else:
        by["excess_fuel_pct"] = 0.0
        by["excess_fuel_l"] = 0.0
    if idle_base is not None:
        by["excess_idle_h"] = np.maximum(
            0.0, (by["idle_h_per_100km"] - idle_base) / 100.0 * by["distance_km"]
        )
    else:
        by["excess_idle_h"] = 0.0

    # Composite score: 60% fuel efficiency vs best, 40% safety (inverse harsh+overspeed).
    fuel_min, fuel_max = by["fuel_l_per_100km"].min(), by["fuel_l_per_100km"].max()
    fuel_norm = (
        1 - (by["fuel_l_per_100km"] - fuel_min) / (fuel_max - fuel_min)
        if fuel_max > fuel_min else pd.Series(1.0, index=by.index)
    )
    safety_raw = by["harsh_brakes"] + by["harsh_accels"] + by["overspeed_pct"]
    s_min, s_max = safety_raw.min(), safety_raw.max()
    safety_norm = (
        1 - (safety_raw - s_min) / (s_max - s_min)
        if s_max > s_min else pd.Series(1.0, index=by.index)
    )
    by["score"] = (0.6 * fuel_norm + 0.4 * safety_norm) * 100.0
    by = by.sort_values("score", ascending=False).reset_index(drop=True)
    by["rank"] = by.index + 1

    return {
        "drivers": by.to_dict(orient="records"),
        "baseline_fuel_l_per_100km": fuel_base,
        "baseline_idle_h_per_100km": idle_base,
    }


@app.get("/api/trucks")
def trucks(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    s = data["trip_summary"]
    truck_meta = data["truck_meta"]
    if s.empty:
        return {"truck": truck_meta, "stats": None}
    return {
        "truck": truck_meta,
        "stats": {
            "n_trips": int(len(s)),
            "distance_km": float(s["distance_km"].sum()),
            "fuel_l_per_100km": float(s["fuel_l"].sum() / s["distance_km"].sum() * 100.0),
            "avg_speed_kph": float(s["avg_speed_kph"].mean()),
            "harsh_brakes": int(s["harsh_brake_events"].sum()),
            "harsh_accels": int(s["harsh_accel_events"].sum()),
        },
    }


@app.get("/api/route/segments")
def route_segments(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
    top: int = Query(15),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    trips = data["trips"]
    route_df = data["route_df"]
    if trips.empty or route_df.empty:
        return {"hotspots": [], "n_segments": int(len(route_df))}
    by_seg = trips.groupby("seg_idx", as_index=False).agg(
        fuel_l=("fuel_l", "sum"),
        dist_km=("seg_len_m", lambda x: x.sum() / 1000.0),
        avg_speed=("speed_kph", "mean"),
    )
    by_seg["fuel_per_km_l"] = np.where(
        by_seg["dist_km"] > 0, by_seg["fuel_l"] / by_seg["dist_km"], 0.0
    )
    seg_geo = route_df[["seg_idx", "lat_mid", "lon_mid", "slope_pct"]] \
        if "lat_mid" in route_df.columns else route_df.assign(
            lat_mid=route_df["lat"], lon_mid=route_df["lon"], seg_idx=route_df.index
        )[["seg_idx", "lat_mid", "lon_mid", "slope_pct"]]
    merged = by_seg.merge(seg_geo, on="seg_idx", how="left")
    hot = merged.sort_values("fuel_per_km_l", ascending=False).head(top)
    return {
        "hotspots": hot.to_dict(orient="records"),
        "n_segments": int(len(route_df)),
    }


@app.get("/api/route/map")
def route_map(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    route_df = data["route_df"]
    trips = data["trips"]
    if route_df.empty:
        return {"segments": [], "origin": None, "destination": None}
    fuel_by_seg = (
        trips.groupby("seg_idx").apply(
            lambda d: d["fuel_l"].sum() / max(d["seg_len_m"].sum() / 1000.0, 1e-6)
        ).to_dict() if not trips.empty else {}
    )
    coord_lat = "lat_mid" if "lat_mid" in route_df.columns else "lat"
    coord_lon = "lon_mid" if "lon_mid" in route_df.columns else "lon"
    rows = route_df[["seg_idx", coord_lat, coord_lon]].iloc[::2]  # decimate
    segs = [
        {
            "seg_idx": int(r["seg_idx"]),
            "lat": float(r[coord_lat]),
            "lon": float(r[coord_lon]),
            "fuel_per_km_l": float(fuel_by_seg.get(r["seg_idx"], 0.0)),
        }
        for _, r in rows.iterrows()
    ]
    meta = data["route_meta"]
    def _coord(v):
        if isinstance(v, dict):
            return v
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return {"lat": float(v[0]), "lon": float(v[1])}
        return None
    return {
        "segments": segs,
        "origin": _coord(meta.get("origin")),
        "destination": _coord(meta.get("destination")),
        "distance_km": (meta.get("total_distance_m") or 0) / 1000.0
            if meta.get("total_distance_m") is not None else meta.get("distance_km"),
    }


@app.get("/api/route/coaching")
def route_coaching(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
) -> dict[str, Any]:
    """Route geometry + median trip telemetry + rule-based recommendations (IF coach)."""
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    payload = build_coaching_payload(
        data["route_meta"], data["route_df"], data["trips"]
    )
    payload["route"] = rs
    payload["truck"] = ts
    return payload


@app.get("/api/anomalies")
def anomalies(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    s = data["trip_summary"]
    if s.empty:
        return {"by_kind": [], "by_driver": [], "recent": []}

    # Build per-trip anomaly index from the merged sim payloads.
    anomaly_rows: list[dict[str, Any]] = []
    for sf in _list_sim_files(rs, ts):
        try:
            payload = json.loads(sf.read_text())
        except Exception:
            continue
        for a in payload.get("anomalies", []):
            anomaly_rows.append(a)
    if not anomaly_rows:
        return {"by_kind": [], "by_driver": [], "recent": []}

    a_df = pd.DataFrame(anomaly_rows)
    # Filter by selected trips (which honors `since`).
    a_df = a_df[a_df["trip_id"].isin(s["trip_id"])]
    if a_df.empty:
        return {"by_kind": [], "by_driver": [], "recent": []}

    a_df = a_df.merge(
        s[["trip_id", "driver_id", "driver_name", "departure_iso"]],
        on="trip_id", how="left",
    )

    by_kind = (
        a_df.groupby("kind", as_index=False)
        .size().rename(columns={"size": "count"})
        .sort_values("count", ascending=False)
    )

    by_driver = (
        a_df.groupby(["driver_id", "driver_name", "kind"], as_index=False)
        .size().rename(columns={"size": "count"})
    )
    pivot = by_driver.pivot_table(
        index=["driver_id", "driver_name"], columns="kind",
        values="count", fill_value=0,
    ).reset_index()
    pivot["total"] = pivot.drop(columns=["driver_id", "driver_name"]).sum(axis=1)
    pivot = pivot.sort_values("total", ascending=False)

    recent = a_df.sort_values("departure_iso", ascending=False).head(200)[
        ["departure_iso", "driver_name", "kind", "trip_id", "segment_start", "segment_end", "detail"]
    ]
    recent["detail"] = recent["detail"].apply(
        lambda d: ", ".join(f"{k}={round(v,2) if isinstance(v,(int,float)) else v}"
                            for k, v in (d or {}).items()) if isinstance(d, dict) else ""
    )

    return {
        "by_kind": by_kind.to_dict(orient="records"),
        "by_driver": pivot.to_dict(orient="records"),
        "kinds": sorted(a_df["kind"].unique().tolist()),
        "recent": recent.to_dict(orient="records"),
        "total": int(len(a_df)),
    }


@app.get("/api/clusters")
def clusters(route: str | None = Query(None)):
    """Per-route driving-style clusters (UMAP + Agglomerative).

    Aggregates all trucks under the route to maximise sample size, since the
    features used are route-invariant driving style metrics.
    """
    rs, _ = _resolve_selection(route, None)
    try:
        return compute_route_clusters(rs)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/idle")
def idle(
    route: str | None = Query(None),
    truck: str | None = Query(None),
    since: str | None = Query(None),
):
    rs, ts = _resolve_selection(route, truck)
    data = load_data(rs, ts, since)
    s = data["trip_summary"]
    df = _idle_per_driver(data["trips"], s)
    base = _idle_baseline_h_per_100km(df)
    if not df.empty and base is not None:
        df["excess_idle_h"] = np.maximum(
            0.0, (df["idle_h_per_100km"] - base) / 100.0 * df["total_km"]
        )
        df["excess_idle_fuel_l"] = df["excess_idle_h"] * IDLE_FUEL_LPH
    df = df.sort_values("idle_h", ascending=False)
    return {
        "baseline_idle_h_per_100km": base,
        "by_driver": df.to_dict(orient="records"),
        "total_idle_h": float(df["idle_h"].sum()) if not df.empty else 0.0,
    }


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
