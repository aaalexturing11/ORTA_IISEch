import os
import math
import json
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from model_optimizer import HeavyTruckOptimizer

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Power E - POC (Python Version)")

# Permitir CORS para desarrollo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir la carpeta output para ver los mapas de Folium
if not os.path.exists("output"):
    os.makedirs("output")
app.mount("/output", StaticFiles(directory="output"), name="output")

# --- LÓGICA DE NEGOCIO ---

DEFAULT_ROUTE = {
    "origin": {"name": "Puebla, Pue.", "lat": 19.0414, "lng": -98.2063},
    "destination": {"name": "Cuautitlán, Edo. Mex.", "lat": 19.6688, "lng": -99.1764},
}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def build_route_payload(origin_name, o_lat, o_lng, dest_name, d_lat, d_lng):
    dist_geo = haversine_km(o_lat, o_lng, d_lat, d_lng)
    road_factor = 1.18
    distance_km = round(dist_geo * road_factor, 1)

    steps = [
        {"order": 1, "label": "Salida / Acoplamiento", "km": 0, "action": "neutral", "headline": "Arranque suave", "detail": "Evita aceleración >80% pedal los primeros 500m."},
        {"order": 2, "label": "Autopista (Plano)", "km": round(distance_km * 0.25, 1), "action": "maintain_speed", "headline": "Velocidad de crucero", "detail": "Mantén ±3 km/h del setpoint."},
        {"order": 3, "label": "Arco Norte", "km": round(distance_km * 0.55, 1), "action": "ease_throttle", "headline": "Anticipación", "detail": "Suelta acelerador 300m antes de incorporaciones."},
        {"order": 4, "label": "Zona Urbana", "km": round(distance_km * 0.85, 1), "action": "reduce_idle", "headline": "Minimiza Ralentí", "detail": "Si esperas >60s, considera apagar motor."},
        {"order": 5, "label": "Destino", "km": distance_km, "action": "neutral", "headline": "Llegada controlada", "detail": "Uso de retarder según carga."},
    ]

    liters_saved = round((distance_km * (38.5 - 33.9)) / 100, 1)
    
    return {
        "origin": origin_name,
        "destination": dest_name,
        "distance_km": distance_km,
        "estimated_time_label": f"{int(distance_km/72)}h {int((distance_km/72 % 1)*60)}min",
        "savings": {
            "fuel_percent": "12%",
            "co2_reduced_kg": round(liters_saved * 2.68, 1)
        },
        "optimized_steps": steps,
        "driver_coaching_summary": [
            "Prioriza arranques suaves.",
            "Usa crucero solo en tramos estables.",
            "Anticipa zonas de frenado."
        ]
    }

# --- ENDPOINTS ---

@app.get("/api/route-optimization")
async def route_opt(
    originLat: float = DEFAULT_ROUTE["origin"]["lat"],
    originLng: float = DEFAULT_ROUTE["origin"]["lng"],
    destLat: float = DEFAULT_ROUTE["destination"]["lat"],
    destLng: float = DEFAULT_ROUTE["destination"]["lng"]
):
    return build_route_payload("Origen", originLat, originLng, "Destino", destLat, destLng)

@app.get("/api/eco-coaching")
async def eco_coaching():
    # Simulamos telemetría actual
    telemetry = {'speed_kmh': 82.0, 'rpm': 1450}
    segment = {'slope_pct': 3.1, 'congestion_ratio': 1.2, 'wind_speed_ms': 4.0, 'precip_mmph': 0.0}
    
    optimizer = HeavyTruckOptimizer()
    advice = optimizer.get_advice(telemetry, segment)
    
    return {
        "telemetry": telemetry,
        "segment": segment,
        "advice": advice
    }

@app.get("/api/latest-map")
async def get_latest_map():
    import glob
    maps = glob.glob("output/*.html")
    if not maps:
        return {"map_url": None}
    latest_map = max(maps, key=os.path.getctime)
    latest_map_url = latest_map.replace("\\", "/")
    return {"map_url": f"/{latest_map_url}"}

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index_vivi.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    print("\nIniciando Servidor Python en http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
