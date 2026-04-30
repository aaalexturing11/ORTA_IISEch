const state = {
  routes: [],
  route: null,
  truck: null,
  since: null,
  mapInstance: null,
  coachingMap: null,
  activeTab: "dash",
  hotspotMarker: null,
  driverChart: null,
  anomChart: null,
  clusterChart: null,
};

const fmt = (n, d = 1) => (n == null || Number.isNaN(+n) ? "—" : Number(n).toFixed(d));
const fmtInt = n => (n == null ? "—" : Math.round(n).toLocaleString());

function qs(extra = {}) {
  const p = new URLSearchParams();
  if (state.route) p.set("route", state.route);
  if (state.truck) p.set("truck", state.truck);
  if (state.since) p.set("since", state.since);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function api(path, extra) {
  const r = await fetch(`/api${path}${qs(extra)}`);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

// ---------------- Selector setup ----------------
async function loadRoutes() {
  const data = await fetch("/api/routes").then(r => r.json());
  state.routes = data.routes || [];
  const sel = document.getElementById("route-select");
  sel.innerHTML = "";
  for (const r of state.routes) {
    const opt = document.createElement("option");
    opt.value = r.slug;
    opt.textContent = `${r.origin} → ${r.destination} (${fmt(r.distance_km, 0)} km)`;
    sel.appendChild(opt);
  }
  if (state.routes.length) {
    state.route = state.routes[0].slug;
    sel.value = state.route;
    populateTrucks();
  }
}

function populateTrucks() {
  const route = state.routes.find(r => r.slug === state.route);
  const sel = document.getElementById("truck-select");
  sel.innerHTML = "";
  if (!route) return;
  for (const t of route.trucks) {
    const opt = document.createElement("option");
    opt.value = t.slug;
    opt.textContent = `${t.label} (${t.n_trips} viajes)`;
    sel.appendChild(opt);
  }
  if (route.trucks.length) {
    state.truck = route.trucks[0].slug;
    sel.value = state.truck;
    const earliest = route.trucks.find(t => t.slug === state.truck)?.earliest;
    if (earliest) document.getElementById("since-input").min = earliest.slice(0, 10);
  } else {
    state.truck = null;
  }
}

function bindControls() {
  document.getElementById("route-select").addEventListener("change", e => {
    state.route = e.target.value;
    populateTrucks();
  });
  document.getElementById("truck-select").addEventListener("change", e => {
    state.truck = e.target.value;
  });
  document.getElementById("since-input").addEventListener("change", e => {
    state.since = e.target.value || null;
  });
  document.getElementById("apply-btn").addEventListener("click", renderAll);
  bindTabs();
}

function bindTabs() {
  document.querySelectorAll(".app-tab").forEach(btn => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  });
}

function setActiveTab(tab) {
  state.activeTab = tab;
  const dash = document.getElementById("panel-dash");
  const coach = document.getElementById("panel-coach");
  document.querySelectorAll(".app-tab").forEach(b => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (tab === "dash") {
    dash.classList.remove("hidden");
    coach.classList.add("hidden");
    coach.setAttribute("aria-hidden", "true");
    dash.removeAttribute("aria-hidden");
    requestAnimationFrame(() => state.mapInstance?.invalidateSize?.());
  } else {
    coach.classList.remove("hidden");
    dash.classList.add("hidden");
    coach.setAttribute("aria-hidden", "false");
    dash.setAttribute("aria-hidden", "true");
    renderCoachingMap().then(() => {
      requestAnimationFrame(() => state.coachingMap?.invalidateSize?.());
    });
  }
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function coachingPopupHtml(s) {
  let h = `<b>Segmento ${s.seg_idx}</b><br>`;
  h += `Distancia: ${fmtInt(s.length_m)} m<br>`;
  h += `Pendiente: ${fmt(s.slope_pct, 2)}%<br>`;
  if (s.altitude_start_m != null && s.altitude_end_m != null) {
    h += `Altura: ${fmt(s.altitude_start_m, 1)} → ${fmt(s.altitude_end_m, 1)} m<br>`;
  }
  if (s.eta_offset_min != null) {
    h += `ETA: +${fmt(s.eta_offset_min, 1)} min<br>`;
  }
  h += `<b>Clima:</b> ${fmt(s.ambient_temp_c, 1)}°C | Viento: ${fmt(s.wind_speed_ms, 1)} m/s | Lluvia: ${fmt(s.precip_mmph, 1)} mm/h<br>`;
  const act = String(s.recommendation_action || "KEEP").toUpperCase();
  if (act === "KEEP") {
    h += `<span style="opacity:0.75">${escapeHtml(s.recommendation_message)}</span>`;
  } else {
    h += `<b>Recomendación:</b> ${escapeHtml(s.recommendation_message)}<br>`;
    if (act !== "CRUISE_OPTIMAL" && s.recommendation_science) {
      h += `<i>Base científica:</i> ${escapeHtml(s.recommendation_science)}<br>`;
    }
    h += `Ahorro est.: ${Math.round((s.recommendation_savings || 0) * 100)}% | ${fmt(s.speed_kmh, 1)} km/h | ${fmtInt(s.rpm)} RPM`;
  }
  return h;
}

async function renderCoachingMap() {
  const legend = document.getElementById("coaching-legend");
  if (!state.route || !state.truck) {
    if (legend) legend.textContent = "Selecciona ruta y camión.";
    return;
  }
  if (state.coachingMap) {
    state.coachingMap.remove();
    state.coachingMap = null;
  }
  let data;
  try {
    data = await api("/route/coaching");
  } catch (e) {
    console.error(e);
    if (legend) legend.innerHTML = "<b>Error</b> al cargar coaching (¿hay simulaciones para esta ruta?).";
    return;
  }
  const leg = data.legend || { label: "Pendiente (%)", min: -8, max: 8 };
  if (data.empty || !(data.segments && data.segments.length)) {
    if (legend) {
      legend.innerHTML = "<b>Sin geometría</b> para esta ruta o faltan columnas en <code>route.parquet</code>.";
    }
    return;
  }
  if (legend) {
    const km = data.total_distance_km != null ? `${fmt(data.total_distance_km, 1)} km` : "—";
    const n = data.n_segments != null ? data.n_segments : data.segments.length;
    legend.innerHTML =
      `<b>${escapeHtml(leg.label)}</b><br>` +
      `${fmt(leg.min, 1)} → ${fmt(leg.max, 1)}<br>` +
      `Ruta: ${escapeHtml(data.origin_query || "")} → ${escapeHtml(data.destination_query || "")}<br>` +
      `${km} · ${n} tramos<br>` +
      `<span style="opacity:0.8;font-size:11px">Línea gris = ruta completa. Colores = tramos más “fuertes” (pendiente, tráfico, clima, etc.) con zoom lejano; al acercarte se dibujan más tramos y marcadores. Popup en cada tramo visible.</span>`;
  }

  const map = L.map("map-coaching", { zoomControl: true });
  state.coachingMap = map;

  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
    maxZoom: 19,
  });
  const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    attribution: 'Map data: © <a href="https://openstreetmap.org">OSM</a> contributors, <a href="https://opentopomap.org">OpenTopoMap</a>',
    maxZoom: 17,
  });
  topo.addTo(map);
  L.control.layers({ "Mapa de calles (OpenStreetMap)": osm, "Mapa topográfico (OpenTopoMap)": topo }, {}).addTo(map);

  const segmentsSorted = [...data.segments].sort((a, b) => a.seg_idx - b.seg_idx);
  const routeCoords = [];
  for (const s of segmentsSorted) {
    if (!routeCoords.length) routeCoords.push([s.start_lat, s.start_lon]);
    routeCoords.push([s.end_lat, s.end_lon]);
  }
  L.polyline(routeCoords, { color: "#64748b", weight: 2.5, opacity: 0.4, interactive: false }).addTo(map);

  function segmentSignificance(s) {
    let sc = Math.abs(+s.slope_pct || 0) * 2.4;
    const al = s.alerts || [];
    if (al.includes("traffic")) sc += 48;
    if (al.includes("steep_slope")) sc += 38;
    if (s.show_weather_marker) sc += 20;
    const ra = String(s.recommendation_action || "").toUpperCase();
    if (ra && ra !== "KEEP" && ra !== "CRUISE_OPTIMAL") sc += 14;
    const c = +s.congestion_ratio || 1;
    if (c > 1.15) sc += Math.min(30, (c - 1.15) * 40);
    sc += Math.min(12, (+s.weight || 4) * 0.9);
    return sc;
  }

  function segmentPolylineCap(z) {
    if (z <= 6) return 50;
    if (z <= 7) return 110;
    if (z <= 8) return 240;
    if (z <= 9) return 520;
    if (z <= 10) return 1000;
    if (z <= 11) return 1700;
    if (z <= 12) return 2600;
    return 999999;
  }

  const layerBySegIdx = new Map();
  const segmentPolylineEntries = [];
  const bounds = [];
  for (const s of data.segments) {
    const line = L.polyline(
      [[s.start_lat, s.start_lon], [s.end_lat, s.end_lon]],
      { color: s.color || "#3388ff", weight: s.weight || 4, opacity: 0.9 }
    ).bindPopup(coachingPopupHtml(s));
    layerBySegIdx.set(s.seg_idx, line);
    segmentPolylineEntries.push({ seg_idx: s.seg_idx, score: segmentSignificance(s) });
    bounds.push([s.start_lat, s.start_lon], [s.end_lat, s.end_lon]);
  }

  const segmentsDetailGroup = L.layerGroup().addTo(map);

  /** Puntuación para priorizar incidentes visibles con zoom lejano. */
  function trafficScore(s) {
    const cong = +s.congestion_ratio || 1;
    return 95 + Math.min(45, Math.max(0, cong - 1) * 28);
  }
  function slopeScore(s) {
    const g = Math.abs(+s.slope_pct || 0);
    return 62 + Math.min(48, g * 5.5);
  }
  function weatherScore(s) {
    const p = +s.precip_mmph || 0;
    const w = +s.wind_speed_ms || 0;
    return 22 + Math.min(55, p * 16 + w * 3.2);
  }

  function incidentVisibleLimit(z) {
    if (z <= 7) return 8;
    if (z <= 9) return 14;
    if (z <= 11) return 32;
    if (z <= 13) return 70;
    return 99999;
  }

  function buildIncidentLayers(segments) {
    const items = [];
    for (const s of segments) {
      const lat = (+s.start_lat + +s.end_lat) / 2;
      const lon = (+s.start_lon + +s.end_lon) / 2;
      const alerts = s.alerts || [];
      if (alerts.includes("traffic")) {
        const sc = trafficScore(s);
        const m = L.circleMarker([lat, lon], {
          radius: 6,
          color: "#ef4444",
          weight: 2,
          fillColor: "#ef4444",
          fillOpacity: 0.78,
        }).bindTooltip(`Tráfico (seg. ${s.seg_idx}, score ${sc.toFixed(0)})`, { sticky: true });
        items.push({ score: sc, layer: m });
      }
      if (alerts.includes("steep_slope")) {
        const sc = slopeScore(s);
        const m = L.circleMarker([lat, lon], {
          radius: 6,
          color: "#111827",
          weight: 2,
          fillColor: "#111827",
          fillOpacity: 0.78,
        }).bindTooltip(`Pendiente fuerte (seg. ${s.seg_idx}, ${fmt(s.slope_pct, 1)}%)`, { sticky: true });
        items.push({ score: sc, layer: m });
      }
      if (s.show_weather_marker) {
        const sc = weatherScore(s);
        const rainy = (+s.precip_mmph || 0) > 0.5;
        const icon = L.divIcon({
          className: "wx-icon",
          html: rainy ? "🌧" : "🌬",
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        });
        const m = L.marker([lat, lon], { icon }).bindTooltip(
          rainy ? `Lluvia: ${fmt(s.precip_mmph, 1)} mm/h` : `Viento: ${fmt(s.wind_speed_ms, 1)} m/s`,
          { sticky: true }
        );
        items.push({ score: sc, layer: m });
      }
    }
    items.sort((a, b) => b.score - a.score);
    return items;
  }

  const incidentEntries = buildIncidentLayers(data.segments);
  const incidentsGroup = L.layerGroup().addTo(map);

  function syncCoachingMapDensity() {
    const z = map.getZoom();

    segmentsDetailGroup.clearLayers();
    const polyLim = segmentPolylineCap(z);
    const sortedSeg = [...segmentPolylineEntries].sort((a, b) => b.score - a.score);
    const keepSeg = new Set(sortedSeg.slice(0, Math.min(polyLim, sortedSeg.length)).map(e => e.seg_idx));
    for (const s of segmentsSorted) {
      if (keepSeg.has(s.seg_idx)) {
        segmentsDetailGroup.addLayer(layerBySegIdx.get(s.seg_idx));
      }
    }

    const incLim = incidentVisibleLimit(z);
    incidentsGroup.clearLayers();
    for (let i = 0; i < incidentEntries.length && i < incLim; i++) {
      incidentsGroup.addLayer(incidentEntries[i].layer);
    }
  }

  map.on("zoomend", syncCoachingMapDensity);

  if (data.origin) {
    L.marker([data.origin.lat, data.origin.lon], { title: data.origin.label })
      .addTo(map)
      .bindPopup(`Origen: ${escapeHtml(data.origin.label || "")}`);
  }
  if (data.destination) {
    L.marker([data.destination.lat, data.destination.lon], { title: data.destination.label })
      .addTo(map)
      .bindPopup(`Destino: ${escapeHtml(data.destination.label || "")}`);
  }

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [24, 24] });
  }
  map.whenReady(() => {
    requestAnimationFrame(syncCoachingMapDensity);
  });
}

