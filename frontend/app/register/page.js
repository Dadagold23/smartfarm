"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { register } from "../../lib/api";
import { setSession } from "../../lib/session";

export default function RegisterPage() {
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const session = await register(form);
      setSession(session);
      router.replace("/dashboard");
    } catch (err) {
      setError(err.message || "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap card">
      <h2>Create your ASIIS account</h2>
      <p className="muted">
        Self-registration provisions a Farm Manager account: you can create and
        manage your own farms and irrigation zones.
      </p>
      <form onSubmit={onSubmit}>
        <label htmlFor="full_name">Full name</label>
        <input id="full_name" value={form.full_name} onChange={set("full_name")} required minLength={2} />
        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={form.email} onChange={set("email")} required />
        <label htmlFor="password">Password (min 8 characters)</label>
        <input id="password" type="password" value={form.password} onChange={set("password")} required minLength={8} />
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "Creating account…" : "Register"}
        </button>
      </form>
      <p className="muted">
        Already registered? <Link href="/login">Sign in</Link>
      </p>
    </div>
  );
}
