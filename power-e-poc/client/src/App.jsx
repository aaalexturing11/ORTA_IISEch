import { useCallback, useEffect, useState } from "react";

const API_BASE =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") || "";

function actionBadge(action) {
  const map = {
    maintain_speed: { label: "Mantener", tone: "good" },
    ease_throttle: { label: "Soltar gas", tone: "warn" },
    reduce_idle: { label: "Ralentí", tone: "warn" },
    neutral: { label: "Info", tone: "muted" },
  };
  return map[action] || map.neutral;
}

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [custom, setCustom] = useState({
    originLat: "",
    originLng: "",
    destLat: "",
    destLng: "",
  });

  const fetchRoute = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    const oLat = custom.originLat.trim();
    const oLng = custom.originLng.trim();
    const dLat = custom.destLat.trim();
    const dLng = custom.destLng.trim();
    if (oLat) params.set("originLat", oLat);
    if (oLng) params.set("originLng", oLng);
    if (dLat) params.set("destLat", dLat);
    if (dLng) params.set("destLng", dLng);

    const qs = params.toString();
    const url = `${API_BASE}/api/route-optimization${qs ? `?${qs}` : ""}`;

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e.message || "Error de red");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [custom]);

  useEffect(() => {
    fetchRoute();
  }, []);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1 className="title">Power E — POC</h1>
          <p className="subtitle">
            Ruta fija Puebla → Cuautitlán (simulación para probar integración antes de
            Swift / backend real).
          </p>
        </div>
        <button type="button" className="btn" onClick={fetchRoute} disabled={loading}>
          {loading ? "Actualizando…" : "Recalcular"}
        </button>
      </header>

      <section className="panel">
        <h2 className="panel-title">Coordenadas (opcional)</h2>
        <p className="panel-hint">
          Vacío = ruta por defecto del servidor. Con proxy de Vite no hace falta CORS
          en desarrollo.
        </p>
        <div className="grid">
          <label>
            Origen lat
            <input
              value={custom.originLat}
              onChange={(e) =>
                setCustom((s) => ({ ...s, originLat: e.target.value }))
              }
              placeholder="19.0414"
            />
          </label>
          <label>
            Origen lng
            <input
              value={custom.originLng}
              onChange={(e) =>
                setCustom((s) => ({ ...s, originLng: e.target.value }))
              }
              placeholder="-98.2063"
            />
          </label>
          <label>
            Destino lat
            <input
              value={custom.destLat}
              onChange={(e) =>
                setCustom((s) => ({ ...s, destLat: e.target.value }))
              }
              placeholder="19.6688"
            />
          </label>
          <label>
            Destino lng
            <input
              value={custom.destLng}
              onChange={(e) =>
                setCustom((s) => ({ ...s, destLng: e.target.value }))
              }
              placeholder="-99.1764"
            />
          </label>
        </div>
      </section>

      {error && (
        <div className="alert error">
          <strong>Error:</strong> {error}
          <br />
          <span className="muted">
            Asegúrate de tener el servidor (puerto por defecto 3041; o el que pongas en{" "}
            <code>PORT</code>) (
            <code>cd power-e-poc/server && npm start</code>
            ) y el front con <code>npm run dev</code> (usa proxy /api).
          </span>
        </div>
      )}

      {loading && !data && !error && (
        <p className="center muted">Calculando ruta y consejos…</p>
      )}

      {data && (
        <>
          <section className="card">
            <div className="card-head">
              <h2>
                {data.origin} → {data.destination}
              </h2>
              {data.meta?.note && (
                <p className="meta">{data.meta.note}</p>
              )}
            </div>
            <div className="stats">
              <div>
                <span className="stat-label">Distancia</span>
                <span className="stat-value">{data.distance_km} km</span>
              </div>
              <div>
                <span className="stat-label">Tiempo estimado</span>
                <span className="stat-value">{data.estimated_time_label}</span>
              </div>
              <div>
                <span className="stat-label">Ahorro combustible</span>
                <span className="stat-value good">
                  {data.savings.fuel_percent_vs_baseline}
                </span>
              </div>
              <div>
                <span className="stat-label">CO₂ evitado (aprox.)</span>
                <span className="stat-value good">
                  {data.savings.co2_reduced_kg} kg
                </span>
              </div>
            </div>
          </section>

          <section className="card">
            <h2 className="card-title">Consejos al conductor (HUD)</h2>
            <ul className="tips">
              {data.driver_coaching_summary?.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </section>

          <section className="card">
            <h2 className="card-title">Tramos y acción sugerida</h2>
            <div className="table-wrap">
              <table className="steps">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Etiqueta</th>
                    <th>km</th>
                    <th>Acción</th>
                    <th>Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {data.optimized_steps?.map((step) => {
                    const b = actionBadge(step.advice?.action);
                    return (
                      <tr key={step.order}>
                        <td>{step.order}</td>
                        <td>{step.label}</td>
                        <td className="mono">{step.km_from_start}</td>
                        <td>
                          <span className={`badge badge-${b.tone}`}>
                            {b.label}
                          </span>
                        </td>
                        <td>
                          <strong>{step.advice?.headline}</strong>
                          <br />
                          <span className="muted small">{step.advice?.detail}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card muted-block">
            <h3 className="card-title">JSON crudo (debug)</h3>
            <pre className="json">{JSON.stringify(data, null, 2)}</pre>
          </section>
        </>
      )}

      <style>{`
        .app {
          max-width: 900px;
          margin: 0 auto;
          padding: 1.5rem 1rem 3rem;
        }
        .header {
          display: flex;
          flex-wrap: wrap;
          align-items: flex-start;
          justify-content: space-between;
          gap: 1rem;
          margin-bottom: 1.5rem;
        }
        .title {
          margin: 0 0 0.35rem;
          font-size: 1.65rem;
          font-weight: 700;
        }
        .subtitle {
          margin: 0;
          color: var(--muted);
          font-size: 0.95rem;
          max-width: 36rem;
        }
        .btn {
          background: var(--accent);
          color: #0a0e12;
          border: none;
          padding: 0.6rem 1.1rem;
          font-weight: 600;
          border-radius: 8px;
          cursor: pointer;
          font-family: inherit;
          font-size: 0.95rem;
        }
        .btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .panel {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 1rem 1.25rem;
          margin-bottom: 1rem;
        }
        .panel-title {
          margin: 0 0 0.35rem;
          font-size: 1rem;
        }
        .panel-hint {
          margin: 0 0 1rem;
          font-size: 0.85rem;
          color: var(--muted);
        }
        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
          gap: 0.75rem;
        }
        .grid label {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
          font-size: 0.8rem;
          color: var(--muted);
        }
        .grid input {
          padding: 0.45rem 0.5rem;
          border-radius: 6px;
          border: 1px solid var(--border);
          background: var(--bg);
          color: var(--text);
          font-family: ui-monospace, monospace;
          font-size: 0.85rem;
        }
        .card {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 1.25rem;
          margin-bottom: 1rem;
        }
        .card-head h2 {
          margin: 0 0 0.5rem;
          font-size: 1.15rem;
        }
        .meta {
          margin: 0;
          font-size: 0.85rem;
          color: var(--muted);
        }
        .card-title {
          margin: 0 0 0.75rem;
          font-size: 1.05rem;
        }
        .stats {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
          gap: 1rem;
        }
        .stat-label {
          display: block;
          font-size: 0.75rem;
          color: var(--muted);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .stat-value {
          font-size: 1.25rem;
          font-weight: 600;
        }
        .stat-value.good {
          color: var(--good);
        }
        .tips {
          margin: 0;
          padding-left: 1.2rem;
        }
        .tips li {
          margin-bottom: 0.5rem;
        }
        .table-wrap {
          overflow-x: auto;
        }
        .steps {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.9rem;
        }
        .steps th,
        .steps td {
          text-align: left;
          padding: 0.6rem 0.5rem;
          border-bottom: 1px solid var(--border);
          vertical-align: top;
        }
        .steps th {
          color: var(--muted);
          font-weight: 600;
          font-size: 0.75rem;
          text-transform: uppercase;
        }
        .mono {
          font-family: ui-monospace, monospace;
        }
        .badge {
          display: inline-block;
          padding: 0.2rem 0.5rem;
          border-radius: 6px;
          font-size: 0.75rem;
          font-weight: 600;
        }
        .badge-good {
          background: rgba(62, 207, 142, 0.2);
          color: var(--good);
        }
        .badge-warn {
          background: rgba(240, 180, 41, 0.15);
          color: var(--warn);
        }
        .badge-muted {
          background: rgba(143, 163, 184, 0.15);
          color: var(--muted);
        }
        .muted {
          color: var(--muted);
        }
        .small {
          font-size: 0.82rem;
        }
        .center {
          text-align: center;
        }
        .alert {
          padding: 1rem;
          border-radius: 10px;
          margin-bottom: 1rem;
        }
        .alert.error {
          background: rgba(220, 80, 80, 0.12);
          border: 1px solid rgba(220, 80, 80, 0.35);
        }
        .muted-block .json {
          margin: 0;
          font-size: 0.72rem;
          overflow: auto;
          max-height: 240px;
        }
      `}</style>
    </div>
  );
}