// ---------------- Renderers ----------------
async function renderOverview() {
  const k = await api("/kpis");
  const route = state.routes.find(r => r.slug === state.route);
  document.getElementById("subtitle").textContent =
    route ? `${route.origin} → ${route.destination} · ${fmt(route.distance_km, 0)} km · ${k.n_trips ?? 0} viajes` : "";
  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = "";
  if (k.empty) {
    grid.innerHTML = `<div class="kpi"><span class="kpi-label">Sin viajes para esta selección</span></div>`;
    return;
  }
  const tiles = [
    { label: "Eficiencia de combustible", value: fmt(k.fuel_l_per_100km, 1), unit: "L/100 km" },
    { label: "Aprovechamiento de carga", value: fmt(k.utilization_pct, 1), unit: "%" },
    { label: "Emisiones de CO₂", value: fmt(k.co2_kg_per_km, 2), unit: "kg/km" },
    { label: "Velocidad promedio", value: fmt(k.avg_speed_kph, 1), unit: "km/h" },
  ];
  for (const t of tiles) {
    const el = document.createElement("div");
    el.className = "kpi";
    el.innerHTML = `<span class="kpi-label">${t.label}</span>
      <span class="kpi-value">${t.value} <small>${t.unit}</small></span>`;
    grid.appendChild(el);
  }
}

