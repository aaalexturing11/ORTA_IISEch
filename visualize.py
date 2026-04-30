from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path

import pandas as pd
import folium

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

    # Simulación (si existe)
    sim_path = OUTPUT_DIR / f"sim_{route_id}_trips.parquet"
    if sim_path.exists():
        sim_df = pd.read_parquet(sim_path)
        first_trip = sim_df['trip_id'].iloc[0]
        # Columnas de interés para visualización
        cols = [
            'segment_id', 'recommendation_message', 'recommendation_action',
            'recommendation_science', 'recommendation_savings',
            'speed_kmh', 'rpm', 'ambient_temp_c', 'wind_speed_ms',
            'wind_dir_deg', 'precip_mmph', 'congestion_ratio', 'traffic_speed_kmh'
        ]
        # Asegurarse de que las columnas existen antes de seleccionar
        available_cols = [c for c in cols if c in sim_df.columns]
        trip_data = sim_df[sim_df['trip_id'] == first_trip][available_cols]
        df = df.merge(trip_data, on='segment_id', how='left')

    return meta, df, meta_path.with_suffix(".html")


def _color_for(value: float, vmin: float, vmax: float) -> str:
    if vmax == vmin or pd.isna(value):
        return "#3388ff"

    t = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))

    if t < 0.5:
        s = t * 2
        r, g, b = 0, int(255 * s), int(255 * (1 - s))
    else:
        s = (t - 0.5) * 2
        r, g, b = int(255 * s), int(255 * (1 - s)), 0

    return f"#{r:02x}{g:02x}{b:02x}"


def render(route_id: str | None, color_by: str = "slope") -> Path:
    meta, df, html_path = _load_route(route_id)

    # Selección de métrica
    if color_by == "slope":
        metric = df["slope_pct"].astype(float)
        vmin, vmax = -8.0, 8.0
        legend = "Slope (%)"
    elif color_by == "elevation":
        metric = df["altitude_start_m"].astype(float)
        vmin, vmax = float(metric.min()), float(metric.max())
        legend = "Elevation (m)"
    elif color_by == "traffic":
        metric = df["congestion_ratio"].astype(float)
        vmin, vmax = 0.0, 2.0
        legend = "Congestion"
    else:
        raise SystemExit(f"Unknown --color {color_by}")

    # Centro del mapa
    mid = df.iloc[len(df) // 2]

    fmap = folium.Map(
        location=[mid["start_lat"], mid["start_lon"]],
        zoom_start=10,
        tiles=None
    )

    # Capas base
    folium.TileLayer("OpenStreetMap", name="Mapa").add_to(fmap)

    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap",
        name="Topográfico",
        overlay=False
    ).add_to(fmap)

    folium.TileLayer(
        tiles="https://tiles.wmflabs.org/hillshading/{z}/{x}/{y}.png",
        attr="Hillshade",
        name="Relieve",
        overlay=True,
        opacity=0.5
    ).add_to(fmap)

    # Dibujar segmentos
    for _, row in df.iterrows():
        value = row.get(metric.name, float("nan"))
        color = _color_for(value, vmin, vmax)

        # Grosor según pendiente
        weight = 4 + min(6, abs(row.get("slope_pct", 0)) / 2)

        tooltip = (
            f"<b>Segmento {int(row['segment_id'])}</b><br>"
            f"Distancia: {row['length_m']:.0f} m<br>"
            f"Pendiente: {row.get('slope_pct', float('nan')):.2f}%<br>"
            f"Altura: {row.get('altitude_start_m', 'NA')} → {row.get('altitude_end_m', 'NA')} m<br>"
            f"ETA: +{row['eta_offset_s'] / 60:.1f} min"
        )

        # Clima
        if "wind_speed_ms" in row and pd.notna(row["wind_speed_ms"]):
            tooltip += (
                f"<br><b>Clima:</b> {row['ambient_temp_c']:.1f}°C | "
                f"Viento: {row['wind_speed_ms']:.1f} m/s | "
                f"Lluvia: {row['precip_mmph']:.1f} mm/h"
            )

        # Recomendaciones
        if "recommendation_message" in row and pd.notna(row["recommendation_message"]):
            if row["recommendation_action"] != "KEEP":
                tooltip += (
                    f"<br><b>Recomendación:</b> {row['recommendation_message']}"
                    f"<br><i>Base científica:</i> {row.get('recommendation_science', 'N/A')}"
                    f"<br>Ahorro est.: {row.get('recommendation_savings', 0)*100:.0f}% | "
                    f"{row['speed_kmh']:.1f} km/h | {row['rpm']:.0f} RPM"
                )

        folium.PolyLine(
            locations=[
                (row["start_lat"], row["start_lon"]),
                (row["end_lat"], row["end_lon"]),
            ],
            color=color,
            weight=weight,
            opacity=0.9,
            tooltip=tooltip,
        ).add_to(fmap)

        # Zonas críticas (Tráfico/Pendiente)
        if abs(row.get("slope_pct", 0)) > 6 or row.get("congestion_ratio", 1) > 1.5:
            folium.CircleMarker(
                location=(row["start_lat"], row["start_lon"]),
                radius=6,
                color="red" if row.get("congestion_ratio", 1) > 1.5 else "black",
                fill=True,
                fill_opacity=0.7,
                tooltip="Congestión alta" if row.get("congestion_ratio", 1) > 1.5 else "Pendiente fuerte"
            ).add_to(fmap)

        # Eventos de Clima (cada N segmentos para no saturar)
        if int(row['segment_id']) % 20 == 0:
            if row.get("precip_mmph", 0) > 0.5:
                folium.Marker(
                    location=(row["start_lat"], row["start_lon"]),
                    icon=folium.Icon(color="blue", icon="cloud-rain", prefix="fa"),
                    tooltip=f"Lluvia: {row['precip_mmph']:.1f} mm/h"
                ).add_to(fmap)
            elif row.get("wind_speed_ms", 0) > 8:
                folium.Marker(
                    location=(row["start_lat"], row["start_lon"]),
                    icon=folium.Icon(color="gray", icon="wind", prefix="fa"),
                    tooltip=f"Viento fuerte: {row['wind_speed_ms']:.1f} m/s"
                ).add_to(fmap)

    # Marcadores
    folium.Marker(
        location=meta["origin"],
        popup=f"Origen: {meta['origin_query']}",
        icon=folium.Icon(color="green")
    ).add_to(fmap)

    folium.Marker(
        location=meta["destination"],
        popup=f"Destino: {meta['destination_query']}",
        icon=folium.Icon(color="red")
    ).add_to(fmap)

    # Leyenda
    legend_html = f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 10px; border: 1px solid #888;
                border-radius: 6px; font-size: 12px;">
      <b>{legend}</b><br>
      {vmin:.1f} → {vmax:.1f}<br>
      Ruta: {meta['origin_query']} → {meta['destination_query']}<br>
      {meta['total_distance_m']/1000:.1f} km · {meta['n_segments']} segmentos
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl().add_to(fmap)

    fmap.save(str(html_path))
    return html_path


def _cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("route_id", nargs="?", default=None)
    parser.add_argument("--color", default="slope", choices=["slope", "elevation", "traffic"])
    parser.add_argument("--no-open", action="store_true")

    args = parser.parse_args()

    html_path = render(args.route_id, args.color)
    print(f"Saved: {html_path}")

    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    _cli()