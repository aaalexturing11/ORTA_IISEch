# Fleet Telemetry Dashboard

Business / management oriented dashboard fueled by simulated heavy-truck
telemetry over a route segmented every 200 m.

## Data sources

The dashboard auto-loads the **latest** simulation in `output/`:

* `output/route_<id>.parquet` – per-segment route topography (from `datosDeRuta.py`)
* `output/sim_<id>_trips.parquet` – per-segment telemetry per trip (from `simulate2.py`)
* `output/sim_<id>_drivers.json` – run metadata (drivers, truck spec, anomalies)

Re-run the upstream tools any time and refresh the page — the cache only
covers a single process; restart `uvicorn` after generating new outputs.

## Install

```bash
pip install -r dashboard/requirements.txt
```

## Run

```bash
python -m uvicorn dashboard.app:app --reload --port 8000
```

Open http://localhost:8000/

## What it shows

| Section | Metrics | Source endpoint |
|---|---|---|
| Executive KPIs | L/100km, MXN/km, on-time %, utilization, CO₂/km, totals | `/api/overview` |
| Route Cost Map | Color-coded segments by **normalized cost** (fuel + time penalty) + top hotspots | `/api/route/map`, `/api/route/segments` |
| Driver Performance | Composite score (45% fuel · 30% safety · 25% on-time), L/100km, harsh events, idle | `/api/drivers` |
| Truck Comparison | Per-model L/100km, cost/km, cumulative fuel along the route | `/api/trucks`, `/api/fuel-trend` |
| Energy vs Slope | Scatter of fuel/km vs grade + anomaly counts | `/api/route/segments`, `/api/anomalies` |
| Idle & Waste | Idle hours, fuel burned, MXN wasted per driver | `/api/idle` |

## Tunable assumptions

Edit constants at the top of `dashboard/app.py`:

* `DIESEL_PRICE_MXN_PER_L` – fuel price for cost calculations
* `CO2_KG_PER_L_DIESEL` – emissions factor
* `ON_TIME_TOLERANCE_PCT` – delay tolerance for on-time %
* `TIME_VALUE_MXN_PER_H` (inside `route_segments`) – cost of a lost hour