function colorForFuel(v, min, max) {
  if (max <= min) return "#3aa856";
  const t = (v - min) / (max - min);
  // green -> amber -> red
  const r = Math.round(74 + t * (248 - 74));
  const g = Math.round(222 - t * (222 - 113));
  const b = Math.round(128 - t * (128 - 113));
  return `rgb(${r},${g},${b})`;
}

async function renderMap() {
  const m = await api("/route/map");
  const segments = m.segments || [];
  if (state.mapInstance) {
    state.mapInstance.remove();
    state.mapInstance = null;
    state.hotspotMarker = null;
  }
  if (!segments.length) return;
  const lats = segments.map(s => s.lat);
  const lons = segments.map(s => s.lon);
  const map = L.map("map", { zoomControl: true });
  state.mapInstance = map;
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap", maxZoom: 18,
  }).addTo(map);
  const fuels = segments.map(s => s.fuel_per_km_l).filter(Boolean);
  const fmin = fuels.length ? Math.min(...fuels) : 0;
  const fmax = fuels.length ? Math.max(...fuels) : 1;
  for (let i = 0; i < segments.length - 1; i++) {
    const a = segments[i], b = segments[i + 1];
    L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
      color: colorForFuel(a.fuel_per_km_l, fmin, fmax), weight: 4, opacity: 0.9,
    }).addTo(map);
  }
  if (m.origin) L.marker([m.origin.lat, m.origin.lon]).addTo(map).bindPopup("Origen");
  if (m.destination) L.marker([m.destination.lat, m.destination.lon]).addTo(map).bindPopup("Destino");
  map.fitBounds([[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]]);

  const seg = await api("/route/segments", { top: 12 });
  const tbody = document.getElementById("hotspots-body");
  tbody.innerHTML = "";
  for (const h of seg.hotspots || []) {
    const tr = document.createElement("tr");
    tr.className = "clickable";
    tr.innerHTML = `<td>${h.seg_idx}</td><td>${fmt(h.fuel_per_km_l, 3)}</td>
      <td>${fmt(h.avg_speed, 1)}</td><td>${fmt(h.slope_pct, 2)}</td>`;
    tr.addEventListener("click", () => focusHotspot(h));
    tbody.appendChild(tr);
  }
}

