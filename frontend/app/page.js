"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSnapshot } from "../lib/session";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getSnapshot() ? "/dashboard" : "/login");
  }, [router]);
  return <p className="muted">Loading ASIIS…</p>;
}
