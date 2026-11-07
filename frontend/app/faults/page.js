"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listDevices, listFaults, listFarms } from "../../lib/api";
import { hasPermission, useSession } from "../../lib/session";

const FAULT_COLORS = {
  stale_data: "#fde2e2",
  out_of_range: "#fde2e2",
  flatline: "#fff3cd",
  auth_failure: "#e2d5f8",
};

function fmtTime(iso) {
  if (!iso) return "—";
  return `${iso.replace("T", " ").slice(0, 16)} UTC`;
}

export default function FaultsPage() {
  const session = useSession();
  const router = useRouter();

  const canRead = hasPermission(session, "faults.read");
  const canSeeDevices = hasPermission(session, "device.manage");
  const [faults, setFaults] = useState([]);
  const [farms, setFarms] = useState([]);
  const [deviceNames, setDeviceNames] = useState({});
  const [farmId, setFarmId] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) router.replace("/login");
  }, [session, router]);

  useEffect(() => {
    listFarms().then((d) => setFarms(d.items)).catch(() => {});
    // Fault rows carry device_id only; names come from the registry when the
    // caller may see devices, otherwise the row falls back to "#<id>".
    if (canSeeDevices)
      listDevices()
        .then((d) => setDeviceNames(Object.fromEntries(d.items.map((x) => [x.id, x.name]))))
        .catch(() => {});
  }, [canSeeDevices]);

  const load = useCallback(async () => {
    if (!canRead) return;
    setLoading(true);
    setError("");
    try {
      // GET /faults runs the staleness sweep server-side before listing.
      const data = await listFaults({ farmId: farmId || undefined, openOnly });
      setFaults(data.items);
    } catch (err) {
      if (err.status !== 401) setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [canRead, farmId, openOnly]);

  useEffect(() => {
    if (session) load();
  }, [session, load]);

  if (!session) return null;

  if (!canRead) {
    return (
      <div className="card">
        <h2>Sensor faults</h2>
        <p className="muted">
          Viewing sensor fault events requires the <code>faults.read</code>{" "}
          permission.
        </p>
      </div>
    );
  }

  const farmName = (id) => farms.find((f) => f.id === id)?.name ?? `#${id}`;

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h2 style={{ margin: 0 }}>Sensor faults</h2>
        <span className="spacer" style={{ flex: 1 }} />
        <select
          value={farmId}
          onChange={(e) => setFarmId(e.target.value)}
          style={{ marginTop: 0, width: "auto" }}
        >
          <option value="">All farms</option>
          {farms.map((f) => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>
        <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 0 }}>
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(e) => setOpenOnly(e.target.checked)}
            style={{ width: "auto" }}
          />
          Open only
        </label>
        <button style={{ marginTop: 0 }} onClick={load}>Refresh</button>
      </div>
      <p className="muted">
        Stale-device events open and resolve automatically as devices report
        in; out-of-range and flatline events are maintained at ingestion
        time. Refreshing this page re-runs the staleness sweep.
      </p>
      {error && <div className="error">{error}</div>}
      {loading ? (
        <p className="muted">Loading faults…</p>
      ) : faults.length === 0 ? (
        <p className="muted">
          {openOnly ? "No open faults — sensors look healthy." : "No fault events recorded."}
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Fault</th>
              <th>Farm</th>
              <th>Device</th>
              <th>Detected</th>
              <th>Resolved</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {faults.map((f) => (
              <tr key={f.id}>
                <td>
                  <span className="badge" style={{ background: FAULT_COLORS[f.fault_type] || "#f1f1f1" }}>
                    {f.fault_type}
                  </span>
                </td>
                <td>{farmName(f.farm_id)}</td>
                <td>{deviceNames[f.device_id] ?? `#${f.device_id}`}</td>
                <td>{fmtTime(f.detected_at)}</td>
                <td>{f.resolved_at ? fmtTime(f.resolved_at) : <span className="badge">open</span>}</td>
                <td>{f.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