function focusHotspot(h) {
  const map = state.mapInstance;
  if (!map) return;
  map.flyTo([h.lat_mid, h.lon_mid], 14, { duration: 0.6 });
  if (state.hotspotMarker) {
    map.removeLayer(state.hotspotMarker);
    state.hotspotMarker = null;
  }
  const marker = L.circleMarker([h.lat_mid, h.lon_mid], {
    radius: 9,
    color: "#f87171",
    weight: 2,
    fillColor: "#f87171",
    fillOpacity: 0.45,
  }).addTo(map);
  marker.bindPopup(
    `<b>Tramo ${h.seg_idx}</b><br>${fmt(h.fuel_per_km_l, 3)} L/km` +
    `<br>${fmt(h.avg_speed, 1)} km/h · pendiente ${fmt(h.slope_pct, 2)}%`
  ).openPopup();
  state.hotspotMarker = marker;
}

async function renderDrivers() {
  const d = await api("/drivers");
  const drivers = d.drivers || [];
  document.getElementById("driver-baselines").textContent =
    `Referencias del histórico: mejor consumo ${fmt(d.baseline_fuel_l_per_100km, 1)} L/100 km · menor ralentí ${fmt(d.baseline_idle_h_per_100km, 3)} h/100 km`;
  const tbody = document.getElementById("drivers-body");
  tbody.innerHTML = "";
  for (const r of drivers) {
    const tr = document.createElement("tr");
    const pct = Math.max(0, Math.min(100, r.score || 0));
    tr.innerHTML = `<td><span class="rank">${r.rank}</span></td>
      <td>${r.driver_name}</td>
      <td><div class="score-cell"><div class="bar"><span style="width:${pct}%"></span></div><span class="num">${fmt(r.score, 0)}</span></div></td>
      <td>${fmt(r.fuel_l_per_100km, 1)}</td>
      <td>${fmt(r.excess_fuel_l, 1)}</td>
      <td>${fmt(r.idle_h, 2)}</td>
      <td>${fmt(r.excess_idle_h, 2)}</td>`;
    tbody.appendChild(tr);
  }

  const ctx = document.getElementById("driver-chart");
  if (state.driverChart) state.driverChart.destroy();
  // Sort ascending so the best driver is at the top of a horizontal chart
  const sorted = [...drivers].sort((a, b) => a.score - b.score);
  const colors = sorted.map(r => colorForFuel(100 - (r.score || 0), 0, 100));
  state.driverChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: sorted.map(r => r.driver_name),
      datasets: [{
        label: "Puntaje general",
        data: sorted.map(r => r.score),
        backgroundColor: colors,
        borderColor: colors,
        borderWidth: 0,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => `${fmt(c.parsed.x, 1)} / 100` } },
      },
      scales: {
        x: {
          beginAtZero: true, max: 100,
          grid: { color: "rgba(255,255,255,0.06)" },
          ticks: { color: "#8a93a8" },
        },
        y: {
          grid: { display: false },
          ticks: { color: "#e6e9f2", font: { size: 11 } },
        },
      },
    },
  });
}

