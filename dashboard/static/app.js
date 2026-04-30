const state = {
  routes: [],
  route: null,
  truck: null,
  since: null,
  mapInstance: null,
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
    opt.textContent = `${t.label} (${t.n_trips} trips)`;
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
}

// ---------------- Renderers ----------------
async function renderOverview() {
  const k = await api("/kpis");
  const route = state.routes.find(r => r.slug === state.route);
  document.getElementById("subtitle").textContent =
    route ? `${route.origin} → ${route.destination} · ${fmt(route.distance_km, 0)} km · ${k.n_trips ?? 0} trips` : "";
  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = "";
  if (k.empty) {
    grid.innerHTML = `<div class="kpi"><span class="kpi-label">No trips for selection</span></div>`;
    return;
  }
  const tiles = [
    { label: "Fuel efficiency", value: fmt(k.fuel_l_per_100km, 1), unit: "L/100km" },
    { label: "Utilization", value: fmt(k.utilization_pct, 1), unit: "%" },
    { label: "CO₂ intensity", value: fmt(k.co2_kg_per_km, 2), unit: "kg/km" },
    { label: "Avg speed", value: fmt(k.avg_speed_kph, 1), unit: "kph" },
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
  if (m.origin) L.marker([m.origin.lat, m.origin.lon]).addTo(map).bindPopup("Origin");
  if (m.destination) L.marker([m.destination.lat, m.destination.lon]).addTo(map).bindPopup("Destination");
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
    `<b>Segment ${h.seg_idx}</b><br>${fmt(h.fuel_per_km_l, 3)} L/km` +
    `<br>${fmt(h.avg_speed, 1)} kph · slope ${fmt(h.slope_pct, 2)}%`
  ).openPopup();
  state.hotspotMarker = marker;
}

async function renderDrivers() {
  const d = await api("/drivers");
  const drivers = d.drivers || [];
  document.getElementById("driver-baselines").textContent =
    `Baselines from data: best fuel ${fmt(d.baseline_fuel_l_per_100km, 1)} L/100km · best idle ${fmt(d.baseline_idle_h_per_100km, 3)} h/100km`;
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
        label: "Composite score",
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
    ["Model", truck.model_name],
    ["Engine", truck.engine_model],
    ["GCW kg", truck.gross_combined_weight_kg],
    ["Tractor mass kg", truck.tractor_mass_kg],
    ["Trailer mass kg", truck.trailer_mass_kg],
    ["Fleet trips", stats.n_trips],
    ["Fleet km", fmt(stats.distance_km, 0)],
    ["Fleet L/100km", fmt(stats.fuel_l_per_100km, 1)],
    ["Avg kph", fmt(stats.avg_speed_kph, 1)],
    ["Harsh B / A", `${fmtInt(stats.harsh_brakes)} / ${fmtInt(stats.harsh_accels)}`],
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
    `Baseline idle: ${fmt(idle.baseline_idle_h_per_100km, 3)} h/100km · total idle ${fmt(idle.total_idle_h, 1)} h`;
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
  fuel_theft: "Fuel theft",
  sensor_dropout: "Sensor dropout",
  overheat: "Overheat",
  tire_leak: "Tire leak",
  harsh_cluster: "Harsh-event cluster",
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
    total ? `${total} events across ${byKind.length} kinds` : "No anomalies for this selection.";

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
  head.innerHTML = `<th>Driver</th>` + kinds.map(k =>
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
  kindSel.innerHTML = `<option value="">All kinds</option>` +
    kindsAll.map(k => `<option value="${k}">${kindLabel(k)}</option>`).join("");
  drvSel.innerHTML = `<option value="">All drivers</option>` +
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
    `k=${data.k} \u00b7 silhouette ${fmt(data.silhouette, 3)} \u00b7 ${data.n_trips} trips, ${data.n_drivers} drivers`;

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
      label: `${cid} \u00b7 ${labelByCluster[cid] || "cluster"}`,
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
              return `${m.driver_id} \u00b7 ${m.truck_model} \u00b7 cluster ${m.cluster}`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8a93a8" }, grid: { color: "rgba(255,255,255,0.06)" }, title: { text: "UMAP-1", display: true, color: "#8a93a8" } },
        y: { ticks: { color: "#8a93a8" }, grid: { color: "rgba(255,255,255,0.06)" }, title: { text: "UMAP-2", display: true, color: "#8a93a8" } },
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
  head.innerHTML = `<th>Driver</th><th>Dominant</th><th>Purity</th>` +
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
    await Promise.all([
      renderOverview(),
      renderMap(),
      renderDrivers(),
      renderTrucks(),
      renderIdleAndAnomalies(),
      renderClusters(),
    ]);
  } catch (e) {
    console.error(e);
  }
}

(async () => {
  bindControls();
  await loadRoutes();
  await renderAll();
})();
