"""
Heavy-truck driving simulator over a route produced by datosDeRuta.py.

For each of N driver profiles, replays the route segment-by-segment and
records realistic telemetry suitable for anomaly detection + clustering.

Physics:
    Power demand at each segment is computed from rolling resistance,
    aerodynamic drag, road grade, and inertia. Fuel rate is derived
    from engine brake-specific fuel consumption (BSFC). Braking dissipates
    energy (no regen on a diesel tractor).

Driver profiles modulate:
    target speed vs. free-flow, anticipation of grades, shifting RPM,
    harsh-event probability, idle tendency, AC usage, payload secured-ness.

Anomalies (sparse, labeled):
    fuel_theft        - sudden tank drop while parked/idle
    overheat          - coolant climbs on long uphill in hot weather
    tire_leak         - slow pressure drop on one trip
    sensor_dropout    - short burst of NaNs in a few channels
    harsh_cluster     - aggressive driving over a few km

Outputs (under output/):
    sim_<route_id>_trips.parquet   one row per (trip_id, segment_id)
    sim_<route_id>_drivers.json    driver + truck + anomaly metadata

Requirements:
    pip install numpy pandas pyarrow

Usage:
    python simulate.py                       # latest route, HOWO MAX 14L Weichai
    python simulate.py 8b78eed1c4b0
    python simulate.py --truck-model 13l-man --trips-per-driver 3 --seed 7
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from model_optimizer import HeavyTruckOptimizer

OUTPUT_DIR = Path("output")

# ----------------------------- physical constants -------------------------- #

G = 9.81                  # m/s^2
AIR_RHO_SEA = 1.225       # kg/m^3 at sea level, 15 C
DIESEL_DENSITY = 0.832    # kg/L
DIESEL_LHV = 42.8e6       # J/kg (lower heating value, informational)
BSFC_G_PER_KWH = 205.0    # modern HD diesel best-island ~195-210
IDLE_FUEL_LPH = 3.2       # liters/hour at idle

# ------------------------------ data models -------------------------------- #


@dataclass
class TruckSpec:
    """HOWO MAX tractor personalized from the uploaded ATRO Motors PDF sheets."""
    model_name: str = "HOWO MAX 14L WEICHAI"
    source_pdf: str = "HOWO MAX 14L WEICHAI.pdf"

    # Dimensions from PDF page 2.
    length_mm: int = 6800
    width_mm: int = 2550
    height_mm: int = 3500
    wheel_base_mm: int = 4000
    rear_overhang_mm: int = 950

    # Weights from PDF page 2.
    tractor_mass_kg: float = 9119.0
    gross_combined_weight_kg: float = 74842.0
    trailer_mass_kg: float = 7000.0
    payload_kg: float | None = None

    # Aerodynamics / rolling resistance are not specified in the PDFs; these
    # remain calibrated simulator assumptions for a 6x4 tractor + semitrailer.
    frontal_area_m2: float = 10.0
    drag_coeff: float = 0.62
    rolling_coeff: float = 0.0068
    drivetrain_eff: float = 0.86

    # Engine from PDF page 3.
    engine_model: str = "WP14T580E52"
    engine_brand: str = "Weichai"
    emission_standard: str = "Euro V"
    displacement_l: float = 14.0
    engine_hp: float = 580.0
    engine_max_kw: float = 580.0 * 0.745699872
    engine_peak_torque_nm: float = 2700.0
    torque_peak_rpm_low: float = 900.0
    torque_peak_rpm_high: float = 1400.0
    engine_max_rpm: float = 1900.0
    engine_idle_rpm: float = 600.0

    # Transmission / driveline from PDF page 3.
    transmission_model: str = "HW16-WY"
    transmission_brand: str = "Sinotruk"
    transmission_type: str = "Automatizada"
    forward_gears: int = 16
    reverse_gears: int = 2
    front_axle_model: str = "VPD71DS"
    front_axle_capacity_kg: float = 7100.0
    rear_axle_model: str = "MCY13BES"
    rear_axle_capacity_kg: float = 25854.0
    rear_axle_ratio_options: tuple[float, float] = (3.7, 4.11)
    rear_axle_ratio: float = 3.7

    # Fuel / DEF, brakes, tires and electrical from PDF page 3.
    fuel_type: str = "Diesel"
    fuel_capacity_l: float = 1060.0       # 860 + 200 L
    urea_capacity_l: float = 45.0
    service_brake: str = "Disco ventilado"
    auxiliary_brake: str = "Retardador hidraulico"
    tire_size: str = "315/80 R22.5"
    n_tires: int = 10                    # PDF says 10 + 1; +1 is spare
    spare_tires: int = 1
    nominal_tire_kpa: float = 758.0      # simulator assumption: ~110 psi
    electrical_voltage_v: float = 24.0
    battery_rating: str = "240A H/2"
    steering_type: str = "BOSCH - Hidraulica"
    clutch_type: str = "Hidraulico con asistencia neumatica"
    front_suspension: str = "Muelles 3 hojas"
    rear_suspension: str = "Suspension de aire 8 bolsas"

    @property
    def gross_mass_kg(self) -> float:
        if self.payload_kg is None:
            return self.gross_combined_weight_kg
        return self.tractor_mass_kg + self.trailer_mass_kg + self.payload_kg

    @property
    def simulated_payload_kg(self) -> float:
        if self.payload_kg is None:
            return max(0.0, self.gross_combined_weight_kg - self.tractor_mass_kg - self.trailer_mass_kg)
        return self.payload_kg


def build_truck_spec(model: str = "14l-weichai") -> TruckSpec:
    """Return a HOWO MAX spec parameterized from the uploaded PDFs."""
    normalized = model.lower().replace("_", "-").strip()
    if normalized in {"14", "14l", "14l-weichai", "howo-max-14l-weichai", "weichai"}:
        return TruckSpec()
    if normalized in {"13", "13l", "13l-man", "howo-max-13l-man", "man"}:
        return TruckSpec(
            model_name="HOWO MAX 13L MAN",
            source_pdf="HOWO MAX 13L MAN.pdf",
            engine_model="MC13 (540HP)",
            engine_brand="Sinotruk",
            displacement_l=13.0,
            engine_hp=540.0,
            engine_max_kw=540.0 * 0.745699872,
            # PDF reports torque as 1844 LBS; in engine datasheets this is lb-ft.
            engine_peak_torque_nm=1844.0 * 1.3558179483314004,
            torque_peak_rpm_low=1100.0,
            torque_peak_rpm_high=1400.0,
        )
    raise ValueError(f"Unknown truck model {model!r}. Use '14l-weichai' or '13l-man'.")


@dataclass
class DriverProfile:
    driver_id: str
    name: str
    experience_years: int
    aggressiveness: float        # 0 calm .. 1 aggressive
    speed_factor: float          # multiplier on segment free-flow speed
    anticipation: float          # 0 reactive .. 1 anticipates grades & turns
    cruise_use: float            # fraction of flat highway under cruise
    shift_rpm: float             # average upshift RPM
    idle_tendency: float         # extra idle minutes per hour driven
    ac_use: float                # 0..1 fraction of trip with AC on
    harsh_event_rate: float      # events per 100 km baseline
    night_factor: float          # speed reduction at night (0..0.2)


@dataclass
class Anomaly:
    trip_id: str
    kind: str
    segment_start: int
    segment_end: int
    detail: dict = field(default_factory=dict)


# ------------------------------ driver pool -------------------------------- #


def build_driver_pool(rng: np.random.Generator) -> list[DriverProfile]:
    """10 distinct profiles spanning the behavior space."""
    base = [
        # name,                     exp, aggr, spd,  antic, cruise, shift, idle, ac,  harsh, night
        ("D01_Veterano_Eco",          22, 0.10, 0.95, 0.90,  0.80,  1300,  0.05, 0.4, 0.3,  0.08),
        ("D02_Veterano_Estandar",     18, 0.25, 1.00, 0.75,  0.70,  1450,  0.08, 0.5, 0.6,  0.06),
        ("D03_Profesional_Promedio",  10, 0.35, 1.02, 0.60,  0.55,  1500,  0.10, 0.6, 0.9,  0.05),
        ("D04_Joven_Agresivo",         3, 0.85, 1.12, 0.20,  0.20,  1750,  0.15, 0.8, 3.5,  0.02),
        ("D05_Cauteloso_Lento",       15, 0.10, 0.88, 0.85,  0.75,  1350,  0.12, 0.5, 0.2,  0.10),
        ("D06_Errante_Inconsistente",  6, 0.55, 1.00, 0.35,  0.30,  1600,  0.20, 0.7, 1.8,  0.04),
        ("D07_Larga_Distancia",       25, 0.20, 0.98, 0.80,  0.90,  1380,  0.06, 0.6, 0.4,  0.07),
        ("D08_Urbano_Frenadas",        8, 0.60, 0.95, 0.25,  0.10,  1650,  0.25, 0.7, 2.5,  0.03),
        ("D09_Nocturno_Rapido",       12, 0.65, 1.08, 0.50,  0.65,  1600,  0.07, 0.3, 1.5,  0.00),
        ("D10_Novato_Conservador",     1, 0.20, 0.92, 0.40,  0.30,  1500,  0.18, 0.6, 0.8,  0.06),
    ]
    drivers = []
    for row in base:
        name, exp, aggr, spd, antic, cruise, shift, idle, ac, harsh, night = row
        drivers.append(
            DriverProfile(
                driver_id=name.split("_")[0],
                name=name,
                experience_years=exp,
                aggressiveness=aggr,
                speed_factor=spd,
                anticipation=antic,
                cruise_use=cruise,
                shift_rpm=shift,
                idle_tendency=idle,
                ac_use=ac,
                harsh_event_rate=harsh,
                night_factor=night,
            )
        )
    return drivers


# ------------------------------ environment -------------------------------- #


def air_density(altitude_m: float, temp_c: float) -> float:
    """Crude ISA-ish correction; good enough for fuel modeling."""
    p = 101325.0 * (1 - 2.25577e-5 * max(altitude_m, 0.0)) ** 5.25588
    t_k = temp_c + 273.15
    return p / (287.05 * t_k)


def sample_weather(rng: np.random.Generator, departure: datetime) -> dict:
    """One weather realization per trip, mildly correlated with hour."""
    hour = departure.hour
    diurnal = 6.0 * math.sin((hour - 9) / 24 * 2 * math.pi)  # peak ~3pm
    base_temp = 15.0 + diurnal + rng.normal(0, 3.0)
    return {
        "base_temp_c": base_temp,
        "wind_speed_ms": float(np.clip(rng.gamma(2.0, 1.5), 0, 18)),
        "wind_dir_deg": float(rng.uniform(0, 360)),
        "precip_mmph": float(max(0.0, rng.gamma(0.4, 1.5) - 0.5)),
        "rain_prob": float(rng.uniform(0, 1)),
    }


def env_for_segment(weather: dict, altitude_m: float, departure: datetime, eta_s: float, rng: np.random.Generator) -> dict:
    # Lapse rate: -6.5 C / km
    temp_c = weather["base_temp_c"] - 0.0065 * max(altitude_m, 0.0) + rng.normal(0, 0.4)
    is_raining = weather["precip_mmph"] > 0.2 and weather["rain_prob"] > 0.5
    road_wet = is_raining or rng.random() < 0.05
    now = departure + timedelta(seconds=eta_s)
    is_night = now.hour < 6 or now.hour >= 20
    return {
        "ambient_temp_c": float(temp_c),
        "wind_speed_ms": float(weather["wind_speed_ms"] + rng.normal(0, 0.5)),
        "wind_dir_deg": float(weather["wind_dir_deg"]),
        "precip_mmph": float(weather["precip_mmph"] if is_raining else 0.0),
        "road_wet": bool(road_wet),
        "is_night": bool(is_night),
        "timestamp": now.isoformat(),
    }


# ------------------------------ fuel & dynamics ---------------------------- #


def power_demand_w(
    mass_kg: float,
    speed_ms: float,
    accel_ms2: float,
    slope_rad: float,
    rho: float,
    cd: float,
    area: float,
    crr: float,
    headwind_ms: float,
) -> float:
    """Mechanical power required at the wheels (W). Negative when downhill braking."""
    v_air = max(speed_ms + headwind_ms, 0.0)
    f_roll = crr * mass_kg * G * math.cos(slope_rad)
    f_aero = 0.5 * rho * cd * area * v_air * v_air
    f_grade = mass_kg * G * math.sin(slope_rad)
    f_inertia = mass_kg * accel_ms2
    return (f_roll + f_aero + f_grade + f_inertia) * speed_ms


def fuel_rate_lph(engine_power_w: float, idle: bool) -> float:
    """Convert engine power demand to L/h using BSFC, with idle as a floor."""
    if idle or engine_power_w <= 0:
        return IDLE_FUEL_LPH
    grams_per_hour = (engine_power_w / 1000.0) * BSFC_G_PER_KWH
    liters_per_hour = grams_per_hour / 1000.0 / DIESEL_DENSITY
    return float(max(IDLE_FUEL_LPH, liters_per_hour))


def estimate_rpm(
    speed_ms: float,
    shift_rpm: float,
    max_rpm: float,
    idle_rpm: float,
    forward_gears: int = 16,
) -> tuple[float, int]:
    """Rough automated HW16-WY gearbox model: pick one of 16 forward gears."""
    if speed_ms < 1.0:
        return idle_rpm, 0
    top_speed_at_shift = 26.4  # m/s = 95 km/h
    top_ratio = shift_rpm / top_speed_at_shift
    gear_ratios = top_ratio * np.geomspace(9.0, 1.0, forward_gears)
    rpms = gear_ratios * speed_ms
    valid = np.where(rpms < shift_rpm * 1.1)[0]
    g = int(valid[0]) if len(valid) else forward_gears - 1
    rpm = float(np.clip(rpms[g], idle_rpm, max_rpm))
    return rpm, g + 1


def headwind_component(wind_speed_ms: float, wind_dir_deg: float, heading_deg: float) -> float:
    """Positive = headwind, negative = tailwind."""
    delta = math.radians(wind_dir_deg - heading_deg)
    return -wind_speed_ms * math.cos(delta)


# ------------------------------ trip simulator ----------------------------- #


def _target_speed(seg: pd.Series, drv: DriverProfile, env: dict, congestion: float = 1.0) -> float:
    base = float(seg["free_flow_speed_kmh"]) * drv.speed_factor
    # Slow down on steep grades (proportional to anticipation)
    slope = float(seg.get("slope_pct") or 0.0)
    if slope > 2.0:
        base *= max(0.6, 1.0 - (slope - 2.0) * 0.04 * (0.5 + drv.anticipation))
    # Wet roads -> compliance-weighted slowdown
    if env["road_wet"]:
        base *= 1.0 - 0.10 * (1.0 - drv.aggressiveness)
    # Night
    if env["is_night"]:
        base *= 1.0 - drv.night_factor
    # Random small variance per driver
    # Traffic congestion effect (skip in test mode to keep speed high for rules)
    if congestion > 1.0 and not getattr(drv, "is_test", False):
        base /= congestion
        
    return float(np.clip(base, 15.0, 110.0))


def simulate_trip(
    route_df: pd.DataFrame,
    truck: TruckSpec,
    drv: DriverProfile,
    departure: datetime,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, list[Anomaly]]:
    n = len(route_df)
    trip_id = f"{drv.driver_id}_{departure.strftime('%Y%m%dT%H%M')}_{uuid.uuid4().hex[:6]}"

    weather = sample_weather(rng, departure)

    # Pre-roll anomalies for this trip (sparse).
    anomalies: list[Anomaly] = []
    inject_overheat = rng.random() < 0.07
    inject_tire_leak = rng.random() < 0.10
    inject_fuel_theft = rng.random() < 0.05
    inject_dropout = rng.random() < 0.15
    inject_harsh_cluster = rng.random() < 0.12

    overheat_seg = rng.integers(int(0.3 * n), int(0.9 * n)) if inject_overheat and n > 50 else -1
    tire_leak_start = rng.integers(0, max(1, n // 2)) if inject_tire_leak else -1
    leaking_tire = int(rng.integers(0, truck.n_tires)) if inject_tire_leak else -1
    fuel_theft_seg = rng.integers(int(0.1 * n), int(0.95 * n)) if inject_fuel_theft and n > 30 else -1
    dropout_start = rng.integers(0, max(1, n - 20)) if inject_dropout else -1
    dropout_len = int(rng.integers(3, 15)) if inject_dropout else 0
    harsh_start = rng.integers(0, max(1, n - 30)) if inject_harsh_cluster and n > 60 else -1
    harsh_len = int(rng.integers(15, 40)) if inject_harsh_cluster else 0

    # State.
    fuel_l = truck.fuel_capacity_l * float(rng.uniform(0.55, 0.95))
    initial_fuel = fuel_l
    coolant_c = 88.0
    oil_c = 95.0
    def_pct = float(rng.uniform(40, 95))
    tire_kpa = np.full(truck.n_tires, truck.nominal_tire_kpa) + rng.normal(0, 8.0, truck.n_tires)
    battery_v = 13.8
    cum_fuel = 0.0
    prev_target_ms = 0.0
    prev_speed_ms = 0.0
    cum_time_s = 0.0

    optimizer = HeavyTruckOptimizer()
    rows = []
    for i, seg in route_df.iterrows():
        # Segment geometry & free-flow.
        length_m = float(seg["length_m"])
        slope_pct = float(seg.get("slope_pct") or 0.0)
        slope_rad = math.atan(slope_pct / 100.0)
        bearing = float(seg.get("bearing_deg") or 0.0)
        alt_mid = float(((seg.get("altitude_start_m") or 0.0) + (seg.get("altitude_end_m") or 0.0)) / 2.0)

        env = env_for_segment(weather, alt_mid, departure, cum_time_s, rng)

        # Initialize factors from data
        current_congestion = float(seg.get("congestion_ratio", 1.0))
        current_wind_speed = env["wind_speed_ms"]
        current_wind_dir = env["wind_dir_deg"]
        current_precip = env["precip_mmph"]
        current_road_wet = env["road_wet"]

        # --- TEST MODE OVERRIDES (to trigger model_optimizer rules) ---
        if getattr(truck, "test_mode", False):
            progress = i / n
            if 0.10 <= progress <= 0.15:
                # Rule 5: Slope > 4
                slope_pct = 6.5
                slope_rad = math.atan(slope_pct / 100.0)
            elif 0.30 <= progress <= 0.35:
                # Rule 2: Congestion > 1.3 (Coasting)
                current_congestion = 1.5
            elif 0.50 <= progress <= 0.55:
                # Rule 1: Congestion > 1.8 (Stop-and-Go)
                current_congestion = 2.1
            elif 0.70 <= progress <= 0.75:
                # Rule 3: Wind > 10
                current_wind_speed = 15.0
                current_wind_dir = bearing # direct headwind
            elif 0.85 <= progress <= 0.90:
                # Rule 4: Precip > 1.5
                current_precip = 3.0
                current_road_wet = True

        # Target & realized speed.
        # Pass current_congestion to speed calculation
        target_kmh = _target_speed(seg, drv, env, congestion=current_congestion)
        target_ms = target_kmh / 3.6
        # Driver noise on the realized speed (does NOT contribute to physical accel).
        noise = rng.normal(0, 1.5 + 4.0 * drv.aggressiveness)
        speed_kmh = float(np.clip(target_kmh + noise, 15.0, 115.0))
        speed_ms = speed_kmh / 3.6

        # Air density & wind.
        rho = air_density(alt_mid, env["ambient_temp_c"])
        head_ms = headwind_component(env["wind_speed_ms"], env["wind_dir_deg"], bearing)

        # Engine power limit: if demanded steady-state power > engine max,
        # the truck physically cannot hold target speed -> solve for v such
        # that power demand equals available wheel power. This is what makes
        # heavy trucks crawl up steep grades regardless of driver intent.
        max_wheel_w = truck.engine_max_kw * 1000.0 * truck.drivetrain_eff
        steady_demand = power_demand_w(
            truck.gross_mass_kg, speed_ms, 0.0, slope_rad,
            rho, truck.drag_coeff, truck.frontal_area_m2, truck.rolling_coeff, head_ms,
        )
        if steady_demand > max_wheel_w:
            # Shrink speed until demand fits available power. Bisection on v.
            lo, hi = 1.0, speed_ms
            for _ in range(25):
                mid = 0.5 * (lo + hi)
                d = power_demand_w(
                    truck.gross_mass_kg, mid, 0.0, slope_rad,
                    rho, truck.drag_coeff, truck.frontal_area_m2, truck.rolling_coeff, head_ms,
                )
                if d > max_wheel_w:
                    hi = mid
                else:
                    lo = mid
            speed_ms = max(2.0, lo)
            speed_kmh = speed_ms * 3.6
            target_ms = speed_ms  # power-limited; that's the new target too

        # Time on segment.
        dt_s = length_m / max(speed_ms, 1.0)

        # Physical acceleration: derived from change in *target* (intent) speed,
        # capped at realistic HD-truck limits. Random noise on realized speed
        # is a measurement / micro-control artifact, not a real acceleration.
        raw_accel = (target_ms - prev_target_ms) / max(dt_s, 1.0)
        accel_ms2 = float(np.clip(raw_accel, -1.2, 0.8))

        # Power & fuel.
        p_wheel = power_demand_w(
            truck.gross_mass_kg, speed_ms, accel_ms2, slope_rad,
            rho, truck.drag_coeff, truck.frontal_area_m2, truck.rolling_coeff, head_ms,
        )
        # Engine power = wheel power / eff when positive; downhill braking -> 0 engine.
        p_engine_w = max(p_wheel, 0.0) / truck.drivetrain_eff
        # AC parasitic load
        if env["ambient_temp_c"] > 22.0 and rng.random() < drv.ac_use:
            p_engine_w += 4500.0
        # Cap at engine max
        p_engine_w = min(p_engine_w, truck.engine_max_kw * 1000.0)

        # Idle injection (driver tendency, scaled per segment time)
        idle_seconds = drv.idle_tendency * dt_s * float(rng.random() < 0.15) * 60.0
        idle_seconds = min(idle_seconds, dt_s * 0.5)
        is_idle_event = idle_seconds > 1.0

        fuel_lph = fuel_rate_lph(p_engine_w, idle=False)
        fuel_used_drive = fuel_lph * (dt_s - idle_seconds) / 3600.0
        fuel_used_idle = IDLE_FUEL_LPH * idle_seconds / 3600.0
        fuel_used = fuel_used_drive + fuel_used_idle
        fuel_l = max(fuel_l - fuel_used, 0.0)
        cum_fuel += fuel_used
        cum_time_s += dt_s + idle_seconds

        # Engine RPM & gear
        rpm, gear = estimate_rpm(speed_ms, drv.shift_rpm, truck.engine_max_rpm, truck.engine_idle_rpm, truck.forward_gears)

        # Engine load = current power / max
        engine_load_pct = float(np.clip(p_engine_w / (truck.engine_max_kw * 10.0), 0.0, 100.0))
        throttle_pct = float(np.clip(engine_load_pct + rng.normal(0, 3), 0, 100))
        # Brake: only when downhill or decelerating
        brake_pct = 0.0
        if accel_ms2 < -0.3 or (slope_pct < -2.0 and speed_kmh > target_kmh * 0.95):
            brake_pct = float(np.clip(-accel_ms2 * 15.0 + max(0.0, -slope_pct - 2.0) * 4.0, 0, 100))

        # Thermal models — first-order toward target.
        target_coolant = 88.0 + max(0.0, engine_load_pct - 30.0) * 0.18 + max(0.0, env["ambient_temp_c"] - 25.0) * 0.2
        coolant_c += (target_coolant - coolant_c) * 0.15 + rng.normal(0, 0.3)
        target_oil = coolant_c + 6.0 + engine_load_pct * 0.05
        oil_c += (target_oil - oil_c) * 0.10 + rng.normal(0, 0.3)
        oil_pressure_kpa = float(np.clip(250.0 + (rpm - 600) * 0.18 + rng.normal(0, 8), 100, 600))
        exhaust_c = float(200.0 + engine_load_pct * 4.5 + rng.normal(0, 12))

        # DEF (AdBlue) consumption ~ 5% of fuel
        def_pct = max(0.0, def_pct - (fuel_used * 0.05) / 50.0 * 100.0 / 100.0)

        # Battery: charged when rpm > 900
        battery_v += (0.02 if rpm > 900 else -0.005) + rng.normal(0, 0.01)
        battery_v = float(np.clip(battery_v, 11.5, 14.6))

        # Tire pressure: temp + slow drift, plus injected leak
        tire_temp = env["ambient_temp_c"] + 18.0 + speed_kmh * 0.15
        tire_kpa += rng.normal(0, 0.4, truck.n_tires)
        if inject_tire_leak and i >= tire_leak_start:
            tire_kpa[leaking_tire] -= 0.6  # ~0.6 kPa per segment
        tire_kpa_avg = float(np.mean(tire_kpa))
        tire_kpa_min = float(np.min(tire_kpa))

        # Harsh events
        baseline_p = drv.harsh_event_rate / 100000.0 * length_m  # per-segment prob
        if inject_harsh_cluster and harsh_start <= i < harsh_start + harsh_len:
            baseline_p *= 6.0
        harsh_brake = bool(rng.random() < baseline_p * (1.0 + max(0.0, -accel_ms2)))
        harsh_accel = bool(rng.random() < baseline_p * (1.0 + max(0.0, accel_ms2)))
        harsh_turn = bool(rng.random() < baseline_p * 0.6)

        # Overheat anomaly: starts at overheat_seg, climbs while loaded
        overheat_flag = False
        if inject_overheat and i >= overheat_seg and engine_load_pct > 50:
            coolant_c += 0.6
            if coolant_c > 105:
                overheat_flag = True

        # Fuel theft: at chosen segment, drop 60-150 L instantly while "parked"
        fuel_theft_event = False
        if inject_fuel_theft and i == fuel_theft_seg:
            stolen = float(rng.uniform(60, 150))
            fuel_l = max(fuel_l - stolen, 0.0)
            fuel_theft_event = True
            anomalies.append(Anomaly(trip_id, "fuel_theft", int(i), int(i), {"liters": stolen}))

        row = {
            "trip_id": trip_id,
            "driver_id": drv.driver_id,
            "segment_id": int(seg["segment_id"]),
            "timestamp": env["timestamp"],
            "lat": float(seg["start_lat"]),
            "lon": float(seg["start_lon"]),
            "altitude_m": alt_mid,
            "slope_pct": slope_pct,
            "bearing_deg": bearing,
            "length_m": length_m,
            "dt_s": float(dt_s + idle_seconds),
            "speed_kmh": speed_kmh,
            "target_speed_kmh": target_kmh,
            "accel_ms2": float(accel_ms2),
            "rpm": rpm,
            "gear": gear,
            "engine_load_pct": engine_load_pct,
            "throttle_pct": throttle_pct,
            "brake_pct": float(brake_pct),
            "engine_power_kw": float(p_engine_w / 1000.0),
            "fuel_rate_lph": fuel_lph,
            "fuel_used_l": float(fuel_used),
            "fuel_level_l": float(fuel_l),
            "cum_fuel_l": float(cum_fuel),
            "coolant_temp_c": float(coolant_c),
            "oil_temp_c": float(oil_c),
            "oil_pressure_kpa": oil_pressure_kpa,
            "exhaust_temp_c": exhaust_c,
            "def_level_pct": float(def_pct),
            "battery_voltage": battery_v,
            "tire_pressure_avg_kpa": tire_kpa_avg,
            "tire_pressure_min_kpa": tire_kpa_min,
            "tire_temp_c": float(tire_temp),
            "ambient_temp_c": env["ambient_temp_c"],
            "wind_speed_ms": current_wind_speed,
            "wind_dir_deg": current_wind_dir,
            "headwind_ms": float(head_ms),
            "precip_mmph": current_precip,
            "road_wet": current_road_wet,
            "is_night": env["is_night"],
            "air_density": float(rho),
            "congestion_ratio": current_congestion,
            "traffic_speed_kmh": float(seg.get("traffic_speed_kmh", speed_kmh)),
            "idle_event": is_idle_event,
            "harsh_brake": harsh_brake,
            "harsh_accel": harsh_accel,
            "harsh_turn": harsh_turn,
            "overheat_flag": overheat_flag,
            "fuel_theft_event": fuel_theft_event,
            # ground-truth labels for evaluation (drop before training!)
            "label_anomaly": (
                overheat_flag
                or fuel_theft_event
                or (inject_tire_leak and i >= tire_leak_start)
                or (inject_dropout and dropout_start <= i < dropout_start + dropout_len)
                or (inject_harsh_cluster and harsh_start <= i < harsh_start + harsh_len)
            ),
        }

        # Sensor dropout: zero out a handful of channels for a stretch
        if inject_dropout and dropout_start <= i < dropout_start + dropout_len:
            for k in ("coolant_temp_c", "oil_temp_c", "oil_pressure_kpa", "exhaust_temp_c"):
                row[k] = float("nan")

        # Generate recommendations
        telemetry_for_opt = {
            'speed_kmh': speed_kmh,
            'rpm': rpm,
        }
        # model_optimizer now expects the second arg to be the segment data dictionary
        advice = optimizer.get_advice(telemetry_for_opt, row)
        
        row["recommendation_action"] = advice["action"]
        row["recommendation_message"] = advice["ui_message"]
        row["recommendation_science"] = advice["science"]
        row["recommendation_savings"] = advice["savings"]

        rows.append(row)
        prev_speed_ms = speed_ms
        prev_target_ms = target_ms

    df = pd.DataFrame(rows)

    # Record long-running anomaly windows
    if inject_overheat and overheat_seg >= 0:
        anomalies.append(Anomaly(trip_id, "overheat", int(overheat_seg), int(n - 1), {}))
    if inject_tire_leak and tire_leak_start >= 0:
        anomalies.append(Anomaly(trip_id, "tire_leak", int(tire_leak_start), int(n - 1), {"tire": leaking_tire}))
    if inject_dropout and dropout_start >= 0:
        anomalies.append(Anomaly(trip_id, "sensor_dropout", int(dropout_start), int(dropout_start + dropout_len - 1), {}))
    if inject_harsh_cluster and harsh_start >= 0:
        anomalies.append(Anomaly(trip_id, "harsh_cluster", int(harsh_start), int(harsh_start + harsh_len - 1), {}))

    df.attrs["trip_id"] = trip_id
    df.attrs["initial_fuel_l"] = initial_fuel
    return df, anomalies


# ------------------------------- driver loop ------------------------------- #


def _load_route(route_id: str | None) -> tuple[dict, pd.DataFrame, str]:
    if route_id is None:
        candidates = sorted(OUTPUT_DIR.glob("route_*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise SystemExit(f"No route_*.json in {OUTPUT_DIR}/")
        route_id = candidates[-1].stem.removeprefix("route_")

    meta_path = OUTPUT_DIR / f"route_{route_id}.json"
    parquet = OUTPUT_DIR / f"route_{route_id}.parquet"
    csv = OUTPUT_DIR / f"route_{route_id}.csv"
    meta = json.loads(meta_path.read_text())
    if parquet.exists():
        df = pd.read_parquet(parquet)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        raise SystemExit(f"No segment data for route {route_id}")
    return meta, df, route_id


def run_simulation(
    route_id: str | None,
    trips_per_driver: int = 1,
    seed: int = 42,
    truck_model: str = "14l-weichai",
    test_mode: bool = False,
) -> tuple[Path, Path]:
    rng = np.random.default_rng(seed)
    route_meta, route_df, route_id = _load_route(route_id)
    drivers = build_driver_pool(rng)
    truck = build_truck_spec(truck_model)
    truck.test_mode = test_mode

    all_trips: list[pd.DataFrame] = []
    all_anomalies: list[Anomaly] = []
    trip_summaries: list[dict] = []

    for drv in drivers:
        for trip_idx in range(trips_per_driver):
            # Vary departure time across trips for diurnal variety
            base_dep = datetime.now(timezone.utc) - timedelta(days=int(rng.integers(0, 60)))
            dep_hour = int(rng.choice([5, 7, 9, 12, 14, 17, 21, 23]))
            departure = base_dep.replace(hour=dep_hour, minute=int(rng.integers(0, 60)),
                                         second=0, microsecond=0)
            
            if test_mode:
                 drv.is_test = True

            df, anoms = simulate_trip(route_df, truck, drv, departure, rng)
            all_trips.append(df)
            all_anomalies.extend(anoms)
            trip_summaries.append({
                "trip_id": df.attrs["trip_id"],
                "driver_id": drv.driver_id,
                "driver_name": drv.name,
                "truck_model": truck.model_name,
                "engine_model": truck.engine_model,
                "departure_iso": departure.isoformat(),
                "initial_fuel_l": df.attrs["initial_fuel_l"],
                "final_fuel_l": float(df["fuel_level_l"].iloc[-1]),
                "total_fuel_l": float(df["fuel_used_l"].sum()),
                "total_distance_km": float(df["length_m"].sum() / 1000.0),
                "total_time_h": float(df["dt_s"].sum() / 3600.0),
                "avg_speed_kmh": float((df["length_m"].sum() / df["dt_s"].sum()) * 3.6),
                "fuel_efficiency_l_per_100km": float(
                    df["fuel_used_l"].sum() / (df["length_m"].sum() / 1000.0) * 100.0
                ),
                "n_harsh_brake": int(df["harsh_brake"].sum()),
                "n_harsh_accel": int(df["harsh_accel"].sum()),
                "n_harsh_turn": int(df["harsh_turn"].sum()),
                "anomalies": [a.kind for a in anoms if a.trip_id == df.attrs["trip_id"]],
            })

    big = pd.concat(all_trips, ignore_index=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"sim_{route_id}_trips.parquet"
    json_path = OUTPUT_DIR / f"sim_{route_id}_drivers.json"
    try:
        big.to_parquet(parquet_path, index=False)
    except (ImportError, ValueError):
        parquet_path = parquet_path.with_suffix(".csv")
        big.to_csv(parquet_path, index=False)

    payload = {
        "route_id": route_id,
        "route_meta": route_meta,
        "truck": asdict(truck),
        "drivers": [asdict(d) for d in drivers],
        "trips": trip_summaries,
        "anomalies": [asdict(a) for a in all_anomalies],
        "seed": seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))

    print(f"Wrote {parquet_path}  ({len(big):,} rows)")
    print(f"Wrote {json_path}")
    print()
    print("Per-trip summary (L/100km):")
    summary = (
        pd.DataFrame(trip_summaries)
        .groupby("driver_name")["fuel_efficiency_l_per_100km"]
        .agg(["mean", "min", "max"])
        .round(2)
        .sort_values("mean")
    )
    print(summary.to_string())
    
    if test_mode:
        analyze_savings_per_km(big)
        
    return parquet_path, json_path


# --------------------------------- entry ----------------------------------- #


def analyze_savings_per_km(df: pd.DataFrame):
    """
    SKELETON: Calculates estimated fuel savings by following coaching 
    vs. base consumption in adverse conditions.
    """
    print("\n" + "="*50)
    print("ANALYTICS: POTENTIAL SAVINGS BY CONDITION")
    print("="*50)
    
    # 1. Identify segments with coaching advice (where follower would save)
    coached = df[df['recommendation_action'] != 'KEEP'].copy()
    
    if coached.empty:
        print("No coaching events recorded in this trip.")
        return

    # 2. Group by action type and calculate potential liters saved
    # Formula: (segment_fuel) * (savings_pct)
    coached['liters_saved'] = coached['fuel_used_l'] * coached['recommendation_savings']
    
    summary = coached.groupby('recommendation_action').agg({
        'length_m': 'sum',
        'fuel_used_l': 'sum',
        'liters_saved': 'sum'
    })
    
    summary['km'] = summary['length_m'] / 1000.0
    summary['savings_per_km'] = summary['liters_saved'] / summary['km']
    
    print(summary[['km', 'fuel_used_l', 'liters_saved', 'savings_per_km']])
    print("="*50 + "\n")


def _cli() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("route_id", nargs="?", default=None, help="Route id (default: latest)")
    p.add_argument(
        "--truck-model",
        default="14l-weichai",
        choices=["14l-weichai", "13l-man"],
        help="HOWO MAX model from the uploaded PDFs (default: 14l-weichai)",
    )
    p.add_argument("--trips-per-driver", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--test-mode", action="store_true", help="Force segments to trigger all optimizer rules")
    args = p.parse_args()
    
    run_simulation(
        args.route_id,
        trips_per_driver=args.trips_per_driver,
        seed=args.seed,
        truck_model=args.truck_model,
        test_mode=args.test_mode,
    )

if __name__ == "__main__":
    _cli()