async function renderTrucks() {
  const t = await api("/trucks");
  const tbody = document.getElementById("trucks-body");
  tbody.innerHTML = "";
  const truck = t.truck || {};
  const stats = t.stats || {};
  const rows = [
    ["Modelo", truck.model_name],
    ["Motor", truck.engine_model],
    ["Peso bruto combinado (kg)", truck.gross_combined_weight_kg],
    ["Masa del tractor (kg)", truck.tractor_mass_kg],
    ["Masa del remolque (kg)", truck.trailer_mass_kg],
    ["Viajes registrados", stats.n_trips],
    ["Kilómetros recorridos", fmt(stats.distance_km, 0)],
    ["Consumo promedio (L/100 km)", fmt(stats.fuel_l_per_100km, 1)],
    ["Velocidad promedio (km/h)", fmt(stats.avg_speed_kph, 1)],
    ["Frenadas / aceleraciones bruscas", `${fmtInt(stats.harsh_brakes)} / ${fmtInt(stats.harsh_accels)}`],
  ];
  for (const [k, v] of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${k}</td><td>${v ?? "—"}</td>`;
    tbody.appendChild(tr);
  }
}

async function renderIdleAndAnomalies() {
  const [idle, an] = await Promise.all([api("/idle"), api("/anomalies")]);
  document.getElementById("idle-baseline").textContent =
    `Ralentí de referencia: ${fmt(idle.baseline_idle_h_per_100km, 3)} h/100 km · ralentí total: ${fmt(idle.total_idle_h, 1)} h`;
  const it = document.getElementById("idle-body"); it.innerHTML = "";
  for (const r of idle.by_driver || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.driver_id}</td><td>${fmt(r.idle_h, 2)}</td>
      <td>${fmt(r.idle_h_per_100km, 3)}</td><td>${fmt(r.excess_idle_h, 2)}</td>`;
    it.appendChild(tr);
  }
  renderAnomalies(an);
}

