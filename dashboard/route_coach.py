"""Rule-based eco-driving coach (relief + traffic + weather → advice).

Ported from the bibi branch ``model_optimizer.py``; used by ``/api/route/coaching``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class HeavyTruckOptimizer:
    def __init__(self) -> None:
        self.optimum_rpm = (900, 1400)
        self.peak_torque_nm = 2700
        self.frontal_area = 9.5

    def get_advice(
        self, telemetry: dict[str, float], segment: dict[str, float]
    ) -> dict[str, Any]:
        speed = float(telemetry.get("speed_kmh") or 0)
        rpm = float(telemetry.get("rpm") or 0)
        slope = float(segment.get("slope_pct") or 0)
        congestion = float(segment.get("congestion_ratio") or 1.0)
        wind_ms = float(segment.get("wind_speed_ms") or 0)
        precip = float(segment.get("precip_mmph") or 0)

        if congestion > 1.8:
            return {
                "action": "LOW_SPEED_STEADY",
                "ui_message": (
                    "Tráfico denso: Mantenga velocidad baja constante. "
                    "No acelere y frene bruscamente."
                ),
                "science": (
                    "Gonder (2012): Mantener una velocidad baja constante en tráfico "
                    "ahorra hasta un 20% frente al ciclo de aceleración y frenado total."
                ),
                "savings": 0.20,
            }
        if congestion > 1.3 and speed > 50:
            return {
                "action": "COASTING",
                "ui_message": (
                    "Congestión detectada adelante: Suelte el pedal. "
                    "Deje que el peso del camión lo lleve."
                ),
                "science": (
                    "Nasir (2014): La navegación verde utiliza datos de flujo para "
                    "reducir la energía cinética desperdiciada en frenado."
                ),
                "savings": 0.35,
            }
        if wind_ms > 10 and speed > 75:
            return {
                "action": "WIND_COMPENSATION",
                "ui_message": (
                    f"Viento fuerte ({wind_ms} m/s): Reduzca a 70 km/h. "
                    "El viento está actuando como un freno constante."
                ),
                "science": (
                    "La fuerza de arrastre aumenta con el cuadrado de la velocidad "
                    "del aire; bajar ~10 km/h reduce el gasto de forma notable."
                ),
                "savings": 0.15,
            }
        if precip > 1.5:
            return {
                "action": "WET_EFFICIENCY",
                "ui_message": (
                    "Lluvia: Reduzca velocidad. El arrastre por agua y la pérdida de "
                    "tracción bajan la eficiencia."
                ),
                "science": (
                    "Gonder (2012): Superficies mojadas aumentan resistencia a la "
                    "rodadura y el riesgo de micro-patinaje."
                ),
                "savings": 0.08,
            }
        if slope > 4:
            return {
                "action": "POWER_BAND",
                "ui_message": (
                    "Subida pronunciada: Mantenga el motor entre 1100-1300 RPM para "
                    f"torque máximo ({self.peak_torque_nm} Nm)."
                ),
                "science": (
                    "Ficha técnica motor: operar en el pico de torque evita "
                    "inyecciones extra de combustible por falta de fuerza."
                ),
                "savings": 0.12,
            }
        return {
            "action": "KEEP",
            "ui_message": "Condiciones óptimas: Mantenga crucero estable.",
            "science": "Estado estacionario: mínima variación de aceleración detectada.",
            "savings": 0.0,
        }


def _slope_color_hex(slope: float, vmin: float = -8.0, vmax: float = 8.0) -> str:
    if vmax == vmin or not np.isfinite(slope):
        return "#3388ff"
    t = max(0.0, min(1.0, (float(slope) - vmin) / (vmax - vmin)))
    if t < 0.5:
        s = t * 2
        r, g, b = 0, int(255 * s), int(255 * (1 - s))
    else:
        s = (t - 0.5) * 2
        r, g, b = int(255 * s), int(255 * (1 - s)), 0
    return f"#{r:02x}{g:02x}{b:02x}"


def build_coaching_payload(
    route_meta: dict[str, Any],
    route_df: pd.DataFrame,
    trips: pd.DataFrame,
) -> dict[str, Any]:
    """Merge route geometry with aggregated trip telemetry and attach IF-model advice."""
    if route_df.empty:
        return {
            "empty": True,
            "segments": [],
            "origin": None,
            "destination": None,
            "legend": {"label": "Pendiente (%)", "min": -8.0, "max": 8.0},
        }

    df = route_df.copy()
    if "seg_idx" not in df.columns and "segment_id" in df.columns:
        df = df.rename(columns={"segment_id": "seg_idx"})

    need = ["start_lat", "start_lon", "end_lat", "end_lon", "seg_idx"]
    for c in need:
        if c not in df.columns:
            return {
                "empty": True,
                "segments": [],
                "origin": None,
                "destination": None,
                "error": f"route.parquet missing column {c}",
                "legend": {"label": "Pendiente (%)", "min": -8.0, "max": 8.0},
            }

    agg_cols = [
        "speed_kmh",
        "rpm",
        "ambient_temp_c",
        "wind_speed_ms",
        "precip_mmph",
        "congestion_ratio",
    ]
    trip_agg = pd.DataFrame()
    if not trips.empty and "seg_idx" in trips.columns:
        present = [c for c in agg_cols if c in trips.columns]
        if present:
            trip_agg = trips.groupby("seg_idx", sort=False)[present].median().reset_index()

    if not trip_agg.empty:
        df = df.merge(trip_agg, on="seg_idx", how="left")

    opt = HeavyTruckOptimizer()
    segments: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        seg_idx = int(row["seg_idx"])
        slope = float(row.get("slope_pct") or 0)
        length_m = float(row.get("length_m") or 0)
        speed = float(row["speed_kmh"]) if pd.notna(row.get("speed_kmh")) else 72.0
        rpm = float(row["rpm"]) if pd.notna(row.get("rpm")) else 1180.0
        temp_c = float(row["ambient_temp_c"]) if pd.notna(row.get("ambient_temp_c")) else 20.0
        wind = float(row["wind_speed_ms"]) if pd.notna(row.get("wind_speed_ms")) else 0.0
        precip = float(row["precip_mmph"]) if pd.notna(row.get("precip_mmph")) else 0.0
        cong = float(row["congestion_ratio"]) if pd.notna(row.get("congestion_ratio")) else 1.0

        seg_env = {
            "slope_pct": slope,
            "congestion_ratio": cong,
            "wind_speed_ms": wind,
            "precip_mmph": precip,
        }
        tel = {"speed_kmh": speed, "rpm": rpm}
        advice = opt.get_advice(tel, seg_env)

        alerts: list[str] = []
        if abs(slope) > 6:
            alerts.append("steep_slope")
        if cong > 1.5:
            alerts.append("traffic")
        if precip > 0.5 or (precip > 0.1 and wind > 6):
            alerts.append("weather")
        elif wind > 10:
            alerts.append("weather")

        eta_s = row.get("eta_offset_s")
        eta_min = float(eta_s) / 60.0 if pd.notna(eta_s) else None

        alt0 = row.get("altitude_start_m")
        alt1 = row.get("altitude_end_m")
        color = _slope_color_hex(slope)
        weight = 4 + min(6, abs(slope) / 2)

        show_weather = seg_idx % 20 == 0 and (precip > 0.5 or wind > 8)

        segments.append(
            {
                "seg_idx": seg_idx,
                "start_lat": float(row["start_lat"]),
                "start_lon": float(row["start_lon"]),
                "end_lat": float(row["end_lat"]),
                "end_lon": float(row["end_lon"]),
                "length_m": length_m,
                "slope_pct": slope,
                "color": color,
                "weight": float(weight),
                "altitude_start_m": float(alt0) if pd.notna(alt0) else None,
                "altitude_end_m": float(alt1) if pd.notna(alt1) else None,
                "eta_offset_min": eta_min,
                "ambient_temp_c": temp_c,
                "wind_speed_ms": wind,
                "precip_mmph": precip,
                "congestion_ratio": cong,
                "speed_kmh": speed,
                "rpm": rpm,
                "recommendation_action": advice["action"],
                "recommendation_message": advice["ui_message"],
                "recommendation_science": advice["science"],
                "recommendation_savings": float(advice["savings"]),
                "alerts": alerts,
                "show_weather_marker": show_weather,
            }
        )

    oq = route_meta.get("origin_query") or "Origen"
    dq = route_meta.get("destination_query") or "Destino"
    om = route_meta.get("origin")
    dm = route_meta.get("destination")
    origin = None
    destination = None
    if isinstance(om, (list, tuple)) and len(om) >= 2:
        origin = {"lat": float(om[0]), "lon": float(om[1]), "label": oq}
    if isinstance(dm, (list, tuple)) and len(dm) >= 2:
        destination = {"lat": float(dm[0]), "lon": float(dm[1]), "label": dq}

    total_km = (route_meta.get("total_distance_m") or 0) / 1000.0
    n_seg = route_meta.get("n_segments") or len(segments)

    return {
        "empty": False,
        "origin_query": oq,
        "destination_query": dq,
        "origin": origin,
        "destination": destination,
        "total_distance_km": float(total_km) if total_km else None,
        "n_segments": int(n_seg),
        "legend": {"label": "Pendiente (%)", "min": -8.0, "max": 8.0},
        "segments": segments,
    }
