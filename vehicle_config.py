"""
vehicle_config.py
-----------------
Parámetros físicos y umbrales operativos del HOWO MAX 14L WEICHAI.
Centraliza toda la configuración para que el optimizer sea independiente
de los valores concretos del vehículo.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class HowoMaxConfig:
    """Especificaciones técnicas del HOWO MAX 14L — Solo lectura."""

    # ── Identificación ────────────────────────────────────────────────────────
    model: str = "HOWO MAX 14L WEICHAI"
    engine: str = "WP14T580E52"
    engine_displacement_l: float = 14.0
    engine_hp: int = 580

    # ── Zona de torque máximo ─────────────────────────────────────────────────
    torque_max_nm: int = 2_700          # Nm
    torque_rpm_min: int = 900           # RPM mínima del rango óptimo
    torque_rpm_max: int = 1_400         # RPM máxima del rango óptimo

    # ── Transmisión ───────────────────────────────────────────────────────────
    transmission: str = "HW16-WY"
    gear_count: int = 16

    # ── Masas ─────────────────────────────────────────────────────────────────
    vehicle_weight_kg: int = 9_119      # Peso vehicular en vacío
    gross_combined_weight_kg: int = 74_842  # Peso bruto combinado

    # ── Sistema de frenado ────────────────────────────────────────────────────
    brake_system: str = "Retardador Hidráulico Integrado"

    # ── Umbrales de las reglas de optimización ────────────────────────────────
    stop_ahead_threshold_m: float = 500.0       # Momento A: distancia al evento
    stop_ahead_min_speed_kmh: float = 40.0      # Momento A: velocidad mínima
    torque_flat_grade_pct: float = 1.5          # Momento B: pendiente ≤ esto = "plano"
    speed_aero_threshold_kmh: float = 80.0      # Momento C: velocidad mínima
    headwind_threshold_kmh: float = 30.0        # Momento C: viento en contra mínimo

    # ── Heading estimado de la ruta Puebla → Cuautitlán ──────────────────────
    route_heading_deg: float = 330.0            # Aprox. NNO


# Instancia global lista para importar
VEHICLE = HowoMaxConfig()