const KIND_LABELS = {
  fuel_theft: "Robo de combustible",
  sensor_dropout: "Falla de sensor",
  overheat: "Sobrecalentamiento",
  tire_leak: "Fuga en llanta",
  harsh_cluster: "Maniobras bruscas seguidas",
};
const KIND_COLORS = {
  fuel_theft: "#f87171",
  sensor_dropout: "#fbbf24",
  overheat: "#fb923c",
  tire_leak: "#a78bfa",
  harsh_cluster: "#4ea1ff",
};
const kindLabel = k => KIND_LABELS[k] || k;
const kindColor = k => KIND_COLORS[k] || "#8a93a8";

function renderAnomalies(an) {
  const byKind = an.by_kind || [];
  const total = an.total || byKind.reduce((s, r) => s + r.count, 0);
  document.getElementById("anom-summary").textContent =
    total ? `${total} eventos en ${byKind.length} tipos` : "Sin anomalías para esta selección.";

  const ctx = document.getElementById("anom-chart");
  if (state.anomChart) state.anomChart.destroy();
  state.anomChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: byKind.map(r => kindLabel(r.kind)),
      datasets: [{
        data: byKind.map(r => r.count),
        backgroundColor: byKind.map(r => kindColor(r.kind)),
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, ticks: { color: "#8a93a8", precision: 0 },
             grid: { color: "rgba(255,255,255,0.06)" } },
        y: { ticks: { color: "#e6e9f2", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });

  const kinds = an.kinds || byKind.map(r => r.kind);
  const head = document.getElementById("anom-driver-head");
  head.innerHTML = `<th>Conductor</th>` + kinds.map(k =>
    `<th title="${k}">${kindLabel(k)}</th>`).join("") + `<th>Total</th>`;
  const body = document.getElementById("anom-driver-body");
  body.innerHTML = "";
  for (const row of an.by_driver || []) {
    const tr = document.createElement("tr");
    const cells = kinds.map(k => `<td>${fmtInt(row[k] || 0)}</td>`).join("");
    tr.innerHTML = `<td>${row.driver_name}</td>${cells}<td><b>${fmtInt(row.total)}</b></td>`;
    body.appendChild(tr);
  }

  const rb = document.getElementById("anom-recent-body");
  const kindSel = document.getElementById("anom-filter-kind");
  const drvSel = document.getElementById("anom-filter-driver");
  const countEl = document.getElementById("anom-recent-count");
  const recent = an.recent || [];

  // Populate filter options (preserve current selection if still valid)
  const prevKind = kindSel.value;
  const prevDrv = drvSel.value;
  const kindsAll = an.kinds || [...new Set(recent.map(r => r.kind))];
  const drivers = [...new Set(recent.map(r => r.driver_name).filter(Boolean))].sort();
  kindSel.innerHTML = `<option value="">Todos los tipos</option>` +
    kindsAll.map(k => `<option value="${k}">${kindLabel(k)}</option>`).join("");
  drvSel.innerHTML = `<option value="">Todos los conductores</option>` +
    drivers.map(d => `<option value="${d}">${d}</option>`).join("");
  if (kindsAll.includes(prevKind)) kindSel.value = prevKind;
  if (drivers.includes(prevDrv)) drvSel.value = prevDrv;

  const renderRows = () => {
    const fk = kindSel.value, fd = drvSel.value;
    const filtered = recent.filter(r =>
      (!fk || r.kind === fk) && (!fd || r.driver_name === fd));
    rb.innerHTML = "";
    for (const r of filtered) {
      const when = (r.departure_iso || "").slice(0, 16).replace("T", " ");
      const seg = r.segment_start === r.segment_end
        ? `${r.segment_start}` : `${r.segment_start}\u2013${r.segment_end}`;
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${when}</td><td>${r.driver_name || ""}</td>
        <td><span class="kind-pill" style="--c:${kindColor(r.kind)}">${kindLabel(r.kind)}</span></td>
        <td>${seg}</td><td class="muted">${r.detail || ""}</td>`;
      rb.appendChild(tr);
    }
    countEl.textContent = `${filtered.length} / ${recent.length}`;
  };
  kindSel.onchange = renderRows;
  drvSel.onchange = renderRows;
  renderRows();
}

// ---------- Driving styles (UMAP clusters) ----------

const CLUSTER_PALETTE = [
  "#4ea1ff", "#f87171", "#fbbf24", "#34d399", "#a78bfa",
  "#fb923c", "#22d3ee", "#f472b6", "#94a3b8", "#facc15",
];
const clusterColor = c => CLUSTER_PALETTE[c % CLUSTER_PALETTE.length];

async function renderClusters() {
  let data;
  try { data = await api("/clusters"); }
  catch (e) { console.warn("clusters", e); return; }

  document.getElementById("cluster-meta").textContent =
    `${data.k} grupos \u00b7 calidad de separación ${fmt(data.silhouette, 3)} \u00b7 ${data.n_trips} viajes, ${data.n_drivers} conductores`;

  // Scatter: trips colored by cluster
  const groups = new Map();
  for (const t of data.trip_assignments) {
    if (!groups.has(t.cluster)) groups.set(t.cluster, []);
    groups.get(t.cluster).push({ x: t.x, y: t.y, _meta: t });
  }
  const labelByCluster = Object.fromEntries(
    data.clusters.map(c => [c.cluster, c.label_hint])
  );
  const datasets = [...groups.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([cid, pts]) => ({
      label: `Grupo ${cid} \u00b7 ${labelByCluster[cid] || "estilo"}`,
      data: pts,
      backgroundColor: clusterColor(cid),
      borderColor: clusterColor(cid),
      pointRadius: 4, pointHoverRadius: 6,
    }));

  const ctx = document.getElementById("cluster-scatter");
  if (state.clusterChart) state.clusterChart.destroy();
  state.clusterChart = new Chart(ctx, {
    type: "scatter",
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: "#e6e9f2", font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const m = ctx.raw._meta;
              return `Conductor ${m.driver_id} \u00b7 camión ${m.truck_model} \u00b7 grupo ${m.cluster}`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8a93a8" }, grid: { color: "rgba(255,255,255,0.06)" }, title: { text: "Componente 1", display: true, color: "#8a93a8" } },
        y: { ticks: { color: "#8a93a8" }, grid: { color: "rgba(255,255,255,0.06)" }, title: { text: "Componente 2", display: true, color: "#8a93a8" } },
      },
    },
  });

  // Cluster summary table
  const cb = document.getElementById("cluster-body");
  cb.innerHTML = "";
  for (const c of data.clusters) {
    const tr = document.createElement("tr");
    const harsh = (c.centroid.harsh_brake_per_100km || 0)
                + (c.centroid.harsh_accel_per_100km || 0)
                + (c.centroid.harsh_turn_per_100km || 0);
    tr.innerHTML = `
      <td><span class="cluster-dot" style="--c:${clusterColor(c.cluster)}"></span>${c.cluster}</td>
      <td>${c.label_hint}</td>
      <td>${c.n_trips}</td>
      <td>${c.n_drivers}</td>
      <td>${fmt(c.centroid.speed_ratio_mean, 2)}</td>
      <td>${fmt(c.centroid.fuel_per_100km, 1)}</td>
      <td>${fmt(100 * (c.centroid.idle_frac || 0), 1)}</td>
      <td>${fmt(harsh, 1)}</td>`;
    cb.appendChild(tr);
  }

  // Driver style mix
  const kinds = data.clusters.map(c => c.cluster);
  const head = document.getElementById("mix-head");
  head.innerHTML = `<th>Conductor</th><th>Estilo dominante</th><th>Constancia</th>` +
    kinds.map(c => `<th><span class="cluster-dot" style="--c:${clusterColor(c)}"></span>${c}</th>`).join("");
  const mix = data.driver_cluster_mix || {};
  const profByDriver = Object.fromEntries((data.driver_profiles || []).map(p => [p.driver_id, p]));
  const body = document.getElementById("mix-body");
  body.innerHTML = "";
  for (const drv of Object.keys(mix).sort()) {
    const p = profByDriver[drv] || {};
    const cells = kinds.map(c => {
      const v = mix[drv][c] || 0;
      const intensity = Math.round(v * 100);
      const bg = `rgba(${hexToRgb(clusterColor(c))}, ${0.05 + 0.55 * v})`;
      return `<td style="background:${bg}">${intensity ? intensity + "%" : ""}</td>`;
    }).join("");
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.driver_name || drv}</td>
      <td><span class="cluster-dot" style="--c:${clusterColor(p.dominant_cluster)}"></span>${p.dominant_cluster}</td>
      <td>${fmt((p.purity || 0) * 100, 0)}%</td>${cells}`;
    body.appendChild(tr);
  }
}

function hexToRgb(hex) {
  const m = hex.replace("#", "");
  const n = parseInt(m, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(",");
}

async function renderAll() {
  if (!state.route || !state.truck) return;
  try {
    const tasks = [
      renderOverview(),
      renderMap(),
      renderDrivers(),
      renderTrucks(),
      renderIdleAndAnomalies(),
      renderClusters(),
    ];
    if (state.activeTab === "coach") {
      tasks.push(renderCoachingMap());
    }
    await Promise.all(tasks);
  } catch (e) {
    console.error(e);
  }
}

(async () => {
  bindControls();
  await loadRoutes();
  await renderAll();
})();
