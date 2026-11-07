"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  createZone,
  deleteFarm,
  deleteZone,
  getFarm,
  listZones,
  updateFarm,
  updateZone,
} from "../../../lib/api";
import { hasPermission, useSession } from "../../../lib/session";

export default function FarmDetailPage() {
  const session = useSession();
  const router = useRouter();
  const params = useParams();
  const farmId = params.id;

  const [farm, setFarm] = useState(null);
  const [zones, setZones] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [farmForm, setFarmForm] = useState(null);
  const [zoneForm, setZoneForm] = useState({ name: "", code: "", area_ha: "", sequence_number: "0" });
  const [busy, setBusy] = useState(false);

  const canUpdate = hasPermission(session, "farm.update.own");
  const canCreateZone = hasPermission(session, "zone.create");
  const canUpdateZone = hasPermission(session, "zone.update");
  const canDeleteZone = hasPermission(session, "zone.delete");

  useEffect(() => {
    if (!session) router.replace("/login");
  }, [session, router]);

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await getFarm(farmId);
      setFarm(res);
      setFarmForm({
        name: res.name,
        code: res.code,
        country: res.country,
        region: res.region,
        locality: res.locality,
        area_ha: res.area_ha || "",
        description: res.description || "",
        status: res.status,
      });
      const z = await listZones(farmId);
      setZones(z);
    } catch (err) {
      if (err.status === 404) router.replace("/dashboard");
      else setError(err.message || "Failed to load farm");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmId]);

  useEffect(() => {
    if (session) load();
  }, [session, load]);

  async function onSubmitFarm(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload = { ...farmForm };
      if (payload.area_ha === "") payload.area_ha = null;
      const updated = await updateFarm(farmId, payload);
      setFarm(updated);
      setNotice("Farm details saved.");
    } catch (err) {
      setError(err.message || "Could not update farm");
    } finally {
      setBusy(false);
    }
  }

  async function onCreateZone(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload = {
        name: zoneForm.name,
        code: zoneForm.code,
        sequence_number: Number(zoneForm.sequence_number || 0),
      };
      if (zoneForm.area_ha !== "") payload.area_ha = zoneForm.area_ha;
      await createZone(farmId, payload);
      setZoneForm({ name: "", code: "", area_ha: "", sequence_number: "0" });
      setZones(await listZones(farmId));
      setNotice("Irrigation zone created.");
    } catch (err) {
      setError(err.message || "Could not create zone");
    } finally {
      setBusy(false);
    }
  }

  async function onZoneStatus(zone, status) {
    setError("");
    try {
      await updateZone(zone.id, { status });
      setZones(await listZones(farmId));
    } catch (err) {
      setError(err.message);
    }
  }

  async function onDeleteZone(zone) {
    if (!window.confirm(`Delete zone “${zone.name}”?`)) return;
    setError("");
    try {
      await deleteZone(zone.id);
      setZones(await listZones(farmId));
    } catch (err) {
      setError(err.message);
    }
  }

  async function onDeleteFarm() {
    if (!window.confirm(`Delete farm “${farm?.name}”?`)) return;
    try {
      await deleteFarm(farm.id);
      router.replace("/dashboard");
    } catch (err) {
      setError(err.message);
    }
  }

  if (!session || !farm || !farmForm) {
    return <p className="muted">{error ? <span className="error">{error}</span> : "Loading farm…"}</p>;
  }

  return (
    <>
      <p>
        <Link href="/dashboard">← Back to farms</Link>
      </p>
      {error && <div className="error">{error}</div>}
      {notice && <div className="notice">{notice}</div>}

      <div className="card">
        <h2>{farm.name} <span className="badge">{farm.code}</span></h2>
        {canUpdate ? (
          <form onSubmit={onSubmitFarm}>
            <div className="row">
              <div>
                <label>Name</label>
                <input value={farmForm.name} onChange={(e) => setFarmForm({ ...farmForm, name: e.target.value })} required minLength={2} />
              </div>
              <div>
                <label>Code</label>
                <input value={farmForm.code} onChange={(e) => setFarmForm({ ...farmForm, code: e.target.value })} required />
              </div>
              <div>
                <label>Status</label>
                <select value={farmForm.status} onChange={(e) => setFarmForm({ ...farmForm, status: e.target.value })}>
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </div>
            </div>
            <div className="row">
              <div>
                <label>Country</label>
                <input value={farmForm.country} onChange={(e) => setFarmForm({ ...farmForm, country: e.target.value })} />
              </div>
              <div>
                <label>Region</label>
                <input value={farmForm.region} onChange={(e) => setFarmForm({ ...farmForm, region: e.target.value })} />
              </div>
              <div>
                <label>Locality</label>
                <input value={farmForm.locality} onChange={(e) => setFarmForm({ ...farmForm, locality: e.target.value })} />
              </div>
              <div>
                <label>Area (ha)</label>
                <input value={farmForm.area_ha} onChange={(e) => setFarmForm({ ...farmForm, area_ha: e.target.value })} inputMode="decimal" />
              </div>
            </div>
            <label>Description</label>
            <textarea rows={2} value={farmForm.description} onChange={(e) => setFarmForm({ ...farmForm, description: e.target.value })} />
            <button className="primary" disabled={busy}>Save farm</button>
          </form>
        ) : (
          <table>
            <tbody>
              <tr><th>Location</th><td>{[farm.locality, farm.region, farm.country].filter(Boolean).join(", ") || "—"}</td></tr>
              <tr><th>Area</th><td>{farm.area_ha ?? "—"} ha</td></tr>
              <tr><th>Water source</th><td>{farm.water_source}</td></tr>
              <tr><th>Coordinates</th><td>{farm.latitude ?? "—"}, {farm.longitude ?? "—"}</td></tr>
              <tr><th>Description</th><td>{farm.description || "—"}</td></tr>
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>Irrigation zones</h3>
        <p className="muted">
          Each zone is an independently controllable irrigation area. Valve and
          sprinkler control for zones arrives with Modules 8/9 (Phase 4).
        </p>
        {zones.length === 0 ? (
          <p className="muted">No zones yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Area (ha)</th>
                <th>Seq</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => (
                <tr key={z.id}>
                  <td>{z.code}</td>
                  <td>{z.name}</td>
                  <td>{z.area_ha ?? "—"}</td>
                  <td>{z.sequence_number}</td>
                  <td>
                    {canUpdateZone ? (
                      <select value={z.status} onChange={(e) => onZoneStatus(z, e.target.value)}>
                        <option value="active">active</option>
                        <option value="maintenance">maintenance</option>
                        <option value="disabled">disabled</option>
                      </select>
                    ) : (
                      <span className="badge">{z.status}</span>
                    )}
                  </td>
                  <td>
                    {canDeleteZone && (
                      <button className="linkish" onClick={() => onDeleteZone(z)}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {canCreateZone && (
          <form onSubmit={onCreateZone}>
            <div className="row">
              <div>
                <label>Zone name *</label>
                <input value={zoneForm.name} onChange={(e) => setZoneForm({ ...zoneForm, name: e.target.value })} required />
              </div>
              <div>
                <label>Zone code *</label>
                <input value={zoneForm.code} onChange={(e) => setZoneForm({ ...zoneForm, code: e.target.value })} required placeholder="e.g. ZN-1" />
              </div>
              <div>
                <label>Area (ha)</label>
                <input value={zoneForm.area_ha} onChange={(e) => setZoneForm({ ...zoneForm, area_ha: e.target.value })} inputMode="decimal" />
              </div>
              <div>
                <label>Sequence</label>
                <input value={zoneForm.sequence_number} onChange={(e) => setZoneForm({ ...zoneForm, sequence_number: e.target.value })} inputMode="numeric" />
              </div>
            </div>
            <button className="primary" disabled={busy}>Add zone</button>
          </form>
        )}
      </div>

      {canUpdate && (
        <div className="card">
          <h3 style={{ color: "var(--danger)" }}>Danger zone</h3>
          <p className="muted">Deleting a farm requires all its zones to be deleted first.</p>
          <button className="linkish" onClick={onDeleteFarm}>Delete this farm</button>
        </div>
      )}
    </>
  );
}
