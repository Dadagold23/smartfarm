"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  createFarm,
  deleteFarm,
  listFarms,
} from "../../lib/api";
import { hasPermission, useSession, refreshUser } from "../../lib/session";

const EMPTY_FORM = {
  name: "",
  code: "",
  country: "",
  region: "",
  locality: "",
  area_ha: "",
  latitude: "",
  longitude: "",
  water_source: "borehole",
};

const WATER_SOURCES = [
  "borehole", "well", "reservoir", "river", "canal",
  "municipal", "harvested_rainwater", "desalinated", "other",
];

export default function DashboardPage() {
  const session = useSession();
  const router = useRouter();
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);

  const canCreate = hasPermission(session, "farm.create");
  const canDeleteAny = hasPermission(session, "farm.delete.all");

  useEffect(() => {
    if (!session) router.replace("/login");
    else refreshUser().catch(() => {});
  }, [session, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setListError("");
    try {
      const data = await listFarms();
      setFarms(data.items);
    } catch (err) {
      if (err.status !== 401) setListError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (session) load();
  }, [session, load]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function onSubmit(e) {
    e.preventDefault();
    setFormError("");
    setBusy(true);
    try {
      const payload = { ...form };
      // Send numeric fields as numbers only when provided; backend validates ranges.
      for (const k of ["area_ha", "latitude", "longitude"]) {
        if (payload[k] === "") payload[k] = null;
      }
      await createFarm(payload);
      setForm(EMPTY_FORM);
      setShowForm(false);
      await load();
    } catch (err) {
      setFormError(err.message || "Could not create farm");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(farm) {
    if (!window.confirm(`Delete farm “${farm.name}”? This cannot be undone from the UI.`))
      return;
    try {
      await deleteFarm(farm.id);
      await load();
    } catch (err) {
      setListError(err.message);
    }
  }

  if (!session) return null;

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>My farms</h2>
          <span className="spacer" style={{ flex: 1 }} />
          {canCreate && (
            <button className="primary" style={{ marginTop: 0 }} onClick={() => setShowForm(!showForm)}>
              {showForm ? "Cancel" : "+ New farm"}
            </button>
          )}
        </div>
        <p className="muted">
          {canDeleteAny
            ? "Administrator view: all farms in the system."
            : "Farms you own or have oversight access to."}
        </p>
        {listError && <div className="error">{listError}</div>}
        {loading ? (
          <p className="muted">Loading farms…</p>
        ) : farms.length === 0 ? (
          <p className="muted">No farms yet. Create your first farm above.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Code</th>
                <th>Location</th>
                <th>Area (ha)</th>
                <th>Water source</th>
                <th>Zones</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {farms.map((f) => (
                <tr key={f.id}>
                  <td>
                    <Link href={`/farms/${f.id}`}>{f.name}</Link>
                  </td>
                  <td>{f.code}</td>
                  <td>{[f.locality, f.region, f.country].filter(Boolean).join(", ") || "—"}</td>
                  <td>{f.area_ha ?? "—"}</td>
                  <td>{f.water_source}</td>
                  <td>{f.zones.length}</td>
                  <td>
                    <span className={`badge${f.status === "active" ? "" : " muted"}`}>{f.status}</span>
                  </td>
                  <td>
                    {(canDeleteAny || f.owner_id === session.user.id) && (
                      <button className="linkish" onClick={() => onDelete(f)}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {canCreate && showForm && (
        <div className="card">
          <h3>Register a new farm</h3>
          <form onSubmit={onSubmit}>
            <div className="row">
              <div>
                <label>Farm name *</label>
                <input value={form.name} onChange={set("name")} required minLength={2} />
              </div>
              <div>
                <label>Short code *</label>
                <input value={form.code} onChange={set("code")} required placeholder="e.g. NRF-01" />
              </div>
            </div>
            <div className="row">
              <div>
                <label>Country</label>
                <input value={form.country} onChange={set("country")} />
              </div>
              <div>
                <label>Region</label>
                <input value={form.region} onChange={set("region")} />
              </div>
              <div>
                <label>Locality</label>
                <input value={form.locality} onChange={set("locality")} />
              </div>
            </div>
            <div className="row">
              <div>
                <label>Latitude (-90..90)</label>
                <input value={form.latitude} onChange={set("latitude")} inputMode="decimal" />
              </div>
              <div>
                <label>Longitude (-180..180)</label>
                <input value={form.longitude} onChange={set("longitude")} inputMode="decimal" />
              </div>
              <div>
                <label>Area (ha)</label>
                <input value={form.area_ha} onChange={set("area_ha")} inputMode="decimal" />
              </div>
              <div>
                <label>Water source</label>
                <select value={form.water_source} onChange={set("water_source")}>
                  {WATER_SOURCES.map((w) => (
                    <option key={w} value={w}>{w}</option>
                  ))}
                </select>
              </div>
            </div>
            {formError && <div className="error">{formError}</div>}
            <button className="primary" disabled={busy}>
              {busy ? "Saving…" : "Create farm"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
