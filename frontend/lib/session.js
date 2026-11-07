"use client";

import { useSyncExternalStore } from "react";
import { loadSession, saveSession, clearSession, fetchMe } from "./api";
import { satisfiesPermission } from "./permissions.js";

// Client-side session store backed by localStorage. The JWT in the store is
// only a carrier: every mutation is re-authorised server-side by the API.

const listeners = new Set();

function emit() {
  for (const l of listeners) l();
}

export function subscribe(listener) {
  listeners.add(listener);
  window.addEventListener("asiis:signed-out", onSignedOut);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("asiis:signed-out", onSignedOut);
  };
}

function onSignedOut() {
  clearSession();
  emit();
}

let cached = null;
let cachedLoaded = false;

export function getSnapshot() {
  if (!cachedLoaded) {
    cached = loadSession();
    cachedLoaded = true;
  }
  return cached;
}

function getServerSnapshot() {
  return null;
}

export function setSession(session) {
  saveSession(session);
  cached = session;
  cachedLoaded = true;
  emit();
}

export function signOut() {
  onSignedOut();
}

// Re-fetch the user (permissions may have changed server-side since login).
export async function refreshUser() {
  const me = await fetchMe();
  const current = getSnapshot();
  if (current) {
    setSession({ ...current, user: me });
  }
  return me;
}

export function useSession() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function hasPermission(session, code) {
  return satisfiesPermission(session?.user?.permissions || [], code);
}
