// API base URL for the ASIIS backend. Point at a deployed API by setting
// NEXT_PUBLIC_API_BASE_URL at build time.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

const STORAGE_KEY = "asiis.a…i.v1";

export function loadSession() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

function authHeaders() {
  const session = loadSession();
  return session?.tokens?.access_token
    ? { Authorization: `Bearer ${session.tokens.access_token}` }
    : {};
}

async function toApiError(response) {
  let message = `Request failed (${response.status})`;
  let code = `http_${response.status}`;
  try {
    const body = await response.json();
    if (body?.error) {
      message = body.error.message;
      code = body.error.code;
    } else if (typeof body?.detail === "string") {
      message = body.detail;
    }
  } catch {
    /* non-JSON error body */
  }
  const err = new Error(message);
  err.status = response.status;
  err.code = code;
  return err;
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) Object.assign(headers, authHeaders());
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (response.status === 401 && auth) {
    clearSession();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("asiis:signed-out"));
    }
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return null;
  return response.json();
}

// --- Module 1: auth ---
export const register = (payload) =>
  request("/api/v1/auth/register", { method: "POST", body: payload, auth: false });
export const login = (payload) =>
  request("/api/v1/auth/login", { method: "POST", body: payload, auth: false });
export const refreshSession = (refreshToken) =>
  request("/api/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
    auth: false,
  });
export const fetchMe = () => request("/api/v1/auth/me");

// --- Module 2: farms ---
export const listFarms = () => request("/api/v1/farms?limit=200");
export const getFarm = (id) => request(`/api/v1/farms/${id}`);
export const createFarm = (payload) =>
  request("/api/v1/farms", { method: "POST", body: payload });
export const updateFarm = (id, payload) =>
  request(`/api/v1/farms/${id}`, { method: "PATCH", body: payload });
export const deleteFarm = (id) =>
  request(`/api/v1/farms/${id}`, { method: "DELETE" });

// --- Module 2: irrigation zones ---
export const listZones = (farmId) => request(`/api/v1/farms/${farmId}/zones`);
export const createZone = (farmId, payload) =>
  request(`/api/v1/farms/${farmId}/zones`, { method: "POST", body: payload });
export const updateZone = (zoneId, payload) =>
  request(`/api/v1/zones/${zoneId}`, { method: "PATCH", body: payload });
export const deleteZone = (zoneId) =>
  request(`/api/v1/zones/${zoneId}`, { method: "DELETE" });

// --- Phase 2: IoT devices (device.manage) ---
export const listDevices = (farmId) =>
  request(`/api/v1/devices?limit=200${farmId ? `&farm_id=${farmId}` : ""}`);
export const registerDevice = (payload) =>
  request("/api/v1/devices", { method: "POST", body: payload });
export const updateDevice = (id, payload) =>
  request(`/api/v1/devices/${id}`, { method: "PATCH", body: payload });
export const deviceStatus = (id) => request(`/api/v1/devices/${id}/status`);
export const rotateDeviceKey = (id) =>
  request(`/api/v1/devices/${id}/rotate-key`, { method: "POST" });
export const revokeDevice = (id) =>
  request(`/api/v1/devices/${id}/revoke`, { method: "POST" });

// --- Phase 2: sensor faults (faults.read) ---
export const listFaults = ({ farmId, openOnly = true } = {}) => {
  const qs = new URLSearchParams({ open_only: String(openOnly) });
  if (farmId) qs.set("farm_id", farmId);
  return request(`/api/v1/faults?${qs.toString()}`);
};

// --- Phase 2: soil telemetry (soil.read) ---
export const soilLatest = (farmId) =>
  request(`/api/v1/soil/latest${farmId ? `?farm_id=${farmId}` : ""}`);

// --- Phase 2: weather telemetry + forecasts (weather.read) ---
export const weatherLatest = (farmId) =>
  request(`/api/v1/weather/latest${farmId ? `?farm_id=${farmId}` : ""}`);
export const listForecastProviders = () => request("/api/v1/weather/forecast-providers");
export const refreshForecast = (payload) =>
  request("/api/v1/weather/forecast-refresh", { method: "POST", body: payload });
