import express from "express";
import cors from "cors";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fillzyDir = path.join(__dirname, "..", "fillzy");

const app = express();
/** 3041 por defecto: 3001 suele estar ocupado por otros stacks locales */
const PORT = Number(process.env.PORT) || 3041;

/** Referencia fija del POC: Puebla → Cuautitlán (ruta típica vía Arco Norte). */
const DEFAULT_ROUTE = {
  origin: { name: "Puebla, Pue.", lat: 19.0414, lng: -98.2063 },
  destination: { name: "Cuautitlán, Edo. Mex.", lat: 19.6688, lng: -99.1764 },
};

function haversineKm(a, b) {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const h =
    sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * Simula salida de un motor tipo Power E / NLR:
 * - geometría simplificada (waypoints)
 * - comparativo vs. “política base” (más aceleraciones bruscas, mayor ralentí)
 * - consejos por tramo para el conductor (eco-driving en ruta fija)
 */
function buildRoutePayload({ origin, destination }) {
  const geoDistanceKm = haversineKm(origin, destination);
  /** Factor realista carretera vs. línea recta ~1.15–1.25 para este corredor */
  const roadFactor = 1.18;
  const distanceKm = Math.round(geoDistanceKm * roadFactor * 10) / 10;

  const optimizedSteps = [
    {
      order: 1,
      lat: origin.lat,
      lng: origin.lng,
      label: "Salida / acoplamiento",
      km_from_start: 0,
      advice: {
        action: "neutral",
        headline: "Arranque suave",
        detail:
          "Evita aceleración >80% pedal los primeros 500 m; motor en régimen óptimo reduce picos de consumo.",
      },
    },
    {
      order: 2,
      lat: 19.22,
      lng: -98.38,
      label: "Autopista (tramo plano)",
      km_from_start: Math.round(distanceKm * 0.25),
      advice: {
        action: "maintain_speed",
        headline: "Mantén velocidad de crucero estable",
        detail:
          "En llano, ±3 km/h alrededor del setpoint ahorra más que “pulses” de aceleración y freno.",
      },
    },
    {
      order: 3,
      lat: 19.45,
      lng: -98.72,
      label: "Arco Norte / incorporación",
      km_from_start: Math.round(distanceKm * 0.55),
      advice: {
        action: "ease_throttle",
        headline: "Anticipa curvas e incorporaciones",
        detail:
          "Suelta acelerador 200–300 m antes; recupera inercia sin frenar de más.",
      },
    },
    {
      order: 4,
      lat: 19.58,
      lng: -99.02,
      label: "Aproximación zona urbana",
      km_from_start: Math.round(distanceKm * 0.85),
      advice: {
        action: "reduce_idle",
        headline: "Minimiza ralentí",
        detail:
          "Si la espera >60 s en congestión puntual, valora apagado encendido según política de flota.",
      },
    },
    {
      order: 5,
      lat: destination.lat,
      lng: destination.lng,
      label: "Destino",
      km_from_start: distanceKm,
      advice: {
        action: "neutral",
        headline: "Llegada controlada",
        detail: "Frenado progresivo y uso de retarder según carga alinea consumo y desgaste.",
      },
    },
  ];

  const baselineFuelLPer100km = 38.5;
  const optimizedFuelLPer100km = 33.9;
  const fuelSavedPercent = Math.round(
    ((baselineFuelLPer100km - optimizedFuelLPer100km) / baselineFuelLPer100km) *
      100
  );
  const litersSaved =
    Math.round(
      ((baselineFuelLPer100km - optimizedFuelLPer100km) * distanceKm) / 100
    ) / 10;
  const co2KgPerLiterDiesel = 2.68;
  const co2ReducedKg =
    Math.round(litersSaved * co2KgPerLiterDiesel * 10) / 10;

  const estimatedMinutes = Math.round((distanceKm / 72) * 60);

  return {
    meta: {
      model: "poc-simulated-power-e",
      note:
        "Respuesta simulada para validar integración. Sustituir por llamada real a NLR/Power E.",
    },
    origin: origin.name,
    destination: destination.name,
    origin_coords: { lat: origin.lat, lng: origin.lng },
    destination_coords: { lat: destination.lat, lng: destination.lng },
    distance_km: distanceKm,
    estimated_time_minutes: estimatedMinutes,
    estimated_time_label: `${Math.floor(estimatedMinutes / 60)}h ${estimatedMinutes % 60}min`,
    optimized_steps: optimizedSteps,
    savings: {
      fuel_percent_vs_baseline: `${fuelSavedPercent}%`,
      fuel_liters_saved_trip_estimate: litersSaved,
      co2_reduced_kg: co2ReducedKg,
      baseline_l_per_100km: baselineFuelLPer100km,
      optimized_l_per_100km: optimizedFuelLPer100km,
    },
    /** Resumen para HUD / notificaciones push al conductor */
    driver_coaching_summary: [
      "Prioriza arranques y recuperaciones suaves en toda la ruta fija.",
      "Usa crucero solo en tramos estables; desactívalo en pendiente fuerte o tráfico variable.",
      "Anticipa: suelta gas antes de zonas de frenado probable (peajes, curvas, tráfico).",
    ],
  };
}

app.use(cors({ origin: true }));
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "power-e-poc" });
});

/**
 * GET /api/route-optimization
 * Query opcional: originLat, originLng, destLat, destLng (defaults = Puebla → Cuautitlán)
 */
app.get("/api/route-optimization", (req, res) => {
  const q = req.query;
  const parse = (v, fallback) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };

  const origin = {
    name: "Origen (custom)",
    lat: parse(q.originLat, DEFAULT_ROUTE.origin.lat),
    lng: parse(q.originLng, DEFAULT_ROUTE.origin.lng),
  };
  const destination = {
    name: "Destino (custom)",
    lat: parse(q.destLat, DEFAULT_ROUTE.destination.lat),
    lng: parse(q.destLng, DEFAULT_ROUTE.destination.lng),
  };

  if (
    q.originLat === undefined &&
    q.originLng === undefined &&
    q.destLat === undefined &&
    q.destLng === undefined
  ) {
    origin.name = DEFAULT_ROUTE.origin.name;
    destination.name = DEFAULT_ROUTE.destination.name;
  }

  try {
    const payload = buildRoutePayload({ origin, destination });
    res.json(payload);
  } catch (e) {
    res.status(400).json({ error: String(e.message || e) });
  }
});

app.use(express.static(fillzyDir));

const server = app.listen(PORT, () => {
  console.log(`Power E POC (simulado) http://localhost:${PORT}`);
  console.log(`  GET /api/route-optimization`);
  console.log(`  GET /health`);
  console.log(`  Fillzy + mapa ruta: http://localhost:${PORT}/dashboard.html`);
});

server.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    console.error(
      `Puerto ${PORT} ocupado. Opciones: (1) mata el proceso que lo usa, o (2) otro puerto:\n  PORT=3042 npm start`
    );
    process.exit(1);
  }
  throw err;
});
