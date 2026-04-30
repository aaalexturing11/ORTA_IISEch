"""
Route topography & (optional) traffic segmenter for heavy-transport telemetry.

Pipeline:
    1. Geocode origin/destination via Nominatim (OSM).
    2. Get road route via OSRM public demo server.
    3. Densify the polyline so no gap exceeds the segment length.
    4. Cut into fixed-length segments (default 200 m).
    5. Batch-fetch elevations from Open-Topo-Data (SRTM 30 m).
    6. Compute slope, bearing, gain/loss, cumulative distance & ETA.
    7. (Hook) attach traffic if a provider is configured.
    8. Persist as Parquet (one row per segment) + JSON metadata.

Output schema is append-friendly: telemetry columns
(fuel_l, speed_kmh, rpm, ...) can be merged on `segment_id` later.

Requirements:
    pip install requests pandas pyarrow

Usage:
    python datosDeRuta.py "Puebla, Mexico" "Cuautitlan, Mexico"
    python datosDeRuta.py "Puebla, Mexico" "Cuautitlan, Mexico" --segment-m 100
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

import requests

# ----------------------------- configuration ------------------------------- #

USER_AGENT = "datosDeRuta/0.1 (telemetry-anomaly-research)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
OPENTOPO_URL = "https://api.opentopodata.org/v1/srtm30m"

OPENTOPO_BATCH = 100        # max locations per request
OPENTOPO_SLEEP = 1.05       # public instance: 1 req/sec
HTTP_TIMEOUT = 30

OUTPUT_DIR = Path("output")
ROUTES_DIR = OUTPUT_DIR / "routes"


def slugify(text: str) -> str:
    """Filesystem-safe slug from a free-form string."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "unknown"


def route_slug(origin_query: str, destination_query: str) -> str:
    return f"{slugify(origin_query)}__{slugify(destination_query)}"

# ------------------------------ data models -------------------------------- #


@dataclass
class Segment:
    segment_id: int
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    length_m: float
    cum_distance_m: float
    altitude_start_m: float | None = None
    altitude_end_m: float | None = None
    altitude_delta_m: float | None = None
    altitude_gain_m: float | None = None
    altitude_loss_m: float | None = None
    slope_pct: float | None = None
    bearing_deg: float | None = None
    free_flow_speed_kmh: float | None = None
    eta_offset_s: float | None = None        # seconds from departure
    departure_iso: str | None = None         # ISO time entering this segment
    traffic_speed_kmh: float | None = None   # filled if provider available
    congestion_ratio: float | None = None


@dataclass
class RouteMetadata:
    route_id: str
    origin_query: str
    destination_query: str
    origin: tuple[float, float]
    destination: tuple[float, float]
    departure_iso: str
    segment_length_m: float
    total_distance_m: float
    total_duration_s: float
    n_segments: int
    routing_provider: str = "OSRM (public demo)"
    elevation_provider: str = "Open-Topo-Data SRTM 30m"
    traffic_provider: str | None = None
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ------------------------------- geometry ---------------------------------- #

EARTH_R = 6_371_000.0  # meters


def haversine_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bearing_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def interpolate(
    p1: tuple[float, float], p2: tuple[float, float], frac: float
) -> tuple[float, float]:
    """Linear interpolation in lat/lon — fine for sub-km segments."""
    return (p1[0] + (p2[0] - p1[0]) * frac, p1[1] + (p2[1] - p1[1]) * frac)


def resample_polyline(
    points: Sequence[tuple[float, float]], step_m: float
) -> list[tuple[float, float]]:
    """Resample a polyline so consecutive points are exactly `step_m` apart."""
    if len(points) < 2:
        return list(points)

    out: list[tuple[float, float]] = [points[0]]
    carry = 0.0  # distance already advanced past the last emitted point
    cursor = points[0]
    i = 1
    while i < len(points):
        nxt = points[i]
        seg_len = haversine_m(cursor, nxt)
        if seg_len == 0:
            i += 1
            continue
        if carry + seg_len < step_m:
            carry += seg_len
            cursor = nxt
            i += 1
            continue
        # need to emit a point on segment cursor->nxt at distance (step_m - carry)
        frac = (step_m - carry) / seg_len
        new_pt = interpolate(cursor, nxt, frac)
        out.append(new_pt)
        cursor = new_pt
        carry = 0.0
        # do NOT increment i; we may emit several points on the same segment
    # Always include the final endpoint
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


