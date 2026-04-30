"""
Visualize a generated route on an interactive Leaflet map (via Folium).

Reads output/route_<id>.{parquet|csv} + output/route_<id>.json and writes
output/route_<id>.html. Open it in any browser.

    pip install folium pandas pyarrow

Usage:
    python visualize.py                       # picks the most recent route
    python visualize.py 8b78eed1c4b0          # specific route id
    python visualize.py --color elevation     # color by altitude instead of slope
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path("output")


def _load_route(route_id: str | None) -> tuple[dict, pd.DataFrame, Path]:
    if route_id is None:
        candidates = sorted(OUTPUT_DIR.glob("route_*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise SystemExit(f"No route_*.json found in {OUTPUT_DIR}/")
        meta_path = candidates[-1]
        route_id = meta_path.stem.removeprefix("route_")
    else:
        meta_path = OUTPUT_DIR / f"route_{route_id}.json"
        if not meta_path.exists():
            raise SystemExit(f"Missing {meta_path}")

    meta = json.loads(meta_path.read_text())

    parquet = OUTPUT_DIR / f"route_{route_id}.parquet"
    csv = OUTPUT_DIR / f"route_{route_id}.csv"
    if parquet.exists():
        df = pd.read_parquet(parquet)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        raise SystemExit(f"No segment data found for route {route_id}")

    return meta, df, meta_path.with_suffix(".html")


def _color_for(value: float, vmin: float, vmax: float) -> str:
    """Blue (low) -> green -> red (high). Returns #rrggbb."""
    if vmax == vmin or pd.isna(value):
        return "#3388ff"
    t = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
    if t < 0.5:
        # blue -> green
        s = t * 2
        r, g, b = 0, int(255 * s), int(255 * (1 - s))
    else:
        # green -> red
        s = (t - 0.5) * 2
        r, g, b = int(255 * s), int(255 * (1 - s)), 0
    return f"#{r:02x}{g:02x}{b:02x}"


def render(route_id: str | None, color_by: str = "slope") -> Path:
    import folium

    meta, df, html_path = _load_route(route_id)

    # Choose the metric used for coloring.
    if color_by == "slope":
        metric = df["slope_pct"].astype(float)
        vmin, vmax = -8.0, 8.0  # clamp for color scale; gradients beyond are saturated
        legend = "Slope (%)"
    elif color_by == "elevation":
        metric = df["altitude_start_m"].astype(float)
        vmin, vmax = float(metric.min()), float(metric.max())
        legend = "Elevation (m)"
    else:
        raise SystemExit(f"Unknown --color {color_by!r}")

    # Center map on route midpoint.
    mid = df.iloc[len(df) // 2]
    fmap = folium.Map(
        location=[mid["start_lat"], mid["start_lon"]],
        zoom_start=9,
        tiles="OpenStreetMap",
    )

    # Draw each segment as its own polyline so colors can vary.
    for _, row in df.iterrows():
        color = _color_for(row[metric.name], vmin, vmax)
        folium.PolyLine(
            locations=[
                (row["start_lat"], row["start_lon"]),
                (row["end_lat"], row["end_lon"]),
            ],
            color=color,
            weight=4,
            opacity=0.85,
            tooltip=(
                f"seg {int(row['segment_id'])} | "
                f"{row['length_m']:.0f} m | "
                f"slope {row.get('slope_pct', float('nan')):.2f}% | "
                f"alt {row.get('altitude_start_m', float('nan'))}→"
                f"{row.get('altitude_end_m', float('nan'))} m | "
                f"ETA +{row['eta_offset_s'] / 60:.1f} min"
            ),
        ).add_to(fmap)

    # Origin / destination markers.
    folium.Marker(
        location=meta["origin"],
        popup=f"Origin: {meta['origin_query']}",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(fmap)
    folium.Marker(
        location=meta["destination"],
        popup=f"Destination: {meta['destination_query']}",
        icon=folium.Icon(color="red", icon="stop"),
    ).add_to(fmap)

    # Simple HTML legend.
    legend_html = f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 10px 14px; border: 1px solid #888;
                border-radius: 6px; font-family: sans-serif; font-size: 12px;">
      <b>{legend}</b><br>
      <span style="display:inline-block;width:12px;height:12px;background:#0000ff;"></span>
      {vmin:.1f}
      &nbsp;→&nbsp;
      <span style="display:inline-block;width:12px;height:12px;background:#00ff00;"></span>
      &nbsp;→&nbsp;
      <span style="display:inline-block;width:12px;height:12px;background:#ff0000;"></span>
      {vmax:.1f}
      <br>
      Route: {meta['origin_query']} → {meta['destination_query']}<br>
      {meta['total_distance_m'] / 1000:.1f} km · {meta['n_segments']} segments
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))

    fmap.save(str(html_path))
    return html_path


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("route_id", nargs="?", default=None, help="Route id (default: latest)")
    p.add_argument("--color", default="slope", choices=["slope", "elevation"])
    p.add_argument("--no-open", action="store_true", help="Don't open the browser")
    args = p.parse_args()

    html_path = render(args.route_id, color_by=args.color)
    print(f"Wrote {html_path}")
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    _cli()
