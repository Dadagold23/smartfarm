"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { login } from "../../lib/api";
import { setSession } from "../../lib/session";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const session = await login({ email, password });
      setSession(session);
      router.replace("/dashboard");
    } catch (err) {
      setError(err.message || "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap card">
      <h2>Sign in to ASIIS</h2>
      <form onSubmit={onSubmit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
        />
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="muted">
        No account? <Link href="/register">Register a farm account</Link>
      </p>
    </div>
  );
}
