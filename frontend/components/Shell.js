"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useSession, signOut } from "../lib/session";

export default function Shell({ children }) {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    const onSignedOut = () => router.replace("/login");
    window.addEventListener("asiis:signed-out", onSignedOut);
    return () => window.removeEventListener("asiis:signed-out", onSignedOut);
  }, [router]);

  return (
    <>
      <header className="topbar">
        <span className="brand">ASIIS</span>
        <span className="muted" style={{ color: "#c5e1a5" }}>
          AgroSmart Irrigation Intelligence
        </span>
        <span className="spacer" />
        {session ? (
          <>
            <Link href="/dashboard">Farms</Link>
            <Link href="/devices">Devices</Link>
            <Link href="/sensor-data">Sensors</Link>
            <Link href="/faults">Faults</Link>
            <span style={{ fontSize: "0.85rem" }}>
              {session.user?.full_name}
              {session.user?.roles?.map((r) => (
                <span key={r.code} className="badge" style={{ marginLeft: 6 }}>
                  {r.code}
                </span>
              ))}
            </span>
            <button
              onClick={() => {
                signOut();
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </>
        ) : (
          <>
            <Link href="/login">Sign in</Link>
            <Link href="/register">Register</Link>
          </>
        )}
      </header>
      <main>{children}</main>
    </>
  );
}
