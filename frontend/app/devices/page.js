"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  deviceStatus,
  listDevices,
  listFarms,
  listZones,
  registerDevice,
  revokeDevice,
  rotateDeviceKey,
} from "../../lib/api";
import { hasPermission, useSession } from "../../lib/session";

const DEVICE_TYPES = [
  "soil_probe", "weather_station", "combined_station", "gateway", "other",
];

const EMPTY_FORM = {
  farm_id: "",
  zone_id: "",
  name: "",
  code: "",
  device_type: "soil_probe",
  model: "",
  firmware_version: "",
};

function fmtTime(iso) {
  if (!iso) return "—";
  return `${iso.replace("T", " ").slice(0, 16)} UTC`;
}

export default function DevicesPage() {
  const session = useSession();
  const router = useRouter();

  const canManage = hasPermission(session, "device.manage");
  const [devices, setDevices] = useState([]);
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [zones, setZones] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [keyReveal, setKeyReveal] = useState(null); // { title, apiKey, notice }
  const [status, setStatus] = useState(null); // DeviceStatusOut for the open row

  useEffect(() => {
    if (!session) router.replace("/login");
  }, [session, router]);

  const load = useCallback(async () => {
    if (!canManage) return;
    setLoading(true);
    try {
      const [d, f] = await Promise.all([listDevices(), listFarms()]);
      setDevices(d.items);
      setFarms(f.items);
    } catch (err) {
      if (err.status !== 401) setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [canManage]);

  useEffect(() => {
    if (session) load();
  }, [session, load]);

  // Zones follow the selected farm in the registration form.
  useEffect(() => {
    setForm((p) => ({ ...p, zone_id: "" }));
    if (!form.farm_id) {
      setZones([]);
      return;
    }
    listZones(form.farm_id).then(setZones).catch(() => setZones([]));
  }, [form.farm_id]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const farmName = (id) => farms.find((f) => f.id === id)?.name ?? `#${id}`;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload = {
        farm_id: Number(form.farm_id),
        name: form.name,
        code: form.code,
        device_type: form.device_type,
        model: form.model,
        firmware_version: form.firmware_version,
      };
      if (form.zone_id) payload.zone_id = Number(form.zone_id);
      const res = await registerDevice(payload);
      setForm(EMPTY_FORM);
      setShowForm(false);
      setKeyReveal({
        title: `Device “${res.device.name}” registered`,
        apiKey: res.api_key,
        notice: res.notice,
      });
      await load();
    } catch (err) {
      setError(err.message || "Could not register device");
    } finally {
      setBusy(false);
    }
  }

  async function onRotate(device) {
    if (!window.confirm(`Rotate the API key for “${device.name}”? The old key stops working immediately.`))
      return;
    setError("");
    try {
      const res = await rotateDeviceKey(device.id);
      setKeyReveal({
        title: `New key for “${device.name}”`,
        apiKey: res.api_key,
        notice: res.notice,
      });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function onRevoke(device) {
    if (!window.confirm(`Revoke device “${device.name}”? It can no longer submit telemetry.`))
      return;
    setError("");
    try {
      await revokeDevice(device.id);
      setNotice(`Device “${device.name}” revoked.`);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function onShowStatus(device) {
    setError("");
    try {
      setStatus(await deviceStatus(device.id));
    } catch (err) {
      setError(err.message);
    }
  }

  if (!session) return null;

  if (!canManage) {
    return (
      <div className="card">
        <h2>Devices</h2>
        <p className="muted">
          Managing IoT devices requires the <code>device.manage</code>{" "}
          permission. Ask a farm manager or administrator to grant access.
        </p>
      </div>
    );
  }

  return (
    <>
      {error && <div className="error">{error}</div>}
      {notice && <div className="notice">{notice}</div>}

      {keyReveal && (
        <div className="card" style={{ borderColor: "var(--danger)" }}>
          <h3>{keyReveal.title}</h3>
          <p>
            <code style={{ userSelect: "all", wordBreak: "break-all" }}>{keyReveal.apiKey}</code>
          </p>
          <p className="muted">{keyReveal.notice}</p>
          <button onClick={() => setKeyReveal(null)}>I have stored the key</button>
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>IoT devices</h2>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="primary" style={{ marginTop: 0 }} onClick={() => setShowForm(!showForm)}>
            {showForm ? "Cancel" : "+ Register device"}
          </button>
        </div>
        <p className="muted">
          Each device authenticates with its own API key (sent as
          <code> X-Device-Key</code>). Keys are shown once at registration or
          rotation. Simulators and real hardware use the same ingestion path.
        </p>
        {loading ? (
          <p className="muted">Loading devices…</p>
        ) : devices.length === 0 ? (
          <p className="muted">No devices registered yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Code</th>
                <th>Farm</th>
                <th>Type</th>
                <th>Key</th>
                <th>Last seen</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td>{d.code}</td>
                  <td>{farmName(d.farm_id)}</td>
                  <td>{d.device_type}</td>
                  <td><code>{d.key_prefix}…</code></td>
                  <td>{fmtTime(d.last_seen_at)}</td>
                  <td>
                    <span className={`badge${d.status === "active" ? "" : " muted"}`}>{d.status}</span>
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="linkish" onClick={() => onShowStatus(d)}>Status</button>
                    {d.status === "active" && (
                      <>
                        <button className="linkish" onClick={() => onRotate(d)}>Rotate key</button>
                        <button className="linkish" onClick={() => onRevoke(d)}>Revoke</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {status && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>
              Status — {status.device.name} <span className="badge">{status.device.code}</span>
            </h3>
            <span className="spacer" style={{ flex: 1 }} />
            <button className="linkish" onClick={() => setStatus(null)}>Close</button>
          </div>
          <p>
            {status.last_seen_minutes_ago === null
              ? "Never reported in."
              : `Last accepted reading ${status.last_seen_minutes_ago} min ago.`}
            {" "}
            {status.is_stale && <span className="badge" style={{ background: "#fde2e2" }}>stale</span>}
          </p>
          {status.open_faults.length > 0 ? (
            <table>
              <thead>
                <tr><th>Fault</th><th>Detected</th><th>Detail</th></tr>
              </thead>
              <tbody>
                {status.open_faults.map((f) => (
                  <tr key={f.id}>
                    <td><span className="badge">{f.fault_type}</span></td>
                    <td>{fmtTime(f.detected_at)}</td>
                    <td>{f.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No open faults for this device.</p>
          )}
        </div>
      )}

      {showForm && (
        <div className="card">
          <h3>Register a device</h3>
          <form onSubmit={onSubmit}>
            <div className="row">
              <div>
                <label>Farm *</label>
                <select value={form.farm_id} onChange={set("farm_id")} required>
                  <option value="">Select farm…</option>
                  {farms.map((f) => (
                    <option key={f.id} value={f.id}>{f.name} ({f.code})</option>
                  ))}
                </select>
              </div>
              <div>
                <label>Zone</label>
                <select value={form.zone_id} onChange={set("zone_id")} disabled={zones.length === 0}>
                  <option value="">Unassigned</option>
                  {zones.map((z) => (
                    <option key={z.id} value={z.id}>{z.name} ({z.code})</option>
                  ))}
                </select>
              </div>
              <div>
                <label>Device type *</label>
                <select value={form.device_type} onChange={set("device_type")}>
                  {DEVICE_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="row">
              <div>
                <label>Name *</label>
                <input value={form.name} onChange={set("name")} required />
              </div>
              <div>
                <label>Code *</label>
                <input value={form.code} onChange={set("code")} required placeholder="e.g. SP-01" />
              </div>
              <div>
                <label>Model</label>
                <input value={form.model} onChange={set("model")} />
              </div>
              <div>
                <label>Firmware</label>
                <input value={form.firmware_version} onChange={set("firmware_version")} />
              </div>
            </div>
            <button className="primary" disabled={busy}>
              {busy ? "Registering…" : "Register device"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