# --------------------------------- HTTP ------------------------------------ #


def _get(url: str, params: dict | None = None) -> dict:
    r = requests.get(
        url, params=params, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT
    )
    r.raise_for_status()
    return r.json()


def _post(url: str, payload: dict) -> dict:
    r = requests.post(
        url,
        json=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


# ------------------------------- providers --------------------------------- #


def geocode(query: str) -> tuple[float, float]:
    data = _get(NOMINATIM_URL, {"q": query, "format": "json", "limit": 1})
    if not data:
        raise RuntimeError(f"Geocoding returned no results for: {query!r}")
    return float(data[0]["lat"]), float(data[0]["lon"])


def osrm_route(
    origin: tuple[float, float], dest: tuple[float, float]
) -> dict:
    coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}
    data = _get(f"{OSRM_URL}/{coords}", params)
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM error: {data.get('code')} {data.get('message')}")
    route = data["routes"][0]
    # GeoJSON coords are [lon, lat]; convert to (lat, lon)
    geom = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
    return {
        "geometry": geom,
        "distance_m": route["distance"],
        "duration_s": route["duration"],
    }


def fetch_elevations(points: Sequence[tuple[float, float]]) -> list[float | None]:
    """Batch elevation lookups. Returns one altitude per point (meters)."""
    out: list[float | None] = []
    for i in range(0, len(points), OPENTOPO_BATCH):
        batch = points[i : i + OPENTOPO_BATCH]
        locations = "|".join(f"{lat},{lon}" for lat, lon in batch)
        try:
            data = _get(OPENTOPO_URL, {"locations": locations})
            for item in data.get("results", []):
                out.append(item.get("elevation"))
        except requests.HTTPError as e:
            # Pad batch with None on failure rather than aborting the whole route
            print(f"[warn] elevation batch failed ({e}); filling with None")
            out.extend([None] * len(batch))
        if i + OPENTOPO_BATCH < len(points):
            time.sleep(OPENTOPO_SLEEP)
    return out


# ------------------------------- segmenter --------------------------------- #


def build_segments(
    polyline: Sequence[tuple[float, float]],
    segment_m: float,
    free_flow_kmh: float,
    departure: datetime,
) -> list[Segment]:
    nodes = resample_polyline(polyline, segment_m)
    segments: list[Segment] = []
    cum_d = 0.0
    cum_t = 0.0
    speed_ms = free_flow_kmh / 3.6
    for i in range(len(nodes) - 1):
        a, b = nodes[i], nodes[i + 1]
        length = haversine_m(a, b)
        cum_d += length
        eta_off = cum_t
        cum_t += length / speed_ms
        segments.append(
            Segment(
                segment_id=i,
                start_lat=a[0],
                start_lon=a[1],
                end_lat=b[0],
                end_lon=b[1],
                length_m=length,
                cum_distance_m=cum_d,
                bearing_deg=bearing_deg(a, b),
                free_flow_speed_kmh=free_flow_kmh,
                eta_offset_s=eta_off,
                departure_iso=(departure + timedelta(seconds=eta_off)).isoformat(),
            )
        )
    return segments


def attach_elevation(segments: list[Segment]) -> None:
    if not segments:
        return
    points = [(segments[0].start_lat, segments[0].start_lon)]
    points += [(s.end_lat, s.end_lon) for s in segments]
    elevs = fetch_elevations(points)
    for i, seg in enumerate(segments):
        a = elevs[i]
        b = elevs[i + 1]
        seg.altitude_start_m = a
        seg.altitude_end_m = b
        if a is not None and b is not None:
            delta = b - a
            seg.altitude_delta_m = delta
            seg.altitude_gain_m = max(delta, 0.0)
            seg.altitude_loss_m = max(-delta, 0.0)
            if seg.length_m > 0:
                seg.slope_pct = (delta / seg.length_m) * 100.0


