"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, setToken, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { access_token } = await api.login(email, password);
      setToken(access_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That email and password don't match.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem 1.25rem",
        background:
          "radial-gradient(ellipse at 50% 0%, var(--stone-raised) 0%, var(--stone) 62%)",
      }}
    >
      <div style={{ marginBottom: "2.25rem", textAlign: "center" }}>
        <div className="wordmark" style={{ fontSize: "1.7rem", color: "var(--ink)" }}>
          Rosetta
        </div>
        <p style={{ color: "var(--ink-faint)", fontSize: "0.85rem", marginTop: "0.4rem" }}>
          Every video, decoded.
        </p>
      </div>

      <div className="panel" style={{ width: "100%", maxWidth: 380, padding: "2rem 1.75rem" }}>
        <h1 style={{ fontFamily: "var(--serif)", fontSize: "1.35rem", fontWeight: 500, marginBottom: "1.5rem" }}>
          Log in
        </h1>
        <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.9rem" }}>
          <input
            className="field"
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
          <input
            className="field"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && (
            <p style={{ color: "var(--danger)", fontSize: "0.87rem" }}>{error}</p>
          )}
          <button className="btn-primary" type="submit" disabled={loading} style={{ marginTop: "0.3rem" }}>
            {loading ? "Signing in…" : "Log in"}
          </button>
        </form>
        <p style={{ marginTop: "1rem", fontSize: "0.85rem" }}>
          <Link href="/forgot-password" style={{ color: "var(--gold)", textDecoration: "underline" }}>
            Forgot password?
          </Link>
        </p>
        <p style={{ marginTop: "0.6rem", fontSize: "0.87rem", color: "var(--ink-dim)" }}>
          New here?{" "}
          <Link href="/signup" style={{ color: "var(--gold)", textDecoration: "underline" }}>
            Create an account
          </Link>
        </p>
      </div>
    </main>
  );
}
