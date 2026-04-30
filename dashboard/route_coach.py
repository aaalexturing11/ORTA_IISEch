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
                    "Tráfico denso. Mantén una velocidad baja y constante; "
                    "evita acelerar y frenar de forma repetida."
                ),
                "science": (
                    "Un ritmo estable en congestión suele consumir menos combustible "
                    "que alternar aceleraciones y frenadas continuas."
                ),
                "savings": 0.20,
            }
        if congestion > 1.3 and speed > 50:
            return {
                "action": "COASTING",
                "ui_message": (
                    "Congestión más adelante. Levanta el pie del acelerador "
                    "y deja avanzar el vehículo por inercia."
                ),
                "science": (
                    "Anticipar la cola y circular sin acelerar de más reduce "
                    "frenadas bruscas y consumo."
                ),
                "savings": 0.35,
            }
        if wind_ms > 10 and speed > 75:
            return {
                "action": "WIND_COMPENSATION",
                "ui_message": (
                    f"Viento fuerte ({wind_ms:.0f} m/s). Reduce la velocidad; "
                    f"por ejemplo hacia 70 km/h si el límite, la carga y la vía lo permiten."
                ),
                "science": (
                    "A mayor velocidad, el viento de frente incrementa la resistencia "
                    "y el consumo de forma notable."
                ),
                "savings": 0.15,
            }
        if precip > 1.5:
            return {
                "action": "WET_EFFICIENCY",
                "ui_message": (
                    "Lluvia intensa. Reduce la velocidad: el pavimento mojado "
                    "disminuye la adherencia y aumenta el riesgo y el consumo."
                ),
                "science": (
                    "En superficie mojada, una marcha más moderada mejora la adherencia "
                    "y ayuda a controlar el consumo."
                ),
                "savings": 0.08,
            }
        # --- Perfil de pendiente (orden: subida fuerte → suave → bajada fuerte → suave → recta) ---
        if slope > 4:
            return {
                "action": "POWER_BAND",
                "ui_message": (
                    "Subida pronunciada. Aumenta la potencia de forma gradual; "
                    "evita patinar y mantener el acelerador al máximo de forma continua."
                ),
                "science": (
                    "En pendientes marcadas, acelerar de manera progresiva suele "
                    "mantener el consumo más controlado."
                ),
                "savings": 0.12,
            }
        if slope > 2:
            return {
                "action": "CLIMB_MILD",
                "ui_message": (
                    "Subida moderada. Mantén un ritmo estable y evita "
                    "aceleraciones bruscas."
                ),
                "science": (
                    "Un avance constante en rampas suaves reduce picos de consumo."
                ),
                "savings": 0.06,
            }
        if slope < -4:
            return {
                "action": "DESCENT_STEEP",
                "ui_message": (
                    "Bajada pronunciada. Prioriza el frenado motor y el uso de "
                    "marchas adecuadas; aplica el freno de pedal solo de forma breve "
                    "para evitar recalentamiento."
                ),
                "science": (
                    "En largas pendientes descendentes, el frenado motor reparte "
                    "mejor la energía que el freno de pedal sostenido."
                ),
                "savings": 0.10,
            }
        if slope < -2:
            return {
                "action": "DESCENT_MODERATE",
                "ui_message": (
                    "Pendiente descendente. Suelta el acelerador, circula por inercia "
                    "y regula la velocidad con retención o marcha adecuada; "
                    "usa el freno de pedal solo cuando sea necesario."
                ),
                "science": (
                    "Combinar inercia y frenado motor reduce el uso prolongado "
                    "del freno de pedal."
                ),
                "savings": 0.07,
            }
        # Casi recto / llano: recomendación de crucero según velocidad típica del tramo
        v_hint = int(round(speed / 5.0) * 5)
        v_hint = max(50, min(95, v_hint))
        return {
            "action": "CRUISE_OPTIMAL",
            "ui_message": (
                f"Tramo recto. Velocidad recomendada en torno a {v_hint} km/h, "
                f"según límite de vía, carga y condiciones meteorológicas."
            ),
            "science": (
                "En tramos llanos, mantener una velocidad estable reduce el consumo "
                "frente a variaciones frecuentes de ritmo."
            ),
            "savings": 0.03,
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