# ------------------------------- persistence ------------------------------- #


def write_outputs(meta: RouteMetadata, segments: list[Segment]) -> tuple[Path, Path]:
    slug = route_slug(meta.origin_query, meta.destination_query)
    route_dir = ROUTES_DIR / slug
    route_dir.mkdir(parents=True, exist_ok=True)
    base = route_dir / "route"
    parquet_path = base.with_suffix(".parquet")
    json_path = base.with_suffix(".json")

    try:
        import pandas as pd  # noqa: WPS433 (lazy import: optional dep)

        df = pd.DataFrame([asdict(s) for s in segments])
        df.to_parquet(parquet_path, index=False)
    except ImportError:
        # Fallback: CSV if pandas/pyarrow not installed
        import csv

        parquet_path = base.with_suffix(".csv")
        with parquet_path.open("w", newline="") as f:
            if segments:
                writer = csv.DictWriter(f, fieldnames=list(asdict(segments[0]).keys()))
                writer.writeheader()
                writer.writerows(asdict(s) for s in segments)

    with json_path.open("w") as f:
        json.dump(asdict(meta), f, indent=2)

    return parquet_path, json_path


# --------------------------------- entry ----------------------------------- #


def generate_route_dataset(
    origin_query: str,
    destination_query: str,
    segment_m: float = 200.0,
    free_flow_kmh: float = 80.0,
    departure: datetime | None = None,
) -> tuple[RouteMetadata, list[Segment]]:
    departure = departure or datetime.now(timezone.utc)

    print(f"[1/5] Geocoding {origin_query!r} and {destination_query!r}...")
    origin = geocode(origin_query)
    time.sleep(1)  # be nice to Nominatim
    dest = geocode(destination_query)

    print(f"[2/5] Routing via OSRM ({origin} -> {dest})...")
    route = osrm_route(origin, dest)
    print(
        f"      total {route['distance_m'] / 1000:.1f} km, "
        f"{route['duration_s'] / 60:.0f} min (free flow)"
    )

    print(f"[3/5] Segmenting at {segment_m:.0f} m intervals...")
    segments = build_segments(route["geometry"], segment_m, free_flow_kmh, departure)
    print(f"      {len(segments)} segments")

    print("[4/5] Fetching elevations (batched)...")
    attach_elevation(segments)

    meta = RouteMetadata(
        route_id=uuid.uuid4().hex[:12],
        origin_query=origin_query,
        destination_query=destination_query,
        origin=origin,
        destination=dest,
        departure_iso=departure.isoformat(),
        segment_length_m=segment_m,
        total_distance_m=route["distance_m"],
        total_duration_s=route["duration_s"],
        n_segments=len(segments),
    )

    print("[5/5] Writing outputs...")
    parquet_path, json_path = write_outputs(meta, segments)
    print(f"      data:     {parquet_path}")
    print(f"      metadata: {json_path}")
    return meta, segments


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("origin", help='e.g. "Puebla, Mexico"')
    p.add_argument("destination", help='e.g. "Cuautitlan, Mexico"')
    p.add_argument("--segment-m", type=float, default=200.0, help="Segment length in meters (default: 200)")
    p.add_argument("--free-flow-kmh", type=float, default=80.0, help="Assumed free-flow speed for ETA (default: 80)")
    p.add_argument("--departure", type=str, default=None, help="ISO datetime; default = now (UTC)")
    args = p.parse_args()

    departure = datetime.fromisoformat(args.departure) if args.departure else None
    generate_route_dataset(
        origin_query=args.origin,
        destination_query=args.destination,
        segment_m=args.segment_m,
        free_flow_kmh=args.free_flow_kmh,
        departure=departure,
    )


if __name__ == "__main__":
    _cli()
