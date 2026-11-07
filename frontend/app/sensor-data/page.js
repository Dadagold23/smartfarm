"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  listDevices,
  listForecastProviders,
  listFarms,
  refreshForecast,
  soilLatest,
  weatherLatest,
} from "../../lib/api";
import { hasPermission, useSession } from "../../lib/session";

function fmtTime(iso) {
  if (!iso) return "—";
  return `${iso.replace("T", " ").slice(0, 16)} UTC`;
}

function fmt(value, unit) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(1)} ${unit}`;
}

// Provenance badges: simulated data and quality flags are never presented
// as measured/reliable — the backend stores them, the UI labels them.
// `quality_flags` names the metric(s) the fault engine flagged, not the
// fault type; the fault itself is on /faults.
function Badges({ row }) {
  return (
    <span>
      {row.is_simulated && (
        <span className="badge" style={{ background: "#fff3cd", marginRight: 4 }}>
          simulated
        </span>
      )}
      {(row.quality_flags || []).map((q) => (
        <span key={q} className="badge" style={{ background: "#fde2e2", marginRight: 4 }}>
          flagged: {q}
        </span>
      ))}
      <span className="badge muted">{row.source}</span>
    </span>
  );
}

export default function SensorDataPage() {
  const session = useSession();
  const router = useRouter();

  const canSoil = hasPermission(session, "soil.read");
  const canWeather = hasPermission(session, "weather.read");
  const canSeeDevices = hasPermission(session, "device.manage");

  const [farms, setFarms] = useState([]);
  const [deviceNames, setDeviceNames] = useState({});
  const [farmId, setFarmId] = useState("");
  const [soil, setSoil] = useState([]);
  const [weather, setWeather] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Forecast panel
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState("");
  const [days, setDays] = useState("7");
  const [forecast, setForecast] = useState(null); // ForecastRefreshOut
  const [forecastBusy, setForecastBusy] = useState(false);
  const [forecastNotice, setForecastNotice] = useState("");

  useEffect(() => {
    if (!session) router.replace("/login");
  }, [session, router]);

  useEffect(() => {
    listFarms().then((d) => setFarms(d.items)).catch(() => {});
    // Read payloads carry device_id only; names come from the registry when
    // the caller may see devices, otherwise rows fall back to "#<id>".
    if (canSeeDevices)
      listDevices()
        .then((d) => setDeviceNames(Object.fromEntries(d.items.map((x) => [x.id, x.name]))))
        .catch(() => {});
    if (canWeather)
      listForecastProviders()
        .then((d) => {
          setProviders(d.items);
          const first = d.items.find((p) => p.configured) || d.items[0];
          if (first) setProvider(first.id);
        })
        .catch(() => {});
  }, [canWeather, canSeeDevices, session]);

  const deviceLabel = (id) => deviceNames[id] ?? `#${id}`;

  const load = useCallback(async () => {
    if (!canSoil && !canWeather) return;
    setLoading(true);
    setError("");
    const id = farmId || undefined;
    try {
      const [s, w] = await Promise.all([
        canSoil ? soilLatest(id) : { items: [] },
        canWeather ? weatherLatest(id) : { items: [] },
      ]);
      setSoil(s.items);
      setWeather(w.items);
    } catch (err) {
      if (err.status !== 401) setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [canSoil, canWeather, farmId]);

  useEffect(() => {
    if (session) load();
  }, [session, load]);

  async function onRefreshForecast(e) {
    e.preventDefault();
    if (!farmId) {
      setError("Pick a farm first — forecasts are per farm coordinates.");
      return;
    }
    setForecastBusy(true);
    setError("");
    setForecastNotice("");
    try {
      const res = await refreshForecast({
        farm_id: Number(farmId),
        days: Number(days),
        provider: provider || null,
      });
      setForecast(res);
      setForecastNotice(
        `Forecast issue ${fmtTime(res.issued_at)}: ${res.created} created, ${res.updated} updated.`
      );
    } catch (err) {
      setError(err.message || "Forecast refresh failed");
    } finally {
      setForecastBusy(false);
    }
  }

  if (!session) return null;

  if (!canSoil && !canWeather) {
    return (
      <div className="card">
        <h2>Sensor data</h2>
        <p className="muted">
          Viewing soil and weather telemetry requires the{" "}
          <code>soil.read</code> or <code>weather.read</code> permission.
        </p>
      </div>
    );
  }

  return (
    <>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h2 style={{ margin: 0 }}>Latest sensor readings</h2>
          <span className="spacer" style={{ flex: 1 }} />
          <select value={farmId} onChange={(e) => setFarmId(e.target.value)} style={{ marginTop: 0, width: "auto" }}>
            <option value="">All farms</option>
            {farms.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
          <button style={{ marginTop: 0 }} onClick={load}>Refresh</button>
        </div>
        <p className="muted">
          Rows badged <span className="badge" style={{ background: "#fff3cd" }}>simulated</span>{" "}
          come from the spec-sanctioned sensor simulator, not measured hardware.
        </p>
        {loading && <p className="muted">Loading readings…</p>}

        {canSoil && (
          <>
            <h3>Soil probes</h3>
            {soil.length === 0 ? (
              <p className="muted">No soil readings yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Device</th><th>Measured</th><th>Moisture</th>
                    <th>Temp</th><th>EC</th><th>Depth</th><th>Provenance</th>
                  </tr>
                </thead>
                <tbody>
                  {soil.map((r) => (
                    <tr key={r.id}>
                      <td>{deviceLabel(r.device_id)}</td>
                      <td>{fmtTime(r.measured_at)}</td>
                      <td>{fmt(r.moisture_pct, "%")}</td>
                      <td>{fmt(r.temperature_c, "°C")}</td>
                      <td>{fmt(r.ec_mS_cm, "mS/cm")}</td>
                      <td>{r.probe_depth_cm ? `${Number(r.probe_depth_cm)} cm` : "—"}</td>
                      <td><Badges row={r} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {canWeather && (
          <>
            <h3>Weather stations</h3>
            {weather.length === 0 ? (
              <p className="muted">No weather observations yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Device</th><th>Measured</th><th>Temp</th><th>Humidity</th>
                    <th>Wind</th><th>Dir</th><th>Solar</th><th>Rain</th>
                    <th>Pressure</th><th>Provenance</th>
                  </tr>
                </thead>
                <tbody>
                  {weather.map((r) => (
                    <tr key={r.id}>
                      <td>{deviceLabel(r.device_id)}</td>
                      <td>{fmtTime(r.measured_at)}</td>
                      <td>{fmt(r.temperature_c, "°C")}</td>
                      <td>{fmt(r.humidity_pct, "%")}</td>
                      <td>{fmt(r.wind_speed_m_s, "m/s")}</td>
                      <td>{fmt(r.wind_direction_deg, "°")}</td>
                      <td>{fmt(r.solar_radiation_w_m2, "W/m²")}</td>
                      <td>{fmt(r.rainfall_mm, "mm")}</td>
                      <td>{fmt(r.pressure_hpa, "hPa")}</td>
                      <td><Badges row={r} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      {canWeather && (
        <div className="card">
          <h3>Weather forecast</h3>
          <p className="muted">
            Pulls the next issue from a provider adapter and stores it against
            the farm. Simulated providers are badged and never presented as
            measured science; real providers fail loudly rather than
            silently falling back to fake data.
          </p>
          {forecastNotice && <div className="notice">{forecastNotice}</div>}
          <form onSubmit={onRefreshForecast}>
            <div className="row">
              <div>
                <label>Farm *</label>
                <select value={farmId} onChange={(e) => setFarmId(e.target.value)}>
                  <option value="">Select farm…</option>
                  {farms.map((f) => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label>Provider</label>
                <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.id}
                      {p.is_simulated ? " (simulated)" : p.configured ? "" : " (no API key)"}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label>Days (1–16)</label>
                <input value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" />
              </div>
            </div>
            <button className="primary" disabled={forecastBusy}>
              {forecastBusy ? "Fetching…" : "Refresh forecast"}
            </button>
          </form>

          {forecast && (
            <>
              <h4>
                {forecast.provider} issue {fmtTime(forecast.issued_at)}
                {forecast.is_simulated && (
                  <span className="badge" style={{ background: "#fff3cd", marginLeft: 8 }}>
                    simulated
                  </span>
                )}
              </h4>
              <table>
                <thead>
                  <tr>
                    <th>Date</th><th>Lead</th><th>Min</th><th>Max</th>
                    <th>Precip</th><th>Rain %</th><th>Wind</th><th>Humidity</th><th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {forecast.items.map((f) => (
                    <tr key={f.id}>
                      <td>{f.forecast_date}</td>
                      <td>{f.lead_time_days} d</td>
                      <td>{fmt(f.temp_min_c, "°C")}</td>
                      <td>{fmt(f.temp_max_c, "°C")}</td>
                      <td>{fmt(f.precipitation_mm, "mm")}</td>
                      <td>{fmt(f.rain_probability_pct, "%")}</td>
                      <td>{fmt(f.wind_speed_m_s, "m/s")}</td>
                      <td>{fmt(f.humidity_pct, "%")}</td>
                      <td>{fmt(f.confidence, "%")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </>
  );
}
